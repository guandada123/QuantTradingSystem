"""
数据库连接层
SQLAlchemy engine 和 session 管理
"""

from core.config import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

engine = create_engine(settings.DATABASE_URL, pool_size=5, max_overflow=10, pool_pre_ping=True)

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
