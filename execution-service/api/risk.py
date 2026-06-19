"""
风险控制API路由 — 使用 DB 依赖注入
"""

import logging

from core.config import settings
from fastapi import APIRouter, Depends, HTTPException, Query

# Prometheus metrics (from main module)
import main as main_module
from models.database import get_db_session
from services.risk_controller import RiskController, circuit_breaker
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/check/{ts_code}")
async def check_risk(
    ts_code: str,
    db: Session = Depends(get_db_session),
    action: str = "BUY",
    quantity: int = 100,
    price: float = 0,
):
    """
    检查交易风险
    例：GET /api/v1/risk/check/600519.SH?action=BUY&quantity=100&price=1800
    """
    try:
        controller = RiskController(
            db=db,
            max_position_ratio=settings.MAX_POSITION_RATIO,
            max_total_positions=settings.MAX_TOTAL_POSITIONS,
            stop_loss_ratio=settings.STOP_LOSS_RATIO,
            take_profit_ratio=settings.TAKE_PROFIT_RATIO,
            max_daily_loss=settings.MAX_DAILY_LOSS,
        )
        result = controller.pre_trade_check(ts_code, action, quantity, price)
        return {"code": 0, "data": result}
    except Exception as e:
        logger.error("风控操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.get("/monitor")
async def monitor_positions(db: Session = Depends(get_db_session)):
    """监控所有持仓止损/止盈（含自动执行）"""
    try:
        controller = RiskController(
            db=db,
            stop_loss_ratio=settings.STOP_LOSS_RATIO,
            take_profit_ratio=settings.TAKE_PROFIT_RATIO,
        )
        result = controller.monitor_positions()

        # 更新 Prometheus 指标
        for alert in result.get("alerts", []):
            event_type = alert.get("action", "UNKNOWN")
            severity = "HIGH" if event_type == "STOP_LOSS" else "MEDIUM"
            main_module.risk_events_total.labels(event_type=event_type, level=severity).inc()
        for executed in result.get("executed", []):
            main_module.risk_events_total.labels(
                event_type=executed.get("action", "EXECUTED"), level="HIGH"
            ).inc()

        # 更新熔断器状态
        cb_status = circuit_breaker.status
        main_module.circuit_breaker_open.set(1 if cb_status["is_open"] else 0)

        return {"code": 0, "data": result}
    except Exception as e:
        logger.error("风控操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.get("/events")
async def get_risk_events(
    db: Session = Depends(get_db_session), limit: int = Query(default=20, le=100)
):
    """获取风险事件列表"""
    try:
        controller = RiskController(db=db)
        events = controller.get_risk_events(limit=limit)
        return {"code": 0, "data": events, "total": len(events)}
    except Exception as e:
        logger.error("风控操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.get("/settings")
async def get_risk_settings():
    """获取当前风控参数"""
    return {
        "code": 0,
        "data": {
            "max_position_ratio": settings.MAX_POSITION_RATIO,
            "max_total_positions": settings.MAX_TOTAL_POSITIONS,
            "stop_loss_ratio": settings.STOP_LOSS_RATIO,
            "take_profit_ratio": settings.TAKE_PROFIT_RATIO,
            "max_daily_loss": settings.MAX_DAILY_LOSS,
            "auto_execute_stop_loss": settings.AUTO_EXECUTE_STOP_LOSS,
            "auto_execute_take_profit": settings.AUTO_EXECUTE_TAKE_PROFIT,
            "order_expiry_days": settings.ORDER_EXPIRY_DAYS,
            "circuit_breaker": circuit_breaker.status,
        },
    }


@router.get("/circuit-breaker")
async def get_circuit_breaker():
    """查询熔断器状态"""
    return {"code": 0, "data": circuit_breaker.status}


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker():
    """手动重置熔断器"""
    circuit_breaker.reset()
    return {"code": 0, "data": {"message": "熔断器已重置", "status": circuit_breaker.status}}
