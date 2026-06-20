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
async def manage_task(action: str, job_id: str | None = None):
    """管理任务: pause / resume / remove / refresh"""
    try:
        from services.scheduler_service import task_scheduler

        if action == "refresh":
            # 刷新任务列表（内存调度器始终为最新，no-op）
            return {
                "status": "ok",
                "action": "refresh",
                "total_jobs": len(task_scheduler.list_jobs()),
            }

        if job_id is None:
            raise HTTPException(status_code=400, detail="需要提供 job_id")
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


@router.get("/tasks/refresh")
async def refresh_tasks_get():
    """刷新任务列表（GET 便利端点）"""
    from services.scheduler_service import task_scheduler

    return {"status": "ok", "action": "refresh", "total_jobs": len(task_scheduler.list_jobs())}


@router.get("/status")
async def scheduler_status():
    """调度器运行状态"""
    from services.scheduler_service import task_scheduler

    return {"running": task_scheduler.is_running, "total_jobs": len(task_scheduler.list_jobs())}


# ── 健康监控端点（兼容前端 alerts.html 的 HealthMonitor 轮询）──


@router.get("/health-monitor/status")
async def health_monitor_status():
    """获取所有微服务健康状态（供前端告警页轮询）"""
    import asyncio

    import httpx

    services = {
        "strategy-service": "http://localhost:8000/health",
        "execution-service": "http://localhost:8001/health",
    }
    results = {}
    async with httpx.AsyncClient(timeout=3) as client:
        for name, url in services.items():
            try:
                resp = await client.get(url)
                results[name] = resp.status_code == 200
            except Exception:
                results[name] = False

    all_healthy = all(results.values()) if results else False
    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": results,
        "all_healthy": all_healthy,
        "checked_at": __import__("datetime").datetime.now().isoformat(),
    }


@router.post("/health-monitor/test-alert")
async def health_monitor_test_alert():
    """发送测试告警（手动触发）"""
    logger.info("手动触发健康监控测试告警")
    return {"status": "ok", "message": "测试告警已发送（如需实际推送请配置飞书 Webhook）"}
