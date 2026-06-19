"""
告警管理API端点的单元测试

覆盖 api/alerts.py 的端点：
- GET /api/v1/alerts/
- GET /api/v1/alerts/rules
- POST /api/v1/alerts/rules
- GET /api/v1/alerts/stats

注意：alerts 端点直接在函数体内调用 get_db_session()（非 FastAPI DI），
因此使用 @patch 在模块导入时模拟。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from main import app
from models.database import get_db
import pytest

from shared.auth import get_current_user


@pytest.fixture
def client():
    """创建 TestClient"""
    app.dependency_overrides[get_current_user] = lambda: {"id": "dev-user"}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


# =========================================================================
# GET /api/v1/alerts - 获取告警列表
# =========================================================================


class TestListAlerts:
    """GET /api/v1/alerts"""

    @patch("api.alerts.get_db_session")
    def test_list_alerts_with_data(self, mock_get_db, client):
        """数据库有告警记录时返回列表"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db

        row1 = ("1", "600519.SH", "price_drop", "warning", "茅台跌超3%", "2026-06-13 10:00:00", "active")
        row2 = ("2", "000001.SZ", "volume_spike", "critical", "平安银行放量", "2026-06-13 09:30:00", "active")
        mock_db.execute.return_value.fetchall.return_value = [row1, row2]

        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 2
        assert data["total"] == 2
        assert data["data"][0]["ts_code"] == "600519.SH"
        assert data["data"][1]["alert_type"] == "volume_spike"

    @patch("api.alerts.get_db_session")
    def test_list_alerts_empty(self, mock_get_db, client):
        """数据库无告警时返回空列表"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = []

        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"] == []
        assert data["total"] == 0

    @patch("api.alerts.get_db_session")
    def test_list_alerts_with_level_filter(self, mock_get_db, client):
        """level 过滤参数传递给 SQL 查询"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = []

        resp = client.get("/api/v1/alerts?level=critical")
        assert resp.status_code == 200
        # 验证 SQL 中包含了 level 条件
        sql = mock_db.execute.call_args[0][0]
        assert "level='critical'" in sql

    @patch("api.alerts.get_db_session")
    def test_list_alerts_with_status_filter(self, mock_get_db, client):
        """status 过滤参数"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = []

        resp = client.get("/api/v1/alerts?status=active")
        assert resp.status_code == 200
        sql = mock_db.execute.call_args[0][0]
        assert "status='active'" in sql

    @patch("api.alerts.get_db_session")
    def test_list_alerts_with_all_filters(self, mock_get_db, client):
        """同时使用 level 和 status 过滤"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = []

        resp = client.get("/api/v1/alerts?level=warning&status=resolved")
        assert resp.status_code == 200
        sql = mock_db.execute.call_args[0][0]
        assert "level='warning'" in sql
        assert "status='resolved'" in sql

    @patch("api.alerts.get_db_session")
    def test_list_alerts_limit_validation(self, mock_get_db, client):
        """limit 参数被控制在 1-200 范围内"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = []

        # 超出上限应被截断
        resp = client.get("/api/v1/alerts?limit=999")
        assert resp.status_code == 422  # FastAPI 校验失败

    @patch("api.alerts.get_db_session")
    def test_list_alerts_limit_zero(self, mock_get_db, client):
        """limit 为 0 应被拒绝"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = []

        resp = client.get("/api/v1/alerts?limit=0")
        assert resp.status_code == 422

    @patch("api.alerts.get_db_session")
    def test_list_alerts_db_exception(self, mock_get_db, client):
        """数据库查询异常时降级返回空列表"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.side_effect = Exception("table not found")

        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"] == []
        assert data["total"] == 0
        assert "暂无告警记录" in data["message"]


# =========================================================================
# GET /api/v1/alerts/rules - 获取告警规则
# =========================================================================


class TestListRules:
    """GET /api/v1/alerts/rules"""

    def test_list_rules_db_unavailable_returns_defaults(self, client):
        """数据库不可用时返回默认告警规则"""
        resp = client.get("/api/v1/alerts/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 4
        names = [r["name"] for r in data["data"]]
        assert "单日亏损超5%" in names
        assert "最大回撤超15%" in names
        assert "持仓集中度超50%" in names
        assert "连续亏损3次" in names

    @patch("api.alerts.get_db_session")
    def test_list_rules_from_db(self, mock_get_db, client):
        """数据库有规则时优先从数据库读取"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        row = (10, "自定义规则", "day_pnl_ratio < -0.03", 0.03, "warning", True)
        mock_db.execute.return_value.fetchall.return_value = [row]

        resp = client.get("/api/v1/alerts/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"][0]["name"] == "自定义规则"
        assert data["data"][0]["threshold"] == 0.03


