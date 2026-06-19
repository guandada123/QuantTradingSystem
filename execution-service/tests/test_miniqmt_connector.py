"""
MiniQMT 连接器单元测试。

测试覆盖：
- 模拟模式下的完整交易生命周期（buy/sell/cancel/positions/account）
- 参数校验（非法数量、非100倍数）
- 连接生命周期管理
- 健康检查
- Context manager 模式
- XtQuant 导入失败时的优雅降级
"""

import pytest
from services.miniqmt_connector import (
    AccountInfo,
    MiniQMTConnector,
    OrderDirection,
    OrderStatus,
    OrderType,
    Position,
    create_connector,
)


@pytest.fixture
async def connector():
    """创建模拟模式连接器——模块级别，所有测试类共用"""
    conn = MiniQMTConnector(simulate=True)
    await conn.connect()
    yield conn
    await conn.disconnect()


class TestMiniQMTConnectorSimulate:
    """模拟模式下的交易测试"""

    # ---- 连接测试 ----

    @pytest.mark.asyncio
    async def test_connect_simulate_mode(self):
        """模拟模式自动连接成功"""
        conn = MiniQMTConnector(simulate=True)
        result = await conn.connect()
        assert result is True
        assert conn.connected is True
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self, connector):
        """断开连接"""
        await connector.disconnect()
        assert connector.connected is False

    @pytest.mark.asyncio
    async def test_ensure_connected(self):
        """测试自动重连"""
        conn = MiniQMTConnector(simulate=True)
        assert conn.connected is False
        result = await conn.ensure_connected()
        assert result is True
        assert conn.connected is True
        await conn.disconnect()

    # ---- 买入测试 ----

    @pytest.mark.asyncio
    async def test_buy_success(self, connector):
        """模拟买入成功"""
        result = await connector.buy("000001.SZ", price=12.50, quantity=100)
        assert result["success"] is True
        assert result["order_id"].startswith("SIM_BUY_")
        assert result["status"] == "SIMULATED"

    @pytest.mark.asyncio
    async def test_buy_invalid_quantity_zero(self, connector):
        """买入数量为零"""
        result = await connector.buy("000001.SZ", price=12.50, quantity=0)
        assert result["success"] is False
        assert "quantity" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_buy_invalid_quantity_not_multiple_of_100(self, connector):
        """买入数量非100倍数"""
        result = await connector.buy("000001.SZ", price=12.50, quantity=150)
        assert result["success"] is False
        assert "100" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_buy_negative_quantity(self, connector):
        """买入负数"""
        result = await connector.buy("000001.SZ", price=12.50, quantity=-100)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_buy_market_order(self, connector):
        """市价买入"""
        result = await connector.buy(
            "000001.SZ", price=0, quantity=200, order_type=OrderType.MARKET
        )
        assert result["success"] is True
        assert result["status"] == "SIMULATED"

    # ---- 卖出测试 ----

    @pytest.mark.asyncio
    async def test_sell_success(self, connector):
        """模拟卖出成功"""
        result = await connector.sell("000001.SZ", price=13.00, quantity=100)
        assert result["success"] is True
        assert result["order_id"].startswith("SIM_SELL_")

    @pytest.mark.asyncio
    async def test_sell_invalid_quantity(self, connector):
        """卖出非法数量"""
        result = await connector.sell("000001.SZ", price=13.00, quantity=50)
        assert result["success"] is False
        assert "100" in result.get("error", "")

    # ---- 撤单测试 ----

    @pytest.mark.asyncio
    async def test_cancel_order(self, connector):
        """模拟撤单"""
        result = await connector.cancel_order("SIM_BUY_000001_100")
        assert result["success"] is True

    # ---- 查询测试 ----

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, connector):
        """模拟模式无持仓"""
        positions = await connector.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_get_account_info_empty(self, connector):
        """模拟模式无账户信息"""
        info = await connector.get_account_info()
        assert isinstance(info, AccountInfo)
        assert info.total_assets == 0.0
        assert info.available_cash == 0.0

    @pytest.mark.asyncio
    async def test_get_orders_empty(self, connector):
        """模拟模式无订单"""
        orders = await connector.get_orders()
        assert orders == []

    @pytest.mark.asyncio
    async def test_get_order_none(self, connector):
        """模拟模式查询不存在订单"""
        order = await connector.get_order("NONEXISTENT")
        assert order is None

    # ---- 健康检查 ----

    @pytest.mark.asyncio
    async def test_health_check(self, connector):
        """健康检查返回模拟模式状态"""
        health = await connector.health_check()
        assert health["status"] == "simulate"
        assert health["connected"] is True


