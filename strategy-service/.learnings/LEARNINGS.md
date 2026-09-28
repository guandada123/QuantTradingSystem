# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [LRN-20250620-001] urllib.urlopen mock 模式匹配

**Logged**: 2026-06-20T15:20:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
Mock `urllib.request.urlopen` 时，必须匹配生产代码的调用模式：非 `with` 上下文管理器模式应使用 `mock_urlopen.return_value = mock_response`，而非 `mock_urlopen.return_value.__enter__.return_value = mock_response`。

### Details
`_fetch_index_via_tencent` 使用 `resp = urllib.request.urlopen(url, timeout=5)`（无 `with` 语句），但测试 mock 了 `__enter__`，导致 mock 不生效。修复后 4 个测试通过。

### Resolution
- **Resolved**: 2026-06-20T15:20:00+08:00
- **Procedure**: 将 `mock_urlopen.return_value.__enter__.return_value = mock_response` 改为 `mock_urlopen.return_value = mock_response`
- **Files**: `tests/test_data_service.py` (4处修改)

---
## [LRN-20260831-001] 收盘回测日报 Top5 单笔交易虚高（✅已升级(2026-09-27)）

**Logged**: 2026-08-31T14:59:00+08:00
**Priority**: high
**Status**: open
**Area**: services/report_service.py

### Summary
`generate_daily_brief` 的 Top5 在 63 个交易日的短窗口下**全部只有 1 笔交易**，sharpe 高达 20~75 系单笔统计假象。min_trades 两级过滤（≥5 → ≥3）全部落空，最终走 714 行保底分支。下游（晚报/选股）若直接引用会误导。

### Details
- 每日回测窗口 = 63 个交易日（日志实锤 `trade_days=63`），单标的独立回测 → 平均 <1 笔交易
- 9988 次回测中，原始 top50 **无一条达 ≥3 笔** → report_service.py L705/L710 两级过滤均空 → L714 保底返回原 top5
- 结果：Top5 全部 `total_trades=1`、`win_rate=100%`、`wf_label="⚠️ 低样本"`、sharpe 24.5~75.5
- 已有护栏：`flags.low_sample=true` 已正确置位，但 **flags 缺少 `fallback_low_sample` 键**，下游无法区分"样本不足5条" vs "完全无≥3笔走保底"

### Resolution（建议，未实施）
1. 回测窗口从 63 天拉长到 ≥250 个交易日，使单标的可积累 ≥5 笔交易
2. 或改为组合级/多标的聚合回测，而非逐票独立回测
3. `flags` 增加 `fallback_low_sample` 键，供晚报判断是否弱化/隐藏 Top5

### 附带发现（✅已升级(2026-09-27)）
股票池仅排 ST/科创(688)，**创业板 300/301 未过滤**（2026-08-31 Top5 含 300534.SZ、301591.SZ），
与用户"仅主板/中小板，不碰创业板/科创板"偏好冲突。与既有待办"信号层 vs sim_trade.py 300/301 过滤不一致"同源。

### Meta
- **Source**: automation-1784216360030（QTS 策略日评，2026-08-31 首次运行）
- **Files**: `services/report_service.py` (L697-716)

---
## [LRN-20260902-001] walk-forward 通过率持续下滑，Top5 应由 overfit 符号而非 sharpe 排序（✅已升级(2026-09-27)）

**Logged**: 2026-09-02T17:37:00+08:00
**Priority**: high
**Status**: open
**Area**: services/report_service.py

### Summary
连续三日数据显示 walk-forward（样本外）通过率单调下滑：08-31 未采集 → 09-01 `wf_passed=5/30`(16.7%) → **09-02 `wf_passed=2/30`(6.7%)**。
同时 Top5 的 `wf_overfit_ratio` 连续两日**全为负**（样本外普遍劣化），说明 sharpe 排名与样本外表现**反向相关**，晚报若按 sharpe 顺序引用 Top5 会系统性放大过拟合标的。

### Details（2026-09-02 实锤）
| 标的 | 策略 | sharpe | total_return | wf_stability | wf_overfit_ratio |
|---|---|---|---|---|---|
| 003032.SZ 传智教育 | kdj | 30.19 | 105.58% | 60% | **-0.55** |
| 603269.SH 海鸥股份 | macd | 29.36 | 93.60% | 60% | **-19.26** |
| 002855.SZ 捷荣技术 | macd | 30.11 | 96.63% | 40% | **-17.87** |
| 002855.SZ 捷荣技术 | ma-cross | 21.80 | 82.58% | 20% | **0.00**（陷阱，见下） |
| 600664.SH 哈药股份 | ma-cross | 78.67 | 179.66% | 40% | **-1.95** |

