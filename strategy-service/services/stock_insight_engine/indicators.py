"""
Stock Insight 技术指标计算模块
价格变化、RSI、最大回撤等指标计算
"""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calculate_price_change(df: pd.DataFrame, days: int) -> float:
    """计算价格变化百分比"""
    if len(df) < days:
        return 0.0

    try:
        close_col = "close" if "close" in df.columns else df.columns[-1]
        start_price = float(df.iloc[-days][close_col])
        end_price = float(df.iloc[-1][close_col])

        if start_price > 0:
            return (end_price - start_price) / start_price * 100
    except Exception as e:
        logger.warning("计算收益率失败: %s", e)

    return 0.0


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    """计算RSI指标"""
    if len(df) < period + 1:
        return 50.0

    try:
        close_col = "close" if "close" in df.columns else df.columns[-1]
        prices = df[close_col].astype(float).values

        deltas = np.diff(prices)
        gains = deltas[deltas > 0]
        losses = -deltas[deltas < 0]

        if len(gains) == 0 and len(losses) == 0:
            return 50.0  # 所有差价为零（价格持平）
        if len(losses) == 0:
            return 100.0  # 全部上涨
        if len(gains) == 0:
            return 0.0  # 全部下跌

        avg_gain = np.mean(gains[-period:]) if len(gains) >= period else np.mean(gains)
        avg_loss = np.mean(losses[-period:]) if len(losses) >= period else np.mean(losses)

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return min(max(rsi, 0), 100)
    except Exception as e:
        logger.warning("计算RSI失败: %s", e)
        return 50.0


def calculate_max_drawdown(df: pd.DataFrame) -> float:
    """计算最大回撤"""
    if len(df) < 2:
        return 0.0

    try:
        close_col = "close" if "close" in df.columns else df.columns[-1]
        prices = df[close_col].astype(float).values

        peak = prices[0]
        max_dd = 0.0

        for price in prices:
            peak = max(peak, price)
            dd = (price - peak) / peak * 100
            max_dd = min(max_dd, dd)

        return max_dd
    except Exception as e:
        logger.warning("计算最大回撤失败: %s", e)
        return 0.0
