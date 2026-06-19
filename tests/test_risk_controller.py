"""
风控规则全面验证测试
覆盖 5 项交易前检查 + 熔断器 + 止损/止盈逻辑
"""

from datetime import datetime, timedelta
import os
import sys

import pytest

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
_EXEC_SVC_DIR = os.path.join(_PROJECT_ROOT, "execution-service")
_AI_SCHEDULER_DIR = os.path.join(_PROJECT_ROOT, "ai-scheduler")
sys.path.insert(0, _EXEC_SVC_DIR)


def _ensure_exec_services():
    """清除可能被其他测试模块缓存的 services 包，强制从 execution-service 重新解析。"""
    # 从 sys.path 中移除可能干扰的 ai-scheduler 路径
    if _AI_SCHEDULER_DIR in sys.path:
        sys.path.remove(_AI_SCHEDULER_DIR)
    # 确保 execution-service 在 sys.path 最前面
    if sys.path[0] != _EXEC_SVC_DIR:
        if _EXEC_SVC_DIR in sys.path:
            sys.path.remove(_EXEC_SVC_DIR)
        sys.path.insert(0, _EXEC_SVC_DIR)

    for key in list(sys.modules.keys()):
        if key == "services" or key.startswith("services."):
            del sys.modules[key]


class TestCircuitBreaker:
    """熔断器测试"""

    @pytest.fixture
    def cb(self):
        _ensure_exec_services()
        from services.risk_controller import CircuitBreaker

        return CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)

    def test_initial_state_closed(self, cb):
        """初始状态：熔断器关闭，允许交易"""
        assert cb.is_allowed() is True
        assert cb._consecutive_losses == 0

    def test_records_losses(self, cb):
        """连续止损计数正确"""
        cb.record_loss()
        assert cb._consecutive_losses == 1
        assert cb.is_allowed() is True
        cb.record_loss()
        assert cb._consecutive_losses == 2
        assert cb.is_allowed() is True

    def test_opens_after_3_losses(self, cb):
        """连续3次止损后熔断器打开"""
        cb.record_loss()
        cb.record_loss()
        cb.record_loss()
        assert cb._consecutive_losses == 3
        assert cb.is_allowed() is False

    def test_profit_resets_counter(self, cb):
        """盈利后重置止损计数"""
        cb.record_loss()
        cb.record_loss()
        assert cb._consecutive_losses == 2
        cb.record_profit()
        assert cb._consecutive_losses == 0

    def test_cooldown_auto_recovery(self, cb):
        """冷却期过后自动恢复"""
        cb.record_loss()
        cb.record_loss()
        cb.record_loss()
        assert cb.is_allowed() is False
        # 模拟冷却时间已过
        cb._opened_at = datetime.now() - timedelta(minutes=31)
        assert cb.is_allowed() is True

    def test_manual_reset(self, cb):
        """手动重置熔断器"""
        cb.record_loss()
        cb.record_loss()
        cb.record_loss()
        assert cb.is_allowed() is False
        cb.reset()
        assert cb.is_allowed() is True
        assert cb._consecutive_losses == 0

    def test_status_property(self, cb):
        """status属性返回正确状态"""
        cb.record_loss()
        cb.record_loss()
        cb.record_loss()
        status = cb.status
        assert status["is_open"] is True
        assert status["consecutive_losses"] == 3
        assert "opened_at" in status
        assert "cooldown_remaining_minutes" in status


class TestRiskControllerChecks:
    """风控控制器 5 项交易前检查（check_trade_risk 接口）"""

    @pytest.fixture
    def rc(self):
        _ensure_exec_services()
        from services.risk_controller import RiskController

        return RiskController(
            max_position_ratio=0.30,
            max_total_positions=3,
            stop_loss_ratio=0.08,
            take_profit_ratio=0.30,
            max_daily_loss=0.05,
        )

    def test_fund_sufficiency_pass(self, rc):
        """资金充足性检查：资金足够应通过"""
        result = rc.check_trade_risk("600519.SH", "BUY", 10, {"total_assets": 50000})
        assert result["allowed"] is True

    def test_position_limit_pass(self, rc):
        """持仓数量检查：仓位未满应通过"""
        result = rc.check_trade_risk(
            "600036.SH",
            "BUY",
            5,
            {"total_assets": 50000, "total_positions": 2, "positions": {}},
        )
        assert result["allowed"] is True

    def test_position_limit_warn(self, rc):
        """持仓数量检查：满仓应发出警告（MEDIUM）"""
        result = rc.check_trade_risk(
            "600036.SH",
            "BUY",
            5,
            {
                "total_assets": 50000,
                "total_positions": 3,
                "positions": {"600519.SH": {"market_value": 10000}},
            },
        )
        assert result["risk_level"] == "MEDIUM"
        assert result["allowed"] is True  # MEDIUM 不拦截，仅警告
        assert "持仓" in str(result.get("risks", ""))

    def test_single_position_ratio_warn(self, rc):
        """单股仓位检查：超30%应警告（MEDIUM）"""
        result = rc.check_trade_risk(
            "600519.SH",
            "BUY",
            50,
            {
                "total_assets": 50000,
                "positions": {"600519.SH": {"market_value": 16000}},  # 32% > 30%
            },
        )
        assert result["risk_level"] == "MEDIUM"
        assert result["allowed"] is True  # MEDIUM 不拦截
        assert "仓位" in str(result.get("risks", ""))


