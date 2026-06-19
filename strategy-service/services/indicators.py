"""
技术指标计算模块
独立纯函数集合，无状态依赖，可独立测试。
提供 EnhancedBacktestEngine 和 SimpleBacktestEngine 共享的指标计算能力。

Supported indicators:
- calculate_ma: 简单移动平均线（前缀和 O(n) 加速）
- calculate_volume_ma: 成交量移动平均线
- calculate_bollinger: 布林带（中轨/上轨/下轨）
- calculate_rsi: RSI 相对强弱指标（Wilder 平滑法）
- calculate_macd: MACD 指标（DIF / DEA / 柱状线）
- calculate_kdj: KDJ 随机指标（K / D / J 三线）
- calculate_adx: ADX/DMI 平均趋向指标（+DI / -DI / ADX）
- calculate_obv: OBV 能量潮指标
"""

from __future__ import annotations

import functools
import math
from typing import List, Tuple

# ============================================================
# MA — 简单移动平均线（LRU 缓存版）
# ============================================================


def calculate_ma(prices: list[float], period: int) -> list[float]:
    """计算简单移动平均线（O(n) 滑动窗口，前缀和加速）
    内部通过 lru_cache 避免同参数重复计算。

    Args:
        prices: 价格序列
        period: 均线周期

    Returns:
        移动平均线列表，前 period-1 个值为 NaN
    """
    return list(_cached_ma(tuple(prices), period))


@functools.lru_cache(maxsize=256)
def _cached_ma(prices: tuple[float, ...], period: int) -> tuple[float, ...]:
    """LRU 缓存的 MA 实现（tuple 入参/出参以支持哈希）"""
    n = len(prices)
    if period <= 0:
        return ()

    ma: list[float] = [float("nan")] * (period - 1)

    prefix = [0.0]
    for p in prices:
        prefix.append(prefix[-1] + p)

    for i in range(period - 1, n):
        avg = (prefix[i + 1] - prefix[i + 1 - period]) / period
        ma.append(avg)

    return tuple(ma)


# ============================================================
# Volume MA — 成交量移动平均线
# ============================================================


def calculate_volume_ma(volumes: list[float], period: int = 20) -> list[float]:
    """计算成交量移动平均线（O(n) 前缀和加速）

    Args:
        volumes: 成交量序列
        period: 均线周期，默认20

    Returns:
        成交量移动平均线列表，前 period-1 个值为 NaN
    """
    return list(_cached_volume_ma(tuple(volumes), period))


@functools.lru_cache(maxsize=128)
def _cached_volume_ma(volumes: tuple[float, ...], period: int) -> tuple[float, ...]:
    """LRU 缓存的成交量 MA 实现"""
    n = len(volumes)
    if period <= 0:
        return ()

    result: list[float] = [float("nan")] * (period - 1)

    prefix = [0.0]
    for v in volumes:
        prefix.append(prefix[-1] + v)

    for i in range(period - 1, n):
        avg = (prefix[i + 1] - prefix[i + 1 - period]) / period
        result.append(avg)

    return tuple(result)


# ============================================================
# Bollinger Bands — 布林带（中轨/上轨/下轨）
# ============================================================


def calculate_bollinger(
    prices: list[float], period: int = 20, std_mult: float = 2.0
) -> tuple[list[float], list[float], list[float]]:
    """计算布林带（O(n) 前缀和加速）

    Args:
        prices: 价格序列
        period: 周期，默认 20
        std_mult: 标准差倍数，默认 2.0

    Returns:
        (middle, upper, lower) 三元组，前 period-1 个值为 NaN
    """
    mid_t, up_t, low_t = _cached_bollinger(tuple(prices), period, std_mult)
    return list(mid_t), list(up_t), list(low_t)


