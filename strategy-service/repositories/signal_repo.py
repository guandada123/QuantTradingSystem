"""
数据仓库层 - 交易信号操作
"""
from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
from models.models import TradingSignal, StockPool
import uuid


def save_signal(db: Session, signal_data: Dict) -> Dict:
    """保存交易信号到数据库"""
    signal = TradingSignal(
        signal_id=signal_data.get('signal_id', uuid.uuid4()),
        ts_code=signal_data['ts_code'],
        signal_type=signal_data['signal_type'],
        signal_strength=signal_data.get('signal_strength'),
        strategy_name=signal_data['strategy_name'],
        strategy_version=signal_data.get('strategy_version', '1.0'),
        indicator_signals=signal_data.get('indicator_signals'),
        confidence_score=signal_data.get('confidence_score'),
        target_price=signal_data.get('target_price'),
        stop_loss_price=signal_data.get('stop_loss_price'),
        take_profit_price=signal_data.get('take_profit_price'),
        timeframe=signal_data.get('timeframe', 'daily'),
        generated_at=signal_data.get('generated_at', datetime.now()),
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return _signal_to_dict(signal)


def get_history(db: Session, ts_code: Optional[str] = None,
                limit: int = 20, offset: int = 0) -> List[Dict]:
    """获取历史信号列表"""
    query = db.query(TradingSignal)
    if ts_code:
        query = query.filter(TradingSignal.ts_code == ts_code.upper())
    signals = (
        query.order_by(desc(TradingSignal.generated_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    # 获取股票名称
    ts_codes = list(set(s.ts_code for s in signals))
    stock_names = {}
    if ts_codes:
        stocks = db.query(StockPool).filter(StockPool.ts_code.in_(ts_codes)).all()
        stock_names = {s.ts_code: s.name for s in stocks}
    return [
        {**_signal_to_dict(s), "name": stock_names.get(s.ts_code, s.ts_code)}
        for s in signals
    ]


def get_latest(db: Session, ts_code: str) -> Optional[Dict]:
    """获取某只股票的最新信号"""
    signal = (
        db.query(TradingSignal)
        .filter(TradingSignal.ts_code == ts_code.upper())
        .order_by(desc(TradingSignal.generated_at))
        .first()
    )
    if not signal:
        return None
    stock = db.query(StockPool).filter(StockPool.ts_code == ts_code.upper()).first()
    result = _signal_to_dict(signal)
    result["name"] = stock.name if stock else ts_code
    return result


def get_signals_by_strategy(db: Session, strategy: str,
                            limit: int = 20) -> List[Dict]:
    """按策略名查询信号"""
    signals = (
        db.query(TradingSignal)
        .filter(TradingSignal.strategy_name == strategy)
        .order_by(desc(TradingSignal.generated_at))
        .limit(limit)
        .all()
    )
    return [_signal_to_dict(s) for s in signals]


def _signal_to_dict(s: TradingSignal) -> Dict:
    return {
        "signal_id": str(s.signal_id),
        "ts_code": s.ts_code,
        "signal_type": s.signal_type,
        "signal_strength": float(s.signal_strength) if s.signal_strength else None,
        "strategy_name": s.strategy_name,
        "strategy_version": s.strategy_version,
        "indicator_signals": s.indicator_signals,
        "confidence_score": float(s.confidence_score) if s.confidence_score else None,
        "target_price": float(s.target_price) if s.target_price else None,
        "stop_loss_price": float(s.stop_loss_price) if s.stop_loss_price else None,
        "take_profit_price": float(s.take_profit_price) if s.take_profit_price else None,
        "timeframe": s.timeframe,
        "generated_at": s.generated_at.isoformat() if s.generated_at else None,
        "executed": s.executed,
    }
