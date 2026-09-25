# 新鲜度检查量的是「容器运行时长」：写接口零调用，评分退化为 uptime 的纯函数

- **日期**: 2026-09-02
- **等级**: P1
- **发现途径**: 统一巡检中枢 run#61 人工深挖（17 项 16✅/1⚠️，脚本 SILENT）
- **状态**: 已修复并部署（QTS commit `2fe5a58f`，未 push）
- **✅已升级(2026-09-06)**: 8 条

---

## 现象

`quant-strategy` 每 5 分钟打一行数据质量日志。把 48h 内 583 条记录按时序展开后，
评分只有三个取值，且**跃迁点全部对齐容器重启时刻**：

```
08-31 21:11 CST  score=100   ← 容器重启
08-31 22:19 CST  score=55    ← 重启后 68 分钟
08-31 22:25 CST  score=100   ← 又重启
08-31 23:32 CST  score=55    ← 67 分钟
09-01 18:59 CST  score=100   ← 又重启
09-01 20:03 CST  score=55    ← 64 分钟
09-01 21:37 CST  score=55    ← 82 分钟
09-01 22:32 CST  score=100   ← 又重启
09-01 23:58 CST  score=100   ← 又重启
09-02 00:58 CST  score=55    ← 60 分钟
```

**6 次 `100→55` 跃迁，间隔 60~82 分钟，无一例外。** 评分与数据毫无关系，
它是「容器 uptime」的阶梯函数：`<1h → 100`、`1h~24h → 55`、`>24h → 25`
（08-31 08:02 那次 `score=25` 正是 uptime 跨过 24h）。

## 根因

```python
# services/data_quality.py
def __init__(self):
    self.last_update: dict[str, datetime] = {}
    for rule in self.rules:
        self.last_update[rule.source] = self._now()   # ① 播种成启动时刻

def mark_update(self, source):                        # ② 唯一会更新 last_update 的入口
    self.last_update[source] = self._now()

async def check_freshness(self, rule):
    last = self.last_update.get(rule.source)          # ③ 读的永远是 ① 播种的那个值
    delay = (self._now() - last).total_seconds()      #    = 容器运行时长
```

全仓 grep `mark_update`：**生产侧零调用，只有测试在调**（`tests/test_data_quality.py`
里 3 处）。于是 `last_update` 从 `__init__` 之后再没被写过，`delay` 恒等于 uptime。

## 后果（比"数字难看"严重得多）

| 真实情况 | 修复前监控的说法 | 错在哪 |
|---|---|---|
| `stock_pool` 最后更新 **2026-08-12**，已 **20 天**未更新 | 通过（uptime<24h 就算新鲜） | **漏报**，且是关键漏报 |
| `minute_quote_metadata` **0 行**，实时行情从未采集 | 通过（同样靠 uptime） | **漏报** |
| 北向资金在 QTS **根本没有存储表** | 通过 | **漏报** |
| 日行情刷新 89.4% 失败（run#60 已定位） | 无感知 | 只会随容器重启"自愈" |

也就是说：**监控的全部信息量 = 容器重启了多久**。任何一个真实的数据中断，
只要容器一重启就会"恢复健康"—— 这正是 run#56/57/60 反复出现的
「部分成功掩盖完全失败」在监控层的形态。

## 修复

1. `DataQualityRule` 增加 `db_table` / `db_ts_col` / `market_hours_only`；
   五条规则全部接上数据库真值来源（`daily_quote.updated_at`、
   `index_snapshots.recorded_at`、`stock_pool.updated_at`、
   `minute_quote_metadata.updated_at`）。
2. 新增 `_probe_latest()` 查库取真实最后更新时间，返回状态显式区分
   `ok / empty / error / unmapped` —— **不用 `None` 表达**，否则
   「没有配置库表」与「表存在但 0 行」会混淆，而两者语义完全相反。
3. `error`（查库失败）与 `empty`（从未采集）一律 **fail-safe 判不通过**，
   不再悄悄退回 in-memory 口径 —— 退回就等于退回 uptime。
