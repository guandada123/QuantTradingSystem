"""
数据仓库层 - 回测结果操作
"""
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import desc
from models.models import BacktestResult


def save_backtest_result(db: Session, result_data: Dict) -> Dict:
    """保存回测结果到数据库"""
    result = BacktestResult(
        strategy_name=result_data['strategy_name'],
        strategy_version=result_data.get('strategy_version', '1.0'),
        ts_code=result_data.get('ts_code', ''),
        start_date=result_data['start_date'],
        end_date=result_data['end_date'],
        initial_cash=result_data['initial_cash'],
        final_value=result_data['final_value'],
        total_return=result_data.get('total_return'),
        annual_return=result_data.get('annual_return'),
        sharpe_ratio=result_data.get('sharpe_ratio'),
        max_drawdown=result_data.get('max_drawdown'),
        win_rate=result_data.get('win_rate'),
        profit_loss_ratio=result_data.get('profit_loss_ratio'),
        total_trades=result_data.get('total_trades'),
        winning_trades=result_data.get('winning_trades'),
        losing_trades=result_data.get('losing_trades'),
        avg_holding_days=result_data.get('avg_holding_days'),
        backtest_details=result_data.get('backtest_details'),
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return _result_to_dict(result)


def get_backtest_result(db: Session, backtest_id: str) -> Optional[Dict]:
    """按 backtest_id 查询回测结果"""
    import uuid
    try:
        uid = uuid.UUID(backtest_id)
    except ValueError:
        return None
    result = db.query(BacktestResult).filter(
        BacktestResult.backtest_id == uid
    ).first()
    return _result_to_dict(result) if result else None


def get_backtest_history(db: Session, limit: int = 20) -> List[Dict]:
    """获取最近回测记录"""
    results = (
        db.query(BacktestResult)
        .order_by(desc(BacktestResult.created_at))
        .limit(limit)
        .all()
    )
    return [_result_to_dict(r) for r in results]


def _result_to_dict(r: BacktestResult) -> Dict:
    return {
        "backtest_id": str(r.backtest_id),
        "strategy_name": r.strategy_name,
        "strategy_version": r.strategy_version,
        "ts_code": r.ts_code or '',
        "start_date": r.start_date.isoformat() if r.start_date else None,
        "end_date": r.end_date.isoformat() if r.end_date else None,
        "initial_cash": float(r.initial_cash),
        "final_value": float(r.final_value),
        "total_return": float(r.total_return) if r.total_return else None,
        "annual_return": float(r.annual_return) if r.annual_return else None,
        "sharpe_ratio": float(r.sharpe_ratio) if r.sharpe_ratio else None,
        "max_drawdown": float(r.max_drawdown) if r.max_drawdown else None,
        "win_rate": float(r.win_rate) if r.win_rate else None,
        "profit_loss_ratio": float(r.profit_loss_ratio) if r.profit_loss_ratio else None,
        "total_trades": r.total_trades,
        "winning_trades": r.winning_trades,
        "losing_trades": r.losing_trades,
        "avg_holding_days": float(r.avg_holding_days) if r.avg_holding_days else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
