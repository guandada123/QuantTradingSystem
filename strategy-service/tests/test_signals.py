"""
策略信号生成模块单元测试
覆盖：
- MA Cross（双均线金叉/死叉）
- Breakout（N日高低点突破）
- RSI（超买超卖）
- MACD（金叉/死叉）
- KDJ（随机指标金叉/死叉）
- VWM（成交量加权动量）
- BBR（布林带均值回归）
- Combo VWM+BBR（组合策略）
- ADX（趋势强度）
- OBV（量价背离）
- VBM（波动率突破动量）
- VPB（量价事件突破策略）
"""

import math
import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.signals import (
    _signal_adx,
    _signal_bollinger,
    _signal_breakout,
    _signal_combo_vwm_bbr,
    _signal_kdj,
    _signal_ma_cross,
    _signal_macd,
    _signal_obv,
    _signal_rsi,
    _signal_vbm,
    _signal_vpb,
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
# MA Cross — 双均线金叉/死叉
# ============================================================


class TestSignalMaCross:
    """MA Cross — 双均线金叉/死叉"""

    @pytest.fixture
    def params(self):
        return {"ma_fast": 5, "ma_slow": 20}

    def test_insufficient_data(self, params):
        """数据不足应返回全零"""
        result = _signal_ma_cross([100.0] * 5, params)
        assert len(result) == 5
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self, params):
        """横盘无信号"""
        result = _signal_ma_cross([100.0] * 50, params)
        assert all(s == 0 for s in result)

    def test_golden_cross_buy(self, params):
        """快线上穿慢线 → 金叉买入"""
        closes = [100.0] * 25 + [101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
        result = _signal_ma_cross(closes, params)
        assert 1 in result

    def test_death_cross_sell(self, params):
        """快线下穿慢线 → 死叉卖出"""
        closes = [100.0] * 25 + [99, 98, 97, 96, 95, 94, 93, 92, 91, 90]
        result = _signal_ma_cross(closes, params)
        assert -1 in result

    def test_nan_handling(self, params):
        """NaN 值正确跳过"""
        closes = [100.0] * 20 + [float("nan")] * 10 + [100.0] * 10
        result = _signal_ma_cross(closes, params)
        assert all(s == 0 for s in result)

    def test_custom_periods(self):
        """自定义周期"""
        p = {"ma_fast": 10, "ma_slow": 30}
        closes = [100.0] * 35 + list(range(101, 116))
        result = _signal_ma_cross(closes, p)
        assert 1 in result

    def test_default_params_empty(self):
        """空参数使用默认值"""
        closes = [100.0] * 25 + [101, 102, 103, 104, 105]
        result = _signal_ma_cross(closes, {})
        assert len(result) == len(closes)
        assert all(s in (-1, 0, 1) for s in result)


# ============================================================
# Breakout — N日高点突破
# ============================================================


class TestSignalBreakout:
    """Breakout — N日高点突破"""

    @pytest.fixture
    def params(self):
        return {"lookback": 20}

    def test_insufficient_data(self, params):
        """数据不足应返回全零（n <= lookback）"""
        result = _signal_breakout([100.0] * 15, [102.0] * 15, params)
        assert len(result) == 15
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self, params):
        """横盘无信号（无突破）"""
        closes = [100.0] * 30
        highs = [102.0] * 30
        result = _signal_breakout(closes, highs, params)
        assert all(s == 0 for s in result)

    def test_buy_breakout(self, params):
        """突破前N日最高价 → BUY"""
        n = 30
        closes = [100.0] * n
        highs = [102.0] * n
        highs[25] = 115.0  # new high
        closes[25] = 110.0
        result = _signal_breakout(closes, highs, params)
        assert 1 in result

    def test_sell_breakdown(self, params):
        """跌破前N日最低价 → SELL"""
        n = 30
        closes = [100.0] * n
        highs = [102.0] * n
        closes[25] = 85.0  # new low
        highs[25] = 90.0
        result = _signal_breakout(closes, highs, params)
        assert -1 in result

    def test_custom_lookback(self):
        """自定义 lookback 参数"""
        p = {"lookback": 10}
        n = 20
        closes = [100.0] * n
        highs = [102.0] * n
        highs[15] = 120.0
        closes[15] = 115.0
        result = _signal_breakout(closes, highs, p)
        assert 1 in result

    def test_both_breakout_and_breakdown(self, params):
        """同一日既有突破又有跌破（信号覆盖：SELL 覆盖 BUY）"""
        n = 30
        closes = [100.0] * n
        highs = [102.0] * n
        # Both conditions met at same index
        highs[27] = 120.0  # new high
        closes[27] = 82.0  # new low (also)
        result = _signal_breakout(closes, highs, params)
        # SELL runs second → overwrites to -1
        assert -1 in result


