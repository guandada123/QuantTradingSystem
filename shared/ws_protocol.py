"""
WebSocket 标准化消息协议 v1.0

统一所有服务间的 WebSocket 消息格式和行为。

消息格式:
{
    "type": "message_type",   # 消息类型 (WSType enum)
    "data": {...},             # 消息载荷
    "timestamp": "ISO8601",    # 服务器时间戳
    "service": "service_name"  # 源服务标识
}

消息类型:
- index_update:  指数行情推送 (strategy-service)
- signal_update:  交易信号推送 (strategy-service)
- order_update:   订单状态变更 (execution-service)
- risk_alert:     风控触发告警 (execution-service)
- position_update:持仓变更通知 (execution-service)
- task_update:    调度任务状态 (ai-scheduler)
- health_update:  服务健康状态 (ai-scheduler)
- connected:      连接成功确认
- subscribed:     订阅成功确认
- error:          错误消息
"""
import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Set, Dict, Any, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─── 消息类型枚举 ────────────────────────────────────────────────────

class WSType(str, Enum):
    """标准化的 WebSocket 消息类型"""

    # 连接生命周期
    CONNECTED = "connected"
    SUBSCRIBED = "subscribed"
    ERROR = "error"

    # strategy-service 推送
    INDEX_UPDATE = "index_update"
    SIGNAL_UPDATE = "signal_update"

    # execution-service 推送
    ORDER_UPDATE = "order_update"
    RISK_ALERT = "risk_alert"
    POSITION_UPDATE = "position_update"

    # ai-scheduler 推送
    TASK_UPDATE = "task_update"
    HEALTH_UPDATE = "health_update"


# ─── 服务标识 ────────────────────────────────────────────────────────

class ServiceName(str, Enum):
    STRATEGY = "strategy"
    EXECUTION = "execution"
    SCHEDULER = "ai-scheduler"


# ─── 消息构建工具 ─────────────────────────────────────────────────────

def build_message(msg_type: WSType, data: Any, service: ServiceName) -> dict:
    """构建标准化的 WebSocket 消息"""
    return {
        "type": msg_type.value,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": service.value,
    }


def build_error_message(code: str, detail: str, service: ServiceName) -> dict:
    """构建标准化的错误消息"""
    return build_message(WSType.ERROR, {"code": code, "detail": detail}, service)


# ─── 连接管理器 ────────────────────────────────────────────────────────

class ConnectionManager:
    """
    异步 WebSocket 连接管理器。

    特性:
    - 活跃连接集合管理
    - 全局广播
    - 主题订阅（按消息类型过滤）
    - 脏连接自动清理
    - 连接数指标回调
    """

    def __init__(self, service: ServiceName, on_count_change: Optional[Callable[[int], None]] = None):
        self.service = service
        self._connections: Set[Any] = set()          # 活跃 WebSocket 连接
        self._subscriptions: Dict[str, Set[Any]] = {}  # topic -> {ws, ...}
        self._on_count_change = on_count_change

    @property
    def count(self) -> int:
        return len(self._connections)

    async def connect(self, ws: Any) -> None:
        """接受新连接并发送欢迎消息"""
        await ws.accept()
        self._connections.add(ws)
        count = len(self._connections)
        logger.info(f"[WS:{self.service.value}] 连接建立，当前连接数: {count}")
        if self._on_count_change:
            self._on_count_change(count)

        # 发送欢迎消息
        welcome = build_message(
            WSType.CONNECTED,
            {"message": f"已连接 {self.service.value} 实时数据通道", "connections": count},
            self.service,
        )
        try:
            await ws.send_json(welcome)
        except Exception:
            pass

    async def disconnect(self, ws: Any) -> None:
        """断开连接并清理订阅"""
        self._connections.discard(ws)
        # 从所有主题订阅中移除
        for topic in self._subscriptions.values():
            topic.discard(ws)
        count = len(self._connections)
        logger.info(f"[WS:{self.service.value}] 连接断开，当前连接数: {count}")
        if self._on_count_change:
            self._on_count_change(count)

    async def broadcast(self, msg_type: WSType, data: Any) -> int:
        """广播消息到所有连接，返回成功发送数"""
        message = build_message(msg_type, data, self.service)
        dead: Set[Any] = set()
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            await self.disconnect(ws)
        success = len(self._connections) - len(dead)
        if dead:
            logger.warning(f"[WS:{self.service.value}] 广播清理 {len(dead)} 个死连接")
        return success

    async def broadcast_to_topic(self, topic: str, msg_type: WSType, data: Any) -> int:
        """广播消息到订阅了指定主题的连接"""
        message = build_message(msg_type, data, self.service)
        subscribers = self._subscriptions.get(topic, set())
        dead: Set[Any] = set()
        for ws in subscribers:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            subscribers.discard(ws)
            self._connections.discard(ws)
        return len(subscribers) - len(dead)

    def subscribe(self, ws: Any, topic: str) -> None:
        """为连接添加主题订阅"""
        if topic not in self._subscriptions:
            self._subscriptions[topic] = set()
        self._subscriptions[topic].add(ws)
        logger.debug(f"[WS:{self.service.value}] 连接订阅主题: {topic}")

    def unsubscribe(self, ws: Any, topic: str) -> None:
        """移除连接的主题订阅"""
        subscribers = self._subscriptions.get(topic)
        if subscribers:
            subscribers.discard(ws)
