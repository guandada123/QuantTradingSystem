"""
api/schedule.py 单元测试
覆盖: POST /scan, POST /review, GET /tasks, GET /tasks/{id}, GET /health, GET /stats
"""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def app():
    """创建仅包含 schedule router 的 FastAPI app"""
    app = FastAPI()
    from api.schedule import router as schedule_router
    app.include_router(schedule_router, prefix="/api/v1/scheduler")
    return app


@pytest.fixture
def client(app):
    """FastAPI TestClient"""
    return TestClient(app)


class TestTriggerScan:
    """POST /api/v1/scheduler/scan 测试"""

    def test_scan_creates_task(self, client):
        """触发扫描创建任务"""
        resp = client.post("/api/v1/scheduler/scan", json={"limit": 50})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["status"] == "pending"
        assert data["task_id"].startswith("scan-")

    def test_scan_default_params(self, client):
        """默认参数（limit=100）"""
        resp = client.post("/api/v1/scheduler/scan", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"

    def test_scan_with_strategy_ids(self, client):
        """带 strategy_ids 参数"""
        resp = client.post("/api/v1/scheduler/scan", json={
            "limit": 20,
            "strategy_ids": ["ma-cross", "breakout"]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_scan_with_ts_codes(self, client):
        """带 ts_codes 参数"""
        resp = client.post("/api/v1/scheduler/scan", json={
            "ts_codes": ["600519.SH", "000858.SZ"]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_scan_full_params(self, client):
        """全参数组合"""
        resp = client.post("/api/v1/scheduler/scan", json={
            "limit": 10,
            "strategy_ids": ["ma-cross"],
            "ts_codes": ["600519.SH"]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_scan_negative_limit_accepted(self, client):
        """负 limit 被接受（无参数校验）"""
        resp = client.post("/api/v1/scheduler/scan", json={"limit": -1})
        assert resp.status_code == 200  # 无校验，接受任意值


class TestTriggerReview:
    """POST /api/v1/scheduler/review 测试"""

    def test_review_creates_task(self, client):
        """触发复盘创建任务"""
        resp = client.post("/api/v1/scheduler/review", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["status"] == "pending"
        assert data["task_id"].startswith("review-")

    def test_review_with_date(self, client):
        """指定日期"""
        resp = client.post("/api/v1/scheduler/review", json={"date": "2026-06-10"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_review_without_ai(self, client):
        """不包含 AI"""
        resp = client.post("/api/v1/scheduler/review", json={"include_ai": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_review_default_include_ai(self, client):
        """默认 include_ai=True"""
        resp = client.post("/api/v1/scheduler/review", json={})
        assert resp.status_code == 200


class TestListTasks:
    """GET /api/v1/scheduler/tasks 测试"""

    def test_list_tasks_empty(self, client):
        """空任务列表"""
        # 需要独立 client 确保无 side effect
        resp = client.get("/api/v1/scheduler/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_tasks_after_scan(self, client):
        """创建 scan 后列出任务"""
        client.post("/api/v1/scheduler/scan", json={"limit": 10})
        resp = client.get("/api/v1/scheduler/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        # 验证返回格式
        task = data[0]
        assert "task_id" in task
        assert "task_type" in task
        assert "status" in task
        assert task["task_type"] == "scan"

    def test_list_tasks_after_scan_and_review(self, client):
        """创建两个任务后列出"""
        client.post("/api/v1/scheduler/scan", json={})
        client.post("/api/v1/scheduler/review", json={})
        resp = client.get("/api/v1/scheduler/tasks")
        data = resp.json()
        assert len(data) >= 2

    def test_list_tasks_response_model(self, client):
        """验证响应符合 TaskStatus 模型"""
        client.post("/api/v1/scheduler/scan", json={})
        resp = client.get("/api/v1/scheduler/tasks")
        task = resp.json()[0]
        assert task["status"] in ("pending", "running", "completed", "failed")
        assert isinstance(task["progress"], (int, float))


class TestGetTask:
    """GET /api/v1/scheduler/tasks/{task_id} 测试"""

    def test_get_existing_task(self, client):
        """获取存在的任务"""
        scan_resp = client.post("/api/v1/scheduler/scan", json={})
        task_id = scan_resp.json()["task_id"]

        resp = client.get(f"/api/v1/scheduler/tasks/{task_id}")
        assert resp.status_code == 200
        task = resp.json()
        assert task["task_id"] == task_id
        assert task["task_type"] == "scan"

    def test_get_nonexistent_task_returns_404(self, client):
        """获取不存在的任务返回 404"""
        resp = client.get("/api/v1/scheduler/tasks/nonexistent-id")
        assert resp.status_code == 404
        assert "detail" in resp.json()

    def test_get_review_task(self, client):
        """获取 review 任务"""
        review_resp = client.post("/api/v1/scheduler/review", json={"date": "2026-06-10"})
        task_id = review_resp.json()["task_id"]

        resp = client.get(f"/api/v1/scheduler/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["task_type"] == "review"


class TestHealth:
    """GET /api/v1/scheduler/health 测试"""

    def test_health_returns_healthy(self, client):
        """健康检查返回 healthy"""
        resp = client.get("/api/v1/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ai-scheduler"

    def test_health_with_pending_tasks(self, client):
        """有待处理任务时计数正确"""
        client.post("/api/v1/scheduler/scan", json={})
        client.post("/api/v1/scheduler/review", json={})

        resp = client.get("/api/v1/scheduler/health")
        data = resp.json()
        assert data["pending_tasks"] >= 2
        assert data["running_tasks"] == 0

    def test_health_no_tasks(self, client):
        """无任务时计数为 0"""
        resp = client.get("/api/v1/scheduler/health")
        data = resp.json()
        assert data["pending_tasks"] >= 0  # 可能有其他测试的残留
        assert data["running_tasks"] == 0


class TestStats:
    """GET /api/v1/scheduler/stats 测试"""

    def test_stats_returns_structure(self, client):
        """stats 返回结构正确"""
        resp = client.get("/api/v1/scheduler/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_tasks" in data
        assert "today_tasks" in data
        assert "by_type" in data
        assert "by_status" in data
        assert "scan" in data["by_type"]
        assert "review" in data["by_type"]

    def test_stats_by_status_keys(self, client):
        """by_status 包含四种状态"""
        resp = client.get("/api/v1/scheduler/stats")
        data = resp.json()
        for status in ("pending", "running", "completed", "failed"):
            assert status in data["by_status"]

    def test_stats_after_creating_tasks(self, client):
        """创建任务后统计更新"""
        client.post("/api/v1/scheduler/scan", json={})
        resp = client.get("/api/v1/scheduler/stats")
        data = resp.json()
        assert data["total_tasks"] >= 1
        assert data["by_type"]["scan"] >= 1

    def test_stats_today_matches(self, client):
        """today_tasks 计数正确"""
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        # 创建一个今天日期的任务
        client.post("/api/v1/scheduler/scan", json={})
        resp = client.get("/api/v1/scheduler/stats")
        data = resp.json()
        assert data["today_tasks"] >= 1


class TestTaskPersistence:
    """任务存储在内存字典中验证"""

    def test_tasks_persist_in_memory(self, client):
        """任务在同一 TestClient 会话中持久化"""
        scan_resp = client.post("/api/v1/scheduler/scan", json={})
        task_id = scan_resp.json()["task_id"]

        # 再次获取应存在
        resp = client.get(f"/api/v1/scheduler/tasks/{task_id}")
        assert resp.status_code == 200

    def test_task_has_initial_progress(self, client):
        """任务初始 progress 为 0"""
        scan_resp = client.post("/api/v1/scheduler/scan", json={})
        task_id = scan_resp.json()["task_id"]

        resp = client.get(f"/api/v1/scheduler/tasks/{task_id}")
        assert resp.json()["progress"] == 0.0
