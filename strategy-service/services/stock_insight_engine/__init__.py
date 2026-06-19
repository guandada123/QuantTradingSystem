"""
Stock Insight 选股引擎包

外部导入保持兼容：
    from services.stock_insight_engine import StockInsightEngine, get_stock_insight_engine
"""

from .engine import StockInsightEngine, get_stock_insight_engine

__all__ = ["StockInsightEngine", "get_stock_insight_engine"]
