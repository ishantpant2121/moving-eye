# trade_manager.py
"""
Trade Management & Exit Engine
==============================
Manages open futures positions, transitions them through stages (OPEN, PARTIAL_1,
PARTIAL_2, CLOSED), and processes exits based on targets, stops, and regime flips.

Stages:
  OPEN       -> entered trade, initial hard stop active
  PARTIAL_1  -> 2R reached, 40% closed, stop moved to breakeven
  PARTIAL_2  -> 3R reached, another 20% closed (60% total out), trailing stop active
  CLOSED     -> trade fully exited
"""

import time
from mtf import detect_swing_points

def open_trade(signal, size_result, score=None):
    """
    Creates and initializes a trade state dictionary from an entry signal and sizing results.

    Args:
        signal:      dict — entry signal from signals.py (keys: "pair", "price", "signal")
        size_result: dict — sizer output from sizer.py (keys: "contracts", "stop_price", "stop_distance")
        score:       float (optional) — the quality score of the entry signal

    Returns:
        dict: The trade state dictionary.
    """
    if not isinstance(signal, dict):
        raise ValueError("Signal must be a dictionary.")
    if not isinstance(size_result, dict):
        raise ValueError("Size result must be a dictionary.")

    sig_name = signal.get("signal", "").upper()
    if "LONG" in sig_name:
        direction = "LONG"
    elif "SHORT" in sig_name:
        direction = "SHORT"
    else:
        raise ValueError(f"Unknown direction in signal name: '{sig_name}'")

    entry_time = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

    # Score fallback
    if score is None:
        score_val = size_result.get("score", signal.get("score", 0.0))
    else:
        score_val = score

    return {
        "pair": signal["pair"],
        "direction": direction,
        "entry_price": float(signal["price"]),
        "original_contracts": float(size_result["contracts"]),
        "remaining_contracts": float(size_result["contracts"]),
        "stop_price": float(size_result["stop_price"]),
        "stop_distance": float(size_result["stop_distance"]),
        "stage": "OPEN",
        "entry_time": entry_time,
        "score": float(score_val)
    }


def is_closed(trade):
    """
    Checks if the trade has been exited.
    """
    if not isinstance(trade, dict):
        return True
    return trade.get("stage") == "CLOSED"


def update_trailing_stop(trade, candle_buffer_4h):
    """
    Updates the trailing stop price for PARTIAL_2 trades based on the 4H candle buffer.
    For LONG, stop trails below the lowest 4H swing low (or lowest low) of the last 10 bars.
    For SHORT, stop trails above the highest 4H swing high (or highest high) of the last 10 bars.

    Only moves stop price in the trade's favor.

    Args:
        trade:             dict — trade state
        candle_buffer_4h:  OHLCVBuffer or list of candles

    Returns:
        dict or None: A STOP_UPDATE action if trailing stop moved, otherwise None.
    """
    if trade.get("stage") != "PARTIAL_2":
        return None

    # Retrieve candles from buffer
    if hasattr(candle_buffer_4h, "get_candles"):
        candles = candle_buffer_4h.get_candles()
    else:
        candles = list(candle_buffer_4h)

    if not candles:
        return None

    # Get the last 10 candles (or all available if less than 10)
    lookback_candles = candles[-10:]
    lookback_len = len(lookback_candles)

    # Detect swing points on the whole buffer to identify structure
    swings = detect_swing_points(candles, left=2, right=2)
    
    # Filter swings that fall within the last 10 bars of the candle buffer
    cutoff_index = len(candles) - lookback_len
    recent_swings = [s for s in swings if s["index"] >= cutoff_index]

    direction = trade["direction"]

    if direction == "LONG":
        # Filter for recent Swing Lows
        recent_sls = [s["value"] for s in recent_swings if s["type"] == "SL"]
        if recent_sls:
            new_stop = min(recent_sls)
        else:
            # Fallback to the absolute lowest low of the last 10 bars
            new_stop = min(c[3] for c in lookback_candles) # Index 3 is Low
        
        new_stop = round(new_stop, 2)
        # Trailing stop for LONG can only move UP
        if new_stop > trade["stop_price"]:
            trade["stop_price"] = new_stop
            return {
                "action": "STOP_UPDATE",
                "new_stop": new_stop,
                "reason": "TRAILING_STOP"
            }

    elif direction == "SHORT":
        # Filter for recent Swing Highs
        recent_shs = [s["value"] for s in recent_swings if s["type"] == "SH"]
        if recent_shs:
            new_stop = max(recent_shs)
        else:
            # Fallback to the absolute highest high of the last 10 bars
            new_stop = max(c[2] for c in lookback_candles) # Index 2 is High
            
        new_stop = round(new_stop, 2)
        # Trailing stop for SHORT can only move DOWN
        if new_stop < trade["stop_price"]:
            trade["stop_price"] = new_stop
            return {
                "action": "STOP_UPDATE",
                "new_stop": new_stop,
                "reason": "TRAILING_STOP"
            }

    return None


