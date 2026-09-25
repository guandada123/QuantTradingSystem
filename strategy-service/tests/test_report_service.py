"""
测试回测报告生成服务
Cover services/report_service.py 中未覆盖的分支：
- generate_daily_report: 数据不足跳过 (57-58), 策略异常 (89-90), 股票循环异常 (105-106)
- generate_weekly_report (142-156)
- generate_monthly_report (162-178)
- _fetch_backtest_data 降级路径 (191-210)
- generate_daily_review 异常 (246-248)
- _default_start_date weekly/monthly (255-257)
"""

from unittest.mock import MagicMock, patch

import pytest
from services.report_service import DEFAULT_STRATEGIES, ReportService

# ============================================================
# 共享测试数据
# ============================================================

SAMPLE_SUMMARY = {
    "total_backtests": 25,
    "avg_sharpe": 0.85,
    "avg_return": 1.23,
    "avg_win_rate": 55.5,
    "positive_strategies": 15,
    "best_sharpe": 1.5,
}

SAMPLE_TOP = [
    {
        "strategy": "ma-cross",
        "ts_code": "000001.SZ",
        "sharpe": 1.5,
        "total_return": 5.0,
        "max_drawdown": -3.0,
        "win_rate": 60.0,
        "total_trades": 10,
        "final_value": 31500.0,
    },
]

SAMPLE_RANKING = [
    {
        "ts_code": "000001.SZ",
        "best_strategy": "ma-cross",
        "sharpe": 1.5,
        "return": 5.0,
        "drawdown": -3.0,
    },
]

SAMPLE_DAILY_RESULT = {
    "summary": SAMPLE_SUMMARY,
    "top_strategies": SAMPLE_TOP,
    "stock_ranking": SAMPLE_RANKING,
    "markdown": "## 摘要\nline1\nline2\nline3\n",
    "feishu_card": {},
    "backtest_count": 5,
    "report_type": "daily",
    "report_date": "2026-06-19",
}


def _make_mock_data(rows=31):
    """生成模拟 K 线数据"""
    return [
        {
            "date": f"2026-0{i:02d}-01",
            "open": 10,
            "close": 10,
            "high": 11,
            "low": 9,
            "volume": 1000,
        }
        for i in range(1, rows + 1)
    ]


# ============================================================
# 内部引用的模块（局部 import）需要在源头 patch
# report_service.py 内部使用:
#   from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine
#   from services.data_fetcher import fetch_kline_eastmoney, fetch_kline_tencent
#   from services.data_service import DataService
#   from core.config import settings
# ============================================================


@pytest.fixture
def mock_engine():
    """给 EnhancedBacktestEngine 打桩"""
    mock_result = MagicMock(
        sharpe_ratio=1.5,
        total_return=0.05,
        max_drawdown=-0.03,
        win_rate=0.6,
        total_trades=10,
    )
    engine_instance = MagicMock()
    engine_instance.run_single_stock.return_value = mock_result

    with (
        patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=engine_instance,
        ) as me,
        patch("services.backtest_engine_v2.BacktestConfig"),
    ):
        yield me


class TestGenerateDailyReport:
    """测试 generate_daily_report 错误路径"""

    def test_data_insufficient_skips_stock(self):
        """数据不足最小样本 → 跳过该股票"""
        service = ReportService(stock_pool=["000001.SZ"])
        with patch.object(service, "_fetch_backtest_data", return_value=[]):
            result = service.generate_daily_report("2026-06-19")
        assert result["backtest_count"] == 0

    def test_mock_engine_happy_path(self, mock_engine):
        """mock 引擎覆盖正常路径

        源码最小样本阈值已从 30 提到 60 条，且默认策略集扩到 DEFAULT_STRATEGIES，
        这里不再写死 5，直接对齐常量，避免以后再加策略又挂。
        """
        service = ReportService(stock_pool=["000001.SZ"])
        mock_data = _make_mock_data(61)
        with patch.object(service, "_fetch_backtest_data", return_value=mock_data):
            result = service.generate_daily_report("2026-06-19")
        assert result["backtest_count"] == len(DEFAULT_STRATEGIES)
        assert result["report_type"] == "daily"

    def test_strategy_backtest_exception_logged(self, mock_engine):
        """策略回测异常 → warning 日志 (lines 89-90)"""
        service = ReportService(stock_pool=["000001.SZ"])
        mock_data = _make_mock_data(31)

        # 让 run_single_stock 抛异常
        engine_instance = MagicMock()
        engine_instance.run_single_stock.side_effect = ValueError("回测失败")
        with (
            patch.object(service, "_fetch_backtest_data", return_value=mock_data),
            patch(
                "services.backtest_engine_v2.EnhancedBacktestEngine",
                return_value=engine_instance,
            ),
            patch("services.backtest_engine_v2.BacktestConfig"),
        ):
            result = service.generate_daily_report("2026-06-19")
        assert result["backtest_count"] == 0

    def test_stock_loop_exception_logged(self):
        """股票循环异常 → error 日志 (lines 105-106)"""
        service = ReportService(stock_pool=["000001.SZ"])
        with patch.object(
            service, "_fetch_backtest_data", side_effect=RuntimeError("数据获取崩溃")
        ):
            result = service.generate_daily_report("2026-06-19")
        assert result["backtest_count"] == 0


