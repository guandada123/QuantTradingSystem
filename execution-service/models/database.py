"""
数据库连接层
SQLAlchemy engine 和 session 管理
"""

import os

from core.config import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_db_url = os.environ.get("DATABASE_URL") or settings.DATABASE_URL
if not _db_url:
    _db_url = "sqlite:///./quant_execution.db"

# 🔴 显式驱动（2026-10-11 同源修复）：SQLAlchemy 2.1 起 `postgresql://` 默认走
# psycopg(v3)，而镜像只装 psycopg2-binary → 重建镜像时会在 import 期直接崩。
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(_db_url, pool_size=5, max_overflow=10, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Session:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


def get_db_session():
    """FastAPI 依赖注入用的 generator"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
