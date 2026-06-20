"""
数据仓库层 - 回测结果操作

backtest_details 压缩存储策略 (P2-PERF-05):
- 保存时: gzip 压缩 JSON → 存入 backtest_details_compressed 列
- 读取时: 优先从 backtest_details_compressed 解压读取
- 兼容: 旧数据仍可从 backtest_details 列读取（未压缩 JSON）
- 压缩比: 常规 JSON 文本可压缩至 15%-25% 原始大小
"""

import gzip
import json
from typing import Any

from models.models import BacktestResult
from sqlalchemy import desc
from sqlalchemy.orm import Session

# ── 压缩/解压 helpers ─────────────────────────────────────


def _compress_details(details: dict) -> bytes:
    """gzip 压缩 backtest_details 字典

    Args:
        details: backtest_details 字典（含 equity_curve/trades 等）

    Returns:
        压缩后的 bytes
    """
    raw = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
    return gzip.compress(raw, compresslevel=6)


def _decompress_details(data: bytes) -> dict:
    """解压 backtest_details

    Args:
        data: gzip 压缩后的 bytes

    Returns:
        原始字典
    """
    raw = gzip.decompress(data)
    result: dict[Any, Any] = json.loads(raw.decode("utf-8"))
    return result


def _extract_details(record: BacktestResult) -> dict | None:
    """从 ORM 记录中提取 backtest_details（压缩列优先，兼容旧数据）

    Args:
        record: BacktestResult ORM 实例

    Returns:
        backtest_details 字典，若无数据则返回 None
    """
    if record.backtest_details_compressed:
        return _decompress_details(record.backtest_details_compressed)  # type: ignore[arg-type]
    if record.backtest_details:
        return record.backtest_details  # type: ignore[return-value]
    return None


# ── 核心 CRUD ──────────────────────────────────────────────


def save_backtest_result(db: Session, result_data: dict) -> dict:
    """保存回测结果到数据库（backtest_details 自动 gzip 压缩）"""
    details_raw = result_data.get("backtest_details")
    details_compressed = _compress_details(details_raw) if details_raw else None

    result = BacktestResult(
        strategy_name=result_data["strategy_name"],
        strategy_version=result_data.get("strategy_version", "1.0"),
        ts_code=result_data.get("ts_code", ""),
        start_date=result_data["start_date"],
        end_date=result_data["end_date"],
        initial_cash=result_data["initial_cash"],
        final_value=result_data["final_value"],
        total_return=result_data.get("total_return"),
        annual_return=result_data.get("annual_return"),
        sharpe_ratio=result_data.get("sharpe_ratio"),
        max_drawdown=result_data.get("max_drawdown"),
        win_rate=result_data.get("win_rate"),
        profit_loss_ratio=result_data.get("profit_loss_ratio"),
        total_trades=result_data.get("total_trades"),
        winning_trades=result_data.get("winning_trades"),
        losing_trades=result_data.get("losing_trades"),
        avg_holding_days=result_data.get("avg_holding_days"),
        backtest_details=None,  # 不再存储未压缩数据
        backtest_details_compressed=details_compressed,  # 压缩存储
    )
    try:
        db.add(result)
        db.commit()
        db.refresh(result)
    except Exception:
        db.rollback()
        raise
    return _result_to_dict(result)


def get_backtest_result(db: Session, backtest_id: str) -> dict | None:
    """按 backtest_id 查询回测结果（仅返回摘要指标，不含 backtest_details）"""
    import uuid

    try:
        uid = uuid.UUID(backtest_id)
    except ValueError:
        return None
    result = db.query(BacktestResult).filter(BacktestResult.backtest_id == uid).first()
    return _result_to_dict(result) if result else None


def get_backtest_result_with_details(db: Session, backtest_id: str) -> dict | None:
    """按 backtest_id 查询回测结果（含解压后的 backtest_details）

    与 get_backtest_result 的区别是返回结果中包含完整的
    backtest_details（equity_curve/trades/benchmark_curve 等），
    适用于 detail 详情页查询。
    """
    import uuid

    try:
        uid = uuid.UUID(backtest_id)
    except ValueError:
        return None
    record = db.query(BacktestResult).filter(BacktestResult.backtest_id == uid).first()
    if not record:
        return None

    d = _result_to_dict(record)
    details = _extract_details(record)
    if details:
        d["backtest_details"] = details
    return d


def get_backtest_history(
    db: Session, limit: int = 20, strategy_name: str | None = None
) -> list[dict]:
    """获取最近回测记录（仅摘要指标，不含 backtest_details）"""
    q = db.query(BacktestResult).order_by(desc(BacktestResult.created_at))
    if strategy_name:
        q = q.filter(BacktestResult.strategy_name == strategy_name)
    results = q.limit(limit).all()
    return [_result_to_dict(r) for r in results]


# ── 内部辅助 ──────────────────────────────────────────────


def _result_to_dict(r: BacktestResult) -> dict:
    return {
        "backtest_id": str(r.backtest_id),
        "strategy_name": r.strategy_name,
        "strategy_version": r.strategy_version,
        "ts_code": r.ts_code or "",
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