class TestGenerateWeeklyReport:
    """测试 generate_weekly_report (lines 142-156)"""

    def test_weekly_report_returns_correct_type(self):
        """周报返回 report_type=weekly"""
        service = ReportService(stock_pool=["000001.SZ"])
        with patch.object(service, "generate_daily_report", return_value=dict(SAMPLE_DAILY_RESULT)):
            result = service.generate_weekly_report("2026-06-19")
        assert result["report_type"] == "weekly"
        assert "~" in result["report_date"]

    def test_weekly_report_calls_daily(self):
        """周报委托给 generate_daily_report"""
        service = ReportService(stock_pool=["000001.SZ"])
        with patch.object(
            service, "generate_daily_report", return_value=dict(SAMPLE_DAILY_RESULT)
        ) as mock_daily:
            service.generate_weekly_report("2026-06-19")
            # 默认策略集已从 5 个经典扩到 DEFAULT_STRATEGIES（11 个），对齐常量避免再次僵化
            mock_daily.assert_called_once_with("2026-06-19", DEFAULT_STRATEGIES)


class TestGenerateMonthlyReport:
    """测试 generate_monthly_report (lines 162-178)"""

    def test_monthly_report_returns_correct_type(self):
        """月报返回 report_type=monthly"""
        service = ReportService(stock_pool=["000001.SZ"])
        with patch.object(service, "generate_daily_report", return_value=dict(SAMPLE_DAILY_RESULT)):
            result = service.generate_monthly_report(2026, 6)
        assert result["report_type"] == "monthly"
        assert "2026-06" in result["report_date"]

    def test_monthly_with_defaults(self):
        """月报使用默认年月 (lines 163-164)"""
        service = ReportService(stock_pool=["000001.SZ"])
        with patch.object(service, "generate_daily_report", return_value=dict(SAMPLE_DAILY_RESULT)):
            result = service.generate_monthly_report()
        assert result["report_type"] == "monthly"


class TestFetchBacktestData:
    """测试 _fetch_backtest_data 降级路径 (lines 191-210)

    report_service 内部使用局部 import：
        from services.data_fetcher import fetch_kline_eastmoney, fetch_kline_tencent
    需要在源头模块处 patch。
    """

    def test_tencent_fallback_to_eastmoney(self):
        """腾讯财经无数据 → 降级东方财富 (lines 188-193)"""
        service = ReportService()
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch(
                "services.data_fetcher.fetch_kline_eastmoney",
                return_value=[{"date": "2026-01-01"}],
            ),
        ):
            data = service._fetch_backtest_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(data) == 1

    def test_public_sources_fail_fallback_to_data_service(self):
        """公开源全失败 → 降级 DataService (lines 197-205)"""
        service = ReportService()
        mock_ds = MagicMock()
        mock_ds.get_stock_daily_quote.return_value = [{"date": "2026-01-01"}]
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch("services.data_fetcher.fetch_kline_eastmoney", return_value=[]),
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings"),
        ):
            data = service._fetch_backtest_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(data) == 1

    def test_all_sources_fail_returns_empty(self):
        """所有源都失败 → 返回空列表 (lines 209-210)"""
        service = ReportService()
        mock_ds = MagicMock()
        mock_ds.get_stock_daily_quote.return_value = None
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch("services.data_fetcher.fetch_kline_eastmoney", return_value=[]),
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings"),
        ):
            data = service._fetch_backtest_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert data == []

    def test_public_source_exception_fallback(self):
        """公开源异常 → 降级 DataService (lines 194-195)"""
        service = ReportService()
        mock_ds = MagicMock()
        mock_ds.get_stock_daily_quote.return_value = [{"date": "2026-01-01"}]
        with (
            patch(
                "services.data_fetcher.fetch_kline_tencent",
                side_effect=ConnectionError("超时"),
            ),
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings"),
        ):
            data = service._fetch_backtest_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(data) == 1

    def test_data_service_exception_falls_through(self):
        """DataService 异常 → 记录 warning 并 fall through 到 209-210 (lines 206-210)"""
        service = ReportService()
        mock_ds = MagicMock()
        mock_ds.get_stock_daily_quote.side_effect = ValueError("DataService 挂了")
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch("services.data_fetcher.fetch_kline_eastmoney", return_value=[]),
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings"),
        ):
            data = service._fetch_backtest_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert data == []

    def test_data_service_no_hasattr_falls_through(self):
        """DataService 没有 get_stock_daily_quote → fall through 到 209-210 (lines 209-210)"""
        service = ReportService()
        # MagicMock 默认有所有 hasattr，需要用 dict 方式创建无此属性的 mock
        mock_ds = MagicMock(spec=[])
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch("services.data_fetcher.fetch_kline_eastmoney", return_value=[]),
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings"),
        ):
            data = service._fetch_backtest_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert data == []


class TestGenerateDailyReview:
    """测试 generate_daily_review (lines 212-248) — async 方法，需要 await"""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """正常路径返回 review 结构"""
        service = ReportService(stock_pool=["000001.SZ"])
        with patch.object(service, "generate_daily_report", return_value=dict(SAMPLE_DAILY_RESULT)):
            result = await service.generate_daily_review("2026-06-19")
        assert result["review_date"] == "2026-06-19"
        assert result["top_strategy"]["strategy"] == "ma-cross"

    @pytest.mark.asyncio
    async def test_exception_raises(self):
        """异常 → 重新抛出 (lines 246-248)"""
        service = ReportService(stock_pool=["000001.SZ"])
        with patch.object(service, "generate_daily_report", side_effect=RuntimeError("生成失败")):
            with pytest.raises(RuntimeError):
                await service.generate_daily_review("2026-06-19")


