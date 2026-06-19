"""
持仓管理API路由测试 — 覆盖 api/positions.py 全部端点

测试策略：
- 使用 dependency_overrides 注入 Mock DB 和 Mock 认证用户
- 主要路径：真实 PositionManager + Mock DB（集成验证）
- 异常路径：patch PositionManager 方法（精准控制）
"""
# ruff: noqa: S101 (assertions in tests)

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


def make_mock_db(account_data=None, position_data=None):
    """创建标准模拟 DB（兼容 orders 测试工具模式）"""
    db = MagicMock()

    default_account = MockRow(
        {
            "available_cash": 1000000.0,
            "total_assets": 1200000.0,
            "market_value": 200000.0,
            "day_profit_loss": None,
        }
    )

    def execute_side_effect(stmt, params=None):
        sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)

        if "FROM accounts" in sql:
            if account_data:
                return MockResult(row=MockRow(account_data))
            return MockResult(row=default_account)

        # 精确匹配：账号+ts_code 查询单个持仓
        # 注意：必须检查 params 中是否真的包含 "tc" 参数，
        # 因为列表查询的 SELECT 子句也包含 "ts_code" 字段名
        if "FROM positions" in sql and "WHERE" in sql and "ts_code" in sql:
            params_has_tc = params is not None and "tc" in params
            if not params_has_tc:
                pass  # 列表查询（SELECT 中包含 ts_code 字段），让下个分支处理
            else:
                req_tc = params.get("tc")
                if position_data and req_tc == position_data.get("ts_code"):
                    return MockResult(row=MockRow(position_data))
                return MockResult(row=None)

        # 宽松匹配：批量查询 positions 表
        if "FROM positions" in sql:
            if position_data:
                return MockResult(rows=[MockRow(position_data)])
            return MockResult(rows=[])

        # trades 表（已实现盈亏默认无数据）
        if "FROM trades" in sql:
            return MockResult(row=None)

        # 写操作
        if "INSERT" in sql or "UPDATE" in sql or "DELETE" in sql:
            return MockResult(rowcount=1)

        return MockResult()

    db.execute.side_effect = execute_side_effect
    db.commit = MagicMock()
    db.close = MagicMock()
    return db


# ─── Fixtures ─────────────────────────────────────────────────────────


DEFAULT_POSITION = {
    "ts_code": "000001.SZ",
    "direction": "LONG",
    "total_quantity": 500,
    "available_quantity": 500,
    "locked_quantity": 0,
    "cost_price": 12.0,
    "current_price": 13.5,
    "market_value": 6750.0,
    "profit_loss": 750.0,
    "profit_loss_ratio": 0.125,
    "days_held": 30,
    "stop_loss_price": 10.0,
    "take_profit_price": 15.0,
    "strategy_name": "MA_CROSS",
    "opened_at": "2026-05-15T09:30:00",
    "updated_at": "2026-06-14T15:00:00",
}

DEFAULT_SUMMARY_POSITION = {
    "ts_code": "000001.SZ",
    "total_quantity": 500,
    "cost_price": 12.0,
    "current_price": 13.5,
    "market_value": 6750.0,
    "profit_loss": 750.0,
    "profit_loss_ratio": 0.125,
}

CLOSEABLE_POSITION = {
    "ts_code": "000001.SZ",
    "total_quantity": 500,
    "available_quantity": 500,
    "cost_price": 12.0,
    "current_price": 13.5,
    "market_value": 6750.0,
}

UPDATABLE_POSITION = {
    "ts_code": "000001.SZ",
    "total_quantity": 500,
    "cost_price": 12.0,
    "current_price": 13.5,
    "market_value": 6750.0,
    "profit_loss": 750.0,
    "profit_loss_ratio": 0.125,
}


# ─── 通用 Fixtures ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app():
    """获取 FastAPI 应用实例（module-scoped）"""
    from main import app as _app

    return _app


@pytest.fixture
def mock_db():
    """返回标准 Mock DB 实例"""
    return make_mock_db()


@pytest.fixture
def override_deps(app, mock_db):
    """注入 Mock DB 和 Mock 认证到 FastAPI 依赖"""
    from models.database import get_db_session

    from shared.auth import get_current_user

    def _mock_db():
        return mock_db

    async def _mock_user():
        return {"id": "test-user", "username": "tester"}

    app.dependency_overrides[get_db_session] = _mock_db
    app.dependency_overrides[get_current_user] = _mock_user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(app, override_deps):
    """TestClient with dependency overrides applied"""
    from fastapi.testclient import TestClient

    return TestClient(app)


