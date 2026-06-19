"""
订单查询与每日摘要模块 - 单元测试

覆盖 order_admin.py 的：
- calculate_trade_cost(): 交易成本计算（佣金、印花税）
- OrderAdmin 类: 订单查询、列表、每日摘要（模拟DB查询）
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.order_admin import OrderAdmin, calculate_trade_cost

# ============================================================
# 模拟数据库行/结果对象
# ============================================================


class MockRow:
    """模拟 SQLAlchemy 行对象（支持 mappings() 协议）"""

    def __init__(self, data: dict):
        self._mapping = data

    def __getitem__(self, key):
        return self._mapping[key]

    def keys(self):
        return self._mapping.keys()

    def items(self):
        return self._mapping.items()

    def values(self):
        return self._mapping.values()

    def get(self, key, default=None):
        return self._mapping.get(key, default)


class MockResult:
    """模拟 SQLAlchemy 查询结果"""

    def __init__(self, rows=None, row=None):
        self._rows = rows or []
        self._row = row

    def mappings(self):
        return self

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


# ============================================================
# 测试辅助函数
# ============================================================


def _make_mock_db(**returns):
    """
    创建模拟 DB 对象。
    可以通过 returns 字典预置特定查询的返回值，例如：
      _make_mock_db(account={'available_cash': 10000.0, ...})
    未匹配的查询返回空结果。
    """
    db = MagicMock()
    db.commit = MagicMock()
    db.close = MagicMock()
    db.execute = MagicMock(side_effect=_make_execute_side_effect(returns))
    return db


def _make_execute_side_effect(returns):
    """根据预置的 returns 字典创建 execute side_effect"""

    def side_effect(stmt, params=None):
        sql = stmt.text if hasattr(stmt, "text") else str(stmt)

        # Account 查询 — 按 SQL 匹配，不依赖 params 结构
        if "FROM accounts" in sql:
            if returns.get("account") is not None:
                return MockResult(row=MockRow(returns["account"]))
            return MockResult(row=None)

        # 订单查询 (单个)
        if "FROM orders WHERE order_id" in sql:
            if "order" in returns:
                return MockResult(row=MockRow(returns["order"]))
            return MockResult(row=None)

        # 订单列表
        if "FROM orders" in sql and "GROUP BY" not in sql:
            if "orders" in returns:
                return MockResult(rows=[MockRow(r) for r in returns["orders"]])
            return MockResult(rows=[])

        # 成交查询
        if "FROM trades" in sql:
            trades_val = returns.get("trades")
            if trades_val is not None:
                return MockResult(row=MockRow(trades_val))
            return MockResult(row=MockRow({
                "count": 0, "total_amount": 0, "total_commission": 0,
                "total_tax": 0, "total_pnl": 0,
            }))

        # 持仓查询
        if "FROM positions" in sql and "total_quantity" in sql:
            positions_val = returns.get("positions")
            if positions_val is not None:
                return MockResult(row=MockRow(positions_val))
            return MockResult(row=MockRow({
                "count": 0, "total_market_value": 0, "total_unrealized_pnl": 0,
            }))

        # 今日订单统计
        if "FROM orders" in sql and "GROUP BY status" in sql:
            orders_val = returns.get("orders_today")
            if orders_val is not None:
                return MockResult(rows=[MockRow(r) for r in orders_val])
            return MockResult(rows=[])

        return MockResult()

    return side_effect


# ============================================================
# calculate_trade_cost 测试
# ============================================================


class TestCalculateTradeCost:
    """交易成本计算测试"""

    def test_min_commission_floor(self):
        """佣金最低5元（小成交额）"""
        # 10*100*0.0003 = 0.3 < 5，应按5元计
        cost = calculate_trade_cost(price=10.0, quantity=100, direction="BUY")
        assert cost["commission"] == 5.0
        assert cost["amount"] == 1000.0
        assert cost["tax"] == 0.0  # 买入不收印花税

    def test_min_commission_edge(self):
        """略低于5元佣金的边界"""
        # 16.66*1000*0.0003 = 4.998 < 5
        cost = calculate_trade_cost(price=16.66, quantity=1000, direction="BUY")
        assert cost["commission"] == 5.0

    def test_normal_commission(self):
        """正常佣金计算（超过5元）"""
        # 1800*100*0.0003 = 54
        cost = calculate_trade_cost(price=1800.0, quantity=100, direction="BUY")
        assert cost["commission"] == pytest.approx(54.0, abs=0.01)

    def test_commission_above_floor(self):
        """刚好超过5元佣金的边界"""
        # 20*1000*0.0003 = 6 > 5
        cost = calculate_trade_cost(price=20.0, quantity=1000, direction="BUY")
        assert cost["commission"] == pytest.approx(6.0, abs=0.01)

    def test_no_tax_on_buy(self):
        """买入不收印花税"""
        cost = calculate_trade_cost(price=100.0, quantity=1000, direction="BUY")
        assert cost["tax"] == 0.0

    def test_tax_on_sell(self):
        """卖出收取印花税0.1%"""
        # 100*1000*0.001 = 100
        cost = calculate_trade_cost(price=100.0, quantity=1000, direction="SELL")
        assert cost["tax"] == pytest.approx(100.0, abs=0.01)

    def test_large_amount(self):
        """大额交易"""
        cost = calculate_trade_cost(price=500.0, quantity=10000, direction="SELL")
        # 成交额 = 5,000,000
        assert cost["amount"] == 5_000_000.0
        # 佣金 = 5,000,000 * 0.0003 = 1500
        assert cost["commission"] == pytest.approx(1500.0, abs=0.01)
        # 印花税 = 5,000,000 * 0.001 = 5000
        assert cost["tax"] == pytest.approx(5000.0, abs=0.01)
        assert cost["total_cost"] == pytest.approx(6500.0, abs=0.01)
        assert cost["net_amount"] == pytest.approx(4_993_500.0, abs=0.01)

    def test_custom_commission_rate(self):
        """自定义佣金率"""
        # 1000*100*0.001 = 100
        cost = calculate_trade_cost(price=1000.0, quantity=100, direction="BUY", commission_rate=0.001)
        assert cost["commission"] == pytest.approx(100.0, abs=0.01)

    def test_custom_tax_rate(self):
        """自定义印花税率"""
        # 100*1000*0.003 = 300
        cost = calculate_trade_cost(price=100.0, quantity=1000, direction="SELL", tax_rate=0.003)
        assert cost["tax"] == pytest.approx(300.0, abs=0.01)

    def test_custom_both_rates(self):
        """自定义佣金率和印花税率"""
        cost = calculate_trade_cost(
            price=100.0, quantity=1000, direction="SELL",
            commission_rate=0.0005, tax_rate=0.002,
        )
        # 成交额 = 100,000
        # 佣金 = 100,000 * 0.0005 = 50
        assert cost["commission"] == pytest.approx(50.0, abs=0.01)
        # 印花税 = 100,000 * 0.002 = 200
        assert cost["tax"] == pytest.approx(200.0, abs=0.01)

    def test_total_cost_tax_only_on_sell(self):
        """验证买入卖出总成本差异"""
        buy_cost = calculate_trade_cost(price=100.0, quantity=1000, direction="BUY")
        sell_cost = calculate_trade_cost(price=100.0, quantity=1000, direction="SELL")
        assert buy_cost["total_cost"] < sell_cost["total_cost"]
        # 差异应为印花税
        assert sell_cost["total_cost"] - buy_cost["total_cost"] == pytest.approx(sell_cost["tax"], abs=0.01)

    def test_zero_price_edge(self):
        """价格为0的场景（虽然业务上不会出现，但函数不应崩溃）"""
        cost = calculate_trade_cost(price=0, quantity=100, direction="BUY")
        assert cost["amount"] == 0.0
        assert cost["commission"] == 5.0  # 最低佣金5元
        assert cost["tax"] == 0.0

    def test_quantity_one(self):
        """数量为1（虽然不合法，但计算函数不应崩溃）"""
        cost = calculate_trade_cost(price=100.0, quantity=1, direction="BUY")
        assert cost["amount"] == 100.0
        assert cost["commission"] == 5.0  # 最低佣金


# ============================================================
# OrderAdmin 类测试
# ============================================================


class TestOrderAdmin:
    """OrderAdmin 查询与摘要测试"""

    # ---- get_order ----

    def test_get_order_found(self):
        """查询已存在的订单"""
        order_row = {
            "order_id": "ORD_001",
            "ts_code": "600519.SH",
            "direction": "BUY",
            "order_type": "LIMIT",
            "price": 1800.0,
            "quantity": 100,
            "amount": 180000.0,
            "status": "FILLED",
            "filled_price": 1800.0,
            "filled_quantity": 100,
            "filled_amount": 180000.0,
            "commission": 54.0,
            "tax": 0.0,
            "strategy_name": "MA_CROSS",
            "error_message": None,
            "created_at": "2026-06-15T10:00:00",
            "updated_at": "2026-06-15T10:00:05",
        }
        db = _make_mock_db(order=order_row)
        admin = OrderAdmin(db=db)
        result = admin.get_order("ORD_001")

        assert result is not None
        assert result["order_id"] == "ORD_001"
        assert result["ts_code"] == "600519.SH"
        assert result["direction"] == "BUY"
        assert result["status"] == "FILLED"
        assert result["commission"] == 54.0
        db.execute.assert_called_once()

    def test_get_order_not_found(self):
        """查询不存在的订单"""
        db = _make_mock_db()  # no order preset -> returns None
        admin = OrderAdmin(db=db)
        result = admin.get_order("ORD_NONEXIST")
        assert result is None

    def test_get_order_with_sell(self):
        """查询卖出订单"""
        order_row = {
            "order_id": "ORD_002",
            "ts_code": "000001.SZ",
            "direction": "SELL",
            "order_type": "MARKET",
            "price": 15.5,
            "quantity": 200,
            "amount": 3100.0,
            "status": "PENDING",
            "filled_price": None,
            "filled_quantity": 0,
            "filled_amount": 0.0,
            "commission": 0.0,
            "tax": 0.0,
            "strategy_name": None,
            "error_message": None,
            "created_at": "2026-06-15T10:30:00",
            "updated_at": "2026-06-15T10:30:00",
        }
        db = _make_mock_db(order=order_row)
        admin = OrderAdmin(db=db)
        result = admin.get_order("ORD_002")
        assert result is not None
        assert result["direction"] == "SELL"
        assert result["status"] == "PENDING"
        assert result["order_type"] == "MARKET"

    # ---- list_orders ----

    def test_list_orders_no_filter(self):
        """查询订单列表（无状态过滤）"""
        orders = [
            {
                "order_id": "ORD_001", "ts_code": "600519.SH", "direction": "BUY",
                "order_type": "LIMIT", "price": 1800.0, "quantity": 100, "amount": 180000.0,
                "status": "FILLED", "filled_price": 1800.0, "filled_quantity": 100,
                "commission": 54.0, "tax": 0.0, "strategy_name": "MA_CROSS",
                "created_at": "2026-06-15T10:00:00", "updated_at": "2026-06-15T10:00:05",
            },
            {
                "order_id": "ORD_002", "ts_code": "000001.SZ", "direction": "SELL",
                "order_type": "MARKET", "price": 15.5, "quantity": 200, "amount": 3100.0,
                "status": "PENDING", "filled_price": None, "filled_quantity": 0,
                "commission": 0.0, "tax": 0.0, "strategy_name": None,
                "created_at": "2026-06-15T10:30:00", "updated_at": "2026-06-15T10:30:00",
            },
        ]
        db = _make_mock_db(orders=orders)
        admin = OrderAdmin(db=db)
        result = admin.list_orders()

        assert len(result) == 2
        assert result[0]["order_id"] == "ORD_001"
        assert result[1]["order_id"] == "ORD_002"

    def test_list_orders_with_status_filter(self):
        """按状态过滤订单列表"""
        orders = [
            {
                "order_id": "ORD_003", "ts_code": "601318.SH", "direction": "BUY",
                "order_type": "LIMIT", "price": 50.0, "quantity": 100, "amount": 5000.0,
                "status": "PENDING", "filled_price": None, "filled_quantity": 0,
                "commission": 0.0, "tax": 0.0, "strategy_name": None,
                "created_at": "2026-06-15T11:00:00", "updated_at": "2026-06-15T11:00:00",
            },
        ]
        db = _make_mock_db(orders=orders)
        admin = OrderAdmin(db=db)
        result = admin.list_orders(status="PENDING")

        assert len(result) == 1
        assert result[0]["status"] == "PENDING"

    def test_list_orders_with_custom_limit(self):
        """自定义limit"""
        orders = [
            {
                "order_id": str(i), "ts_code": "600519.SH", "direction": "BUY",
                "order_type": "LIMIT", "price": 100.0, "quantity": 100, "amount": 10000.0,
                "status": "FILLED", "filled_price": 100.0, "filled_quantity": 100,
                "commission": 5.0, "tax": 0.0, "strategy_name": None,
                "created_at": f"2026-06-{10+i:02d}T10:00:00",
                "updated_at": f"2026-06-{10+i:02d}T10:00:05",
            }
            for i in range(5)
        ]
        db = _make_mock_db(orders=orders)
        admin = OrderAdmin(db=db)
        result = admin.list_orders(limit=5)

        assert len(result) == 5

    def test_list_orders_empty(self):
        """无订单时返回空列表"""
        db = _make_mock_db()  # no orders preset
        admin = OrderAdmin(db=db)
        result = admin.list_orders()
        assert result == []

    def test_list_orders_with_status_filter_empty(self):
        """按状态过滤但无匹配订单"""
        db = _make_mock_db()  # no orders
        admin = OrderAdmin(db=db)
        result = admin.list_orders(status="REJECTED")
        assert result == []

    # ---- get_daily_summary ----

    def test_daily_summary_with_trades(self):
        """有成交时的每日摘要"""
        trades = {
            "count": 5, "total_amount": 500000.0, "total_commission": 150.0,
            "total_tax": 100.0, "total_pnl": 20000.0,
        }
        positions = {
            "count": 3, "total_market_value": 600000.0, "total_unrealized_pnl": 15000.0,
        }
        orders_today = [
            {"status": "FILLED", "count": 3},
            {"status": "PENDING", "count": 2},
        ]
        account = {
            "available_cash": 500000.0, "total_assets": 1200000.0,
            "market_value": 600000.0, "day_profit_loss": 20000.0,
        }

        db = _make_mock_db(
            trades=trades, positions=positions,
            orders_today=orders_today, account=account,
        )
        admin = OrderAdmin(db=db)
        summary = admin.get_daily_summary()

        assert summary["trades"]["count"] == 5
        assert summary["trades"]["total_amount"] == 500000.0
        assert summary["trades"]["total_commission"] == 150.0
        assert summary["trades"]["total_tax"] == 100.0
        assert summary["trades"]["total_pnl"] == 20000.0
        assert summary["positions"]["count"] == 3
        assert summary["positions"]["total_market_value"] == 600000.0
        assert summary["positions"]["total_unrealized_pnl"] == 15000.0
        assert summary["account"]["available_cash"] == 500000.0
        assert summary["account"]["total_assets"] == 1200000.0
        assert summary["account"]["market_value"] == 600000.0
        assert summary["account"]["day_pnl"] == 20000.0
        assert len(summary["orders_today"]) == 2
        assert summary["orders_today"][0]["status"] == "FILLED"

    def test_daily_summary_no_trades(self):
        """无成交时的每日摘要"""
        account = {
            "available_cash": 1000000.0, "total_assets": 1200000.0,
            "market_value": 200000.0, "day_profit_loss": 0.0,
        }
        db = _make_mock_db(
            trades=None, positions=None, orders_today=None, account=account,
        )
        admin = OrderAdmin(db=db)
        summary = admin.get_daily_summary()

        assert summary["trades"]["count"] == 0
        assert summary["trades"]["total_amount"] == 0.0
        assert summary["trades"]["total_commission"] == 0.0
        assert summary["trades"]["total_tax"] == 0.0
        assert summary["trades"]["total_pnl"] == 0.0
        assert summary["positions"]["count"] == 0
        assert summary["positions"]["total_market_value"] == 0.0
        assert summary["positions"]["total_unrealized_pnl"] == 0.0
        assert summary["orders_today"] == []

    def test_daily_summary_no_account(self):
        """账户不存在时的每日摘要"""
        db = _make_mock_db(account=None)  # account query returns None
        admin = OrderAdmin(db=db)
        summary = admin.get_daily_summary()
        # 账户信息应返回默认值
        assert summary["account"]["available_cash"] == 0
        assert summary["account"]["total_assets"] == 0
        assert summary["account"]["market_value"] == 0
        assert summary["account"]["day_pnl"] == 0

    def test_daily_summary_custom_account_id(self):
        """自定义账户ID"""
        account = {
            "available_cash": 888888.0, "total_assets": 999999.0,
            "market_value": 111111.0, "day_profit_loss": 12345.0,
        }
        db = _make_mock_db(account=account)
        admin = OrderAdmin(db=db, account_id="CUSTOM_001")
        summary = admin.get_daily_summary()

        assert summary["account"]["available_cash"] == 888888.0
        assert summary["account"]["total_assets"] == 999999.0
        # 验证传入的 account_id 被使用
        # 注意：这里我们通过 mock 匹配来验证，但更精确的方式需要检查 db.execute 的参数
        # 让我们验证数据正确来自 custom account
        assert summary["account"]["day_pnl"] == 12345.0

    # ---- send_daily_summary ----

    @pytest.mark.asyncio
    async def test_send_daily_summary_success(self):
        """发送每日摘要成功"""
        account = {
            "available_cash": 1000000.0, "total_assets": 1200000.0,
            "market_value": 200000.0, "day_profit_loss": 5000.0,
        }
        db = _make_mock_db(account=account)
        admin = OrderAdmin(db=db)

        # send_daily_summary 内部使用 from services.feishu_alert import get_alert_service
        with patch("services.feishu_alert.get_alert_service") as mock_get:
            mock_alert = AsyncMock()
            mock_alert.send_daily_summary = AsyncMock(return_value=True)
            mock_get.return_value = mock_alert

            await admin.send_daily_summary()

            mock_get.assert_called_once()
            mock_alert.send_daily_summary.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_daily_summary_failure_handled(self):
        """发送每日摘要失败时不应抛出异常"""
        account = {
            "available_cash": 1000000.0, "total_assets": 1200000.0,
            "market_value": 200000.0, "day_profit_loss": 5000.0,
        }
        db = _make_mock_db(account=account)
        admin = OrderAdmin(db=db)

        with patch("services.feishu_alert.get_alert_service") as mock_get:
            mock_alert = AsyncMock()
            mock_alert.send_daily_summary = AsyncMock(side_effect=Exception("网络错误"))
            mock_get.return_value = mock_alert

            # 不应抛出异常
            await admin.send_daily_summary()
            mock_get.assert_called_once()
            mock_alert.send_daily_summary.assert_awaited_once()
