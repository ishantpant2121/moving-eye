# Memory Status: ApexBot Strategy Tracker

Active strategy tracking, experiment history, and pending tasks.

---

## 1. Strategy Versioning
*   **Last Strategy Version**: v4.1 (MSS Filter on Mode A breakouts enabled, Mode R globally disabled, 30-day paper trading validation framework installed).
*   **Active Production Candidate**:
    *   **BTC/USDT**: Mode A v2 (Breakout with MSS Filter + RVOL>2.0) and Mode B v2 (Pullback) active. Mode R disabled.
    *   **LINK/USDT**: Mode B v2 (Pullback) active. Mode R disabled.
    *   *Altcoins (ETH, SOL, BNB, AVAX)*: Paused/excluded from execution pending BTC live performance.

---

## 2. Completed Experiments & Validation Runs
*   **Mode B v2 Pullback Upgrade (A/B Test)**:
    *   *Result*: Mode B v2 significantly reduced false signals during choppy ranges by checking 4H trend confirmation, ATR stability, and volume contraction.
    *   *Altcoin Allow-list*: Confirmed that altcoins like SOL and AVAX suffer severe stop-out rates due to high intraday volatility. Mode B is restricted strictly to BTC and LINK.
*   **Filter Sensitivity Analysis**:
    *   *RVOL Pullback Gate (RVOL > 1.0)*: Confirmed redundant due to strong candlestick pattern filters.
    *   *ADX Breakout Exhaustion Gate (ADX > 50.0)*: Confirmed effective at screening late-stage breakout traps.
    *   *Volume Slope Gate*: Identified as the most efficient gate to adjust for higher trade frequency with minimal Profit Factor degradation.
*   **Mode R Isolation & Portfolio Validation (June 2026)**:
    *   *Result*: Isolated Mode R across 4 experiments. Mode R is highly unprofitable on altcoins and BTC in its baseline form. Disabling Mode R entirely (Experiment 1) restores portfolio profitability to PF 1.47 and MaxDD 9.67% in OOS. Strict gating of Mode R (Experiment 3) on BTC is a viable alternative if mean reversion is desired.
*   **Institutional Trading Experiments (June 2026)**:
    *   *Result*: Evaluated 9 combinations of Liquidity Sweeps, Market Structure Shifts (MSS/CHOCH), Pullback Depth, and Regime Transition concepts. Baseline OOS had 151 trades, 1.47 PF, and 9.67% MaxDD. Adding the MSS Filter on Mode A breakouts specifically (v4.0 candidate) optimizes the portfolio: OOS trades count is normalized to **97 trades** (fitting target 96-180 trades), Max Drawdown drops to **6.99%** (target <8%), Win Rate rises to **54.64%** (target 50%-60%), and Profit Factor rises to **1.70** (up from 1.47). Other filter options (like MSS filter on both) are too restrictive, dropping trades count to 32.
*   **Regime Robustness Audit (June–July 2026)**:
    *   *Result*: Partitioned OOS 2024–2026 into Bull / Bear / Sideways / HighVol regimes using 1D BTC data. Strategy is bull-market dependent (best results in Bull). Sideways regime produces marginal results (PF≈1.0, DD 9.76%). No Bear trades executed due to existing daily EMA gates. HighVol regime trades are limited but profitable.
    *   *Output*: `results/regime_partition_report.md`
*   **Adversarial Red-Team Audit (July 2026)**:
    *   *Result*: Identified 4 structural risks: (1) bull-market dependence, (2) sideways regime marginal performance, (3) limited bear market exposure data, (4) slippage/fill model simplifications. None require strategy changes for paper trial. Risk accepted for controlled 30-day test.
*   **Validation Framework Installation (July 2026)**:
    *   *Result*: Installed `validation/signal_auditor.py` and `validation/report_generator.py`. Signal audit hook injected into `paper_trader.py`. All 9 integration tests pass. Daily and weekly summary writers tested and functional.
    *   *Bug Found & Fixed*: June 2026 paper run used an intermediate version of paper_trader.py (pre-July-5 injection) that raised `NameError: name 'timestamp_ms' is not defined` on every 1H candle. Current paper_trader.py (modified 2026-07-05) has the correct injection — no error reproduces.
    *   *Baseline Clarification*: `validate_v41.py` uses `backtest.py` engine (Result B: 87T / PF=1.75 / WR=56.32% / DD=6.75%). Canonical paper-trial target uses `portfolio_validation.py` engine (Result C: 83T / PF=1.82 / WR=54.22% / DD=5.97%). Both are known-good; no regression detected.
    *   *Pre-trial data archived*: `logs/archive_pre_trial_20260712_133445/` (2 duplicate BTC test trades, empty signal audit from June run).

---

## 3. Portfolio Validation Status
*   **Shared Capital Simulation**: **YES** (implementation exists in `backtest.py` and is fully utilized).
*   **Validation Execution**: **YES** (completed full portfolio validation on 6-asset universe in both IS and OOS).
*   **Correlated Drawdown Audited**: **YES** (analyzed and reported in `results/portfolio_experiments_report.md`).

---

## 4. Pending Tasks & Roadmap
1.  **30-Day Paper Trading Validation (NEXT)**: Reset log files to clean baseline, then run `python paper_trader.py` for 30 days. After 30 days trigger `python -c "from validation.report_generator import generate_final_report; generate_final_report()"` to produce `paper_trial_report.md`. Target: PF≥1.60, WR≥48%, DD<8%.
    *   **Pre-trial logs archived**: `logs/archive_pre_trial_20260712_133445/`
    *   **Clean start command**: Reset paper_trades.csv, signal_audit.csv, daily_summary.csv, weekly_summary.csv, paper_log.txt headers only, then `python paper_trader.py`
2.  **Future Research — Trade Frequency** (NOT to be mixed with paper trial): Explore increasing to 8–15 trades/month.

---

## 5. Canonical Engine & Production Metrics

### Canonical Backtest Engine
*   **File**: `scratch/portfolio_validation.py`
*   **Command**: `python canonical_validation.py` (from `d:/moving eye`)
*   **Why canonical**: Enforces `alignment["aligned"]` gate, `breakout_filter_config="B"` (RVOL>2.0), regime update every 1H, full R2 circuit breakers (daily/weekly/monthly), and max 2 concurrent positions with shared capital.
*   **NOT canonical**: `backtest.py run_backtest()` — missing alignment gate, missing RVOL>2.0 config, no circuit breakers, regime only on 4H close.

### v4.1 Production Candidate Metrics (BTC/USDT + LINK/USDT, OOS 2024-2026)
*   **Total Trades**: 83 (BTC=43, LINK=40)
*   **Profit Factor**: 1.82
*   **Win Rate**: 54.22%
*   **Max Drawdown**: 5.97%
*   **CAGR**: 10.89%
*   **Expectancy**: ₹173.91
*   **Avg R**: 0.4795
*   **Source**: Confirmed 2026-06-19 via `canonical_validation.py`

