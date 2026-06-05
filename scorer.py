# scorer.py
"""
Signal Scoring System
======================
Takes a detected signal dict from signals.scan_entry(), plus the
regime and alignment dicts, and returns a quality score between 0.0 and 1.0.

Scoring weights (sum to 1.0):
  - regime == "TRENDING"              +0.25
  - All 3 timeframes aligned          +0.20
  - RVOL > 1.5                        +0.20
  - ATR expanding                     +0.15
  - Volume trend slope > 0            +0.10
  - Candlestick pattern confirms      +0.10

Thresholds:
  - score >= 0.85  -> "strong" entry
  - score >= 0.70  -> "normal" entry
  - score <  0.70  -> no entry allowed

No new calculations — the scorer reads values already present
in the signal, regime, and alignment dicts.
"""


import config

# ──────────────────────────────────────────────────────────────
# Weight definitions
# ──────────────────────────────────────────────────────────────

WEIGHTS = {
    "regime_trending":    0.25,
    "tf_aligned":         0.20,
    "rvol_strong":        0.20,
    "atr_expanding":      0.15,
    "vol_slope_positive": 0.10,
    "pattern_confirms":   0.10,
}

# Thresholds
THRESHOLD_STRONG = 0.85
THRESHOLD_NORMAL = 0.70


# ──────────────────────────────────────────────────────────────
# Main scoring function
# ──────────────────────────────────────────────────────────────

