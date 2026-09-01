# 降级链熔断做成实例级：跨定时任务完全失效，每天白等 16 分钟

> 日期：2026-09-01 | 发现：统一巡检中枢 run#58 | 等级：P1（已修复并部署）
> 关联：同日 run#57《provider 吞异常致 4494 次无效调用》—— 本条是那次修复的**续集**

## 现象（实测证据）

run#57 给降级链加了「限频熔断」，单任务内验证有效（4494 → 48 次）。
run#58 回读生产日志时发现它**跨任务根本没生效**：

```
$ docker logs --since 24h quant-strategy | grep -c "创建 akshare 提供者"
48                          # 大盘快照每 30 分钟一次 × 24h
$ docker logs --since 24h quant-strategy | grep "source=akshare" | wc -l
0                           # ← 成功次数 = 0，24h 内 48 次调用 100% 失败
```

大盘快照单点耗时拆解（11:59:33 那一轮）：

| 阶段 | 起止 | 耗时 | 结果 |
|---|---|---|---|
| tushare (`index_daily`) | 33.431 → 33.431 | 0.09s | ❌ 频率超限(5次/天) |
| akshare (重试 3 次) | 33.439 → 53.723 | **20.4s** | ❌ RemoteDisconnected |
| tencent (兜底) | 53.723 → 53.794 | 0.07s | ✅ count=8 |

**每次大盘快照 20.7s，其中 20.4s（98.6%）耗在一个 100% 失败的源上**，
真正拿到数据的腾讯源只要 0.07s。48 次/天 ≈ **16.4 分钟/天空转**。

## 根因：三个独立的错误叠在一起

### ① 冷却表是实例级，而每个任务都 new 一个 DataService

```python
def __init__(self, ...):
    self._source_cooldown: dict[str, float] = {}   # ← 实例属性
```
```python
async def market_snapshot():
    ds = DataService(...)        # ← 每次任务新建，冷却表随实例一起销毁
```
任务间隔 30 分钟，实例生命周期只有 20 秒。**冷却状态从未跨过任务边界**。

### ② 冷却粒度是数据源级，而 Tushare 的限频是按接口的

- `index_daily` 限 **5 次/天**，耗尽后降级为 1 次/小时
- `daily` 限 **50 次/分钟**

run#57 的修复让 `index_daily` 配额耗尽后熔断**整个 tushare 源** 300s，
`daily`（额度充足）无辜受罚。实测日志可证：

```
11:29:33 降级链熔断 source=tushare cooldown_seconds=300   ← 起因是 index_daily
11:59:33 降级链熔断 source=tushare cooldown_seconds=300   ← 又熔断，起因还是 index_daily
```

### ③ 固定 300s 冷却对 30 分钟周期的任务等于不冷却

即使修好 ①，冷却 300s < 任务间隔 1800s ⇒ **每一轮冷却都已过期 ⇒ 每轮都重试一次**。
省不下任何时间。

## 修复（v2，`strategy-service/services/data_service.py`）

| 维度 | v1 | v2 |
|---|---|---|
| 作用域 | 实例级 `self._source_cooldown` | 模块级 `_METHOD_COOLDOWN`（进程内跨实例共享） |
| 粒度 | `source` | `f"{source}:{method_name}"` |
| 触发 | 仅限频 | 限频**命中即熔断**；网络类需连续 2 次 |
| 时长 | 固定 300s | 指数退避 300s→600s→1200s…，上限 6h |
| 恢复 | 无 | 成功即清空连续失败计数 |

**网络类错误需连续 2 次的理由**：避免单次抖动把批量任务（4494 只标的）的
主数据源误熔断。业务性错误（代码无效/停牌无数据）**不触发**冷却 ——
这类错误换个标的就会成功，且会打断连续失败计数。

## 验证

新建 `strategy-service/tests/test_fallback_cooldown.py`（7 个用例，全绿）：

| 用例 | 断言 |
|---|---|
| `test_cooldown_shared_across_instances` | 新实例不再调用已熔断的源（缺陷①） |
| `test_cooldown_is_per_method_not_per_source` | `daily_kline` 不被 `index_realtime` 连坐（缺陷②） |
| `test_rate_limit_trips_immediately` | 限频后 50 轮只实际调用 1 次（保留 v1 行为） |
| `test_business_error_does_not_trip_cooldown` | 10 次业务错误不熔断 |
| `test_single_network_blip_does_not_trip_cooldown` | 单次抖动不误伤 |
| `test_repeated_failures_back_off_exponentially` | 冷却时长 `[0, 300, 600, 1200, 2400]` 单调增长且 ≤6h |
| `test_success_clears_failure_counter` | 恢复后正常取数且计数清零 |

回归：strategy-service 全量 **1253 passed / 3 skipped**，ruff + pre-commit 全绿。

## ★ 升级候选（复用写法）

1. **加了熔断不等于熔断生效 —— 必须确认作用域能跨到"故障重复的粒度"上。**
   故障每 30 分钟重复一次，而熔断状态只活 20 秒，等于没加。
   **判据：熔断的生命周期必须 ≥ 故障的发生周期。**
2. **熔断粒度必须与限流粒度对齐。** 服务端按接口限流，客户端按数据源熔断，
   就会一个接口配额耗尽连坐整源。看到"限 5 次/天"这种**按接口**的文案，
   冷却键里就必须带上接口/方法名。
3. **固定时长冷却对周期性任务无效**：冷却时长 < 任务间隔 ⇒ 每轮都重试一次，
   省下的时间为 0。要么指数退避，要么冷却时长 > 任务间隔。
4. **耗时占比是最直观的浪费探测器**：20.7s 的任务里某源占 20.4s 且成功率为 0，
   不需要复杂分析就能定位。看到"某阶段耗时占比 >90% 且最终成功来自其他源"就查它。
5. **区分「系统性错误」与「业务性错误」是熔断设计的前提**：
   前者（限频/网络/鉴权）重试无意义该冷却；后者（代码无效/停牌）换标的就好，
   冷却反而会误伤批量任务。
6. **"修复已验证"的结论只在验证的口径内成立**。run#57 验证了「单任务内调用次数
   4494→48」，但没验证「跨任务的空转是否消失」—— 后者才是生产实际形态。

## 备注：akshare 失败并非代码缺陷

实测宿主机 `curl https://push2.eastmoney.com/...` 同样返回 `000`（0.149s 立即失败），
容器内 DNS 把 `push2.eastmoney.com` 解析到 `198.18.0.8`（benchmark 保留网段，
典型本地代理/fake-ip 特征）。即**本机网络环境下东财 push2 不可达**，
属环境事实而非代码 bug。故修复方向不是"修好 akshare"，而是**让它别再被反复尝试**。
