"""
策略服务性能回归门禁
在 CI 中运行，超过阈值阻止合并。
"""

import time

import pytest
import requests

STRATEGY_URL = "http://localhost:8000"

# 性能阈值（毫秒）
MAX_HEALTH_MS = 100
MAX_INDEX_MS = 5000
MAX_REALTIME_MS = 3000
MAX_BACKTEST_MS = 30000


class TestLatency:
    def test_health_latency(self):
        latencies = []
        for _ in range(5):
            start = time.perf_counter()
            requests.get(f"{STRATEGY_URL}/health", timeout=5)
            latencies.append((time.perf_counter() - start) * 1000)
        avg = sum(latencies) / len(latencies)
        assert avg < MAX_HEALTH_MS, f"health endpoint avg {avg:.1f}ms > {MAX_HEALTH_MS}ms"

    def test_index_realtime_latency(self):
        start = time.perf_counter()
        resp = requests.get(f"{STRATEGY_URL}/api/v1/stocks/index/realtime", timeout=10)
        elapsed = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed < MAX_INDEX_MS, f"index endpoint {elapsed:.0f}ms > {MAX_INDEX_MS}ms"

    def test_realtime_quote_latency(self):
        start = time.perf_counter()
        resp = requests.get(f"{STRATEGY_URL}/api/v1/stocks/realtime/600519.SH", timeout=10)
        elapsed = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed < MAX_REALTIME_MS, f"realtime endpoint {elapsed:.0f}ms > {MAX_REALTIME_MS}ms"

    def test_backtest_latency(self):
        payload = {
            "ts_code": "000001.SZ",
            "strategies": ["ma-cross"],
            "start_date": "20250101",
            "end_date": "20250331",
            "initial_cash": 100000,
        }
        start = time.perf_counter()
        resp = requests.post(
            f"{STRATEGY_URL}/api/v1/backtest/run",
            json=payload,
            timeout=60,
        )
        elapsed = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed < MAX_BACKTEST_MS, f"backtest {elapsed:.0f}ms > {MAX_BACKTEST_MS}ms"
