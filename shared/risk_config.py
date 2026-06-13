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

from dataclasses import dataclass, field
import os


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
            "ORDER_EXPIRY_DAYS": self.order_expiry_days,
            "ALLOW_OFF_HOURS_TRADING": self.allow_off_hours_trading,
        }


# 全局默认实例
DEFAULT_RISK_CONFIG = RiskConfig()
