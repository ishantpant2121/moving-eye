# signals.py
"""
Entry Signal Engine
====================
Runs on every closed 1H candle. Detects two types of entry setups:

  MODE A — Breakout:
    - Price closes above resistance (top 3 recent swing highs)
    - RVOL > 1.5
    - ATR expanding (current ATR > mean of last 5 ATRs)
    - Volume trend slope positive (numpy polyfit on last 10 volume bars)

  MODE B — Pullback:
    - Price within 0.3% of EMA50 on 1H
    - Bullish engulfing OR hammer candle
    - RSI(14) between 40 and 55
    - RVOL > 1.0

Gate: only runs when regime == "TRENDING" AND aligned == True.
If the gate is closed, returns None immediately.

This module does NOT place orders. It only reports setups.
"""

import numpy as np
from mtf import compute_ema, detect_swing_points, classify_market_structure
import config


# ──────────────────────────────────────────────────────────────
# Mode B Asset Allow-List
# ──────────────────────────────────────────────────────────────
# Diagnostics (2021–2026, 300 trades) show Mode B has a proven edge
# only on BTC and LINK (OOS PF: 1.90 and 1.64 respectively).
# On SOL, BNB, AVAX (PF 0.83–1.03) excessive microvolatility stops out
# valid pullback setups within hours — no filter combination fixes this.
# Adding a new symbol requires re-running the diagnostic pipeline first.
MODE_B_ALLOWED_SYMBOLS = {"BTC/USDT", "LINK/USDT"}

# ──────────────────────────────────────────────────────────────
# Global Configuration Flags
# ──────────────────────────────────────────────────────────────
ENABLE_MODE_R = False


# ──────────────────────────────────────────────────────────────
# Technical indicator helpers
# ──────────────────────────────────────────────────────────────

def compute_rsi(closes, period=14):
    """
    Relative Strength Index.
    Returns a list of RSI values. Length = len(closes) - period.
    Returns [] if insufficient data.
    """
    if len(closes) < period + 1:
        return []

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Seed averages with the first `period` deltas
    gains = [d if d > 0 else 0.0 for d in deltas[:period]]
    losses = [-d if d < 0 else 0.0 for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    rsi_values = []

    # First RSI value
    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100.0 - 100.0 / (1.0 + rs))

    # Walk forward using Wilder's smoothing (same as EMA with period-based decay)
    for i in range(period, len(deltas)):
        d = deltas[i]
        gain = d if d > 0 else 0.0
        loss = -d if d < 0 else 0.0

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100.0 - 100.0 / (1.0 + rs))

    return rsi_values


def compute_atr(candles, period=14):
    """
    Average True Range.
    Returns a list of ATR values. Length = len(candles) - period.
    Returns [] if insufficient data.

    True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
    """
    if len(candles) < period + 1:
        return []

    # Calculate True Range for each candle starting from index 1
    tr_values = []
    for i in range(1, len(candles)):
        high = candles[i][2]
        low = candles[i][3]
        prev_close = candles[i - 1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)

    # Seed ATR with the SMA of the first `period` True Range values
    if len(tr_values) < period:
        return []

    atr_values = [sum(tr_values[:period]) / period]

    # Walk forward using Wilder's smoothing
    for i in range(period, len(tr_values)):
        atr_values.append((atr_values[-1] * (period - 1) + tr_values[i]) / period)

    return atr_values


def compute_rvol(volumes, lookback=20):
    """
    Relative Volume.
    Current volume divided by the average of the previous `lookback` bars.
    Returns the RVOL for the last bar only, or None if insufficient data.
    """
    if len(volumes) < lookback + 1:
        return None

    avg_vol = sum(volumes[-(lookback + 1):-1]) / lookback
    if avg_vol == 0:
        return None

    return volumes[-1] / avg_vol


def volume_slope(volumes, lookback=10):
    """
    Linear regression slope of the last `lookback` volume bars.
    Uses numpy polyfit (degree 1). Returns the slope coefficient.
    Positive slope = volume trending up.
    Returns None if insufficient data.
    """
    if len(volumes) < lookback:
        return None

    recent = volumes[-lookback:]
    x = np.arange(lookback, dtype=float)
    y = np.array(recent, dtype=float)

    # polyfit returns [slope, intercept]
    coeffs = np.polyfit(x, y, 1)
    return coeffs[0]


# ──────────────────────────────────────────────────────────────
# Resistance detection
# ──────────────────────────────────────────────────────────────

def find_resistance_levels(candles, count=3):
    """
    Returns the `count` most recent swing highs from the 1H candle buffer.
    These act as resistance levels for breakout detection.

    Args:
        candles: list of [timestamp, open, high, low, close, volume]
        count:   how many recent swing highs to return.

    Returns:
        list of floats — swing high price values, most recent last.
    """
    swings = detect_swing_points(candles, left=2, right=2)
    swing_highs = [s["value"] for s in swings if s["type"] == "SH"]

    # Return the most recent `count` swing highs
    return swing_highs[-count:] if len(swing_highs) >= count else swing_highs


# ──────────────────────────────────────────────────────────────
# Candlestick pattern detection
# ──────────────────────────────────────────────────────────────

def is_bullish_engulfing(candles):
    """
    Checks if the last two candles form a bullish engulfing pattern.
    Requirements:
      - Current candle: close > previous open
      - Current candle: open  < previous close
    (Implies previous candle was bearish, current candle engulfs it.)

    Args:
        candles: list of at least 2 OHLCV candles.

    Returns:
        bool
    """
    if len(candles) < 2:
        return False

    prev = candles[-2]  # [ts, open, high, low, close, vol]
    curr = candles[-1]

    prev_open = prev[1]
    prev_close = prev[4]
    curr_open = curr[1]
    curr_close = curr[4]

    return curr_close > prev_open and curr_open < prev_close


