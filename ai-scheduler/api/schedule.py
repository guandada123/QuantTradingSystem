"""
AI调度器 — 调度任务API
管理智能选股、复盘、预测等AI任务的调度状态
"""

import asyncio
import logging
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.task_scheduler import TaskScheduler

logger = logging.getLogger(__name__)
router = APIRouter()


class ScanRequest(BaseModel):
    """选股扫描请求"""

    limit: int = 100
    strategy_ids: list[str] | None = None
    ts_codes: list[str] | None = None


class ReviewRequest(BaseModel):
    """复盘请求"""

    date: str | None = None  # 默认今天
    include_ai: bool = True


class TaskStatus(BaseModel):
    task_id: str
    task_type: str
    status: str  # pending / running / completed / failed
    progress: float = 0.0
    message: str | None = None


# 内存任务状态
_tasks: dict = {}

# ─── 调度器实例（由 main.py lifespan 调用 init_scheduler() 初始化） ──
_scheduler: TaskScheduler | None = None


def init_scheduler(task_store: dict) -> None:
    """初始化调度器实例（注入共享的 _tasks 引用）

    在 main.py 的 lifespan 中调用一次即可。
    """
    global _scheduler
    _scheduler = TaskScheduler(task_store=task_store)


def _on_task_done(task_id: str, task: asyncio.Task) -> None:
    """后台任务完成回调：捕获异常并更新任务状态，防止异常被事件循环静默吞掉"""
    try:
        exc = task.exception()
        if exc:
            logger.error(f"[AI调度器] 任务 {task_id} 执行异常: {exc}")
            if task_id in _tasks:
                _tasks[task_id].update({"status": "failed", "message": str(exc)})
        elif task_id in _tasks and _tasks[task_id]["status"] != "failed":
            _tasks[task_id].update({"status": "completed", "progress": 1.0})
    except asyncio.CancelledError:
        if task_id in _tasks:
            _tasks[task_id].update({"status": "failed", "message": "任务被取消"})
    except Exception as e:
        logger.error(f"[AI调度器] _on_task_done 异常 (task_id={task_id}): {e}")


def _cleanup_old_tasks(max_age_hours: int = 48) -> None:
    """清理超过指定时间的已结束任务，防止 _tasks 全局字典内存泄漏"""
    now_ts = time.time()
    expired_keys = []
    for tid, t in list(_tasks.items()):
        if t.get("status") not in ("completed", "failed"):
            continue
        try:
            # task_id 格式: scan-20260627120000 或 review-20260627120000
            ts_str = tid.split("-", 1)[1]
            task_ts = time.mktime(datetime.strptime(ts_str, "%Y%m%d%H%M%S").timetuple())
            if now_ts - task_ts > max_age_hours * 3600:
                expired_keys.append(tid)
        except (ValueError, IndexError, KeyError):
            continue
    for tid in expired_keys:
        del _tasks[tid]
        logger.debug(f"[AI调度器] 清理过期任务: {tid}")


@router.post("/scan")
async def trigger_scan(req: ScanRequest):
    """触发AI选股扫描"""
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化，请稍后重试")

    task_id = f"scan-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    _tasks[task_id] = {
        "task_id": task_id,
        "task_type": "scan",
        "status": "pending",
        "progress": 0.0,
        "message": "扫描任务已提交",
        "params": req.model_dump(),
    }
    logger.info(f"[AI调度器] 提交扫描任务 {task_id}, limit={req.limit}")

    _cleanup_old_tasks()

    # 后台异步执行（不阻塞响应），通过 add_done_callback 捕获异常
    task = asyncio.create_task(_scheduler.execute_scan(task_id, req.model_dump()))
    task.add_done_callback(lambda t: _on_task_done(task_id, t))
    return {"code": 0, "task_id": task_id, "status": "pending"}


@router.post("/review")
async def trigger_review(req: ReviewRequest):
    """触发AI每日复盘"""
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化，请稍后重试")

    task_id = f"review-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    review_date = req.date or datetime.now().strftime("%Y-%m-%d")
    _tasks[task_id] = {
        "task_id": task_id,
        "task_type": "review",
        "status": "pending",
        "progress": 0.0,
        "message": f"复盘任务已提交（日期: {review_date}）",
        "params": req.model_dump(),
    }
    logger.info(f"[AI调度器] 提交复盘任务 {task_id}, date={review_date}")

    _cleanup_old_tasks()

    # 后台异步执行（不阻塞响应），通过 add_done_callback 捕获异常
    task = asyncio.create_task(_scheduler.execute_review(task_id, req.model_dump()))
    task.add_done_callback(lambda t: _on_task_done(task_id, t))
    return {"code": 0, "task_id": task_id, "status": "pending"}


@router.get("/tasks", response_model=list[TaskStatus])
async def list_tasks():
    """列出所有调度任务"""
    return [TaskStatus(**t) for t in _tasks.values()]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """获取单个任务状态"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/health")
async def health():
    """AI调度器健康检查"""
    return {
        "status": "healthy",
        "service": "ai-scheduler",
        "pending_tasks": sum(1 for t in _tasks.values() if t["status"] == "pending"),
        "running_tasks": sum(1 for t in _tasks.values() if t["status"] == "running"),
    }


@router.get("/stats")
async def stats():
    """调度统计信息"""
    today = datetime.now().strftime("%Y%m%d")
    today_tasks = [t for t in _tasks.values() if today in t.get("task_id", "")]
    return {
        "total_tasks": len(_tasks),
        "today_tasks": len(today_tasks),
        "by_type": {
            "scan": sum(1 for t in _tasks.values() if t["task_type"] == "scan"),
            "review": sum(1 for t in _tasks.values() if t["task_type"] == "review"),
        },
        "by_status": {
            "pending": sum(1 for t in _tasks.values() if t["status"] == "pending"),
            "running": sum(1 for t in _tasks.values() if t["status"] == "running"),
            "completed": sum(1 for t in _tasks.values() if t["status"] == "completed"),
            "failed": sum(1 for t in _tasks.values() if t["status"] == "failed"),
        },
    }
