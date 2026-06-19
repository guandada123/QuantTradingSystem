"""
交易记录API - 已接入数据库
"""

from fastapi import APIRouter, Depends
from models.database import get_db
from repositories import trade_repo
from shared.exceptions import RepositoryException
from shared.structured_log import get_logger
from sqlalchemy.orm import Session

logger = get_logger(__name__)
router = APIRouter(tags=["交易记录"])


@router.get("")
async def get_trades(
    limit: int = 100, offset: int = 0, direction: str | None = None, db: Session = Depends(get_db)
):
    """获取交易记录列表（从数据库读取）"""
    try:
        trades = trade_repo.get_trades(db, limit=limit, offset=offset, direction=direction)
        logger.info("获取交易记录成功", count=len(trades))
        return {"success": True, "data": trades}
    except RepositoryException:
        raise
    except Exception as e:
        logger.error("获取交易记录失败", error=str(e))
        return {"success": False, "error": str(e)}


@router.get("/stats")
async def get_trade_stats(db: Session = Depends(get_db)):
    """获取交易统计（从数据库读取）"""
    try:
        stats = trade_repo.get_trade_stats(db)
        logger.info("获取交易统计成功")
        return {"success": True, "data": stats}
    except RepositoryException:
        raise
    except Exception as e:
        logger.error("获取交易统计失败", error=str(e))
        return {"success": False, "error": str(e)}
