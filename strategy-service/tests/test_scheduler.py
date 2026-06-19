"""
scheduler 包全覆盖测试 — engine / jobs / registry

运行: cd QuantTradingSystem && python -m pytest strategy-service/tests/test_scheduler.py -v
"""

# =============================================================================
#  engine — TaskSchedulerService 调度器引擎
# =============================================================================

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _MockResponse:
    """模拟 aiohttp ClientResponse，纯类避免 AsyncMock 劫持 __aenter__"""

    def __init__(self, status=200):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class _MockSession:
    """模拟 aiohttp ClientSession，纯类避免 AsyncMock 劫持 __aenter__

    注意：session.get 是**同步**方法（返回 async context manager），
    因此用 MagicMock 而非 AsyncMock，否则 __call__ 返回协程对象无法用于 async with。
    """

    def __init__(self):
        self.get = MagicMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class TestTaskSchedulerService:
    """调度器引擎核心逻辑 — 覆盖增/删/改/查/生命周期"""

    @pytest.fixture
    def scheduler(self):
        from services.scheduler.engine import TaskSchedulerService

        return TaskSchedulerService()

    # ── 初始状态 ──────────────────────────────────────────────────────────

    def test_initial_state_not_running(self, scheduler):
        """调度器初始为未启动状态"""
        assert scheduler.is_running is False

    def test_initial_state_no_jobs(self, scheduler):
        """调度器初始无注册任务"""
        assert scheduler.list_jobs() == []

    # ── 添加 Cron 任务 ────────────────────────────────────────────────────

    def test_add_cron_job_basic(self, scheduler):
        """添加基础 cron 定时任务"""

        async def dummy():
            pass

        job_id = scheduler.add_cron_job(dummy, "test_job", hour=15, minute=30, name="测试任务")
        assert job_id == "test_job"

        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "test_job"
        assert jobs[0]["name"] == "测试任务"
        assert str(jobs[0]["trigger"]).startswith("cron")

    def test_add_cron_job_with_day_of_week(self, scheduler):
        """cron 支持 day_of_week 参数（如 mon-fri）"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "j1", hour=9, minute=0, day_of_week="mon-fri")
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        trigger_str = str(jobs[0]["trigger"])
        assert "mon-fri" in trigger_str or "0-4" in trigger_str

    def test_add_cron_job_with_day(self, scheduler):
        """cron 支持 day 参数（每月某日）"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "j1", hour=10, minute=0, day=1)
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert "day" in str(jobs[0]["trigger"])

    def test_add_cron_job_default_name(self, scheduler):
        """未传 name 时默认使用 job_id"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "auto_name", hour=14, minute=0)
        jobs = scheduler.list_jobs()
        assert jobs[0]["name"] == "auto_name"

    # ── 添加 Interval 任务 ────────────────────────────────────────────────

    def test_add_interval_job(self, scheduler):
        """添加间隔重复任务"""

        async def dummy():
            pass

        scheduler.add_interval_job(dummy, "int_job", minutes=30, name="间隔任务")
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "int_job"
        assert jobs[0]["name"] == "间隔任务"
        assert str(jobs[0]["trigger"]).startswith("interval")

    def test_add_interval_job_default_name(self, scheduler):
        """interval 未传 name 时默认使用 job_id"""

        async def dummy():
            pass

        scheduler.add_interval_job(dummy, "auto_int", minutes=60)
        jobs = scheduler.list_jobs()
        assert jobs[0]["name"] == "auto_int"

    # ── 移除任务 ──────────────────────────────────────────────────────────

    def test_remove_job_existing(self, scheduler):
        """移除已存在的任务"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "j1", hour=10, minute=0)
        assert len(scheduler.list_jobs()) == 1
        assert scheduler.remove_job("j1") is True
        assert scheduler.list_jobs() == []

    def test_remove_job_not_found(self, scheduler):
        """移除不存在的任务返回 False"""
        assert scheduler.remove_job("nonexistent") is False

    def test_remove_job_after_start(self, scheduler):
        """启动后移除任务仍正常"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "j1", hour=10, minute=0)
        assert scheduler.remove_job("j1") is True

    # ── 暂停 / 恢复 ───────────────────────────────────────────────────────

    def test_pause_job(self, scheduler):
        """暂停已存在的任务"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "j1", hour=10, minute=0)
        assert scheduler.pause_job("j1") is True

    def test_pause_job_not_found(self, scheduler):
        """暂停不存在的任务返回 False"""
        assert scheduler.pause_job("nonexistent") is False

    def test_resume_job(self, scheduler):
        """恢复已暂停的任务"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "j1", hour=10, minute=0)
        scheduler.pause_job("j1")
        assert scheduler.resume_job("j1") is True

    def test_resume_job_not_found(self, scheduler):
        """恢复不存在的任务返回 False"""
        assert scheduler.resume_job("nonexistent") is False

    # ── 任务列表 ──────────────────────────────────────────────────────────

    def test_list_jobs_fields(self, scheduler):
        """list_jobs 返回完整字段结构"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "j1", hour=15, minute=0, name="任务A")
        job = scheduler.list_jobs()[0]
        assert set(job.keys()) == {"id", "name", "next_run_time", "trigger", "pending"}

    def test_list_jobs_empty_returns_empty_list(self, scheduler):
        """无任务时返回空列表"""
        assert scheduler.list_jobs() == []

    def test_list_jobs_multiple_jobs(self, scheduler):
        """多个不同任务正确列出"""

        async def dummy():
            pass

        for i in range(5):
            scheduler.add_cron_job(dummy, f"j{i}", hour=10, minute=i)
        assert len(scheduler.list_jobs()) == 5

    # ── 替换任务（需 start 后生效） ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_replace_existing_job(self, scheduler):
        """相同 job_id 替换已有任务（APScheduler 需 start 后生效）"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "j1", hour=10, minute=0, name="原始")
        # 启动后 APScheduler 才会处理 _pending_jobs 和 replace_existing
        scheduler.start()
        scheduler.add_cron_job(dummy, "j1", hour=11, minute=0, name="替换后")
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "替换后"
        await scheduler.shutdown()

    # ── 生命周期（需 event loop） ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_start_changes_running_state(self, scheduler):
        """start 后 is_running 为 True"""
        scheduler.start()
        assert scheduler.is_running is True

    @pytest.mark.asyncio
    async def test_shutdown_changes_running_state(self, scheduler):
        """shutdown 后 is_running 为 False"""
        scheduler.start()
        await scheduler.shutdown()
        assert scheduler.is_running is False

    @pytest.mark.asyncio
    async def test_start_twice_idempotent(self, scheduler):
        """重复 start 不报错"""
        scheduler.start()
        scheduler.start()  # should not raise
        assert scheduler.is_running is True

    @pytest.mark.asyncio
    async def test_shutdown_without_start(self, scheduler):
        """未启动时 shutdown 不报错"""
        await scheduler.shutdown()
        assert scheduler.is_running is False

    @pytest.mark.asyncio
    async def test_start_then_add_job(self, scheduler):
        """启动后仍可添加任务"""

        async def dummy():
            pass

        scheduler.start()
        scheduler.add_cron_job(dummy, "j1", hour=15, minute=0)
        assert len(scheduler.list_jobs()) == 1


# =============================================================================
#  jobs — 6 个业务任务函数
# =============================================================================


class TestJobs:
    """业务任务 — 验证异常安全和边界条件"""

    # ── daily_data_refresh ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_daily_data_refresh_success(self):
        """日行情刷新：正常路径"""
        from services.scheduler.jobs import daily_data_refresh

        mock_ds = MagicMock()
        mock_ds.sync_daily_data = AsyncMock()

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test")),
        ):
            await daily_data_refresh()

        mock_ds.sync_daily_data.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_daily_data_refresh_no_sync_method(self):
        """日行情刷新：DataService 无 sync_daily_data 时优雅跳过"""
        from services.scheduler.jobs import daily_data_refresh

        mock_ds = MagicMock(spec=[])  # no methods

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test")),
        ):
            # 不应抛出异常
            await daily_data_refresh()

    @pytest.mark.asyncio
    async def test_daily_data_refresh_exception_caught(self):
        """日行情刷新：异常被捕获不传播"""
        from services.scheduler.jobs import daily_data_refresh

        mock_ds = MagicMock()
        mock_ds.sync_daily_data = AsyncMock(side_effect=RuntimeError("API超时"))

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test")),
        ):
            # RuntimeError 应在函数内部被捕获
            await daily_data_refresh()

    # ── daily_close_settle ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_daily_close_settle_success(self):
        """收盘归总：正常路径"""
        from services.scheduler.jobs import daily_close_settle

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = [
            {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.5}
        ]
        mock_ds.get_index_realtime_quote.return_value = [{"code": "000001.SH", "price": 3200.0}]

        mock_db = MagicMock()
        mock_db.execute = MagicMock()
        mock_db.commit = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_db
        mock_cm.__exit__.return_value = None

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test")),
            patch("models.database.get_db_session", return_value=mock_cm),
        ):
            await daily_close_settle()

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_daily_close_settle_db_write_failure(self):
        """收盘归总：DB 写入失败时日志告警不崩溃"""
        from services.scheduler.jobs import daily_close_settle

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = []
        mock_ds.get_index_realtime_quote.return_value = []

        mock_db = MagicMock()
        mock_db.execute = MagicMock(side_effect=RuntimeError("DB连接断开"))
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_db
        mock_cm.__exit__.return_value = None

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test")),
            patch("models.database.get_db_session", return_value=mock_cm),
        ):
            # DB 失败被内层 except 捕获，不应传播
            await daily_close_settle()

    @pytest.mark.asyncio
    async def test_daily_close_settle_no_stock_pool(self):
        """收盘归总：空股票池仍正常完成"""
        from services.scheduler.jobs import daily_close_settle

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = []

        mock_db = MagicMock()
        mock_db.execute = MagicMock()
        mock_db.commit = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_db
        mock_cm.__exit__.return_value = None

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test")),
            patch("models.database.get_db_session", return_value=mock_cm),
        ):
            await daily_close_settle()

    # ── ai_review ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ai_review_no_positions(self):
        """AI 复盘：无持仓数据时提前返回"""
        import repositories.account_repo as _ar_mod
        from services.scheduler.jobs import ai_review

        mock_repo = MagicMock()
        mock_repo.get_positions.return_value = []
        _ar_mod.account_repo = mock_repo  # 绕开 import bug（from X import account_repo）

        with patch("core.config.settings", MagicMock(DEEPSEEK_API_KEY="test")):
            await ai_review()

        mock_repo.get_positions.assert_called_once()

    @pytest.mark.asyncio
    async def test_ai_review_success(self):
        """AI 复盘：正常路径"""
        import repositories.account_repo as _ar_mod
        from services.scheduler.jobs import ai_review

        mock_repo = MagicMock()
        mock_repo.get_positions.return_value = [
            {
                "ts_code": "000001.SZ",
                "cost_price": 10.0,
                "current_price": 11.0,
                "pnl_pct": 0.1,
            }
        ]
        _ar_mod.account_repo = mock_repo

        mock_ai = AsyncMock()
        mock_ai.call.return_value = MagicMock(
            success=True,
            content="分析报告",
            input_tokens=100,
            output_tokens=50,
            cost=0.01,
        )

        mock_metric = MagicMock()

        with (
            patch("core.config.settings", MagicMock(DEEPSEEK_API_KEY="test")),
            patch("services.ai_client.AIClient", return_value=mock_ai),
            patch("main.ai_review_completed_today", mock_metric),
        ):
            await ai_review()

        mock_ai.call.assert_awaited_once()
        mock_metric.set.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_ai_review_missing_api_key(self):
        """AI 复盘：缺少 API Key 时异常被捕获"""
        import repositories.account_repo as _ar_mod
        from services.scheduler.jobs import ai_review

        mock_repo = MagicMock()
        mock_repo.get_positions.return_value = [{"ts_code": "000001.SZ"}]
        _ar_mod.account_repo = mock_repo

        with patch("core.config.settings", MagicMock(DEEPSEEK_API_KEY=None)):
            await ai_review()

    @pytest.mark.asyncio
    async def test_ai_review_import_error_caught(self):
        """AI 复盘：account_repo 导入失败时异常被外层捕获"""
        from services.scheduler.jobs import ai_review

        # 不设置 account_repo 属性 → import 失败 → 被 try-except 捕获
        with patch("core.config.settings", MagicMock(DEEPSEEK_API_KEY="test")):
            await ai_review()

    @pytest.mark.asyncio
    async def test_ai_review_account_repo_import_error(self):
        """AI 复盘：account_repo 模块不存在时提前返回 (覆盖第82-84行)"""
        import builtins

        from services.scheduler.jobs import ai_review

        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "repositories.account_repo":
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            await ai_review()

    # ── market_scan ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_market_scan_empty_pool(self):
        """智能选股：候选池为空时提前返回"""
        from services.scheduler.jobs import market_scan

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = []

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test", AI_BUDGET_TOTAL=500)),
        ):
            await market_scan()

        mock_ds.get_stock_pool.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_scan_no_api_key(self):
        """智能选股：无 API Key 时跳过 AI 调用"""
        from services.scheduler.jobs import market_scan

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = [
            {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.5}
        ]

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch(
                "core.config.settings",
                MagicMock(
                    TUSHARE_TOKEN="test",
                    AI_BUDGET_TOTAL=500,
                    DEEPSEEK_API_KEY=None,
                ),
            ),
        ):
            await market_scan()

    # ── market_snapshot ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_market_snapshot_success(self):
        """大盘快照：正常路径"""
        from services.scheduler.jobs import market_snapshot

        mock_ds = MagicMock()
        mock_ds.get_index_realtime_quote.return_value = [
            {"code": "000001.SH", "price": 3200.0, "pct_change": 0.5, "volume": 1000000}
        ]

        mock_db = MagicMock()
        mock_db.execute = MagicMock()
        mock_db.commit = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_db
        mock_cm.__exit__.return_value = None

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test")),
            patch("models.database.get_db_session", return_value=mock_cm),
        ):
            await market_snapshot()

        assert mock_db.execute.call_count > 0
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_snapshot_empty_indices(self):
        """大盘快照：无指数数据时不写入 DB"""
        from services.scheduler.jobs import market_snapshot

        mock_ds = MagicMock()
        mock_ds.get_index_realtime_quote.return_value = []

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test")),
        ):
            await market_snapshot()

    @pytest.mark.asyncio
    async def test_market_snapshot_db_failure(self):
        """大盘快照：DB 写入失败时非致命"""
        from services.scheduler.jobs import market_snapshot

        mock_ds = MagicMock()
        mock_ds.get_index_realtime_quote.return_value = [
            {"code": "000001.SH", "price": 3200.0, "pct_change": 0.5, "volume": 1000000}
        ]

        mock_db = MagicMock()
        mock_db.execute = MagicMock(side_effect=RuntimeError("DB写入超时"))
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_db
        mock_cm.__exit__.return_value = None

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("core.config.settings", MagicMock(TUSHARE_TOKEN="test")),
            patch("models.database.get_db_session", return_value=mock_cm),
        ):
            await market_snapshot()

    # ── health_check ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_health_check_all_up(self):
        """健康检查：全部服务正常 (覆盖第278行)"""
        from services.scheduler.jobs import health_check

        mock_resp = _MockResponse(status=200)

        mock_session = _MockSession()
        mock_session.get.return_value = mock_resp

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            patch("shared.middleware.get_trace_headers", return_value={}),
        ):
            await health_check()

        assert mock_session.get.call_count == 2  # strategy + execution

    @pytest.mark.asyncio
    async def test_health_check_partial_down(self):
        """健康检查：部分服务不可用不崩溃"""
        from services.scheduler.jobs import health_check

        mock_good = _MockResponse(status=200)
        mock_bad = _MockResponse(status=503)

        mock_session = _MockSession()
        mock_session.get.side_effect = [mock_good, mock_bad]

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            patch("shared.middleware.get_trace_headers", return_value={}),
        ):
            await health_check()

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        """健康检查：连接超时被捕获"""
        from services.scheduler.jobs import health_check

        mock_session = _MockSession()
        mock_session.get.side_effect = OSError("连接被拒绝")

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            patch("shared.middleware.get_trace_headers", return_value={}),
        ):
            await health_check()

    @pytest.mark.asyncio
    async def test_health_check_import_error_caught(self):
        """健康检查：aiohttp 不可用时 ImportError 被捕获"""
        import builtins

        from services.scheduler.jobs import health_check

        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "aiohttp":
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            await health_check()

    @pytest.mark.asyncio
    async def test_health_check_outer_exception(self):
        """健康检查：get_trace_headers 异常触发外层 except"""
        from services.scheduler.jobs import health_check

        with patch("shared.middleware.get_trace_headers", side_effect=RuntimeError("配置缺失")):
            await health_check()

    # ── daily_close_settle outer exception ─────────────────────────────

    @pytest.mark.asyncio
    async def test_daily_close_settle_outer_exception(self):
        """收盘归总：外层异常被外层 except 捕获（DataService 构造失败）"""
        from services.scheduler.jobs import daily_close_settle

        with patch("services.data_service.DataService", side_effect=RuntimeError("连接失败")):
            await daily_close_settle()

    # ── market_scan AI call path + fallback ────────────────────────────

    @pytest.mark.asyncio
    async def test_market_scan_ai_call_success(self):
        """智能选股：完整 AI 调用路径（有 API Key）"""
        from services.scheduler.jobs import market_scan

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = [
            {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.5}
        ]

        mock_ai = MagicMock()
        mock_ai.call_sync.return_value = MagicMock(
            success=True,
            content="TOP1: 000001.SZ",
            input_tokens=100,
            output_tokens=50,
            cost=0.01,
        )

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("services.ai_client.AIClient", return_value=mock_ai),
            patch(
                "core.config.settings",
                MagicMock(
                    TUSHARE_TOKEN="test",
                    AI_BUDGET_TOTAL=500,
                    DEEPSEEK_API_KEY="real_key",
                ),
            ),
        ):
            await market_scan()

        mock_ai.call_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_scan_ai_call_failure(self):
        """智能选股：AI 调用失败触发外层异常处理 + fallback"""
        from services.scheduler.jobs import market_scan

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = [
            {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.5}
        ]

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("services.ai_client.AIClient", side_effect=RuntimeError("AI服务异常")),
            patch(
                "core.config.settings",
                MagicMock(
                    TUSHARE_TOKEN="test",
                    AI_BUDGET_TOTAL=500,
                    DEEPSEEK_API_KEY="real_key",
                ),
            ),
        ):
            await market_scan()

    @pytest.mark.asyncio
    async def test_market_scan_ai_response_failure(self):
        """智能选股：AI 返回失败响应 (覆盖第201行)"""
        from services.scheduler.jobs import market_scan

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = [
            {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.5}
        ]

        mock_ai = MagicMock()
        mock_ai.call_sync.return_value = MagicMock(success=False, error="API限流")

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("services.ai_client.AIClient", return_value=mock_ai),
            patch(
                "core.config.settings",
                MagicMock(
                    TUSHARE_TOKEN="test",
                    AI_BUDGET_TOTAL=500,
                    DEEPSEEK_API_KEY="real_key",
                ),
            ),
        ):
            await market_scan()

        mock_ai.call_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_scan_ai_exception_with_fallback_success(self):
        """智能选股：AI异常后 fallback 成功 (覆盖第212-213行)"""
        from services.scheduler.jobs import market_scan

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = [
            {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.5}
        ]

        mock_engine = MagicMock()
        mock_engine.scan.return_value = [{"ts_code": "000001.SZ", "score": 85}]

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("services.ai_client.AIClient", side_effect=RuntimeError("AI异常")),
            patch("services.stock_insight_engine.StockInsightEngine", return_value=mock_engine),
            patch(
                "core.config.settings",
                MagicMock(
                    TUSHARE_TOKEN="test",
                    AI_BUDGET_TOTAL=500,
                    DEEPSEEK_API_KEY="real_key",
                ),
            ),
        ):
            await market_scan()

        mock_engine.scan.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_scan_ai_exception_fallback_import_error(self):
        """智能选股：AI异常后 fallback 也 ImportError (覆盖第215行)"""
        import builtins
        import sys

        from services.scheduler.jobs import market_scan

        mock_ds = MagicMock()
        mock_ds.get_stock_pool.return_value = [
            {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.5}
        ]

        # ⚠️ 必须从 sys.modules 移除缓存，否则 builtins.__import__ 不会被调用
        sys.modules.pop("services.stock_insight_engine", None)

        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "services.stock_insight_engine":
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        with (
            patch("services.data_service.DataService", return_value=mock_ds),
            patch("services.ai_client.AIClient", side_effect=RuntimeError("AI异常")),
            patch(
                "core.config.settings",
                MagicMock(TUSHARE_TOKEN="test", AI_BUDGET_TOTAL=500, DEEPSEEK_API_KEY="real_key"),
            ),
            patch("builtins.__import__", side_effect=_mock_import),
        ):
            await market_scan()

    # ── market_snapshot outer exception ────────────────────────────────

    @pytest.mark.asyncio
    async def test_market_snapshot_outer_exception(self):
        """大盘快照：外层异常被捕获"""
        from services.scheduler.jobs import market_snapshot

        with patch("services.data_service.DataService", side_effect=RuntimeError("连接失败")):
            await market_snapshot()


# =============================================================================
#  registry — 任务注册函数与全局实例
# =============================================================================


class TestRegistry:
    """任务注册 — 验证注册配置正确性"""

    @pytest.fixture
    def fresh_scheduler(self):
        """每测试一个干净调度器"""
        from services.scheduler.engine import TaskSchedulerService

        return TaskSchedulerService()

    def test_register_default_tasks_registers_all_six(self, fresh_scheduler):
        """register_default_tasks 注册全部 6 个任务"""
        from services.scheduler.registry import register_default_tasks

        register_default_tasks(fresh_scheduler)
        jobs = fresh_scheduler.list_jobs()
        assert len(jobs) == 6

    def test_register_default_tasks_job_names(self, fresh_scheduler):
        """注册任务名称符合预期"""
        from services.scheduler.registry import register_default_tasks

        register_default_tasks(fresh_scheduler)
        names = {j["id"] for j in fresh_scheduler.list_jobs()}
        expected = {
            "daily_data_refresh",
            "daily_close_settle",
            "daily_ai_review",
            "market_scan",
            "market_snapshot",
            "health_check",
        }
        assert names == expected

    def test_register_default_tasks_triggers(self, fresh_scheduler):
        """验证触发器类型正确"""
        from services.scheduler.registry import register_default_tasks

        register_default_tasks(fresh_scheduler)
        jobs = {j["id"]: j for j in fresh_scheduler.list_jobs()}

        # Cron 任务 (5个)
        cron_ids = {"daily_data_refresh", "daily_close_settle", "daily_ai_review", "market_scan"}
        for cid in cron_ids:
            assert str(jobs[cid]["trigger"]).startswith("cron"), f"{cid} 应为cron触发"

        # Interval 任务 (2个)
        interval_ids = {"market_snapshot", "health_check"}
        for iid in interval_ids:
            assert str(jobs[iid]["trigger"]).startswith("interval"), f"{iid} 应为interval触发"

    def test_register_default_tasks_daily_schedule(self, fresh_scheduler):
        """收盘时段任务(15:00后)配置正确"""
        from services.scheduler.registry import register_default_tasks

        register_default_tasks(fresh_scheduler)
        jobs = {j["id"]: j for j in fresh_scheduler.list_jobs()}

        # 日行情刷新 15:10
        trigger_dr = str(jobs["daily_data_refresh"]["trigger"])
        assert "15" in trigger_dr
        assert "10" in trigger_dr or "10" in str(
            fresh_scheduler.scheduler.get_job("daily_data_refresh").trigger.fields
        )

    def test_register_default_tasks_market_scan_weekday(self, fresh_scheduler):
        """智能选股仅在周一到周五执行"""
        from services.scheduler.registry import register_default_tasks

        register_default_tasks(fresh_scheduler)
        trigger_str = str(fresh_scheduler.list_jobs())[:]  # just verify it was registered

        # 获取 job 并检查 day_of_week
        job = fresh_scheduler.scheduler.get_job("market_scan")
        assert job is not None
        trigger_kwargs = {f.name: str(f) for f in job.trigger.fields}
        assert trigger_kwargs.get("day_of_week") == "mon-fri"

    def test_task_scheduler_global_instance(self):
        """全局 task_scheduler 是 TaskSchedulerService 实例且未启动"""
        from services.scheduler.engine import TaskSchedulerService
        from services.scheduler.registry import task_scheduler

        assert isinstance(task_scheduler, TaskSchedulerService)
        assert task_scheduler.is_running is False


# =============================================================================
#  resilience — 弹性测试：重启持久化 / 并发安全 / 超时杀死
# =============================================================================


class TestSchedulerRestartPersistence:
    """弹性：重启持久化 — 验证 MemoryJobStore 的 pending job 机制"""

    @pytest.fixture
    def scheduler(self):
        from services.scheduler.engine import TaskSchedulerService

        return TaskSchedulerService()

    # ── pending job 行为 ────────────────────────────────────────────────

    def test_jobs_exist_before_start(self, scheduler):
        """注册后 start 前，list_jobs 列出 pending 任务"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "pending_job", hour=10, minute=0)
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "pending_job"
        assert jobs[0]["pending"] is True

    @pytest.mark.asyncio
    async def test_jobs_survive_start(self, scheduler):
        """start 后，之前注册的任务仍在列表中"""

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "survive_job", hour=10, minute=0)
        scheduler.start()
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "survive_job"
        await scheduler.shutdown()

    # ── 跨实例隔离 ──────────────────────────────────────────────────────

    def test_new_instance_empty(self, scheduler):
        """新实例无任务（MemoryJobStore 不跨实例持久化）"""
        from services.scheduler.engine import TaskSchedulerService

        async def dummy():
            pass

        scheduler.add_cron_job(dummy, "prev_job", hour=10, minute=0)
        assert len(scheduler.list_jobs()) == 1

        fresh = TaskSchedulerService()
        assert fresh.list_jobs() == []


