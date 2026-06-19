"""
数据源配置 API
支持运行时查询和切换数据源
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.exceptions import DataSourceException
from shared.structured_log import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["数据源配置"])


class DataSourceSwitch(BaseModel):
    """数据源切换请求"""

    source: str  # tdx / tushare / akshare


@router.get("/config/data-source")
async def get_data_source() -> dict[str, Any]:
    """获取当前数据源状态"""
    try:
        from core.config import settings
        from services.data_service import DataService

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        current = getattr(ds, "_factory", None)
        current_source = current._default_source if current else settings.QTS_DATA_SOURCE

        return {
            "current_source": current_source,
            "available_sources": ["tdx", "tushare", "akshare"],
            "configured_sources": {
                "tushare": bool(settings.TUSHARE_TOKEN),
                "tdx_http": bool(settings.TDX_CONNECTOR_URL),
                "tdx_mcp": bool(settings.TDX_MCP_CMD),
            },
        }
    except DataSourceException:
        raise
    except Exception as e:
        logger.error("获取数据源状态失败", error=str(e))
        raise HTTPException(status_code=500, detail=f"获取数据源状态失败: {str(e)}")


@router.post("/config/data-source")
async def set_data_source(body: DataSourceSwitch) -> dict[str, Any]:
    """切换数据源"""
    try:
        from core.config import settings
        from services.data_service import DataService

        valid_sources = {"tdx", "tushare", "akshare"}
        if body.source not in valid_sources:
            raise HTTPException(
                status_code=400,
                detail=f"数据源 '{body.source}' 无效，可选: {', '.join(sorted(valid_sources))}",
            )

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        ds.set_data_source(body.source)

        logger.info("数据源已切换", source=body.source)
        return {
            "status": "ok",
            "current_source": body.source,
            "message": f"数据源已切换为 {body.source}",
        }
    except DataSourceException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error("切换数据源失败", source=body.source, error=str(e))
        raise HTTPException(status_code=500, detail=f"切换数据源失败: {str(e)}")
