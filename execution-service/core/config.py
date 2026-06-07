"""
交易执行服务 - 集中配置管理
"""

from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "QuantTradingSystem-Execution"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    DATABASE_URL: str = "postgresql://quant_user:quant_pass@localhost:5432/quant_trading"
    RABBITMQ_URL: str = "amqp://localhost:5672"
    
    MINIQMT_USER: Optional[str] = None
    MINIQMT_PASSWORD: Optional[str] = None
    
    FEISHU_WEBHOOK: Optional[str] = None
    
    MAX_POSITION_RATIO: float = 0.30
    MAX_TOTAL_POSITIONS: int = 3
    STOP_LOSS_RATIO: float = 0.08
    TAKE_PROFIT_RATIO: float = 0.30
    MAX_DAILY_LOSS: float = 0.05
    
    class Config:
        env_file = ".env"

settings = Settings()