def is_hammer(candle):
    """
    Checks if a single candle is a hammer.
    Requirements:
      - Lower wick >= 2x the body size
      - Close is in the upper 30% of the candle range

    Args:
        candle: [timestamp, open, high, low, close, volume]

    Returns:
        bool
    """
    o = candle[1]
    h = candle[2]
    l = candle[3]
    c = candle[4]

    body = abs(c - o)
    candle_range = h - l

    if candle_range == 0:
        return False

    # Lower wick = distance from the lower of open/close to the low
    lower_wick = min(o, c) - l

    # Body size check: lower wick >= 2x body
    body_check = lower_wick >= 2.0 * body

    # Close position check: close in upper 30% of the candle range
    close_pct = (c - l) / candle_range
    position_check = close_pct >= 0.70

    return body_check and position_check


# ──────────────────────────────────────────────────────────────
# Pullback Depth Detection Helper
# ──────────────────────────────────────────────────────────────

def detect_impulse_and_pullback(h1_candles, current_atr, entry_price, direction):
    """
    Measures the depth of the pullback prior to breakout entry.
    Identifies impulse swings to calculate retracement percentage.
    """
    from mtf import detect_swing_points
    h1_swings = detect_swing_points(h1_candles, left=2, right=2)
    if not h1_swings:
        return 0.0, 0.0, 0, 0.0, 0.0
    
    SL_val, HH_val, HH_idx = None, None, None
    SH_val, LL_val, LL_idx = None, None, None
    
    if direction == "LONG":
        for s in reversed(h1_swings):
            if s["type"] == "SL":
                sl_idx = s["index"]
                candles_sub = h1_candles[sl_idx:]
                hh_v = max(c[2] for c in candles_sub)
                hh_i = sl_idx + np.argmax([c[2] for c in candles_sub])
                if hh_v - s["value"] > 1.0 * current_atr:
                    SL_val = s["value"]
                    HH_val = hh_v
                    HH_idx = hh_i
                    break
        
        if SL_val is None:
            for s in reversed(h1_swings):
                if s["type"] == "SL":
                    SL_val = s["value"]
                    sl_idx = s["index"]
                    candles_sub = h1_candles[sl_idx:]
                    HH_val = max(c[2] for c in candles_sub)
                    HH_idx = sl_idx + np.argmax([c[2] for c in candles_sub])
                    break
                    
        if SL_val is not None and HH_val is not None:
            imp_size_atr = (HH_val - SL_val) / current_atr if current_atr > 0 else 0.0
            pb_depth = (HH_val - entry_price) / (HH_val - SL_val) * 100.0 if (HH_val - SL_val) > 0 else 0.0
            pb_duration = len(h1_candles) - 1 - HH_idx
            return imp_size_atr, pb_depth, pb_duration, SL_val, HH_val
            
    else: # SHORT
        for s in reversed(h1_swings):
            if s["type"] == "SH":
                sh_idx = s["index"]
                candles_sub = h1_candles[sh_idx:]
                ll_v = min(c[3] for c in candles_sub)
                ll_i = sh_idx + np.argmin([c[3] for c in candles_sub])
                if s["value"] - ll_v > 1.0 * current_atr:
                    SH_val = s["value"]
                    LL_val = ll_v
                    LL_idx = ll_i
                    break
                    
        if SH_val is None:
            for s in reversed(h1_swings):
                if s["type"] == "SH":
                    SH_val = s["value"]
                    sh_idx = s["index"]
                    candles_sub = h1_candles[sh_idx:]
                    LL_val = min(c[3] for c in candles_sub)
                    LL_idx = sh_idx + np.argmin([c[3] for c in candles_sub])
                    break
                    
        if SH_val is not None and LL_val is not None:
            imp_size_atr = (SH_val - LL_val) / current_atr if current_atr > 0 else 0.0
            pb_depth = (entry_price - LL_val) / (SH_val - LL_val) * 100.0 if (SH_val - LL_val) > 0 else 0.0
            pb_duration = len(h1_candles) - 1 - LL_idx
            return imp_size_atr, pb_depth, pb_duration, SH_val, LL_val

    return 0.0, 0.0, 0, 0.0, 0.0


def check_liquidity_sweep(h1_candles):
    """
    Experiment A: Liquidity Sweep Detector on 1H timeframe.
    - Bullish sweep: Low sweeps previous swing low, close back above swing low.
    - Bearish sweep: High sweeps previous swing high, close back below swing high.
    """
    swings = detect_swing_points(h1_candles[:-1], left=2, right=2)
    sh_vals = [s["value"] for s in swings if s["type"] == "SH"]
    sl_vals = [s["value"] for s in swings if s["type"] == "SL"]
    
    last_sh = sh_vals[-1] if sh_vals else None
    last_sl = sl_vals[-1] if sl_vals else None
    
    curr_high = h1_candles[-1][2]
    curr_low = h1_candles[-1][3]
    curr_close = h1_candles[-1][4]
    
    bullish_sweep = False
    bearish_sweep = False
    
    if last_sl is not None and curr_low < last_sl and curr_close > last_sl:
        bullish_sweep = True
    if last_sh is not None and curr_high > last_sh and curr_close < last_sh:
        bearish_sweep = True
        
    return bullish_sweep, bearish_sweep