def score_signal(signal, regime_result, alignment):
    """
    Scores a detected entry signal.

    Args:
        signal:        dict — output from signals.scan_entry().
                       Must not be None (caller should check first).
                       Keys used: "rvol", "vol_slope", "pattern",
                                  "mode", "type"

        regime_result: dict — output from regime.classify_regime().
                       Keys used: "regime"

        alignment:     dict — output from mtf.check_trend_alignment().
                       Keys used: "aligned"

    Returns:
        dict:
            "score":    float  — 0.0 to 1.0
            "entry":    bool   — True if score >= THRESHOLD_NORMAL
            "strength": str    — "strong", "normal", or "none"
            "breakdown": dict  — individual component scores for debugging
    """

    # ── For Ranging Mode signals, we score based on mean-reversion quality ──
    if signal.get("mode") == "R":
        breakdown = {}
        score = 0.0
        
        # 1. 4H alignment: +0.20 if alignment aligned or bias is NEUTRAL (no opposing trend)
        if alignment and (alignment.get("aligned", False) or alignment.get("bias") == "NEUTRAL"):
            score += 0.20
            breakdown["tf_aligned"] = 0.20
        else:
            breakdown["tf_aligned"] = 0.0
            
        # 2. RVOL: +0.20 if rvol > 1.5, else +0.10 if rvol > 1.0
        rvol = signal.get("rvol", 0.0)
        if rvol > 1.5:
            score += 0.20
            breakdown["rvol_strong"] = 0.20
        elif rvol > 1.0:
            score += 0.10
            breakdown["rvol_strong"] = 0.10
        else:
            breakdown["rvol_strong"] = 0.0
            
        # 3. Pattern confirms: +0.20 if engulfing or hammer is present
        pattern = signal.get("pattern")
        if pattern is not None:
            score += 0.20
            breakdown["pattern_confirms"] = 0.20
        else:
            breakdown["pattern_confirms"] = 0.0
            
        # 4. RSI extreme: +0.20 if RSI is extreme (RSI < 30 or RSI > 70), else +0.10
        rsi = signal.get("rsi")
        if rsi is not None:
            if rsi < 30 or rsi > 70:
                score += 0.20
                breakdown["rsi_extreme"] = 0.20
            else:
                score += 0.10
                breakdown["rsi_extreme"] = 0.10
        else:
            breakdown["rsi_extreme"] = 0.0
            
        # 5. Bollinger Band proximity: +0.30 if distance is very close
        price = signal.get("price", 0.0)
        lower_band = signal.get("lower_band", 0.0)
        upper_band = signal.get("upper_band", 0.0)
        dist_lower = abs(price - lower_band) / lower_band if lower_band else 999.0
        dist_upper = abs(price - upper_band) / upper_band if upper_band else 999.0
        min_dist = min(dist_lower, dist_upper)
        if min_dist <= 0.005:
            score += 0.30
            breakdown["bb_proximity"] = 0.30
        else:
            score += 0.15
            breakdown["bb_proximity"] = 0.15
            
        score = round(score, 4)
        if score >= THRESHOLD_STRONG:
            strength = "strong"
            entry = True
        elif score >= THRESHOLD_NORMAL:
            strength = "normal"
            entry = True
        else:
            strength = "none"
            entry = False
            
        return {
            "score": score,
            "entry": entry,
            "strength": strength,
            "breakdown": breakdown,
        }

    # ── For Mode B v2 signals (crypto-native pullback) ────────
    # Detected by presence of 'volume_contracting' key set by _check_mode_b_v2.
    # Scoring weights:
    #   regime_trending    +0.25
    #   tf_aligned         +0.20
    #   atr_not_collapsing +0.15  (replaces generic atr_expanding for pullbacks)
    #   volume_contracting +0.15  (replaces rvol_strong — pullbacks need LOW volume)
    #   pattern_confirms   +0.15  (trigger candle: engulfing/hammer/strong-close/pb-break)
    #   structure_bonus    +0.10  (4H HH+HL or LH+LL structure confirms bias)
    #   Total max:          1.00
    if signal.get("mode") == "B" and "volume_contracting" in signal:
        breakdown = {}
        score = 0.0

        # 1. Regime == TRENDING: +0.25
        if regime_result and regime_result.get("regime") == "TRENDING":
            score += 0.25
            breakdown["regime_trending"] = 0.25
        else:
            breakdown["regime_trending"] = 0.0

        # 2. TF alignment: +0.20
        if alignment and alignment.get("aligned", False):
            score += 0.20
            breakdown["tf_aligned"] = 0.20
        else:
            breakdown["tf_aligned"] = 0.0

        # 3. ATR not collapsing: +0.15
        if signal.get("atr_not_collapsing", False):
            score += 0.15
            breakdown["atr_not_collapsing"] = 0.15
        else:
            breakdown["atr_not_collapsing"] = 0.0

        # 4. Volume contracting (quality pullback): +0.15
        if signal.get("volume_contracting", False):
            score += 0.15
            breakdown["volume_contracting"] = 0.15
        else:
            breakdown["volume_contracting"] = 0.0

        # 5. Entry trigger / pattern: +0.15
        trigger = signal.get("trigger") or signal.get("pattern")
        if trigger is not None:
            score += 0.15
            breakdown["pattern_confirms"] = 0.15
        else:
            breakdown["pattern_confirms"] = 0.0

        # 6. 4H structure confirms bias: +0.10 bonus
        h4_structure = signal.get("h4_structure", "MIXED")
        sig_name = signal.get("signal", "")
        if (h4_structure == "BULLISH" and "LONG" in sig_name) or \
           (h4_structure == "BEARISH" and "SHORT" in sig_name):
            score += 0.10
            breakdown["structure_bonus"] = 0.10
        # ── Institutional Concept Bonuses (Experiment A, B, C, D) ──
        # Experiment A: Liquidity Sweep
        if getattr(config, "ENABLE_LIQUIDITY_SWEEPS", False) == "bonus":
            sweep_mode = getattr(config, "LIQUIDITY_SWEEP_MODE", "both")
            if sweep_mode == "both" or sweep_mode == "B":
                if signal.get("liquidity_sweep", False):
                    bonus_val = getattr(config, "LIQUIDITY_SWEEP_BONUS", 0.10)
                    score += bonus_val
                    breakdown["liquidity_sweep_bonus"] = bonus_val

        # Experiment B: MSS / CHOCH
        if getattr(config, "ENABLE_MSS", False) == "bonus":
            if signal.get("mss", False):
                bonus_val = getattr(config, "MSS_BONUS", 0.10)
                score += bonus_val
                breakdown["mss_bonus"] = bonus_val

        # Experiment C: Pullback Depth
        if getattr(config, "ENABLE_PULLBACK_DEPTH_BONUS", False):
            pb_depth = signal.get("pullback_depth")
            if pb_depth is not None and 38.2 <= pb_depth <= 61.8:
                bonus_val = getattr(config, "PULLBACK_DEPTH_BONUS_VAL", 0.10)
                score += bonus_val
                breakdown["pullback_depth_bonus"] = bonus_val

        # Experiment D: Regime Transition
        if getattr(config, "ENABLE_REGIME_TRANSITION_BONUS", False):
            recent_transition = signal.get("recent_transition", "NO_TRANSITION")
            if recent_transition == "VOLATILE -> TRENDING":
                bonus_val = getattr(config, "REGIME_TRANSITION_BONUS_VAL", 0.10)
                score += bonus_val
                breakdown["regime_transition_bonus"] = bonus_val

        score = min(round(score, 4), 1.0)

        if score >= THRESHOLD_STRONG:
            strength = "strong"
            entry = True
        elif score >= THRESHOLD_NORMAL:
            strength = "normal"
            entry = True
        else:
            strength = "none"
            entry = False

        return {
            "score": score,
            "entry": entry,
            "strength": strength,
            "breakdown": breakdown,
        }

    breakdown = {}
    score = 0.0


    # ── 1. Regime == TRENDING (+0.25) ──────────────────────────
    # By the time a signal reaches the scorer, regime should be TRENDING
    # (because scan_entry gates on it). But we score it explicitly for
    # robustness and clarity.
    if regime_result and regime_result.get("regime") == "TRENDING":
        score += WEIGHTS["regime_trending"]
        breakdown["regime_trending"] = WEIGHTS["regime_trending"]
    else:
        breakdown["regime_trending"] = 0.0

    # ── 2. All 3 TFs aligned (+0.20) ──────────────────────────
    if alignment and alignment.get("aligned", False):
        score += WEIGHTS["tf_aligned"]
        breakdown["tf_aligned"] = WEIGHTS["tf_aligned"]
    else:
        breakdown["tf_aligned"] = 0.0

    # ── 3. RVOL > 1.5 (+0.20) ────────────────────────────────
    # Signal dict always has "rvol". Mode A requires > 1.5 already,
    # Mode B requires > 1.0. We award the full weight only if > 1.5.
    rvol = signal.get("rvol", 0.0)
    if rvol > 1.5:
        score += WEIGHTS["rvol_strong"]
        breakdown["rvol_strong"] = WEIGHTS["rvol_strong"]
    else:
        breakdown["rvol_strong"] = 0.0

    # ── 4. ATR expanding (+0.15) ─────────────────────────────
    # Mode A signals only exist when ATR is expanding (it's a hard gate
    # in _check_mode_a). For Mode B, ATR expansion is not checked.
    # We infer ATR expansion from the signal mode:
    #   - Mode A: ATR was confirmed expanding -> full weight
    #   - Mode B: we don't know -> no weight (conservative)
    mode = signal.get("mode", "")
    if mode == "A":
        # Mode A already verified ATR expansion as a hard requirement
        score += WEIGHTS["atr_expanding"]
        breakdown["atr_expanding"] = WEIGHTS["atr_expanding"]
    else:
        breakdown["atr_expanding"] = 0.0

    # ── 5. Volume trend slope > 0 (+0.10) ────────────────────
    vol_slope = signal.get("vol_slope")
    if vol_slope is not None and vol_slope > 0:
        score += WEIGHTS["vol_slope_positive"]
        breakdown["vol_slope_positive"] = WEIGHTS["vol_slope_positive"]
    else:
        breakdown["vol_slope_positive"] = 0.0

    # ── 6. Candlestick pattern confirms (+0.10) ──────────────
    # Mode B signals contain a "pattern" key (ENGULFING, HAMMER,
    # BEARISH_ENGULFING, SHOOTING_STAR). Mode A doesn't use patterns.
    # We award this weight if any pattern is present.
    pattern = signal.get("pattern")
    if pattern is not None:
        score += WEIGHTS["pattern_confirms"]
        breakdown["pattern_confirms"] = WEIGHTS["pattern_confirms"]
    else:
        breakdown["pattern_confirms"] = 0.0

    # ── Optional Bonuses for Mode A Breakouts ──
    if signal.get("mode") == "A":
        # 1. Regime Transition Bonus: +0.10 for VOLATILE -> TRENDING
        if signal.get("regime_transition_bonus", False):
            recent_transition = signal.get("recent_transition", "NO_TRANSITION")
            if recent_transition == "VOLATILE -> TRENDING":
                score += 0.10
                breakdown["regime_transition_bonus"] = 0.10
            else:
                breakdown["regime_transition_bonus"] = 0.0

        # 2. Moderate Pullback Bonus: +0.10 for 38.2% - 61.8% pullback depth
        if signal.get("moderate_pullback_bonus", False):
            pullback_depth = signal.get("pullback_depth", 0.0)
            if 38.2 <= pullback_depth <= 61.8:
                score += 0.10
                breakdown["moderate_pullback_bonus"] = 0.10
            else:
                breakdown["moderate_pullback_bonus"] = 0.0

    # ── Institutional Concept Bonuses (Experiment A, B, C, D) ──
    # Experiment A: Liquidity Sweep
    if getattr(config, "ENABLE_LIQUIDITY_SWEEPS", False) == "bonus":
        sweep_mode = getattr(config, "LIQUIDITY_SWEEP_MODE", "both")
        if sweep_mode == "both" or sweep_mode == signal.get("mode"):
            if signal.get("liquidity_sweep", False):
                bonus_val = getattr(config, "LIQUIDITY_SWEEP_BONUS", 0.10)
                score += bonus_val
                breakdown["liquidity_sweep_bonus"] = bonus_val

    # Experiment B: MSS / CHOCH
    if getattr(config, "ENABLE_MSS", False) == "bonus":
        if signal.get("mss", False):
            bonus_val = getattr(config, "MSS_BONUS", 0.10)
            score += bonus_val
            breakdown["mss_bonus"] = bonus_val

    # Experiment C: Pullback Depth (if not already handled or overrides)
    if getattr(config, "ENABLE_PULLBACK_DEPTH_BONUS", False):
        # Apply to Mode B (since Mode A is already handled by moderate_pullback_bonus)
        if signal.get("mode") == "B":
            pb_depth = signal.get("pullback_depth")
            if pb_depth is not None and 38.2 <= pb_depth <= 61.8:
                bonus_val = getattr(config, "PULLBACK_DEPTH_BONUS_VAL", 0.10)
                score += bonus_val
                breakdown["pullback_depth_bonus"] = bonus_val
        elif signal.get("mode") == "A" and not signal.get("moderate_pullback_bonus", False):
            # Fallback if moderate_pullback_bonus wasn't set on signal
            pb_depth = signal.get("pullback_depth")
            if pb_depth is not None and 38.2 <= pb_depth <= 61.8:
                bonus_val = getattr(config, "PULLBACK_DEPTH_BONUS_VAL", 0.10)
                score += bonus_val
                breakdown["pullback_depth_bonus"] = bonus_val

    # Experiment D: Regime Transition
    if getattr(config, "ENABLE_REGIME_TRANSITION_BONUS", False):
        if signal.get("mode") == "B":
            recent_transition = signal.get("recent_transition", "NO_TRANSITION")
            if recent_transition == "VOLATILE -> TRENDING":
                bonus_val = getattr(config, "REGIME_TRANSITION_BONUS_VAL", 0.10)
                score += bonus_val
                breakdown["regime_transition_bonus"] = bonus_val

    # ── Determine entry eligibility and strength ─────────────
    score = min(round(score, 4), 1.0)

    if score >= THRESHOLD_STRONG:
        strength = "strong"
        entry = True
    elif score >= THRESHOLD_NORMAL:
        strength = "normal"
        entry = True
    else:
        strength = "none"
        entry = False

    return {
        "score": score,
        "entry": entry,
        "strength": strength,
        "breakdown": breakdown,
    }
