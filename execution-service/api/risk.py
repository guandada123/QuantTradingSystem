"""
风险控制API路由
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Dict, Any

router = APIRouter()

@router.get("/check/{ts_code}")
async def check_risk(ts_code: str, action: str = "BUY", quantity: int = 100):
    """
    检查交易风险
    例：GET /api/v1/risk/check/600519.SH?action=BUY&quantity=100
    """
    try:
        from services.risk_controller import RiskController
        from core.config import settings
        
        controller = RiskController(
            max_position_ratio=settings.MAX_POSITION_RATIO,
            max_total_positions=settings.MAX_TOTAL_POSITIONS
        )
        
        result = controller.check_trade_risk(ts_code, action, quantity, {})
        return {"code": 0, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/events")
async def get_risk_events(
    limit: int = Query(default=20, le=100)
):
    """获取风险事件列表"""
    return {"code": 0, "data": [], "total": 0}

@router.get("/settings")
async def get_risk_settings():
    """获取当前风控参数"""
    from core.config import settings
    return {
        "code": 0,
        "data": {
            "max_position_ratio": settings.MAX_POSITION_RATIO,
            "max_total_positions": settings.MAX_TOTAL_POSITIONS,
            "stop_loss_ratio": settings.STOP_LOSS_RATIO,
            "take_profit_ratio": settings.TAKE_PROFIT_RATIO,
            "max_daily_loss": settings.MAX_DAILY_LOSS
        }
    }
