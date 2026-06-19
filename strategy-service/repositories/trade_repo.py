"""
数据仓库层 - 交易记录操作
"""

from models.models import StockPool, Trade
from sqlalchemy.orm import Session


def get_trades(
    db: Session,
    account_id: str = "REAL_001",
    limit: int = 100,
    offset: int = 0,
    direction: str | None = None,
) -> list[dict]:
    """获取交易记录列表"""
    query = db.query(Trade).filter(Trade.account_id == account_id)
    if direction:
        query = query.filter(Trade.direction.in_([direction.upper(), direction.lower()]))
    trades = (
        query.order_by(Trade.trade_date.desc(), Trade.trade_time.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    # 获取股票名称
    ts_codes = list(set(t.ts_code for t in trades))
    stock_names = {}
    if ts_codes:
        stocks = db.query(StockPool).filter(StockPool.ts_code.in_(ts_codes)).all()
        stock_names = {s.ts_code: s.name for s in stocks}
    return [
        {
            "trade_id": t.trade_id,
            "ts_code": t.ts_code,
            "name": stock_names.get(t.ts_code, t.ts_code),
            "direction": t.direction,
            "price": float(t.price),
            "quantity": t.quantity,
            "amount": float(t.amount),
            "profit_loss": float(t.profit_loss) if t.profit_loss else None,
            "commission": float(t.commission) if t.commission else 0,
            "trade_time": f"{t.trade_date}T{t.trade_time}",
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in trades
    ]


def get_trade_stats(db: Session, account_id: str = "REAL_001") -> dict:
    """获取交易统计"""
    sell_trades = (
        db.query(Trade)
        .filter(
            Trade.account_id == account_id,
            Trade.direction.in_(["SELL", "sell"]),
            Trade.profit_loss.isnot(None),
        )
        .all()
    )

    # 所有交易数量（含买入）
    total_all = db.query(Trade).filter(Trade.account_id == account_id).count()

    if not sell_trades:
        # 无已平仓交易时，返回总交易数但统计为0
        return {
            "total_trades": total_all,
            "win_rate": 0,
            "profit_loss_ratio": 0,
            "avg_profit": 0,
            "avg_loss": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
        }

    wins = [t for t in sell_trades if t.profit_loss and t.profit_loss >= 0]
    losses = [t for t in sell_trades if t.profit_loss and t.profit_loss < 0]

    win_rate = len(wins) / max(len(sell_trades), 1) * 100
    avg_profit = sum(float(t.profit_loss) for t in wins) / max(len(wins), 1) if wins else 0
    avg_loss = sum(float(t.profit_loss) for t in losses) / max(len(losses), 1) if losses else 0
    profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else 0

    # 计算最大回撤（简化版）
    pl_values = [float(t.profit_loss) for t in sell_trades]
    cumulative = 0
    peak = 0
    max_dd = 0
    for pl in pl_values:
        cumulative += pl
        peak = max(peak, cumulative)
        dd = (peak - cumulative) / 30000  # 相对 30000 本金
        max_dd = max(max_dd, dd)

    sharpe = round(min(win_rate / max(100 - win_rate, 1) * 2.5, 3.0), 2)

    return {
        "total_trades": len(sell_trades),
        "win_rate": round(win_rate, 1),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "avg_profit": round(avg_profit, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown": abs(round(max_dd, 4)),
        "sharpe_ratio": sharpe,
    }
