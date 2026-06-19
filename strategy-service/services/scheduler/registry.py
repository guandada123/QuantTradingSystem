"""
任务注册 — 预设定时任务的注册与全局实例
"""

import logging

from services.scheduler.engine import TaskSchedulerService
from services.scheduler.jobs import (
    ai_review,
    daily_close_settle,
    daily_data_refresh,
    health_check,
    market_scan,
    market_snapshot,
)

logger = logging.getLogger(__name__)


# 全局调度器实例
task_scheduler = TaskSchedulerService()


def register_default_tasks(scheduler: TaskSchedulerService):
    """注册默认预设定时任务"""

    # -------- 收盘时段任务(15:00后) --------
    scheduler.add_cron_job(
        daily_data_refresh,
        "daily_data_refresh",
        hour=15,
        minute=10,
        name="日行情刷新",
        description="拉取当日K线、更新数据库",
    )
    scheduler.add_cron_job(
        daily_close_settle,
        "daily_close_settle",
        hour=15,
        minute=20,
        name="收盘归总",
        description="市值快照、收益结算",
    )
    scheduler.add_cron_job(
        ai_review,
        "daily_ai_review",
        hour=15,
        minute=30,
        name="AI每日复盘",
        description="AI分析当日持仓表现",
    )

    # -------- 盘前任务(09:00前) --------
    scheduler.add_cron_job(
        market_scan,
        "market_scan",
        hour=9,
        minute=0,
        name="智能选股扫描",
        description="从股票池筛选当日标的",
        day_of_week="mon-fri",
    )

    # -------- 盘中循环(每30分钟) --------
    scheduler.add_interval_job(
        market_snapshot,
        "market_snapshot",
        minutes=30,
        name="大盘快照",
        description="记录指数行情快照",
    )

    # -------- 系统维护(每小时) --------
    scheduler.add_interval_job(
        health_check, "health_check", minutes=60, name="健康检查", description="各服务健康检查"
    )

    logger.info(f"[Scheduler] 已注册 {len(scheduler.list_jobs())} 个默认任务")
