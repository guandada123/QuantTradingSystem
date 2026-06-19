"""
数据仓库层 - Walk-Forward 分析结果持久化 (P2-ARCH-05)

提供 WalkForwardResult 的保存、列表查询和详情查询功能。
结果以 JSON 格式存储窗口数据，便于前端直接渲染。
"""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from models.models import WalkForwardResult
from sqlalchemy import desc
from sqlalchemy.orm import Session


def _serialize_for_json(obj: Any) -> Any:
    """将 Decimal/datetime/date 等类型转换为 JSON 可序列化类型"""
    if isinstance(obj, (Decimal, uuid.UUID)):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def _dict_to_json(d: dict) -> Any:
    """递归转换字典中的特殊类型为 JSON 友好格式"""
    if not d:
        return d
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _dict_to_json(v)
        elif isinstance(v, list):
            result[k] = [  # noqa: ECE001
                _dict_to_json(item) if isinstance(item, dict) else _serialize_for_json(item)
                for item in v
            ]
        else:
            result[k] = _serialize_for_json(v)
    return result


def save_walkforward_result(
    db: Session,
    *,
    strategy_name: str,
    ts_code: str,
    start_date: str,
    end_date: str,
    train_days: int,
    test_days: int,
    step_days: int,
    param_grid: dict | None,
    initial_cash: float,
    slippage: float,
    commission_rate: float,
    benchmark: str,
    windows: list[dict],
    overall_test_return: float,
    overfit_ratio: float,
    num_windows: int,
    data_source: str = "tencent",
) -> str:
    """保存 Walk-Forward 分析结果到数据库

    Args:
        db: DB session
        strategy_name: 策略名称
        ts_code: 股票代码
        start_date/end_date: 分析日期范围
        train_days/test_days/step_days: 窗口参数
        param_grid: 使用的参数网格
        windows: 各窗口分析结果
        overall_test_return/overfit_ratio/num_windows: 汇总指标
        data_source: 数据源

    Returns:
        wf_id (UUID 字符串)
    """
    # 日期格式 YYYYMMDD → date
    def _parse_date(d: str) -> date:
        d_clean = d.replace("-", "")
        return date(int(d_clean[:4]), int(d_clean[4:6]), int(d_clean[6:8]))

    record = WalkForwardResult(
        strategy_name=strategy_name,
        ts_code=ts_code,
        start_date=_parse_date(start_date),
        end_date=_parse_date(end_date),
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        param_grid=_dict_to_json(param_grid) if param_grid else None,
        initial_cash=initial_cash,
        slippage=slippage,
        commission_rate=commission_rate,
        benchmark=benchmark,
        windows=json.loads(json.dumps(windows, default=_serialize_for_json)),
        overall_test_return=overall_test_return,
        overfit_ratio=overfit_ratio,
        num_windows=num_windows,
        data_source=data_source,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return str(record.wf_id)


def get_walkforward_history(
    db: Session,
    limit: int = 20,
    strategy_name: str | None = None,
) -> list[dict]:
    """查询 Walk-Forward 历史列表（不含窗口详情）

    Args:
        db: DB session
        limit: 返回条数
        strategy_name: 按策略筛选

    Returns:
        摘要字典列表
    """
    query = db.query(WalkForwardResult)
    if strategy_name:
        query = query.filter(WalkForwardResult.strategy_name == strategy_name)
    records = (
        query.order_by(desc(WalkForwardResult.created_at))
        .limit(limit)
        .all()
    )

    result = []
    for r in records:
        result.append(
            {
                "wf_id": str(r.wf_id),
                "strategy_name": r.strategy_name,
                "ts_code": r.ts_code,
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat(),
                "train_days": r.train_days,
                "test_days": r.test_days,
                "step_days": r.step_days,
                "overall_test_return": float(r.overall_test_return) if r.overall_test_return else None,
                "overfit_ratio": float(r.overfit_ratio) if r.overfit_ratio else None,
                "num_windows": r.num_windows,
                "data_source": r.data_source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return result


def get_walkforward_detail(
    db: Session,
    wf_id: str,
) -> dict | None:
    """查询单条 Walk-Forward 完整结果（含窗口详情）

    Args:
        db: DB session
        wf_id: Walk-Forward 结果 UUID

    Returns:
        完整字典，不存在时返回 None
    """
    try:
        uid = uuid.UUID(wf_id)
    except ValueError:
        return None

    record = db.query(WalkForwardResult).filter(
        WalkForwardResult.wf_id == uid
    ).first()

    if record is None:
        return None

    return {
        "wf_id": str(record.wf_id),
        "strategy_name": record.strategy_name,
        "ts_code": record.ts_code,
        "start_date": record.start_date.isoformat(),
        "end_date": record.end_date.isoformat(),
        "train_days": record.train_days,
        "test_days": record.test_days,
        "step_days": record.step_days,
        "param_grid": record.param_grid,
        "initial_cash": float(record.initial_cash) if record.initial_cash else None,
        "slippage": float(record.slippage) if record.slippage else None,
        "commission_rate": float(record.commission_rate) if record.commission_rate else None,
        "benchmark": record.benchmark,
        "windows": record.windows,
        "overall_test_return": float(record.overall_test_return) if record.overall_test_return else None,
        "overfit_ratio": float(record.overfit_ratio) if record.overfit_ratio else None,
        "num_windows": record.num_windows,
        "data_source": record.data_source,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
