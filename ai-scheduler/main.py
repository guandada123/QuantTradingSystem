"""
AI调度器微服务 v1.0
负责智能选股扫描、AI每日复盘等AI任务的调度与管理
独立微服务，端口8002
"""

from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from services.feishu_alert import HealthAlertService
from services.health_monitor import HealthMonitor
import uvicorn

from shared.middleware import TraceIDMiddleware, setup_trace_logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s",
)
setup_trace_logging()
logger = logging.getLogger(__name__)

# Prometheus metrics
ai_calls_total = Counter("ai_calls_total", "Total number of AI API calls", ["model"])
ai_latency_seconds = Histogram("ai_latency_seconds", "AI call latency in seconds", ["model"])
scheduled_tasks_active = Gauge(
    "scheduled_tasks_active", "Number of currently active scheduled tasks"
)
# WebSocket 指标
websocket_connections_active = Gauge(
    "websocket_connections_active", "Active WebSocket connections", ["service"]
)

http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration in seconds", ["method", "endpoint"]
)


# 全局健康监控实例
health_monitor: HealthMonitor = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    global health_monitor
    logger.info("🤖 AI调度器启动中...")
    logger.info(f"  策略服务: {settings.STRATEGY_SERVICE_URL}")
    logger.info(f"  执行服务: {settings.EXECUTION_SERVICE_URL}")

    # 初始化飞书告警和健康监控
    alert_service = None
    if settings.FEISHU_WEBHOOK:
        alert_service = HealthAlertService(settings.FEISHU_WEBHOOK)
        logger.info("  飞书告警服务已启用")
    else:
        logger.warning("  FEISHU_WEBHOOK 未配置，告警功能禁用")

    health_monitor = HealthMonitor(alert_service=alert_service)
    await health_monitor.start(interval=settings.HEALTH_CHECK_INTERVAL)

    yield

    # 关闭健康监控
    if health_monitor:
        await health_monitor.stop()
    logger.info("AI调度器关闭中...")


from core.config import settings

app = FastAPI(
    title="QuantTradingSystem - AI调度器",
    description="A股量化交易系统 - AI智能调度微服务",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Trace ID 中间件 — 跨服务请求链路追踪
app.add_middleware(TraceIDMiddleware)

# WebSocket 连接管理器 — 挂载指标回调
from api.ws_scheduler import ws_manager as sched_ws_manager

sched_ws_manager._on_count_change = lambda n: websocket_connections_active.labels(
    service="ai-scheduler"
).set(n)

# 注册路由
from api.schedule import router as schedule_router
from api.ws_scheduler import router as ws_router

app.include_router(schedule_router, prefix="/api/v1/scheduler", tags=["调度任务"])
app.include_router(ws_router, prefix="/ws", tags=["WebSocket实时推送"])


@app.get("/")
async def root():
    return {"service": "QuantTradingSystem AI Scheduler", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "ai-scheduler"}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/health-monitor/status")
async def health_monitor_status():
    """获取各服务健康状态"""
    if health_monitor is None:
        return {"error": "健康监控未初始化", "services": {}}
    status = health_monitor.get_status()
    return {
        "services": status,
        "all_healthy": all(status.values()) if status else False,
    }


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    if request.url.path not in ("/metrics", "/health"):
        http_requests_total.labels(
            method=request.method, endpoint=request.url.path, status=str(response.status_code)
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method, endpoint=request.url.path
        ).observe(duration)
    return response


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.SERVICE_HOST, port=settings.SERVICE_PORT, reload=False)
