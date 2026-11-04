"""
v5/models/portfolio.py
======================
Portfolio capital, equity curve, and circuit breaker tracking.
"""

from dataclasses import dataclass, field
from typing import Dict, List
from .trade import Trade


@dataclass
class PortfolioState:
    """Represents current capital, open exposure, and circuit breaker state."""

    initial_balance: float = 50000.0
    current_balance: float = 50000.0
    peak_balance: float = 50000.0
    open_trades: Dict[str, Trade] = field(default_factory=dict)
    closed_trades: List[Trade] = field(default_factory=list)

    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0

    daily_paused: bool = False
    weekly_halved: bool = False
    monthly_paused: bool = False

    def equity(self, current_prices: Dict[str, float]) -> float:
        """Total account equity = cash balance + open unrealized PnL."""
        unrealized = 0.0
        for sym, trade in self.open_trades.items():
            if sym in current_prices:
                unrealized += trade.calculate_pnl(current_prices[sym])
        return self.current_balance + unrealized

    def drawdown_pct(self, current_prices: Dict[str, float] = None) -> float:
        """Current equity drawdown percentage relative to peak balance."""
        eq = self.equity(current_prices or {})
        if self.peak_balance <= 0:
            return 0.0
        return max(0.0, (self.peak_balance - eq) / self.peak_balance * 100.0)

    def record_pnl(self, realized_pnl: float):
        """Update balances with closed PnL."""
        self.current_balance += realized_pnl
        self.daily_pnl += realized_pnl
        self.weekly_pnl += realized_pnl
        self.monthly_pnl += realized_pnl

        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
