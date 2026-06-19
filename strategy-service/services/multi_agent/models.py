"""
多智能体协作框架 — 数据模型

包含所有 Pydantic 数据模型：
- StockData       股票行情数据
- AnalysiResult   分析结果（分析师输出）
- DebateArgument  辩论论点（研究员输出）
- TradingDecision 交易决策（交易员输出）
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StockData(BaseModel):
    """股票数据模型"""

    ts_code: str
    name: str
    current_price: float
    open: float
    high: float
    low: float
    volume: int
    amount: float
    change: float
    pct_change: float


class AnalysiResult(BaseModel):
    """分析结果模型"""

    agent_name: str
    ts_code: str
    signal: str  # 'BUY'/'SELL'/'HOLD'
    confidence: float  # 0-100
    reason: str
    key_indicators: dict[str, Any]
    risks: list[str]
    timestamp: datetime = Field(default_factory=datetime.now)


class DebateArgument(BaseModel):
    """辩论论点模型"""

    agent_name: str
    stance: str  # 'BULL'/'BEAR'/'NEUTRAL'
    argument: str
    evidence: list[str]
    confidence: float
    timestamp: datetime = Field(default_factory=datetime.now)


class TradingDecision(BaseModel):
    """交易决策模型"""

    ts_code: str
    action: str  # 'BUY'/'SELL'/'HOLD'
    quantity: int | None = None
    target_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: float
    reasoning: str
    risk_assessment: str
    timestamp: datetime = Field(default_factory=datetime.now)
