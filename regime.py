# regime.py
"""
Market Regime Classifier
=========================
Classifies the current market regime on the 4H timeframe.

Uses ADX (Average Directional Index) to determine whether the
market is TRENDING or RANGING.

  - ADX > 25  -> TRENDING   (strong directional move in progress)
  - ADX <= 25 -> RANGING    (consolidation, chop, no clear direction)

ADX is calculated from the DI+ and DI- components, which are derived
from directional movement and the Average True Range.

Triggered on every closed 4H candle from the main event loop.
"""

from mtf import compute_ema


def compute_adx(candles, period=14):
    """
    Computes ADX (Average Directional Index) from OHLCV candles.

    Steps:
      1. Calculate True Range (TR), +DM, -DM for each bar.
      2. Smooth TR, +DM, -DM using Wilder's smoothing (period-based).
      3. Calculate +DI and -DI as percentages.
      4. Calculate DX from +DI and -DI.
      5. Smooth DX to get ADX.

    Args:
        candles: list of [timestamp, open, high, low, close, volume]
        period:  ADX period (default 14).

    Returns:
        list of ADX values. Length = len(candles) - 2*period.
        Returns [] if insufficient data.
    """
    if len(candles) < 2 * period + 1:
        return []

    # Step 1: raw TR, +DM, -DM
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(candles)):
        high = candles[i][2]
        low = candles[i][3]
        prev_high = candles[i - 1][2]
        prev_low = candles[i - 1][3]
        prev_close = candles[i - 1][4]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

        up_move = high - prev_high
        down_move = prev_low - low

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    # Step 2: Wilder's smoothing for TR, +DM, -DM
    def wilder_smooth(values, period):
        """Wilder's smoothing: first value = sum of first `period` values,
        then smooth_i = smooth_{i-1} - (smooth_{i-1}/period) + value_i."""
        if len(values) < period:
            return []
        smoothed = [sum(values[:period])]
        for v in values[period:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / period + v)
        return smoothed

    smooth_tr = wilder_smooth(tr_list, period)
    smooth_plus_dm = wilder_smooth(plus_dm_list, period)
    smooth_minus_dm = wilder_smooth(minus_dm_list, period)

    n = min(len(smooth_tr), len(smooth_plus_dm), len(smooth_minus_dm))
    if n == 0:
        return []

    # Step 3: +DI and -DI
    plus_di = []
    minus_di = []
    for i in range(n):
        if smooth_tr[i] == 0:
            plus_di.append(0.0)
            minus_di.append(0.0)
        else:
            plus_di.append(100.0 * smooth_plus_dm[i] / smooth_tr[i])
            minus_di.append(100.0 * smooth_minus_dm[i] / smooth_tr[i])

    # Step 4: DX
    dx_list = []
    for i in range(n):
        di_sum = plus_di[i] + minus_di[i]
        if di_sum == 0:
            dx_list.append(0.0)
        else:
            dx_list.append(100.0 * abs(plus_di[i] - minus_di[i]) / di_sum)

    # Step 5: Smooth DX -> ADX using Wilder's smoothing
    if len(dx_list) < period:
        return []

    adx_values = [sum(dx_list[:period]) / period]
    for dx in dx_list[period:]:
        adx_values.append((adx_values[-1] * (period - 1) + dx) / period)

    return adx_values


def compute_atr(candles, period=14):
    """
    Average True Range.
    Returns a list of ATR values. Length = len(candles) - period.
    Returns [] if insufficient data.
    """
    if len(candles) < period + 1:
        return []

    tr_values = []
    for i in range(1, len(candles)):
        high = candles[i][2]
        low = candles[i][3]
        prev_close = candles[i - 1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)

    if len(tr_values) < period:
        return []

    atr_values = [sum(tr_values[:period]) / period]
    for i in range(period, len(tr_values)):
        atr_values.append((atr_values[-1] * (period - 1) + tr_values[i]) / period)

    return atr_values


def classify_regime(buffers, symbol, period=14, threshold=25.0):
    """
    Classifies the current market regime for `symbol` on the 4H timeframe.
    Supports TRENDING, RANGING, and VOLATILE.

    Args:
        buffers:    dict — buffers[symbol][timeframe] -> OHLCVBuffer
        symbol:     str  — e.g. "BTC/USDT"
        period:     int  — ADX period (default 14).
        threshold:  float — ADX value above which regime is TRENDING.

    Returns:
        dict with keys:
            "regime":  "TRENDING" | "RANGING" | "VOLATILE"
            "adx":     float — current ADX value
            "details": dict  — supplementary data for logging
    """
    import numpy as np

    h4_candles = buffers[symbol]["4H"].get_candles()

    if len(h4_candles) < 200:
        return {
            "regime": "RANGING",
            "adx": 0.0,
            "details": {"error": f"Insufficient 4H data ({len(h4_candles)}/200 candles)"},
        }

    adx_values = compute_adx(h4_candles, period)
    if not adx_values or len(adx_values) < 2:
        return {
            "regime": "RANGING",
            "adx": 0.0,
            "details": {"error": "Insufficient ADX values"},
        }

    atr_values = compute_atr(h4_candles, period)
    if not atr_values or len(atr_values) < 100:
        return {
            "regime": "RANGING",
            "adx": round(adx_values[-1], 2),
            "details": {"error": f"Insufficient ATR values ({len(atr_values) if atr_values else 0}/100)"},
        }

    closes = [c[4] for c in h4_candles]
    ema50 = compute_ema(closes, 50)
    ema200 = compute_ema(closes, 200)

    if not ema50 or len(ema50) < 2 or not ema200:
        return {
            "regime": "RANGING",
            "adx": round(adx_values[-1], 2),
            "details": {"error": "Insufficient EMA values"},
        }

    latest_adx = adx_values[-1]
    prev_adx = adx_values[-2]

    latest_atr = atr_values[-1]
    atr_window = atr_values[-100:]
    p40 = np.percentile(atr_window, 40)
    p85 = np.percentile(atr_window, 85)

    latest_ema50 = ema50[-1]
    prev_ema50 = ema50[-2]
    ema50_slope_positive = latest_ema50 > prev_ema50

    latest_ema200 = ema200[-1]
    current_price = closes[-1]
    price_within_range = abs(current_price - latest_ema200) <= 1.5 * latest_atr

    adx_rising = latest_adx > prev_adx

    # Decision logic
    if 20.0 <= latest_adx <= 25.0:
        # Classify by ATR percentile only
        if latest_atr > p85:
            regime = "VOLATILE"
        elif latest_atr > p40:
            regime = "TRENDING"
        else:
            regime = "RANGING"
    else:
        # Check conditions
        is_volatile = (latest_atr > p85) and adx_rising
        is_trending = (latest_adx > 25.0) and ema50_slope_positive and (latest_atr > p40)
        is_ranging = (latest_adx < 20.0) and price_within_range

        if is_volatile:
            regime = "VOLATILE"
        elif is_trending:
            regime = "TRENDING"
        elif is_ranging:
            regime = "RANGING"
        else:
            regime = "RANGING"

    return {
        "regime": regime,
        "adx": round(latest_adx, 2),
        "details": {
            "p40": round(p40, 2),
            "p85": round(p85, 2),
            "latest_atr": round(latest_atr, 2),
            "adx_rising": adx_rising,
            "ema50_slope_positive": ema50_slope_positive,
            "price_within_range": price_within_range,
        }
    }
