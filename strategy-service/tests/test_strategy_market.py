"""Tests for strategy_market.py — StrategyMarketService + run_ai_scan"""

from unittest.mock import MagicMock, patch

from models.strategy import Strategy
import pytest


class TestStrategyMarketService:
    """StrategyMarketService 业务逻辑测试"""

    def test_list_strategies(self):
        """Happy path: 正常列出策略"""
        mock_repo = MagicMock()
        expected = [{"id": "s1", "name": "策略A"}, {"id": "s2", "name": "策略B"}]
        mock_repo.list_all.return_value = expected

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.list_strategies(type_filter="custom", status="active")

        mock_repo.list_all.assert_called_once_with(type_filter="custom", status="active")
        assert result == expected

    def test_list_strategies_defaults(self):
        """默认参数: type_filter=None, status='active'"""
        mock_repo = MagicMock()
        mock_repo.list_all.return_value = []

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.list_strategies()

        mock_repo.list_all.assert_called_once_with(type_filter=None, status="active")
        assert result == []

    def test_get_strategy_found(self):
        """获取已有策略 → 返回 dict (line 23 happy path)"""
        s = Strategy(name="Test", id="test-1")
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = s

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.get_strategy("test-1")

        assert result == s.to_dict()

    def test_get_strategy_not_found(self):
        """策略不存在 → 返回 None (line 24 else branch)"""
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = None

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.get_strategy("nonexistent")

        assert result is None

    def test_create_strategy(self):
        """创建策略 → 返回 dict (line 26-30)"""
        mock_repo = MagicMock()
        captured = []

        def _track_create(s):
            captured.append(s)
            return s

        mock_repo.create.side_effect = _track_create

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.create_strategy(
                name="My Strategy", params={"ma_fast": 5}, description="测试策略"
            )

        assert len(captured) == 1
        created = captured[0]
        assert created.name == "My Strategy"
        assert created.type == "custom"
        assert created.params == {"ma_fast": 5}
        assert created.description == "测试策略"
        assert result["name"] == "My Strategy"
        assert result["type"] == "custom"

    def test_update_strategy_found(self):
        """更新已有策略 (line 34 happy path)"""
        s = Strategy(name="Updated", id="test-1")
        mock_repo = MagicMock()
        mock_repo.update.return_value = s

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.update_strategy("test-1", {"name": "Updated"})

        mock_repo.update.assert_called_once_with("test-1", {"name": "Updated"})
        assert result == s.to_dict()

    def test_update_strategy_not_found(self):
        """更新不存在的策略 → 返回 None (line 35 else branch)"""
        mock_repo = MagicMock()
        mock_repo.update.return_value = None

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.update_strategy("nonexistent", {})

        assert result is None

    def test_delete_strategy_true(self):
        """删除存在的策略 → 返回 True"""
        mock_repo = MagicMock()
        mock_repo.delete.return_value = True

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.delete_strategy("test-1")

        mock_repo.delete.assert_called_once_with("test-1")
        assert result is True

    def test_delete_strategy_false(self):
        """删除不存在的策略 → 返回 False"""
        mock_repo = MagicMock()
        mock_repo.delete.return_value = False

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.delete_strategy("nonexistent")

        assert result is False

    def test_backtest_strategy_not_found(self):
        """回测不存在的策略 → ValueError (line 46-47)"""
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = None

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            with pytest.raises(ValueError, match="策略不存在"):
                svc.backtest_strategy("nonexistent")

    def test_backtest_strategy_success(self):
        """完整回测成功 (lines 45-93, known strategy_id mapped)"""
        s = Strategy(name="双均线金叉", id="builtin-ma-cross", type="builtin", params={})

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = s

        mock_result = MagicMock()
        mock_result.sharpe_ratio = 1.55
        mock_result.total_return = 0.253
        mock_result.max_drawdown = -0.123
        mock_result.win_rate = 0.55
        mock_result.total_trades = 20
        mock_result.equity_curve = [100000, 101000, 100500, 102000]

        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        with (
            patch("services.strategy_market.strategy_repo", mock_repo),
            patch(
                "services.backtest_engine_v2.EnhancedBacktestEngine",
                return_value=mock_engine,
            ),
            patch("services.backtest_engine_v2.BacktestConfig"),
        ):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.backtest_strategy("builtin-ma-cross", "000001")

        assert result["strategy"]["id"] == "builtin-ma-cross"
        assert result["backtest"]["sharpe"] == 1.55
        assert result["backtest"]["total_return"] == 0.253
        assert result["backtest"]["max_drawdown"] == -0.123
        assert result["backtest"]["win_rate"] == 0.55
        assert result["backtest"]["total_trades"] == 20
        assert result["backtest"]["data_source"] == "tencent"
        assert len(result["daily_values"]) == 4
        mock_repo.save_performance.assert_called_once()

    def test_backtest_strategy_unmapped_id(self):
        """未映射的策略ID → fallback 到 ma-cross (line 58)"""
        s = Strategy(name="自定义", id="custom-001", type="custom", params={})

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = s

        mock_result = MagicMock()
        mock_result.sharpe_ratio = 1.0
        mock_result.total_return = 0.1
        mock_result.max_drawdown = -0.05
        mock_result.win_rate = 0.5
        mock_result.total_trades = 10
        mock_result.equity_curve = [100000, 100500]

        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        with (
            patch("services.strategy_market.strategy_repo", mock_repo),
            patch(
                "services.backtest_engine_v2.EnhancedBacktestEngine",
                return_value=mock_engine,
            ),
            patch("services.backtest_engine_v2.BacktestConfig"),
        ):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.backtest_strategy("custom-001", "000001")

        assert result["backtest"]["sharpe"] == 1.0

    def test_backtest_strategy_ts_code_sh(self):
        """ts_code 标准化: 6开头 → .SH (line 61-62)"""
        s = Strategy(name="茅台", id="builtin-ma-cross", type="builtin")

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = s

        mock_result = MagicMock()
        mock_result.sharpe_ratio = 1.2
        mock_result.total_return = 0.15
        mock_result.max_drawdown = -0.08
        mock_result.win_rate = 0.6
        mock_result.total_trades = 12
        mock_result.equity_curve = [100000, 100800]

        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        with (
            patch("services.strategy_market.strategy_repo", mock_repo),
            patch(
                "services.backtest_engine_v2.EnhancedBacktestEngine",
                return_value=mock_engine,
            ),
            patch("services.backtest_engine_v2.BacktestConfig"),
        ):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.backtest_strategy("builtin-ma-cross", "600519")

        assert result["backtest"]["sharpe"] == 1.2

    def test_backtest_strategy_ts_code_sz(self):
        """ts_code 标准化: 非6开头 → .SZ (line 61-62)"""
        s = Strategy(name="平安银行", id="builtin-ma-cross", type="builtin")

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = s

        mock_result = MagicMock()
        mock_result.sharpe_ratio = 0.9
        mock_result.total_return = 0.08
        mock_result.max_drawdown = -0.06
        mock_result.win_rate = 0.4
        mock_result.total_trades = 8
        mock_result.equity_curve = [100000, 100300]

        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        with (
            patch("services.strategy_market.strategy_repo", mock_repo),
            patch(
                "services.backtest_engine_v2.EnhancedBacktestEngine",
                return_value=mock_engine,
            ),
            patch("services.backtest_engine_v2.BacktestConfig"),
        ):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.backtest_strategy("builtin-ma-cross", "000001")

        assert result["backtest"]["sharpe"] == 0.9

    def test_backtest_strategy_with_data(self):
        """回测时传递自定义数据 (line 79 with data)"""
        s = Strategy(name="测试", id="builtin-ma-cross", type="builtin")

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = s

        mock_result = MagicMock()
        mock_result.sharpe_ratio = 0.5
        mock_result.total_return = 0.05
        mock_result.max_drawdown = -0.03
        mock_result.win_rate = 0.3
        mock_result.total_trades = 5
        mock_result.equity_curve = [100000, 100100]

        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        custom_data = [{"date": "20260101", "close": 10.0}]

        with (
            patch("services.strategy_market.strategy_repo", mock_repo),
            patch(
                "services.backtest_engine_v2.EnhancedBacktestEngine",
                return_value=mock_engine,
            ),
            patch("services.backtest_engine_v2.BacktestConfig"),
        ):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.backtest_strategy("builtin-ma-cross", "000001", data=custom_data)

        assert result["backtest"]["sharpe"] == 0.5
        mock_engine.run.assert_called_once()

    def test_backtest_strategy_exception(self):
        """回测引擎抛异常 → 返回 error dict (line 94-96)"""
        s = Strategy(name="测试", id="builtin-ma-cross", type="builtin")

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = s

        with (
            patch("services.strategy_market.strategy_repo", mock_repo),
            patch(
                "services.backtest_engine_v2.EnhancedBacktestEngine",
                side_effect=ValueError("数据不足"),
            ),
            patch("services.backtest_engine_v2.BacktestConfig"),
            patch("services.strategy_market.logger"),
        ):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.backtest_strategy("builtin-ma-cross", "000001")

        assert result["strategy"]["id"] == "builtin-ma-cross"
        assert "error" in result["backtest"]
        assert "数据不足" in result["backtest"]["error"]

    def test_compare_strategies(self):
        """多策略对比 (line 102-109)"""
        from services.strategy_market import StrategyMarketService

        svc = StrategyMarketService()

        with patch.object(svc, "backtest_strategy") as mock_bt:
            mock_bt.side_effect = [
                {"strategy": {"id": "s1"}, "backtest": {"sharpe": 1.5}},
                {"strategy": {"id": "s2"}, "backtest": {"sharpe": 1.2}},
                {"strategy": {"id": "s3"}, "backtest": {"sharpe": 0.8}},
            ]
            result = svc.compare_strategies(["s1", "s2", "s3"])

        assert len(result) == 3
        assert result[0]["strategy"]["id"] == "s1"
        assert result[1]["backtest"]["sharpe"] == 1.2
        assert result[2]["backtest"]["sharpe"] == 0.8

    def test_compare_strategies_partial_fail(self):
        """部分策略回测失败 → 包含错误信息 (line 107-108)"""
        from services.strategy_market import StrategyMarketService

        svc = StrategyMarketService()

        with patch.object(svc, "backtest_strategy") as mock_bt:
            mock_bt.side_effect = [
                {"strategy": {"id": "s1"}, "backtest": {"sharpe": 1.5}},
                ValueError("策略不存在: s2"),
                {"strategy": {"id": "s3"}, "backtest": {"sharpe": 0.8}},
            ]
            result = svc.compare_strategies(["s1", "s2", "s3"])

        assert len(result) == 3
        assert result[0]["strategy"]["id"] == "s1"
        assert "error" in result[1]["backtest"]
        assert "策略不存在" in result[1]["backtest"]["error"]
        assert result[2]["backtest"]["sharpe"] == 0.8

    def test_get_ranking(self):
        """排行榜 (line 111-128)"""
        mock_strategies = [
            {
                "id": "s1",
                "name": "策略A",
                "type": "builtin",
                "performance": {"sharpe": 1.5},
            },
            {
                "id": "s2",
                "name": "策略B",
                "type": "custom",
                "performance": {"sharpe": 2.0},
            },
            {
                "id": "s3",
                "name": "策略C",
                "type": "builtin",
                "performance": {"sharpe": 1.0},
            },
        ]
        mock_repo = MagicMock()
        mock_repo.list_all.return_value = mock_strategies

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.get_ranking(metric="sharpe")

        assert result[0]["id"] == "s2"  # sharpe 2.0 max
        assert result[1]["id"] == "s1"  # sharpe 1.5
        assert result[2]["id"] == "s3"  # sharpe 1.0

    def test_get_ranking_custom_metric(self):
        """自定义排序指标"""
        mock_strategies = [
            {
                "id": "s1",
                "name": "A",
                "type": "builtin",
                "performance": {"total_return": 0.5},
            },
            {
                "id": "s2",
                "name": "B",
                "type": "custom",
                "performance": {"total_return": 0.8},
            },
        ]
        mock_repo = MagicMock()
        mock_repo.list_all.return_value = mock_strategies

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.get_ranking(metric="total_return")

        assert result[0]["id"] == "s2"

    def test_get_ranking_empty_performance(self):
        """performance 为 None 时 score=0 (line 116)"""
        mock_strategies = [
            {"id": "s1", "name": "A", "type": "builtin", "performance": None},
            {"id": "s2", "name": "B", "type": "custom", "performance": None},
        ]
        mock_repo = MagicMock()
        mock_repo.list_all.return_value = mock_strategies

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.get_ranking(metric="sharpe")

        assert result[0]["score"] == 0
        assert result[1]["score"] == 0

    def test_get_ranking_missing_metric(self):
        """performance 存在但缺少 metric 字段 → score=0"""
        mock_strategies = [
            {
                "id": "s1",
                "name": "A",
                "type": "builtin",
                "performance": {"sharpe": 1.5},
            },
        ]
        mock_repo = MagicMock()
        mock_repo.list_all.return_value = mock_strategies

        with patch("services.strategy_market.strategy_repo", mock_repo):
            from services.strategy_market import StrategyMarketService

            svc = StrategyMarketService()
            result = svc.get_ranking(metric="nonexistent")

        assert result[0]["score"] == 0