@functools.lru_cache(maxsize=64)
def _cached_bollinger(
    prices: tuple[float, ...], period: int, std_mult: float
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """LRU 缓存的布林带实现"""
    n = len(prices)
    if period <= 0:
        return (), (), ()

    # 前缀和
    prefix = [0.0]
    for p in prices:
        prefix.append(prefix[-1] + p)

    # 前缀平方和（用于计算标准差）
    prefix_sq = [0.0]
    for p in prices:
        prefix_sq.append(prefix_sq[-1] + p * p)

    middle: list[float] = [float("nan")] * (period - 1)
    upper: list[float] = [float("nan")] * (period - 1)
    lower: list[float] = [float("nan")] * (period - 1)

    for i in range(period - 1, n):
        # 均值
        sma = (prefix[i + 1] - prefix[i + 1 - period]) / period
        middle.append(sma)

        # 标准差 = sqrt(E[X²] - E[X]²)
        sum_sq = prefix_sq[i + 1] - prefix_sq[i + 1 - period]
        variance = sum_sq / period - sma * sma
        std = math.sqrt(max(variance, 0))

        upper.append(sma + std_mult * std)
        lower.append(sma - std_mult * std)

    return tuple(middle), tuple(upper), tuple(lower)


# ============================================================
# RSI — 相对强弱指标（Wilder 平滑法）
# ============================================================


def calculate_rsi(prices: list[float], period: int = 14) -> list[float]:
    """计算RSI（相对强弱指标）
    内部通过 lru_cache 避免同参数重复计算。

    Args:
        prices: 价格序列
        period: RSI周期，默认14

    Returns:
        RSI值列表
    """
    return list(_cached_rsi(tuple(prices), period))


@functools.lru_cache(maxsize=256)
def _cached_rsi(prices: tuple[float, ...], period: int = 14) -> tuple[float, ...]:
    """LRU 缓存的 RSI 实现"""
    if len(prices) < period + 1:
        return tuple(50.0 for _ in prices)

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    rsi: list[float] = [50.0] * period

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100.0 - (100.0 / (1 + rs)))

    return tuple(rsi)


# ============================================================
# MACD — 异同移动平均线（DIF / DEA / 柱状线）
# ============================================================


def calculate_macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float], list[float], list[float]]:
    """计算MACD指标
    内部通过 lru_cache 避免同参数重复计算。

    Returns:
        (DIF, DEA, MACD柱) 三元组
    """
    dif_t, dea_t, hist_t = _cached_macd(tuple(prices), fast, slow, signal)
    return list(dif_t), list(dea_t), list(hist_t)


