"""
回测引擎单元测试
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# 故意测试已废弃模块 — 抑制 DeprecationWarning
warnings.filterwarnings("ignore", message=".*backtest_service.py.*", category=DeprecationWarning)
from services.backtest_service import SimpleBacktestEngine


class TestSimpleBacktestEngine:
    """SimpleBacktestEngine 单元测试"""

    @pytest.fixture
    def engine(self):
        return SimpleBacktestEngine(initial_cash=100000.0)

    @pytest.fixture
    def sample_data(self):
        """生成50个交易日的模拟数据"""
        closes = []
        price = 100.0
        for i in range(50):
            price *= 1 + (i % 5 - 2) / 100
            closes.append(round(price, 2))
        dates = [f"2024-01-{i + 1:02d}" for i in range(50)]
        return closes, dates

    def test_initial_state(self, engine):
        """测试初始状态正确"""
        assert engine.initial_cash == 100000.0
        assert engine.cash == 100000.0
        assert engine.holdings == 0
        assert len(engine.trades) == 0

    def test_ma_cross_strategy(self, engine, sample_data):
        """测试双均线策略"""
        closes, dates = sample_data
        result = engine.run_ma_cross(closes, dates, ma_fast=5, ma_slow=20)
        assert result.total_return is not None
        assert result.total_trades >= 0

    def test_ma_cross_no_trades_short_data(self, engine):
        """测试数据太少时不产生交易"""
        closes = [100.0] * 3
        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
        result = engine.run_ma_cross(closes, dates, ma_fast=5, ma_slow=10)
        assert result.total_trades == 0

    def test_breakout_strategy(self, engine, sample_data):
        """测试突破策略"""
        closes, dates = sample_data
        result = engine.run_breakout(closes, dates=dates)
        assert result.total_return is not None
        assert result.total_trades >= 0

    def test_breakout_with_highs(self, engine, sample_data):
        """测试突破策略带上高价格"""
        closes, dates = sample_data
        highs = [c * 1.02 for c in closes]
        result = engine.run_breakout(closes, highs=highs, dates=dates)
        assert result.total_return is not None

    def test_rsi_strategy(self, engine, sample_data):
        """测试RSI策略"""
        closes, dates = sample_data
        result = engine.run_rsi(closes, dates)
        assert result.total_return is not None
        assert result.total_trades >= 0

    def test_rsi_no_trades_flat(self, engine):
        """横盘时RSI不应频繁交易"""
        closes = [100.0] * 40
        dates = [f"2024-01-{i + 1:02d}" for i in range(40)]
        result = engine.run_rsi(closes, dates)
        assert result.total_trades < 8

    def test_parameter_grid_search(self, engine, sample_data):
        """测试参数网格搜索（手动方式）"""
        closes, dates = sample_data
        best_sharpe = -1
        best_params = None
        for ma_fast in [5, 10]:
            for ma_slow in [20, 30]:
                if ma_slow <= ma_fast:
                    continue
                result = engine.run_ma_cross(closes, dates, ma_fast=ma_fast, ma_slow=ma_slow)
                if result.sharpe_ratio > best_sharpe:
                    best_sharpe = result.sharpe_ratio
                    best_params = (ma_fast, ma_slow)
        assert best_params is not None

    def test_all_strategies_return_results(self, engine, sample_data):
        """所有策略都应返回有效结果"""
        closes, dates = sample_data
        for strategy_name in ["ma_cross", "breakout", "rsi"]:
            method = getattr(engine, f"run_{strategy_name}")
            result = method(closes, dates)
            assert result.total_return is not None
            assert result.sharpe_ratio is not None
            assert result.win_rate is not None

    def test_reset_preserves_engine(self, engine):
        """测试重置后状态回到初始"""
        engine.cash = 50000.0
        engine.position = 100
        engine.reset()
        assert engine.cash == 100000.0
        assert engine.holdings == 0
        assert len(engine.trades) == 0

    def test_calculate_ma(self, engine):
        """测试移动平均线计算"""
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = engine.calculate_ma(data, period=3)
        assert len(result) == 10
        assert result[5] == (4 + 5 + 6) / 3  # 第6个元素的3日均值
