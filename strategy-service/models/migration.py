"""
DB迁移辅助脚本 v1.0
用于开发环境快速应用schema变更，无需手动执行SQL
"""
import logging
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


MIGRATIONS = [
    # 迁移1: backtest_results 添加 ts_code 列
    {
        "version": "v2.1",
        "description": "backtest_results 添加 ts_code 列",
        "sql": "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS ts_code VARCHAR(20) NOT NULL DEFAULT ''"
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
        """
    },
    # 迁移3: 创建索引
    {
        "version": "v2.1",
        "description": "backtest_reports 添加索引",
        "sql": "CREATE INDEX IF NOT EXISTS idx_reports_type_date ON backtest_reports(report_type, report_date)"
    },
    {
        "version": "v2.1",
        "description": "backtest_results 添加 ts_code 索引",
        "sql": "CREATE INDEX IF NOT EXISTS idx_backtest_results_ts_code ON backtest_results(ts_code)"
    },
]


def run_migrations(db_url: str = None):
    """执行所有待处理的迁移"""
    if not db_url:
        try:
            from core.config import settings
            db_url = settings.DATABASE_URL
        except Exception:
            pass

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
    sys.path.insert(0, '.')
    logging.basicConfig(level=logging.INFO)
    run_migrations()
