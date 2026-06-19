"""
api/ws_scheduler.py 单元测试
覆盖: WebSocket 端点 (/ws/scheduler) 完整生命周期:
      连接/断开、订阅/退订、ping/pong、异常处理
      广播辅助函数: broadcast_task_update, broadcast_health_update
"""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def app():
    """创建仅包含 ws_scheduler router 的 FastAPI app"""
    app = FastAPI()
    from api.ws_scheduler import router as ws_router

    app.include_router(ws_router, prefix="/ws")
    return app


@pytest.fixture
def client(app):
    """FastAPI TestClient"""
    return TestClient(app)


class TestSchedulerWsEndpoint:
    """WebSocket 端点 /ws/scheduler 全生命周期测试"""

    def test_welcome_on_connect(self, client):
        """连接后收到欢迎消息"""
        with client.websocket_connect("/ws/scheduler") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["service"] == "ai-scheduler"
            assert "timestamp" in data

    def test_subscribe_action(self, client):
        """订阅主题"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome
            ws.send_json({"action": "subscribe", "topic": "task_update"})
            data = ws.receive_json()
            assert data["type"] == "subscribed"
            assert data["data"]["topic"] == "task_update"

    def test_unsubscribe_action(self, client):
        """退订主题（不应抛出异常）"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome
            # 先订阅，再退订
            ws.send_json({"action": "subscribe", "topic": "task_update"})
            ws.receive_json()  # consume subscribed
            ws.send_json({"action": "unsubscribe", "topic": "task_update"})
            # 退订后无响应，只需不抛出异常

    def test_unsubscribe_without_subscribing(self, client):
        """退订未订阅的主题不应抛出异常"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome
            # 直接退订一个从未订阅的主题
            ws.send_json({"action": "unsubscribe", "topic": "nonexistent"})
            # 应静默处理

    def test_ping_pong(self, client):
        """发送 ping 收到 pong"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"
            assert "timestamp" in data

    def test_subscribe_multiple_topics(self, client):
        """订阅多个主题"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome

            ws.send_json({"action": "subscribe", "topic": "task_update"})
            ws.receive_json()  # consume subscribed

            ws.send_json({"action": "subscribe", "topic": "health_update"})
            data = ws.receive_json()
            assert data["type"] == "subscribed"
            assert data["data"]["topic"] == "health_update"

    def test_invalid_json_silently_ignored(self, client):
        """非法 JSON 被静默忽略"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome
            ws.send_text("{{{invalid json}}")
            # 应该静默忽略，连接仍可用
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_unknown_action_silently_ignored(self, client):
        """未知 action 被静默忽略"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome
            ws.send_json({"action": "foobar"})
            # 应该静默忽略，连接仍可用
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_subscribe_without_topic_ignored(self, client):
        """subscribe 不带 topic 不处理"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome
            ws.send_json({"action": "subscribe"})  # no "topic" key
            # 应静默忽略
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_unsubscribe_without_topic_ignored(self, client):
        """unsubscribe 不带 topic 不处理"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome
            ws.send_json({"action": "unsubscribe"})  # no "topic" key
            # 应静默忽略
            ws.send_json({"action": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_connect_then_close(self, client):
        """连接后关闭，不应抛出异常"""
        with client.websocket_connect("/ws/scheduler") as ws:
            ws.receive_json()  # consume welcome
        # 退出 context manager 自动关闭连接

    def test_multiple_connections(self, client):
        """多个并发连接"""
        from api.ws_scheduler import ws_manager

        initial_count = ws_manager.count
        with (
            client.websocket_connect("/ws/scheduler") as ws1,
            client.websocket_connect("/ws/scheduler") as ws2,
        ):
            ws1.receive_json()  # consume welcome
            ws2.receive_json()  # consume welcome
            assert ws_manager.count >= initial_count + 2

            ws1.send_json({"action": "subscribe", "topic": "task_update"})
            ws1.receive_json()

            ws2.send_json({"action": "subscribe", "topic": "health_update"})
            ws2.receive_json()

        # 断开后连接数减少
        # 注意：由于 disconnect 是异步且可能未完成，这里不做严格断言


class TestWebSocketErrorHandling:
    """WebSocket 意外异常处理测试（覆盖 line 61-66 外层 except Exception）"""

    def test_exception_during_receive_caught_by_outer_handler(self, client):
        """receive_text 抛出非 WebSocketDisconnect 异常 → 外层 except Exception 捕获"""
        import starlette.websockets

        async def broken_receive_text(ws_self):
            raise RuntimeError("模拟非预期崩溃")

        with patch.object(
            starlette.websockets.WebSocket, "receive_text", broken_receive_text
        ):
            with client.websocket_connect("/ws/scheduler") as ws:
                # 收欢迎消息（connect 阶段正常）
                data = ws.receive_json()
                assert data["type"] == "connected"

            # 退出 context manager 自动 close，handler 内部应由外层 except Exception 兜底
            # 不抛出任何异常到测试层即为通过

    def test_exception_in_disconnect_also_caught(self, client):
        """外层 except Exception 中的 disconnect 二次异常也被捕获（覆盖 line 65-66）"""
        from api.ws_scheduler import ws_manager

        original_disconnect = ws_manager.disconnect

        async def broken_disconnect(ws):
            raise RuntimeError("disconnect 也崩溃了")

        async def broken_receive_text(ws_self):
            raise RuntimeError("模拟崩溃")

        import starlette.websockets

        with patch.object(starlette.websockets.WebSocket, "receive_text", broken_receive_text):
            with patch.object(ws_manager, "disconnect", broken_disconnect):
                with client.websocket_connect("/ws/scheduler") as ws:
                    ws.receive_json()  # welcome
                # disconnect 会抛，但被内层 try/except 吃掉
                # 不抛出异常到测试层即为通过


class TestBroadcastFunctions:
    """broadcast_* 广播辅助函数测试"""

    @pytest.mark.asyncio
    async def test_broadcast_task_update_basic(self):
        """broadcast_task_update 基本调用"""
        with patch("api.ws_scheduler.ws_manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock(return_value=3)
            from api.ws_scheduler import broadcast_task_update

            result = await broadcast_task_update(
                task_id="scan_001", task_name="选股扫描", status="running"
            )
            assert result == 3
            mock_mgr.broadcast.assert_called_once()
            args, kwargs = mock_mgr.broadcast.call_args
            # 第一个参数是 WSType
            assert args[0].value == "task_update"
            # 第二个参数是 data dict
            data = args[1]
            assert data["task_id"] == "scan_001"
            assert data["task_name"] == "选股扫描"
            assert data["status"] == "running"
            assert "detail" not in data

    @pytest.mark.asyncio
    async def test_broadcast_task_update_with_detail(self):
        """broadcast_task_update 带 detail 参数"""
        with patch("api.ws_scheduler.ws_manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock(return_value=1)
            from api.ws_scheduler import broadcast_task_update

            result = await broadcast_task_update(
                task_id="review_001",
                task_name="每日复盘",
                status="completed",
                detail="分析完成，共处理 50 只股票",
            )
            assert result == 1
            args = mock_mgr.broadcast.call_args[0]
            data = args[1]
            assert data["detail"] == "分析完成，共处理 50 只股票"

    @pytest.mark.asyncio
    async def test_broadcast_task_update_without_detail_empty(self):
        """broadcast_task_update detail=None 时不包含 detail 字段"""
        with patch("api.ws_scheduler.ws_manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock(return_value=0)
            from api.ws_scheduler import broadcast_task_update

            await broadcast_task_update(
                task_id="scan_002", task_name="选股扫描", status="failed", detail=None
            )
            args = mock_mgr.broadcast.call_args[0]
            data = args[1]
            assert "detail" not in data

    @pytest.mark.asyncio
    async def test_broadcast_health_update_basic(self):
        """broadcast_health_update 基本调用"""
        with patch("api.ws_scheduler.ws_manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock(return_value=5)
            from api.ws_scheduler import broadcast_health_update

            services = {"strategy-service": True, "execution-service": True}
            result = await broadcast_health_update(services=services, all_healthy=True)
            assert result == 5
            args = mock_mgr.broadcast.call_args[0]
            assert args[0].value == "health_update"
            data = args[1]
            assert data["services"] == services
            assert data["all_healthy"] is True

    @pytest.mark.asyncio
    async def test_broadcast_health_update_not_healthy(self):
        """broadcast_health_update all_healthy=False"""
        with patch("api.ws_scheduler.ws_manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock(return_value=2)
            from api.ws_scheduler import broadcast_health_update

            services = {"strategy-service": True, "execution-service": False}
            result = await broadcast_health_update(services=services, all_healthy=False)
            assert result == 2
            args = mock_mgr.broadcast.call_args[0]
            data = args[1]
            assert data["all_healthy"] is False

    @pytest.mark.asyncio
    async def test_broadcast_health_update_empty_services(self):
        """broadcast_health_update 空服务字典"""
        with patch("api.ws_scheduler.ws_manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock(return_value=0)
            from api.ws_scheduler import broadcast_health_update

            result = await broadcast_health_update(services={}, all_healthy=True)
            assert result == 0
            args = mock_mgr.broadcast.call_args[0]
            data = args[1]
            assert data["services"] == {}
            assert data["all_healthy"] is True
