"""
数据仓库层 - 股票池操作
"""

from models.models import StockPool
from shared.exceptions import RepositoryException
from shared.structured_log import get_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

logger = get_logger(__name__)


def get_stock_pool(
    db: Session, industry: str | None = None, limit: int = 50, offset: int = 0
) -> list[dict]:
    """查询股票池"""
    try:
        query = db.query(StockPool).filter(StockPool.is_active == True)
        if industry:
            query = query.filter(StockPool.industry.ilike(f"%{industry}%"))
        stocks = query.order_by(StockPool.ts_code).offset(offset).limit(limit).all()
        result = [
            {
                "ts_code": s.ts_code,
                "name": s.name,
                "industry": s.industry,
                "sector": s.sector,
                "market": s.market,
                "list_date": s.list_date.isoformat() if s.list_date else None,
                "is_active": s.is_active,
            }
            for s in stocks
        ]
        logger.info("查询股票池成功", count=len(result), industry=industry or "*")
        return result
    except SQLAlchemyError as e:
        logger.error("查询股票池失败", error=str(e))
        raise RepositoryException("查询股票池失败", code="QUERY_STOCK_POOL_FAILED", cause=e)


def search_stocks(db: Session, keyword: str, limit: int = 20) -> list[dict]:
    """搜索股票（代码或名称模糊匹配）"""
    try:
        stocks = (
            db.query(StockPool)
            .filter(
                StockPool.is_active == True,
                (StockPool.ts_code.ilike(f"%{keyword}%") | StockPool.name.ilike(f"%{keyword}%")),
            )
            .limit(limit)
            .all()
        )
        result = [
            {"ts_code": s.ts_code, "name": s.name, "industry": s.industry, "market": s.market}
            for s in stocks
        ]
        logger.info("搜索股票成功", keyword=keyword, count=len(result))
        return result
    except SQLAlchemyError as e:
        logger.error("搜索股票失败", keyword=keyword, error=str(e))
        raise RepositoryException("搜索股票失败", code="SEARCH_STOCK_FAILED", cause=e)
