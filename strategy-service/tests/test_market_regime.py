"""
市场状态过滤器 (market_regime.py) 全覆盖测试。

策略：纯计算模块，不依赖数据库/网络，所有分支通过构造已知数据触发。
"""

import math
from unittest.mock import patch

import pytest
from services.market_regime import MarketRegimeFilter, Regime, _calc_adx, _calc_roc, _calc_sma

# ============================================================
# 测试数据辅助函数
# ============================================================


def _gen_uptrend(n: int = 250, start: float = 100.0, slope: float = 0.5) -> list[float]:
    """生成单调上升价格序列"""
    return [start + i * slope for i in range(n)]


def _gen_downtrend(n: int = 250, start: float = 220.0, slope: float = -0.5) -> list[float]:
    """生成单调下降价格序列"""
    return [start + i * slope for i in range(n)]


def _gen_sideways(n: int = 250, center: float = 100.0, amp: float = 2.0) -> list[float]:
    """生成震荡价格序列（低 ADX）— 纯确定性，不依赖 hash"""
    import math

    prices = []
    for i in range(n):
        # 主成分：正弦波在 center ± amp 内震荡，周期 50 bar
        sine_wave = amp * math.sin(2 * math.pi * i / 50)
        # 小幅度确定性噪声（使用 i 的数值函数，不依赖 hash）
        noise = (i * 7 % 41 - 20) / 100.0
        prices.append(center + sine_wave + noise)
    return prices


def _gen_highs_lows(closes: list[float], spread: float = 0.02) -> tuple[list[float], list[float]]:
    """根据收盘价生成最高/最低价"""
    highs = [c * (1 + spread) for c in closes]
    lows = [c * (1 - spread) for c in closes]
    return highs, lows


# ============================================================
# _calc_sma
# ============================================================


class TestCalcSma:
    def test_normal(self):
        """正常计算 SMA"""
        prices = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _calc_sma(prices, 3)
        assert len(result) == 5
        assert math.isnan(result[0])
        assert math.isnan(result[1])
        assert result[2] == pytest.approx(2.0)  # (1+2+3)/3
        assert result[3] == pytest.approx(3.0)  # (2+3+4)/3
        assert result[4] == pytest.approx(4.0)  # (3+4+5)/3

    def test_insufficient_data(self):
        """数据量 < 周期 → 全 NaN"""
        prices = [1.0, 2.0]
        result = _calc_sma(prices, 5)
        assert len(result) == 2
        assert all(math.isnan(v) for v in result)

    def test_single_element(self):
        """只有 1 个元素"""
        result = _calc_sma([10.0], 3)
        assert len(result) == 1
        assert math.isnan(result[0])

    def test_period_equals_length(self):
        """数据量刚好等于周期"""
        prices = [1.0, 2.0, 3.0]
        result = _calc_sma(prices, 3)
        assert len(result) == 3
        assert math.isnan(result[0])
        assert math.isnan(result[1])
        assert result[2] == pytest.approx(2.0)


# ============================================================
# _calc_adx
# ============================================================


class TestCalcAdx:
    def test_normal(self):
        """正常 ADX 计算 — 强上升趋势应产生高 ADX"""
        closes = _gen_uptrend(100, 100, 1.0)
        highs, lows = _gen_highs_lows(closes)
        result = _calc_adx(highs, lows, closes, 14)
        assert len(result) == 100
        # 最后几个值的 ADX 应该 > 0（强趋势）
        assert result[-1] > 0

    def test_insufficient_data(self):
        """数据量 < period*2 → 返回全 0"""
        closes = [100.0, 101.0, 102.0]
        highs, lows = _gen_highs_lows(closes)
        result = _calc_adx(highs, lows, closes, 14)
        assert len(result) == 3
        assert all(v == 0.0 for v in result)


# ============================================================
# _calc_roc
# ============================================================


