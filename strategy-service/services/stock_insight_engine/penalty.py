"""
Stock Insight 惩罚计算模块
长线/短线惩罚逻辑，避免追高和过热
"""

import logging

logger = logging.getLogger(__name__)


def calculate_long_penalty(r: dict) -> tuple[float, list[str]]:
    """计算长线惩罚"""
    pen, reasons = 0, []
    near_20d = r.get("near_20d", 0)
    rsi_val = r.get("rsi", 50)
    max_dd = r.get("max_dd", 0)
    roe = r.get("roe", 10)

    if near_20d > 35:
        pen += 12
        reasons.append(f"近20日涨{near_20d:.0f}%")
    elif near_20d > 30:
        pen += 8
        reasons.append(f"近20日涨{near_20d:.0f}%")
    elif near_20d > 25:
        pen += 4
        reasons.append(f"近20日涨{near_20d:.0f}%")

    if rsi_val > 78:
        pen += 10
        reasons.append(f"RSI={rsi_val:.0f}过热")
    elif rsi_val > 75:
        pen += 6
        reasons.append(f"RSI={rsi_val:.0f}过热")
    elif rsi_val > 72:
        pen += 3
        reasons.append(f"RSI={rsi_val:.0f}偏高")

    if max_dd < -45:
        pen += 8
        reasons.append(f"回撤{max_dd:.0f}%深")
    elif max_dd < -35:
        pen += 4
        reasons.append(f"回撤{max_dd:.0f}%")

    if roe < 0:
        pen += 12
        reasons.append("ROE为负")
    elif roe < 1:
        pen += 5
        reasons.append(f"ROE仅{roe:.1f}%")

    return pen, reasons


def calculate_short_penalty(r: dict) -> tuple[float, list[str]]:
    """计算短线惩罚"""
    pen, reasons = 0, []
    near_5d = r.get("near_5d", 0)

    if near_5d > 18:
        pen += 10
        reasons.append(f"近5日涨{near_5d:.0f}%")
    elif near_5d > 15:
        pen += 5
        reasons.append(f"近5日涨{near_5d:.0f}%")

    return pen, reasons