def check_mss(h1_candles):
    """
    Experiment B: Market Structure Shift (MSS / CHOCH) on 1H timeframe.
    - Bullish MSS: LL formed, break above previous LH.
    - Bearish MSS: HH formed, break below previous HL.
    """
    swings = detect_swing_points(h1_candles[:-1], left=2, right=2)
    sl_points = [s for s in swings if s["type"] == "SL"]
    sh_points = [s for s in swings if s["type"] == "SH"]
    
    bullish_mss = False
    bearish_mss = False
    
    # Bullish MSS
    if len(sl_points) >= 2 and len(sh_points) >= 1:
        last_sl = sl_points[-1]
        prev_sl = sl_points[-2]
        last_sh = sh_points[-1]
        if last_sl["value"] < prev_sl["value"] and last_sl["index"] > last_sh["index"]:
            if h1_candles[-1][4] > last_sh["value"]:
                bullish_mss = True
                
    # Bearish MSS
    if len(sh_points) >= 2 and len(sl_points) >= 1:
        last_sh = sh_points[-1]
        prev_sh = sh_points[-2]
        last_sl = sl_points[-1]
        if last_sh["value"] > prev_sh["value"] and last_sh["index"] > last_sl["index"]:
            if h1_candles[-1][4] < last_sl["value"]:
                bearish_mss = True
                
    return bullish_mss, bearish_mss

# ──────────────────────────────────────────────────────────────
# Main signal scanner
# ──────────────────────────────────────────────────────────────

def scan_entry(buffers, symbol, regime, alignment, on_reject_cb=None,
               regime_transition_bonus=None, moderate_pullback_bonus=None,
               breakout_filter_config=None, regime_history=None):
    """
    Master function — scans for entry signals on the 1H timeframe.

    Gate conditions (both must be true to proceed):
      - regime  == "TRENDING"
      - alignment["aligned"] == True

    If the gate is closed, returns None immediately.
    """

    # ── Ranging markets route ───────────────────────────────────
    if regime == "RANGING":
        if not ENABLE_MODE_R:
            if on_reject_cb:
                on_reject_cb("mode_r_disabled")
            return None
        return range_scan_entry(buffers, symbol, alignment, on_reject_cb)

    # ── Gate check ──────────────────────────────────────────────
    if regime not in ["TRENDING", "VOLATILE"]:
        return None

    if not alignment or not alignment.get("aligned", False):
        return None

    bias = alignment.get("bias", "NEUTRAL")
    if bias == "NEUTRAL":
        return None

    # --- ADX exhaustion check ---
    import regime as rgm
    h4_candles = buffers[symbol]["4H"].get_candles()
    adx_values = rgm.compute_adx(h4_candles, period=14)
    adx_val = adx_values[-1] if adx_values else 0.0
    prev_adx_val = adx_values[-2] if adx_values and len(adx_values) >= 2 else 0.0
    adx_rising = adx_val > prev_adx_val

    # Recent Regime Transition
    transition = "NO_TRANSITION"
    if regime_history and len(regime_history) >= 2:
        curr_r = regime_history[-1][1]
        prev_r = None
        for item in reversed(regime_history[:-1]):
            if item[1] != curr_r:
                prev_r = item[1]
                break
        if prev_r is not None:
            transition = f"{prev_r} -> {curr_r}"

    if regime_transition_bonus is None:
        regime_transition_bonus = getattr(config, "ENABLE_REGIME_TRANSITION_BONUS", False)
    if moderate_pullback_bonus is None:
        moderate_pullback_bonus = getattr(config, "ENABLE_PULLBACK_DEPTH_BONUS", False)

    # ── Pull 1H candle data ─────────────────────────────────────
    h1_candles = buffers[symbol]["1H"].get_candles()
    if len(h1_candles) < 50:
        return None  # Not enough data to compute anything meaningful

    h1_closes = [c[4] for c in h1_candles]
    h1_volumes = [c[5] for c in h1_candles]

    current_candle = h1_candles[-1]
    current_close = h1_closes[-1]

    # ── Compute shared indicators ──────────────────────────────
    # ATR(14)
    atr_values = compute_atr(h1_candles, period=14)
    if not atr_values:
        return None
    current_atr = atr_values[-1]

    # RVOL (current volume / 20-bar average)
    rvol = compute_rvol(h1_volumes, lookback=20)
    if rvol is None:
        return None

    # RSI(14)
    rsi_values = compute_rsi(h1_closes, period=14)
    if not rsi_values:
        return None
    current_rsi = rsi_values[-1]

    # EMA50 on 1H
    ema50_values = compute_ema(h1_closes, 50)
    if not ema50_values:
        return None
    current_ema50 = ema50_values[-1]

    # Volume slope (last 10 bars)
    vol_slope = volume_slope(h1_volumes, lookback=10)

    # ── MODE B V2 — Crypto-native Pullback (Check First) ───────
    if symbol in MODE_B_ALLOWED_SYMBOLS:
        signal_b = _check_mode_b_v2(
            h1_candles, h4_candles, current_close, current_ema50,
            rvol, bias, symbol, current_atr, atr_values, h1_volumes, on_reject_cb
        )
        if signal_b is not None:
            signal_b["regime_transition_bonus"] = regime_transition_bonus
            signal_b["moderate_pullback_bonus"] = moderate_pullback_bonus
            signal_b["recent_transition"] = transition
            return signal_b

    # ── MODE A — Breakout (Check Second) ───────────────────────
    if adx_val > 50.0:
        print(f"[SKIP] ADX too extended: {adx_val:.1f}")
        signal_a = None
    else:
        signal_a = _check_mode_a(
            h1_candles, current_close, rvol, atr_values,
            vol_slope, bias, symbol, current_atr, on_reject_cb,
            filter_config=breakout_filter_config, adx_rising=adx_rising
        )
    if signal_a is not None:
        signal_a["regime_transition_bonus"] = regime_transition_bonus
        signal_a["moderate_pullback_bonus"] = moderate_pullback_bonus
        signal_a["recent_transition"] = transition

        from scorer import score_signal
        reg_res = {"regime": "TRENDING"} # scorer needs regime == "TRENDING" for full weight
        score_res = score_signal(signal_a, reg_res, alignment)
        if score_res["score"] >= 0.80:
            signal_a["score"] = score_res["score"]
            return signal_a

    # No signal found
    return None


