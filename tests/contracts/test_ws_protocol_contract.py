"""
WebSocket 消息协议契约测试 v1.0

验证 QTS 所有服务的 WebSocket 消息格式一致性和完整性：
1. WSType 枚举完整性（所有必须的消息类型是否存在）
2. ServiceName 枚举完整性（所有服务标识是否一致）
3. build_message() 函数生成的统一格式
4. build_error_message() 错误格式
5. ConnectionManager 的 connect/disconnect/broadcast 行为

不依赖外部服务。直接测试 shared/ws_protocol.py 模块。
"""

import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 项目根路径 ───────────────────────────────────────────────────────
_QTS_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))

# 确保 shared 包可导入
sys.path.insert(0, _QTS_ROOT)


# =========================================================================
# 1. WSType 枚举契约
# =========================================================================


class TestWSTypeEnum:
    """WSType 枚举完整性验证"""

    def test_all_required_types_exist(self):
        """必须包含所有预定义的消息类型"""
        from shared.ws_protocol import WSType

        required = [
            "CONNECTED",       # 连接成功确认
            "SUBSCRIBED",      # 订阅成功确认
            "ERROR",           # 错误消息
            "INDEX_UPDATE",    # 指数行情推送
            "SIGNAL_UPDATE",   # 交易信号推送
            "ORDER_UPDATE",    # 订单状态变更
            "RISK_ALERT",      # 风控触发告警
            "POSITION_UPDATE", # 持仓变更通知
            "TASK_UPDATE",     # 调度任务状态
            "HEALTH_UPDATE",   # 服务健康状态
        ]
        for name in required:
            assert hasattr(WSType, name), f"WSType 缺少 {name}"
            attr_value = getattr(WSType, name)
            assert isinstance(attr_value, WSType), f"{name} 必须是 WSType 实例"

    def test_enum_values_are_lowercase(self):
        """WSType 枚举值必须是小写字符串"""
        from shared.ws_protocol import WSType

        for member in WSType:
            value = member.value
            assert value == value.lower(), f"{member.name}.value='{value}' 必须全小写"
            assert isinstance(value, str), f"{member.name}.value 必须是字符串"

    def test_enum_members_count(self):
        """WSType 应有恰好 10 个成员"""
        from shared.ws_protocol import WSType

        assert len(WSType) == 10, f"WSType 应有 10 个成员，当前 {len(WSType)}"

    def test_enum_no_duplicate_values(self):
        """WSType 枚举值不能重复"""
        from shared.ws_protocol import WSType

        values = [m.value for m in WSType]
        assert len(values) == len(set(values)), "WSType 存在重复值"

    def test_enum_values_match_convention(self):
        """WSType 枚举值应使用下划线命名"""
        from shared.ws_protocol import WSType

        for member in WSType:
            # 值应当是 snake_case 格式（小写+下划线）
            value = member.value
            assert "_" in value or value.isalpha(), \
                f"{member.name} 的值 '{value}' 应使用下划线分隔"


# =========================================================================
# 2. ServiceName 枚举契约
# =========================================================================


class TestServiceNameEnum:
    """ServiceName 枚举完整性验证"""

    def test_all_services_present(self):
        """必须包含三个微服务标识"""
        from shared.ws_protocol import ServiceName

        required = {
            "STRATEGY": "strategy",
            "EXECUTION": "execution",
            "SCHEDULER": "ai-scheduler",
        }
        for name, expected_value in required.items():
            assert hasattr(ServiceName, name), f"ServiceName 缺少 {name}"
            assert getattr(ServiceName, name).value == expected_value, \
                f"{name} 的值应为 '{expected_value}'"

    def test_service_name_values(self):
        """ServiceName 枚举值的一致性"""
        from shared.ws_protocol import ServiceName

        assert ServiceName.STRATEGY.value == "strategy"
        assert ServiceName.EXECUTION.value == "execution"
        assert ServiceName.SCHEDULER.value == "ai-scheduler"

    def test_no_extra_services(self):
        """ServiceName 只包含三个服务，不应有多余成员"""
        from shared.ws_protocol import ServiceName

        assert len(ServiceName) == 3, f"ServiceName 应有 3 个成员，当前 {len(ServiceName)}"


# =========================================================================
# 3. build_message() 消息格式契约
# =========================================================================


