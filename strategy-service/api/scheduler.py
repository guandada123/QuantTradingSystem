"""
定时任务管理 API
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class JobStatus(BaseModel):
    id: str
    name: str
    next_run_time: str | None = None
    trigger: str = ""
    pending: bool = False


class JobAction(BaseModel):
    job_id: str
    action: str  # pause / resume / remove


@router.get("/tasks", response_model=list[JobStatus])
async def list_tasks():
    """列出所有定时任务"""
    try:
        from services.scheduler_service import task_scheduler

        jobs = task_scheduler.list_jobs()
        return jobs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {e}")


@router.post("/tasks/{action}")
async def manage_task(job_id: str, action: str):
    """管理任务: pause / resume / remove"""
    try:
        from services.scheduler_service import task_scheduler

        if action == "pause":
            ok = task_scheduler.pause_job(job_id)
        elif action == "resume":
            ok = task_scheduler.resume_job(job_id)
        elif action == "remove":
            ok = task_scheduler.remove_job(job_id)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")

        if not ok:
            raise HTTPException(status_code=404, detail=f"任务不存在或操作失败: {job_id}")

        return {"status": "ok", "job_id": job_id, "action": action}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def scheduler_status():
    """调度器运行状态"""
    from services.scheduler_service import task_scheduler

    return {"running": task_scheduler.is_running, "total_jobs": len(task_scheduler.list_jobs())}
