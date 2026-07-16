"""
共享风控配置模块 — 策略服务与执行服务共用。
所有风控参数在此集中定义，避免配置漂移。

Usage:
    from shared.risk_config import DEFAULT_RISK_CONFIG, RiskConfig

    # 使用默认配置
    config = RiskConfig()

    # 从环境变量覆盖
    config = RiskConfig(stop_loss_ratio=0.10)
"""

import os
from dataclasses import dataclass, field


def _env_float(key: str, default: float) -> float:
    """安全读取环境变量浮点数。"""
    val = os.getenv(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def _env_int(key: str, default: int) -> int:
    """安全读取环境变量整数。"""
    val = os.getenv(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


def _env_bool(key: str, default: bool) -> bool:
    """安全读取环境变量布尔值。"""
    val = os.getenv(key)
    if val is not None:
        return val.lower() in ("1", "true", "yes", "on")
    return default


@dataclass
class RiskConfig:
    """
    风控配置 — 单例模式，通过环境变量覆盖默认值。

    环境变量覆盖规则：
        QTS_MAX_POSITION_RATIO → max_position_ratio
        QTS_STOP_LOSS_RATIO    → stop_loss_ratio
        ...以此类推
    """

    # ——— 仓位管理 ———
    max_position_ratio: float = field(
        default_factory=lambda: _env_float("QTS_MAX_POSITION_RATIO", 0.30)
    )
    """单只股票最大仓位比例（0-1）"""

    max_total_positions: int = field(default_factory=lambda: _env_int("QTS_MAX_TOTAL_POSITIONS", 3))
    """最大同时持仓数量"""

    # ——— 止损止盈 ———
    stop_loss_ratio: float = field(default_factory=lambda: _env_float("QTS_STOP_LOSS_RATIO", 0.08))
    """固定止损比例（0-1），亏损超过此值触发止损"""

    take_profit_ratio: float = field(
        default_factory=lambda: _env_float("QTS_TAKE_PROFIT_RATIO", 0.30)
    )
    """固定止盈比例（0-1），盈利超过此值触发止盈"""

    max_daily_loss: float = field(default_factory=lambda: _env_float("QTS_MAX_DAILY_LOSS", 0.05))
    """单日最大亏损比例（0-1），超过则暂停交易"""

    # ——— 熔断机制（执行服务） ———
    cb_consecutive_losses: int = field(
        default_factory=lambda: _env_int("QTS_CB_CONSECUTIVE_LOSSES", 3)
    )
    """连续止损 N 次触发熔断"""

    cb_cooldown_minutes: int = field(
        default_factory=lambda: _env_int("QTS_CB_COOLDOWN_MINUTES", 30)
    )
    """熔断冷却时间（分钟）"""

    # ——— 自动执行开关 ———
    auto_execute_stop_loss: bool = field(
        default_factory=lambda: _env_bool("QTS_AUTO_EXECUTE_STOP_LOSS", True)
    )
    """止损触发时是否自动平仓"""

    auto_execute_take_profit: bool = field(
        default_factory=lambda: _env_bool("QTS_AUTO_EXECUTE_TAKE_PROFIT", True)
    )
    """止盈触发时是否自动平仓"""

    auto_execute_signals: bool = field(
        default_factory=lambda: _env_bool("QTS_AUTO_EXECUTE_SIGNALS", False)
    )
    """是否自动执行策略信号（安全开关）"""

    # ——— 高级风控规则（2026-07-15 新增，试运行模式） ———
    advanced_rules_enabled: bool = field(
        default_factory=lambda: _env_bool("QTS_ADVANCED_RULES_ENABLED", True)
    )
    """是否启用高级风控规则"""

    advanced_rules_auto_execute: bool = field(
        default_factory=lambda: _env_bool("QTS_ADVANCED_RULES_AUTO_EXECUTE", False)
    )
    """高级规则是否自动执行（默认NO：只提醒不执行）"""

    # Rule1: 止损硬化
    stop_loss_hard_pct: float = field(
        default_factory=lambda: _env_float("QTS_STOP_LOSS_HARD_PCT", 0.08)
    )
    """硬止损阈值：收盘价 ≤ 成本*(1-此值)"""

    stop_loss_atr_mult: float = field(
        default_factory=lambda: _env_float("QTS_STOP_LOSS_ATR_MULT", 1.8)
    )
    """ATR止损倍数：收盘价 ≤ 入场价 - N×ATR(14)"""

    stop_loss_atr_period: int = field(
        default_factory=lambda: _env_int("QTS_STOP_LOSS_ATR_PERIOD", 14)
    )
    """ATR计算周期"""

    # Rule2: 暴跌日冻结买入
    freeze_buy_stock_drop: float = field(
        default_factory=lambda: _env_float("QTS_FREEZE_BUY_STOCK_DROP", 0.07)
    )
    """个股单日跌幅触发买入冻结"""

    freeze_buy_sector_drop: float = field(
        default_factory=lambda: _env_float("QTS_FREEZE_BUY_SECTOR_DROP", 0.05)
    )
    """行业指数单日跌幅触发买入冻结"""

    freeze_buy_limit_ratio: float = field(
        default_factory=lambda: _env_float("QTS_FREEZE_BUY_LIMIT_RATIO", 3.0)
    )
    """跌停家数/涨停家数 触发买入冻结"""

    freeze_buy_thaw_days: int = field(
        default_factory=lambda: _env_int("QTS_FREEZE_BUY_THAW_DAYS", 2)
    )
    """解冻条件：两连阳天数"""

    freeze_buy_thaw_volume_mult: float = field(
        default_factory=lambda: _env_float("QTS_FREEZE_BUY_THAW_VOLUME_MULT", 1.5)
    )
    """解冻条件：放量倍数（成交量/5日均量）"""

    # Rule3: 卖飞冷却
    sell_cooldown_days: int = field(default_factory=lambda: _env_int("QTS_SELL_COOLDOWN_DAYS", 10))
    """卖出后冷却期（交易日）"""

    sell_cooldown_extended_days: int = field(
        default_factory=lambda: _env_int("QTS_SELL_COOLDOWN_EXTENDED_DAYS", 20)
    )
    """卖出后创新高 → 延长冷却期"""

    sell_cooldown_new_high_days: int = field(
        default_factory=lambda: _env_int("QTS_SELL_COOLDOWN_NEW_HIGH_DAYS", 5)
    )
    """卖出后N日内创新高触发延长"""

    # Rule4: T+3 决策矩阵
    t3_lock_profit_pct: float = field(
        default_factory=lambda: _env_float("QTS_T3_LOCK_PROFIT_PCT", 0.05)
    )
    """T+3 浮盈≥N% 锁利30%"""

    t3_reduce_light_pct: float = field(
        default_factory=lambda: _env_float("QTS_T3_REDUCE_LIGHT_PCT", 0.03)
    )
    """T+3 浮亏≥N% 减仓50%"""

    t3_reduce_early_pct: float = field(
        default_factory=lambda: _env_float("QTS_T3_REDUCE_EARLY_PCT", 0.0)
    )
    """T+3 浮亏≥N%(轻) 减仓30%"""

    # Rule5: 双账户合并记账
    dual_account_premium_threshold: float = field(
        default_factory=lambda: _env_float("QTS_DUAL_ACCOUNT_PREMIUM_PCT", 0.10)
    )
    """多次买入价差≥N%触发高位接刀告警"""

    # Rule6: 卖飞保留仓
    sell_retention_pct: float = field(
        default_factory=lambda: _env_float("QTS_SELL_RETENTION_PCT", 0.15)
    )
    """清仓时建议保留的跟踪仓比例"""

    # Rule7: 单票仓位上限
    max_single_position_ratio: float = field(
        default_factory=lambda: _env_float("QTS_MAX_SINGLE_POSITION_RATIO", 0.15)
    )
    """单票仓位上限（总资产比例）"""

    # Rule8: 入场区间
    entry_ma_period: int = field(default_factory=lambda: _env_int("QTS_ENTRY_MA_PERIOD", 20))
    """入场建议参照的MA周期"""

    # Rule9: 盈亏比
    min_risk_reward_ratio: float = field(
        default_factory=lambda: _env_float("QTS_MIN_RISK_REWARD_RATIO", 1.8)
    )
    """最低可接受盈亏比"""

    # 高级规则状态存储路径
    advanced_rules_state_path: str = field(
        default_factory=lambda: os.getenv(
            "QTS_ADVANCED_RULES_STATE_PATH",
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "/tmp",
                "claw_data",
                "advanced_rules_state.json",
            ),
        )
    )

    # ——— 订单管理（执行服务） ———
    order_expiry_days: int = field(default_factory=lambda: _env_int("QTS_ORDER_EXPIRY_DAYS", 5))
    """限价单过期天数"""

    allow_off_hours_trading: bool = field(
        default_factory=lambda: _env_bool("QTS_ALLOW_OFF_HOURS_TRADING", False)
    )
    """是否允许非交易时间下单"""

    def to_dict(self) -> dict:
        """导出为字典，供 Pydantic Settings 合并使用。"""
        return {
            "MAX_POSITION_RATIO": self.max_position_ratio,
            "MAX_TOTAL_POSITIONS": self.max_total_positions,
            "STOP_LOSS_RATIO": self.stop_loss_ratio,
            "TAKE_PROFIT_RATIO": self.take_profit_ratio,
            "MAX_DAILY_LOSS": self.max_daily_loss,
            "CB_CONSECUTIVE_LOSSES": self.cb_consecutive_losses,
            "CB_COOLDOWN_MINUTES": self.cb_cooldown_minutes,
            "AUTO_EXECUTE_STOP_LOSS": self.auto_execute_stop_loss,
            "AUTO_EXECUTE_TAKE_PROFIT": self.auto_execute_take_profit,
            "AUTO_EXECUTE_SIGNALS": self.auto_execute_signals,
            "ADVANCED_RULES_ENABLED": self.advanced_rules_enabled,
            "ADVANCED_RULES_AUTO_EXECUTE": self.advanced_rules_auto_execute,
            "STOP_LOSS_HARD_PCT": self.stop_loss_hard_pct,
            "STOP_LOSS_ATR_MULT": self.stop_loss_atr_mult,
            "FREEZE_BUY_STOCK_DROP": self.freeze_buy_stock_drop,
            "FREEZE_BUY_SECTOR_DROP": self.freeze_buy_sector_drop,
            "SELL_COOLDOWN_DAYS": self.sell_cooldown_days,
            "T3_LOCK_PROFIT_PCT": self.t3_lock_profit_pct,
            "T3_REDUCE_LIGHT_PCT": self.t3_reduce_light_pct,
            "T3_REDUCE_EARLY_PCT": self.t3_reduce_early_pct,
            "ORDER_EXPIRY_DAYS": self.order_expiry_days,
            "ALLOW_OFF_HOURS_TRADING": self.allow_off_hours_trading,
        }


# 全局默认实例
DEFAULT_RISK_CONFIG = RiskConfig()
