"""
市场状态过滤器 — L1 架构（最高杠杆优化）

核心功能：
  根据价格趋势、趋势强度、动量确认，判定当前市场状态，
  输出仓位系数供策略引擎进行动态仓位管理。

判定流程（三级判定）：
  1. 趋势方向：MA50 vs MA200 的相对位置 + 斜率
  2. 趋势强度：ADX(14) 过滤弱趋势/震荡
  3. 动量确认：短期 ROC + 成交量配合

状态输出（三档）：
  BULL (1.0):   MA50 > MA200 + 上升趋势 → 全仓开火
  OSCILLATE (0.5): MA50 ≈ MA200 + 低ADX → 半仓谨慎
  BEAR (0.25):  MA50 < MA200 + 下降趋势 → 25%或空仓

用法示例：
    >>> from services.market_regime import MarketRegimeFilter, Regime
    >>> rf = MarketRegimeFilter()
    >>> regime = rf.classify(closes, highs, lows, volumes)
    >>> mult = rf.get_position_mult(regime)
    >>> print(regime, mult)  # Regime.BULL, 1.0
"""

from __future__ import annotations

import enum
import math

# ============================================================
# 市场状态枚举
# ============================================================


class Regime(enum.Enum):
    """市场状态四档（v2.1 新增 TRANSITION 过渡态）"""

    BULL = "bull"  # 牛市 — 全仓
    OSCILLATE = "oscillate"  # 震荡 — 半仓
    BEAR = "bear"  # 熊市 — 25%仓或空仓
    TRANSITION = "transition"  # 过渡态 — 快/慢窗口分歧，半仓谨慎


# ============================================================
# 内部指标计算（轻量版，避免引入 indicators 模块的依赖）
# ============================================================


def _calc_sma(prices: list[float], period: int) -> list[float]:
    """简单移动平均（前缀和 O(n)）"""
    n = len(prices)
    if n < period:
        return [float("nan")] * n
    result: list[float] = [float("nan")] * (period - 1)
    prefix = [0.0]
    for p in prices:
        prefix.append(prefix[-1] + p)
    for i in range(period - 1, n):
        result.append((prefix[i + 1] - prefix[i + 1 - period]) / period)
    return result


