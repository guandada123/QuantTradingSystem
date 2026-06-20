"""
LLM客户端 — 封装 DeepSeek API 调用
提供选股分析、每日复盘等 AI 能力
"""

import json
import logging
from typing import Any

from core.config import settings
import httpx

logger = logging.getLogger(__name__)


class LLMClient:
    """DeepSeek AI 模型调用客户端

    通过 httpx.AsyncClient 直接调用 DeepSeek chat/completions API
    （不使用 openai 库，避免额外依赖）
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 30,
    ):
        self.api_key = api_key or settings.DEEPSEEK_API_KEY
        self.base_url = (base_url or settings.DEEPSEEK_BASE_URL).rstrip("/")
        self.model = model or settings.DEEPSEEK_MODEL
        self.timeout = timeout or settings.AI_TIMEOUT_SECONDS

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        """调用 DeepSeek chat/completions API

        Args:
            messages: 对话消息列表 [{"role": "user", "content": "..."}]
            temperature: 生成温度 (0-1)
            max_tokens: 最大输出 token 数

        Returns:
            DeepSeek API 完整响应

        Raises:
            ValueError: API Key 未配置
            httpx.HTTPError: API 调用失败
        """
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY 未配置，请在 .env 中设置")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            resp_data: dict[str, Any] = response.json()
            return resp_data

    async def analyze_stock(self, stock_data: dict) -> str:
        """AI 分析单只股票

        从技术面和基本面两个维度给出简要分析。
        返回纯文本分析结果（300字以内）。
        """
        prompt = (
            "请对以下A股股票进行技术面和基本面分析：\n\n"
            f"股票代码: {stock_data.get('ts_code', 'N/A')}\n"
            f"股票名称: {stock_data.get('name', 'N/A')}\n"
            f"最新价格: {stock_data.get('price', 'N/A')}\n"
            f"涨跌幅: {stock_data.get('pct_chg', 'N/A')}%\n"
            f"成交量: {stock_data.get('vol', 'N/A')}\n"
            f"市盈率: {stock_data.get('pe', 'N/A')}\n"
            f"市净率: {stock_data.get('pb', 'N/A')}\n\n"
            "请从以下维度分析（300字以内，用中文）：\n"
            "1. 技术面趋势判断\n"
            "2. 基本面概况\n"
            "3. 短期风险提示\n"
            "4. 操作建议"
        )

        result = await self.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=500,
        )
        try:
            content: str = (result.get("choices") or [{}])[0].get("message", {}).get("content", "")
            return content
        except (IndexError, AttributeError, KeyError):
            return ""

    async def generate_review(self, market_data: dict) -> str:
        """生成每日复盘报告

        基于市场数据（指数、板块、资金流向等）生成结构化复盘。
        返回纯文本复盘报告（500字以内）。
        """
        prompt = (
            "请根据以下A股市场数据生成今日复盘报告：\n\n"
            "大盘指数:\n"
            f"{json.dumps(market_data.get('indices', []), ensure_ascii=False, indent=2)}\n\n"
            "行业板块:\n"
            f"{json.dumps(market_data.get('sectors', []), ensure_ascii=False, indent=2)}\n\n"
            f"涨跌家数: 上涨 {market_data.get('advance', 0)} 家，"
            f"下跌 {market_data.get('decline', 0)} 家\n"
            f"北向资金: {market_data.get('north_flow', 'N/A')} 亿元\n"
            f"成交额: {market_data.get('volume', 'N/A')} 亿元\n\n"
            "请生成包含以下内容的复盘报告（500字以内，用中文）：\n"
            "1. 大盘走势回顾\n"
            "2. 热点板块分析\n"
            "3. 资金面概况\n"
            "4. 明日展望"
        )

        result = await self.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1000,
        )
        try:
            content: str = (result.get("choices") or [{}])[0].get("message", {}).get("content", "")
            return content
        except (IndexError, AttributeError, KeyError):
            return ""
