"""
订单管理API路由 — 使用 DB 依赖注入
"""

from core.config import settings
from fastapi import APIRouter, Depends, HTTPException, Query
from models.database import get_db_session
from pydantic import BaseModel
from services.order_manager import OrderManager
from services.risk_controller import RiskController
from sqlalchemy import text
from sqlalchemy.orm import Session

router = APIRouter()


class CreateOrderRequest(BaseModel):
    account_id: str = "REAL_001"
    ts_code: str
    direction: str  # BUY/SELL
    order_type: str = "LIMIT"  # LIMIT/MARKET/STOP
    price: float | None = None
    quantity: int = 100
    strategy_name: str | None = None
    trigger_price: float | None = None  # STOP条件单触发价


class SubmitOrderRequest(BaseModel):
    account_id: str = "REAL_001"
    ts_code: str
    direction: str
    order_type: str = "LIMIT"
    price: float | None = None
    quantity: int = 100
    strategy_name: str | None = None
    trigger_price: float | None = None


@router.post("/")
async def create_order(req: CreateOrderRequest, db: Session = Depends(get_db_session)):
    """
    创建订单
    POST /api/v1/orders/
    """
    try:
        # 风控检查
        risk_ctrl = RiskController(
            db=db,
            max_position_ratio=settings.MAX_POSITION_RATIO,
            max_total_positions=settings.MAX_TOTAL_POSITIONS,
            stop_loss_ratio=settings.STOP_LOSS_RATIO,
            take_profit_ratio=settings.TAKE_PROFIT_RATIO,
            max_daily_loss=settings.MAX_DAILY_LOSS,
            account_id=req.account_id,
        )

        if req.price:
            risk_result = risk_ctrl.pre_trade_check(
                req.ts_code, req.direction, req.quantity, req.price
            )
            if not risk_result["allowed"]:
                return {"code": -1, "message": "风控拦截", "data": risk_result}

        # 创建订单
        mgr = OrderManager(db=db, account_id=req.account_id)
        order = mgr.create_order(
            ts_code=req.ts_code,
            direction=req.direction,
            order_type=req.order_type,
            price=req.price,
            quantity=req.quantity,
            strategy_name=req.strategy_name,
            trigger_price=req.trigger_price,
        )

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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/submit")
async def submit_order(req: SubmitOrderRequest, db: Session = Depends(get_db_session)):
    """
    提交订单（创建+立即执行）
    POST /api/v1/orders/submit
    Body: {ts_code, direction, order_type, price, quantity, trigger_price}
    """
    try:
        risk_ctrl = RiskController(
            db=db,
            max_position_ratio=settings.MAX_POSITION_RATIO,
            max_total_positions=settings.MAX_TOTAL_POSITIONS,
            stop_loss_ratio=settings.STOP_LOSS_RATIO,
            take_profit_ratio=settings.TAKE_PROFIT_RATIO,
            max_daily_loss=settings.MAX_DAILY_LOSS,
            account_id=req.account_id,
        )

        if req.price:
            risk_result = risk_ctrl.pre_trade_check(
                req.ts_code, req.direction, req.quantity, req.price
            )
            if not risk_result["allowed"]:
                return {"code": -1, "message": "风控拦截", "data": risk_result}

        mgr = OrderManager(db=db, account_id=req.account_id)
        order = mgr.create_order(
            ts_code=req.ts_code,
            direction=req.direction,
            order_type=req.order_type,
            price=req.price,
            quantity=req.quantity,
            strategy_name=req.strategy_name,
            trigger_price=req.trigger_price,
        )

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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{order_id}/execute")
async def execute_order(order_id: str, db: Session = Depends(get_db_session)):
    """执行挂起的订单"""
    try:
        mgr = OrderManager(db=db)
        result = mgr.execute_order(order_id)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return {"code": 0, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{order_id}/cancel")
async def cancel_order(order_id: str, db: Session = Depends(get_db_session)):
    """撤销订单"""
    try:
        mgr = OrderManager(db=db)
        success = mgr.cancel_order(order_id)
        if not success:
            raise HTTPException(status_code=400, detail="无法撤销订单（可能已成交或不存在）")
        return {"code": 0, "data": {"order_id": order_id, "status": "CANCELLED"}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def list_orders(
    db: Session = Depends(get_db_session),
    account_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=20, le=100),
):
    """查询订单列表"""
    try:
        mgr = OrderManager(db=db, account_id=account_id or "REAL_001")
        orders = mgr.list_orders(status=status, limit=limit)
        return {"code": 0, "data": orders, "total": len(orders)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{order_id}")
async def get_order(order_id: str, db: Session = Depends(get_db_session)):
    """查询订单状态"""
    try:
        mgr = OrderManager(db=db)
        order = mgr.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail=f"订单 {order_id} 不存在")
        return {"code": 0, "data": order}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/daily")
async def daily_summary(db: Session = Depends(get_db_session)):
    """获取当日交易摘要"""
    try:
        mgr = OrderManager(db=db)
        summary = mgr.get_daily_summary()
        return {"code": 0, "data": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop/check")
async def check_stop_orders(db: Session = Depends(get_db_session)):
    """扫描STOP条件单并执行已触发的"""
    try:
        # 从positions获取最新价格
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

        mgr = OrderManager(db=db)
        triggered = mgr.check_stop_orders(price_map)
        return {"code": 0, "data": triggered, "total": len(triggered)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/expire")
async def cancel_expired(db: Session = Depends(get_db_session)):
    """取消所有过期的限价单"""
    try:
        mgr = OrderManager(db=db)
        count = mgr.cancel_expired_orders()
        return {"code": 0, "data": {"cancelled_count": count}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