# ──────────────────────────────────────────────────────────────
# Mode A — Breakout
# ──────────────────────────────────────────────────────────────

def _check_mode_a(h1_candles, current_close, rvol, atr_values,
                   vol_slope, bias, symbol, current_atr, on_reject_cb=None,
                   filter_config=None, adx_rising=True):
    """
    Breakout entry checks with A/B test experiments (A-E).
    """

    # --- Resistance / support levels ---
    recent_candles = h1_candles[-50:] if len(h1_candles) >= 50 else h1_candles
    resistance_levels = find_resistance_levels(recent_candles, count=3)

    if not resistance_levels:
        return None  # Can't detect resistance without swing data

    # Resolve Experiment Configs (Task 4)
    rvol_thresh = 1.5
    check_vol_slope = True
    check_adx_rising = False
    
    if filter_config == "A":
        rvol_thresh = 1.5
        check_vol_slope = False
        check_adx_rising = False
    elif filter_config == "B":
        rvol_thresh = 2.0
        check_vol_slope = False
        check_adx_rising = False
    elif filter_config == "C":
        rvol_thresh = 2.0
        check_vol_slope = False
        check_adx_rising = True
    elif filter_config == "D":
        rvol_thresh = 2.0
        check_vol_slope = True
        check_adx_rising = False
    elif filter_config == "E":
        rvol_thresh = 2.0
        check_vol_slope = True
        check_adx_rising = True

    # Check: RVOL
    if rvol <= rvol_thresh:
        if on_reject_cb:
            on_reject_cb("volume")
        return None

    # Check: ADX rising
    if check_adx_rising and not adx_rising:
        return None

    # Check: ATR expanding
    if len(atr_values) < 6:
        return None
    avg_atr_5 = sum(atr_values[-6:-1]) / 5
    if current_atr <= avg_atr_5:
        return None

    # Check: volume slope
    if check_vol_slope:
        if vol_slope is None or vol_slope <= 0:
            return None

    # Bullish / Bearish Sweeps and MSS
    bullish_sweep, bearish_sweep = check_liquidity_sweep(h1_candles)
    bullish_mss, bearish_mss = check_mss(h1_candles)

    # --- Direction-specific checks ---
    if bias == "LONG":
        broken_resistance = [r for r in resistance_levels if current_close > r]
        if not broken_resistance:
            return None

        # Sweeps filter
        enable_sweeps = getattr(config, "ENABLE_LIQUIDITY_SWEEPS", False)
        sweep_mode = getattr(config, "LIQUIDITY_SWEEP_MODE", "both")
        if enable_sweeps == "filter" and (sweep_mode == "both" or sweep_mode == "A"):
            if not bullish_sweep:
                return None

        # MSS filter
        enable_mss = getattr(config, "ENABLE_MSS", False)
        mss_mode = getattr(config, "MSS_MODE", "both")
        if enable_mss in ["filter", "trend_continuation"] and (mss_mode == "both" or mss_mode == "A"):
            if not bullish_mss:
                return None

        _, pb_depth, _, _, _ = detect_impulse_and_pullback(h1_candles, current_atr, current_close, "LONG")

        return {
            "signal": "LONG_A",
            "mode": "A",
            "type": "BREAKOUT",
            "pair": symbol,
            "price": round(current_close, 2),
            "atr": round(current_atr, 2),
            "rvol": round(rvol, 2),
            "rsi": None,
            "vol_slope": round(vol_slope, 4) if vol_slope is not None else 0.0,
            "resistance_broken": round(max(broken_resistance), 2),
            "pullback_depth": round(pb_depth, 2),
            "liquidity_sweep": bullish_sweep,
            "mss": bullish_mss
        }

    elif bias == "SHORT":
        swings = detect_swing_points(recent_candles, left=2, right=2)
        support_levels = [s["value"] for s in swings if s["type"] == "SL"][-3:]

        if not support_levels:
            return None

        broken_support = [s for s in support_levels if current_close < s]
        if not broken_support:
            return None

        # Sweeps filter
        enable_sweeps = getattr(config, "ENABLE_LIQUIDITY_SWEEPS", False)
        sweep_mode = getattr(config, "LIQUIDITY_SWEEP_MODE", "both")
        if enable_sweeps == "filter" and (sweep_mode == "both" or sweep_mode == "A"):
            if not bearish_sweep:
                return None

        # MSS filter
        enable_mss = getattr(config, "ENABLE_MSS", False)
        mss_mode = getattr(config, "MSS_MODE", "both")
        if enable_mss in ["filter", "trend_continuation"] and (mss_mode == "both" or mss_mode == "A"):
            if not bearish_mss:
                return None

        _, pb_depth, _, _, _ = detect_impulse_and_pullback(h1_candles, current_atr, current_close, "SHORT")

        return {
            "signal": "SHORT_A",
            "mode": "A",
            "type": "BREAKOUT",
            "pair": symbol,
            "price": round(current_close, 2),
            "atr": round(current_atr, 2),
            "rvol": round(rvol, 2),
            "rsi": None,
            "vol_slope": round(vol_slope, 4) if vol_slope is not None else 0.0,
            "support_broken": round(min(broken_support), 2),
            "pullback_depth": round(pb_depth, 2),
            "liquidity_sweep": bearish_sweep,
            "mss": bearish_mss
        }

    return None


