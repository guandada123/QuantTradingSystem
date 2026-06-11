"""
Trading signal API routes for the Strategy Research Service.

Endpoints:
- GET  /signals/     — List trading signals with optional filters
- GET  /signals/{id} — Get signal detail with analysis
"""

import logging
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/signals", tags=["Signals"])


class SignalItem(BaseModel):
    """交易信号条目"""
    signal_id: str = Field(..., example="SIG_001")
    ts_code: str = Field(..., example="000001.SZ", description="证券代码")
    name: str = Field("", example="平安银行")
    signal_type: str = Field(..., example="golden_cross", description="信号类型: golden_cross, macd_divergence, volume_breakout")
    direction: str = Field("BUY", example="BUY", description="BUY / SELL")
    confidence: float = Field(..., ge=0, le=1, example=0.85)
    price: float = Field(..., example=12.50)
    created_at: str = Field(..., example="2026-06-11T14:30:00")

    class Config:
        json_schema_extra = {
            "example": {
                "signal_id": "SIG_001",
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "signal_type": "golden_cross",
                "direction": "BUY",
                "confidence": 0.85,
                "price": 12.50,
                "created_at": "2026-06-11T14:30:00",
            }
        }


@router.get(
    "/",
    response_model=dict,
    summary="获取交易信号列表",
    description="获取最近的交易信号，可按股票代码和信号类型筛选。置信度 ≥ 0.7 的信号为高置信度。",
)
async def get_signals(
    ts_code: str | None = Query(None, example="000001.SZ", description="证券代码（可选）"),
    signal_type: str | None = Query(None, example="golden_cross", description="信号类型（可选）"),
    min_confidence: float = Query(0.5, ge=0, le=1, description="最低置信度阈值"),
    limit: int = Query(50, ge=1, le=200, description="返回数量上限"),
):
    """Get trading signals with optional filters."""
    filters = {
        "ts_code": ts_code,
        "signal_type": signal_type,
        "min_confidence": min_confidence,
    }
    return {
        "code": 0,
        "data": {"signals": [], "total": 0, "filters": {k: v for k, v in filters.items() if v}},
    }


@router.get(
    "/{signal_id}",
    response_model=dict,
    summary="获取信号详情",
    description="获取指定信号的详细分析结果，包括触发因素和关联指标。",
)
async def get_signal_detail(signal_id: str):
    """Get detailed signal analysis."""
    return {
        "code": 0,
        "data": {
            "signal_id": signal_id,
            "analysis": {},
            "confidence": 0.0,
        },
    }
