# Learnings INDEX — QuantTradingSystem

> ⚠️ **本文件由 `learnings_index.py` 自动生成，请勿手改**（改了会在下次生成时被覆盖）。
> 权威内容是 `.learnings/*.md` 正文；本文件只是**派生视图**。
> ⚠️ 手工维护的 `LEARNINGS.md` 里的**浓缩条目不在本表内**（它已停更，见其抬头说明）。
> 生成时间：2026-10-11 22:14　｜　条目数：**22**

- **按类型**：silent-failure×2　false-positive×1　false-negative / environment-boundary×1　（另有 18 条未标注该字段）
- **按等级**：P1×2　P0×1　P2×1　🔴 数据完整性×1　（另有 17 条未标注该字段）

| 日期 | 标题 | 等级 | 类型 | 状态 | 文件 |
|---|---|---|---|---|---|
| 2026-10-11 | ★升级候选：接线类静默失效三连 —— 对象式 import / 字段名不存在 / 无认证端口 | P1（功能从未执行、数据恒为 0、暴露面静默存在） | silent-failure（接线错误三种典型形态） | 均已修复 | `2026-10-11-wiring-silent-failure-trio.md` |
| 2026-10-11 | ★升级候选：重建镜像 = 依赖漂移 → 静默降级 → **服务对着错误的库读写**（四层掩蔽） | P0（服务实际读写 SQLite 而非生产 PG；健康检查/接口全部"正常"） | silent-failure（依赖漂移 + 裸 except 降级 + 下游类型错） | 已修复（显式驱动 + 降级留证 + URL 归一化），并新增回归测试 | `2026-10-11-rebuild-image-drifts-to-wrong-database.md` |
| 2026-10-11 | ★升级候选：做「负向验证」会在 CI 健康检查里**永久留一条假红** —— 删分支不够 | P2（不误伤数据；但会让巡检长期挂一条**无人能处置**的红灯） | false-positive（验证产物的生命周期没被当成问题看） | 验证分支已删；健康检查侧已加豁免（Claw `qts_pmf_health_guard.scan_ci`） | `2026-10-11-negative-verification-leaves-permanent-red.md` |
| 2026-10-11 | ★升级候选：备份校验把**宿主路径**塞进容器 → 校验恒失败（假失败掩盖真失败） | P1（备份系统可信度；且「恒红」会让真失败淹没在噪音里） | false-negative / environment-boundary | 已修复（改为 `docker cp` 进容器再校验；新建每日备份自动化） | `2026-10-11-backup-verify-false-negative-host-path.md` |
| 2026-09-04 | WF（Walk-Forward）判据四处漂移，同一份数据得出相反结论 | — | — | — | `2026-09-04-wf-criteria-drifted-four-ways.md` |
| 2026-09-04 | Top5 连续 5 天全是单笔噪声：根因是回测窗口太短 + 挑选只在前 10 名里做 | — | — | — | `2026-09-04-top5-single-trade-noise-short-window.md` |
| 2026-09-04 | 灌库任务截断后「MAX(trade_date) 仍然说数据是最新的」：三处新鲜度检查全部被骗过 | — | — | — | `2026-09-04-max-trade-date-hides-truncated-ingest.md` |
| 2026-09-04 | 间接统计探针的系统性误报：不要用 vol/MA(均值) 判"快照污染" | — | — | — | `2026-09-04-indirect-statistical-probe-false-positives.md` |
| 2026-09-04 | 定级数据问题前先查下游消费方：不然会修错地方、加错调度 | — | — | — | `2026-09-04-check-blast-radius-before-escalating-fix.md` |
| 2026-09-03 | 盘中快照被永久固化 —— "结构合法"不等于"数值正确" | 🔴 数据完整性（影响回测输入正确性） | — | 已修复（脚本加 `--refresh` + 3072 行已刷新） | `2026-09-03-intraday-snapshot-frozen-as-daily-bar.md` |
| 2026-09-02 | 2026-09-02 verification-guard-quietly-dead-two-ways | — | — | — | `2026-09-02-verification-guard-quietly-dead-two-ways.md` |
| 2026-09-02 | 判据里只要存在「每轮重置」的项，低频持续故障 100% 测不出来 | — | — | — | `2026-09-02-per-run-reset-in-criterion-blinds-low-rate-failures.md` |
| 2026-09-02 | 日志只配了一半：structlog 可用时 INFO 级全部静默丢失 | — | — | — | `2026-09-02-half-configured-logging-makes-monitor-invisible.md` |
| 2026-09-02 | 新鲜度检查量的是「容器运行时长」：写接口零调用，评分退化为 uptime 的纯函数 | — | — | — | `2026-09-02-freshness-measures-uptime-not-data.md` |
| 2026-09-02 | 修了「一处」不等于修了「一类」：验收口径倒挂让同款 bug 存活 4 天 | — | — | — | `2026-09-02-fix-one-instance-verify-whole-class.md` |
| 2026-09-02 | 把告警委托给别人，就必须先校验那个人还活着 | — | — | — | `2026-09-02-delegated-alert-without-liveness-check-goes-silent.md` |
| 2026-09-02 | 配置写了三处，代码一处都不读 —— 「配置被无视」比「配置写错」更隐蔽 | — | — | — | `2026-09-02-config-written-three-places-read-nowhere.md` |
| 2026-09-01 | 定时任务 24×7 空跑：交易时段守卫缺失 × cron 缺 day_of_week | — | — | — | `2026-09-01-scheduled-jobs-run-24x7-without-trading-hours-guard.md` |
| 2026-09-01 | Provider 吞掉限频异常 → 批量任务对超限源发起 4494 次无效调用 | — | — | — | `2026-09-01-provider-swallows-ratelimit-4494-useless-calls.md` |
| 2026-09-01 | 降级链熔断做成实例级：跨定时任务完全失效，每天白等 16.4 分钟 | — | — | — | `2026-09-01-instance-scoped-cooldown-crosses-no-task-boundary.md` |
| 2026-09-01 | 「默认通过」的统计口径让监控自我否定：评分 55/100 却报 通过 7/7 | — | — | — | `2026-09-01-default-true-makes-monitor-self-negating.md` |
| 2026-09-01 | QTS 全容器 UTC + 代码零时区保护：落库时间戳早 8 小时，凌晨日期会记成前一天 | — | — | — | `2026-09-01-container-utc-codes-zero-timezone-guard.md` |
