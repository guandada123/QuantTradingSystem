"""
多智能体协作框架 v2.2（缓存优化版）

参考TradingAgents-CN架构，实现AI原生交易决策系统
包含：基本面分析师、技术面分析师、资金面分析师、情绪分析师、
      研究员（多空辩论）、风险管理员、交易员

v2.2 变更：提示词外置为 YAML 配置文件，支持非程序员调优
"""

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
from .base import BaseAgent
from .models import AnalysiResult, DebateArgument, StockData, TradingDecision
from .system import MultiAgentTradingSystem

__all__ = [
    # 数据模型
    "StockData",
    "AnalysiResult",
    "DebateArgument",
    "TradingDecision",
    # 基类
    "BaseAgent",
    # 分析师
    "FundamentalAnalyst",
    "TechnicalAnalyst",
    "MoneyFlowAnalyst",
    "SentimentAnalyst",
    # 研究员
    "BullResearcher",
    "BearResearcher",
    # 风险 & 交易
    "RiskManager",
    "Trader",
    # 编排器
    "MultiAgentTradingSystem",
]
