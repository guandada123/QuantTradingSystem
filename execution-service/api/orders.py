"""
订单管理API路由 — 使用 DB 依赖注入
"""

from enum import Enum
import logging

from core.config import settings
from core.constants import DEFAULT_ACCOUNT_ID
from fastapi import APIRouter, Depends, HTTPException, Query
from models.database import get_db_session
from pydantic import BaseModel
from services.order_manager import OrderManager
from services.risk_controller import RiskController
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter()


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderRequest(BaseModel):
    """统一订单请求体 — 同时用于创建和提交"""

    account_id: str = DEFAULT_ACCOUNT_ID
    ts_code: str
    direction: Direction  # BUY/SELL
    order_type: str = "LIMIT"  # LIMIT/MARKET/STOP
    price: float | None = None
    quantity: int = 100
    strategy_name: str | None = None
    trigger_price: float | None = None  # STOP条件单触发价


# ─── 工厂方法 ───────────────────────────────────────────────


def _build_risk_ctrl(db: Session, account_id: str) -> RiskController:
    """从 settings 构建标准 RiskController"""
    return RiskController(
        db=db,
        max_position_ratio=settings.MAX_POSITION_RATIO,
        max_total_positions=settings.MAX_TOTAL_POSITIONS,
        stop_loss_ratio=settings.STOP_LOSS_RATIO,
        take_profit_ratio=settings.TAKE_PROFIT_RATIO,
        max_daily_loss=settings.MAX_DAILY_LOSS,
        account_id=account_id,
    )


def _build_order_mgr(db: Session, account_id: str = DEFAULT_ACCOUNT_ID) -> OrderManager:
    """构建标准 OrderManager"""
    return OrderManager(db=db, account_id=account_id)


def _do_risk_check(risk_ctrl: RiskController, req: OrderRequest) -> dict | None:
    """
    执行风控前置检查，返回风控结果 dict（含 code/message/data）或 None（通过）
    """
    if req.price:
        risk_result = risk_ctrl.pre_trade_check(req.ts_code, req.direction, req.quantity, req.price)
        if not risk_result["allowed"]:
            return {"code": -1, "message": "风控拦截", "data": risk_result}
    return None


def _do_create_order(mgr: OrderManager, req: OrderRequest):
    """创建订单（内部逻辑，不直接返回 HTTP）"""
    return mgr.create_order(
        ts_code=req.ts_code,
        direction=req.direction,
        order_type=req.order_type,
        price=req.price,
        quantity=req.quantity,
        strategy_name=req.strategy_name,
        trigger_price=req.trigger_price,
    )


# ─── 路由 ─────────────────────────────────────────────────────


@router.post("/")
async def create_order(req: OrderRequest, db: Session = Depends(get_db_session)):
    """
    创建订单
    POST /api/v1/orders/
    """
    try:
        blocked = _do_risk_check(_build_risk_ctrl(db, req.account_id), req)
        if blocked:
            return blocked

        order = _do_create_order(_build_order_mgr(db, req.account_id), req)

        return {
            "code": 0,
            "data": {
                "order_id": order.order_id,
                "status": order.status.value,
                "ts_code": req.ts_code,
                "direction": req.direction,
                "order_type": req.order_type,
                "price": req.price,
                "quantity": req.quantity,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("订单操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.post("/submit")
async def submit_order(req: OrderRequest, db: Session = Depends(get_db_session)):
    """
    提交订单（创建+立即执行）
    POST /api/v1/orders/submit
    """
    try:
        blocked = _do_risk_check(_build_risk_ctrl(db, req.account_id), req)
        if blocked:
            return blocked

        mgr = _build_order_mgr(db, req.account_id)
        order = _do_create_order(mgr, req)
        exec_result = mgr.execute_order(order.order_id)

        return {
            "code": 0,
            "data": {
                "order_id": order.order_id,
                "status": "FILLED" if exec_result["success"] else "REJECTED",
                "ts_code": req.ts_code,
                "direction": req.direction,
                "order_type": req.order_type,
                "price": req.price,
                "quantity": req.quantity,
                "execution": exec_result,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("订单操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.post("/{order_id}/execute")
async def execute_order(order_id: str, db: Session = Depends(get_db_session)):
    """执行挂起的订单"""
    try:
        mgr = _build_order_mgr(db)
        result = mgr.execute_order(order_id)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return {"code": 0, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("订单操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.post("/{order_id}/cancel")
async def cancel_order(order_id: str, db: Session = Depends(get_db_session)):
    """撤销订单"""
    try:
        mgr = _build_order_mgr(db)
        success = mgr.cancel_order(order_id)
        if not success:
            raise HTTPException(status_code=400, detail="无法撤销订单（可能已成交或不存在）")
        return {"code": 0, "data": {"order_id": order_id, "status": "CANCELLED"}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("订单操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.get("/")
async def list_orders(
    db: Session = Depends(get_db_session),
    account_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=20, le=100),
):
    """查询订单列表"""
    try:
        mgr = _build_order_mgr(db, account_id or DEFAULT_ACCOUNT_ID)
        orders = mgr.list_orders(status=status, limit=limit)
        return {"code": 0, "data": orders, "total": len(orders)}
    except Exception as e:
        logger.error("订单操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.get("/{order_id}")
async def get_order(order_id: str, db: Session = Depends(get_db_session)):
    """查询订单状态"""
    try:
        mgr = _build_order_mgr(db)
        order = mgr.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail=f"订单 {order_id} 不存在")
        return {"code": 0, "data": order}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("订单操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.get("/summary/daily")
async def daily_summary(db: Session = Depends(get_db_session)):
    """获取当日交易摘要"""
    try:
        mgr = _build_order_mgr(db)
        summary = mgr.get_daily_summary()
        return {"code": 0, "data": summary}
    except Exception as e:
        logger.error("订单操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.post("/stop/check")
async def check_stop_orders(db: Session = Depends(get_db_session)):
    """扫描STOP条件单并执行已触发的"""
    try:
        price_rows = (
            db.execute(
                text("SELECT ts_code, current_price FROM positions WHERE total_quantity > 0")
            )
            .mappings()
            .fetchall()
        )
        price_map = {
            r["ts_code"]: float(r["current_price"]) for r in price_rows if r["current_price"]
        }

        mgr = _build_order_mgr(db)
        triggered = mgr.check_stop_orders(price_map)
        return {"code": 0, "data": triggered, "total": len(triggered)}
    except Exception as e:
        logger.error("订单操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@router.post("/expire")
async def cancel_expired(db: Session = Depends(get_db_session)):
    """取消所有过期的限价单"""
    try:
        mgr = _build_order_mgr(db)
        count = mgr.cancel_expired_orders()
        return {"code": 0, "data": {"cancelled_count": count}}
    except Exception as e:
        logger.error("订单操作失败", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")
