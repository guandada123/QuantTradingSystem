"""
多智能体协作框架 — 交易系统编排器

包含 MultiAgentTradingSystem，负责编排多智能体协作流程：
1. 并行分析（4个分析师智能体）
2. 多空辩论（2个研究员智能体）
3. 风险评估（风险管理员智能体）
4. 交易决策（交易员智能体）
"""

import logging
from typing import Any

from .agents import (
    BearResearcher,
    BullResearcher,
    FundamentalAnalyst,
    MoneyFlowAnalyst,
    RiskManager,
    SentimentAnalyst,
    TechnicalAnalyst,
    Trader,
)
from .models import StockData, TradingDecision

logger = logging.getLogger(__name__)


class MultiAgentTradingSystem:
    """多智能体交易系统"""

    def __init__(self, model_scheduler=None, ai_client=None):
        """初始化多智能体系统"""
        self.model_scheduler = model_scheduler
        self.ai_client = ai_client

        # 初始化所有智能体（传递ai_client以支持真实AI调用）
        self.agents = {
            "fundamental_analyst": FundamentalAnalyst(model_scheduler, ai_client),
            "technical_analyst": TechnicalAnalyst(model_scheduler, ai_client),
            "money_flow_analyst": MoneyFlowAnalyst(model_scheduler, ai_client),
            "sentiment_analyst": SentimentAnalyst(model_scheduler, ai_client),
            "bull_researcher": BullResearcher(model_scheduler, ai_client),
            "bear_researcher": BearResearcher(model_scheduler, ai_client),
            "risk_manager": RiskManager(model_scheduler, ai_client),
            "trader": Trader(model_scheduler, ai_client),
        }

        logger.info("多智能体交易系统初始化完成")

    def analyze_stock(
        self, stock_data: StockData, market_context: dict[str, Any]
    ) -> TradingDecision:
        """
        完整的股票分析流程（多智能体协作）

        流程：
        1. 并行分析（4个分析师智能体）
        2. 多空辩论（2个研究员智能体）
        3. 风险评估（风险管理员智能体）
        4. 交易决策（交易员智能体）
        """
        logger.info(f"开始分析股票：{stock_data.ts_code}")

        # ===== 第一阶段：并行分析 =====
        analysis_results = []

        # 基本面分析
        fundamental_result = self.agents["fundamental_analyst"].analyze(stock_data, market_context)
        analysis_results.append(fundamental_result)

        # 技术面分析
        technical_result = self.agents["technical_analyst"].analyze(stock_data, market_context)
        analysis_results.append(technical_result)

        # 资金面分析
        money_flow_result = self.agents["money_flow_analyst"].analyze(stock_data, market_context)
        analysis_results.append(money_flow_result)

        # 情绪分析
        sentiment_result = self.agents["sentiment_analyst"].analyze(stock_data, market_context)
        analysis_results.append(sentiment_result)

        logger.info("第一阶段完成：4个分析师完成分析")

        # ===== 第二阶段：多空辩论 =====
        debate_arguments = []

        # 看涨研究员辩论
        bull_argument = self.agents["bull_researcher"].debate(analysis_results)  # type: ignore[attr-defined]
        debate_arguments.append(bull_argument)

        # 看跌研究员辩论
        bear_argument = self.agents["bear_researcher"].debate(analysis_results)  # type: ignore[attr-defined]
        debate_arguments.append(bear_argument)

        logger.info("第二阶段完成：多空辩论结束")

        # ===== 第三阶段：风险评估 =====
        # 获取当前持仓（如果有）
        current_position = market_context.get("positions", {}).get(stock_data.ts_code)

        # 初步交易决策（用于风险评估）
        preliminary_decision = self.agents["trader"].make_decision(  # type: ignore[attr-defined]
            stock_data.ts_code,
            analysis_results,
            debate_arguments,
            {"risk_level": "LOW", "recommended_action": "APPROVE"},  # 临时，后面会重新评估
        )

        # 风险评估
        risk_assessment = self.agents["risk_manager"].assess_risk(  # type: ignore[attr-defined]
            stock_data.ts_code, current_position, preliminary_decision, market_context
        )

        logger.info(f"第三阶段完成：风险评估完成，风险等级={risk_assessment['risk_level']}")

        # ===== 第四阶段：最终交易决策 =====
        final_decision = self.agents["trader"].make_decision(  # type: ignore[attr-defined]
            stock_data.ts_code, analysis_results, debate_arguments, risk_assessment
        )

        logger.info(
            f"第四阶段完成：最终决策={final_decision.action}，置信度={final_decision.confidence:.1f}"
        )

        # 返回最终决策
        decision: TradingDecision = final_decision
        return decision

    def batch_analyze(
        self, stock_list: list[StockData], market_context: dict[str, Any]
    ) -> list[TradingDecision]:
        """
        批量分析多只股票
        """
        decisions = []

        for stock_data in stock_list:
            decision = self.analyze_stock(stock_data, market_context)
            decisions.append(decision)

        return decisions
