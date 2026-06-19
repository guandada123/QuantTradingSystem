"""
统一行情数据提供者接口 v1.0

定义 QuoteProvider ABC，支持 Tushare、通达信、AKShare 数据源切换。
使用工厂模式 + 配置驱动，运行时动态切换。
"""

from shared.quote_provider.akshare import AKShareQuoteProvider
from shared.quote_provider.base import QuoteProvider
from shared.quote_provider.factory import (
    QuoteProviderFactory,
    get_quote_provider,
    set_data_source,
)
from shared.quote_provider.tdx import TdxQuoteProvider
from shared.quote_provider.tushare import TushareQuoteProvider

__all__ = [
    "QuoteProvider",
    "TushareQuoteProvider",
    "TdxQuoteProvider",
    "AKShareQuoteProvider",
    "QuoteProviderFactory",
    "get_quote_provider",
    "set_data_source",
]