def _calc_adx(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[float]:
    """计算 ADX（仅返回 ADX 值，用于趋势强度判定）"""
    n = len(closes)
    adx = [0.0] * n
    if n < period * 2:
        return adx

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
        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0

    # Wilder 平滑
    smooth_tr = [0.0] * n
    smooth_plus = [0.0] * n
    smooth_minus = [0.0] * n
    dx = [0.0] * n

    smooth_tr[period] = sum(tr[1 : period + 1]) / period
    smooth_plus[period] = sum(plus_dm[1 : period + 1]) / period
    smooth_minus[period] = sum(minus_dm[1 : period + 1]) / period

    for i in range(period + 1, n):
        smooth_tr[i] = smooth_tr[i - 1] - smooth_tr[i - 1] / period + tr[i]
        smooth_plus[i] = smooth_plus[i - 1] - smooth_plus[i - 1] / period + plus_dm[i]
        smooth_minus[i] = smooth_minus[i - 1] - smooth_minus[i - 1] / period + minus_dm[i]

    for i in range(period, n):
        if smooth_tr[i] > 0:
            pdi = (smooth_plus[i] / smooth_tr[i]) * 100
            mdi = (smooth_minus[i] / smooth_tr[i]) * 100
            di_sum = pdi + mdi
            if di_sum > 0:
                dx[i] = abs(pdi - mdi) / di_sum * 100

    # ADX = SMA of DX
    for i in range(period * 2 - 1, n):
        adx[i] = sum(dx[i - period + 1 : i + 1]) / period

    return adx


def _calc_roc(prices: list[float], period: int = 20) -> list[float]:
    """计算 ROC（变动率）"""
    n = len(prices)
    result: list[float] = [0.0] * n
    for i in range(period, n):
        prev = prices[i - period]
        result[i] = (prices[i] - prev) / prev if prev != 0 else 0.0
    return result


# ============================================================
# 市场状态过滤器
# ============================================================


class MarketRegimeFilter:
    """市场状态过滤器

    对任意价格序列进行状态判定，输出 BULL / OSCILLATE / BEAR。

    Parameters
    ----------
    ma_fast : int
        快速均线周期（默认 50）
    ma_slow : int
        慢速均线周期（默认 200）
    adx_period : int
        ADX 计算周期（默认 14）
    adx_threshold : float
        强趋势 ADX 阈值（默认 22）
    roc_period : int
        ROC 计算周期（默认 20）
    roc_bull_threshold : float
        确认牛市的 ROC 下限（默认 0.02, 即 2%）
    roc_bear_threshold : float
        确认熊市的 ROC 上限（默认 -0.02）
    """

    def __init__(
        self,
        ma_fast: int = 50,
        ma_slow: int = 200,
        adx_period: int = 14,
        adx_threshold: float = 22.0,
        roc_period: int = 20,
        roc_bull_threshold: float = 0.02,
        roc_bear_threshold: float = -0.02,
    ):
        self.ma_fast = ma_fast
        self.ma_slow = ma_slow
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.roc_period = roc_period
        self.roc_bull_threshold = roc_bull_threshold
        self.roc_bear_threshold = roc_bear_threshold

        # 缓存上次分类结果
        self._last_regime: Regime = Regime.OSCILLATE
        self._last_position_mult: float = 0.5
        self._last_ma_fast_val: float = float("nan")
        self._last_ma_slow_val: float = float("nan")
        self._last_adx_val: float = float("nan")

    # -----------------------------------------------------------
    # 核心判定
    # -----------------------------------------------------------

    def classify(
        self,
        closes: list[float],
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        volumes: list[float] | None = None,
    ) -> Regime:
        """判定市场状态

        Args:
            closes: 收盘价序列（必须）
            highs: 最高价序列（ADX 判定需要，可省略）
            lows: 最低价序列（ADX 判定需要，可省略）
            volumes: 成交量序列（可选，用于辅助确认）

        Returns:
            当前市场状态 Regime 枚举
        """
        n = len(closes)
        if n < max(self.ma_slow, self.adx_period * 2) + 5:
            return Regime.OSCILLATE  # 数据不足，保守处理

        # ---- Step 1: 趋势方向判定 ----
        ma_fast = _calc_sma(closes, self.ma_fast)
        ma_slow = _calc_sma(closes, self.ma_slow)

        fast_val = ma_fast[-1] if not math.isnan(ma_fast[-1]) else closes[-1]
        slow_val = ma_slow[-1] if not math.isnan(ma_slow[-1]) else closes[-1]

        # MA 斜率（用最后 5 根 bar 的均值变化）
        fast_slope = self._calc_slope(ma_fast, 5)
        slow_slope = self._calc_slope(ma_slow, 5)

        # ---- Step 2: 趋势强度判定 ----
        if highs and lows:
            adx_values = _calc_adx(highs, lows, closes, self.adx_period)
            adx_val = adx_values[-1] if not math.isnan(adx_values[-1]) else 0.0
        else:
            adx_val = 0.0

        # ---- Step 3: 动量确认 ----
        roc = _calc_roc(closes, self.roc_period)
        roc_val = roc[-1] if not math.isnan(roc[-1]) else 0.0

        # 缓存中间值（供调试查看）
        self._last_ma_fast_val = fast_val
        self._last_ma_slow_val = slow_val
        self._last_adx_val = adx_val

        # ---- 综合判定 ----
        # 牛市条件（全部满足）：
        #   1. MA50 > MA200
        #   2. MA50 斜率 > 0（短期上升）
        #   3. ADX > 阈值 或 ROC > 阈值（趋势确认）
        if (
            fast_val > slow_val
            and fast_slope > 0
            and (adx_val > self.adx_threshold or roc_val > self.roc_bull_threshold)
        ):
            self._last_regime = Regime.BULL
            self._last_position_mult = 1.0
            return Regime.BULL

        # 熊市条件（全部满足）：
        #   1. MA50 < MA200
        #   2. MA50 斜率 < 0（短期下降）
        #   3. ROC < 阈值（动量衰竭）
        if fast_val < slow_val and fast_slope < 0 and roc_val < self.roc_bear_threshold:
            self._last_regime = Regime.BEAR
            self._last_position_mult = 0.25
            return Regime.BEAR

        # 其余归为震荡
        self._last_regime = Regime.OSCILLATE
        self._last_position_mult = 0.5
        return Regime.OSCILLATE

    def classify_fast(
        self,
        closes: list[float],
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> Regime:
        """快速模式判定（EMA20/60 — v2.1 新增）

        用于补充慢速 MA50/200 的滞后问题。当快速模式与慢速模式结论冲突时，
        输出 TRANSITION 过渡态。
        """
        slow_result = self.classify(closes, highs, lows)

        n = len(closes)
        if n < 65:
            return slow_result  # 数据不足以跑快速窗口

        # 快速窗口：EMA20 vs EMA60
        ema20 = _calc_sma(closes, 20)  # 用 SMA 近似 EMA（够用）
        ema60 = _calc_sma(closes, 60)

        ema20_val = ema20[-1] if not math.isnan(ema20[-1]) else closes[-1]
        ema60_val = ema60[-1] if not math.isnan(ema60[-1]) else closes[-1]
        ema20_slope = MarketRegimeFilter._calc_slope(ema20, 3)

        # 快速牛：EMA20 > EMA60 + 短线上扬
        fast_bull = ema20_val > ema60_val and ema20_slope > 0
        # 快速熊：EMA20 < EMA60 + 短线下行
        fast_bear = ema20_val < ema60_val and ema20_slope < 0

        # 过渡态检测：慢速窗口信号与快速窗口相反
        if slow_result == Regime.BULL and fast_bear:
            self._last_regime = Regime.TRANSITION
            self._last_position_mult = 0.4
            return Regime.TRANSITION
        if slow_result == Regime.BEAR and fast_bull:
            self._last_regime = Regime.TRANSITION
            self._last_position_mult = 0.4
            return Regime.TRANSITION

        return slow_result

    # -----------------------------------------------------------
    # 仓位系数
    # -----------------------------------------------------------

    @staticmethod
    def get_position_mult(regime: Regime) -> float:
        """根据市场状态获取仓位系数"""
        return {
            Regime.BULL: 1.0,
            Regime.OSCILLATE: 0.5,
            Regime.BEAR: 0.25,
            Regime.TRANSITION: 0.4,  # 过渡态：快慢窗口分歧，略低于震荡
        }.get(regime, 0.5)

    # -----------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------

    @staticmethod
    def _calc_slope(series: list[float], window: int = 5) -> float:
        """计算序列最近 window 个有效值的斜率（简单线性回归）"""
        valid = [(i, v) for i, v in enumerate(series) if not math.isnan(v)]
        if len(valid) < window:
            return 0.0
        recent = valid[-window:]
        x_vals = [p[0] for p in recent]
        y_vals = [p[1] for p in recent]
        n = len(x_vals)
        if n < 2:
            return 0.0
        x_mean = sum(x_vals) / n
        y_mean = sum(y_vals) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
        den = sum((x - x_mean) ** 2 for x in x_vals)
        return num / den if den != 0 else 0.0

    # -----------------------------------------------------------
    # 报告
    # -----------------------------------------------------------

    def get_last_state(self) -> dict:
        """获取最近一次判定的详细信息"""
        return {
            "regime": self._last_regime.value,
            "position_mult": self._last_position_mult,
            "ma_fast": round(self._last_ma_fast_val, 2)
            if not math.isnan(self._last_ma_fast_val)
            else None,
            "ma_slow": round(self._last_ma_slow_val, 2)
            if not math.isnan(self._last_ma_slow_val)
            else None,
            "adx": round(self._last_adx_val, 2) if not math.isnan(self._last_adx_val) else None,
        }
