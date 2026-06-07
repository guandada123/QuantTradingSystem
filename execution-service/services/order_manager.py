"""
订单管理器
订单创建、状态追踪、成交记录、佣金计算
"""

import uuid
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

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
        price: Optional[float] = None,
        stop_price: Optional[float] = None
    ):
        self.order_id = f"ORD_{uuid.uuid4().hex[:12]}"
        self.ts_code = ts_code
        self.direction = direction
        self.order_type = order_type
        self.quantity = quantity
        self.price = price
        self.stop_price = stop_price
        self.status = OrderStatus.PENDING
        self.filled_quantity = 0
        self.filled_price = 0.0
        self.commission = 0.0
        self.tax = 0.0
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.error_message = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'order_id': self.order_id,
            'ts_code': self.ts_code,
            'direction': self.direction.value,
            'order_type': self.order_type.value,
            'quantity': self.quantity,
            'price': self.price,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'filled_price': self.filled_price,
            'commission': self.commission,
            'tax': self.tax,
            'created_at': self.created_at.isoformat()
        }

class OrderManager:
    """订单管理器"""
    
    def __init__(self, commission_rate: float = 0.0003, tax_rate: float = 0.001):
        self.commission_rate = commission_rate  # 佣金率（万3）
        self.tax_rate = tax_rate  # 印花税率（千1，仅卖出）
        self.orders: Dict[str, Order] = {}
        self.miniqmt_connector = None
    
    def create_order(
        self,
        ts_code: str,
        direction: str,
        order_type: str = "LIMIT",
        price: Optional[float] = None,
        quantity: int = 100
    ) -> Order:
        """创建订单"""
        order = Order(
            ts_code=ts_code,
            direction=OrderDirection(direction),
            order_type=OrderType(order_type),
            quantity=quantity,
            price=price
        )
        self.orders[order.order_id] = order
        logger.info(f"创建订单：{order.order_id} {direction} {ts_code} {quantity}股")
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        if order_id in self.orders:
            order = self.orders[order_id]
            if order.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.now()
                logger.info(f"撤销订单：{order_id}")
                return True
        return False
    
    def calculate_cost(self, price: float, quantity: int, direction: str) -> Dict[str, float]:
        """计算交易成本"""
        amount = price * quantity
        commission = amount * self.commission_rate
        if commission < 5:
            commission = 5  # 最低佣金5元
        
        tax = 0.0
        if direction == 'SELL':
            tax = amount * self.tax_rate
        
        return {
            'amount': amount,
            'commission': commission,
            'tax': tax,
            'total_cost': commission + tax,
            'net_amount': amount - commission - tax
        }
