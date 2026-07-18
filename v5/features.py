"""Stateless mathematical calculations for technical indicators.

This module contains pure mathematical computations for EMA, ADX, and ATR.
It has no internal state, no caching, and no external dependencies other than numpy.
"""

import numpy as np


def compute_ema(closes: np.ndarray, period: int) -> np.ndarray:
    """Calculate the Exponential Moving Average (EMA) over a price series.

    Uses standard smoothing multiplier: k = 2 / (period + 1).
    Seeds the EMA with the simple average of the first `period` closes.

    Args:
        closes: Chronologically ordered closes, 1D float array.
        period: The EMA lookback window period (must be >= 1).

    Returns:
        EMA values aligned to the closes. Length = len(closes) - period + 1.
        Returns an empty array of dtype float64 if closes has insufficient length.

    Raises:
        ValueError: If period is less than 1 or if input data is malformed.
    """
    if not isinstance(closes, np.ndarray):
        raise ValueError("Input closes must be a numpy ndarray.")
    if closes.ndim != 1:
        raise ValueError("Input closes must be a 1-dimensional array.")
    if period < 1:
        raise ValueError(f"EMA period must be >= 1, got: {period}")

    # Check for NaN values and raise if any invalid input elements exist
    if np.isnan(closes).any():
        raise ValueError("Input closes array contains NaN values.")

    n = len(closes)
    if n < period:
        return np.array([], dtype=np.float64)

    k = 2.0 / (period + 1)
    
    # Seed with Simple Moving Average of the first `period` closes
    sma = float(np.mean(closes[:period]))
    
    ema_values = np.zeros(n - period + 1, dtype=np.float64)
    ema_values[0] = sma

    for idx in range(period, n):
        ema_values[idx - period + 1] = closes[idx] * k + ema_values[idx - period] * (1.0 - k)

    return ema_values


def _wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """Apply Wilder's smoothing helper logic to an array.

    Wilder's smoothing: first value = sum of first `period` values,
    then smooth_i = smooth_{i-1} - (smooth_{i-1} / period) + value_i.
    """
    n = len(values)
    if n < period:
        return np.array([], dtype=np.float64)
        
    smoothed = np.zeros(n - period + 1, dtype=np.float64)
    smoothed[0] = float(np.sum(values[:period]))
    
    for idx in range(period, n):
        smoothed[idx - period + 1] = smoothed[idx - period] - (smoothed[idx - period] / period) + values[idx]
        
    return smoothed


def compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
    """Calculate the Average Directional Index (ADX) from OHLC arrays.

    Follows Wilder's ADX smoothing and True Range formulation.

    Args:
        highs: Chronologically ordered highs, 1D float array.
        lows: Chronologically ordered lows, 1D float array.
        closes: Chronologically ordered closes, 1D float array.
        period: ADX period window (must be >= 1).

    Returns:
        ADX values. Length = len(closes) - 2 * period + 1.
        Returns an empty array of dtype float64 if inputs have insufficient length.

    Raises:
        ValueError: If input arrays are not of equal length or contain NaNs.
    """
    if not (isinstance(highs, np.ndarray) and isinstance(lows, np.ndarray) and isinstance(closes, np.ndarray)):
        raise ValueError("Inputs highs, lows, and closes must be numpy ndarrays.")
    if highs.ndim != 1 or lows.ndim != 1 or closes.ndim != 1:
        raise ValueError("Input arrays must be 1-dimensional.")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("Input arrays highs, lows, and closes must be of equal length.")
    if period < 1:
        raise ValueError(f"ADX period must be >= 1, got: {period}")

    if np.isnan(highs).any() or np.isnan(lows).any() or np.isnan(closes).any():
        raise ValueError("Input arrays contain NaN values.")

    n = len(closes)
    # Wilder's ADX requires 2 * period data points to start producing values
    if n < 2 * period + 1:
        return np.array([], dtype=np.float64)

    # Step 1: Calculate raw TR, +DM, -DM (length = n - 1)
    tr = np.zeros(n - 1, dtype=np.float64)
    plus_dm = np.zeros(n - 1, dtype=np.float64)
    minus_dm = np.zeros(n - 1, dtype=np.float64)

    for i in range(1, n):
        idx = i - 1
        h = highs[i]
        low_val = lows[i]
        prev_h = highs[idx]
        prev_l = lows[idx]
        prev_c = closes[idx]

        tr[idx] = max(h - low_val, abs(h - prev_c), abs(low_val - prev_c))

        up_move = h - prev_h
        down_move = prev_l - low_val

        plus_dm[idx] = up_move if (up_move > down_move and up_move > 0.0) else 0.0
        minus_dm[idx] = down_move if (down_move > up_move and down_move > 0.0) else 0.0

    # Step 2: Apply Wilder's smoothing
    smooth_tr = _wilder_smooth(tr, period)
    smooth_plus_dm = _wilder_smooth(plus_dm, period)
    smooth_minus_dm = _wilder_smooth(minus_dm, period)

    n_smooth = len(smooth_tr)
    if n_smooth == 0:
        return np.array([], dtype=np.float64)

    # Step 3: Calculate +DI and -DI
    plus_di = np.zeros(n_smooth, dtype=np.float64)
    minus_di = np.zeros(n_smooth, dtype=np.float64)

    for i in range(n_smooth):
        if smooth_tr[i] == 0.0:
            plus_di[i] = 0.0
            minus_di[i] = 0.0
        else:
            plus_di[i] = 100.0 * smooth_plus_dm[i] / smooth_tr[i]
            minus_di[i] = 100.0 * smooth_minus_dm[i] / smooth_tr[i]

    # Step 4: Calculate DX
    dx = np.zeros(n_smooth, dtype=np.float64)
    for i in range(n_smooth):
        di_sum = plus_di[i] + minus_di[i]
        if di_sum == 0.0:
            dx[i] = 0.0
        else:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum

    # Step 5: Smooth DX -> ADX using Wilder's DX smoothing rules
    if len(dx) < period:
        return np.array([], dtype=np.float64)

    adx = np.zeros(len(dx) - period + 1, dtype=np.float64)
    adx[0] = float(np.mean(dx[:period]))

    for i in range(period, len(dx)):
        adx[i - period + 1] = (adx[i - period] * (period - 1) + dx[i]) / period

    return adx


def compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
    """Calculate the Average True Range (ATR) from OHLC arrays.

    Uses Wilder's ATR smoothing.

    Args:
        highs: Chronologically ordered highs, 1D float array.
        lows: Chronologically ordered lows, 1D float array.
        closes: Chronologically ordered closes, 1D float array.
        period: ATR period window (must be >= 1).

    Returns:
        ATR values. Length = len(closes) - period.
        Returns an empty array of dtype float64 if inputs have insufficient length.

    Raises:
        ValueError: If inputs are malformed, not equal length, or contain NaNs.
    """
    if not (isinstance(highs, np.ndarray) and isinstance(lows, np.ndarray) and isinstance(closes, np.ndarray)):
        raise ValueError("Inputs highs, lows, and closes must be numpy ndarrays.")
    if highs.ndim != 1 or lows.ndim != 1 or closes.ndim != 1:
        raise ValueError("Input arrays must be 1-dimensional.")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("Input arrays highs, lows, and closes must be of equal length.")
    if period < 1:
        raise ValueError(f"ATR period must be >= 1, got: {period}")

    if np.isnan(highs).any() or np.isnan(lows).any() or np.isnan(closes).any():
        raise ValueError("Input arrays contain NaN values.")

    n = len(closes)
    if n < period + 1:
        return np.array([], dtype=np.float64)

    # Step 1: Calculate raw TR values (length = n - 1)
    tr = np.zeros(n - 1, dtype=np.float64)
    for i in range(1, n):
        idx = i - 1
        h = highs[i]
        low_val = lows[i]
        prev_c = closes[idx]
        tr[idx] = max(h - low_val, abs(h - prev_c), abs(low_val - prev_c))

    if len(tr) < period:
        return np.array([], dtype=np.float64)

    # Step 2: Smooth TR to get ATR using Wilder's ATR smoothing rules
    atr = np.zeros(len(tr) - period + 1, dtype=np.float64)
    atr[0] = float(np.mean(tr[:period]))

    for i in range(period, len(tr)):
        atr[i - period + 1] = (atr[i - period] * (period - 1) + tr[i]) / period

    return atr
