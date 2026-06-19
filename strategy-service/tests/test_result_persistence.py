"""
测试 ResultPersistence 持久化服务
Cover services/result_persistence.py 中未覆盖的分支：
- _ensure_imports ImportError 路径 (lines 36-38)
- save() 返回 None (line 119)
- save_backtest_result 包装函数 (line 150)
"""

import builtins
from unittest.mock import MagicMock, patch

from services.result_persistence import ResultPersistence, save_backtest_result


class TestEnsureImports:
    """测试 _ensure_imports() 异常路径"""

    def test_import_error_returns_false(self):
        """模拟 ImportError → 返回 False, log warning (lines 36-38)"""
        instance = ResultPersistence()
        _real_import = builtins.__import__

        def _fail_import(name, *args, **kwargs):
            if name in ("models.database", "repositories.backtest_repo") or name.startswith(
                "models."
            ):
                raise ImportError(f"No module named {name}")
            return _real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_fail_import):
            assert instance._ensure_imports() is False


class TestSaveReturnsNone:
    """测试 save() 在 DB 不可用时的 None 返回"""

    def test_save_returns_none_when_import_fails(self):
        """_ensure_imports 返回 False → save 返回 None (line 118-119)"""
        instance = ResultPersistence()

        with patch.object(instance, "_ensure_imports", return_value=False):
            result = instance.save(
                strategy="test_strat",
                ts_code="000001.SZ",
                start_date="20260101",
                end_date="20260619",
                initial_cash=100000.0,
                result=MagicMock(equity_curve=[{"value": 110000}], avg_hold_days=5),
                result_dict={
                    "metrics": {
                        "total_return": 0.1,
                        "annual_return": 0.05,
                        "sharpe_ratio": 1.5,
                        "max_drawdown": -0.1,
                        "win_rate": 0.6,
                        "profit_loss_ratio": 1.5,
                        "total_trades": 5,
                    },
                    "equity_curve": [],
                    "benchmark_curve": [],
                    "drawdown_curve": [],
                    "monthly_returns": [],
                    "trades": [],
                },
            )
        assert result is None


class TestComputeFinalValue:
    """测试 compute_final_value 计算逻辑"""

    def test_with_equity_curve(self):
        """有净值曲线时用最后一个点的 value (line 42-44)"""
        from collections import namedtuple

        Result = namedtuple("Result", ["equity_curve"])
        result = Result(equity_curve=[{"value": 110000}])
        instance = ResultPersistence()
        fv = instance.compute_final_value(result, 100000, 0.1)
        assert fv == 110000.0

    def test_without_equity_curve(self):
        """无净值曲线时用 initial_cash * (1 + total_return) (line 45)"""
        from collections import namedtuple

        Result = namedtuple("Result", ["equity_curve"])
        result = Result(equity_curve=[])
        instance = ResultPersistence()
        fv = instance.compute_final_value(result, 100000, 0.05)
        assert fv == 105000.0


class TestBuildDbRecord:
    """测试 build_db_record 构建"""

    def test_builds_record(self):
        """正常构建 DB 记录"""
        from collections import namedtuple

        Result = namedtuple(
            "Result", ["equity_curve", "winning_trades", "losing_trades", "avg_hold_days"]
        )
        result = Result(
            equity_curve=[{"value": 110000}], winning_trades=3, losing_trades=2, avg_hold_days=5.0
        )
        instance = ResultPersistence()
        record = instance.build_db_record(
            strategy="ma-cross",
            ts_code="600519.SH",
            start_date="20260101",
            end_date="20260619",
            initial_cash=100000,
            result=result,
            result_dict={
                "metrics": {
                    "total_return": 0.1,
                    "annual_return": 0.05,
                    "sharpe_ratio": 1.5,
                    "max_drawdown": -0.1,
                    "win_rate": 0.6,
                    "profit_loss_ratio": 1.5,
                    "total_trades": 5,
                }
            },
        )
        assert record["strategy_name"] == "ma-cross"
        assert record["ts_code"] == "600519.SH"
        assert record["winning_trades"] == 3
        assert record["losing_trades"] == 2
        assert record["avg_holding_days"] == 5.0


class TestSaveBacktestResultWrapper:
    """测试 save_backtest_result 顶层包装函数（line 150）"""

    def test_wrapper_delegates_to_persistence(self):
        """包装函数委托给 _persistence.save (line 150)"""
        with patch("services.result_persistence._persistence") as mock_pers:
            mock_pers.save.return_value = "mock_bid"
            from collections import namedtuple

            Result = namedtuple("Result", ["equity_curve", "avg_hold_days"])
            result = Result(equity_curve=[], avg_hold_days=0)
            bid = save_backtest_result(
                strategy="test",
                ts_code="000001.SZ",
                start_date="20260101",
                end_date="20260619",
                initial_cash=100000,
                result=result,
                result_dict={
                    "metrics": {
                        "total_return": 0,
                        "annual_return": 0,
                        "sharpe_ratio": 0,
                        "max_drawdown": 0,
                        "win_rate": 0,
                        "profit_loss_ratio": 0,
                        "total_trades": 0,
                    }
                },
            )
            assert bid == "mock_bid"
            mock_pers.save.assert_called_once()
