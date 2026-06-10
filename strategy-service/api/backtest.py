"""
回测API路由 v2.0 - 已接入数据库
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from models.database import get_db
from repositories import backtest_repo

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/run")
async def run_backtest(
    ts_code: str,
    strategy: str = Query(..., description="策略：ma-cross/breakout/rsi/macd/kdj"),
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    initial_cash: float = 30000.0,
    ma_fast: int = 5,
    ma_slow: int = 20,
    lookback: int = 20,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    db: Session = Depends(get_db)
):
    """
    运行策略回测并保存结果到数据库
    例：POST /api/v1/backtest/run?ts_code=600519.SH&strategy=ma-cross
    """
    try:
        from services.data_service import DataService
        from services.backtest_service import BacktestService
        from core.config import settings

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        data = ds.get_stock_daily_quote(ts_code, start_date, end_date)

        if len(data) < 30:
            return {"code": 1, "message": f"数据不足（需要至少30条，当前{len(data)}条）", "data": None}

        params = {
            'ma_fast': ma_fast, 'ma_slow': ma_slow,
            'lookback': lookback, 'period': rsi_period,
            'oversold': 30, 'overbought': 70,
            'fast': macd_fast, 'slow': macd_slow, 'signal': macd_signal,
            'k_smooth': 3, 'd_smooth': 3
        }

        bs = BacktestService()
        result = bs.run_backtest(ts_code, strategy, data, params)

        # 保存到数据库
        saved = backtest_repo.save_backtest_result(db, {
            "strategy_name": strategy,
            "strategy_version": "1.0",
            "start_date": datetime.strptime(start_date, '%Y-%m-%d').date(),
            "end_date": datetime.strptime(end_date, '%Y-%m-%d').date(),
            "initial_cash": initial_cash,
            "final_value": round(result.final_value, 2),
            "total_return": result.total_return,
            "annual_return": result.annual_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "total_trades": result.total_trades,
        })

        return {
            "code": 0,
            "data": {
                "backtest_id": saved["backtest_id"],
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
                "trades": result.trades[:10]
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/result/{backtest_id}")
async def get_backtest_result(backtest_id: str, db: Session = Depends(get_db)):
    """从数据库查询回测结果"""
    try:
        result = backtest_repo.get_backtest_result(db, backtest_id)
        if not result:
            return {"code": 1, "message": "回测结果不存在"}
        return {"code": 0, "data": result}
    except Exception as e:
        logger.warning(f"回测结果查询失败(DB未就绪): {e}")
        return {"code": 1, "message": "DB schema pending migration"}


@router.get("/history")
async def get_backtest_history(limit: int = 20, db: Session = Depends(get_db)):
    """查询历史回测记录"""
    try:
        results = backtest_repo.get_backtest_history(db, limit=limit)
        return {"code": 0, "data": results, "total": len(results)}
    except Exception as e:
        logger.warning(f"回测历史查询失败(DB未就绪或schema未迁移): {e}")
        return {"code": 0, "data": [], "total": 0, "note": "DB schema pending migration"}


@router.post("/optimize")
async def optimize_params(
    ts_code: str,
    strategy: str = "ma-cross",
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    kdj_period: int = 9,
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
            {"name": "rsi", "description": "RSI超买超卖策略", "params": ["period", "oversold", "overbought"]},
            {"name": "macd", "description": "MACD金叉死叉策略", "params": ["fast", "slow", "signal"]},
            {"name": "kdj", "description": "KDJ随机指标策略", "params": ["period", "k_smooth", "d_smooth"]}
        ]
    }


@router.get("/reports")
async def get_reports(
    report_type: str = None,
    report_date: str = None,
    limit: int = 20
):
    """查询回测报告

    GET /api/v1/backtest/reports?type=daily&date=2026-06-09&limit=10
    """
    try:
        from models.database import get_db_session
        db = get_db_session()
        query = "SELECT * FROM backtest_reports WHERE 1=1"
        params = {}

        if report_type:
            query += " AND report_type = :rtype"
            params["rtype"] = report_type
        if report_date:
            query += " AND report_date = :rdate"
            params["rdate"] = report_date

        query += " ORDER BY created_at DESC LIMIT :lim"
        params["lim"] = min(limit, 100)

        rows = db.execute(query, params).fetchall()
        results = []
        for row in rows:
            results.append({
                "report_id": str(row.report_id) if hasattr(row, 'report_id') else None,
                "report_type": row.report_type,
                "report_date": row.report_date.isoformat() if hasattr(row.report_date, 'isoformat') else str(row.report_date),
                "strategy_count": row.strategy_count,
                "summary": row.summary,
                "push_success": row.push_success,
                "created_at": row.created_at.isoformat() if hasattr(row.created_at, 'isoformat') else str(row.created_at),
            })

        return {"code": 0, "data": results, "total": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/report/generate")
async def generate_report(
    report_type: str = "daily",
    ts_codes: str = "000001.SZ,600519.SH",
    strategies: str = None
):
    """手动触发生成回测报告

    POST /api/v1/backtest/report/generate?type=daily&ts_codes=000001.SZ,600519.SH
    """
    try:
        from services.report_service import ReportService

        stock_pool = [s.strip() for s in ts_codes.split(",") if s.strip()]
        strategy_list = [s.strip() for s in strategies.split(",")] if strategies else None

        svc = ReportService(stock_pool=stock_pool)

        if report_type == "daily":
            report = svc.generate_daily_report(strategies=strategy_list)
        elif report_type == "weekly":
            report = svc.generate_weekly_report(strategies=strategy_list)
        elif report_type == "monthly":
            report = svc.generate_monthly_report(strategies=strategy_list)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的报告类型: {report_type}")

        return {
            "code": 0,
            "data": {
                "report_type": report["report_type"],
                "report_date": report["report_date"],
                "backtest_count": report["backtest_count"],
                "summary": report["summary"],
                "markdown": report["markdown"],
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
