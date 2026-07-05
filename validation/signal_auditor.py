# validation/signal_auditor.py
"""
Signal Audit Logger — 30-Day Paper Trading Validation
======================================================
Writes one row to logs/signal_audit.csv for every signal that passes
through the pipeline, whether accepted or rejected.

This module is called from paper_trader.py at two points:
  1. log_signal()         — after scan_entry() + score_signal() complete
  2. log_pre_rejection()  — for rejections that occur BEFORE a signal dict
                            exists (regime gate, MTF gate, circuit breaker,
                            open-trade block, max-positions block)

No strategy logic lives here. This module is read-only relative to the
trading engine — it only observes and records.

Output: logs/signal_audit.csv
"""

import os
import csv
import threading
from datetime import datetime, timezone, timedelta

# ── Constants ────────────────────────────────────────────────────────────────

SIGNAL_AUDIT_PATH = "logs/signal_audit.csv"

SIGNAL_AUDIT_HEADER = [
    # --- When ---
    "timestamp_utc",        # ISO-8601 UTC of the closed 1H candle
    "timestamp_ms",         # raw epoch ms (for exact candle identification)
    # --- What ---
    "symbol",
    "mode",                 # A, B, R, or "" for pre-signal rejections
    # --- Context ---
    "regime",
    "trend_alignment",      # LONG / SHORT / NEUTRAL
    "rvol",
    "atr",
    "adx",
    "mss",                  # True / False / "" (pre-signal)
    "pullback_depth",       # float or ""
    # --- Scoring ---
    "score",                # float or "" (pre-signal)
    "score_breakdown",      # JSON string of individual component scores, or ""
    # --- Decision ---
    "decision",             # ACCEPTED or REJECTED
    "reject_reason",        # score / mtf / regime / circuit_breaker /
                            # open_trade / max_positions / no_signal / ""
    # --- Entry details (filled only when ACCEPTED) ---
    "entry_price",
    "stop_price",
    "target_2r",
    "target_3r",
    "position_size",        # contracts
    "risk_pct",             # risk_inr / balance * 100
]

_lock = threading.Lock()
_header_written = False


# ── Internal helpers ─────────────────────────────────────────────────────────

