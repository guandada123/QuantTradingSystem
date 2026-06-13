"""
QTS 标准化 Health Check 端点

提供 /health (liveness) 和 /ready (readiness) 两个探针，
适配 Docker healthcheck 和 Kubernetes probes。

用法:
    from shared.health import create_health_router

    app = FastAPI()
    app.include_router(create_health_router(
        service_name="strategy-service",
        version="1.0.0",
        checks={"database": check_db, "redis": check_redis},
    ))

输出:
    GET /health → {"status":"ok","service":"strategy-service","uptime_s":1234}
    GET /ready  → {"status":"ok","checks":{"database":"ok","redis":"ok"},"version":"1.0.0"}
"""

from collections.abc import Callable
import time
from typing import Any

from fastapi import APIRouter

_start_time = time.time()


def create_health_router(
    service_name: str = "unknown",
    version: str = "0.0.0",
    checks: dict[str, Callable[[], bool | str]] | None = None,
) -> APIRouter:
    """
    创建标准化健康检查路由。

    Args:
        service_name: 服务名称
        version: 服务版本
        checks: 依赖检查函数字典 {"name": callable}
                callable 返回 True/"ok" 表示正常，返回 False/str 表示异常
    """
    router = APIRouter(tags=["健康检查"])
    dependency_checks = checks or {}

    @router.get("/health")
    async def liveness():
        """
        存活探针 (Liveness Probe)
        — 服务进程是否存活，不检查依赖。
        Docker: HEALTHCHECK --interval=30s CMD curl -f http://localhost:PORT/health
        K8s: livenessProbe.httpGet.path: /health
        """
        return {
            "status": "ok",
            "service": service_name,
            "version": version,
            "uptime_s": round(time.time() - _start_time, 1),
        }

    @router.get("/ready")
    async def readiness():
        """
        就绪探针 (Readiness Probe)
        — 服务是否可以接收流量（依赖全部就绪）。
        K8s: readinessProbe.httpGet.path: /ready
        """
        results: dict[str, Any] = {}
        all_ok = True

        for name, check_fn in dependency_checks.items():
            try:
                result = check_fn()
                if result is True or result == "ok":
                    results[name] = "ok"
                else:
                    results[name] = str(result) if result else "failed"
                    all_ok = False
            except Exception as e:
                results[name] = f"error: {str(e)[:100]}"
                all_ok = False

        status_code = 200 if all_ok else 503
        return {
            "status": "ok" if all_ok else "degraded",
            "service": service_name,
            "version": version,
            "checks": results,
        }

    return router
