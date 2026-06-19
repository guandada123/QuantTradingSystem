"""
交易记录API端点的单元测试

覆盖 api/trades.py 的端点：
- GET /api/v1/trades/
- GET /api/v1/trades/stats

使用 FastAPI TestClient + dependency overrides 模拟数据库会话和认证。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from main import app
from models.database import get_db
import pytest

from shared.auth import get_current_user


@pytest.fixture
def mock_db():
    """创建模拟数据库会话"""
    return MagicMock()


@pytest.fixture
def client(mock_db):
    """创建 TestClient 并覆盖 FastAPI 依赖项"""
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: {"id": "dev-user"}
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def _make_trade_mock(**kwargs):
    """辅助创建模拟 Trade"""
    t = MagicMock()
    for k, v in kwargs.items():
        setattr(t, k, v)
    return t


def _setup_trade_and_stock_queries(mock_db, trade_list, stock_list=None):
    """
    使用 side_effect 区分 Trade 和 StockPool 的查询链，
    避免 MagicMock 链自动冲突。
    """
    if stock_list is None:
        stock_list = []

    trade_q = MagicMock()
    trade_filter = MagicMock()
    # 模拟 query(Trade).filter(account_id=X).order_by(...).offset(...).limit(...).all()
    # 支持 direction 过滤链：query.filter(account_id).filter(direction).order_by(...)
    direction_filter = MagicMock()
    direction_filter.order_by.return_value.offset.return_value.limit.return_value.all.return_value = trade_list
    trade_filter.filter.return_value = direction_filter
    # 无 direction 时：query.filter(account_id).order_by(...)
    trade_filter.order_by.return_value.offset.return_value.limit.return_value.all.return_value = trade_list
    trade_q.filter.return_value = trade_filter

    stock_q = MagicMock()
    stock_q.filter.return_value.all.return_value = stock_list

    def query_side_effect(model_cls):
        if model_cls.__name__ == "Trade":
            return trade_q
        return stock_q

    mock_db.query.side_effect = query_side_effect


# =========================================================================
# GET /api/v1/trades/ - 交易记录列表
# =========================================================================


class TestGetTrades:
    """GET /api/v1/trades/"""

    def test_list_trades_default(self, client, mock_db):
        """默认参数返回交易列表"""
        t = _make_trade_mock(
            trade_id="T001", ts_code="600519.SH", direction="BUY",
            price=180.0, quantity=100, amount=18000.0,
            profit_loss=None, commission=5.0,
            trade_date=date(2026, 6, 10), trade_time="09:30:00",
            created_at=datetime(2026, 6, 10, 9, 30, 0),
        )
        _setup_trade_and_stock_queries(mock_db, [t])

        resp = client.get("/api/v1/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["data"][0]["trade_id"] == "T001"
        assert data["data"][0]["direction"] == "BUY"
        assert data["data"][0]["price"] == 180.0
        assert data["data"][0]["quantity"] == 100

    def test_list_trades_empty(self, client, mock_db):
        """无交易记录时返回空列表"""
        _setup_trade_and_stock_queries(mock_db, [])

        resp = client.get("/api/v1/trades")
        data = resp.json()
        assert data["data"] == []

    def test_list_trades_limit_and_offset(self, client, mock_db):
        """limit 和 offset 参数传递给查询"""
        t = _make_trade_mock(
            trade_id="T002", ts_code="000001.SZ", direction="SELL",
            price=12.5, quantity=200, amount=2500.0,
            profit_loss=100.0, commission=2.5,
            trade_date=date(2026, 6, 11), trade_time="10:00:00",
            created_at=datetime(2026, 6, 11, 10, 0, 0),
        )
        _setup_trade_and_stock_queries(mock_db, [t])

        resp = client.get("/api/v1/trades?limit=5&offset=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 1

    def test_list_trades_filter_direction_buy(self, client, mock_db):
        """direction=BUY 过滤买入交易"""
        t = _make_trade_mock(
            trade_id="T003", ts_code="600519.SH", direction="BUY",
            price=181.0, quantity=50, amount=9050.0,
            profit_loss=None, commission=2.5,
            trade_date=date(2026, 6, 12), trade_time="09:35:00",
            created_at=datetime(2026, 6, 12, 9, 35, 0),
        )
        _setup_trade_and_stock_queries(mock_db, [t])

        resp = client.get("/api/v1/trades?direction=BUY")
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["direction"] == "BUY" for t in data["data"])

    def test_list_trades_filter_direction_sell(self, client, mock_db):
        """direction=SELL 过滤卖出交易"""
        t = _make_trade_mock(
            trade_id="T004", ts_code="000001.SZ", direction="SELL",
            price=13.0, quantity=100, amount=1300.0,
            profit_loss=50.0, commission=1.3,
            trade_date=date(2026, 6, 12), trade_time="10:05:00",
            created_at=datetime(2026, 6, 12, 10, 5, 0),
        )
        _setup_trade_and_stock_queries(mock_db, [t])

        resp = client.get("/api/v1/trades?direction=SELL")
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["direction"] == "SELL" for t in data["data"])

    def test_list_trades_no_profit_loss(self, client, mock_db):
        """利润为 None 的交易也被正确处理"""
        t = _make_trade_mock(
            trade_id="T005", ts_code="600519.SH", direction="BUY",
            price=182.0, quantity=100, amount=18200.0,
            profit_loss=None, commission=5.0,
            trade_date=date(2026, 6, 13), trade_time="09:30:00",
            created_at=datetime(2026, 6, 13, 9, 30, 0),
        )
        _setup_trade_and_stock_queries(mock_db, [t])

        resp = client.get("/api/v1/trades")
        data = resp.json()
        assert data["data"][0]["profit_loss"] is None

    def test_list_trades_with_stock_names(self, client, mock_db):
        """关联股票名称被正确填充"""
        t = _make_trade_mock(
            trade_id="T006", ts_code="600519.SH", direction="BUY",
            price=180.0, quantity=100, amount=18000.0,
            profit_loss=None, commission=5.0,
            trade_date=date(2026, 6, 10), trade_time="09:30:00",
            created_at=datetime(2026, 6, 10, 9, 30, 0),
        )
        mock_stock = MagicMock()
        mock_stock.ts_code = "600519.SH"
        mock_stock.name = "贵州茅台"
        _setup_trade_and_stock_queries(mock_db, [t], stock_list=[mock_stock])

        resp = client.get("/api/v1/trades")
        data = resp.json()
        assert data["data"][0]["name"] == "贵州茅台"


# =========================================================================
# GET /api/v1/trades/stats - 交易统计
# =========================================================================


def _setup_trade_stats_queries(mock_db, sell_trades_result, total_count=0, other_q_count=0):
    """
    为 get_trade_stats 设置 mock 查询链。

    get_trade_stats 内部做了两次 db.query(Trade)：
      1) db.query(Trade).filter(account_id, direction_in, profit_loss_isnot_None).all()
         — 单次 filter() 调用，3个参数
      2) db.query(Trade).filter(account_id).count()
    """
    trade_q = MagicMock()

    # 第一次 query：.filter(arg1, arg2, arg3).all()
    # 第二次 query：.filter(arg).count()
    filter_result = MagicMock()
    filter_result.all.return_value = sell_trades_result
    filter_result.count.return_value = total_count
    trade_q.filter.return_value = filter_result

    def query_side_effect(model_cls):
        if model_cls.__name__ == "Trade":
            return trade_q
        q = MagicMock()
        q.count.return_value = other_q_count
        return q

    mock_db.query.side_effect = query_side_effect


class TestTradeStats:
    """GET /api/v1/trades/stats"""

    def test_stats_with_wins_and_losses(self, client, mock_db):
        """有盈利和亏损交易时返回完整统计"""
        win1 = MagicMock()
        win1.profit_loss = 500.0
        win1.direction = "SELL"
        win1.account_id = "REAL_001"
        loss1 = MagicMock()
        loss1.profit_loss = -200.0
        loss1.direction = "SELL"
        loss1.account_id = "REAL_001"
        win2 = MagicMock()
        win2.profit_loss = 300.0
        win2.direction = "SELL"
        win2.account_id = "REAL_001"

        _setup_trade_stats_queries(mock_db, [win1, loss1, win2], total_count=3)

        resp = client.get("/api/v1/trades/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["total_trades"] == 3
        assert data["data"]["win_rate"] == pytest.approx(66.7, rel=0.1)

    def test_stats_no_sell_trades(self, client, mock_db):
        """无卖出交易（仅买入）时返回零统计"""
        _setup_trade_stats_queries(mock_db, [], total_count=5)

        resp = client.get("/api/v1/trades/stats")
        data = resp.json()
        assert data["data"]["total_trades"] == 5
        assert data["data"]["win_rate"] == 0
        assert data["data"]["profit_loss_ratio"] == 0

    def test_stats_all_wins(self, client, mock_db):
        """全部盈利时 win_rate=100"""
        win = MagicMock()
        win.profit_loss = 100.0
        win.direction = "SELL"
        win.account_id = "REAL_001"
        win2 = MagicMock()
        win2.profit_loss = 200.0
        win2.direction = "SELL"
        win2.account_id = "REAL_001"

        _setup_trade_stats_queries(mock_db, [win, win2], total_count=5)

        resp = client.get("/api/v1/trades/stats")
        data = resp.json()
        assert data["data"]["win_rate"] == 100.0
        assert data["data"]["avg_loss"] == 0

    def test_stats_all_losses(self, client, mock_db):
        """全部亏损时 win_rate=0"""
        loss = MagicMock()
        loss.profit_loss = -150.0
        loss.direction = "SELL"
        loss.account_id = "REAL_001"

        _setup_trade_stats_queries(mock_db, [loss], total_count=3)

        resp = client.get("/api/v1/trades/stats")
        data = resp.json()
        assert data["data"]["win_rate"] == 0.0
