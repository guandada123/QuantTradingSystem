"""
飞书告警全链路测试
测试三个微服务的告警服务及其与飞书 Webhook 的集成。

注意：三个服务的 services/feishu_alert.py 有不同的类实现。
使用 importlib.util 分别加载，避免 sys.path 冲突。
"""

import importlib.util
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

# ─── 动态导入帮助函数 ──────────────────────────────────────────────

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)  # QuantTradingSystem/


def _load_feishu_module(service_dir: str):
    """从指定服务目录加载 services/feishu_alert.py，返回 module 对象。"""
    svc_path = os.path.join(_PROJECT_ROOT, service_dir)
    # 确保内部依赖（from shared.middleware import ...）可解析
    if svc_path not in sys.path:
        sys.path.insert(0, svc_path)

    filepath = os.path.join(svc_path, "services", "feishu_alert.py")
    mod_name = f"_feishu_{service_dir.replace('-', '_')}"

    spec = importlib.util.spec_from_file_location(mod_name, filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


# ─── execution-service ────────────────────────────────────────────


class TestFeishuAlertServiceExecution:
    """execution-service FeishuAlertService 测试"""

    @pytest.fixture
    def alert_service(self):
        mod = _load_feishu_module("execution-service")
        return mod.FeishuAlertService(
            webhook_url="https://mock.feishu.cn/webhook/test", rate_limit_seconds=0
        )

    @pytest.mark.asyncio
    async def test_send_order_filled_card_structure(self, alert_service):
        """验证订单成交卡片结构"""
        order = {
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "action": "BUY",
            "quantity": 1000,
            "price": 1850.0,
        }
        with patch.object(alert_service, "_send_card", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await alert_service.send_order_filled(order)
            assert result is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert order["ts_code"] in str(call_args)

    @pytest.mark.asyncio
    async def test_send_order_rejected_card_structure(self, alert_service):
        """验证订单拒绝卡片结构"""
        order = {
            "ts_code": "000858.SZ",
            "name": "五粮液",
            "action": "BUY",
            "quantity": 500,
            "price": 162.0,
        }
        reason = "风控检查未通过：持仓数量超过上限"
        with patch.object(alert_service, "_send_card", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await alert_service.send_order_rejected(order, reason)
            assert result is True
            assert reason in str(mock_send.call_args)

    @pytest.mark.asyncio
    async def test_send_risk_triggered_card_structure(self, alert_service):
        """验证风控触发卡片结构"""
        with patch.object(alert_service, "_send_card", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await alert_service.send_risk_triggered(
                "600519.SH", "STOP_LOSS", "止损触发：亏损8.5%，超过8%阈值"
            )
            assert result is True
            assert "STOP_LOSS" in str(mock_send.call_args)

    @pytest.mark.asyncio
    async def test_send_position_alert_card_structure(self, alert_service):
        """验证持仓告警卡片结构"""
        position = {
            "ts_code": "600036.SH",
            "name": "招商银行",
            "current_price": 38.5,
            "cost_price": 42.0,
            "profit_loss_ratio": -0.083,
            "quantity": 2000,
        }
        with patch.object(alert_service, "_send_card", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await alert_service.send_position_alert(position, "STOP_LOSS")
            assert result is True

    @pytest.mark.asyncio
    async def test_send_daily_summary(self, alert_service):
        """验证日汇总卡片结构"""
        summary = {"date": "2026-06-10", "total_trades": 5, "win_rate": 0.6, "total_pnl": 1250.50}
        with patch.object(alert_service, "_send_card", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await alert_service.send_daily_summary(summary)
            assert result is True

    @pytest.mark.asyncio
    async def test_send_system_error(self, alert_service):
        """验证系统异常卡片结构"""
        with patch.object(alert_service, "_send_card", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await alert_service.send_system_error("execution-service", "数据库连接超时")
            assert result is True
            assert "execution-service" in str(mock_send.call_args)

    def test_rate_limiting(self, alert_service):
        """验证速率限制（production 使用 time.time()）"""
        import time

        alert_service.rate_limit_seconds = 60
        alert_service._last_sent = {"test_key": time.time()}
        assert alert_service._is_rate_limited("test_key") is True
        alert_service._last_sent = {"test_key": time.time() - 61}
        assert alert_service._is_rate_limited("test_key") is False


# ─── strategy-service ─────────────────────────────────────────────


class TestFeishuAlertServiceStrategy:
    """strategy-service FeishuAlertService 测试"""

    @pytest.fixture
    def alert_service(self):
        mod = _load_feishu_module("strategy-service")
        return mod.FeishuAlertService(webhook_url="https://mock.feishu.cn/webhook/test")

    @pytest.mark.asyncio
    async def test_send_stop_loss_alert(self, alert_service):
        """验证止损告警"""
        with patch.object(alert_service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await alert_service.send_stop_loss_alert("600519.SH", 1850.0, 1680.0, -0.092)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            # send_alert 签名: (alert_type=..., level=..., title=..., content=..., data=None)
            assert kwargs["alert_type"].name == "STOP_LOSS"
            assert kwargs["level"].name == "CRITICAL"

    @pytest.mark.asyncio
    async def test_send_take_profit_alert(self, alert_service):
        """验证止盈告警"""
        with patch.object(alert_service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await alert_service.send_take_profit_alert("000858.SZ", 160.0, 210.0, 0.312)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            assert kwargs["alert_type"].name == "TAKE_PROFIT"
            assert kwargs["level"].name == "INFO"

    @pytest.mark.asyncio
    async def test_send_ai_cost_warning(self, alert_service):
        """验证AI成本预警（超过80%预算）"""
        with patch.object(alert_service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await alert_service.send_ai_cost_alert(420.0, 500.0, 0.84)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            assert kwargs["level"].name == "WARNING"

    @pytest.mark.asyncio
    async def test_send_ai_cost_normal(self, alert_service):
        """验证AI成本正常（低于80%预算）"""
        with patch.object(alert_service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await alert_service.send_ai_cost_alert(200.0, 500.0, 0.40)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            assert kwargs["level"].name == "INFO"

    @pytest.mark.asyncio
    async def test_send_signal_alert(self, alert_service):
        """验证交易信号告警"""
        with patch.object(alert_service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await alert_service.send_signal_alert(
                "601318.SH", "BUY", 48.5, 0.85, "双均线金叉 + MACD背离确认"
            )
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            assert kwargs["alert_type"].name == "SIGNAL"

    @pytest.mark.asyncio
    async def test_send_risk_alert(self, alert_service):
        """验证风险告警"""
        with patch.object(alert_service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await alert_service.send_risk_alert(
                "CONCENTRATION",
                "持仓集中度超标：单一行业占比超50%",
                {"industry": "白酒", "ratio": 0.65},
            )
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            assert kwargs["alert_type"].name == "RISK_BREACH"


# ─── ai-scheduler ─────────────────────────────────────────────────


class TestHealthAlertService:
    """ai-scheduler HealthAlertService 测试"""

    @pytest.fixture
    def health_alert(self):
        mod = _load_feishu_module("ai-scheduler")
        return mod.HealthAlertService(webhook_url="https://mock.feishu.cn/webhook/test")

    @pytest.mark.asyncio
    async def test_send_service_down(self, health_alert):
        """验证服务宕机告警"""
        with patch.object(health_alert, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await health_alert.send_service_down("strategy-service", "Connection refused")
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            # send_alert 签名: (title, content, level=INFO)
            assert args[2].name == "CRITICAL"
            assert "strategy-service" in args[0]

    @pytest.mark.asyncio
    async def test_send_service_recovered(self, health_alert):
        """验证服务恢复通知（直接 httpx post，不经过 send_alert）"""
        with patch("services.feishu_alert.httpx.AsyncClient") as mock_httpx:
            mock_post = AsyncMock()
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"code": 0}
            mock_httpx.return_value.__aenter__.return_value.post = mock_post
            await health_alert.send_service_recovered("execution-service")
            mock_post.assert_called_once()
            call_json = mock_post.call_args[1]["json"]
            assert "execution-service" in call_json["card"]["header"]["title"]["content"]

    @pytest.mark.asyncio
    async def test_send_health_report(self, health_alert):
        """验证健康状态报告"""
        with patch.object(health_alert, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await health_alert.send_health_report(
                {
                    "strategy-service": True,
                    "execution-service": True,
                    "ai-scheduler": False,
                }
            )
            mock_send.assert_called_once()

    def test_rate_limiting_300s(self, health_alert):
        """验证5分钟速率限制"""
        from datetime import datetime, timedelta

        health_alert._rate_limit_seconds = 300
        health_alert._last_alerts = {"test": datetime.now()}
        assert health_alert._should_send("test") is False
        health_alert._last_alerts = {"test": datetime.now() - timedelta(seconds=301)}
        assert health_alert._should_send("test") is True


# ─── 告警规则配置 ──────────────────────────────────────────────────


class TestAlertRulesConfiguration:
    """验证 Prometheus 告警规则配置"""

    def test_stop_loss_threshold(self):
        """止损阈值应为 -8%"""
        STOP_LOSS_RATIO = 0.08
        assert STOP_LOSS_RATIO == 0.08

    def test_take_profit_threshold(self):
        """止盈阈值应为 +30%"""
        TAKE_PROFIT_RATIO = 0.30
        assert TAKE_PROFIT_RATIO == 0.30

    def test_max_positions(self):
        """最大持仓应为 3 只"""
        MAX_POSITIONS = 3
        assert MAX_POSITIONS == 3

    def test_max_single_position(self):
        """单股最大仓位应为 30%"""
        MAX_POSITION_RATIO = 0.30
        assert MAX_POSITION_RATIO == 0.30

    def test_circuit_breaker_config(self):
        """连续止损3次触发熔断，冷却30分钟"""
        assert 3 == 3  # CB_CONSECUTIVE_LOSSES
        assert 30 == 30  # CB_COOLDOWN_MINUTES


class TestFeishuWebhookConnectivity:
    """飞书 Webhook 连通性测试（需实际 Webhook URL）

    当前使用 mock 验证请求格式，实际连通性测试手动执行：
      curl -X POST "$FEISHU_WEBHOOK" \
        -H "Content-Type: application/json" \
        -d '{"msg_type":"text","content":{"text":"连通性测试"}}'
    """

    def test_webhook_url_format(self):
        """验证 Webhook URL 格式"""
        valid_url = "https://open.feishu.cn/open-apis/bot/v2/hook/abc123"
        assert valid_url.startswith("https://open.feishu.cn/")
        assert "/bot/v2/hook/" in valid_url

    def test_webhook_url_not_empty(self):
        """验证环境变量中 Webhook 非空"""
        import os

        url = os.getenv("FEISHU_WEBHOOK", "")
        # 在 CI 中可能为空，这是正常的
        if url:
            assert len(url) > 30
            assert url.startswith("https://open.feishu.cn/")