@functools.lru_cache(maxsize=128)
def _cached_macd(
    prices: tuple[float, ...],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """LRU 缓存的 MACD 实现"""
    if len(prices) < slow:
        n = len(prices)
        return (tuple([0.0] * n), tuple([0.0] * n), tuple([0.0] * n))

    alpha_fast = 2.0 / (fast + 1)
    alpha_slow = 2.0 / (slow + 1)

    ema_fast: list[float] = [prices[0]]
    ema_slow: list[float] = [prices[0]]

    for i in range(1, len(prices)):
        ema_fast.append(alpha_fast * prices[i] + (1 - alpha_fast) * ema_fast[-1])
        ema_slow.append(alpha_slow * prices[i] + (1 - alpha_slow) * ema_slow[-1])

    dif = [ema_fast[i] - ema_slow[i] for i in range(len(prices))]

    dea: list[float] = [0.0] * len(prices)
    if len(prices) > signal:
        dea[signal - 1] = sum(dif[:signal]) / signal
        alpha_signal = 2.0 / (signal + 1)
        for i in range(signal, len(dif)):
            dea[i] = alpha_signal * dif[i] + (1 - alpha_signal) * dea[i - 1]

    macd_hist = [(dif[i] - dea[i]) * 2 for i in range(len(prices))]
    return tuple(dif), tuple(dea), tuple(macd_hist)


# ============================================================
# KDJ — 随机指标（K / D / J 三线）
# ============================================================


def calculate_kdj(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    period: int = 9,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> tuple[list[float], list[float], list[float]]:
    """计算KDJ指标
    内部通过 lru_cache 避免同参数重复计算。

    Returns:
        (K, D, J) 三元组
    """
    k_t, d_t, j_t = _cached_kdj(
        tuple(closes), tuple(highs), tuple(lows), period, k_smooth, d_smooth
    )
    return list(k_t), list(d_t), list(j_t)


@functools.lru_cache(maxsize=128)
def _cached_kdj(
    closes: tuple[float, ...],
    highs: tuple[float, ...],
    lows: tuple[float, ...],
    period: int = 9,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """LRU 缓存的 KDJ 实现"""
    n = len(closes)
    k_vals: list[float] = [50.0] * n
    d_vals: list[float] = [50.0] * n
    j_vals: list[float] = [50.0] * n

    for i in range(period - 1, n):
        high_max = max(highs[i - period + 1 : i + 1])
        low_min = min(lows[i - period + 1 : i + 1])
        if high_max == low_min:
            rsv = 50.0
        else:
            rsv = (closes[i] - low_min) / (high_max - low_min) * 100

        if i >= period:
            k_vals[i] = (k_smooth - 1) / k_smooth * k_vals[i - 1] + 1 / k_smooth * rsv
            d_vals[i] = (d_smooth - 1) / d_smooth * d_vals[i - 1] + 1 / d_smooth * k_vals[i]
        else:
            k_vals[i] = rsv
            d_vals[i] = rsv
        j_vals[i] = 3 * k_vals[i] - 2 * d_vals[i]

    return tuple(k_vals), tuple(d_vals), tuple(j_vals)


# ============================================================
# ADX / DMI — 平均趋向指标（Wilder 平滑法）
#  +DI: 正向趋向指标（衡量上涨力度）
#  -DI: 负向趋向指标（衡量下跌力度）
#  ADX: 平均趋向指数（衡量趋势强度）
# ============================================================


def calculate_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> tuple[list[float], list[float], list[float]]:
    """计算 ADX / DMI 指标（Wilder 原始平滑法）

    Args:
        highs: 最高价序列
        lows: 最低价序列
        closes: 收盘价序列
        period: 周期，默认 14

    Returns:
        (plus_di, minus_di, adx) 三元组，前 period*2-1 个值为 NaN
    """
    mid_t, up_t, low_t = _cached_adx(tuple(highs), tuple(lows), tuple(closes), period)
    return list(mid_t), list(up_t), list(low_t)


@functools.lru_cache(maxsize=64)
def _cached_adx(
    highs: tuple[float, ...],
    lows: tuple[float, ...],
    closes: tuple[float, ...],
    period: int = 14,
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    n = len(closes)
    plus_di = [0.0] * n
    minus_di = [0.0] * n
    adx = [0.0] * n

    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n

    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        else:
            plus_dm[i] = 0

        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
        else:
            minus_dm[i] = 0

    # Wilder 平滑（类似 RSI 的平滑方法）
    smooth_tr = [0.0] * n
    smooth_plus_dm = [0.0] * n
    smooth_minus_dm = [0.0] * n
    dx = [0.0] * n

    # 第一个平滑值用 SMA
    smooth_tr[period] = sum(tr[1 : period + 1]) / period
    smooth_plus_dm[period] = sum(plus_dm[1 : period + 1]) / period
    smooth_minus_dm[period] = sum(minus_dm[1 : period + 1]) / period

    # Wilder 递推
    for i in range(period + 1, n):
        smooth_tr[i] = smooth_tr[i - 1] - smooth_tr[i - 1] / period + tr[i]
        smooth_plus_dm[i] = smooth_plus_dm[i - 1] - smooth_plus_dm[i - 1] / period + plus_dm[i]
        smooth_minus_dm[i] = smooth_minus_dm[i - 1] - smooth_minus_dm[i - 1] / period + minus_dm[i]

    # +DI / -DI / DX
    for i in range(period, n):
        if smooth_tr[i] > 0:
            plus_di[i] = (smooth_plus_dm[i] / smooth_tr[i]) * 100
            minus_di[i] = (smooth_minus_dm[i] / smooth_tr[i]) * 100
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = abs(plus_di[i] - minus_di[i]) / di_sum * 100

    # ADX = Wilder 平滑 DX
    adx_start = period * 2 - 1
    if adx_start < n:
        adx[adx_start] = sum(dx[period:adx_start]) / (period - 1)
        for i in range(adx_start + 1, n):
            adx[i] = adx[i - 1] - adx[i - 1] / period + dx[i]

    # NaN 标记
    nan = float("nan")
    for i in range(min(adx_start, n)):
        plus_di[i] = nan
        minus_di[i] = nan
        adx[i] = nan

    return tuple(plus_di), tuple(minus_di), tuple(adx)


# ============================================================
# OBV — 能量潮指标（On-Balance Volume）
# 反映量价关系，用于检测量价背离
# ============================================================


def calculate_obv(
    closes: list[float],
    volumes: list[float],
    obv_period: int = 20,
) -> tuple[list[float], list[float]]:
    """计算 OBV 及其移动平均线

    OBV = 累计量：上涨日 +vol，下跌日 -vol，平盘不变
    返回 (obv, obv_ma) — obv_ma 用于观察背离

    Args:
        closes: 收盘价序列
        volumes: 成交量序列
        obv_period: OBV 均线周期，默认 20

    Returns:
        (obv, obv_ma) 二元组
    """
    obv_t, ma_t = _cached_obv(tuple(closes), tuple(volumes), obv_period)
    return list(obv_t), list(ma_t)


@functools.lru_cache(maxsize=64)
def _cached_obv(
    closes: tuple[float, ...],
    volumes: tuple[float, ...],
    obv_period: int = 20,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    n = len(closes)
    obv = [0.0] * n

    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]

    # OBV 均线
    obv_ma = list(_cached_ma(tuple(obv), obv_period))

    return tuple(obv), tuple(obv_ma)
