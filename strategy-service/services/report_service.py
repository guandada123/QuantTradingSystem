"""
回测报告生成服务 v1.0
支持日报/周报/月报自动生成，输出飞书卡片 + Markdown格式
"""

import logging
import time as _time
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# 日报/周报/月报默认策略列表（11 策略全量同台竞技）
DEFAULT_STRATEGIES = [
    "ma-cross",
    "breakout",
    "rsi",
    "macd",
    "kdj",  # 5 经典
    "vwm",
    "bollinger",
    "adx",
    "combo-vwm-bbr",  # 4 中级
    "vbm",
    "vpb",  # 2 高级
]


def normalize_ts_code(ts_code: str) -> str:
    """归一化股票代码为标准格式 ts_code (如 002636.SZ)

    兼容 daily_kline 表中混用的非标格式: SZ002636/SH603002 -> 002636.SZ/603002.SH
    """
    s = ts_code.strip().upper()
    if "." in s:
        return s
    if len(s) >= 8 and s[:2] in ("SZ", "SH", "BJ"):
        mkt, num = s[:2], s[2:]
        return f"{num}.{mkt}"
    return s


def _exclude_banned(codes: list[str]) -> tuple[list[str], bool]:
    """剔除 ST/*ST 与科创板(68x)，避免回测样本污染与禁买标的混入

    Returns:
        (过滤后代码列表, ST名称过滤是否真的生效)

    2026-09-03 修复: ST 层原实现查 `stock_basic` 表，但该表在库中根本不存在
    （`stock_info` 亦为空且无 name 列）→ 过滤**静默失效**，日志却仍写"已排ST"，
    排查时会先入为主地排除这个方向。改用 `shared.stock_name`
    （astock_code_name.json，5528 条映射，与 execution/ai-scheduler 共用），
    懒加载一次后纯内存查表，无 DB 依赖。

    ⚠️ 创业板 300/301 **不在**排除列表内——USER.md「不碰创业板」与 sim_trade.py
    2026-07-29 已放开创业板的规则冲突未裁决，保持现状不擅自改。
    """
    # 1) 代码层排科创板
    codes = [c for c in codes if not (c.startswith("68") or c.startswith("689"))]
    # 2) 名称层排 ST
    st_filtered = False
    try:
        from shared.stock_name import resolve_name_batch

        names = resolve_name_batch(codes)
        st_set = {c for c in codes if "ST" in str(names.get(c) or "").upper()}
        if st_set:
            logger.info(f"[ReportService] 排除 ST 股票 {len(st_set)} 只: {list(st_set)[:5]}")
            codes = [c for c in codes if c not in st_set]
        st_filtered = True
    except Exception as e:
        # 名称源不可用时如实标注，由调用方在日志里写明"ST未过滤"
        logger.warning(f"[ReportService] ST 过滤失败(跳过名称层): {e}")
    return codes, st_filtered


# 用户实盘可交易的板块（USER.md「仅主板/中小板」）。
# 与 _exclude_banned 的**排除**逻辑刻意区分开：回测样本池要全（保证统计功效），
# 但输出给晚报的 Top5 必须让"策略好不好"和"你能不能买"分开呈现，
# 不能让禁买板块的条目混在可交易条目里被默认当成推荐。
TRADABLE_BOARDS: frozenset[str] = frozenset({"沪主板", "深主板", "深主板(原中小板)"})


def classify_board(ts_code: str) -> str:
    """按代码前缀判定板块。

    2026-09-04 加：创业板 300/301 一直有规则冲突 —— USER.md 写「不碰创业板」
    （实盘口径），而 sim_trade.py 2026-07-29 已放开创业板（模拟盘口径）。
    两边都是用户自己的规则，过滤掉任何一边都会毁掉另一边的信息：
      - 过滤创业板 → 回测池缩水、统计功效下降，且模拟盘也用不了
      - 不过滤      → 晚报 Top5 会静默推荐实盘不能买的标的
    故**改为标注**：每条 Top5 附上 board，summary 汇总非主板条数，
    由下游（晚报/模拟盘）各自按自己的口径消费。
    """
    code, _, suffix = str(ts_code).partition(".")
    if suffix == "BJ" or code.startswith(("43", "83", "87", "88", "92")):
        return "北交所"
    if suffix == "SH":
        if code.startswith(("688", "689")):
            return "科创板"
        if code.startswith("900"):
            return "沪B股"
        return "沪主板"
    if suffix == "SZ":
        if code.startswith(("300", "301")):
            return "创业板"
        if code.startswith(("002", "003", "004")):
            return "深主板(原中小板)"
        if code.startswith("200"):
            return "深B股"
        return "深主板"
    return "未知"


