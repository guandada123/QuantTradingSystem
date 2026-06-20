"""
Alembic 运行时环境配置

从 core.config.settings.DATABASE_URL 读取连接字符串，
支持 online (直连数据库) 和 offline (生成 SQL 文件) 两种模式。
"""

from logging.config import fileConfig
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# 确保 strategy-service 根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据（如有 SQLAlchemy 声明式模型则在此导入）
# from models.base import Base
# target_metadata = Base.metadata
target_metadata = None


def get_url() -> str:
    """从环境变量或 settings 获取数据库 URL。"""
    # 优先读取环境变量
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    # 其次从 settings 读取
    try:
        from core.config import settings

        settings_url: str = settings.DATABASE_URL
        return settings_url
    except ImportError:
        pass
    # 最后使用 alembic.ini 中的默认值
    db_url: str = config.get_main_option("sqlalchemy.url", "")
    return db_url


def run_migrations_offline() -> None:
    """
    Offline 模式 — 生成 SQL 脚本而非直接执行。
    用法: alembic upgrade head --sql > migration.sql
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Online 模式 — 直接连接数据库执行迁移。
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
