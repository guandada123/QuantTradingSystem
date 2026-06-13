"""
数据库连接管理 - SQLAlchemy 引擎与会话
"""

import logging

from core.config import settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# SQLAlchemy 基类
Base = declarative_base()

# 数据库引擎
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """获取数据库会话（FastAPI 依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session():
    """获取数据库会话（非生成器，供后台任务/定时任务直接使用）

    调用方负责关闭：
        db = get_db_session()
        try:
            ...
            db.commit()
        finally:
            db.close()
    """
    return SessionLocal()


def init_db():
    """初始化数据库（在生产中应使用 Alembic 管理迁移）"""
    try:
        # 测试连接
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("数据库连接成功")
    except Exception as e:
        logger.warning(f"数据库连接失败: {e}")
        logger.warning("系统将以模拟数据模式运行")