- **陷阱**：`wf_overfit_ratio=0.00` **不等于**"不过拟合"。ma-cross/002855 的 `wf_stability=20%`（5 个 WF 窗口仅 1 个有交易），
  0.00 是"样本外压根没交易"的默认值。**判读规则：`wf_stability < 40%` 时 `overfit_ratio` 无意义，应先看 stability。**
- Top5 仍全部 `total_trades=1` / `win_rate=100%` / `wf_label="⚠️ 低样本"`（与 08-31、09-01 同，结构性未解）
- 回测窗口 09-02 为 `trade_days=120`（08-31 时 63 天），窗口已拉长但单标的交易数仍为 1 → **LRN-20260831-001 的建议①部分生效但未根治**

### Resolution（建议，未实施；无人值守默认不改代码）
1. Top5 排序改为**一级按 `wf_overfit_ratio` 降序（取负值小者）、二级按 `wf_stability` 降序、三级才看 sharpe**，
   避免把"样本内漂亮、样本外崩盘"的标的排到第一
2. `wf_overfit_ratio == 0` 且 `wf_stability < 40%` 时，label 应置为 `⚠️ 无有效样本` 而非复用 `⚠️ 低样本`，防止误读为"稳健"
3. `summary` 增加 `wf_pass_rate`（= wf_passed/wf_candidates）趋势字段，供晚报做环比

### 附带改善（2026-09-02）
Top5 **首次零创业板**（003032/603269/002855/600664 均为主板/中小板），但这是**结果巧合，代码未改**——
`report_service.py:76` 仍只排除 68/689。创业板过滤的规则冲突（USER.md「不碰创业板」vs sim_trade.py 07-29 已放开）**仍待用户裁决**。

### Meta
- **Source**: automation-1784216360030（QTS 策略日评，2026-09-02 运行）
- **Files**: `services/report_service.py`
- **Related**: LRN-20260831-001

---
## [LRN-20260903-001] 全市场回测三重数据层故障：WAF 频控 + 部分灌数静默降级 + 缺失表致过滤失效（✅已升级(2026-09-27)）

**Logged**: 2026-09-03T20:52:00+08:00
**Priority**: high
**Status**: resolved
**Area**: services/data_fetcher.py, services/report_service.py

### Summary
2026-09-03 收盘回测**跑满 14 分钟仍未完成**（历史 103~199s）。表面现象"进程卡死"，
实为三层独立故障叠加。三层全部定位并修复后，回测 **101s 完成 13453 次**，结果与历史完全可比。

### 三层根因（由表及里）

| 层 | 故障 | 证据 | 后果 |
|---|---|---|---|
| ① 网络源 | 腾讯 fqkline 对单 IP 有 WAF 频控 | `web.ifzq.gtimg.cn` 稳定 501(`waf.tencent.com`)；换 `ifzq.gtimg.cn` 后前 ~2000 次 200，**之后同样 501** | 4579 只股票串行取数必然跑不完 |
| ② 池选择 | `daily_quote` 的 2026-09-02 **只灌了 44 行**（前一日 4893 行，amount 均值 38 万 vs 正常 3.7 亿） | `MAX(trade_date)` 指向这个不完整日 → 流动性筛选 `amount>=3亿` 命中 **0 只** | 静默降级到全量池 **4579 只**（正常 1235，3.7 倍）→ 直接把 ① 顶穿频控 |
| ③ 过滤 | `stock_basic` 表**根本不存在**（`stock_info` 空且无 name 列） | 日志 `ST 过滤失败(跳过名称层)` | ST 股未排除，但日志仍打印"已排ST/科创"→ **误导排查** |

**因果链**：③ 让池子变大 → ② 的不完整日让池子再膨胀 3.7 倍 → 超过 ① 的 WAF 阈值 → 全部取数失败 → 每只股票走 3 次重试 + 退避 sleep + 东财回落（东财亦不可达）→ 单只成本 10~30s → 小时级。

### 关键取证手法（可复用）
- **`/usr/bin/sample <pid> 2 2 -mayDie`（无需 root，py-spy 在 macOS 要 root）**：抓到主线程 **74% 落在 `time.sleep`→`nanosleep`**、15% 在 SSL 握手 `poll` → 立刻锁定"重试退避 + 网络等待"，而非 CPU 密集。
  注意：venv 里有同名 `sample` 会抢 PATH，**必须写全路径 `/usr/bin/sample`**。
- Docker 端口映射会**重写源端口**，无法用 `lsof` 的客户端端口去 `pg_stat_activity.client_port` 对号入座。
- 判"进程是否真阻塞"：间隔 15~30s 采两次 `ps -o time=`（累计 CPU 秒）。本次 30s 只涨 0.35s ≈ 2.3% → 实锤非计算密集。

