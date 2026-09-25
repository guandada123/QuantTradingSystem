# 修了「一处」不等于修了「一类」：验收口径倒挂让同款 bug 存活 4 天

- **日期**: 2026-09-02
- **等级**: P1
- **发现途径**: 统一巡检中枢 run#62 人工深挖（17 项 16✅/1⚠️，脚本 SILENT）
- **状态**: 已修复并部署（QTS commit `2db1231f`，未 push）
- **✅已升级(2026-09-06)**: 7 条

---

## 现象

`strategy-service` 有两个「服务健康探测」实现，探测的是同一对服务：

| 位置 | 用途 | execution 探测地址 | 状态 |
|---|---|---|---|
| `services/scheduler/jobs.py:health_check()` | 定时健康检查作业 | 读 `EXECUTION_SERVICE_URL` | ✅ run#58 已修 |
| `api/scheduler.py:health_monitor_status()` | 前端告警页轮询端点 | **硬编码 `http://localhost:8001`** | ❌ 本次发现 |

后者在 strategy 容器内探测 `localhost:8001` —— 而 execution 是**另一个容器**，
容器内 8001 无监听者，探测必然失败：

```
容器内实测对照：
  http://localhost:8001/health         -> ConnectError
  http://execution-service:8001/health -> 200
```

后果：前端 `alerts.html` 的 HealthMonitor 轮询拿到的 `execution-service` **恒为
false**，页面永远显示 `degraded`。**告警页长期处于"有故障"状态 = 无人再信它。**

## 根因：验证口径倒挂（本条最值得记住）

run#58 修 `jobs.py` 时，验收记录写的是：

> 修：读 `EXECUTION_SERVICE_URL`，fallback `http://execution-service:8001/health`。
> 实测 `up_count=2/2, execution: UP`。

`up_count=2/2` 验证的是**它改的那一个调用点通过了**，不是**全系统再无同类写法**。
两个口径的差别，就是这个 bug 多活 4 天的原因。

更讽刺的是，run#58 自己沉淀的复用写法⑥白纸黑字写着：

> ⑥ **修「某一类错误」先 grep 全仓同类写法**（run#57 只修 tushare，akshare 同款
> 第二天以「每天 16 分钟空转」的形态复现）

**教训写下来了，下一次仍然只修了眼前那一处。** 说明「知道」与「执行」之间缺一个
强制检查点 —— 光写进 .learnings 不够，要写进**修复动作本身的验收步骤**。

## 次生缺陷：吞异常让两种失败不可区分

```python
try:
    resp = await client.get(url)
    results[name] = resp.status_code == 200
except Exception:
    results[name] = False          # ← 原因被丢弃
```

「服务真的挂了」与「地址写错了」在返回体里长得一模一样（都是 `false`）。
这让问题在**排查阶段**也难以定位 —— 前端只显示 false，日志里连一行 warning 都没有。

这是 run#57（provider 吞异常）/ run#58（akshare 吞网络异常）第三次复现。

## 结构性成因：服务地址没有单一真源

同一个 execution 地址散落四处，写法各不相同：

```
strategy-service/core/config.py:59          EXECUTION_SERVICE_URL = "http://execution-service:8001"   ← 正确默认值
strategy-service/services/execution_client.py:16   getattr(settings, ...)                              ← 走配置
strategy-service/services/scheduler/jobs.py:513    os.getenv(...)                                      ← 走环境变量
strategy-service/api/scheduler.py:102              "http://localhost:8001"                             ← 硬编码（本次修）
```

**N 个消费方各自决定怎么取地址 ⇒ 必然有某一个忘记取。** 根子上应该只有一个函数
提供地址，其余全部调用它。

## 修复

1. `api/scheduler.py`：改读 `EXECUTION_SERVICE_URL`，fallback `http://execution-service:8001`，
   与 `jobs.py` / `config.py` 同源；`strategy` 探测自己仍用 `localhost:8000`（写法正确，不动）
2. 不再吞异常：返回体新增 `details` 字段记录失败原因（HTTP 状态码 / 异常类型），
   并在非全健康时打 warning 日志
3. 新增 `TestHealthMonitorStatus` 5 用例（**该端点此前零测试覆盖**）

## 验证（三层）

| 层 | 方法 | 结果 |
|---|---|---|
| 单测 | 5 用例 | 全过 |
| **反向验证** | 把代码还原成 `localhost:8001` 重跑 | **2 用例失败** → 证明断言有效，非恒真 |
| 生产 | 容器内调用 + API 网关（带鉴权） | `status: healthy`、两服务均 true、`details` 有状态码 |

生产日志可见 `connect_tcp.started host='execution-service' port=8001`，确认走的是服务名。

回归：strategy-service **1268 passed / 3 skipped**（较 run#61 的 1263 恰 +5）、
shared **311 passed**；ruff + ruff-format + bandit + pre-commit 全绿。
重启后 401 锚点未移动、新增 401/403 = 0、28 个调度作业重新注册。

## ✅已升级(2026-09-06)

1. **修「某一类错误」的验收口径必须是「全仓再无同类写法」，不是「改的那处对了」。**
   `up_count=2/2` 这种只验证改动点的验收，等于宣布"我不知道还有没有别的"。
   修复完成的定义应包含一次全仓 grep 的**结果**（发现了几处、分别在哪）。
2. **写进 .learnings 的教训不会自动执行。** run#58 写下了"先 grep 全仓同类写法"，
   4 天后仍然只修了一处 —— 教训必须固化为**动作清单里的一个勾选步骤**，
   而不是结论里的一句话。
3. **「同一个值在 N 处各写一遍」是缺陷的温床。** 服务地址、限流阈值、时区、
   超时时长都属此类。判定标准很简单：改一个值需要改几个文件？>1 就该抽函数。
4. **吞异常第三次复现：让「配置错误」与「运行故障」长得一样。**
   健康探测 / 熔断 / 降级这类**诊断型代码**，异常原因必须保留到输出里 ——
   它们存在的意义就是回答"为什么不好"，回答不了就失去了存在价值。
5. **长期显示"有故障"的监控比没有监控更糟。** 前端告警页恒 degraded 4 天无人处理，
   说明团队已默认它不可信。监控一旦被判定为"狼来了"，恢复可信度的成本远高于修复成本。
6. **反向验证（把 bug 改回去看测试挂不挂）是唯一能证明"测试有效"的方法。**
   测试通过只能证明"当前代码下不挂"，不能证明"能抓住 bug"。
7. **聚合计数会诱导误判存量 vs 新增 —— 必须落到精确时间线。**
   本轮 24h 聚合看到「18 次 execution DOWN」「272 次 Tushare 限频」，两个数字都很吓人；
   拉出精确时间线后，最后一条分别是 `09-01T11:59Z` 和 `09-01T14:07Z`，
   **均在对应修复部署之后，12h+ 无新增**。若按聚合数字定性，会把两个已止血的问题
   当成回归，白白消耗整轮调查。（此条为 run#54 已有教训，本轮系正确执行并再次验证其价值。）
