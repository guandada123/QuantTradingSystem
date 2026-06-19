"""
订单数据模型 — 枚举定义 + Order 实体类
从 order_manager.py 提取，消除 567 行单文件中的 ~70 行模型代码
"""

from datetime import datetime
from enum import Enum
from typing import Any
import uuid


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
