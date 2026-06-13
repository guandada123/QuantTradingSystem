"""
AI调度器微服务配置
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 服务配置
    SERVICE_NAME: str = "ai-scheduler"
    SERVICE_HOST: str = "0.0.0.0"
    SERVICE_PORT: int = 8002
    DEBUG: bool = False

    # 数据库
    DATABASE_URL: str = "postgresql://quant:quant123@postgres:5432/quanttrading"
    REDIS_URL: str = "redis://redis:6379/0"

    # AI模型
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # 下游服务
    STRATEGY_SERVICE_URL: str = "http://strategy-service:8000"
    EXECUTION_SERVICE_URL: str = "http://execution-service:8001"

    # 飞书告警
    FEISHU_WEBHOOK: str | None = None
    HEALTH_CHECK_INTERVAL: int = 300  # 5 minutes

    # 调度参数
    SCAN_INTERVAL_MINUTES: int = 30
    MAX_CANDIDATES: int = 100
    AI_TIMEOUT_SECONDS: int = 30

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 忽略其他服务的环境变量，只提取本模块定义的字段


settings = Settings()