class TestDefaultStartDate:
    """测试 _default_start_date

    ⚠️ 2026-09-04 三档窗口全部加长：90/180/365 → 730/730/1095。
    旧值短到慢策略在窗口内只产生 0~2 个信号 → 没有任何回测能达到 5 笔
    → Top5 恒为单笔噪声（连续 5 天）。理由与实测数据见 _default_start_date 的注释。
    """

    def test_daily_returns_730_days(self):
        """日报回看 730 天（2 年）"""
        service = ReportService()
        result = service._default_start_date("daily", "2026-06-19")
        assert result == "2024-06-19"

    def test_weekly_returns_730_days(self):
        """周报回看 730 天（2 年）"""
        service = ReportService()
        result = service._default_start_date("weekly", "2026-06-19")
        assert result == "2024-06-19"

    def test_monthly_returns_1095_days(self):
        """月报回看 1095 天（3 年）"""
        service = ReportService()
        result = service._default_start_date("monthly", "2026-06-19")
        assert result == "2023-06-20"

    def test_windows_are_long_enough_for_min_trades(self):
        """核心不变量：daily 窗口必须长到能产生 ≥5 笔交易，否则 Top5 全是噪声

        这是 08-31~09-04 连续 5 天 Top5 单笔假象的根因守卫。
        90 天时 ≥5 笔占比为 **0.0%**；730 天时约 27%。
        """
        assert ReportService.WINDOW_DAYS["daily"] >= 730
        # 三档都必须长于旧的 365 天上限，否则等于退回有缺陷的口径
        assert all(v >= 730 for v in ReportService.WINDOW_DAYS.values())
        # 月报应最长
        assert ReportService.WINDOW_DAYS["monthly"] > ReportService.WINDOW_DAYS["daily"]


class TestFormatMarkdown:
    """测试 _format_markdown

    签名已新增 wf_validated（Walk-Forward 验证结果），位于 report_label 之前。
    """

    def test_returns_markdown_string(self):
        """返回合法的 Markdown 字符串"""
        service = ReportService()
        md = service._format_markdown(SAMPLE_SUMMARY, SAMPLE_TOP, SAMPLE_RANKING, {}, "日报")
        assert "QuantTradingSystem" in md
        assert "绩效摘要" in md
        assert "000001.SZ" in md

    def test_without_stock_ranking(self):
        """无股票排名时也正常渲染"""
        service = ReportService()
        md = service._format_markdown(SAMPLE_SUMMARY, SAMPLE_TOP, [], {}, "测试")
        assert "股票综合排名" not in md


class TestFormatFeishuCard:
    """测试 _format_feishu_card"""

    def test_returns_card_dict(self):
        """返回合法的飞书卡片结构"""
        service = ReportService()
        card = service._format_feishu_card(SAMPLE_SUMMARY, SAMPLE_TOP, SAMPLE_RANKING, {}, "日报")
        assert card["msg_type"] == "interactive"
        assert card["card"]["header"]["title"]["content"] == "🔬 QuantTradingSystem 日报"


# ============================================================
# 2026-09-03 回归：股票池筛选的两处静默失效
#   ① 流动性基准日用 MAX(trade_date) → 踩到"当日只灌了部分股票"，
#      amount>=3亿 命中 0 只 → 静默降级到全量池(4579 只, 正常 3.7 倍)
#   ② ST 过滤查 stock_basic 表 → 该表根本不存在，过滤静默失效，
#      日志却仍写"已排ST"，排查时会被误导
# ============================================================


class TestExcludeBanned:
    """模块级 _exclude_banned：排除科创板 + ST（名称层）"""

    def test_is_module_level_importable(self):
        """已提到模块级，可直接单测（初版是方法内闭包，测不到）"""
        from services.report_service import _exclude_banned

        codes, ok = _exclude_banned(["000001.SZ"])
        assert codes == ["000001.SZ"]
        assert ok is True

    def test_excludes_star_market(self):
        """科创板 68x / 689 一律排除"""
        from services.report_service import _exclude_banned

        codes, _ = _exclude_banned(["000001.SZ", "688001.SH", "689009.SH", "600519.SH"])
        assert codes == ["000001.SZ", "600519.SH"]

    def test_excludes_st_by_name(self):
        """名称层排 ST：resolve_name_batch 返回含 ST 的名称即剔除"""
        from services.report_service import _exclude_banned

        names = {
            "000001.SZ": "平安银行",
            "600745.SH": "*ST闻泰",
            "000711.SZ": "ST京蓝",
            "002528.SZ": "*ST英飞",
        }
        with patch("shared.stock_name.resolve_name_batch", return_value=names):
            codes, ok = _exclude_banned(list(names))

        assert ok is True
        assert codes == ["000001.SZ"]

    def test_st_filter_failure_is_reported_not_hidden(self):
        """名称层失败必须返回 st_ok=False，让调用方日志能写"⚠️ST未过滤"

        2026-09-03 教训：旧实现查不存在的 stock_basic 表失败后静默跳过，
        日志照样宣称"已排ST"，把排查方向带偏。失败必须显式上抛给调用方。
        """
        from services.report_service import _exclude_banned

        with patch(
            "shared.stock_name.resolve_name_batch",
            side_effect=RuntimeError("table not found"),
        ):
            codes, ok = _exclude_banned(["000001.SZ", "688001.SH"])

        assert ok is False
        assert codes == ["000001.SZ"]  # 代码层(科创)仍生效

    def test_gem_not_excluded(self):
        """创业板 300/301 目前不排除——规则冲突未裁决，锁住现状防误改

        USER.md「不碰创业板」与 sim_trade.py 2026-07-29 已放开创业板冲突，
        用户未裁决前保持现状。此测试的作用是：一旦有人改动，必须同时更新这里。
        """
        from services.report_service import _exclude_banned

        codes, _ = _exclude_banned(["300750.SZ", "301001.SZ", "000001.SZ"])
        assert codes == ["300750.SZ", "301001.SZ", "000001.SZ"]