# ──────────────────────────────────────────────────────────────
# Mode B — Pullback
# ──────────────────────────────────────────────────────────────

def _check_mode_b_legacy(h1_candles, current_close, current_ema50, current_rsi,
                   rvol, bias, symbol, current_atr, on_reject_cb=None):
    """
    Pullback entry checks:
      1. Price within 0.8% of EMA50 on 1H (relaxed from 0.3%)
      2. Bullish engulfing or hammer candle in last 3 candles (for LONG)
         Bearish engulfing or inverted hammer in last 3 candles (for SHORT)
      3. RSI(14) between 40–55 (LONG) or 45–60 (SHORT)
      4. RVOL > 1.0
    """

    # --- Check: price within 0.8% of EMA50 ---
    if current_ema50 == 0:
        return None
    distance_pct = abs(current_close - current_ema50) / current_ema50 * 100.0
    if distance_pct > 0.8:
        return None

    # --- Check: RVOL > 1.0 ---
    if rvol <= 1.0:
        if on_reject_cb:
            on_reject_cb("volume")
        return None

    # --- Direction-specific checks ---
    if bias == "LONG":
        # RSI between 40 and 55
        if not (40.0 <= current_rsi <= 55.0):
            return None

        # Bullish engulfing or hammer in the last 3 candles (current and previous 2)
        engulfing = False
        hammer = False

        if len(h1_candles) >= 2 and is_bullish_engulfing(h1_candles):
            engulfing = True
        elif len(h1_candles) >= 3 and is_bullish_engulfing(h1_candles[:-1]):
            engulfing = True
        elif len(h1_candles) >= 4 and is_bullish_engulfing(h1_candles[:-2]):
            engulfing = True

        if len(h1_candles) >= 1 and is_hammer(h1_candles[-1]):
            hammer = True
        elif len(h1_candles) >= 2 and is_hammer(h1_candles[-2]):
            hammer = True
        elif len(h1_candles) >= 3 and is_hammer(h1_candles[-3]):
            hammer = True

        if not (engulfing or hammer):
            return None

        pattern = "ENGULFING" if engulfing else "HAMMER"

        return {
            "signal": "LONG_B",
            "mode": "B",
            "type": "PULLBACK",
            "pair": symbol,
            "price": round(current_close, 2),
            "atr": round(current_atr, 2),
            "rvol": round(rvol, 2),
            "rsi": round(current_rsi, 2),
            "ema50": round(current_ema50, 2),
            "distance_pct": round(distance_pct, 4),
            "pattern": pattern,
        }

    elif bias == "SHORT":
        # RSI between 45 and 60 (inverse pullback zone)
        if not (45.0 <= current_rsi <= 60.0):
            return None

        # Helper for bearish engulfing at a specific index relative to the end (e.g. idx=-1, idx=-2, idx=-3)
        def check_bearish_engulfing_at(candles, idx):
            if len(candles) < abs(idx - 1):
                return False
            curr = candles[idx]
            prev = candles[idx - 1]
            return curr[4] < prev[1] and curr[1] > prev[4]

        def check_shooting_star_at(candles, idx):
            if len(candles) < abs(idx):
                return False
            curr = candles[idx]
            o, h, l, c = curr[1], curr[2], curr[3], curr[4]
            body = abs(c - o)
            candle_range = h - l
            if candle_range <= 0:
                return False
            upper_wick = h - max(o, c)
            close_pct = (c - l) / candle_range
            return upper_wick >= 2.0 * body and close_pct <= 0.30

        bearish_engulfing = False
        shooting_star = False

        # Check last 3 candles (-1, -2, -3)
        for idx in [-1, -2, -3]:
            if check_bearish_engulfing_at(h1_candles, idx):
                bearish_engulfing = True
            if check_shooting_star_at(h1_candles, idx):
                shooting_star = True

        if not (bearish_engulfing or shooting_star):
            return None

        pattern = "BEARISH_ENGULFING" if bearish_engulfing else "SHOOTING_STAR"

        return {
            "signal": "SHORT_B",
            "mode": "B",
            "type": "PULLBACK",
            "pair": symbol,
            "price": round(current_close, 2),
            "atr": round(current_atr, 2),
            "rvol": round(rvol, 2),
            "rsi": round(current_rsi, 2),
            "ema50": round(current_ema50, 2),
            "distance_pct": round(distance_pct, 4),
            "pattern": pattern,
        }

    return None


# ──────────────────────────────────────────────────────────────
# Mode R — Ranging (Mean Reversion)
# ──────────────────────────────────────────────────────────────

def compute_bollinger_bands(closes, period=20, num_std=2):
    """
    Computes Bollinger Bands (Middle, Upper, Lower) from a list of closes.
    Returns (middle, upper, lower) for the latest bar, or (None, None, None).
    """
    if len(closes) < period:
        return None, None, None
    
    recent_closes = closes[-period:]
    middle = sum(recent_closes) / period
    
    # Population standard deviation
    variance = sum((x - middle) ** 2 for x in recent_closes) / period
    std = variance ** 0.5
    
    upper = middle + num_std * std
    lower = middle - num_std * std
    return middle, upper, lower


