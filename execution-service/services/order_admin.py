"""
订单查询与每日摘要模块
从 order_manager 拆分 — 只读查询和报告生成
"""
import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def calculate_trade_cost(
    price: float,
    quantity: int,
    direction: str,
    commission_rate: float = 0.0003,
    tax_rate: float = 0.001,
) -> dict[str, float]:
    """
    计算 A 股交易成本
    - 佣金: 成交额 × 佣金率，最低 5 元
    - 印花税: 卖出时成交额 × 0.1%
    """
    amount = price * quantity
    commission = amount * commission_rate
    commission = max(commission, 5.0)

    tax = 0.0
    if direction == "SELL":
        tax = amount * tax_rate

    return {
        "amount": amount,
        "commission": commission,
        "tax": tax,
        "total_cost": commission + tax,
        "net_amount": amount - commission - tax,
    }


class OrderAdmin:
    """订单查询与每日摘要 — 只读操作为主"""

    def __init__(self, db, account_id: str = "REAL_001"):
        self.db = db
        self.account_id = account_id

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        """从 DB 查询单个订单"""
        row = (
            self.db.execute(
                text("""
            SELECT order_id, ts_code, direction, order_type, price, quantity, amount,
                   status, filled_price, filled_quantity, filled_amount, commission, tax,
                   strategy_name, error_message, created_at, updated_at
            FROM orders WHERE order_id = :oid
        """),
                {"oid": order_id},
            )
            .mappings()
            .fetchone()
        )
        if not row:
            return None
        return dict(row)

    def list_orders(
        self, status: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """从 DB 查询订单列表，可按状态过滤"""
        if status:
            rows = (
                self.db.execute(
                    text("""
                SELECT order_id, ts_code, direction, order_type, price, quantity, amount,
                       status, filled_price, filled_quantity, commission, tax,
                       strategy_name, created_at, updated_at
                FROM orders WHERE status = :status
                ORDER BY created_at DESC LIMIT :limit
            """),
                    {"status": status, "limit": limit},
                )
                .mappings()
                .fetchall()
            )
        else:
            rows = (
                self.db.execute(
                    text("""
                SELECT order_id, ts_code, direction, order_type, price, quantity, amount,
                       status, filled_price, filled_quantity, commission, tax,
                       strategy_name, created_at, updated_at
                FROM orders ORDER BY created_at DESC LIMIT :limit
            """),
                    {"limit": limit},
                )
                .mappings()
                .fetchall()
            )
        return [dict(r) for r in rows]

    def get_daily_summary(self) -> dict[str, Any]:
        """获取当日交易摘要 — 成交、持仓、订单统计"""
        today = date.today()

        # 当日成交
        trades = (
            self.db.execute(
                text("""
            SELECT COUNT(*) as count, COALESCE(SUM(amount), 0) as total_amount,
                   COALESCE(SUM(commission), 0) as total_commission,
                   COALESCE(SUM(tax), 0) as total_tax,
                   COALESCE(SUM(profit_loss), 0) as total_pnl
            FROM trades WHERE trade_date = :td
        """),
                {"td": today},
            )
            .mappings()
            .fetchone()
        )

        # 当前持仓
        positions = (
            self.db.execute(
                text("""
            SELECT COUNT(*) as count, COALESCE(SUM(market_value), 0) as total_market_value,
                   COALESCE(SUM(profit_loss), 0) as total_unrealized_pnl
            FROM positions WHERE total_quantity > 0
        """)
            )
            .mappings()
            .fetchone()
        )

        # 今日订单
        orders = (
            self.db.execute(
                text("""
            SELECT status, COUNT(*) as count FROM orders
            WHERE created_at::date = :td
            GROUP BY status
        """),
                {"td": today},
            )
            .mappings()
            .fetchall()
        )

        # 账户信息
        account = (
            self.db.execute(
                text(
                    "SELECT available_cash, total_assets, market_value, day_profit_loss "
                    "FROM accounts WHERE account_id = :aid"
                ),
                {"aid": self.account_id},
            )
            .mappings()
            .fetchone()
        )

        return {
            "date": today.isoformat(),
            "account": {
                "available_cash": float(account["available_cash"]) if account else 0,
                "total_assets": float(account["total_assets"]) if account else 0,
                "market_value": float(account["market_value"]) if account else 0,
                "day_pnl": float(account["day_profit_loss"] or 0) if account else 0,
            },
            "trades": {
                "count": int(trades["count"]) if trades else 0,
                "total_amount": float(trades["total_amount"] or 0) if trades else 0,
                "total_commission": float(trades["total_commission"] or 0) if trades else 0,
                "total_tax": float(trades["total_tax"] or 0) if trades else 0,
                "total_pnl": float(trades["total_pnl"] or 0) if trades else 0,
            },
            "positions": {
                "count": int(positions["count"]) if positions else 0,
                "total_market_value": (
                    float(positions["total_market_value"] or 0) if positions else 0
                ),
                "total_unrealized_pnl": (
                    float(positions["total_unrealized_pnl"] or 0) if positions else 0
                ),
            },
            "orders_today": [
                {"status": r["status"], "count": int(r["count"])} for r in orders
            ],
        }

    async def send_daily_summary(self):
        """发送每日摘要到飞书"""
        summary = self.get_daily_summary()
        try:
            from services.feishu_alert import get_alert_service

            alert_svc = get_alert_service()
            await alert_svc.send_daily_summary(summary)
            logger.info("每日摘要已发送到飞书")
        except Exception as e:
            logger.error(f"每日摘要发送失败: {e}")
