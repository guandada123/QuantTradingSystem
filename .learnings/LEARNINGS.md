# Learnings (QuantTradingSystem)

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | best_practice | knowledge_gap

---

## [correction] gitleaks-action@v2 强制 GITLEAKS_LICENSE 致 quality-gate 红灯（✅已升级(2026-08-16)）

- **日期**: 2026-08-12
- **现象**: QTS `CI - Quality Gate` 在 08-11 21:40 推送后突然红灯，根因非代码问题，而是 `gitleaks/gitleaks-action@v2` 自 2026-08 起 breaking change 强制要求 `GITLEAKS_LICENSE` 密钥，缺失即 `🛑 missing gitleaks license` 报错。
- **影响面**: 所有引用 `engineering-audit-kit` quality-gate `@v1` 的仓库（QTS/Claw/StockInsight/MarvisBridge）同步红灯。
- **根因**: `@v2` 浮动 tag 被 repoint 到强制 license 的新版本；同仓库 `security-scan.yml` 用 `@v3` 且无 license 仍跑通，证伪"gitleaks 需付费"假设——实为 action 包装器的 license 限制，gitleaks 引擎本身（MIT）始终免费。
- **修复**: quality-gate.yml / eak-ci.yml 改为直接经 Docker 调用开源引擎 `zricethezav/gitleaks:latest detect --redact --source=/repo`，自动探测仓库根 `.gitleaks.toml`；并将 `v1` tag 同步至修复提交 ae57b18。
- **✅已升级(2026-08-16)**: 升为🔴铁律「第三方 GitHub Action 浮动 tag 会静默弄红 CI」(优先commit SHA或Docker直调引擎; 巡检dedup按run/根因)。

## [correction] brief 落库日志误报"已落库"实为事务回滚（✅已升级(2026-08-16)）

- **日期**: 2026-08-13
- **现象**: QTS brief 落库链路 08-13 首跑失败——日志打印"[Brief] 已落库 PG"但 qts_daily_brief 表无当日记录；Claw 消费铁律"report_date 必须为今日"面临晚报 QTS 段整段缺失风险。
- **排查弯路**: 最初推测"调度任务没执行到落库分支"（因日志 grep 不到 Brief 记录），实为误判——补跑后日志有"已落库"但 PG 表仍空，回读矛盾才暴露真根因。
- **根因**: `models/database.py` 的 `get_db_session()` contextmanager **不自动 commit**（docstring 明确"db.commit()"由调用方执行），`report_service.py` 落库块漏 `db.commit()` → INSERT 在 session close 时隐式 rollback；同仓其他调用方（report_scheduler L516/L551）都有 commit，唯独此处遗漏。08-12 表内记录是手动 psql 补录，从未真正验证过该代码路径。
- **修复**: report_service.py 落库块补 `db.commit()`（a48d6335），容器 bind mount 即时生效。
- **✅已升级(2026-08-16)**: 升为🔴铁律「日志成功≠数据落库, 凡写库须 readback」(contextmanager隐式rollback; 逐调用方核对commit; 新路径查手动补录污染)。

## [correction] strategy-service `uvicorn --workers 2` 致回测日报/周报每日双推（✅已升级(2026-08-16)）

- **日期**: 2026-08-15
- **现象**: 飞书群 08-13 起连续两天「🔬 回测日报」(15:35) 和「🔬 回测周报」(15:40) 各推送 2 条，message_id 不同、同秒发出；08-11/08-12 均只有 1 条。
- **根因**: quant-strategy 容器以 `uvicorn main:app --workers 2` 运行（2 个 worker 进程），而 `main.py` 的 `lifespan()` 内 `register_report_tasks(task_scheduler)` + `task_scheduler.start()` 每个 worker 都会执行 → APScheduler 注册两遍 → 到点双推。镜像内建 CMD 是 `--workers 2`（旧镜像），Dockerfile 07-17 已改 `--workers 1` 但**镜像从未重建**；08-13 00:29 容器重建时复用旧镜像 → 双推自当天开始。
- **修复**: `docker compose --profile microservices --profile infra up -d --build --no-deps strategy-service` 重建镜像（Dockerfile workers=1 生效）→ 单 worker，调度器 14 任务单份注册，容器 healthy。
- **排查要点**: ① 飞书"通不通/推几条"必须拉真实消息流核对（`im +chat-messages-list --start/--end`），不能只看 automation_runs（QTS 容器推送不落 workbuddy.db）② uvicorn 多 worker 下 lifespan 内注册调度器 = 必然重复注册 ③ 改 Dockerfile 后必须 `--build` 重建，compose up 默认复用旧镜像。
- **✅已升级(2026-08-16)**: 升为🔴铁律「容器内定时器(APScheduler)必须单 worker」(workers=1/独立进程; Dockerfile改workers须--build重建并验证Cmd; compose profiles须显式--profile)。

