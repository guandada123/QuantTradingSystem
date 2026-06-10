"""
交易执行服务 - 综合单元测试
覆盖：订单创建/执行/撤销、持仓管理、盈亏计算、风控、API端点
"""

import pytest
import uuid
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.order_manager import OrderManager, Order, OrderStatus, OrderDirection, OrderType
from services.position_manager import PositionManager
from services.risk_controller import RiskController

# 全局补丁：测试环境允许非交易时间下单
import core.config
core.config.settings.ALLOW_OFF_HOURS_TRADING = True


# ============================================================
# 测试工具：模拟数据库
# ============================================================

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
    def __init__(self, rows=None, row=None):
        self._rows = rows or []
        self._row = row

    def mappings(self):
        return self

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


def make_mock_db(account_data=None, position_data=None, order_data=None):
    """创建标准模拟DB"""
    db = MagicMock()

    default_account = MockRow({
        'available_cash': 1000000.0,
        'total_assets': 1200000.0,
        'market_value': 200000.0
    })

    def execute_side_effect(stmt, params=None):
        sql = str(stmt.text) if hasattr(stmt, 'text') else str(stmt)

        if 'FROM accounts' in sql:
            if account_data:
                return MockResult(row=MockRow(account_data))
            return MockResult(row=default_account)
        elif 'FROM positions' in sql and 'WHERE' in sql and 'ts_code' in sql:
            if position_data:
                return MockResult(row=MockRow(position_data))
            return MockResult(row=None)
        elif 'FROM positions' in sql:
            if position_data:
                return MockResult(rows=[MockRow(position_data)])
            return MockResult(rows=[])
        elif 'FROM orders WHERE order_id' in sql:
            if order_data:
                return MockResult(row=MockRow(order_data))
            return MockResult(row=None)
        elif 'FROM orders' in sql:
            if order_data:
                return MockResult(rows=[MockRow(order_data)])
            return MockResult(rows=[])
        elif 'INSERT' in sql or 'UPDATE' in sql or 'DELETE' in sql:
            return MockResult()
        elif 'day_profit_loss' in sql:
            return MockResult(row=MockRow({'day_profit_loss': None}))
        else:
            return MockResult()

    db.execute = MagicMock(side_effect=execute_side_effect)
    db.commit = MagicMock()
    db.close = MagicMock()
    return db


# ============================================================
# 订单创建测试
# ============================================================

