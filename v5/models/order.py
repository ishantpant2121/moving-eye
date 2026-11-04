"""
v5/models/order.py
==================
Order entities and execution state representations.
"""

from enum import Enum
from dataclasses import dataclass, field
import uuid
from typing import Optional


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(slots=True)
class Order:
    """Represents an order and its lifecycle state."""

    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    fee_paid: float = 0.0
    created_at_ms: int = 0

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError(f"Order quantity must be positive: {self.quantity}")

    @property
    def is_complete(self) -> bool:
        return self.status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}

    def fill(self, fill_qty: float, fill_price: float, fee: float = 0.0):
        """Execute a fill against the order."""
        if fill_qty <= 0 or fill_price <= 0:
            raise ValueError("Fill quantity and price must be positive.")
        if self.filled_quantity + fill_qty > self.quantity + 1e-6:
            raise ValueError("Cumulative fill exceeds order quantity.")

        # Update VWAP fill price
        total_value = (self.filled_quantity * self.average_fill_price) + (fill_qty * fill_price)
        self.filled_quantity += fill_qty
        self.average_fill_price = total_value / self.filled_quantity
        self.fee_paid += fee

        if abs(self.filled_quantity - self.quantity) < 1e-6:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED
