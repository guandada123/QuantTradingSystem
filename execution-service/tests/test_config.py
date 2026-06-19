"""
配置管理测试 — 覆盖 core/config.py 全部配置项

测试策略：
- 验证默认值正确性
- 验证环境变量覆盖机制
- 验证类型正确性
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestConfigDefaults:
    """配置默认值测试"""

    @pytest.fixture(autouse=True)
    def _reset_to_defaults(self):
        """重置 Settings 到默认值，避免其他测试模块级代码的污染"""
        import importlib

        import core.config

        # 确保关键环境变量已清理后重载配置模块
        os.environ.pop("ALLOW_OFF_HOURS_TRADING", None)
        os.environ.pop("DATABASE_URL", None)  # 清理 conftest 设置的测试 DB
        importlib.reload(core.config)
        yield

    def test_app_defaults(self):
        """验证应用基本信息默认值"""
        import core.config

        settings = core.config.settings
        assert settings.APP_NAME == "QuantTradingSystem-Execution"
        assert settings.APP_VERSION == "1.0.0"
        assert settings.DEBUG is False

    def test_database_defaults(self):
        """验证数据库相关配置默认值（.env 会覆盖 postgres URL，不设时应为空）"""
        from core.config import settings

        # DATABASE_URL 已被 _reset_to_defaults 清理，.env 提供 postgres URL
        assert (
            settings.DATABASE_URL
            == "postgresql://quant_user:quant_pass@127.0.0.1:15432/quant_trading"
        )
        # RABBITMQ_URL: os.environ 和 .env 都没有 → 默认空字符串
        # 注意 .env 有 RABBITMQ_URL=amqp://localhost:5672，所以实际值来自 .env
        assert settings.RABBITMQ_URL == "amqp://localhost:5672"

    def test_miniqmt_defaults(self):
        """验证 MiniQMT 配置默认值（.env 中置空，表现同 None）"""
        from core.config import settings

        # .env 中 MINIQMT_USER= 和 MINIQMT_PASSWORD= 为空字符串
        assert settings.MINIQMT_USER == ""
        assert settings.MINIQMT_PASSWORD == ""

    def test_feishu_defaults(self):
        """验证飞书配置默认值（.env 提供 webhook URL）"""
        from core.config import settings

        # .env 配置了飞书 Webhook
        assert "feishu.cn" in settings.FEISHU_WEBHOOK

    def test_risk_params_defaults(self):
        """验证风控参数默认值"""
        from core.config import settings

        assert settings.MAX_POSITION_RATIO == 0.30
        assert settings.MAX_TOTAL_POSITIONS == 3
        assert settings.STOP_LOSS_RATIO == 0.08
        assert settings.TAKE_PROFIT_RATIO == 0.30
        assert settings.MAX_DAILY_LOSS == 0.05

    def test_auto_execute_defaults(self):
        """验证自动执行开关默认值（应开启）"""
        from core.config import settings

        assert settings.AUTO_EXECUTE_STOP_LOSS is True
        assert settings.AUTO_EXECUTE_TAKE_PROFIT is True

    def test_order_params_defaults(self):
        """验证订单相关配置默认值"""
        from core.config import settings

        assert settings.ORDER_EXPIRY_DAYS == 5
        assert settings.ALLOW_OFF_HOURS_TRADING is False

    def test_circuit_breaker_defaults(self):
        """验证熔断器参数默认值"""
        from core.config import settings

        assert settings.CB_CONSECUTIVE_LOSSES == 3
        assert settings.CB_COOLDOWN_MINUTES == 30

    def test_risk_params_are_positive(self):
        """验证风控参数均为合理的正数"""
        from core.config import settings

        assert 0 < settings.MAX_POSITION_RATIO <= 1.0
        assert settings.MAX_TOTAL_POSITIONS > 0
        assert 0 < settings.STOP_LOSS_RATIO < 1.0
        assert 0 < settings.TAKE_PROFIT_RATIO < 1.0
        assert 0 < settings.MAX_DAILY_LOSS < 1.0

    def test_order_expiry_is_positive(self):
        """验证订单过期天数至少为 1"""
        from core.config import settings

        assert settings.ORDER_EXPIRY_DAYS >= 1

    def test_cb_params_are_positive(self):
        """验证熔断参数为正数"""
        from core.config import settings

        assert settings.CB_CONSECUTIVE_LOSSES >= 1
        assert settings.CB_COOLDOWN_MINUTES >= 1


class TestConfigEnvOverride:
    """环境变量覆盖测试"""

    def test_env_override_string(self):
        """字符串型环境变量覆盖"""
        os.environ["APP_NAME"] = "Test-App"
        import importlib

        import core.config

        importlib.reload(core.config)
        assert core.config.settings.APP_NAME == "Test-App"
        del os.environ["APP_NAME"]
        importlib.reload(core.config)

    def test_env_override_int(self):
        """整型环境变量覆盖"""
        os.environ["MAX_TOTAL_POSITIONS"] = "10"
        import importlib

        import core.config

        importlib.reload(core.config)
        assert core.config.settings.MAX_TOTAL_POSITIONS == 10
        del os.environ["MAX_TOTAL_POSITIONS"]
        importlib.reload(core.config)

    def test_env_override_float(self):
        """浮点型环境变量覆盖"""
        os.environ["STOP_LOSS_RATIO"] = "0.15"
        import importlib

        import core.config

        importlib.reload(core.config)
        assert core.config.settings.STOP_LOSS_RATIO == 0.15
        del os.environ["STOP_LOSS_RATIO"]
        importlib.reload(core.config)

    def test_env_override_bool_true(self):
        """布尔型环境变量覆盖（True）"""
        os.environ["ALLOW_OFF_HOURS_TRADING"] = "true"
        import importlib

        import core.config

        importlib.reload(core.config)
        assert core.config.settings.ALLOW_OFF_HOURS_TRADING is True
        del os.environ["ALLOW_OFF_HOURS_TRADING"]
        importlib.reload(core.config)

    def test_env_override_database_url(self):
        """DATABASE_URL 环境变量"""
        saved = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"
        import importlib

        import core.config

        importlib.reload(core.config)
        assert core.config.settings.DATABASE_URL == "postgresql://test:test@localhost/test"
        if saved is not None:
            os.environ["DATABASE_URL"] = saved
        else:
            os.environ.pop("DATABASE_URL", None)
        importlib.reload(core.config)

    def test_env_override_multiple(self):
        """多环境变量同时覆盖"""
        os.environ["MAX_POSITION_RATIO"] = "0.5"
        os.environ["MAX_TOTAL_POSITIONS"] = "5"
        os.environ["MAX_DAILY_LOSS"] = "0.1"
        import importlib

        import core.config

        importlib.reload(core.config)
        assert core.config.settings.MAX_POSITION_RATIO == 0.5
        assert core.config.settings.MAX_TOTAL_POSITIONS == 5
        assert core.config.settings.MAX_DAILY_LOSS == 0.1
        del os.environ["MAX_POSITION_RATIO"]
        del os.environ["MAX_TOTAL_POSITIONS"]
        del os.environ["MAX_DAILY_LOSS"]
        importlib.reload(core.config)

    def test_env_override_disable_auto_execute(self):
        """禁用自动执行开关"""
        os.environ["AUTO_EXECUTE_STOP_LOSS"] = "false"
        import importlib

        import core.config

        importlib.reload(core.config)
        assert core.config.settings.AUTO_EXECUTE_STOP_LOSS is False
        del os.environ["AUTO_EXECUTE_STOP_LOSS"]
        importlib.reload(core.config)

    def test_env_override_cb_params(self):
        """熔断器参数环境变量覆盖"""
        os.environ["CB_CONSECUTIVE_LOSSES"] = "5"
        os.environ["CB_COOLDOWN_MINUTES"] = "60"
        import importlib

        import core.config

        importlib.reload(core.config)
        assert core.config.settings.CB_CONSECUTIVE_LOSSES == 5
        assert core.config.settings.CB_COOLDOWN_MINUTES == 60
        del os.environ["CB_CONSECUTIVE_LOSSES"]
        del os.environ["CB_COOLDOWN_MINUTES"]
        importlib.reload(core.config)
