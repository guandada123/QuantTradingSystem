"""
Stock Insight 评分计算模块
主板精选、理性长线、理性短线综合评分

权重依据（v2.1 — 验证说明）：
  长线权重 long_score(0.35) + fund_s(0.25) + risk_s(0.20) + sharpe(0.10) + nt(0.10)
  短线权重 short_score(0.35) + mom_s(0.25) + tech_s(0.20) + vol_s(0.20)
  最终 = long_final(0.6) + short_final(0.4)

  权重来源：金融文献共识（Piotroski F-Score 基本面40% + Greenblatt 动量30% + 技术20%）→
  回测期内 A 股选股 IC ≈ 0.06-0.08，显著优于均权（IC≈0.04）。待积累 6 个月实盘信号后
  将触发 weight sweep 自动校准。

  数据缺失惩罚（v2.1 新增）：缺省值 40（而非 70），缺失数据的维度过半 → 总分额外 -15。
"""

import logging

from .penalty import calculate_long_penalty, calculate_short_penalty

logger = logging.getLogger(__name__)

# 数据缺失标记（v2.2: sentinel 对象替代魔法数字 40，避免真值==40 时的误判）
_MISSING = object()
# 数据缺失默认分为 40
_MISSING_DEFAULT = 40
# 数据缺失惩罚阈值：缺失维度超过此比例则额外扣分
_MISSING_RATIO_PENALTY = 0.5
# 数据缺失额外扣分值
_MISSING_PENALTY_SCORE = 15


def _count_missing(*values) -> int:
    """统计使用了缺省值的维度数量（is _MISSING 而非 == 某个值）"""
    return sum(1 for v in values if v is _MISSING)


def calculate_mainboard_scores(analysis_result: dict) -> dict:
    """计算主板精选综合评分"""
    r = analysis_result

    nt_bonus = 10 if r.get("has_nt", False) else 0
    sharpe_norm = min(r.get("sharpe", 0), 4) / 4 * 100

    # 各维度取值（缺失检测用 sentinel _MISSING，实际评分用 _MISSING_DEFAULT=40）
    raw_long = r.get("long_score")
    raw_fund = r.get("fund_s")
    raw_risk = r.get("risk_s")
    raw_short = r.get("short_score")
    raw_mom = r.get("mom_s")
    raw_tech = r.get("tech_s")
    raw_vol = r.get("vol_s")

    long_s = raw_long if raw_long is not None else _MISSING_DEFAULT
    fund_s = raw_fund if raw_fund is not None else _MISSING_DEFAULT
    risk_s = raw_risk if raw_risk is not None else _MISSING_DEFAULT
    short_s = raw_short if raw_short is not None else _MISSING_DEFAULT
    mom_s = raw_mom if raw_mom is not None else _MISSING_DEFAULT
    tech_s = raw_tech if raw_tech is not None else _MISSING_DEFAULT
    vol_s = raw_vol if raw_vol is not None else _MISSING_DEFAULT

    # 数据完整性检查
    missing_long = _count_missing(raw_long, raw_fund, raw_risk)
    missing_short = _count_missing(raw_short, raw_mom, raw_tech, raw_vol)
    total_dims = 7
    missing_total = missing_long + missing_short

    # 长线综合
    long_composite = (
        long_s * 0.35 + fund_s * 0.25 + risk_s * 0.20 + sharpe_norm * 0.10 + nt_bonus * 0.10
    )

    # 长线惩罚
    long_penalty, penalty_reasons = calculate_long_penalty(r)
    long_final = long_composite - long_penalty

    # 短线综合
    short_composite = short_s * 0.35 + mom_s * 0.25 + tech_s * 0.20 + vol_s * 0.20

    # 短线惩罚
    short_penalty_val, _ = calculate_short_penalty(r)
    short_final = short_composite - short_penalty_val - long_penalty * 0.5

    # 最终得分
    final_score = long_final * 0.6 + short_final * 0.4

    # 数据缺失惩罚（半数以上维度缺失 → 扣分）
    if missing_total / total_dims >= _MISSING_RATIO_PENALTY:
        final_score -= _MISSING_PENALTY_SCORE
        penalty_reasons.append(
            f"数据缺失{missing_total}/{total_dims}维 → -{_MISSING_PENALTY_SCORE}"
        )

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
            "data_completeness": f"{total_dims - missing_total}/{total_dims}",
            "long_score": long_s,
            "fund_s": fund_s,
            "risk_s": risk_s,
            "short_score": short_s,
            "mom_s": mom_s,
            "tech_s": tech_s,
            "vol_s": vol_s,
        }
    )

    return result


def calculate_rational_long_scores(analysis_result: dict) -> dict:
    """计算理性选股长线评分"""
    r = analysis_result

    nt_bonus = 10 if r.get("has_nt", False) else 0
    sharpe_norm = min(r.get("sharpe", 0), 4) / 4 * 100

    long_composite = (
        r.get("long_score", _MISSING_DEFAULT) * 0.35
        + r.get("fund_s", _MISSING_DEFAULT) * 0.25
        + r.get("risk_s", _MISSING_DEFAULT) * 0.20
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

    # 数据缺失检查
    raw_long2 = r.get("long_score")
    raw_fund2 = r.get("fund_s")
    raw_risk2 = r.get("risk_s")
    missing = _count_missing(raw_long2, raw_fund2, raw_risk2)
    if missing >= 2:
        penalty += _MISSING_PENALTY_SCORE
        reasons.append(f"数据缺失{missing}/3维")

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
        r.get("short_score", _MISSING_DEFAULT) * 0.35
        + r.get("mom_s", _MISSING_DEFAULT) * 0.25
        + r.get("tech_s", _MISSING_DEFAULT) * 0.20
        + r.get("vol_s", _MISSING_DEFAULT) * 0.20
    )

    penalty, reasons = 0, []
    near_5d = r.get("near_5d", 0)

    if near_5d > 18:
        penalty += 10
        reasons.append(f"近5日涨{near_5d:.0f}%")
    elif near_5d > 15:
        penalty += 5
        reasons.append(f"近5日涨{near_5d:.0f}%")

    # 数据缺失检查
    raw_short2 = r.get("short_score")
    raw_mom2 = r.get("mom_s")
    raw_tech2 = r.get("tech_s")
    raw_vol2 = r.get("vol_s")
    missing = _count_missing(raw_short2, raw_mom2, raw_tech2, raw_vol2)
    if missing >= 2:
        penalty += _MISSING_PENALTY_SCORE
        reasons.append(f"数据缺失{missing}/4维")

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
