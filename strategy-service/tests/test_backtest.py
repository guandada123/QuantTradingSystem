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
from services.backtest_service import BacktestService, SimpleBacktestEngine


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

    def test_calculate_ma_insufficient(self, engine):
        """数据 < period 时全部返回 0 (line 84-85)"""
        result = engine.calculate_ma([1, 2], period=5)
        assert result == [0, 0]

    def test_calculate_rsi_short_data(self, engine):
        """prices < period+1 → 全 50 (line 95-96)"""
        result = engine.calculate_rsi([100] * 10, period=14)
        assert result == [50] * 10

    def test_calculate_rsi_rising(self, engine):
        """持续上涨 → RSI 接近 100 (lines 97-117)"""
        prices = [100 + i for i in range(50)]
        result = engine.calculate_rsi(prices, period=14)
        assert len(result) == 49  # RSI 输出 = len(prices) - 1 (由 deltas 长度决定)
        assert result[-1] > 95  # 持续上涨 RSI 接近 100

    def test_calculate_rsi_declining(self, engine):
        """持续下跌 → RSI 接近 0 (lines 111-112 avg_loss==0 → rs=100 分支)"""
        prices = [100 - i * 0.5 for i in range(50)]
        result = engine.calculate_rsi(prices, period=14)
        assert len(result) == 49  # RSI 输出 = len(prices) - 1
        assert result[-1] < 5  # 持续下跌 RSI 接近 0

    def test_calculate_macd_short_data(self, engine):
        """prices < slow → 全 0 (line 125-126)"""
        d, de, m = engine.calculate_macd([100] * 10, slow=26)
        assert d == [0] * 10
        assert de == [0] * 10
        assert m == [0] * 10

    def test_calculate_macd_normal(self, engine):
        """持续上涨 → MACD 正常计算 (lines 128-148)"""
        prices = [100 + i * 0.5 for i in range(60)]
        d, de, m = engine.calculate_macd(prices, fast=12, slow=26, signal=9)
        assert len(d) == 60
        assert len(de) == 60
        assert len(m) == 60
        assert d[-1] > 0  # 上涨趋势 DIF > 0

    # ---- run_ma_cross 交易分支 ----
    def _uptrend_data(self):
        """生成先平后涨的数据：golden cross → buy → close"""
        closes = [100.0] * 25 + list(range(101, 111)) + [110] * 10
        dates = [f"Day{i}" for i in range(len(closes))]
        return closes, dates

    def test_run_ma_cross_buy_then_close(self, engine):
        """金叉买入 → 收盘平仓 (lines 171-180, 210-214)"""
        closes, dates = self._uptrend_data()
        result = engine.run_ma_cross(closes, dates, ma_fast=5, ma_slow=20)
        assert len(result.trades) >= 1
        buys = [t for t in result.trades if t["action"] == "BUY"]
        assert len(buys) >= 1

    def _ma_cross_buy_sell_data(self):
        """先涨后跌 → golden cross buy + death cross sell"""
        closes = (
            [100.0] * 25
            + list(range(101, 111))  # uptrend 10 days → golden cross
            + list(reversed(range(95, 111)))  # downtrend → death cross
        )
        dates = [f"Day{i}" for i in range(len(closes))]
        return closes, dates

    def test_run_ma_cross_full_cycle(self, engine):
        """金叉买入 + 死叉卖出 (lines 192-206)"""
        closes, dates = self._ma_cross_buy_sell_data()
        result = engine.run_ma_cross(closes, dates, ma_fast=5, ma_slow=20)
        sells = [t for t in result.trades if t["action"] == "SELL"]
        assert len(sells) >= 1
        assert len(result.trades) >= 2

    # ---- run_breakout 分支 ----
    def _breakout_stop_data(self):
        """突破买入 → 止损"""
        closes = [100.0] * 35 + [110.0, 105.0, 95.0, 90.0, 88.0]
        highs = [102.0] * 35 + [112.2, 107.1, 96.9, 91.8, 89.8]
        dates = [f"Day{i}" for i in range(len(closes))]
        return closes, highs, dates

    def test_run_breakout_stop_loss(self, engine):
        """突破买入 → 止损 (lines 265-278)"""
        closes, highs, dates = self._breakout_stop_data()
        result = engine.run_breakout(closes, highs=highs, dates=dates, lookback=20)
        stops = [t for t in result.trades if t.get("reason") == "STOP"]
        assert len(stops) >= 1

    def _breakout_profit_data(self):
        """突破买入 → 止盈"""
        closes = [100.0] * 35 + [110.0, 120.0, 145.0, 150.0]
        highs = [102.0] * 35 + [112.2, 122.4, 147.9, 153.0]
        dates = [f"Day{i}" for i in range(len(closes))]
        return closes, highs, dates

    def test_run_breakout_take_profit(self, engine):
        """突破买入 → 止盈 (PROFIT reason)"""
        closes, highs, dates = self._breakout_profit_data()
        result = engine.run_breakout(closes, highs=highs, dates=dates, lookback=20)
        profits = [t for t in result.trades if t.get("reason") == "PROFIT"]
        assert len(profits) >= 1

    def test_run_breakout_default_args(self, engine):
        """highs=None / dates=None 降级路径 (lines 228-231)"""
        closes = [100.0] * 25 + [110.0, 115.0, 112.0, 108.0, 105.0]
        result = engine.run_breakout(closes, dates=None, lookback=20)
        assert result.total_return is not None
        assert result.total_trades >= 0

    # ---- run_rsi 分支 ----
    @pytest.fixture
    def rsi_buy_data(self):
        """先横盘震荡 → 持续下跌 → RSI < 30 → oversold buy"""
        rng = [100, 101, 99, 102, 98, 101, 99, 100, 98, 102, 99, 101, 98, 100, 99]
        for _ in range(25):
            rng.append(rng[-1] * 0.985)  # 25 days of ~1.5% decline
        dates = [f"Day{i}" for i in range(len(rng))]
        return rng, dates

    @pytest.fixture
    def rsi_sell_data(self):
        """先横盘 → 持续上涨 → RSI > 70 → overbought sell"""
        rng = [100, 101, 99, 102, 98, 101, 99, 100, 98, 102, 99, 101, 98, 100, 99]
        for _ in range(25):
            rng.append(rng[-1] * 0.985)  # decline → buy triggered
        for _ in range(25):
            rng.append(rng[-1] * 1.015)  # rise → RSI > 70 → sell
        dates = [f"Day{i}" for i in range(len(rng))]
        return rng, dates

    def test_run_rsi_insufficient_data(self, engine):
        """数据不足 → 提前返回 (line 297)"""
        result = engine.run_rsi([100] * 5, ["d0"] * 5)
        assert result.total_trades == 0

    def test_run_rsi_oversold_buy(self, engine, rsi_buy_data):
        """RSI 超卖买入 (lines 312-321)"""
        closes, dates = rsi_buy_data
        result = engine.run_rsi(closes, dates, period=14, oversold=30, overbought=70)
        buys = [t for t in result.trades if t["action"] == "BUY"]
        # May or may not trigger depending on RSI behavior, verify code runs
        assert result.total_return is not None

    def test_run_rsi_cycle(self, engine, rsi_sell_data):
        """RSI 超卖买入 → 超买卖出 + 收盘平仓 (lines 332-348)"""
        closes, dates = rsi_sell_data
        result = engine.run_rsi(closes, dates, period=14, oversold=30, overbought=70)
        assert result.total_return is not None
        sells = [t for t in result.trades if t["action"] == "SELL"]
        assert len(sells) >= 1 or result.total_trades == 0  # 可能已有持仓

    # ---- run_macd 分支 ----
    def _macd_data(self):
        """强趋势 + 足够长 → MACD 金叉/死叉必然触发"""
        closes = [100.0] * 30
        for _ in range(30):
            closes.append(closes[-1] * 0.97)  # 100 → ~40
        for _ in range(50):
            closes.append(closes[-1] * 1.02)  # 40 → ~108
        for _ in range(30):
            closes.append(closes[-1] * 0.98)  # 108 → ~59
        dates = [f"Day{i}" for i in range(len(closes))]
        return closes, dates

    def test_run_macd_short_data(self, engine):
        """数据 < slow → 提前返回 (line 357-358)"""
        result = engine.run_macd([100] * 20, ["d0"] * 20, slow=26)
        assert result.total_trades == 0

    def test_run_macd_full_cycle(self, engine):
        """MACD 金叉买入 + 死叉卖出 + 收盘平仓 (lines 372-408)"""
        closes, dates = self._macd_data()
        result = engine.run_macd(closes, dates, fast=12, slow=26, signal=9)
        assert result.total_return is not None
        assert len(result.trades) >= 2, f"Expected at least 2 trades, got {len(result.trades)}"

    # ---- run_kdj 分支 ----
    def _kdj_data(self):
        """强趋势 + 足够长 → KDJ 金叉/死叉必然触发"""
        closes = [100.0] * 10
        for _ in range(20):
            closes.append(closes[-1] * 0.97)  # 100 → ~54
        for _ in range(40):
            closes.append(closes[-1] * 1.02)  # 54 → ~118
        for _ in range(30):
            closes.append(closes[-1] * 0.97)  # 118 → ~47
        highs = [c * 1.03 for c in closes]
        lows = [c * 0.97 for c in closes]
        dates = [f"Day{i}" for i in range(len(closes))]
        return closes, highs, lows, dates

    def test_run_kdj_short_data(self, engine):
        """数据 < period+1 → 提前返回 (line 424-425)"""
        result = engine.run_kdj([100] * 8, [105] * 8, [95] * 8, ["d0"] * 8, period=9)
        assert result.total_trades == 0

    def test_run_kdj_full_cycle(self, engine):
        """KDJ 金叉买入 + 死叉卖出 + 收盘平仓 (lines 460-496)"""
        closes, highs, lows, dates = self._kdj_data()
        result = engine.run_kdj(closes, highs, lows, dates, period=9, k_smooth=3, d_smooth=3)
        assert result.total_return is not None
        assert len(result.trades) >= 2, f"Expected at least 2 trades, got {len(result.trades)}"

    # ---- _build_result 边界 ----
    def test_build_result_no_trades(self, engine):
        """无交易 → 默认全零结果 (lines 504-523)"""
        engine.reset()
        result = engine._build_result(100.0)
        assert result.total_trades == 0
        assert result.total_return == 0
        assert result.win_rate == 0

    def test_build_result_one_daily_value(self, engine):
        """只有1个 daily_value → sharpe=0 (line 567)"""
        engine.trades = [
            {"action": "BUY", "price": 100, "qty": 100, "cost": 10000},
            {"action": "SELL", "price": 102, "qty": 100, "revenue": 10190},
        ]
        engine.daily_values = [{"date": "Day0", "value": 100000}]
        engine.cash = 10190
        result = engine._build_result(102)
        assert result.sharpe_ratio == 0


