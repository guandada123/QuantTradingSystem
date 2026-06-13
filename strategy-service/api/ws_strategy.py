"""
Strategy-service WebSocket: 指数行情/交易信号实时推送

端点: /ws/strategy
消息类型:
  - index_update:  指数行情推送（每3秒）
  - signal_update: 交易信号推送
"""

import asyncio
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
ws_manager = ConnectionManager(service=ServiceName.STRATEGY)

# ─── WebSocket 端点 ───────────────────────────────────────────────────


async def strategy_ws_handler(ws: WebSocket):
    """策略服务 WebSocket 处理函数（可被 router 和旧版 /ws 复用）"""
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                topic = msg.get("topic")
                ts_code = msg.get("ts_code")

                if action == "subscribe":
                    if topic:
                        ws_manager.subscribe(ws, topic)
                        await ws.send_json(
                            build_message(
                                WSType.SUBSCRIBED,
                                {"topic": topic, "message": f"已订阅 {topic}"},
                                ServiceName.STRATEGY,
                            )
                        )
                    elif ts_code:
                        # 兼容旧的订阅格式（按股票代码）
                        ws_manager.subscribe(ws, f"stock:{ts_code}")
                        await ws.send_json(
                            {
                                "type": "subscribed",
                                "ts_code": ts_code,
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        )
                    else:
                        ws_manager.subscribe(ws, "all")
                        await ws.send_json(
                            build_message(
                                WSType.SUBSCRIBED,
                                {"topic": "all", "message": "已订阅全部"},
                                ServiceName.STRATEGY,
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
        logger.error(f"[WS:strategy] 异常断开: {e}")
        try:
            ws_manager.disconnect(ws)
        except Exception:
            pass


@router.websocket("/strategy")
async def strategy_ws_route(ws: WebSocket):
    """策略服务实时数据通道"""
    await strategy_ws_handler(ws)


# ─── 广播辅助函数 ──────────────────────────────────────────────────────


async def broadcast_index_update(indices: list) -> int:
    """广播指数行情"""
    return await ws_manager.broadcast(WSType.INDEX_UPDATE, {"indices": indices})


async def broadcast_signal_update(
    ts_code: str, action: str, price: float, confidence: float, reason: str
) -> int:
    """广播交易信号"""
    return await ws_manager.broadcast(
        WSType.SIGNAL_UPDATE,
        {
            "ts_code": ts_code,
            "action": action,
            "price": price,
            "confidence": confidence,
            "reason": reason,
        },
    )


# ─── 后台广播任务 ──────────────────────────────────────────────────────


async def run_index_broadcast_loop(ds_getter):
    """
    后台任务：定时广播指数行情。
    ds_getter 是一个可调用对象，返回 (DataService实例, 设置实例)。
    采用延迟注入方式，避免启动时循环引用。
    """
    while True:
        try:
            if ws_manager.count > 0:
                ds = ds_getter()
                instances = ds.get_index_realtime_quote()
                await broadcast_index_update(instances)
                logger.debug(f"[WS] 广播指数行情: {len(instances)}个指数, {ws_manager.count}个连接")
        except Exception as e:
            logger.error(f"[WS] 广播失败: {e}")
        await asyncio.sleep(3)
