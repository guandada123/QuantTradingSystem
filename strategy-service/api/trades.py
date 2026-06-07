"""
交易记录与统计API
"""
from fastapi import APIRouter, Query
from typing import Dict, Any, List
import random
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
router = APIRouter()


def _generate_mock_trades(count: int = 50) -> List[Dict]:
    """生成模拟交易记录"""
    stocks = [
        ("600519.SH", "贵州茅台"), ("000858.SZ", "五粮液"),
        ("601318.SH", "中国平安"), ("000001.SZ", "平安银行"),
        ("600036.SH", "招商银行"), ("002594.SZ", "比亚迪")
    ]
    trades = []
    for i in range(count):
        s = stocks[i % len(stocks)]
        is_buy = random.random() > 0.5
        price = round(40 + random.random() * 200, 2)
        qty = random.randint(10, 100) * 10
        trade_time = (datetime.now() - timedelta(days=i * random.random() * 3)).strftime("%Y-%m-%d %H:%M:%S")
        pl = None
        if not is_buy:
            pl = round((random.random() - 0.45) * 500, 2)
        trades.append({
            "id": i + 1,
            "ts_code": s[0],
            "name": s[1],
            "direction": "BUY" if is_buy else "SELL",
            "price": price,
            "quantity": qty,
            "amount": round(price * qty, 2),
            "trade_time": trade_time,
            "profit_loss": pl
        })
    return trades


@router.get("")
async def get_trades(limit: int = Query(default=50, ge=1, le=200),
                     direction: str = Query(default=None, pattern="^(BUY|SELL|buy|sell)$|^$")):
    """获取交易记录列表"""
    all_trades = _generate_mock_trades(limit * 2)
    if direction:
        d = direction.upper()
        all_trades = [t for t in all_trades if t["direction"] == d]
    return {"success": True, "data": all_trades[:limit], "total": len(all_trades)}


@router.get("/stats")
async def get_trade_stats():
    """获取交易统计"""
    sell_trades = [t for t in _generate_mock_trades(100) if t["direction"] == "SELL" and t.get("profit_loss")]
    wins = [t for t in sell_trades if t["profit_loss"] >= 0]
    losses = [t for t in sell_trades if t["profit_loss"] < 0]

    win_rate = len(wins) / max(len(sell_trades), 1) * 100
    avg_profit = sum(t["profit_loss"] for t in wins) / max(len(wins), 1)
    avg_loss = sum(t["profit_loss"] for t in losses) / max(len(losses), 1)
    profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else 0

    cumulative = 0
    max_val = 0
    drawdown = 0
    for t in sell_trades:
        cumulative += t["profit_loss"]
        max_val = max(max_val, cumulative)
        drawdown = min(drawdown, cumulative - max_val)

    return {"success": True, "data": {
        "total_trades": len(sell_trades),
        "win_rate": round(win_rate, 1),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "avg_profit": round(avg_profit, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown": abs(round(drawdown / (max_val or 50000), 4)),
        "sharpe_ratio": round(min(win_rate / max(100 - win_rate, 1) * 2.5, 3.0), 2)
    }}
