"""
services/feishu_alert.py 单元测试
覆盖: 初始化、send_alert、send_health_report、send_service_down/recovered、
      速率限制、异常处理、卡片 JSON 结构
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timedelta


class TestHealthAlertServiceInit:
    """HealthAlertService 初始化测试"""

    def test_init_with_webhook_url(self, alert_service):
        """使用 webhook_url 初始化"""
        assert alert_service.webhook_url == "https://open.feishu.cn/open-apis/bot/v2/hook/test-mock"
        assert isinstance(alert_service._last_alerts, dict)
        assert len(alert_service._last_alerts) == 0
        assert alert_service._rate_limit_seconds == 300

    def test_init_empty_last_alerts(self, alert_service):
        """初始化时 _last_alerts 为空字典"""
        assert alert_service._last_alerts == {}

    def test_rate_limit_default_300s(self, alert_service):
        """默认速率限制为 300 秒"""
        assert alert_service._rate_limit_seconds == 300


class TestShouldSend:
    """_should_send 速率限制逻辑测试"""

    def test_first_alert_should_send(self, alert_service):
        """首次告警应该发送"""
        assert alert_service._should_send("test:alert") is True

    def test_duplicate_within_300s_should_not_send(self, alert_service):
        """300 秒内重复告警不应该发送"""
        alert_service._last_alerts["test:alert"] = datetime.now()
        assert alert_service._should_send("test:alert") is False

    def test_duplicate_after_300s_should_send(self, alert_service):
        """超过 300 秒后应该重新发送"""
        alert_service._last_alerts["test:alert"] = datetime.now() - timedelta(seconds=301)
        assert alert_service._should_send("test:alert") is True

    def test_different_alert_keys_independent(self, alert_service):
        """不同告警 key 独立计算速率限制"""
        alert_service._last_alerts["info:Alert A"] = datetime.now()
        # Alert B 应该是新的，不触发速率限制
        assert alert_service._should_send("warning:Alert B") is True

    def test_rate_limit_updates_timestamp(self, alert_service):
        """发送后更新时间戳"""
        key = "info:Test Alert"
        assert alert_service._should_send(key) is True
        # 立即再次检查应该被限制
        assert alert_service._should_send(key) is False


class TestSendAlert:
    """send_alert 方法测试"""

    @pytest.mark.asyncio
    async def test_send_alert_success(self, alert_service, mock_httpx_post):
        """成功发送告警"""
        await alert_service.send_alert("测试标题", "测试内容")
        mock_httpx_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_alert_card_structure(self, alert_service, mock_httpx_post):
        """验证飞书卡片 JSON 结构"""
        from services.feishu_alert import AlertLevel
        await alert_service.send_alert("服务告警", "详细内容", level=AlertLevel.WARNING)
        call_args = mock_httpx_post.call_args
        # call_args 格式: (url, ...), kwargs 中包含 json
        _, kwargs = call_args
        card_data = kwargs.get("json", {})
        assert card_data["msg_type"] == "interactive"
        assert card_data["card"]["header"]["title"]["content"] == "服务告警"
        assert card_data["card"]["header"]["template"] == "orange"
        assert card_data["card"]["config"]["wide_screen_mode"] is True
        # 验证内容
        elements = card_data["card"]["elements"]
        assert len(elements) == 1
        assert elements[0]["tag"] == "div"
        assert elements[0]["text"]["tag"] == "lark_md"
        assert elements[0]["text"]["content"] == "详细内容"

    @pytest.mark.asyncio
    async def test_send_alert_default_level_is_info(self, alert_service, mock_httpx_post):
        """默认告警级别为 INFO (blue)"""
        await alert_service.send_alert("标题", "内容")
        _, kwargs = mock_httpx_post.call_args
        card_data = kwargs["json"]
        assert card_data["card"]["header"]["template"] == "blue"

    @pytest.mark.asyncio
    async def test_send_alert_warning_level(self, alert_service, mock_httpx_post):
        """WARNING 级别为 orange"""
        from services.feishu_alert import AlertLevel
        await alert_service.send_alert("标题", "内容", level=AlertLevel.WARNING)
        _, kwargs = mock_httpx_post.call_args
        assert kwargs["json"]["card"]["header"]["template"] == "orange"

    @pytest.mark.asyncio
    async def test_send_alert_critical_level(self, alert_service, mock_httpx_post):
        """CRITICAL 级别为 red"""
        from services.feishu_alert import AlertLevel
        await alert_service.send_alert("标题", "内容", level=AlertLevel.CRITICAL)
        _, kwargs = mock_httpx_post.call_args
        assert kwargs["json"]["card"]["header"]["template"] == "red"

    @pytest.mark.asyncio
    async def test_send_alert_http_failure(self, alert_service, mock_httpx_post_fail):
        """发送失败时不应抛出异常（内部处理）"""
        # 不应抛出异常，因为 send_alert 内部捕获了异常
        await alert_service.send_alert("标题", "内容")
        mock_httpx_post_fail.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_alert_network_exception(self, alert_service):
        """网络异常时不应抛出异常"""
        with patch("services.feishu_alert.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("Network error")
            )
            await alert_service.send_alert("标题", "内容")
            # 不应抛出异常

    @pytest.mark.asyncio
    async def test_send_alert_rate_limited(self, alert_service):
        """速率限制下的告警不应发送 HTTP 请求"""
        # 先发送一次
        alert_service._last_alerts["info:速率测试"] = datetime.now()
        with patch("services.feishu_alert.httpx.AsyncClient.post", new_callable=AsyncMock) as mock:
            mock.return_value.status_code = 200
            await alert_service.send_alert("速率测试", "内容")
            mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_alert_calls_webhook_url(self, alert_service, mock_httpx_post):
        """验证发送到正确的 webhook URL"""
        await alert_service.send_alert("标题", "内容")
        call_args = mock_httpx_post.call_args
        args, _ = call_args
        assert args[0] == "https://open.feishu.cn/open-apis/bot/v2/hook/test-mock"

    @pytest.mark.asyncio
    async def test_send_alert_rate_limit_key_format(self, alert_service, mock_httpx_post):
        """验证速率限制 key 格式为 level:title"""
        from services.feishu_alert import AlertLevel
        await alert_service.send_alert("My Alert", "content", AlertLevel.CRITICAL)
        assert "critical:My Alert" in alert_service._last_alerts


class TestSendHealthReport:
    """send_health_report 方法测试"""

    @pytest.mark.asyncio
    async def test_all_healthy_report(self, alert_service, mock_httpx_post):
        """全部健康时发送 INFO 级别报告"""
        services = {
            "strategy-service": True,
            "execution-service": True,
            "ai-scheduler": True,
        }
        await alert_service.send_health_report(services)
        mock_httpx_post.assert_called_once()
        _, kwargs = mock_httpx_post.call_args
        card_data = kwargs["json"]
        # 全部健康 → blue
        assert card_data["card"]["header"]["template"] == "blue"
        assert "系统健康报告" in card_data["card"]["header"]["title"]["content"]
        content = card_data["card"]["elements"][0]["text"]["content"]
        assert "✅" in content
        assert "正常" in content
        assert "❌" not in content

    @pytest.mark.asyncio
    async def test_partial_unhealthy_report(self, alert_service, mock_httpx_post):
        """部分异常时发送 WARNING 级别报告"""
        services = {
            "strategy-service": True,
            "execution-service": False,
            "ai-scheduler": True,
        }
        await alert_service.send_health_report(services)
        _, kwargs = mock_httpx_post.call_args
        card_data = kwargs["json"]
        # 部分异常 → orange
        assert card_data["card"]["header"]["template"] == "orange"
        assert "异常报告" in card_data["card"]["header"]["title"]["content"]
        content = card_data["card"]["elements"][0]["text"]["content"]
        assert "❌" in content
        assert "✅" in content

    @pytest.mark.asyncio
    async def test_all_unhealthy_report(self, alert_service, mock_httpx_post):
        """全部异常时发送 WARNING 级别报告"""
        services = {
            "strategy-service": False,
            "execution-service": False,
        }
        await alert_service.send_health_report(services)
        _, kwargs = mock_httpx_post.call_args
        assert kwargs["json"]["card"]["header"]["template"] == "orange"

    @pytest.mark.asyncio
    async def test_report_includes_timestamp(self, alert_service, mock_httpx_post):
        """报告应包含检查时间戳"""
        await alert_service.send_health_report({"svc": True})
        _, kwargs = mock_httpx_post.call_args
        content = kwargs["json"]["card"]["elements"][0]["text"]["content"]
        assert "检查时间" in content

    @pytest.mark.asyncio
    async def test_report_includes_all_service_names(self, alert_service, mock_httpx_post):
        """报告应包含所有服务名称"""
        services = {"svc-a": True, "svc-b": False, "svc-c": True}
        await alert_service.send_health_report(services)
        _, kwargs = mock_httpx_post.call_args
        content = kwargs["json"]["card"]["elements"][0]["text"]["content"]
        for name in services:
            assert name in content

    @pytest.mark.asyncio
    async def test_report_respects_rate_limit(self, alert_service):
        """健康报告也受速率限制"""
        # 先发一次
        alert_service._last_alerts["warning:⚠️ 系统健康异常报告"] = datetime.now()
        with patch("services.feishu_alert.httpx.AsyncClient.post", new_callable=AsyncMock) as mock:
            await alert_service.send_health_report({"svc": False})
            mock.assert_not_called()


class TestSendServiceDown:
    """send_service_down 方法测试"""

    @pytest.mark.asyncio
    async def test_send_service_down_critical(self, alert_service, mock_httpx_post):
        """服务宕机发送 CRITICAL 级别（red）"""
        await alert_service.send_service_down("strategy-service", "Connection refused")
        mock_httpx_post.assert_called_once()
        _, kwargs = mock_httpx_post.call_args
        card_data = kwargs["json"]
        assert card_data["card"]["header"]["template"] == "red"
        assert "🚨" in card_data["card"]["header"]["title"]["content"]
        assert "strategy-service" in card_data["card"]["header"]["title"]["content"]

    @pytest.mark.asyncio
    async def test_send_service_down_includes_error(self, alert_service, mock_httpx_post):
        """宕机告警包含错误信息"""
        await alert_service.send_service_down("execution-service", "Timeout after 5s")
        _, kwargs = mock_httpx_post.call_args
        content = kwargs["json"]["card"]["elements"][0]["text"]["content"]
        assert "execution-service" in content
        assert "Timeout after 5s" in content
        assert "立即检查" in content

    @pytest.mark.asyncio
    async def test_send_service_down_includes_timestamp(self, alert_service, mock_httpx_post):
        """宕机告警包含时间戳"""
        await alert_service.send_service_down("svc", "error")
        _, kwargs = mock_httpx_post.call_args
        content = kwargs["json"]["card"]["elements"][0]["text"]["content"]
        assert "告警时间" in content


class TestSendServiceRecovered:
    """send_service_recovered 方法测试"""

    @pytest.mark.asyncio
    async def test_send_service_recovered_green_card(self, alert_service, mock_httpx_post):
        """恢复通知使用绿色卡片（不走 send_alert）"""
        await alert_service.send_service_recovered("strategy-service")
        mock_httpx_post.assert_called_once()
        _, kwargs = mock_httpx_post.call_args
        card_data = kwargs["json"]
        assert card_data["card"]["header"]["template"] == "green"
        assert "✅" in card_data["card"]["header"]["title"]["content"]
        assert "strategy-service" in card_data["card"]["header"]["title"]["content"]

    @pytest.mark.asyncio
    async def test_send_service_recovered_content(self, alert_service, mock_httpx_post):
        """恢复通知包含服务名和恢复时间"""
        await alert_service.send_service_recovered("execution-service")
        _, kwargs = mock_httpx_post.call_args
        content = kwargs["json"]["card"]["elements"][0]["text"]["content"]
        assert "execution-service" in content
        assert "恢复时间" in content
        assert "已恢复正常" in content

    @pytest.mark.asyncio
    async def test_send_service_recovered_http_failure(self, alert_service, mock_httpx_post_fail):
        """恢复通知发送失败不应抛异常"""
        await alert_service.send_service_recovered("svc")
        mock_httpx_post_fail.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_service_recovered_network_exception(self, alert_service):
        """恢复通知网络异常不应抛异常"""
        with patch("services.feishu_alert.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("Network error")
            )
            await alert_service.send_service_recovered("svc")
            # 不应抛出异常

    @pytest.mark.asyncio
    async def test_send_service_recovered_bypasses_rate_limit(self, alert_service, mock_httpx_post):
        """恢复通知不走 _should_send 速率限制（直接构造卡片）"""
        # 确保 _last_alerts 中有旧记录，但恢复应该直接发送
        alert_service._last_alerts["info:✅ 服务恢复: svc"] = datetime.now()
        await alert_service.send_service_recovered("svc")
        mock_httpx_post.assert_called_once()


class TestAlertLevelEnum:
    """AlertLevel 枚举测试"""

    def test_alert_level_values(self):
        from services.feishu_alert import AlertLevel
        assert AlertLevel.INFO.value == "info"
        assert AlertLevel.WARNING.value == "warning"
        assert AlertLevel.CRITICAL.value == "critical"

    def test_alert_level_members(self):
        from services.feishu_alert import AlertLevel
        members = list(AlertLevel)
        assert len(members) == 3


class TestLevelTemplate:
    """LEVEL_TEMPLATE 映射测试"""

    def test_level_template_mapping(self):
        from services.feishu_alert import LEVEL_TEMPLATE, AlertLevel
        assert LEVEL_TEMPLATE[AlertLevel.INFO] == "blue"
        assert LEVEL_TEMPLATE[AlertLevel.WARNING] == "orange"
        assert LEVEL_TEMPLATE[AlertLevel.CRITICAL] == "red"
