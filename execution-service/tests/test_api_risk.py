"""
风控API路由测试 — 覆盖 api/risk.py 全部端点

测试策略：
- 使用 dependency_overrides 注入 Mock DB 和 Mock 认证用户
- settings/circuit-breaker 端点无 DB 依赖，但需要绕过 auth
- check/monitor/events 端点需要 mock RiskController 或 mock DB
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.config

core.config.settings.ALLOW_OFF_HOURS_TRADING = True


# ─── 测试工具 ─────────────────────────────────────────────────────────


class MockRow:
    """模拟 SQLAlchemy 行对象"""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()


class MockResult:
    """模拟查询结果"""

    def __init__(self, rows=None, row=None, rowcount=0):
        self._rows = rows or []
        self._row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows
        return self._rows


def make_mock_db(account_data=None, position_data=None, events_data=None):
    """创建风控测试专用 Mock DB"""
    db = MagicMock()

    default_account = MockRow(
        {
            "total_assets": 1000000.0,
            "available_cash": 500000.0,
            "market_value": 200000.0,
            "day_profit_loss": None,
        }
    )

    def execute_side_effect(stmt, params=None):
        sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)

        # 账户查询（含 day_profit_loss）
        if "FROM accounts" in sql:
            if account_data:
                return MockResult(row=MockRow(account_data))
            return MockResult(row=default_account)

        # 单只持仓查询（WHERE ts_code）
        if "FROM positions" in sql and "WHERE" in sql and "ts_code" in sql:
            req_tc = params.get("tc") if params else None
            if position_data and req_tc == position_data.get("ts_code"):
                return MockResult(row=MockRow(position_data))
            return MockResult(row=None)

        # 批量持仓查询
        if "FROM positions" in sql:
            if position_data:
                return MockResult(rows=[MockRow(position_data)])
            return MockResult(rows=[])

        # 风险事件查询
        if "FROM risk_events" in sql:
            if events_data:
                return MockResult(rows=[MockRow(e) for e in events_data])
            return MockResult(rows=[])

        # 写操作
        if "INSERT" in sql or "UPDATE" in sql or "DELETE" in sql:
            return MockResult(rowcount=1)

        return MockResult()

    db.execute.side_effect = execute_side_effect
    db.commit = MagicMock()
    db.close = MagicMock()
    return db


# ─── Fixtures ─────────────────────────────────────────────────────────


DEFAULT_ACCOUNT = {
    "total_assets": 1000000.0,
    "available_cash": 500000.0,
    "market_value": 200000.0,
    "day_profit_loss": None,
}

DEFAULT_POSITION = {
    "ts_code": "000001.SZ",
    "total_quantity": 1000,
    "available_quantity": 1000,
    "market_value": 13500.0,
    "cost_price": 12.0,
    "current_price": 13.5,
}

DEFAULT_EVENT = {
    "event_type": "PRE_TRADE_CHECK",
    "severity": "MEDIUM",
    "ts_code": "000001.SZ",
    "description": "资金不足",
    "action_taken": "BLOCK",
    "threshold_value": None,
    "actual_value": None,
    "is_resolved": False,
    "created_at": "2026-06-14T15:00:00",
}


@pytest.fixture(scope="module")
def app():
    """获取 FastAPI 应用实例"""
    from main import app as _app

    return _app


@pytest.fixture
def mock_db():
    """返回标准 Mock DB"""
    return make_mock_db()


# ─── 通用 auth/db 覆盖 fixture ──────────────────────────────────────


@pytest.fixture
def client(app, mock_db):
    """TestClient with standard mock DB + auth bypass"""
    from models.database import get_db_session

    from shared.auth import get_current_user

    app.dependency_overrides[get_db_session] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-user",
        "username": "tester",
    }

    from fastapi.testclient import TestClient

    tc = TestClient(app)
    yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def auth_only_client(app):
    """仅绕过 auth（用于无 DB 依赖的端点）"""
    from shared.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-user",
        "username": "tester",
    }

    from fastapi.testclient import TestClient

    tc = TestClient(app)
    yield tc
    app.dependency_overrides.clear()


# ─── 带预置数据的 seeded_client 工厂 ────────────────────────────────


def _make_seeded_client(app, account_data=None, position_data=None, events_data=None):
    """创建带预置数据的测试客户端"""
    from models.database import get_db_session

    from shared.auth import get_current_user

    db = make_mock_db(account_data=account_data, position_data=position_data, events_data=events_data)
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-user",
        "username": "tester",
    }

    from fastapi.testclient import TestClient

    yield TestClient(app)
    app.dependency_overrides.clear()


# ====================================================================
#  GET /api/v1/risk/settings  — 风控参数
# ====================================================================


class TestRiskSettings:
    """风控参数端点测试（无 DB 依赖）"""

    @pytest.fixture
    def seeded_client(self, app):
        yield from _make_seeded_client(app)

    def test_settings_success(self, auth_only_client):
        """返回全部风控参数"""
        resp = auth_only_client.get("/api/v1/risk/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        params = data["data"]
        assert params["max_position_ratio"] == 0.30
        assert params["max_total_positions"] == 3
        assert params["stop_loss_ratio"] == 0.08
        assert params["take_profit_ratio"] == 0.30
        assert params["max_daily_loss"] == 0.05
        assert params["auto_execute_stop_loss"] is True
        assert params["auto_execute_take_profit"] is True
        assert params["order_expiry_days"] == 5
        assert "circuit_breaker" in params
        assert params["circuit_breaker"]["is_open"] is False


# ====================================================================
#  GET /api/v1/risk/circuit-breaker  — 熔断器状态
# ====================================================================


class TestCircuitBreaker:
    """熔断器状态端点测试"""

    def test_status(self, auth_only_client):
        """初始状态为 CLOSED"""
        resp = auth_only_client.get("/api/v1/risk/circuit-breaker")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        cb = data["data"]
        assert cb["is_open"] is False
        assert cb["consecutive_losses"] == 0
        assert cb["cooldown_remaining_minutes"] == 0


# ====================================================================
#  POST /api/v1/risk/circuit-breaker/reset  — 重置熔断器
# ====================================================================


class TestResetCircuitBreaker:
    """重置熔断器端点测试"""

    def test_reset(self, auth_only_client):
        """重置后状态恢复"""
        # 先触发熔断
        from services.risk_controller import circuit_breaker

        circuit_breaker._is_open = True
        circuit_breaker._consecutive_losses = 5
        import datetime
        circuit_breaker._opened_at = datetime.datetime.now()

        resp = auth_only_client.post("/api/v1/risk/circuit-breaker/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["message"] == "熔断器已重置"
        assert data["data"]["status"]["is_open"] is False
        assert data["data"]["status"]["consecutive_losses"] == 0

    def test_reset_from_closed(self, auth_only_client):
        """从闭合状态重置仍保持关闭"""
        from services.risk_controller import circuit_breaker

        circuit_breaker.reset()  # 确保初始状态

        resp = auth_only_client.post("/api/v1/risk/circuit-breaker/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["status"]["is_open"] is False


# ====================================================================
#  GET /api/v1/risk/check/{ts_code}  — 风控检查
# ====================================================================


class TestRiskCheck:
    """风控检查端点测试"""

    def test_check_buy_pass(self, client):
        """买入检查通过"""
        resp = client.get(
            "/api/v1/risk/check/000001.SZ",
            params={"action": "BUY", "quantity": 100, "price": 15.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["allowed"] is True
        assert data["data"]["risk_level"] == "LOW"

    def test_check_buy_insufficient_funds(self, client):
        """资金不足&仓位超标时返回风控阻断"""
        resp = client.get(
            "/api/v1/risk/check/000001.SZ",
            params={"action": "BUY", "quantity": 500000, "price": 10.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        # 500000*10 = 5,000,000 > 500,000 (available_cash) → 资金不足
        # 同时 5,000,000 / 1,000,000 = 500% > 30% → 仓位超标
        # 两条风险 → HIGH → allowed=False
        assert data["data"]["allowed"] is False
        assert len(data["data"]["risks"]) >= 2

    def test_check_sell_pass(self, client):
        """用预置持仓数据测试卖出检查通过"""
        from main import app as _app
        from models.database import get_db_session

        from shared.auth import get_current_user

        pos_data = {
            "ts_code": "600519.SH",
            "available_quantity": 500,
        }
        db = make_mock_db(position_data=pos_data)
        _app.dependency_overrides[get_db_session] = lambda: db
        _app.dependency_overrides[get_current_user] = lambda: {
            "id": "test-user",
            "username": "tester",
        }
        from fastapi.testclient import TestClient

        tc = TestClient(_app)
        resp = tc.get(
            "/api/v1/risk/check/600519.SH",
            params={"action": "SELL", "quantity": 200, "price": 14.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["allowed"] is True
        _app.dependency_overrides.clear()

    def test_check_sell_insufficient_position(self, client):
        """持仓不足时返回风控警告"""
        from main import app as _app
        from models.database import get_db_session

        from shared.auth import get_current_user

        pos_data = {
            "ts_code": "600519.SH",
            "available_quantity": 100,
        }
        db = make_mock_db(position_data=pos_data)
        _app.dependency_overrides[get_db_session] = lambda: db
        _app.dependency_overrides[get_current_user] = lambda: {
            "id": "test-user",
            "username": "tester",
        }
        from fastapi.testclient import TestClient

        tc = TestClient(_app)
        resp = tc.get(
            "/api/v1/risk/check/600519.SH",
            params={"action": "SELL", "quantity": 500, "price": 14.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]["risks"]) > 0
        assert "持仓不足" in data["data"]["risks"][0]
        _app.dependency_overrides.clear()

    def test_check_buy_position_ratio_exceeded(self, client):
        """仓位比例超标时返回警告"""
        account_data = {
            "total_assets": 100000.0,
            "available_cash": 50000.0,
            "market_value": 0.0,
            "day_profit_loss": None,
        }
        pos_data = {
            "ts_code": "000001.SZ",
            "total_quantity": 1000,
            "market_value": 35000.0,
            "cost_price": 12.0,
            "current_price": 13.5,
        }
        from main import app as _app
        from models.database import get_db_session

        from shared.auth import get_current_user

        db = make_mock_db(account_data=account_data, position_data=pos_data)
        _app.dependency_overrides[get_db_session] = lambda: db
        _app.dependency_overrides[get_current_user] = lambda: {
            "id": "test-user",
            "username": "tester",
        }
        from fastapi.testclient import TestClient

        tc = TestClient(_app)
        # 000001.SZ 已持仓 market_value=35000，再买 5000 股 @10.0 = 50000
        # total_market_value = 35000 + 50000 = 85000
        # ratio = 85000/100000 = 85% > 30% → 超标
        resp = tc.get(
            "/api/v1/risk/check/000001.SZ",
            params={"action": "BUY", "quantity": 5000, "price": 10.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]["risks"]) > 0
        assert any("仓位" in r for r in data["data"]["risks"])
        _app.dependency_overrides.clear()

    def test_check_position_limit_exceeded(self, client):
        """持仓数量超标时返回警告"""
        # 持仓超过 max_total_positions=3
        positions = [
            MockRow({"ts_code": "600519.SH", "total_quantity": 100, "market_value": 180000.0,
                      "cost_price": 1800.0, "current_price": 1800.0}),
            MockRow({"ts_code": "000001.SZ", "total_quantity": 500, "market_value": 6750.0,
                      "cost_price": 12.0, "current_price": 13.5}),
            MockRow({"ts_code": "601318.SH", "total_quantity": 200, "market_value": 90000.0,
                      "cost_price": 45.0, "current_price": 45.0}),
        ]

        mock_db = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        def execute_side(stmt, params=None):
            sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
            if "FROM accounts" in sql:
                return MockResult(row=MockRow(DEFAULT_ACCOUNT))
            if "FROM positions" in sql and "WHERE" in sql:
                return MockResult(row=None)  # 新股票，无持仓
            if "FROM positions" in sql:
                return MockResult(rows=positions)
            if "INSERT" in sql or "UPDATE" in sql or "DELETE" in sql:
                return MockResult(rowcount=1)
            return MockResult()

        mock_db.execute.side_effect = execute_side

        from main import app as _app
        from models.database import get_db_session

        from shared.auth import get_current_user

        _app.dependency_overrides[get_db_session] = lambda: mock_db
        _app.dependency_overrides[get_current_user] = lambda: {
            "id": "test-user",
            "username": "tester",
        }
        from fastapi.testclient import TestClient

        tc = TestClient(_app)
        # 买入新股票 300001.SZ（不在现有持仓中）
        resp = tc.get(
            "/api/v1/risk/check/300001.SZ",
            params={"action": "BUY", "quantity": 100, "price": 30.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert any("持仓数量" in r for r in data["data"]["risks"])
        _app.dependency_overrides.clear()

    def test_check_daily_loss_exceeded(self, client):
        """当日亏损超标时返回警告"""
        account_data = {
            "total_assets": 1000000.0,
            "available_cash": 500000.0,
            "market_value": 200000.0,
            "day_profit_loss": -100000.0,  # 亏损10%
        }
        from main import app as _app
        from models.database import get_db_session

        from shared.auth import get_current_user

        db = make_mock_db(account_data=account_data)
        _app.dependency_overrides[get_db_session] = lambda: db
        _app.dependency_overrides[get_current_user] = lambda: {
            "id": "test-user",
            "username": "tester",
        }
        from fastapi.testclient import TestClient

        tc = TestClient(_app)
        resp = tc.get(
            "/api/v1/risk/check/000001.SZ",
            params={"action": "BUY", "quantity": 100, "price": 15.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        # day_loss_ratio = 100000/1000000 = 10% > 5% → warning
        assert any("亏损" in r for r in data["data"]["risks"])
        _app.dependency_overrides.clear()


# ====================================================================
#  GET /api/v1/risk/monitor  — 监控
# ====================================================================


class TestRiskMonitor:
    """监控端点测试"""

    def test_monitor_no_positions(self, client):
        """无持仓时返回空结果"""
        resp = client.get("/api/v1/risk/monitor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["total_alerts"] == 0
        assert data["data"]["total_executed"] == 0
        assert data["data"]["alerts"] == []
        assert data["data"]["executed"] == []

    def test_monitor_internal_error(self, client):
        """内部异常返回 500"""
        from services.risk_controller import RiskController

        with patch.object(
            RiskController, "monitor_positions", side_effect=RuntimeError("fail")
        ):
            resp = client.get("/api/v1/risk/monitor")
            assert resp.status_code == 500


# ====================================================================
#  GET /api/v1/risk/events  — 风险事件列表
# ====================================================================


class TestRiskEvents:
    """风险事件列表端点测试"""

    def test_events_empty(self, client):
        """无事件时返回空列表"""
        resp = client.get("/api/v1/risk/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"] == []
        assert data["total"] == 0

    def test_events_with_data(self, client):
        """有事件时返回列表"""
        from main import app as _app
        from models.database import get_db_session

        from shared.auth import get_current_user

        db = make_mock_db(events_data=[DEFAULT_EVENT])
        _app.dependency_overrides[get_db_session] = lambda: db
        _app.dependency_overrides[get_current_user] = lambda: {
            "id": "test-user",
            "username": "tester",
        }
        from fastapi.testclient import TestClient

        tc = TestClient(_app)
        resp = tc.get("/api/v1/risk/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]) == 1
        assert data["total"] == 1
        assert data["data"][0]["event_type"] == "PRE_TRADE_CHECK"
        assert data["data"][0]["severity"] == "MEDIUM"
        _app.dependency_overrides.clear()

    def test_events_with_limit(self, client):
        """返回指定数量的事件"""
        from main import app as _app
        from models.database import get_db_session

        from shared.auth import get_current_user

        events = [dict(DEFAULT_EVENT, event_type=f"EVENT_{i}") for i in range(5)]
        db = make_mock_db(events_data=events)
        _app.dependency_overrides[get_db_session] = lambda: db
        _app.dependency_overrides[get_current_user] = lambda: {
            "id": "test-user",
            "username": "tester",
        }
        from fastapi.testclient import TestClient

        tc = TestClient(_app)
        resp = tc.get("/api/v1/risk/events", params={"limit": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["total"] == 5  # len(events)
        _app.dependency_overrides.clear()

    def test_events_internal_error(self, client, mock_db):
        """内部异常返回 500"""
        mock_db.execute.side_effect = RuntimeError("query failed")
        from main import app as _app
        from models.database import get_db_session

        def _broken_db():
            return mock_db

        _app.dependency_overrides[get_db_session] = _broken_db
        resp = client.get("/api/v1/risk/events")
        assert resp.status_code == 500
        _app.dependency_overrides[get_db_session] = lambda: mock_db