### Resolution（已实施）
1. **`services/data_fetcher.py`**：`fetch_kline_tencent` 增加 **L0 本地库 `daily_quote` 优先**。
   校验过本地库与腾讯前复权数据**逐笔一致**（000001.SZ 2026-09-02：o=11.92 h=11.99 l=11.85 c=11.91 vol=892247 vs 腾讯 892248）。
   所有取数路径（行情/回测/Walk-Forward/基准指数）都汇聚到此函数，改一处全覆盖。
   附带：腾讯双 host 轮转（`ifzq` ↔ `web.ifzq`，任一被封自愈）+ 本地库**新鲜度守卫**
   （`max(trade_date)` 距今 ≤5 天才用本地源，否则走网络，避免静默用陈数据）。
2. **`services/report_service.py`**：流动性筛选基准日由 `MAX(trade_date)` 改为
   **"记录数 ≥1000 的最后一个交易日"**，`HAVING COUNT(*) >= 1000`，缺失时再退回 MAX。
3. **`services/report_service.py`**：`_exclude_banned` 返回 `(codes, st_filtered)`，
   日志如实标注 `已排科创，⚠️ST未过滤`，不再假称已排 ST。

### 效果（2026-09-03 实锤）
| 指标 | 修复前 | 修复后 |
|---|---|---|
| 耗时 | >14 min 未完成（最终 kill） | **101s** |
| 股票池 | 4579 只（降级模式） | **1235 只**（流动性筛选，回到 09-01/02 水平） |
| 回测次数 | — | **13453**（09-01/02 为 13464） |
| 网络请求 | 4579 次串行（触发 WAF） | **0**（全走本地库） |

### ✅已升级(2026-09-27) 铁律
1. **全市场批量回测不得依赖单 IP 的公开行情 API**——腾讯/东财都有 WAF 频控，本地库才是系统主源，网络仅作补充。
2. **任何"最近日期"基准不能用 `MAX(date)`**，必须加"完整性阈值"（如当日记录数 ≥1000），否则**部分灌数会静默降级**且无告警。
3. **日志声称的过滤必须与实际生效一致**。假称"已排ST"比不排更危险——排查时会先入为主地排除这个方向。

### 未解决（需用户裁决，延续 LRN-20260831-001）
- ~~`stock_basic` 表缺失 → ST 股仍未过滤~~ **已于同日 21:00 修复**：改用 `shared.stock_name`
  （`astock_code_name.json`，5528 条映射）。实际排除 4 只（600745/000711/002528/300010），
  池 1235→1231。⚠️ 名称文件是 **2026-07-17** 的快照，7 月后新戴帽的 ST 会漏网。
- 创业板 300/301 仍未过滤（`_exclude_banned` 只排 68/689），规则冲突待裁决。
  已加 `test_gem_not_excluded` 锁住现状，改动必须同时更新该测试。
- Top5 仍全部 `total_trades=1` / `wf_label="⚠️ 低样本"`，结构性问题未解（见 LRN-20260831-001 / LRN-20260902-001）。

### Meta
- **Source**: automation-1784216360030（QTS 策略日评，2026-09-03 运行）
- **Files**: `services/data_fetcher.py`, `services/report_service.py`
- **Tests**: 三件套 **124 passed**（基线 108，本次新增 16 条）
- **Related**: LRN-20260831-001, LRN-20260902-001, LRN-20260903-002

---

## LRN-20260903-002: 缓存分层顺序错误 → 内存缓存形同虚设（✅已升级(2026-09-27)）

**Date**: 2026-09-03 | **Severity**: high | **Status**: resolved | **★**: 是

### 现象
三处修复 + 回归测试全部写完后跑测试，`test_local_db_hit_populates_mem_cache` 失败：
同参数二次调用仍触发第二次查库（`mock_db.call_count == 2`，期望 1）。

### 根因（第一版修复自己引入的）
加"本地库优先"时，把 L0(本地库) 插在了 **L1(内存缓存) 之前**：

```python
# ❌ 错误
local = _fetch_kline_from_db(...)      # 每次都打 DB
if local:
    _mem_cache[key] = local
    return local
cached = _mem_cache.get(mem_key)       # 永远走不到
```

内存缓存写是写了，**但永远没机会被读**。11 策略 × 1231 只 = 13541 次调用，
每次都真查库；正确分层下只需 1231 次唯一键查询 + 12270 次内存命中。

### 修复
内存缓存提到最前（最廉价的层必须最先判）：L0 内存 → L1 本地库 → L2 磁盘 → L3 网络。