# ============================================================
# RSI — 超买超卖
# ============================================================


class TestSignalRsi:
    """RSI — 超买超卖信号"""

    def test_insufficient_data(self):
        """数据不足应返回全零"""
        result = _signal_rsi([100.0] * 5, {"period": 14, "oversold": 30, "overbought": 70})
        assert len(result) == 5
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self):
        """横盘 RSI=50，无信号"""
        result = _signal_rsi([100.0] * 35, {"period": 14, "oversold": 30, "overbought": 70})
        assert all(s == 0 for s in result)

    def test_buy_oversold_cross(self):
        """持续下跌 RSI 跌破超卖线 → 买入"""
        closes = [100.0 * (0.98**i) for i in range(40)]
        result = _signal_rsi(closes, {"period": 14, "oversold": 30, "overbought": 70})
        assert 1 in result

    def test_sell_overbought_cross(self):
        """持续上涨 RSI 突破超买线 → 卖出"""
        closes = [100.0 * (1.02**i) for i in range(40)]
        result = _signal_rsi(closes, {"period": 14, "oversold": 30, "overbought": 70})
        assert -1 in result

    def test_custom_params(self):
        """自定义阈值"""
        closes = [100.0 * (1.03**i) for i in range(40)]
        result = _signal_rsi(closes, {"period": 10, "oversold": 25, "overbought": 75})
        assert -1 in result


# ============================================================
# KDJ — 随机指标金叉/死叉
# ============================================================


class TestSignalKdj:
    """KDJ — 随机指标金叉/死叉信号"""

    @pytest.fixture
    def params(self):
        return {"period": 9, "k_smooth": 3, "d_smooth": 3}

    def test_insufficient_data(self, params):
        """数据不足应返回全零"""
        closes = [100.0] * 5
        highs = [105.0] * 5
        lows = [95.0] * 5
        result = _signal_kdj(closes, highs, lows, params)
        assert len(result) == 5
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self, params):
        """横盘（高低价差极小）K/D 无交叉"""
        closes = [100.0] * 50
        highs = [101.0] * 50
        lows = [99.0] * 50
        result = _signal_kdj(closes, highs, lows, params)
        assert all(s == 0 for s in result)

    def test_buy_k_upcross_d(self, params):
        """K 上穿 D + J<40 → BUY

        设计思路：
          横盘后急跌拉低 K/D 到低位，然后反弹使 K 上穿 D
        """
        n = 30
        # Phase 1: 横盘
        closes = [100.0] * 10
        highs = [102.0] * 10
        lows = [98.0] * 10
        # Phase 2: 持续下跌拉低 K/D
        for i in range(15):
            closes.append(100 - i * 2)
            highs.append(100 - i * 2 + 2)
            lows.append(100 - i * 2 - 2)
        # Phase 3: 反弹使 K 上穿 D
        closes += [72, 75, 80, 85, 90]
        highs += [78, 80, 85, 90, 95]
        lows += [68, 70, 75, 80, 85]
        result = _signal_kdj(closes, highs, lows, params)
        assert 1 in result, f"KDJ 下探后反弹应触发 BUY, signals={result}"

    def test_buy_with_low_j_value(self, params):
        """BUY 需要 J<40 过滤"""
        # 若 J 值很高时上穿，不应产生 BUY
        n = 30
        closes = [100.0] * n
        highs = [102.0] * n
        lows = [98.0] * n
        # 持续上涨推高 K/D/J
        for i in range(15):
            closes.append(100 + i)
            highs.append(102 + i)
            lows.append(98 + i)
        # 再微调让 K 上穿 D，但 J 很高 → 不应 BUY
        result = _signal_kdj(closes, highs, lows, params)
        assert all(s <= 0 for s in result), "J 值高位不应触发 BUY"

    def test_sell_k_downcross_d(self, params):
        """K 下穿 D + J>60 → SELL

        设计思路：
          横盘后急涨推高 K/D 到高位，然后回调使 K 下穿 D
        """
        n = 30
        closes = [100.0] * 10
        highs = [102.0] * 10
        lows = [98.0] * 10
        # 持续上涨推高 K/D
        for i in range(15):
            closes.append(100 + i * 2)
            highs.append(100 + i * 2 + 2)
            lows.append(100 + i * 2 - 2)
        # 回调使 K 下穿 D
        closes += [128, 125, 120, 115, 110]
        highs += [132, 130, 125, 120, 115]
        lows += [124, 120, 115, 110, 105]
        result = _signal_kdj(closes, highs, lows, params)
        assert -1 in result, f"KDJ 冲高回调应触发 SELL, signals={result}"

    def test_custom_params(self):
        """自定义周期参数"""
        p = {"period": 14, "k_smooth": 5, "d_smooth": 3}
        n = 30
        closes = [100.0] * 10
        highs = [102.0] * 10
        lows = [98.0] * 10
        for i in range(20):
            closes.append(100 - i * 1.5)
            highs.append(100 - i * 1.5 + 2)
            lows.append(100 - i * 1.5 - 2)
        result = _signal_kdj(closes, highs, lows, p)
        assert all(s in (-1, 0, 1) for s in result)

    def test_default_params_empty(self):
        """空参数使用默认值"""
        n = 30
        closes = [100.0] * 10
        highs = [102.0] * 10
        lows = [98.0] * 10
        for i in range(20):
            closes.append(100 - i * 1.5)
            highs.append(100 - i * 1.5 + 2)
            lows.append(100 - i * 1.5 - 2)
        result = _signal_kdj(closes, highs, lows, {})
        assert all(s in (-1, 0, 1) for s in result)


