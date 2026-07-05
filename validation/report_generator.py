# validation/report_generator.py
"""
Report Generator — 30-Day Paper Trading Validation
===================================================
Three public entry points:

  write_daily_summary(portfolio, circuit_breaker, day_str)
    → appends one row to logs/daily_summary.csv
    → called every day at 21:00 IST from paper_trader background timer

  write_weekly_summary(portfolio, closed_trades, iso_week_tuple)
    → appends one row to logs/weekly_summary.csv
    → called every Sunday at 21:00 IST from paper_trader background timer

  generate_final_report()
    → reads all log files, computes aggregate stats, writes paper_trial_report.md
    → triggered manually after 30 days:
        python -c "from validation.report_generator import generate_final_report; generate_final_report()"

No strategy logic lives here.
"""

import os
import csv
import json
import math
from datetime import datetime, timezone, timedelta

# ── File paths ───────────────────────────────────────────────────────────────

DAILY_SUMMARY_PATH  = "logs/daily_summary.csv"
WEEKLY_SUMMARY_PATH = "logs/weekly_summary.csv"
TRADE_LOG_PATH      = "logs/paper_trades.csv"
SIGNAL_AUDIT_PATH   = "logs/signal_audit.csv"
REPORT_PATH         = "paper_trial_report.md"

# ── Canonical v4.1 targets ───────────────────────────────────────────────────

CANONICAL = {
    "trades":          83,
    "profit_factor":   1.82,
    "win_rate_pct":    54.22,
    "max_drawdown_pct": 5.97,
}

# ── CSV headers ──────────────────────────────────────────────────────────────

DAILY_HEADER = [
    "date",
    "signals_generated",
    "signals_rejected",
    "trades_opened",
    "trades_closed",
    "balance",
    "open_positions",
    "daily_pnl",
    "current_drawdown_pct",
    "cb_daily_paused",
    "cb_weekly_halved",
    "cb_monthly_paused",
]

WEEKLY_HEADER = [
    "week",                 # ISO week string e.g. "2026-W27"
    "win_rate_pct",
    "profit_factor",
    "avg_r",
    "expectancy_inr",
    "avg_duration_h",
    "mode_a_trades",
    "mode_a_wr_pct",
    "mode_b_trades",
    "mode_b_wr_pct",
    "btc_trades",
    "btc_wr_pct",
    "link_trades",
    "link_wr_pct",
    "largest_winner_r",
    "largest_loser_r",
    "max_drawdown_pct",
]


# ── Internal helpers ─────────────────────────────────────────────────────────