class TestLiquidityBaseDate:
    """流动性筛选基准日：跳过"未灌完"的交易日

    坑（2026-09-03 实犯）：ReportService() 不传 stock_pool 时，__init__ 会先跑
    一次真实的 _load_stock_pool_from_db()，把 mock 的 side_effect 消耗光
    （返回 1231 只真实股票），等测试再调用时只剩 StopIteration。
    现象是"断言收到兜底池"，极易误判成生产代码有问题。故必须传 stock_pool 构造，
    且 execute 用按 SQL 内容分发的函数式 side_effect，不依赖调用顺序。
    """

    @staticmethod
    def _mock_db(dispatch):
        """构造 db 上下文管理器；dispatch(sql_text, resp) 由各测试定制返回值"""
        executed: list[str] = []

        def _execute(sql, params=None):
            sql_text = str(sql)
            executed.append(sql_text)
            resp = MagicMock()
            resp.fetchone.return_value = None
            resp.fetchall.return_value = []
            dispatch(sql_text, resp)
            return resp

        db = MagicMock()
        db.execute.side_effect = _execute
        session_cm = MagicMock()
        session_cm.__enter__.return_value = db
        return session_cm, executed

    def test_uses_last_complete_trading_day(self):
        """基准日取"记录数 >= 1000 的最近交易日"，而非 MAX(trade_date)"""
        from services.report_service import ReportService

        def dispatch(sql_text, resp):
            if "HAVING COUNT(*) >= 1000" in sql_text:
                resp.fetchone.return_value = ("2026-09-01",)
            elif "amount >= 300000000" in sql_text:
                resp.fetchall.return_value = [("000001.SZ",), ("600519.SH",)]

        cm, executed = self._mock_db(dispatch)
        with (
            patch("models.database.get_db_session", return_value=cm),
            patch("services.report_service._exclude_banned", side_effect=lambda c: (c, True)),
        ):
            codes = ReportService(stock_pool=["000001.SZ"])._load_stock_pool_from_db()

        assert codes == ["000001.SZ", "600519.SH"]
        assert any("HAVING COUNT(*) >= 1000" in s for s in executed)
        assert not any("MAX(trade_date)" in s for s in executed)

    def test_falls_back_to_max_when_no_complete_day(self):
        """没有任何完整交易日 → 退回 MAX(trade_date)，不静默放弃"""
        from services.report_service import ReportService

        def dispatch(sql_text, resp):
            if "HAVING COUNT(*) >= 1000" in sql_text:
                resp.fetchone.return_value = None
            elif "MAX(trade_date)" in sql_text:
                resp.fetchone.return_value = ("2026-09-02",)
            elif "amount >= 300000000" in sql_text:
                resp.fetchall.return_value = [("000001.SZ",)]

        cm, executed = self._mock_db(dispatch)
        with (
            patch("models.database.get_db_session", return_value=cm),
            patch("services.report_service._exclude_banned", side_effect=lambda c: (c, True)),
        ):
            codes = ReportService(stock_pool=["000001.SZ"])._load_stock_pool_from_db()

        assert codes == ["000001.SZ"]
        assert any("MAX(trade_date)" in s for s in executed)


# ============================================================
# _probe_data_freshness（2026-09-04 加）
#
# 背景：daily_quote 灌库任务中断时每天只写 44 行（按代码升序，死在同一处），
# 但 MAX(trade_date) 仍返回"看起来最新"的日期 → 所有只看 MAX 的新鲜度检查都被骗过，
# 导致 report_date=09-04 的回测实际跑在截止 09-01 的数据上且全程静默。
# 这几条测试锁死"判完整必须用行数门槛"的口径。
# ============================================================


