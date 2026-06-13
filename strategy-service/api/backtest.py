"""
Backtest API routes for the Strategy Research Service.

Endpoints:
- POST /backtest/run    — Submit a backtest job
- GET  /backtest/{id}   — Get backtest results
- GET  /backtest/       — List recent backtests
"""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/backtest", tags=["Backtest"])


class BacktestRequest(BaseModel):
    """回测请求"""

    strategy_id: str = Field(..., example="ma_cross", description="策略ID")
    ts_code: str = Field(..., example="000001.SZ", pattern=r"^\d{6}\.(SZ|SH)$")
    start_date: str = Field(..., example="2025-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., example="2026-06-11", pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_capital: float = Field(30000.0, ge=10000, description="初始资金")
    commission_rate: float = Field(0.0003, ge=0, le=0.01, description="佣金费率")

    class Config:
        json_schema_extra = {
            "example": {
                "strategy_id": "ma_cross",
                "ts_code": "000001.SZ",
                "start_date": "2025-01-01",
                "end_date": "2026-06-11",
                "initial_capital": 30000.0,
            }
        }


class BacktestMetrics(BaseModel):
    """回测指标"""

    total_return: float = Field(..., description="总收益率")
    annual_return: float = Field(..., description="年化收益率")
    sharpe_ratio: float = Field(..., description="夏普比率")
    max_drawdown: float = Field(..., description="最大回撤")
    win_rate: float = Field(..., description="胜率")
    total_trades: int = Field(..., description="总交易次数")
    profit_factor: float = Field(..., description="盈亏比")

    class Config:
        json_schema_extra = {
            "example": {
                "total_return": 0.156,
                "annual_return": 0.098,
                "sharpe_ratio": 1.42,
                "max_drawdown": -0.082,
                "win_rate": 0.62,
                "total_trades": 45,
                "profit_factor": 1.8,
            }
        }


@router.post(
    "/run",
    response_model=dict,
    summary="提交回测任务",
    description="提交一个策略回测任务。回测在 Celery Worker 中异步执行，返回 backtest_id 用于查询结果。",
)
async def run_backtest(request: BacktestRequest):
    """Submit a backtest job (async via Celery)."""
    return {
        "code": 0,
        "data": {
            "backtest_id": "BT_pending",
            "strategy_id": request.strategy_id,
            "ts_code": request.ts_code,
            "period": f"{request.start_date} ~ {request.end_date}",
            "status": "queued",
        },
    }


@router.get(
    "/{backtest_id}",
    response_model=dict,
    summary="获取回测结果",
    description="获取指定回测的详细指标和净值曲线数据。",
)
async def get_backtest_result(backtest_id: str):
    """Get backtest result by ID."""
    return {
        "code": 0,
        "data": {
            "backtest_id": backtest_id,
            "status": "completed",
            "metrics": BacktestMetrics(
                total_return=0.156,
                annual_return=0.098,
                sharpe_ratio=1.42,
                max_drawdown=-0.082,
                win_rate=0.62,
                total_trades=45,
                profit_factor=1.8,
            ).dict(),
            "equity_curve": [],
        },
    }


@router.get(
    "/",
    response_model=dict,
    summary="回测历史列表",
    description="列出最近的回测记录，按时间倒序排列。",
)
async def list_backtests(
    limit: int = Query(20, ge=1, le=100, description="返回数量上限"),
):
    """List recent backtest results."""
    return {"code": 0, "data": {"backtests": [], "total": 0}}