class TestMiniQMTConnectorContextManager:
    """Context Manager 模式测试"""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """async with 自动连接和断开"""
        async with create_connector(simulate=True) as conn:
            assert conn.connected is True
            result = await conn.buy("000001.SZ", price=12.50, quantity=100)
            assert result["success"] is True
        # 退出 context manager 后应断开
        assert conn.connected is False

    @pytest.mark.asyncio
    async def test_context_manager_exception(self):
        """context manager 内异常时仍会断开"""
        try:
            async with create_connector(simulate=True) as conn:
                assert conn.connected is True
                raise RuntimeError("test exception")
        except RuntimeError:
            pass
        assert conn.connected is False


class TestMiniQMTConnectorEdgeCases:
    """边界情况测试"""

    @pytest.mark.asyncio
    async def test_connect_with_env_vars(self, monkeypatch):
        """从环境变量读取配置"""
        monkeypatch.setenv("MINIQMT_USER", "test_user")
        monkeypatch.setenv("MINIQMT_PASSWORD", "test_pass")
        monkeypatch.setenv("QMT_PATH", "/opt/qmt")

        conn = MiniQMTConnector(simulate=True)
        assert conn.user == "test_user"
        assert conn.password == "test_pass"
        assert conn.path == "/opt/qmt"

    @pytest.mark.asyncio
    async def test_connect_with_explicit_params(self):
        """显式参数优先于环境变量"""
        conn = MiniQMTConnector(
            user="explicit_user",
            password="explicit_pass",
            path="/custom/path",
            simulate=True,
        )
        assert conn.user == "explicit_user"
        assert conn.path == "/custom/path"

    @pytest.mark.asyncio
    async def test_default_simulate_mode(self):
        """默认使用模拟模式（xtquant 未安装时）"""
        conn = MiniQMTConnector()
        assert conn._simulate is True  # _SIMULATE_FLAG = True

    @pytest.mark.asyncio
    async def test_multiple_buy_orders(self, connector):
        """连续多笔买入"""
        for i in range(3):
            result = await connector.buy(f"00000{i + 1}.SZ", price=10.0 + i, quantity=100 * (i + 1))
            assert result["success"] is True
            assert result["order_id"].startswith("SIM_BUY_")


class TestDataStructures:
    """数据结构测试"""

    def test_order_dataclass(self):
        from services.miniqmt_connector import Order

        order = Order(
            order_id="ORD_001",
            ts_code="000001.SZ",
            direction=OrderDirection.BUY,
            quantity=100,
            price=12.50,
        )
        assert order.status == OrderStatus.PENDING
        assert order.filled_qty == 0

    def test_position_dataclass(self):
        pos = Position(
            ts_code="000001.SZ",
            name="平安银行",
            quantity=500,
            avg_cost=12.00,
            current_price=12.50,
            market_value=6250.0,
            unrealized_pnl=250.0,
        )
        assert pos.unrealized_pnl == 250.0

    def test_account_info_dataclass(self):
        info = AccountInfo(
            total_assets=30000.0,
            available_cash=5000.0,
            market_value=25000.0,
        )
        assert info.frozen_cash == 0.0
        assert info.total_pnl == 0.0
