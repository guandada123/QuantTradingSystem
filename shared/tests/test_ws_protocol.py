"""shared/ws_protocol.py 单元测试 — WebSocket 标准化消息协议"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.ws_protocol import (
    ConnectionManager,
    ServiceName,
    WSType,
    build_error_message,
    build_message,
)

# ============================================================
#  WSType 枚举测试
# ============================================================


class TestWSType:
    """消息类型枚举"""

    def test_enum_values(self):
        assert WSType.CONNECTED.value == "connected"
        assert WSType.SUBSCRIBED.value == "subscribed"
        assert WSType.ERROR.value == "error"
        assert WSType.INDEX_UPDATE.value == "index_update"
        assert WSType.SIGNAL_UPDATE.value == "signal_update"
        assert WSType.ORDER_UPDATE.value == "order_update"
        assert WSType.RISK_ALERT.value == "risk_alert"
        assert WSType.POSITION_UPDATE.value == "position_update"
        assert WSType.TASK_UPDATE.value == "task_update"
        assert WSType.HEALTH_UPDATE.value == "health_update"

    def test_enum_members_count(self):
        assert len(WSType) == 10

    def test_enum_inherits_str(self):
        assert isinstance(WSType.CONNECTED, str)


# ============================================================
#  ServiceName 枚举测试
# ============================================================


class TestServiceName:
    def test_strategy(self):
        assert ServiceName.STRATEGY.value == "strategy"

    def test_execution(self):
        assert ServiceName.EXECUTION.value == "execution"

    def test_scheduler(self):
        assert ServiceName.SCHEDULER.value == "ai-scheduler"

    def test_inherits_str(self):
        assert isinstance(ServiceName.STRATEGY, str)


# ============================================================
#  build_message / build_error_message 测试
# ============================================================


class TestBuildMessage:
    def test_build_message_structure(self, freezer):
        """验证消息结构包含所有必需字段"""
        msg = build_message(WSType.INDEX_UPDATE, {"code": "000001"}, ServiceName.STRATEGY)
        assert msg["type"] == "index_update"
        assert msg["data"] == {"code": "000001"}
        assert msg["service"] == "strategy"
        assert "timestamp" in msg
        assert isinstance(msg["timestamp"], str)

    def test_build_message_with_different_types(self):
        msg = build_message(WSType.ORDER_UPDATE, {"order_id": "123"}, ServiceName.EXECUTION)
        assert msg["type"] == "order_update"
        assert msg["service"] == "execution"

    def test_build_message_with_scheduler(self):
        msg = build_message(WSType.TASK_UPDATE, {"task_id": "abc"}, ServiceName.SCHEDULER)
        assert msg["type"] == "task_update"
        assert msg["service"] == "ai-scheduler"

    def test_build_error_message(self):
        msg = build_error_message("ERR_001", "something went wrong", ServiceName.STRATEGY)
        assert msg["type"] == "error"
        assert msg["data"] == {"code": "ERR_001", "detail": "something went wrong"}
        assert msg["service"] == "strategy"

    def test_build_error_message_structure(self):
        msg = build_error_message("AUTH_FAILED", "invalid token", ServiceName.EXECUTION)
        assert msg["type"] == "error"
        assert msg["data"]["code"] == "AUTH_FAILED"
        assert msg["data"]["detail"] == "invalid token"


# ============================================================
#  ConnectionManager 测试
# ============================================================


class _MockWebSocket:
    """用于 ConnectionManager 测试的模拟 WebSocket"""

    def __init__(self, ws_id: str = "ws1"):
        self.ws_id = ws_id
        self.accept = AsyncMock()
        self.send_json = AsyncMock()
        self.accepted = False
        self.closed = False


class TestConnectionManager:
    """连接管理器同步行为测试"""

    def test_init_defaults(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        assert mgr.service == ServiceName.STRATEGY
        assert mgr.count == 0
        assert mgr._on_count_change is None

    def test_init_with_callback(self):
        cb = MagicMock()
        mgr = ConnectionManager(ServiceName.EXECUTION, on_count_change=cb)
        assert mgr._on_count_change is cb

    def test_count_property(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        assert mgr.count == 0

    def test_subscribe_adds_connection(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        mgr.subscribe(ws, "index_update")
        assert ws in mgr._subscriptions["index_update"]

    def test_subscribe_multiple_topics(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        mgr.subscribe(ws, "index_update")
        mgr.subscribe(ws, "signal_update")
        assert ws in mgr._subscriptions["index_update"]
        assert ws in mgr._subscriptions["signal_update"]

    def test_unsubscribe_removes_connection(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        mgr.subscribe(ws, "index_update")
        mgr.unsubscribe(ws, "index_update")
        assert ws not in mgr._subscriptions["index_update"]

    def test_get_subscriptions(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws1 = _MockWebSocket("ws1")
        ws2 = _MockWebSocket("ws2")
        mgr.subscribe(ws1, "index_update")
        mgr.subscribe(ws2, "index_update")
        assert len(mgr._subscriptions["index_update"]) == 2


class TestConnectionManagerAsync:
    """连接管理器异步行为测试"""

    @pytest.mark.asyncio
    async def test_connect_accepts_and_adds(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        await mgr.connect(ws)
        ws.accept.assert_awaited_once()
        assert mgr.count == 1

    @pytest.mark.asyncio
    async def test_connect_sends_welcome(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        await mgr.connect(ws)
        ws.send_json.assert_awaited_once()
        call_args = ws.send_json.await_args[0][0]
        assert call_args["type"] == "connected"

    @pytest.mark.asyncio
    async def test_connect_calls_callback(self):
        cb = MagicMock()
        mgr = ConnectionManager(ServiceName.STRATEGY, on_count_change=cb)
        ws = _MockWebSocket()
        await mgr.connect(ws)
        cb.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_connect_welcome_failure_doesnt_raise(self):
        """send_json 失败时不抛出异常"""
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        ws.send_json.side_effect = ConnectionError("broken")
        await mgr.connect(ws)  # should not raise
        assert mgr.count == 1

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        await mgr.connect(ws)
        assert mgr.count == 1
        await mgr.disconnect(ws)
        assert mgr.count == 0

    @pytest.mark.asyncio
    async def test_disconnect_removes_subscriptions(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        await mgr.connect(ws)
        mgr.subscribe(ws, "index_update")
        await mgr.disconnect(ws)
        # 连接不应出现在任何订阅中
        for subscribers in mgr._subscriptions.values():
            assert ws not in subscribers

    @pytest.mark.asyncio
    async def test_disconnect_calls_callback(self):
        cb = MagicMock()
        mgr = ConnectionManager(ServiceName.STRATEGY, on_count_change=cb)
        ws = _MockWebSocket()
        await mgr.connect(ws)
        cb.reset_mock()
        await mgr.disconnect(ws)
        cb.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws1 = _MockWebSocket("ws1")
        ws2 = _MockWebSocket("ws2")
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        success = await mgr.broadcast(WSType.INDEX_UPDATE, {"code": "000001"})
        assert success == 2
        ws1.send_json.assert_awaited()
        ws2.send_json.assert_awaited()

    @pytest.mark.asyncio
    async def test_broadcast_cleans_dead_connections(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws1 = _MockWebSocket("ws1")
        ws2 = _MockWebSocket("ws2")
        ws2.send_json.side_effect = ConnectionError("dead")
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        success = await mgr.broadcast(WSType.INDEX_UPDATE, {})
        assert success == 1
        assert mgr.count == 1  # ws2 cleaned

    @pytest.mark.asyncio
    async def test_broadcast_to_topic(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws1 = _MockWebSocket("ws1")
        ws2 = _MockWebSocket("ws2")
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        mgr.subscribe(ws1, "index_update")
        mgr.subscribe(ws2, "signal_update")

        success = await mgr.broadcast_to_topic("index_update", WSType.INDEX_UPDATE, {})
        assert success == 1  # only ws1
        ws1.send_json.assert_awaited()
        ws2.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_broadcast_to_nonexistent_topic(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        await mgr.connect(ws)
        success = await mgr.broadcast_to_topic("nonexistent", WSType.INDEX_UPDATE, {})
        assert success == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_topic_cleans_dead(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws1 = _MockWebSocket("ws1")
        ws2 = _MockWebSocket("ws2")
        ws2.send_json.side_effect = ConnectionError("dead")
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        mgr.subscribe(ws1, "topic_a")
        mgr.subscribe(ws2, "topic_a")
        success = await mgr.broadcast_to_topic("topic_a", WSType.INDEX_UPDATE, {})
        assert success == 1
        # ws2 should be removed from connections
        assert mgr.count == 1

    @pytest.mark.asyncio
    async def test_multiple_connections_count(self):
        mgr = ConnectionManager(ServiceName.STRATEGY)
        wss = [_MockWebSocket(f"ws{i}") for i in range(5)]
        for ws in wss:
            await mgr.connect(ws)
        assert mgr.count == 5

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_connection(self):
        """discard 不存在的连接不报错"""
        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = _MockWebSocket()
        await mgr.disconnect(ws)  # should not raise
        assert mgr.count == 0
