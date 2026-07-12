"""
validate_v41.py
===============
Targeted regression validation for the v4.1 production candidate.
Universe: BTC/USDT + LINK/USDT (Universe C)
Period:   OOS 2024-01-01 to 2026-06-14

Verifies that the deployment blocker fixes (buffer.py, paper_trader.py, main.py)
have NOT changed backtest metrics from the canonical reference baseline:
  PF=1.82, WR=54.22%, DD=5.97%, Trades=83

This validation uses the true canonical engine (scratch/portfolio_validation.py).
"""

import os
import sys
import time

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

import scratch.portfolio_validation as pv
from backtest import load_csv_candles

# ── Reference baseline (v4.1 candidate, Universe C, OOS, canonical engine) ──
BASELINE = {
    "trades": 83,
    "profit_factor": 1.82,
    "win_rate": 54.22,
    "max_drawdown": 5.97,
}

TOLERANCE = {
    "trades": 0,         # must be exact
    "profit_factor": 0.02,
    "win_rate": 0.5,
    "max_drawdown": 0.2,
}

def check(label, actual, expected, tol):
    diff = abs(actual - expected)
    ok = diff <= tol
    status = "PASS" if ok else "FAIL"
    sign = "+" if actual > expected else ""
    print(f"  {status}  {label:22s}  expected={expected}  actual={actual:.4f}  diff={sign}{actual - expected:.4f}  (tol ±{tol})")
    return ok


def main():
    print("=" * 65)
    print("  v4.1 REGRESSION VALIDATION — Universe C (BTC/USDT + LINK/USDT)")
    print("  OOS Period: 2024-01-01 to 2026-06-14")
    print("=" * 65)

    # ── Load cached CSVs ─────────────────────────────────────────────────────
    symbols = ["BTC/USDT", "LINK/USDT"]
    pv.SYMBOLS = symbols
    data_1h, data_4h, data_1d = {}, {}, {}
    for sym in symbols:
        prefix = sym.split("/")[0]
        data_1h[sym] = load_csv_candles(f"data/{prefix}_1H.csv")
        data_4h[sym] = load_csv_candles(f"data/{prefix}_4H.csv")
        data_1d[sym] = load_csv_candles(f"data/{prefix}_1D.csv")
        print(f"  Loaded {sym}: 1H={len(data_1h[sym])}, 4H={len(data_4h[sym])}, 1D={len(data_1d[sym])} bars")

    INITIAL_BALANCE = 50000.0

    # ── OOS date range ────────────────────────────────────────────────────────
    oos_start_ms = 1704067200000   # 2024-01-01 00:00:00 UTC
    oos_end_ms   = 1781395199000   # 2026-06-14 23:59:59 UTC

    print(f"\nRunning OOS backtest for {symbols}...")
    t0 = time.time()
    trades, equity, _, _, _, _, _ = pv.run_portfolio_backtest(
        data_1h, data_4h, data_1d,
        oos_start_ms, oos_end_ms,
        initial_balance=INITIAL_BALANCE
    )
    elapsed = time.time() - t0

    metrics = pv.calculate_portfolio_metrics(trades, equity, initial_balance=INITIAL_BALANCE)

    btc_count  = sum(1 for t in trades if t.get("pair") == "BTC/USDT")
    link_count = sum(1 for t in trades if t.get("pair") == "LINK/USDT")

    print(f"\nBacktest complete in {elapsed:.1f}s")
    print(f"\n{'-'*65}")
    print(f"  Total Trades : {metrics['total_trades']}  (BTC={btc_count}, LINK={link_count})")
    print(f"  Win Rate     : {metrics['win_rate']:.2f}%")
    print(f"  Profit Factor: {metrics['profit_factor']:.4f}")
    print(f"  Max Drawdown : {metrics['max_drawdown']:.2f}%")
    print(f"  CAGR         : {metrics.get('cagr', 0.0):.2f}%")
    print(f"{'-'*65}")

    # ── Regression check ─────────────────────────────────────────────────────
    print(f"\n{'-'*65}")
    print("  REGRESSION CHECKS vs BASELINE")
    print(f"{'-'*65}")

    results = []
    results.append(check("Trades", metrics["total_trades"], BASELINE["trades"], TOLERANCE["trades"]))
    results.append(check("Profit Factor",   metrics["profit_factor"], BASELINE["profit_factor"], TOLERANCE["profit_factor"]))
    results.append(check("Win Rate (%)",    metrics["win_rate"],       BASELINE["win_rate"],       TOLERANCE["win_rate"]))
    results.append(check("Max Drawdown (%)",metrics["max_drawdown"],   BASELINE["max_drawdown"],   TOLERANCE["max_drawdown"]))

    all_pass = all(results)
    print(f"{'-'*65}")
    print(f"\n  OVERALL: {'[PASS] ALL PASS - v4.1 metrics PRESERVED (zero regression)' if all_pass else '[FAIL] FAIL - strategy or logic change detected!'}")
    print()

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