def _ensure_csv():
    """Create logs/signal_audit.csv with header if it does not exist."""
    global _header_written
    os.makedirs("logs", exist_ok=True)
    if not os.path.exists(SIGNAL_AUDIT_PATH):
        with open(SIGNAL_AUDIT_PATH, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(SIGNAL_AUDIT_HEADER)
        _header_written = True
    else:
        _header_written = True


def _ms_to_iso(ts_ms):
    """Convert epoch milliseconds to ISO-8601 UTC string."""
    if ts_ms is None:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _append_row(row: dict):
    """Thread-safe append of one row to the CSV."""
    if not _header_written:
        _ensure_csv()
    with _lock:
        with open(SIGNAL_AUDIT_PATH, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow([row.get(col, "") for col in SIGNAL_AUDIT_HEADER])


# ── Public API ───────────────────────────────────────────────────────────────

def initialise():
    """
    Called once at PaperTrader startup to ensure the CSV exists with headers.
    Safe to call multiple times.
    """
    _ensure_csv()


def log_signal(
    timestamp_ms,
    symbol: str,
    signal: dict,
    score_result: dict,
    alignment: dict,
    regime: str,
    adx: float,
    size_res,           # dict or None
    balance: float,
    decision: str,      # "ACCEPTED" or "REJECTED"
    reject_reason: str = "",
):
    """
    Record a fully-evaluated signal (one that reached scan_entry + score_signal).

    Args:
        timestamp_ms  : closed 1H candle epoch ms
        symbol        : e.g. "BTC/USDT"
        signal        : dict from signals.scan_entry()
        score_result  : dict from scorer.score_signal()
        alignment     : dict from mtf.check_trend_alignment()
        regime        : current regime string
        adx           : latest ADX value for the symbol
        size_res      : dict from sizer.calculate_size(), or None if rejected
        balance       : current portfolio balance
        decision      : "ACCEPTED" or "REJECTED"
        reject_reason : rejection category string (empty when ACCEPTED)
    """
    import json

    bias = alignment.get("bias", "NEUTRAL") if alignment else "NEUTRAL"
    score = score_result.get("score", "")
    breakdown_str = json.dumps(score_result.get("breakdown", {})) if score_result else ""

    # Entry details — only populated on ACCEPTED signals
    entry_price = ""
    stop_price  = ""
    target_2r   = ""
    target_3r   = ""
    position_size = ""
    risk_pct    = ""

    if decision == "ACCEPTED" and size_res is not None:
        entry_price = signal.get("price", "")
        stop_price  = size_res.get("stop_price", "")
        stop_dist   = size_res.get("stop_distance", 0.0)
        direction   = "LONG" if "LONG" in signal.get("signal", "").upper() else "SHORT"
        if entry_price != "":
            ep = float(entry_price)
            sd = float(stop_dist)
            if direction == "LONG":
                target_2r = round(ep + 2.0 * sd, 2)
                target_3r = round(ep + 3.0 * sd, 2)
            else:
                target_2r = round(ep - 2.0 * sd, 2)
                target_3r = round(ep - 3.0 * sd, 2)
        position_size = size_res.get("contracts", "")
        risk_inr = size_res.get("risk_inr", 0.0)
        if balance and balance > 0:
            risk_pct = round(float(risk_inr) / float(balance) * 100.0, 4)

    row = {
        "timestamp_utc":   _ms_to_iso(timestamp_ms),
        "timestamp_ms":    timestamp_ms or "",
        "symbol":          symbol,
        "mode":            signal.get("mode", ""),
        "regime":          regime,
        "trend_alignment": bias,
        "rvol":            signal.get("rvol", ""),
        "atr":             signal.get("atr", ""),
        "adx":             round(adx, 2) if adx else "",
        "mss":             signal.get("mss", ""),
        "pullback_depth":  signal.get("pullback_depth", ""),
        "score":           score,
        "score_breakdown": breakdown_str,
        "decision":        decision,
        "reject_reason":   reject_reason,
        "entry_price":     entry_price,
        "stop_price":      stop_price,
        "target_2r":       target_2r,
        "target_3r":       target_3r,
        "position_size":   position_size,
        "risk_pct":        risk_pct,
    }
    _append_row(row)


def log_pre_rejection(
    timestamp_ms,
    symbol: str,
    regime: str,
    trend_alignment: str,
    adx: float,
    reject_reason: str,
):
    """
    Record a rejection that occurred BEFORE a signal dict was produced.

    Used for: regime gate, MTF gate, circuit breaker, open-trade block,
              max-positions block, stale-candle block.

    Args:
        timestamp_ms    : closed 1H candle epoch ms
        symbol          : e.g. "BTC/USDT"
        regime          : current regime string
        trend_alignment : bias string ("LONG", "SHORT", "NEUTRAL")
        adx             : latest ADX value
        reject_reason   : one of: regime / mtf / circuit_breaker /
                          open_trade / max_positions / stale_candle
    """
    row = {
        "timestamp_utc":   _ms_to_iso(timestamp_ms),
        "timestamp_ms":    timestamp_ms or "",
        "symbol":          symbol,
        "mode":            "",
        "regime":          regime,
        "trend_alignment": trend_alignment,
        "rvol":            "",
        "atr":             "",
        "adx":             round(adx, 2) if adx else "",
        "mss":             "",
        "pullback_depth":  "",
        "score":           "",
        "score_breakdown": "",
        "decision":        "REJECTED",
        "reject_reason":   reject_reason,
        "entry_price":     "",
        "stop_price":      "",
        "target_2r":       "",
        "target_3r":       "",
        "position_size":   "",
        "risk_pct":        "",
    }
    _append_row(row)
