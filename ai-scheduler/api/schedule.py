"""
AI调度器 — 调度任务API
管理智能选股、复盘、预测等AI任务的调度状态
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class ScanRequest(BaseModel):
    """选股扫描请求"""
    limit: int = 100
    strategy_ids: Optional[List[str]] = None
    ts_codes: Optional[List[str]] = None


class ReviewRequest(BaseModel):
    """复盘请求"""
    date: Optional[str] = None  # 默认今天
    include_ai: bool = True


class TaskStatus(BaseModel):
    task_id: str
    task_type: str
    status: str  # pending / running / completed / failed
    progress: float = 0.0
    message: Optional[str] = None


# 内存任务状态
_tasks: dict = {}


@router.post("/scan")
async def trigger_scan(req: ScanRequest):
    """触发AI选股扫描"""
    task_id = f"scan-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    _tasks[task_id] = {
        "task_id": task_id,
        "task_type": "scan",
        "status": "pending",
        "progress": 0.0,
        "message": "扫描任务已提交",
        "params": req.model_dump()
    }
    logger.info(f"[AI调度器] 提交扫描任务 {task_id}, limit={req.limit}")

    # TODO: 异步执行扫描
    return {"code": 0, "task_id": task_id, "status": "pending"}


@router.post("/review")
async def trigger_review(req: ReviewRequest):
    """触发AI每日复盘"""
    task_id = f"review-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    review_date = req.date or datetime.now().strftime("%Y-%m-%d")
    _tasks[task_id] = {
        "task_id": task_id,
        "task_type": "review",
        "status": "pending",
        "progress": 0.0,
        "message": f"复盘任务已提交（日期: {review_date}）",
        "params": req.model_dump()
    }
    logger.info(f"[AI调度器] 提交复盘任务 {task_id}, date={review_date}")
    return {"code": 0, "task_id": task_id, "status": "pending"}


@router.get("/tasks", response_model=List[TaskStatus])
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
        }
    }