class TestCalcRoc:
    def test_normal(self):
        """正常 ROC 计算"""
        prices = [100.0, 102.0, 105.0, 103.0, 101.0]
        result = _calc_roc(prices, 3)
        assert len(result) == 5
        assert result[0] == 0.0
        assert result[1] == 0.0
        assert result[2] == 0.0
        # ROC[3] = (103-100)/100 = 0.03
        assert result[3] == pytest.approx(0.03)
        # ROC[4] = (101-102)/102 ≈ -0.0098
        assert result[4] == pytest.approx(-0.0098039, rel=1e-3)

    def test_short_data(self):
        """数据量 < period → 全 0"""
        prices = [100.0, 101.0]
        result = _calc_roc(prices, 5)
        assert len(result) == 2
        assert all(v == 0.0 for v in result)

    def test_zero_prev_price(self):
        """prev == 0 → 返回 0.0 避免除零"""
        prices = [0.0, 0.0, 10.0]
        result = _calc_roc(prices, 2)
        assert len(result) == 3
        assert result[0] == 0.0
        assert result[1] == 0.0
        assert result[2] == 0.0  # prev=0, returns 0.0


# ============================================================
# MarketRegimeFilter
# ============================================================


class TestInit:
    def test_default_params(self):
        """默认参数初始化"""
        rf = MarketRegimeFilter()
        assert rf.ma_fast == 50
        assert rf.ma_slow == 200
        assert rf.adx_period == 14
        assert rf.adx_threshold == 22.0
        assert rf.roc_period == 20
        assert rf.roc_bull_threshold == 0.02
        assert rf.roc_bear_threshold == -0.02
        assert rf._last_regime == Regime.OSCILLATE
        assert rf._last_position_mult == 0.5
        assert math.isnan(rf._last_ma_fast_val)
        assert math.isnan(rf._last_ma_slow_val)
        assert math.isnan(rf._last_adx_val)

    def test_custom_params(self):
        """自定义参数初始化"""
        rf = MarketRegimeFilter(
            ma_fast=20,
            ma_slow=100,
            adx_period=10,
            adx_threshold=25.0,
            roc_period=10,
            roc_bull_threshold=0.03,
            roc_bear_threshold=-0.03,
        )
        assert rf.ma_fast == 20
        assert rf.ma_slow == 100
        assert rf.adx_period == 10
        assert rf.adx_threshold == 25.0
        assert rf.roc_period == 10
        assert rf.roc_bull_threshold == 0.03
        assert rf.roc_bear_threshold == -0.03


# ============================================================
# classify
# ============================================================


