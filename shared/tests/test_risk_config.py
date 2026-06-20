"""shared/risk_config.py 单元测试 — 风控配置数据类"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os

import pytest

from shared.risk_config import DEFAULT_RISK_CONFIG, RiskConfig

# ============================================================
#  env helper 函数测试
# ============================================================
# _env_float / _env_int / _env_bool 是私有的，
# 但可以通过 RiskConfig dataclass 的 default_factory 间接测试。


class TestRiskConfigDefaults:
    """不设置环境变量时的默认值"""

    def test_max_position_ratio_default(self):
        config = RiskConfig()
        assert config.max_position_ratio == 0.30

    def test_max_total_positions_default(self):
        config = RiskConfig()
        assert config.max_total_positions == 3

    def test_stop_loss_ratio_default(self):
        config = RiskConfig()
        assert config.stop_loss_ratio == 0.08

    def test_take_profit_ratio_default(self):
        config = RiskConfig()
        assert config.take_profit_ratio == 0.30

    def test_max_daily_loss_default(self):
        config = RiskConfig()
        assert config.max_daily_loss == 0.05

    def test_cb_consecutive_losses_default(self):
        config = RiskConfig()
        assert config.cb_consecutive_losses == 3

    def test_cb_cooldown_minutes_default(self):
        config = RiskConfig()
        assert config.cb_cooldown_minutes == 30

    def test_auto_execute_stop_loss_default(self):
        config = RiskConfig()
        assert config.auto_execute_stop_loss is True

    def test_auto_execute_take_profit_default(self):
        config = RiskConfig()
        assert config.auto_execute_take_profit is True

    def test_auto_execute_signals_default(self):
        config = RiskConfig()
        assert config.auto_execute_signals is False

    def test_order_expiry_days_default(self):
        config = RiskConfig()
        assert config.order_expiry_days == 5

    def test_allow_off_hours_trading_default(self):
        config = RiskConfig()
        assert config.allow_off_hours_trading is False


class TestRiskConfigEnvOverrides:
    """通过环境变量覆盖默认值"""

    ENV_MAP = {
        "QTS_MAX_POSITION_RATIO": ("QTS_MAX_POSITION_RATIO", "max_position_ratio", "0.50", 0.50),
        "QTS_MAX_TOTAL_POSITIONS": ("QTS_MAX_TOTAL_POSITIONS", "max_total_positions", "10", 10),
        "QTS_STOP_LOSS_RATIO": ("QTS_STOP_LOSS_RATIO", "stop_loss_ratio", "0.05", 0.05),
        "QTS_TAKE_PROFIT_RATIO": ("QTS_TAKE_PROFIT_RATIO", "take_profit_ratio", "0.15", 0.15),
        "QTS_MAX_DAILY_LOSS": ("QTS_MAX_DAILY_LOSS", "max_daily_loss", "0.03", 0.03),
        "QTS_CB_CONSECUTIVE_LOSSES": ("QTS_CB_CONSECUTIVE_LOSSES", "cb_consecutive_losses", "5", 5),
        "QTS_CB_COOLDOWN_MINUTES": ("QTS_CB_COOLDOWN_MINUTES", "cb_cooldown_minutes", "60", 60),
        "QTS_AUTO_EXECUTE_STOP_LOSS": (
            "QTS_AUTO_EXECUTE_STOP_LOSS",
            "auto_execute_stop_loss",
            "false",
            False,
        ),
        "QTS_AUTO_EXECUTE_TAKE_PROFIT": (
            "QTS_AUTO_EXECUTE_TAKE_PROFIT",
            "auto_execute_take_profit",
            "0",
            False,
        ),
        "QTS_AUTO_EXECUTE_SIGNALS": (
            "QTS_AUTO_EXECUTE_SIGNALS",
            "auto_execute_signals",
            "true",
            True,
        ),
        "QTS_ORDER_EXPIRY_DAYS": ("QTS_ORDER_EXPIRY_DAYS", "order_expiry_days", "3", 3),
        "QTS_ALLOW_OFF_HOURS_TRADING": (
            "QTS_ALLOW_OFF_HOURS_TRADING",
            "allow_off_hours_trading",
            "1",
            True,
        ),
    }

    @pytest.mark.parametrize("env_key,attr,env_val,expected", ENV_MAP.values(), ids=ENV_MAP.keys())
    def test_single_env_override(self, monkeypatch, env_key, attr, env_val, expected):
        monkeypatch.setenv(env_key, env_val)
        config = RiskConfig()
        assert getattr(config, attr) == expected


class TestRiskConfigConstructorOverrides:
    """通过构造函数参数覆盖默认值"""

    def test_constructor_override_position_ratio(self):
        config = RiskConfig(max_position_ratio=0.15)
        assert config.max_position_ratio == 0.15

    def test_constructor_override_stop_loss(self):
        config = RiskConfig(stop_loss_ratio=0.05)
        assert config.stop_loss_ratio == 0.05

    def test_constructor_override_auto_execute(self):
        config = RiskConfig(auto_execute_signals=True)
        assert config.auto_execute_signals is True


class TestRiskConfigEnvEdgeCases:
    """环境变量边界情况"""

    def test_invalid_float_falls_back(self, monkeypatch):
        monkeypatch.setenv("QTS_MAX_POSITION_RATIO", "not_a_number")
        config = RiskConfig()
        assert config.max_position_ratio == 0.30  # fallback to default

    def test_invalid_int_falls_back(self, monkeypatch):
        monkeypatch.setenv("QTS_MAX_TOTAL_POSITIONS", "abc")
        config = RiskConfig()
        assert config.max_total_positions == 3  # fallback to default

    def test_invalid_bool_falls_back_to_false(self, monkeypatch):
        """非 True 字符串按 False 处理"""
        monkeypatch.setenv("QTS_AUTO_EXECUTE_STOP_LOSS", "random_string")
        config = RiskConfig()
        # "random_string" lower() 不在 ("1", "true", "yes", "on")
        assert config.auto_execute_stop_loss is False

    def test_empty_env_var_falls_back(self, monkeypatch):
        monkeypatch.setenv("QTS_MAX_POSITION_RATIO", "")
        config = RiskConfig()
        # float("") raises ValueError → fallback to default
        assert config.max_position_ratio == 0.30


class TestRiskConfigToDict:
    """to_dict() 导出测试"""

    def test_to_dict_keys_uppercase(self):
        config = RiskConfig()
        d = config.to_dict()
        assert d["MAX_POSITION_RATIO"] == 0.30
        assert d["MAX_TOTAL_POSITIONS"] == 3
        assert d["STOP_LOSS_RATIO"] == 0.08
        assert d["TAKE_PROFIT_RATIO"] == 0.30
        assert d["MAX_DAILY_LOSS"] == 0.05
        assert d["CB_CONSECUTIVE_LOSSES"] == 3
        assert d["CB_COOLDOWN_MINUTES"] == 30
        assert d["AUTO_EXECUTE_STOP_LOSS"] is True
        assert d["AUTO_EXECUTE_TAKE_PROFIT"] is True
        assert d["AUTO_EXECUTE_SIGNALS"] is False
        assert d["ORDER_EXPIRY_DAYS"] == 5
        assert d["ALLOW_OFF_HOURS_TRADING"] is False

    def test_to_dict_after_override(self, monkeypatch):
        monkeypatch.setenv("QTS_MAX_POSITION_RATIO", "0.60")
        monkeypatch.setenv("QTS_AUTO_EXECUTE_SIGNALS", "true")
        config = RiskConfig()
        d = config.to_dict()
        assert d["MAX_POSITION_RATIO"] == 0.60
        assert d["AUTO_EXECUTE_SIGNALS"] is True

    def test_to_dict_all_keys_present(self):
        config = RiskConfig()
        d = config.to_dict()
        assert len(d) == 12
        expected_keys = {
            "MAX_POSITION_RATIO",
            "MAX_TOTAL_POSITIONS",
            "STOP_LOSS_RATIO",
            "TAKE_PROFIT_RATIO",
            "MAX_DAILY_LOSS",
            "CB_CONSECUTIVE_LOSSES",
            "CB_COOLDOWN_MINUTES",
            "AUTO_EXECUTE_STOP_LOSS",
            "AUTO_EXECUTE_TAKE_PROFIT",
            "AUTO_EXECUTE_SIGNALS",
            "ORDER_EXPIRY_DAYS",
            "ALLOW_OFF_HOURS_TRADING",
        }
        assert set(d.keys()) == expected_keys


class TestDEFAULT_RISK_CONFIG:  # noqa: N801
    """全局默认实例"""

    def test_default_is_risk_config_instance(self):
        assert isinstance(DEFAULT_RISK_CONFIG, RiskConfig)

    def test_default_has_default_values(self):
        assert DEFAULT_RISK_CONFIG.max_position_ratio == 0.30
        assert DEFAULT_RISK_CONFIG.max_total_positions == 3