def range_scan_entry(buffers, symbol, alignment, on_reject_cb=None):
    """
    Ranging mean-reversion scanner:
    - MIDDLE, UPPER, LOWER Bollinger Bands (20-period SMA, 2 std)
    - RVOL > 1.0
    - Check direction alignment (prevent trading against 4H bias if bias is LONG or SHORT)
    """
    if not ENABLE_MODE_R:
        return None
        
    bias = alignment.get("bias", "NEUTRAL")
    
    h1_candles = buffers[symbol]["1H"].get_candles()
    if len(h1_candles) < 50:
        return None
        
    h1_closes = [c[4] for c in h1_candles]
    h1_volumes = [c[5] for c in h1_candles]
    current_close = h1_closes[-1]
    
    # 1. Bollinger Bands
    middle, upper, lower = compute_bollinger_bands(h1_closes, period=20, num_std=2)
    if middle is None:
        return None
        
    # 2. RSI(14)
    rsi_values = compute_rsi(h1_closes, period=14)
    if not rsi_values:
        return None
    current_rsi = rsi_values[-1]
    
    # 3. RVOL > 1.0
    rvol = compute_rvol(h1_volumes, lookback=20)
    if rvol is None or rvol <= 1.0:
        if on_reject_cb:
            on_reject_cb("volume")
        return None
        
    # ATR for stop/target calculations
    atr_values = compute_atr(h1_candles, period=14)
    if not atr_values:
        return None
    current_atr = atr_values[-1]
    
    # LONG check
    # Price near lower band (within 1%)
    is_near_lower = (abs(current_close - lower) / lower) <= 0.01
    is_rsi_oversold = current_rsi < 40
    
    # Bullish candle pattern
    engulfing = False
    hammer = False
    if len(h1_candles) >= 2 and is_bullish_engulfing(h1_candles):
        engulfing = True
    elif len(h1_candles) >= 3 and is_bullish_engulfing(h1_candles[:-1]):
        engulfing = True
    elif len(h1_candles) >= 4 and is_bullish_engulfing(h1_candles[:-2]):
        engulfing = True

    if len(h1_candles) >= 1 and is_hammer(h1_candles[-1]):
        hammer = True
    elif len(h1_candles) >= 2 and is_hammer(h1_candles[-2]):
        hammer = True
    elif len(h1_candles) >= 3 and is_hammer(h1_candles[-3]):
        hammer = True
        
    bullish_pattern = engulfing or hammer
    
    # Verify alignment (if 4H bias is SHORT, we cannot go LONG)
    if bias != "SHORT" and is_near_lower and is_rsi_oversold and bullish_pattern:
        return {
            "signal": "LONG_R",
            "mode": "R",
            "type": "MEAN_REVERSION",
            "pair": symbol,
            "price": round(current_close, 2),
            "atr": round(current_atr, 2),
            "rvol": round(rvol, 2),
            "rsi": round(current_rsi, 2),
            "lower_band": round(lower, 2),
            "upper_band": round(upper, 2),
            "pattern": "ENGULFING" if engulfing else "HAMMER"
        }
        
    # SHORT check
    # Price near upper band (within 1%)
    is_near_upper = (abs(current_close - upper) / upper) <= 0.01
    is_rsi_overbought = current_rsi > 60
    
    # Bearish engulfing check
    def check_bearish_engulfing_at(candles, idx):
        if len(candles) < abs(idx - 1):
            return False
        curr = candles[idx]
        prev = candles[idx - 1]
        return curr[4] < prev[1] and curr[1] > prev[4]
        
    bearish_engulfing = False
    for idx in [-1, -2, -3]:
        if check_bearish_engulfing_at(h1_candles, idx):
            bearish_engulfing = True
            break
            
    # Verify alignment (if 4H bias is LONG, we cannot go SHORT)
    if bias != "LONG" and is_near_upper and is_rsi_overbought and bearish_engulfing:
        return {
            "signal": "SHORT_R",
            "mode": "R",
            "type": "MEAN_REVERSION",
            "pair": symbol,
            "price": round(current_close, 2),
            "atr": round(current_atr, 2),
            "rvol": round(rvol, 2),
            "rsi": round(current_rsi, 2),
            "lower_band": round(lower, 2),
            "upper_band": round(upper, 2),
            "pattern": "BEARISH_ENGULFING"
        }
        
    return None


# ──────────────────────────────────────────────────────────────
# Mode B v2 — helper functions
# ──────────────────────────────────────────────────────────────

def is_strong_bullish_close(candle):
    """
    Returns True if the candle has a strong bullish close:
    - Close is in the upper 30% of the candle's total range
    - Body is >= 50% of the total range
    - Candle is bullish (close > open)
    """
    o, h, l, c = candle[1], candle[2], candle[3], candle[4]
    candle_range = h - l
    if candle_range <= 0:
        return False
    body = abs(c - o)
    close_pct = (c - l) / candle_range
    body_pct = body / candle_range
    return close_pct >= 0.70 and body_pct >= 0.50 and c > o


def is_strong_bearish_close(candle):
    """
    Returns True if the candle has a strong bearish close:
    - Close is in the lower 30% of the candle's total range
    - Body is >= 50% of the total range
    - Candle is bearish (close < open)
    """
    o, h, l, c = candle[1], candle[2], candle[3], candle[4]
    candle_range = h - l
    if candle_range <= 0:
        return False
    body = abs(c - o)
    close_pct = (c - l) / candle_range
    body_pct = body / candle_range
    return close_pct <= 0.30 and body_pct >= 0.50 and c < o


