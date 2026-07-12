import os
import shutil
import datetime
import json
import csv

os.chdir("d:/moving eye")

# 1. Archive
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
archive_dir = f"logs/archive_pre_trial_{ts}"
os.makedirs(archive_dir, exist_ok=True)

files_to_archive = [
    "logs/paper_log.txt",
    "logs/paper_trades.csv", 
    "logs/signal_audit.csv",
    "logs/daily_summary.csv",
    "logs/weekly_summary.csv",
]

for src in files_to_archive:
    if os.path.exists(src):
        dst = os.path.join(archive_dir, os.path.basename(src))
        shutil.copy2(src, dst)
        print(f"Archived: {src} -> {dst}")

# 2. Reset files to headers/empty
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

files_to_reset = {
    "logs/paper_trades.csv":   TRADE_CSV_HEADER,
    "logs/signal_audit.csv":   SIGNAL_AUDIT_HEADER,
    "logs/daily_summary.csv":  DAILY_HEADER,
    "logs/weekly_summary.csv": WEEKLY_HEADER,
}

for path, header in files_to_reset.items():
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(header)
    print(f"Reset: {path}")

# Reset paper_log.txt
with open("logs/paper_log.txt", "w", encoding="utf-8") as fh:
    fh.write("")
print("Reset: logs/paper_log.txt")

# Ensure no portfolio_state.json exists
state_path = "logs/portfolio_state.json"
if os.path.exists(state_path):
    os.remove(state_path)
    print(f"Removed stale state: {state_path}")

# 3. Create Trial Status File
trial_id = f"TRIAL-V4.1-{ts}"
now_utc = datetime.datetime.now(datetime.timezone.utc)
now_ist = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

trial_status = {
    "trial_id": trial_id,
    "strategy_version": "v4.1",
    "status": "ACTIVE",
    "start_time_utc": now_utc.isoformat(),
    "start_time_ist": now_ist.isoformat(),
    "duration_days": 30,
    "target_end_time_utc": (now_utc + datetime.timedelta(days=30)).isoformat(),
    "target_end_time_ist": (now_ist + datetime.timedelta(days=30)).isoformat(),
    "starting_balance": 50000.0,
    "symbols": ["BTC/USDT", "LINK/USDT"],
    "canonical_baselines": {
        "trades": 83,
        "profit_factor": 1.82,
        "win_rate_pct": 54.22,
        "max_drawdown_pct": 5.97
    },
    "archived_logs": archive_dir
}

with open("trial_status.json", "w", encoding="utf-8") as fh:
    json.dump(trial_status, fh, indent=4)
print(f"Created trial status file: trial_status.json with ID {trial_id}")
