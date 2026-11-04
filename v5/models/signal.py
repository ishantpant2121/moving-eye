"""
v5/models/signal.py
===================
Signal domain model representing generated trading setups.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


class SignalType(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalMode(str, Enum):
    A = "A"  # Breakout
    B = "B"  # Pullback
    R = "R"  # Mean Reversion


@dataclass(frozen=True, slots=True)
class Signal:
    """Represents a validated entry signal."""

    symbol: str
    mode: SignalMode
    type: SignalType
    price: float
    atr: float
    rvol: float
    timestamp_ms: int
    score: float = 0.0
    mss: bool = False
    pattern: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.price <= 0:
            raise ValueError(f"Signal price must be positive: {self.price}")
        if self.atr <= 0:
            raise ValueError(f"Signal ATR must be positive: {self.atr}")
        if self.rvol < 0:
            raise ValueError(f"Signal RVOL cannot be negative: {self.rvol}")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"Signal score must be between 0.0 and 1.0: {self.score}")

    @property
    def is_strong(self) -> bool:
        """Score >= 0.85 threshold."""
        return self.score >= 0.85

    @property
    def is_executable(self) -> bool:
        """Score >= 0.70 threshold."""
        return self.score >= 0.70

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary matching legacy signals format."""
        return {
            "pair": self.symbol,
            "mode": self.mode.value,
            "type": self.type.value,
            "signal": f"MODE_{self.mode.value}_{self.type.value}",
            "price": self.price,
            "atr": self.atr,
            "rvol": self.rvol,
            "timestamp_ms": self.timestamp_ms,
            "score": self.score,
            "mss": self.mss,
            "pattern": self.pattern,
            "metadata": dict(self.metadata),
        }
