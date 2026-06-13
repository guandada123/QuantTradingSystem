"""
QTS API 限流中间件 — 令牌桶算法

用法:
    from shared.rate_limiter import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)

特性:
    - 令牌桶算法（平滑限流，不拒绝突发小流量）
    - 按 IP 隔离（不同客户端独立计数）
    - 返回标准 429 + Retry-After 头
    - 白名单支持（健康检查等内部端点）
    - 自动清理过期桶（防内存泄漏）
"""

from collections.abc import Callable
import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class _TokenBucket:
    """令牌桶 — 按固定速率补充令牌。"""

    __slots__ = ("capacity", "tokens", "refill_rate", "last_refill")

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate  # tokens per second
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        """尝试消耗一个令牌，返回是否成功。"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    @property
    def retry_after(self) -> float:
        """下一个令牌到达需要等待的秒数。"""
        if self.tokens >= 1:
            return 0
        return (1 - self.tokens) / self.refill_rate


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI 限流中间件。

    Args:
        app: ASGI 应用
        max_requests: 窗口内最大请求数（桶容量）
        window_seconds: 时间窗口（秒）
        whitelist_paths: 不限流的路径前缀列表
    """

    def __init__(
        self,
        app,
        max_requests: int = 60,
        window_seconds: int = 60,
        whitelist_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.max_requests = max_requests
        self.refill_rate = max_requests / window_seconds
        self.whitelist_paths = whitelist_paths or ["/health", "/ready", "/metrics", "/docs"]
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 300  # 每5分钟清理过期桶

    def _get_bucket(self, key: str) -> _TokenBucket:
        with self._lock:
            # 定期清理（防止内存泄漏）
            now = time.monotonic()
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_stale_buckets()
                self._last_cleanup = now

            if key not in self._buckets:
                self._buckets[key] = _TokenBucket(self.max_requests, self.refill_rate)
            return self._buckets[key]

    def _cleanup_stale_buckets(self):
        """清理 5 分钟无活动的桶。"""
        now = time.monotonic()
        stale = [k for k, b in self._buckets.items() if now - b.last_refill > 300]
        for k in stale:
            del self._buckets[k]

    def _get_client_ip(self, request: Request) -> str:
        """提取真实客户端 IP（支持反向代理）。"""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: Callable):
        # 白名单路径不限流
        path = request.url.path
        if any(path.startswith(wp) for wp in self.whitelist_paths):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        bucket = self._get_bucket(client_ip)

        if bucket.consume():
            response = await call_next(request)
            # 添加限流信息头（帮助客户端自适应）
            response.headers["X-RateLimit-Limit"] = str(self.max_requests)
            response.headers["X-RateLimit-Remaining"] = str(int(bucket.tokens))
            return response

        # 限流 — 返回 429
        retry_after = int(bucket.retry_after) + 1
        return JSONResponse(
            status_code=429,
            content={
                "error": "请求过于频繁，请稍后重试",
                "retry_after_seconds": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(self.max_requests),
                "X-RateLimit-Remaining": "0",
            },
        )
