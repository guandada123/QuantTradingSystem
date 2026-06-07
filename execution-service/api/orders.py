"""
订单管理API路由
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

router = APIRouter()

@router.post("/submit")
async def submit_order(
    ts_code: str,
    direction: str,  # BUY/SELL
    order_type: str = "LIMIT",  # LIMIT/MARKET
    price: Optional[float] = None,
    quantity: int = 100,
    strategy_name: Optional[str] = None
):
    """
    提交订单
    例：POST /api/v1/orders/submit?ts_code=600519.SH&direction=BUY&price=1800.00&quantity=100
    """
    try:
        # TODO: 集成MiniQMT执行订单
        return {
            "code": 0,
            "data": {
                "order_id": f"ORD_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "status": "pending",
                "ts_code": ts_code,
                "direction": direction,
                "order_type": order_type,
                "price": price,
                "quantity": quantity
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{order_id}")
async def get_order(order_id: str):
    """查询订单状态"""
    return {"code": 0, "data": {"order_id": order_id, "status": "unknown"}}

@router.delete("/{order_id}")
async def cancel_order(order_id: str):
    """撤销订单"""
    return {"code": 0, "data": {"order_id": order_id, "status": "cancelled"}}

@router.get("/")
async def list_orders(
    status: Optional[str] = None,
    limit: int = Query(default=20, le=100)
):
    """查询订单列表"""
    return {"code": 0, "data": [], "total": 0}
