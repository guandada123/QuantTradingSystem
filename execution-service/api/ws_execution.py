"""
Execution-service WebSocket: 实时订单/风控/持仓推送

端点: /ws/execution
消息类型:
  - order_update:  订单状态变更（创建/成交/拒绝/取消）
  - risk_alert:    风控触发通知
  - position_update: 持仓变更
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared.ws_protocol import (
    ConnectionManager, WSType, ServiceName, build_message, build_error_message,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── 全局连接管理器 ──────────────────────────────────────────────────
ws_manager = ConnectionManager(service=ServiceName.EXECUTION)

# ─── WebSocket 端点 ───────────────────────────────────────────────────

@router.websocket("/execution")
async def execution_ws(ws: WebSocket):
    """执行服务实时数据通道"""
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            import json
            try:
                msg = json.loads(data)
                action = msg.get("action")
                topic = msg.get("topic")
                if action == "subscribe" and topic:
                    ws_manager.subscribe(ws, topic)
                    await ws.send_json(build_message(
                        WSType.SUBSCRIBED,
                        {"topic": topic, "message": f"已订阅 {topic}"},
                        ServiceName.EXECUTION,
                    ))
                elif action == "unsubscribe" and topic:
                    ws_manager.unsubscribe(ws, topic)
                elif action == "ping":
                    await ws.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception as e:
        logger.error(f"[WS:execution] 异常断开: {e}")
        try:
            ws_manager.disconnect(ws)
        except Exception:
            pass


# ─── 广播辅助函数（供其他 API 模块调用） ──────────────────────────

async def broadcast_order_update(order_id: str, ts_code: str, direction: str,
                                 status: str, price: float, quantity: int) -> int:
    """广播订单状态变更"""
    return await ws_manager.broadcast(
        WSType.ORDER_UPDATE,
        {
            "order_id": order_id,
            "ts_code": ts_code,
            "direction": direction,
            "status": status,
            "price": price,
            "quantity": quantity,
        }
    )


async def broadcast_risk_alert(ts_code: str, risk_type: str, detail: str) -> int:
    """广播风控触发"""
    return await ws_manager.broadcast(
        WSType.RISK_ALERT,
        {"ts_code": ts_code, "risk_type": risk_type, "detail": detail}
    )


async def broadcast_position_update(ts_code: str, action: str,
                                    quantity: int, price: float) -> int:
    """广播持仓变更"""
    return await ws_manager.broadcast(
        WSType.POSITION_UPDATE,
        {"ts_code": ts_code, "action": action, "quantity": quantity, "price": price}
    )