4. `_today()` 与 `is_trading_hours()` 改用 `shared.trading_calendar`（北京时间口径）。
5. 盘中数据源（`realtime_quote` / `index_quote` / `northbound_flow`）在
   非交易时段跳过检查，避免"收盘后必然陈旧"的噪音。

### 顺带修掉的第二个缺陷：交易时段判断整体偏移 8 小时

```python
CHINA_MARKET_HOURS = (9, 15)
def is_trading_hours(self):
    return self.CHINA_MARKET_HOURS[0] <= self._now().hour < self.CHINA_MARKET_HOURS[1]
```

容器 `TZ=UTC`，`_now().hour` 是 **UTC 小时** → 「交易时段」被判成
**北京时间 17:00–23:00**，与真实盘中完全错位。这正是 run#56/run#60 记录的
「容器 TZ=UTC + 代码零时区保护」待办的又一实例 —— 此前只看到它污染
`created_at`/`updated_at`，本次发现它连**交易时段判定**都污染了。

## 验证（生产容器内实测，非单测模拟）

| 场景 | 结果 |
|---|---|
| 修复前 16:53Z | `评分: 100/100 \| 通过: 7/7`（此时 stock_pool 已 20 天未更新） |
| 修复后 17:17Z / 17:22Z | `评分: 85/100 \| 通过: 6/7 \| 不通过: freshness:stock_pool` |
| 库真值探测 | `stock_pool -> ok 2026-08-12 14:12`，delay=1,739,191s（20.1 天）|
| 模拟盘中（北京 10:30） | `is_trading_hours=True`，指数快照更新后即恢复通过 |
| 单测 | 本文件 51 passed；全量 **1263 passed / 3 skipped** |
| lint | ruff check + format + pre-commit 全绿 |
| 自伤规避 | 401 锚点未移动，重启后新增 401/403 = **0** |

## ✅已升级(2026-09-06)（供周度 auto-promote 升铁律）

1. **「指标在测什么」必须能追溯到真实数据源**。凡是靠内存计数器/字典维护的
   健康指标，先 grep 它的**写入方**在生产侧有几个调用；零调用 = 指标是死的。
   本次 `mark_update()` 生产零调用，指标却每天产出 288 条"健康"日志。
2. **能自证健康的监控最危险**：值与被监控对象无关时，它仍会稳定输出格式正确、
   从不报错的日志。判断方法 —— **重启被监控对象，指标若随之"好转"，说明它测的是进程状态**。
   本次 6 次跃迁全部对齐重启时刻，这就是铁证。
3. **指标取值若只出现少数几个离散值，先怀疑它是某个变量的阶梯函数**。
   评分只有 100/55/25 三态，而"数据质量"本该是连续量 —— 离散化本身就是线索。
4. **不要用 `None` 表达多种失败**：「未配置」「查不到」「空集」是三种语义，
   共用一个 `None` 必然在某个分支上做出错误默认。用显式状态枚举。
5. **fallback 到内存状态要极其谨慎**：「查库失败 → 退回内存值」看起来是健壮性，
   实际是**在最需要数据的时刻悄悄换了个更差的数据源**。无法判定时应 fail-safe。
6. **修「监控不准」要连它的时间基准一起修**：本次若只把 last_update 换成库真值，
   `is_trading_hours()` 仍然偏 8 小时 —— 盘中数据源会在真正的盘中被判为"非交易时段"而跳过。
   凡涉及时段判断，先确认时区口径。
7. **测试会忠实固化错误的时区假设**。旧断言 `10:30 → True` 把 `_now()` 当北京墙钟，
   而生产里 `_now()` 返回 UTC —— 测试全绿，bug 全在。改时区语义时必须同步审查测试。
8. **交易时段的边界要按代码读，不要按常识猜**。`trading_calendar.SESSIONS` 午盘到
   **15:35**（刻意留收盘后收尾窗口），我按"15:00 收盘"写的断言反而错了。
   这类"设计上刻意放宽"的边界，读源码比凭印象可靠。
