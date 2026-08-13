"""qts_daily_brief 表 — Claw↔QTS 打通 (2026-08-13)

brief 落库单点：QTS generate_daily_brief() 写入，Claw qts_client 只读。
废除 /tmp 文件桥接依赖。

Revision ID: 004_claw_qts_bridge
Revises: 003_v2_2_daily_quote
Create Date: 2026-08-13
"""

import sqlalchemy as sa
from alembic import op

revision = "004_claw_qts_bridge"
down_revision = "003_v2_2_daily_quote"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qts_daily_brief",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("report_date", sa.Date, nullable=False, unique=True),
        sa.Column("brief", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("qts_daily_brief")