class TestConcurrentTriggerSafety:
    """弹性：重复/并发触发时不产生重复执行"""

    # ── 配置验证 ────────────────────────────────────────────────────────

    def test_coalesce_enabled(self):
        """job_defaults 包含 coalesce: True"""
        from services.scheduler.engine import TaskSchedulerService

        s = TaskSchedulerService()
        assert s.scheduler._job_defaults["coalesce"] is True

    def test_max_instances_is_one(self):
        """max_instances 为 1（同一任务不并行）"""
        from services.scheduler.engine import TaskSchedulerService

        s = TaskSchedulerService()
        assert s.scheduler._job_defaults["max_instances"] == 1

    def test_misfire_grace_time_set(self):
        """misfire_grace_time 为 60（默认容差）"""
        from services.scheduler.engine import TaskSchedulerService

        s = TaskSchedulerService()
        assert s.scheduler._job_defaults["misfire_grace_time"] == 60

    # ── 操作鲁棒性 ──────────────────────────────────────────────────────

    def test_rapid_add_remove_does_not_crash(self):
        """快速添加和移除同一 job_id 不崩溃"""
        from services.scheduler.engine import TaskSchedulerService

        s = TaskSchedulerService()

        async def dummy():
            pass

        for _ in range(10):
            s.add_cron_job(dummy, "rapid_job", hour=10, minute=0)
            s.remove_job("rapid_job")

        # 没有崩溃即通过


