"""
Stock Insight 评分计算模块
主板精选、理性长线、理性短线综合评分
"""

import logging

from .penalty import calculate_long_penalty, calculate_short_penalty

logger = logging.getLogger(__name__)


def calculate_mainboard_scores(analysis_result: dict) -> dict:
    """计算主板精选综合评分"""
    r = analysis_result

    nt_bonus = 10 if r.get("has_nt", False) else 0
    sharpe_norm = min(r.get("sharpe", 0), 4) / 4 * 100

    # 长线综合
    long_composite = (
        r.get("long_score", 70) * 0.35
        + r.get("fund_s", 70) * 0.25
        + r.get("risk_s", 70) * 0.20
        + sharpe_norm * 0.10
        + nt_bonus * 0.10
    )

    # 长线惩罚
    long_penalty, penalty_reasons = calculate_long_penalty(r)
    long_final = long_composite - long_penalty

    # 短线综合
    short_composite = (
        r.get("short_score", 70) * 0.35
        + r.get("mom_s", 70) * 0.25
        + r.get("tech_s", 70) * 0.20
        + r.get("vol_s", 70) * 0.20
    )

    # 短线惩罚
    short_penalty_val, _ = calculate_short_penalty(r)
    short_final = short_composite - short_penalty_val - long_penalty * 0.5

    # 最终得分
    final_score = long_final * 0.6 + short_final * 0.4

    result = r.copy()
    result.update(
        {
            "long_composite": long_composite,
            "long_penalty": long_penalty,
            "long_final": long_final,
            "short_composite": short_composite,
            "short_penalty": short_penalty_val,
            "short_final": short_final,
            "final_score": final_score,
            "penalty_reasons": penalty_reasons,
            "long_score": r.get("long_score", 70),
            "fund_s": r.get("fund_s", 70),
            "risk_s": r.get("risk_s", 70),
            "short_score": r.get("short_score", 70),
            "mom_s": r.get("mom_s", 70),
            "tech_s": r.get("tech_s", 70),
            "vol_s": r.get("vol_s", 70),
        }
    )

    return result


def calculate_rational_long_scores(analysis_result: dict) -> dict:
    """计算理性选股长线评分"""
    r = analysis_result

    nt_bonus = 10 if r.get("has_nt", False) else 0
    sharpe_norm = min(r.get("sharpe", 0), 4) / 4 * 100

    long_composite = (
        r.get("long_score", 70) * 0.35
        + r.get("fund_s", 70) * 0.25
        + r.get("risk_s", 70) * 0.20
        + sharpe_norm * 0.10
        + nt_bonus * 0.10
    )

    # 惩罚计算（行内版，独立于 mainboard 惩罚）
    penalty, reasons = 0, []
    near_20d = r.get("near_20d", 0)
    rsi_val = r.get("rsi", 50)
    max_dd = r.get("max_dd", 0)
    roe = r.get("roe", 10)

    if near_20d > 30:
        penalty += 10
        reasons.append(f"近20日涨{near_20d:.0f}%")
    elif near_20d > 25:
        penalty += 5
        reasons.append(f"近20日涨{near_20d:.0f}%")

    if rsi_val > 75:
        penalty += 8
        reasons.append(f"RSI={rsi_val:.0f}过热")
    elif rsi_val > 72:
        penalty += 4
        reasons.append(f"RSI={rsi_val:.0f}偏高")

    if max_dd < -35:
        penalty += 5
        reasons.append(f"回撤{max_dd:.0f}%过大")

    if roe < 0:
        penalty += 10
        reasons.append("ROE为负")

    long_final = long_composite - penalty

    result = r.copy()
    result.update(
        {
            "long_composite": long_composite,
            "penalty": penalty,
            "penalty_reasons": reasons,
            "long_final": long_final,
            "selection_type": "long_term",
        }
    )

    return result


def calculate_rational_short_scores(analysis_result: dict) -> dict:
    """计算理性选股短线评分"""
    r = analysis_result

    short_composite = (
        r.get("short_score", 70) * 0.35
        + r.get("mom_s", 70) * 0.25
        + r.get("tech_s", 70) * 0.20
        + r.get("vol_s", 70) * 0.20
    )

    penalty, reasons = 0, []
    near_5d = r.get("near_5d", 0)

    if near_5d > 18:
        penalty += 10
        reasons.append(f"近5日涨{near_5d:.0f}%")
    elif near_5d > 15:
        penalty += 5
        reasons.append(f"近5日涨{near_5d:.0f}%")

    short_final = short_composite - penalty

    result = r.copy()
    result.update(
        {
            "short_composite": short_composite,
            "penalty": penalty,
            "penalty_reasons": reasons,
            "short_final": short_final,
            "selection_type": "short_term",
        }
    )

    return result
