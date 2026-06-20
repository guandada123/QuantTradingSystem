"""
Execution Service HTTP Client
Bridges strategy signals to order execution
"""

import logging
from typing import Any

from core.config import settings
import httpx

from shared.middleware import get_trace_headers

logger = logging.getLogger(__name__)

EXECUTION_BASE_URL = getattr(settings, "EXECUTION_SERVICE_URL", "http://execution-service:8001")


class ExecutionClient:
    """Client for execution-service API calls"""

    def __init__(self):
        self.base_url = EXECUTION_BASE_URL
        self.timeout = 10.0

    async def submit_order(
        self,
        account_id: str,
        ts_code: str,
        direction: str,
        order_type: str,
        price: float,
        quantity: int,
        strategy_name: str | None = None,
        source: str = "AUTO",
    ) -> dict[str, Any]:
        """Submit order to execution service"""
        payload = {
            "account_id": account_id,
            "ts_code": ts_code,
            "direction": direction,
            "order_type": order_type,
            "price": price,
            "quantity": quantity,
            "strategy_name": strategy_name,
            "source": source,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, headers=get_trace_headers()
            ) as client:
                resp = await client.post(f"{self.base_url}/api/v1/orders/submit", json=payload)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                return data
        except Exception as e:
            logger.error(f"Failed to submit order: {e}")
            return {"success": False, "error": str(e)}

    async def get_positions(self, account_id: str) -> dict[str, Any]:
        """Get current positions"""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, headers=get_trace_headers()
            ) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/positions/", params={"account_id": account_id}
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                return data
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return {"success": False, "error": str(e)}

    async def check_risk(self, ts_code: str) -> dict[str, Any]:
        """Pre-trade risk check"""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, headers=get_trace_headers()
            ) as client:
                resp = await client.get(f"{self.base_url}/api/v1/risk/check/{ts_code}")
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                return data
        except Exception as e:
            logger.error(f"Failed to check risk: {e}")
            return {"success": False, "error": str(e)}


# Singleton
execution_client = ExecutionClient()
