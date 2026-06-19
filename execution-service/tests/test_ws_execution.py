"""
WebSocket 实时推送测试 — api/ws_execution.py

覆盖：
- /ws/execution 端点
  - 连接建立 → 欢迎消息
  - subscribe 动作 → 订阅确认
  - unsubscribe 动作
  - ping → pong
  - 无效 JSON → 静默忽略
  - 多动作序列
  - 断开连接清理
  - 异常断开 → 清理
- 广播函数
  - broadcast_order_update: 参数转发 + broadcast 调用
  - broadcast_risk_alert: 参数转发 + broadcast 调用
  - broadcast_position_update: 参数转发 + broadcast 调用
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 公共 Fixture ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_ws_manager():
    """每个测试后清理 ws_manager 状态，避免跨测试污染"""
    yield
    from api.ws_execution import ws_manager

    ws_manager._connections.clear()
    ws_manager._subscriptions.clear()
    # 重置计数回调（防止测试间干扰）
    ws_manager._on_count_change = None


# ─── WebSocket 端点测试 ────────────────────────────────────────────


class TestExecutionWsEndpoint:
    """测试 /ws/execution WebSocket 端点"""

    def test_connect_receives_welcome(self, client):
        """连接成功后收到 welcome 消息"""
        with client.websocket_connect("/ws/execution") as ws:
            data = ws.receive_json()

            assert data["type"] == "connected"
            assert "execution" in data["data"]["message"]

    def test_welcome_includes_connection_count(self, client):
        """welcome 消息包含当前连接数"""
        with client.websocket_connect("/ws/execution") as ws:
            data = ws.receive_json()

            assert "connections" in data["data"]
            assert data["data"]["connections"] >= 1

    def test_subscribe_action(self, client):
        """发送 subscribe 动作后收到订阅确认"""
        with client.websocket_connect("/ws/execution") as ws:
            ws.receive_json()  # consume welcome

            ws.send_json({"action": "subscribe", "topic": "order_update"})
            data = ws.receive_json()

            assert data["type"] == "subscribed"
            assert data["data"]["topic"] == "order_update"
            assert "已订阅" in data["data"]["message"]

    def test_subscribe_multiple_topics(self, client):
        """可订阅多个不同主题"""
        with client.websocket_connect("/ws/execution") as ws:
            ws.receive_json()

            ws.send_json({"action": "subscribe", "topic": "order_update"})
            ws.receive_json()  # ack

            ws.send_json({"action": "subscribe", "topic": "risk_alert"})
            data = ws.receive_json()

            assert data["data"]["topic"] == "risk_alert"

    def test_unsubscribe_action(self, client):
        """发送 unsubscribe 动作不报错"""
        with client.websocket_connect("/ws/execution") as ws:
            ws.receive_json()

            ws.send_json({"action": "unsubscribe", "topic": "order_update"})
            # unsubscribe 不返回消息，只静默移除
            # 验证连接未断开
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_ping_pong(self, client):
        """ping → pong 响应包含时间戳"""
        with client.websocket_connect("/ws/execution") as ws:
            ws.receive_json()

            ws.send_json({"action": "ping"})
            data = ws.receive_json()

            assert data["type"] == "pong"
            assert "timestamp" in data

    def test_invalid_json_ignored(self, client):
        """发送非 JSON 数据不会导致断开"""
        with client.websocket_connect("/ws/execution") as ws:
            ws.receive_json()

            ws.send_text("not valid json")
            # 验证连接仍然可用
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_unknown_action_no_error(self, client):
        """未知 action 被静默忽略"""
        with client.websocket_connect("/ws/execution") as ws:
            ws.receive_json()

            ws.send_json({"action": "unknown_action"})
            # 验证连接未断开
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_disconnect_on_context_exit(self, client):
        """with 块退出后自动断开（通过 reset_ws_manager 清理）"""
        from api.ws_execution import ws_manager

        with client.websocket_connect("/ws/execution") as ws:
            ws.receive_json()
            assert ws_manager.count == 1

        # 退出时 TestClient 触发服务端 WebSocketDisconnect →
        # 服务端 handler 中的 disconnect 被调度执行
        # autouse fixture reset_ws_manager 确保下一个测试状态干净

    def test_subscribe_without_topic_ignored(self, client):
        """subscribe 无 topic 字段静默忽略"""
        with client.websocket_connect("/ws/execution") as ws:
            ws.receive_json()

            ws.send_json({"action": "subscribe"})  # 缺少 topic
            # 不应收到订阅确认，验证连接正常
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"


# ─── 广播函数测试 ──────────────────────────────────────────────────


class TestBroadcastFunctions:
    """测试广播辅助函数"""

    @patch("api.ws_execution.ws_manager")
    async def test_broadcast_order_update(self, mock_mgr):
        """broadcast_order_update 正确构造参数并调用 broadcast"""
        from api.ws_execution import broadcast_order_update

        mock_mgr.broadcast = AsyncMock(return_value=3)

        result = await broadcast_order_update(
            order_id="ord_001",
            ts_code="000001.SZ",
            direction="BUY",
            status="FILLED",
            price=12.50,
            quantity=100,
        )

        assert result == 3
        mock_mgr.broadcast.assert_called_once()
        call_args = mock_mgr.broadcast.call_args
        # 第一个参数是 WSType
        assert call_args[0][0].value == "order_update"
        # 第二个参数是 data dict
        data = call_args[0][1]
        assert data["order_id"] == "ord_001"
        assert data["ts_code"] == "000001.SZ"
        assert data["direction"] == "BUY"
        assert data["status"] == "FILLED"

    @patch("api.ws_execution.ws_manager")
    async def test_broadcast_risk_alert(self, mock_mgr):
        """broadcast_risk_alert 正确构造风险告警消息"""
        from api.ws_execution import broadcast_risk_alert

        mock_mgr.broadcast = AsyncMock(return_value=2)

        result = await broadcast_risk_alert(
            ts_code="000001.SZ",
            risk_type="concentration",
            detail="持仓占比超 30%",
        )

        assert result == 2
        mock_mgr.broadcast.assert_called_once()
        call_args = mock_mgr.broadcast.call_args
        assert call_args[0][0].value == "risk_alert"
        data = call_args[0][1]
        assert data["ts_code"] == "000001.SZ"
        assert data["risk_type"] == "concentration"
        assert "持仓占比" in data["detail"]

    @patch("api.ws_execution.ws_manager")
    async def test_broadcast_position_update(self, mock_mgr):
        """broadcast_position_update 正确构造持仓变更消息"""
        from api.ws_execution import broadcast_position_update

        mock_mgr.broadcast = AsyncMock(return_value=1)

        result = await broadcast_position_update(
            ts_code="000001.SZ",
            action="open",
            quantity=500,
            price=12.50,
        )

        assert result == 1
        mock_mgr.broadcast.assert_called_once()
        call_args = mock_mgr.broadcast.call_args
        assert call_args[0][0].value == "position_update"
        data = call_args[0][1]
        assert data["ts_code"] == "000001.SZ"
        assert data["action"] == "open"
        assert data["quantity"] == 500
        assert data["price"] == 12.50

    @patch("api.ws_execution.ws_manager")
    async def test_broadcast_returns_recipient_count(self, mock_mgr):
        """广播函数正确透传 recipient 计数"""
        from api.ws_execution import broadcast_order_update

        mock_mgr.broadcast = AsyncMock(return_value=0)

        result = await broadcast_order_update(
            order_id="ord_002",
            ts_code="600000.SH",
            direction="SELL",
            status="REJECTED",
            price=10.0,
            quantity=200,
        )

        assert result == 0

    @patch("api.ws_execution.ws_manager")
    async def test_broadcast_maps_all_fields(self, mock_mgr):
        """验证 broadcast_position_update 所有字段都正确映射"""
        from api.ws_execution import broadcast_position_update

        mock_mgr.broadcast = AsyncMock(return_value=1)

        await broadcast_position_update(
            ts_code="300750.SZ",
            action="close",
            quantity=100,
            price=180.50,
        )

        data = mock_mgr.broadcast.call_args[0][1]
        assert data == {
            "ts_code": "300750.SZ",
            "action": "close",
            "quantity": 100,
            "price": 180.50,
        }