## [best_practice] Colima 关机防护：AlwaysSIGTERMOnShutdown 守护（2026-08-22）

- **日期**: 2026-08-22
- **现象**: 8/19 晚两次关机卡死（shutdown stall ×2，各约2分钟），元凶=limactl hostagent+ssh 挂起阻塞 launchd 关机流程；8/18 17:22 同因。用户感知"系统又崩了"，实为关机被拖慢，最终均关机成功。
- **根因**: 日志实锤（stall 记录 + limactl/ssh 挂起进程）——Colima VM hostagent 处于不可中断等待，launchd ExitTimeOut 后仍拖慢关机。
- **处置**: 落地 `com.user.colima-shutdown-guard` LaunchAgent：`AlwaysSIGTERMOnShutdown=true` + `ExitTimeOut=90`，脚本 trap SIGTERM → `colima stop`（perl 50s 超时）→ 失败按 `ha.pid` 精确 kill hostagent。colima 已有开机自启 agent（com.github.abiosoft.colima.plist），stop 后开机自动恢复，闭环无副作用。已验证：DRY_RUN SIGTERM 链路通过（exit 0），真实模式运行中（pid 记录于日志），colima 当前不受影响。
- **排查要点**: ① LogoutHook 已废弃且 macOS 26 关机时实测不触发（社区案例），不可作唯一防线 ② launchd `AlwaysSIGTERMOnShutdown` 官方机制保证关机/注销时发 SIGTERM（agent/daemon 均支持；用户级 LaunchAgent 免 sudo） ③ bash trap 陷阱：前台 `while sleep 60` 会等 sleep 跑完才执行 trap（延迟 60s）→ 必须用 `sleep 60 & wait $!` 模式（wait 可被信号立即中断）④ 测试先 DRY_RUN 再切真实，勿在运行中容器环境直接真停。
- **防复犯**: 守护已常驻；日志 `/Users/guan/.colima/shutdown-guard.log`；卸载方式 `launchctl bootout gui/501/com.user.colima-shutdown-guard`
- **去重**: 首次

## [correction] Wind MCP 工具不可用 → 改走 wind-mcp-skill 本地 CLI（✅已升级(2026-08-30)）

- **日期**: 2026-08-30
- **现象**: WIND→QTS基本面桥（automation-1784766479083）按 prompt 调 `mcp__wind_stock_data__get_stock_fundamentals` / `get_stock_price_indicators`，ToolSearch 精确名与关键词搜索均返回 "No matching tools found"。
- **根因（取证）**: `~/.workbuddy/mcp.json` 中 5 个 wind server（wind_stock_data / wind_analytics_data / wind_index_data / vserver_financial_info / wind_economic_data）全部 `"disabled": true` → MCP 工具未注册进会话。**非 Key 失效、非网络故障**。
- **修复**: 改走 wind-mcp-skill 自带本地 CLI，同一 API Key 同一后端，取数成功：
  `cd ~/.workbuddy/skills/wind-mcp-skill && node scripts/cli.mjs call stock_data <tool> '<params_json>'`
  返回体在 `content[0].text`（需再解析一层 JSON 字符串）；失败为 `{ok:false, code, message}` 信封。
