"""
QTS 共享模块
"""

from .quote_provider import (
    AKShareQuoteProvider,
    QuoteProvider,
    QuoteProviderFactory,
    TdxQuoteProvider,
    TushareQuoteProvider,
    get_quote_provider,
    set_data_source,
)
