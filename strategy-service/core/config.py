"""
策略研究服务 - 集中配置管理
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    # 服务相关
    APP_NAME: str = "QuantTradingSystem"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # 数据库
    DATABASE_URL: str = ""  # 必须通过 .env 或环境变量设置

    # Redis（单实例模式）
    REDIS_URL: str = "redis://localhost:6379/0"

    # Redis Sentinel 高可用（非空时优先于 REDIS_URL）
    REDIS_SENTINEL_HOSTS: str = ""  # "host1:26379,host2:26379"
    REDIS_SENTINEL_SERVICE_NAME: str = "mymaster"
    REDIS_SENTINEL_SOCKET_TIMEOUT: float = 0.1

    # 消息队列
    RABBITMQ_URL: str = "amqp://localhost:5672"

    # 数据源API
    TUSHARE_TOKEN: str | None = None
    AKSHARE_ENABLED: bool = True

    # 数据源切换（tdx / tushare / akshare）
    QTS_DATA_SOURCE: str = "tushare"
    TDX_CONNECTOR_URL: str | None = None
    TDX_MCP_CMD: str | None = None

    # AI模型API密钥
    DEEPSEEK_API_KEY: str | None = None
    GLM_API_KEY: str | None = None
    KIMI_API_KEY: str | None = None
    MINIMAX_API_KEY: str | None = None

    # 飞书告警
    FEISHU_WEBHOOK: str | None = None

    # 风险控制参数
    MAX_POSITION_RATIO: float = 0.30  # 单只股票最大仓位
    MAX_TOTAL_POSITIONS: int = 3  # 最大持仓数量
    STOP_LOSS_RATIO: float = 0.08  # 止损比例
    TAKE_PROFIT_RATIO: float = 0.30  # 止盈比例
    MAX_DAILY_LOSS: float = 0.05  # 单日最大亏损

    # AI预算
    AI_BUDGET_TOTAL: float = 500.0  # 月预算（美元）

    # 执行服务联动
    EXECUTION_SERVICE_URL: str = "http://execution-service:8001"
    AUTO_EXECUTE_SIGNALS: bool = False  # Safety switch: True = auto-execute, False = notify only

    # 回测参数
    BACKTEST_START_DATE: str = "2019-01-01"
    BACKTEST_MIN_SHARPE: float = 1.5

    # K线数据缓存 TTL（秒，默认 86400 = 1天）
    CACHE_TTL_SECONDS: int = 86400

    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8")

    def validate_startup(self) -> bool:
        """启动时校验配置完整性。返回是否有校验失败项。"""
        import logging

        logger = logging.getLogger(__name__)
        errors = []

        # 数据库密码不能为空
        db_url = self.DATABASE_URL
        if "://" in db_url:
            creds = db_url.split("@")[0].split("://")[-1]
            if ":" in creds and creds.split(":")[1] == "":
                errors.append("DATABASE_URL: 密码为空")

        # AI 密钥（仅警告）
        ai_keys = [self.DEEPSEEK_API_KEY, self.GLM_API_KEY, self.KIMI_API_KEY, self.MINIMAX_API_KEY]
        if not any(ai_keys):
            logger.warning("AI模型: 未配置API密钥，AI功能将不可用")

        for err in errors:
            logger.error(f"配置校验失败: {err}")
        return len(errors) == 0


settings = Settings()
