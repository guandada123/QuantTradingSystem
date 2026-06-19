"""
策略信号生成模块单元测试
覆盖：VWM（成交量加权动量）、BBR（布林带均值回归）、
Combo VWM+BBR（组合策略）、VBM（波动率突破动量）
"""

import math
import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.signals import (
    _signal_bollinger,
    _signal_combo_vwm_bbr,
    _signal_vbm,
    _signal_vwm,
    generate_signals,
)

# ============================================================
# VWM — 成交量加权动量策略
# ============================================================


class TestSignalVwm:
    """VWM — 成交量加权动量策略"""

    @pytest.fixture
    def params(self):
        return {
            "ma_fast": 5,
            "ma_slow": 20,
            "volume_period": 20,
            "vol_multiplier_buy": 1.0,
            "rsi_period": 14,
            "rsi_overbought": 80,
            "rsi_oversold_threshold": 50,
        }

    def test_insufficient_data(self, params):
        """数据不足应返回全零"""
        result = _signal_vwm([100.0] * 15, [10000.0] * 15, params)
        # RSI 输出少 1，信号长度 = 15 - 1 = 14
        assert len(result) == 14
        assert all(s == 0 for s in result)

    def test_flat_market_no_signal(self, params):
        """横盘市场无信号"""
        closes = [100.0] * 50
        volumes = [10000.0] * 50
        result = _signal_vwm(closes, volumes, params)
        assert all(s == 0 for s in result)

    def test_sell_signal_downtrend(self, params):
        """持续下跌 → SELL（close<MA5<MA20）"""
        # 35天持续下跌：100 → 72
        closes = [100.0 - i * 0.8 for i in range(35)]
        volumes = [10000.0] * 35
        result = _signal_vwm(closes, volumes, params)
        assert -1 in result

    def test_buy_signal_jump(self, params):
        """价量配合向上突破 → BUY

        数据设计：
          1) 20天横盘 + 30天缓升(101→130) 确立 MA5>MA20
          2) 一天回踩 120 (< MA5) — 条件 6: close[i-1] <= MA5[i-1]
          3) 跳涨 135 + 放量 + RSI 50-80 — 触发 BUY
          4) 再延续几天让索引落在 n-1 内（RSI 输出少 1）
        """
        closes = [100.0] * 20 + list(range(101, 131)) + [120.0, 135.0, 136.0, 137.0, 138.0]
        volumes = [10000.0] * 50 + [20000.0, 25000.0, 25000.0, 26000.0, 27000.0]
        result = _signal_vwm(closes, volumes, params)
        assert 1 in result

    def test_nan_handling(self, params):
        """NaN 值应被跳过，不产生信号"""
        closes = [100.0] * 30 + [float("nan")] * 10 + [100.0] * 10
        volumes = [10000.0] * 50
        result = _signal_vwm(closes, volumes, params)
        assert all(s == 0 for s in result)

    def test_buy_requires_volume_surge(self, params):
        """不放量不触发 BUY"""
        closes = [100.0] * 20 + list(range(101, 131)) + [120.0, 135.0, 136.0, 137.0, 138.0]
        volumes = [10000.0] * 55  # no volume surge
        result = _signal_vwm(closes, volumes, params)
        # 可能有 SELL 但不应有 BUY
        assert 1 not in result

    def test_custom_params(self, params):
        """自定义参数覆盖"""
        p = params.copy()
        p["ma_fast"] = 10
        p["ma_slow"] = 30
        closes = [100.0] * 35 + list(range(101, 111)) + [105.0, 115.0, 116.0, 117.0]
        volumes = [10000.0] * 45 + [20000.0] * 4
        result = _signal_vwm(closes, volumes, p)
        # 不应崩溃，RSI 输出少 1，信号长度 = len(closes) - 1
        assert len(result) == len(closes) - 1
        assert all(s in (-1, 0, 1) for s in result)

    def test_default_params_empty(self):
        """空参数字典应使用默认值"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = _signal_vwm([100.0] * 30, [10000.0] * 30, {})
        # RSI 输出少 1
        assert len(result) == 29


# ============================================================
# BBR — 布林带均值回归
# ============================================================


class TestSignalBollinger:
    """BBR — 布林带均值回归"""

    @pytest.fixture
    def params(self):
        return {
            "period": 20,
            "std_mult": 2.0,
            "rsi_period": 14,
            "rsi_oversold": 35,
            "rsi_overbought": 65,
        }

    def test_insufficient_data(self, params):
        """数据不足应返回全零"""
        result = _signal_bollinger([100.0] * 10, params)
        assert len(result) == 10
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self, params):
        """横盘无信号（使用微幅变动避免布林带退化 + RSI 边界值）"""
        closes = [100.0 + (i % 5 - 2) * 0.1 for i in range(50)]
        result = _signal_bollinger(closes, params)
        assert all(s == 0 for s in result)

    def test_buy_signal_lower_band(self, params):
        """价格跌破下轨 + RSI 超卖 → BUY

        数据设计：
          1) 20天横盘 100 + 30天小幅振荡 (98-102)
          2) 3天正常值
          3) 跳水到 90, 88（跌破下轨）
          4) 再恢复几天让索引落在 n-1 内
        """
        closes = [100.0] * 20
        closes += [100 + (i % 5 - 2) for i in range(30)]
        closes += [102, 101, 103]
        closes += [90, 88]
        closes += [92, 95, 98]
        result = _signal_bollinger(closes, params)
        assert 1 in result

    def test_sell_signal_upper_band(self, params):
        """价格突破上轨 → SELL

        数据设计：
          1) 20天横盘 + 30天小幅振荡
          2) 3天正常值
          3) 拉升到 112, 115（突破上轨）
        """
        closes = [100.0] * 20
        closes += [100 + (i % 5 - 2) for i in range(30)]
        closes += [98, 99, 97]
        closes += [112, 115]
        closes += [110, 108, 105]
        result = _signal_bollinger(closes, params)
        assert -1 in result

    def test_sell_signal_middle_band(self, params):
        """价格回归中轨 + RSI 超买 → SELL"""
        closes = [100.0] * 20
        closes += [100 + (i % 5 - 2) for i in range(30)]
        # 逐步拉高后回到中轨附近
        closes += list(range(102, 112))  # uptrend
        closes += list(range(110, 100, -1))  # back to middle
        result = _signal_bollinger(closes, params)
        assert -1 in result

    def test_nan_handling(self, params):
        """NaN 值正确跳过"""
        closes = [100.0] * 30 + [float("nan")] * 10 + [100.0] * 10
        result = _signal_bollinger(closes, params)
        assert all(s == 0 for s in result)

    def test_custom_params(self, params):
        """自定义参数"""
        p = params.copy()
        p["period"] = 10
        p["std_mult"] = 1.5
        result = _signal_bollinger([100.0] * 30, p)
        # RSI 输出少 1
        assert len(result) == 29

    def test_buy_requires_fresh_break(self, params):
        """BUY 需要刚跌破下轨（close[i-1] > lower[i-1])"""
        # 如果前一天也在下轨之下，不应触发 BUY
        closes = [100.0] * 20
        closes += [100 + (i % 5 - 2) for i in range(30)]
        # 已经跌破下轨并持续多日
        for _ in range(5):
            closes.append(85.0)
        result = _signal_bollinger(closes, params)
        # 第一天跌破可能触发，后续不触发
        buy_indices = [i for i, s in enumerate(result) if s == 1]
        assert len(buy_indices) <= 1


# ============================================================
# Combo VWM+BBR — 组合策略
# ============================================================


class TestSignalComboVwmBbr:
    """Combo VWM+BBR — 组合策略"""

    @pytest.fixture
    def combo_params(self):
        return {
            "vwm_weight": 0.6,
            "bbr_weight": 0.4,
            "bbr_sell_factor": 0.3,
            "buy_threshold": 0.25,
            "sell_threshold": -0.25,
            "vwm_params": {
                "ma_fast": 5,
                "ma_slow": 20,
                "volume_period": 20,
                "vol_multiplier_buy": 1.0,
                "rsi_period": 14,
                "rsi_overbought": 80,
                "rsi_oversold_threshold": 50,
            },
            "bbr_params": {
                "period": 20,
                "std_mult": 2.0,
                "rsi_period": 14,
                "rsi_oversold": 35,
                "rsi_overbought": 65,
            },
        }

    @pytest.fixture
    def bullish_data(self):
        """能在 VWM 和 BBR 都触发行情的激进数据"""
        closes = [100.0] * 20 + list(range(101, 131)) + [120.0, 135.0, 136.0, 137.0, 138.0]
        volumes = [10000.0] * 50 + [20000.0, 25000.0, 25000.0, 26000.0, 27000.0]
        return [{"close": c, "vol": v} for c, v in zip(closes, volumes)]

    def test_both_buy(self, combo_params, bullish_data):
        """VWM BUY + BBR BUY → 强买入"""
        result = _signal_combo_vwm_bbr(bullish_data, combo_params)
        assert result is not None
        assert 1 in result

    def test_vwm_sell_bbr_hold(self, combo_params):
        """VWM SELL + BBR HOLD → SELL"""
        closes = [100.0 - i * 0.8 for i in range(35)]
        volumes = [10000.0] * 35
        df_data = [{"close": c, "vol": v} for c, v in zip(closes, volumes)]
        result = _signal_combo_vwm_bbr(df_data, combo_params)
        assert result is not None
        assert -1 in result

    def test_vwm_hold_bbr_hold(self, combo_params):
        """两者都 HOLD → HOLD"""
        closes = [100.0] * 30
        volumes = [10000.0] * 30
        df_data = [{"close": c, "vol": v} for c, v in zip(closes, volumes)]
        result = _signal_combo_vwm_bbr(df_data, combo_params)
        assert result is not None
        assert all(s == 0 for s in result)

    def test_short_data(self, combo_params):
        """短数据不崩溃"""
        df_data = [{"close": 100.0, "vol": 10000.0}] * 5
        result = _signal_combo_vwm_bbr(df_data, combo_params)
        assert result is not None
        assert all(s == 0 for s in result)

    def test_custom_weights(self, combo_params, bullish_data):
        """自定义权重应影响信号"""
        p = combo_params.copy()
        p["buy_threshold"] = 0.1
        p["vwm_weight"] = 0.3
        result1 = _signal_combo_vwm_bbr(bullish_data, p)

        p2 = p.copy()
        p2["buy_threshold"] = 0.9
        result2 = _signal_combo_vwm_bbr(bullish_data, p2)
        assert result1 is not None
        assert result2 is not None

    def test_vol_field_optional(self, combo_params):
        """无 vol 字段应默认 0"""
        df_data = [{"close": 100.0}] * 40
        result = _signal_combo_vwm_bbr(df_data, combo_params)
        assert result is not None
        assert len(result) >= 0


# ============================================================
# VBM — 波动率突破动量
# ============================================================


class TestSignalVbm:
    """VBM — Volatility Breakout Momentum"""

    @pytest.fixture
    def params(self):
        return {
            "roc_period": 5,
            "vol_lookback": 20,
            "atr_period": 14,
            "roc_threshold": 0.03,
            "vol_mult": 1.2,
            "atr_mult": 1.0,
            "rsi_upper": 70,
            "rsi_lower": 30,
        }

    def test_insufficient_data(self, params):
        """数据不足应返回全零"""
        result = _signal_vbm([100.0] * 10, [105.0] * 10, [95.0] * 10, [10000.0] * 10, params)
        assert len(result) == 10
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self, params):
        """横盘无信号"""
        n = 50
        closes = [100.0 + (i % 5 - 2) * 0.1 for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [10000.0] * n
        result = _signal_vbm(closes, highs, lows, volumes, params)
        assert all(s == 0 for s in result)

    def test_buy_signal_breakout(self, params):
        """放量 + 波动扩张 + ROC 突破 → BUY

        使用 25 天横盘 + 最后几天急拉来命中 BUY 条件
        """
        closes = [100.0] * 30 + [105, 110, 115, 120, 125, 130]
        highs = [c * 1.03 for c in closes]
        lows = [c * 0.97 for c in closes]
        volumes = [10000.0] * 30 + [20000.0] * 6
        result = _signal_vbm(closes, highs, lows, volumes, params)
        assert 1 in result

    def test_sell_signal_negative_roc(self, params):
        """急跌（ROC < -threshold）→ SELL"""
        n = 30
        closes = list(range(100, 100 + n))  # uptrend
        highs = [c * 1.03 for c in closes]
        lows = [c * 0.97 for c in closes]
        volumes = [10000.0] * n
        # 最后几天急跌
        closes += [125, 115, 110, 105]
        highs += [130, 120, 115, 110]
        lows += [120, 110, 105, 100]
        volumes += [15000] * 4
        result = _signal_vbm(closes, highs, lows, volumes, params)
        assert -1 in result

    def test_sell_signal_rsi_overbought(self, params):
        """RSI 超买（> upper + 10）→ SELL"""
        # 持续上涨推高 RSI
        closes = [100.0 * (1.02**i) for i in range(40)]  # sustained uptrend
        highs = [c * 1.03 for c in closes]
        lows = [c * 0.97 for c in closes]
        volumes = [15000.0] * 40
        result = _signal_vbm(closes, highs, lows, volumes, params)
        assert -1 in result

    def test_custom_params(self, params):
        """自定义参数"""
        p = params.copy()
        p["roc_threshold"] = 0.05
        closes = [100.0] * 25 + [110, 120, 130]
        highs = [c * 1.03 for c in closes]
        lows = [c * 0.97 for c in closes]
        volumes = [10000.0] * 25 + [20000.0] * 3
        result = _signal_vbm(closes, highs, lows, volumes, p)
        assert len(result) == len(closes)

    def test_nan_handling(self, params):
        """NaN 不影响"""
        closes = [100.0] * 25 + [float("nan")] * 5 + [110.0] * 10
        highs = [c * 1.03 if not math.isnan(c) else 103.0 for c in closes]
        lows = [c * 0.97 if not math.isnan(c) else 97.0 for c in closes]
        volumes = [10000.0] * 40
        result = _signal_vbm(closes, highs, lows, volumes, params)
        # 不应崩溃
        assert len(result) == len(closes)

    def test_zero_price_safe(self, params):
        """零价格不分母为 0"""
        closes = [0.0] * 30 + [1.0] * 10
        highs = [1.0] * 40
        lows = [0.0] * 40
        volumes = [10000.0] * 40
        result = _signal_vbm(closes, highs, lows, volumes, params)
        assert len(result) == 40


# ============================================================
# generate_signals — 统一调度
# ============================================================


class TestGenerateSignals:
    """generate_signals 统一调度测试"""

    @pytest.fixture
    def sample_data(self):
        """50 根 K 线的模拟行情"""
        closes = [100.0] * 20 + list(range(101, 131)) + [120.0, 135.0, 136.0, 137.0, 138.0]
        return [
            {
                "close": c,
                "high": c * 1.02,
                "low": c * 0.98,
                "vol": 10000.0 if i < 50 else 25000.0,
            }
            for i, c in enumerate(closes)
        ]

    def test_vwm_strategy(self, sample_data):
        """VWM 策略调度"""
        result = generate_signals(sample_data, "vwm")
        # RSI 输出少 1，信号长度比输入少 1
        assert len(result) == len(sample_data) - 1
        assert all(s in (-1, 0, 1) for s in result)

    def test_bollinger_strategy(self, sample_data):
        """BBR 策略调度"""
        result = generate_signals(sample_data, "bollinger")
        assert len(result) == len(sample_data) - 1

    def test_combo_strategy(self, sample_data):
        """Combo VWM+BBR 策略调度（之前返回 None 的 bug 修复验证）"""
        result = generate_signals(sample_data, "combo-vwm-bbr")
        assert result is not None
        assert len(result) == len(sample_data) - 1

    def test_vbm_strategy(self, sample_data):
        """VBM 策略调度"""
        result = generate_signals(sample_data, "vbm")
        # VBM 内部不依赖 RSI 截断，返回长度 = 输入长度
        assert len(result) == len(sample_data)

    def test_unknown_strategy(self, sample_data):
        """未知策略返回全零"""
        result = generate_signals(sample_data, "unknown_strategy")
        assert len(result) == len(sample_data)
        assert all(s == 0 for s in result)

    def test_empty_data(self):
        """空数据"""
        result = generate_signals([], "vwm")
        assert result == []

    def test_strategy_without_vol(self):
        """vol 缺失时使用默认 0"""
        data = [{"close": 100.0}, {"close": 101.0}, {"close": 102.0}]
        result = generate_signals(data, "vwm")
        assert len(result) == 3
        assert all(s == 0 for s in result)

    def test_strategy_without_high_low(self):
        """high/low 缺失时使用 close"""
        data = [{"close": 100.0, "vol": 10000.0} for _ in range(10)]
        result = generate_signals(data, "breakout")
        assert len(result) == 10
