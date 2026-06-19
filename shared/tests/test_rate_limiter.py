"""shared/rate_limiter.py 单元测试 — 令牌桶算法"""

from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.rate_limiter import _TokenBucket


class TestTokenBucket:
    def test_initial_tokens_full(self):
        """初始化时令牌桶应满"""
        bucket = _TokenBucket(capacity=10, refill_rate=10)
        assert bucket.consume()

    def test_consume_tokens(self):
        """连续请求应消耗令牌"""
        bucket = _TokenBucket(capacity=5, refill_rate=100)
        results = [bucket.consume() for _ in range(5)]
        assert all(results)

    def test_exceed_capacity_rejected(self):
        """超过容量的请求应被拒绝"""
        bucket = _TokenBucket(capacity=3, refill_rate=0.01)
        for _ in range(3):
            bucket.consume()
        assert bucket.consume() is False

    def test_refill_over_time(self):
        """令牌随时间补充"""
        bucket = _TokenBucket(capacity=5, refill_rate=1000)
        for _ in range(5):
            bucket.consume()
        assert bucket.consume() is False
        time.sleep(0.01)  # 1000 tokens/s * 0.01s = 10 tokens
        assert bucket.consume() is True

    def test_retry_after_positive_when_empty(self):
        """令牌耗尽时 retry_after > 0"""
        bucket = _TokenBucket(capacity=1, refill_rate=1.0)
        bucket.consume()
        assert bucket.retry_after > 0

    def test_retry_after_zero_when_available(self):
        """有令牌时 retry_after == 0"""
        bucket = _TokenBucket(capacity=10, refill_rate=10)
        assert bucket.retry_after == 0

    def test_capacity_not_exceeded_after_refill(self):
        """补充后令牌不超过容量"""
        bucket = _TokenBucket(capacity=3, refill_rate=1000)
        time.sleep(0.1)  # 等待大量补充
        # 连续消耗不应超过容量
        results = [bucket.consume() for _ in range(4)]
        assert results[:3] == [True, True, True]
        assert results[3] is False


class TestTokenBucketEdgeCases:
    def test_zero_capacity(self):
        """容量为 0 时所有请求被拒"""
        bucket = _TokenBucket(capacity=0, refill_rate=10)
        assert bucket.consume() is False

    def test_very_high_rate(self):
        """极高速率不崩溃"""
        bucket = _TokenBucket(capacity=100, refill_rate=1_000_000)
        results = [bucket.consume() for _ in range(100)]
        assert all(results)

    def test_slots_optimization(self):
        """_TokenBucket 使用 __slots__ 优化"""
        bucket = _TokenBucket(capacity=5, refill_rate=1)
        assert hasattr(bucket, "__slots__")
