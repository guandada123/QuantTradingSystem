"""
Ai-scheduler WebSocket: 任务状态/健康监控实时推送

端点: /ws/scheduler
消息类型:
  - task_update:  调度任务状态变更
  - health_update: 服务健康状态变更
"""

from datetime import UTC, datetime
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared.ws_protocol import (
    ConnectionManager,
    ServiceName,
    WSType,
    build_message,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── 全局连接管理器 ──────────────────────────────────────────────────
ws_manager = ConnectionManager(service=ServiceName.SCHEDULER)

# ─── WebSocket 端点 ───────────────────────────────────────────────────


@router.websocket("/scheduler")
async def scheduler_ws(ws: WebSocket):
    """AI调度器实时数据通道"""
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                topic = msg.get("topic")
                if action == "subscribe" and topic:
                    ws_manager.subscribe(ws, topic)
                    await ws.send_json(
                        build_message(
                            WSType.SUBSCRIBED,
                            {"topic": topic, "message": f"已订阅 {topic}"},
                            ServiceName.SCHEDULER,
                        )
                    )
                elif action == "unsubscribe" and topic:
                    ws_manager.unsubscribe(ws, topic)
                elif action == "ping":
                    await ws.send_json({"type": "pong", "timestamp": datetime.now(UTC).isoformat()})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception as e:
        logger.error(f"[WS:scheduler] 异常断开: {e}")
        try:
            ws_manager.disconnect(ws)
        except Exception:
            pass


# ─── 广播辅助函数 ──────────────────────────────────────────────────────


async def broadcast_task_update(
    task_id: str, task_name: str, status: str, detail: str | None = None
) -> int:
    """广播调度任务状态变更"""
    data = {"task_id": task_id, "task_name": task_name, "status": status}
    if detail:
        data["detail"] = detail
    return await ws_manager.broadcast(WSType.TASK_UPDATE, data)


async def broadcast_health_update(services: dict, all_healthy: bool) -> int:
    """广播服务健康状态"""
    return await ws_manager.broadcast(
        WSType.HEALTH_UPDATE,
        {"services": services, "all_healthy": all_healthy},
    )
