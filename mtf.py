# mtf.py
"""
Multi-Timeframe Trend Alignment Module
=======================================
Reads from the existing in-memory candle buffers (1D, 4H) and decides
whether a LONG or SHORT trade is permitted based on trend alignment
across all monitored timeframes.

LONG conditions (ALL must be true):
  - Daily: Close > EMA200  AND  EMA50 > EMA200
  - 4H:    Market structure = Higher Highs + Higher Lows (last 5 swing points)
  - 4H:    Current price > EMA50

SHORT conditions (ALL must be true — inverted):
  - Daily: Close < EMA200  AND  EMA50 < EMA200
  - 4H:    Market structure = Lower Highs + Lower Lows (last 5 swing points)
  - 4H:    Current price < EMA50

If neither set is fully met → NEUTRAL, no trade allowed.

Triggered on every closed 1H candle from the main event loop.
"""


# ---------------------------------------------------------------------------
# EMA calculation
# ---------------------------------------------------------------------------

def compute_ema(closes, period):
    """
    Calculates the Exponential Moving Average over a list of close prices.

    Uses the standard smoothing multiplier: k = 2 / (period + 1)
    Seeds the EMA with the simple average of the first `period` values,
    then iterates forward.

    Args:
        closes: list[float] — chronologically ordered close prices.
        period: int — EMA look-back window (e.g. 50 or 200).

    Returns:
        list[float] — EMA values aligned to the end of `closes`.
                       Length = len(closes) - period + 1.
                       Returns [] if there aren't enough data points.
    """
    if len(closes) < period:
        return []

    k = 2.0 / (period + 1)

    # Seed: simple moving average of the first `period` closes
    sma = sum(closes[:period]) / period
    ema_values = [sma]

    # Walk forward from index `period` onward
    for price in closes[period:]:
        ema_values.append(price * k + ema_values[-1] * (1.0 - k))

    return ema_values


# ---------------------------------------------------------------------------
# Swing-point detection
# ---------------------------------------------------------------------------

def detect_swing_points(candles, left=2, right=2):
    """
    Identifies swing highs and swing lows in a list of OHLCV candles.

    A swing high at index i means:
        candle[i].high > candle[j].high  for all j in [i-left … i-1, i+1 … i+right]

    A swing low at index i means:
        candle[i].low  < candle[j].low   for all j in [i-left … i-1, i+1 … i+right]

    Args:
        candles: list of [timestamp, open, high, low, close, volume]
        left:    number of bars to the left that must be lower/higher.
        right:   number of bars to the right that must be lower/higher.

    Returns:
        list of dicts sorted chronologically:
        [{"type": "HH"|"LL", "index": i, "value": float, "time": int}, ...]
    """
    swings = []

    for i in range(left, len(candles) - right):
        high_i = candles[i][2]  # index 2 = high
        low_i  = candles[i][3]  # index 3 = low

        # --- Check swing high ---
        is_swing_high = True
        for j in range(i - left, i):
            if candles[j][2] >= high_i:
                is_swing_high = False
                break
        if is_swing_high:
            for j in range(i + 1, i + right + 1):
                if candles[j][2] >= high_i:
                    is_swing_high = False
                    break

        if is_swing_high:
            swings.append({
                "type":  "SH",
                "index": i,
                "value": high_i,
                "time":  candles[i][0],
            })

        # --- Check swing low ---
        is_swing_low = True
        for j in range(i - left, i):
            if candles[j][3] <= low_i:
                is_swing_low = False
                break
        if is_swing_low:
            for j in range(i + 1, i + right + 1):
                if candles[j][3] <= low_i:
                    is_swing_low = False
                    break

        if is_swing_low:
            swings.append({
                "type":  "SL",
                "index": i,
                "value": low_i,
                "time":  candles[i][0],
            })

    # Already chronological because we iterate left-to-right
    return swings


