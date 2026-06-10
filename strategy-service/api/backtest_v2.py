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
        engine = EnhancedBacktestEngine()
        results = []

        for strategy in req.strategies:
            config = BacktestConfig(
                ts_codes=[req.ts_code],
                strategy=strategy,
                start_date=req.start_date,
                end_date=req.end_date,
                initial_cash=req.initial_cash,
                slippage_rate=req.slippage,
                commission_rate=req.commission_rate,
                benchmark_code=req.benchmark,
                enable_walk_forward=req.enable_walk_forward,
            )

            result = await engine.run(config)

            result_dict = {
                "strategy": strategy,
                "metrics": result.metrics,
                "equity_curve": result.equity_curve,
                "trades": result.trades,
            }
            if result.walk_forward_results:
                result_dict["walk_forward"] = result.walk_forward_results

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
