"""
Tests for scheduler_service.py — 兼容层 shim

测试目标：
- DeprecationWarning 正确发出
- 重导出的符号（TaskSchedulerService, register_default_tasks, task_scheduler）可访问
"""

import warnings

import pytest


class TestSchedulerServiceCompat:
    """scheduler_service.py 兼容层"""

    def test_deprecation_warning_issued(self):
        """导入 scheduler_service 触发 DeprecationWarning"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from services.scheduler_service import (  # noqa: F811
                TaskSchedulerService,
                register_default_tasks,
                task_scheduler,
            )

            deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecations) >= 1
            assert any("已拆分为" in str(d.message) for d in deprecations)

    def test_re_exports_available(self):
        """兼容层正确重导出 scheduler 包符号"""
        # 验证类型
        from services.scheduler import TaskSchedulerService as OrigTaskSchedulerService
        from services.scheduler import register_default_tasks as orig_reg
        from services.scheduler import task_scheduler as orig_ts
        from services.scheduler_service import (  # noqa: F811
            TaskSchedulerService,
            register_default_tasks,
            task_scheduler,
        )

        assert TaskSchedulerService is OrigTaskSchedulerService
        assert register_default_tasks is orig_reg
        assert task_scheduler is orig_ts
