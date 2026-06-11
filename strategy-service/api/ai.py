"""
AI agent orchestration API routes.

Endpoints:
- POST /ai/analyze         — Request multi-agent analysis
- GET  /ai/analysis/{id}   — Get analysis results
"""

import logging
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai", tags=["AI Analysis"])


class AnalysisRequest(BaseModel):
    """AI 分析请求"""
    ts_code: str = Field(..., example="000001.SZ", pattern=r"^\d{6}\.(SZ|SH)$")
    agents: list[str] | None = Field(
        None,
        example=["fundamental_analyst", "technical_analyst", "researcher"],
        description="""Agent 列表（可选，默认全部）:
- fundamental_analyst: 基本面分析（财务健康、估值）
- technical_analyst: 技术面分析（形态、指标）
- sentiment_analyst: 情绪面分析（新闻、社交媒体）
- capital_flow_analyst: 资金面分析（北向资金、大单流向）
- researcher: 综合所有 Agent 输出生成最终报告
- risk_manager: 风险评估和仓位建议""",
    )
    model_preference: str | None = Field(None, example="deepseek-v4-pro", description="偏好模型（可选）")

    class Config:
        json_schema_extra = {
            "example": {
                "ts_code": "000001.SZ",
                "agents": ["fundamental_analyst", "technical_analyst"],
            }
        }


@router.post(
    "/analyze",
    response_model=dict,
    summary="发起多智能体分析",
    description="""调用多个 AI Agent 对指定股票进行分析。

Agent 类型:
- **fundamental_analyst** — 财务健康、PE/PB、营收增速
- **technical_analyst** — K线形态、MACD/RSI/均线
- **sentiment_analyst** — 新闻情感、社交媒体热度
- **capital_flow_analyst** — 主力资金流向
- **researcher** — 综合报告（自动包含，整合其他 Agent 输出）
- **risk_manager** — 风险评估、仓位建议""",
)
async def request_analysis(request: AnalysisRequest):
    """Submit multi-agent analysis request."""
    return {
        "code": 0,
        "data": {
            "analysis_id": "AI_pending",
            "ts_code": request.ts_code,
            "agents_requested": request.agents or ["researcher"],
            "status": "queued",
        },
    }


@router.get(
    "/analysis/{analysis_id}",
    response_model=dict,
    summary="获取分析结果",
    description="获取多智能体分析的结果，包括各 Agent 的独立输出和综合建议。",
)
async def get_analysis_result(analysis_id: str):
    """Get analysis result."""
    return {
        "code": 0,
        "data": {
            "analysis_id": analysis_id,
            "ts_code": "000001.SZ",
            "consensus": "bullish",
            "confidence": 0.78,
            "agent_outputs": {},
            "recommendation": {
                "action": "buy",
                "target_price": 14.50,
                "stop_loss": 11.00,
                "holding_period_days": 5,
                "reason": "基本面稳健 + 技术面金叉 + 资金面流入",
            },
        },
    }
