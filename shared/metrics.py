"""
QTS Prometheus 指标端点 — 轻量级实现（无需 prometheus_client 依赖）

用法:
    from shared.metrics import MetricsMiddleware, create_metrics_router

    app.add_middleware(MetricsMiddleware)
    app.include_router(create_metrics_router())

    # 访问: GET /metrics → Prometheus text format

自定义业务指标:
    from shared.metrics import COUNTER, HISTOGRAM
    COUNTER.inc("signals_generated", labels={"strategy": "ma_cross"})
    HISTOGRAM.observe("backtest_duration_seconds", 2.35)
"""

from collections import defaultdict
import threading
import time
from typing import Any

from fastapi import APIRouter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse

# ═══════════════════════════════════════
# 指标存储
# ═══════════════════════════════════════


class _Counter:
    """Prometheus Counter — 只增不减。"""

    def __init__(self):
        self._values: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1.0, labels: dict | None = None):
        key = self._key(name, labels)
        with self._lock:
            self._values[key] += value

    def get_all(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)

    @staticmethod
    def _key(name: str, labels: dict | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


class _Histogram:
    """简化 Histogram — 记录 sum/count/buckets。"""

    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._buckets = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

    def observe(self, name: str, value: float, labels: dict | None = None):
        key = _Counter._key(name, labels)
        with self._lock:
            if key not in self._data:
                self._data[key] = {"sum": 0.0, "count": 0, "buckets": [0] * len(self._buckets)}
            d = self._data[key]
            d["sum"] += value
            d["count"] += 1
            for i, b in enumerate(self._buckets):
                if value <= b:
                    d["buckets"][i] += 1

    def get_all(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._data)


class _Gauge:
    """Prometheus Gauge — 可增可减。"""

    def __init__(self):
        self._values: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def set(self, name: str, value: float, labels: dict | None = None):
        key = _Counter._key(name, labels)
        with self._lock:
            self._values[key] = value

    def inc(self, name: str, value: float = 1.0):
        with self._lock:
            self._values[name] += value

    def dec(self, name: str, value: float = 1.0):
        with self._lock:
            self._values[name] -= value

    def get_all(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)


# 全局实例
COUNTER = _Counter()
HISTOGRAM = _Histogram()
GAUGE = _Gauge()


# ═══════════════════════════════════════
# 中间件 — 自动采集请求指标
# ═══════════════════════════════════════


class MetricsMiddleware(BaseHTTPMiddleware):
    """自动采集 HTTP 请求指标。"""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        GAUGE.inc("http_active_requests")
        start = time.time()

        try:
            response = await call_next(request)
            duration = time.time() - start

            labels = {
                "method": request.method,
                "path": self._normalize_path(request.url.path),
                "status": str(response.status_code),
            }
            COUNTER.inc("http_requests_total", labels=labels)
            HISTOGRAM.observe("http_request_duration_seconds", duration, labels=labels)

            return response
        finally:
            GAUGE.dec("http_active_requests")

    @staticmethod
    def _normalize_path(path: str) -> str:
        """规范化路径（替换动态参数为占位符）。"""
        parts = path.strip("/").split("/")
        normalized = []
        for p in parts:
            if p.isdigit() or (len(p) == 6 and p.isdigit()):
                normalized.append(":id")
            else:
                normalized.append(p)
        return "/" + "/".join(normalized)


# ═══════════════════════════════════════
# /metrics 端点
# ═══════════════════════════════════════


def create_metrics_router() -> APIRouter:
    """创建 /metrics 路由，返回 Prometheus text exposition format。"""
    router = APIRouter()

    @router.get("/metrics", include_in_schema=False)
    async def metrics():
        lines = []

        # Counters
        lines.append("# HELP http_requests_total Total HTTP requests")
        lines.append("# TYPE http_requests_total counter")
        for key, val in COUNTER.get_all().items():
            lines.append(f"{key} {val}")

        # Histograms
        lines.append("")
        lines.append("# HELP http_request_duration_seconds Request duration")
        lines.append("# TYPE http_request_duration_seconds histogram")
        for key, data in HISTOGRAM.get_all().items():
            lines.append(f"{key}_sum {data['sum']:.6f}")
            lines.append(f"{key}_count {data['count']}")

        # Gauges
        lines.append("")
        lines.append("# HELP http_active_requests Active HTTP requests")
        lines.append("# TYPE http_active_requests gauge")
        for key, val in GAUGE.get_all().items():
            lines.append(f"{key} {val}")

        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")

    return router
