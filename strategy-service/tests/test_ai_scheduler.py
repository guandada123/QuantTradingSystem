"""
AI模型调度器单元测试
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from services.ai_scheduler import AIModelScheduler, TaskComplexity, TaskType, SLARequirement


class TestAIModelScheduler:
    """AIModelScheduler 单元测试"""

    @pytest.fixture
    def scheduler(self):
        return AIModelScheduler(total_budget=100.0)

    def test_select_low_complexity_model(self, scheduler):
        """低复杂度任务应选最便宜模型"""
        model = scheduler.select_model(TaskType.DATA_CLEANING, TaskComplexity.LOW)
        assert model in ['Hy3 preview', 'Deepseek-V4-Flash']

    def test_select_high_complexity_model(self, scheduler):
        """高复杂度任务应选Pro"""
        model = scheduler.select_model(TaskType.PATTERN_RECOGNITION, TaskComplexity.CRITICAL)
        assert model in ['Deepseek-V4-Pro', 'GLM-5.1']

    def test_budget_zero_uses_cheapest(self, scheduler):
        """预算为0时强制使用最便宜模型"""
        scheduler.used_budget = 100.0
        model = scheduler.select_model(TaskType.STOCK_SELECTION, TaskComplexity.HIGH)
        assert model == 'Deepseek-V4-Flash'

    def test_select_for_data_cleaning(self, scheduler):
        """数据清洗任务选最便宜的"""
        model = scheduler.select_model(TaskType.DATA_CLEANING, TaskComplexity.LOW)
        assert model in ['Hy3 preview', 'Deepseek-V4-Flash']

    def test_select_for_multi_agent_debate(self, scheduler):
        """多智能体辩论选Kimi或Pro"""
        model = scheduler.select_model(TaskType.MULTI_AGENT_DEBATE, TaskComplexity.HIGH)
        assert model in ['Kimi-K2.6', 'Deepseek-V4-Pro']

    def test_select_for_strategy_optimization(self, scheduler):
        """策略优化选最强模型"""
        model = scheduler.select_model(TaskType.STRATEGY_OPTIMIZATION, TaskComplexity.CRITICAL)
        assert model in ['GLM-5.1', 'Deepseek-V4-Pro']

    def test_select_for_news_sentiment(self, scheduler):
        """新闻情绪分析选DeepSeek-V3.2"""
        model = scheduler.select_model(TaskType.NEWS_SENTIMENT, TaskComplexity.MEDIUM)
        assert model == 'DeepSeek-V3.2'

    @pytest.mark.parametrize("task", list(TaskType))
    def test_all_tasks_return_valid_model(self, scheduler, task):
        """所有任务类型都应返回有效模型"""
        model = scheduler.select_model(task, TaskComplexity.MEDIUM)
        assert model in scheduler.MODEL_COST_COEFFICIENT
        assert scheduler.MODEL_COST_COEFFICIENT[model] > 0

    def test_record_usage_and_history(self, scheduler):
        """记录调用应更新使用量和历史"""
        cost = scheduler.record_usage(
            model='Deepseek-V4-Flash',
            task_type=TaskType.DATA_CLEANING,
            input_tokens=100,
            output_tokens=50,
            latency_ms=200,
            status='success'
        )
        assert cost > 0
        assert len(scheduler.call_history) == 1
        assert scheduler.used_budget > 0

    def test_cost_calculation_accuracy(self, scheduler):
        """成本计算应准确"""
        # Deepseek-V4-Flash coefficient: 0.06
        # cost = (1000+500)/1000 * 0.002 * 0.06 = 1.5 * 0.002 * 0.06 = 0.00018
        cost = scheduler.record_usage(
            model='Deepseek-V4-Flash',
            task_type=TaskType.INDICATOR_CALC,
            input_tokens=1000,
            output_tokens=500,
            latency_ms=150,
            status='success'
        )
        assert abs(cost - 0.00018) < 0.00001

    def test_cost_higher_for_pro(self, scheduler):
        """Pro模型成本应高于Flash"""
        flash_cost = scheduler.record_usage('Deepseek-V4-Flash', TaskType.DATA_CLEANING, 1000, 500, 100)
        pro_cost = scheduler.record_usage('Deepseek-V4-Pro', TaskType.DATA_CLEANING, 1000, 500, 100)
        assert pro_cost > flash_cost

    def test_budget_exhaustion(self, scheduler):
        """预算耗尽时应接近0"""
        scheduler.used_budget = 99.99
        remaining = scheduler.remaining_budget
        assert remaining == pytest.approx(0.01, rel=1e-3)

    def test_get_cost_summary_empty(self, scheduler):
        """无调用记录时返回零"""
        summary = scheduler.get_cost_summary(days=7)
        assert summary['total_cost'] == 0.0
        assert summary['call_count'] == 0

    def test_get_cost_summary_with_data(self, scheduler):
        """有调用记录时返回正确统计"""
        scheduler.record_usage('Deepseek-V4-Flash', TaskType.DATA_CLEANING, 100, 50, 100)
        scheduler.record_usage('Deepseek-V4-Pro', TaskType.MULTI_AGENT_DEBATE, 200, 100, 200)
        summary = scheduler.get_cost_summary(days=7)
        assert summary['call_count'] == 2
        assert summary['total_cost'] > 0