- **连带发现（数据口径坑，均已写进自动化 prompt）**:
  1. `indexes` 里「市净率」恒返回 `0.000`，必须用「**市净率(LF)**」。
  2. `windcode` 支持英文逗号批量单次 ≤50 只 → 多标的应合并成 1 次调用（省每日免费积分）。
  3. `get_stock_fundamentals` 对部分标的（002185.SZ / 000333.SZ）返回**旧快照**的 最新总市值/PE/PB（响应体缺 `交易时间`/`日期` 列即为特征，且与 price×总股本 不符）。裁决规则：price/pe/pb/总市值 一律取价格指标（实时），roe/营收/净利/总股本 取 fundamentals（报告期）。
  4. 标的后缀笔误：华天科技 002185 是深市中小板，应为 `.SZ`（原 prompt 写 `.SH`）。
- ✅已升级(2026-08-30): 「MCP 工具找不到时先查 `~/.workbuddy/mcp.json` 的 `disabled` 标记，不要先怀疑 Key/网络；若 disabled，优先找该厂商 skill 自带的 CLI 兜底通道。取多标的同类指标前先查契约是否支持批量参数，避免逐只调用浪费积分。」

## 2026-08-31 Quant 数据管线 v4 首跑 — 3 条方法论教训

### 教训 1：「重复行」≠「可安全去重」 ★升级候选
- 现象：`daily_kline` 检出 22 组 (ts_code, trade_date) 重复，第一反应是 dedupe + 加唯一索引。
- 取证推翻：19 组 close **不同**、价差恒定 +3.4%（10.86 vs 10.50），而 vol 几乎一致（856381.57 vs 856382）→ 两个行情源**复权基准不同**，是数据冲突不是重复。
- 结论：DELETE 掉其中一行 = 替用户选定数据源。**凡判定"重复"，必先比对关键业务字段是否一致；不一致即为冲突，须人工裁决，不得自动删。**
- 延伸：无唯一约束时 `ON CONFLICT DO NOTHING` 根本不成立。脚本的去重方式必须回读代码确认，不能信文档/注释里的措辞（本次文档写 ON CONFLICT，实为逐行 SELECT）。

### 教训 2：`source xxx.sh | tail` 在 zsh 下函数定义会丢失 ★升级候选
- 现象：source 后报 `run_l3_pre: command not found`，差点误判为"L3 护栏缺失"。
- 根因：管道使 source 在**子 shell** 执行，函数与变量不回传父 shell。grep 确认函数确实定义在脚本内 → 排除脚本缺陷。
- 结论：**source 启动/护栏脚本时禁止接管道**；要过滤输出就先 source 再单独处理。
- 通用化：遇到"某某函数/变量未定义"，先查调用方式（子 shell、env -u、非交互 shell），再查脚本本身。

### 教训 3：自动化自带的校验 SQL 可能从未成功执行过 ★升级候选
- 本自动化 PHASE 3 的验证 SQL 因 `trade_date` 为 TEXT 与 timestamp 比较，必然报 `operator does not exist`，却长期无人发现（本 ID 无历史 memory）。
- 结论：**校验语句本身也要验证能跑通**，不能假定模板里的 SQL 正确；尤其当"正常=静默"时，校验失效会被静默掩盖 —— 校验挂了和校验通过长得一模一样。

## [correction] QTS 策略日评 brief：wf 校验已上线但「单笔假象 + 创业板未过滤」仍在（2026-09-01）

- **日期**: 2026-09-01（automation-1784216360030 第 2 次有记录运行，对比 08-31 基线）
- **本次运行**: 交易日 ✅，L3 gates_failed=0，耗时 199s（08-31 为 155s），EXIT=0，lock 由 trap EXIT 正常清理，`report_date=2026-09-01` 通过晚报日期校验。回测量 **13464 次**（08-31 为 9988，+34.8%）。
- **✅ 已改善（对比 08-31）**: brief 新增 walk-forward 字段 —— summary 层 `wf_candidates=30 / wf_passed=5`，明细层 `wf_stability / wf_overfit_ratio / wf_label`。08-31 教训「Top5 全为单笔统计假象却无任何标注」已被**部分修复**：本次 Top5 全部带 `wf_label="⚠️ 低样本"`，消费方可据此降权。
- **⚠️ 复犯项 1（08-31 已记，未修）**: 股票池过滤仍只排 ST + 科创（`report_service.py:76` 仅 `startswith("68")/("689")`），**创业板 300/301 未过滤** → 本次 Top5 中 `301520.SZ`、`300903.SZ` 占 2/5。
  - **注意存在规则冲突，不可擅自单向修改**：USER.md 写「仅主板/中小板，不碰创业板/科创板」；但用户 TODO ③ 明确写「300/301 创业板代码过滤需**放开**以匹配 sim_trade.py 07-29 已放开规则」。两条方向相反 → **须用户裁决**，无人值守自动化默认不改代码（本次即按此默认执行）。
