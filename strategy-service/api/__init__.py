"""Strategy Service — API Layer.

Routes:
- stock: Stock pool and fundamental data endpoints
- signal: Trading signal generation and retrieval
- backtest: Backtest execution and result retrieval
- ai: Multi-agent AI analysis orchestration
"""

from .ai import router as ai_router
from .backtest import router as backtest_router
from .signal import router as signal_router
from .stock import router as stock_router

__all__ = ["ai_router", "backtest_router", "signal_router", "stock_router"]