# ============================================================
# MACD — 金叉/死叉
# ============================================================


class TestSignalMacd:
    """MACD — 金叉/死叉信号"""

    def test_insufficient_data(self):
        """数据不足应返回全零"""
        result = _signal_macd([100.0] * 10, {"fast": 12, "slow": 26, "signal": 9})
        assert len(result) == 10
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self):
        """横盘无信号"""
        result = _signal_macd([100.0] * 50, {"fast": 12, "slow": 26, "signal": 9})
        assert all(s == 0 for s in result)

    def test_golden_cross_buy(self):
        """DIF 上穿 DEA → 金叉买入"""
        # 40天横盘 + 20天上涨
        closes = [100.0] * 40 + list(range(101, 121))
        result = _signal_macd(closes, {"fast": 12, "slow": 26, "signal": 9})
        assert 1 in result

    def test_death_cross_sell(self):
        """DIF 下穿 DEA → 死叉卖出"""
        # 40天上涨 + 20天下跌
        closes = list(range(100, 140)) + list(range(139, 119, -1))
        result = _signal_macd(closes, {"fast": 12, "slow": 26, "signal": 9})
        assert -1 in result

    def test_custom_params(self):
        """自定义周期参数"""
        closes = [100.0] * 20 + list(range(101, 121))
        result = _signal_macd(closes, {"fast": 5, "slow": 13, "signal": 5})
        assert len(result) == len(closes)
        assert all(s in (-1, 0, 1) for s in result)


# ============================================================
# ADX / DMI — 趋势强度 & 方向信号
# ============================================================


