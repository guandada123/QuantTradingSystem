"""
STOP 条件单与过期订单管理
从 order_manager.py 提取，职责单一化：
- check_stop_orders: 扫描 PENDING 的 STOP 订单，检查触发价
- cancel_expired_orders: 取消过期的 PENDING 限价单
"""

from datetime import datetime, timedelta
import logging
from typing import Any

from core.config import settings
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from .alert_utils import fire_alert

logger = logging.getLogger(__name__)


class StopOrderProcessor:
    """STOP 条件单处理器"""

    def __init__(self, db: Session, account_id: str, execute_order_fn, notify_helper=None):
        """
        :param db: 数据库 Session
        :param account_id: 账户 ID
        :param execute_order_fn: 执行订单的回调（order_id: str → dict）
        :param notify_helper: 告警/通知辅助对象（可选）
        """
        self.db = db
        self.account_id = account_id
        self._execute_order = execute_order_fn
        self._notify = notify_helper

    # ─────────────────── STOP 条件单扫描 ───────────────────

    def check_stop_orders(self, price_map: dict[str, float]) -> list[dict[str, Any]]:
        """
        扫描 PENDING 的 STOP 订单，检查是否触发
        price_map: {ts_code: current_price}
        返回: 已触发的订单列表
        """
        triggered = []

        rows = (
            self.db.execute(
                sa_text("""
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

            # 买入 STOP: 当前价 >= 触发价 → 触发
            # 卖出 STOP: 当前价 <= 触发价 → 触发
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
                    f"STOP 订单触发: {order_id} {ts_code} {direction} "
                    f"@触发价={trigger_price} 现价={current_price}"
                )

                # 转为市价单并执行
                self.db.execute(
                    sa_text("""
                    UPDATE orders SET order_type = 'MARKET', price = :price,
                           status = 'SUBMITTED', updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = :oid
                """),
                    {"price": current_price, "oid": order_id},
                )

                exec_result = self._execute_order(order_id)
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

    # ─────────────────── 订单过期清理 ───────────────────

    def cancel_expired_orders(self) -> int:
        """取消过期的 PENDING 限价单，返回取消数量"""
        expiry_days = settings.ORDER_EXPIRY_DAYS
        cutoff = datetime.now() - timedelta(days=expiry_days)

        result = self.db.execute(
            sa_text("""
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
