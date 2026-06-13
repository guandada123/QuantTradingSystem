"""
QTS 优雅关闭模块 — 零停机部署支持

用法:
    from shared.graceful_shutdown import setup_graceful_shutdown, is_shutting_down

    app = FastAPI(lifespan=setup_graceful_shutdown("strategy-service"))

    @app.middleware("http")
    async def reject_during_shutdown(request, call_next):
        if is_shutting_down():
            return JSONResponse(status_code=503, content={"error": "shutting down"})
        return await call_next(request)

K8s 配合:
    spec.containers[].lifecycle.preStop.exec.command: ["sleep", "5"]
    spec.terminationGracePeriodSeconds: 45
"""

from collections.abc import Callable
from contextlib import asynccontextmanager
import logging
import signal
import threading
import time

logger = logging.getLogger(__name__)

# 全局状态
_shutdown_flag = threading.Event()
_active_requests = 0
_active_lock = threading.Lock()
_shutdown_callbacks: list[Callable] = []

# 配置
GRACEFUL_TIMEOUT = 30  # 最多等待30秒完成进行中请求


def is_shutting_down() -> bool:
    """检查是否正在关闭中。"""
    return _shutdown_flag.is_set()


def register_shutdown_callback(fn: Callable):
    """注册关闭时的清理回调（如关闭数据库连接池）。"""
    _shutdown_callbacks.append(fn)


def increment_active():
    """请求开始时调用。"""
    with _active_lock:
        global _active_requests
        _active_requests += 1


def decrement_active():
    """请求结束时调用。"""
    with _active_lock:
        global _active_requests
        _active_requests -= 1


def get_active_count() -> int:
    """当前进行中的请求数。"""
    return _active_requests


def _signal_handler(signum, frame):
    """SIGTERM/SIGINT 信号处理器。"""
    sig_name = signal.Signals(signum).name
    logger.info("graceful_shutdown: received %s, starting shutdown sequence...", sig_name)
    _shutdown_flag.set()


def _wait_for_requests():
    """等待所有进行中的请求完成。"""
    start = time.time()
    while _active_requests > 0:
        elapsed = time.time() - start
        if elapsed > GRACEFUL_TIMEOUT:
            logger.warning(
                "graceful_shutdown: timeout after %ds, %d requests still active — forcing exit",
                GRACEFUL_TIMEOUT,
                _active_requests,
            )
            break
        logger.info(
            "graceful_shutdown: waiting for %d active request(s)... (%.0fs elapsed)",
            _active_requests,
            elapsed,
        )
        time.sleep(0.5)

    logger.info("graceful_shutdown: all requests drained (or timeout reached)")


def setup_graceful_shutdown(service_name: str = "unknown"):
    """
    返回 FastAPI lifespan context manager。

    用法:
        app = FastAPI(lifespan=setup_graceful_shutdown("strategy-service"))
    """

    @asynccontextmanager
    async def lifespan(app):
        # Startup
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
        logger.info("graceful_shutdown: %s registered signal handlers", service_name)
        yield
        # Shutdown
        logger.info("graceful_shutdown: %s shutdown initiated", service_name)
        _shutdown_flag.set()
        _wait_for_requests()
        # 执行清理回调
        for cb in _shutdown_callbacks:
            try:
                cb()
                logger.info("graceful_shutdown: callback %s executed", cb.__name__)
            except Exception as e:
                logger.error("graceful_shutdown: callback %s failed: %s", cb.__name__, e)
        logger.info("graceful_shutdown: %s shutdown complete ✓", service_name)

    return lifespan
