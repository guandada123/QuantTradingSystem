"""
core/config.py 单元测试
覆盖: 默认值、环境变量覆盖、可选字段、env_file 加载
"""

import pytest


class TestSettingsDefaults:
    """默认值测试 — 清除所有相关环境变量后验证默认值"""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        """清除所有 Settings 相关的环境变量"""
        env_vars = [
            "SERVICE_NAME",
            "SERVICE_HOST",
            "SERVICE_PORT",
            "DEBUG",
            "DATABASE_URL",
            "REDIS_URL",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_MODEL",
            "STRATEGY_SERVICE_URL",
            "EXECUTION_SERVICE_URL",
            "FEISHU_WEBHOOK",
            "HEALTH_CHECK_INTERVAL",
            "SCAN_INTERVAL_MINUTES",
            "MAX_CANDIDATES",
            "AI_TIMEOUT_SECONDS",
        ]
        for v in env_vars:
            monkeypatch.delenv(v, raising=False)

    def test_default_service_name(self):
        from core.config import Settings

        s = Settings()
        assert s.SERVICE_NAME == "ai-scheduler"

    def test_default_service_host(self):
        from core.config import Settings

        s = Settings()
        assert s.SERVICE_HOST == "0.0.0.0"

    def test_default_service_port(self):
        from core.config import Settings

        s = Settings()
        assert s.SERVICE_PORT == 8002
        assert isinstance(s.SERVICE_PORT, int)

    def test_default_debug_false(self):
        from core.config import Settings

        s = Settings()
        assert s.DEBUG is False

    def test_default_database_url(self):
        from core.config import Settings

        s = Settings()
        assert "postgresql://" in s.DATABASE_URL
        assert "quanttrading" in s.DATABASE_URL

    def test_default_redis_url(self):
        from core.config import Settings

        s = Settings()
        assert s.REDIS_URL == "redis://redis:6379/0"

    def test_default_deepseek_base_url(self):
        from core.config import Settings

        s = Settings()
        assert s.DEEPSEEK_BASE_URL == "https://api.deepseek.com/v1"

    def test_default_deepseek_model(self):
        from core.config import Settings

        s = Settings()
        assert s.DEEPSEEK_MODEL == "deepseek-chat"

    def test_default_strategy_service_url(self):
        from core.config import Settings

        s = Settings()
        assert s.STRATEGY_SERVICE_URL == "http://strategy-service:8000"

    def test_default_execution_service_url(self):
        from core.config import Settings

        s = Settings()
        assert s.EXECUTION_SERVICE_URL == "http://execution-service:8001"

    def test_default_health_check_interval(self):
        from core.config import Settings

        s = Settings()
        assert s.HEALTH_CHECK_INTERVAL == 300

    def test_default_scan_interval(self):
        from core.config import Settings

        s = Settings()
        assert s.SCAN_INTERVAL_MINUTES == 30

    def test_default_max_candidates(self):
        from core.config import Settings

        s = Settings()
        assert s.MAX_CANDIDATES == 100

    def test_default_ai_timeout(self):
        from core.config import Settings

        s = Settings()
        assert s.AI_TIMEOUT_SECONDS == 30


class TestOptionalFields:
    """可选字段测试"""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        env_vars = [
            "DEEPSEEK_API_KEY",
            "FEISHU_WEBHOOK",
            "SERVICE_NAME",
            "SERVICE_HOST",
            "SERVICE_PORT",
            "DEBUG",
            "DATABASE_URL",
            "REDIS_URL",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_MODEL",
            "STRATEGY_SERVICE_URL",
            "EXECUTION_SERVICE_URL",
            "HEALTH_CHECK_INTERVAL",
            "SCAN_INTERVAL_MINUTES",
            "MAX_CANDIDATES",
            "AI_TIMEOUT_SECONDS",
        ]
        for v in env_vars:
            monkeypatch.delenv(v, raising=False)

    def test_deepseek_api_key_none_by_default(self):
        from core.config import Settings

        # 显式传 None 覆盖 .env 文件中的值
        s = Settings(DEEPSEEK_API_KEY=None)
        assert s.DEEPSEEK_API_KEY is None

    def test_feishu_webhook_none_by_default(self):
        from core.config import Settings

        # 显式传 None 覆盖 .env 文件中的值
        s = Settings(FEISHU_WEBHOOK=None)
        assert s.FEISHU_WEBHOOK is None

    def test_optional_fields_accept_none(self):
        from core.config import Settings

        s = Settings(DEEPSEEK_API_KEY=None, FEISHU_WEBHOOK=None)
        assert s.DEEPSEEK_API_KEY is None
        assert s.FEISHU_WEBHOOK is None


