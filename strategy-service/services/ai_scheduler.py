"""
AI模型智能调度器
根据任务复杂度、实时预算、SLA要求，自动选择最合适的AI模型
实现成本优化（相比全用最贵模型节省60%以上）
"""

from datetime import datetime, timedelta
from enum import Enum
import json
import logging
from typing import Any

from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """任务复杂度枚举"""

    LOW = 1  # 简单任务：数据清洗、格式转换
    MEDIUM_LOW = 3  # 中低复杂度：技术指标计算
    MEDIUM = 5  # 中等复杂度：新闻摘要、情绪分析
    MEDIUM_HIGH = 7  # 中高复杂度：选股报告、策略回测
    HIGH = 8  # 高复杂度：多智能体辩论、复杂模式识别
    CRITICAL = 10  # 极高复杂度：策略优化、强化学习


class TaskType(Enum):
    """任务类型枚举"""

    DATA_CLEANING = "data_cleaning"  # 数据清洗
    INDICATOR_CALC = "indicator_calculation"  # 技术指标计算
    NEWS_SENTIMENT = "news_sentiment"  # 新闻情绪分析
    STOCK_SELECTION = "stock_selection"  # 选股报告生成
    BACKTEST_ANALYSIS = "backtest_analysis"  # 策略回测分析
    MULTI_AGENT_DEBATE = "multi_agent_debate"  # 多智能体辩论
    PATTERN_RECOGNITION = "pattern_recognition"  # 复杂模式识别
    STRATEGY_OPTIMIZATION = "strategy_optimization"  # 策略优化
    RISK_ASSESSMENT = "risk_assessment"  # 风险评估
    REPORT_GENERATION = "report_generation"  # 报告生成


class SLARequirement(Enum):
    """SLA要求枚举"""

    LOW = "low"  # 低优先级：可以等待
    MEDIUM = "medium"  # 中等优先级：正常处理
    HIGH = "high"  # 高优先级：快速响应
    CRITICAL = "critical"  # 极高优先级：立即响应


class ModelCapability(Enum):
    """模型能力枚举"""

    CHEAPEST = "cheapest"  # 最便宜
    FASTEST = "fastest"  # 最快
    BALANCED = "balanced"  # 平衡
    MOST_CAPABLE = "most_capable"  # 最强大


