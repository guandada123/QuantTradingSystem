"""v2.2: 确保 daily_quote 表存在

对应原 models/migration.py 的第5条迁移。

Revision ID: 003
Revises: 002
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v2.2: 确保 daily_quote 表存在（兜底 001 未执行的情况）"""
    op.execute("""
        CREATE TABLE IF NOT EXISTS daily_quote (
            id BIGSERIAL PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL,
            trade_date DATE NOT NULL,
            open DECIMAL(12,2),
            high DECIMAL(12,2),
            low DECIMAL(12,2),
            close DECIMAL(12,2),
            pre_close DECIMAL(12,2),
            change DECIMAL(12,2),
            pct_change DECIMAL(12,4),
            volume BIGINT,
            amount DECIMAL(20,2),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ts_code, trade_date)
        )
    """)


def downgrade() -> None:
    """回滚 v2.2 — 注意: 如果 001 已创建此表则此处不应删除"""
    # 仅当 001_initial_schema 未创建此表时才删除
    # 实际操作中建议手动判断
