"""
SQLite UUID 兼容性工具 — 将 PostgreSQL UUID 列替换为 TypeDecorator。

在 SQLite 环境中 PostgreSQL 的 UUID 类型不可用（fallback 生成 NUMERIC 列），
此模块通过 TypeDecorator 在 ORM 层处理 uuid.UUID ↔ str 转换，
使测试能用 SQLite 内存数据库正确读写 UUID 列。

用法:
    from tests.uuid_compat import make_uuid_sqlite_compat

    make_uuid_sqlite_compat()  # 在 Base.metadata.create_all() 之前调用
"""

import uuid as _uuid

from sqlalchemy import String as _String
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID
from sqlalchemy.types import TypeDecorator as _TypeDecorator


class _UUIDString(_TypeDecorator):
    """将 Python uuid.UUID ↔ SQLite VARCHAR(36) 互转的 TypeDecorator"""

    impl = _String(36)
    cache_ok = True
    python_type = _uuid.UUID

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return value
        return _uuid.UUID(value)


def make_uuid_sqlite_compat():
    """扫描 Base.metadata 中所有 PostgreSQL UUID 列，替换为 _UUIDString。

    必须在所有 ORM 模型导入完成后、Base.metadata.create_all() 之前调用。
    多次调用幂等（已替换的列不会再次匹配 _PG_UUID）。
    """
    from models.database import Base

    _replaced = 0
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, _PG_UUID):
                col.type = _UUIDString(36)
                _replaced += 1
    return _replaced