def classify_market_structure(swings, count=5):
    """
    Given a list of swing points (from `detect_swing_points`), looks at the
    last `count` swings and determines whether the market is making:

      - Higher Highs AND Higher Lows  →  "BULLISH"
      - Lower Highs  AND Lower Lows   →  "BEARISH"
      - Anything else                  →  "MIXED"

    Args:
        swings: list of swing dicts from `detect_swing_points`.
        count:  how many recent swings to evaluate (default 5).

    Returns:
        str — "BULLISH", "BEARISH", or "MIXED"
    """
    if len(swings) < count:
        return "MIXED"

    recent = swings[-count:]

    # Separate the recent swings into highs and lows
    recent_highs = [s["value"] for s in recent if s["type"] == "SH"]
    recent_lows  = [s["value"] for s in recent if s["type"] == "SL"]

    # We need at least 2 swing highs and 2 swing lows to judge direction
    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return "MIXED"

    # Check Higher Highs: each successive swing high is higher than the previous
    hh = all(recent_highs[i] > recent_highs[i - 1] for i in range(1, len(recent_highs)))
    # Check Higher Lows: each successive swing low is higher than the previous
    hl = all(recent_lows[i]  > recent_lows[i - 1]  for i in range(1, len(recent_lows)))

    # Check Lower Highs / Lower Lows (inverse)
    lh = all(recent_highs[i] < recent_highs[i - 1] for i in range(1, len(recent_highs)))
    ll = all(recent_lows[i]  < recent_lows[i - 1]  for i in range(1, len(recent_lows)))

    if hh and hl:
        return "BULLISH"
    elif lh and ll:
        return "BEARISH"
    else:
        return "MIXED"


# ---------------------------------------------------------------------------
# Core alignment check
# ---------------------------------------------------------------------------

def check_trend_alignment(buffers, symbol):
    """
    Master function — evaluates multi-timeframe trend alignment.

    Reads the 1D and 4H candle buffers for `symbol`, computes EMAs,
    detects swing structure, and returns an alignment verdict.

    Args:
        buffers: dict — buffers[symbol][timeframe] -> OHLCVBuffer
        symbol:  str  — e.g. "BTC/USDT"

    Returns:
        dict with keys:
            "bias":     "LONG" | "SHORT" | "NEUTRAL"
            "aligned":  bool
            "reason":   str  — human-readable summary of why
            "details":  dict — individual check results for debugging
    """

    details = {}
    reasons_long = []
    reasons_short = []
    failures_long = []
    failures_short = []

    # ------------------------------------------------------------------
    # 1.  DAILY (1D) checks: EMA50, EMA200, close vs EMA200
    # ------------------------------------------------------------------
    daily_candles = buffers[symbol]["1D"].get_candles()
    daily_closes  = [c[4] for c in daily_candles]  # index 4 = close

    if len(daily_closes) < 200:
        details["daily"] = "insufficient data (need 200+ candles)"
        return _neutral(f"Not enough 1D candles ({len(daily_closes)}/200)", details)

    daily_ema50  = compute_ema(daily_closes, 50)
    daily_ema200 = compute_ema(daily_closes, 200)

    current_daily_close = daily_closes[-1]
    latest_ema50_daily  = daily_ema50[-1]
    latest_ema200_daily = daily_ema200[-1]

    details["daily_close"]  = round(current_daily_close, 2)
    details["daily_ema50"]  = round(latest_ema50_daily, 2)
    details["daily_ema200"] = round(latest_ema200_daily, 2)

    # LONG daily conditions
    if current_daily_close > latest_ema200_daily:
        reasons_long.append("1D close > EMA200")
    else:
        failures_long.append("1D close <= EMA200")

    if latest_ema50_daily > latest_ema200_daily:
        reasons_long.append("1D EMA50 > EMA200")
    else:
        failures_long.append("1D EMA50 <= EMA200")

    # SHORT daily conditions
    if current_daily_close < latest_ema200_daily:
        reasons_short.append("1D close < EMA200")
    else:
        failures_short.append("1D close >= EMA200")

    if latest_ema50_daily < latest_ema200_daily:
        reasons_short.append("1D EMA50 < EMA200")
    else:
        failures_short.append("1D EMA50 >= EMA200")

    # ------------------------------------------------------------------
    # 2.  4H checks: market structure + price vs EMA50
    # ------------------------------------------------------------------
    h4_candles = buffers[symbol]["4H"].get_candles()
    h4_closes  = [c[4] for c in h4_candles]

    if len(h4_closes) < 50:
        details["4h"] = "insufficient data (need 50+ candles)"
        return _neutral(f"Not enough 4H candles ({len(h4_closes)}/50)", details)

    # 4H EMA50
    h4_ema50 = compute_ema(h4_closes, 50)
    latest_ema50_4h   = h4_ema50[-1]
    current_4h_close  = h4_closes[-1]

    details["4h_close"] = round(current_4h_close, 2)
    details["4h_ema50"] = round(latest_ema50_4h, 2)

    # 4H price vs EMA50
    if current_4h_close > latest_ema50_4h:
        reasons_long.append("4H close > EMA50")
    else:
        failures_long.append("4H close <= EMA50")

    if current_4h_close < latest_ema50_4h:
        reasons_short.append("4H close < EMA50")
    else:
        failures_short.append("4H close >= EMA50")

    # 4H market structure via swing points
    swings = detect_swing_points(h4_candles, left=2, right=2)
    structure = classify_market_structure(swings, count=5)

    details["4h_structure"]   = structure
    details["4h_swing_count"] = len(swings)

    if structure == "BULLISH":
        reasons_long.append("4H structure: HH + HL")
    else:
        failures_long.append(f"4H structure: {structure} (need BULLISH)")

    if structure == "BEARISH":
        reasons_short.append("4H structure: LH + LL")
    else:
        failures_short.append(f"4H structure: {structure} (need BEARISH)")

    # ------------------------------------------------------------------
    # 3.  Decision
    # ------------------------------------------------------------------
    long_ok  = len(failures_long) == 0
    short_ok = len(failures_short) == 0

    details["long_pass"]     = reasons_long
    details["long_fail"]     = failures_long
    details["short_pass"]    = reasons_short
    details["short_fail"]    = failures_short

    if long_ok:
        return {
            "bias":    "LONG",
            "aligned": True,
            "reason":  "All TFs agree — " + "; ".join(reasons_long),
            "details": details,
        }
    elif short_ok:
        return {
            "bias":    "SHORT",
            "aligned": True,
            "reason":  "All TFs agree — " + "; ".join(reasons_short),
            "details": details,
        }
    else:
        # Build a combined failure summary
        combined_fails = []
        if failures_long:
            combined_fails.append("LONG blocked: " + ", ".join(failures_long))
        if failures_short:
            combined_fails.append("SHORT blocked: " + ", ".join(failures_short))
        return _neutral(" | ".join(combined_fails), details)


