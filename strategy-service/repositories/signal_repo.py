"""
数据仓库层 - 交易信号操作
"""

from datetime import datetime
import uuid

from models.models import StockPool, TradingSignal
from sqlalchemy import desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from shared.exceptions import RepositoryException
from shared.structured_log import get_logger

logger = get_logger(__name__)


def save_signal(db: Session, signal_data: dict) -> dict:
    """保存交易信号到数据库"""
    try:
        signal = TradingSignal(
            signal_id=signal_data.get("signal_id", uuid.uuid4()),
            ts_code=signal_data["ts_code"],
            signal_type=signal_data["signal_type"],
            signal_strength=signal_data.get("signal_strength"),
            strategy_name=signal_data["strategy_name"],
            strategy_version=signal_data.get("strategy_version", "1.0"),
            indicator_signals=signal_data.get("indicator_signals"),
            confidence_score=signal_data.get("confidence_score"),
            target_price=signal_data.get("target_price"),
            stop_loss_price=signal_data.get("stop_loss_price"),
            take_profit_price=signal_data.get("take_profit_price"),
            timeframe=signal_data.get("timeframe", "daily"),
            generated_at=signal_data.get("generated_at", datetime.now()),
        )
        db.add(signal)
        db.commit()
        db.refresh(signal)
        result = _signal_to_dict(signal)
        logger.info(
            "交易信号已保存", ts_code=signal_data["ts_code"], strategy=signal_data["strategy_name"]
        )
        return result
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("保存交易信号失败", ts_code=signal_data.get("ts_code"), error=str(e))
        raise RepositoryException(
            "保存交易信号失败",
            code="SAVE_SIGNAL_FAILED",
            detail={"ts_code": signal_data.get("ts_code")},
            cause=e,
        )
    except KeyError as e:
        logger.error("交易信号数据缺少必填字段", field=str(e))
        raise RepositoryException(f"交易信号数据缺少必填字段: {e}", code="SIGNAL_MISSING_FIELD")


def get_history(
    db: Session, ts_code: str | None = None, limit: int = 20, offset: int = 0
) -> list[dict]:
    """获取历史信号列表"""
    try:
        query = db.query(TradingSignal)
        if ts_code:
            query = query.filter(TradingSignal.ts_code == ts_code.upper())
        signals = query.order_by(desc(TradingSignal.generated_at)).offset(offset).limit(limit).all()
        # 获取股票名称
        ts_codes = list(set(s.ts_code for s in signals))
        stock_names = {}
        if ts_codes:
            stocks = db.query(StockPool).filter(StockPool.ts_code.in_(ts_codes)).all()
            stock_names = {s.ts_code: s.name for s in stocks}
        return [
            {**_signal_to_dict(s), "name": stock_names.get(s.ts_code, s.ts_code)} for s in signals
        ]
    except SQLAlchemyError as e:
        logger.error("查询历史信号失败", error=str(e))
        raise RepositoryException("查询历史信号失败", code="QUERY_SIGNAL_FAILED", cause=e)


def get_latest(db: Session, ts_code: str) -> dict | None:
    """获取某只股票的最新信号"""
    try:
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
    except SQLAlchemyError as e:
        logger.error("查询最新信号失败", ts_code=ts_code, error=str(e))
        raise RepositoryException(
            "查询最新信号失败",
            code="QUERY_LATEST_SIGNAL_FAILED",
            detail={"ts_code": ts_code},
            cause=e,
        )


def get_signals_by_strategy(db: Session, strategy: str, limit: int = 20) -> list[dict]:
    """按策略名查询信号"""
    try:
        signals = (
            db.query(TradingSignal)
            .filter(TradingSignal.strategy_name == strategy)
            .order_by(desc(TradingSignal.generated_at))
            .limit(limit)
            .all()
        )
        return [_signal_to_dict(s) for s in signals]
    except SQLAlchemyError as e:
        logger.error("按策略查询信号失败", strategy=strategy, error=str(e))
        raise RepositoryException(
            "按策略查询信号失败", code="QUERY_SIGNAL_BY_STRATEGY_FAILED", cause=e
        )


def _signal_to_dict(s: TradingSignal) -> dict:
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
