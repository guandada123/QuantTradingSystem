"""
账户与持仓API - 已接入数据库
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional
import logging

from models.database import get_db
from repositories import account_repo

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/summary")
async def get_account_summary(db: Session = Depends(get_db)):
    """获取账户概要（从数据库读取）"""
    data = account_repo.get_account_summary(db)
    if not data:
        # 数据库有数据但无此账户
        return {"success": False, "message": "账户不存在"}
    return {"success": True, "data": data}


@router.get("")
async def get_account(db: Session = Depends(get_db)):
    """获取账户详情"""
    data = account_repo.get_account_detail(db)
    if not data:
        return {"success": False, "message": "账户不存在"}
    return {"success": True, "data": data}


@router.get("/positions")
async def get_positions(ts_code: Optional[str] = None, db: Session = Depends(get_db)):
    """获取持仓列表（从数据库读取）"""
    positions = account_repo.get_positions(db, ts_code=ts_code)
    return {"success": True, "data": positions}
