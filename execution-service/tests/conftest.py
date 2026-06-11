"""
execution-service 测试公共 fixtures 和工具函数。
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock
from typing import Any

import pytest

# ---- Python Path Setup ----
_TEST_DIR = os.path.dirname(__file__)
_SERVICE_DIR = os.path.join(_TEST_DIR, "..")
sys.path.insert(0, _SERVICE_DIR)

# ---- Environment Cleanup ----
os.environ.pop("MINIQMT_USER", None)
os.environ.pop("MINIQMT_PASSWORD", None)
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
def client(app):
    """FastAPI TestClient — per-test isolation."""
    from fastapi.testclient import TestClient
    return TestClient(app)


# ============================================================
#  Mock Order Fixtures
# ============================================================

@pytest.fixture
def mock_order() -> dict[str, Any]:
    """Mock buy order data."""
    return {
        "order_id": "ord_test_001",
        "ts_code": "000001.SZ",
        "direction": "BUY",
        "quantity": 100,
        "price": 12.50,
        "status": "PENDING",
        "created_at": "2026-06-11T10:00:00",
    }


@pytest.fixture
def mock_order_book() -> list[dict[str, Any]]:
    """Mock order book (bid/ask depth)."""
    return {
        "ts_code": "000001.SZ",
        "bids": [
            {"price": 12.49, "volume": 5000},
            {"price": 12.48, "volume": 10000},
            {"price": 12.47, "volume": 8000},
        ],
        "asks": [
            {"price": 12.51, "volume": 3000},
            {"price": 12.52, "volume": 12000},
            {"price": 12.53, "volume": 6000},
        ],
    }


@pytest.fixture
def mock_position() -> dict[str, Any]:
    """Mock position data."""
    return {
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "quantity": 500,
        "avg_cost": 12.00,
        "current_price": 12.50,
        "market_value": 6250.00,
        "unrealized_pnl": 250.00,
        "pnl_pct": 4.17,
    }


# ============================================================
#  Mock MiniQMT Fixtures
# ============================================================

@pytest.fixture
def mock_miniqmt_connector():
    """Mock MiniQMT connector with simulated responses."""
    from unittest.mock import AsyncMock

    connector = AsyncMock()
    connector.connect = AsyncMock(return_value=True)
    connector.disconnect = AsyncMock()
    connector.is_connected = MagicMock(return_value=True)
    connector.buy = AsyncMock(return_value={
        "order_id": "ord_mock_001",
        "status": "SUBMITTED",
    })
    connector.sell = AsyncMock(return_value={
        "order_id": "ord_mock_002",
        "status": "SUBMITTED",
    })
    connector.cancel_order = AsyncMock(return_value=True)
    connector.get_positions = AsyncMock(return_value=[])
    connector.get_balance = AsyncMock(return_value={"available": 30000.00})
    return connector


# ============================================================
#  Generic Mock Fixtures
# ============================================================

@pytest.fixture
def mock_db_session():
    """Mock SQLAlchemy async session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session
