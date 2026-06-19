"""
AIClient 的单元测试

测试 services/ai_client.py 的 AI 模型调用逻辑：
- AIClient 初始化
- call() 异步调用 — 成功/失败路径
- call_sync() 同步调用 — 成功/失败路径
- ModelProvider 枚举
- 成本计算

使用 @patch("services.ai_client.httpx.AsyncClient") 和
@patch("services.ai_client.httpx.Client") 模拟 HTTP 请求。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.ai_client import AICallResult, AIClient, ModelProvider

# =========================================================================
# ModelProvider 枚举
# =========================================================================


class TestModelProvider:
    """ModelProvider 枚举值与成员"""

    def test_enum_values(self):
        """所有枚举成员有正确值"""
        assert ModelProvider.DEEPSEEK.value == "deepseek"
        assert ModelProvider.KIMI.value == "kimi"
        assert ModelProvider.GLM.value == "glm"
        assert ModelProvider.MINIMAX.value == "minimax"
        assert ModelProvider.HY3.value == "hy3"

    def test_enum_members(self):
        """所有预期成员都存在"""
        expected = {"DEEPSEEK", "KIMI", "GLM", "MINIMAX", "HY3"}
        assert set(m.name for m in ModelProvider) == expected


# =========================================================================
# AICallResult 数据类
# =========================================================================


class TestAICallResult:
    """AICallResult dataclass 基本行为"""

    def test_default_error_is_none(self):
        """error 字段默认为 None"""
        result = AICallResult(
            model="deepseek-chat",
            provider=ModelProvider.DEEPSEEK,
            success=True,
            content="test",
            input_tokens=10,
            output_tokens=20,
            latency_ms=100,
            cost=0.001,
        )
        assert result.error is None

    def test_error_can_be_set(self):
        """可以提供 error 信息"""
        result = AICallResult(
            model="deepseek-chat",
            provider=ModelProvider.DEEPSEEK,
            success=False,
            content="",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            cost=0,
            error="API key missing",
        )
        assert result.error == "API key missing"


# =========================================================================
# AIClient 初始化
# =========================================================================


class TestAIClientInit:
    """AIClient 初始化"""

    def test_default_no_keys(self):
        """不传 api_keys 时初始化为空字典"""
        client = AIClient()
        assert client.api_keys == {}

    def test_custom_api_keys(self):
        """传入 api_keys 时正确保存"""
        keys = {
            ModelProvider.DEEPSEEK: "sk-test-key",
            ModelProvider.KIMI: "kimi-test-key",
        }
        client = AIClient(api_keys=keys)
        assert client.api_keys[ModelProvider.DEEPSEEK] == "sk-test-key"
        assert client.api_keys[ModelProvider.KIMI] == "kimi-test-key"
        assert ModelProvider.GLM not in client.api_keys

    def test_endpoints_and_pricing_are_class_vars(self):
        """ENDPOINTS 和 PRICING 是类变量"""
        assert len(AIClient.ENDPOINTS) == 4  # HY3 无独立端点
        assert len(AIClient.PRICING) == 5  # 所有 5 个 provider 都有定价


# =========================================================================
# AIClient.call() — async 调用
# =========================================================================


class TestCall:
    """AIClient.call() — 异步 AI 模型调用"""

    @pytest.fixture
    def client(self):
        """带 DeepSeek 密钥的 AIClient 实例"""
        return AIClient(api_keys={ModelProvider.DEEPSEEK: "sk-test-key"})

    # ---- 辅助方法 ----

    def _make_mock_async_client(self, response_json=None):
        """创建 Mock httpx.AsyncClient (async context manager)"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = response_json or {}
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response
        return mock_client

    # ---- 成功路径 ----

    @pytest.mark.asyncio
    async def test_call_success(self, client):
        """成功调用 DeepSeek 返回完整 AICallResult"""
        mock_response_data = {
            "choices": [{"message": {"content": "Hello from AI"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 100},
        }
        mock_client = self._make_mock_async_client(mock_response_data)

        with patch("services.ai_client.httpx.AsyncClient", return_value=mock_client):
            result = await client.call(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[{"role": "user", "content": "Hi"}],
            )

        assert result.success is True
        assert result.content == "Hello from AI"
        assert result.input_tokens == 50
        assert result.output_tokens == 100
        assert result.latency_ms >= 0
        # cost = 50*0.00014/1000 + 100*0.00028/1000 = 0.000035
        assert result.cost == pytest.approx(3.5e-5, rel=1e-6)
        assert result.model == "deepseek-chat"
        assert result.provider == ModelProvider.DEEPSEEK
        assert result.error is None

    @pytest.mark.asyncio
    async def test_call_authorization_header(self, client):
        """验证 Authorization header 被正确设置"""
        mock_client = self._make_mock_async_client(
            {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        )

        with patch("services.ai_client.httpx.AsyncClient", return_value=mock_client):
            await client.call(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[{"role": "user", "content": "Hi"}],
            )

        _, kwargs = mock_client.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test-key"
        assert kwargs["headers"]["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_call_minimax_additional_header(self, client):
        """MiniMax 额外发送 api-key header"""
        minimax_client = AIClient(api_keys={ModelProvider.MINIMAX: "mm-test-key"})
        mock_client = self._make_mock_async_client(
            {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        )

        with patch("services.ai_client.httpx.AsyncClient", return_value=mock_client):
            await minimax_client.call(
                provider=ModelProvider.MINIMAX,
                model_name="minimax-chat",
                messages=[{"role": "user", "content": "Hi"}],
            )

        _, kwargs = mock_client.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer mm-test-key"
        assert kwargs["headers"]["api-key"] == "mm-test-key"

    @pytest.mark.asyncio
    async def test_call_request_body(self, client):
        """验证请求 body 包含 model/messages/temperature/max_tokens"""
        mock_client = self._make_mock_async_client(
            {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        )

        with patch("services.ai_client.httpx.AsyncClient", return_value=mock_client):
            await client.call(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[{"role": "user", "content": "Hi"}],
                temperature=0.7,
                max_tokens=1024,
            )

        _, kwargs = mock_client.post.call_args
        body = kwargs["json"]
        assert body["model"] == "deepseek-chat"
        assert body["messages"] == [{"role": "user", "content": "Hi"}]
        assert body["temperature"] == 0.7
        assert body["max_tokens"] == 1024

    @pytest.mark.asyncio
    async def test_call_usage_fallback_zero(self, client):
        """usage 缺失时 input/output_tokens 默认 0"""
        mock_client = self._make_mock_async_client(
            {"choices": [{"message": {"content": "no usage data"}}]}
        )

        with patch("services.ai_client.httpx.AsyncClient", return_value=mock_client):
            result = await client.call(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[],
            )

        assert result.success is True
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.cost == 0.0

    # ---- 失败路径 ----

    @pytest.mark.asyncio
    async def test_call_unsupported_provider(self, client):
        """不支持的 provider 返回错误结果"""
        # 使用字符串而非 ModelProvider 枚举来模拟未知 provider
        result = await client.call(
            provider="unknown_provider",  # type: ignore[arg-type]
            model_name="test",
            messages=[],
        )
        assert result.success is False
        assert result.error is not None
        assert "Unsupported provider" in result.error

    @pytest.mark.asyncio
    async def test_call_missing_api_key(self):
        """未配置 API key 的 provider 返回错误"""
        client = AIClient()  # 无任何 key
        result = await client.call(
            provider=ModelProvider.DEEPSEEK,
            model_name="deepseek-chat",
            messages=[],
        )
        assert result.success is False
        assert result.error is not None
        assert "API key not configured" in result.error

    @pytest.mark.asyncio
    async def test_call_http_error(self, client):
        """HTTP 请求失败（如 401）被捕获"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")
        mock_client.post.return_value = mock_response

        with patch("services.ai_client.httpx.AsyncClient", return_value=mock_client):
            result = await client.call(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[],
            )

        assert result.success is False
        assert result.error is not None
        assert "401" in result.error

    @pytest.mark.asyncio
    async def test_call_network_error(self, client):
        """网络异常被捕获（如 DNS 解析失败）"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.side_effect = ConnectionError("DNS resolution failed")

        with patch("services.ai_client.httpx.AsyncClient", return_value=mock_client):
            result = await client.call(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[],
            )

        assert result.success is False
        assert result.error is not None
        assert "DNS resolution failed" in result.error
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_call_hy3_without_key_returns_error(self):
        """HY3 provider 无 key 时返回错误（HY3 允许但需要 key）"""
        client = AIClient()
        result = await client.call(
            provider=ModelProvider.HY3,
            model_name="hy3-chat",
            messages=[],
        )
        assert result.success is False
        assert result.error is not None
        assert "API key not configured" in result.error


# =========================================================================
# AIClient.call_sync() — 同步调用
# =========================================================================


class TestCallSync:
    """AIClient.call_sync() — 同步 AI 模型调用"""

    @pytest.fixture
    def client(self):
        """带 DeepSeek 密钥的 AIClient 实例"""
        return AIClient(api_keys={ModelProvider.DEEPSEEK: "sk-test-key"})

    # ---- 辅助方法 ----

    def _make_mock_sync_client(self, response_json=None):
        """创建 Mock httpx.Client (sync context manager)"""
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = response_json or {}
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response
        return mock_client

    # ---- 成功路径 ----

    def test_call_sync_success(self, client):
        """同步调用成功返回完整结果"""
        mock_response_data = {
            "choices": [{"message": {"content": "sync response"}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 60},
        }
        mock_client = self._make_mock_sync_client(mock_response_data)

        with patch("services.ai_client.httpx.Client", return_value=mock_client):
            result = client.call_sync(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[{"role": "user", "content": "Hi"}],
            )

        assert result.success is True
        assert result.content == "sync response"
        assert result.input_tokens == 30
        assert result.output_tokens == 60
        assert result.model == "deepseek-chat"
        assert result.provider == ModelProvider.DEEPSEEK

    def test_call_sync_default_max_tokens(self, client):
        """call_sync 默认 max_tokens 为 4096"""
        mock_client = self._make_mock_sync_client(
            {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        )

        with patch("services.ai_client.httpx.Client", return_value=mock_client):
            client.call_sync(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[],
            )

        _, kwargs = mock_client.post.call_args
        assert kwargs["json"]["max_tokens"] == 4096

    # ---- 失败路径 ----

    def test_call_sync_unsupported_provider(self, client):
        """同步调用不支持的 provider"""
        result = client.call_sync(
            provider="unknown",  # type: ignore[arg-type]
            model_name="test",
            messages=[],
        )
        assert result.success is False
        assert result.error is not None
        assert "Unsupported provider" in result.error

    def test_call_sync_missing_api_key(self):
        """同步调用未配置 key"""
        client = AIClient()
        result = client.call_sync(
            provider=ModelProvider.DEEPSEEK,
            model_name="deepseek-chat",
            messages=[],
        )
        assert result.success is False
        assert result.error is not None
        assert "API key not configured" in result.error

    def test_call_sync_http_error(self, client):
        """同步调用 HTTP 错误被捕获"""
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("500 Server Error")
        mock_client.post.return_value = mock_response

        with patch("services.ai_client.httpx.Client", return_value=mock_client):
            result = client.call_sync(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[],
            )

        assert result.success is False
        assert "500" in (result.error or "")

    def test_call_sync_network_error(self, client):
        """同步调用网络异常被捕获"""
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = ConnectionError("Timeout connecting")

        with patch("services.ai_client.httpx.Client", return_value=mock_client):
            result = client.call_sync(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[],
            )

        assert result.success is False
        assert result.error is not None
        assert "Timeout" in result.error
        assert result.latency_ms >= 0


# =========================================================================
# 成本计算
# =========================================================================


class TestCostCalculation:
    """各种 provider 的成本计算验证"""

    def test_cost_deepseek(self):
        """DeepSeek: input*0.00014 + output*0.00028 每 1K"""
        pricing = AIClient.PRICING[ModelProvider.DEEPSEEK]
        cost = 100 * pricing["input"] / 1000 + 200 * pricing["output"] / 1000
        assert cost == pytest.approx(0.00007, rel=1e-6)

    def test_cost_kimi(self):
        """Kimi: input/output 统一 0.0012 每 1K"""
        pricing = AIClient.PRICING[ModelProvider.KIMI]
        cost = 500 * pricing["input"] / 1000 + 300 * pricing["output"] / 1000
        assert cost == pytest.approx(0.00096, rel=1e-6)

    def test_cost_glm(self):
        """GLM: input/output 统一 0.002 每 1K"""
        pricing = AIClient.PRICING[ModelProvider.GLM]
        cost = 1000 * pricing["input"] / 1000 + 500 * pricing["output"] / 1000
        # = 1000*0.002/1000 + 500*0.002/1000 = 0.002 + 0.001 = 0.003
        assert cost == pytest.approx(0.003, rel=1e-6)

    def test_cost_minimax(self):
        """MiniMax: input/output 统一 0.0005 每 1K"""
        pricing = AIClient.PRICING[ModelProvider.MINIMAX]
        cost = 200 * pricing["input"] / 1000 + 300 * pricing["output"] / 1000
        assert cost == pytest.approx(0.00025, rel=1e-6)

    def test_cost_hy3(self):
        """HY3: input 0.0001, output 0.0002 每 1K"""
        pricing = AIClient.PRICING[ModelProvider.HY3]
        cost = 1000 * pricing["input"] / 1000 + 500 * pricing["output"] / 1000
        # = 1000*0.0001/1000 + 500*0.0002/1000 = 0.0001 + 0.0001 = 0.0002
        assert cost == pytest.approx(0.0002, rel=1e-6)


# =========================================================================
# HY3 特殊处理
# =========================================================================


class TestHY3Provider:
    """HY3 provider 特殊逻辑（有枚举、有定价、无独立端点）"""

    def test_hy3_not_in_endpoints(self):
        """HY3 不在 ENDPOINTS 字典中"""
        assert ModelProvider.HY3 not in AIClient.ENDPOINTS

    def test_hy3_has_pricing(self):
        """HY3 在 PRICING 字典中有定价"""
        assert ModelProvider.HY3 in AIClient.PRICING
        assert AIClient.PRICING[ModelProvider.HY3]["input"] == 0.0001
        assert AIClient.PRICING[ModelProvider.HY3]["output"] == 0.0002

    @pytest.mark.asyncio
    async def test_hy3_with_key_fallsback_to_deepseek_endpoint(self):
        """HY3 有 key 时 URL fallback 到 DeepSeek 端点"""
        client = AIClient(api_keys={ModelProvider.HY3: "hy3-test-key"})
        mock_response_data = {
            "choices": [{"message": {"content": "hy3 ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }
        mock_async = AsyncMock()
        mock_async.__aenter__.return_value = mock_async
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response_data
        mock_resp.raise_for_status.return_value = None
        mock_async.post.return_value = mock_resp

        with patch("services.ai_client.httpx.AsyncClient", return_value=mock_async):
            result = await client.call(
                provider=ModelProvider.HY3,
                model_name="hy3-chat",
                messages=[],
            )

        assert result.success is True
        assert result.content == "hy3 ok"
        # 验证 URL fallback 到 DeepSeek 端点（url 是位置参数）
        call_args = mock_async.post.call_args
        assert call_args is not None
        assert "api.deepseek.com" in str(call_args[0][0])

        # 成本使用 HY3 定价计算
        expected_cost = 10 * 0.0001 / 1000 + 10 * 0.0002 / 1000
        assert result.cost == pytest.approx(expected_cost, rel=1e-6)