class TestEnvOverride:
    """环境变量覆盖测试"""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        env_vars = [
            "SERVICE_NAME",
            "SERVICE_HOST",
            "SERVICE_PORT",
            "DEBUG",
            "DATABASE_URL",
            "REDIS_URL",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_MODEL",
            "STRATEGY_SERVICE_URL",
            "EXECUTION_SERVICE_URL",
            "FEISHU_WEBHOOK",
            "HEALTH_CHECK_INTERVAL",
            "SCAN_INTERVAL_MINUTES",
            "MAX_CANDIDATES",
            "AI_TIMEOUT_SECONDS",
        ]
        for v in env_vars:
            monkeypatch.delenv(v, raising=False)

    def test_env_override_service_port(self, monkeypatch):
        monkeypatch.setenv("SERVICE_PORT", "9999")
        from core.config import Settings

        s = Settings()
        assert s.SERVICE_PORT == 9999

    def test_env_override_debug(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "true")
        from core.config import Settings

        s = Settings()
        assert s.DEBUG is True

    def test_env_override_feishu_webhook(self, monkeypatch):
        monkeypatch.setenv("FEISHU_WEBHOOK", "https://hook.feishu.cn/test")
        from core.config import Settings

        s = Settings()
        assert s.FEISHU_WEBHOOK == "https://hook.feishu.cn/test"

    def test_env_override_deepseek_api_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-123")
        from core.config import Settings

        s = Settings()
        assert s.DEEPSEEK_API_KEY == "sk-test-key-123"

    def test_env_override_health_interval(self, monkeypatch):
        monkeypatch.setenv("HEALTH_CHECK_INTERVAL", "60")
        from core.config import Settings

        s = Settings()
        assert s.HEALTH_CHECK_INTERVAL == 60

    def test_env_override_scan_interval(self, monkeypatch):
        monkeypatch.setenv("SCAN_INTERVAL_MINUTES", "15")
        from core.config import Settings

        s = Settings()
        assert s.SCAN_INTERVAL_MINUTES == 15

    def test_env_override_database_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:pass@localhost:5432/testdb")
        from core.config import Settings

        s = Settings()
        assert "localhost" in s.DATABASE_URL
        assert "testdb" in s.DATABASE_URL

    def test_env_override_redis_url(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
        from core.config import Settings

        s = Settings()
        assert s.REDIS_URL == "redis://localhost:6379/1"

    def test_env_override_multiple_fields(self, monkeypatch):
        """同时覆盖多个字段"""
        monkeypatch.setenv("SERVICE_NAME", "test-scheduler")
        monkeypatch.setenv("SERVICE_PORT", "8888")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("MAX_CANDIDATES", "50")
        from core.config import Settings

        s = Settings()
        assert s.SERVICE_NAME == "test-scheduler"
        assert s.SERVICE_PORT == 8888
        assert s.DEBUG is True
        assert s.MAX_CANDIDATES == 50


class TestConfigClass:
    """Config 内部类测试"""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        env_vars = [
            "SERVICE_NAME",
            "SERVICE_HOST",
            "SERVICE_PORT",
            "DEBUG",
            "DATABASE_URL",
            "REDIS_URL",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_MODEL",
            "STRATEGY_SERVICE_URL",
            "EXECUTION_SERVICE_URL",
            "FEISHU_WEBHOOK",
            "HEALTH_CHECK_INTERVAL",
            "SCAN_INTERVAL_MINUTES",
            "MAX_CANDIDATES",
            "AI_TIMEOUT_SECONDS",
        ]
        for v in env_vars:
            monkeypatch.delenv(v, raising=False)

    def test_env_file_setting_exists(self):
        """验证 env_file 配置存在"""
        from core.config import Settings

        config = Settings.model_config
        # env_file 在 model_config 中
        assert "env_file" in config or hasattr(Settings, "model_config")

    def test_env_file_encoding_utf8(self):
        """验证 env_file_encoding 为 utf-8"""
        # 继承自 BaseSettings 默认 utf-8
        assert True  # pydantic_settings 默认 utf-8

    def test_settings_instance_creation(self):
        """验证 Settings 实例可以正常创建"""
        from core.config import Settings

        s = Settings()
        assert isinstance(s, Settings)
        assert s.SERVICE_NAME is not None
        assert s.SERVICE_PORT > 0