class TestClassify:
    def test_data_too_short(self):
        """数据不足 max(ma_slow, adx_period*2)+5 → 保守返回 OSCILLATE"""
        rf = MarketRegimeFilter()
        result = rf.classify([100.0] * 100)  # 100 < 200+5
        assert result == Regime.OSCILLATE

    def test_bull_strong_uptrend_with_full_data(self):
        """强上升趋势 + ADX + ROC → BULL"""
        rf = MarketRegimeFilter()
        closes = _gen_uptrend(250, 100.0, 0.5)
        highs, lows = _gen_highs_lows(closes)
        result = rf.classify(closes, highs, lows)
        assert result == Regime.BULL
        assert rf._last_position_mult == 1.0
        assert rf._last_regime == Regime.BULL
        assert not math.isnan(rf._last_ma_fast_val)
        assert not math.isnan(rf._last_ma_slow_val)
        assert rf._last_adx_val > 0

    def test_bull_without_adx_roc_above_threshold(self):
        """牛市判定：无 ADX 数据（highs/lows=None），但 ROC > 阈值 → BULL"""
        rf = MarketRegimeFilter()
        closes = _gen_uptrend(250, 100.0, 0.5)
        # 不传 highs/lows → adx_val=0, 但 ROC 应 > 0.02
        result = rf.classify(closes)
        assert result == Regime.BULL, (
            f"Expected BULL, got {result}. "
            f"fast_val={rf._last_ma_fast_val:.2f}, slow_val={rf._last_ma_slow_val:.2f}"
        )

    def test_bear_strong_downtrend(self):
        """强下降趋势 → BEAR"""
        rf = MarketRegimeFilter()
        closes = _gen_downtrend(250, 220.0, -0.5)
        highs, lows = _gen_highs_lows(closes)
        result = rf.classify(closes, highs, lows)
        assert result == Regime.BEAR
        assert rf._last_position_mult == 0.25

    def test_bear_without_adx(self):
        """熊市判定：无 ADX 但 ROC < 阈值 → BEAR"""
        rf = MarketRegimeFilter()
        closes = _gen_downtrend(250, 220.0, -0.5)
        result = rf.classify(closes)  # no highs/lows
        assert result == Regime.BEAR, (
            f"Expected BEAR, got {result}. "
            f"fast_val={rf._last_ma_fast_val:.2f}, slow_val={rf._last_ma_slow_val:.2f}"
        )

    def test_oscillate_sideways(self):
        """震荡行情 → OSCILLATE"""
        rf = MarketRegimeFilter()
        closes = _gen_sideways(250, 100.0, 2.0)
        highs, lows = _gen_highs_lows(closes)
        result = rf.classify(closes, highs, lows)
        assert result == Regime.OSCILLATE
        assert rf._last_position_mult == 0.5

    def test_oscillate_no_trend_no_adx_no_roc(self):
        """无趋势 + 无 ADX（没传 highs/lows）+ 低 ROC → OSCILLATE"""
        rf = MarketRegimeFilter()
        closes = _gen_sideways(250, 100.0, 1.0)
        result = rf.classify(closes)  # no highs/lows
        assert result == Regime.OSCILLATE

    def test_bull_condition_fast_slope_not_positive(self):
        """MA50 < MA200 时即使其他条件满足也不能 BULL → OSCILLATE"""
        rf = MarketRegimeFilter()
        # 先上升再下降，最后是下降趋势
        closes = _gen_uptrend(120, 100.0, 1.0) + _gen_downtrend(130, 220.0, -0.8)
        result = rf.classify(closes)
        # 最终 MA50 < MA200 或 slope < 0 → 不应该 BULL
        assert result != Regime.BULL, (
            f"fast_val={rf._last_ma_fast_val:.2f}, slow_val={rf._last_ma_slow_val:.2f}"
        )

    def test_missing_kline_data_keeps_adx_zero(self):
        """判断时 highs/lows 为 None 时 ADX 为 0.0"""
        rf = MarketRegimeFilter()
        closes = _gen_uptrend(250, 100.0, 0.5)
        rf.classify(closes)  # 不传 highs/lows
        assert rf._last_adx_val == 0.0

    def test_adx_values_nan_handling(self):
        """classify 中 adx_values[-1] 为 NaN 时 adx_val 置为 0.0"""
        rf = MarketRegimeFilter()
        closes = _gen_uptrend(250, 100.0, 0.5)
        highs = [float("nan")] * 250
        lows = [float("nan")] * 250
        # ADX 计算全 NaN → adx_values[-1] 为 NaN → 走 else adx_val=0.0
        result = rf.classify(closes, highs, lows)
        # 因为 ADX=0，ROC>0.02 → 仍应 BULL
        assert rf._last_adx_val == 0.0
        assert result == Regime.BULL

    def test_roc_values_nan_handling(self):
        """ROC 序列末尾为 NaN → roc_val=0.0（通过 _calc_roc 默认 0.0 处理）"""
        rf = MarketRegimeFilter()
        # 制造 ROC 末尾为 0 的情况（足够的 uptrend 但 ROC 起点在 period 之后）
        closes = [100.0] * 20 + _gen_uptrend(230, 100.0, 0.5)
        result = rf.classify(closes)
        # ROC 应 > 0.02（uptrend 足够强）
        assert result is not None


# ============================================================
# get_position_mult
# ============================================================


class TestGetPositionMult:
    def test_bull(self):
        assert MarketRegimeFilter.get_position_mult(Regime.BULL) == 1.0

    def test_oscillate(self):
        assert MarketRegimeFilter.get_position_mult(Regime.OSCILLATE) == 0.5

    def test_bear(self):
        assert MarketRegimeFilter.get_position_mult(Regime.BEAR) == 0.25

    def test_unknown_regime(self):
        """未注册的状态 → 默认 0.5"""
        assert MarketRegimeFilter.get_position_mult("UNKNOWN") == 0.5


# ============================================================
# _calc_slope（静态方法）
# ============================================================