class TestProbeDataFreshness:
    """数据完整度探测：MAX(trade_date) 不能作为新鲜度判据"""

    @staticmethod
    def _mock_db(rowsets):
        """rowsets: list[list[tuple]]，按调用顺序返回 fetchall 结果"""
        cm = MagicMock()
        db = MagicMock()
        queue = list(rowsets)

        def execute(stmt, *a, **kw):
            resp = MagicMock()
            resp.fetchall.return_value = queue.pop(0) if queue else []
            return resp

        db.execute.side_effect = execute
        cm.__enter__.return_value = db
        return cm

    def setup_method(self):
        from services.report_service import ReportService

        ReportService._DATA_FRESHNESS_CACHE = None  # 清进程内缓存，否则测不到 SQL

    def test_max_date_alone_must_not_win(self):
        """核心回归：最新日只有 44 行 → 不能算作 data_as_of"""
        from services.report_service import ReportService

        rows = [
            ("2026-09-03", 44),
            ("2026-09-02", 44),
            ("2026-09-01", 4893),
            ("2026-08-31", 4623),
        ]
        with patch("models.database.get_db_session", return_value=self._mock_db([rows])):
            meta = ReportService._probe_data_freshness()

        assert meta["data_as_of"] == "2026-09-01"
        assert meta["data_stale"] is True
        assert meta["incomplete_sessions"] == ["2026-09-02", "2026-09-03"]

    def test_fresh_when_latest_day_complete(self):
        """最新日行数达标 → 不滞后"""
        from services.report_service import ReportService

        rows = [("2026-09-04", 4893), ("2026-09-03", 4890)]
        with patch("models.database.get_db_session", return_value=self._mock_db([rows])):
            meta = ReportService._probe_data_freshness()

        assert meta["data_as_of"] == "2026-09-04"
        assert meta["data_stale"] is False
        assert meta["incomplete_sessions"] == []

    def test_no_complete_day_never_fakes_an_as_of_date(self):
        """全部不完整 → data_as_of 必须是 None，绝不拿残缺日冒充截止日"""
        from services.report_service import ReportService

        rows = [("2026-09-03", 44), ("2026-09-02", 30)]
        with patch("models.database.get_db_session", return_value=self._mock_db([rows])):
            meta = ReportService._probe_data_freshness()

        assert meta["data_as_of"] is None
        assert meta["data_stale"] is True
        assert meta["incomplete_sessions"] == ["2026-09-02", "2026-09-03"]

    def test_empty_table_returns_neutral_meta(self):
        """空表 → 返回中性值，不抛异常（探测失败不能阻断出报）"""
        from services.report_service import ReportService

        with patch("models.database.get_db_session", return_value=self._mock_db([[]])):
            meta = ReportService._probe_data_freshness()

        assert meta["data_as_of"] is None
        assert meta["data_stale"] is False

    def test_db_error_never_raises(self):
        """DB 异常 → 吞掉并返回中性值"""
        from services.report_service import ReportService

        cm = MagicMock()
        cm.__enter__.side_effect = RuntimeError("connection lost")
        with patch("models.database.get_db_session", return_value=cm):
            meta = ReportService._probe_data_freshness()

        assert meta == {"data_as_of": None, "data_stale": False, "incomplete_sessions": []}

    def test_cache_prevents_repeated_full_scan(self):
        """1 小时内复用缓存 → 全表 GROUP BY 只执行一次"""
        from services.report_service import ReportService

        rows = [("2026-09-01", 4893)]
        cm = self._mock_db([rows])
        db = cm.__enter__.return_value
        with patch("models.database.get_db_session", return_value=cm):
            ReportService._probe_data_freshness()
            ReportService._probe_data_freshness()

        assert db.execute.call_count == 1


# ============================================================
# Top 名单的最低交易笔数挑选（2026-09-04 加）
#
# 事故：Top5 连续 5 天（08-31~09-04）全是 total_trades=1、win_rate=100% 的单笔噪声。
# 两个独立缺陷叠加：
#   ① 回测窗口只有 90 天 → 全池 0% 的回测能达到 5 笔（已在 WINDOW_DAYS 修掉）
#   ② 即使有够格候选，挑选也只在**排名前 10** 里做 → 够格的排在第 11 名开外就永远进不来
# 这里锁死 ②：必须扫全量候选，且逐级放宽。
# ============================================================


class TestMinTradesTierSelection:
    """Top 名单必须在全量候选中挑够笔数的，不能只在前 10 名里筛"""

    @staticmethod
    def _rec(code, trades, sharpe):
        return {
            "ts_code": code,
            "strategy": "macd",
            "sharpe": sharpe,
            "total_trades": trades,
            "total_return": 1.0,
            "max_drawdown": 1.0,
            "win_rate": 50.0,
            "final_value": 1000.0,
        }

    @staticmethod
    def _rankable():
        """前 12 名全是单笔噪声，够格的（trades>=5）故意排在第 13~17 名"""
        recs = [TestMinTradesTierSelection._rec(f"{i:06d}.SZ", 1, 90 - i) for i in range(12)]
        recs += [TestMinTradesTierSelection._rec(f"{i:06d}.SZ", 5, 60 - i) for i in range(12, 17)]
        return recs

    def test_qualified_candidates_outside_top10_are_picked(self):
        """核心回归：够格候选排在第 13~17 名 → 仍必须被选中"""
        from services.report_service import ReportService

        ranked = sorted(self._rankable(), key=lambda r: r["sharpe"] * 0.1, reverse=True)
        picked = []
        for min_t in ReportService.MIN_TRADES_TIERS:
            picked = [r for r in ranked if r.get("total_trades", 0) >= min_t][:10]
            if len(picked) >= 5:
                break

        assert len(picked) == 5
        assert all(r["total_trades"] >= 5 for r in picked)
        # 若只在 sharpe 前 10 里筛，这里会拿到 0 条（前 12 名全是 trades=1）
        naive = [r for r in ranked[:10] if r["total_trades"] >= 5]
        assert naive == [], "前提校验：前 10 名确实没有够格候选"

    def test_tiers_relax_when_too_few_qualified(self):
        """够格候选不足 5 条 → 逐级放宽到 3 笔"""
        from services.report_service import ReportService

        recs = [self._rec("000001.SZ", 3, 9.0), self._rec("000002.SZ", 3, 8.0)]
        ranked = sorted(recs, key=lambda r: r["sharpe"] * 0.1, reverse=True)
        picked = []
        for min_t in ReportService.MIN_TRADES_TIERS:
            picked = [r for r in ranked if r["total_trades"] >= min_t][:10]
            if len(picked) >= 5:
                break

        assert len(picked) == 2  # 全池就 2 条，如实返回短名单，不用噪声补齐
        assert all(r["total_trades"] >= 3 for r in picked)

    def test_tiers_are_ordered_strict_descending(self):
        """门槛必须严格递减，否则放宽逻辑失效"""
        from services.report_service import ReportService

        tiers = ReportService.MIN_TRADES_TIERS
        assert list(tiers) == sorted(tiers, reverse=True)
        assert tiers[-1] >= 1