# =========================================================================
# POST /api/v1/alerts/rules - 创建告警规则
# =========================================================================


class TestCreateRule:
    """POST /api/v1/alerts/rules"""

    def test_create_rule_success(self, client):
        """传入有效参数创建规则"""
        payload = {
            "name": "测试规则",
            "condition": "day_pnl_ratio < -0.02",
            "threshold": 0.02,
            "level": "warning",
            "enabled": True,
        }
        resp = client.post("/api/v1/alerts/rules", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["name"] == "测试规则"
        assert data["data"]["condition"] == "day_pnl_ratio < -0.02"
        assert data["data"]["level"] == "warning"
        assert data["data"]["enabled"] is True
        assert data["data"]["id"] == 999
        assert "规则已创建" in data["message"]

    def test_create_rule_with_defaults(self, client):
        """不传可选字段时使用默认值"""
        payload = {
            "name": "最小规则",
            "condition": "price > 100",
            "threshold": 100.0,
        }
        resp = client.post("/api/v1/alerts/rules", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["level"] == "warning"  # 默认值
        assert data["data"]["enabled"] is True  # 默认值

    def test_create_rule_missing_required(self, client):
        """缺少必填字段时返回 422"""
        resp = client.post("/api/v1/alerts/rules", json={"name": "incomplete"})
        assert resp.status_code == 422

    def test_create_rule_invalid_level(self, client):
        """传入非法 level（不影响，因 Pydantic 无校验，但可额外约束）"""
        payload = {
            "name": "奇怪的级别",
            "condition": "x > 1",
            "threshold": 1.0,
            "level": "unknown",
            "enabled": True,
        }
        resp = client.post("/api/v1/alerts/rules", json=payload)
        assert resp.status_code == 200  # Pydantic 不限制 level 的枚举值


# =========================================================================
# GET /api/v1/alerts/stats - 告警统计
# =========================================================================


class TestAlertStats:
    """GET /api/v1/alerts/stats"""

    @patch("api.alerts.get_db_session")
    def test_stats_with_data(self, mock_get_db, client):
        """数据库有告警时返回统计数据"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = (25, 5, 15, 5)

        resp = client.get("/api/v1/alerts/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["total"] == 25
        assert data["data"]["critical"] == 5
        assert data["data"]["warning"] == 15
        assert data["data"]["info"] == 5

    @patch("api.alerts.get_db_session")
    def test_stats_empty(self, mock_get_db, client):
        """无告警时返回全零统计"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = (0, None, None, None)

        resp = client.get("/api/v1/alerts/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 0
        assert data["data"]["critical"] == 0
        assert data["data"]["warning"] == 0
        assert data["data"]["info"] == 0

    @patch("api.alerts.get_db_session")
    def test_stats_db_exception(self, mock_get_db, client):
        """数据库异常时降级返回全零统计"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_get_db.return_value = mock_db
        mock_db.execute.side_effect = Exception("no such table")

        resp = client.get("/api/v1/alerts/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 0
        assert data["data"]["critical"] == 0
        assert data["data"]["warning"] == 0
        assert data["data"]["info"] == 0
