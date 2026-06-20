"""
多智能体协作框架 — 智能体基类

包含 BaseAgent 基类，提供：
- 通用 AI 模型调用（真实 API / 模拟降级）
- 智能模型调度（跨厂商路由）
- 缓存优化：system prompt 作为固定前缀提高 KV Cache 命中率
"""

import logging
from typing import Any

from .models import AnalysiResult, StockData

logger = logging.getLogger(__name__)


class BaseAgent:
    """智能体基类"""

    def __init__(self, name: str, model_scheduler=None, ai_client=None):
        self.name = name
        self.model_scheduler = model_scheduler
        self.ai_client = ai_client
        logger.info(f"智能体初始化：{name}")

    def analyze(self, stock_data: StockData, context: dict[str, Any] = None) -> AnalysiResult:
        """
        分析股票
        子类必须实现此方法
        """
        raise NotImplementedError("子类必须实现analyze方法")

    def _call_ai_model(
        self, user_message: str, system_prompt: str = None, task_type: str = "analysis"
    ) -> str:
        """
        调用AI模型（真实API调用）
        支持智能调度和成本优化
        缓存优化：system prompt作为固定前缀→提高cache命中率
        """
        if not self.ai_client:
            logger.warning(f"{self.name}: AIClient未配置，使用模拟分析")
            return self._simulate_analysis(user_message)

        try:
            # 使用智能调度选择模型
            model_name = "deepseek-chat"
            provider_name = "deepseek"

            if self.model_scheduler:
                from ..ai_scheduler import TaskComplexity, TaskType

                task_map = {
                    "analysis": TaskType.MULTI_AGENT_DEBATE,
                    "sentiment": TaskType.NEWS_SENTIMENT,
                    "selection": TaskType.STOCK_SELECTION,
                    "report": TaskType.DATA_CLEANING,
                    "fundamental_analysis": TaskType.NEWS_SENTIMENT,
                    "technical_analysis": TaskType.MULTI_AGENT_DEBATE,
                    "money_flow_analysis": TaskType.RISK_ASSESSMENT,
                    "sentiment_analysis": TaskType.NEWS_SENTIMENT,
                    "debate": TaskType.MULTI_AGENT_DEBATE,
                }
                selected = self.model_scheduler.select_model(
                    task_map.get(task_type, TaskType.MULTI_AGENT_DEBATE), TaskComplexity.HIGH
                )

                # 模型→Provider映射（支持跨厂商调度）
                model_provider_map = {
                    "Deepseek-V4-Flash": ("deepseek", "deepseek-chat"),
                    "Deepseek-V4-Pro": ("deepseek", "deepseek-reasoner"),
                    "DeepSeek-V3.2": ("deepseek", "deepseek-chat"),
                    "GLM-5.0-Turbo": ("glm", "glm-4-flash"),
                    "GLM-5.1": ("glm", "glm-4"),
                    "MiniMax-M2.7": ("minimax", "abab6.5s-chat"),
                    "Kimi-K2.5": ("kimi", "moonshot-v1-8k"),
                    "Kimi-K2.6": ("kimi", "moonshot-v1-32k"),
                    "Hy3 preview": ("deepseek", "deepseek-chat"),  # HY3→DeepSeek兼容
                }
                provider_name, model_name = model_provider_map.get(
                    selected, ("deepseek", "deepseek-chat")
                )
                logger.info(f"智能调度选择: {selected} → {provider_name}/{model_name}")

            from ..ai_client import ModelProvider

            PROVIDER_MAP = {
                "deepseek": ModelProvider.DEEPSEEK,
                "glm": ModelProvider.GLM,
                "kimi": ModelProvider.KIMI,
                "minimax": ModelProvider.MINIMAX,
            }
            provider = PROVIDER_MAP.get(provider_name, ModelProvider.DEEPSEEK)

            # 构建消息：固定system prompt（缓存命中）+ 动态user message（不命中）
            messages = [{"role": "user", "content": user_message}]
            if system_prompt:
                # system角色在最前面，作为缓存前缀
                messages = [{"role": "system", "content": system_prompt}] + messages

            result = self.ai_client.call_sync(
                provider=provider,
                model_name=model_name,
                messages=messages,
                temperature=0.3,
                max_tokens=4096,
            )

            if result.success:
                content: str = result.content
                return content
            logger.warning(f"AI调用失败（降级模拟）: {result.error}")
            return self._simulate_analysis(user_message)

        except Exception as e:
            logger.warning(f"AI模型调用异常（降级模拟）: {e}")
            return self._simulate_analysis(user_message)

    def _simulate_analysis(self, user_message: str) -> str:
        """降级：模拟分析结果（当AI不可用时）"""
        return f"{self.name}的分析结果（模拟模式）"
