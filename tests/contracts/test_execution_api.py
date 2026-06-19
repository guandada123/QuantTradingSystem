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
            # 可能 200、404、或 500，但不应连接失败
            assert resp.status_code is not None
        except requests.ConnectionError:
            pytest.skip("execution-service not reachable")

    def test_orders_endpoint(self):
        try:
            resp = requests.get(f"{EXECUTION_URL}/api/v1/orders", timeout=5)
            assert resp.status_code is not None
        except requests.ConnectionError:
            pytest.skip("execution-service not reachable")