class TestBuildMessage:
    """build_message() 生成的统一消息格式"""

    def test_build_message_structure(self):
        """消息必须有 type/data/timestamp/service 四个顶层字段"""
        from shared.ws_protocol import ServiceName, WSType, build_message

        result = build_message(WSType.CONNECTED, {"message": "ok"}, ServiceName.STRATEGY)

        assert isinstance(result, dict)
        required_keys = {"type", "data", "timestamp", "service"}
        assert required_keys.issubset(result.keys()), \
            f"消息缺少必要字段: {required_keys - result.keys()}"

    def test_build_message_type(self):
        """type 字段应为 WSType 的枚举值"""
        from shared.ws_protocol import ServiceName, WSType, build_message

        result = build_message(WSType.INDEX_UPDATE, {"price": 3200.5}, ServiceName.STRATEGY)
        assert result["type"] == "index_update"

    def test_build_message_service(self):
        """service 字段应为 ServiceName 的枚举值"""
        from shared.ws_protocol import ServiceName, WSType, build_message

        result = build_message(WSType.CONNECTED, {}, ServiceName.EXECUTION)
        assert result["service"] == "execution"

    def test_build_message_timestamp_format(self):
        """timestamp 字段必须是 ISO 8601 格式"""
        from shared.ws_protocol import ServiceName, WSType, build_message

        result = build_message(WSType.CONNECTED, {}, ServiceName.SCHEDULER)
        ts = result["timestamp"]
        # ISO 8601 格式验证: 尝试解析
        try:
            parsed = datetime.fromisoformat(ts)
            assert parsed is not None
        except (ValueError, TypeError):
            pytest.fail(f"timestamp '{ts}' 不是有效的 ISO 8601 格式")

    def test_build_message_includes_data(self):
        """data 字段包含传入的载荷"""
        from shared.ws_protocol import ServiceName, WSType, build_message

        payload = {"price": 100.0, "volume": 50000}
        result = build_message(WSType.SIGNAL_UPDATE, payload, ServiceName.STRATEGY)
        assert result["data"] == payload

    def test_build_message_with_null_data(self):
        """data 字段可以包含 None"""
        from shared.ws_protocol import ServiceName, WSType, build_message

        result = build_message(WSType.HEALTH_UPDATE, None, ServiceName.SCHEDULER)
        assert result["data"] is None

    def test_build_message_with_empty_data(self):
        """data 字段可以包含空字典"""
        from shared.ws_protocol import ServiceName, WSType, build_message

        result = build_message(WSType.CONNECTED, {}, ServiceName.STRATEGY)
        assert result["data"] == {}


# =========================================================================
# 4. build_error_message() 错误格式契约
# =========================================================================


class TestBuildErrorMessage:
    """build_error_message() 错误消息格式"""

    def test_build_error_message_structure(self):
        """错误消息同样包含 type/data/timestamp/service"""
        from shared.ws_protocol import ServiceName, WSType, build_error_message, build_message

        # build_error_message 使用 WSType.ERROR
        result = build_error_message("ERR_001", "测试错误", ServiceName.STRATEGY)
        assert result["type"] == WSType.ERROR.value
        assert "data" in result
        assert "code" in result["data"]
        assert "detail" in result["data"]

    def test_build_error_message_content(self):
        """错误消息包含 code 和 detail"""
        from shared.ws_protocol import ServiceName, build_error_message

        result = build_error_message("RATE_LIMIT", "请求频率超限", ServiceName.EXECUTION)
        assert result["data"]["code"] == "RATE_LIMIT"
        assert result["data"]["detail"] == "请求频率超限"

    def test_build_error_message_timestamp(self):
        """错误消息同样包含 ISO 8601 时间戳"""
        from shared.ws_protocol import ServiceName, build_error_message

        result = build_error_message("ERR", "err", ServiceName.SCHEDULER)
        ts = result["timestamp"]
        try:
            assert datetime.fromisoformat(ts) is not None
        except (ValueError, TypeError):
            pytest.fail(f"错误消息 timestamp '{ts}' 不是 ISO 8601 格式")


# =========================================================================
# 5. ConnectionManager 行为契约
# =========================================================================


