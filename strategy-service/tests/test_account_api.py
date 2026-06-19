"""
账户API端点的单元测试

覆盖 api/account.py 的4个端点：
- GET /api/v1/account/summary
- GET /api/v1/account/
- GET /api/v1/account/daily-values
- GET /api/v1/account/positions

使用 FastAPI TestClient + dependency overrides 模拟数据库会话和认证。
"""

from datetime import date, timedelta
import os
import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# 路径引导：让测试能找到 service 根目录
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
    # 清理覆盖
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


class TestAccountSummary:
    """GET /api/v1/account/summary"""

    def test_summary_success(self, client, mock_db):
        """账户存在时返回完整概要"""
        mock_account = MagicMock()
        mock_account.total_assets = 150000.00
        mock_account.available_cash = 50000.00
        mock_account.market_value = 100000.00
        mock_account.total_profit_loss = 5000.00
        mock_account.total_profit_loss_ratio = 0.0345
        mock_account.currency = "CNY"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_account

        resp = client.get("/api/v1/account/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["total_assets"] == 150000.00
        assert data["data"]["available_cash"] == 50000.00
        assert data["data"]["market_value"] == 100000.00
        assert data["data"]["total_profit_loss"] == 5000.00
        assert data["data"]["total_profit_loss_ratio"] == 0.0345
        assert data["data"]["currency"] == "CNY"

    def test_summary_account_not_found(self, client, mock_db):
        """账户不存在时返回 success=False"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = client.get("/api/v1/account/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["message"] == "账户不存在"

    def test_summary_none_values_handled(self, client, mock_db):
        """各数字字段为 None 时默认返回 0"""
        mock_account = MagicMock()
        mock_account.total_assets = None
        mock_account.available_cash = None
        mock_account.market_value = None
        mock_account.total_profit_loss = None
        mock_account.total_profit_loss_ratio = None
        mock_account.currency = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_account

        resp = client.get("/api/v1/account/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["total_assets"] == 0.0
        assert data["data"]["available_cash"] == 0.0
        assert data["data"]["total_profit_loss_ratio"] == 0.0
        assert data["data"]["currency"] == "CNY"


class TestAccountDetail:
    """GET /api/v1/account"""

    def test_detail_success(self, client, mock_db):
        """账户存在时返回含持仓数的详细信息"""
        mock_account = MagicMock()
        mock_account.total_assets = 200000.00
        mock_account.available_cash = 80000.00
        mock_account.market_value = 120000.00
        mock_account.total_profit_loss = 10000.00
        mock_account.total_profit_loss_ratio = 0.0527
        mock_account.currency = "CNY"
        # 对于 get_account_detail: query(Account).filter(...).first() 和 query(Position).filter(...).filter(...).count()
        # 使用 side_effect 来区分 Account 和 Position 的查询链
        account_filter = MagicMock()
        account_filter.first.return_value = mock_account
        position_filter = MagicMock()
        # get_account_detail: db.query(Position).filter(...).count() — 单次 filter
        position_filter.count.return_value = 3

        def query_side_effect(model_cls):
            if model_cls.__name__ == "Account":
                q = MagicMock()
                q.filter.return_value = account_filter
                return q
            elif model_cls.__name__ == "Position":
                q = MagicMock()
                q.filter.return_value = position_filter
                return q
            return MagicMock()

        mock_db.query.side_effect = query_side_effect

        resp = client.get("/api/v1/account")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["positions"] == 3
        assert data["data"]["total_assets"] == 200000.00
        assert data["data"]["days_active"] == 12
        assert data["data"]["daily_return"] == 0.0042

    def test_detail_account_not_found(self, client, mock_db):
        """账户不存在时返回 success=False"""
        account_q = MagicMock()
        account_q.filter.return_value.first.return_value = None

        def query_side_effect(model_cls):
            if model_cls.__name__ == "Account":
                return account_q
            return MagicMock()

        mock_db.query.side_effect = query_side_effect

        resp = client.get("/api/v1/account")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["message"] == "账户不存在"


class TestDailyValues:
    """GET /api/v1/account/daily-values"""

    def test_daily_values_with_trades(self, client, mock_db):
        """有交易记录时返回完整的净值曲线"""
        mock_account = MagicMock()
        mock_account.total_assets = 35000.00
        mock_db.query.return_value.filter.return_value.first.return_value = mock_account

        # 模拟两笔交易
        t1 = MagicMock()
        t1.trade_date = date.today() - timedelta(days=5)
        t1.profit_loss = 1000.00

        t2 = MagicMock()
        t2.trade_date = date.today() - timedelta(days=2)
        t2.profit_loss = -500.00

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [t1, t2]

        resp = client.get("/api/v1/account/daily-values")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        # 应包含从最早交易日-30天到今天的所有日期
        assert len(data["data"]) >= 35

    def test_daily_values_no_trades(self, client, mock_db):
        """无交易记录时返回最近31天的平坦净值线"""
        mock_account = MagicMock()
        mock_account.total_assets = 30000.00
        mock_db.query.return_value.filter.return_value.first.return_value = mock_account
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        resp = client.get("/api/v1/account/daily-values")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 31  # 30天前到今天，共31个点
        assert data["data"][0]["value"] == 30000.0

    def test_daily_values_account_no_assets(self, client, mock_db):
        """账户资产为 None 时使用默认值 30000"""
        mock_account = MagicMock()
        mock_account.total_assets = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_account
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        resp = client.get("/api/v1/account/daily-values")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"][0]["value"] == 30000.0

    def test_daily_values_account_not_found(self, client, mock_db):
        """账户记录不存在时使用默认资金 30000"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        resp = client.get("/api/v1/account/daily-values")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 31
        assert data["data"][0]["value"] == 30000.0


class TestPositions:
    """GET /api/v1/account/positions"""

    def test_positions_list(self, client, mock_db):
        """返回持仓列表"""
        mock_position = MagicMock()
        mock_position.ts_code = "600519.SH"
        mock_position.total_quantity = 100
        mock_position.available_quantity = 100
        mock_position.cost_price = 180.0
        mock_position.current_price = 185.5
        mock_position.profit_loss = 550.0
        mock_position.profit_loss_ratio = 0.0306
        mock_position.market_value = 18550.0
        mock_position.days_held = 10
        mock_position.stop_loss_price = 170.0
        mock_position.take_profit_price = 200.0

        # 使用 side_effect 区分 Position 和 StockPool 查询
        # get_positions: db.query(Position).filter(...).all() — 单次 filter
        position_q = MagicMock()
        position_q.filter.return_value.all.return_value = [mock_position]
        stock_q = MagicMock()
        stock_q.filter.return_value.all.return_value = []

        def query_side_effect(model_cls):
            if model_cls.__name__ == "Position":
                return position_q
            return stock_q

        mock_db.query.side_effect = query_side_effect

        resp = client.get("/api/v1/account/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["data"][0]["ts_code"] == "600519.SH"
        assert data["data"][0]["quantity"] == 100

    def test_positions_empty(self, client, mock_db):
        """无持仓时返回空列表"""
        mock_filter = mock_db.query.return_value.filter.return_value
        mock_filter.all.return_value = []

        resp = client.get("/api/v1/account/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"] == []

    def test_positions_filter_by_ts_code(self, client, mock_db):
        """ts_code 过滤参数生效"""
        mock_position = MagicMock()
        mock_position.ts_code = "000001.SZ"
        mock_position.total_quantity = 500
        mock_position.available_quantity = 200
        mock_position.cost_price = 12.0
        mock_position.current_price = 12.5
        mock_position.profit_loss = 250.0
        mock_position.profit_loss_ratio = 0.0417
        mock_position.market_value = 6250.0
        mock_position.days_held = 5
        mock_position.stop_loss_price = 11.0
        mock_position.take_profit_price = 14.0

        mock_stock = MagicMock()
        mock_stock.ts_code = "000001.SZ"
        mock_stock.name = "平安银行"

        position_q = MagicMock()
        position_q.filter.return_value.filter.return_value.all.return_value = [mock_position]
        stock_q = MagicMock()
        stock_q.filter.return_value.all.return_value = [mock_stock]

        def query_side_effect(model_cls):
            if model_cls.__name__ == "Position":
                return position_q
            return stock_q

        mock_db.query.side_effect = query_side_effect

        resp = client.get("/api/v1/account/positions?ts_code=000001.SZ")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"][0]["name"] == "平安银行"
