"""
v5/indicators/patterns.py
=========================
Candlestick pattern recognition engine matching legacy signals.py rules:
- Bullish Engulfing
- Bearish Engulfing
- Hammer
- Shooting Star
"""

from enum import Enum
from typing import Sequence, Optional


class CandlestickPattern(str, Enum):
    BULLISH_ENGULFING = "BULLISH_ENGULFING"
    BEARISH_ENGULFING = "BEARISH_ENGULFING"
    HAMMER = "HAMMER"
    SHOOTING_STAR = "SHOOTING_STAR"


def detect_candlestick_pattern(candles: Sequence[Sequence[float]]) -> Optional[str]:
    """
    Scans the latest bars in `candles` for key reversal patterns.
    Candles are formatted as: [timestamp, open, high, low, close, volume]
    """
    if len(candles) < 2:
        return None

    # Current bar
    curr = candles[-1]
    curr_o, curr_h, curr_l, curr_c = float(curr[1]), float(curr[2]), float(curr[3]), float(curr[4])
    curr_body = abs(curr_c - curr_o)
    curr_range = curr_h - curr_l

    # Previous bar
    prev = candles[-2]
    prev_o, prev_c = float(prev[1]), float(prev[4])

    if curr_range <= 0:
        return None

    # 1. Bullish Engulfing: previous bar was red, current bar is green and engulfs body
    if prev_c < prev_o and curr_c > curr_o:
        if curr_o <= prev_c and curr_c >= prev_o:
            return CandlestickPattern.BULLISH_ENGULFING.value

    # 2. Bearish Engulfing: previous bar was green, current bar is red and engulfs body
    if prev_c > prev_o and curr_c < curr_o:
        if curr_o >= prev_c and curr_c <= prev_o:
            return CandlestickPattern.BEARISH_ENGULFING.value

    # 3. Hammer: small body at top, lower shadow >= 2x body, upper shadow <= 0.1x range
    lower_shadow = min(curr_o, curr_c) - curr_l
    upper_shadow = curr_h - max(curr_o, curr_c)
    if curr_body > 0 and lower_shadow >= 2.0 * curr_body and upper_shadow <= 0.2 * curr_range:
        return CandlestickPattern.HAMMER.value

    # 4. Shooting Star: small body at bottom, upper shadow >= 2x body, lower shadow <= 0.1x range
    if curr_body > 0 and upper_shadow >= 2.0 * curr_body and lower_shadow <= 0.2 * curr_range:
        return CandlestickPattern.SHOOTING_STAR.value

    return None
