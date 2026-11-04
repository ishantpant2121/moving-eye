"""
v5/indicators/atr.py
====================
Average True Range (ATR) calculation with Wilder's smoothing.
"""

from typing import List, Sequence


def compute_tr(candles: Sequence[Sequence[float]]) -> List[float]:
    """Calculates True Range series for OHLCV candles."""
    if len(candles) < 2:
        return []

    tr_values = []
    for i in range(1, len(candles)):
        h = float(candles[i][2])
        l = float(candles[i][3])
        prev_close = float(candles[i - 1][4])
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        tr_values.append(tr)

    return tr_values


def compute_atr(candles: Sequence[Sequence[float]], period: int = 14) -> List[float]:
    """
    Computes Wilder's smoothed ATR matching legacy regime.py.
    """
    if len(candles) < period + 1 or period <= 0:
        return []

    tr_values = compute_tr(candles)
    if len(tr_values) < period:
        return []

    atr_values = [sum(tr_values[:period]) / period]
    for i in range(period, len(tr_values)):
        atr_values.append((atr_values[-1] * (period - 1) + tr_values[i]) / period)

    return atr_values
