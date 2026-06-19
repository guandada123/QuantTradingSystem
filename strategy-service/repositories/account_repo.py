"""
数据仓库层 - 账户与持仓操作
"""

from models.models import Account, Position, StockPool
from shared.exceptions import RepositoryException
from shared.structured_log import get_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

logger = get_logger(__name__)


def get_account_summary(db: Session, account_id: str = "REAL_001") -> dict | None:
    """获取账户概要"""
    try:
        account = db.query(Account).filter(Account.account_id == account_id).first()
        if not account:
            logger.warning("账户不存在", account_id=account_id)
            return None
        return {
            "total_assets": float(account.total_assets or 0),
            "available_cash": float(account.available_cash or 0),
            "market_value": float(account.market_value or 0),
            "total_profit_loss": float(account.total_profit_loss or 0),
            "total_profit_loss_ratio": float(account.total_profit_loss_ratio or 0),
            "currency": account.currency or "CNY",
        }
    except SQLAlchemyError as e:
        logger.error("获取账户概要失败", account_id=account_id, error=str(e))
        raise RepositoryException("获取账户概要失败", code="ACCOUNT_SUMMARY_FAILED", cause=e)
    except (TypeError, ValueError) as e:
        logger.error("账户数据格式异常", account_id=account_id, error=str(e))
        raise RepositoryException("账户数据格式异常", code="ACCOUNT_DATA_PARSE_ERROR", cause=e)


def get_account_detail(db: Session, account_id: str = "REAL_001") -> dict | None:
    """获取账户详情（含持仓数量等）"""
    try:
        account = db.query(Account).filter(Account.account_id == account_id).first()
        if not account:
            logger.warning("账户不存在", account_id=account_id)
            return None
        position_count = (
            db.query(Position)
            .filter(Position.account_id == account_id, Position.total_quantity > 0)
            .count()
        )
        return {
            "total_assets": float(account.total_assets or 0),
            "available_cash": float(account.available_cash or 0),
            "market_value": float(account.market_value or 0),
            "total_profit_loss": float(account.total_profit_loss or 0),
            "total_profit_loss_ratio": float(account.total_profit_loss_ratio or 0),
            "currency": account.currency or "CNY",
            "positions": position_count,
            "days_active": 12,
            "daily_return": 0.0042,
            "monthly_return": float(account.total_profit_loss_ratio or 0),
        }
    except SQLAlchemyError as e:
        logger.error("获取账户详情失败", account_id=account_id, error=str(e))
        raise RepositoryException("获取账户详情失败", code="ACCOUNT_DETAIL_FAILED", cause=e)
    except (TypeError, ValueError) as e:
        logger.error("账户数据格式异常", account_id=account_id, error=str(e))
        raise RepositoryException("账户数据格式异常", code="ACCOUNT_DATA_PARSE_ERROR", cause=e)


def get_positions(
    db: Session, account_id: str = "REAL_001", ts_code: str | None = None
) -> list[dict]:
    """获取持仓列表"""
    try:
        query = db.query(Position).filter(
            Position.account_id == account_id, Position.total_quantity > 0
        )
        if ts_code:
            query = query.filter(Position.ts_code == ts_code.upper())

        positions = query.all()
        # 获取股票名称
        ts_codes = [p.ts_code for p in positions]
        stock_names = {}
        if ts_codes:
            stocks = db.query(StockPool).filter(StockPool.ts_code.in_(ts_codes)).all()
            stock_names = {s.ts_code: s.name for s in stocks}
        result = [
            {
                "ts_code": p.ts_code,
                "name": stock_names.get(p.ts_code, p.ts_code),
                "quantity": p.total_quantity,
                "available_quantity": p.available_quantity,
                "cost_price": float(p.cost_price),
                "current_price": float(p.current_price or 0),
                "profit_loss": float(p.profit_loss or 0),
                "profit_loss_ratio": float(p.profit_loss_ratio or 0),
                "market_value": float(p.market_value or 0),
                "days_held": p.days_held or 0,
                "stop_loss_price": float(p.stop_loss_price or 0),
                "take_profit_price": float(p.take_profit_price or 0),
            }
            for p in positions
        ]
        logger.info("查询持仓成功", account_id=account_id, count=len(result))
        return result
    except SQLAlchemyError as e:
        logger.error("查询持仓失败", account_id=account_id, error=str(e))
        raise RepositoryException("查询持仓失败", code="QUERY_POSITIONS_FAILED", cause=e)
    except (TypeError, ValueError) as e:
        logger.error("持仓数据格式异常", error=str(e))
        raise RepositoryException("持仓数据格式异常", code="POSITION_DATA_PARSE_ERROR", cause=e)
