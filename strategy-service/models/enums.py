"""
枚举类型定义 — 编译期校验的合法值约束
"""

from __future__ import annotations

from enum import Enum


class StrategyName(str, Enum):
    """回测策略名称枚举

    值直接使用底层内部标识符（小写 + 连字符），可无缝替换 str 用法。
    Pydantic v2 自动将传入字符串转为枚举成员（大小写不敏感已内置）。
    """

    # === 传统技术指标策略 ===
    MA_CROSS = "ma-cross"
    BREAKOUT = "breakout"
    RSI = "rsi"
    MACD = "macd"
    KDJ = "kdj"

    # === 高级自定义策略 ===
    VWM = "vwm"                          # 成交量加权动量
    BOLLINGER = "bollinger"              # 布林带均值回归 (BBR)
    ADX = "adx"                          # ADX/DMI 趋势强度
    OBV = "obv"                          # 量价背离
    VBM = "vbm"                          # Volatility Breakout Momentum

    # === 组合策略 ===
    COMBO_VWM_BBR = "combo-vwm-bbr"      # VWM + BBR 组合

    # === v2.1 新策略 ===
    VPB = "vpb"                          # 量价事件突破 (Volume-Price Event Breakout)

    def __str__(self) -> str:
        return self.value

    @classmethod
    def has_value(cls, value: str) -> bool:
        return value in cls._value2member_map_

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]