class ReportService:
    """回测报告生成服务"""

    # 回测窗口长度（天），按报告类型。理由见 _default_start_date 的实测表格：
    # 窗口必须长到让慢策略能产生 ≥5 笔交易，否则 min_trades 过滤恒为空、
    # Top5 只能退回单笔噪声。daily_quote 自 2023-01-03 起有数据，3 年窗口安全。
    WINDOW_DAYS: dict[str, int] = {"daily": 730, "weekly": 730, "monthly": 1095}

    # Walk-Forward 判可信的门槛。四处（wf_passed / wf_label / _wf_rank_score /
    # 飞书卡片）此前各用各的判据且互相矛盾，现统一走 _wf_is_trustworthy()。
    #
    # overfit_ratio 的语义（backtest_engine_v2.walk_forward）：
    #   mean(测试期夏普 / 训练期夏普)，1.0 = 样本外完全保持，负值 = 方向反转。
    # 实测 2026-09-04 的 30 个候选：
    #   min=-59.43  中位=-0.50  max=88.75；负值 17/30；>=0.5 的仅 7/30
    # 而旧的 wf_passed 判据是 `ratio <= 0.2` → 21/30 "通过"，把 -59 也算通过。
    WF_MIN_STABILITY: float = 50.0
    WF_MIN_OVERFIT_RATIO: float = 0.5

    @classmethod
    def _wf_is_trustworthy(cls, wf: dict | None) -> bool:
        """Walk-Forward 结果是否可信。三道闸，缺一不可：

        1. **稳定性** `stability >= 50`：过半的滚动窗口样本外盈利。
        2. **样本外未显著劣化** `overfit_ratio >= 0.5`：至少保留一半样本内优势。
        3. **样本外净盈利** `wf_return > 0`：复合样本外收益为正。

        第 3 道闸的理由（2026-09-04 实测补上）：前两道挡不住两类漏网——
          - **比值爆炸**：`ratio = test_sharpe / train_sharpe`，训练期夏普趋近 0 时
            分母极小，ratio 会飙到几十上百（实测 73.59 / 88.75）。这表示
            "样本内本来就没优势"，不是"样本外保持得好"。
          - **盈亏不对称**：过半窗口小赚 + 一次大亏 → stability 高但净收益为负。
        净收益为正才是"样本外真的赚到钱"的直接证据。

        ⚠️ 2026-09-04 修复：此前四处判据互相矛盾，且其中三处方向是反的——
          - wf_passed  : `stability>=50 且 ratio <= 0.2` → 把 ratio=-59 判为通过
          - wf_label   : `stability>=50 且 ratio >  0.2` → 与上一条正好相反
          - _is_overfit: `ratio > 0.2` 判为过拟合并硬排除 → 把 ratio=0.9（好）排除掉
          - _wf_rank_score: 同 wf_passed，给 ratio=-59 的策略打满权重（决定 Top5 排序）
        同一份数据能同时得出"通过"和"过拟合"两个结论。现统一到本函数。
        """
        if not wf:
            return False
        # bool() 是必需的：wf 是未定型 dict，三个 .get() 都是 Any → 不包一层则函数
        # 声明返回 bool 却实际返回 Any（mypy no-any-return），语义不变。
        return bool(
            wf.get("stability", 0) >= cls.WF_MIN_STABILITY
            and wf.get("overfit_ratio", 0) >= cls.WF_MIN_OVERFIT_RATIO
            and wf.get("wf_return", 0) > 0
        )

    @classmethod
    def _wf_rank_score(cls, rec: dict, wf_validated: dict) -> float:
        """排名权重。三档：验证可信 > 验证但不达标 > 未验证。

        2026-09-04：从 generate_daily_report 的嵌套闭包提到类方法上 ——
        闭包形态无法单测，两次判据反转都栽在这个测试盲区里。
        """
        wf = wf_validated.get(f"{rec['ts_code']}|{rec['strategy']}")
        if wf:
            # ⚠️ 2026-09-04 修复：此处原为 `stability>=50 and ratio <= 0.2`，
            # 与 wf_passed / wf_label 判据各异。旧判据会给 ratio=-59
            # （样本外方向反转，最差的一类）打满权重，而 ratio=0.9（样本外
            # 保留 90%，最好）反而只拿 0.5 折 —— 排序方向完全反了。
            # 统一走 _wf_is_trustworthy()。
            if cls._wf_is_trustworthy(wf):
                return float(wf["wf_return"] * (wf["stability"] / 100))
            # 验证过但不达标：折扣必须与稳定性**叠加**，不能替换掉稳定性缩放。
            # 2026-09-04 修复：原为 `wf_return * 0.5`（平折），导致 stability=40%
            # 的劣化策略拿 0.5、stability=60% 的可信策略只拿 0.6 —— 几乎无差别，
            # 于是 Top1 长期被"⚠️ 样本外劣化"占据（实测 000415.SZ，
            # stability=40% 且 ratio=73.59 的比值爆炸条目）。
            # 改为叠加后：40% 劣化 → ×0.2，60% 可信 → ×0.6，差 3 倍。
            return float(wf["wf_return"] * (wf["stability"] / 100) * 0.5)
        return float(rec["sharpe"] * 0.1)  # 未验证的原始 Sharpe 严重打折

    # Top 名单的最低交易笔数，逐级放宽（见 generate_daily_report 的挑选逻辑）。
    # 单笔回测的 sharpe / win_rate 是纯噪声（win_rate 恒为 0% 或 100%），
    # 必须优先挑够笔数的；全池都不够时才逐级退让，并靠 low_sample 标记暴露。
    MIN_TRADES_TIERS: tuple[int, ...] = (5, 3, 1)

    # 数据完整度探测缓存: (timestamp, result)，1 小时内复用（见 _probe_data_freshness）
    _DATA_FRESHNESS_CACHE: tuple[float, dict] | None = None

    def __init__(self, stock_pool: list[str] = None):
        """
        Args:
            stock_pool: 默认回测股票池。不传则从数据库 daily_kline 表读取有K线数据的股票。
        """
        if stock_pool:
            self.stock_pool = [normalize_ts_code(c) for c in stock_pool]
        else:
            self.stock_pool = self._load_stock_pool_from_db()

    def _get_stock_name(self, ts_code: str) -> str:
        """查询单只股票名称（委托 shared.stock_name）"""
        from shared.stock_name import resolve_name

        name: str = resolve_name(ts_code)
        return name

    def _load_stock_pool_from_db(self) -> list[str]:
        """从数据库读取有足够K线数据且流动性好的股票作为回测池

        v2.2 优化: 从 3494 只全量 → 过滤成交量/换手率 → ~500 只（节省 85% 算力）
        规则: 近20日均成交额>=3亿 OR 换手率>=1% → 排除僵尸股/仙股
        ⚠️ 2026-07-29 加: 排除 ST/*ST 股(样本污染) + 科创板(68%/689, Claw禁买)
        """
        min_date = date.today() - timedelta(days=60)

        try:
            from models.database import get_db_session

            with get_db_session() as db:
                # 查询用于流动性筛选的基准交易日
                # 2026-09-03 修复: 直接用 MAX(trade_date) 会踩到"当日只导入了部分股票"的坑
                # —— 09-02 仅 44 行(前一日 4893 行)且 amount 未灌完, 导致 amount>=3亿 命中 0 只,
                #    静默降级到全量池(4579 只, 是正常池 ~1242 只的 3.7 倍)。
                # 改为取"最后一个数据完整的交易日"(当日记录数 >= 1000), 缺失时再退回 MAX。
                latest_date_row = db.execute(
                    text("""SELECT trade_date FROM daily_quote
                            GROUP BY trade_date
                            HAVING COUNT(*) >= 1000
                            ORDER BY trade_date DESC LIMIT 1""")
                ).fetchone()
                if not latest_date_row:
                    latest_date_row = db.execute(
                        text("SELECT MAX(trade_date) FROM daily_quote")
                    ).fetchone()
                latest_date = latest_date_row[0] if latest_date_row else None
                if latest_date:
                    logger.info(
                        f"[ReportService] 流动性筛选基准日 = {latest_date} (跳过未灌完的交易日)"
                    )

                if latest_date:
                    # 过滤流动性：当日总成交额 >= 3亿（粗略: 成交量*均价 / 1e8）
                    result = db.execute(
                        text("""SELECT ts_code FROM daily_quote
                           WHERE trade_date = :ld
                           AND volume > 0
                           AND amount >= 300000000
                           AND (ts_code LIKE '60%' OR ts_code LIKE '00%' OR ts_code LIKE '30%' OR ts_code LIKE '68%')
                           ORDER BY ts_code"""),
                        {"ld": latest_date},
                    )
                    codes = (
                        [normalize_ts_code(row[0]) for row in result.fetchall()] if result else []
                    )
                    if codes:
                        codes, st_ok = _exclude_banned(codes)
                        logger.info(
                            f"[ReportService] 从 daily_quote 加载 {len(codes)} 只流动性充足股票"
                            f"(已排科创{'/ST' if st_ok else '，⚠️ST未过滤'}): "
                            f"{codes[:5]}..."
                        )
                        return codes

                # 降级：无最新日数据时回退到原始查询
                result = db.execute(
                    text("""SELECT ts_code FROM daily_quote
                       WHERE trade_date >= :min_date
                       AND (ts_code LIKE '60%' OR ts_code LIKE '00%' OR ts_code LIKE '30%' OR ts_code LIKE '68%')
                       GROUP BY ts_code
                       HAVING COUNT(*) >= 20
                       ORDER BY ts_code"""),
                    {"min_date": min_date},
                )
                codes = [normalize_ts_code(row[0]) for row in result.fetchall()] if result else []
                if codes:
                    codes, st_ok = _exclude_banned(codes)
                    logger.info(
                        f"[ReportService] 从 daily_quote 加载 {len(codes)} 只回测股票"
                        f"（降级模式,已排科创{'/ST' if st_ok else '，⚠️ST未过滤'}）: "
                        f"{codes[:5]}..."
                    )
                    return codes
        except Exception as e:
            logger.warning(f"[ReportService] 从 daily_quote 加载失败: {e}")
        # 2) 回退 daily_kline (小样本池)
        try:
            from models.database import get_db_session

            with get_db_session() as db:
                result = db.execute(
                    text("""SELECT ts_code FROM daily_kline
                       WHERE trade_date >= :min_date
                       GROUP BY ts_code
                       HAVING COUNT(*) >= 20
                       ORDER BY ts_code"""),
                    {"min_date": min_date.isoformat()},
                )
                codes = [row[0] for row in result.fetchall()] if result else []
                if codes:
                    codes = [normalize_ts_code(c) for c in codes]
                    codes, st_ok = _exclude_banned(codes)
                    logger.info(
                        f"[ReportService] 从 daily_kline 加载 {len(codes)} 只回测股票"
                        f"(已排科创{'/ST' if st_ok else '，⚠️ST未过滤'}): {codes[:5]}..."
                    )
                    return codes
        except Exception as e:
            logger.warning(f"[ReportService] 从 daily_kline 加载失败: {e}")
        # 兜底
        logger.warning("[ReportService] 使用兜底股票池: 000001.SZ")
        return ["000001.SZ"]

    def generate_daily_report(
        self, target_date: str = None, strategies: list[str] = None
    ) -> dict[str, Any]:
        """
        生成日报：对每只股票运行所有策略回测，汇总排名

        Args:
            target_date: 回测截止日期，默认今天
            strategies: 策略列表，默认全部11个

        Returns:
            {
                "report_type": "daily",
                "report_date": "2026-06-09",
                "backtest_count": 25,
                "top_strategies": [...],
                "stock_ranking": [...],
                "summary": {...},
                "markdown": "...",
                "feishu_card": {...}
            }
        """
        target = target_date or date.today().isoformat()
        strategies = strategies or DEFAULT_STRATEGIES
        start_date = self._default_start_date("daily", target)

        all_results: list[dict[str, Any]] = []
        stock_ranking: list[dict[str, Any]] = []

        for ts_code in self.stock_pool:
            stock_results: list[dict[str, Any]] = []
            try:
                data = self._fetch_backtest_data(ts_code, start_date, target)
                if not data or len(data) < 60:
                    logger.warning(f"[Report] 数据不足 {ts_code}, 跳过")
                    continue

                from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine

                _REPORT_INITIAL_CASH = 30000.0
                engine = EnhancedBacktestEngine(
                    BacktestConfig(
                        initial_cash=_REPORT_INITIAL_CASH,
                        position_size=1.0,
                        max_positions=1,
                        enable_t1=True,  # ← 开 T+1，滤掉日内反转
                        enable_limit=True,  # ← 开涨跌停，涨停买不进
                    )
                )

                for strat in strategies:
                    try:
                        result = engine.run_single_stock(ts_code, strat, data)
                        final_value = round(_REPORT_INITIAL_CASH * (1 + result.total_return), 2)
                        entry = {
                            "ts_code": ts_code,
                            "strategy": strat,
                            "sharpe": round(result.sharpe_ratio, 3),
                            "total_return": round(result.total_return * 100, 2),
                            "max_drawdown": round(result.max_drawdown * 100, 2),
                            "win_rate": round(result.win_rate * 100, 1),
                            "total_trades": result.total_trades,
                            "final_value": final_value,
                        }
                        stock_results.append(entry)
                        all_results.append(entry)
                    except Exception as e:
                        logger.warning(f"[Report] 回测失败 {ts_code}/{strat}: {e}")

                # 股票排行：取该股票下最优夏普
                if stock_results:
                    best = max(stock_results, key=lambda x: x["sharpe"])
                    stock_ranking.append(
                        {
                            "ts_code": ts_code,
                            "best_strategy": best["strategy"],
                            "sharpe": best["sharpe"],
                            "return": best["total_return"],
                            "drawdown": best["max_drawdown"],
                        }
                    )

            except Exception as e:
                logger.error(f"[Report] 数据处理异常 {ts_code}: {e}")

        # 策略排名（初排 — 用于筛选进入 Walk-Forward 的 Top N）
        # ⚠️ 2026-09-04 修复：原实现 `sorted(all_results, key=sharpe)[:50]`，
        # 而 raw sharpe 最高的恰恰是 total_trades=1 的运气单（单笔 sharpe 可达 46，
        # 多笔的只有 4~5）→ WF 那 30 个名额**全被噪声占满**，
        # 真正够格的候选一个都没验证到（Top5 因此全标「⚪ 未验证」，wf_passed 长期 2~5）。
        initial_top = self._select_wf_candidates(all_results, limit=50)

        # ── Walk-Forward 验证（对初排 Top 30 跑滚动窗口，防过拟合）──
        wf_validated: dict[str, dict] = {}  # key: "ts_code|strategy"
        wf_candidates = initial_top[:30]

        from services.param_grids import get_daily_param_grid

        logger.info(f"[Report] Walk-Forward 验证 Top {len(wf_candidates)} 个候选")
        for entry in wf_candidates:
            ts_code = str(entry["ts_code"])
            strat = str(entry["strategy"])
            try:
                wf = engine.walk_forward(
                    ts_code,
                    strat,
                    train_days=120,  # 半年训练（减少窗口计算量）
                    test_days=90,  # 08-04 方案A：一个半月→一季度(30天窗口信号稀疏致stability虚低,90天提升窗口内信号数)
                    step_days=60,  # 步长≈3个月（≥测试窗口,数据383天可支撑2-3窗口）
                    param_grid=get_daily_param_grid(strat),  # 精简网格（1-4 combos）
                )
                if wf.get("error"):
                    continue
                num_w = wf.get("num_windows", 0)
                if num_w < 2:
                    continue  # 数据不够走至少 2 个窗口

                # 稳定性：测试期盈利窗口占比
                profitable = sum(1 for w in wf["windows"] if w["test_return"] > 0)
                stability = profitable / num_w

                # 过拟合比率：测试夏普 / 训练夏普（均值）。
                # 1.0 = 样本外完全保持，负值 = 方向反转。判可信的门槛见
                # WF_MIN_OVERFIT_RATIO（0.5，即样本外至少保留一半表现）。
                of_ratio = wf.get("overfit_ratio", 0)

                wf_validated[f"{ts_code}|{strat}"] = {
                    "wf_return": round(wf["overall_test_return"] * 100, 2),
                    "stability": round(stability * 100, 1),
                    "overfit_ratio": round(of_ratio, 2),
                    "windows": num_w,
                }
            except Exception as e:
                logger.debug(f"[Report] Walk-Forward 失败 {ts_code}/{strat}: {e}")

        # 最终排名：Walk-Forward 验证过的优先（加权 = wf_return × stability），未验证的降权
        # ⚠️ 过拟合硬排除：样本外方向反转（overfit_ratio < 0）的直接剔除出排名。
        # 2026-09-04 修正判据：原为 `overfit_ratio > 0.2`，方向是反的 ——
        # 它剔除的是样本外保留最好的那批，却留下方向反转的。详见 _is_overfit。
        # 注意：以下统一用 rec 而非 e —— 本函数上文有 `except Exception as e`，
        # Python 在 except 块结束时会 del e，复用同名会让静态检查判为
        # "读取已删除变量"，也容易在重构时踩到真实的 NameError。
        def _is_overfit(rec: dict) -> bool:
            wf = wf_validated.get(f"{rec['ts_code']}|{rec['strategy']}")
            # ⚠️ 2026-09-04 修复：原判据 `ratio > 0.2` 是反的 —— 它把 ratio=0.9
            # （样本外保留了 90%，好）排除，却留下 ratio=-59（方向反转，坏）。
            # 改为只硬排除"样本外方向反转"的（ratio < 0）。
            #
            # 为什么不用 _wf_is_trustworthy（一刀切排除所有不达标的）：
            # 那会在"没有一条达标"的日子里把 30 条已验证的全排除，排名被未验证的
            # 单笔噪声填满 —— 与修复目的背道而驰。验证过但表现平平的
            # （0 <= ratio < 0.5）留在池里，仍优于 1 笔噪声。
            if not wf:  # 显式收窄：mypy 不会从 `bool(wf) and ...` 推出非 None
                return False
            return bool(wf.get("overfit_ratio", 0) < 0)  # .get() 是 Any → 包 bool 才符合返回类型

        # 过滤掉过拟合策略（审计 🟡2 修复：stock_ranking 也统一过滤，与注释一致）
        _rankable = [rec for rec in all_results if not _is_overfit(rec)]
        # 2026-09-04：排名口径提到类方法 _wf_rank_score 上（原先是这里的嵌套闭包，
        # 无法单测，两次判据反转都栽在测试盲区里）。语义不变。
        _ranked_all = sorted(
            _rankable, key=lambda r: self._wf_rank_score(r, wf_validated), reverse=True
        )

        # 2026-09-04 修复：Top 名单必须在**全量**候选里挑交易笔数够的，
        # 不能只从排名前 10 里筛 —— 够格的候选常排在几十名开外，原逻辑下
        # Top5 恒为单笔噪声（08-31~09-04 连续 5 天，trades 全为 1、win_rate 全 100%）。
        # 排序口径统一走 _rank_trades_first（笔数档位优先、档内比 rank_score），
        # 保证高档候选既排得进、也不会在放宽时被低档挤掉。
        top_strategies = self._rank_trades_first(
            _ranked_all, lambda r: self._wf_rank_score(r, wf_validated), 10
        )

        # stock_ranking 也按 WF 验证重排（使用 _rankable，过拟合已排除）
        stock_best: dict[str, dict] = {}
        for rec in _rankable:
            key = rec["ts_code"]
            if key not in stock_best or self._wf_rank_score(
                rec, wf_validated
            ) > self._wf_rank_score(stock_best[key], wf_validated):
                stock_best[key] = rec
        stock_ranking = []
        for ts_code, rec in sorted(
            stock_best.items(),
            key=lambda x: self._wf_rank_score(x[1], wf_validated),
            reverse=True,
        ):
            stock_ranking.append(
                {
                    "ts_code": ts_code,
                    "best_strategy": rec["strategy"],
                    "sharpe": rec["sharpe"],
                    "return": rec["total_return"],
                    "drawdown": rec["max_drawdown"],
                    "wf_return": wf_validated.get(f"{ts_code}|{rec['strategy']}", {}).get(
                        "wf_return"
                    ),
                    "stability": wf_validated.get(f"{ts_code}|{rec['strategy']}", {}).get(
                        "stability"
                    ),
                    "overfit_ratio": wf_validated.get(f"{ts_code}|{rec['strategy']}", {}).get(
                        "overfit_ratio"
                    ),
                }
            )

        # 汇总摘要
        wf_passed = len([w for w in wf_validated.values() if self._wf_is_trustworthy(w)])
        summary = {
            "total_backtests": len(all_results),
            "avg_sharpe": round(
                sum(r["sharpe"] for r in all_results) / max(len(all_results), 1), 3
            ),
            "avg_return": round(
                sum(r["total_return"] for r in all_results) / max(len(all_results), 1), 2
            ),
            "avg_win_rate": round(
                sum(r["win_rate"] for r in all_results) / max(len(all_results), 1), 1
            ),
            "positive_strategies": sum(1 for r in all_results if r["total_return"] > 0),
            "best_sharpe": top_strategies[0]["sharpe"] if top_strategies else 0,
            "wf_candidates": len(wf_candidates),
            "wf_passed": wf_passed,
        }

        return {
            "report_type": "daily",
            "report_date": target,
            "backtest_count": len(all_results),
            "top_strategies": top_strategies,
            "stock_ranking": stock_ranking,
            "summary": summary,
            "wf_validated": wf_validated,
            "markdown": self._format_markdown(
                summary, top_strategies, stock_ranking, wf_validated, "日报"
            ),
            "feishu_card": self._format_feishu_card(
                summary, top_strategies, stock_ranking, wf_validated, "日报"
            ),
        }

    def generate_weekly_report(
        self, end_date: str = None, strategies: list[str] = None
    ) -> dict[str, Any]:
        """生成周报：汇总本周回测 + 策略排名 + 风险事件"""
        end = end_date or date.today().isoformat()
        start = (date.fromisoformat(end) - timedelta(days=7)).isoformat()
        strategies = strategies or DEFAULT_STRATEGIES

        # 用本周最后一天作为回测基准，标记为周报
        report = self.generate_daily_report(end, strategies)
        report["report_type"] = "weekly"
        report["report_date"] = f"{start} ~ {end}"
        report["markdown"] = self._format_markdown(
            report["summary"],
            report["top_strategies"],
            report["stock_ranking"],
            report.get("wf_validated", {}),
            "周报",
        )
        report["feishu_card"] = self._format_feishu_card(
            report["summary"],
            report["top_strategies"],
            report["stock_ranking"],
            report.get("wf_validated", {}),
            "周报",
        )
        return report

    def generate_monthly_report(
        self, year: int = None, month: int = None, strategies: list[str] = None
    ) -> dict[str, Any]:
        """生成月报：月回报率排名 + 参数优化趋势"""
        today = date.today()
        year = year or today.year
        month = month or today.month
        end_str = date(year, month, min(today.day, 28)).isoformat()
        start_str = date(year, month, 1).isoformat()
        strategies = strategies or DEFAULT_STRATEGIES

        report = self.generate_daily_report(end_str, strategies)
        report["report_type"] = "monthly"
        report["report_date"] = f"{year}-{month:02d}"
        report["markdown"] = self._format_markdown(
            report["summary"],
            report["top_strategies"],
            report["stock_ranking"],
            report.get("wf_validated", {}),
            "月报",
        )
        report["feishu_card"] = self._format_feishu_card(
            report["summary"],
            report["top_strategies"],
            report["stock_ranking"],
            report.get("wf_validated", {}),
            "月报",
        )
        return report

    # ========== 数据获取 ==========

    def _fetch_backtest_data(self, ts_code: str, start: str, end: str) -> list[dict]:
        """获取真实回测K线数据（腾讯财经 → 东方财富 → DataService）"""
        try:
            from services.data_fetcher import fetch_kline_eastmoney, fetch_kline_tencent

            data = fetch_kline_tencent(ts_code, start, end)
            if data:
                result: list[dict] = data
                return result

            data = fetch_kline_eastmoney(ts_code, start, end)
            if data:
                result = data
                return result
        except Exception as e:
            logger.warning(f"[Report] 公开行情源获取失败 {ts_code}: {e}")

        try:
            from core.config import settings

            from services.data_service import DataService

            ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
            if hasattr(ds, "get_stock_daily_quote"):
                data = ds.get_stock_daily_quote(ts_code, start, end)
                return data or []
        except Exception as e:
            logger.warning(f"[Report] DataService获取失败 {ts_code}: {e}")

        logger.warning(f"[Report] 无真实行情数据 {ts_code}")
        return []

    async def generate_daily_review(self, target_date: str = None) -> dict:
        """
        生成每日 AI 复盘分析，供前端 review-analysis 页面消费。
        尝试基于真实回测数据生成摘要；失败则返回占位结构。
        """
        from datetime import date as date_cls
        from datetime import timedelta

        today = target_date or date_cls.today().isoformat()
        end = date_cls.fromisoformat(today)
        start = (end - timedelta(days=30)).isoformat()

        try:
            report = self.generate_daily_report(today)
            top = report.get("top_strategies", [])
            summary = report.get("summary", {})
            return {
                "review_date": today,
                "market_overview": f"基于 {len(self.stock_pool)} 支股票、{summary.get('total_backtests', 0)} 次回测的分析摘要。",
                "key_observations": report.get("markdown", "").split("\n")[:10],
                "risk_warnings": "请注意：量化策略存在历史不代表未来的风险，请结合实际市场情况操作。",
                "strategy_performance": {
                    "months": [today[:7]],
                    "series": [
                        {
                            "name": s.get("strategy", "策略"),
                            "data": [round(s.get("avg_return", 0), 4)],
                        }
                        for s in top[:3]
                    ],
                },
                "top_strategy": top[0] if top else None,
                "generated_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.warning(f"[Review] 复盘数据生成失败 ({today}): {e}")
            raise

    def _default_start_date(self, report_type: str, end_date: str) -> str:
        """根据报告类型计算回测起始日期

        ⚠️ 2026-09-04 调整：三档窗口全面加长（90/180/365 → 730/730/1095）。

        原值太短，短到**统计上不可能得出结论**。实测（150 只 × 11 策略 = 1650 次回测）：

        | 窗口  | ≥3 笔 | ≥5 笔 | ≥8 笔 |
        |-------|-------|-------|-------|
        | 90 天 | 1.5%  | 0.0%  | 0.0%  |
        | 365 天| 38.3% | 9.9%  | 0.4%  |
        | 730 天| 58.1% | 27.0% | 5.3%  |

        90 天 ≈ 61 个交易日，慢策略（ma-cross 5/20、macd、kdj）在 3 个月里只产生 0~2 个
        信号 → **没有任何一次回测能达到 5 笔** → generate_daily_brief 里 `min_trades>=5`
        的过滤**必然落空**，只能保底退回单笔结果（total_trades=1、win_rate=100%、
        sharpe 20~60 的纯噪声）。这就是连续 5 天（08-31~09-04）Top5 全是单笔假象的根因
        —— 不是排序问题，是**样本里根本没有够格的候选**。

        取 730 天后约 27% 的回测达到 ≥5 笔，全池约 3700 条合格候选，Top5 才真正有意义。
        代价：150 只从 2.2s → 3.0s，全量约 13s → 40s 量级，可接受。

        注：这是**滚动窗口**（报告的 report_date 仍是当天），不是把日报改成年报。
        """
        end = date.fromisoformat(end_date)
        if report_type == "daily":
            return (end - timedelta(days=self.WINDOW_DAYS["daily"])).isoformat()
        if report_type == "weekly":
            return (end - timedelta(days=self.WINDOW_DAYS["weekly"])).isoformat()
        return (end - timedelta(days=self.WINDOW_DAYS["monthly"])).isoformat()

    # ========== 格式化输出 ==========

    def _format_markdown(
        self,
        summary: dict,
        top_strategies: list[dict],
        stock_ranking: list[dict],
        wf_validated: dict,
        report_label: str,
    ) -> str:
        """生成 Markdown 格式报告"""
        lines = [
            f"# 🔬 QuantTradingSystem {report_label}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 📊 绩效摘要",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 回测总数 | {summary['total_backtests']} |",
            f"| 平均夏普 | {summary['avg_sharpe']} |",
            f"| 平均收益率 | {summary['avg_return']}% |",
            f"| 平均胜率 | {summary['avg_win_rate']}% |",
            f"| 正收益策略 | {summary['positive_strategies']}/{summary['total_backtests']} |",
            "",
            "## 🏆 策略排名 Top5",
            "| 排名 | 策略 | 标的 | 夏普 | 收益率 | 最大回撤 | 胜率 |",
            "|------|------|------|------|--------|----------|------|",
        ]

        for i, s in enumerate(top_strategies[:5], 1):
            return_sign = "🔴" if s["total_return"] > 0 else "🟢"
            name = self._get_stock_name(s["ts_code"])
            label = f"{name}({s['ts_code']})" if name else s["ts_code"]
            lines.append(
                f"| {i} | {s['strategy']} | {label} | "
                f"{s['sharpe']} | {return_sign} {s['total_return']}% | "
                f"{s['max_drawdown']}% | {s['win_rate']}% |"
            )

        if stock_ranking:
            lines.append("")
            lines.append("## 📈 股票综合排名")
            lines.append("| 排名 | 标的 | 最优策略 | 夏普 | 收益率 |")
            lines.append("|------|------|----------|------|--------|")
            for i, s in enumerate(stock_ranking[:5], 1):
                name = self._get_stock_name(s["ts_code"])
                label = f"{name}({s['ts_code']})" if name else s["ts_code"]
                lines.append(
                    f"| {i} | {label} | {s['best_strategy']} | {s['sharpe']} | {s['return']}% |"
                )

        lines.append("")
        lines.append("---")
        lines.append("⚠️ 仅供参考，不构成投资建议 · 由 QuantTradingSystem 自动生成")

        return "\n".join(lines)

    def _format_feishu_card(
        self,
        summary: dict,
        top_strategies: list[dict],
        stock_ranking: list[dict],
        wf_validated: dict,
        report_label: str,
    ) -> dict[str, Any]:
        """生成飞书交互式卡片格式"""
        # 构建策略排名文本（含股票名称 + Walk-Forward 验证标记）
        rank_lines = []
        for i, s in enumerate(top_strategies[:5], 1):
            emoji = "🔴" if s["total_return"] > 0 else "🟢"
            name = self._get_stock_name(s["ts_code"])
            label = f"{name}({s['ts_code']})" if name else s["ts_code"]
            # Walk-Forward 标记
            wf_tag = ""
            wf_key = f"{s['ts_code']}|{s['strategy']}"
            if wf_validated.get(wf_key):
                wf = wf_validated[wf_key]
                wf_tag = f" | WF稳{wf['stability']}%"
                # 2026-09-04 修复：原为 `stability < 50 or overfit_ratio < 0.2`，
                # 与 wf_passed 的 `<= 0.2` 判"通过"自相矛盾（同一条既过拟合又通过）。
                # 统一走 _wf_is_trustworthy。
                if not self._wf_is_trustworthy(wf):
                    wf_tag += " ⚠️样本外劣化"
            elif len(s.get("ts_code", "")) > 0:
                wf_tag = " | ⚪未验证"
            rank_lines.append(
                f"{i}. **{s['strategy']}** @ {label} | "
                f"夏普 {s['sharpe']} | {emoji} {s['total_return']}% | 胜率 {s['win_rate']}%{wf_tag}"
            )

        # 构建股票排名文本（含 Walk-Forward 验证）
        stock_lines = []
        ranked_stocks = stock_ranking[:5]
        for s in ranked_stocks:
            name = self._get_stock_name(s["ts_code"])
            label = f"{name}({s['ts_code']})" if name else s["ts_code"]
            wf_tag = ""
            if s.get("stability") is not None and s.get("stability", 0) >= 50:
                wf_tag = f" WF稳{s['stability']}%"
            elif s.get("stability") is not None:
                wf_tag = f" ⚠️样本外不稳(稳{s['stability']}%)"
            stock_lines.append(f"• {label} → **{s['best_strategy']}** (夏普 {s['sharpe']}{wf_tag})")

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"🔬 QuantTradingSystem {report_label}",
                    },
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                        f"**回测总数**: {summary['total_backtests']} | "
                        f"**平均夏普**: {summary['avg_sharpe']} | "
                        f"**正收益占比**: {summary['positive_strategies']}/{summary['total_backtests']}\n"
                        f"**Walk-Forward 验证**: Top {summary.get('wf_candidates', 0)} 候选，通过 {summary.get('wf_passed', 0)} 个",
                    },
                    {"tag": "hr"},
                    {"tag": "markdown", "content": "**🏆 策略 Top5**\n" + "\n".join(rank_lines)},
                    {"tag": "hr"},
                    {
                        "tag": "markdown",
                        "content": "**📈 股票综合排名**\n" + "\n".join(stock_lines)
                        if stock_lines
                        else "暂无排名数据",
                    },
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": "⚠️ 仅供学习研究，不构成投资建议 · 由 QuantTradingSystem 自动生成",
                            }
                        ],
                    },
                ],
            },
        }
        return card

    @classmethod
    def _rank_trades_first(cls, records: list[dict], score_key, limit: int) -> list[dict]:
        """排序：笔数档位优先，档内按 score_key 降序，取前 limit 条。

        为什么必须"档位优先"而不是"按分排序后过滤"：
        分数（sharpe / rank_score）与交易笔数**不同量纲可比** —— 单笔回测的 sharpe
        没有分母约束，一笔 +20% 就能算出 46；8 笔、胜率 37.5% 的真实策略只有 4.5。
        按分数硬排必然让噪声赢。所以先把候选按笔数分档，只在**同档内部**比分数。

        为什么不能"逐档过滤、该档不够就整档丢弃"：
        放宽到下一档时反而会把上一档够格的候选挤掉（实测 10 条够格 + 100 条噪声时，
        退到最后一档会退化成纯分数排序，10 条够格的全丢）。
        故用复合键 (档位, -分数) 一次排序，天然保证高档在前且不会被挤掉。
        """
        tiers = sorted(cls.MIN_TRADES_TIERS, reverse=True)  # 门槛降序 [5, 3, 1]

        def _sort_key(rec: dict) -> tuple[int, float]:
            n = rec.get("total_trades", 0)
            tier = len(tiers)
            for idx, t in enumerate(tiers):
                if n >= t:
                    tier = idx  # 0 = 最高档
                    break
            return (tier, -float(score_key(rec)))

        return sorted(records, key=_sort_key)[:limit]

    @classmethod
    def _select_wf_candidates(cls, all_results: list[dict], limit: int = 50) -> list[dict]:
        """挑选进入 Walk-Forward 的候选：先按交易笔数分档，档内按 sharpe 排。

        WF 名额有限（30 个），必须花在**统计上有意义**的候选上。
        原实现 `sorted(all_results, key=sharpe)[:50]`：而 raw sharpe 最高的恰恰是
        total_trades=1 的运气单 → 30 个名额**全被噪声占满**，真正够格的候选一个都没
        验证到（Top5 因此全标「⚪ 未验证」，wf_passed 长期只有 2~5）。
        """
        return cls._rank_trades_first(all_results, lambda r: r.get("sharpe", 0), limit)

    @staticmethod
    def _probe_data_freshness(min_complete_rows: int = 1000) -> dict[str, Any]:
        """探测 daily_quote 的数据完整度，供 brief 标注真实数据截止日。

        背景(2026-09-04): 灌库任务中断时每天只写 44 行(按代码升序, 死在同一处),
        而 MAX(trade_date) 仍会返回一个"看起来最新"的日期 → 所有新鲜度检查都被骗过。
        因此判"完整"必须用行数门槛, 与 _load_stock_pool 的基准日口径保持一致。

        Returns:
            {
              "data_as_of": str|None,          # 最后一个完整交易日
              "data_stale": bool,              # 是否有滞后(存在不完整/缺失的会话)
              "incomplete_sessions": list[str], # 晚于 data_as_of 的不完整交易日(升序)
            }
        """
        from models.database import get_db_session

        # 进程内缓存 1 小时, 避免每次调用都扫全表
        _now_ts = _time.time()
        _cache = ReportService._DATA_FRESHNESS_CACHE
        if _cache and _now_ts - _cache[0] < 3600:
            return _cache[1]

        result: dict[str, Any] = {
            "data_as_of": None,
            "data_stale": False,
            "incomplete_sessions": [],
        }
        try:
            with get_db_session() as db:
                rows = db.execute(
                    text("""SELECT trade_date, COUNT(*) FROM daily_quote
                            GROUP BY trade_date ORDER BY trade_date DESC LIMIT 30""")
                ).fetchall()
            if not rows:
                return result

            last_complete = next((d for d, c in rows if c >= min_complete_rows), None)
            # 一个完整交易日都没有 → data_as_of 保持 None，绝不能拿残缺日冒充截止日
            if last_complete is not None:
                result["data_as_of"] = str(last_complete)
                incomplete = [str(d) for d, _ in rows if d > last_complete]
            else:
                incomplete = [str(d) for d, _ in rows]
            result["incomplete_sessions"] = sorted(incomplete)
            result["data_stale"] = bool(result["incomplete_sessions"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ReportService] 数据完整度探测失败: {e}")

        ReportService._DATA_FRESHNESS_CACHE = (_now_ts, result)
        return result

    def generate_daily_brief(
        self, output_path: str = "/tmp/qts_daily_brief.json"
    ) -> dict[str, Any]:
        """生成日报摘要 JSON，供晚报 / 外部系统消费 — 含 WF 验证标记

        与 generate_daily_report() 的唯一区别：跑完整日报后提取 Top 5 + 汇总，
        写入 JSON 文件，返回同样结构。避免晚报重复跑 33825 次回测。

        Args:
            output_path: 输出 JSON 文件路径，默认 /tmp/qts_daily_brief.json

        Returns:
            {"status": "ok"/"error", "path": ..., "brief": {...}}
        """
        import json as _json
        from datetime import date as _date
        from datetime import datetime as _dt

        try:
            target = _date.today().isoformat()
            report = self.generate_daily_report(target)

            top5 = report.get("top_strategies", [])[:5]
            wf = report.get("wf_validated", {})
            summary = report.get("summary", {})

            # 2026-09-04 加: 数据时效标注。
            # daily_quote 灌库自 09-02 起中断(09-02/09-03 各仅 44 行, 09-04 无数据),
            # 而 data_fetcher 新鲜度检查只看 MAX(trade_date)=09-03 就判"可用",
            # 导致 report_date=09-04 的回测实际跑在截止 09-01 的数据上, 且全程静默。
            # 这里把"最后一个数据完整的交易日"写进 brief, 让下游无法误报为当日结论。
            try:
                _data_meta = self._probe_data_freshness()
                summary["data_as_of"] = _data_meta["data_as_of"]
                summary["data_stale"] = _data_meta["data_stale"]
                summary["incomplete_sessions"] = _data_meta["incomplete_sessions"]
                if _data_meta["data_stale"]:
                    logger.warning(
                        f"[Brief] ⚠️ 数据滞后: 回测数据截至 {_data_meta['data_as_of']}, "
                        f"report_date={target}; 不完整交易日={_data_meta['incomplete_sessions']}"
                    )
            except Exception as _e:  # noqa: BLE001
                logger.warning(f"[Brief] 数据时效探测失败(不影响出报): {_e}")

            # Q2(08-04): 最少交易笔数过滤 — 防单笔/双笔 win=100% 虚高策略被晚报/外部系统引用
            # 规则: 首选 ≥5 笔; 不足 3 条时降级 ≥3 笔; 仍空则保底原 top5（低样本标记延后到 WF 标注之后，防覆盖）
            _MIN_TRADES = 5
            _MIN_TRADES_FALLBACK = 3
            top5 = [e for e in top5 if e.get("total_trades", 0) >= _MIN_TRADES]
            if len(top5) < 3:
                top5 = [
                    e
                    for e in report.get("top_strategies", [])[:5]
                    if e.get("total_trades", 0) >= _MIN_TRADES_FALLBACK
                ]
            low_sample = len(top5) < 5
            _fallback_low_sample = False
            if not top5:
                top5 = report.get("top_strategies", [])[:5]
                _fallback_low_sample = True

            # Top 5 每条附 WF 稳定性标记
            for entry in top5:
                key = f"{entry['ts_code']}|{entry['strategy']}"
                wf_data = wf.get(key, {})
                entry["wf_stability"] = wf_data.get("stability")
                entry["wf_overfit_ratio"] = wf_data.get("overfit_ratio")
                # 判可信的唯一口径（2026-09-04 修复：原为 `ratio > 0.2`，
                # 与 wf_passed 的 `<= 0.2` 正好相反，同一份数据两种结论）
                if self._wf_is_trustworthy(wf_data):
                    entry["wf_label"] = "✅ 可信"
                elif wf_data.get("stability") is not None:
                    entry["wf_label"] = "⚠️ 样本外劣化"
                else:
                    entry["wf_label"] = "⚪ 未验证"
                # 板块标注（2026-09-04）：创业板规则冲突的解法——不过滤、只标注，
                # 让实盘口径（USER.md 仅主板/中小板）与模拟盘口径
                # （sim_trade.py 07-29 已放开创业板）各自消费，互不毁伤。
                entry["board"] = classify_board(entry["ts_code"])

            # 低样本保底标记（必须在 WF 标注之后，否则被覆盖）
            if _fallback_low_sample:
                for entry in top5:
                    entry["wf_label"] = "⚠️ 低样本"

            # 极端市场日检测：WF 全部失败且 OF 普遍为负 → 不是策略问题，是市场反转
            of_values = [
                e["wf_overfit_ratio"] for e in top5 if e.get("wf_overfit_ratio") is not None
            ]
            extreme_day = (
                summary.get("wf_passed", 0) == 0
                and len(of_values) >= 3
                and all(v < 0 for v in of_values)
            )
            if extreme_day:
                for entry in top5:
                    # ⚠️ 2026-09-04 修复：原比对 `"⚠️ 过拟合"`，但该标签已改名为
                    # `"⚠️ 样本外劣化"` → 这个分支变成了永不触发的死代码。
                    # 标签改名时必须同步改这里（已加守卫测试）。
                    if entry.get("wf_label") == "⚠️ 样本外劣化":
                        entry["wf_label"] = "🌪️ 极端日"

            # 非（主板/中小板）条数：实盘口径不能买，但模拟盘可以，故只统计不剔除
            _non_mainboard = [e["ts_code"] for e in top5 if e.get("board") not in TRADABLE_BOARDS]
            if _non_mainboard:
                summary["top5_non_mainboard"] = _non_mainboard
                logger.warning(
                    f"[Brief] ⚠️ Top5 含非主板标的 {len(_non_mainboard)}/{len(top5)}: "
                    f"{_non_mainboard}（实盘口径 USER.md 仅主板/中小板，模拟盘可用）"
                )

            brief = {
                "generated_at": _dt.now().isoformat(),
                "report_date": target,
                "summary": summary,
                "top5": top5,
                "flags": {
                    "extreme_day": extreme_day,
                    "low_sample": low_sample,
                    "min_trades_applied": True,
                },
            }

            # 2026-08-12: 原子写(tmp+os.replace), 防写一半崩溃留残文件(跨项目共享文件, 巡检中枢会校验)
            import os as _os

            _tmp = output_path + ".tmp"
            with open(_tmp, "w", encoding="utf-8") as f:
                _json.dump(brief, f, ensure_ascii=False, indent=2, default=str)
            _os.replace(_tmp, output_path)

            # 2026-08-13 打通: brief 同步落库 PG(qts_daily_brief), Claw 服务直连读取,
            # 不再依赖 /tmp 文件桥接。落库失败仅告警不阻断(文件仍是兜底)。
            try:
                from models.database import get_db_session
                from sqlalchemy import text as _text

                with get_db_session() as db:
                    db.execute(
                        _text(
                            """
                            INSERT INTO qts_daily_brief
                                (report_date, brief, created_at)
                            VALUES (:report_date, :brief, NOW())
                            ON CONFLICT (report_date)
                            DO UPDATE SET brief = EXCLUDED.brief, created_at = NOW()
                            """
                        ),
                        {
                            "report_date": target,
                            "brief": _json.dumps(brief, ensure_ascii=False, default=str),
                        },
                    )
                    db.commit()  # 2026-08-13 hotfix: get_db_session 不自动 commit，缺此句 INSERT 被回滚
                logger.info(f"[Brief] 已落库 PG qts_daily_brief ({target})")
            except Exception as _e:  # noqa: BLE001
                logger.warning(f"[Brief] PG 落库失败(文件仍有效): {_e}")

            logger.info(
                f"[Brief] 日报摘要已写入 {output_path} "
                f"(回测{summary.get('total_backtests', 0)}次, "
                f"Top1={top5[0]['strategy'] if top5 else 'N/A'})"
            )

            return {"status": "ok", "path": output_path, "brief": brief}
        except Exception as e:
            logger.error(f"[Brief] 生成失败: {e}")
            return {"status": "error", "path": output_path, "error": str(e)}


# 全局单例
report_service = ReportService()
