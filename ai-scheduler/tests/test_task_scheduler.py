"""
services/task_scheduler.py 单元测试
覆盖: TaskScheduler 的 execute_scan / execute_review 完整生命周期
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def task_store():
    """空任务存储（模拟 api.schedule._tasks）"""
    return {}


# ─── Scan 任务测试 ───────────────────────────────────────────────────


class TestTaskSchedulerExecuteScan:
    """execute_scan 完整生命周期"""

    @pytest.mark.asyncio
    async def test_scan_full_success(self, task_store):
        """完整 scan 流程：策略扫描 → AI 分析 → 完成"""
        from services.task_scheduler import TaskScheduler

        # 创建任务条目
        task_store["scan-001"] = {
            "task_id": "scan-001",
            "task_type": "scan",
            "status": "pending",
            "progress": 0.0,
            "message": "初始",
        }

        mock_strategy = AsyncMock()
        mock_strategy.scan_stocks.return_value = [
            {"ts_code": "600519.SH", "name": "贵州茅台", "price": 1880.0},
            {"ts_code": "000858.SZ", "name": "五粮液", "price": 168.0},
        ]

        mock_llm = AsyncMock()
        mock_llm.analyze_stock.return_value = "技术面表现强势..."

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch(
                "services.task_scheduler.asyncio.ensure_future",
            ):
                await scheduler.execute_scan(
                    "scan-001",
                    {
                        "limit": 100,
                        "strategy_ids": None,
                        "ts_codes": None,
                        "ai_analysis": True,
                    },
                )

        # 验证最终状态
        task = task_store["scan-001"]
        assert task["status"] == "completed"
        assert task["progress"] == 1.0
        assert "扫描完成" in task["message"]

        # 验证调用顺序
        mock_strategy.scan_stocks.assert_awaited_once_with(
            limit=100,
            strategy_ids=None,
            ts_codes=None,
        )
        assert mock_llm.analyze_stock.await_count == 2  # 两只股票

    @pytest.mark.asyncio
    async def test_scan_skip_ai_analysis(self, task_store):
        """跳过 AI 分析"""
        from services.task_scheduler import TaskScheduler

        task_store["scan-002"] = {
            "task_id": "scan-002",
            "task_type": "scan",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_strategy.scan_stocks.return_value = [
            {"ts_code": "600519.SH", "name": "贵州茅台"},
        ]

        mock_llm = AsyncMock()

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_scan(
                    "scan-002",
                    {
                        "limit": 50,
                        "ai_analysis": False,
                    },
                )

        task = task_store["scan-002"]
        assert task["status"] == "completed"
        assert "跳过AI分析" in task["message"]
        assert "扫描完成" in task["message"]
        mock_llm.analyze_stock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scan_ai_analysis_failure(self, task_store):
        """AI 分析失败时不应中断整体流程"""
        from services.task_scheduler import TaskScheduler

        task_store["scan-003"] = {
            "task_id": "scan-003",
            "task_type": "scan",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_strategy.scan_stocks.return_value = [
            {"ts_code": "600519.SH"},
            {"ts_code": "000858.SZ"},
        ]

        mock_llm = AsyncMock()
        mock_llm.analyze_stock.side_effect = Exception("API超时")

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_scan(
                    "scan-003",
                    {
                        "limit": 100,
                        "ai_analysis": True,
                    },
                )

        # 即使 AI 全部失败，整体任务仍应完成
        task = task_store["scan-003"]
        assert task["status"] == "completed"
        assert task["progress"] == 1.0

    @pytest.mark.asyncio
    async def test_scan_empty_candidates(self, task_store):
        """策略服务返回空列表"""
        from services.task_scheduler import TaskScheduler

        task_store["scan-004"] = {
            "task_id": "scan-004",
            "task_type": "scan",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_strategy.scan_stocks.return_value = []

        mock_llm = AsyncMock()

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_scan(
                    "scan-004",
                    {
                        "limit": 100,
                        "ai_analysis": True,
                    },
                )

        task = task_store["scan-004"]
        assert task["status"] == "completed"
        assert "0 只" in task["message"]
        # 空列表不应触发 AI 分析
        mock_llm.analyze_stock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scan_strategy_failure(self, task_store):
        """策略服务调用失败"""
        from services.task_scheduler import TaskScheduler

        task_store["scan-005"] = {
            "task_id": "scan-005",
            "task_type": "scan",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_strategy.scan_stocks.side_effect = Exception("策略服务不可达")

        mock_llm = AsyncMock()

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_scan(
                    "scan-005",
                    {
                        "limit": 100,
                        "ai_analysis": True,
                    },
                )

        task = task_store["scan-005"]
        assert task["status"] == "failed"
        assert "扫描失败" in task["message"]

    @pytest.mark.asyncio
    async def test_scan_progress_updates(self, task_store):
        """进度更新依次递增"""
        from services.task_scheduler import TaskScheduler

        task_store["scan-006"] = {
            "task_id": "scan-006",
            "task_type": "scan",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_strategy.scan_stocks.return_value = [{"ts_code": f"stock-{i}"} for i in range(3)]

        mock_llm = AsyncMock()
        mock_llm.analyze_stock.return_value = "分析结果"

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_scan(
                    "scan-006",
                    {
                        "limit": 100,
                        "ai_analysis": True,
                    },
                )

        # 验证最终状态
        task = task_store["scan-006"]
        assert task["progress"] == 1.0
        assert task["status"] == "completed"


# ─── Review 任务测试 ─────────────────────────────────────────────────


class TestTaskSchedulerExecuteReview:
    """execute_review 完整生命周期"""

    @pytest.mark.asyncio
    async def test_review_full_success(self, task_store):
        """完整 review 流程：市场数据 → AI 复盘 → 完成"""
        from services.task_scheduler import TaskScheduler

        task_store["review-001"] = {
            "task_id": "review-001",
            "task_type": "review",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_llm = AsyncMock()
        mock_llm.generate_review.return_value = "今日大盘震荡上行..."

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )

        # Mock _fetch_market_data 返回模拟数据
        scheduler._fetch_market_data = AsyncMock(
            return_value={
                "indices": [{"name": "上证指数", "close": 3200}],
                "advance": 2500,
                "decline": 1500,
            }
        )

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_review(
                    "review-001",
                    {
                        "date": "2026-06-15",
                        "include_ai": True,
                    },
                )

        task = task_store["review-001"]
        assert task["status"] == "completed"
        assert task["progress"] == 1.0
        assert "2026-06-15" in task["message"]
        mock_llm.generate_review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_review_without_ai(self, task_store):
        """跳过 AI 复盘"""
        from services.task_scheduler import TaskScheduler

        task_store["review-002"] = {
            "task_id": "review-002",
            "task_type": "review",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_llm = AsyncMock()

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )
        scheduler._fetch_market_data = AsyncMock(return_value={})

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_review(
                    "review-002",
                    {
                        "date": None,
                        "include_ai": False,
                    },
                )

        task = task_store["review-002"]
        assert task["status"] == "completed"
        assert "跳过AI复盘" in task["message"]
        mock_llm.generate_review.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_ai_failure(self, task_store):
        """AI 复盘失败不应影响整体完成"""
        from services.task_scheduler import TaskScheduler

        task_store["review-003"] = {
            "task_id": "review-003",
            "task_type": "review",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_llm = AsyncMock()
        mock_llm.generate_review.side_effect = Exception("API超时")

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )
        scheduler._fetch_market_data = AsyncMock(return_value={})

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_review(
                    "review-003",
                    {
                        "date": "2026-06-15",
                        "include_ai": True,
                    },
                )

        task = task_store["review-003"]
        assert task["status"] == "completed"
        assert "AI复盘生成失败" in task["message"]

    @pytest.mark.asyncio
    async def test_review_market_data_failure(self, task_store):
        """获取市场数据失败时容错"""
        from services.task_scheduler import TaskScheduler

        task_store["review-004"] = {
            "task_id": "review-004",
            "task_type": "review",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_llm = AsyncMock()
        mock_llm.generate_review.return_value = "复盘报告"

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )
        # 模拟市场数据获取失败
        scheduler._fetch_market_data = AsyncMock(side_effect=Exception("网络异常"))

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_review(
                    "review-004",
                    {
                        "include_ai": True,
                    },
                )

        task = task_store["review-004"]
        assert task["status"] == "completed"
        # 市场数据获取失败不应阻止整体完成
        mock_llm.generate_review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_review_default_date(self, task_store):
        """未指定日期时使用今天"""
        from datetime import datetime

        from services.task_scheduler import TaskScheduler

        task_store["review-005"] = {
            "task_id": "review-005",
            "task_type": "review",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        mock_strategy = AsyncMock()
        mock_llm = AsyncMock()
        mock_llm.generate_review.return_value = "报告"

        scheduler = TaskScheduler(
            task_store=task_store,
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )
        scheduler._fetch_market_data = AsyncMock(return_value={})

        with patch(
            "services.task_scheduler.broadcast_task_update",
            new_callable=AsyncMock,
        ):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                await scheduler.execute_review(
                    "review-005",
                    {
                        "date": None,
                        "include_ai": True,
                    },
                )

        task = task_store["review-005"]
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in task["message"]


# ─── 初始化测试 ─────────────────────────────────────────────────────


class TestTaskSchedulerInit:
    """TaskScheduler 初始化测试"""

    def test_init_creates_default_clients(self):
        """未传入 client 时自动创建"""
        from services.llm_client import LLMClient
        from services.strategy_client import StrategyClient
        from services.task_scheduler import TaskScheduler

        scheduler = TaskScheduler(task_store={})
        assert isinstance(scheduler._strategy_client, StrategyClient)
        assert isinstance(scheduler._llm_client, LLMClient)

    def test_init_accepts_custom_clients(self):
        """传入自定义 client"""
        from services.task_scheduler import TaskScheduler

        mock_strategy = AsyncMock()
        mock_llm = AsyncMock()

        scheduler = TaskScheduler(
            task_store={},
            strategy_client=mock_strategy,
            llm_client=mock_llm,
        )
        assert scheduler._strategy_client is mock_strategy
        assert scheduler._llm_client is mock_llm


# ─── 内部方法测试 ────────────────────────────────────────────────────


class TestTaskSchedulerInternal:
    """TaskScheduler 内部方法测试"""

    @pytest.mark.asyncio
    async def test_fetch_market_data_success(self):
        """_fetch_market_data 成功"""
        from services.task_scheduler import TaskScheduler

        mock_get = AsyncMock()
        mock_get.return_value.status_code = 200
        mock_get.return_value.json = MagicMock(
            return_value={"ts_code": "000001.SH", "close": 3200},
        )

        scheduler = TaskScheduler(task_store={})

        with patch("httpx.AsyncClient.get", mock_get):
            result = await scheduler._fetch_market_data()
            assert "indices" in result
            assert len(result["indices"]) > 0

    @pytest.mark.asyncio
    async def test_fetch_market_data_partial_failure(self):
        """部分指数获取失败时容错"""
        import httpx
        from services.task_scheduler import TaskScheduler

        mock_get = AsyncMock()
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: {"ts_code": "000001.SH"}),
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
        ]

        scheduler = TaskScheduler(task_store={})

        with patch("httpx.AsyncClient.get", mock_get):
            result = await scheduler._fetch_market_data()
            assert len(result["indices"]) == 1  # 只有第一个成功

    @pytest.mark.asyncio
    async def test_fetch_market_data_all_fail(self):
        """全部指数获取失败时返回空结构"""
        from services.task_scheduler import TaskScheduler

        mock_get = AsyncMock(side_effect=Exception("网络异常"))

        scheduler = TaskScheduler(task_store={})

        with patch("httpx.AsyncClient.get", mock_get):
            result = await scheduler._fetch_market_data()
            assert result == {"indices": [], "advance": 0, "decline": 0}

    @pytest.mark.asyncio
    async def test_update_task_updates_store(self, task_store):
        """_update_task 正确更新任务存储"""
        from services.task_scheduler import TaskScheduler

        task_store["test-task"] = {
            "task_id": "test-task",
            "status": "pending",
            "progress": 0.0,
            "message": "",
        }

        scheduler = TaskScheduler(task_store=task_store)

        with patch("services.task_scheduler.broadcast_task_update"):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                scheduler._update_task("test-task", "running", 0.5, "处理中...")

        task = task_store["test-task"]
        assert task["status"] == "running"
        assert task["progress"] == 0.5
        assert task["message"] == "处理中..."

    @pytest.mark.asyncio
    async def test_update_task_nonexistent(self, task_store):
        """不存在的 task_id 不应抛出异常"""
        from services.task_scheduler import TaskScheduler

        scheduler = TaskScheduler(task_store=task_store)

        with patch("services.task_scheduler.broadcast_task_update"):
            with patch("services.task_scheduler.asyncio.ensure_future"):
                # 不应抛出异常
                scheduler._update_task("nonexistent", "running", 0.5, "?")

    @pytest.mark.asyncio
    async def test_update_task_broadcast_failure_ignored(self, task_store):
        """WebSocket 广播失败被忽略"""
        from services.task_scheduler import TaskScheduler

        task_store["test-task"] = {
            "task_id": "test-task",
            "status": "pending",
        }

        scheduler = TaskScheduler(task_store=task_store)

        with patch(
            "services.task_scheduler.broadcast_task_update",
            side_effect=Exception("广播失败"),
        ):
            # 不应抛出异常
            scheduler._update_task("test-task", "completed", 1.0, "完成")