### 效果（实锤）
| 指标 | 顺序错误时 | 修正后 |
|---|---|---|
| 回测耗时 | 85s | **12s**（7×） |
| DB 查询次数 | ~13541 | **1231** |
| 结果一致性 | — | 13409 次回测 / sharpe 0.279 / wf_passed 3，**完全一致** |

### ✅已升级(2026-09-27) 铁律
1. **多层缓存必须按"单次成本升序"排列**：内存 < 本地DB < 磁盘 < 网络。
   新增一层时，先确认它插在成本序的正确位置——**插错位置比不加更隐蔽，
   因为功能正确（缓存有写入），只是性能全丢，且不报错**。
2. **加缓存层后必须写"命中次数"断言**，不能只断言"返回正确"。
   `assert mock.call_count == 1` 是唯一能抓到"写了不读"的测试形态。

### 附带：写回归测试时踩的两个陷阱（已写进 skill）
1. **磁盘缓存泄漏进测试**：`fetch_kline_tencent` 有 `.cache/tx_*.json` 磁盘层，
   只 patch `urlopen` 不够——若该代码+日期区间之前被真实跑过，会直接命中磁盘
   返回真数据，`urlopen` 的 mock 根本不被调用。必须同时
   `patch("...os.path.exists", return_value=False)`。
2. **构造函数副作用吃掉 mock 队列**：`ReportService()` 不传 `stock_pool` 时，
   `__init__` 会跑一次真实的 `_load_stock_pool_from_db()`，把 `execute.side_effect`
   列表消耗光，等测试再调用只剩 `StopIteration`，表现为"收到兜底池"，
   极易误判成生产代码有问题。解法：传 `stock_pool` 构造 + 用**按 SQL 内容分发**的
   函数式 side_effect（不依赖调用顺序）。

### Meta
- **Source**: automation-1784216360030（QTS 策略日评，2026-09-03 收尾验证）
- **Files**: `services/data_fetcher.py`（L0/L1 顺序）、`tests/test_data_fetcher.py`
- **Tests**: `TestLocalDbFirst::test_mem_cache_checked_before_local_db` 专门守卫此顺序
- **Skill**: 两个测试陷阱已写入 `mock-http-context-manager`（Trap 5 / Trap 6）

---

## LRN-20260903-003: 静态快照无刷新机制 → ST 识别静默失真（✅已升级(2026-09-27)）

**Date**: 2026-09-03 | **Severity**: high | **Status**: resolved | **★**: 是

