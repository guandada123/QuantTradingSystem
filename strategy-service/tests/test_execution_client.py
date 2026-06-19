"""
ExecutionClient 的单元测试

测试 services/execution_client.py 的 HTTP 客户端逻辑：
- submit_order() — 提交订单
- get_positions() — 获取持仓
- check_risk() — 风险检查
- 连接错误处理（超时、连接拒绝）

使用 @patch("services.execution_client.httpx.AsyncClient") 模拟 HTTP 请求。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def client():
    """创建 ExecutionClient 实例"""
    from services.execution_client import ExecutionClient

    return ExecutionClient()


# =========================================================================
# submit_order
# =========================================================================


class TestSubmitOrder:
    """submit_order() — 提交订单"""

    @pytest.mark.asyncio
    async def test_submit_order_success(self, client):
        """成功提交订单"""
        expected_response = {"success": True, "order_id": "ORD001"}

        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_response = MagicMock()
            mock_response.json.return_value = expected_response
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response

            result = await client.submit_order(
                account_id="REAL_001",
                ts_code="600519.SH",
                direction="BUY",
                order_type="limit",
                price=180.0,
                quantity=100,
                strategy_name="ma-cross",
            )

            assert result == expected_response
            mock_instance.post.assert_called_once_with(
                f"{client.base_url}/api/v1/orders/submit",
                json={
                    "account_id": "REAL_001",
                    "ts_code": "600519.SH",
                    "direction": "BUY",
                    "order_type": "limit",
                    "price": 180.0,
                    "quantity": 100,
                    "strategy_name": "ma-cross",
                    "source": "AUTO",
                },
            )

    @pytest.mark.asyncio
    async def test_submit_order_no_strategy(self, client):
        """不传 strategy_name 时 payload 中为 None"""
        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_response = MagicMock()
            mock_response.json.return_value = {"success": True}
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response

            result = await client.submit_order(
                account_id="REAL_001",
                ts_code="000001.SZ",
                direction="SELL",
                order_type="market",
                price=12.5,
                quantity=200,
            )
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_submit_order_http_error(self, client):
        """HTTP 请求失败时返回错误响应"""
        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_instance.post.side_effect = Exception("Connection refused")

            result = await client.submit_order(
                account_id="REAL_001",
                ts_code="600519.SH",
                direction="BUY",
                order_type="limit",
                price=180.0,
                quantity=100,
            )

            assert result["success"] is False
            assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_order_timeout(self, client):
        """请求超时返回错误"""
        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_instance.post.side_effect = TimeoutError("Request timed out")

            result = await client.submit_order(
                account_id="REAL_001",
                ts_code="600519.SH",
                direction="BUY",
                order_type="limit",
                price=180.0,
                quantity=100,
            )

            assert result["success"] is False
            assert "timed out" in result["error"].lower()


# =========================================================================
# get_positions
# =========================================================================


class TestGetPositions:
    """get_positions() — 获取持仓"""

    @pytest.mark.asyncio
    async def test_get_positions_success(self, client):
        """成功获取持仓"""
        expected_response = {
            "success": True,
            "data": [{"ts_code": "600519.SH", "quantity": 100, "market_value": 18500.0}],
        }

        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_response = MagicMock()
            mock_response.json.return_value = expected_response
            mock_response.raise_for_status.return_value = None
            mock_instance.get.return_value = mock_response

            result = await client.get_positions(account_id="REAL_001")

            assert result == expected_response
            mock_instance.get.assert_called_once_with(
                f"{client.base_url}/api/v1/positions/",
                params={"account_id": "REAL_001"},
            )

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, client):
        """获取到空持仓列表"""
        expected_response = {"success": True, "data": []}

        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_response = MagicMock()
            mock_response.json.return_value = expected_response
            mock_response.raise_for_status.return_value = None
            mock_instance.get.return_value = mock_response

            result = await client.get_positions(account_id="REAL_001")
            assert result["data"] == []

    @pytest.mark.asyncio
    async def test_get_positions_connection_error(self, client):
        """连接错误时返回错误响应"""
        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_instance.get.side_effect = Exception("ConnectionError: service unavailable")

            result = await client.get_positions(account_id="REAL_001")
            assert result["success"] is False
            assert "unavailable" in result["error"]


# =========================================================================
# check_risk
# =========================================================================


class TestCheckRisk:
    """check_risk() — 交易前风险检查"""

    @pytest.mark.asyncio
    async def test_check_risk_pass(self, client):
        """风险检查通过"""
        expected_response = {"success": True, "risk_level": "low", "allow_trade": True}

        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_response = MagicMock()
            mock_response.json.return_value = expected_response
            mock_response.raise_for_status.return_value = None
            mock_instance.get.return_value = mock_response

            result = await client.check_risk(ts_code="600519.SH")

            assert result == expected_response
            assert result["allow_trade"] is True
            mock_instance.get.assert_called_once_with(
                f"{client.base_url}/api/v1/risk/check/600519.SH"
            )

    @pytest.mark.asyncio
    async def test_check_risk_fail(self, client):
        """风险检查不通过"""
        expected_response = {
            "success": True,
            "risk_level": "high",
            "allow_trade": False,
            "reason": "持仓集中度超限",
        }

        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_response = MagicMock()
            mock_response.json.return_value = expected_response
            mock_response.raise_for_status.return_value = None
            mock_instance.get.return_value = mock_response

            result = await client.check_risk(ts_code="000001.SZ")
            assert result["allow_trade"] is False
            assert "超限" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_risk_request_error(self, client):
        """风险检查请求失败时降级返回"""
        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_instance.get.side_effect = TimeoutError("risk check timed out")

            result = await client.check_risk(ts_code="600519.SH")
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_check_risk_http_500(self, client):
        """服务端 500 错误被捕获"""
        with patch("services.execution_client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            MockClient.return_value = mock_instance

            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = Exception("500 Internal Server Error")
            mock_instance.get.return_value = mock_response

            result = await client.check_risk(ts_code="600519.SH")
            assert result["success"] is False


# =========================================================================
# Client initialization
# =========================================================================


class TestClientInit:
    """ExecutionClient 初始化"""

    def test_default_base_url(self):
        """默认使用配置中的 EXECUTION_SERVICE_URL"""
        from services.execution_client import ExecutionClient

        cli = ExecutionClient()
        assert cli.base_url is not None
        assert cli.timeout == 10.0

    def test_singleton_exists(self):
        """模块级单例 execution_client 存在且是 ExecutionClient 实例"""
        from services.execution_client import ExecutionClient, execution_client

        assert isinstance(execution_client, ExecutionClient)
