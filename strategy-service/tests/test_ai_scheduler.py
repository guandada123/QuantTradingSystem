"""
AI模型调度器单元测试
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import pytest
from services.ai_scheduler import AIModelScheduler, SLARequirement, TaskComplexity, TaskType


class TestAIModelScheduler:
    """AIModelScheduler 单元测试"""

    @pytest.fixture
    def scheduler(self):
        s = AIModelScheduler(total_budget=100.0)
        s.redis_client = None  # 避免测试数据写入本地 Redis
        return s

    def test_select_low_complexity_model(self, scheduler):
        """低复杂度任务应选最便宜模型"""
        model = scheduler.select_model(TaskType.DATA_CLEANING, TaskComplexity.LOW)
        assert model in ["Hy3 preview", "Deepseek-V4-Flash"]

    def test_select_high_complexity_model(self, scheduler):
        """高复杂度任务应选Pro"""
        model = scheduler.select_model(TaskType.PATTERN_RECOGNITION, TaskComplexity.CRITICAL)
        assert model in ["Deepseek-V4-Pro", "GLM-5.1"]

    def test_budget_zero_uses_cheapest(self, scheduler):
        """预算为0时强制使用最便宜模型"""
        scheduler.used_budget = 100.0
        model = scheduler.select_model(TaskType.STOCK_SELECTION, TaskComplexity.HIGH)
        assert model == "Deepseek-V4-Flash"

    def test_select_for_data_cleaning(self, scheduler):
        """数据清洗任务选最便宜的"""
        model = scheduler.select_model(TaskType.DATA_CLEANING, TaskComplexity.LOW)
        assert model in ["Hy3 preview", "Deepseek-V4-Flash"]

    def test_select_for_multi_agent_debate(self, scheduler):
        """多智能体辩论选Kimi或Pro"""
        model = scheduler.select_model(TaskType.MULTI_AGENT_DEBATE, TaskComplexity.HIGH)
        assert model in ["Kimi-K2.6", "Deepseek-V4-Pro"]

    def test_select_for_strategy_optimization(self, scheduler):
        """策略优化选最强模型"""
        model = scheduler.select_model(TaskType.STRATEGY_OPTIMIZATION, TaskComplexity.CRITICAL)
        assert model in ["GLM-5.1", "Deepseek-V4-Pro"]

    def test_select_for_news_sentiment(self, scheduler):
        """新闻情绪分析选DeepSeek-V3.2"""
        model = scheduler.select_model(TaskType.NEWS_SENTIMENT, TaskComplexity.MEDIUM)
        assert model == "DeepSeek-V3.2"

    @pytest.mark.parametrize("task", list(TaskType))
    def test_all_tasks_return_valid_model(self, scheduler, task):
        """所有任务类型都应返回有效模型"""
        model = scheduler.select_model(task, TaskComplexity.MEDIUM)
        assert model in scheduler.MODEL_COST_COEFFICIENT
        assert scheduler.MODEL_COST_COEFFICIENT[model] > 0

    def test_record_usage_and_history(self, scheduler):
        """记录调用应更新使用量和历史"""
        cost = scheduler.record_usage(
            model="Deepseek-V4-Flash",
            task_type=TaskType.DATA_CLEANING,
            input_tokens=100,
            output_tokens=50,
            latency_ms=200,
            status="success",
        )
        assert cost > 0
        assert len(scheduler.call_history) == 1
        assert scheduler.used_budget > 0

    def test_cost_calculation_accuracy(self, scheduler):
        """成本计算应准确"""
        # Deepseek-V4-Flash coefficient: 0.06
        # cost = (1000+500)/1000 * 0.002 * 0.06 = 1.5 * 0.002 * 0.06 = 0.00018
        cost = scheduler.record_usage(
            model="Deepseek-V4-Flash",
            task_type=TaskType.INDICATOR_CALC,
            input_tokens=1000,
            output_tokens=500,
            latency_ms=150,
            status="success",
        )
        assert abs(cost - 0.00018) < 0.00001

    def test_cost_higher_for_pro(self, scheduler):
        """Pro模型成本应高于Flash"""
        flash_cost = scheduler.record_usage(
            "Deepseek-V4-Flash", TaskType.DATA_CLEANING, 1000, 500, 100
        )
        pro_cost = scheduler.record_usage("Deepseek-V4-Pro", TaskType.DATA_CLEANING, 1000, 500, 100)
        assert pro_cost > flash_cost

    def test_budget_exhaustion(self, scheduler):
        """预算耗尽时应接近0"""
        scheduler.used_budget = 99.99
        remaining = scheduler.remaining_budget
        assert remaining == pytest.approx(0.01, rel=1e-3)

    def test_get_cost_summary_empty(self, scheduler):
        """无调用记录时返回零"""
        summary = scheduler.get_cost_summary(days=7)
        assert summary["total_cost"] == 0.0
        assert summary["call_count"] == 0

    def test_get_cost_summary_with_data(self, scheduler):
        """有调用记录时返回正确统计"""
        scheduler.record_usage("Deepseek-V4-Flash", TaskType.DATA_CLEANING, 100, 50, 100)
        scheduler.record_usage("Deepseek-V4-Pro", TaskType.MULTI_AGENT_DEBATE, 200, 100, 200)
        summary = scheduler.get_cost_summary(days=7)
        assert summary["call_count"] == 2
        assert summary["total_cost"] > 0

    # ================================================================
    #   覆盖率提升追加测试（覆盖全部剩余分支）
    # ================================================================

    # --- __init__ 异常分支 ---

    def test_init_redis_failure(self):
        """Redis 连接失败走 except 分支 — line 142-143"""
        with patch(
            "services.ai_scheduler.get_redis_client", side_effect=ConnectionError("拒绝连接")
        ):
            s = AIModelScheduler(total_budget=100.0, redis_url="redis://invalid:6379")
            assert s.redis_client is None

    # --- select_model 分支 ---

    def test_preferred_model_within_budget(self, scheduler):
        """偏好模型预算充足直接使用 — line 173-177"""
        model = scheduler.select_model(
            TaskType.DATA_CLEANING, TaskComplexity.LOW, preferred_model="Deepseek-V4-Pro"
        )
        assert model == "Deepseek-V4-Pro"

    def test_preferred_model_exceeds_budget(self, scheduler):
        """偏好模型超出预算回退自动选择 — line 178（需临时抬高成本系数使成本 > 剩余预算）"""
        # DATA_CLEANING 仅200 token: cost = 0.0004 * coeff; budget=100 需 coeff > 250000
        orig_coeff = scheduler.MODEL_COST_COEFFICIENT.copy()
        scheduler.MODEL_COST_COEFFICIENT["GLM-5.1"] = 9999999  # cost ≈ $4,000 >> $100
        model = scheduler.select_model(
            TaskType.DATA_CLEANING, TaskComplexity.LOW, preferred_model="GLM-5.1"
        )
        scheduler.MODEL_COST_COEFFICIENT.clear()
        scheduler.MODEL_COST_COEFFICIENT.update(orig_coeff)
        # GLM-5.1 成本极高超预算 → 回退自动选择
        assert model != "GLM-5.1"
        assert model in scheduler.MODEL_COST_COEFFICIENT

    def test_sla_critical_selects_most_capable(self, scheduler):
        """SLA=CRITICAL → _select_most_capable_model — line 183"""
        model = scheduler.select_model(
            TaskType.MULTI_AGENT_DEBATE, TaskComplexity.HIGH, sla=SLARequirement.CRITICAL
        )
        assert model in ["Kimi-K2.6", "GLM-5.1", "Deepseek-V4-Pro"]

    def test_sla_high_selects_balanced(self, scheduler):
        """SLA=HIGH → _select_balanced_model — line 186"""
        model = scheduler.select_model(
            TaskType.STOCK_SELECTION, TaskComplexity.MEDIUM, sla=SLARequirement.HIGH
        )
        assert model in scheduler.MODEL_COST_COEFFICIENT

    # --- _select_most_capable_model 分支 ---

    def test_most_capable_normal_path(self, scheduler):
        """_select_most_capable_model 正常选择最强模型"""
        scheduler.total_budget = 100.0
        model = scheduler._select_most_capable_model(
            TaskType.MULTI_AGENT_DEBATE, TaskComplexity.HIGH
        )
        # GLM-5.1 能力评分 10，应被选中
        assert model in ["GLM-5.1", "Kimi-K2.6"]

    def test_most_capable_all_over_budget(self, scheduler):
        """_select_most_capable_model 全部超出预算 → Deepseek-V4-Flash — line 207-208"""
        scheduler.total_budget = 0.0
        model = scheduler._select_most_capable_model(
            TaskType.STRATEGY_OPTIMIZATION, TaskComplexity.HIGH
        )
        assert model == "Deepseek-V4-Flash"

    # --- _select_balanced_model 分支 ---

    def test_balanced_budget_exceeded_fallbacks(self, scheduler):
        """_select_balanced_model 超出预算 → 降级成本优化 — line 241-242"""
        scheduler.total_budget = 0.0
        model = scheduler._select_balanced_model(
            TaskType.STRATEGY_OPTIMIZATION, TaskComplexity.HIGH
        )
        # 降级到成本优化模式，所有模型超预算 → 从此返回 Deepseek-V4-Flash
        assert model == "Deepseek-V4-Flash"

    # --- _select_cost_optimized_model 分支 ---

    def test_cost_optimized_medium_high_complexity(self, scheduler):
        """中高复杂度走 MEDIUM_HIGH 分支 — line 263"""
        model = scheduler._select_cost_optimized_model(
            TaskType.STOCK_SELECTION, TaskComplexity.MEDIUM_HIGH
        )
        assert model in ["Kimi-K2.5", "Deepseek-V4-Pro"]

    def test_cost_optimized_medium_low_complexity(self, scheduler):
        """中低复杂度走 MEDIUM_LOW 分支 — line 257"""
        model = scheduler._select_cost_optimized_model(
            TaskType.DATA_CLEANING, TaskComplexity.MEDIUM_LOW
        )
        assert model in ["Deepseek-V4-Flash", "DeepSeek-V3.2"]

    def test_balanced_model_fallback_no_candidates(self, scheduler):
        """_select_balanced_model 空候选列表回退默认 — line 247"""
        with patch.dict(scheduler.TASK_MODEL_MAPPING, {TaskType.DATA_CLEANING: []}):
            model = scheduler._select_balanced_model(TaskType.DATA_CLEANING, TaskComplexity.MEDIUM)
            assert model == "GLM-5.0-Turbo"

    def test_cost_optimized_all_over_budget(self, scheduler):
        """_select_cost_optimized_model 全部超预算 → Deepseek-V4-Flash — line 276-277"""
        scheduler.total_budget = 0.0
        model = scheduler._select_cost_optimized_model(TaskType.DATA_CLEANING, TaskComplexity.LOW)
        assert model == "Deepseek-V4-Flash"

    # --- record_usage Redis 分支 ---

    def test_record_usage_redis_write_failure(self, scheduler):
        """Redis lpush 失败走 except — line 362-367"""
        mock_redis = MagicMock()
        mock_redis.lpush.side_effect = ConnectionError("写入超时")
        scheduler.redis_client = mock_redis
        cost = scheduler.record_usage("Deepseek-V4-Flash", TaskType.DATA_CLEANING, 100, 50, 200)
        assert cost > 0
        assert len(scheduler.call_history) == 1

    def test_record_usage_redis_lpush_succeeds_expire_fails(self, scheduler):
        """Redis lpush 成功 + expire 异常 — line 365"""
        mock_redis = MagicMock()
        mock_redis.lpush.return_value = 1  # 成功
        mock_redis.expire.side_effect = ConnectionError("expire超时")
        scheduler.redis_client = mock_redis
        cost = scheduler.record_usage("Hy3 preview", TaskType.REPORT_GENERATION, 200, 100, 150)
        assert cost > 0

    # --- get_cost_summary Redis 分支 ---

    def test_get_cost_summary_redis_read_failure(self, scheduler):
        """Redis lrange 失败回退内存 — line 395-403"""
        scheduler.record_usage("Deepseek-V4-Flash", TaskType.DATA_CLEANING, 100, 50, 100)
        mock_redis = MagicMock()
        mock_redis.lrange.side_effect = ConnectionError("读取超时")
        scheduler.redis_client = mock_redis
        summary = scheduler.get_cost_summary(days=1)
        assert summary["call_count"] == 1
        assert summary["total_cost"] > 0

    def test_get_cost_summary_redis_read_success(self, scheduler):
        """Redis lrange 成功 + 解析调用记录 — line 400-401"""
        import json

        scheduler.record_usage("Deepseek-V4-Flash", TaskType.DATA_CLEANING, 100, 50, 100)
        # 构造 Redis 返回数据
        call_record = json.dumps(scheduler.call_history[0])
        mock_redis = MagicMock()
        mock_redis.lrange.return_value = [call_record]
        scheduler.redis_client = mock_redis
        summary = scheduler.get_cost_summary(days=1)
        assert summary["call_count"] == 1
        assert summary["total_cost"] > 0

    # --- reset_budget ---

    def test_reset_budget(self, scheduler):
        """reset_budget 重置 — line 439-442"""
        scheduler.record_usage("Deepseek-V4-Flash", TaskType.DATA_CLEANING, 100, 50, 100)
        assert scheduler.used_budget > 0
        scheduler.reset_budget(200.0)
        assert scheduler.total_budget == 200.0
        assert scheduler.used_budget == 0.0
        assert len(scheduler.call_history) == 0