# ─── 带预置数据的 seeded_client 工厂 ────────────────────────────────


def _make_seeded_client(app, position_data=None):
    """创建带预置 position_data 的测试客户端"""
    from models.database import get_db_session

    from shared.auth import get_current_user

    db = make_mock_db(position_data=position_data)
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-user",
        "username": "tester",
    }
    from fastapi.testclient import TestClient

    yield TestClient(app)
    app.dependency_overrides.clear()


# ====================================================================
#  GET /api/v1/positions/  — 持仓列表
# ====================================================================


class TestListPositions:
    """持仓列表端点测试"""

    def test_list_success_empty(self, client):
        """无持仓时返回空列表"""
        resp = client.get("/api/v1/positions/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["total"] == 0
        assert data["data"] == []

    @pytest.fixture
    def seeded_client(self, app):
        yield from _make_seeded_client(app, position_data=DEFAULT_POSITION)

    def test_list_success_with_data(self, seeded_client):
        """有持仓时返回列表"""
        resp = seeded_client.get("/api/v1/positions/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["total"] == 1
        assert len(data["data"]) == 1
        assert data["data"][0]["ts_code"] == "000001.SZ"
        assert data["data"][0]["total_quantity"] == 500

    def test_list_internal_error(self, client):
        """内部异常返回 500"""
        from api.positions import PositionManager

        with patch.object(PositionManager, "get_positions", side_effect=RuntimeError("fail")):
            resp = client.get("/api/v1/positions/")
            assert resp.status_code == 500


# ====================================================================
#  GET /api/v1/positions/summary  — 持仓汇总
# ====================================================================


class TestPositionSummary:
    """持仓汇总端点测试"""

    def test_summary_empty(self, client):
        """无持仓时汇总为零"""
        resp = client.get("/api/v1/positions/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["position_count"] == 0
        assert data["data"]["total_market_value"] == 0
        assert data["data"]["total_cost"] == 0
        assert data["data"]["total_profit_loss"] == 0

    @pytest.fixture
    def seeded_client(self, app):
        yield from _make_seeded_client(app, position_data=DEFAULT_SUMMARY_POSITION)

    def test_summary_with_data(self, seeded_client):
        """有持仓时计算汇总值"""
        resp = seeded_client.get("/api/v1/positions/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["position_count"] == 1
        assert data["data"]["total_market_value"] == 6750.0
        # total_cost = cost_price * total_quantity = 12.0 * 500
        assert data["data"]["total_cost"] == 6000.0
        assert data["data"]["total_profit_loss"] == 750.0
        # pnl_ratio = (6750 - 6000) / 6000 = 0.125
        assert data["data"]["total_profit_loss_ratio"] == 0.125

    def test_summary_internal_error(self, client, mock_db):
        """内部异常返回 500"""
        mock_db.execute.side_effect = RuntimeError("query failed")
        from main import app as _app
        from models.database import get_db_session

        def _broken_db():
            return mock_db

        _app.dependency_overrides[get_db_session] = _broken_db
        resp = client.get("/api/v1/positions/summary")
        assert resp.status_code == 500
        _app.dependency_overrides[get_db_session] = lambda: mock_db


# ====================================================================
#  POST /api/v1/positions/close  — 平仓
# ====================================================================


class TestClosePosition:
    """平仓端点测试"""

    def test_close_position_not_found(self, client):
        """持仓不存在时返回 400"""
        resp = client.post(
            "/api/v1/positions/close",
            json={"ts_code": "999999.SZ", "quantity": 100, "price": 13.0},
        )
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "未找到" in detail

    @pytest.fixture
    def seeded_client(self, app):
        yield from _make_seeded_client(app, position_data=CLOSEABLE_POSITION)

    def test_close_success(self, seeded_client):
        """成功平仓"""
        resp = seeded_client.post(
            "/api/v1/positions/close",
            json={"ts_code": "000001.SZ", "quantity": 100, "price": 13.5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["success"] is True
        assert data["data"]["ts_code"] == "000001.SZ"
        assert data["data"]["quantity"] == 100
        assert data["data"]["price"] == 13.5
        assert "profit_loss" in data["data"]

    def test_close_insufficient_quantity(self, seeded_client):
        """请求数量超过可用持仓时返回 400"""
        resp = seeded_client.post(
            "/api/v1/positions/close",
            json={"ts_code": "000001.SZ", "quantity": 9999, "price": 13.5},
        )
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "可用持仓不足" in detail

    def test_close_internal_error(self, seeded_client):
        """内部异常返回 500"""
        from api.positions import PositionManager

        with patch.object(
            PositionManager,
            "close_position",
            side_effect=RuntimeError("fail"),
        ):
            resp = seeded_client.post(
                "/api/v1/positions/close",
                json={"ts_code": "000001.SZ", "quantity": 100, "price": 13.5},
            )
            assert resp.status_code == 500


# ====================================================================
#  POST /api/v1/positions/update-prices  — 批量更新持仓价格
# ====================================================================


class TestUpdatePrices:
    """批量更新价格端点测试"""

    @pytest.fixture
    def seeded_client(self, app):
        yield from _make_seeded_client(app, position_data=UPDATABLE_POSITION)

    def test_update_prices_success(self, seeded_client):
        """成功更新价格"""
        resp = seeded_client.post(
            "/api/v1/positions/update-prices",
            json={"price_map": {"000001.SZ": 14.0, "600519.SH": 1800.0}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["success"] is True
        # 000001.SZ 存在 → 更新; 600519.SH 不存在 → 跳过
        assert data["data"]["updated_count"] == 1

    def test_update_prices_internal_error(self, seeded_client):
        """内部异常返回 500"""
        from api.positions import PositionManager

        with patch.object(
            PositionManager,
            "update_position_prices",
            side_effect=RuntimeError("fail"),
        ):
            resp = seeded_client.post(
                "/api/v1/positions/update-prices",
                json={"price_map": {"000001.SZ": 14.0}},
            )
            assert resp.status_code == 500


# ====================================================================
#  GET /api/v1/positions/summary/pnl  — 已实现盈亏
# ====================================================================


class TestRealizedPnl:
    """已实现盈亏汇总端点测试"""

    def test_pnl_empty(self, client):
        """无成交时盈亏为零"""
        resp = client.get("/api/v1/positions/summary/pnl")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["total_trades"] == 0
        assert data["data"]["total_realized_pnl"] == 0
        assert data["data"]["win_rate"] == 0

    def test_pnl_with_trades(self, client):
        """有成交记录时返回汇总"""
        from api.positions import PositionManager

        with patch.object(
            PositionManager,
            "get_realized_pnl_summary",
            return_value={
                "total_trades": 5,
                "total_realized_pnl": 2500.0,
                "total_profit": 3500.0,
                "total_loss": -1000.0,
                "win_count": 3,
                "loss_count": 2,
                "win_rate": 0.6,
                "total_commission": 75.0,
                "total_tax": 25.0,
            },
        ):
            resp = client.get("/api/v1/positions/summary/pnl")
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == 0
            assert data["data"]["total_trades"] == 5
            assert data["data"]["total_realized_pnl"] == 2500.0
            assert data["data"]["win_count"] == 3
            assert data["data"]["loss_count"] == 2
            assert data["data"]["win_rate"] == 0.6
            assert data["data"]["total_commission"] == 75.0
            assert data["data"]["total_tax"] == 25.0

    def test_pnl_internal_error(self, client):
        """内部异常返回 500"""
        from api.positions import PositionManager

        with patch.object(
            PositionManager,
            "get_realized_pnl_summary",
            side_effect=RuntimeError("fail"),
        ):
            resp = client.get("/api/v1/positions/summary/pnl")
            assert resp.status_code == 500


# ====================================================================
#  GET /api/v1/positions/{ts_code}  — 单只持仓
# ====================================================================


class TestGetPosition:
    """单只持仓查询端点测试"""

    def test_get_position_not_found(self, client):
        """不存在的持仓返回 404"""
        resp = client.get("/api/v1/positions/999999.SZ")
        assert resp.status_code == 404

    @pytest.fixture
    def seeded_client(self, app):
        yield from _make_seeded_client(app, position_data=DEFAULT_POSITION)

    def test_get_position_found(self, seeded_client):
        """查询存在的持仓"""
        resp = seeded_client.get("/api/v1/positions/000001.SZ")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["ts_code"] == "000001.SZ"
        assert data["data"]["total_quantity"] == 500
        assert data["data"]["direction"] == "LONG"
        assert data["data"]["cost_price"] == 12.0
        assert data["data"]["profit_loss"] == 750.0

    def test_get_position_internal_error(self, client, mock_db):
        """内部异常返回 500"""
        mock_db.execute.side_effect = RuntimeError("query failed")
        from main import app as _app
        from models.database import get_db_session

        def _broken_db():
            return mock_db

        _app.dependency_overrides[get_db_session] = _broken_db
        resp = client.get("/api/v1/positions/000001.SZ")
        assert resp.status_code == 500
        _app.dependency_overrides[get_db_session] = lambda: mock_db
