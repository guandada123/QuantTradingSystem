"""
调度器引擎 — APScheduler 封装
"""

import logging
from typing import Any

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class TaskSchedulerService:
    """后台任务调度器"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={
                "coalesce": True,  # 合并错过的执行
                "max_instances": 1,  # 同一任务不并行
                "misfire_grace_time": 60,  # 错过执行容差(秒)
            },
            timezone="Asia/Shanghai",
        )
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    def add_cron_job(
        self,
        func,
        job_id: str,
        hour: int,
        minute: int,
        args: list = None,
        kwargs: dict = None,
        name: str = "",
        day_of_week: str = None,
        day: int = None,
        description: str = "",
    ) -> str:
        """添加 cron 定时任务"""
        trigger_kwargs = {"hour": hour, "minute": minute, "timezone": "Asia/Shanghai"}
        if day_of_week:
            trigger_kwargs["day_of_week"] = day_of_week
        if day:
            trigger_kwargs["day"] = day
        trigger = CronTrigger(**trigger_kwargs)
        self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        logger.info(f"[Scheduler] 添加cron任务 {job_id}: {hour:02d}:{minute:02d} {description}")
        return job_id

    def add_interval_job(
        self,
        func,
        job_id: str,
        minutes: int,
        args: list = None,
        kwargs: dict = None,
        name: str = "",
        description: str = "",
    ) -> str:
        """添加间隔重复任务"""
        trigger = IntervalTrigger(minutes=minutes, timezone="Asia/Shanghai")
        self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        logger.info(f"[Scheduler] 添加间隔任务 {job_id}: 每{minutes}分钟 {description}")
        return job_id

    def remove_job(self, job_id: str) -> bool:
        """移除任务"""
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"[Scheduler] 移除任务 {job_id}")
            return True
        except Exception as e:
            logger.warning(f"[Scheduler] 移除任务失败 {job_id}: {e}")
            return False

    def pause_job(self, job_id: str) -> bool:
        """暂停任务"""
        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"[Scheduler] 暂停任务 {job_id}")
            return True
        except Exception as e:
            logger.warning("[Scheduler] 暂停任务失败 %s: %s", job_id, e)
            return False

    def resume_job(self, job_id: str) -> bool:
        """恢复任务"""
        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"[Scheduler] 恢复任务 {job_id}")
            return True
        except Exception as e:
            logger.warning("[Scheduler] 恢复任务失败 %s: %s", job_id, e)
            return False

    def list_jobs(self) -> list[dict[str, Any]]:
        """列出所有任务"""
        jobs = []
        for job in self.scheduler.get_jobs():
            trigger_desc = str(job.trigger) if job.trigger else ""
            try:
                next_run = job.next_run_time
                next_run_str = next_run.isoformat() if next_run else None
            except (AttributeError, ValueError):
                next_run_str = None
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run_str,
                    "trigger": trigger_desc,
                    "pending": job.pending,
                }
            )
        return jobs

    def start(self):
        """启动调度器"""
        if not self._started:
            self.scheduler.start()
            self._started = True
            logger.info("[Scheduler] ✅ 调度器已启动")
        else:
            logger.info("[Scheduler] 调度器已在运行中")

    async def shutdown(self, wait: bool = True):
        """关闭调度器"""
        if self._started:
            # AsyncIOScheduler.shutdown() 内部通过 @run_in_event_loop
            # 调度 _shutdown() 异步执行，方法本身返回 None
            self.scheduler.shutdown(wait=wait)
            self._started = False
            logger.info("[Scheduler] 调度器已关闭")
