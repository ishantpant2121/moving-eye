"""
canonical_validation.py
=======================
Runs the CANONICAL BTC+LINK portfolio validation using scratch/portfolio_validation.py.
This is the single source of truth for v4.1 production metrics.

Key differences from backtest.py run_backtest():
  - alignment["aligned"] gate required before entry
  - breakout_filter_config="B" (RVOL>2.0, vol slope disabled)
  - Regime classified every 1H candle (not just on 4H close)
  - Full circuit breakers: daily >=2%, weekly >=5%, monthly >=10%
  - Weekly size halving when weekly DD >=5%
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Patch SYMBOLS before anything else runs
import scratch.portfolio_validation as pv
pv.SYMBOLS = ["BTC/USDT", "LINK/USDT"]

from backtest import load_csv_candles

def main():
    print("=" * 65)
    print("  CANONICAL v4.1 VALIDATION")
    print("  Engine  : scratch/portfolio_validation.py")
    print("  Universe: BTC/USDT + LINK/USDT (shared capital)")
    print("  OOS     : 2024-01-01 to 2026-06-14")
    print("=" * 65)

    data_1h, data_4h, data_1d = {}, {}, {}
    for sym in pv.SYMBOLS:
        p = sym.split("/")[0]
        data_1h[sym] = load_csv_candles(f"data/{p}_1H.csv")
        data_4h[sym] = load_csv_candles(f"data/{p}_4H.csv")
        data_1d[sym] = load_csv_candles(f"data/{p}_1D.csv")
        print(f"  Loaded {sym}: 1H={len(data_1h[sym])}, 4H={len(data_4h[sym])}, 1D={len(data_1d[sym])}")

    oos_start = 1704067200000  # 2024-01-01 00:00:00 UTC
    oos_end   = 1781395199000  # 2026-06-14 23:59:59 UTC

    print("\nRunning OOS backtest...")
    trades, equity, dates, closes, util, steps, overlap = pv.run_portfolio_backtest(
        data_1h, data_4h, data_1d, oos_start, oos_end
    )
    m = pv.calculate_portfolio_metrics(trades, equity)

    btc_count  = sum(1 for t in trades if t["pair"] == "BTC/USDT")
    link_count = sum(1 for t in trades if t["pair"] == "LINK/USDT")

    wins  = [t for t in trades if t["pnl_inr"] > 0]
    losses = [t for t in trades if t["pnl_inr"] < 0]

    print()
    print("-" * 65)
    print("  OOS RESULTS (CANONICAL)")
    print("-" * 65)
    print(f"  Total Trades  : {m['total_trades']}  (BTC={btc_count}, LINK={link_count})")
    print(f"  Win Rate      : {m['win_rate']}%")
    print(f"  Profit Factor : {m['profit_factor']}")
    print(f"  Max Drawdown  : {m['max_drawdown']}%")
    print(f"  CAGR          : {m['cagr']}%")
    print(f"  Total Return  : {m['total_return']}%")
    print(f"  Expectancy    : {m['expectancy']}")
    print(f"  Avg R         : {m['avg_r']}")
    print("-" * 65)
    print()
    print("  COMPARISON vs PRIOR RESULTS")
    print("-" * 65)
    print("  Result A (6-asset portfolio, BTC+LINK filtered): 83T / PF=1.82 / WR=54.22% / DD=5.97%")
    print("  Result B (backtest.py 2-asset isolation):         87T / PF=1.75 / WR=56.32% / DD=6.75%")
    print(f"  Result C (CANONICAL 2-asset shared capital):      {m['total_trades']}T / PF={m['profit_factor']} / WR={m['win_rate']}% / DD={m['max_drawdown']}%")
    print("-" * 65)

if __name__ == "__main__":
    main()
