"""
测试回测报告定时调度器 — report_scheduler.py 全覆盖 (0% → 80%+)

覆盖:
- register_report_tasks: 注册 6 个 cron 任务
- _job_daily_signal_summary: 信号汇总 (有/无信号, 飞书失败, 查询异常)
- _job_daily_report: 日报生成 (正常, 飞书失败, DB失败, 生成异常, 无 webhook)
- _job_weekly_report: 周报 (正常, 异常)
- _job_monthly_report: 月报 (正常, 异常)
- _job_stock_insight_mainboard: 主板扫描 (有结果/无结果/飞书失败/DB失败/异常)
- _job_stock_insight_rational: 理性10扫描 (长线+短线/无结果/空列表/异常)
- _save_scan_result_to_db: DB 存储 (成功/空列表/失败)
- _save_report_to_db: DB 存储 (成功/无report_date/失败)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 注意: 所有被测试函数使用局部 import (from services.xxx import ...)
# 因此 patch 目标必须是原始模块，而非 services.report_scheduler

# ============================================================
# register_report_tasks — 注册 6 个 cron 任务
# ============================================================


class TestRegisterReportTasks:
    """验证 register_report_tasks 正确注册所有定时任务

    add_cron_job(func, job_id, hour=..., minute=..., name=..., ...)
    job_id 是第 2 个位置参数 => call.args[1]
    """

    def test_registers_six_cron_jobs(self):
        """注册 6 个 cron 任务"""
        from services.report_scheduler import register_report_tasks

        scheduler = MagicMock()
        register_report_tasks(scheduler)

        assert scheduler.add_cron_job.call_count == 6

    def test_job_ids_are_correct(self):
        """任务 ID 包含全部 6 个预期 ID"""
        from services.report_scheduler import register_report_tasks

        scheduler = MagicMock()
        register_report_tasks(scheduler)

        call_ids = [call.args[1] for call in scheduler.add_cron_job.call_args_list]
        assert "signal_daily_summary" in call_ids
        assert "report_daily" in call_ids
        assert "report_weekly" in call_ids
        assert "report_monthly" in call_ids
        assert "stock_insight_mainboard" in call_ids
        assert "stock_insight_rational" in call_ids

    def test_signal_summary_trigger(self):
        """每日信号汇总: mon-fri 15:30"""
        from services.report_scheduler import register_report_tasks

        scheduler = MagicMock()
        register_report_tasks(scheduler)

        calls = scheduler.add_cron_job.call_args_list
        target = [c for c in calls if c.args[1] == "signal_daily_summary"][0]
        assert target.kwargs["hour"] == 15
        assert target.kwargs["minute"] == 30
        assert target.kwargs["day_of_week"] == "mon-fri"

    def test_mainboard_scan_trigger(self):
        """主板扫描: mon-fri 09:00"""
        from services.report_scheduler import register_report_tasks

        scheduler = MagicMock()
        register_report_tasks(scheduler)

        calls = scheduler.add_cron_job.call_args_list
        target = [c for c in calls if c.args[1] == "stock_insight_mainboard"][0]
        assert target.kwargs["hour"] == 9
        assert target.kwargs["minute"] == 0
        assert target.kwargs["day_of_week"] == "mon-fri"

    def test_monthly_report_has_day(self):
        """月报有 day 参数 (每月28日)"""
        from services.report_scheduler import register_report_tasks

        scheduler = MagicMock()
        register_report_tasks(scheduler)

        calls = scheduler.add_cron_job.call_args_list
        target = [c for c in calls if c.args[1] == "report_monthly"][0]
        assert target.kwargs["day"] == 28

    def test_names_and_descriptions(self):
        """所有任务都有 name 和 description"""
        from services.report_scheduler import register_report_tasks

        scheduler = MagicMock()
        register_report_tasks(scheduler)

        for call in scheduler.add_cron_job.call_args_list:
            assert call.kwargs.get("name") is not None
            assert call.kwargs.get("description") is not None


# ============================================================
# _job_daily_signal_summary — 每日信号汇总
# ============================================================


class TestJobDailySignalSummary:
    """覆盖有信号/无信号/飞书失败/查询异常/顶层异常路径"""

    @pytest.mark.asyncio
    async def test_with_signals_and_high_conf(self):
        """有信号+高置信度 → 正常推送"""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            ("BUY", 85.0, "000001.SZ", "2026-06-20 10:00:00"),
            ("SELL", 72.0, "600519.SH", "2026-06-20 10:05:00"),
            ("hold", 55.0, "000002.SZ", "2026-06-20 10:10:00"),
        ]
        mock_session.execute.return_value.fetchone.return_value = (2,)

        mock_alert = AsyncMock()
        mock_alert.enabled = True

        mock_settings = MagicMock(FEISHU_WEBHOOK="https://webhook.example.com")

        with (
            patch("services.report_scheduler.get_db_session") as mock_get_db,
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings", mock_settings),
        ):
            mock_get_db.return_value.__enter__.return_value = mock_session
            from services.report_scheduler import _job_daily_signal_summary

            await _job_daily_signal_summary()

        mock_alert.send_alert.assert_awaited_once()
        call_args = mock_alert.send_alert.call_args.kwargs
        assert "每日信号汇总" in call_args["title"]
        assert "3" in call_args["data"]["总信号数"]

    @pytest.mark.asyncio
    async def test_no_signals(self):
        """无信号 → 内容包含今日无交易信号"""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session.execute.return_value.fetchone.return_value = (0,)

        mock_alert = AsyncMock()
        mock_alert.enabled = True

        mock_settings = MagicMock(FEISHU_WEBHOOK="https://webhook.example.com")

        with (
            patch("services.report_scheduler.get_db_session") as mock_get_db,
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings", mock_settings),
        ):
            mock_get_db.return_value.__enter__.return_value = mock_session
            from services.report_scheduler import _job_daily_signal_summary

            await _job_daily_signal_summary()

        mock_alert.send_alert.assert_awaited_once()
        content = mock_alert.send_alert.call_args.kwargs["content"]
        assert "今日无交易信号" in content

    @pytest.mark.asyncio
    async def test_feishu_push_failure(self):
        """飞书推送异常 → warning 日志不抛异常"""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [("BUY", 85.0, "000001.SZ", "")]
        mock_session.execute.return_value.fetchone.return_value = (1,)

        mock_alert = AsyncMock()
        mock_alert.enabled = True
        mock_alert.send_alert.side_effect = RuntimeError("飞书网络超时")

        mock_settings = MagicMock(FEISHU_WEBHOOK="https://webhook.example.com")

        with (
            patch("services.report_scheduler.get_db_session") as mock_get_db,
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings", mock_settings),
        ):
            mock_get_db.return_value.__enter__.return_value = mock_session
            from services.report_scheduler import _job_daily_signal_summary

            await _job_daily_signal_summary()  # 不抛异常

    @pytest.mark.asyncio
    async def test_exec_order_query_failure(self):
        """订单查询异常 → 降级为 0, 不抛异常"""
        mock_result1 = MagicMock()
        mock_result1.fetchall.return_value = [("BUY", 85.0, "000001.SZ", "")]
        mock_result2 = MagicMock()
        mock_result2.fetchone.side_effect = Exception("表不存在")

        mock_session = MagicMock()
        mock_session.execute.side_effect = [mock_result1, mock_result2]

        mock_alert = AsyncMock()
        mock_alert.enabled = True

        mock_settings = MagicMock(FEISHU_WEBHOOK="https://webhook.example.com")

        with (
            patch("services.report_scheduler.get_db_session") as mock_get_db,
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings", mock_settings),
        ):
            mock_get_db.return_value.__enter__.return_value = mock_session
            from services.report_scheduler import _job_daily_signal_summary

            await _job_daily_signal_summary()

        mock_alert.send_alert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_top_level_exception(self):
        """最外层异常 → error 日志不抛出"""
        with patch("services.report_scheduler.get_db_session") as mock_get_db:
            mock_get_db.side_effect = RuntimeError("DB连接失败")
            from services.report_scheduler import _job_daily_signal_summary

            await _job_daily_signal_summary()  # 不抛异常


# ============================================================
# _job_daily_report — 日报
# ============================================================


class TestJobDailyReport:
    """覆盖日报生成正常/飞书失败/DB失败/生成异常/无webhook路径"""

    SAMPLE_REPORT = {
        "report_type": "daily",
        "report_date": "2026-06-20",
        "backtest_count": 5,
        "summary": {"avg_sharpe": 0.85, "avg_return": 1.2},
        "top_strategies": [],
        "markdown": "## 日报",
    }

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """日报正常生成+推送+DB存储"""
        mock_report_service = MagicMock()
        mock_report_service.generate_daily_report.return_value = dict(self.SAMPLE_REPORT)

        mock_alert = MagicMock()

        with (
            patch("services.report_service.report_service", mock_report_service),
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings") as mock_settings,
            patch("services.report_scheduler._save_report_to_db", return_value=True),
        ):
            mock_settings.FEISHU_WEBHOOK = "https://webhook.example.com"

            from services.report_scheduler import _job_daily_report

            await _job_daily_report()

        mock_report_service.generate_daily_report.assert_called_once()
        mock_alert.send_backtest_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_feishu_push_failure(self):
        """飞书推送失败 → warning 日志"""
        mock_report_service = MagicMock()
        mock_report_service.generate_daily_report.return_value = dict(self.SAMPLE_REPORT)

        mock_alert = MagicMock()
        mock_alert.send_backtest_report.side_effect = RuntimeError("推送失败")

        with (
            patch("services.report_service.report_service", mock_report_service),
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings") as mock_settings,
            patch("services.report_scheduler._save_report_to_db", return_value=True),
        ):
            mock_settings.FEISHU_WEBHOOK = "https://webhook.example.com"

            from services.report_scheduler import _job_daily_report

            await _job_daily_report()  # 不抛异常

    @pytest.mark.asyncio
    async def test_db_save_failure(self):
        """DB 存储失败 → warning 日志"""
        mock_report_service = MagicMock()
        mock_report_service.generate_daily_report.return_value = dict(self.SAMPLE_REPORT)

        mock_alert = MagicMock()

        with (
            patch("services.report_service.report_service", mock_report_service),
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings") as mock_settings,
            patch(
                "services.report_scheduler._save_report_to_db",
                side_effect=RuntimeError("DB错误"),
            ),
        ):
            mock_settings.FEISHU_WEBHOOK = "https://webhook.example.com"

            from services.report_scheduler import _job_daily_report

            await _job_daily_report()  # 不抛异常

    @pytest.mark.asyncio
    async def test_generation_failure(self):
        """报告生成异常 → error 日志"""
        mock_report_service = MagicMock()
        mock_report_service.generate_daily_report.side_effect = ValueError("数据不足")

        with patch("services.report_service.report_service", mock_report_service):
            from services.report_scheduler import _job_daily_report

            await _job_daily_report()  # 不抛异常

    @pytest.mark.asyncio
    async def test_no_webhook_no_push(self):
        """没有 FEISHU_WEBHOOK → hasattr 为 False → 不推送"""
        mock_report_service = MagicMock()
        mock_report_service.generate_daily_report.return_value = dict(self.SAMPLE_REPORT)

        with (
            patch("services.report_service.report_service", mock_report_service),
            patch("core.config.settings", MagicMock(spec=[])),
            patch("services.report_scheduler._save_report_to_db", return_value=True),
        ):
            from services.report_scheduler import _job_daily_report

            await _job_daily_report()  # 不推送


# ============================================================
# _job_weekly_report — 周报
# ============================================================


class TestJobWeeklyReport:
    """覆盖周报正常/异常路径"""

    SAMPLE_REPORT = {
        "report_type": "weekly",
        "report_date": "2026-06-15~2026-06-20",
        "backtest_count": 25,
        "summary": {"avg_sharpe": 0.9},
        "top_strategies": [],
        "markdown": "## 周报",
    }

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """周报正常生成+推送+DB存储"""
        mock_report_service = MagicMock()
        mock_report_service.generate_weekly_report.return_value = dict(self.SAMPLE_REPORT)

        mock_alert = MagicMock()

        with (
            patch("services.report_service.report_service", mock_report_service),
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings") as mock_settings,
            patch("services.report_scheduler._save_report_to_db", return_value=True),
        ):
            mock_settings.FEISHU_WEBHOOK = "https://webhook.example.com"

            from services.report_scheduler import _job_weekly_report

            await _job_weekly_report()

        mock_report_service.generate_weekly_report.assert_called_once()
        mock_alert.send_backtest_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_path(self):
        """周报生成异常 → error 日志"""
        mock_report_service = MagicMock()
        mock_report_service.generate_weekly_report.side_effect = ValueError("周报生成失败")

        with patch("services.report_service.report_service", mock_report_service):
            from services.report_scheduler import _job_weekly_report

            await _job_weekly_report()  # 不抛异常


# ============================================================
# _job_monthly_report — 月报
# ============================================================


class TestJobMonthlyReport:
    """覆盖月报正常/异常路径"""

    SAMPLE_REPORT = {
        "report_type": "monthly",
        "report_date": "2026-06",
        "backtest_count": 100,
        "summary": {"avg_sharpe": 0.95},
        "top_strategies": [],
        "markdown": "## 月报",
    }

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """月报正常生成+推送+DB存储"""
        mock_report_service = MagicMock()
        mock_report_service.generate_monthly_report.return_value = dict(self.SAMPLE_REPORT)

        mock_alert = MagicMock()

        with (
            patch("services.report_service.report_service", mock_report_service),
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings") as mock_settings,
            patch("services.report_scheduler._save_report_to_db", return_value=True),
        ):
            mock_settings.FEISHU_WEBHOOK = "https://webhook.example.com"

            from services.report_scheduler import _job_monthly_report

            await _job_monthly_report()

        mock_report_service.generate_monthly_report.assert_called_once()
        mock_alert.send_backtest_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_path(self):
        """月报生成异常 → error 日志"""
        mock_report_service = MagicMock()
        mock_report_service.generate_monthly_report.side_effect = ValueError("月报生成失败")

        with patch("services.report_service.report_service", mock_report_service):
            from services.report_scheduler import _job_monthly_report

            await _job_monthly_report()  # 不抛异常


# ============================================================
# _job_stock_insight_mainboard — 主板精选扫描
# ============================================================


class TestJobStockInsightMainboard:
    """覆盖有结果/无结果/飞书失败/DB失败/扫描异常"""

    SAMPLE_RESULTS = [
        {"code": "000001.SZ", "name": "平安银行", "final_score": 85.3},
        {"code": "600519.SH", "name": "贵州茅台", "final_score": 92.1},
        {"code": "000002.SZ", "name": "万科A", "final_score": 78.5},
        {"code": "600036.SH", "name": "招商银行", "final_score": 81.0},
        {"code": "601166.SH", "name": "兴业银行", "final_score": 76.8},
        {"code": "600030.SH", "name": "中信证券", "final_score": 74.2},
    ]

    @pytest.mark.asyncio
    async def test_with_results(self):
        """有扫描结果 → 推送飞书 + 保存DB"""
        mock_engine = MagicMock()
        mock_engine.scan_mainboard.return_value = self.SAMPLE_RESULTS

        mock_alert = AsyncMock()
        mock_alert.enabled = True

        mock_settings = MagicMock(
            FEISHU_WEBHOOK="https://webhook.example.com", TUSHARE_TOKEN="mock"
        )

        with (
            patch("services.data_service.DataService"),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings", mock_settings),
            patch("services.report_scheduler._save_scan_result_to_db", return_value=True),
        ):
            from services.report_scheduler import _job_stock_insight_mainboard

            await _job_stock_insight_mainboard()

        mock_engine.scan_mainboard.assert_called_once_with(top_n=10)
        mock_alert.send_alert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_results(self):
        """无结果 → 不推送"""
        mock_engine = MagicMock()
        mock_engine.scan_mainboard.return_value = None

        mock_settings = MagicMock(
            FEISHU_WEBHOOK="https://webhook.example.com", TUSHARE_TOKEN="mock"
        )

        with (
            patch("services.data_service.DataService"),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch("core.config.settings", mock_settings),
            patch("services.report_scheduler._save_scan_result_to_db", return_value=True),
        ):
            from services.report_scheduler import _job_stock_insight_mainboard

            await _job_stock_insight_mainboard()

        # 不推送飞书（count=0→推送分支跳过）

    @pytest.mark.asyncio
    async def test_feishu_push_failure(self):
        """飞书推送失败 → warning 日志"""
        mock_engine = MagicMock()
        mock_engine.scan_mainboard.return_value = self.SAMPLE_RESULTS[:1]

        mock_alert = AsyncMock()
        mock_alert.enabled = True
        mock_alert.send_alert.side_effect = RuntimeError("飞书失败")

        mock_settings = MagicMock(
            FEISHU_WEBHOOK="https://webhook.example.com", TUSHARE_TOKEN="mock"
        )

        with (
            patch("services.data_service.DataService"),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings", mock_settings),
            patch("services.report_scheduler._save_scan_result_to_db", return_value=True),
        ):
            from services.report_scheduler import _job_stock_insight_mainboard

            await _job_stock_insight_mainboard()  # 不抛异常

    @pytest.mark.asyncio
    async def test_db_save_failure(self):
        """DB 保存失败 → warning 日志"""
        mock_engine = MagicMock()
        mock_engine.scan_mainboard.return_value = self.SAMPLE_RESULTS[:2]

        mock_alert = AsyncMock()
        mock_alert.enabled = True

        mock_settings = MagicMock(
            FEISHU_WEBHOOK="https://webhook.example.com", TUSHARE_TOKEN="mock"
        )

        with (
            patch("services.data_service.DataService"),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings", mock_settings),
            patch(
                "services.report_scheduler._save_scan_result_to_db",
                side_effect=RuntimeError("DB错误"),
            ),
        ):
            from services.report_scheduler import _job_stock_insight_mainboard

            await _job_stock_insight_mainboard()  # 不抛异常

    @pytest.mark.asyncio
    async def test_scan_exception(self):
        """扫描异常 → error 日志"""
        mock_engine = MagicMock()
        mock_engine.scan_mainboard.side_effect = ValueError("扫描失败")

        mock_settings = MagicMock(
            FEISHU_WEBHOOK="https://webhook.example.com", TUSHARE_TOKEN="mock"
        )

        with (
            patch("services.data_service.DataService"),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch("core.config.settings", mock_settings),
        ):
            from services.report_scheduler import _job_stock_insight_mainboard

            await _job_stock_insight_mainboard()  # 不抛异常


# ============================================================
# _job_stock_insight_rational — 理性10选股扫描
# ============================================================


class TestJobStockInsightRational:
    """覆盖长线+短线有结果/无结果/空列表/异常"""

    SAMPLE_RESULTS_MIXED = [
        {
            "code": "600519.SH",
            "name": "贵州茅台",
            "selection_type": "long_term",
            "long_final": 92.0,
            "short_final": 60.0,
        },
        {
            "code": "000001.SZ",
            "name": "平安银行",
            "selection_type": "short_term",
            "long_final": 60.0,
            "short_final": 85.0,
        },
        {
            "code": "000002.SZ",
            "name": "万科A",
            "selection_type": "long_term",
            "long_final": 78.0,
            "short_final": 55.0,
        },
        {
            "code": "600036.SH",
            "name": "招商银行",
            "selection_type": "short_term",
            "long_final": 65.0,
            "short_final": 82.0,
        },
    ]

    @pytest.mark.asyncio
    async def test_with_long_and_short_term(self):
        """长线+短线混合 → 推送包含两类精选"""
        mock_engine = MagicMock()
        mock_engine.scan_rational.return_value = self.SAMPLE_RESULTS_MIXED

        mock_alert = AsyncMock()
        mock_alert.enabled = True

        mock_settings = MagicMock(
            FEISHU_WEBHOOK="https://webhook.example.com", TUSHARE_TOKEN="mock"
        )

        with (
            patch("services.data_service.DataService"),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch("services.feishu_alert.get_alert_service", return_value=mock_alert),
            patch("core.config.settings", mock_settings),
            patch("services.report_scheduler._save_scan_result_to_db", return_value=True),
        ):
            from services.report_scheduler import _job_stock_insight_rational

            await _job_stock_insight_rational()

        mock_engine.scan_rational.assert_called_once_with(top_n=10)
        mock_alert.send_alert.assert_awaited_once()
        content = mock_alert.send_alert.call_args.kwargs["content"]
        assert "长线" in content
        assert "短线" in content
        assert "贵州茅台" in content
        assert "平安银行" in content

    @pytest.mark.asyncio
    async def test_no_results(self):
        """无结果 (None) → 不推送"""
        mock_engine = MagicMock()
        mock_engine.scan_rational.return_value = None

        mock_settings = MagicMock(
            FEISHU_WEBHOOK="https://webhook.example.com", TUSHARE_TOKEN="mock"
        )

        with (
            patch("services.data_service.DataService"),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch("core.config.settings", mock_settings),
            patch("services.report_scheduler._save_scan_result_to_db", return_value=True),
        ):
            from services.report_scheduler import _job_stock_insight_rational

            await _job_stock_insight_rational()

    @pytest.mark.asyncio
    async def test_empty_results_list(self):
        """空列表 → 不推送"""
        mock_engine = MagicMock()
        mock_engine.scan_rational.return_value = []

        mock_settings = MagicMock(
            FEISHU_WEBHOOK="https://webhook.example.com", TUSHARE_TOKEN="mock"
        )

        with (
            patch("services.data_service.DataService"),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch("core.config.settings", mock_settings),
            patch("services.report_scheduler._save_scan_result_to_db", return_value=True),
        ):
            from services.report_scheduler import _job_stock_insight_rational

            await _job_stock_insight_rational()

    @pytest.mark.asyncio
    async def test_scan_exception(self):
        """扫描异常 → error 日志"""
        mock_engine = MagicMock()
        mock_engine.scan_rational.side_effect = ValueError("理性扫描失败")

        mock_settings = MagicMock(
            FEISHU_WEBHOOK="https://webhook.example.com", TUSHARE_TOKEN="mock"
        )

        with (
            patch("services.data_service.DataService"),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch("core.config.settings", mock_settings),
        ):
            from services.report_scheduler import _job_stock_insight_rational

            await _job_stock_insight_rational()  # 不抛异常


# ============================================================
# _save_scan_result_to_db — 选股扫描结果 DB 存储
# ============================================================


class TestSaveScanResultToDb:
    """覆盖 DB 存储成功/空列表/失败路径"""

    SAMPLE_RESULTS = [
        {"code": "000001.SZ", "name": "平安银行", "final_score": 85.0},
    ]

    def test_success(self):
        """正常存储返回 True"""
        mock_session = MagicMock()

        with patch("services.report_scheduler.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_session
            from services.report_scheduler import _save_scan_result_to_db

            result = _save_scan_result_to_db("mainboard", self.SAMPLE_RESULTS)
            assert result is True

    def test_success_with_no_results(self):
        """空结果列表也正常存储"""
        mock_session = MagicMock()

        with patch("services.report_scheduler.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_session
            from services.report_scheduler import _save_scan_result_to_db

            result = _save_scan_result_to_db("rational", None)
            assert result is True

    def test_db_exception_returns_false(self):
        """DB 异常 → 返回 False"""
        with patch("services.report_scheduler.get_db_session") as mock_get_db:
            mock_get_db.side_effect = RuntimeError("DB 连接失败")
            from services.report_scheduler import _save_scan_result_to_db

            result = _save_scan_result_to_db("mainboard", self.SAMPLE_RESULTS)
            assert result is False


# ============================================================
# _save_report_to_db — 报告 DB 存储
# ============================================================


class TestSaveReportToDb:
    """覆盖报告 DB 存储成功/无report_date/失败"""

    SAMPLE_REPORT = {
        "report_type": "daily",
        "report_date": "2026-06-20",
        "backtest_count": 5,
        "top_strategies": [
            {"ts_code": "000001.SZ", "strategy": "ma-cross", "sharpe": 1.5},
        ],
        "summary": {"avg_sharpe": 0.85, "avg_return": 1.2},
        "markdown": "## 报告内容",
    }

    def test_success(self):
        """正常存储返回 True"""
        mock_session = MagicMock()

        with patch("services.report_scheduler.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_session
            from services.report_scheduler import _save_report_to_db

            result = _save_report_to_db(self.SAMPLE_REPORT)
            assert result is True
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

    def test_report_without_date(self):
        """report 没有 report_date → 使用今天"""
        mock_session = MagicMock()

        report_no_date = dict(self.SAMPLE_REPORT)
        del report_no_date["report_date"]

        with patch("services.report_scheduler.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_session
            from services.report_scheduler import _save_report_to_db

            result = _save_report_to_db(report_no_date)
            assert result is True

    def test_db_exception_returns_false(self):
        """DB 异常 → 返回 False"""
        with patch("services.report_scheduler.get_db_session") as mock_get_db:
            mock_get_db.side_effect = RuntimeError("DB 连接失败")
            from services.report_scheduler import _save_report_to_db

            result = _save_report_to_db(self.SAMPLE_REPORT)
            assert result is False