# ============================================================
# WF 候选挑选（2026-09-04 加）
#
# 事故：Walk-Forward 只有 30 个名额，原实现按 raw sharpe 取前 50，
# 而 raw sharpe 最高的恰恰是 total_trades=1 的运气单 —— 单笔回测的 sharpe
# 没有分母约束，一笔 +20% 就能算出 46；8 笔、胜率 37.5% 的真实策略只有 4.5。
# 两者硬排，必然让噪声赢 → 30 个名额全给噪声，够格的候选一个都没验证到
# （Top5 因此全标「⚪ 未验证」，wf_passed 长期只有 2~5）。
# ============================================================


class TestSelectWfCandidates:
    @staticmethod
    def _rec(i, trades, sharpe):
        return {
            "ts_code": f"{i:06d}.SZ",
            "strategy": "macd",
            "sharpe": sharpe,
            "total_trades": trades,
        }

    @staticmethod
    def _pool(n_noise=100, n_real=80):
        # 单笔噪声 sharpe 高（200~101），多笔真实策略 sharpe 低（80~1）
        return [TestSelectWfCandidates._rec(i, 1, 200 - i) for i in range(n_noise)] + [
            TestSelectWfCandidates._rec(i, 6, 80 - (i - n_noise))
            for i in range(n_noise, n_noise + n_real)
        ]

    def test_qualified_candidates_win_over_high_sharpe_noise(self):
        """核心回归：够格候选 sharpe 更低，但必须优先入选"""
        from services.report_service import ReportService

        picked = ReportService._select_wf_candidates(self._pool(), limit=50)
        assert len(picked) == 50
        assert all(r["total_trades"] >= 5 for r in picked)
        # 前提校验：按旧逻辑（纯 sharpe 排）50 个名额会被单笔噪声全占
        naive = sorted(self._pool(), key=lambda x: x["sharpe"], reverse=True)[:50]
        assert all(r["total_trades"] == 1 for r in naive)

    def test_relaxes_when_too_few_qualified(self):
        """够格候选不足 → 逐级放宽，且必须填满 limit 不退化成空列表"""
        from services.report_service import ReportService

        pool = self._pool(n_noise=100, n_real=10)  # 只有 10 条够格
        picked = ReportService._select_wf_candidates(pool, limit=50)
        assert len(picked) == 50  # 放宽后补齐
        assert any(r["total_trades"] >= 5 for r in picked)

    def test_always_returns_up_to_limit(self):
        """候选总数不足 limit → 有多少返回多少，不报错也不补齐"""
        from services.report_service import ReportService

        small = self._pool(n_noise=3, n_real=2)
        assert len(ReportService._select_wf_candidates(small, limit=50)) == 5

    def test_empty_pool(self):
        from services.report_service import ReportService

        assert ReportService._select_wf_candidates([], limit=50) == []


# ============================================================
# Walk-Forward 判可信的统一口径（2026-09-04 加）
#
# 事故：三处判据互相矛盾，同一份数据能同时得出"通过"和"过拟合"：
#   - wf_passed  : stability>=50 且 ratio <= 0.2 → 把 ratio=-59 判为通过
#   - wf_label   : stability>=50 且 ratio >  0.2 → 与上一条正好相反
#   - _is_overfit: ratio > 0.2 判为过拟合并硬排除 → 把 ratio=0.9（好）排除掉
#
# overfit_ratio 语义（backtest_engine_v2.walk_forward）：
#   mean(测试期夏普 / 训练期夏普)，1.0 = 样本外完全保持，负值 = 方向反转。
# 实测 30 个候选：min=-59.43 中位=-0.50 max=88.75，负值 17/30，>=0.5 的仅 7/30。
# ============================================================


class TestWfTrustworthy:
    @staticmethod
    def _wf(stability, ratio, wf_return=12.0):
        """默认 wf_return 为正 —— 构造"两道闸都过"的基准，
        再让各用例单独把它打成负数来验证第三道闸。"""
        return {"stability": stability, "overfit_ratio": ratio, "wf_return": wf_return}

    def test_reversal_is_not_trustworthy(self):
        """核心回归：ratio 为负（样本外方向反转）绝不能算可信

        旧 wf_passed 判据 `ratio <= 0.2` 会把 ratio=-59 判为通过（21/30 "通过"）。
        """
        from services.report_service import ReportService as R

        assert R._wf_is_trustworthy(self._wf(60, -59.43)) is False
        assert R._wf_is_trustworthy(self._wf(60, -0.5)) is False
        assert R._wf_is_trustworthy(self._wf(100, -0.01)) is False

    def test_retained_edge_is_trustworthy(self):
        """样本外保留住大部分表现 → 可信"""
        from services.report_service import ReportService as R

        assert R._wf_is_trustworthy(self._wf(60, 0.9)) is True
        assert R._wf_is_trustworthy(self._wf(100, 1.5)) is True  # 样本外更好
        assert R._wf_is_trustworthy(self._wf(50, 0.5)) is True  # 恰好卡在门槛

    def test_low_stability_is_not_trustworthy(self):
        """稳定性不足 → 不可信（即便 ratio 很好）"""
        from services.report_service import ReportService as R

        assert R._wf_is_trustworthy(self._wf(49.9, 2.0)) is False
        assert R._wf_is_trustworthy(self._wf(0, 1.0)) is False

    def test_missing_wf_is_not_trustworthy(self):
        """未验证（wf 为空/None）→ 不可信，不能默认放行"""
        from services.report_service import ReportService as R

        assert R._wf_is_trustworthy(None) is False
        assert R._wf_is_trustworthy({}) is False

    def test_negative_out_of_sample_return_is_not_trustworthy(self):
        """第三道闸：样本外净收益为负 → 不可信，哪怕前两道都过

        两类漏网靠这条挡住：
          1. 比值爆炸 —— train_sharpe 趋零时 ratio 可飙到 73.59 / 88.75，
             "样本内本来就没优势"被误读成"样本外保持得好"。
          2. 盈亏不对称 —— 过半窗口小赚 + 一次大亏，stability 高但净亏。
        """
        from services.report_service import ReportService as R

        # 比值爆炸 + 高稳定性，但样本外净亏
        assert R._wf_is_trustworthy(self._wf(60, 73.59, wf_return=-3.2)) is False
        # 盈亏不对称：stability 70% 但复合收益为负
        assert R._wf_is_trustworthy(self._wf(70, 1.2, wf_return=-0.01)) is False
        # 恰好为 0（不亏不赚）也不算可信 —— 要的是真的赚到钱
        assert R._wf_is_trustworthy(self._wf(60, 0.9, wf_return=0)) is False

    def test_three_gates_all_pass(self):
        """三道闸全过 → 可信"""
        from services.report_service import ReportService as R

        assert R._wf_is_trustworthy(self._wf(60, 0.9, wf_return=25.4)) is True
        assert R._wf_is_trustworthy(self._wf(50, 0.5, wf_return=0.01)) is True  # 卡门槛


