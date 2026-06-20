"""
DB迁移辅助脚本 v1.0 (DEPRECATED)

⚠️ 此模块已弃用，请改用 Alembic:
    cd strategy-service
    alembic upgrade head      # 升级到最新
    alembic downgrade -1      # 回滚一步
    alembic revision -m "xxx" # 新建迁移

保留此文件仅为向后兼容。新的迁移请创建 Alembic revision。
"""

import logging

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


MIGRATIONS = [
    # 迁移1: backtest_results 添加 ts_code 列
    {
        "version": "v2.1",
        "description": "backtest_results 添加 ts_code 列",
        "sql": "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS ts_code VARCHAR(20) NOT NULL DEFAULT ''",
    },
    # 迁移2: 创建 backtest_reports 表
    {
        "version": "v2.1",
        "description": "创建 backtest_reports 表",
        "sql": """
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
        """,
    },
    # 迁移3: 创建索引
    {
        "version": "v2.1",
        "description": "backtest_reports 添加索引",
        "sql": "CREATE INDEX IF NOT EXISTS idx_reports_type_date ON backtest_reports(report_type, report_date)",
    },
    {
        "version": "v2.1",
        "description": "backtest_results 添加 ts_code 索引",
        "sql": "CREATE INDEX IF NOT EXISTS idx_backtest_results_ts_code ON backtest_results(ts_code)",
    },
    # 迁移4: 创建 daily_quote 表（兜底 init.sql 未执行的情况）
    {
        "version": "v2.2",
        "description": "确保 daily_quote 表存在",
        "sql": """
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
        """,
    },
]


def run_migrations(db_url: str = None):
    """执行所有待处理的迁移"""
    if not db_url:
        try:
            from core.config import settings

            db_url = settings.DATABASE_URL
        except Exception:
            logger.warning("[Migration] 加载配置失败，尝试直接使用参数")

    if not db_url:
        logger.warning("[Migration] DATABASE_URL 未配置，跳过迁移")
        return False

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            for m in MIGRATIONS:
                try:
                    conn.execute(text(m["sql"]))
                    conn.commit()
                    logger.info(f"[Migration] ✅ {m['version']}: {m['description']}")
                except Exception as e:
                    logger.warning(f"[Migration] ⚠️ {m['version']}: {m['description']} — {e}")

        logger.info("[Migration] 所有迁移执行完成")
        return True
    except Exception as e:
        logger.warning(f"[Migration] 数据库连接失败，跳过迁移: {e}")
        return False


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    logging.basicConfig(level=logging.INFO)
    run_migrations()
