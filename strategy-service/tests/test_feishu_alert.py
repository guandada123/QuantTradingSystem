"""
FeishuAlertService 单元测试

覆盖 services/feishu_alert.py 的 FeishuAlertService 类：
- 服务初始化（启用/禁用）
- send_alert 核心方法（HTTP 调用、卡片结构、颜色映射）
- 各便捷告警方法（止损/止盈/风险/AI成本/信号）
- send_backtest_report（飞书卡片推送）
- _send_card 内部方法
- get_alert_service 工厂函数（单例行为）

注意：FeishuAlertService.send_alert 和 _send_card 使用 httpx.AsyncClient，
需要 mock async 上下文管理器。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, patch

import pytest
from services.feishu_alert import (
    AlertLevel,
    AlertType,
    FeishuAlertService,
    get_alert_service,
)

# =========================================================================
# 辅助 fixture: mock httpx.AsyncClient（async 上下文管理器）
# =========================================================================


@pytest.fixture
def mock_httpx():
    """Mock httpx.AsyncClient 及其 async 上下文管理器。

    用法:
        mock_httpx.post.return_value.status_code = 200
        mock_httpx.post.return_value.json.return_value = {"code": 0}
    """
    with patch("services.feishu_alert.httpx.AsyncClient") as cls:
        instance = AsyncMock()
        cls.return_value = instance
        # async with AsyncClient(...) as client: → client = instance
        instance.__aenter__.return_value = instance
        yield instance


# =========================================================================
# FeishuAlertService 初始化
# =========================================================================


class TestFeishuAlertServiceInit:
    """FeishuAlertService 初始化"""

    def test_init_with_webhook(self):
        """有 webhook_url → enabled=True"""
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        assert service.enabled is True
        assert service.webhook_url == "https://hooks.feishu.cn/hook"

    def test_init_without_webhook(self):
        """无 webhook_url → enabled=False"""
        service = FeishuAlertService()
        assert service.enabled is False
        assert service.webhook_url is None


# =========================================================================
# send_alert 核心方法
# =========================================================================


class TestSendAlert:
    """FeishuAlertService.send_alert — 核心方法"""

    @pytest.mark.asyncio
    async def test_disabled_returns_false(self):
        """webhook 未配置 → 返回 False，不发起 HTTP"""
        service = FeishuAlertService()
        with patch("services.feishu_alert.httpx.AsyncClient") as mock_http:
            result = await service.send_alert(
                AlertType.STOP_LOSS,
                AlertLevel.CRITICAL,
                "x",
                "x",
            )
            assert result is False
            mock_http.assert_not_called()

    @pytest.mark.asyncio
    async def test_success(self, mock_httpx):
        """200 OK → 返回 True，验证卡结构"""
        mock_httpx.post.return_value.status_code = 200
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        result = await service.send_alert(
            AlertType.STOP_LOSS,
            AlertLevel.CRITICAL,
            "止损触发",
            "股票: 600519.SH\\n亏损: 8.5%",
        )
        assert result is True
        mock_httpx.post.assert_called_once()

        # 验证请求 URL
        args, kwargs = mock_httpx.post.call_args
        assert args[0] == "https://hooks.feishu.cn/hook"

        # 验证卡片结构
        card = kwargs["json"]
        assert card["msg_type"] == "interactive"
        assert card["card"]["header"]["title"]["content"] == "🔔 止损触发: 止损触发"
        assert card["card"]["header"]["template"] == "red"  # CRITICAL → red

    @pytest.mark.asyncio
    async def test_http_non_200_returns_false(self, mock_httpx):
        """非 200 响应 → 返回 False"""
        mock_httpx.post.return_value.status_code = 403
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        result = await service.send_alert(
            AlertType.SYSTEM_ERROR,
            AlertLevel.WARNING,
            "x",
            "x",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_http_exception_returns_false(self, mock_httpx):
        """网络异常 → 返回 False（不抛出）"""
        mock_httpx.post.side_effect = Exception("Connection refused")
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        result = await service.send_alert(
            AlertType.SYSTEM_ERROR,
            AlertLevel.WARNING,
            "x",
            "x",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_card_includes_data_block(self, mock_httpx):
        """带 data 参数时，card 中插入数据详情块"""
        mock_httpx.post.return_value.status_code = 200
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        await service.send_alert(
            AlertType.STOP_LOSS,
            AlertLevel.CRITICAL,
            "标题",
            "内容",
            data={"止损价": "¥8.50", "建议操作": "卖出"},
        )
        elements = mock_httpx.post.call_args[1]["json"]["card"]["elements"]
        assert len(elements) == 4  # content + hr + data + note
        data_element = elements[2]  # data 是第三个
        assert data_element["tag"] == "markdown"
        assert "数据详情" in data_element["content"]
        assert "止损价" in data_element["content"]

    @pytest.mark.asyncio
    async def test_card_without_data_has_three_elements(self, mock_httpx):
        """无 data 参数 → card 只有 3 个元素（content + hr + note）"""
        mock_httpx.post.return_value.status_code = 200
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        await service.send_alert(
            AlertType.SIGNAL,
            AlertLevel.INFO,
            "信号",
            "内容",
        )
        elements = mock_httpx.post.call_args[1]["json"]["card"]["elements"]
        assert len(elements) == 3

    @pytest.mark.asyncio
    async def test_level_color_mapping(self, mock_httpx):
        """AlertLevel 到 header template 颜色的映射"""
        mock_httpx.post.return_value.status_code = 200
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")

        await service.send_alert(AlertType.STOP_LOSS, AlertLevel.CRITICAL, "x", "x")
        assert mock_httpx.post.call_args[1]["json"]["card"]["header"]["template"] == "red"

        await service.send_alert(AlertType.TAKE_PROFIT, AlertLevel.WARNING, "x", "x")
        assert mock_httpx.post.call_args[1]["json"]["card"]["header"]["template"] == "yellow"

        await service.send_alert(AlertType.SIGNAL, AlertLevel.INFO, "x", "x")
        assert mock_httpx.post.call_args[1]["json"]["card"]["header"]["template"] == "blue"

    @pytest.mark.asyncio
    async def test_note_contains_trace_id(self, mock_httpx):
        """note 元素包含 trace_id 标记"""
        mock_httpx.post.return_value.status_code = 200
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        await service.send_alert(AlertType.SIGNAL, AlertLevel.INFO, "x", "x")
        note = mock_httpx.post.call_args[1]["json"]["card"]["elements"][-1]
        assert note["tag"] == "note"
        assert "QuantTradingSystem" in note["elements"][0]["content"]


# =========================================================================
# 便捷告警方法
# =========================================================================


class TestConvenienceMethods:
    """各便捷告警方法 — 通过 mock send_alert 验证传参

    注意：便捷方法为 fire-and-forget 设计（不 return send_alert 结果），
    因此返回值始终为 None。
    """

    @pytest.fixture
    def service(self):
        return FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")

    # -----------------------------------------------------------------
    # 止损
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_send_stop_loss_alert(self, service):
        """止损告警 → CRITICAL 级别，股票信息正确"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_stop_loss_alert("600519.SH", 100.0, 91.5, 0.085)
            mock_send.assert_called_once()
            kwargs = mock_send.call_args[1]
            assert kwargs["alert_type"] == AlertType.STOP_LOSS
            assert kwargs["level"] == AlertLevel.CRITICAL
            assert "600519.SH" in kwargs["title"]
            assert kwargs["data"] is not None

    # -----------------------------------------------------------------
    # 止盈
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_send_take_profit_alert(self, service):
        """止盈告警 → INFO 级别"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_take_profit_alert("000001.SZ", 10.0, 13.0, 0.30)
            mock_send.assert_called_once()
            kwargs = mock_send.call_args[1]
            assert kwargs["level"] == AlertLevel.INFO
            assert "000001.SZ" in kwargs["title"]

    # -----------------------------------------------------------------
    # 风险
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_send_risk_alert(self, service):
        """风险告警 → WARNING 级别，risk_type 传递正确"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_risk_alert(
                "集中度超标",
                "茅台持仓占比55%",
                {"集中度": "55%"},
            )
            mock_send.assert_called_once()
            kwargs = mock_send.call_args[1]
            assert kwargs["alert_type"] == AlertType.RISK_BREACH
            assert kwargs["level"] == AlertLevel.WARNING
            assert "集中度超标" in kwargs["title"]

    # -----------------------------------------------------------------
    # AI 成本
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_send_ai_cost_alert_warning(self, service):
        """使用率 > 80% → WARNING"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_ai_cost_alert(90.0, 100.0, 0.90)
            mock_send.assert_called_once()
            assert mock_send.call_args[1]["level"] == AlertLevel.WARNING

    @pytest.mark.asyncio
    async def test_send_ai_cost_alert_info(self, service):
        """使用率 <= 80% → INFO"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_ai_cost_alert(50.0, 100.0, 0.50)
            mock_send.assert_called_once()
            assert mock_send.call_args[1]["level"] == AlertLevel.INFO

    @pytest.mark.asyncio
    async def test_send_ai_cost_alert_edge_80(self, service):
        """使用率恰好 80% → INFO（<=80%）"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_ai_cost_alert(80.0, 100.0, 0.80)
            mock_send.assert_called_once()
            assert mock_send.call_args[1]["level"] == AlertLevel.INFO

    # -----------------------------------------------------------------
    # 信号
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_send_signal_alert_buy_emoji(self, service):
        """BUY → 📈 emoji"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_signal_alert("000001.SZ", "BUY", 12.50, 85.0, "金叉信号")
            mock_send.assert_called_once()
            title = mock_send.call_args[1]["title"]
            assert "📈" in title
            assert "BUY" in title

    @pytest.mark.asyncio
    async def test_send_signal_alert_sell_emoji(self, service):
        """SELL → 📉 emoji"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_signal_alert("600519.SH", "SELL", 200.0, 90.0, "死叉信号")
            mock_send.assert_called_once()
            title = mock_send.call_args[1]["title"]
            assert "📉" in title
            assert "SELL" in title

    @pytest.mark.asyncio
    async def test_send_signal_alert_passive_emoji(self, service):
        """非 BUY/SELL → ⏸ emoji（兜底）"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_signal_alert("000001.SZ", "HOLD", 11.0, 50.0, "持仓观望")
            mock_send.assert_called_once()
            title = mock_send.call_args[1]["title"]
            assert "⏸" in title

    @pytest.mark.asyncio
    async def test_send_signal_alert_default(self, service):
        """信号告警传递正确参数"""
        with patch.object(service, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await service.send_signal_alert("000001.SZ", "BUY", 12.50, 85.0, "金叉")
            mock_send.assert_called_once()
            kwargs = mock_send.call_args[1]
            assert kwargs["alert_type"] == AlertType.SIGNAL
            assert kwargs["level"] == AlertLevel.INFO
            assert "000001.SZ" in kwargs["title"]


# =========================================================================
# send_backtest_report
# =========================================================================


class TestSendBacktestReport:
    """send_backtest_report 方法"""

    @pytest.mark.asyncio
    async def test_with_card_sends_card(self):
        """报告含 feishu_card → 调用 _send_card，标题替换为日报标签"""
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        report = {
            "feishu_card": {
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "原有标题"}},
                    "elements": [],
                },
            },
            "report_date": "2026-06-14",
        }
        with patch.object(service, "_send_card") as mock_send:
            await service.send_backtest_report(report, report_type="daily")
            mock_send.assert_called_once()
            card = mock_send.call_args[0][0]
            header_content = card["card"]["header"]["title"]["content"]
            assert "回测日报" in header_content
            assert "2026-06-14" in header_content

    @pytest.mark.asyncio
    async def test_weekly_report_label(self):
        """周报标签"""
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        report = {
            "feishu_card": {
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "x"}},
                    "elements": [],
                },
            },
            "report_date": "2026-W24",
        }
        with patch.object(service, "_send_card") as mock_send:
            await service.send_backtest_report(report, report_type="weekly")
            assert "回测周报" in mock_send.call_args[0][0]["card"]["header"]["title"]["content"]

    @pytest.mark.asyncio
    async def test_monthly_report_label(self):
        """月报标签"""
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        report = {
            "feishu_card": {
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "x"}},
                    "elements": [],
                },
            },
            "report_date": "2026-06",
        }
        with patch.object(service, "_send_card") as mock_send:
            await service.send_backtest_report(report, report_type="monthly")
            assert "回测月报" in mock_send.call_args[0][0]["card"]["header"]["title"]["content"]

    @pytest.mark.asyncio
    async def test_without_card_skips(self):
        """报告无 feishu_card → 跳过，不调用 _send_card"""
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        with patch.object(service, "_send_card") as mock_send:
            await service.send_backtest_report({"report_date": "2026-06-14"})
            mock_send.assert_not_called()


