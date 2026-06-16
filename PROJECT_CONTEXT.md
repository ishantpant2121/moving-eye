# Project Context: ApexBot Trading Engine

Persistent project context and system specifications.

## 1. Project Objective
ApexBot is a high-performance quantitative trading engine designed for **CoinDCX Pro Futures**. It integrates multi-timeframe analysis, market regime classification, technical signal scanners, position sizing, risk management, and a live paper trading system.

---

## 2. Assets Traded
*   **BTC/USDT** (Primary Production Asset - fully validated for all modes).
*   **LINK/USDT** (Validated specifically for Mode B pullback setups).
*   **ETH/USDT, SOL/USDT, BNB/USDT, AVAX/USDT** (Altcoins monitored but excluded from execution pending a 60-day live paper trading trial on BTC).

---

## 3. Market Regimes & Indicators
Classification runs on the **4H Timeframe** using Wilder's ADX and ATR percentiles:
*   **TRENDING**: ADX > 25.0, positive EMA(50) slope, and ATR above 40th percentile.
*   **VOLATILE**: ATR above 85th percentile and ADX rising.
*   **RANGING**: ADX < 20.0 and price within 1.5 * ATR of EMA(200).

---

## 4. Entry Scan Modes (1H Timeframe)

### Mode A: Breakout
*   **Pre-requisite**: Regime is `TRENDING` or `VOLATILE`, and daily/4H trend alignment bias matches trade direction.
*   **Trigger**: Price closes above the highest of the last 3 swing highs (LONG) or below the lowest of the last 3 swing lows (SHORT).
*   **Filters**:
    *   Relative Volume (RVOL) > 1.5 (current volume / 20-bar SMA).
    *   ATR Expanding: Current ATR(14) > 5-bar average ATR.
    *   Volume Slope: Linear regression slope of last 10 volume bars is positive (> 0).
    *   ADX Exhaustion: ADX(14) <= 50.0.
    *   **MSS Filter**: Market Structure Shift (MSS) required on 1H timeframe to permit breakout entries (`ENABLE_MSS = "filter"`, `MSS_MODE = "A"`).

### Mode B: Pullback (Crypto-Native v2)
*   **Pre-requisite**: Regime is `TRENDING` or `VOLATILE`, and daily/4H trend alignment bias matches trade direction. Restricted to **BTC/USDT** and **LINK/USDT**.
*   **Trigger**: Price retraces within 2.0 * ATR of 1H EMA(20) or EMA(50) and prints a Bullish Engulfing or Hammer (LONG) / Bearish Engulfing or Shooting Star (SHORT) in the last 3 bars.
*   **Filters**:
    *   ATR Health: Current ATR >= 70% of 5-bar average ATR (prevents entering during market collapse).
    *   Volume Contraction: 3-bar average volume < 20-bar average volume (confirms a healthy consolidation pullback rather than a distribution dump).

### Mode R: Mean Reversion (Globally Disabled for Production)
*   **Status**: Disabled globally in production configuration via `ENABLE_MODE_R = False` (Experiment 1). Code remains preserved for research.
*   **Pre-requisite**: Regime is `RANGING`.
*   **Trigger**: Price comes within 1.0% of the Upper Bollinger Band (SHORT) or Lower Bollinger Band (LONG) [20-SMA, 2-std].
*   **Filters**:
    *   RSI(14) oversold (< 40 for LONG) or overbought (> 60 for SHORT).
    *   RVOL > 1.0.
    *   Candlestick pattern (Hammer/Engulfing) confirmation in last 3 bars.
    *   Macro trend alignment: Trade direction must not oppose the 4H macro bias.

---

## 5. Risk & Money Management

### Position Sizing
*   **Base Risk**: Capped at 1% of the shared account balance per trade.
*   **Formula**: `contracts = risk_per_trade / stop_distance`.
*   **Multipliers** (applied sequentially):
    1.  If Regime is `VOLATILE`: Multiply contracts by `0.5`.
    2.  If Signal Score is `strong` (Score >= 0.85): Multiply contracts by `1.25`.
    3.  If Weekly Drawdown is > 5.0%: Multiply contracts by `0.5`.
*   **Risk Capping**: Capped strictly at 1% of equity.

### Circuit Breakers (R2 Rules)
*   **Daily Drawdown**: If daily balance drawdown >= 2.0%, pause entries for the rest of the day.
*   **Weekly Drawdown**: If weekly drawdown >= 5.0%, halve all position sizes.
*   **Monthly Drawdown**: If monthly drawdown >= 10.0%, pause entries for the rest of the month.
*   **Gap Risk Limit**: Exit calculations cap simulated gap risk at 1.5R loss.

### Stop Loss & Multi-Stage Target Exits
*   **Initial Stop Loss**: `1.5 * ATR` from the entry price.
*   **Target Exits**:
    *   **OPEN**: Hard stop active.
    *   **PARTIAL_1**: Hit `2R` target $\rightarrow$ Close 40% of position and move stop to breakeven (entry price).
    *   **PARTIAL_2**: Hit `3R` target $\rightarrow$ Close 20% of position and activate trailing stop.
    *   **CLOSED**: Position fully exited.
*   **Trailing Stop**: Evaluated on 4H close. Trails below/above the lowest low / highest high (or swing points) of the last 10 bars on the 4H chart.
*   **Regime Flip Exit**: Exit remaining position immediately if regime turns to `RANGING` or `VOLATILE` (except when overridden).

---

## 6. Execution Workflow Constraints
All future development, coding, and debugging tasks must follow these rules:

1.  **Read PROJECT_CONTEXT.md first**: Read this context file before any code inspections.
2.  **Minimize Token Usage**: Avoid re-reading unchanged source code files. Use `context-compressor` configurations or summaries where possible.
3.  **Codebase Mapper**: Run codebase checks before inspecting individual files.
4.  **Reuse Prior Findings**: Do not run redundant backtests or repeat already validated findings.
5.  **Context Summarization**: Summarize context into $\le$ 1,000 tokens before execution.
6.  **No Logic Modifications**: Never modify core trading rules or risk management algorithms unless explicitly asked by the user.

---

## 7. Project Success Criteria
*   Out-of-sample Profit Factor $\ge$ 1.30.
*   Annualized Sharpe Ratio $\ge$ 1.50 (or high positive expectancy).
*   Maximum Portfolio Drawdown $\le$ 15.0%.
*   Win Rate $\ge$ 40.0%.