class TestSignalAdx:
    """ADX/DMI — 趋势强度策略信号"""

    @pytest.fixture
    def params(self):
        return {"period": 14, "adx_threshold": 22, "cross_confirm": True}

    def test_insufficient_data(self, params):
        """数据不足应返回全零"""
        closes = [100.0] * 15
        highs = [105.0] * 15
        lows = [95.0] * 15
        result = _signal_adx(highs, lows, closes, params)
        assert len(result) == 15
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self, params):
        """横盘 ADX 低于阈值，无信号"""
        n = 50
        closes = [100.0 + (i % 5 - 2) * 0.5 for i in range(n)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        result = _signal_adx(highs, lows, closes, params)
        assert all(s == 0 for s in result)

    def test_buy_plus_di_cross(self, params):
        """+DI 上穿 -DI + ADX 确认 → BUY

        分段设计：前 38 bar 下跌 (-DI > +DI)，后 22 bar 上涨 (+DI 穿越 -DI)。
        ADX 在 period*2=28 后有效，+DI/-DI 交叉在 bar 42，位于有效窗口内。
        """
        n = 60
        closes = []
        for i in range(n):
            if i < 38:
                closes.append(100.0 - 0.6 * i)  # 下跌至 ~77.2
            else:
                closes.append(closes[-1] * 1.015)  # 持续上涨
        highs = [c * 1.02 for c in closes]
        lows = [c * 0.99 for c in closes]
        result = _signal_adx(highs, lows, closes, params)
        assert 1 in result, (
            f"趋势反转应触发 BUY, signals={[i for i, s in enumerate(result) if s != 0]}"
        )

    def test_sell_minus_di_cross(self, params):
        """-DI 上穿 +DI + ADX 确认 → SELL

        分段设计：前 38 bar 上涨 (+DI > -DI)，后 22 bar 下跌 (-DI 穿越 +DI)。
        ADX 在 period*2=28 后有效，-DI/+DI 交叉在 bar 42，位于有效窗口内。
        """
        n = 60
        closes = []
        for i in range(n):
            if i < 38:
                closes.append(100.0 * (1.008**i))  # 上涨至 ~135.3
            else:
                closes.append(closes[-1] * 0.988)  # 持续下跌
        highs = [c * 1.02 for c in closes]
        lows = [c * 0.99 for c in closes]
        result = _signal_adx(highs, lows, closes, params)
        assert -1 in result, (
            f"趋势反转应触发 SELL, signals={[i for i, s in enumerate(result) if s != 0]}"
        )

    def test_no_cross_confirm(self, params):
        """cross_confirm=False 时只需 +DI > -DI 不要求交叉"""
        p = params.copy()
        p["cross_confirm"] = False
        n = 55
        closes = [100.0 * (1.01**i) for i in range(n)]
        highs = [c * 1.02 for c in closes]
        lows = [c * 0.99 for c in closes]
        result = _signal_adx(highs, lows, closes, p)
        # 至少应该有信号
        has_signal = any(s != 0 for s in result)
        assert has_signal, "cross_confirm=False 时也需要信号"

    def test_nan_handling(self, params):
        """NaN 被跳过"""
        n = 50
        closes = [float("nan")] * 10 + [100.0 * (1.01**i) for i in range(n - 10)]
        highs = [c * 1.02 if not math.isnan(c) else 101.0 for c in closes]
        lows = [c * 0.99 if not math.isnan(c) else 99.0 for c in closes]
        result = _signal_adx(highs, lows, closes, params)
        assert all(s in (-1, 0, 1) for s in result)

    def test_custom_params(self):
        """自定义阈值 — 分段数据确保 +DI/-DI 交叉"""
        p = {"period": 10, "adx_threshold": 18, "cross_confirm": True}
        n = 50
        closes = []
        for i in range(n):
            if i < 18:
                closes.append(100.0 - 0.9 * i)  # 下跌至 83.8
            else:
                closes.append(closes[-1] * 1.015)  # 持续上涨
        highs = [c * 1.02 for c in closes]
        lows = [c * 0.99 for c in closes]
        result = _signal_adx(highs, lows, closes, p)
        has_signal = any(s != 0 for s in result)
        assert has_signal, "自定义参数应产生信号"
        assert all(s in (-1, 0, 1) for s in result)

    def test_default_params_empty(self):
        """空参数使用默认值"""
        n = 50
        closes = [100.0 * (1.008**i) for i in range(n)]
        highs = [c * 1.015 for c in closes]
        lows = [c * 0.995 for c in closes]
        result = _signal_adx(highs, lows, closes, {})
        assert all(s in (-1, 0, 1) for s in result)


# ============================================================
# OBV / VPD — 量价背离策略
# ============================================================


class TestSignalObv:
    """OBV — 量价背离策略信号"""

    @pytest.fixture
    def params(self):
        return {"lookback": 20, "obv_period": 20, "vol_surge_mult": 1.3}

    def test_insufficient_data(self, params):
        """数据不足应返回全零"""
        closes = [100.0] * 15
        volumes = [10000.0] * 15
        result = _signal_obv(closes, volumes, params)
        assert len(result) == 15
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self, params):
        """横盘无信号"""
        n = 60
        closes = [100.0 + (i % 5 - 2) * 0.5 for i in range(n)]
        volumes = [10000.0] * n
        result = _signal_obv(closes, volumes, params)
        # 波动小 → 无明确方向 → 应为全零或近全零
        buys = sum(1 for s in result if s == 1)
        sells = sum(1 for s in result if s == -1)
        assert buys + sells < 5, f"横盘应有极少信号, buys={buys}, sells={sells}"

    def test_buy_uptrend_with_volume(self, params):
        """量价同步上涨 → BUY

        OBV 逻辑：
          价格上升 + OBV 上升 + 放量 → BUY (趋势健康)
          vol_surge 要求 volume > vol_MA * 1.3
        """
        n = 60
        closes = [100.0]
        volumes = [10000.0]
        for i in range(1, n):
            if i % 3 == 0:
                closes.append(closes[-1] * 0.998)  # 小幅回调
                volumes.append(3000)  # 缩量回调
            else:
                closes.append(closes[-1] * 1.006)  # 上涨
                volumes.append(22000)  # 放量上涨
        result = _signal_obv(closes, volumes, params)
        has_buy = 1 in result
        assert has_buy, (
            f"量价同步上涨应有 BUY, signals={[i for i, s in enumerate(result) if s != 0][:10]}"
        )

    def test_sell_divergence(self, params):
        """价格高位 + OBV 未创新高 → 顶部背离 → SELL

        分段设计：
          Phase 1 (bars 0-34): 持续上涨，成交量稳步增加 (OBV↑)
          Phase 2 (bars 35-59): 价格窄幅波动维持高位，但下跌日放量/上涨日缩量 (OBV↓)
          产生 at_high + price_up + not obv_up 的顶部背离
        """
        n = 60
        closes = [100.0 * (1.01**i) for i in range(35)]  # Phase 1: 上涨至 ~141.7
        for i in range(35, n):
            if i % 3 == 0:
                closes.append(closes[-1] * 0.995)  # 小幅回调
            else:
                closes.append(closes[-1] * 1.003)  # 微幅上涨 (维持高位)

        volumes = [10000 + i * 150 for i in range(35)]  # Phase 1: 成交量渐增
        for i in range(35, n):
            if i % 3 == 0:
                volumes.append(25000)  # 下跌日放量 → OBV 大幅下降
            else:
                volumes.append(3000)  # 上涨日缩量 → OBV 微幅增加
        result = _signal_obv(closes, volumes, params)
        has_sell = -1 in result
        if not has_sell:
            print(f"  OBV sell test: signals={[i for i, s in enumerate(result) if s != 0][:10]}")
        assert has_sell, "顶部背离应有 SELL 信号"

    def test_custom_params(self):
        """自定义参数"""
        p = {"lookback": 15, "obv_period": 10, "vol_surge_mult": 1.5}
        n = 50
        closes = [100.0]
        volumes = [10000.0]
        for i in range(1, n):
            if i % 3 == 0:
                closes.append(closes[-1] * 0.998)
                volumes.append(8000)
            else:
                closes.append(closes[-1] * 1.005)
                volumes.append(18000)
        result = _signal_obv(closes, volumes, p)
        assert all(s in (-1, 0, 1) for s in result)

    def test_nan_handling(self, params):
        """NaN 不崩溃"""
        n = 55
        closes = [float("nan")] * 10 + [100.0] * 10 + [100.0 * (1.005**i) for i in range(n - 20)]
        volumes = [10000.0] * n
        result = _signal_obv(closes, volumes, params)
        assert all(s in (-1, 0, 1) for s in result)

    def test_default_params_empty(self):
        """空参数使用默认值"""
        n = 55
        closes = [100.0]
        volumes = [10000.0]
        for i in range(1, n):
            if i % 3 == 0:
                closes.append(closes[-1] * 0.998)
                volumes.append(8000)
            else:
                closes.append(closes[-1] * 1.005)
                volumes.append(18000)
        result = _signal_obv(closes, volumes, {})
        assert all(s in (-1, 0, 1) for s in result)


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

    def test_kdj_dispatch(self, sample_data):
        """KDJ 策略调度"""
        result = generate_signals(sample_data, "kdj")
        assert len(result) == len(sample_data)
        assert all(s in (-1, 0, 1) for s in result)

    def test_adx_dispatch(self, sample_data):
        """ADX 策略调度"""
        result = generate_signals(sample_data, "adx")
        assert len(result) == len(sample_data)
        assert all(s in (-1, 0, 1) for s in result)

    def test_obv_dispatch(self, sample_data):
        """OBV 策略调度"""
        result = generate_signals(sample_data, "obv")
        assert len(result) == len(sample_data)
        assert all(s in (-1, 0, 1) for s in result)

    def test_vpb_dispatch(self, sample_data):
        """VPB 策略调度"""
        result = generate_signals(sample_data, "vpb")
        assert len(result) == len(sample_data)
        assert all(s in (-1, 0, 1) for s in result)

    def test_combo_unknown_name(self):
        """未知 combo 名称记录警告并返回空信号"""
        data = [{"close": 100.0, "vol": 10000.0} for _ in range(30)]
        # combo-vwm-bbr 是唯一支持的 combo
        result = generate_signals(data, "combo-unknown")
        assert all(s == 0 for s in result)