# =========================================================================
# _send_card 内部方法
# =========================================================================


class TestSendCard:
    """_send_card 内部方法"""

    @pytest.mark.asyncio
    async def test_success(self, mock_httpx):
        """POST 返回 code=0 → 成功，payload 含 timestamp 和 note"""
        mock_httpx.post.return_value.status_code = 200
        mock_httpx.post.return_value.json.return_value = {"code": 0}
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        card = {
            "card": {
                "header": {"title": {"tag": "plain_text", "content": "测试"}},
                "elements": [],
            },
        }
        await service._send_card(card)
        mock_httpx.post.assert_called_once()
        payload = mock_httpx.post.call_args[1]["json"]
        assert "timestamp" in payload
        assert payload["card"]["elements"][-1]["tag"] == "note"
        assert "QuantTradingSystem" in payload["card"]["elements"][-1]["elements"][0]["content"]

    @pytest.mark.asyncio
    async def test_non_zero_code(self, mock_httpx):
        """POST 返回 code != 0 → 不抛出异常"""
        mock_httpx.post.return_value.status_code = 200
        mock_httpx.post.return_value.json.return_value = {"code": 10001}
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        await service._send_card(
            {
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "x"}},
                    "elements": [],
                },
            }
        )
        # 优雅降级，无异常

    @pytest.mark.asyncio
    async def test_http_failure(self, mock_httpx):
        """HTTP 500 → 不抛出异常"""
        mock_httpx.post.return_value.status_code = 500
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        await service._send_card(
            {
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "x"}},
                    "elements": [],
                },
            }
        )

    @pytest.mark.asyncio
    async def test_http_exception_graceful(self, mock_httpx):
        """网络异常 → 不抛出异常（优雅降级）"""
        mock_httpx.post.side_effect = Exception("timeout")
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        await service._send_card(
            {
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "x"}},
                    "elements": [],
                },
            }
        )

    @pytest.mark.asyncio
    async def test_trace_id_appended(self, mock_httpx):
        """note 元素追加 trace_id 标记"""
        mock_httpx.post.return_value.status_code = 200
        mock_httpx.post.return_value.json.return_value = {"code": 0}
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        await service._send_card(
            {
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "x"}},
                    "elements": [],
                },
            }
        )
        note = mock_httpx.post.call_args[1]["json"]["card"]["elements"][-1]
        assert "QuantTradingSystem" in note["elements"][0]["content"]

    @pytest.mark.asyncio
    async def test_sign_in_payload(self, mock_httpx):
        """payload 包含 sign 和 timestamp 字段"""
        mock_httpx.post.return_value.status_code = 200
        mock_httpx.post.return_value.json.return_value = {"code": 0}
        service = FeishuAlertService(webhook_url="https://hooks.feishu.cn/hook")
        await service._send_card(
            {
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "x"}},
                    "elements": [],
                },
            }
        )
        payload = mock_httpx.post.call_args[1]["json"]
        assert "sign" in payload
        assert "timestamp" in payload


