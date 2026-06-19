"""
AI调度器微服务配置
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略其他服务的环境变量，只提取本模块定义的字段
    )

    # 服务配置
    SERVICE_NAME: str = "ai-scheduler"
    SERVICE_HOST: str = "0.0.0.0"
    SERVICE_PORT: int = 8002
    DEBUG: bool = False

    # 数据库
    DATABASE_URL: str = "postgresql://quant_user:quant_pass@localhost:5432/quant_trading"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Redis Sentinel 高可用（非空时优先于 REDIS_URL）
    REDIS_SENTINEL_HOSTS: str = ""
    REDIS_SENTINEL_SERVICE_NAME: str = "mymaster"
    REDIS_SENTINEL_SOCKET_TIMEOUT: float = 0.1

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


settings = Settings()