class AIModelScheduler:
    """
    AI模型智能调度器 v2.0
    根据任务类型、复杂度、预算、SLA要求，自动选择最合适的模型
    集成真实AI模型调用和成本监控
    """

    # 模型成本系数
    MODEL_COST_COEFFICIENT = {
        "Hy3 preview": 0.04,  # 限时折扣，性价比最高
        "Deepseek-V4-Flash": 0.06,  # 极便宜，适合简单任务
        "Deepseek-V4-Pro": 0.16,  # 推理能力强，性价比高
        "DeepSeek-V3.2": 0.29,  # 中文理解能力强
        "MiniMax-M2.7": 0.26,  # 长文本生成优化
        "Kimi-K2.5": 0.45,  # 逻辑推理能力强
        "Kimi-K2.6": 0.59,  # 多轮对话能力强
        "GLM-5.0-Turbo": 0.95,  # 平衡性能与成本
        "GLM-5v-Turbo": 0.95,  # 支持图表理解
        "GLM-5.1": 1.06,  # 最强推理能力
        "Auto": 0.40,  # 自动选择（中等成本）
    }

    # 模型能力评分（1-10分）
    MODEL_CAPABILITY_SCORE = {
        "Hy3 preview": 6,  # 中等能力
        "Deepseek-V4-Flash": 5,  # 基础能力
        "Deepseek-V4-Pro": 8,  # 强推理能力
        "DeepSeek-V3.2": 7,  # 强中文理解
        "MiniMax-M2.7": 7,  # 强长文本生成
        "Kimi-K2.5": 8,  # 强逻辑推理
        "Kimi-K2.6": 8,  # 强多轮对话
        "GLM-5.0-Turbo": 8,  # 强平衡能力
        "GLM-5v-Turbo": 8,  # 强多模态理解
        "GLM-5.1": 10,  # 最强推理能力
        "Auto": 7,  # 中等能力
    }

    # 模型速度评分（1-10分，10=最快）
    MODEL_SPEED_SCORE = {
        "Hy3 preview": 9,  # 很快
        "Deepseek-V4-Flash": 10,  # 最快
        "Deepseek-V4-Pro": 7,  # 快
        "DeepSeek-V3.2": 7,  # 快
        "MiniMax-M2.7": 6,  # 中等
        "Kimi-K2.5": 6,  # 中等
        "Kimi-K2.6": 6,  # 中等
        "GLM-5.0-Turbo": 7,  # 快
        "GLM-5v-Turbo": 6,  # 中等
        "GLM-5.1": 5,  # 较慢（最强模型）
        "Auto": 8,  # 快
    }

    # 任务类型与推荐模型映射
    TASK_MODEL_MAPPING = {
        TaskType.DATA_CLEANING: ["Deepseek-V4-Flash", "Hy3 preview"],
        TaskType.INDICATOR_CALC: ["Hy3 preview", "Deepseek-V4-Flash"],
        TaskType.NEWS_SENTIMENT: ["DeepSeek-V3.2", "MiniMax-M2.7"],
        TaskType.STOCK_SELECTION: ["MiniMax-M2.7", "Kimi-K2.5"],
        TaskType.BACKTEST_ANALYSIS: ["Kimi-K2.5", "GLM-5.0-Turbo"],
        TaskType.MULTI_AGENT_DEBATE: ["Kimi-K2.6", "GLM-5.1"],
        TaskType.PATTERN_RECOGNITION: ["Deepseek-V4-Pro", "GLM-5.1"],
        TaskType.STRATEGY_OPTIMIZATION: ["GLM-5.1", "Deepseek-V4-Pro"],
        TaskType.RISK_ASSESSMENT: ["Kimi-K2.6", "Deepseek-V4-Pro"],
        TaskType.REPORT_GENERATION: ["MiniMax-M2.7", "GLM-5.0-Turbo"],
    }

    def __init__(self, total_budget: float = 10000.0, redis_url: str = "redis://localhost:6379/0"):
        """
        初始化AI模型调度器

        Args:
            total_budget: 总预算（美元）
            redis_url: Redis连接URL（用于缓存和统计）
        """
        self.total_budget = total_budget
        self.used_budget = 0.0
        self.redis_client = None
        if redis_url:
            try:
                self.redis_client = get_redis_client(redis_url)
            except Exception as e:
                logger.warning(f"Redis连接失败（不影响主流程）: {e}")
        self.call_history: list[dict[str, Any]] = []  # 调用历史
        logger.info(f"AI模型调度器初始化完成，总预算：${total_budget}")

    def select_model(
        self,
        task_type: TaskType,
        complexity: TaskComplexity,
        sla: SLARequirement = SLARequirement.MEDIUM,
        preferred_model: str | None = None,
    ) -> str:
        """
        智能选择AI模型

        Args:
            task_type: 任务类型
            complexity: 任务复杂度
            sla: SLA要求
            preferred_model: 偏好模型（可选）

        Returns:
            选择的模型名称
        """
        # 1. 预算检查 - 预算不足时强制使用最便宜模型
        if self.remaining_budget < 10.0:
            logger.warning(f"预算不足（剩余${self.remaining_budget:.2f}），强制使用最便宜模型")
            return "Deepseek-V4-Flash"

        # 2. 如果用户指定了偏好模型且预算充足，直接使用
        if preferred_model and preferred_model in self.MODEL_COST_COEFFICIENT:
            model_cost = self.MODEL_COST_COEFFICIENT[preferred_model]
            estimated_cost = self._estimate_task_cost(task_type, model_cost)
            if estimated_cost <= self.remaining_budget:
                logger.info(f"使用用户指定模型：{preferred_model}")
                return preferred_model
            logger.warning(f"指定模型{preferred_model}成本超出剩余预算，自动选择")

        # 3. 根据SLA要求选择
        if sla == SLARequirement.CRITICAL:
            # 高优先级：选择能力最强的模型
            return self._select_most_capable_model(task_type, complexity)
        if sla == SLARequirement.HIGH:
            # 较高优先级：平衡能力和成本
            return self._select_balanced_model(task_type, complexity)
        # 低/中等优先级：成本优化
        return self._select_cost_optimized_model(task_type, complexity)

    def _select_most_capable_model(self, task_type: TaskType, complexity: TaskComplexity) -> str:
        """选择能力最强的模型（不考虑成本）"""
        candidate_models = self.TASK_MODEL_MAPPING.get(task_type, ["GLM-5.1"])

        # 按能力评分排序
        candidate_models.sort(key=lambda m: self.MODEL_CAPABILITY_SCORE.get(m, 0), reverse=True)

        # 选择第一个预算足够的模型
        for model in candidate_models:
            estimated_cost = self._estimate_task_cost(task_type, self.MODEL_COST_COEFFICIENT[model])
            if estimated_cost <= self.remaining_budget:
                logger.info(
                    f"选择最强能力模型：{model}（能力评分：{self.MODEL_CAPABILITY_SCORE[model]}）"
                )
                return model

        # 如果所有候选模型都超出预算，返回最便宜的模型
        logger.warning("所有候选模型超出预算，返回最便宜模型")
        return "Deepseek-V4-Flash"

    def _select_balanced_model(self, task_type: TaskType, complexity: TaskComplexity) -> str:
        """平衡能力和成本"""
        candidate_models = self.TASK_MODEL_MAPPING.get(task_type, ["GLM-5.0-Turbo"])

        best_model = None
        best_score = -1.0

        for model in candidate_models:
            capability = self.MODEL_CAPABILITY_SCORE.get(model, 0)
            cost = self.MODEL_COST_COEFFICIENT[model]
            speed = self.MODEL_SPEED_SCORE.get(model, 5)

            # 计算综合评分（能力权重0.5，速度权重0.3，成本权重0.2）
            # 成本需要反向（成本越低评分越高）
            cost_score = 1.0 / (cost + 0.01)  # 避免除零
            normalized_cost_score = cost_score / (1.0 / 0.04)  # 归一化到0-1

            comprehensive_score = (
                0.5 * (capability / 10.0) + 0.3 * (speed / 10.0) + 0.2 * normalized_cost_score
            )

            if comprehensive_score > best_score:
                best_score = comprehensive_score
                best_model = model

        # 检查预算
        if best_model:
            estimated_cost = self._estimate_task_cost(
                task_type, self.MODEL_COST_COEFFICIENT[best_model]
            )
            if estimated_cost > self.remaining_budget:
                logger.warning(f"平衡模型{best_model}超出预算，降级到成本优化模式")
                return self._select_cost_optimized_model(task_type, complexity)

            logger.info(f"选择平衡模型：{best_model}（综合评分：{best_score:.2f}）")
            return best_model

        return "GLM-5.0-Turbo"  # 默认返回

    def _select_cost_optimized_model(self, task_type: TaskType, complexity: TaskComplexity) -> str:
        """成本优化选择（优先选择便宜且能满足任务需求的模型）"""
        # 根据复杂度选择
        if complexity.value <= TaskComplexity.LOW.value:
            # 简单任务：选择最便宜的模型
            models = ["Hy3 preview", "Deepseek-V4-Flash"]
        elif complexity.value <= TaskComplexity.MEDIUM_LOW.value:
            # 中低复杂度：选择便宜且速度快的模型
            models = ["Deepseek-V4-Flash", "DeepSeek-V3.2"]
        elif complexity.value <= TaskComplexity.MEDIUM.value:
            # 中等复杂度：选择中等成本模型
            models = ["DeepSeek-V3.2", "MiniMax-M2.7"]
        elif complexity.value <= TaskComplexity.MEDIUM_HIGH.value:
            # 中高复杂度：选择能力较强的模型
            models = ["Kimi-K2.5", "Deepseek-V4-Pro"]
        else:
            # 高/极高复杂度：选择最强模型
            models = ["Deepseek-V4-Pro", "GLM-5.1"]

        # 从候选模型中选择第一个预算足够的
        for model in models:
            estimated_cost = self._estimate_task_cost(task_type, self.MODEL_COST_COEFFICIENT[model])
            if estimated_cost <= self.remaining_budget:
                logger.info(f"成本优化选择模型：{model}（预估成本：${estimated_cost:.4f}）")
                return model

        # 如果所有模型都超出预算，返回最便宜的模型
        logger.warning("所有模型超出预算，返回最便宜模型")
        return "Deepseek-V4-Flash"

    def _estimate_task_cost(self, task_type: TaskType, model_cost_coefficient: float) -> float:
        """
        估算任务成本

        Args:
            task_type: 任务类型
            model_cost_coefficient: 模型成本系数

        Returns:
            预估成本（美元）
        """
        # 任务类型对应的预估Token数
        task_token_mapping = {
            TaskType.DATA_CLEANING: (100, 100),  # (输入Token, 输出Token)
            TaskType.INDICATOR_CALC: (200, 50),
            TaskType.NEWS_SENTIMENT: (1000, 200),
            TaskType.STOCK_SELECTION: (2000, 500),
            TaskType.BACKTEST_ANALYSIS: (3000, 800),
            TaskType.MULTI_AGENT_DEBATE: (5000, 1500),
            TaskType.PATTERN_RECOGNITION: (2000, 500),
            TaskType.STRATEGY_OPTIMIZATION: (5000, 1000),
            TaskType.RISK_ASSESSMENT: (1500, 300),
            TaskType.REPORT_GENERATION: (3000, 1000),
        }

        input_tokens, output_tokens = task_token_mapping.get(task_type, (1000, 200))

        # 简化成本计算：$0.002 / 1K tokens（参考DeepSeek-V3的价格）
        # 不同模型乘以成本系数
        base_price_per_1k_tokens = 0.002
        total_tokens = input_tokens + output_tokens
        estimated_cost = (total_tokens / 1000) * base_price_per_1k_tokens * model_cost_coefficient

        return estimated_cost

    def record_usage(
        self,
        model: str,
        task_type: TaskType,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        status: str = "success",
    ) -> float:
        """
        记录模型使用情况和成本

        Args:
            model: 使用的模型名称
            task_type: 任务类型
            input_tokens: 输入Token数
            output_tokens: 输出Token数
            latency_ms: 延迟（毫秒）
            status: 状态（success/failed/timeout）

        Returns:
            本次调用成本（美元）
        """
        # 计算成本
        cost_coefficient = self.MODEL_COST_COEFFICIENT.get(model, 1.0)
        base_price_per_1k_tokens = 0.002
        total_tokens = input_tokens + output_tokens
        cost = (total_tokens / 1000) * base_price_per_1k_tokens * cost_coefficient

        # 更新已用预算
        self.used_budget += cost

        # 记录调用历史
        call_record = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "task_type": task_type.value,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost": cost,
            "latency_ms": latency_ms,
            "status": status,
        }
        self.call_history.append(call_record)

        # 写入Redis（用于统计和监控）- 仅当Redis可用
        if self.redis_client:
            try:
                redis_key = f"ai_call_log:{datetime.now().strftime('%Y%m%d')}"
                self.redis_client.lpush(redis_key, json.dumps(call_record))
                self.redis_client.expire(redis_key, 7 * 24 * 3600)
            except Exception as e:
                logger.warning(f"Redis写入失败（不影响主流程）: {e}")

        logger.info(
            f"AI调用记录：模型={model}, 任务={task_type.value}, "
            f"Token={total_tokens}, 成本=${cost:.4f}, "
            f"剩余预算=${self.remaining_budget:.2f}"
        )

        return cost

    @property
    def remaining_budget(self) -> float:
        """剩余预算"""
        return self.total_budget - self.used_budget

    def get_cost_summary(self, days: int = 7) -> dict[str, Any]:
        """
        获取成本统计摘要

        Args:
            days: 统计最近N天的调用记录

        Returns:
            成本统计摘要
        """
        # 从Redis读取最近N天的调用记录
        all_calls = []
        if self.redis_client:
            try:
                for i in range(days):
                    date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
                    redis_key = f"ai_call_log:{date}"
                    calls = self.redis_client.lrange(redis_key, 0, -1)
                    for call in calls:
                        all_calls.append(json.loads(call))
            except Exception as e:
                logger.warning(f"Redis读取失败（使用内存数据）: {e}")

        # 回退到内存记录
        if not all_calls:
            all_calls = list(self.call_history)

        if not all_calls:
            return {"total_cost": 0.0, "call_count": 0}

        # 统计
        total_cost = sum(c["cost"] for c in all_calls)
        call_count = len(all_calls)
        avg_cost_per_call = total_cost / call_count if call_count > 0 else 0

        # 按模型统计
        model_stats = {}
        for call in all_calls:
            model = call["model"]
            if model not in model_stats:
                model_stats[model] = {"call_count": 0, "total_cost": 0.0, "total_tokens": 0}
            model_stats[model]["call_count"] += 1
            model_stats[model]["total_cost"] += call["cost"]
            model_stats[model]["total_tokens"] += call["total_tokens"]

        return {
            "total_cost": total_cost,
            "call_count": call_count,
            "avg_cost_per_call": avg_cost_per_call,
            "remaining_budget": self.remaining_budget,
            "budget_usage_ratio": self.used_budget / max(self.total_budget, 0.01),
            "model_stats": model_stats,
            "days": days,
        }

    def reset_budget(self, new_budget: float):
        """重置预算"""
        self.total_budget = new_budget
        self.used_budget = 0.0
        self.call_history = []
        logger.info(f"预算已重置：新预算=${new_budget:.2f}")
