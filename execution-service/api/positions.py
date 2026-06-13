"""
持仓管理API路由 — 使用 DB 依赖注入
"""

from fastapi import APIRouter, Depends, HTTPException
from models.database import get_db_session
from pydantic import BaseModel
from services.position_manager import PositionManager
from sqlalchemy import text
from sqlalchemy.orm import Session

router = APIRouter()


class ClosePositionRequest(BaseModel):
    account_id: str = "REAL_001"
    ts_code: str
    quantity: int
    price: float


class UpdatePricesRequest(BaseModel):
    account_id: str = "REAL_001"
    price_map: dict[str, float]


@router.get("/")
async def list_positions(
    db: Session = Depends(get_db_session), account_id: str | None = "REAL_001"
):
    """获取持仓列表"""
    try:
        mgr = PositionManager(db=db, account_id=account_id)
        positions = mgr.get_positions()
        return {"code": 0, "data": positions, "total": len(positions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_position_summary(
    db: Session = Depends(get_db_session), account_id: str | None = "REAL_001"
):
    """获取持仓汇总"""
    try:
        rows = (
            db.execute(
                text(
                    "SELECT ts_code, total_quantity, cost_price, current_price, market_value, "
                    "profit_loss, profit_loss_ratio FROM positions "
                    "WHERE account_id = :aid AND total_quantity > 0"
                ),
                {"aid": account_id},
            )
            .mappings()
            .fetchall()
        )

        total_market_value = sum(float(r["market_value"] or 0) for r in rows)
        total_cost = sum(float(r["cost_price"] or 0) * int(r["total_quantity"]) for r in rows)
        total_pnl = sum(float(r["profit_loss"] or 0) for r in rows)
        total_pnl_ratio = (total_market_value - total_cost) / total_cost if total_cost > 0 else 0

        return {
            "code": 0,
            "data": {
                "total_market_value": total_market_value,
                "total_cost": total_cost,
                "total_profit_loss": total_pnl,
                "total_profit_loss_ratio": round(total_pnl_ratio, 4),
                "position_count": len(rows),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/close")
async def close_position(req: ClosePositionRequest, db: Session = Depends(get_db_session)):
    """平仓"""
    try:
        mgr = PositionManager(db=db, account_id=req.account_id)
        result = mgr.close_position(ts_code=req.ts_code, quantity=req.quantity, price=req.price)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return {"code": 0, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-prices")
async def update_prices(req: UpdatePricesRequest, db: Session = Depends(get_db_session)):
    """批量更新持仓价格"""
    try:
        mgr = PositionManager(db=db, account_id=req.account_id)
        result = mgr.update_position_prices(req.price_map)
        return {"code": 0, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/pnl")
async def get_realized_pnl(
    db: Session = Depends(get_db_session), account_id: str | None = "REAL_001"
):
    """获取当日累计已实现盈亏"""
    try:
        mgr = PositionManager(db=db, account_id=account_id)
        result = mgr.get_realized_pnl_summary()
        return {"code": 0, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ts_code}")
async def get_position(
    ts_code: str, db: Session = Depends(get_db_session), account_id: str | None = "REAL_001"
):
    """获取单只股票持仓"""
    try:
        row = (
            db.execute(
                text("""
            SELECT ts_code, direction, total_quantity, available_quantity, locked_quantity,
                   cost_price, current_price, market_value, profit_loss, profit_loss_ratio,
                   days_held, stop_loss_price, take_profit_price, strategy_name, opened_at, updated_at
            FROM positions WHERE account_id = :aid AND ts_code = :tc
        """),
                {"aid": account_id, "tc": ts_code},
            )
            .mappings()
            .fetchone()
        )

        if not row:
            raise HTTPException(status_code=404, detail=f"未找到 {ts_code} 的持仓")
        return {"code": 0, "data": dict(row)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
