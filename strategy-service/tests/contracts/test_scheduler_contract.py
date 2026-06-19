"""
调度器契约测试 v1.0

验证 TaskSchedulerService 的核心行为契约：
1. TestRegisterJobContract — 注册任务必须返回 job_id
2. TestCancelJobContract — 取消/暂停/恢复不存在 job 返回 False（非抛出异常）
3. TestSchedulerRecoveryContract — 调度器重启/实例隔离行为

不依赖外部服务。直接测试 services.scheduler.engine 模块。
"""

import pytest

from services.scheduler.engine import TaskSchedulerService


# ─── 公共 Fixture ───────────────────────────────────────────────────────


@pytest.fixture
def scheduler():
    """每测试一个干净调度器实例"""
    return TaskSchedulerService()


async def _dummy():
    """占位异步函数，用于注册任务"""
    pass


# =========================================================================
# 1. 注册任务返回 job_id
# =========================================================================


class TestRegisterJobContract:
    """契约：add_cron_job / add_interval_job 必须返回 job_id 字符串"""

    def test_cron_job_returns_job_id(self, scheduler):
        """add_cron_job 返回的 job_id 等于传入的 ID"""
        job_id = scheduler.add_cron_job(_dummy, "cron_test_job", hour=14, minute=30)
        assert job_id == "cron_test_job"

    def test_interval_job_returns_job_id(self, scheduler):
        """add_interval_job 返回的 job_id 等于传入的 ID"""
        job_id = scheduler.add_interval_job(_dummy, "interval_test_job", minutes=15)
        assert job_id == "interval_test_job"

    def test_job_id_type_is_string(self, scheduler):
        """返回的 job_id 是 str 类型"""
        job_id_cron = scheduler.add_cron_job(_dummy, "type_check_cron", hour=10, minute=0)
        job_id_interval = scheduler.add_interval_job(_dummy, "type_check_int", minutes=30)
        assert isinstance(job_id_cron, str)
        assert isinstance(job_id_interval, str)

    def test_job_id_appears_in_list_jobs(self, scheduler):
        """注册后的 job_id 能在 list_jobs 中找到"""
        scheduler.add_cron_job(_dummy, "list_job_1", hour=9, minute=0)
        scheduler.add_interval_job(_dummy, "list_job_2", minutes=60)
        job_ids = {j["id"] for j in scheduler.list_jobs()}
        assert "list_job_1" in job_ids
        assert "list_job_2" in job_ids


# =========================================================================
# 2. 取消不存在的 job 返回 False/404 语义
# =========================================================================


class TestCancelJobContract:
    """契约：remove_job / pause_job / resume_job 对不存在 job 返回 False（非抛出异常）"""

    def test_remove_nonexistent_returns_false(self, scheduler):
        """移除不存在 job 返回 False"""
        assert scheduler.remove_job("nonexistent_job") is False

    def test_remove_nonexistent_does_not_raise(self, scheduler):
        """移除不存在 job 不抛异常"""
        try:
            scheduler.remove_job("ghost_job")
        except Exception:
            pytest.fail("remove_job 对不存在 job 不应抛出异常")

    def test_remove_twice_idempotent(self, scheduler):
        """移除两次：第一次返回 True，第二次返回 False"""
        scheduler.add_cron_job(_dummy, "twice_job", hour=10, minute=0)
        assert scheduler.remove_job("twice_job") is True
        assert scheduler.remove_job("twice_job") is False

    def test_pause_nonexistent_returns_false(self, scheduler):
        """暂停不存在的 job 返回 False"""
        assert scheduler.pause_job("nonexistent_pause") is False

    def test_resume_nonexistent_returns_false(self, scheduler):
        """恢复不存在的 job 返回 False"""
        assert scheduler.resume_job("nonexistent_resume") is False


# =========================================================================
# 3. 调度器重启/持久化行为（架构级契约）
# =========================================================================


class TestSchedulerRecoveryContract:
    """契约（架构级）：新实例不应有旧实例的任务；shutdown 清理运行状态"""

    def test_new_instance_has_no_jobs(self):
        """新创建的 TaskSchedulerService 实例 list_jobs 为空"""
        svc = TaskSchedulerService()
        assert svc.list_jobs() == []

    def test_jobs_not_shared_across_instances(self, scheduler):
        """两个独立实例不共享任务"""
        scheduler.add_cron_job(_dummy, "isolated_job", hour=10, minute=0)
        assert len(scheduler.list_jobs()) == 1

        another = TaskSchedulerService()
        assert another.list_jobs() == [], "第二个实例不应包含第一个实例的任务"

    @pytest.mark.asyncio
    async def test_shutdown_cleans_state(self, scheduler):
        """shutdown 后 is_running 为 False"""
        scheduler.start()
        assert scheduler.is_running is True
        await scheduler.shutdown()
        assert scheduler.is_running is False
