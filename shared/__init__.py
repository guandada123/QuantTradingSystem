"""
QTS 共享模块
"""

from .quote_provider import (
    QuoteProvider, TushareQuoteProvider, TdxQuoteProvider,
    AKShareQuoteProvider, QuoteProviderFactory,
    get_quote_provider, set_data_source,
)
