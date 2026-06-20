"""
策略信号生成模块
独立纯函数集合，依赖 indicators 模块的技术指标计算，
生成统一的交易信号：1(买入), -1(卖出), 0(持有)。

支持的策略：
- ma-cross: 双均线金叉/死叉
- breakout: N日高点突破
- rsi: RSI超买超卖
- macd: MACD金叉/死叉
- kdj: KDJ金叉/死叉
- vwm: 成交量加权动量（VWM）
- bollinger: 布林带均值回归（BBR）
- adx: ADX/DMI 趋势强度（+DI/-DI 交叉 + ADX 确认）
- combo-vwm-bbr: VWM + BBR 组合策略（加权投票合并）
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import logging
import math
from typing import Any, List

from . import indicators

logger = logging.getLogger(__name__)

# 金叉/死叉判定浮点精度容差
_MA_EPSILON: float = 1e-10


# ============================================================
# MA Cross — 双均线金叉/死叉
# ============================================================


def _signal_ma_cross(closes: list[float], params: dict) -> list[int]:
    """双均线金叉/死叉信号"""
    ma_fast_period = params.get("ma_fast", 5)
    ma_slow_period = params.get("ma_slow", 20)
    fast_ma = indicators.calculate_ma(closes, ma_fast_period)
    slow_ma = indicators.calculate_ma(closes, ma_slow_period)

    n = len(closes)
    signals: list[int] = [0] * n
    start = max(ma_fast_period, ma_slow_period)
    eps = _MA_EPSILON

    for i in range(start, n):
        if math.isnan(fast_ma[i]) or math.isnan(slow_ma[i]):
            continue
        if math.isnan(fast_ma[i - 1]) or math.isnan(slow_ma[i - 1]):
            continue
        # 金叉买入（浮点精度容差 eps）
        if fast_ma[i] > slow_ma[i] + eps and fast_ma[i - 1] <= slow_ma[i - 1] + eps:
            signals[i] = 1
        # 死叉卖出（浮点精度容差 eps）
        elif fast_ma[i] < slow_ma[i] - eps and fast_ma[i - 1] >= slow_ma[i - 1] - eps:
            signals[i] = -1

    return signals


# ============================================================
# Breakout — N日高点突破
# ============================================================


def _signal_breakout(closes: list[float], highs: list[float], params: dict) -> list[int]:
    """突破N日高点买入信号（单调队列 O(n) 优化版）

    维护两个单调队列：
    - max_q: 单调递减队列，队首始终为当前 sliding window 中 highest 的 index
    - min_q: 单调递增队列，队首始终为当前 sliding window 中 lowest 的 index

    每步操作 O(1) 均摊，替代原来 O(lookback) 的切片全扫描。
    """
    lookback = params.get("lookback", 20)
    n = len(closes)
    signals: list[int] = [0] * n

    if n <= lookback:
        return signals

    max_q: deque[int] = deque()  # 单调递减（高->低），队首为窗口内最大值
    min_q: deque[int] = deque()  # 单调递增（低->高），队首为窗口内最小值

    for i in range(n):
        # === 信号判定（基于前 N 日窗口 [i-lookback, i-1]）===
        if i >= lookback:
            # 突破前 N 日最高价
            if highs[i] > highs[max_q[0]]:
                signals[i] = 1
            # 跌破前 N 日最低价
            if closes[i] < closes[min_q[0]]:
                signals[i] = -1

        # === 移除窗口外的过期元素（为下一次迭代准备）===
        while max_q and max_q[0] <= i - lookback:
            max_q.popleft()
        while min_q and min_q[0] <= i - lookback:
            min_q.popleft()

        # === 将当前元素加入单调队列 ===
        # max_q: 递减 — 移除尾部所有 <= 当前值 的索引
        while max_q and highs[max_q[-1]] <= highs[i]:
            max_q.pop()
        max_q.append(i)

        # min_q: 递增 — 移除尾部所有 >= 当前值 的索引
        while min_q and closes[min_q[-1]] >= closes[i]:
            min_q.pop()
        min_q.append(i)

    return signals


# ============================================================
# RSI — 超买超卖
# ============================================================


def _signal_rsi(closes: list[float], params: dict) -> list[int]:
    """RSI超买超卖信号"""
    period = params.get("period", 14)
    oversold = params.get("oversold", 30)
    overbought = params.get("overbought", 70)

    rsi_values = indicators.calculate_rsi(closes, period)
    n = len(closes)
    signals: list[int] = [0] * n

    for i in range(period, min(n, len(rsi_values))):
        # RSI下穿超卖线 → 买入
        if rsi_values[i] < oversold and rsi_values[i - 1] >= oversold:
            signals[i] = 1
        # RSI上穿超买线 → 卖出
        elif rsi_values[i] > overbought and rsi_values[i - 1] <= overbought:
            signals[i] = -1

    return signals


# ============================================================
# MACD — 金叉/死叉
# ============================================================


def _signal_macd(closes: list[float], params: dict) -> list[int]:
    """MACD金叉/死叉信号"""
    fast = params.get("fast", 12)
    slow = params.get("slow", 26)
    signal = params.get("signal", 9)

    dif, dea, _ = indicators.calculate_macd(closes, fast, slow, signal)
    n = len(closes)
    signals: list[int] = [0] * n

    for i in range(slow + signal, n):
        # DIF上穿DEA → 金叉买入
        if dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
            signals[i] = 1
        # DIF下穿DEA → 死叉卖出
        elif dif[i] < dea[i] and dif[i - 1] >= dea[i - 1]:
            signals[i] = -1

    return signals


# ============================================================
# KDJ — 金叉/死叉
# ============================================================


def _signal_kdj(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    params: dict,
) -> list[int]:
    """KDJ金叉/死叉信号"""
    period = params.get("period", 9)
    k_smooth = params.get("k_smooth", 3)
    d_smooth = params.get("d_smooth", 3)

    k_vals, d_vals, j_vals = indicators.calculate_kdj(
        closes, highs, lows, period, k_smooth, d_smooth
    )
    n = len(closes)
    signals: list[int] = [0] * n

    for i in range(period + k_smooth, n):
        # K上穿D + J<40(超卖区) → 买入
        if k_vals[i] > d_vals[i] and k_vals[i - 1] <= d_vals[i - 1] and j_vals[i] < 40:
            signals[i] = 1
        # K下穿D + J>60(超买区) → 卖出
        elif k_vals[i] < d_vals[i] and k_vals[i - 1] >= d_vals[i - 1] and j_vals[i] > 60:
            signals[i] = -1

    return signals


# ============================================================
# VWM — 成交量加权动量策略
# 当前市场环境（AI/算力/半导体主线）定制的趋势突破策略。
# 核心逻辑：价格趋势确认 + 成交量放大验证 + RSI 情绪过滤
# ============================================================


def _signal_vwm(closes: list[float], volumes: list[float], params: dict) -> list[int]:
    """成交量加权动量策略信号

    短线动量策略，专为 A 股趋势行情设计。

    SELL（全部满足）：Close<MA5 且 MA5<MA20 —— 趋势破位+死叉滤除噪声
    BUY（全部满足）：Close>MA5>MA20 + Vol>=MA_Vol + RSI 50-80 + 趋势刚启动
    """
    ma_fast = params.get("ma_fast", 5)
    ma_slow = params.get("ma_slow", 20)
    volume_period = params.get("volume_period", 20)
    vol_multiplier_buy = params.get("vol_multiplier_buy", 1.0)
    vol_multiplier_sell = params.get("vol_multiplier_sell", 0.4)
    rsi_period = params.get("rsi_period", 14)
    rsi_overbought = params.get("rsi_overbought", 80)
    rsi_oversold_threshold = params.get("rsi_oversold_threshold", 50)

    close_ma_fast = indicators.calculate_ma(closes, ma_fast)
    close_ma_slow = indicators.calculate_ma(closes, ma_slow)
    vol_ma = indicators.calculate_volume_ma(volumes, volume_period)
    rsi_values = indicators.calculate_rsi(closes, rsi_period)

    n = min(len(closes), len(close_ma_fast), len(close_ma_slow), len(vol_ma), len(rsi_values))
    signals: list[int] = [0] * n
    start = max(ma_slow, volume_period, rsi_period)

    for i in range(start, n):
        if any(
            math.isnan(x) for x in [close_ma_fast[i], close_ma_slow[i], vol_ma[i], rsi_values[i]]
        ):
            continue

        # SELL: Close 跌破快线 + 均线死叉（滤除短期噪声）
        if closes[i] < close_ma_fast[i] and close_ma_fast[i] < close_ma_slow[i]:
            signals[i] = -1

        # BUY: 价量配合向上突破
        elif (
            closes[i] > close_ma_fast[i]  # 短期向上
            and close_ma_fast[i] > close_ma_slow[i]  # 多头排列
            and volumes[i] > vol_ma[i] * vol_multiplier_buy  # 放量确认
            and rsi_values[i] > rsi_oversold_threshold  # 非超卖
            and rsi_values[i] < rsi_overbought  # 非超买
            and i > start
            and closes[i - 1] <= close_ma_fast[i - 1]  # 趋势刚启动（前一交易日未站稳快线）
        ):
            signals[i] = 1

    return signals


# ============================================================
# BBR — 布林带均值回归（Bollinger Mean Reversion）
# 与 VWM（动量）互补：VWM 抓趋势，BBR 抓超买超卖回归。
# ============================================================


def _signal_bollinger(closes: list[float], params: dict) -> list[int]:
    """布林带均值回归策略信号

    核心：价格触及布林带极端 + RSI 确认超买超卖 → 赌回归中轨。

    BUY 条件（全部满足）：
      1. Close <= Lower Band          —— 下触布林下轨（超卖）
      2. RSI(14) < rsi_oversold       —— RSI 确认超卖
      3. 前一交易日 Close > Lower Band —— 刚跌破下轨（新鲜信号）

    SELL 条件（任一满足）：
      1. Close >= Middle Band          —— 回归中轨（止盈）
      2. Close >= Upper Band AND RSI > rsi_overbought  —— 触上轨+超买
    """
    period = params.get("period", 20)
    std_mult = params.get("std_mult", 2.0)
    rsi_period = params.get("rsi_period", 14)
    rsi_oversold = params.get("rsi_oversold", 35)
    rsi_overbought = params.get("rsi_overbought", 65)

    middle, upper, lower = indicators.calculate_bollinger(closes, period, std_mult)
    rsi_values = indicators.calculate_rsi(closes, rsi_period)

    n = min(len(closes), len(middle), len(upper), len(lower), len(rsi_values))
    signals: list[int] = [0] * n
    start = period + rsi_period

    for i in range(start, n):
        if any(math.isnan(x) for x in [middle[i], upper[i], lower[i], rsi_values[i]]):
            continue

        # BUY: 跌破下轨 + RSI 超卖确认 + 刚突破
        if closes[i] <= lower[i] and rsi_values[i] < rsi_oversold and closes[i - 1] > lower[i - 1]:
            signals[i] = 1

        # SELL: 触上轨止盈（均值回归完成）|| RSI超买+中轨之上
        if closes[i] >= upper[i] or closes[i] >= middle[i] and rsi_values[i] > rsi_overbought:
            signals[i] = -1

    return signals


# ============================================================
# ADX / DMI — 趋势强度 & 方向信号
# ============================================================


def _signal_adx(
    highs: list[float], lows: list[float], closes: list[float], params: dict
) -> list[int]:
    """ADX/DMI 趋势强度策略信号

    BUY 条件（全部满足）：
      1. +DI > -DI                     —— 上涨力量主导
      2. ADX > adx_threshold           —— 趋势确认（过滤震荡）
      3. 前一日 +DI <= -DI            —— 交叉确认（趋势刚启动）

    SELL 条件（全部满足）：
      1. -DI > +DI                     —— 下跌力量主导
      2. ADX > adx_threshold           —— 趋势确认
      3. 前一日 -DI <= +DI            —— 交叉确认
    """
    period = params.get("period", 14)
    adx_threshold = params.get("adx_threshold", 22)
    cross_confirm = params.get("cross_confirm", True)

    plus_di, minus_di, adx = indicators.calculate_adx(highs, lows, closes, period)

    n = min(len(closes), len(plus_di), len(minus_di), len(adx))
    signals: list[int] = [0] * n
    start = period * 2  # ADX 需要 2*period 才稳定

    for i in range(start, n):
        if any(math.isnan(x) for x in [plus_di[i], minus_di[i], adx[i]]):
            continue

        # BUY: +DI 上穿 -DI 且 ADX 确认趋势
        if cross_confirm:
            buy_signal = (
                plus_di[i] > minus_di[i]
                and adx[i] > adx_threshold
                and plus_di[i - 1] <= minus_di[i - 1]
            )
            sell_signal = (
                minus_di[i] > plus_di[i]
                and adx[i] > adx_threshold
                and minus_di[i - 1] <= plus_di[i - 1]
            )
        else:
            buy_signal = plus_di[i] > minus_di[i] and adx[i] > adx_threshold
            sell_signal = minus_di[i] > plus_di[i] and adx[i] > adx_threshold

        if buy_signal:
            signals[i] = 1
        elif sell_signal:
            signals[i] = -1

    return signals


# ============================================================
# OBV / VPD — 量价背离策略
# ============================================================


def _signal_obv(closes: list[float], volumes: list[float], params: dict) -> list[int]:
    """OBV 量价背离策略信号

    核心逻辑：
      量价同步 → 趋势确认
      量价背离 → 反转预警

    BUY 条件（任一）：
      1. OBV↑ + Price↑ + 放量  —— 量价同步上涨（趋势健康）
      2. 价格低位 + OBV未创新低  —— 底部背离（卖压衰竭）

    SELL 条件（任一）：
      1. OBV↓ + Price↓ + 缩量  —— 量价同步下跌（趋势走弱）
      2. 价格高位 + OBV未创新高  —— 顶部背离（买盘衰竭）
    """
    lookback = params.get("lookback", 20)
    obv_period = params.get("obv_period", 20)
    vol_surge_mult = params.get("vol_surge_mult", 1.3)

    obv, obv_ma = indicators.calculate_obv(closes, volumes, obv_period)
    vol_ma = indicators.calculate_volume_ma(volumes, obv_period)

    n = min(len(closes), len(obv), len(obv_ma), len(vol_ma))
    signals: list[int] = [0] * n
    start = lookback + obv_period

    for i in range(start, n):
        if i < lookback or i < 2:
            continue

        # 近期价格极值
        recent_closes = closes[i - lookback + 1 : i + 1]
        recent_high = max(recent_closes)
        recent_low = min(recent_closes)

        # 确保前 lookback 天的索引有效
        obv_start = max(0, i - lookback + 1)
        recent_obv = obv[obv_start : i + 1]

        # OBV 趋势方向
        half = max(1, lookback // 2)
        obv_half_start = max(0, i - half + 1)
        obv_recent_avg = sum(obv[obv_half_start : i + 1]) / (i - obv_half_start + 1)
        obv_prior_start = max(0, i - lookback + 1)
        obv_prior_avg = sum(obv[obv_prior_start:obv_half_start]) / max(
            1, obv_half_start - obv_prior_start
        )
        obv_up = obv_recent_avg > obv_prior_avg

        # 成交量确认
        vol_surge = False
        if i >= obv_period and vol_ma[i] > 0:
            vol_surge = volumes[i] > vol_ma[i] * vol_surge_mult

        # 价格位置
        at_high = recent_high > 0 and closes[i] >= recent_high * 0.98
        at_low = recent_low > 0 and closes[i] <= recent_low * 1.02

        # 价格趋势
        price_recent = sum(closes[obv_half_start : i + 1]) / (i - obv_half_start + 1)
        price_prior = sum(closes[obv_prior_start:obv_half_start]) / max(
            1, obv_half_start - obv_prior_start
        )
        price_up = price_recent > price_prior

        # 信号
        if price_up and obv_up and vol_surge or at_low and not price_up and not obv_up:
            signals[i] = 1
        elif at_high and price_up and not obv_up or not price_up and not obv_up and not vol_surge:
            signals[i] = -1

    return signals


def _signal_combo_vwm_bbr(df_data: list[dict], params: dict) -> list[int]:
    """VWM + BBR 组合策略信号

    核心思路：趋势跟踪（VWM）与均值回归（BBR）互补。
      同向 → 强信号（全力）
      冲突 → VWM 主导（趋势信号权重更高）
      反向 → BBR 贡献减半（卖出是止盈而非看空）

    合并规则：
      VWM 信号: +vwm_weight (BUY), -vwm_weight (SELL), 0 (HOLD)
      BBR BUY:  +bbr_weight
      BBR SELL: -bbr_weight * bbr_sell_factor（默认 0.5，止盈信号弱于趋势信号）
      BBR HOLD:  0

      Score = VWM + BBR
      >  buy_threshold  → BUY
      <  sell_threshold → SELL
      其他 → HOLD
    """
    vwm_weight = params.get("vwm_weight", 0.6)
    bbr_weight = params.get("bbr_weight", 0.4)
    bbr_sell_factor = params.get("bbr_sell_factor", 0.3)  # BBR 卖出贡献减半
    buy_threshold = params.get("buy_threshold", 0.25)
    sell_threshold = params.get("sell_threshold", -0.25)

    # 提取 VWM 和 BBR 的独立参数
    vwm_p = params.get("vwm_params", {})
    bbr_p = params.get("bbr_params", {})

    # 分别计算两份信号
    closes = [float(d["close"]) for d in df_data]
    volumes = [float(d.get("vol", 0)) for d in df_data]
    n = len(closes)

    vwm_sig = _signal_vwm(closes, volumes, vwm_p)
    bbr_sig = _signal_bollinger(closes, bbr_p)

    # 截齐长度
    min_n = min(n, len(vwm_sig), len(bbr_sig))
    signals: list[int] = [0] * min_n

    for i in range(min_n):
        # BBR 卖出贡献减半（BBR 卖出是中轨止盈，不是强烈看空）
        effective_bbr = bbr_weight * (
            bbr_sig[i] if bbr_sig[i] >= 0 else -abs(bbr_sig[i]) * bbr_sell_factor
        )
        score = vwm_weight * vwm_sig[i] + effective_bbr
        if score >= buy_threshold:
            signals[i] = 1
        elif score <= sell_threshold:
            signals[i] = -1

    return signals


_COMBO_STRATEGIES = {"combo-vwm-bbr"}

# VBM — Volatility Breakout Momentum（v2.1 新增）
_VBM_DEFAULT = {
    "roc_period": 5,
    "vol_lookback": 20,
    "atr_period": 14,
    "roc_threshold": 0.03,
    "vol_mult": 1.2,
    "atr_mult": 1.0,
    "rsi_upper": 70,
    "rsi_lower": 30,
}


def _signal_vbm(
    closes: list[float], highs: list[float], lows: list[float], volumes: list[float], params: dict
) -> list[int]:
    """VBM — Volatility Breakout Momentum 短线动量突破策略"""
    lookback = params.get("roc_period", _VBM_DEFAULT["roc_period"])
    vol_lookback = params.get("vol_lookback", _VBM_DEFAULT["vol_lookback"])
    atr_period = params.get("atr_period", _VBM_DEFAULT["atr_period"])
    roc_threshold = params.get("roc_threshold", _VBM_DEFAULT["roc_threshold"])
    vol_mult = params.get("vol_mult", _VBM_DEFAULT["vol_mult"])
    rsi_upper = params.get("rsi_upper", _VBM_DEFAULT["rsi_upper"])

    n = len(closes)
    signals: list[int] = [0] * n
    if n <= max(lookback, vol_lookback, atr_period) + 5:
        return signals
    tr_values = [0.0] * n
    for k in range(1, n):
        tr_values[k] = max(
            highs[k] - lows[k], abs(highs[k] - closes[k - 1]), abs(lows[k] - closes[k - 1])
        )
    atr = [0.0] * n
    if n > atr_period:
        atr[atr_period] = sum(tr_values[1 : atr_period + 1]) / atr_period
        for k in range(atr_period + 1, n):
            atr[k] = (atr[k - 1] * (atr_period - 1) + tr_values[k]) / atr_period
    vol_ma = indicators.calculate_volume_ma(volumes, vol_lookback)
    rsi = indicators.calculate_rsi(closes, atr_period)
    atr_ma = indicators.calculate_ma(atr, vol_lookback)
    start = max(lookback, vol_lookback, atr_period)
    for i in range(start, n):
        roc = (
            (closes[i] - closes[i - lookback]) / closes[i - lookback]
            if closes[i - lookback] > 0
            else 0
        )
        vol_ok = vol_ma[i] > 0 and volumes[i] > vol_ma[i] * vol_mult
        atr_ok = atr_ma[i] > 0 and atr[i] > atr_ma[i]
        rsi_val = rsi[i] if i < len(rsi) else 50
        if roc > roc_threshold and vol_ok and atr_ok and rsi_val < rsi_upper:
            signals[i] = 1
        elif roc < -roc_threshold or rsi_val > rsi_upper + 10:
            signals[i] = -1
    return signals


# ============================================================
# VPB — 量价事件突破策略 (Volume-Price Event Breakout)
# 填补现有策略的事件驱动 + 形态突破缺口。
# 双阶段确认架构：
#   Stage 1: 事件检测（成交量/波动率/跳空异常）
#   Stage 2: 突破确认（价格突破区间 + RSI/量过滤）
# 退出：ATR 动态跟踪止损 + 最大持有期限
# ============================================================


def _signal_vpb(
    closes: list[float], highs: list[float], lows: list[float], volumes: list[float], params: dict
) -> list[int]:
    """VPB 量价事件突破策略信号

    核心逻辑——只交易"有事发生"的突破：

    BUY 条件（全部满足）：
      1. 事件激活：成交量激增 OR 波动率扩张 OR 跳空
      2. 突破确认：价格突破前N日区间最高价
      3. 日内强势：收盘在当日区间上半部 (close > mid)
      4. RSI 非超买 + 放量确认

    SELL 条件（任一满足，优先级从高到低）：
      1. 价格跌破前N日区间最低价（趋势反转）
      2. 固定止盈触发 (take_profit_pct) [v2.2+]
      3. 最高点回撤止损 (trailing_stop_pct) [v2.2+]
      4. ATR 硬止损（防跳空/极端波动） [保留]
      5. 最大持有天数到期 (max_hold_days)
      6. RSI 超买 + 跌破短期均线（动量衰竭）
    """
    # ---------- 参数提取 ----------
    # 事件检测参数
    event_lookback = params.get("event_lookback", 20)
    vol_surge_mult = params.get("vol_surge_mult", 1.5)
    atr_surge_mult = params.get("atr_surge_mult", 1.3)
    gap_threshold = params.get("gap_threshold", 0.02)

    # 突破确认参数
    breakout_lookback = params.get("breakout_lookback", 15)
    confirm_bars = params.get("confirm_bars", 1)  # 突破后等待确认天数
    require_volume = params.get("require_volume", True)  # 突破日是否要求放量
    vol_confirm_mult = params.get("vol_confirm_mult", 1.0)  # 突破日成交量倍数

    # 过滤参数
    rsi_overbought = params.get("rsi_overbought", 75)
    rsi_lower_bound = params.get("rsi_lower_bound", 40)
    min_price = params.get("min_price", 1.0)

    # v2.3 趋势过滤（减少假突破）
    trend_filter = params.get("trend_filter", True)  # 是否启用趋势过滤
    trend_ma = params.get("trend_ma", 200)  # 长期均线周期
    combined_event = params.get("combined_event", False)  # 是否要求多重事件确认

    # 退出参数（v2.2 增强版）
    max_hold_days = params.get("max_hold_days", 15)
    atr_mult_stop = params.get("atr_mult_stop", 2.0)
    rsi_trend_exit = params.get("rsi_trend_exit", 80)  # RSI超买+破均线
    ma_exit_period = params.get("ma_exit_period", 10)  # 短期均线跟踪
    # v2.2 新增退出参数
    trailing_stop_pct = params.get("trailing_stop_pct", 0.06)  # 从最高点回撤6%止损
    take_profit_pct = params.get("take_profit_pct", 0.15)  # 15%固定止盈
    use_enhanced_exits = params.get("use_enhanced_exits", True)  # 使用增强版退出机制

    n = len(closes)
    signals: list[int] = [0] * n
    max_required = max(event_lookback, breakout_lookback, 20)
    if n <= max_required + 5:
        return signals

    # ---------- 预计算 ----------
    # 成交量均线
    vol_ma = indicators.calculate_volume_ma(volumes, event_lookback)

    # ATR (Average True Range)
    tr_values = [0.0] * n
    for k in range(1, n):
        tr_values[k] = max(
            highs[k] - lows[k], abs(highs[k] - closes[k - 1]), abs(lows[k] - closes[k - 1])
        )
    atr = [0.0] * n
    atr_period = 14
    if n > atr_period:
        atr[atr_period] = sum(tr_values[1 : atr_period + 1]) / atr_period
        for k in range(atr_period + 1, n):
            atr[k] = (atr[k - 1] * (atr_period - 1) + tr_values[k]) / atr_period

    # ATR 均线（用于波动率事件检测）
    atr_ma = indicators.calculate_ma(atr, event_lookback)

    # RSI (返回长度可能比 closes 少 1，补齐 NaN 保持对齐)
    rsi_values = list(indicators.calculate_rsi(closes, 14))
    while len(rsi_values) < n:
        rsi_values.append(float("nan"))

    # 短期均线（用于趋势退出判断）
    short_ma = indicators.calculate_ma(closes, ma_exit_period)

    # v2.3 长期均线（用于趋势过滤）
    if trend_filter:
        long_ma = indicators.calculate_ma(closes, trend_ma)
    else:
        long_ma = [0.0] * n

    # ---------- 滚动窗口事件检测 + 突破确认 ----------
    # 使用滑动窗口：维护区间最高/最低的单调队列优化
    from collections import deque

    range_high_q: deque[int] = deque()  # 单调递减，breakout_lookback 窗口新高
    range_low_q: deque[int] = deque()  # 单调递增，breakout_lookback 窗口新低

    # 事件标记：0=无事件, 1=成交量爆发, 2=波动率扩张, 3=跳空
    event_flags = [0] * n

    # 每个位置的窗口极值（用于第二轮信号生成）
    range_high_vals = [0.0] * n
    range_low_vals = [0.0] * n

    for i in range(n):
        # ---- 窗口维护 ----
        while range_high_q and range_high_q[0] <= i - breakout_lookback:
            range_high_q.popleft()
        while range_low_q and range_low_q[0] <= i - breakout_lookback:
            range_low_q.popleft()

        while range_high_q and highs[range_high_q[-1]] <= highs[i]:
            range_high_q.pop()
        range_high_q.append(i)

        while range_low_q and lows[range_low_q[-1]] >= lows[i]:
            range_low_q.pop()
        range_low_q.append(i)

        # 保存当前位置的窗口极值（第二轮用）
        range_high_vals[i] = highs[range_high_q[0]]
        range_low_vals[i] = lows[range_low_q[0]]

        # ---- 事件检测 (i >= max_required) ----
        if i < max_required:
            continue

        vol_ok = vol_ma[i] > 0 and volumes[i] > vol_ma[i] * vol_surge_mult
        atr_ok = atr_ma[i] > 0 and atr[i] > atr_ma[i] * atr_surge_mult
        gap_ok = abs(closes[i] - closes[i - 1]) / max(closes[i - 1], 0.01) > gap_threshold

        if combined_event:
            # v2.3: 要求多重事件确认（至少两个事件同时触发）
            event_score = sum([vol_ok, atr_ok, gap_ok])
            if event_score >= 2:
                event_flags[i] = 4  # 复合事件
        elif vol_ok:
            event_flags[i] = 1
        elif atr_ok:
            event_flags[i] = 2
        elif gap_ok:
            event_flags[i] = 3

    # ---------- 信号生成 ----------
    max_idx = n
    # 跟踪持仓天数（用于 max_hold_days 退出）
    entry_day: dict[int, float] = {}  # idx -> entry price

    # v2.2: 跟踪每笔持仓的期间最高价（用于最高点回撤止损）
    entry_highest: dict[int, float] = {}  # idx -> highest_close_since_entry

    # 假突破跟踪：突破后需要 confirm_bars 天确认
    pending_entries: list[tuple[int, float]] = []  # (idx, entry_price) 待确认

    for i in range(max_required + 1, max_idx):
        if math.isnan(short_ma[i]):
            continue

        # === 检查已有持仓是否需要卖出 ===
        remove_entries = []
        for entry_idx, entry_price in list(entry_day.items()):
            # 条件1: 跌破前N日最低价（趋势反转）
            if closes[i] <= range_low_vals[i]:
                signals[i] = -1
                remove_entries.append(entry_idx)
                continue

            if use_enhanced_exits:
                # 更新期间最高价
                entry_highest[entry_idx] = max(entry_highest.get(entry_idx, entry_price), closes[i])

                # 条件2a: 固定止盈（优先）
                if (closes[i] - entry_price) / entry_price >= take_profit_pct:
                    signals[i] = -1
                    remove_entries.append(entry_idx)
                    continue

                # 条件2b: 最高点回撤止损（锁定利润，替代原 ATR 固定止损）
                trail_stop = entry_highest[entry_idx] * (1 - trailing_stop_pct)
                if closes[i] < trail_stop:
                    signals[i] = -1
                    remove_entries.append(entry_idx)
                    continue

                # 条件2c: ATR 硬止损（防跳空/极端波动 — 仍保留作为地板保护）
                stop_price = entry_price - atr[i] * atr_mult_stop
                if closes[i] < stop_price:
                    signals[i] = -1
                    remove_entries.append(entry_idx)
                    continue
            else:
                # 原版：ATR 固定止损
                stop_price = entry_price - atr[i] * atr_mult_stop
                if closes[i] < stop_price:
                    signals[i] = -1
                    remove_entries.append(entry_idx)
                    continue

            # 条件3: 最大持有天数
            hold_days = i - entry_idx
            if hold_days >= max_hold_days:
                signals[i] = -1
                remove_entries.append(entry_idx)
                continue

            # 条件4: RSI 超买 + 跌破短期均线（动量衰竭）
            if (
                rsi_values[i] > rsi_trend_exit
                and closes[i] < short_ma[i]
                and closes[i - 1] >= short_ma[i - 1]
            ):
                signals[i] = -1
                remove_entries.append(entry_idx)
                continue

        for idx in remove_entries:
            del entry_day[idx]

        # 已有持仓则不再开新仓
        if entry_day:
            continue

        # === 已产生卖出信号则不再开仓 ===
        if signals[i] == -1:
            continue

        # === 检查待确认突破 ===
        new_pending = []
        for pidx, pprice in pending_entries:
            if i - pidx >= confirm_bars:
                # 确认期内始终未跌破区间上轨 → 确认突破
                min_price_since = min(lows[pidx : i + 1])
                if min_price_since >= pprice * 0.98:  # 允许 2% 回踩
                    signals[pidx] = 1  # 在突破日发出买入信号
                    entry_day[pidx] = closes[pidx]
                # 无论确认与否，移除该待办
                continue
            new_pending.append((pidx, pprice))
        pending_entries = new_pending

        # === 新开仓信号检测 ===
        if event_flags[i] == 0:
            continue  # 无事件不交易

        # 事件已发生，检查突破确认
        # 使用前一根K线的窗口极值（排除当前K线本身）
        # 避免当前K线自身创出新高/新低导致条件永远无法满足
        prev_range_high = range_high_vals[i - 1] if i > 0 else 0.0
        range_low = range_low_vals[i]

        # 日内强度: 收盘接近区间上半部
        mid_price = (highs[i] + lows[i]) / 2
        intraday_strong = closes[i] > mid_price

        if not intraday_strong:
            continue

        # BUY: 突破前N日最高价（与上一K线的窗口最高价比较）
        if closes[i] > prev_range_high * 1.001:  # 0.1% 容差
            # v2.3 趋势过滤：价格必须在长期均线之上
            if trend_filter and closes[i] <= long_ma[i]:
                continue

            # RSI 过滤
            if rsi_values[i] > rsi_overbought:
                continue

            # 成交量确认
            if require_volume and vol_ma[i] > 0:
                if volumes[i] < vol_ma[i] * vol_confirm_mult:
                    continue

            # 价格过滤（避免仙股）
            if closes[i] < min_price:
                continue

            # RSI 过低也不买（可能是恐慌性下跌后的反抽）
            if rsi_values[i] < rsi_lower_bound:
                continue

            if confirm_bars > 0:
                # 需要确认：先加入待办列表
                pending_entries.append((i, prev_range_high))
            else:
                # 无需确认：直接发信号
                signals[i] = 1
                entry_day[i] = closes[i]

        # SELL: 跌破前N日最低价（事件驱动的反方向）
        # 使用前一根K线的窗口最低价（排除当前K线自身拉低窗口的情况）
        range_low_prev = range_low_vals[i - 1] if i > 0 else 0.0
        if closes[i] < range_low_prev * 0.999:
            signals[i] = -1

    return signals


_SIGNAL_DISPATCH: dict[str, Callable[..., Any]] = {
    "ma-cross": _signal_ma_cross,
    "breakout": _signal_breakout,
    "rsi": _signal_rsi,
    "macd": _signal_macd,
    "kdj": _signal_kdj,
    "vwm": _signal_vwm,
    "bollinger": _signal_bollinger,
    "adx": _signal_adx,
    "obv": _signal_obv,
    "vbm": _signal_vbm,
    "vpb": _signal_vpb,
}


def generate_signals(df_data: list[dict], strategy: str, params: dict = None) -> list[int]:
    """统一策略信号生成接口

    根据策略类型和参数，对行情数据生成交易信号。

    Args:
        df_data: 行情数据列表，每项包含 close/high/low/vol/trade_date 等字段
        strategy: 策略名称 (ma-cross/breakout/rsi/macd/kdj/vwm/bollinger/adx/obv/vbm/vpb/combo-vwm-bbr)
        params: 策略参数字典

    Returns:
        信号列表，signal in {1(买), -1(卖), 0(持有)}
    """
    params = params or {}
    closes = [float(d["close"]) for d in df_data]
    n = len(closes)
    signals: list[int] = [0] * n

    # 组合策略：需要完整的 df_data（含 vol）
    if strategy in _COMBO_STRATEGIES:
        if strategy == "combo-vwm-bbr":
            return _signal_combo_vwm_bbr(df_data, params)
        logger.warning(f"未知组合策略: {strategy}，返回空信号")
        return signals

    signal_fn = _SIGNAL_DISPATCH.get(strategy)
    if signal_fn is not None:
        if strategy in ("vwm", "obv"):
            volumes = [float(d.get("vol", 0)) for d in df_data]
            signals = signal_fn(closes, volumes, params)
        elif strategy in ("breakout", "kdj", "adx", "vbm", "vpb"):
            highs = [float(d.get("high", d["close"])) for d in df_data]
            lows = [float(d.get("low", d["close"])) for d in df_data]
            if strategy in ("vbm", "vpb"):
                volumes = [float(d.get("vol", 0)) for d in df_data]
                signals = signal_fn(closes, highs, lows, volumes, params)
            elif strategy == "kdj":
                signals = signal_fn(closes, highs, lows, params)
            elif strategy == "adx":
                signals = signal_fn(highs, lows, closes, params)
            else:
                signals = signal_fn(closes, highs, params)
        else:
            signals = signal_fn(closes, params)
    else:
        logger.warning(f"未知策略: {strategy}，返回空信号")

    return signals
