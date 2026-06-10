"""
数据源配置 API
支持运行时查询和切换数据源
"""
import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["数据源配置"])


class DataSourceSwitch(BaseModel):
    """数据源切换请求"""
    source: str  # tdx / tushare / akshare


@router.get("/config/data-source")
async def get_data_source() -> Dict[str, Any]:
    """获取当前数据源状态"""
    from services.data_service import DataService
    from core.config import settings

    ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
    current = getattr(ds, '_factory', None)
    current_source = current._default_source if current else settings.QTS_DATA_SOURCE

    return {
        'current_source': current_source,
        'available_sources': ['tdx', 'tushare', 'akshare'],
        'configured_sources': {
            'tushare': bool(settings.TUSHARE_TOKEN),
            'tdx_http': bool(settings.TDX_CONNECTOR_URL),
            'tdx_mcp': bool(settings.TDX_MCP_CMD),
        },
    }


@router.post("/config/data-source")
async def set_data_source(body: DataSourceSwitch) -> Dict[str, Any]:
    """切换数据源"""
    from services.data_service import DataService
    from core.config import settings

    valid_sources = {'tdx', 'tushare', 'akshare'}
    if body.source not in valid_sources:
        raise HTTPException(
            status_code=400,
            detail=f"数据源 '{body.source}' 无效，可选: {', '.join(sorted(valid_sources))}",
        )

    ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
    ds.set_data_source(body.source)

    logger.info(f"数据源已切换为: {body.source}")
    return {
        'status': 'ok',
        'current_source': body.source,
        'message': f"数据源已切换为 {body.source}",
    }
