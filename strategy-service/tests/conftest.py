"""
strategy-service 测试公共 fixtures 和工具函数。

Usage:
    测试文件无需手动设置 sys.path，conftest.py 自动处理。
"""

import os
import sys
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

# ---- Python Path Setup ----
_TEST_DIR = os.path.realpath(os.path.dirname(__file__))
_SERVICE_DIR = os.path.realpath(os.path.join(_TEST_DIR, ".."))
_QTS_ROOT = os.path.realpath(os.path.join(_SERVICE_DIR, ".."))  # QuantTradingSystem root / host

# shared/ 位置检测：
#   Host 环境: _QTS_ROOT/shared （如 /Users/guan/WorkBuddy/QuantTradingSystem/shared）
#   容器环境: _SERVICE_DIR/shared （docker-compose 将 ./shared 挂载为 /app/shared）
_SHARED_DIR = os.path.join(_QTS_ROOT, "shared")
if not os.path.isfile(os.path.join(_SHARED_DIR, "auth.py")):
    _SHARED_DIR = os.path.join(_SERVICE_DIR, "shared")
    _QTS_ROOT = _SERVICE_DIR  # 容器中无上级项目根，QTS root ≈ /app

sys.path.insert(0, _QTS_ROOT)
sys.path.insert(0, _SERVICE_DIR)

# 强制 shared 包指向正确的共享目录，避免 strategy-service/shared/ stub 干扰
import shared  # type: ignore[import-untyped]

shared.__path__ = [_SHARED_DIR]

# ---- Environment Cleanup & Database Setup ----
os.environ.pop("DEEPSEEK_API_KEY", None)
os.environ.pop("TUSHARE_TOKEN", None)
os.environ.pop("AKSHARE_TOKEN", None)
os.environ.pop("REDIS_URL", None)
os.environ.pop("REDIS_SENTINEL_HOSTS", None)
os.environ.pop("REDIS_SENTINEL_SERVICE_NAME", None)
os.environ.pop("REDIS_SENTINEL_SOCKET_TIMEOUT", None)
os.environ.setdefault("ENV", "test")

# 指向 strategy-service/quant_trading.db（该 DB 有完整表结构）
# 根目录的 quant_trading.db 是空文件，会导致 trades/accounts 等表缺失错误
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_SERVICE_DIR, 'quant_trading.db')}"

# CI 环境没有预置的 quant_trading.db，手动创建所有表
try:
    from models.database import Base
    from models.models import Account, Order, Position, Trade  # noqa: F401 — 注册 ORM 模型
    from sqlalchemy import create_engine as _ce

    _engine = _ce(os.environ["DATABASE_URL"])
    Base.metadata.create_all(_engine)
    _engine.dispose()
except Exception:
    pass


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
        {
            "date": "2026-06-05",
            "open": 12.10,
            "close": 12.30,
            "high": 12.40,
            "low": 12.05,
            "volume": 45000000,
        },
        {
            "date": "2026-06-08",
            "open": 12.30,
            "close": 12.15,
            "high": 12.50,
            "low": 12.10,
            "volume": 52000000,
        },
        {
            "date": "2026-06-09",
            "open": 12.15,
            "close": 12.50,
            "high": 12.60,
            "low": 12.10,
            "volume": 48000000,
        },
        {
            "date": "2026-06-10",
            "open": 12.50,
            "close": 12.35,
            "high": 12.70,
            "low": 12.30,
            "volume": 55000000,
        },
        {
            "date": "2026-06-11",
            "open": 12.35,
            "close": 12.50,
            "high": 12.60,
            "low": 12.25,
            "volume": 50000000,
        },
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
