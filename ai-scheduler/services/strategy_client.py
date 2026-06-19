"""
策略服务客户端 — 通过 HTTP 调用 strategy-service
提供选股扫描和策略配置查询能力
"""

import logging
from typing import Any

import httpx

from core.config import settings
from shared.middleware import get_trace_headers

logger = logging.getLogger(__name__)


class StrategyClient:
    """strategy-service HTTP 客户端

    封装与策略服务的所有 HTTP 通信，自动传播 trace_id。
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int = 30,
    ):
        self.base_url = (base_url or settings.STRATEGY_SERVICE_URL).rstrip("/")
        self.timeout = timeout

    async def scan_stocks(
        self,
        limit: int = 100,
        strategy_ids: list[str] | None = None,
        ts_codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """调用策略服务执行选股扫描

        Args:
            limit: 返回候选股票上限
            strategy_ids: 要使用的策略 ID 列表（None=全部）
            ts_codes: 要扫描的股票代码列表（None=全市场）

        Returns:
            候选股票列表，每项包含 ts_code/name/price 等字段

        Raises:
            httpx.HTTPError: HTTP 调用失败
        """
        params: dict[str, Any] = {"limit": limit}
        if strategy_ids:
            params["strategy_ids"] = strategy_ids
        if ts_codes:
            params["ts_codes"] = ts_codes

        headers = {
            **(get_trace_headers() or {}),
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/strategies/scan",
                json=params,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            # 兼容不同响应格式
            return data.get("data", data.get("results", []))

    async def get_strategy_config(self, strategy_id: str) -> dict[str, Any]:
        """获取策略配置详情

        Args:
            strategy_id: 策略 ID（如 "ma-cross"、"breakout"）

        Returns:
            策略配置字典

        Raises:
            httpx.HTTPError: HTTP 调用失败
            ValueError: 策略不存在
        """
        headers = {
            **(get_trace_headers() or {}),
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/strategies/{strategy_id}",
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", data)
