"""
v5/models/trade.py
==================
Position and trade execution state models.
"""

from enum import Enum
from dataclasses import dataclass, field
import uuid
from typing import Optional


class TradeStage(str, Enum):
    OPEN = "OPEN"
    PARTIAL_1 = "PARTIAL_1"
    PARTIAL_2 = "PARTIAL_2"
    CLOSED = "CLOSED"


@dataclass(slots=True)
class Trade:
    """Represents an active or closed position."""

    symbol: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    original_contracts: float
    stop_price: float
    stop_distance: float
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    remaining_contracts: float = field(init=False)
    stage: TradeStage = TradeStage.OPEN
    entry_time_ms: int = 0
    exit_time_ms: Optional[int] = None
    realized_pnl: float = 0.0
    exit_reason: Optional[str] = None
    score: float = 0.0

    def __post_init__(self):
        if self.entry_price <= 0:
            raise ValueError(f"Entry price must be positive: {self.entry_price}")
        if self.original_contracts <= 0:
            raise ValueError(f"Original contracts must be positive: {self.original_contracts}")
        self.remaining_contracts = self.original_contracts

    @property
    def is_closed(self) -> bool:
        return self.stage == TradeStage.CLOSED

    def calculate_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL for remaining contracts."""
        if self.direction == "LONG":
            return (current_price - self.entry_price) * self.remaining_contracts
        else:
            return (self.entry_price - current_price) * self.remaining_contracts

    def close_partial(self, contracts: float, exit_price: float, reason: str, timestamp_ms: int = 0) -> float:
        """Close partial contracts and update realized PnL."""
        if contracts <= 0 or contracts > self.remaining_contracts + 1e-6:
            raise ValueError(f"Invalid close quantity: {contracts}")

        if self.direction == "LONG":
            pnl = (exit_price - self.entry_price) * contracts
        else:
            pnl = (self.entry_price - exit_price) * contracts

        self.remaining_contracts = max(0.0, self.remaining_contracts - contracts)
        self.realized_pnl += pnl

        if self.remaining_contracts < 1e-6:
            self.stage = TradeStage.CLOSED
            self.exit_time_ms = timestamp_ms
            self.exit_reason = reason

        return pnl

    def close_full(self, exit_price: float, reason: str, timestamp_ms: int = 0) -> float:
        """Close all remaining contracts."""
        return self.close_partial(self.remaining_contracts, exit_price, reason, timestamp_ms)
