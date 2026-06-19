"""
调度器包 — 将原 scheduler_service.py 按职责拆为 3 子模块

兼容导出：
- TaskSchedulerService  → scheduler/engine.py
- register_default_tasks / task_scheduler  → scheduler/registry.py
"""

from services.scheduler.engine import TaskSchedulerService
from services.scheduler.registry import register_default_tasks, task_scheduler

__all__ = [
    "TaskSchedulerService",
    "register_default_tasks",
    "task_scheduler",
]
