"""v2.1: backtest_reports 表 + ts_code 列

对应原 models/migration.py 的前4条迁移。

Revision ID: 002
Revises: 001
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v2.1 增量迁移"""
    # 1. backtest_results 添加 ts_code 列
    op.execute(
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS "
        "ts_code VARCHAR(20) NOT NULL DEFAULT ''"
    )

    # 2. 创建 backtest_reports 表
    op.execute("""
        CREATE TABLE IF NOT EXISTS backtest_reports (
            id BIGSERIAL PRIMARY KEY,
            report_id UUID DEFAULT uuid_generate_v4(),
            report_type VARCHAR(10) NOT NULL,
            report_date DATE NOT NULL,
            ts_codes TEXT[],
            strategy_count INTEGER DEFAULT 0,
            strategies_covered JSONB,
            summary JSONB,
            detail_content TEXT,
            feishu_msg_id VARCHAR(100),
            push_success BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 3. 创建索引
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reports_type_date "
        "ON backtest_reports(report_type, report_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_backtest_results_ts_code ON backtest_results(ts_code)"
    )


def downgrade() -> None:
    """回滚 v2.1"""
    op.execute("DROP INDEX IF EXISTS idx_backtest_results_ts_code")
    op.execute("DROP INDEX IF EXISTS idx_reports_type_date")
    op.execute("DROP TABLE IF EXISTS backtest_reports")
    op.execute("ALTER TABLE backtest_results DROP COLUMN IF EXISTS ts_code")
