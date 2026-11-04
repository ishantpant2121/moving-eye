"""
v5/indicators/ema.py
====================
Vectorized and streaming Exponential Moving Average computation.
"""

from typing import List


def compute_ema(closes: List[float], period: int) -> List[float]:
    """
    Computes standard EMA matching legacy v4.1 implementation.
    Seed = simple moving average of first `period` closes.
    Multiplier k = 2.0 / (period + 1).
    """
    if len(closes) < period or period <= 0:
        return []

    k = 2.0 / (period + 1)
    sma = sum(closes[:period]) / period
    ema_values = [sma]

    for price in closes[period:]:
        ema_values.append(price * k + ema_values[-1] * (1.0 - k))

    return ema_values


def compute_ema_series(closes: List[float], period: int) -> List[float]:
    """
    Returns an aligned series of length len(closes), padding with None or NaN
    until the initial seed is reached.
    """
    raw_ema = compute_ema(closes, period)
    if not raw_ema:
        return [float("nan")] * len(closes)

    pad_count = len(closes) - len(raw_ema)
    return [float("nan")] * pad_count + raw_ema


def update_ema_tick(prev_ema: float, new_price: float, period: int) -> float:
    """Incremental streaming update of an existing EMA value."""
    k = 2.0 / (period + 1)
    return new_price * k + prev_ema * (1.0 - k)
