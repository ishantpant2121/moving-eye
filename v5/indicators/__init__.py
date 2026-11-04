"""v5 Modular Technical Indicator Engine."""

from .ema import compute_ema, compute_ema_series
from .atr import compute_atr, compute_tr
from .adx import compute_adx
from .bollinger import compute_bollinger_bands, BollingerBands
from .patterns import detect_candlestick_pattern, CandlestickPattern

__all__ = [
    "compute_ema",
    "compute_ema_series",
    "compute_atr",
    "compute_tr",
    "compute_adx",
    "compute_bollinger_bands",
    "BollingerBands",
    "detect_candlestick_pattern",
    "CandlestickPattern",
]
