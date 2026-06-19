"""
Stock-related API routes for the Strategy Research Service.

Provides endpoints for:
- Stock pool management
- Stock fundamental data queries
- Real-time quotes (index + individual)
- K-line data
"""

from fastapi import APIRouter, HTTPException
from shared.exceptions import DataSourceException
from shared.structured_log import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Stocks"])


def _get_data_service():
    """延迟获取 DataService 实例。"""
    from core.config import settings
    from services.data_service import DataService

    return DataService(tushare_token=settings.TUSHARE_TOKEN or None)


@router.get("/pool")
async def get_stock_pool():
    """获取当前股票池。"""
    try:
        ds = _get_data_service()
        pool = ds.get_stock_pool(limit=50)
        logger.info("获取股票池成功", count=len(pool))
        return {"code": 0, "data": pool, "total": len(pool)}
    except DataSourceException:
        raise
    except Exception as e:
        logger.error("获取股票池失败", error=str(e))
        raise HTTPException(status_code=500, detail=f"获取股票池失败: {str(e)}")


@router.get("/index/realtime")
async def get_index_realtime():
    """获取核心大盘指数实时行情。"""
    try:
        ds = _get_data_service()
        data = ds.get_index_realtime_quote()
        logger.info("获取指数行情成功", count=len(data))
        return {"code": 0, "data": data}
    except DataSourceException:
        raise
    except Exception as e:
        logger.error("获取指数行情失败", error=str(e))
        raise HTTPException(status_code=500, detail=f"获取指数行情失败: {str(e)}")


@router.get("/realtime/{ts_code}")
async def get_realtime_quote(ts_code: str):
    """获取个股实时行情。"""
    try:
        ds = _get_data_service()
        data = ds.get_stock_realtime_quote(ts_code)
        logger.info("获取个股行情成功", ts_code=ts_code)
        return {"code": 0, "data": data}
    except DataSourceException:
        raise
    except Exception as e:
        logger.error("获取个股行情失败", ts_code=ts_code, error=str(e))
        raise HTTPException(status_code=500, detail=f"获取个股行情失败: {str(e)}")


@router.get("/{ts_code}")
async def get_stock_detail(ts_code: str):
    """获取个股基本面数据。"""
    try:
        ds = _get_data_service()
        fundamentals = ds.get_stock_fundamental(ts_code)
        logger.info("获取个股基本面成功", ts_code=ts_code)
        return {"code": 0, "data": {"ts_code": ts_code, "fundamentals": fundamentals}}
    except DataSourceException:
        raise
    except Exception as e:
        logger.error("获取个股基本面失败", ts_code=ts_code, error=str(e))
        raise HTTPException(status_code=500, detail=f"获取个股基本面失败: {str(e)}")


@router.get("/{ts_code}/kline")
async def get_kline_data(
    ts_code: str,
    period: str = "daily",
    limit: int = 100,
):
    """获取 K 线数据。"""
    from datetime import datetime, timedelta

    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=limit * 2)).strftime("%Y%m%d")
        ds = _get_data_service()
        data = ds.get_stock_daily_quote(ts_code, start, end, limit=limit)
        logger.info("获取K线成功", ts_code=ts_code, period=period, count=len(data))
        return {"code": 0, "data": data, "count": len(data)}
    except DataSourceException:
        raise
    except Exception as e:
        logger.error("获取K线失败", ts_code=ts_code, error=str(e))
        raise HTTPException(status_code=500, detail=f"获取K线失败: {str(e)}")