def is_break_of_pullback_high(h1_candles, lookback=5):
    """
    Break-of-pullback-high trigger for LONG entries.
    Finds the highest high among the prior `lookback` candles (excluding current).
    Returns True if the current candle's close exceeds that high.
    This signals the pullback is ending and the prior trend is resuming.
    """
    if len(h1_candles) < lookback + 1:
        return False
    prior_candles = h1_candles[-(lookback + 1):-1]
    pullback_high = max(c[2] for c in prior_candles)
    return h1_candles[-1][4] > pullback_high


def is_break_of_pullback_low(h1_candles, lookback=5):
    """
    Break-of-pullback-low trigger for SHORT entries.
    Finds the lowest low among the prior `lookback` candles (excluding current).
    Returns True if the current candle's close goes below that low.
    """
    if len(h1_candles) < lookback + 1:
        return False
    prior_candles = h1_candles[-(lookback + 1):-1]
    pullback_low = min(c[3] for c in prior_candles)
    return h1_candles[-1][4] < pullback_low


def _check_bearish_engulfing_at(candles, idx):
    """Module-level helper: bearish engulfing check at index idx."""
    if len(candles) < abs(idx - 1):
        return False
    curr = candles[idx]
    prev = candles[idx - 1]
    return curr[4] < prev[1] and curr[1] > prev[4]


def _check_shooting_star_at(candles, idx):
    """Module-level helper: shooting star check at index idx."""
    if len(candles) < abs(idx):
        return False
    curr = candles[idx]
    o, h, l, c = curr[1], curr[2], curr[3], curr[4]
    body = abs(c - o)
    candle_range = h - l
    if candle_range <= 0:
        return False
    upper_wick = h - max(o, c)
    close_pct = (c - l) / candle_range
    return upper_wick >= 2.0 * body and close_pct <= 0.30


# ──────────────────────────────────────────────────────────────
# Mode B v2 — Crypto-native Pullback
# ──────────────────────────────────────────────────────────────

