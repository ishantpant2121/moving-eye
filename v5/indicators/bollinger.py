"""
v5/indicators/bollinger.py
==========================
Bollinger Bands and Bandwidth indicator calculations.
"""

from dataclasses import dataclass
from typing import List
import math


@dataclass(frozen=True, slots=True)
class BollingerBands:
    upper: float
    middle: float
    lower: float
    bandwidth: float
    percent_b: float


def compute_bollinger_bands(closes: List[float], period: int = 20, num_std: float = 2.0) -> List[BollingerBands]:
    """
    Computes rolling Bollinger Bands over close prices.
    Returns list of BollingerBands objects.
    """
    if len(closes) < period or period <= 0:
        return []

    results = []
    for i in range(period, len(closes) + 1):
        window = closes[i - period:i]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std = math.sqrt(variance)

        upper = sma + num_std * std
        lower = sma - num_std * std
        bandwidth = (upper - lower) / sma if sma > 0 else 0.0

        current_close = window[-1]
        percent_b = (current_close - lower) / (upper - lower) if (upper - lower) > 0 else 0.5

        results.append(BollingerBands(
            upper=round(upper, 4),
            middle=round(sma, 4),
            lower=round(lower, 4),
            bandwidth=round(bandwidth, 6),
            percent_b=round(percent_b, 4),
        ))

    return results
