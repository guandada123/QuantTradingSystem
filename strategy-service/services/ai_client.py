"""
AI模型客户端 v2.0
支持DeepSeek/Kimi/GLM/MiniMax多模型统一调用接口
"""

import json
import logging
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import httpx

logger = logging.getLogger(__name__)

class ModelProvider(Enum):
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    GLM = "glm"
    MINIMAX = "minimax"
    HY3 = "hy3"

@dataclass
class AICallResult:
    """AI调用结果"""
    model: str
    provider: ModelProvider
    success: bool
    content: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost: float
    error: Optional[str] = None

class AIClient:
    """统一AI模型客户端"""
    
    # API端点
    ENDPOINTS = {
        ModelProvider.DEEPSEEK: "https://api.deepseek.com/v1/chat/completions",
        ModelProvider.KIMI: "https://api.moonshot.cn/v1/chat/completions",
        ModelProvider.GLM: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        ModelProvider.MINIMAX: "https://api.minimax.chat/v1/text/chatcompletion_v2",
    }
    
    # 模型价格（美元/1K tokens）
    PRICING = {
        ModelProvider.DEEPSEEK: {'input': 0.00014, 'output': 0.00028},
        ModelProvider.KIMI: {'input': 0.0012, 'output': 0.0012},
        ModelProvider.GLM: {'input': 0.002, 'output': 0.002},
        ModelProvider.MINIMAX: {'input': 0.0005, 'output': 0.0005},
        ModelProvider.HY3: {'input': 0.0001, 'output': 0.0002},
    }
    
    def __init__(self, api_keys: Dict[ModelProvider, str] = None):
        self.api_keys = api_keys or {}
    
    async def call(
        self,
        provider: ModelProvider,
        model_name: str,
        messages: list,
        temperature: float = 0.3,
        max_tokens: int = 2048
    ) -> AICallResult:
        """调用AI模型"""
        if provider not in self.ENDPOINTS and provider != ModelProvider.HY3:
            return AICallResult(model=model_name, provider=provider, success=False, content="",
                              input_tokens=0, output_tokens=0, latency_ms=0, cost=0,
                              error=f"Unsupported provider: {provider}")
        
        api_key = self.api_keys.get(provider)
        if not api_key:
            return AICallResult(model=model_name, provider=provider, success=False, content="",
                              input_tokens=0, output_tokens=0, latency_ms=0, cost=0,
                              error=f"API key not configured for {provider}")
        
        start_time = time.time()
        
        try:
            headers = {"Content-Type": "application/json"}
            
            if provider == ModelProvider.DEEPSEEK:
                headers["Authorization"] = f"Bearer {api_key}"
            elif provider == ModelProvider.KIMI:
                headers["Authorization"] = f"Bearer {api_key}"
            elif provider == ModelProvider.GLM:
                headers["Authorization"] = f"Bearer {api_key}"
            elif provider == ModelProvider.MINIMAX:
                headers["Authorization"] = f"Bearer {api_key}"
                headers["api-key"] = api_key
            
            body = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            url = self.ENDPOINTS.get(provider, self.ENDPOINTS[ModelProvider.DEEPSEEK])
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            content = data['choices'][0]['message']['content']
            usage = data.get('usage', {})
            input_tokens = usage.get('prompt_tokens', 0)
            output_tokens = usage.get('completion_tokens', 0)
            
            # 计算成本
            pricing = self.PRICING.get(provider, {'input': 0.001, 'output': 0.001})
            cost = input_tokens * pricing['input'] / 1000 + output_tokens * pricing['output'] / 1000
            
            logger.info(f"AI调用成功: {provider.value}/{model_name}, {input_tokens}+{output_tokens}tokens, ${cost:.4f}, {latency_ms}ms")
            
            return AICallResult(
                model=model_name, provider=provider, success=True, content=content,
                input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=latency_ms, cost=cost
            )
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"AI调用失败: {provider.value}/{model_name}: {e}")
            return AICallResult(
                model=model_name, provider=provider, success=False, content="",
                input_tokens=0, output_tokens=0, latency_ms=latency_ms, cost=0, error=str(e)
            )

    def call_sync(
        self,
        provider: ModelProvider,
        model_name: str,
        messages: list,
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> AICallResult:
        """
        同步调用AI模型（用于非异步环境）
        """
        if provider not in self.ENDPOINTS and provider != ModelProvider.HY3:
            return AICallResult(model=model_name, provider=provider, success=False, content="",
                              input_tokens=0, output_tokens=0, latency_ms=0, cost=0,
                              error=f"Unsupported provider: {provider}")

        api_key = self.api_keys.get(provider)
        if not api_key:
            return AICallResult(model=model_name, provider=provider, success=False, content="",
                              input_tokens=0, output_tokens=0, latency_ms=0, cost=0,
                              error=f"API key not configured for {provider}")

        start_time = time.time()
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            if provider == ModelProvider.MINIMAX:
                headers["api-key"] = api_key
            body = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            url = self.ENDPOINTS.get(provider, self.ENDPOINTS[ModelProvider.DEEPSEEK])

            import httpx
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()

            latency_ms = int((time.time() - start_time) * 1000)
            content = data['choices'][0]['message']['content']
            usage = data.get('usage', {})
            input_tokens = usage.get('prompt_tokens', 0)
            output_tokens = usage.get('completion_tokens', 0)

            pricing = self.PRICING.get(provider, {'input': 0.001, 'output': 0.001})
            cost = input_tokens * pricing['input'] / 1000 + output_tokens * pricing['output'] / 1000

            logger.info(f"AI调用成功: {provider.value}/{model_name}, {input_tokens}+{output_tokens}tokens, ${cost:.4f}, {latency_ms}ms")

            return AICallResult(
                model=model_name, provider=provider, success=True, content=content,
                input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=latency_ms, cost=cost
            )
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"AI调用失败(sync): {provider.value}/{model_name}: {e}")
            return AICallResult(
                model=model_name, provider=provider, success=False, content="",
                input_tokens=0, output_tokens=0, latency_ms=latency_ms, cost=0, error=str(e)
            )
