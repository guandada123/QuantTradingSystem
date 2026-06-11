"""
Stock-related API routes for the Strategy Research Service.

Provides endpoints for:
- Stock pool management
- Stock fundamental data queries
- Real-time quotes (index + individual)
- K-line data
"""

import logging
from fastapi import APIRouter, Query
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Stocks"])


def _get_data_service():
    """延迟获取 DataService 实例。"""
    from services.data_service import DataService
    from core.config import settings
    return DataService(tushare_token=settings.TUSHARE_TOKEN or None)


@router.get("/pool")
async def get_stock_pool():
    """获取当前股票池。"""
    ds = _get_data_service()
    pool = ds.get_stock_pool(limit=50)
    return {"code": 0, "data": pool, "total": len(pool)}


@router.get("/index/realtime")
async def get_index_realtime():
    """获取核心大盘指数实时行情。"""
    ds = _get_data_service()
    data = ds.get_index_realtime_quote()
    return {"code": 0, "data": data}


@router.get("/realtime/{ts_code}")
async def get_realtime_quote(ts_code: str):
    """获取个股实时行情。"""
    ds = _get_data_service()
    data = ds.get_stock_realtime_quote(ts_code)
    return {"code": 0, "data": data}


@router.get("/{ts_code}")
async def get_stock_detail(ts_code: str):
    """获取个股基本面数据。"""
    ds = _get_data_service()
    fundamentals = ds.get_stock_fundamental(ts_code)
    return {"code": 0, "data": {"ts_code": ts_code, "fundamentals": fundamentals}}


@router.get("/{ts_code}/kline")
async def get_kline_data(
    ts_code: str,
    period: str = "daily",
    limit: int = 100,
):
    """获取 K 线数据。"""
    from datetime import datetime, timedelta
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=limit * 2)).strftime("%Y%m%d")
    ds = _get_data_service()
    data = ds.get_stock_daily_quote(ts_code, start, end, limit=limit)
    return {"code": 0, "data": data, "count": len(data)}