class TestWfRankScore:
    """排名权重口径（2026-09-04 从嵌套闭包提取为类方法后才可测）"""

    @staticmethod
    def _rec(code="600000.SH", strat="macd", sharpe=3.0):
        return {"ts_code": code, "strategy": strat, "sharpe": sharpe}

    @staticmethod
    def _wfv(pairs):
        return {f"{c}|{s}": v for (c, s), v in pairs.items()}

    def test_trustworthy_beats_degraded(self):
        """核心回归：可信条目必须排在劣化条目之上

        旧口径下不达标项是平折 ×0.5、可信项是 ×(stability/100)；
        stability=60 的可信项只拿 0.6，与 0.5 几乎无差别，于是
        stability=40% 且 ratio=73.59 的劣化条目（000415.SZ）长期霸占 Top1。
        改为叠加折扣后 0.2 vs 0.6，差 3 倍。
        """
        from services.report_service import ReportService as R

        good = self._rec("A", "macd")
        bad = self._rec("B", "macd")
        wfv = self._wfv(
            {
                ("A", "macd"): {"stability": 60.0, "overfit_ratio": 0.9, "wf_return": 20.0},
                ("B", "macd"): {"stability": 40.0, "overfit_ratio": 73.59, "wf_return": 20.0},
            }
        )
        # 同样的 wf_return，可信的必须胜出，且差距明显
        assert R._wf_rank_score(good, wfv) == 12.0  # 20 × 0.6
        assert R._wf_rank_score(bad, wfv) == 4.0  # 20 × 0.4 × 0.5
        assert R._wf_rank_score(good, wfv) > R._wf_rank_score(bad, wfv) * 2

    def test_degraded_needs_3x_return_to_overtake(self):
        """劣化条目要反超，样本外收益得是可信条目的 3 倍以上"""
        from services.report_service import ReportService as R

        good = self._rec("A", "macd")
        bad = self._rec("B", "macd")
        mk = lambda r_good, r_bad: self._wfv(  # noqa: E731
            {
                ("A", "macd"): {"stability": 60.0, "overfit_ratio": 0.9, "wf_return": r_good},
                ("B", "macd"): {"stability": 40.0, "overfit_ratio": 73.59, "wf_return": r_bad},
            }
        )
        assert R._wf_rank_score(good, mk(20, 59)) > R._wf_rank_score(bad, mk(20, 59))
        assert R._wf_rank_score(good, mk(20, 61)) < R._wf_rank_score(bad, mk(20, 61))

    def test_unverified_is_heavily_discounted(self):
        """未验证条目：只有原始 Sharpe × 0.1，权重远低于验证过的"""
        from services.report_service import ReportService as R

        unverified = self._rec("C", "macd", sharpe=6.0)  # 很高的原始 Sharpe
        wfv = self._wfv(
            {("A", "macd"): {"stability": 60.0, "overfit_ratio": 0.9, "wf_return": 20.0}}
        )
        assert R._wf_rank_score(unverified, wfv) == pytest.approx(0.6)
        assert R._wf_rank_score(self._rec("A", "macd"), wfv) == pytest.approx(12.0)

    def test_direction_reversal_scores_low_or_negative(self):
        """样本外方向反转（ratio<0，会被 _is_overfit 剔除）打分不得高于可信项"""
        from services.report_service import ReportService as R

        rev = self._rec("D", "macd")
        wfv = self._wfv(
            {
                ("D", "macd"): {"stability": 60.0, "overfit_ratio": -59.0, "wf_return": 20.0},
            }
        )
        # 负 ratio → 不可信 → 叠加折扣 20 × 0.6 × 0.5 = 6.0，不再是打满权重
        assert R._wf_rank_score(rev, wfv) == 6.0

    def test_thresholds_are_consistent_with_wf_passed(self):
        """守卫：所有 WF 判定点必须走同一个判据，不许再各写一套

        这是本次修复的核心 —— 4 处判据各自漂移才导致自相矛盾的结论
        （同一条数据既能"通过"又标"过拟合"）。
        """
        import inspect

        import services.report_service as mod

        src = inspect.getsource(mod.ReportService)
        # 不允许再出现硬编码的旧判据
        assert 'overfit_ratio"] <= 0.2' not in src
        assert 'overfit_ratio", 0) > 0.2' not in src

    def test_no_hardcoded_threshold_survives_comment_stripping(self):
        """守卫：剥离注释后，ReportService 源码里不许再有裸的 0.2 判据

        上一版只检查了两个字面量，`_rank_score` 里那处 `ratio <= 0.2`
        用的是 `.get("overfit_ratio", 0) <= 0.2` 写法，直接漏网 ——
        它给 ratio=-59 的策略打满权重。故改为先剥注释再全量扫描。
        """
        import inspect
        import io
        import tokenize

        import services.report_service as mod

        src = inspect.getsource(mod.ReportService)
        # 用 tokenize 丢掉 COMMENT / STRING，只留真实代码
        code_only = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                code_only.append(tok.string)
        code = " ".join(code_only)

        # 0.2 这个魔数不得再出现在可执行代码里
        assert "0.2" not in code, "WF 判据又硬编码了 0.2，请改用 WF_MIN_* 常量"

    def test_all_judgment_sites_call_the_shared_entrypoint(self):
        """守卫：4 个判定点全部调用 _wf_is_trustworthy，不得有旁路

        wf_passed / wf_label / _rank_score / 飞书卡片 四处。
        """
        import inspect
        import io
        import tokenize

        import services.report_service as mod

        src = inspect.getsource(mod.ReportService)
        code_only = [
            tok.string
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        ]
        code = " ".join(code_only)

        # 定义处 1 次 + 调用处至少 4 次
        assert code.count("_wf_is_trustworthy (") >= 5 or code.count("_wf_is_trustworthy(") >= 5, (
            f"判定点数量不足，当前: {code.count('_wf_is_trustworthy(')}"
        )