class TestRunAiScan:
    """run_ai_scan 函数测试 (line 135-207)"""

    @pytest.mark.asyncio
    async def test_ai_scan_success(self):
        """完整 AI 扫描流程 (line 135-207)"""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {"metrics": {"sharpe": 1.5, "total_return": 0.2}}

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({})

        assert len(result) <= 10
        assert len(result) > 0
        for r in result:
            assert "ts_code" in r
            assert "score" in r
            assert "signal" in r
            assert "best_strategy" in r

    @pytest.mark.asyncio
    async def test_ai_scan_custom_pool_and_strategies(self):
        """自定义股票池和策略列表 (line 147, 157)"""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {"metrics": {"sharpe": 1.5, "total_return": 0.2}}

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan(
                {
                    "pool": ["600519.SH", "000858.SZ"],
                    "strategies": ["ma-cross", "breakout"],
                }
            )

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_ai_scan_best_strategy_selected(self):
        """多策略中选最佳 sharpe (line 176-181)"""
        mock_engine = MagicMock()
        mock_engine.run_single_stock.side_effect = [
            MagicMock(sharpe_ratio=0.5, total_return=0.05),
            MagicMock(sharpe_ratio=2.0, total_return=0.3),
        ]

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan(
                {
                    "pool": ["000001.SZ"],
                    "strategies": ["ma-cross", "breakout"],
                }
            )

        assert len(result) == 1
        # breakout 有 better sharpe 2.0 > 0.5
        assert result[0]["best_strategy"] == "breakout"
        assert result[0]["sharpe"] == 2.0

    @pytest.mark.asyncio
    async def test_ai_scan_strategy_exception_continues(self):
        """单个策略评估异常 → 跳过继续 (line 182-184)"""
        mock_engine = MagicMock()
        mock_engine.run_single_stock.side_effect = [
            Exception("策略评估失败"),
            MagicMock(sharpe_ratio=1.5, total_return=0.2),
        ]

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan(
                {
                    "pool": ["000001.SZ"],
                    "strategies": ["ma-cross", "breakout"],
                }
            )

        assert len(result) == 1
        assert result[0]["best_strategy"] == "breakout"

    @pytest.mark.asyncio
    async def test_ai_scan_stock_exception_continues(self):
        """单只股票扫描异常 → 跳过继续 (line 202-204)"""
        # 注：params.get("strategies") or [...] 中 [] 是 falsy → 走默认列表.
        # 这里通过让所有 engine.run_single_stock() 都抛出异常来覆盖 inner except，
        # 外层的 except 是防御性的（取决于不可预测的堆栈异常）。
        mock_engine = MagicMock()
        mock_engine.run_single_stock.side_effect = Exception("该股票数据异常")

        with (
            patch(
                "services.backtest_engine_v2.EnhancedBacktestEngine",
                return_value=mock_engine,
            ),
            patch("services.strategy_market.logger"),
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan(
                {
                    "pool": ["000001.SZ", "600519.SH"],
                    "strategies": ["ma-cross"],
                }
            )

        # 只有内层异常，股票仍写入结果（score=0）
        assert len(result) == 2
        assert all(r["score"] == 0 for r in result)

    @pytest.mark.asyncio
    async def test_ai_scan_signal_buy(self):
        """信号: BUY (best_return>0 and best_sharpe>0.5)"""
        mock_engine = MagicMock()
        mock_engine.run_single_stock.return_value = MagicMock(sharpe_ratio=1.0, total_return=0.1)

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({"pool": ["000001.SZ"]})

        assert result[0]["signal"] == "BUY"

    @pytest.mark.asyncio
    async def test_ai_scan_signal_hold(self):
        """信号: HOLD (not BUY but return > -0.05)"""
        mock_engine = MagicMock()
        mock_engine.run_single_stock.return_value = MagicMock(sharpe_ratio=0.3, total_return=-0.02)

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({"pool": ["000001.SZ"]})

        assert result[0]["signal"] == "HOLD"

    @pytest.mark.asyncio
    async def test_ai_scan_signal_sell(self):
        """信号: SELL (return <= -0.05)"""
        mock_engine = MagicMock()
        mock_engine.run_single_stock.return_value = MagicMock(sharpe_ratio=-1.0, total_return=-0.1)

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({"pool": ["000001.SZ"]})

        assert result[0]["signal"] == "SELL"

    @pytest.mark.asyncio
    async def test_ai_scan_empty_metric_fallback(self):
        """metrics 中字段为空 → 使用默认值 -99/0 (line 177, 180)"""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {"metrics": {"sharpe": None, "total_return": None}}

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({"pool": ["000001.SZ"]})

        assert len(result) == 1
        # sharpe=None → or -99 → -99, total_return=None → or 0 → 0
        # score = max(0, min(100, (-99+2)*20)) = 0
        assert result[0]["score"] == 0
        # best_strategy stays at strategies[0] since no strategy improved
        assert result[0]["best_strategy"] == "ma-cross"
        # return=0 > -0.05 → HOLD (return not > 0)
        assert result[0]["signal"] == "HOLD"

    @pytest.mark.asyncio
    async def test_ai_scan_metrics_not_present(self):
        """res 中没有 metrics → 使用默认值 (line 176)"""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({"pool": ["000001.SZ"]})

        assert len(result) == 1
        # res.get("metrics", {}) → {}
        # sharpe = {}.get("sharpe", -99) = -99
        # total_return = {}.get("total_return", 0) = 0
        # score = max(0, min(100, (-99+2)*20)) = 0
        assert result[0]["score"] == 0

    @pytest.mark.asyncio
    async def test_ai_scan_sorted_by_score(self):
        """结果按 score 降序排列 (line 206)"""
        mock_engine = MagicMock()
        mock_engine.run.side_effect = [
            {"metrics": {"sharpe": 0.5, "total_return": 0.02}},
            {"metrics": {"sharpe": 2.0, "total_return": 0.3}},
        ]

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan(
                {
                    "pool": ["000001.SZ", "600519.SH"],
                    "strategies": ["ma-cross"],
                }
            )

        assert len(result) == 2
        # 600519.SH (sharpe=2.0) should rank higher than 000001.SZ (sharpe=0.5)
        assert result[0]["score"] >= result[1]["score"]

    @pytest.mark.asyncio
    async def test_ai_scan_pool_limit_10(self):
        """股票池超过10只 → 只取前10 (line 162)"""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {"metrics": {"sharpe": 1.0, "total_return": 0.1}}

        big_pool = [f"{i:06d}.SZ" for i in range(1, 20)]

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({"pool": big_pool})

        assert len(result) == 10  # pool[:10]

    @pytest.mark.asyncio
    async def test_ai_scan_default_pool_fallback(self):
        """params 无 pool → 使用默认股票池 (line 147-156)"""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {"metrics": {"sharpe": 1.0, "total_return": 0.1}}

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({})

        # Default pool has 8 stocks
        assert len(result) == 8

    @pytest.mark.asyncio
    async def test_ai_scan_empty_pool(self):
        """params.pool 为空列表 → 使用默认股票池 (line 147)"""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {"metrics": {"sharpe": 1.0, "total_return": 0.1}}

        with patch(
            "services.backtest_engine_v2.EnhancedBacktestEngine",
            return_value=mock_engine,
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({"pool": []})

        # Empty list is falsy → fallback to default (8 stocks)
        assert len(result) == 8

    @pytest.mark.asyncio
    async def test_ai_scan_all_strategies_fail_no_stock_drop(self):
        """所有策略都失败 → 该股票仍写入结果，score=0"""
        mock_engine = MagicMock()
        mock_engine.run.side_effect = Exception("全部失败")

        with (
            patch(
                "services.backtest_engine_v2.EnhancedBacktestEngine",
                return_value=mock_engine,
            ),
            patch("services.strategy_market.logger"),
        ):
            from services.strategy_market import run_ai_scan

            result = await run_ai_scan({"pool": ["000001.SZ"], "strategies": ["ma-cross"]})

        # 内层循环全部 catch，股票仍会加入结果（score=0）
        assert len(result) == 1
        assert result[0]["score"] == 0
        assert result[0]["best_strategy"] == "ma-cross"
        assert result[0]["signal"] == "HOLD"
