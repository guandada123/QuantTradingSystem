"""Strategy Service — API Layer.

Routes:
- stock: Stock pool and fundamental data endpoints
- signal: Trading signal generation and retrieval
- backtest: Backtest execution and result retrieval
- ai: Multi-agent AI analysis orchestration
"""

# 注意：backtest.py 已废弃（v2 引擎在 backtest_v2.py），由 main.py 直接导入
from .ai import router as ai_router
from .signal import router as signal_router
from .stock import router as stock_router

__all__ = ["ai_router", "signal_router", "stock_router"]
