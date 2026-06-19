"""
[兼容层] scheduler_service.py → scheduler/ 包

原文件已按职责拆分到 scheduler/ 包：
  - scheduler/engine.py    → TaskSchedulerService 类
  - scheduler/jobs.py      → 6 个业务任务实现
  - scheduler/registry.py  → register_default_tasks() + task_scheduler 实例
  - scheduler/__init__.py  → 兼容导出

直接引用路径保持不变：
  from services.scheduler_service import task_scheduler
"""

import warnings

warnings.warn(
    "services/scheduler_service.py 已拆分为 services/scheduler/ 包，"
    "请改为 from services.scheduler import ... 以避免本兼容层",
    DeprecationWarning,
    stacklevel=2,
)

from services.scheduler import (  # noqa: F401, E402
    TaskSchedulerService,
    register_default_tasks,
    task_scheduler,
)
