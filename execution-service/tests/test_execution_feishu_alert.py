"""
飞书告警通知服务 - 单元测试

覆盖 services/feishu_alert.py 的 FeishuAlertService 类：
- 初始化（启用/禁用）
- 各类通知（订单成交、拒绝、风控、持仓异常、每日汇总、系统异常）
- 速率限制
- HTTP 调用失败优雅处理
- 禁用状态下的行为
"""

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.feishu_alert import AlertLevel, FeishuAlertService

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_httpx():
    """Mock httpx.AsyncClient 返回成功响应"""
    with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        MockAC.return_value.__aenter__.return_value = mock_client
        yield MockAC, mock_client, mock_response


@pytest.fixture
def alert_service():
    """已启用飞书告警的服务"""
    return FeishuAlertService(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test")


# ============================================================
# 初始化测试
# ============================================================


class TestInitialization:
    """初始化测试"""

    def test_init_with_webhook(self):
        """使用 webhook URL 初始化"""
        svc = FeishuAlertService(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test")
        assert svc.enabled is True
        assert svc.webhook_url == "https://open.feishu.cn/open-apis/bot/v2/hook/test"
        assert svc.rate_limit_seconds == 60

    def test_init_without_webhook(self):
        """不传 webhook URL（禁用状态）"""
        svc = FeishuAlertService()
        assert svc.enabled is False
        assert svc.webhook_url is None

    def test_init_empty_webhook(self):
        """空字符串 webhook"""
        svc = FeishuAlertService(webhook_url="")
        assert svc.enabled is False

    def test_init_custom_rate_limit(self):
        """自定义速率限制"""
        svc = FeishuAlertService(webhook_url="https://example.com", rate_limit_seconds=30)
        assert svc.rate_limit_seconds == 30


# ============================================================
# 订单成交通知
# ============================================================


class TestSendOrderFilled:
    """订单成交通知测试"""

    @pytest.mark.asyncio
    async def test_buy_filled(self, alert_service, mock_httpx):
        """买入订单成交通知"""
        MockAC, mock_client, _ = mock_httpx

        order_info = {
            "direction": "BUY",
            "ts_code": "600519.SH",
            "price": 1800.0,
            "quantity": 100,
            "amount": 180000.0,
            "commission": 54.0,
            "tax": 0.0,
            "order_id": "ORD_TEST_001",
        }

        result = await alert_service.send_order_filled(order_info)
        assert result is True

        # 验证发送了正确的 card
        _, kwargs = mock_client.post.call_args
        card = kwargs["json"]
        assert card["msg_type"] == "interactive"
        assert "成交" in card["card"]["header"]["title"]["content"]
        assert "600519.SH" in card["card"]["header"]["title"]["content"]
        assert card["card"]["header"]["template"] == "blue"

    @pytest.mark.asyncio
    async def test_sell_filled(self, alert_service, mock_httpx):
        """卖出订单成交通知"""
        MockAC, mock_client, _ = mock_httpx

        order_info = {
            "direction": "SELL",
            "ts_code": "000001.SZ",
            "price": 15.5,
            "quantity": 200,
            "amount": 3100.0,
            "commission": 5.0,
            "tax": 3.1,
            "order_id": "ORD_TEST_002",
        }

        result = await alert_service.send_order_filled(order_info)
        assert result is True

        _, kwargs = mock_client.post.call_args
        card = kwargs["json"]
        title = card["card"]["header"]["title"]["content"]
        assert "卖出" in title or "SELL" in title.upper()

    @pytest.mark.asyncio
    async def test_order_filled_without_order_id(self, alert_service, mock_httpx):
        """订单成交不带 order_id"""
        MockAC, mock_client, _ = mock_httpx

        order_info = {
            "direction": "BUY",
            "ts_code": "600519.SH",
            "price": 1800.0,
            "quantity": 100,
            "amount": 180000.0,
            "commission": 54.0,
            "tax": 0.0,
        }

        result = await alert_service.send_order_filled(order_info)
        assert result is True

        # 验证调用成功
        mock_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_order_filled_missing_fields(self, alert_service, mock_httpx):
        """订单成交缺少部分字段"""
        MockAC, mock_client, _ = mock_httpx

        order_info = {
            "direction": "BUY",
            "ts_code": "600519.SH",
            # 缺少 price, quantity, amount, commission, tax
        }

        result = await alert_service.send_order_filled(order_info)
        assert result is True
        mock_client.post.assert_awaited_once()


# ============================================================
# 订单拒绝告警
# ============================================================


class TestSendOrderRejected:
    """订单拒绝告警测试"""

    @pytest.mark.asyncio
    async def test_order_rejected(self, alert_service, mock_httpx):
        """订单被拒绝告警"""
        MockAC, mock_client, _ = mock_httpx

        order_info = {
            "ts_code": "600519.SH",
            "direction": "BUY",
            "quantity": 100,
            "price": 1800.0,
        }

        result = await alert_service.send_order_rejected(order_info, "资金不足")
        assert result is True

        _, kwargs = mock_client.post.call_args
        card = kwargs["json"]
        title = card["card"]["header"]["title"]["content"]
        assert "拒绝" in title
        assert card["card"]["header"]["template"] == "orange"

    @pytest.mark.asyncio
    async def test_order_rejected_with_long_reason(self, alert_service, mock_httpx):
        """订单被拒绝含详细原因"""
        MockAC, mock_client, _ = mock_httpx

        order_info = {
            "ts_code": "000001.SZ",
            "direction": "SELL",
            "quantity": 500,
            "price": 12.0,
        }

        result = await alert_service.send_order_rejected(
            order_info, "持仓不足: 当前可用持仓仅200股"
        )
        assert result is True
        mock_client.post.assert_awaited_once()


# ============================================================
# 风控触发告警
# ============================================================


class TestSendRiskTriggered:
    """风控触发告警测试"""

    @pytest.mark.asyncio
    async def test_risk_triggered(self, alert_service, mock_httpx):
        """风控触发告警"""
        MockAC, mock_client, _ = mock_httpx

        result = await alert_service.send_risk_triggered(
            ts_code="600519.SH",
            risk_type="仓位超标",
            details="单只股票仓位达到45%，超过30%限制",
        )
        assert result is True

        _, kwargs = mock_client.post.call_args
        card = kwargs["json"]
        title = card["card"]["header"]["title"]["content"]
        assert "风控" in title
        assert card["card"]["header"]["template"] == "red"

    @pytest.mark.asyncio
    async def test_multiple_risk_types(self, alert_service, mock_httpx):
        """不同风控类型"""
        MockAC, mock_client, _ = mock_httpx

        risk_cases = [
            ("止损触发", "股价跌破8%止损线"),
            ("持仓数量超限", "当前持仓6只超过上限5只"),
            ("日内交易超频", "今日已交易20次超过限制10次"),
            ("资金使用率过高", "资金使用率85%超过80%限制"),
        ]

        for risk_type, details in risk_cases:
            result = await alert_service.send_risk_triggered(
                ts_code="000001.SZ",
                risk_type=risk_type,
                details=details,
            )
            assert result is True

        assert mock_client.post.await_count == len(risk_cases)


# ============================================================
# 持仓异常告警
# ============================================================


class TestSendPositionAlert:
    """持仓异常告警测试"""

    @pytest.mark.asyncio
    async def test_position_alert_critical(self, alert_service, mock_httpx):
        """止损类持仓告警（CRITICAL级别）"""
        MockAC, mock_client, _ = mock_httpx

        position_info = {
            "ts_code": "600519.SH",
            "cost_price": 100.0,
            "current_price": 85.0,
            "quantity": 500,
        }

        result = await alert_service.send_position_alert(position_info, "止损触发")
        assert result is True

        _, kwargs = mock_client.post.call_args
        card = kwargs["json"]
        assert card["card"]["header"]["template"] == "red"

    @pytest.mark.asyncio
    async def test_position_alert_warning(self, alert_service, mock_httpx):
        """非止损类持仓告警（WARNING级别）"""
        MockAC, mock_client, _ = mock_httpx

        position_info = {
            "ts_code": "000001.SZ",
            "cost_price": 10.0,
            "current_price": 12.0,
            "quantity": 1000,
        }

        result = await alert_service.send_position_alert(position_info, "持仓异动")
        assert result is True

        _, kwargs = mock_client.post.call_args
        card = kwargs["json"]
        assert card["card"]["header"]["template"] == "orange"

    @pytest.mark.asyncio
    async def test_position_alert_pnl_ratio_calculation(self, alert_service, mock_httpx):
        """验证盈亏比计算正确"""
        MockAC, mock_client, _ = mock_httpx

        # 亏损场景: (5-10)/10*100 = -50%
        position_info = {
            "ts_code": "600519.SH",
            "cost_price": 10.0,
            "current_price": 5.0,
            "quantity": 200,
        }

        await alert_service.send_position_alert(position_info, "止损触发")
        _, kwargs = mock_client.post.call_args
        elements = kwargs["json"]["card"]["elements"]
        # 找到第一个 markdown 元素
        md_content = elements[0]["content"]
        assert "-50" in md_content or "-50" in md_content

    @pytest.mark.asyncio
    async def test_position_alert_zero_cost_price(self, alert_service, mock_httpx):
        """成本价为0时的处理"""
        MockAC, mock_client, _ = mock_httpx

        position_info = {
            "ts_code": "600519.SH",
            "cost_price": 0.0,
            "current_price": 50.0,
            "quantity": 100,
        }

        result = await alert_service.send_position_alert(position_info, "持仓异常")
        assert result is True

        _, kwargs = mock_client.post.call_args
        md_content = kwargs["json"]["card"]["elements"][0]["content"]
        assert "0.0" in md_content  # pnl_ratio = 0 since cost_price == 0


# ============================================================
# 每日交易汇总
# ============================================================


class TestSendDailySummary:
    """每日交易汇总测试"""

    @pytest.mark.asyncio
    async def test_daily_summary_positive_pnl(self, alert_service, mock_httpx):
        """盈利日的每日汇总"""
        MockAC, mock_client, _ = mock_httpx

        summary_data = {
            "date": "2026-06-15",
            "total_trades": 10,
            "buy_count": 6,
            "sell_count": 4,
            "total_commission": 150.0,
            "realized_pnl": 5000.0,
            "position_count": 5,
            "total_assets": 1200000.0,
        }

        result = await alert_service.send_daily_summary(summary_data)
        assert result is True

        _, kwargs = mock_client.post.call_args
        card_title = kwargs["json"]["card"]["header"]["title"]["content"]
        assert "2026-06-15" in card_title
        assert card_title.startswith("📋")

    @pytest.mark.asyncio
    async def test_daily_summary_negative_pnl(self, alert_service, mock_httpx):
        """亏损日的每日汇总"""
        MockAC, mock_client, _ = mock_httpx

        summary_data = {
            "date": "2026-06-14",
            "total_trades": 3,
            "buy_count": 1,
            "sell_count": 2,
            "total_commission": 25.0,
            "realized_pnl": -3000.0,
            "position_count": 4,
            "total_assets": 950000.0,
        }

        result = await alert_service.send_daily_summary(summary_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_daily_summary_empty_data(self, alert_service, mock_httpx):
        """空数据的每日汇总（默认值）"""
        MockAC, mock_client, _ = mock_httpx

        summary_data = {}

        result = await alert_service.send_daily_summary(summary_data)
        assert result is True
        mock_client.post.assert_awaited_once()


# ============================================================
# 系统异常告警
# ============================================================


class TestSendSystemError:
    """系统异常告警测试"""

    @pytest.mark.asyncio
    async def test_system_error(self, alert_service, mock_httpx):
        """系统异常告警"""
        MockAC, mock_client, _ = mock_httpx

        result = await alert_service.send_system_error(
            service_name="execution-service",
            error_msg="数据库连接超时",
        )
        assert result is True

        _, kwargs = mock_client.post.call_args
        card = kwargs["json"]
        title = card["card"]["header"]["title"]["content"]
        assert "异常" in title
        assert "execution-service" in title
        assert card["card"]["header"]["template"] == "red"

    @pytest.mark.asyncio
    async def test_system_error_empty_message(self, alert_service, mock_httpx):
        """空错误信息的系统异常"""
        MockAC, mock_client, _ = mock_httpx

        result = await alert_service.send_system_error(
            service_name="test-service",
            error_msg="",
        )
        assert result is True


# ============================================================
# 速率限制测试
# ============================================================


class TestRateLimiting:
    """速率限制测试"""

    @pytest.mark.asyncio
    async def test_rate_limit_same_type(self):
        """同一告警类型60秒内重复发送被限制"""
        svc = FeishuAlertService(
            webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
            rate_limit_seconds=60,
        )

        with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"code": 0}
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockAC.return_value.__aenter__.return_value = mock_client

            # 使用相同 alert_key 快速发送两次
            order_info = {
                "direction": "BUY",
                "ts_code": "600519.SH",
                "price": 100.0,
                "quantity": 100,
            }
            first = await svc.send_order_filled(order_info)
            second = await svc.send_order_filled(order_info)

            assert first is True  # 第一次成功
            assert second is False  # 第二次被速率限制
            # post 只应被调用一次
            assert mock_client.post.await_count == 1

    @pytest.mark.asyncio
    async def test_rate_limit_different_types(self):
        """不同类型的告警不受速率限制影响"""
        svc = FeishuAlertService(
            webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
            rate_limit_seconds=60,
        )

        with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"code": 0}
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockAC.return_value.__aenter__.return_value = mock_client

            # 不同类型告警快速发送，不应被限制
            r1 = await svc.send_system_error("svc1", "err1")
            r2 = await svc.send_risk_triggered("000001.SZ", "仓位超标", "details")
            r3 = await svc.send_order_filled({"direction": "BUY", "ts_code": "600519.SH"})

            assert r1 is True
            assert r2 is True
            assert r3 is True
            assert mock_client.post.await_count == 3

    @pytest.mark.asyncio
    async def test_rate_limit_expires(self):
        """速率限制过期后可以再次发送"""
        svc = FeishuAlertService(
            webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
            rate_limit_seconds=60,
        )

        original_time = time.time

        with (
            patch("services.feishu_alert.httpx.AsyncClient") as MockAC,
            patch("services.feishu_alert.time") as mock_time,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"code": 0}
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockAC.return_value.__aenter__.return_value = mock_client

            # 第一次：t=100
            mock_time.time.return_value = 100.0
            r1 = await svc.send_system_error("svc1", "err1")
            assert r1 is True

            # 第二次：t=130（仍在60秒窗口内）
            mock_time.time.return_value = 130.0
            r2 = await svc.send_system_error("svc1", "err1")
            assert r2 is False  # 被限制

            # 第三次：t=170（已过60秒窗口）
            mock_time.time.return_value = 170.0
            r3 = await svc.send_system_error("svc1", "err1")
            assert r3 is True  # 限制过期，可再次发送

            # post 应只被调用2次（第1次成功，第2次被限制，第3次又成功了）
            assert mock_client.post.await_count == 2


# ============================================================
# HTTP 错误处理测试
# ============================================================


class TestHTTPErrorHandling:
    """HTTP 调用失败优雅处理测试"""

    @pytest.mark.asyncio
    async def test_http_non_200(self):
        """Webhook 返回非200状态码"""
        svc = FeishuAlertService(webhook_url="https://example.com/webhook")

        with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.json.return_value = {}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockAC.return_value.__aenter__.return_value = mock_client

            result = await svc.send_system_error("test", "error")
            assert result is False  # 不抛出异常，返回False

    @pytest.mark.asyncio
    async def test_http_bad_json(self):
        """Webhook 返回异常JSON（code != 0）"""
        svc = FeishuAlertService(webhook_url="https://example.com/webhook")

        with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"code": 10003, "msg": "invalid webhook"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockAC.return_value.__aenter__.return_value = mock_client

            result = await svc.send_order_filled({"direction": "BUY", "ts_code": "600519.SH"})
            assert result is False

    @pytest.mark.asyncio
    async def test_http_exception(self):
        """Webhook 请求抛出异常（如网络超时）"""
        svc = FeishuAlertService(webhook_url="https://example.com/webhook")

        with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection timeout"))
            MockAC.return_value.__aenter__.return_value = mock_client

            # 不应抛出异常
            result = await svc.send_system_error("test", "timeout")
            assert result is False

    @pytest.mark.asyncio
    async def test_http_401(self):
        """Webhook 返回401"""
        svc = FeishuAlertService(webhook_url="https://example.com/webhook")

        with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
            mock_response = MagicMock()
            mock_response.status_code = 401

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockAC.return_value.__aenter__.return_value = mock_client

            result = await svc.send_risk_triggered("600519.SH", "测试", "details")
            assert result is False


# ============================================================
# 禁用状态测试
# ============================================================


class TestDisabledService:
    """禁用状态测试"""

    @pytest.mark.asyncio
    async def test_disabled_no_http_call(self):
        """禁用状态下不发起HTTP调用"""
        svc = FeishuAlertService()  # no webhook -> disabled

        with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
            result = await svc.send_system_error("test", "error")
            assert result is False
            MockAC.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_all_message_types(self):
        """禁用状态下所有消息类型均返回False且不报错"""
        svc = FeishuAlertService()

        with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
            results = await asyncio.gather(
                svc.send_order_filled({"direction": "BUY", "ts_code": "600519.SH"}),
                svc.send_order_rejected({"ts_code": "600519.SH"}, "原因"),
                svc.send_risk_triggered("600519.SH", "风险", "详情"),
                svc.send_position_alert({"ts_code": "600519.SH"}, "异常"),
                svc.send_daily_summary({"date": "2026-06-15"}),
                svc.send_system_error("test", "error"),
            )
            assert all(r is False for r in results)
            MockAC.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_empty_webhook(self):
        """空字符串webhook不发起HTTP调用"""
        svc = FeishuAlertService(webhook_url="")

        with patch("services.feishu_alert.httpx.AsyncClient") as MockAC:
            result = await svc.send_system_error("test", "error")
            assert result is False
            MockAC.assert_not_called()


# ============================================================
# 速率限制内部方法测试
# ============================================================


class TestInternalMethods:
    """内部方法测试"""

    def test_is_rate_limited_first_call(self):
        """首次调用不被限制"""
        svc = FeishuAlertService(webhook_url="https://example.com")
        assert svc._is_rate_limited("test_key") is False
        assert "test_key" in svc._last_sent

    def test_is_rate_limited_immediate_second(self):
        """立即再次调用被限制"""
        svc = FeishuAlertService(webhook_url="https://example.com")
        assert svc._is_rate_limited("test_key") is False
        assert svc._is_rate_limited("test_key") is True

    def test_is_rate_limited_different_keys(self):
        """不同key互不影响"""
        svc = FeishuAlertService(webhook_url="https://example.com")
        assert svc._is_rate_limited("key_a") is False
        assert svc._is_rate_limited("key_b") is False
        # key_a 刚被访问过，应被限制
        assert svc._is_rate_limited("key_a") is True
        # key_b 也应被限制
        assert svc._is_rate_limited("key_b") is True

    def test_enabled_property_no_webhook(self):
        """无webhook时enabled=False"""
        svc = FeishuAlertService()
        assert svc.enabled is False

    def test_enabled_property_with_webhook(self):
        """有webhook时enabled=True"""
        svc = FeishuAlertService(webhook_url="https://example.com")
        assert svc.enabled is True

    def test_last_sent_empty_initial(self):
        """初始状态_last_sent为空"""
        svc = FeishuAlertService(webhook_url="https://example.com")
        assert svc._last_sent == {}
