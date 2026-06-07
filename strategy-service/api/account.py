"""
账户与持仓API
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

# 模拟账户数据（后续接入PostgreSQL）
_mock_account = {
    "total_assets": 52340.50,
    "available_cash": 22000.00,
    "market_value": 30340.50,
    "total_profit_loss": 2340.50,
    "total_profit_loss_ratio": 0.0468,
    "currency": "CNY"
}

_mock_positions = [
    {"ts_code": "600519.SH", "name": "贵州茅台", "quantity": 10, "available_quantity": 10,
     "cost_price": 1250.00, "current_price": 1272.86, "profit_loss": 228.60,
     "profit_loss_ratio": 0.0183, "market_value": 12728.60},
    {"ts_code": "000858.SZ", "name": "五粮液", "quantity": 50, "available_quantity": 50,
     "cost_price": 80.50, "current_price": 81.08, "profit_loss": 29.00,
     "profit_loss_ratio": 0.0072, "market_value": 4054.00},
    {"ts_code": "601318.SH", "name": "中国平安", "quantity": 30, "available_quantity": 30,
     "cost_price": 48.20, "current_price": 49.85, "profit_loss": 49.50,
     "profit_loss_ratio": 0.0342, "market_value": 1495.50}
]


@router.get("/summary")
async def get_account_summary():
    """获取账户概要"""
    return {"success": True, "data": _mock_account}


@router.get("")
async def get_account():
    """获取账户详情"""
    return {"success": True, "data": {
        **_mock_account,
        "positions": len(_mock_positions),
        "days_active": 12,
        "daily_return": 0.0042,
        "monthly_return": 0.0468
    }}


@router.get("/positions")
async def get_positions(ts_code: str = None):
    """获取持仓列表"""
    if ts_code:
        filtered = [p for p in _mock_positions
                    if p["ts_code"].upper() == ts_code.upper()]
        return {"success": True, "data": filtered}
    return {"success": True, "data": _mock_positions}
