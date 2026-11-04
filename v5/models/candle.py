"""
v5/models/candle.py
===================
Immutable OHLCV Candle entity with vectorized properties and validation.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Any


@dataclass(frozen=True, slots=True)
class Candle:
    """Represents a validated, immutable single OHLCV candlestick."""

    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self):
        if self.timestamp_ms <= 0:
            raise ValueError(f"Invalid timestamp: {self.timestamp_ms}")
        if self.open <= 0 or self.high <= 0 or self.low <= 0 or self.close <= 0:
            raise ValueError("OHLC prices must be strictly positive.")
        if self.high < max(self.open, self.close) - 1e-4:
            raise ValueError(f"High ({self.high}) cannot be less than open ({self.open}) or close ({self.close}).")
        if self.low > min(self.open, self.close) + 1e-4:
            raise ValueError(f"Low ({self.low}) cannot be greater than open ({self.open}) or close ({self.close}).")
        if self.volume < 0:
            raise ValueError(f"Volume cannot be negative: {self.volume}")

    @property
    def range(self) -> float:
        """Total high-to-low price range."""
        return self.high - self.low

    @property
    def body(self) -> float:
        """Absolute candle body size."""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        """True if close is greater than open."""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """True if close is less than open."""
        return self.close < self.open

    @property
    def upper_wick(self) -> float:
        """Upper shadow length."""
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        """Lower shadow length."""
        return min(self.open, self.close) - self.low

    @property
    def datetime_utc(self) -> datetime:
        """UTC datetime representation."""
        return datetime.fromtimestamp(self.timestamp_ms / 1000.0, tz=timezone.utc)

    def to_ccxt(self) -> List[Any]:
        """Convert to CCXT list format [timestamp_ms, open, high, low, close, volume]."""
        return [self.timestamp_ms, self.open, self.high, self.low, self.close, self.volume]

    @classmethod
    def from_ccxt(cls, row: List[Any]) -> "Candle":
        """Construct from CCXT format row."""
        return cls(
            timestamp_ms=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp_ms,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