def _ensure_csv(path, header):
    os.makedirs("logs", exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(header)


def _read_csv(path):
    """Read a CSV file and return list of dicts. Returns [] if file missing."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _compute_trade_stats(trades):
    """
    Compute aggregate metrics from a list of closed-trade dicts
    (as read from paper_trades.csv).

    Returns a dict with:
      total, wins, losses, win_rate_pct, gross_win, gross_loss,
      profit_factor, avg_r, expectancy_inr, avg_duration_h,
      largest_winner_r, largest_loser_r
    """
    if not trades:
        return {
            "total": 0, "wins": 0, "losses": 0,
            "win_rate_pct": 0.0, "gross_win": 0.0, "gross_loss": 0.0,
            "profit_factor": 0.0, "avg_r": 0.0, "expectancy_inr": 0.0,
            "avg_duration_h": 0.0, "largest_winner_r": 0.0, "largest_loser_r": 0.0,
        }

    wins   = [t for t in trades if _safe_float(t.get("pnl_inr")) > 0]
    losses = [t for t in trades if _safe_float(t.get("pnl_inr")) <= 0]

    gross_win  = sum(_safe_float(t.get("pnl_inr")) for t in wins)
    gross_loss = abs(sum(_safe_float(t.get("pnl_inr")) for t in losses))

    total      = len(trades)
    win_count  = len(wins)
    wr_pct     = (win_count / total * 100.0) if total > 0 else 0.0
    pf         = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    r_vals     = [_safe_float(t.get("pnl_r")) for t in trades]
    avg_r      = (sum(r_vals) / total) if total > 0 else 0.0
    expectancy = (sum(_safe_float(t.get("pnl_inr")) for t in trades) / total) if total > 0 else 0.0

    # Duration in hours (entry_time to exit_time, both ISO strings)
    durations = []
    for t in trades:
        try:
            entry = datetime.fromisoformat(t.get("entry_time", "").replace("Z", "+00:00"))
            exit_ = datetime.fromisoformat(t.get("exit_time", "").replace("Z", "+00:00"))
            durations.append((exit_ - entry).total_seconds() / 3600.0)
        except Exception:
            pass
    avg_dur = (sum(durations) / len(durations)) if durations else 0.0

    r_vals_sorted = sorted(r_vals)
    largest_loser  = r_vals_sorted[0]  if r_vals_sorted else 0.0
    largest_winner = r_vals_sorted[-1] if r_vals_sorted else 0.0

    return {
        "total":            total,
        "wins":             win_count,
        "losses":           total - win_count,
        "win_rate_pct":     round(wr_pct, 2),
        "gross_win":        round(gross_win, 2),
        "gross_loss":       round(gross_loss, 2),
        "profit_factor":    round(pf, 4),
        "avg_r":            round(avg_r, 4),
        "expectancy_inr":   round(expectancy, 2),
        "avg_duration_h":   round(avg_dur, 2),
        "largest_winner_r": round(largest_winner, 4),
        "largest_loser_r":  round(largest_loser, 4),
    }


def _compute_max_drawdown(daily_rows):
    """
    Compute max drawdown from daily_summary.csv rows.
    Uses the 'balance' column to reconstruct equity curve.
    """
    balances = [_safe_float(r.get("balance")) for r in daily_rows if r.get("balance")]
    if not balances:
        return 0.0
    peak = balances[0]
    max_dd = 0.0
    for b in balances:
        if b > peak:
            peak = b
        if peak > 0:
            dd = (peak - b) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 2)


def _filter_trades_by(trades, key, value):
    return [t for t in trades if t.get(key, "") == value]


# ── Public: daily summary ────────────────────────────────────────────────────

def write_daily_summary(portfolio, circuit_breaker, day_str: str):
    """
    Append one row to logs/daily_summary.csv.

    Args:
        portfolio      : PaperPortfolio instance
        circuit_breaker: CircuitBreaker instance
        day_str        : ISO date string e.g. "2026-07-05"
    """
    _ensure_csv(DAILY_SUMMARY_PATH, DAILY_HEADER)

    # Count trades opened today from signal audit (ACCEPTED rows with today's date)
    signals_today = _read_csv(SIGNAL_AUDIT_PATH)
    accepted_today = [
        r for r in signals_today
        if r.get("decision") == "ACCEPTED" and r.get("timestamp_utc", "").startswith(day_str)
    ]
    trades_opened_today = len(accepted_today)

    # Closed trades today from paper_trades.csv
    closed_all = _read_csv(TRADE_LOG_PATH)
    trades_closed_today = len([
        r for r in closed_all
        if r.get("exit_time", "").startswith(day_str)
    ])

    row = {
        "date":                 day_str,
        "signals_generated":    portfolio.weekly_signals_gen,
        "signals_rejected":     portfolio.weekly_signals_rej,
        "trades_opened":        trades_opened_today,
        "trades_closed":        trades_closed_today,
        "balance":              round(portfolio.current_balance, 2),
        "open_positions":       len(portfolio.open_trades),
        "daily_pnl":            round(portfolio.daily_pnl, 2),
        "current_drawdown_pct": round(portfolio.drawdown_pct(), 4),
        "cb_daily_paused":      circuit_breaker.daily_paused,
        "cb_weekly_halved":     circuit_breaker.weekly_halved,
        "cb_monthly_paused":    circuit_breaker.monthly_paused,
    }

    with open(DAILY_SUMMARY_PATH, "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow([row.get(c, "") for c in DAILY_HEADER])


# ── Public: weekly summary ───────────────────────────────────────────────────

def write_weekly_summary(portfolio, closed_trades, iso_week_tuple):
    """
    Append one row to logs/weekly_summary.csv.

    Args:
        portfolio     : PaperPortfolio instance
        closed_trades : list of closed trade dicts (portfolio.closed_trades)
        iso_week_tuple: tuple (year, week, weekday) from datetime.isocalendar()
    """
    _ensure_csv(WEEKLY_SUMMARY_PATH, WEEKLY_HEADER)

    year, week, _ = iso_week_tuple
    week_str = f"{year}-W{week:02d}"

    stats = _compute_trade_stats(closed_trades)

    # Per-mode stats
    mode_a_trades = _filter_trades_by(closed_trades, "exit_reason", "2R_TARGET")  # proxy
    # Use score column since mode is not in paper_trades.csv — derive from signal_audit
    audit_rows    = _read_csv(SIGNAL_AUDIT_PATH)
    accepted_audit = [r for r in audit_rows if r.get("decision") == "ACCEPTED"]

    def _audit_mode_stats(mode_key):
        mode_rows = [r for r in accepted_audit if r.get("mode") == mode_key]
        mode_syms = {r["symbol"] for r in mode_rows}
        mode_closed = []
        for t in closed_trades:
            sym = t.get("pair", "")
            # match closed trades to mode via entry_time lookup in audit
            audit_match = [
                r for r in mode_rows
                if r.get("symbol") == sym and
                   r.get("timestamp_utc", "")[:16] == t.get("entry_time", "")[:16]
            ]
            if audit_match:
                mode_closed.append(t)
        return _compute_trade_stats(mode_closed)

    stats_a = _audit_mode_stats("A")
    stats_b = _audit_mode_stats("B")

    # Per-symbol stats
    btc_trades  = _filter_trades_by(closed_trades, "pair", "BTC/USDT")
    link_trades = _filter_trades_by(closed_trades, "pair", "LINK/USDT")
    stats_btc   = _compute_trade_stats(btc_trades)
    stats_link  = _compute_trade_stats(link_trades)

    # Max drawdown this week from daily summaries
    daily_rows = _read_csv(DAILY_SUMMARY_PATH)
    week_daily = [r for r in daily_rows if r.get("date", "").startswith(str(year))]
    max_dd     = _compute_max_drawdown(week_daily)

    row = {
        "week":              week_str,
        "win_rate_pct":      stats["win_rate_pct"],
        "profit_factor":     stats["profit_factor"],
        "avg_r":             stats["avg_r"],
        "expectancy_inr":    stats["expectancy_inr"],
        "avg_duration_h":    stats["avg_duration_h"],
        "mode_a_trades":     stats_a["total"],
        "mode_a_wr_pct":     stats_a["win_rate_pct"],
        "mode_b_trades":     stats_b["total"],
        "mode_b_wr_pct":     stats_b["win_rate_pct"],
        "btc_trades":        stats_btc["total"],
        "btc_wr_pct":        stats_btc["win_rate_pct"],
        "link_trades":       stats_link["total"],
        "link_wr_pct":       stats_link["win_rate_pct"],
        "largest_winner_r":  stats["largest_winner_r"],
        "largest_loser_r":   stats["largest_loser_r"],
        "max_drawdown_pct":  max_dd,
    }

    with open(WEEKLY_SUMMARY_PATH, "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow([row.get(c, "") for c in WEEKLY_HEADER])


# ── Public: final report ─────────────────────────────────────────────────────

def generate_final_report():
    """
    Read all log files and write paper_trial_report.md to the project root.

    Trigger manually after 30 days:
        python -c "from validation.report_generator import generate_final_report; generate_final_report()"
    """
    now_str = datetime.now(tz=timezone(timedelta(hours=5, minutes=30))).strftime(
        "%Y-%m-%d %H:%M:%S IST"
    )

    # ── Load data ──────────────────────────────────────────────────────────
    closed_trades  = _read_csv(TRADE_LOG_PATH)
    signal_audit   = _read_csv(SIGNAL_AUDIT_PATH)
    daily_rows     = _read_csv(DAILY_SUMMARY_PATH)
    weekly_rows    = _read_csv(WEEKLY_SUMMARY_PATH)

    # ── Overall stats ──────────────────────────────────────────────────────
    stats_all  = _compute_trade_stats(closed_trades)
    max_dd     = _compute_max_drawdown(daily_rows)

    btc_trades  = _filter_trades_by(closed_trades, "pair", "BTC/USDT")
    link_trades = _filter_trades_by(closed_trades, "pair", "LINK/USDT")
    stats_btc   = _compute_trade_stats(btc_trades)
    stats_link  = _compute_trade_stats(link_trades)

    # Mode stats via signal audit cross-reference
    accepted_audit = [r for r in signal_audit if r.get("decision") == "ACCEPTED"]

    def _mode_closed(mode_key):
        matched = []
        for t in closed_trades:
            sym   = t.get("pair", "")
            entry = t.get("entry_time", "")[:16]
            hit = any(
                r.get("symbol") == sym and r.get("timestamp_utc", "")[:16] == entry
                for r in accepted_audit if r.get("mode") == mode_key
            )
            if hit:
                matched.append(t)
        return matched

    mode_a_closed = _mode_closed("A")
    mode_b_closed = _mode_closed("B")
    stats_a       = _compute_trade_stats(mode_a_closed)
    stats_b       = _compute_trade_stats(mode_b_closed)

    # ── Signal funnel ──────────────────────────────────────────────────────
    total_signals   = len(signal_audit)
    accepted_count  = len([r for r in signal_audit if r.get("decision") == "ACCEPTED"])
    rejected_count  = total_signals - accepted_count

    reject_reasons  = {}
    for r in signal_audit:
        if r.get("decision") == "REJECTED":
            reason = r.get("reject_reason", "unknown") or "unknown"
            reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

    # ── Deviation analysis ─────────────────────────────────────────────────
    actual_pf  = stats_all["profit_factor"]
    actual_wr  = stats_all["win_rate_pct"]
    actual_dd  = max_dd
    actual_cnt = stats_all["total"]

    def _dev(actual, target):
        if target == 0:
            return 0.0
        return round((actual - target) / target * 100.0, 2)

    dev_pf  = _dev(actual_pf, CANONICAL["profit_factor"])
    dev_wr  = _dev(actual_wr, CANONICAL["win_rate_pct"])
    dev_dd  = _dev(actual_dd, CANONICAL["max_drawdown_pct"])
    dev_cnt = _dev(actual_cnt, CANONICAL["trades"])

    # ── Pass / Fail verdict ────────────────────────────────────────────────
    pf_pass  = actual_pf  >= 1.60                 # allow ±12% of 1.82
    wr_pass  = actual_wr  >= 48.0                 # allow ±6pp of 54%
    dd_pass  = actual_dd  <  8.0                  # hard ceiling per spec
    verdict  = "✅ PASS" if (pf_pass and wr_pass and dd_pass) else "❌ FAIL"

    # ── Daily PnL table ────────────────────────────────────────────────────
    daily_table_rows = []
    for r in daily_rows:
        daily_table_rows.append(
            f"| {r.get('date','')} "
            f"| {r.get('trades_opened','')} "
            f"| {r.get('trades_closed','')} "
            f"| {r.get('daily_pnl','')} "
            f"| {r.get('balance','')} "
            f"| {r.get('current_drawdown_pct','')}% "
            f"| {'⛔' if r.get('cb_daily_paused','False')=='True' else '✓'} "
            f"| {'⚠' if r.get('cb_weekly_halved','False')=='True' else '✓'} |"
        )
    daily_table = "\n".join(daily_table_rows) if daily_table_rows else "_No daily data yet._"

    # ── Weekly performance table ───────────────────────────────────────────
    weekly_table_rows = []
    for r in weekly_rows:
        weekly_table_rows.append(
            f"| {r.get('week','')} "
            f"| {r.get('win_rate_pct','')}% "
            f"| {r.get('profit_factor','')} "
            f"| {r.get('avg_r','')} "
            f"| {r.get('expectancy_inr','')} "
            f"| {r.get('avg_duration_h','')}h "
            f"| A:{r.get('mode_a_trades','')} B:{r.get('mode_b_trades','')} "
            f"| {r.get('max_drawdown_pct','')}% |"
        )
    weekly_table = "\n".join(weekly_table_rows) if weekly_table_rows else "_No weekly data yet._"

    # ── Discrepancy section ────────────────────────────────────────────────
    discrepancies = []
    if abs(dev_pf)  > 15:
        discrepancies.append(
            f"- **Profit Factor** deviated {dev_pf:+.1f}% from canonical "
            f"(live {actual_pf:.4f} vs canonical {CANONICAL['profit_factor']})."
        )
    if abs(dev_wr)  > 10:
        discrepancies.append(
            f"- **Win Rate** deviated {dev_wr:+.1f}% from canonical "
            f"(live {actual_wr:.2f}% vs canonical {CANONICAL['win_rate_pct']}%)."
        )
    if actual_dd >= 8.0:
        discrepancies.append(
            f"- **Max Drawdown** exceeded 8% ceiling: {actual_dd:.2f}%."
        )
    if abs(dev_cnt) > 20:
        discrepancies.append(
            f"- **Trade count** deviated {dev_cnt:+.1f}% from canonical "
            f"(live {actual_cnt} vs canonical {CANONICAL['trades']})."
        )

    # Find the candles where the largest deviating trades occurred
    if discrepancies:
        # Surface the 5 worst trades for manual audit
        worst_trades = sorted(
            closed_trades,
            key=lambda t: _safe_float(t.get("pnl_r")),
        )[:5]
        worst_section = "\n### Worst Trades for Manual Audit\n"
        worst_section += "| # | Pair | Entry | Exit | Exit Reason | PnL R |\n"
        worst_section += "|---|---|---|---|---|---|\n"
        for i, t in enumerate(worst_trades, 1):
            worst_section += (
                f"| {i} | {t.get('pair','')} | {t.get('entry_time','')} "
                f"| {t.get('exit_time','')} | {t.get('exit_reason','')} "
                f"| {t.get('pnl_r','')} |\n"
            )
        discrepancy_section = "\n".join(discrepancies) + "\n" + worst_section
        discrepancy_section += (
            "\n> To identify the exact candle of divergence, cross-reference the "
            "entry_time above against `logs/signal_audit.csv` "
            "(filter: symbol + timestamp_utc prefix) and compare indicator values "
            "(RVOL, ATR, MSS, ADX) against the canonical backtest run on the same "
            "candle using `canonical_validation.py`."
        )
    else:
        discrepancy_section = "_No significant deviations detected. Live execution matches canonical engine within tolerance._"

    # ── Rejection breakdown table ──────────────────────────────────────────
    rej_table = "| Reason | Count |\n|---|---|\n"
    for reason, count in sorted(reject_reasons.items(), key=lambda x: -x[1]):
        rej_table += f"| {reason} | {count} |\n"

    # ── CB events ─────────────────────────────────────────────────────────
    cb_daily   = sum(1 for r in daily_rows if r.get("cb_daily_paused","False") == "True")
    cb_weekly  = sum(1 for r in daily_rows if r.get("cb_weekly_halved","False") == "True")
    cb_monthly = sum(1 for r in daily_rows if r.get("cb_monthly_paused","False") == "True")

    # ── Build report ───────────────────────────────────────────────────────
    report = f"""# ApexBot v4.1 — 30-Day Paper Trial Report

**Generated:** {now_str}
**Universe:** BTC/USDT + LINK/USDT
**Strategy version:** v4.1 (Mode A: MSS + RVOL > 2.0 | Mode B: Pullback | Mode R: Disabled)
**Verdict:** {verdict}

---

## 1. Canonical Targets vs Actual Results

| Metric | Canonical (v4.1 OOS) | Live Paper | Deviation | Pass? |
|---|---|---|---|---|
| Total Trades | {CANONICAL['trades']} | {actual_cnt} | {dev_cnt:+.1f}% | {'✅' if abs(dev_cnt) <= 20 else '❌'} |
| Profit Factor | {CANONICAL['profit_factor']} | {actual_pf:.4f} | {dev_pf:+.1f}% | {'✅' if pf_pass else '❌'} |
| Win Rate | {CANONICAL['win_rate_pct']}% | {actual_wr:.2f}% | {dev_wr:+.1f}% | {'✅' if wr_pass else '❌'} |
| Max Drawdown | {CANONICAL['max_drawdown_pct']}% | {actual_dd:.2f}% | {dev_dd:+.1f}% | {'✅' if dd_pass else '❌'} |

---

## 2. Trade Statistics

### Overall

| Metric | Value |
|---|---|
| Total Trades | {stats_all['total']} |
| Wins | {stats_all['wins']} |
| Losses | {stats_all['losses']} |
| Win Rate | {stats_all['win_rate_pct']}% |
| Profit Factor | {stats_all['profit_factor']} |
| Avg R | {stats_all['avg_r']} |
| Expectancy | ₹{stats_all['expectancy_inr']:,.2f} |
| Avg Trade Duration | {stats_all['avg_duration_h']}h |
| Largest Winner | {stats_all['largest_winner_r']}R |
| Largest Loser | {stats_all['largest_loser_r']}R |
| Max Drawdown | {actual_dd}% |

### By Mode

| Mode | Trades | Win Rate | PF | Avg R |
|---|---|---|---|---|
| Mode A (Breakout) | {stats_a['total']} | {stats_a['win_rate_pct']}% | {stats_a['profit_factor']} | {stats_a['avg_r']} |
| Mode B (Pullback) | {stats_b['total']} | {stats_b['win_rate_pct']}% | {stats_b['profit_factor']} | {stats_b['avg_r']} |

### By Symbol

| Symbol | Trades | Win Rate | PF | Avg R |
|---|---|---|---|---|
| BTC/USDT | {stats_btc['total']} | {stats_btc['win_rate_pct']}% | {stats_btc['profit_factor']} | {stats_btc['avg_r']} |
| LINK/USDT | {stats_link['total']} | {stats_link['win_rate_pct']}% | {stats_link['profit_factor']} | {stats_link['avg_r']} |

---

## 3. Signal Funnel

| Stage | Count |
|---|---|
| Total pipeline evaluations | {total_signals} |
| Accepted (entry taken) | {accepted_count} |
| Rejected | {rejected_count} |
| Acceptance rate | {round(accepted_count / total_signals * 100, 2) if total_signals > 0 else 0}% |

---

## 4. Rejection Breakdown

{rej_table}
---

## 5. Circuit Breaker Events

| Rule | Trigger Count (days active) |
|---|---|
| Daily pause (−2% daily) | {cb_daily} |
| Weekly size-halve (−5% weekly) | {cb_weekly} |
| Monthly pause (−10% monthly) | {cb_monthly} |

---

## 6. Daily PnL Table

| Date | Opened | Closed | Daily PnL | Balance | DD% | CB Daily | CB Weekly |
|---|---|---|---|---|---|---|---|
{daily_table}

---

## 7. Weekly Performance Table

| Week | WR% | PF | Avg R | Expectancy | Avg Dur | Modes | Max DD% |
|---|---|---|---|---|---|---|---|
{weekly_table}

---

## 8. Drawdown Analysis

- **Max drawdown over 30 days:** {actual_dd}%
- **Canonical max drawdown (OOS):** {CANONICAL['max_drawdown_pct']}%
- **Hard ceiling:** 8.0%
- **Status:** {'WITHIN BOUNDS ✅' if actual_dd < 8.0 else 'EXCEEDED CEILING ❌'}

---

## 9. Discrepancy Analysis

{discrepancy_section}

---

## 10. Conclusion

**Verdict: {verdict}**

Acceptance criteria:
- Profit Factor ≥ 1.60 (≈ 1.82 ± 12%): {'PASS ✅' if pf_pass else 'FAIL ❌'}
- Win Rate ≥ 48.0% (≈ 54% ± 6pp): {'PASS ✅' if wr_pass else 'FAIL ❌'}
- Max Drawdown < 8.0%: {'PASS ✅' if dd_pass else 'FAIL ❌'}

{"The live paper trading results confirm that the execution engine faithfully replicates the canonical backtest strategy. The system is ready for the next phase." if verdict == "✅ PASS" else "Live paper trading results fell outside acceptable tolerance bands. Review Section 9 (Discrepancy Analysis) to identify the root cause before proceeding to the next phase."}

---

_This report was generated automatically by `validation/report_generator.py`._
_Source data: `logs/paper_trades.csv`, `logs/signal_audit.csv`, `logs/daily_summary.csv`, `logs/weekly_summary.csv`._
"""

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(report)

    verdict_ascii = "PASS" if verdict.startswith("\u2705") else "FAIL"
    print(f"[REPORT] paper_trial_report.md written ({len(report):,} bytes).")
    print(f"[REPORT] Verdict: {verdict_ascii}")
    return REPORT_PATH