def update_trade(trade, current_price, current_regime, candle_buffer_4h):
    """
    Updates the trade state on every closed 1H candle. Evaluates exit rules in priority order.

    Exit Rules:
      1. HARD STOP: price hits stop_price -> Close 100%, stage=CLOSED
      2. REGIME FLIP: regime is RANGING or VOLATILE -> Close 100%, stage=CLOSED
      3. 2R TARGET (stage == OPEN):
           - Close 40% of original size
           - Move stop to breakeven (entry_price)
           - Stage -> PARTIAL_1
      4. 3R TARGET (stage == PARTIAL_1):
           - Close 20% more of original size (60% total out)
           - Stage -> PARTIAL_2

    Args:
        trade:            dict — trade state
        current_price:    float — current 1H candle close price
        current_regime:   str — current market regime (e.g. "TRENDING", "RANGING", "VOLATILE")
        candle_buffer_4h: OHLCVBuffer or list of candles — 4H candles for trailing stop calculation

    Returns:
        tuple: (updated_trade_dict, list_of_exit_actions)
    """
    exit_actions = []

    if trade["stage"] == "CLOSED":
        return trade, exit_actions

    # ── 1. HARD STOP / TRAILING STOP BREACH ──
    # Check if price has hit or breached the stop price
    is_stop_hit = False
    if trade["direction"] == "LONG" and current_price <= trade["stop_price"]:
        is_stop_hit = True
    elif trade["direction"] == "SHORT" and current_price >= trade["stop_price"]:
        is_stop_hit = True

    if is_stop_hit:
        reason = "TRAILING_STOP" if trade["stage"] == "PARTIAL_2" else "HARD_STOP"
        
        exit_price = current_price
        if reason == "HARD_STOP":
            entry_p = trade["entry_price"]
            stop_dist = trade["stop_distance"]
            if trade["direction"] == "LONG":
                actual_loss_r = (entry_p - current_price) / stop_dist
                if actual_loss_r > 1.5:
                    print(f"[GAP RISK] Capped loss from {actual_loss_r:.2f} R to 1.5R")
                    exit_price = entry_p - 1.5 * stop_dist
            else:  # SHORT
                actual_loss_r = (current_price - entry_p) / stop_dist
                if actual_loss_r > 1.5:
                    print(f"[GAP RISK] Capped loss from {actual_loss_r:.2f} R to 1.5R")
                    exit_price = entry_p + 1.5 * stop_dist

        exit_actions.append({
            "action": "FULL_CLOSE",
            "contracts": round(trade["remaining_contracts"], 4),
            "reason": reason,
            "price": exit_price
        })
        trade["remaining_contracts"] = 0.0
        trade["stage"] = "CLOSED"
        return trade, exit_actions

    # ── 2. REGIME FLIP ──
    # If the regime turns ranging or volatile, exit immediately
    if current_regime in ["RANGING", "VOLATILE"]:
        exit_actions.append({
            "action": "FULL_CLOSE",
            "contracts": round(trade["remaining_contracts"], 4),
            "reason": "REGIME_FLIP",
            "price": current_price
        })
        trade["remaining_contracts"] = 0.0
        trade["stage"] = "CLOSED"
        return trade, exit_actions

    # ── 3. 2R TARGET ──
    # Check if price reaches 2R from entry
    if trade["stage"] == "OPEN":
        is_2r_hit = False
        if trade["direction"] == "LONG":
            target_2r = trade["entry_price"] + 2.0 * trade["stop_distance"]
            if current_price >= target_2r:
                is_2r_hit = True
        else: # SHORT
            target_2r = trade["entry_price"] - 2.0 * trade["stop_distance"]
            if current_price <= target_2r:
                is_2r_hit = True

        if is_2r_hit:
            contracts_to_close = round(trade["original_contracts"] * 0.40, 4)
            contracts_to_close = min(contracts_to_close, trade["remaining_contracts"])
            
            trade["remaining_contracts"] = round(trade["remaining_contracts"] - contracts_to_close, 4)
            trade["stop_price"] = trade["entry_price"]
            trade["stage"] = "PARTIAL_1"

            exit_actions.append({
                "action": "PARTIAL_CLOSE",
                "contracts": contracts_to_close,
                "reason": "2R_TARGET",
                "price": current_price
            })
            exit_actions.append({
                "action": "STOP_UPDATE",
                "new_stop": trade["entry_price"],
                "reason": "BREAKEVEN"
            })

    # ── 4. 3R TARGET ──
    # Check if price reaches 3R from entry (allowing sequential transition in the same candle)
    if trade["stage"] == "PARTIAL_1":
        is_3r_hit = False
        if trade["direction"] == "LONG":
            target_3r = trade["entry_price"] + 3.0 * trade["stop_distance"]
            if current_price >= target_3r:
                is_3r_hit = True
        else: # SHORT
            target_3r = trade["entry_price"] - 3.0 * trade["stop_distance"]
            if current_price <= target_3r:
                is_3r_hit = True

        if is_3r_hit:
            contracts_to_close = round(trade["original_contracts"] * 0.20, 4)
            contracts_to_close = min(contracts_to_close, trade["remaining_contracts"])

            trade["remaining_contracts"] = round(trade["remaining_contracts"] - contracts_to_close, 4)
            trade["stage"] = "PARTIAL_2"

            exit_actions.append({
                "action": "PARTIAL_CLOSE",
                "contracts": contracts_to_close,
                "reason": "3R_TARGET",
                "price": current_price
            })

            # Since we just hit 3R (PARTIAL_2), we immediately calculate the trailing stop
            # so it is initialized based on the current 4H swing lows / highs.
            trail_action = update_trailing_stop(trade, candle_buffer_4h)
            if trail_action:
                exit_actions.append(trail_action)

    return trade, exit_actions