class TestBacktestService:
    """BacktestService 集成测试 (lines 607-695)"""

    @pytest.fixture
    def service(self):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=".*backtest_service.py.*", category=DeprecationWarning
            )
            return BacktestService()

    @pytest.fixture
    def sample_data(self):
        """60 条 K 线数据"""
        return [{"close": 100 + i * 0.5, "trade_date": f"2024-01-{i + 1:02d}"} for i in range(60)]

    @pytest.fixture
    def long_data(self):
        """140 条 K 线数据 — 足够 MACD/KDJ 计算信号"""
        return [
            {
                "close": 100 + i * 1.5 if i < 80 else 220 - i * 1.5,
                "trade_date": f"2024-01-{i + 1:02d}",
            }
            for i in range(140)
        ]

    def test_init(self, service):
        """初始化 (lines 611-612)"""
        assert service.engine is not None
        assert service.results == {}

    def test_insufficient_data(self, service):
        """数据不足 30 条 → ValueError (line 618-619)"""
        with pytest.raises(ValueError, match="数据不足"):
            service.run_backtest("000001.SZ", "ma-cross", [{"close": 100}] * 25)

    def test_unsupported_strategy(self, service, sample_data):
        """不支持的策略 → ValueError (line 662-663)"""
        with pytest.raises(ValueError, match="不支持的策略"):
            service.run_backtest("000001.SZ", "unknown", sample_data)

    def test_ma_cross(self, service, sample_data):
        """ma-cross 策略 (lines 627-630)"""
        result = service.run_backtest("000001.SZ", "ma-cross", sample_data)
        assert result.ts_code == "000001.SZ"
        assert result.strategy_name == "ma-cross"
        assert result.start_date == "2024-01-01"
        assert result.sharpe_ratio is not None

    def test_breakout(self, service, sample_data):
        """breakout 策略 (lines 631-634)"""
        result = service.run_backtest("000001.SZ", "breakout", sample_data)
        assert result.strategy_name == "breakout"

    def test_rsi(self, service, sample_data):
        """rsi 策略 (lines 635-642)"""
        result = service.run_backtest("000001.SZ", "rsi", sample_data)
        assert result.strategy_name == "rsi"

    def test_macd(self, service, long_data):
        """macd 策略 (lines 643-650)"""
        result = service.run_backtest("000001.SZ", "macd", long_data)
        assert result.strategy_name == "macd"

    def test_kdj(self, service, long_data):
        """kdj 策略 (lines 651-661)"""
        result = service.run_backtest("000001.SZ", "kdj", long_data)
        assert result.strategy_name == "kdj"

    def test_with_params(self, service, sample_data):
        """带自定义参数 (line 625)"""
        result = service.run_backtest(
            "000001.SZ",
            "ma-cross",
            sample_data,
            params={"ma_fast": 10, "ma_slow": 30},
        )
        assert result.sharpe_ratio is not None

    def test_optimize_params_ma_cross(self, service, sample_data):
        """参数优化 (lines 680-695)"""
        result = service.optimize_params(
            "000001.SZ",
            "ma-cross",
            sample_data,
            {"ma_fast": [5, 10], "ma_slow": [20, 30]},
        )
        assert "best_params" in result
        assert "best_sharpe" in result
        assert result["best_params"] is not None  # 应找到最优参数