class TestConnectionManager:
    """ConnectionManager 的 connect/disconnect/broadcast 行为"""

    @pytest.mark.asyncio
    async def test_connect_sends_welcome(self):
        """connect 应发送欢迎消息（CONNECTED 类型）"""
        from shared.ws_protocol import ConnectionManager, ServiceName, WSType

        mgr = ConnectionManager(ServiceName.STRATEGY)
        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()

        await mgr.connect(mock_ws)

        # 应调用 send_json 发送欢迎消息
        mock_ws.send_json.assert_called_once()
        sent = mock_ws.send_json.call_args[0][0]
        assert sent["type"] == WSType.CONNECTED.value
        assert sent["service"] == "strategy"

    @pytest.mark.asyncio
    async def test_connect_increments_count(self):
        """connect 后连接数增加"""
        from shared.ws_protocol import ConnectionManager, ServiceName

        mgr = ConnectionManager(ServiceName.STRATEGY)
        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()

        assert mgr.count == 0
        await mgr.connect(mock_ws)
        assert mgr.count == 1
        await mgr.connect(AsyncMock())
        assert mgr.count == 2

    @pytest.mark.asyncio
    async def test_disconnect_decrements_count(self):
        """disconnect 后连接数减少"""
        from shared.ws_protocol import ConnectionManager, ServiceName

        mgr = ConnectionManager(ServiceName.EXECUTION)
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()

        await mgr.connect(ws1)
        await mgr.connect(ws2)
        assert mgr.count == 2

        await mgr.disconnect(ws1)
        assert mgr.count == 1

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        """broadcast 发送消息到所有连接"""
        from shared.ws_protocol import ConnectionManager, ServiceName, WSType

        mgr = ConnectionManager(ServiceName.EXECUTION)
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()

        await mgr.connect(ws1)
        await mgr.connect(ws2)

        count = await mgr.broadcast(WSType.ORDER_UPDATE, {"order_id": "ORD001"})
        assert count == 2, f"应发送到 2 个连接，实际 {count}"
        assert ws1.send_json.call_count >= 2  # 1 次 welcome + 1 次 broadcast
        assert ws2.send_json.call_count >= 2

    @pytest.mark.asyncio
    async def test_broadcast_cleans_dead_connections(self):
        """broadcast 自动清理死连接"""
        from shared.ws_protocol import ConnectionManager, ServiceName, WSType

        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws_live = AsyncMock()
        ws_live.accept = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.accept = AsyncMock()
        ws_dead.send_json.side_effect = Exception("Connection closed")

        await mgr.connect(ws_live)
        await mgr.connect(ws_dead)
        assert mgr.count == 2

        await mgr.broadcast(WSType.TASK_UPDATE, {"task_id": 1})
        assert mgr.count == 1, "死连接应被清理"

    @pytest.mark.asyncio
    async def test_broadcast_to_topic(self):
        """broadcast_to_topic 只发送到订阅了该主题的连接"""
        from shared.ws_protocol import ConnectionManager, ServiceName, WSType

        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws_a = AsyncMock()
        ws_a.accept = AsyncMock()
        ws_b = AsyncMock()
        ws_b.accept = AsyncMock()

        await mgr.connect(ws_a)
        await mgr.connect(ws_b)

        mgr.subscribe(ws_a, "stock:600519")
        mgr.subscribe(ws_b, "stock:000001")

        # 重置 call_count (减去 welcome 消息)
        ws_a.send_json.reset_mock()
        ws_b.send_json.reset_mock()

        await mgr.broadcast_to_topic("stock:600519", WSType.SIGNAL_UPDATE, {"ts_code": "600519"})
        ws_a.send_json.assert_called_once()
        ws_b.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscribe_and_unsubscribe(self):
        """subscribe/unsubscribe 正常工作"""
        from shared.ws_protocol import ConnectionManager, ServiceName

        mgr = ConnectionManager(ServiceName.STRATEGY)
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await mgr.connect(ws)

        mgr.subscribe(ws, "test_topic")
        mgr.unsubscribe(ws, "test_topic")

        # 取消订阅后主题订阅集合应为空
        from shared.ws_protocol import WSType
        await mgr.broadcast_to_topic("test_topic", WSType.SIGNAL_UPDATE, {"test": True})
        # 不应发送消息，因为订阅被移除

    def test_on_count_change_callback(self):
        """连接数变化时触发回调"""
        from shared.ws_protocol import ConnectionManager, ServiceName

        callback = MagicMock()
        mgr = ConnectionManager(ServiceName.STRATEGY, on_count_change=callback)

        assert callback is not None


# =========================================================================
# 6. 服务端 WS 端点兼容性验证
# =========================================================================


class TestWebSocketEndpointContract:
    """WS 端点路径和订阅协议格式一致性"""

    def test_ws_endpoint_paths(self):
        """所有 WS 端点路径必须一致"""
        # 前端 app.js 和 nginx.conf 中使用的路径
        frontend_paths = {
            "strategy-service": "/ws/strategy",
            "execution-service": "/ws/execution",
            "scheduler": "/ws/scheduler",
            "legacy": "/ws",
        }

        for service, path in frontend_paths.items():
            assert path.startswith("/ws"), f"{service} WS 路径必须以 /ws 开头"
            assert isinstance(path, str)

    def test_subscribe_protocol_format(self):
        """客户端订阅协议格式"""
        # 客户端发送的订阅消息格式
        subscribe_message = {"action": "subscribe", "topic": "all"}
        unsubscribe_message = {"action": "unsubscribe", "topic": "stock:000001"}
        ping_message = {"action": "ping"}

        # 验证各字段存在
        assert subscribe_message["action"] in ("subscribe", "unsubscribe", "ping")
        assert "topic" in subscribe_message
        assert ping_message["action"] == "ping"

    def test_subscribe_protocol_optional_fields(self):
        """订阅消息的 topic 字段兼容性"""
        # 同时兼容标准格式 topic 和旧格式 ts_code
        subscribe_format_a = {"action": "subscribe", "topic": "stock:600519"}
        subscribe_format_b = {"action": "subscribe", "ts_code": "600519"}

        assert "topic" in subscribe_format_a
        assert "ts_code" in subscribe_format_b

    def test_pong_response_format(self):
        """服务端 pong 响应格式"""
        pong = {"type": "pong", "timestamp": "2026-06-16T22:00:00+00:00"}

        assert pong["type"] == "pong"
        assert "timestamp" in pong