### 现象
`shared/astock_code_name.json`（5528 条代码→名称映射）自 **2026-07-17** 生成后
**没有任何刷新机制**，7 周未更新。该映射是 ST/*ST 识别的唯一名称源。

### 危害（实测，双向误差）
| 方向 | 数量 | 例子 |
|---|---|---|
| **漏网**（新戴帽） | 5 只 | 002759 天际股份→ST天际、301117 佳缘科技→ST佳缘、600439、600530、688089 |
| **误杀**（已摘帽） | 12 只 | 000711 ST京蓝→京蓝科技、002199、002214、300125 等 |

最危险的是**它不报错**：名称查得到、ST 过滤照跑、日志照写"已排ST"，只是结果全错。
与 LRN-20260903-001 的 `stock_basic` 缺失属同一类——**静默失效比功能缺失更难发现**。

### 修复
1. 新增 `shared/refresh_stock_names.py`：腾讯 `qt.gtimg.cn` 批量拉取（100 只/批，56 批）。
   **刻意不用 `ifzq.gtimg.cn` / `web.ifzq.gtimg.cn`** —— 那两个域名有 WAF 频控。
   三条硬约束：拉取失败保留旧值（绝不丢键）、原子写、完整性守卫（新映射不得少键）。
2. `shared/stock_name.py` 加 `_warn_if_stale()`：>30 天未更新即告警（不抛异常，
   名称过期影响准确性而非可用性）。
3. 刷新后池 1231 → 1232（000711 回归）。

### ✅已升级(2026-09-27) 铁律
1. **任何"静态快照 + 无刷新机制"的数据源都是定时炸弹**。快照类数据必须有：
   刷新脚本 + 过期告警（阈值）+ 备份。三者缺一，就等着静默失真。
2. **依赖名称做规则判断（如 ST 过滤）时，名称源的时效性 = 规则的正确性**。
   名称变了规则结论就变，这不是"锦上添花的数据更新"，是**正确性依赖**。
3. 刷新类脚本的默认值：**失败保留旧值 > 失败写空**。宁可用旧数据，不能让键消失。

---

## LRN-20260903-004: 验证 `trap EXIT` 清理时误判 lock 泄漏

**Date**: 2026-09-03 | **Severity**: low | **Status**: resolved | **★**: 否（但易复发）

### 现象
运行 `touch L && trap "rm -f L" EXIT && <cmd>` 后，在**同一条 Bash 调用内**
`ls L` 仍看到文件 → 判为"🔴 lock 残留"，一度准备报告为故障。

### 根因
Bash 工具**每个调用是独立 shell**，`trap ... EXIT` 注册在当前 shell，
只在**该调用结束、shell 退出时**才触发。同一调用内的 `ls` 必然早于 trap。

### 验证
另起一个 Bash 调用检查 → 文件已清（trap 正常）。
顺带排除错误假设：实测 `(...)` 子shell / 管道 / 无管道 四种组合，
**管道不是原因**（曾以为是 `| grep` 把 trap 挤进子shell）。

### 铁律
**验证 `trap EXIT` 的清理效果，必须另起一个 shell 调用检查，不能在同一调用内验证。**
同一原理适用于任何"依赖进程退出才生效"的机制（atexit、finally 在长驻进程里等）。

### Meta
- **Files**: 无代码变更（纯方法论）
- **已写入**: 项目 `.workbuddy/memory/2026-09-03.md`、自动化 memory

---

## LRN-20260907-001: `data_stale=false` 只代表"没有截断日"，不代表"数据是今天的"

**Date**: 2026-09-07 | **Severity**: medium | **Status**: open | **★**: 是（✅已升级(2026-09-27)）

### 现象
2026-09-07 14:55 跑出 brief：`report_date=2026-09-07`、`data_as_of=2026-09-04`、
`data_stale=false`、`incomplete_sessions=[]`。
即：**数据比报告日晚 1 个交易日，但"滞后"标记是绿的。**

### 根因
`report_service.py:949` 的实现是 `result["data_stale"] = bool(result["incomplete_sessions"])`
—— 它只检测"某个交易日灌了一半（截断）"，**完全不比较 `data_as_of` 与 `report_date`**。
09-04 那次 P0（灌库被杀只写进 44 行）之后，freshness 探针是围绕"截断"设计的，
于是"整段缺失最新交易日"这个兄弟场景天然免疫：
没有残缺日可报 → `incomplete_sessions=[]` → `data_stale=false`。

**这是 09-04 教训的同族第三个变体**：失效方向仍然一律是"误报为健康"。

### 影响
晚报「量化策略验证」段若只判 `data_stale` 就当作"今天的回测"来表述，会把
截至上周五的结论说成今日结论。本次恰好无害（14:55 跑、15:00 才收盘，
**当日 K 线客观上不存在**，滞后 1 个交易日是结构性正确的），
但字段名与语义不匹配，迟早误导下游。

### 判据（下游该用的正确口径）
**比较 `summary.data_as_of` 与 `report_date`，不要用 `data_stale` 判滞后。**
`data_stale` 的准确语义应读作 `data_truncated`。

### 待办（未改代码，无人值守不擅动生产语义 + 1344 条测试基线）
1. 新增 `data_lag_sessions`（`report_date` 与 `data_as_of` 之间相差几个交易日），
   保留 `data_stale` 原义不变（避免破坏既有消费方）
2. 或把 `data_stale` 改名 `data_truncated` + 新增 `data_lag_sessions`，语义正交
3. 配套守卫测试：注入 `data_as_of < report_date` 的 case，断言滞后字段能被点亮

### 复用要点
- **给指标命名时，名字要能翻译成一个问句**。`data_stale` 听着像"数据旧了吗"，
  实则答的是"有没有灌一半的日子"。名字与实现各答一个问题 → 必然有人读错。
- **修完一类故障后，主动找它的兄弟场景**：09-04 修了"截断"，就该顺手问
  "整日缺失会怎样？"——本题答案是一样静默。修 A 不查 A' 等于把风险推到下一次。

### Meta
- **Files**: `services/report_service.py`（`_probe_data_freshness` / L949 附近）
- **已写入**: 项目 `.workbuddy/memory/2026-09-07.md`、自动化 memory

---

## LRN-20260908-001: 库内自比查不出"整段缺失的交易日"，必须拿交易日历做外部基准

**Date**: 2026-09-08 | **Severity**: high | **Status**: open | **★**: 是（✅已升级(2026-09-27)）

### 现象
2026-09-08 14:55 的定时回测，首轮 `generate_daily_brief()` 正常返回无报错，
但 `data_as_of=2026-09-04` —— **比 report_date 落后 2 个交易日（09-07、09-08 全缺）**。
`data_stale=false`、`incomplete_sessions=[]`，全程零告警。
回测结果因此与 09-07 几乎逐字重复（best_sharpe 同为 6.393、Top5 前 3 名完全相同）。

### 根因
灌库自动化 `automation-1784811393302`（QTS日线全市场回填，16:30）在 09-07 失败：
```
09-07T08:30:23Z run start  → 09-07T08:32:26Z run finished success=false
  [CANCELLED] Automation prompt interrupted: unknown_interrupted   （仅撑 2 分钟）
```
09-02/03/04 三次是 `Run timed out`，09-07 换成 `unknown_interrupted`（并发饿死的另一种表现），
**失败模式会变脸，但产物一样：那个交易日的 K 线一行都没有。**

为什么所有检查都瞎了：现有三处新鲜度/完整度探针（`report_service._probe_data_freshness`、
`data_fetcher._local_db_fresh`、`data_quality.check_freshness`）**全部只在 daily_quote 内部做库内自比**
—— `GROUP BY trade_date ORDER BY DESC`。库里最新日就是 09-04，于是"最新日"永远成立。
**库内自比永远看不见"本该存在却不在库里的日子"。**

这是 09-04「`MAX(trade_date)` 掩盖截断」、09-07「`data_stale` 语义错位」的**同族第四个变体**，
失效方向第四次是"误报为健康"。

### 处置（本次已自愈）
直接跑 `qts_daily_backfill.py --days 4 --min-coverage 0.9`（30s）→
09-07 补 4571 行、09-08 补 4892 行，覆盖率 97.0%；重跑回测 21s →
`data_as_of=2026-09-08`，**12969 次 / sharpe 0.014 / wf_passed 5**。
（未修复首轮的 13882 次 / sharpe -0.045 已作废，勿引用）

### 待办（未改代码，无人值守 + 1344 条测试基线）
1. brief 增加 `data_lag_sessions`（承 LRN-20260907-001）
2. **新增"交易日缺失"探针**：拿交易日历（本地已有 `Claw/scripts/is_trading_day.py` 口径）
   与 `daily_quote` 的 DISTINCT trade_date 做差集，缺 N 个交易日即告警 —— 这是唯一能抓本题的检查
3. 灌库自动化失败时没有下游告警，建议 health-check 侧挂一条"最近 3 个交易日是否齐全"

### 复用要点
- **"数据够不够新"这类检查，基准必须来自库外**。库内自比（`MAX(date)`、`GROUP BY` 排序取最新、
  行数门槛）全部只能回答"库里有什么"，回答不了"库里缺什么"。**缺的东西不会出现在任何聚合结果里。**
- **上游定时任务失败 → 下游静默产出旧结论，是本系统最高频的一类事故**（04 截断、07 语义、08 整段缺失）。
  判据：**下游产物的"新鲜度"字段必须能独立于上游的成功/失败而自证**，不能假设上游一定跑过。
- **重复结果本身就是一个告警信号**：两次不同 report_date 的回测若 best_sharpe 与 Top5 逐字相同，
  99% 是数据源没动，不是策略稳定。
- **自愈优先级**：发现数据缺失时，先补数据再重跑，比在旧数据上写免责声明有用。
  `qts_daily_backfill.py --days 4` 只要 30s，成本远低于交付一份滞后 2 日的结论。

### Meta
- **Files**: `services/report_service.py`（`_probe_data_freshness`）、`services/data_fetcher.py`、
  `services/data_quality.py`；上游 `Claw/.workbuddy/scripts/qts_daily_backfill.py`
- **关联**: LRN-20260904-001（截断）、LRN-20260907-001（data_stale 语义）
- **已写入**: 项目 `.workbuddy/memory/2026-09-08.md`、自动化 memory

## LRN-20260909-001 ✅已升级(2026-09-27)｜盘前时段跑"收盘回测"，必然产出与昨日逐字相同的日报

**现象**：09-09 日报 12969 次 / sharpe 0.014 / best 6.322 / wf 5 / Top5 顺序，
与 09-08 **逐字相同**，连 `positive_strategies` 都只差 1（6016 vs 6017）。

**根因（不是故障，是口径设计缺陷）**：本自动化调度在 **14:55**，A 股 **15:00 才收盘**。
`data_as_of` 因此恒为 **T-1**（今日 09-09 → 数据 09-08）。09-08 那轮修复后的
`data_as_of` 也是 09-08 —— **同一份输入，自然产出同一份输出**。

**为什么危险**：09-08 刚写下铁律「连续两天结果逐字相同 = 数据源没动，不是策略稳定 → 当告警」。
今天这条铁律**立刻自我命中**，但根因完全不同：不是灌库失败，是**调度时刻早于收盘 5 分钟**。
两类根因产物同形，处置却相反（一个要补数据，一个要改调度时刻）。

**判据（下游/巡检必用）**：
- 比 `summary.data_as_of` 与 `report_date`：**相等才算"当日回测"**，差 1 即 T-1 口径
- 连日 `data_as_of` **不前进** → 灌库挂了（09-08 型）
- 连日 `data_as_of` **每天都前进但 report_date 总快 1 天** → 调度时刻早于收盘（本例）
- `data_stale` 仍应读作 `data_truncated`（LRN-20260907-001），它**不参与**这个判断

**本次未改代码**（无人值守 + 1344 条测试基线）。建议裁决项（二选一）：
1. 调度改 **15:35**（收盘后 35 分钟，等灌库窗口）→ `data_as_of` 可真正等于 `report_date`
2. 保持 14:55，但在 summary 显式注入 `data_lag_sessions: 1`，让晚报自行标注"截至 T-1"

**对晚报的直接影响**：09-09「量化策略验证」段的 Top5 与 09-08 完全相同，**无新增信息量**，
应照抄昨日结论或明确标注"与昨日一致（数据未更新）"，不要写成"今日新发现"。

**⚠️ 待裁决项已连续 3 次人工绕过（09-09 / 09-10 / 09-11），仍未改代码**：
- 09-09：人肉盘中补一次 + 收盘后补一次
- 09-10：同上，且盘中那次踩了 LRN-20260910-001（数值截断）
- 09-11：**首次把等待写进自动化执行流程** —— 检测到 `date` 早于 15:00 即 `sleep` 到 15:05，
  再 `--days 4` 回填（35s，4890 行 / 17251 亿）后跑回测 → `data_as_of=2026-09-11 == report_date` ✅
- 三次都"这一次跑通了"，但**每次都要靠执行者记得等**。调度时刻 14:55 一天不改，
  就一天存在"换个执行者/换个上下文就产出 T-1 口径"的风险。
- **这是治标：脚本层等待消耗约 7 分钟墙钟，且不改变调度语义。裁决项 1（调度改 15:35）仍有效且更省。**

### Meta
- **Files**: `services/report_service.py`（`generate_daily_brief` / `_probe_data_freshness`）
- **关联**: LRN-20260907-001（data_stale 语义）、LRN-20260908-001（库内自比查不出整段缺失）
- **复用要点**：**告警信号命中后，先确认它命中的是不是同一条铁律的"另一种根因"**。
  同形异因时，直接套用旧处置方案（本次会是"去补数据"）会白跑一轮 —— 数据本来就是新的。

---

## ✅已升级(2026-09-27) LRN-20260910-001：行数齐全 ≠ 数值收盘 —— 盘中 bar 会悄悄改小过滤口径

**现象**：09-10 首轮回测 **11275 次**（前两日恒为 12969），池子凭空少 13%。日志全绿：
`data_as_of=2026-09-10`、`data_stale=false`、`incomplete_sessions=[]`，无任何告警。

**根因**：本任务 14:55 调度、我在 14:57 执行 `--days 4` 回填 —— **盘中拉到了当日 bar**。
该 bar 行数 **4889**（与正常交易日同量级），`_probe_data_freshness` 的
`HAVING COUNT(*) >= 1000` **顺利通过**，但它只答"今天有没有这么多只股票的记录"，
**答不了"每只股票的 `amount` 是不是全天的"**。

盘中 `amount` 只有全日的 ~4/5 → `report_service.py:256` 的
`amount >= 300000000`（3亿）流动性门槛**命中率被压低**：

| 基准日 | 总数 | 成交额≥3亿 | 占比 |
|---|---|---|---|
| 09-08（完整） | 4892 | 1199 | 24.5% |
| 09-09（完整） | 4571 | 1125 | 24.6% |
| **09-10（盘中 14:57）** | 4889 | **1033** | **21.1%** |

→ 池 1179 → **1025**（-13%）→ 回测 12969 → 11275。

**同族第 5 个变体，失效方向依然全是"误报为健康"**：
1. 09-04 `MAX(trade_date)` 掩盖截断（行数 44 却称最新）
2. 09-07 `data_stale` 只报 `incomplete_sessions`，不比日期
3. 09-08 库内自比查不出整段缺失的交易日
4. 09-09 调度早于收盘 → `data_as_of` 恒为 T-1
5. **本例：行数齐全但数值未收盘 → 过滤口径被悄悄改小**
共同点：**每一次都量到了一个真实但无关的量**。

**判据（建议补的守卫）**：用「当日 `SUM(amount)` 或 amount 中位数 vs 近 10 日同口径」
判是否盘中/未结算，**不要只看行数**。行数完整性 ≠ 数值完整性。

**处置（本次已执行）**：15:03 收盘后重跑 `--days 2` 回填 → 池 1025 → **1041**，
回测 11275 → **11451**。

**本次未改代码**（无人值守 + 1344 条测试基线）。

⚠️ **重要边界：重跑后"恢复"不等于"完全恢复"**。收盘后重拉，09-10 总成交额
**14512 亿**仍比 09-09 的 16197 亿低 **10%**，流动性占比 21.5% 仍低于 24.6% 常态。
说明 **-13% 里只有一小部分是盘中截断，主体是当日真实缩量**。
→ 今日 **11451 次与前两日 12969 次不可直接环比**，属口径差异，不是策略变化。

✅ **附带成果：09-09 的 T-1 问题在操作层被绕过**（未改代码）。
做法：盘中先补一次让当日数据存在，收盘后再补一次拿终值 →
首次实现 `data_as_of == report_date`（PG 中 09-09 行的 `data_as_of` 仍是 09-08，可对照）。
这比改调度更快，但依赖"有人在本轮里做二次回填"，不可持续 —— 仍建议裁决改 15:35。

### Meta
- **Files**: `services/report_service.py`（`_probe_data_freshness` / `_load_stock_pool_from_db`）
- **关联**: LRN-20260904（截断）、LRN-20260907-001、LRN-20260908-001、LRN-20260909-001
- **复用要点**：**"这指标在数据坏的时候会变吗？"要追问到数值层，不止行数层**。
  行数只能证明"记录写进去了"，证明不了"写进去的是终值"。
  凡按绝对值门槛过滤（成交额/成交量/市值）的池子，遇到盘中数据必然静默缩水。

## ✅已升级(2026-09-27) LRN-20260911-001：brief 契约缺口 —— Top5 只输出 WF 结论，不输出第三道闸的证据值

**现象**：09-11 日报 Top1 `603823.SH / macd` 的 `wf_overfit_ratio = 9.15`，标签却是 `✅ 可信`。
两个数字摆在一起自相矛盾 —— 按 09-04 的定义 `ratio = test/train`，9.15 通常读作"样本外收益
是样本内的 9 倍"，直觉上更像异常而非稳健。

**根因（不是算错，是输出契约缺字段）**：
- WF 判可信是**三道闸**（`services/report_service.py:163`）：
  ① `stability >= 50` ② `overfit_ratio >= 0.5` ③ **`wf_return > 0`**
- Top5 组装处（L1021-1022）只写 `entry["wf_stability"]` 与 `entry["wf_overfit_ratio"]`，
  **没有 `entry["wf_return"]`**
- 所以下游拿到的是 `✅ 可信` 这个**结论**，却拿不到第三道闸**凭什么通过**的证据
- 本例真相：`ratio=9.15` 是因为**训练期夏普趋零**（分母极小 → 比值爆炸），
  正是 09-04 修 WF 判据时点名的场景；样本外实际是赚钱的，故 `wf_return > 0` 通过。
  **结论是对的，但消费方无从验证。**

**为什么危险**：
1. `dict.get("wf_return")` **静默返回 `None`**，不报错 —— 与"grep 查不到"同形（承 LRN-20260907-001）
2. 晚报若按 `overfit_ratio` 排序或评述，会把 Top1 判成"严重过拟合"，与代码结论相反
3. 判读顺序（承 LRN-20260902-001）因此断链：本应 `stability → wf_return → ratio`，
   缺了中间一环就只能靠 ratio 猜

**判据（下游/巡检必用）**：
- **`wf_label` 是唯一可信的 WF 结论**，不要自己用 `wf_overfit_ratio` 反推
- `overfit_ratio` 极大（>5）时**不是过拟合，是样本内无优势**（分母趋零），读 `wf_return` 才准
- 需要复核时去 WF 明细里取 `wf_return`；**Top5 条目里没有这个键，取到 None 是正常的，不是数据坏了**

**本次未改代码**（无人值守 + 1344 条测试基线）。建议裁决项：
Top5 组装处补 `entry["wf_return"]`，让结论与证据同出。

### Meta
- **Files**: `services/report_service.py`（L142/163/181/188 判据 vs L1021-1022 输出）
- **关联**: LRN-20260904（WF 四处判据漂移）、LRN-20260902-001（判读顺序）、LRN-20260907-001（键名静默 None）
- **复用要点**：**"结论字段"和"得出该结论的证据字段"必须一起输出。**
  只给标签不给证据，等于把复核能力锁死在生产端 —— 消费方要么盲信，要么用错误的替代指标反推。
  每加一道判据闸门，都要回头确认它的输入是否已出现在输出契约里。

---