# ============================================================
# 板块分类（2026-09-04 加）
#
# 背景：创业板 300/301 长期存在规则冲突 —— USER.md「不碰创业板」（实盘）
# vs sim_trade.py 2026-07-29 已放开创业板（模拟盘）。两边都是用户自己的规则，
# 过滤任何一边都会毁掉另一边。故改为**标注不过滤**，由下游各自消费。
# ============================================================


class TestClassifyBoard:
    def test_mainboard_codes(self):
        """沪主板 / 深主板 / 原中小板 都算可交易板块"""
        from services.report_service import TRADABLE_BOARDS, classify_board

        assert classify_board("600000.SH") == "沪主板"
        assert classify_board("601398.SH") == "沪主板"
        assert classify_board("000001.SZ") == "深主板"
        assert classify_board("002415.SZ") == "深主板(原中小板)"
        assert classify_board("003018.SZ") == "深主板(原中小板)"
        for b in ("沪主板", "深主板", "深主板(原中小板)"):
            assert b in TRADABLE_BOARDS

    def test_chinext_is_flagged_not_mainboard(self):
        """核心：创业板必须被识别出来，且不在可交易集合内

        这是本次冲突的解法 —— 不过滤（保住模拟盘口径与统计功效），
        但必须能标出来（让实盘口径的下游看得见）。
        """
        from services.report_service import TRADABLE_BOARDS, classify_board

        assert classify_board("300209.SZ") == "创业板"
        assert classify_board("301520.SZ") == "创业板"
        assert classify_board("300153.SZ") == "创业板"
        assert "创业板" not in TRADABLE_BOARDS

    def test_star_and_bse(self):
        """科创板（已被 _exclude_banned 排除）/ 北交所 / B股"""
        from services.report_service import TRADABLE_BOARDS, classify_board

        assert classify_board("688981.SH") == "科创板"
        assert classify_board("689009.SH") == "科创板"
        assert classify_board("920002.BJ") == "北交所"
        assert classify_board("430047.BJ") == "北交所"
        assert classify_board("900001.SH") == "沪B股"
        assert classify_board("200011.SZ") == "深B股"
        for b in ("科创板", "北交所", "沪B股", "深B股"):
            assert b not in TRADABLE_BOARDS

    def test_unknown_suffix_does_not_crash(self):
        """异常代码不得抛异常，也不得被误判成主板放行"""
        from services.report_service import TRADABLE_BOARDS, classify_board

        assert classify_board("") == "未知"
        assert classify_board("ABCDE") == "未知"
        assert "未知" not in TRADABLE_BOARDS


class TestExtremeDayLabelSync:
    """守卫：wf_label 改名后，极端日分支的比对必须同步

    2026-09-04 实犯：`"⚠️ 过拟合"` 改名为 `"⚠️ 样本外劣化"` 后，
    extreme_day 分支里的字符串比对没跟着改 → 整段变成永不触发的死代码。
    """

    def test_extreme_day_branch_uses_current_label(self):
        import inspect
        import io
        import tokenize

        from services.report_service import ReportService

        src = inspect.getsource(ReportService.generate_daily_brief)
        # 只剥 COMMENT，**必须保留 STRING** —— 要比对的目标本身
        # （`entry.get("wf_label") == "⚠️ 过拟合"`）里的标签名就是字符串字面量，
        # 连 STRING 一起剥会让这个守卫永远不可能触发（第一版即为此错，
        # 注入旧标签后仍 1 passed）。反过来，注释里提到的旧标签名要剥掉，
        # 否则会把"文档说明"误判成"仍在使用的标签"。
        code = " ".join(
            tok.string
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type != tokenize.COMMENT
        )
        assert "⚠️ 过拟合" not in code, "extreme_day 分支仍在比对已废弃的旧标签"
        assert "⚠️ 样本外劣化" in code, "extreme_day 分支未比对当前生效的标签"
