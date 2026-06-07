"""
股票数据API路由
提供股票行情、基本面、技术指标等数据
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

router = APIRouter()

# 数据服务实例（延迟初始化）
data_service = None

def get_data_service():
    """获取数据服务实例"""
    global data_service
    if data_service is None:
        from services.data_service import DataService
        from core.config import settings
        data_service = DataService(tushare_token=settings.TUSHARE_TOKEN)
    return data_service

@router.get("/realtime/{ts_code}")
async def get_stock_realtime(ts_code: str):
    """
    获取股票实时行情
    例：GET /api/v1/stocks/realtime/600519.SH
    """
    try:
        ds = get_data_service()
        result = ds.get_stock_realtime_quote(ts_code)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到股票：{ts_code}")
        return {"code": 0, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/daily/{ts_code}")
async def get_stock_daily(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(default=100, le=365)
):
    """
    获取股票日行情数据
    例：GET /api/v1/stocks/daily/600519.SH?start_date=20260101&end_date=20260607
    """
    try:
        ds = get_data_service()
        result = ds.get_stock_daily_quote(ts_code, start_date, end_date, limit)
        return {"code": 0, "data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/minute/{ts_code}")
async def get_stock_minute(
    ts_code: str,
    freq: str = Query(default="1min", pattern="^(1min|5min|15min|30min|60min)$"),
    count: int = Query(default=240, le=480)
):
    """
    获取股票分钟级K线
    例：GET /api/v1/stocks/minute/600519.SH?freq=5min&count=100
    """
    try:
        ds = get_data_service()
        result = ds.get_stock_minute_quote(ts_code, freq, count)
        return {"code": 0, "data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/index/realtime")
async def get_index_realtime():
    """
    获取核心指数实时行情（参考金子塔网站顶部展示）
    返回上证/深证/创业板/科创50/北证50/沪深300/中证500/中证1000
    """
    try:
        ds = get_data_service()
        result = ds.get_index_realtime_quote()
        return {"code": 0, "data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/fundamental/{ts_code}")
async def get_stock_fundamental(ts_code: str):
    """
    获取股票基本面数据
    例：GET /api/v1/stocks/fundamental/600519.SH
    """
    try:
        ds = get_data_service()
        result = ds.get_stock_fundamental(ts_code)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到基本面数据：{ts_code}")
        return {"code": 0, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/money-flow/{ts_code}")
async def get_stock_money_flow(ts_code: str, days: int = 5):
    """
    获取股票资金流向数据
    例：GET /api/v1/stocks/money-flow/600519.SH?days=5
    """
    try:
        ds = get_data_service()
        result = ds.get_stock_money_flow(ts_code, days)
        return {"code": 0, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/northbound-flow")
async def get_northbound_flow(date: Optional[str] = None):
    """
    获取北向资金流向数据
    例：GET /api/v1/stocks/northbound-flow?date=20260607
    """
    try:
        ds = get_data_service()
        result = ds.get_northbound_money_flow(date)
        return {"code": 0, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pool")
async def get_stock_pool(
    industry: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, le=100)
):
    """
    获取股票池
    例：GET /api/v1/stocks/pool?industry=食品饮料&page=1&page_size=20
    """
    try:
        ds = get_data_service()
        # TODO: 从数据库中查询股票池
        return {"code": 0, "data": [], "total": 0, "page": page, "page_size": page_size}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
