"""
交易执行服务 - 主应用入口
提供订单管理、MiniQMT集成、交易风险控制等API
"""

import asyncio
from contextlib import asynccontextmanager
import os
import signal
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
import uvicorn

from shared.auth import get_current_user
from shared.logging_config import configure_logging, get_logger
from shared.middleware import TraceIDMiddleware, setup_trace_logging

configure_logging("execution-service")
setup_trace_logging()
logger = get_logger(__name__)

# Prometheus metrics
orders_total = Counter("orders_total", "Total number of orders processed", ["status"])
positions_count = Gauge("positions_count", "Current number of open positions")
risk_events_total = Counter(
    "risk_events_total", "Total number of risk events", ["event_type", "level"]
)
circuit_breaker_open = Gauge(
    "circuit_breaker_open", "Circuit breaker status (1=open/blocked, 0=closed/allowed)"
)
http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration in seconds", ["method", "endpoint"]
)

# WebSocket 指标
websocket_connections_active = Gauge(
    "websocket_connections_active", "Active WebSocket connections", ["service"]
)


from core.exceptions import OrderError, RiskError, PositionError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动初始化 + 优雅关闭"""
    logger.info("=" * 50)
    logger.info("交易执行服务启动中...")

    # 初始化数据库连接
    db_session = None
    try:
        from models.database import get_db_session

        db_session = get_db_session()
        db_session.execute("SELECT 1")
        logger.info("数据库连接验证通过")
    except Exception as e:
        logger.warning(f"数据库连接失败（非致命）: {e}")

    # 初始化飞书告警服务
    alert_service = None
    try:
        from services.feishu_alert import get_alert_service

        alert_service = get_alert_service()
        logger.info(f"飞书告警服务初始化{'成功' if alert_service else '跳过（无webhook）'}")
    except Exception as e:
        logger.warning(f"飞书告警初始化失败（非致命）: {e}")

    # 初始化熔断器状态
    try:
        from services.risk_controller import circuit_breaker

        cb_status = circuit_breaker.status
        circuit_breaker_open.set(1 if cb_status["is_open"] else 0)
        logger.info(
            f"熔断器状态: {'OPEN' if cb_status['is_open'] else 'CLOSED'} (连续止损 {cb_status['consecutive_losses']} 次)"
        )
    except Exception as e:
        logger.warning(f"熔断器初始化失败（非致命）: {e}")

    # 设置信号处理器
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler():
        logger.info("收到终止信号，准备优雅关闭...")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows 不支持 add_signal_handler

    logger.info(f"交易执行服务就绪 | PID={os.getpid()}")
    logger.info("=" * 50)

    # 发送启动通知
    if alert_service:
        try:
            await alert_service.send_system_error("execution-service", "服务已启动")
        except Exception as e:
            logger.error(f"飞书启动通知失败: {e}")

    yield

    # === 优雅关闭 ===
    logger.info("=" * 50)
    logger.info("交易执行服务关闭中...")

    # 1. 停止接收新请求（由 uvicorn 处理）

    # 2. 发送关闭通知
    if alert_service:
        try:
            await alert_service.send_system_error("execution-service", "服务正在关闭")
        except Exception as e:
            logger.error(f"飞书关闭通知失败: {e}")

    # 3. 关闭数据库连接
    if db_session:
        try:
            db_session.close()
            logger.info("数据库连接已关闭")
        except Exception as e:
            logger.warning(f"关闭数据库连接失败: {e}")

    # 4. 等待进行中的请求完成（最多5秒）
    logger.info("等待进行中的请求完成...")
    await asyncio.sleep(1)

    logger.info("交易执行服务已关闭")
    logger.info("=" * 50)


app = FastAPI(
    title="QuantTradingSystem - 交易执行服务",
    description="A股量化交易系统 - 交易执行微服务 v1.1.0",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# Trace ID 中间件 — 跨服务请求链路追踪
app.add_middleware(TraceIDMiddleware)

# 响应体脱敏中间件 — 自动脱敏 API Key / Token / Secret 等敏感字段
from shared.middleware import ResponseSanitizerMiddleware

app.add_middleware(ResponseSanitizerMiddleware)

# 限流中间件
from shared.rate_limiter import RateLimitMiddleware

app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)

# WebSocket 连接管理器 — 挂载指标回调
from api.ws_execution import ws_manager as exec_ws_manager

exec_ws_manager._on_count_change = lambda n: websocket_connections_active.labels(
    service="execution"
).set(n)


# 全局异常处理器
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    logger.warning(f"输入验证失败: {exc}")
    return JSONResponse(status_code=400, content={"code": -1, "message": str(exc), "data": None})


@app.exception_handler(OrderError)
async def order_error_handler(request: Request, exc: OrderError):
    return JSONResponse(
        status_code=exc.status_code, content={"code": -1, "message": exc.message, "data": None}
    )


@app.exception_handler(RiskError)
async def risk_error_handler(request: Request, exc: RiskError):
    return JSONResponse(
        status_code=exc.status_code, content={"code": -1, "message": exc.message, "data": None}
    )


@app.exception_handler(PositionError)
async def position_error_handler(request: Request, exc: PositionError):
    return JSONResponse(
        status_code=exc.status_code, content={"code": -1, "message": exc.message, "data": None}
    )


# 导入并注册路由
from api.orders import router as orders_router
from api.positions import router as positions_router
from api.risk import router as risk_router
from api.ws_execution import router as ws_router

app.include_router(
    orders_router,
    prefix="/api/v1/orders",
    tags=["订单管理"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    positions_router,
    prefix="/api/v1/positions",
    tags=["持仓管理"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    risk_router, prefix="/api/v1/risk", tags=["风险控制"], dependencies=[Depends(get_current_user)]
)
app.include_router(ws_router, prefix="/ws", tags=["WebSocket实时推送"])


@app.get("/", dependencies=[])
async def root():
    return {
        "service": "QuantTradingSystem Execution Service",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health", dependencies=[])
async def health_check():
    return {"status": "healthy"}


@app.get("/metrics", dependencies=[])
async def metrics():
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


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
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
