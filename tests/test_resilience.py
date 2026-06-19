"""
shared/resilience.py 单元测试。

覆盖：retry / retry_async / CircuitBreaker / safe_import
"""

import asyncio
import time

import pytest

from shared.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    get_circuit_breaker,
    retry,
    retry_async,
    safe_import,
)

# ============================================================
#  retry() 测试
# ============================================================


class TestRetry:
    """指数退避重试测试"""

    def test_retry_success_first_attempt(self):
        """第一次即成功，不重试"""
        call_count = 0

        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = retry(succeed, max_retries=3)
        assert result == "ok"
        assert call_count == 1

    def test_retry_success_after_failures(self):
        """失败2次后第3次成功"""
        call_count = 0

        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "eventually ok"

        result = retry(fail_then_succeed, max_retries=3)
        assert result == "eventually ok"
        assert call_count == 3

    def test_retry_exhausted_raises(self):
        """所有重试耗尽，抛出原始异常"""

        def always_fail():
            raise ConnectionError("always fail")

        with pytest.raises(ConnectionError, match="always fail"):
            retry(always_fail, max_retries=2)

    def test_retry_non_retryable_raises_immediately(self):
        """非重试型异常不重试，直接抛出"""

        def value_error():
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            retry(value_error, max_retries=5)


# ============================================================
#  retry_async() 测试
# ============================================================


class TestRetryAsync:
    """异步重试测试"""

    @pytest.mark.asyncio
    async def test_retry_async_success(self):
        async def succeed():
            return "async_ok"

        result = await retry_async(succeed, max_retries=3)
        assert result == "async_ok"

    @pytest.mark.asyncio
    async def test_retry_async_eventual_success(self):
        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("timeout")
            return "eventually"

        result = await retry_async(fail_twice, max_retries=3)
        assert result == "eventually"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_async_exhausted(self):
        async def always_fail():
            raise ConnectionError("dead")

        with pytest.raises(ConnectionError, match="dead"):
            await retry_async(always_fail, max_retries=1)


# ============================================================
#  CircuitBreaker 测试
# ============================================================


class TestCircuitBreaker:
    """断路器状态机测试"""

    def test_initial_state_closed(self):
        breaker = CircuitBreaker("test", failure_threshold=3)
        assert not breaker.is_open

    def test_closed_after_success(self):
        breaker = CircuitBreaker("test", failure_threshold=2)
        for _ in range(3):
            breaker.record_success()
        assert not breaker.is_open
        assert breaker._failures == 0  # noqa: SLF001

    def test_opens_after_threshold(self):
        breaker = CircuitBreaker("test", failure_threshold=2)
        breaker.record_failure()
        assert not breaker.is_open  # 1 failure < 2
        breaker.record_failure()
        assert breaker.is_open  # 2 failures = threshold → OPEN

    def test_half_open_after_timeout(self, monkeypatch):
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        breaker.record_failure()
        assert breaker.is_open

        # 等待恢复时间 + 少许余量
        time.sleep(0.15)

        # 下一次访问时应变为 HALF_OPEN（即 is_open=False）
        assert not breaker.is_open

    def test_half_open_success_closes(self, monkeypatch):
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        breaker.record_failure()
        assert breaker.is_open
        time.sleep(0.1)

        # HALF_OPEN → success → CLOSED
        breaker.record_success()
        assert not breaker.is_open
        assert breaker._failures == 0  # noqa: SLF001

    def test_half_open_failure_reopens(self, monkeypatch):
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        breaker.record_failure()
        assert breaker.is_open
        time.sleep(0.1)

        # HALF_OPEN → failure → OPEN again
        breaker.record_failure()
        assert breaker.is_open

    @pytest.mark.asyncio
    async def test_call_success(self):
        breaker = CircuitBreaker("test", failure_threshold=2)

        async def good():
            return "ok"

        result = await breaker.call(good)
        assert result == "ok"
        assert not breaker.is_open

    @pytest.mark.asyncio
    async def test_call_opens_breaker(self):
        breaker = CircuitBreaker("test", failure_threshold=2)

        async def bad():
            raise ConnectionError("bad")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                await breaker.call(bad)

        # 断路器应打开
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(bad)

    @pytest.mark.asyncio
    async def test_call_sync_function(self):
        breaker = CircuitBreaker("test", failure_threshold=2)

        def sync_ok():
            return "sync"

        result = await breaker.call(sync_ok)
        assert result == "sync"


# ============================================================
#  get_circuit_breaker 测试
# ============================================================


class TestGetCircuitBreaker:
    """全局断路器工厂测试"""

    def test_same_name_returns_same_instance(self):
        b1 = get_circuit_breaker("test-global", failure_threshold=3)
        b2 = get_circuit_breaker("test-global")
        assert b1 is b2

    def test_different_names_different_instances(self):
        b1 = get_circuit_breaker("akshare")
        b2 = get_circuit_breaker("llm")
        assert b1 is not b2
        assert b1.name == "akshare"
        assert b2.name == "llm"


# ============================================================
#  safe_import 测试
# ============================================================


class TestSafeImport:
    """安全导入测试"""

    def test_import_existing_module(self):
        mod = safe_import("os")
        assert mod is not None
        assert hasattr(mod, "path")

    def test_import_nonexistent_module(self):
        mod = safe_import("this_module_does_not_exist_xyz")
        assert mod is None

    def test_import_subpackage(self):
        mod = safe_import("json", package="json")
        assert mod is not None
