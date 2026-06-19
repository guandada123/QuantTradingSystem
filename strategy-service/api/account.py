"""
账户与持仓API - 已接入数据库
"""

import logging

from fastapi import APIRouter, Depends
from models.database import get_db
from repositories import account_repo
from sqlalchemy.orm import Session

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


@router.get("/daily-values")
async def get_daily_values(db: Session = Depends(get_db)):
    """获取每日净值数据（用于盈亏曲线图）

    从最近交易记录按日期聚合盈亏，生成净值曲线。
    若无交易记录，返回空数组让前端显示空图表。
    """
    from datetime import date, timedelta

    from models.models import Account, Trade

    account = db.query(Account).filter(Account.account_id == "REAL_001").first()
    current_assets = float(account.total_assets) if account and account.total_assets else 0.0

    trades = (
        db.query(Trade)
        .filter(Trade.account_id == "REAL_001")
        .order_by(Trade.trade_date.asc())
        .all()
    )

    if not trades:
        # 无交易记录时，返回最近30天的平坦净值线
        today = date.today()
        return {
            "success": True,
            "data": [
                {
                    "date": (today - timedelta(days=i)).isoformat(),
                    "value": current_assets or 30000.0,
                }
                for i in range(30, -1, -1)
            ],
        }

    # 按日期聚合盈亏
    daily_pnl: dict[str, float] = {}
    for t in trades:
        d = t.trade_date.isoformat() if hasattr(t.trade_date, "isoformat") else str(t.trade_date)
        daily_pnl[d] = daily_pnl.get(d, 0.0) + float(t.profit_loss or 0)

    # 从最早交易日前30天开始构建净值曲线
    sorted_dates = sorted(daily_pnl.keys())
    first_trade_date = date.fromisoformat(sorted_dates[0]) if sorted_dates else date.today()

    # 初始资金估算（当前资产 - 累计盈亏）
    total_pnl = sum(daily_pnl.values())
    initial_capital = current_assets - total_pnl if current_assets > 0 else 30000.0

    # 生成完整日期序列
    today = date.today()
    current = first_trade_date - timedelta(days=30)
    cumulative = initial_capital
    values = []

    while current <= today:
        date_str = current.isoformat()
        if date_str in daily_pnl:
            cumulative += daily_pnl[date_str]
        values.append({"date": date_str, "value": round(cumulative, 2)})
        current += timedelta(days=1)

    return {"success": True, "data": values}


@router.get("/positions")
async def get_positions(ts_code: str | None = None, db: Session = Depends(get_db)):
    """获取持仓列表（从数据库读取）"""
    positions = account_repo.get_positions(db, ts_code=ts_code)
    return {"success": True, "data": positions}