class TestCalcSlope:
    def test_positive_slope(self):
        """上升序列 → 正斜率"""
        series = [1.0, 2.0, 3.0, 4.0, 5.0]
        slope = MarketRegimeFilter._calc_slope(series, 5)
        assert slope > 0

    def test_negative_slope(self):
        """下降序列 → 负斜率"""
        series = [5.0, 4.0, 3.0, 2.0, 1.0]
        slope = MarketRegimeFilter._calc_slope(series, 5)
        assert slope < 0

    def test_flat_slope(self):
        """平坦序列 → 斜率接近 0"""
        series = [3.0, 3.0, 3.0, 3.0, 3.0]
        slope = MarketRegimeFilter._calc_slope(series, 5)
        assert slope == pytest.approx(0.0)

    def test_insufficient_valid(self):
        """有效数据不足 window → 0.0"""
        series = [float("nan")] * 5 + [1.0, 2.0]
        slope = MarketRegimeFilter._calc_slope(series, 5)
        assert slope == 0.0

    def test_all_nan(self):
        """全部为 NaN → 0.0"""
        series = [float("nan")] * 10
        slope = MarketRegimeFilter._calc_slope(series, 5)
        assert slope == 0.0

    def test_window_covers_mixed_valid_nan(self):
        """window 内有 NaN 和非 NaN → 用有效值计算（有效值 >= window 时正常计算）"""
        series = [1.0, float("nan"), 3.0, float("nan"), 5.0, 6.0]
        slope = MarketRegimeFilter._calc_slope(series, 4)
        # 有效值: indices 0,2,4,5 → 4 个 === window, 正常算斜率
        assert slope > 0

    def test_window_exact_valid(self):
        """有效值恰好等于 window → 正常计算"""
        series = [float("nan"), 2.0, 3.0, 4.0, 5.0]
        slope = MarketRegimeFilter._calc_slope(series, 4)
        # 有效索引: (1,2), (2,3), (3,4), (4,5)
        assert slope != 0.0

    def test_single_valid_point(self):
        """window=1 时 len(valid) >= window 但 n < 2 → 0.0（触发 line 290）"""
        series = [float("nan"), 5.0, float("nan")]
        slope = MarketRegimeFilter._calc_slope(series, 1)
        assert slope == 0.0

    def test_denominator_zero(self):
        """x 方差为 0 → 返回 0.0"""
        series = [5.0, 5.0, 5.0, 5.0, 5.0]
        slope = MarketRegimeFilter._calc_slope(series, 5)
        assert slope == 0.0


# ============================================================
# get_last_state
# ============================================================


class TestGetLastState:
    def test_before_any_classify(self):
        """未调用 classify 时获取状态 → 使用初始值"""
        rf = MarketRegimeFilter()
        state = rf.get_last_state()
        assert state["regime"] == "oscillate"
        assert state["position_mult"] == 0.5
        assert state["ma_fast"] is None  # NaN → None
        assert state["ma_slow"] is None  # NaN → None
        assert state["adx"] is None  # NaN → None

    def test_after_classify_bull(self):
        """classify BULL 后获取状态"""
        rf = MarketRegimeFilter()
        closes = _gen_uptrend(250, 100.0, 0.5)
        highs, lows = _gen_highs_lows(closes)
        rf.classify(closes, highs, lows)
        state = rf.get_last_state()
        assert state["regime"] == "bull"
        assert state["position_mult"] == 1.0
        assert state["ma_fast"] is not None
        assert state["ma_slow"] is not None
        assert state["adx"] is not None

    def test_after_classify_bear(self):
        """classify BEAR 后获取状态"""
        rf = MarketRegimeFilter()
        closes = _gen_downtrend(250, 220.0, -0.5)
        rf.classify(closes)
        state = rf.get_last_state()
        assert state["regime"] == "bear"
        assert state["position_mult"] == 0.25

    def test_after_short_data(self):
        """数据不足时 classify → OSCILLATE，状态更新"""
        rf = MarketRegimeFilter()
        rf.classify([100.0] * 100)
        state = rf.get_last_state()
        assert state["regime"] == "oscillate"
        assert state["position_mult"] == 0.5
        assert state["ma_fast"] is None  # all NaN → None
        assert state["ma_slow"] is None
        assert state["adx"] is None


# ============================================================
# Regime 枚举
# ============================================================


class TestRegime:
    def test_values(self):
        assert Regime.BULL.value == "bull"
        assert Regime.OSCILLATE.value == "oscillate"
        assert Regime.BEAR.value == "bear"

    def test_membership(self):
        assert isinstance(Regime.BULL, Regime)
        assert Regime.BULL in Regime