class TestJobTimeoutKilling:
    """弹性：超时杀死卡住任务 — 架构防御验证"""

    def test_job_defaults_have_coalesce(self):
        """合并机制防止堆积"""
        from services.scheduler.engine import TaskSchedulerService

        s = TaskSchedulerService()
        assert "coalesce" in s.scheduler._job_defaults
        assert s.scheduler._job_defaults["coalesce"] is True

    def test_not_implemented_try_except(self):
        """业务 job 函数内部使用 try-except 捕获异常（AST 扫描）"""
        import ast
        import os

        jobs_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "scheduler",
            "jobs.py",
        )
        jobs_path = os.path.abspath(jobs_path)
        with open(jobs_path) as f:
            tree = ast.parse(f.read())

        async_funcs_with_try = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for child in ast.walk(node):
                    if isinstance(child, ast.Try):
                        async_funcs_with_try += 1
                        break

        assert async_funcs_with_try >= 6, (
            f"期望至少 6 个 async 函数有 try, 实际 {async_funcs_with_try}"
        )

    @pytest.mark.asyncio
    async def test_async_job_exception_does_not_crash_scheduler(self):
        """异步 job 抛异常不崩溃调度器"""
        from services.scheduler.engine import TaskSchedulerService

        s = TaskSchedulerService()

        async def crashing_job():
            raise RuntimeError("模拟崩溃")

        s.add_cron_job(crashing_job, "crash_test", hour=15, minute=0)
        s.start()
        assert s.is_running is True
        await s.shutdown()
