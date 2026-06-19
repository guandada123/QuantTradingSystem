"""
集成测试 / E2E 测试共享 fixtures。

依赖 Docker Compose 启动的完整服务栈。
注意：docker-compose.yml 实际端口映射为：
  - strategy-service: 8000
  - execution-service: 8001
  - ai-scheduler: 8002
"""

import os
import time

import pytest
import requests

# ---- Environment ----
os.environ.setdefault("ENV", "test")
# 与 docker-compose.yml 端口映射对齐（若非标准端口可覆盖）
os.environ.setdefault("STRATEGY_SERVICE_URL", "http://localhost:8000")
os.environ.setdefault("EXECUTION_SERVICE_URL", "http://localhost:8001")
os.environ.setdefault("AI_SCHEDULER_URL", "http://localhost:8002")


# ============================================================
#  Service Health Fixtures
# ============================================================


def _check_service(url: str, timeout: int = 5) -> bool:
    """Quick health check for a service (5s max)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{url}/health", timeout=3)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def strategy_service_url() -> str:
    """URL for the strategy service (docker-compose port 8000)."""
    return os.environ["STRATEGY_SERVICE_URL"]


@pytest.fixture(scope="session")
def execution_service_url() -> str:
    """URL for the execution service (docker-compose port 8001)."""
    return os.environ["EXECUTION_SERVICE_URL"]


@pytest.fixture(scope="session")
def ai_scheduler_url() -> str:
    """URL for the AI scheduler service (docker-compose port 8002)."""
    return os.environ["AI_SCHEDULER_URL"]


@pytest.fixture(scope="session")
def services_healthy(
    strategy_service_url: str,
    execution_service_url: str,
    ai_scheduler_url: str,
) -> dict[str, bool]:
    """Quick-check all services. Returns health status per service."""
    results = {
        "strategy": _check_service(strategy_service_url),
        "execution": _check_service(execution_service_url),
        "ai_scheduler": _check_service(ai_scheduler_url),
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
    Unit tests (no 'e2e' marker) are NOT affected.
    """
    if "e2e" in request.keywords:
        if not all(services_healthy.values()):
            unavailable = [k for k, v in services_healthy.items() if not v]
            pytest.skip(f"Services not available: {', '.join(unavailable)}")
