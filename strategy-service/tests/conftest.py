"""
strategy-service 测试公共 fixtures 和工具函数。

Usage:
    测试文件无需手动设置 sys.path，conftest.py 自动处理。
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock
from typing import Any

import pytest
from fastapi.testclient import TestClient

# ---- Python Path Setup ----
_TEST_DIR = os.path.dirname(__file__)
_SERVICE_DIR = os.path.join(_TEST_DIR, "..")
sys.path.insert(0, _SERVICE_DIR)

# ---- Environment Cleanup ----
os.environ.pop("DEEPSEEK_API_KEY", None)
os.environ.pop("TUSHARE_TOKEN", None)
os.environ.pop("AKSHARE_TOKEN", None)
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("ENV", "test")


# ============================================================
#  Application Fixtures
# ============================================================

@pytest.fixture(scope="session")
def app():
    """Create the FastAPI application for testing (session-scoped)."""
    from main import app as _app
    return _app


@pytest.fixture
def client(app) -> TestClient:
    """FastAPI TestClient — per-test isolation."""
    return TestClient(app)


# ============================================================
#  Mock Market Data Fixtures
# ============================================================

@pytest.fixture
def mock_stock_quote() -> dict[str, Any]:
    """Mock real-time stock quote data."""
    return {
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "price": 12.50,
        "change_pct": 2.35,
        "volume": 50000000,
        "amount": 625000000.0,
        "high": 12.65,
        "low": 12.20,
    }


@pytest.fixture
def mock_kline_data() -> list[dict[str, Any]]:
    """Mock daily K-line data for the last 5 trading days."""
    return [
        {"date": "2026-06-05", "open": 12.10, "close": 12.30, "high": 12.40, "low": 12.05, "volume": 45000000},
        {"date": "2026-06-08", "open": 12.30, "close": 12.15, "high": 12.50, "low": 12.10, "volume": 52000000},
        {"date": "2026-06-09", "open": 12.15, "close": 12.50, "high": 12.60, "low": 12.10, "volume": 48000000},
        {"date": "2026-06-10", "open": 12.50, "close": 12.35, "high": 12.70, "low": 12.30, "volume": 55000000},
        {"date": "2026-06-11", "open": 12.35, "close": 12.50, "high": 12.60, "low": 12.25, "volume": 50000000},
    ]


@pytest.fixture
def mock_signal_data() -> dict[str, Any]:
    """Mock trading signal."""
    return {
        "ts_code": "000001.SZ",
        "signal_type": "golden_cross",
        "confidence": 0.85,
        "indicators": {
            "ma5": 12.40,
            "ma20": 12.20,
            "rsi": 62.5,
            "macd": 0.15,
        },
    }


# ============================================================
#  Generic Mock Fixtures
# ============================================================

@pytest.fixture
def mock_async_client():
    """Mock httpx.AsyncClient for external API calls."""
    return AsyncMock()


@pytest.fixture
def mock_db_session():
    """Mock SQLAlchemy async session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session
