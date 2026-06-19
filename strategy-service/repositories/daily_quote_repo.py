"""
日线行情数据仓库
封装 daily_quote 和 stock_pool 表的所有 DB 操作，
替代 data_service.py 中的裸 SQL + engine.connect() 调用。

用法:
    repo = DailyQuoteRepo()
    rows = repo.select_daily_quote("000001.SZ", "2026-01-01", "2026-06-18")
    repo.upsert_daily_quote("000001.SZ", [{"trade_date": "2026-06-18", ...}])
    symbols = repo.fetch_symbols()
"""

from datetime import datetime
from typing import Any

from models.database import get_db_session
from models.models import DailyQuote
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.exceptions import RepositoryException
from shared.structured_log import get_logger

logger = get_logger(__name__)

# =============================================================================
# SQL 常量
# =============================================================================

_SQL_SELECT_DAILY_QUOTE = """
    SELECT ts_code, trade_date, open, high, low, close, pre_close,
           change, pct_change, volume, amount
    FROM daily_quote
    WHERE ts_code = :ts_code
      AND trade_date >= :start_date
      AND trade_date <= :end_date
    ORDER BY trade_date ASC
"""

_SQL_UPSERT_DAILY_QUOTE = """
    INSERT INTO daily_quote (ts_code, trade_date, open, high, low, close,
        pre_close, change, pct_change, volume, amount)
    VALUES (:ts_code, :trade_date, :open, :high, :low, :close,
        :pre_close, :change, :pct_change, :volume, :amount)
    ON CONFLICT (ts_code, trade_date) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        pre_close = EXCLUDED.pre_close,
        change = EXCLUDED.change,
        pct_change = EXCLUDED.pct_change,
        volume = EXCLUDED.volume,
        amount = EXCLUDED.amount
"""

_SQL_SELECT_SYMBOLS = """
    SELECT ts_code FROM stock_pool ORDER BY ts_code LIMIT :limit
"""


class DailyQuoteRepo:
    """日线行情 + 股票池查询仓库

    所有方法使用 get_db_session() ORM 上下文管理器管理连接生命周期。
    失败时抛出 RepositoryException (带 code 和 cause)。
    """

    # ------------------------------------------------------------------
    # 日线行情查询
    # ------------------------------------------------------------------

    def select_daily_quote(
        self, ts_code: str, start_date: str, end_date: str, min_rows: int = 30
    ) -> list[dict[str, Any]] | None:
        """从 daily_quote 表查询日线行情

        Args:
            ts_code: 股票代码
            start_date: 起始日期 (YYYY-MM-DD)
            end_date: 截止日期 (YYYY-MM-DD)
            min_rows: 最少行数阈值，少于该值视为"数据不足"返回 None

        Returns:
            list[dict] — 行情记录列表；数据不足时返回 None
        """
        try:
            with get_db_session() as db:
                rows = db.execute(
                    text(_SQL_SELECT_DAILY_QUOTE),
                    {
                        "ts_code": ts_code,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                ).fetchall()

                if rows and len(rows) >= min_rows:
                    result = [dict(row._mapping) for row in rows]
                    logger.info(
                        "从DB读取日线数据",
                        ts_code=ts_code,
                        count=len(result),
                    )
                    return result
                return None
        except SQLAlchemyError as e:
            logger.debug("DB查询日线失败，降级到数据源", ts_code=ts_code, error=str(e))
            return None
        except Exception as e:
            logger.warning("DB查询日线异常", ts_code=ts_code, error=str(e))
            return None

    # ------------------------------------------------------------------
    # 日线行情写入 (upsert)
    # ------------------------------------------------------------------

    def upsert_daily_quote(self, ts_code: str, rows: list[dict[str, Any]]) -> int:
        """批量 upsert 日线行情到 daily_quote 表

        Args:
            ts_code: 股票代码
            rows: 行情记录列表，每项含 open/high/low/close 等字段

        Returns:
            int — 成功写入的行数
        """
        try:
            with get_db_session() as db:
                count = 0
                for row in rows:
                    params = self._build_params(row, ts_code)
                    if not params:
                        continue
                    db.execute(text(_SQL_UPSERT_DAILY_QUOTE), params)
                    count += 1
                db.commit()

            if count > 0:
                logger.info("日线数据 upsert 完成", ts_code=ts_code, count=count)
            return count
        except SQLAlchemyError as e:
            logger.error("日线数据 upsert 失败", ts_code=ts_code, error=str(e))
            raise RepositoryException(
                f"日线数据写入失败: {ts_code}", code="UPSERT_DAILY_QUOTE_FAILED", cause=e
            )

    @staticmethod
    def _build_params(row: dict[str, Any], ts_code: str) -> dict[str, Any]:
        """将 API 返回的行字段转换为 upsert 参数字典"""
        trade_date = str(row.get("trade_date", ""))
        # 统一日期格式为 YYYY-MM-DD
        if trade_date and "-" not in trade_date and len(trade_date) == 8:
            trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        if len(trade_date) != 10 or "-" not in trade_date:
            return {}

        return {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "pre_close": float(row.get("pre_close", 0)),
            "change": float(row.get("change", 0)),
            "pct_change": float(row.get("pct_chg", row.get("pct_change", 0))),
            "volume": int(row.get("vol", row.get("volume", 0))),
            "amount": float(row.get("amount", 0)),
        }

    # ------------------------------------------------------------------
    # 股票池查询
    # ------------------------------------------------------------------

    def fetch_symbols(self, limit: int = 50) -> list[str]:
        """从 stock_pool 表获取标的列表

        Args:
            limit: 最大返回数量

        Returns:
            list[str] — ts_code 列表；失败时返回空列表
        """
        try:
            with get_db_session() as db:
                result = db.execute(
                    text("SELECT ts_code FROM stock_pool ORDER BY ts_code LIMIT :limit"),
                    {"limit": limit},
                )
                symbols = [row[0] for row in result.fetchall()]
                logger.debug("获取标的列表", count=len(symbols))
                return symbols
        except SQLAlchemyError as e:
            logger.warning("从 stock_pool 获取标的失败", error=str(e))
            return []
        except Exception as e:
            logger.warning("获取标的列表异常", error=str(e))
            return []

    def select_stock_pool(self, limit: int = 50) -> list[dict[str, Any]]:
        """从 stock_pool 表查询完整股票池

        Args:
            limit: 最大返回数量

        Returns:
            list[dict] — [{ts_code, name, industry, market}, ...]；失败时返回空列表
        """
        try:
            with get_db_session() as db:
                result = db.execute(
                    text("SELECT ts_code, name, industry, market FROM stock_pool LIMIT :limit"),
                    {"limit": limit},
                )
                rows = result.fetchall()
                pool = [dict(row._mapping) for row in rows] if rows else []
                logger.debug("查询股票池", count=len(pool))
                return pool
        except SQLAlchemyError as e:
            logger.warning("从 DB stock_pool 获取股票池失败", error=str(e))
            return []
        except Exception as e:
            logger.warning("获取股票池异常", error=str(e))
            return []
