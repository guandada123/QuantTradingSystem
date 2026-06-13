"""
数据仓库层 - 股票池操作
"""

from models.models import StockPool
from sqlalchemy.orm import Session


def get_stock_pool(
    db: Session, industry: str | None = None, limit: int = 50, offset: int = 0
) -> list[dict]:
    """查询股票池"""
    query = db.query(StockPool).filter(StockPool.is_active == True)
    if industry:
        query = query.filter(StockPool.industry.ilike(f"%{industry}%"))
    stocks = query.order_by(StockPool.ts_code).offset(offset).limit(limit).all()
    return [
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


def search_stocks(db: Session, keyword: str, limit: int = 20) -> list[dict]:
    """搜索股票（代码或名称模糊匹配）"""
    stocks = (
        db.query(StockPool)
        .filter(
            StockPool.is_active == True,
            (StockPool.ts_code.ilike(f"%{keyword}%") | StockPool.name.ilike(f"%{keyword}%")),
        )
        .limit(limit)
        .all()
    )
    return [
        {"ts_code": s.ts_code, "name": s.name, "industry": s.industry, "market": s.market}
        for s in stocks
    ]