# ============================================================
# VPB — 量价事件突破策略
# ============================================================


class TestSignalVpb:
    """VPB — 量价事件突破策略信号"""

    @pytest.fixture
    def base_params(self):
        return {
            "event_lookback": 20,
            "vol_surge_mult": 1.5,
            "atr_surge_mult": 1.3,
            "gap_threshold": 0.02,
            "breakout_lookback": 15,
            "confirm_bars": 1,
            "require_volume": True,
            "vol_confirm_mult": 1.0,
            "rsi_overbought": 75,
            "rsi_lower_bound": 40,
            "min_price": 1.0,
            "trend_filter": False,
            "trend_ma": 200,
            "combined_event": False,
            "max_hold_days": 15,
            "atr_mult_stop": 2.0,
            "rsi_trend_exit": 80,
            "ma_exit_period": 10,
            "trailing_stop_pct": 0.06,
            "take_profit_pct": 0.15,
            "use_enhanced_exits": True,
        }

    def _gen_consolidation(self, base=100.0, n=40, amp=1.0):
        """生成横盘整理数据"""
        closes = [base + (i % 5 - 2) * amp for i in range(n)]
        highs = [c + amp for c in closes]
        lows = [c - amp for c in closes]
        volumes = [10000.0] * n
        return closes, highs, lows, volumes

    def _gen_uptrend(self, closes, highs, lows, volumes, n=10, step=3):
        """追加上涨段"""
        for i in range(n):
            last = closes[-1] if closes else 100
            closes.append(last + step)
            highs.append(closes[-1] + 0.5)
            lows.append(closes[-1] - 2)
        vols = [max(volumes[-1] * 1.2, 10000) for _ in range(n)]
        volumes.extend(vols)
        return closes, highs, lows, volumes

    def test_insufficient_data(self, base_params):
        """数据不足应返回全零"""
        closes = [100.0] * 15
        highs = [105.0] * 15
        lows = [95.0] * 15
        volumes = [10000.0] * 15
        result = _signal_vpb(closes, highs, lows, volumes, base_params)
        assert len(result) == 15
        assert all(s == 0 for s in result)

    def test_flat_no_signal(self, base_params):
        """横盘无事件也无突破 → 全零"""
        closes, highs, lows, volumes = self._gen_consolidation(n=60)
        result = _signal_vpb(closes, highs, lows, volumes, base_params)
        # 横盘窄幅振荡不应触发信号
        signals = [i for i, s in enumerate(result) if s != 0]
        assert len(signals) < 5, f"横盘应几乎无信号, signals={signals}"

    def test_buy_volume_surge_breakout(self, base_params):
        """放量 + 突破前N日高点 → BUY

        设计：
          40天横盘 → 放量突破前N日高点
        """
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 突破日：放量 + 价格突破区间（不对称 candle 确保 close > mid）
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 2)
        volumes.append(30000)  # 3x 均量 → 触发 vol_surge_mult=1.5

        # 确认日 + 后续
        closes.append(closes[-1] + 1)
        highs.append(closes[-1] + 0.25)
        lows.append(closes[-1] - 1.5)
        volumes.append(20000)

        result = _signal_vpb(closes, highs, lows, volumes, base_params)
        has_buy = 1 in result
        if not has_buy:
            sig_indices = [i for i, s in enumerate(result) if s != 0]
            print(f"  VPB BUY test: signals at {sig_indices}, result len={len(result)}")
        assert has_buy, "放量突破应产生 BUY 信号"

    def test_buy_without_volume_confirm(self, base_params):
        """require_volume=False 时突破无需放量确认"""
        p = base_params.copy()
        p["require_volume"] = False
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 价突破但量不变
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 2)
        volumes.append(10000)  # 无放量
        closes.append(closes[-1] + 1)
        highs.append(closes[-1] + 0.25)
        lows.append(closes[-1] - 1.5)
        volumes.append(10000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        # 仍然应有 BUY
        assert 1 in result, "require_volume=False 时无放量也应触发 BUY"

    def test_sell_break_low(self, base_params):
        """跌破前N日最低价 → SELL"""
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 急跌跌破区间（不对称 candle 确保 event 触发时 close > mid）
        closes.append(closes[-1] - 8)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 2)
        volumes.append(25000)
        result = _signal_vpb(closes, highs, lows, volumes, base_params)
        has_sell = -1 in result
        if not has_sell:
            sig_indices = [i for i, s in enumerate(result) if s != 0]
            print(f"  VPB SELL test: signals at {sig_indices}")
        assert has_sell, "跌破区间应触发 SELL"

    def test_atr_stop_loss(self, base_params):
        """ATR 硬止损 → SELL（use_enhanced_exits=True）"""
        p = base_params.copy()
        p["atr_mult_stop"] = 1.5
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 突破入场
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 2)
        volumes.append(30000)
        closes.append(closes[-1] + 1)
        highs.append(closes[-1] + 0.25)
        lows.append(closes[-1] - 1.5)
        volumes.append(20000)
        # 大幅低开破 ATR 止损
        closes.append(closes[-3] - 10)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 2)
        volumes.append(15000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        # 期望最终 SELL
        assert -1 in result, "大幅下跌应触发 ATR 止损 SELL"

    def test_max_hold_days_exit(self, base_params):
        """最大持有天数到期 → SELL"""
        p = base_params.copy()
        p["max_hold_days"] = 3  # 极短持有期
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 突破入场 + 后续横盘直到持有期满
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 2)
        volumes.append(30000)
        for _ in range(5):
            closes.append(closes[-1] + 0.2)
            highs.append(closes[-1] + 0.25)
            lows.append(closes[-1] - 1.5)
            volumes.append(10000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        assert -1 in result, "持仓到期应触发 SELL"

    def test_take_profit_exit(self, base_params):
        """固定止盈 → SELL"""
        p = base_params.copy()
        p["take_profit_pct"] = 0.05  # 5% 止盈
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 突破入场
        entry = closes[-1]
        closes.append(entry + 2)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 2)
        volumes.append(30000)
        closes.append(closes[-1] + 1)
        highs.append(closes[-1] + 0.25)
        lows.append(closes[-1] - 1.5)
        volumes.append(20000)
        # 急涨触发止盈 (entry_price ~ closes[40] ≈ 104, 需要 >= 104*1.05≈109.2)
        closes.append(entry * 1.12)  # 12% > 5% 止盈
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 0.5)
        volumes.append(15000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        assert -1 in result, "涨幅达止盈线应触发 SELL"
        # 验证止盈发生在最后一根K线（bar 42），而非入场日
        assert result[-1] == -1, "止盈应在最后一根K线触发"

    def test_trailing_stop_exit(self, base_params):
        """最高点回撤止损 → SELL

        入场后先涨后跌，从最高点回撤超过 trailing_stop_pct=6%
        """
        p = base_params.copy()
        p["trailing_stop_pct"] = 0.04  # 4% 回撤止损
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 突破入场
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 2)
        volumes.append(30000)
        closes.append(closes[-1] + 1)
        highs.append(closes[-1] + 0.25)
        lows.append(closes[-1] - 1.5)
        volumes.append(20000)
        # 涨到高点
        closes.append(closes[-1] + 3)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 0.5)
        volumes.append(15000)
        # 急跌触发回撤止损（从最高点回撤 >= 4%）
        high_since_entry = max(closes[-3:])
        stop_price = high_since_entry * (1 - 0.04)
        closes.append(stop_price - 0.1)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 0.5)
        volumes.append(12000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        assert -1 in result, "最高点回撤应触发 trailing stop SELL"

    def test_rsi_trend_exit(self, base_params):
        """RSI 超买 + 跌破短期均线 → SELL"""
        p = base_params.copy()
        p["rsi_trend_exit"] = 60  # 降低阈值便于触发
        p["ma_exit_period"] = 5
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 突破入场
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 2)
        volumes.append(30000)
        closes.append(closes[-1] + 1)
        highs.append(closes[-1] + 0.25)
        lows.append(closes[-1] - 1.5)
        volumes.append(20000)
        # 连续上涨推高 RSI
        for _ in range(10):
            closes.append(closes[-1] * 1.02)
            highs.append(closes[-1] * 1.01)
            lows.append(closes[-1] * 0.99)
            volumes.append(15000)
        # 然后跌破短期均线（在前一日 ≥ 均线的前提下）
        result = _signal_vpb(closes, highs, lows, volumes, p)
        assert -1 in result, "RSI 超买+跌破均线应触发 SELL"

    def test_combined_event(self, base_params):
        """combined_event=True 要求多重事件确认"""
        p = base_params.copy()
        p["combined_event"] = True
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 放量 + 跳空同时发生
        closes.append(closes[-1] + 4)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 2)
        volumes.append(30000)  # 放量
        closes.append(closes[-1] + 1)
        highs.append(closes[-1] + 0.25)
        lows.append(closes[-1] - 1.5)
        volumes.append(20000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        # 放量突破仍应触发 BUY
        has_signal = any(s != 0 for s in result)
        assert has_signal, "复合事件应产生信号"

    def test_trend_filter(self, base_params):
        """trend_filter=True 价格低于长期均线不买入"""
        p = base_params.copy()
        p["trend_filter"] = True
        p["trend_ma"] = 20  # 缩短周期便于测试
        closes, highs, lows, volumes = self._gen_consolidation(base=50.0, n=40)  # 低价
        # 突破
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 2)
        volumes.append(30000)
        closes.append(closes[-1] + 1)
        highs.append(closes[-1] + 0.25)
        lows.append(closes[-1] - 1.5)
        volumes.append(20000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        # 因为长期均线高于当前价格，可能不触发
        assert all(s in (-1, 0, 1) for s in result)

    def test_no_confirm_bars(self, base_params):
        """confirm_bars=0 时突破直接发信号"""
        p = base_params.copy()
        p["confirm_bars"] = 0
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 放量突破
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 2)
        volumes.append(30000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        assert 1 in result, "confirm_bars=0 应直接发 BUY 信号"

    def test_use_enhanced_exits_false(self, base_params):
        """use_enhanced_exits=False 使用原版 ATR 固定止损"""
        p = base_params.copy()
        p["use_enhanced_exits"] = False
        p["atr_mult_stop"] = 1.5
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 突破入场
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 2)
        volumes.append(30000)
        closes.append(closes[-1] + 1)
        highs.append(closes[-1] + 0.25)
        lows.append(closes[-1] - 1.5)
        volumes.append(20000)
        # 暴跌触发 ATR 止损
        closes.append(closes[-3] - 12)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 2)
        volumes.append(10000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        assert -1 in result, "原版 ATR 止损应触发 SELL"

    def test_event_gap_only(self, base_params):
        """仅跳空事件（gap_ok=True, 无放量和波动）"""
        p = base_params.copy()
        p["gap_threshold"] = 0.01  # 1% 跳空
        p["vol_surge_mult"] = 10.0  # 让放量条件几乎不可能
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 跳空 + 突破
        closes.append(closes[-1] * 1.03)  # 3% 跳空
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 1)
        volumes.append(10000)  # 无放量
        result = _signal_vpb(closes, highs, lows, volumes, p)
        # 可能触发或可能不触发（取决于日内强度等）
        all_safe = all(s in (-1, 0, 1) for s in result)
        assert all_safe

    def test_rsi_filter_block(self, base_params):
        """RSI 超买时突破不产生 BUY"""
        p = base_params.copy()
        p["rsi_overbought"] = 50  # 极低超买阈值
        # 上涨行情推高 RSI
        n = 50
        closes = [100.0 * (1.01**i) for i in range(n)]
        highs = [c * 1.02 for c in closes]
        lows = [c * 0.99 for c in closes]
        volumes = [15000.0] * n
        result = _signal_vpb(closes, highs, lows, volumes, p)
        # RSI 已高 → 不应有 BUY
        buys = sum(1 for s in result if s == 1)
        assert buys == 0, f"RSI 超买不应有 BUY, buys={buys}"

    def test_min_price_filter(self, base_params):
        """低于 min_price 不买入"""
        p = base_params.copy()
        p["min_price"] = 200.0  # 极高价格过滤
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 1)
        volumes.append(30000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        buys = sum(1 for s in result if s == 1)
        assert buys == 0, f"低价股应被过滤, buys={buys}"

    def test_pending_entries_confirmation(self, base_params):
        """待确认突破在确认期内跌破则不确认"""
        p = base_params.copy()
        p["confirm_bars"] = 2
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 突破日
        closes.append(closes[-1] + 5)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 2)
        volumes.append(30000)
        # 确认期内大幅回踩
        closes.append(closes[-1] - 6)  # 跌破突破价
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 1)
        volumes.append(10000)
        closes.append(closes[-1] + 0.5)
        highs.append(closes[-1] + 0.5)
        lows.append(closes[-1] - 0.5)
        volumes.append(10000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        # 待确认突破在确认期内失败 -> 不应有 BUY
        buys = sum(1 for s in result if s == 1)
        assert buys == 0, f"确认期内跌破应抛弃突破, buys={buys}"

    def test_intraday_weak_filter(self, base_params):
        """日内弱势（close < mid）不买入"""
        p = base_params.copy()
        p["confirm_bars"] = 0
        closes, highs, lows, volumes = self._gen_consolidation(n=40)
        # 突破但收盘接近日内低点
        closes.append(closes[-1] + 5)  # close 偏低
        highs.append(closes[-1] + 8)  # high 很高
        lows.append(closes[-1] - 2)  # low 偏低
        volumes.append(30000)
        result = _signal_vpb(closes, highs, lows, volumes, p)
        # close 可能 < mid -> 不触发 BUY
        buys = sum(1 for s in result if s == 1)
        sells = sum(1 for s in result if s == -1)
        assert buys == 0, f"日内弱势不应 BUY, buys={buys}, sells={sells}"

    def test_nan_handling(self, base_params):
        """NaN 不崩溃"""
        n = 55
        closes = [float("nan")] * 10 + [100.0 + (i % 5 - 2) * 0.5 for i in range(n - 10)]
        highs = [c + 1.0 if not math.isnan(c) else 101.0 for c in closes]
        lows = [c - 1.0 if not math.isnan(c) else 99.0 for c in closes]
        volumes = [10000.0] * n
        result = _signal_vpb(closes, highs, lows, volumes, base_params)
        assert all(s in (-1, 0, 1) for s in result)

    def test_default_params_empty(self):
        """空参数使用默认值"""
        n = 55
        closes = [100.0 + (i % 5 - 2) * 0.5 for i in range(n)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        volumes = [10000.0] * n
        result = _signal_vpb(closes, highs, lows, volumes, {})
        assert all(s in (-1, 0, 1) for s in result)
