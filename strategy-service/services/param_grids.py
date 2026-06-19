"""
参数网格定义 — Walk-Forward 参数搜索空间

所有策略的默认参数网格集中管理，供引擎和 API 层共用。
包含个股最优参数字典（策略-股票配对）。
"""

import json
from pathlib import Path

DEFAULT_PARAM_GRIDS: dict[str, dict[str, list]] = {
    "ma-cross": {"ma_fast": [5, 10, 15, 20], "ma_slow": [20, 30, 40, 60]},
    "breakout": {"lookback": [10, 15, 20, 30, 40]},
    "rsi": {"period": [6, 14, 21], "oversold": [20, 30], "overbought": [70, 80]},
    "macd": {"fast": [8, 12, 16], "slow": [20, 26, 30], "signal": [7, 9, 11]},
    "kdj": {"period": [5, 9, 14], "k_smooth": [3, 5], "d_smooth": [3, 5]},
    "vwm": {
        "ma_fast": [3, 5, 8, 10],
        "ma_slow": [15, 20, 30, 40],
        "volume_period": [20],
        "vol_multiplier_buy": [0.8, 1.0, 1.2],
        "rsi_period": [14],
        "rsi_overbought": [80],
    },
    "bollinger": {
        "period": [15, 20, 25],
        "std_mult": [1.8, 2.0, 2.2],
        "rsi_period": [14],
        "rsi_oversold": [30, 35, 40],
        "rsi_overbought": [60, 65, 70],
    },
    "adx": {
        "period": [10, 14, 20],
        "adx_threshold": [20, 22, 25],
        "cross_confirm": [True, False],
    },
    "obv": {
        "lookback": [15, 20, 30],
        "obv_period": [15, 20],
        "vol_surge_mult": [1.2, 1.3, 1.5],
    },
    # VBM — Volatility Breakout Momentum 短线动量突破（v2.1 新增）
    "vbm": {
        "roc_period": [3, 5, 8],
        "vol_lookback": [15, 20],
        "atr_period": [14],
        "roc_threshold": [0.02, 0.03, 0.04],
        "vol_mult": [1.0, 1.2, 1.5],
        "rsi_upper": [65, 70, 75],
    },
    # VPB — 量价事件突破策略（v2.2 退出机制增强）
    # 事件驱动 + 形态突破，双阶段确认架构
    # 默认推荐: use_enhanced_exits=true, trailing_stop_pct=0.06, take_profit_pct=0.15
    "vpb": {
        # 事件检测
        "event_lookback": [15, 20, 30],
        "vol_surge_mult": [1.3, 1.5, 2.0],
        "atr_surge_mult": [1.2, 1.3, 1.5],
        "gap_threshold": [0.015, 0.02, 0.03],
        # 突破确认
        "breakout_lookback": [10, 15, 20],
        "confirm_bars": [0, 1, 2],
        "require_volume": [True, False],
        "vol_confirm_mult": [0.8, 1.0, 1.2],
        # 过滤
        "rsi_overbought": [70, 75, 80],
        "rsi_lower_bound": [35, 40, 45],
        "min_price": [1.0, 5.0],
        # 退出（v2.1 原版）
        "max_hold_days": [10, 15, 20],
        "atr_mult_stop": [1.5, 2.0, 2.5],
        "rsi_trend_exit": [75, 80, 85],
        "ma_exit_period": [5, 10, 15],
        # 退出增强（v2.2 新增 — 最高点回撤止损 + 固定止盈）
        "use_enhanced_exits": [True, False],
        "trailing_stop_pct": [0.04, 0.06, 0.08],
        "take_profit_pct": [0.10, 0.12, 0.15, 0.18],
        # v2.3 趋势过滤 + 复合事件
        "trend_filter": [True, False],
        "trend_ma": [200],
        "combined_event": [False, True],
    },
    # 组合策略：VWM（趋势跟踪）+ BBR（均值回归）
    "combo-vwm-bbr": {
        "vwm_weight": [0.5, 0.6, 0.7, 0.8],
        "bbr_weight": [0.2, 0.3, 0.4, 0.5],
        "bbr_sell_factor": [0.2, 0.3, 0.5],
        "buy_threshold": [0.2, 0.25, 0.3],
        "sell_threshold": [-0.25, -0.2, -0.15],
    },
}

# 策略-股票配对参数（网格搜索优化结果）
# 对每只股票单独优化的策略参数，显著优于统一默认值
_STOCK_PARAMS_CACHE: dict[str, dict] | None = None


def _load_stock_params_file(filename: str) -> dict[str, dict]:
    """加载个股最优参数字典"""
    path = Path(__file__).parent / filename
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _ensure_stock_params_loaded():
    """确保个股参数缓存已加载"""
    global _STOCK_PARAMS_CACHE
    if _STOCK_PARAMS_CACHE is None:
        _STOCK_PARAMS_CACHE = {}
        vwm = _load_stock_params_file("stock_vwm_params.json")
        bbr = _load_stock_params_file("stock_bbr_params.json")
        for k, v in vwm.items():
            v["_strategy_tag"] = "vwm"
            _STOCK_PARAMS_CACHE[f"vwm:{k}"] = v
        for k, v in bbr.items():
            v["_strategy_tag"] = "bollinger"
            _STOCK_PARAMS_CACHE[f"bollinger:{k}"] = v


def get_stock_params(ts_code: str, strategy: str = "vwm") -> dict | None:
    """获取某只股票的最优策略参数（如果已优化）

    Args:
        ts_code: 股票代码
        strategy: 策略名称（vwm / bollinger）

    Returns:
        参数字典，无匹配时返回 None
    """
    _ensure_stock_params_loaded()
    key = f"{strategy}:{ts_code}"
    raw = _STOCK_PARAMS_CACHE.get(key)
    if raw is None:
        return None

    if strategy == "vwm":
        return {
            "ma_fast": raw["ma_fast"],
            "ma_slow": raw["ma_slow"],
            "vol_multiplier_buy": raw["vol_multiplier_buy"],
            "volume_period": 20,
            "rsi_period": 14,
            "rsi_overbought": 80,
        }
    elif strategy == "bollinger":
        p = raw.get("params", {})
        return {
            "period": p.get("period", 20),
            "std_mult": p.get("std_mult", 1.8),
            "rsi_period": p.get("rsi_period", 14),
            "rsi_oversold": p.get("rsi_oversold", 40),
            "rsi_overbought": p.get("rsi_overbought", 60),
        }
    return None


def get_default_param_grid(strategy: str) -> dict[str, list]:
    """获取指定策略的默认参数搜索空间

    Args:
        strategy: 策略名称（ma-cross / breakout / rsi / macd / kdj / vwm / bollinger / adx / obv / vbm / vpb）

    Returns:
        参数网格字典，策略不存在时返回空字典
    """
    return DEFAULT_PARAM_GRIDS.get(strategy, {}).copy()
