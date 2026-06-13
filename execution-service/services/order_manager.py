"""
订单管理器
订单创建、状态追踪、成交记录、佣金计算、DB持久化
支持: 限价单/市价单/STOP条件单、订单验证、过期取消、每日摘要
"""

import asyncio
from datetime import date, datetime, time, timedelta
from enum import Enum
import logging
import re
from typing import Any
import uuid

from core.config import settings
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fire_alert(coro):
    """安全地在事件循环中调度告警协程（fire-and-forget）"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(coro)
        else:
            loop.run_until_complete(coro)
    except Exception as e:
        logger.debug(f"告警调度失败(非关键): {e}")


DEFAULT_ACCOUNT_ID = "REAL_001"


class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP = "STOP"


class Order:
    """订单模型"""

    def __init__(
        self,
        ts_code: str,
        direction: OrderDirection,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        stop_price: float | None = None,
        trigger_price: float | None = None,
    ):
        self.order_id = f"ORD_{uuid.uuid4().hex[:12]}"
        self.ts_code = ts_code
        self.direction = direction
        self.order_type = order_type
        self.quantity = quantity
        self.price = price
        self.stop_price = stop_price
        self.trigger_price = trigger_price  # STOP条件单触发价
        self.status = OrderStatus.PENDING
        self.filled_quantity = 0
        self.filled_price = 0.0
        self.commission = 0.0
        self.tax = 0.0
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.error_message = None
        self.strategy_name = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "ts_code": self.ts_code,
            "direction": self.direction.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "commission": self.commission,
            "tax": self.tax,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error_message": self.error_message,
        }


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

    def create_order(
        self,
        ts_code: str,
        direction: str,
        order_type: str = "LIMIT",
        price: float | None = None,
        quantity: int = 100,
        strategy_name: str | None = None,
        trigger_price: float | None = None,
    ) -> Order:
        """创建订单并持久化到DB — 含输入验证"""
        # 验证输入
        validation_error = self._validate_order(
            ts_code, direction, order_type, price, quantity, trigger_price
        )
        if validation_error:
            raise ValueError(validation_error)

        # 交易时间检查
        if not settings.ALLOW_OFF_HOURS_TRADING:
            trading_error = self._check_trading_status()
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
                "order_source": "AUTO",
                "strategy_name": strategy_name,
                "trigger_price": trigger_price,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
            },
        )
        self.db.commit()
        logger.info(f"创建订单：{order.order_id} {direction} {ts_code} {quantity}股 @{price}")
        return order

    def execute_order(self, order_id: str) -> dict[str, Any]:
        """
        模拟执行订单
        BUY: 扣减现金，创建/更新持仓
        SELL: 减少持仓，增加现金
        计算佣金（万3）和印花税（千1仅卖出）
        """
        # 获取订单信息
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

        # 计算交易成本
        cost_info = self.calculate_cost(price, quantity, direction)
        commission = cost_info["commission"]
        tax_amount = cost_info["tax"]
        trade_amount = price * quantity

        # 获取账户信息
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

        if direction == "BUY":
            total_deduct = trade_amount + commission
            if available_cash < total_deduct:
                # 资金不足，拒绝
                self._update_order_status(order_id, "REJECTED", error_message="资金不足")
                # 飞书告警：订单拒绝
                try:
                    from services.feishu_alert import get_alert_service

                    alert_svc = get_alert_service()
                    _fire_alert(
                        alert_svc.send_order_rejected(
                            {
                                "ts_code": ts_code,
                                "direction": direction,
                                "quantity": quantity,
                                "price": price,
                                "order_id": order_id,
                            },
                            f"资金不足: 需要¥{total_deduct:.2f}, 可用¥{available_cash:.2f}",
                        )
                    )
                except Exception as e:
                    logger.debug(f"订单拒绝告警失败: {e}")
                # WebSocket 广播：订单拒绝
                try:
                    from api.ws_execution import broadcast_order_update

                    _fire_alert(
                        broadcast_order_update(
                            order_id,
                            ts_code,
                            direction,
                            "REJECTED",
                            price,
                            quantity,
                        )
                    )
                except Exception as e:
                    logger.debug(f"WS广播失败: {e}")
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

            # 创建或更新持仓
            existing = (
                self.db.execute(
                    text("SELECT total_quantity, cost_price FROM positions WHERE ts_code = :tc"),
                    {"tc": ts_code},
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
                           profit_loss = :pnl, profit_loss_ratio = :pnl_ratio, updated_at = CURRENT_TIMESTAMP
                    WHERE ts_code = :tc
                """),
                    {
                        "qty": new_qty,
                        "add_qty": quantity,
                        "cost": new_cost,
                        "price": price,
                        "mv": new_mv,
                        "pnl": pnl,
                        "pnl_ratio": pnl_ratio,
                        "tc": ts_code,
                    },
                )
            else:
                self.db.execute(
                    text("""
                    INSERT INTO positions (ts_code, direction, total_quantity, available_quantity,
                                          cost_price, current_price, market_value, profit_loss,
                                          profit_loss_ratio, opened_at, updated_at)
                    VALUES (:tc, 'LONG', :qty, :qty, :cost, :price, :mv, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                    {
                        "tc": ts_code,
                        "qty": quantity,
                        "cost": price,
                        "price": price,
                        "mv": trade_amount,
                    },
                )

        elif direction == "SELL":
            # 检查持仓
            existing = (
                self.db.execute(
                    text(
                        "SELECT total_quantity, available_quantity, cost_price FROM positions WHERE ts_code = :tc"
                    ),
                    {"tc": ts_code},
                )
                .mappings()
                .fetchone()
            )

            if not existing or int(existing["available_quantity"]) < quantity:
                avail = int(existing["available_quantity"]) if existing else 0
                self._update_order_status(order_id, "REJECTED", error_message="持仓不足")
                # 飞书告警：订单拒绝
                try:
                    from services.feishu_alert import get_alert_service

                    alert_svc = get_alert_service()
                    _fire_alert(
                        alert_svc.send_order_rejected(
                            {
                                "ts_code": ts_code,
                                "direction": direction,
                                "quantity": quantity,
                                "price": price,
                                "order_id": order_id,
                            },
                            f"持仓不足: 需要{quantity}股, 可用{avail}股",
                        )
                    )
                except Exception as e:
                    logger.debug(f"订单拒绝告警失败: {e}")
                # WebSocket 广播：订单拒绝
                try:
                    from api.ws_execution import broadcast_order_update

                    _fire_alert(
                        broadcast_order_update(
                            order_id,
                            ts_code,
                            direction,
                            "REJECTED",
                            price,
                            quantity,
                        )
                    )
                except Exception as e:
                    logger.debug(f"WS广播失败: {e}")
                return {"success": False, "error": f"持仓不足: 需要{quantity}股, 可用{avail}股"}

            # 增加现金 (卖出金额 - 佣金 - 印花税)
            net_income = trade_amount - commission - tax_amount
            new_cash = available_cash + net_income

            old_qty = int(existing["total_quantity"])
            new_qty = old_qty - quantity
            cost_price = float(existing["cost_price"])

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

            if new_qty == 0:
                # 清仓
                self.db.execute(text("DELETE FROM positions WHERE ts_code = :tc"), {"tc": ts_code})
            else:
                new_mv = new_qty * price
                pnl = (price - cost_price) * new_qty
                pnl_ratio = (price - cost_price) / cost_price if cost_price > 0 else 0
                self.db.execute(
                    text("""
                    UPDATE positions SET total_quantity = :qty,
                           available_quantity = available_quantity - :sell_qty,
                           current_price = :price, market_value = :mv,
                           profit_loss = :pnl, profit_loss_ratio = :pnl_ratio,
                           updated_at = CURRENT_TIMESTAMP
                    WHERE ts_code = :tc
                """),
                    {
                        "qty": new_qty,
                        "sell_qty": quantity,
                        "price": price,
                        "mv": new_mv,
                        "pnl": pnl,
                        "pnl_ratio": pnl_ratio,
                        "tc": ts_code,
                    },
                )

        # 更新订单状态为 FILLED
        self.db.execute(
            text("""
            UPDATE orders SET status = 'FILLED', filled_price = :price, filled_quantity = :qty,
                   filled_amount = :amount, commission = :comm, tax = :tax, updated_at = CURRENT_TIMESTAMP
            WHERE order_id = :oid
        """),
            {
                "price": price,
                "qty": quantity,
                "amount": trade_amount,
                "comm": commission,
                "tax": tax_amount,
                "oid": order_id,
            },
        )

        # 写入成交记录
        trade_id = f"TRD_{uuid.uuid4().hex[:12]}"
        now = datetime.now()
        self.db.execute(
            text("""
            INSERT INTO trades (trade_id, order_id, ts_code, direction, price, quantity, amount,
                               commission, tax, trade_date, trade_time, created_at)
            VALUES (:tid, :oid, :tc, :dir, :price, :qty, :amount, :comm, :tax, :td, :tt, :created)
        """),
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

        # 飞书告警：订单成交
        try:
            from services.feishu_alert import get_alert_service

            alert_svc = get_alert_service()
            _fire_alert(
                alert_svc.send_order_filled(
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
            logger.debug(f"订单成交告警失败: {e}")

        # WebSocket 广播：订单成交 + 持仓变更
        try:
            from api.ws_execution import broadcast_order_update, broadcast_position_update

            _fire_alert(
                broadcast_order_update(
                    order_id,
                    ts_code,
                    direction,
                    "FILLED",
                    price,
                    quantity,
                )
            )
            action = "open" if direction == "BUY" else "close"
            _fire_alert(broadcast_position_update(ts_code, action, quantity, price))
        except Exception as e:
            logger.debug(f"WebSocket 广播失败: {e}")

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

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        """从DB查询单个订单"""
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

    def list_orders(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """从DB查询订单列表"""
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

    def calculate_cost(self, price: float, quantity: int, direction: str) -> dict[str, float]:
        """计算交易成本"""
        amount = price * quantity
        commission = amount * self.commission_rate
        commission = max(commission, 5)  # 最低佣金5元

        tax = 0.0
        if direction == "SELL":
            tax = amount * self.tax_rate

        return {
            "amount": amount,
            "commission": commission,
            "tax": tax,
            "total_cost": commission + tax,
            "net_amount": amount - commission - tax,
        }

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

    # ==================== 订单验证 ====================

    TS_CODE_PATTERN = re.compile(r"^\d{6}\.(SZ|SH)$")

    def _validate_order(
        self,
        ts_code: str,
        direction: str,
        order_type: str,
        price: float | None,
        quantity: int,
        trigger_price: float | None = None,
    ) -> str | None:
        """输入校验，返回None表示通过，否则返回错误信息"""
        # TS Code 格式
        if not self.TS_CODE_PATTERN.match(ts_code):
            return f"股票代码格式错误: {ts_code}，正确格式如 600519.SH"

        # Direction
        if direction not in ("BUY", "SELL"):
            return f"交易方向错误: {direction}，仅支持 BUY/SELL"

        # Order type
        if order_type not in ("LIMIT", "MARKET", "STOP"):
            return f"订单类型错误: {order_type}，仅支持 LIMIT/MARKET/STOP"

        # Quantity 正整数且为100的倍数
        if not isinstance(quantity, int) or quantity <= 0:
            return f"数量必须为正整数: {quantity}"
        if quantity % 100 != 0:
            return f"数量必须为100的整数倍（A股最小交易单位）: {quantity}"

        # Price 正数（限价单和STOP单必须）
        if order_type in ("LIMIT", "STOP"):
            if price is None or price <= 0:
                return f"限价单/STOP单必须提供有效价格: {price}"

        # STOP 条件单验证
        if order_type == "STOP":
            if trigger_price is None or trigger_price <= 0:
                return "STOP单必须提供trigger_price（触发价格）"
            if direction == "BUY" and trigger_price <= price:
                return f"买入STOP单触发价({trigger_price})必须 > 当前价({price})"
            if direction == "SELL" and trigger_price >= price:
                return f"卖出STOP单触发价({trigger_price})必须 < 当前价({price})"

        return None  # 通过

    def _check_trading_status(self) -> str | None:
        """检查当前是否在交易时间，返回None表示可交易，否则返回错误信息"""
        now = datetime.now()
        weekday = now.weekday()

        # 周末
        if weekday >= 5:
            return (
                f"非交易日（周末），当前: 周{['一', '二', '三', '四', '五', '六', '日'][weekday]}"
            )

        # 交易时间: 9:30-11:30, 13:00-15:00
        current_time = now.time()
        morning_start = time(9, 30)
        morning_end = time(11, 30)
        afternoon_start = time(13, 0)
        afternoon_end = time(15, 0)

        if not (
            (morning_start <= current_time <= morning_end)
            or (afternoon_start <= current_time <= afternoon_end)
        ):
            return f"非交易时间，当前: {current_time.strftime('%H:%M')}"

        return None

    # ==================== STOP 条件单 ====================

    def check_stop_orders(self, price_map: dict[str, float]) -> list[dict[str, Any]]:
        """
        扫描PENDING的STOP订单，检查是否触发
        price_map: {ts_code: current_price}
        返回: 已触发的订单列表
        """
        triggered = []

        # 获取所有PENDING的STOP订单
        rows = (
            self.db.execute(
                text("""
            SELECT order_id, ts_code, direction, price, quantity, trigger_price, strategy_name
            FROM orders WHERE order_type = 'STOP' AND status = 'PENDING'
        """)
            )
            .mappings()
            .fetchall()
        )

        for row in rows:
            ts_code = row["ts_code"]
            current_price = price_map.get(ts_code)
            if current_price is None:
                continue

            trigger_price = float(row["trigger_price"]) if row["trigger_price"] else None
            direction = row["direction"]

            if trigger_price is None:
                continue

            # 买入STOP: 当前价 >= 触发价 → 触发
            # 卖出STOP: 当前价 <= 触发价 → 触发
            should_trigger = False
            if (
                direction == "BUY"
                and current_price >= trigger_price
                or direction == "SELL"
                and current_price <= trigger_price
            ):
                should_trigger = True

            if should_trigger:
                order_id = row["order_id"]
                logger.info(
                    f"STOP订单触发: {order_id} {ts_code} {direction} @触发价={trigger_price} 现价={current_price}"
                )

                # 转为市价单并执行
                self.db.execute(
                    text("""
                    UPDATE orders SET order_type = 'MARKET', price = :price,
                           status = 'SUBMITTED', updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = :oid
                """),
                    {"price": current_price, "oid": order_id},
                )

                exec_result = self.execute_order(order_id)
                triggered.append(
                    {
                        "order_id": order_id,
                        "ts_code": ts_code,
                        "direction": direction,
                        "trigger_price": trigger_price,
                        "executed_price": current_price,
                        "execution": exec_result,
                    }
                )

        return triggered

    # ==================== 订单过期 ====================

    def cancel_expired_orders(self) -> int:
        """取消过期的PENDING限价单，返回取消数量"""
        expiry_days = settings.ORDER_EXPIRY_DAYS
        cutoff = datetime.now() - timedelta(days=expiry_days)

        result = self.db.execute(
            text("""
            UPDATE orders SET status = 'EXPIRED', error_message = :err,
                   updated_at = CURRENT_TIMESTAMP
            WHERE status = 'PENDING' AND order_type = 'LIMIT' AND created_at < :cutoff
        """),
            {"err": f"订单超过{expiry_days}天未成交已自动取消", "cutoff": cutoff},
        )

        self.db.commit()
        cancelled = result.rowcount
        if cancelled > 0:
            logger.info(f"过期订单清理: {cancelled}个限价单已过期取消")
        return cancelled

    # ==================== 每日摘要 ====================

    def get_daily_summary(self) -> dict[str, Any]:
        """获取当日交易摘要"""
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
                    "SELECT available_cash, total_assets, market_value, day_profit_loss FROM accounts WHERE account_id = :aid"
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
                "total_market_value": float(positions["total_market_value"] or 0)
                if positions
                else 0,
                "total_unrealized_pnl": float(positions["total_unrealized_pnl"] or 0)
                if positions
                else 0,
            },
            "orders_today": [{"status": r["status"], "count": int(r["count"])} for r in orders],
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
