"""
交易记录API - 已接入数据库
"""

import logging

from fastapi import APIRouter, Depends
from models.database import get_db
from repositories import trade_repo
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def get_trades(
    limit: int = 100, offset: int = 0, direction: str | None = None, db: Session = Depends(get_db)
):
    """获取交易记录列表（从数据库读取）"""
    trades = trade_repo.get_trades(db, limit=limit, offset=offset, direction=direction)
    return {"success": True, "data": trades}


@router.get("/stats")
async def get_trade_stats(db: Session = Depends(get_db)):
    """获取交易统计（从数据库读取）"""
    stats = trade_repo.get_trade_stats(db)
    return {"success": True, "data": stats}