def _neutral(reason, details):
    """Helper to return a NEUTRAL result."""
    return {
        "bias":    "NEUTRAL",
        "aligned": False,
        "reason":  reason,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Market Structure State — public wrapper
# ---------------------------------------------------------------------------

def get_market_structure_state(buffers, symbol):
    """
    Returns the current 4H market structure state for `symbol`.

    Wraps detect_swing_points + classify_market_structure for downstream
    consumers (signals, scorer, logger) without duplicating logic.

    Args:
        buffers: dict — buffers[symbol][timeframe] -> OHLCVBuffer
        symbol:  str  — e.g. "BTC/USDT"

    Returns:
        dict:
            "structure":   "BULLISH" | "BEARISH" | "MIXED"
            "last_sh":     float | None  — most recent swing high price
            "last_sl":     float | None  — most recent swing low price
            "swing_count": int
            "source":      "4H"
    """
    h4_candles = buffers[symbol]["4H"].get_candles()
    if len(h4_candles) < 10:
        return {
            "structure": "MIXED",
            "last_sh": None,
            "last_sl": None,
            "swing_count": 0,
            "source": "4H",
        }

    swings = detect_swing_points(h4_candles, left=2, right=2)
    structure = classify_market_structure(swings, count=5)

    last_sh = None
    last_sl = None
    for s in reversed(swings):
        if last_sh is None and s["type"] == "SH":
            last_sh = s["value"]
        if last_sl is None and s["type"] == "SL":
            last_sl = s["value"]
        if last_sh is not None and last_sl is not None:
            break

    return {
        "structure": structure,
        "last_sh": last_sh,
        "last_sl": last_sl,
        "swing_count": len(swings),
        "source": "4H",
    }
