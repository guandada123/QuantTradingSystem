"""
订单管理器 (Facade) — 订单创建、执行、状态追踪、成交记录
验证逻辑 → services/order_validator.py
查询/摘要 → services/order_admin.py
数据模型 → services/models.py
STOP条件单 → services/order_stop.py
"""

from datetime import datetime
import logging
from typing import Any
import uuid

from core.config import settings
from core.constants import DEFAULT_ACCOUNT_ID
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import order_validator
from .alert_utils import fire_alert
from .models import Order, OrderDirection, OrderStatus, OrderType  # noqa: F401 - re-export
from .order_admin import OrderAdmin, calculate_trade_cost
from .order_stop import StopOrderProcessor
from .position_manager import PositionManager

logger = logging.getLogger(__name__)


class OrderManager:
    """订单管理器"""

    def __init__(
        self,
        db: Session,
        commission_rate: float = 0.0003,
        tax_rate: float = 0.001,
        account_id: str = DEFAULT_ACCOUNT_ID,
    ):
        self.db = db
        self.commission_rate = commission_rate  # 佣金率（万3）
        self.tax_rate = tax_rate  # 印花税率（千1，仅卖出）
        self.account_id = account_id
        self.admin = OrderAdmin(db, account_id)  # 查询/摘要委托

    def create_order(
        self,
        ts_code: str,
        direction: str,
        order_type: str = "LIMIT",
        price: float | None = None,
        quantity: int = 100,
        strategy_name: str | None = None,
        trigger_price: float | None = None,
        source: str = "AUTO",
    ) -> Order:
        """创建订单并持久化到DB — 含输入验证"""
        # 验证输入（委托给 order_validator）
        validation_error = order_validator.validate_order_input(
            ts_code, direction, order_type, price, quantity, trigger_price
        )
        if validation_error:
            raise ValueError(validation_error)

        # 交易时间检查
        if not settings.ALLOW_OFF_HOURS_TRADING:
            trading_error = order_validator.check_trading_hours()
            if trading_error:
                raise ValueError(trading_error)

        order = Order(
            ts_code=ts_code,
            direction=OrderDirection(direction),
            order_type=OrderType(order_type),
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
        )
        order.strategy_name = strategy_name

        # 写入数据库
        amount = (price or 0) * quantity
        self.db.execute(
            text("""
            INSERT INTO orders (order_id, ts_code, direction, order_type, price, quantity, amount,
                               status, filled_price, filled_quantity, filled_amount,
                               commission, tax, order_source, strategy_name, trigger_price, created_at, updated_at)
            VALUES (:order_id, :ts_code, :direction, :order_type, :price, :quantity, :amount,
                    :status, 0, 0, 0, 0, 0, :order_source, :strategy_name, :trigger_price, :created_at, :updated_at)
        """),
            {
                "order_id": order.order_id,
                "ts_code": ts_code,
                "direction": direction,
                "order_type": order_type,
                "price": price,
                "quantity": quantity,
                "amount": amount,
                "status": order.status.value,
                "order_source": source,
                "strategy_name": strategy_name,
                "trigger_price": trigger_price,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
            },
        )
        self.db.commit()
        logger.info(f"创建订单：{order.order_id} {direction} {ts_code} {quantity}股 @{price}")
        return order

    # ─────────────────── 订单拒绝 ───────────────────
    def _reject_order(
        self,
        order_id: str,
        ts_code: str,
        direction: str,
        price: float,
        quantity: int,
        reason: str,
    ) -> dict[str, Any]:
        """统一拒绝流水线: 更新状态 + 飞书告警 + WS广播"""
        self._update_order_status(order_id, "REJECTED", error_message=reason)
        try:
            from services.feishu_alert import get_alert_service

            alert_svc = get_alert_service()
            fire_alert(
                alert_svc.send_order_rejected(
                    {
                        "ts_code": ts_code,
                        "direction": direction,
                        "quantity": quantity,
                        "price": price,
                        "order_id": order_id,
                    },
                    reason,
                )
            )
        except Exception as e:
            logger.warning(f"订单拒绝告警失败: {e}")
        try:
            from api.ws_execution import broadcast_order_update

            fire_alert(
                broadcast_order_update(order_id, ts_code, direction, "REJECTED", price, quantity)
            )
        except Exception as e:
            logger.warning(f"WS广播失败: {e}")
        return {"success": False, "error": reason}

    # ─────────────────── 买入执行 — 委托 PositionManager ──────────────
    def _execute_buy(
        self,
        ts_code: str,
        price: float,
        quantity: int,
        trade_amount: float,
        commission: float,
        available_cash: float,
    ) -> None:
        """执行买入：委托 PositionManager.open_position"""
        pm = PositionManager(
            db=self.db,
            account_id=self.account_id,
            commission_rate=self.commission_rate,
            tax_rate=self.tax_rate,
        )
        result = pm.open_position(ts_code=ts_code, quantity=quantity, price=price, direction="LONG")
        if not result["success"]:
            raise ValueError(result.get("error", "开仓失败"))

    # ─────────────────── 卖出执行 — 委托 PositionManager ──────────────
    def _execute_sell(
        self,
        ts_code: str,
        price: float,
        quantity: int,
        trade_amount: float,
        commission: float,
        tax_amount: float,
        available_cash: float,
    ) -> None:
        """执行卖出：委托 PositionManager.close_position（不创建trade记录，由execute_order统一管理）"""
        pm = PositionManager(
            db=self.db,
            account_id=self.account_id,
            commission_rate=self.commission_rate,
            tax_rate=self.tax_rate,
        )
        result = pm.close_position(
            ts_code=ts_code, quantity=quantity, price=price, record_trade=False
        )
        if not result["success"]:
            raise ValueError(result.get("error", "平仓失败"))

    # ─────────────────── 主执行流程 ───────────────────
    def execute_order(self, order_id: str) -> dict[str, Any]:
        """
        模拟执行订单（orchestrator）
        - 校验订单 & 账户 → 分发到 _execute_buy / _execute_sell
        - 记录成交 & 推送告警/WS
        """
        row = (
            self.db.execute(
                text(
                    "SELECT order_id, ts_code, direction, price, quantity, status FROM orders WHERE order_id = :oid"
                ),
                {"oid": order_id},
            )
            .mappings()
            .fetchone()
        )
        if not row:
            return {"success": False, "error": "订单不存在"}
        if row["status"] not in ("PENDING", "SUBMITTED"):
            return {"success": False, "error": f"订单状态不允许执行: {row['status']}"}

        ts_code = row["ts_code"]
        direction = row["direction"]
        price = float(row["price"])
        quantity = int(row["quantity"])

        cost_info = calculate_trade_cost(
            price, quantity, direction, self.commission_rate, self.tax_rate
        )
        commission = cost_info["commission"]
        tax_amount = cost_info["tax"]
        trade_amount = price * quantity

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

        # 分发到方向特化方法
        try:
            if direction == "BUY":
                self._execute_buy(
                    ts_code, price, quantity, trade_amount, commission, available_cash
                )
            elif direction == "SELL":
                self._execute_sell(
                    ts_code, price, quantity, trade_amount, commission, tax_amount, available_cash
                )
        except ValueError as e:
            return self._reject_order(order_id, ts_code, direction, price, quantity, str(e))

        # 记录成交
        self.db.execute(
            text("""UPDATE orders SET status = 'FILLED', filled_price = :price, filled_quantity = :qty,
                   filled_amount = :amount, commission = :comm, tax = :tax, updated_at = CURRENT_TIMESTAMP
                   WHERE order_id = :oid"""),
            {
                "price": price,
                "qty": quantity,
                "amount": trade_amount,
                "comm": commission,
                "tax": tax_amount,
                "oid": order_id,
            },
        )

        trade_id = f"TRD_{uuid.uuid4().hex[:12]}"
        now = datetime.now()
        self.db.execute(
            text("""INSERT INTO trades (trade_id, order_id, ts_code, direction, price, quantity, amount,
                   commission, tax, trade_date, trade_time, created_at)
                   VALUES (:tid, :oid, :tc, :dir, :price, :qty, :amount, :comm, :tax, :td, :tt, :created)"""),
            {
                "tid": trade_id,
                "oid": order_id,
                "tc": ts_code,
                "dir": direction,
                "price": price,
                "qty": quantity,
                "amount": trade_amount,
                "comm": commission,
                "tax": tax_amount,
                "td": now.date(),
                "tt": now.time(),
                "created": now,
            },
        )

        self.db.commit()
        logger.info(
            f"执行订单成功：{order_id} {direction} {ts_code} {quantity}股 @{price} 佣金={commission:.2f} 税={tax_amount:.2f}"
        )

        # 推送：飞书 + WebSocket
        try:
            from services.feishu_alert import get_alert_service

            fire_alert(
                get_alert_service().send_order_filled(
                    {
                        "order_id": order_id,
                        "ts_code": ts_code,
                        "direction": direction,
                        "price": price,
                        "quantity": quantity,
                        "amount": trade_amount,
                        "commission": commission,
                        "tax": tax_amount,
                    }
                )
            )
        except Exception as e:
            logger.warning(f"订单成交告警失败: {e}")

        try:
            from api.ws_execution import broadcast_order_update, broadcast_position_update

            fire_alert(
                broadcast_order_update(order_id, ts_code, direction, "FILLED", price, quantity)
            )
            fire_alert(
                broadcast_position_update(
                    ts_code, "open" if direction == "BUY" else "close", quantity, price
                )
            )
        except Exception as e:
            logger.warning(f"WebSocket 广播失败: {e}")

        return {
            "success": True,
            "order_id": order_id,
            "trade_id": trade_id,
            "direction": direction,
            "ts_code": ts_code,
            "price": price,
            "quantity": quantity,
            "amount": trade_amount,
            "commission": commission,
            "tax": tax_amount,
            "net_amount": trade_amount - commission - tax_amount
            if direction == "SELL"
            else trade_amount + commission,
        }

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        row = (
            self.db.execute(
                text("SELECT status FROM orders WHERE order_id = :oid"), {"oid": order_id}
            )
            .mappings()
            .fetchone()
        )

        if not row:
            return False

        if row["status"] in ("PENDING", "SUBMITTED"):
            self.db.execute(
                text("""
                UPDATE orders SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP
                WHERE order_id = :oid
            """),
                {"oid": order_id},
            )
            self.db.commit()
            logger.info(f"撤销订单：{order_id}")
            return True
        return False

    # ==================== 查询/摘要 — 委托给 OrderAdmin ====================

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        """从DB查询单个订单 — 委托 order_admin"""
        return self.admin.get_order(order_id)

    def list_orders(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """从DB查询订单列表 — 委托 order_admin"""
        return self.admin.list_orders(status, limit)

    def get_daily_summary(self) -> dict[str, Any]:
        """获取当日交易摘要 — 委托 order_admin"""
        return self.admin.get_daily_summary()

    async def send_daily_summary(self):
        """发送每日摘要到飞书 — 委托 order_admin"""
        await self.admin.send_daily_summary()

    def _update_order_status(self, order_id: str, status: str, error_message: str | None = None):
        """内部方法：更新订单状态"""
        params = {"status": status, "oid": order_id}
        sql = "UPDATE orders SET status = :status, updated_at = CURRENT_TIMESTAMP"
        if error_message:
            sql += ", error_message = :err"
            params["err"] = error_message
        sql += " WHERE order_id = :oid"
        self.db.execute(text(sql), params)
        self.db.commit()

    # ─────────────────── STOP 条件单 — 委托 StopOrderProcessor ───────────

    @property
    def _stop_processor(self) -> StopOrderProcessor:
        """惰性初始化 STOP 处理器"""
        if not hasattr(self, "__stop_proc"):
            self.__stop_proc = StopOrderProcessor(
                db=self.db,
                account_id=self.account_id,
                execute_order_fn=self.execute_order,
            )
        return self.__stop_proc

    def check_stop_orders(self, price_map: dict[str, float]) -> list[dict[str, Any]]:
        """委托 StopOrderProcessor 扫描 STOP 条件单"""
        return self._stop_processor.check_stop_orders(price_map)

    def cancel_expired_orders(self) -> int:
        """委托 StopOrderProcessor 取消过期订单"""
        return self._stop_processor.cancel_expired_orders()