- **⚠️ 复犯项 2（结构性，未修）**: Top5 `total_trades` 仍为 1~2、`win_rate` 恒 100%、`sharpe` 17~90 —— 63 交易日窗口下单标的平均 <1 笔交易，两级 min_trades 过滤依旧全空并落到保底分支（`min_trades_applied=true` + `low_sample=true` 同时为真即为特征）。**Top5 仍不可直接当选股依据**，只能作策略族倾向参考。
- **新增取证发现**: 本次 Top5 的 `wf_overfit_ratio` **全部为负**（-0.55 / -19.26 / -1.11 / -17.87 / -0.91），且 `wf_passed/wf_candidates = 5/30 = 16.7%` —— 即样本外表现普遍劣于样本内。这为「单笔高 sharpe 是假象」提供了独立于 total_trades 的第二个量化证据，**晚报引用时应优先看 wf_overfit_ratio 符号而非 sharpe 排名**。
- **去重**: 复犯（第 2 次）。★升级候选 —— 建议升为规则：「回测摘要类产出，凡 `low_sample=true` 或 `wf_overfit_ratio<0`，下游消费方禁止表述为『推荐/买入信号』，只能表述为『策略族统计倾向』」。

## [correction] 上游新增字段被下游"读到"≠判定正确：晚报 WF 口径漏洞 + brief_path NameError（2026-09-01）★升级候选

- **日期**: 2026-09-01（承接同日 QTS 策略日评 brief 运行，做下游消费方核验）
- **动因**: brief 新增 wf_* 字段后，不能假定晚报会正确使用。核验 `Claw/src/claw/feeds/wx_assembler.py` 第八段「量化策略验证」。
- **核验结论**: 字段**确实已被读取**（wf_passed / wf_candidates / wf_stability / wf_label 均入表），但**判定阈值错误**，另发现一处崩溃隐患。
- **缺陷 A（口径漏洞，会污染当晚推送）**: 原 `elif wf_passed > 0: trend = "…量价策略在当前市场相对有效"` —— 只看「有无通过」，无通过率门槛、完全不读 `wf_overfit_ratio`。今日真实数据 wf_passed=5/30（**16.7%**）、Top5 overfit_ratio **全负**、low_sample=true，原逻辑仍会输出正面结论「5 个策略通过 WF 验证，量价策略在当前市场相对有效」。
  - **修复**: 改为三重门 —— `wf_rate < 30% or all(overfit_ratio<0) or low_sample` → 输出「仅可作策略族统计倾向参考，**不构成推荐或买入信号**」并逐条列出触发原因。实测今日输出变为：「5/30 个策略通过 WF 验证，但通过率仅 17%、Top5 样本外收益全部劣于样本内、低样本… → 不构成推荐或买入信号」。此即 08-31/09-01 两次 ★升级候选规则的**代码落地**。