def _check_mode_b_v2(h1_candles, h4_candles, current_close, current_ema50,
                     rvol, bias, symbol, current_atr, atr_values, h1_volumes,
                     on_reject_cb=None):
    """
    Mode B v2 — Crypto-native pullback entry.

    LONG entry (ALL required):
    1. 4H trend bullish: h4 EMA50 > EMA200  OR  4H market structure BULLISH (HH+HL)
    2. 1H price near EMA20 or EMA50 (within 2.0 x ATR)
    3. ATR not collapsing: current ATR >= 0.70 x avg of last 5 ATRs
    4. Volume contraction: 3-bar avg volume < 20-bar avg volume (real pullback)
    5. Entry trigger (ANY ONE):
       - Bullish Engulfing (last 3 candles)
       - Hammer (last 3 candles)
       - Strong Bullish Close (close >= upper 30%, body >= 50% of range)
       - Break of pullback high (close > highest high of prior 5 candles)

    SHORT: mirror logic.
    """

    # --- Check 1: 4H Trend (EMA OR market structure) ---
    h4_closes = [c[4] for c in h4_candles]
    h4_ema_trend = False
    h4_structure = "MIXED"

    if len(h4_closes) >= 200:
        h4_ema50_vals = compute_ema(h4_closes, 50)
        h4_ema200_vals = compute_ema(h4_closes, 200)
        if h4_ema50_vals and h4_ema200_vals:
            if bias == "LONG" and h4_ema50_vals[-1] > h4_ema200_vals[-1]:
                h4_ema_trend = True
            elif bias == "SHORT" and h4_ema50_vals[-1] < h4_ema200_vals[-1]:
                h4_ema_trend = True

    if len(h4_candles) >= 10:
        swings_4h = detect_swing_points(h4_candles, left=2, right=2)
        h4_structure = classify_market_structure(swings_4h, count=5)

    if bias == "LONG":
        trend_ok = h4_ema_trend or (h4_structure == "BULLISH")
    else:
        trend_ok = h4_ema_trend or (h4_structure == "BEARISH")

    if not trend_ok:
        if on_reject_cb:
            on_reject_cb("h4_trend")
        return None

    # --- Check 2: 1H price near EMA20 or EMA50 ---
    h1_closes = [c[4] for c in h1_candles]
    ema20_vals = compute_ema(h1_closes, 20)
    if not ema20_vals:
        return None
    current_ema20 = ema20_vals[-1]

    near_ema20 = abs(current_close - current_ema20) <= 2.0 * current_atr
    near_ema50 = abs(current_close - current_ema50) <= 2.0 * current_atr

    if not (near_ema20 or near_ema50):
        if on_reject_cb:
            on_reject_cb("not_near_ema")
        return None

    # --- Check 3: ATR not collapsing ---
    if len(atr_values) < 6:
        return None
    avg_atr_5 = sum(atr_values[-6:-1]) / 5
    atr_not_collapsing = (avg_atr_5 > 0) and (current_atr >= 0.70 * avg_atr_5)
    if not atr_not_collapsing:
        if on_reject_cb:
            on_reject_cb("atr_collapsing")
        return None

    # --- Check 4: Volume contraction (3-bar avg < 20-bar avg) ---
    if len(h1_volumes) < 23:
        return None
    avg_vol_3 = sum(h1_volumes[-3:]) / 3
    avg_vol_20 = sum(h1_volumes[-23:-3]) / 20
    volume_contracting = (avg_vol_20 > 0) and (avg_vol_3 < avg_vol_20)
    if not volume_contracting:
        if on_reject_cb:
            on_reject_cb("volume_not_contracting")
        return None

    # RSI computed for logging only (not a hard gate in v2)
    rsi_values = compute_rsi(h1_closes, period=14)
    current_rsi = rsi_values[-1] if rsi_values else 50.0

    # --- Check 5: Entry trigger ---
    trigger = None

    if bias == "LONG":
        # Trigger A: Bullish Engulfing (last 3 candles)
        for offset in [0, 1, 2]:
            slice_end = len(h1_candles) - offset
            if slice_end >= 2 and is_bullish_engulfing(h1_candles[:slice_end]):
                trigger = "ENGULFING"
                break

        # Trigger B: Hammer (last 3 candles)
        if trigger is None:
            for idx in [-1, -2, -3]:
                if len(h1_candles) >= abs(idx) and is_hammer(h1_candles[idx]):
                    trigger = "HAMMER"
                    break

        # Trigger C: Strong Bullish Close
        if trigger is None and is_strong_bullish_close(h1_candles[-1]):
            trigger = "STRONG_CLOSE"

        # Trigger D: Break of pullback high
        if trigger is None and is_break_of_pullback_high(h1_candles, lookback=5):
            trigger = "PULLBACK_HIGH_BREAK"

        if trigger is None:
            return None

        # Sweeps & MSS checks
        bullish_sweep, bearish_sweep = check_liquidity_sweep(h1_candles)
        bullish_mss, bearish_mss = check_mss(h1_candles)

        enable_sweeps = getattr(config, "ENABLE_LIQUIDITY_SWEEPS", False)
        sweep_mode = getattr(config, "LIQUIDITY_SWEEP_MODE", "both")
        if enable_sweeps == "filter" and (sweep_mode == "both" or sweep_mode == "B"):
            if not bullish_sweep:
                return None

        enable_mss = getattr(config, "ENABLE_MSS", False)
        mss_mode = getattr(config, "MSS_MODE", "both")
        if enable_mss in ["filter", "trend_continuation"] and (mss_mode == "both" or mss_mode == "B"):
            if not bullish_mss:
                return None

        # Pullback depth
        _, pb_depth, _, _, _ = detect_impulse_and_pullback(h1_candles, current_atr, current_close, "LONG")

        return {
            "signal": "LONG_B",
            "mode": "B",
            "type": "PULLBACK",
            "pair": symbol,
            "price": round(current_close, 2),
            "atr": round(current_atr, 2),
            "rvol": round(rvol, 2),
            "rsi": round(current_rsi, 2),
            "ema20": round(current_ema20, 2),
            "ema50": round(current_ema50, 2),
            "near_ema": "EMA20" if near_ema20 else "EMA50",
            "h4_ema_trend": h4_ema_trend,
            "h4_structure": h4_structure,
            "volume_contracting": volume_contracting,
            "atr_not_collapsing": atr_not_collapsing,
            "trigger": trigger,
            "pattern": trigger,   # scorer compatibility
            "pullback_depth": round(pb_depth, 2),
            "liquidity_sweep": bullish_sweep,
            "mss": bullish_mss
        }

    elif bias == "SHORT":
        # Trigger A: Bearish Engulfing (last 3 candles)
        for idx in [-1, -2, -3]:
            if _check_bearish_engulfing_at(h1_candles, idx):
                trigger = "BEARISH_ENGULFING"
                break

        # Trigger B: Shooting Star (last 3 candles)
        if trigger is None:
            for idx in [-1, -2, -3]:
                if _check_shooting_star_at(h1_candles, idx):
                    trigger = "SHOOTING_STAR"
                    break

        # Trigger C: Strong Bearish Close
        if trigger is None and is_strong_bearish_close(h1_candles[-1]):
            trigger = "STRONG_BEARISH_CLOSE"

        # Trigger D: Break of pullback low
        if trigger is None and is_break_of_pullback_low(h1_candles, lookback=5):
            trigger = "PULLBACK_LOW_BREAK"

        if trigger is None:
            return None

        # Sweeps & MSS checks
        bullish_sweep, bearish_sweep = check_liquidity_sweep(h1_candles)
        bullish_mss, bearish_mss = check_mss(h1_candles)

        enable_sweeps = getattr(config, "ENABLE_LIQUIDITY_SWEEPS", False)
        sweep_mode = getattr(config, "LIQUIDITY_SWEEP_MODE", "both")
        if enable_sweeps == "filter" and (sweep_mode == "both" or sweep_mode == "B"):
            if not bearish_sweep:
                return None

        enable_mss = getattr(config, "ENABLE_MSS", False)
        mss_mode = getattr(config, "MSS_MODE", "both")
        if enable_mss in ["filter", "trend_continuation"] and (mss_mode == "both" or mss_mode == "B"):
            if not bearish_mss:
                return None

        # Pullback depth
        _, pb_depth, _, _, _ = detect_impulse_and_pullback(h1_candles, current_atr, current_close, "SHORT")

        return {
            "signal": "SHORT_B",
            "mode": "B",
            "type": "PULLBACK",
            "pair": symbol,
            "price": round(current_close, 2),
            "atr": round(current_atr, 2),
            "rvol": round(rvol, 2),
            "rsi": round(current_rsi, 2),
            "ema20": round(current_ema20, 2),
            "ema50": round(current_ema50, 2),
            "near_ema": "EMA20" if near_ema20 else "EMA50",
            "h4_ema_trend": h4_ema_trend,
            "h4_structure": h4_structure,
            "volume_contracting": volume_contracting,
            "atr_not_collapsing": atr_not_collapsing,
            "trigger": trigger,
            "pattern": trigger,  # scorer compatibility
            "pullback_depth": round(pb_depth, 2),
            "liquidity_sweep": bearish_sweep,
            "mss": bearish_mss
        }

    return None
