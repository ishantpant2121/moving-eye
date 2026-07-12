"""
reset_for_trial.py
==================
One-time clean-start script for the official 30-day paper trial.

Run this ONCE, immediately before starting paper_trader.py for the official trial.
It resets all log files to header-only state without deleting the archive.

Usage:
    python reset_for_trial.py
    python paper_trader.py

Prerequisites:
    - Pre-trial data already archived in logs/archive_pre_trial_*/
    - validate_v41.py must be PASS before running this
"""

import os
import csv

os.chdir(os.path.dirname(os.path.abspath(__file__)))

TRADE_CSV_HEADER = [
    "pair", "entry_time", "exit_time", "direction", "entry_price",
    "exit_price", "contracts", "pnl_inr", "pnl_r", "exit_reason",
    "score", "regime_at_entry",
]

SIGNAL_AUDIT_HEADER = [
    "timestamp_utc", "timestamp_ms", "symbol", "mode",
    "regime", "trend_alignment", "rvol", "atr", "adx", "mss", "pullback_depth",
    "score", "score_breakdown", "decision", "reject_reason",
    "entry_price", "stop_price", "target_2r", "target_3r", "position_size", "risk_pct",
]

DAILY_HEADER = [
    "date", "signals_generated", "signals_rejected", "trades_opened",
    "trades_closed", "balance", "open_positions", "daily_pnl",
    "current_drawdown_pct", "cb_daily_paused", "cb_weekly_halved", "cb_monthly_paused",
]

WEEKLY_HEADER = [
    "week", "win_rate_pct", "profit_factor", "avg_r", "expectancy_inr",
    "avg_duration_h", "mode_a_trades", "mode_a_wr_pct", "mode_b_trades",
    "mode_b_wr_pct", "btc_trades", "btc_wr_pct", "link_trades", "link_wr_pct",
    "largest_winner_r", "largest_loser_r", "max_drawdown_pct",
]

os.makedirs("logs", exist_ok=True)

files_to_reset = {
    "logs/paper_trades.csv":   TRADE_CSV_HEADER,
    "logs/signal_audit.csv":   SIGNAL_AUDIT_HEADER,
    "logs/daily_summary.csv":  DAILY_HEADER,
    "logs/weekly_summary.csv": WEEKLY_HEADER,
}

for path, header in files_to_reset.items():
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(header)
    print(f"Reset: {path} (header only)")

# Reset paper_log.txt
with open("logs/paper_log.txt", "w", encoding="utf-8") as fh:
    fh.write("")
print("Reset: logs/paper_log.txt (empty)")

# Remove stale portfolio state so paper_trader starts fresh
state_path = "logs/portfolio_state.json"
if os.path.exists(state_path):
    os.remove(state_path)
    print(f"Removed: {state_path}")

print()
print("Clean baseline established.")
print("You may now run: python paper_trader.py")
