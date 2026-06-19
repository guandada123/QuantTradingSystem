"""WebSocket protocol stubs"""
import asyncio
from enum import Enum
import json
from typing import Any

from fastapi import WebSocket


class ServiceName(str, Enum):
    STRATEGY = "strategy"
    MARKET = "market"


class WSType(str, Enum):
    SIGNAL = "signal"
    QUOTE = "quote"
    SYSTEM = "system"


def build_message(ws_type: WSType, data: dict) -> str:
    return json.dumps({"type": ws_type.value, "data": data}, ensure_ascii=False)


class ConnectionManager:
    def __init__(self, service: ServiceName = ServiceName.STRATEGY):
        self.service = service
        self._connections: dict[str, WebSocket] = {}
        self._on_count_change = None

    async def connect(self, ws: WebSocket, client_id: str = None):
        await ws.accept()
        cid = client_id or str(id(ws))
        self._connections[cid] = ws
        if self._on_count_change:
            self._on_count_change(len(self._connections))

    def disconnect(self, client_id: str):
        self._connections.pop(client_id, None)
        if self._on_count_change:
            self._on_count_change(len(self._connections))

    async def broadcast(self, message: str):
        dead = []
        for cid, ws in self._connections.items():
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    @property
    def active_count(self) -> int:
        return len(self._connections)

    @property
    def count(self) -> int:
        """Alias for active_count - compatibility."""
        return len(self._connections)
