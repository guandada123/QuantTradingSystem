"""
执行服务 API 契约测试
"""

import pytest
import requests

EXECUTION_URL = "http://localhost:8001"


class TestExecutionHealth:
    def test_service_reachable(self):
        try:
            resp = requests.get(f"{EXECUTION_URL}/health", timeout=3)
            assert resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            pytest.skip("execution-service not reachable")

    def test_positions_endpoint(self):
        try:
            resp = requests.get(f"{EXECUTION_URL}/api/v1/positions", timeout=5)
            # 🔴 2026-10-31 修：原 `assert resp.status_code is not None` 恒真（任何 HTTP 响应
            # 都非 None），等于没测。契约下限改为「服务端不得 5xx」——能抓住真实故障。
            assert resp.status_code < 500, f"positions 返回服务端错误 {resp.status_code}"
        except requests.ConnectionError:
            pytest.skip("execution-service not reachable")

    def test_orders_endpoint(self):
        try:
            resp = requests.get(f"{EXECUTION_URL}/api/v1/orders", timeout=5)
            # 同上：原为恒真断言，改为排除 5xx
            assert resp.status_code < 500, f"orders 返回服务端错误 {resp.status_code}"
        except requests.ConnectionError:
            pytest.skip("execution-service not reachable")