class TestOrderCreation:
    """订单创建测试"""

    def test_create_order_basic(self):
        """测试基本订单创建"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        order = mgr.create_order(
            ts_code='600519.SH',
            direction='BUY',
            order_type='LIMIT',
            price=1800.0,
            quantity=100
        )
        assert order.order_id.startswith('ORD_')
        assert order.ts_code == '600519.SH'
        assert order.direction == OrderDirection.BUY
        assert order.status == OrderStatus.PENDING
        assert order.quantity == 100
        assert order.price == 1800.0
        db.commit.assert_called()

    def test_create_order_sell(self):
        """测试创建卖出订单"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        order = mgr.create_order(
            ts_code='000001.SZ',
            direction='SELL',
            order_type='LIMIT',
            price=15.5,
            quantity=200
        )
        assert order.direction == OrderDirection.SELL
        assert order.quantity == 200

    def test_create_order_with_strategy(self):
        """测试创建带策略名的订单"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        order = mgr.create_order(
            ts_code='600036.SH',
            direction='BUY',
            price=40.0,
            quantity=500,
            strategy_name='MA_CROSS'
        )
        assert order.strategy_name == 'MA_CROSS'

    def test_create_order_market_type(self):
        """测试创建市价订单"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        order = mgr.create_order(
            ts_code='601318.SH',
            direction='BUY',
            order_type='MARKET',
            price=50.0,
            quantity=100
        )
        assert order.order_type == OrderType.MARKET

    def test_create_order_invalid_direction(self):
        """测试无效方向抛出异常"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        with pytest.raises(ValueError):
            mgr.create_order(
                ts_code='600519.SH',
                direction='INVALID',
                price=1800.0,
                quantity=100
            )


# ============================================================
# STOP 条件单测试
# ============================================================

class TestStopOrders:
    """STOP 条件单创建与触发测试"""

    def test_create_stop_buy_valid(self):
        """测试创建有效的BUY STOP单"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        order = mgr.create_order(
            ts_code='600519.SH',
            direction='BUY',
            order_type='STOP',
            price=1300.0,
            quantity=100,
            trigger_price=1400.0
        )
        assert order.order_type == OrderType.STOP
        assert order.direction == OrderDirection.BUY
        assert order.trigger_price == 1400.0
        assert order.price == 1300.0
        assert order.status == OrderStatus.PENDING
        db.commit.assert_called()

    def test_create_stop_sell_valid(self):
        """测试创建有效的SELL STOP单"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        order = mgr.create_order(
            ts_code='000001.SZ',
            direction='SELL',
            order_type='STOP',
            price=15.0,
            quantity=200,
            trigger_price=12.0
        )
        assert order.order_type == OrderType.STOP
        assert order.direction == OrderDirection.SELL
        assert order.trigger_price == 12.0

    def test_stop_order_missing_trigger_price(self):
        """STOP单缺少trigger_price应抛出异常"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        with pytest.raises(ValueError, match='trigger_price'):
            mgr.create_order(
                ts_code='600519.SH',
                direction='BUY',
                order_type='STOP',
                price=1300.0,
                quantity=100
            )

    def test_stop_buy_trigger_le_price(self):
        """BUY STOP: trigger_price <= price 应抛出异常"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        with pytest.raises(ValueError, match='触发价'):
            mgr.create_order(
                ts_code='600519.SH',
                direction='BUY',
                order_type='STOP',
                price=1500.0,
                quantity=100,
                trigger_price=1400.0  # trigger <= price
            )

    def test_stop_sell_trigger_ge_price(self):
        """SELL STOP: trigger_price >= price 应抛出异常"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        with pytest.raises(ValueError, match='触发价'):
            mgr.create_order(
                ts_code='600519.SH',
                direction='SELL',
                order_type='STOP',
                price=50.0,
                quantity=100,
                trigger_price=60.0  # trigger >= price
            )

    def test_stop_buy_trigger_equal_price(self):
        """BUY STOP: trigger_price == price 应抛出异常"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        with pytest.raises(ValueError):
            mgr.create_order(
                ts_code='600519.SH',
                direction='BUY',
                order_type='STOP',
                price=1300.0,
                quantity=100,
                trigger_price=1300.0  # equal
            )

    def test_stop_sell_trigger_equal_price(self):
        """SELL STOP: trigger_price == price 应抛出异常"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        with pytest.raises(ValueError):
            mgr.create_order(
                ts_code='600519.SH',
                direction='SELL',
                order_type='STOP',
                price=50.0,
                quantity=100,
                trigger_price=50.0  # equal
            )

    def test_stop_order_negative_trigger(self):
        """STOP单: trigger_price <= 0 应抛出异常"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        with pytest.raises(ValueError, match='触发价格'):
            mgr.create_order(
                ts_code='600519.SH',
                direction='BUY',
                order_type='STOP',
                price=1300.0,
                quantity=100,
                trigger_price=-10.0
            )

    def test_check_stop_buy_triggered(self):
        """BUY STOP: 当前价 >= 触发价 → 应触发"""
        db = make_mock_db(order_data={
            'order_id': 'ORD_STOP001',
            'ts_code': '600519.SH',
            'direction': 'BUY',
            'price': 1300.0,
            'quantity': 100,
            'status': 'PENDING',
            'trigger_price': 1400.0,
            'order_type': 'STOP'
        })
        mgr = OrderManager(db=db)

        # Price map: current price >= trigger
        triggered = mgr.check_stop_orders({'600519.SH': 1420.0})
        assert len(triggered) == 1
        assert triggered[0]['order_id'] == 'ORD_STOP001'
        assert triggered[0]['trigger_price'] == 1400.0
        assert triggered[0]['executed_price'] == 1420.0

    def test_check_stop_buy_not_triggered(self):
        """BUY STOP: 当前价 < 触发价 → 不触发"""
        db = make_mock_db(order_data={
            'order_id': 'ORD_STOP002',
            'ts_code': '600519.SH',
            'direction': 'BUY',
            'price': 1300.0,
            'quantity': 100,
            'status': 'PENDING',
            'trigger_price': 1400.0,
            'order_type': 'STOP'
        })
        mgr = OrderManager(db=db)

        # Price map: current price below trigger
        triggered = mgr.check_stop_orders({'600519.SH': 1350.0})
        assert len(triggered) == 0

    def test_check_stop_sell_triggered(self):
        """SELL STOP: 当前价 <= 触发价 → 应触发"""
        db = make_mock_db(order_data={
            'order_id': 'ORD_STOP003',
            'ts_code': '000001.SZ',
            'direction': 'SELL',
            'price': 15.0,
            'quantity': 200,
            'status': 'PENDING',
            'trigger_price': 12.0,
            'order_type': 'STOP'
        })
        mgr = OrderManager(db=db)

        triggered = mgr.check_stop_orders({'000001.SZ': 11.5})
        assert len(triggered) == 1
        assert triggered[0]['order_id'] == 'ORD_STOP003'
        assert triggered[0]['direction'] == 'SELL'

    def test_check_stop_sell_not_triggered(self):
        """SELL STOP: 当前价 > 触发价 → 不触发"""
        db = make_mock_db(order_data={
            'order_id': 'ORD_STOP004',
            'ts_code': '000001.SZ',
            'direction': 'SELL',
            'price': 15.0,
            'quantity': 200,
            'status': 'PENDING',
            'trigger_price': 12.0,
            'order_type': 'STOP'
        })
        mgr = OrderManager(db=db)

        triggered = mgr.check_stop_orders({'000001.SZ': 13.0})
        assert len(triggered) == 0

    def test_check_stop_orders_empty_price_map(self):
        """STOP扫描: 价格映射中无对应股票 → 不触发"""
        db = make_mock_db(order_data={
            'order_id': 'ORD_STOP005',
            'ts_code': '600519.SH',
            'direction': 'BUY',
            'price': 1300.0,
            'quantity': 100,
            'status': 'PENDING',
            'trigger_price': 1400.0,
            'order_type': 'STOP'
        })
        mgr = OrderManager(db=db)

        # Empty price map
        triggered = mgr.check_stop_orders({})
        assert len(triggered) == 0

    def test_check_stop_multiple_orders(self):
        """STOP扫描: 多订单混合场景"""
        stop_rows = [
            MockRow({
                'order_id': 'ORD_STOP_M001',
                'ts_code': '600519.SH',
                'direction': 'BUY',
                'price': 1300.0,
                'quantity': 100,
                'status': 'PENDING',
                'trigger_price': 1400.0,
                'order_type': 'STOP',
                'strategy_name': None
            }),
            MockRow({
                'order_id': 'ORD_STOP_M002',
                'ts_code': '000001.SZ',
                'direction': 'SELL',
                'price': 15.0,
                'quantity': 200,
                'status': 'PENDING',
                'trigger_price': 12.0,
                'order_type': 'STOP',
                'strategy_name': None
            })
        ]

        db = MagicMock()
        db.execute = MagicMock()
        # First execute: check_stop_orders SELECT
        db.execute.return_value = MockResult(rows=stop_rows)
        db.commit = MagicMock()
        db.close = MagicMock()

        mgr = OrderManager(db=db)
        # Current prices: 600519.SH=1420 (triggers buy), 000001.SZ=13 (doesn't trigger sell)
        triggered = mgr.check_stop_orders({'600519.SH': 1420.0, '000001.SZ': 13.0})
        # Only the BUY STOP should trigger (1420 >= 1400), SELL STOP not (13 > 12)
        assert len(triggered) == 1
        assert triggered[0]['ts_code'] == '600519.SH'


# ============================================================
# 订单执行测试
# ============================================================

class TestOrderExecution:
    """订单执行测试"""

    def test_execute_buy_order_success(self):
        """测试成功执行买入订单"""
        order_data = {
            'order_id': 'ORD_test001',
            'ts_code': '600519.SH',
            'direction': 'BUY',
            'price': 1800.0,
            'quantity': 100,
            'status': 'PENDING'
        }
        db = make_mock_db(order_data=order_data)
        mgr = OrderManager(db=db)
        result = mgr.execute_order('ORD_test001')
        assert result['success'] is True
        assert result['direction'] == 'BUY'
        assert result['quantity'] == 100
        assert result['price'] == 1800.0
        assert result['commission'] > 0
        assert 'trade_id' in result

    def test_execute_order_not_found(self):
        """测试执行不存在的订单"""
        db = make_mock_db(order_data=None)
        mgr = OrderManager(db=db)
        result = mgr.execute_order('ORD_nonexist')
        assert result['success'] is False
        assert '不存在' in result['error']

    def test_execute_order_wrong_status(self):
        """测试执行已成交订单"""
        order_data = {
            'order_id': 'ORD_filled',
            'ts_code': '600519.SH',
            'direction': 'BUY',
            'price': 1800.0,
            'quantity': 100,
            'status': 'FILLED'
        }
        db = make_mock_db(order_data=order_data)
        mgr = OrderManager(db=db)
        result = mgr.execute_order('ORD_filled')
        assert result['success'] is False
        assert '状态不允许' in result['error']

    def test_execute_buy_insufficient_funds(self):
        """测试资金不足时买入被拒绝"""
        order_data = {
            'order_id': 'ORD_poor',
            'ts_code': '600519.SH',
            'direction': 'BUY',
            'price': 1800.0,
            'quantity': 1000,
            'status': 'PENDING'
        }
        account_data = {
            'available_cash': 10000.0,
            'total_assets': 50000.0,
            'market_value': 40000.0
        }
        db = make_mock_db(account_data=account_data, order_data=order_data)
        mgr = OrderManager(db=db)
        result = mgr.execute_order('ORD_poor')
        assert result['success'] is False
        assert '资金不足' in result['error']

    def test_execute_sell_insufficient_position(self):
        """测试持仓不足时卖出被拒绝"""
        order_data = {
            'order_id': 'ORD_sell001',
            'ts_code': '600519.SH',
            'direction': 'SELL',
            'price': 1900.0,
            'quantity': 500,
            'status': 'PENDING'
        }
        position_data = {
            'total_quantity': 100,
            'available_quantity': 100,
            'cost_price': 1800.0
        }
        db = make_mock_db(order_data=order_data, position_data=position_data)
        mgr = OrderManager(db=db)
        result = mgr.execute_order('ORD_sell001')
        assert result['success'] is False
        assert '持仓不足' in result['error']

    def test_commission_calculation_min(self):
        """测试最低佣金5元"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        cost = mgr.calculate_cost(10.0, 100, 'BUY')
        # 10*100*0.0003 = 0.3 < 5，应按5元计
        assert cost['commission'] == 5.0

    def test_commission_calculation_normal(self):
        """测试正常佣金计算"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        cost = mgr.calculate_cost(1800.0, 100, 'BUY')
        # 1800*100*0.0003 = 54
        assert cost['commission'] == pytest.approx(54.0, abs=0.01)

    def test_tax_only_on_sell(self):
        """测试印花税仅卖出收取"""
        db = make_mock_db()
        mgr = OrderManager(db=db)
        buy_cost = mgr.calculate_cost(100.0, 1000, 'BUY')
        sell_cost = mgr.calculate_cost(100.0, 1000, 'SELL')
        assert buy_cost['tax'] == 0.0
        assert sell_cost['tax'] == pytest.approx(100.0, abs=0.01)  # 100*1000*0.001


# ============================================================
# 订单撤销测试
# ============================================================

class TestOrderCancellation:
    """订单撤销测试"""

    def test_cancel_pending_order(self):
        """测试撤销挂起订单"""
        order_data = {'status': 'PENDING'}
        db = make_mock_db(order_data=order_data)
        mgr = OrderManager(db=db)
        result = mgr.cancel_order('ORD_cancel001')
        assert result is True
        db.commit.assert_called()

    def test_cancel_submitted_order(self):
        """测试撤销已提交订单"""
        order_data = {'status': 'SUBMITTED'}
        db = make_mock_db(order_data=order_data)
        mgr = OrderManager(db=db)
        result = mgr.cancel_order('ORD_cancel002')
        assert result is True

    def test_cancel_filled_order_fails(self):
        """测试无法撤销已成交订单"""
        order_data = {'status': 'FILLED'}
        db = make_mock_db(order_data=order_data)
        mgr = OrderManager(db=db)
        result = mgr.cancel_order('ORD_filled001')
        assert result is False

    def test_cancel_nonexistent_order(self):
        """测试撤销不存在的订单"""
        db = make_mock_db(order_data=None)
        mgr = OrderManager(db=db)
        result = mgr.cancel_order('ORD_nonexist')
        assert result is False


# ============================================================
# 持仓管理测试
# ============================================================

class TestPositionManager:
    """持仓管理测试"""

    def test_open_position_new(self):
        """测试新开仓"""
        db = make_mock_db()
        mgr = PositionManager(db=db)
        result = mgr.open_position(
            ts_code='600519.SH',
            quantity=100,
            price=1800.0,
            direction='LONG'
        )
        assert result['success'] is True
        assert result['ts_code'] == '600519.SH'
        assert result['quantity'] == 100
        assert result['commission'] > 0

    def test_open_position_insufficient_funds(self):
        """测试资金不足开仓失败"""
        account_data = {
            'available_cash': 100.0,
            'total_assets': 100.0,
            'market_value': 0.0
        }
        db = make_mock_db(account_data=account_data)
        mgr = PositionManager(db=db)
        result = mgr.open_position(
            ts_code='600519.SH',
            quantity=100,
            price=1800.0
        )
        assert result['success'] is False
        assert '资金不足' in result['error']

    def test_close_position_success(self):
        """测试平仓成功"""
        position_data = {
            'total_quantity': 200,
            'available_quantity': 200,
            'cost_price': 1800.0
        }
        db = make_mock_db(position_data=position_data)
        mgr = PositionManager(db=db)
        result = mgr.close_position(
            ts_code='600519.SH',
            quantity=100,
            price=1900.0
        )
        assert result['success'] is True
        assert result['profit_loss'] > 0  # 赚钱了
        assert 'trade_id' in result
        assert result['commission'] > 0
        assert result['tax'] > 0

    def test_close_position_no_position(self):
        """测试平仓时无持仓"""
        db = make_mock_db(position_data=None)
        mgr = PositionManager(db=db)
        result = mgr.close_position(
            ts_code='999999.SH',
            quantity=100,
            price=10.0
        )
        assert result['success'] is False
        assert '未找到' in result['error']

    def test_close_position_insufficient(self):
        """测试平仓数量超过可用持仓"""
        position_data = {
            'total_quantity': 100,
            'available_quantity': 50,
            'cost_price': 20.0
        }
        db = make_mock_db(position_data=position_data)
        mgr = PositionManager(db=db)
        result = mgr.close_position(
            ts_code='000001.SZ',
            quantity=100,
            price=25.0
        )
        assert result['success'] is False
        assert '不足' in result['error']

    def test_pnl_calculation_profit(self):
        """测试盈利计算"""
        position_data = {
            'total_quantity': 100,
            'available_quantity': 100,
            'cost_price': 50.0
        }
        db = make_mock_db(position_data=position_data)
        mgr = PositionManager(db=db)
        result = mgr.close_position(
            ts_code='000001.SZ',
            quantity=100,
            price=60.0  # 涨了20%
        )
        assert result['success'] is True
        # PnL = (60-50)*100 - commission - tax
        # trade_amount = 6000, commission = max(6000*0.0003, 5) = 5, tax = 6000*0.001 = 6
        expected_pnl = (60.0 - 50.0) * 100 - 5.0 - 6.0
        assert result['profit_loss'] == pytest.approx(expected_pnl, abs=0.01)

    def test_pnl_calculation_loss(self):
        """测试亏损计算"""
        position_data = {
            'total_quantity': 100,
            'available_quantity': 100,
            'cost_price': 50.0
        }
        db = make_mock_db(position_data=position_data)
        mgr = PositionManager(db=db)
        result = mgr.close_position(
            ts_code='000001.SZ',
            quantity=100,
            price=40.0  # 跌了20%
        )
        assert result['success'] is True
        # PnL = (40-50)*100 - commission - tax = -1000 - 5 - 4 = -1009
        assert result['profit_loss'] < 0


# ============================================================
# 风控测试
# ============================================================

class TestRiskController:
    """风控测试"""

    def test_risk_check_pass(self):
        """测试正常风控通过"""
        controller = RiskController(
            db=None,
            max_position_ratio=0.30,
            max_total_positions=3
        )
        result = controller.check_trade_risk(
            ts_code='600519.SH',
            action='BUY',
            quantity=100,
            account_info={
                'total_assets': 1000000,
                'positions': {},
                'total_positions': 0
            }
        )
        assert result['allowed'] is True
        assert result['risk_level'] == 'LOW'

    def test_risk_check_position_limit(self):
        """测试仓位比例超标"""
        controller = RiskController(
            db=None,
            max_position_ratio=0.30,
            max_total_positions=5
        )
        result = controller.check_trade_risk(
            ts_code='600519.SH',
            action='BUY',
            quantity=100,
            account_info={
                'total_assets': 1000000,
                'positions': {
                    '600519.SH': {'market_value': 400000}  # 已占40%
                },
                'total_positions': 1
            }
        )
        assert len(result['risks']) > 0
        assert '仓位超标' in result['risks'][0]

    def test_risk_check_max_positions(self):
        """测试持仓数量超标"""
        controller = RiskController(
            db=None,
            max_position_ratio=0.30,
            max_total_positions=3
        )
        result = controller.check_trade_risk(
            ts_code='300001.SZ',
            action='BUY',
            quantity=100,
            account_info={
                'total_assets': 1000000,
                'positions': {
                    '600519.SH': {'market_value': 100000},
                    '000001.SZ': {'market_value': 100000},
                    '601318.SH': {'market_value': 100000}
                },
                'total_positions': 3
            }
        )
        assert len(result['risks']) > 0
        assert '持仓数量' in result['risks'][0]

    def test_stop_loss_triggered(self):
        """测试止损触发"""
        controller = RiskController(db=None, stop_loss_ratio=0.08)
        result = controller.check_stop_loss(
            ts_code='600519.SH',
            cost_price=100.0,
            current_price=90.0  # 跌10%
        )
        assert result['triggered'] is True
        assert result['action'] == 'STOP_LOSS'

    def test_stop_loss_not_triggered(self):
        """测试止损未触发"""
        controller = RiskController(db=None, stop_loss_ratio=0.08)
        result = controller.check_stop_loss(
            ts_code='600519.SH',
            cost_price=100.0,
            current_price=95.0  # 跌5%
        )
        assert result['triggered'] is False

    def test_take_profit_triggered(self):
        """测试止盈触发"""
        controller = RiskController(db=None, take_profit_ratio=0.30)
        result = controller.check_take_profit(
            ts_code='600519.SH',
            cost_price=100.0,
            current_price=135.0  # 涨35%
        )
        assert result['triggered'] is True
        assert result['action'] == 'TAKE_PROFIT'

    def test_take_profit_not_triggered(self):
        """测试止盈未触发"""
        controller = RiskController(db=None, take_profit_ratio=0.30)
        result = controller.check_take_profit(
            ts_code='600519.SH',
            cost_price=100.0,
            current_price=120.0  # 涨20%
        )
        assert result['triggered'] is False


# ============================================================
# API 集成测试
# ============================================================

class TestAPIEndpoints:
    """API端点集成测试"""

    @pytest.fixture
    def client(self):
        """创建测试客户端 — 使用 dependency_overrides 注入 Mock DB"""
        from fastapi.testclient import TestClient
        from main import app
        from models.database import get_db_session

        def override_get_db_session():
            db = make_mock_db()
            try:
                yield db
            finally:
                pass  # mock doesn't need real close

        app.dependency_overrides[get_db_session] = override_get_db_session
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    def test_health_endpoint(self, client):
        """测试健康检查端点"""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'healthy'

    def test_root_endpoint(self, client):
        """测试根路径"""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'running'

    def test_risk_settings_endpoint(self, client):
        """测试风控参数端点"""
        resp = client.get("/api/v1/risk/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data['code'] == 0
        assert 'max_position_ratio' in data['data']
        assert 'stop_loss_ratio' in data['data']

    def test_list_orders_endpoint(self, client):
        """测试订单列表端点"""
        with patch('models.database.get_db', return_value=make_mock_db()):
            resp = client.get("/api/v1/orders/")
            assert resp.status_code == 200

    def test_list_positions_endpoint(self, client):
        """测试持仓列表端点"""
        with patch('models.database.get_db', return_value=make_mock_db()):
            resp = client.get("/api/v1/positions/")
            assert resp.status_code == 200


# ============================================================
# 运行入口
# ============================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
