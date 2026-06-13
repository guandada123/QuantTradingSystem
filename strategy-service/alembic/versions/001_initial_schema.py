"""初始 schema 基线 — 对应 docs/init.sql

注意: 生产环境如果数据库已有完整 schema，请运行:
    alembic stamp 001
跳过此迁移直接标记为已应用。

Revision ID: 001
Revises: None
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建核心表结构（对应 docs/init.sql 精简版）"""

    # UUID 扩展
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # 交易日历
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade_calendar (
            id SERIAL PRIMARY KEY,
            exchange VARCHAR(10) NOT NULL,
            cal_date DATE NOT NULL,
            is_open BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE(exchange, cal_date)
        )
    """)

    # 股票基本信息
    op.execute("""
        CREATE TABLE IF NOT EXISTS stock_basic (
            id SERIAL PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL UNIQUE,
            symbol VARCHAR(10),
            name VARCHAR(50),
            area VARCHAR(20),
            industry VARCHAR(30),
            market VARCHAR(20),
            list_date DATE,
            list_status VARCHAR(1) DEFAULT 'L',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 日线行情
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

    # 每日基本指标
    op.execute("""
        CREATE TABLE IF NOT EXISTS daily_basic (
            id BIGSERIAL PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL,
            trade_date DATE NOT NULL,
            turnover_rate DECIMAL(10,4),
            volume_ratio DECIMAL(10,4),
            pe DECIMAL(12,4),
            pb DECIMAL(12,4),
            ps DECIMAL(12,4),
            total_mv DECIMAL(20,2),
            circ_mv DECIMAL(20,2),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ts_code, trade_date)
        )
    """)

    # 资金流向
    op.execute("""
        CREATE TABLE IF NOT EXISTS moneyflow (
            id BIGSERIAL PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL,
            trade_date DATE NOT NULL,
            buy_sm_amount DECIMAL(20,2),
            sell_sm_amount DECIMAL(20,2),
            buy_md_amount DECIMAL(20,2),
            sell_md_amount DECIMAL(20,2),
            buy_lg_amount DECIMAL(20,2),
            sell_lg_amount DECIMAL(20,2),
            buy_elg_amount DECIMAL(20,2),
            sell_elg_amount DECIMAL(20,2),
            net_mf_amount DECIMAL(20,2),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ts_code, trade_date)
        )
    """)

    # 行业分类
    op.execute("""
        CREATE TABLE IF NOT EXISTS industry_classification (
            id SERIAL PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL,
            industry_name VARCHAR(50),
            level VARCHAR(10),
            src VARCHAR(20) DEFAULT 'SW',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 交易信号
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade_signals (
            id BIGSERIAL PRIMARY KEY,
            signal_id UUID DEFAULT uuid_generate_v4(),
            ts_code VARCHAR(20) NOT NULL,
            signal_type VARCHAR(10) NOT NULL,
            strategy_name VARCHAR(50),
            price DECIMAL(12,2),
            confidence DECIMAL(5,2),
            reason TEXT,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 回测结果
    op.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id BIGSERIAL PRIMARY KEY,
            strategy_name VARCHAR(50) NOT NULL,
            start_date DATE,
            end_date DATE,
            initial_capital DECIMAL(20,2),
            final_capital DECIMAL(20,2),
            total_return DECIMAL(10,4),
            sharpe_ratio DECIMAL(10,4),
            max_drawdown DECIMAL(10,4),
            win_rate DECIMAL(10,4),
            total_trades INTEGER,
            params JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 持仓
    op.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id BIGSERIAL PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL,
            shares INTEGER NOT NULL DEFAULT 0,
            avg_cost DECIMAL(12,2),
            current_price DECIMAL(12,2),
            market_value DECIMAL(20,2),
            profit_loss DECIMAL(20,2),
            profit_pct DECIMAL(10,4),
            status VARCHAR(10) DEFAULT 'open',
            open_date DATE,
            close_date DATE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 订单
    op.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id BIGSERIAL PRIMARY KEY,
            order_id UUID DEFAULT uuid_generate_v4(),
            ts_code VARCHAR(20) NOT NULL,
            direction VARCHAR(4) NOT NULL,
            order_type VARCHAR(10) DEFAULT 'limit',
            price DECIMAL(12,2),
            volume INTEGER NOT NULL,
            filled_volume INTEGER DEFAULT 0,
            status VARCHAR(20) DEFAULT 'pending',
            signal_id UUID,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建常用索引
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_daily_quote_code_date ON daily_quote(ts_code, trade_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_daily_basic_code_date ON daily_basic(ts_code, trade_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_moneyflow_code_date ON moneyflow(ts_code, trade_date)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_signals_code ON trade_signals(ts_code)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON trade_signals(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)")


def downgrade() -> None:
    """回滚: 删除所有表（⚠️ 仅开发环境使用）"""
    tables = [
        "orders",
        "positions",
        "backtest_results",
        "trade_signals",
        "industry_classification",
        "moneyflow",
        "daily_basic",
        "daily_quote",
        "stock_basic",
        "trade_calendar",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