# =========================================================================
# get_alert_service 工厂函数（单例）
# =========================================================================


class TestGetAlertService:
    """get_alert_service 工厂函数"""

    @pytest.fixture(autouse=True)
    def reset_global(self):
        """每个测试前重置全局 alert_service"""
        import services.feishu_alert as fa

        original = fa.alert_service
        fa.alert_service = None
        yield
        fa.alert_service = original

    def test_no_config_returns_instance(self):
        """无 webhook → 返回 FeishuAlertService()（disabled）"""
        service = get_alert_service()
        assert isinstance(service, FeishuAlertService)
        assert service.enabled is False

    def test_with_webhook_returns_configured(self):
        """有 webhook → 返回已配置实例"""
        service = get_alert_service(webhook_url="https://hooks.feishu.cn/test")
        assert isinstance(service, FeishuAlertService)
        assert service.enabled is True
        assert service.webhook_url == "https://hooks.feishu.cn/test"

    def test_singleton_reuses_instance(self):
        """多次调用返回同一实例"""
        s1 = get_alert_service(webhook_url="https://hooks.feishu.cn/s1")
        s2 = get_alert_service()
        assert s1 is s2

    def test_singleton_first_call_wins(self):
        """首次配置的 webhook_url 生效，后续参数被忽略"""
        s1 = get_alert_service(webhook_url="https://hooks.feishu.cn/first")
        s2 = get_alert_service(webhook_url="https://hooks.feishu.cn/second")
        assert s1 is s2
        assert s1.webhook_url == "https://hooks.feishu.cn/first"

    def test_get_alert_service_creates_new_when_none(self):
        """alert_service 为 None 且无 webhook → 返回全新实例"""
        service = get_alert_service()
        # 此时 alert_service 未被赋值（无 webhook → if 不成立）
        # 但返回 FeishuAlertService()（临时实例）
        assert isinstance(service, FeishuAlertService)
        assert service.enabled is False
        # 全局仍为 None（因为没有 webhook_url）
        import services.feishu_alert as fa

        assert fa.alert_service is None
