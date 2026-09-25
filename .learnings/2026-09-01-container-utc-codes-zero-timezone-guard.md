# QTS 全容器 UTC + 代码零时区保护：落库时间戳早 8 小时，凌晨日期会记成前一天

> 日期：2026-09-01 | 发现：统一巡检中枢 run#56 | 等级：P1（待用户拍板，未修复）
> 状态：**已验证修复方案可行，未实施**（需重建容器）

## 现象（实测证据）

```bash
$ docker exec quant-strategy date
Tue Sep  1 09:45:46 UTC 2026          # 真实北京时间 = 17:45

$ docker exec quant-strategy python -c "..."
TZ env       = None
time.tzname  = ('UTC', 'UTC')
datetime.now = 2026-09-01 09:46:32    # ← 比北京时间早 8 小时
datetime.utc = 2026-09-01 09:46:32    # ← 与 now() 完全同值
```

**关键**：`datetime.now()` 与 `datetime.utcnow()` 返回**同一个值**，
说明容器内 Python 完全工作在 UTC 下，`now()` 并不是本地时间。

## 影响面

- 全仓 `datetime.now()` 使用点 **167 处**（`strategy-service/`，含 tests/.venv）
- 全仓 **无一处**显式设置 `Asia/Shanghai`（grep 结果仅命中 `.venv/` 第三方库）
- 所有落库时间戳（`created_at` / `updated_at`）比北京时间早 8 小时
- **每日北京时间 00:00–08:00 之间生成的日期字段，会被写成前一天**
  （UTC 比 CST 晚 8h，此时 UTC 日期尚未翻页）

### 佐证

run#56 复查 `backtest_reports` 时看到的新增行：

```
id=6 | report_date=2026-09-01 | created_at=2026-09-01 07:35:05
```

07:35:05 是 UTC，对应**北京时间 15:35:05** —— 正好是回测日报 cron 窗口。
作业触发时间是对的（APScheduler 在代码里指定了时区参数），
但**落库写的是 UTC**。若日报改到凌晨跑，`report_date` 就会错一天。

## 为什么健康检查抓不到（沉默型缺陷）

- 不抛异常、不报错、退出码 0
- `/health` 探活全绿
- 日志时间戳自洽（全都是 UTC，看不出问题）
- **只在每日 00:00–08:00 这个窗口暴露**，且暴露方式是「日期看起来差一天」，
  容易被当成「数据延迟」而非时区 bug

## 修复方案（已验证可行，未实施）

容器内**已自带** zoneinfo，无需改镜像、无需装 tzdata：

```bash
$ docker exec quant-strategy ls /usr/share/zoneinfo/Asia/Shanghai
-rw-r--r-- 1 root root 561 Apr 28 18:45 /usr/share/zoneinfo/Asia/Shanghai

$ docker exec quant-strategy sh -c "TZ=Asia/Shanghai date"
Tue Sep  1 17:46:10 CST 2026        # ← 正确
```

### 做法

在 `docker-compose.yml` 各服务的 `environment` 下加：

```yaml
environment:
  - TZ=Asia/Shanghai
```

**建议只加应用服务**：`strategy-service` / `execution` / `ai-scheduler` /
`dashboard` / `alertmanager-feishu`。
**不动数据容器**：`postgres` / `questdb` / `redis` / `rabbitmq`
（重建风险高于收益，且它们的内部时间多为 UTC 存储，改了反而可能引入新的不一致）。

### 对照参考：pmf 就是这么配的

```
project-monitor-fusion-scheduler-1:
  env TZ=Asia/Shanghai
  /etc/localtime -> Asia/Shanghai
  date -> CST 17:45  ✅
```

同机对照一眼看出：不是「镜像做不到」，是「QTS 忘了做」。

## 风险（需用户拍板的原因）

改 TZ 会让容器重建，且会**改变这 167 处 `now()` 的语义**（从 UTC 跳到 CST，+8h）：

- 已落库的历史时间戳仍是 UTC，新旧混存 —— 需要决定是迁移还是接受并存
- 若存在「拿落库时间与 `datetime.now()` 比较」的逻辑，改造窗口内可能短暂不一致
- 数据容器不改 TZ → 应用层 CST、存储层 UTC 的差异需在写入时明确处理

## 建议的落地顺序

1. 先盘点 167 处里**真正落库/参与日期计算**的部分（tests 和 .venv 可排除）
2. 明确「落库统一存 UTC」还是「统一存 CST」（推荐：**存 UTC，展示层转 CST**，
   这样只需保证代码不直接用 `now()` 生成业务日期，改动最小）
3. 加 `TZ=Asia/Shanghai` 让日志与 shell 时间可读（低风险，可先做）
4. 重建应用容器并灰度观察 1 个交易日

## 教训

- **沉默型缺陷只能靠主动语义校验发现**：异常驱动的监控对它完全失效
- 判断时区是否正确，**不要看时间戳"像不像"，要拿它与已知事件对齐**
  （本次是靠「cron 15:35 触发 → 落库 07:35」这个已知锚点反推出来的）
- 排查容器时区前先查**容器内有没有 zoneinfo**，能直接区分「重装镜像」和「加个变量」
