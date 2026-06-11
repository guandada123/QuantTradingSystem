"""
回测API路由 v2 - 对接 EnhancedBacktestEngine (backtest_engine_v2)
前端 dashboard/backtest.html 通过 POST /api/v1/backtest/run JSON body 调用
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import logging

from services.backtest_engine_v2 import EnhancedBacktestEngine, BacktestConfig

logger = logging.getLogger(__name__)

router = APIRouter()


class BacktestRequest(BaseModel):
    ts_code: str = Field(..., description="股票代码，如 600519.SH")
    strategies: List[str] = Field(default=["ma-cross"], description="策略列表")
    start_date: str = Field(..., description="开始日期 YYYYMMDD")
    end_date: str = Field(..., description="结束日期 YYYYMMDD")
    initial_cash: float = Field(default=100000)
    slippage: float = Field(default=0.001)
    commission_rate: float = Field(default=0.00025)
    benchmark: str = Field(default="000300.SH")
    enable_walk_forward: bool = Field(default=False)


class BacktestResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    comparison: Optional[List[dict]] = None
    error: Optional[str] = None


@router.post("/run", response_model=BacktestResponse)
async def run_backtest(req: BacktestRequest):
    """执行单/多策略回测（V2引擎）"""
    try:
        results = []

        for strategy in req.strategies:
            config = BacktestConfig(
                ts_codes=[req.ts_code],
                strategies=[strategy],
                start_date=req.start_date,
                end_date=req.end_date,
                initial_cash=req.initial_cash,
                slippage=req.slippage,
                commission_rate=req.commission_rate,
                benchmark=req.benchmark,
            )

            engine = EnhancedBacktestEngine(config)
            result = engine.run()

            result_dict = {
                "strategy": strategy,
                "metrics": {
                    "total_return": result.total_return,
                    "annual_return": result.annual_return,
                    "sharpe_ratio": result.sharpe_ratio,
                    "max_drawdown": result.max_drawdown,
                    "win_rate": result.win_rate,
                    "profit_factor": result.profit_factor,
                    "calmar_ratio": result.calmar_ratio,
                    "sortino_ratio": result.sortino_ratio,
                    "information_ratio": result.information_ratio,
                    "alpha": result.alpha,
                    "beta": result.beta,
                    "volatility": result.volatility,
                    "turnover_rate": result.turnover_rate,
                },
                "equity_curve": result.equity_curve,
                "monthly_returns": result.monthly_returns,
            }
            if result.trades:
                result_dict["trades"] = [{
                    "date": t.date, "ts_code": t.ts_code, "direction": t.direction,
                    "price": t.price, "quantity": t.quantity, "amount": t.amount,
                    "slippage_cost": t.slippage_cost, "commission": t.commission,
                    "tax": t.tax, "pnl": t.pnl,
                } for t in result.trades]

            results.append(result_dict)

        if len(results) == 1:
            return BacktestResponse(success=True, data=results[0])
        else:
            return BacktestResponse(success=True, data=results[0], comparison=results)

    except ValueError as e:
        logger.warning(f"回测参数错误: {e}")
        return BacktestResponse(success=False, error=str(e))
    except Exception as e:
        logger.error(f"回测执行异常: {e}", exc_info=True)
        return BacktestResponse(success=False, error=str(e))
