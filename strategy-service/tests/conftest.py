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

# 尽早导入 numpy/pandas，避免 pytest-cov 激活后重复加载导致 DataFrame 损坏
import numpy as np  # noqa: F401 — 防止 cov 追踪时重载
import pandas as pd  # noqa: F401
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
sys.path.insert(0, _TEST_DIR)

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
import logging as _logging

_seed_logger = _logging.getLogger("conftest.seed")
_SEED_DATA_TABLES_CREATED = False  # 标志位：供测试判断是否可依赖种子数据

try:
    from datetime import date, datetime, time

    from models.database import Base
    from models.models import (  # noqa: F401 — 注册 ORM 模型
        Account,
        Order,
        Position,
        StockPool,
        Trade,
    )
    from sqlalchemy import create_engine as _ce
    from sqlalchemy.orm import Session as _SESession
    from uuid_compat import make_uuid_sqlite_compat

    # 在创建表之前应用 UUID 补丁，确保 SQLite 正确存储 UUID 列
    try:
        _replaced = make_uuid_sqlite_compat()
        _seed_logger.info("UUID 兼容补丁已应用，替换了 %d 列", _replaced)
    except Exception as _e:
        _seed_logger.warning("UUID 兼容补丁失败 (非致命): %s", _e)

    _engine = _ce(os.environ["DATABASE_URL"])
    Base.metadata.create_all(_engine)
    _seed_logger.info("数据库表已创建: %s", os.environ["DATABASE_URL"])

    # 插入种子数据 — 使 data-dependent 集成测试在 CI 上正常工作
    _session = _SESession(_engine)
    try:
        if not _session.query(Account).first():
            _acct = Account(
                account_id="REAL_001",
                account_name="量化主账户",
                account_type="paper",
                total_assets=1000000.0,
                available_cash=435820.5,
                market_value=564179.5,
                total_profit_loss=23450.0,
                total_profit_loss_ratio=0.0245,
                currency="CNY",
            )
            _session.add(_acct)
            for _ts, _name, _price, _qty in [
                ("600519.SH", "贵州茅台", 1723.0, 100),
                ("000001.SZ", "平安银行", 12.5, 5000),
                ("300750.SZ", "宁德时代", 210.5, 200),
            ]:
                _session.add(
                    StockPool(
                        ts_code=_ts, name=_name, market="SSE" if _ts.endswith(".SH") else "SZSE"
                    )
                )
                _session.add(
                    Position(
                        account_id="REAL_001",
                        ts_code=_ts,
                        direction="long",
                        total_quantity=_qty,
                        available_quantity=_qty,
                        cost_price=_price,
                        current_price=_price * 1.02,
                        market_value=_price * _qty,
                        profit_loss=_price * 0.02 * _qty,
                        profit_loss_ratio=0.02,
                        days_held=15,
                        opened_at=datetime(2026, 6, 1, 9, 30, 0),
                    )
                )
            _session.add(
                Trade(
                    trade_id="T2026060001",
                    account_id="REAL_001",
                    ts_code="600519.SH",
                    direction="buy",
                    price=1650.0,
                    quantity=100,
                    amount=165000.0,
                    commission=165.0,
                    trade_date=date(2026, 6, 1),
                    trade_time=time(9, 30, 0),
                )
            )
            _session.commit()
            _seed_logger.info("种子数据已插入 (Account + 3 Positions + 1 Trade)")
        else:
            _seed_logger.info("种子数据已存在，跳过插入")
    except Exception as _seed_e:
        _session.rollback()
        _seed_logger.warning("种子数据插入失败 (非致命，数据依赖测试将跳过): %s", _seed_e)
    finally:
        _session.close()

    _engine.dispose()
    _SEED_DATA_TABLES_CREATED = True
except Exception as _setup_e:
    _seed_logger.warning("DB 表/种子数据创建失败 (非致命): %s", _setup_e)


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
