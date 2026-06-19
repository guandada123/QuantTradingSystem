"""
弹性模式模块 — 重试、断路器、降级。

用于保护对外部不稳定服务的调用（AkShare、大模型 API 等）。

Usage:
    from shared.resilience import retry_async, CircuitBreaker

    # 重试
    result = await retry_async(akshare_callable, "000001.SZ", max_retries=3)

    # 断路器
    breaker = CircuitBreaker("akshare", failure_threshold=5, recovery_timeout=60)
    try:
        data = await breaker.call(akshare_callable, "000001.SZ")
    except CircuitBreakerOpenError:
        data = await fallback_source.get_quote("000001.SZ")
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Prometheus metrics (lazy import — only if prometheus_client is installed)
try:
    from prometheus_client import Counter, Gauge

    _CB_STATE = Gauge(
        "circuit_breaker_state",
        "Circuit breaker state (0=CLOSED, 1=OPEN, 2=HALF_OPEN)",
        ["name"],
    )
    _CB_FAILURES = Counter(
        "circuit_breaker_failures_total",
        "Total failures recorded by circuit breaker",
        ["name"],
    )
    _RETRY_ATTEMPTS = Counter(
        "retry_attempts_total",
        "Total retry attempts",
        ["func"],
    )
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


# ============================================================
#  Retry with Exponential Backoff
# ============================================================


def retry(
    func: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple[type[BaseException], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    ),
    **kwargs: Any,
) -> Any:
    """同步重试——指数退避。

    Args:
        func: 被调用的函数
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒），每次重试 delay = base_delay * 2^attempt
        max_delay: 最大延迟上限（秒）
        retryable_exceptions: 可重试的异常类型
    """
    last_exception: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries:
                logger.error(
                    "retry_exhausted func=%s attempts=%s error=%s",
                    func.__name__,
                    attempt + 1,
                    str(e)[:200],
                )
                raise

            delay = min(base_delay * (2**attempt), max_delay)
            logger.warning(
                "retry_attempt func=%s attempt=%s max_retries=%s delay=%s error=%s",
                func.__name__,
                attempt + 1,
                max_retries,
                delay,
                str(e)[:100],
            )
            time.sleep(delay)


async def retry_async(
    func: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple[type[BaseException], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    ),
    **kwargs: Any,
) -> Any:
    """异步重试——指数退避。

    Args:
        func: 被调用的异步函数
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟上限（秒）
        retryable_exceptions: 可重试的异常类型
    """
    last_exception: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries:
                logger.error(
                    "retry_async_exhausted func=%s attempts=%s error=%s",
                    func.__name__,
                    attempt + 1,
                    str(e)[:200],
                )
                raise

            delay = min(base_delay * (2**attempt), max_delay)
            logger.warning(
                "retry_async_attempt func=%s attempt=%s max_retries=%s delay=%s error=%s",
                func.__name__,
                attempt + 1,
                max_retries,
                delay,
                str(e)[:100],
            )
            await asyncio.sleep(delay)


# ============================================================
#  Circuit Breaker
# ============================================================


class CircuitBreakerOpenError(Exception):
    """断路器打开时抛出。"""


@dataclass
class CircuitBreaker:
    """断路器 — 连续失败达到阈值后，短时间内跳过调用。

    Usage:
        breaker = CircuitBreaker("akshare", failure_threshold=5, recovery_timeout=60)

        async def get_quote(ts_code: str):
            try:
                return await breaker.call(akshare_get_quote, ts_code)
            except CircuitBreakerOpenError:
                return await tencent_get_quote(ts_code)  # 降级
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # 断路器打开后等待多少秒再尝试恢复

    _failures: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _state: str = field(default="CLOSED", init=False)  # CLOSED | OPEN | HALF_OPEN
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def is_open(self) -> bool:
        """断路器是否打开（拒绝请求）"""
        with self._lock:
            if self._state == "CLOSED":
                return False
            if self._state == "OPEN":
                # 检查是否可以恢复
                if time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = "HALF_OPEN"
                    logger.info(
                        "circuit_breaker_half_open name=%s elapsed=%.1f",
                        self.name,
                        time.time() - self._last_failure_time,
                    )
                    return False
                return True
            # HALF_OPEN — 允许通过
            return False

    def record_success(self) -> None:
        """记录成功——关闭断路器"""
        with self._lock:
            self._failures = 0
            if self._state != "CLOSED":
                logger.info("circuit_breaker_closed name=%s", self.name)
                self._state = "CLOSED"
        self._update_prometheus()

    def record_failure(self) -> None:
        """记录失败——可能触发断路器打开"""
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()

            if self._failures >= self.failure_threshold:
                if self._state != "OPEN":
                    self._state = "OPEN"
                    logger.error(
                        "circuit_breaker_opened name=%s failures=%s threshold=%s",
                        self.name,
                        self._failures,
                        self.failure_threshold,
                    )
        self._update_prometheus()
        if _HAS_PROMETHEUS:
            _CB_FAILURES.labels(name=self.name).inc()

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """通过断路器调用函数。

        Raises:
            CircuitBreakerOpenError: 断路器打开
            原始异常: 调用失败（HALF_OPEN 状态下失败会重新打开断路器）
        """
        if self.is_open:
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is OPEN "
                f"(failures={self._failures}/{self.failure_threshold})"
            )

        try:
            result = (
                await func(*args, **kwargs)
                if asyncio.iscoroutinefunction(func)
                else func(*args, **kwargs)
            )
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def _update_prometheus(self) -> None:
        """更新 Prometheus 指标."""
        if not _HAS_PROMETHEUS:
            return
        state_map = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}
        _CB_STATE.labels(name=self.name).set(state_map.get(self._state, -1))


# ============================================================
#  Global Circuit Breakers
# ============================================================

# 全局断路器实例——按服务名索引
_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """获取或创建命名断路器。

    断路器是全局单例，按 name 去重。
    """
    with _breakers_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
            logger.info("circuit_breaker_created name=%s", name)
        return _breakers[name]


# ============================================================
#  Safe Import（不会因外部库异常导致服务崩溃）
# ============================================================


def safe_import(module_name: str, package: str | None = None) -> Any | None:
    """安全导入——导入失败返回 None 而不是崩溃。

    Usage:
        ak = safe_import("akshare")
        if ak is None:
            logger.warning("akshare not available, using fallback")
    """
    try:
        return __import__(module_name, fromlist=[package] if package else None)
    except ImportError as e:
        logger.warning("safe_import_failed module=%s error=%s", module_name, str(e))
        return None
    except Exception as e:
        logger.error("safe_import_crashed module=%s error=%s", module_name, str(e))
        return None