- **缺陷 B（NameError 崩溃隐患）**: `brief_path` 原仅在 `if brief is None:` 降级分支内定义，但服务直连返回**空 dict**（非 None）时：`brief is None`=False → 跳过分支 → `if brief:` 因空 dict falsy 也为 False → 末尾 `elif not os.path.exists(brief_path)` **NameError**，整个晚报组装崩溃。已把定义提到 try 之前（回读确认全文仅 1 处定义）。
- **连带修复**: 数据来源标注原硬编码「服务直连 PG，15:00 预生成」，走 /tmp 降级时属**虚假溯源**；改为 `brief_src` 变量动态标注 + 批次时间纠正为 14:55（与实际调度一致）。
- **验证**: py_compile ✅ / ruff All checks passed ✅ / 模块 import 冒烟 ✅ / 用今日真实 brief 跑通新旧口径对比 ✅。
- **⚠️ 覆盖率缺口**: `pytest -k "assembler or wx_report or evening"` → **485 测试全部 deselected**，晚报组装器**零测试覆盖**。这类"正常=静默"的推送链路无测试 = 口径错误只能靠人工发现（本次即是）。建议补最小用例：三重门各分支 + 空 dict 直连路径。
- **通用化教训（★升级候选）**: **上游 schema 新增字段后，核验必须做两层 —— ① 下游是否读取；② 下游的判定阈值/文案是否与字段语义一致。只做①会漏掉"字段读到了但结论反了"这类最危险的静默错误。** 且凡二元门（`x > 0`）用于质量判定，必检查是否该换成比率门 + 方向门。
- **去重**: 首次（缺陷 A 是 08-31/09-01 连续两次记录的"单笔假象"教训在消费端的具体表现，本次已闭环修复）

## [correction] 降级链熔断做成实例级：跨定时任务完全失效，每天白等 16.4 分钟

- **日期**: 2026-09-01（统一巡检中枢 run#58）
- **现象**: 大盘快照 24h 调用 48 次、耗时 20.7s/次，其中 **20.4s(98.6%) 耗在 100% 失败的 akshare 源**（成功次数=0），真正取到数的腾讯源只要 0.07s → 约 16.4 分钟/天空转。同日 run#57 刚加过限频熔断并验证「4494→48 次」，看起来是修好的。
- **根因（四处叠加，缺一不可）**: ①冷却表是**实例级** `self._source_cooldown`，而每个定时任务都 new 一个 DataService → 状态随实例销毁，**从未跨过任务边界**（故障每 30min 重复，冷却只活 20s）②冷却粒度是**数据源级**，而 Tushare 限频是**按接口**的（index_daily 5次/天 vs daily 50次/分）→ index_daily 配额耗尽**连坐熔断整源** ③**provider 吞掉网络异常返回空**（akshare 未随 run#57 一起修）→ 降级链看到「有结果但 price=0」，既不报错也不熔断，**日志里连「降级链: akshare 调用失败」都没有** ④固定 300s < 任务间隔 1800s ⇒ 每轮冷却都已过期 ⇒ 每轮都重试一次，省下时间为 0。
- **修复**: `base.py` 新增 `is_systemic_error()`（限频+网络 vs 业务性错误）；`tushare.py`/`akshare.py` 系统性错误**上抛**、业务性错误仍返回空；`data_service.py` 冷却表提升为**模块级**（进程内跨实例共享）+ 键细化到 **(source, method)** + 限频即熔断/网络连续 2 次 + **指数退避** 300s→…上限 6h + 成功清零。另修 `jobs.py` 健康检查 `execution` 硬编码 `localhost:8001`（容器内无监听者，08-31 起误报 DOWN 23 次）→ 改用 compose 服务名。
- **验证**: akshare 失败**首次出现在 `降级链:` 日志**；21:07 定时作业读到 `consecutive_failures=2/3`（计数跨实例边界带过来）；熔断后同进程再调用 `latency_ms 19040 → 65`（−99.7%）；新增 11 用例，全量 1257 passed。
- **★升级候选**: 熔断状态生命周期必须 ≥ 故障发生周期；熔断粒度必须与限流粒度对齐；固定时长冷却短于任务周期=零收益，须指数退避；耗时占比>90%且成功率0 是最直观的浪费探测器；日志里没有「X 调用失败」不等于 X 没失败（可能被吞）；修「某一类错误」先 grep 全仓同类写法；「修复已验证」只在验证口径内成立，要在「故障重复的粒度」上复验。
- **详情**: `.learnings/2026-09-01-instance-scoped-cooldown-crosses-no-task-boundary.md`