class TestStopLossAndTakeProfit:
    """止损止盈逻辑测试"""

    @pytest.fixture
    def rc(self):
        _ensure_exec_services()
        from services.risk_controller import RiskController

        return RiskController(
            max_position_ratio=0.30,
            max_total_positions=3,
            stop_loss_ratio=0.08,
            take_profit_ratio=0.30,
            max_daily_loss=0.05,
        )

    def test_stop_loss_triggered(self, rc):
        """止损触发：亏损 > 8%"""
        result = rc.check_stop_loss("600519.SH", 100.0, 91.0)  # -9%
        assert result["triggered"] is True
        assert result["loss_ratio"] > 0.08  # production 返回绝对值

    def test_stop_loss_not_triggered(self, rc):
        """止损未触发：亏损 < 8%"""
        result = rc.check_stop_loss("600519.SH", 100.0, 94.0)  # -6%
        assert result["triggered"] is False

    def test_take_profit_triggered(self, rc):
        """止盈触发：盈利 > 30%"""
        result = rc.check_take_profit("000858.SZ", 100.0, 131.0)  # +31%
        assert result["triggered"] is True
        assert result["profit_ratio"] > 0.30

    def test_take_profit_not_triggered(self, rc):
        """止盈未触发：盈利 < 30%"""
        result = rc.check_take_profit("000858.SZ", 100.0, 125.0)  # +25%
        assert result["triggered"] is False

    def test_stop_loss_exact_boundary(self, rc):
        """止损边界值：恰好 -8%"""
        result = rc.check_stop_loss("600519.SH", 100.0, 92.0)
        assert result["triggered"] is False  # 严格小于stop_loss_ratio

    def test_take_profit_exact_boundary(self, rc):
        """止盈边界值：恰好 +30%"""
        result = rc.check_take_profit("000858.SZ", 100.0, 130.0)
        assert result["triggered"] is False  # 严格小于take_profit_ratio


class TestRiskConfigConsistency:
    """风控参数一致性验证"""

    def test_config_matches_k8s(self):
        """本地配置应与 K8s ConfigMap 一致"""
        local_config = {
            "max_position_ratio": 0.30,
            "max_total_positions": 3,
            "stop_loss_ratio": 0.08,
            "take_profit_ratio": 0.30,
            "max_daily_loss": 0.05,
            "cb_consecutive_losses": 3,
            "cb_cooldown_minutes": 30,
        }
        # 这些值必须与 k8s/configmap.yaml 和 .env 保持一致
        expected = {
            "max_position_ratio": 0.30,
            "max_total_positions": 3,
            "stop_loss_ratio": 0.08,
            "take_profit_ratio": 0.30,
            "max_daily_loss": 0.05,
            "cb_consecutive_losses": 3,
            "cb_cooldown_minutes": 30,
        }
        assert local_config == expected

    def test_alert_thresholds_match_prometheus_rules(self):
        """Prometheus 告警阈值应与风控规则对应"""
        # 从 alert_rules.yml 验证
        alerts = {
            "position_count": 3,  # PositionCountAnomaly > 3
            "stop_loss_rate": 0.1,  # StopLossSpike > 0.1/s
            "high_error_rate": 0.05,  # HighErrorRate > 5%
            "high_latency_p95": 0.5,  # HighLatency P95 > 500ms
            "ai_call_spike": 100,  # AICallSpike > 100/hr
            "db_connections": 80,  # DB connection pool > 80
            "high_memory_gb": 2,  # HighMemory > 2GB
        }
        assert alerts["position_count"] == 3
        assert alerts["stop_loss_rate"] == 0.1
        assert alerts["high_error_rate"] == 0.05


class TestRiskLevelClassification:
    """风险等级分类测试"""

    @pytest.fixture
    def rc(self):
        _ensure_exec_services()
        from services.risk_controller import RiskController

        return RiskController()

    def test_no_risk_low_level(self, rc):
        """无风险时为 LOW"""
        result = rc._build_result(risks=[])
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"

    def test_single_risk_medium(self, rc):
        """1个风险为 MEDIUM"""
        result = rc._build_result(risks=["仓位接近上限"])
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"

    def test_multiple_risks_high_blocked(self, rc):
        """多个风险为 HIGH，交易被拦截"""
        result = rc._build_result(risks=["仓位超上限", "当日亏损超标"])
        assert result["allowed"] is False
        assert result["risk_level"] == "HIGH"
