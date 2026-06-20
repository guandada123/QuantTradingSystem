"""
持仓管理器
持仓开仓、平仓、价格更新、盈亏计算、累计盈亏汇总
"""

from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from shared.structured_log import get_logger

logger = get_logger(__name__)

from core.constants import DEFAULT_ACCOUNT_ID


class PositionManager:
    """持仓管理器"""

    def __init__(
        self,
        db: Session,
        account_id: str = DEFAULT_ACCOUNT_ID,
        commission_rate: float = 0.0003,
        min_commission: float = 5.0,
        tax_rate: float = 0.001,
    ):
        self.db = db
        self.account_id = account_id
        self.commission_rate = commission_rate  # 佣金率（万3）
        self.min_commission = min_commission  # 最低佣金5元
        self.tax_rate = tax_rate  # 千1印花税（仅卖出）

    def open_position(
        self,
        ts_code: str,
        quantity: int,
        price: float,
        direction: str = "LONG",
        strategy_name: str | None = None,
    ) -> dict[str, Any]:
        """
        开仓/加仓
        创建或更新持仓，扣减账户现金
        """
        trade_amount = price * quantity
        commission = max(trade_amount * self.commission_rate, self.min_commission)
        total_deduct = trade_amount + commission

        # 检查账户现金
        account = (
            self.db.execute(
                text(
                    "SELECT available_cash, total_assets, market_value FROM accounts WHERE account_id = :aid"
                ),
                {"aid": self.account_id},
            )
            .mappings()
            .fetchone()
        )

        if not account:
            return {"success": False, "error": f"账户 {self.account_id} 不存在"}

        available_cash = float(account["available_cash"])
        if available_cash < total_deduct:
            return {
                "success": False,
                "error": f"资金不足: 需要{total_deduct:.2f}, 可用{available_cash:.2f}",
            }

        # 扣减现金
        new_cash = available_cash - total_deduct
        self.db.execute(
            text("""
            UPDATE accounts SET available_cash = :cash,
                   market_value = market_value + :mv,
                   total_assets = :cash + market_value + :mv,
                   updated_at = CURRENT_TIMESTAMP
            WHERE account_id = :aid
        """),
            {"cash": new_cash, "mv": trade_amount, "aid": self.account_id},
        )

        # 检查现有持仓
        existing = (
            self.db.execute(
                text(
                    "SELECT total_quantity, available_quantity, cost_price FROM positions "
                    "WHERE account_id = :aid AND ts_code = :tc"
                ),
                {"aid": self.account_id, "tc": ts_code},
            )
            .mappings()
            .fetchone()
        )

        if existing:
            old_qty = int(existing["total_quantity"])
            old_cost = float(existing["cost_price"])
            new_qty = old_qty + quantity
            new_cost = (old_cost * old_qty + price * quantity) / new_qty
            new_mv = new_qty * price
            pnl = (price - new_cost) * new_qty
            pnl_ratio = (price - new_cost) / new_cost if new_cost > 0 else 0

            self.db.execute(
                text("""
                UPDATE positions SET total_quantity = :qty, available_quantity = available_quantity + :add_qty,
                       cost_price = :cost, current_price = :price, market_value = :mv,
                       profit_loss = :pnl, profit_loss_ratio = :pnl_ratio,
                       strategy_name = COALESCE(:strategy, strategy_name),
                       updated_at = CURRENT_TIMESTAMP
                WHERE account_id = :aid AND ts_code = :tc
            """),
                {
                    "qty": new_qty,
                    "add_qty": quantity,
                    "cost": new_cost,
                    "price": price,
                    "mv": new_mv,
                    "pnl": pnl,
                    "pnl_ratio": pnl_ratio,
                    "strategy": strategy_name,
                    "aid": self.account_id,
                    "tc": ts_code,
                },
            )
        else:
            self.db.execute(
                text("""
                INSERT INTO positions (account_id, ts_code, direction, total_quantity, available_quantity,
                                      cost_price, current_price, market_value, profit_loss,
                                      profit_loss_ratio, strategy_name, opened_at, updated_at)
                VALUES (:aid, :tc, :dir, :qty, :qty, :cost, :price, :mv, 0, 0,
                        :strategy, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
                {
                    "aid": self.account_id,
                    "tc": ts_code,
                    "dir": direction,
                    "qty": quantity,
                    "cost": price,
                    "price": price,
                    "mv": trade_amount,
                    "strategy": strategy_name,
                },
            )

        self.db.commit()
        logger.info(f"开仓: {ts_code} {quantity}股 @{price} 账户:{self.account_id}")

        return {
            "success": True,
            "ts_code": ts_code,
            "quantity": quantity,
            "price": price,
            "direction": direction,
            "commission": commission,
            "total_cost": total_deduct,
        }

    def close_position(
        self, ts_code: str, quantity: int, price: float, record_trade: bool = True
    ) -> dict[str, Any]:
        """
        平仓/减仓
        减少持仓，增加账户现金，可选创建成交记录(由调用方决定)，计算盈亏
        """
        # 检查持仓
        pos = (
            self.db.execute(
                text(
                    "SELECT total_quantity, available_quantity, cost_price FROM positions "
                    "WHERE account_id = :aid AND ts_code = :tc"
                ),
                {"aid": self.account_id, "tc": ts_code},
            )
            .mappings()
            .fetchone()
        )

        if not pos:
            return {"success": False, "error": f"未找到 {ts_code} 的持仓"}

        available_qty = int(pos["available_quantity"])
        if available_qty < quantity:
            return {
                "success": False,
                "error": f"可用持仓不足: 需要{quantity}股, 可用{available_qty}股",
            }

        cost_price = float(pos["cost_price"])
        total_qty = int(pos["total_quantity"])

        # 计算交易成本
        trade_amount = price * quantity
        commission = max(trade_amount * self.commission_rate, self.min_commission)
        tax = trade_amount * self.tax_rate
        net_income = trade_amount - commission - tax

        # 计算本次盈亏
        pnl = (price - cost_price) * quantity - commission - tax

        # 更新账户现金
        account = (
            self.db.execute(
                text("SELECT available_cash, market_value FROM accounts WHERE account_id = :aid"),
                {"aid": self.account_id},
            )
            .mappings()
            .fetchone()
        )

        if account is None:
            logger.error("账户不存在", account_id=self.account_id)
            return {}
        available_cash = float(account["available_cash"])
        new_cash = available_cash + net_income

        self.db.execute(
            text("""
            UPDATE accounts SET available_cash = :cash,
                   market_value = GREATEST(market_value - :mv, 0),
                   total_assets = :cash + GREATEST(market_value - :mv, 0),
                   updated_at = CURRENT_TIMESTAMP
            WHERE account_id = :aid
        """),
            {"cash": new_cash, "mv": trade_amount, "aid": self.account_id},
        )

        # 更新或删除持仓
        new_qty = total_qty - quantity
        if new_qty == 0:
            self.db.execute(
                text("DELETE FROM positions WHERE account_id = :aid AND ts_code = :tc"),
                {"aid": self.account_id, "tc": ts_code},
            )
        else:
            remaining_mv = new_qty * price
            remaining_pnl = (price - cost_price) * new_qty
            remaining_ratio = (price - cost_price) / cost_price if cost_price > 0 else 0
            self.db.execute(
                text("""
                UPDATE positions SET total_quantity = :qty,
                       available_quantity = available_quantity - :sell_qty,
                       current_price = :price, market_value = :mv,
                       profit_loss = :pnl, profit_loss_ratio = :pnl_ratio,
                       updated_at = CURRENT_TIMESTAMP
                WHERE account_id = :aid AND ts_code = :tc
            """),
                {
                    "qty": new_qty,
                    "sell_qty": quantity,
                    "price": price,
                    "mv": remaining_mv,
                    "pnl": remaining_pnl,
                    "pnl_ratio": remaining_ratio,
                    "aid": self.account_id,
                    "tc": ts_code,
                },
            )

        # 创建成交记录（部分调用方已自行记录，如 OrderManager.execute_order）
        trade_id = None
        if record_trade:
            trade_id = f"TRD_{uuid.uuid4().hex[:12]}"
            now = datetime.now()
            self.db.execute(
                text("""
                INSERT INTO trades (trade_id, account_id, ts_code, direction, price, quantity, amount,
                                   commission, tax, profit_loss, trade_date, trade_time, created_at)
                VALUES (:tid, :aid, :tc, 'SELL', :price, :qty, :amount, :comm, :tax, :pnl, :td, :tt, :created)
            """),
                {
                    "tid": trade_id,
                    "aid": self.account_id,
                    "tc": ts_code,
                    "price": price,
                    "qty": quantity,
                    "amount": trade_amount,
                    "comm": commission,
                    "tax": tax,
                    "pnl": pnl,
                    "td": now.date(),
                    "tt": now.time(),
                    "created": now,
                },
            )

        self.db.commit()
        logger.info(f"平仓: {ts_code} {quantity}股 @{price} 盈亏={pnl:.2f}")

        return {
            "success": True,
            "ts_code": ts_code,
            "quantity": quantity,
            "price": price,
            "trade_id": trade_id,
            "commission": commission,
            "tax": tax,
            "profit_loss": pnl,
            "net_income": net_income,
        }

    def get_positions(self) -> list[dict[str, Any]]:
        """获取所有持仓"""
        rows = (
            self.db.execute(
                text("""
            SELECT ts_code, direction, total_quantity, available_quantity,
                   cost_price, current_price, market_value, profit_loss, profit_loss_ratio,
                   days_held, strategy_name, opened_at, updated_at
            FROM positions WHERE account_id = :aid AND total_quantity > 0
            ORDER BY market_value DESC
        """),
                {"aid": self.account_id},
            )
            .mappings()
            .fetchall()
        )

        return [dict(r) for r in rows]

    def update_position_prices(self, price_map: dict[str, float]) -> dict[str, Any]:
        """
        批量更新持仓价格
        price_map: {ts_code: current_price}
        """
        updated_count = 0
        for ts_code, new_price in price_map.items():
            pos = (
                self.db.execute(
                    text(
                        "SELECT total_quantity, cost_price FROM positions "
                        "WHERE account_id = :aid AND ts_code = :tc AND total_quantity > 0"
                    ),
                    {"aid": self.account_id, "tc": ts_code},
                )
                .mappings()
                .fetchone()
            )

            if not pos:
                continue

            qty = int(pos["total_quantity"])
            cost = float(pos["cost_price"])
            new_mv = qty * new_price
            pnl = (new_price - cost) * qty
            pnl_ratio = (new_price - cost) / cost if cost > 0 else 0

            self.db.execute(
                text("""
                UPDATE positions SET current_price = :price, market_value = :mv,
                       profit_loss = :pnl, profit_loss_ratio = :pnl_ratio,
                       days_held = EXTRACT(DAY FROM (CURRENT_DATE - opened_at::date))::int,
                       updated_at = CURRENT_TIMESTAMP
                WHERE account_id = :aid AND ts_code = :tc
            """),
                {
                    "price": new_price,
                    "mv": new_mv,
                    "pnl": pnl,
                    "pnl_ratio": pnl_ratio,
                    "aid": self.account_id,
                    "tc": ts_code,
                },
            )
            updated_count += 1

        self.db.commit()
        return {"success": True, "updated_count": updated_count}

    def get_realized_pnl_summary(self) -> dict[str, Any]:
        """获取累计已实现盈亏汇总"""
        row = (
            self.db.execute(
                text("""
            SELECT
                COUNT(*) as total_trades,
                COALESCE(SUM(profit_loss), 0) as total_realized_pnl,
                COALESCE(SUM(CASE WHEN profit_loss > 0 THEN profit_loss ELSE 0 END), 0) as total_profit,
                COALESCE(SUM(CASE WHEN profit_loss < 0 THEN profit_loss ELSE 0 END), 0) as total_loss,
                COALESCE(SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END), 0) as win_count,
                COALESCE(SUM(CASE WHEN profit_loss < 0 THEN 1 ELSE 0 END), 0) as loss_count,
                COALESCE(SUM(commission), 0) as total_commission,
                COALESCE(SUM(tax), 0) as total_tax
            FROM trades
            WHERE account_id = :aid AND trade_date = CURRENT_DATE
        """),
                {"aid": self.account_id},
            )
            .mappings()
            .fetchone()
        )

        if not row or row["total_trades"] == 0:
            return {
                "total_trades": 0,
                "total_realized_pnl": 0,
                "total_profit": 0,
                "total_loss": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0,
                "total_commission": 0,
                "total_tax": 0,
            }

        win_count = int(row["win_count"])
        total_trades = int(row["total_trades"])
        return {
            "total_trades": total_trades,
            "total_realized_pnl": round(float(row["total_realized_pnl"]), 2),
            "total_profit": round(float(row["total_profit"]), 2),
            "total_loss": round(float(row["total_loss"]), 2),
            "win_count": win_count,
            "loss_count": int(row["loss_count"]),
            "win_rate": round(win_count / total_trades, 4) if total_trades > 0 else 0,
            "total_commission": round(float(row["total_commission"]), 2),
            "total_tax": round(float(row["total_tax"]), 2),
        }
