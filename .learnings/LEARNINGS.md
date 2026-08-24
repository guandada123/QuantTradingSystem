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
