"""
services/llm_client.py 单元测试
覆盖: LLMClient 的 chat / analyze_stock / generate_review 方法
"""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest


class TestLLMClientInit:
    """LLMClient 初始化测试"""

    def test_init_with_explicit_values(self):
        """显式传入参数"""
        from services.llm_client import LLMClient

        client = LLMClient(
            api_key="test-key",
            base_url="https://custom.api.com/v1",
            model="test-model",
            timeout=60,
        )
        assert client.api_key == "test-key"
        assert client.base_url == "https://custom.api.com/v1"
        assert client.model == "test-model"
        assert client.timeout == 60

    def test_init_trailing_slash_stripped(self):
        """base_url 末尾斜杠被移除"""
        from services.llm_client import LLMClient

        client = LLMClient(
            api_key="key",
            base_url="https://api.deepseek.com/v1/",
        )
        assert client.base_url == "https://api.deepseek.com/v1"


class TestLLMClientChat:
    """LLMClient.chat() 测试"""

    @pytest.mark.asyncio
    async def test_chat_success(self):
        """基本聊天成功"""
        from services.llm_client import LLMClient

        client = LLMClient(api_key="test-key", base_url="https://test.api/v1")

        mock_response = {
            "choices": [{"message": {"content": "你好！我是AI助手。"}}],
        }
        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(return_value=mock_response)

        with patch("httpx.AsyncClient.post", mock_post):
            result = await client.chat(
                messages=[{"role": "user", "content": "你好"}],
                temperature=0.5,
                max_tokens=100,
            )
            assert result == mock_response
            # 验证请求参数
            call_kwargs = mock_post.call_args
            assert call_kwargs[0][0] == "https://test.api/v1/chat/completions"
            assert call_kwargs[1]["headers"]["Authorization"] == "Bearer test-key"
            assert call_kwargs[1]["json"]["model"] == "deepseek-chat"

    @pytest.mark.asyncio
    @patch("services.llm_client.settings.DEEPSEEK_API_KEY", None)
    async def test_chat_no_api_key_raises(self):
        """API Key 未配置时抛 ValueError"""
        from services.llm_client import LLMClient

        client = LLMClient(api_key=None)
        with pytest.raises(ValueError, match="DEEPSEEK_API_KEY 未配置"):
            await client.chat(messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_http_error(self):
        """HTTP 错误时抛 httpx.HTTPError"""
        import httpx
        from services.llm_client import LLMClient

        client = LLMClient(api_key="test-key", base_url="https://test.api/v1")

        mock_post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized",
                request=MagicMock(),
                response=MagicMock(status_code=401),
            )
        )

        with patch("httpx.AsyncClient.post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await client.chat(messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_default_temperature(self):
        """默认 temperature=0.7, max_tokens=2000"""
        from services.llm_client import LLMClient

        client = LLMClient(api_key="test-key", base_url="https://test.api/v1")
        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(return_value={"choices": []})

        with patch("httpx.AsyncClient.post", mock_post):
            await client.chat(messages=[{"role": "user", "content": "hi"}])
            call_json = mock_post.call_args[1]["json"]
            assert call_json["temperature"] == 0.7
            assert call_json["max_tokens"] == 2000

    @pytest.mark.asyncio
    async def test_chat_custom_parameters(self):
        """自定义 temperature / max_tokens 透传"""
        from services.llm_client import LLMClient

        client = LLMClient(api_key="test-key", base_url="https://test.api/v1")
        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(return_value={"choices": []})

        with patch("httpx.AsyncClient.post", mock_post):
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.1,
                max_tokens=500,
            )
            call_json = mock_post.call_args[1]["json"]
            assert call_json["temperature"] == 0.1
            assert call_json["max_tokens"] == 500


class TestLLMClientAnalyzeStock:
    """LLMClient.analyze_stock() 测试"""

    @pytest.mark.asyncio
    async def test_analyze_stock_success(self):
        """基本股票分析成功"""
        from services.llm_client import LLMClient

        client = LLMClient(api_key="test-key", base_url="https://test.api/v1")

        stock_data = {
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "price": 1880.50,
            "pct_chg": 2.5,
            "vol": 5000000,
            "pe": 35.0,
            "pb": 10.0,
        }

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(
            return_value={
                "choices": [{"message": {"content": "贵州茅台技术面表现强势..."}}],
            }
        )

        with patch("httpx.AsyncClient.post", mock_post):
            result = await client.analyze_stock(stock_data)
            assert result == "贵州茅台技术面表现强势..."
            # 验证 prompt 包含股票数据
            call_json = mock_post.call_args[1]["json"]
            assert "贵州茅台" in call_json["messages"][0]["content"]
            assert "600519.SH" in call_json["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_analyze_stock_missing_fields(self):
        """缺少字段时使用默认值"""
        from services.llm_client import LLMClient

        client = LLMClient(api_key="test-key", base_url="https://test.api/v1")

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(
            return_value={
                "choices": [{"message": {"content": "分析结果"}}],
            }
        )

        with patch("httpx.AsyncClient.post", mock_post):
            result = await client.analyze_stock({"ts_code": "000001.SZ"})
            assert result == "分析结果"

    @pytest.mark.asyncio
    async def test_analyze_stock_empty_response(self):
        """API 返回空 choices"""
        from services.llm_client import LLMClient

        client = LLMClient(api_key="test-key", base_url="https://test.api/v1")

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(return_value={"choices": []})

        with patch("httpx.AsyncClient.post", mock_post):
            result = await client.analyze_stock({"ts_code": "000001.SZ"})
            assert result == ""


class TestLLMClientGenerateReview:
    """LLMClient.generate_review() 测试"""

    @pytest.mark.asyncio
    async def test_generate_review_success(self):
        """基本复盘生成成功"""
        from services.llm_client import LLMClient

        client = LLMClient(api_key="test-key", base_url="https://test.api/v1")

        market_data = {
            "indices": [{"name": "上证指数", "close": 3200}],
            "sectors": [{"name": "半导体", "pct_chg": 3.5}],
            "advance": 2500,
            "decline": 1500,
            "north_flow": 50.5,
            "volume": 8500,
        }

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(
            return_value={
                "choices": [{"message": {"content": "今日大盘震荡上行..."}}],
            }
        )

        with patch("httpx.AsyncClient.post", mock_post):
            result = await client.generate_review(market_data)
            assert result == "今日大盘震荡上行..."
            call_json = mock_post.call_args[1]["json"]
            assert "上证指数" in call_json["messages"][0]["content"]
            assert "半导体" in call_json["messages"][0]["content"]
            assert "50.5" in call_json["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_generate_review_empty_market_data(self):
        """空市场数据时仍然生成"""
        from services.llm_client import LLMClient

        client = LLMClient(api_key="test-key", base_url="https://test.api/v1")

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = MagicMock(
            return_value={
                "choices": [{"message": {"content": "无数据"}}],
            }
        )

        with patch("httpx.AsyncClient.post", mock_post):
            result = await client.generate_review({})
            assert result == "无数据"
