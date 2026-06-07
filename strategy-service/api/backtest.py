"""
回测API路由 v2.0
集成内置回测引擎，支持ma-cross/breakout/rsi策略回测和参数优化
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import Optional
import uuid

router = APIRouter()

@router.post("/run")
async def run_backtest(
    ts_code: str,
    strategy: str = Query(..., description="策略：ma-cross/breakout/rsi"),
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    initial_cash: float = 50000.0,
    ma_fast: int = 5,
    ma_slow: int = 20,
    lookback: int = 20,
    rsi_period: int = 14,
):
    """
    运行策略回测
    例：POST /api/v1/backtest/run?ts_code=600519.SH&strategy=ma-cross&start_date=2024-01-01
    """
    backtest_id = str(uuid.uuid4())[:8]
    
    try:
        from services.data_service import DataService
        from services.backtest_service import BacktestService
        from core.config import settings
        
        # 获取历史数据
        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        
        data = ds.get_stock_daily_quote(ts_code, start_date, end_date)
        
        if len(data) < 30:
            return {"code": 1, "message": f"数据不足（需要至少30条，当前{len(data)}条）", "data": None}
        
        # 准备参数
        params = {
            'ma_fast': ma_fast, 'ma_slow': ma_slow,
            'lookback': lookback, 'period': rsi_period,
            'oversold': 30, 'overbought': 70
        }
        
        # 运行回测
        bs = BacktestService()
        result = bs.run_backtest(ts_code, strategy, data, params)
        
        # 缓存结果
        bs.results[backtest_id] = result
        
        return {
            "code": 0,
            "data": {
                "backtest_id": backtest_id,
                "ts_code": ts_code,
                "strategy": strategy,
                "start_date": result.start_date,
                "end_date": result.end_date,
                "initial_cash": result.initial_cash,
                "final_value": round(result.final_value, 2),
                "total_return": round(result.total_return * 100, 2),
                "annual_return": round(result.annual_return * 100, 2),
                "sharpe_ratio": round(result.sharpe_ratio, 3),
                "max_drawdown": round(result.max_drawdown * 100, 2),
                "win_rate": round(result.win_rate * 100, 2),
                "total_trades": result.total_trades,
                "trades": result.trades[:10]  # 只返回最近10笔
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/result/{backtest_id}")
async def get_backtest_result(backtest_id: str):
    """查询回测结果"""
    from services.backtest_service import BacktestService
    bs = BacktestService()
    result = bs.results.get(backtest_id)
    if not result:
        return {"code": 1, "message": "回测结果不存在或已过期"}
    return {"code": 0, "data": result.__dict__}

@router.post("/optimize")
async def optimize_params(
    ts_code: str,
    strategy: str = "ma-cross",
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31"
):
    """参数优化"""
    try:
        from services.data_service import DataService
        from services.backtest_service import BacktestService
        from core.config import settings
        
        ds = DataService(redis_url=settings.REDIS_URL)
        if settings.TUSHARE_TOKEN:
            ds.set_tushare_token(settings.TUSHARE_TOKEN)
        
        data = ds.get_stock_daily_quote(ts_code, start_date, end_date)
        
        if len(data) < 30:
            return {"code": 1, "message": f"数据不足（{len(data)}条）"}
        
        bs = BacktestService()
        result = bs.optimize_params(ts_code, strategy, data, {
            'ma_fast': [5, 10, 20],
            'ma_slow': [20, 30, 60]
        })
        
        return {"code": 0, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/strategies")
async def list_strategies():
    """列出所有可用策略"""
    return {
        "code": 0,
        "data": [
            {"name": "ma-cross", "description": "双均线金叉策略", "params": ["ma_fast", "ma_slow"]},
            {"name": "breakout", "description": "突破策略", "params": ["lookback"]},
            {"name": "rsi", "description": "RSI超买超卖策略", "params": ["period", "oversold", "overbought"]}
        ]
    }
