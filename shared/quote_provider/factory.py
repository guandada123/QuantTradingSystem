"""
QuoteProvider 工厂 + 全局实例管理
"""

import logging
import os
from typing import Any

from shared.quote_provider.akshare import AKShareQuoteProvider
from shared.quote_provider.base import QuoteProvider
from shared.quote_provider.tdx import TdxQuoteProvider
from shared.quote_provider.tushare import TushareQuoteProvider

logger = logging.getLogger(__name__)


class QuoteProviderFactory:
    """行情数据提供者工厂"""

    REGISTRY = {
        "tushare": TushareQuoteProvider,
        "tdx": TdxQuoteProvider,
        "akshare": AKShareQuoteProvider,
    }

    def __init__(self, default_source: str = "tushare", **kwargs):
        self._default_source = default_source
        self._kwargs = kwargs
        self._instances: dict[str, QuoteProvider] = {}

    def get_provider(self, source: str | None = None) -> QuoteProvider:
        """获取指定或默认的数据提供者"""
        source = source or self._default_source
        if source not in self._instances:
            cls = self.REGISTRY.get(source)
            if not cls:
                logger.warning(f"未知数据源 '{source}'，使用 tushare 回退")
                cls = TushareQuoteProvider
            logger.info(f"QuoteProviderFactory: 创建 {source} 提供者")
            self._instances[source] = cls(**self._kwargs.get(source, {}))
        return self._instances[source]

    def set_default_source(self, source: str):
        """动态切换默认数据源"""
        if source not in self.REGISTRY:
            logger.warning(f"未知数据源 '{source}'，忽略切换")
            return
        self._default_source = source
        logger.info(f"QuoteProviderFactory: 默认数据源切换为 {source}")

    @property
    def default(self) -> QuoteProvider:
        return self.get_provider()

    @classmethod
    def register(cls, name: str, provider_cls) -> None:
        """注册自定义提供者"""
        cls.REGISTRY[name] = provider_cls


# 全局工厂实例（延迟初始化）
_factory: QuoteProviderFactory | None = None


def get_quote_provider(source: str | None = None) -> QuoteProvider:
    """获取全局行情提供者"""
    global _factory
    if _factory is None:
        _factory = QuoteProviderFactory(
            default_source=os.getenv("QTS_DATA_SOURCE", "tushare"),
            tdx={"api_url": os.getenv("TDX_CONNECTOR_URL", "")},
            tushare={"token": os.getenv("TUSHARE_TOKEN", "")},
        )
    return _factory.get_provider(source)


def set_data_source(source: str):
    """全局切换数据源"""
    global _factory
    if _factory is None:
        _factory = QuoteProviderFactory(default_source=source)
    else:
        _factory.set_default_source(source)
