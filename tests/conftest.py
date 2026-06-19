"""
集成测试 / E2E 测试共享 fixtures。

依赖 Docker Compose 启动的完整服务栈。
"""

import os
import sys
import time
from typing import Any

import pytest
import requests

# ---- Environment ----
os.environ.setdefault("ENV", "test")
os.environ.setdefault("SERVICE_BASE_URL", "http://localhost:8000")


# ============================================================
#  Service Health Fixtures
# ============================================================


def _wait_for_service(url: str, timeout: int = 60, interval: float = 2.0) -> bool:
    """Wait for a service to become healthy."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{url}/health", timeout=5)
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(interval)
    return False


@pytest.fixture(scope="session")
def strategy_service_url() -> str:
    """URL for the strategy service."""
    return os.environ.get("STRATEGY_SERVICE_URL", "http://localhost:8001")


@pytest.fixture(scope="session")
def execution_service_url() -> str:
    """URL for the execution service."""
    return os.environ.get("EXECUTION_SERVICE_URL", "http://localhost:8002")


@pytest.fixture(scope="session")
def ai_scheduler_url() -> str:
    """URL for the AI scheduler service."""
    return os.environ.get("AI_SCHEDULER_URL", "http://localhost:8003")


@pytest.fixture(scope="session")
def services_healthy(
    strategy_service_url: str,
    execution_service_url: str,
    ai_scheduler_url: str,
) -> dict[str, bool]:
    """Wait for all services to be healthy. Returns health status per service."""
    results = {
        "strategy": _wait_for_service(strategy_service_url),
        "execution": _wait_for_service(execution_service_url),
        "ai_scheduler": _wait_for_service(ai_scheduler_url),
    }
    return results


# ============================================================
#  HTTP Session Fixtures
# ============================================================


@pytest.fixture
def strategy_client(strategy_service_url: str) -> requests.Session:
    """HTTP client for strategy service."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.base_url = strategy_service_url  # type: ignore[attr-defined]
    return session


@pytest.fixture
def execution_client(execution_service_url: str) -> requests.Session:
    """HTTP client for execution service."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.base_url = execution_service_url  # type: ignore[attr-defined]
    return session


# ============================================================
#  E2E Test Data Fixtures
# ============================================================


@pytest.fixture
def e2e_stock_code() -> str:
    """Stock code used for E2E tests (liquid, large-cap)."""
    return "000001.SZ"


@pytest.fixture
def e2e_test_user() -> dict[str, str]:
    """Mock test user credentials for E2E tests."""
    return {
        "username": "test_user",
        "api_key": "test_api_key_e2e",
    }


# ============================================================
#  Test Hooks
# ============================================================


@pytest.fixture(autouse=True)
def check_services(services_healthy: dict[str, bool], request: pytest.FixtureRequest):
    """Auto-check that services are healthy before E2E tests.

    Skips E2E tests if services are not available (avoids false failures in CI).
    """
    if "e2e" in request.keywords:
        if not all(services_healthy.values()):
            unavailable = [k for k, v in services_healthy.items() if not v]
            pytest.skip(f"Services not available: {', '.join(unavailable)}")
