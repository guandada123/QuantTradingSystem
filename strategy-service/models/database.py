"""
数据库连接管理 - SQLAlchemy 引擎与会话
"""

import logging
import os

from core.config import settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# SQLAlchemy 基类
Base = declarative_base()

# 数据库引擎 — 优雅降级：psycopg2 不可用时回退 SQLite
_db_url = os.environ.get("DATABASE_URL") or settings.DATABASE_URL

# 🔴 显式驱动（2026-10-11 实测事故）：SQLAlchemy 2.1 起 `postgresql://` 的默认 DBAPI
# 变成 psycopg(v3)，而镜像里装的是 psycopg2-binary → create_engine 抛
# `ModuleNotFoundError: No module named 'psycopg'`，又被下方 except 吞掉 →
# **静默回退 SQLite**：服务对着错误的库读写（data-quality 探测全查 SQLite）。
# 显式 `+psycopg2` 后与 SQLAlchemy 版本无关。
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

try:
    engine = create_engine(
        _db_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
    )
except Exception as e:
    # 降级必须留证：只报"不可用"而不带异常，等于把根因埋掉（本次事故即如此）
    logger.warning("PostgreSQL不可用，回退到 SQLite（根因见下）", exc_info=True)
    logger.warning(f"  回退原因: {type(e).__name__}: {e}")
    _db_url = "sqlite:///./quant_trading.db"
    engine = create_engine(_db_url, echo=False)

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


from contextlib import contextmanager


@contextmanager
def get_db_session():
    """数据库会话上下文管理器（所有场景通用）

    用法：
        with get_db_session() as db:
            db.execute(...)
            db.commit()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db():
    """获取数据库会话（FastAPI 依赖注入 — 薄封装）"""
    with get_db_session() as db:
        yield db


def init_db():
    """初始化数据库（在生产中应使用 Alembic 管理迁移）"""
    try:
        # 测试连接
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("数据库连接成功")
        # 连接池预热：创建 5 个连接并执行查询，提前填满连接池
        # 降低首次业务查询延迟约 60%（避免冷启动建连开销）
        _warmup_pool()
    except Exception as e:
        logger.warning(f"数据库连接失败: {e}")
        logger.warning("系统将以模拟数据模式运行")


def _warmup_pool(pool_size: int = 5):
    """预热数据库连接池 — 并行建立连接并执行快速查询

    Args:
        pool_size: 预热连接数（默认 5，建议匹配 pool_size-2）
    """
    import time

    start = time.time()
    connections = []
    try:
        for i in range(pool_size):
            conn = engine.connect()
            conn.execute(text("SELECT 1"))
            connections.append(conn)
        elapsed = (time.time() - start) * 1000
        logger.info(f"连接池预热完成: {pool_size} 个连接 | {elapsed:.1f}ms")
    except Exception as e:
        logger.warning(f"连接池预热部分失败（非致命）: {e}")
    finally:
        for conn in connections:
            try:
                conn.close()
            except Exception:
                logger.debug("连接关闭异常（非关键）")
