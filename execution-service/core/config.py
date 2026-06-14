"""
交易执行服务 - 集中配置管理
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "QuantTradingSystem-Execution"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    DATABASE_URL: str = ""  # 必须通过 .env 或环境变量设置
    RABBITMQ_URL: str = ""  # 必须通过 .env 或环境变量设置

    MINIQMT_USER: str | None = None
    MINIQMT_PASSWORD: str | None = None

    FEISHU_WEBHOOK: str | None = None

    # 风控参数
    MAX_POSITION_RATIO: float = 0.30
    MAX_TOTAL_POSITIONS: int = 3
    STOP_LOSS_RATIO: float = 0.08
    TAKE_PROFIT_RATIO: float = 0.30
    MAX_DAILY_LOSS: float = 0.05

    # 自动执行开关
    AUTO_EXECUTE_STOP_LOSS: bool = True  # 止损触发时自动平仓
    AUTO_EXECUTE_TAKE_PROFIT: bool = True  # 止盈触发时自动平仓

    # 订单验证
    ORDER_EXPIRY_DAYS: int = 5  # 限价单过期天数
    ALLOW_OFF_HOURS_TRADING: bool = False  # 允许非交易时间下单

    # 熔断机制
    CB_CONSECUTIVE_LOSSES: int = 3  # 连续止损N次触发熔断
    CB_COOLDOWN_MINUTES: int = 30  # 熔断冷却时间（分钟）

    class Config:
        env_file = ".env"


settings = Settings()
