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

from datetime import date
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from services.report_service import ReportService

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
        """数据不足 30 条 → 跳过该股票 (lines 57-58)"""
        service = ReportService(stock_pool=["000001.SZ"])
        with patch.object(service, "_fetch_backtest_data", return_value=[]):
            result = service.generate_daily_report("2026-06-19")
        assert result["backtest_count"] == 0

    def test_mock_engine_happy_path(self, mock_engine):
        """mock 引擎覆盖正常路径 (lines 60-87)"""
        service = ReportService(stock_pool=["000001.SZ"])
        mock_data = _make_mock_data(31)
        with patch.object(service, "_fetch_backtest_data", return_value=mock_data):
            result = service.generate_daily_report("2026-06-19")
        assert result["backtest_count"] == 5  # 5 个策略
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
            mock_daily.assert_called_once_with(
                "2026-06-19", ["ma-cross", "breakout", "rsi", "macd", "kdj"]
            )


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
    """测试 _default_start_date (lines 250-257)"""

    def test_daily_returns_90_days(self):
        """日报回看 90 天 (line 254)"""
        service = ReportService()
        result = service._default_start_date("daily", "2026-06-19")
        assert result == "2026-03-21"

    def test_weekly_returns_180_days(self):
        """周报回看 180 天 (lines 255-256)"""
        service = ReportService()
        result = service._default_start_date("weekly", "2026-06-19")
        assert result == "2025-12-21"

    def test_other_returns_365_days(self):
        """其他类型回看 365 天 (line 257)"""
        service = ReportService()
        result = service._default_start_date("monthly", "2026-06-19")
        assert result == "2025-06-19"


class TestFormatMarkdown:
    """测试 _format_markdown"""

    def test_returns_markdown_string(self):
        """返回合法的 Markdown 字符串"""
        service = ReportService()
        md = service._format_markdown(SAMPLE_SUMMARY, SAMPLE_TOP, SAMPLE_RANKING, "日报")
        assert "QuantTradingSystem" in md
        assert "绩效摘要" in md
        assert "000001.SZ" in md

    def test_without_stock_ranking(self):
        """无股票排名时也正常渲染"""
        service = ReportService()
        md = service._format_markdown(SAMPLE_SUMMARY, SAMPLE_TOP, [], "测试")
        assert "股票综合排名" not in md


class TestFormatFeishuCard:
    """测试 _format_feishu_card"""

    def test_returns_card_dict(self):
        """返回合法的飞书卡片结构"""
        service = ReportService()
        card = service._format_feishu_card(SAMPLE_SUMMARY, SAMPLE_TOP, SAMPLE_RANKING, "日报")
        assert card["msg_type"] == "interactive"
        assert card["card"]["header"]["title"]["content"] == "🔬 QuantTradingSystem 日报"
