"""shared/health.py 单元测试 — /health + /ready 探针"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from shared.health import create_health_router


def _make_app(**kwargs) -> TestClient:
    """创建带 health router 的测试 app"""
    app = FastAPI()
    app.include_router(create_health_router(**kwargs))
    return TestClient(app)


class TestLivenessProbe:
    def test_health_returns_200(self):
        client = _make_app(service_name="test-svc", version="1.0.0")
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_service_name(self):
        client = _make_app(service_name="my-service")
        data = client.get("/health").json()
        assert data["service"] == "my-service"

    def test_health_returns_version(self):
        client = _make_app(version="2.5.0")
        data = client.get("/health").json()
        assert data["version"] == "2.5.0"

    def test_health_returns_uptime(self):
        client = _make_app()
        data = client.get("/health").json()
        assert "uptime_s" in data
        assert data["uptime_s"] >= 0

    def test_health_status_ok(self):
        client = _make_app()
        data = client.get("/health").json()
        assert data["status"] == "ok"


class TestReadinessProbe:
    def test_ready_returns_200_with_no_checks(self):
        client = _make_app()
        response = client.get("/ready")
        assert response.status_code == 200

    def test_ready_with_passing_checks(self):
        client = _make_app(checks={"db": lambda: True, "cache": lambda: True})
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_ready_with_failing_check(self):
        client = _make_app(checks={"db": lambda: True, "cache": lambda: False})
        response = client.get("/ready")
        data = response.json()
        # 有失败的检查，状态应为 degraded 或 503
        assert data["status"] != "ok" or response.status_code == 503


class TestRouterStructure:
    def test_returns_api_router(self):
        router = create_health_router("svc")
        assert isinstance(router, APIRouter)

    def test_default_service_name(self):
        client = _make_app()
        data = client.get("/health").json()
        assert data["service"] == "unknown"
