"""
services/strategy_client.py 单元测试
覆盖: StrategyClient 的 scan_stocks / get_strategy_config 方法
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestStrategyClientInit:
    """StrategyClient 初始化测试"""

    def test_init_default_base_url(self):
        """默认 base_url 来自 settings"""
        from services.strategy_client import StrategyClient

        client = StrategyClient()
        assert "strategy-service" in client.base_url
        assert client.timeout == 30

    def test_init_custom_base_url(self):
        """自定义 base_url"""
        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:18000", timeout=60)
        assert client.base_url == "http://localhost:18000"
        assert client.timeout == 60

    def test_init_trailing_slash_stripped(self):
        """末尾斜杠被移除"""
        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:8000/")
        assert client.base_url == "http://localhost:8000"


class TestStrategyClientScanStocks:
    """StrategyClient.scan_stocks() 测试"""

    @pytest.mark.asyncio
    async def test_scan_basic(self):
        """基本扫描调用"""
        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:18000")

        mock_candidates = [
            {"ts_code": "600519.SH", "name": "贵州茅台", "price": 1880.0},
            {"ts_code": "000858.SZ", "name": "五粮液", "price": 168.0},
        ]

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(
            return_value={"data": mock_candidates},
        )

        with patch("httpx.AsyncClient.post", mock_post):
            result = await client.scan_stocks(limit=50)
            assert result == mock_candidates
            # 验证请求 URL 和参数
            call_args = mock_post.call_args
            assert call_args[0][0] == "http://localhost:18000/api/v1/strategies/scan"
            assert call_args[1]["json"]["limit"] == 50

    @pytest.mark.asyncio
    async def test_scan_with_strategy_ids(self):
        """带 strategy_ids 参数"""
        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:18000")

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(return_value={"data": []})

        with patch("httpx.AsyncClient.post", mock_post):
            await client.scan_stocks(
                limit=20,
                strategy_ids=["ma-cross", "breakout"],
                ts_codes=["600519.SH"],
            )
            call_json = mock_post.call_args[1]["json"]
            assert call_json["strategy_ids"] == ["ma-cross", "breakout"]
            assert call_json["ts_codes"] == ["600519.SH"]
            assert call_json["limit"] == 20

    @pytest.mark.asyncio
    async def test_scan_without_strategy_ids(self):
        """不传 strategy_ids 时不应出现在请求体中"""
        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:18000")

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(return_value={"data": []})

        with patch("httpx.AsyncClient.post", mock_post):
            await client.scan_stocks(limit=100)
            call_json = mock_post.call_args[1]["json"]
            assert "strategy_ids" not in call_json
            assert "ts_codes" not in call_json

    @pytest.mark.asyncio
    async def test_scan_uses_results_fallback(self):
        """兼容 'results' 键的响应格式"""
        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:18000")

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(
            return_value={"results": [{"ts_code": "000001.SZ"}]},
        )

        with patch("httpx.AsyncClient.post", mock_post):
            result = await client.scan_stocks()
            assert result == [{"ts_code": "000001.SZ"}]

    @pytest.mark.asyncio
    async def test_scan_empty_list(self):
        """空结果"""
        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:18000")

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(return_value={"data": []})

        with patch("httpx.AsyncClient.post", mock_post):
            result = await client.scan_stocks()
            assert result == []

    @pytest.mark.asyncio
    async def test_scan_http_error(self):
        """HTTP 错误时抛异常"""
        import httpx

        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:18000")

        mock_post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "502 Bad Gateway",
            request=MagicMock(),
            response=MagicMock(status_code=502),
        ))

        with patch("httpx.AsyncClient.post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await client.scan_stocks()


class TestStrategyClientGetStrategyConfig:
    """StrategyClient.get_strategy_config() 测试"""

    @pytest.mark.asyncio
    async def test_get_config_success(self):
        """获取策略配置成功"""
        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:18000")

        mock_config = {
            "id": "ma-cross",
            "name": "双均线金叉",
            "params": {"fast": 5, "slow": 20},
        }

        mock_get = AsyncMock()
        mock_get.return_value.status_code = 200
        mock_get.return_value.json = MagicMock(
            return_value={"data": mock_config},
        )

        with patch("httpx.AsyncClient.get", mock_get):
            result = await client.get_strategy_config("ma-cross")
            assert result == mock_config
            call_args = mock_get.call_args
            assert "ma-cross" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_config_not_found(self):
        """策略不存在返回空 dict"""
        from services.strategy_client import StrategyClient

        client = StrategyClient(base_url="http://localhost:18000")

        mock_get = AsyncMock()
        mock_get.return_value.status_code = 200
        mock_get.return_value.json = MagicMock(return_value={"data": {}})

        with patch("httpx.AsyncClient.get", mock_get):
            result = await client.get_strategy_config("nonexistent-strategy")
            assert result == {}
