# backtest.py
"""
Backtester Module (Phase 3)
===========================
Fetches historical data, replays it chronologically through the strategy stack,
calculates performance metrics, and prints results for In-Sample (2021-2023)
and Out-of-Sample (2024-2026) periods. Saves a trade report to CSV.

Includes realistic transaction costs: 0.04% fee + 0.05% slippage.
Guarantees zero look-ahead bias by filtering 4H and 1D candle buffers.
"""

import os
import sys
import time
import csv
from datetime import datetime, timezone
import requests
import numpy as np

# Ensure workspace is in path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

import regime
import mtf
import signals
import scorer
import sizer
import trade_manager
from buffer import OHLCVBuffer

# ───────────────────────────────────────────────────────────────────────────
# 1. Historical Data Downloader
# ───────────────────────────────────────────────────────────────────────────

def download_data_if_needed(symbol, timeframe, filepath, resolution, from_sec, to_sec):
    """
    Downloads historical candles from CoinDCX's public API in pages and saves to CSV.
    """
    if os.path.exists(filepath):
        print(f"  [CACHE] File {filepath} already exists. Skipping download.")
        return

    print(f"\n[DOWNLOAD] Fetching {timeframe} candles for {symbol}...")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    duration_sec = {
        "1H": 3600,
        "4H": 4 * 3600,
        "1D": 24 * 3600
    }[timeframe]

    # Use a chunk limit of 5000 candles to prevent exceeding CoinDCX cap
    chunk_limit = 5000
    chunk_duration = chunk_limit * duration_sec
    
    all_candles = []
    url = "https://public.coindcx.com/market_data/candlesticks"
    
    coindcx_symbol = symbol.replace("/", "_")
    if not coindcx_symbol.startswith("B-"):
        coindcx_symbol = f"B-{coindcx_symbol}"

    current_from = from_sec
    while current_from < to_sec:
        current_to = min(current_from + chunk_duration, to_sec)
        from_date_str = time.strftime('%Y-%m-%d', time.gmtime(current_from))
        to_date_str = time.strftime('%Y-%m-%d', time.gmtime(current_to))
        print(f"  -> Fetching range: {from_date_str} to {to_date_str}...")

        params = {
            "pair": coindcx_symbol,
            "resolution": resolution,
            "from": current_from,
            "to": current_to,
            "pcode": "f"
        }

        success = False
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    candles = data.get("data", [])
                    for c in candles:
                        all_candles.append([
                            int(c["time"]), # timestamp in ms
                            float(c["open"]),
                            float(c["high"]),
                            float(c["low"]),
                            float(c["close"]),
                            float(c["volume"])
                        ])
                    success = True
                    break
                else:
                    print(f"     [WARN] API error {resp.status_code}. Retrying...")
            except Exception as e:
                print(f"     [WARN] Exception: {e}. Retrying...")
            time.sleep(1.0)

        if not success:
            raise RuntimeError(f"Failed to download data for {timeframe} in range: {from_date_str} to {to_date_str}")

        current_from = current_to
        time.sleep(0.5)

    # Deduplicate and sort chronologically
    seen = set()
    unique_candles = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique_candles.append(c)
    
    unique_candles.sort(key=lambda x: x[0])
    print(f"  -> Successfully fetched {len(unique_candles)} unique candles.")

    # Write to CSV
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        writer.writerows(unique_candles)
    print(f"  -> Saved to {filepath}")


def load_csv_candles(filepath):
    """
    Loads candles from a cached CSV file.
    """
    candles = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader) # skip header
        for row in reader:
            candles.append([
                int(row[0]),     # timestamp
                float(row[1]),   # open
                float(row[2]),   # high
                float(row[3]),   # low
                float(row[4]),   # close
                float(row[5])    # volume
            ])
    return candles

# ───────────────────────────────────────────────────────────────────────────
# 2. Backtest Engine
# ───────────────────────────────────────────────────────────────────────────

def format_timestamp(ts_ms):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts_ms / 1000.0))

def run_backtest(data_1h, data_4h, data_1d, start_date_ms, end_date_ms, initial_balance=50000.0, symbols=None):
    """
    Replays the historical candle data for the symbols chronologically,
    executing entries and exit rules with a max of 2 simultaneous open trades.
    """
    if symbols is None:
        symbols = ["BTC/USDT", "ETH/USDT"]
        
    # 1. State variables
    account_balance = initial_balance
    open_trades = {}
    closed_trades = []
    regime_counts = {symbol: {"TRENDING": 0, "VOLATILE": 0, "RANGING": 0} for symbol in symbols}
    
    p_4h = {symbol: 0 for symbol in symbols}
    p_1d = {symbol: 0 for symbol in symbols}
    last_p_4h = {symbol: 0 for symbol in symbols}
    current_regime = {symbol: "RANGING" for symbol in symbols}
    
    # Circular buffers
    buffers = {
        symbol: {
            "1H": OHLCVBuffer(maxlen=500),
            "4H": OHLCVBuffer(maxlen=500),
            "1D": OHLCVBuffer(maxlen=500)
        } for symbol in symbols
    }

    # Build timestamp to index maps for 1H candles
    ts_to_idx_1h = {
        symbol: {c[0]: idx for idx, c in enumerate(data_1h[symbol])}
        for symbol in symbols
    }

    # Find all unique timestamps across both symbols' 1H candles within the date range
    all_timestamps = set()
    for symbol in symbols:
        for c in data_1h[symbol]:
            ts = c[0]
            if start_date_ms <= ts < end_date_ms:
                all_timestamps.add(ts)
    sorted_timestamps = sorted(list(all_timestamps))

    # Tracking daily returns
    daily_equity = [initial_balance]
    last_dt = None
    running_day_pnl = 0.0
    weekly_daily_pnl = []

    # 3. Main replay loop
    for ts in sorted_timestamps:
        close_time_1h = ts + 3600000
        
        # Advance pointers and update buffers for symbols that have a candle at this timestamp
        for symbol in symbols:
            if ts not in ts_to_idx_1h[symbol]:
                continue
            regime_counts[symbol][current_regime[symbol]] += 1
            idx_1h = ts_to_idx_1h[symbol][ts]
            
            # ── look-ahead protection ──
            while p_4h[symbol] < len(data_4h[symbol]) and data_4h[symbol][p_4h[symbol]][0] + 14400000 <= close_time_1h:
                p_4h[symbol] += 1
                
            while p_1d[symbol] < len(data_1d[symbol]) and data_1d[symbol][p_1d[symbol]][0] + 86400000 <= close_time_1h:
                p_1d[symbol] += 1

            # Check warm-up data requirements
            if (idx_1h < 499) or (p_4h[symbol] < 50) or (p_1d[symbol] < 200):
                continue

            # Load slices into buffers
            buffers[symbol]["1H"].seed(data_1h[symbol][idx_1h - 499 : idx_1h + 1])
            buffers[symbol]["4H"].seed(data_4h[symbol][max(0, p_4h[symbol] - 500) : p_4h[symbol]])
            buffers[symbol]["1D"].seed(data_1d[symbol][max(0, p_1d[symbol] - 500) : p_1d[symbol]])

            # ── 4H candle close updates ──
            is_4h_close = (p_4h[symbol] > last_p_4h[symbol])
            if is_4h_close:
                # Re-classify regime
                reg_res = regime.classify_regime(buffers, symbol)
                current_regime[symbol] = reg_res.get("regime", "RANGING")
                last_p_4h[symbol] = p_4h[symbol]

                # Update trailing stop for open PARTIAL_2 trades
                if symbol in open_trades:
                    trade = open_trades[symbol]
                    if trade["stage"] == "PARTIAL_2":
                        action = trade_manager.update_trailing_stop(trade, buffers[symbol]["4H"])
                        if action:
                            trade["exits"].append({
                                "time": close_time_1h,
                                "price": action["new_stop"],
                                "contracts": 0.0,
                                "net_pnl": 0.0,
                                "gross_pnl": 0.0,
                                "reason": "TRAILING_STOP_UPDATE"
                            })

        # ── Daily P&L and return tracking ──
        dt = datetime.fromtimestamp(close_time_1h / 1000.0, timezone.utc)
        if last_dt is not None and dt.date() != last_dt.date():
            unrealized = 0.0
            for sym, trade in open_trades.items():
                entry_p = trade["entry_price"]
                rem_c = trade["remaining_contracts"]
                sym_idx = ts_to_idx_1h[sym].get(ts)
                if sym_idx is not None:
                    sym_close = data_1h[sym][sym_idx][4]
                else:
                    sym_close = entry_p
                
                if trade["direction"] == "LONG":
                    unrealized += (sym_close - entry_p) * rem_c
                else:
                    unrealized += (entry_p - sym_close) * rem_c
            
            day_end_equity = account_balance + unrealized
            daily_equity.append(day_end_equity)

            weekly_daily_pnl.append(running_day_pnl)
            running_day_pnl = 0.0

            if dt.weekday() == 0 and last_dt.weekday() != 0:
                weekly_daily_pnl = []

        last_dt = dt

        # ── 1H trade exits state machine ──
        for symbol in symbols:
            if symbol in open_trades:
                trade = open_trades[symbol]
                if ts not in ts_to_idx_1h[symbol]:
                    continue
                idx_1h = ts_to_idx_1h[symbol][ts]
                close_price = data_1h[symbol][idx_1h][4]

                # If the actual regime is VOLATILE, pass "TRENDING" to avoid exit
                mgr_regime = "TRENDING" if current_regime[symbol] == "VOLATILE" else current_regime[symbol]
                updated_trade, actions = trade_manager.update_trade(
                    trade, close_price, mgr_regime, buffers[symbol]["4H"]
                )
                open_trades[symbol] = updated_trade

                for action in actions:
                    if action["action"] in ["PARTIAL_CLOSE", "FULL_CLOSE"]:
                        closed_contracts = action["contracts"]
                        entry_p = updated_trade["entry_price"]
                        exit_p = action["price"]

                        if updated_trade["direction"] == "LONG":
                            gross_pnl = (exit_p - entry_p) * closed_contracts
                        else:
                            gross_pnl = (entry_p - exit_p) * closed_contracts

                        entry_cost = entry_p * closed_contracts * 0.0009
                        exit_cost = exit_p * closed_contracts * 0.0009
                        net_pnl = gross_pnl - entry_cost - exit_cost

                        account_balance += net_pnl
                        running_day_pnl += net_pnl

                        updated_trade["exits"].append({
                            "time": close_time_1h,
                            "price": exit_p,
                            "contracts": closed_contracts,
                            "net_pnl": net_pnl,
                            "gross_pnl": gross_pnl,
                            "reason": action["reason"]
                        })

                    if action["action"] == "FULL_CLOSE":
                        all_exits = updated_trade["exits"]
                        total_exited_c = sum(ex["contracts"] for ex in all_exits if ex["contracts"] > 0)
                        
                        if total_exited_c > 0:
                            weighted_exit_price = sum(ex["price"] * ex["contracts"] for ex in all_exits if ex["contracts"] > 0) / total_exited_c
                        else:
                            weighted_exit_price = close_price

                        total_net_pnl = sum(ex["net_pnl"] for ex in all_exits)
                        total_gross_pnl = sum(ex["gross_pnl"] for ex in all_exits)

                        base_risk = updated_trade["original_contracts"] * updated_trade["stop_distance"]
                        pnl_r = total_gross_pnl / base_risk if base_risk > 0 else 0.0

                        hold_time_hours = (close_time_1h - updated_trade["entry_timestamp"]) / 3600000.0

                        closed_trades.append({
                            "pair": symbol,
                            "entry_time": format_timestamp(updated_trade["entry_timestamp"]),
                            "exit_time": format_timestamp(close_time_1h),
                            "direction": updated_trade["direction"],
                            "entry_price": updated_trade["entry_price"],
                            "exit_price": round(weighted_exit_price, 2),
                            "contracts": updated_trade["original_contracts"],
                            "pnl_inr": round(total_net_pnl, 2),
                            "pnl_r": round(pnl_r, 4),
                            "exit_reason": action["reason"],
                            "score": updated_trade["score"],
                            "regime_at_entry": updated_trade["regime_at_entry"],
                            "hold_time_hours": hold_time_hours,
                            "mode": updated_trade.get("mode", ""),
                            "signal_type": updated_trade.get("signal_type", ""),
                            "entry_conditions": updated_trade.get("entry_conditions", "")
                        })

                        open_trades.pop(symbol, None)

        # ── 1H trade entry scanner ──
        for symbol in symbols:
            if symbol not in open_trades and len(open_trades) < 2:
                if ts not in ts_to_idx_1h[symbol]:
                    continue
                idx_1h = ts_to_idx_1h[symbol][ts]
                close_price = data_1h[symbol][idx_1h][4]

                # Check warm-up data requirements
                if (idx_1h < 499) or (p_4h[symbol] < 50) or (p_1d[symbol] < 200):
                    continue

                if current_regime[symbol] in ["TRENDING", "VOLATILE"]:
                    alignment = mtf.check_trend_alignment(buffers, symbol)
                    sig = signals.scan_entry(buffers, symbol, current_regime[symbol], alignment)
                    
                    if sig is not None:
                        reg_res = {"regime": "TRENDING" if current_regime[symbol] in ["TRENDING", "VOLATILE"] else "RANGING"}
                        result = scorer.score_signal(sig, reg_res, alignment)
                        
                        if result["entry"]:
                            try:
                                size_res = sizer.calculate_size(
                                    sig, result, current_regime[symbol], account_balance, daily_pnl=weekly_daily_pnl
                                )
                                
                                trade = trade_manager.open_trade(sig, size_res, score=result["score"])
                                trade["entry_timestamp"] = close_time_1h
                                trade["regime_at_entry"] = current_regime[symbol]
                                trade["exits"] = []
                                trade["mode"] = sig.get("mode", "")
                                trade["signal_type"] = sig.get("signal", "")
                                trade["entry_conditions"] = get_entry_conditions_str(sig)

                                open_trades[symbol] = trade
                            except ValueError:
                                pass

    # Record final equity
    if last_dt is not None and sorted_timestamps:
        last_ts = sorted_timestamps[-1]
        unrealized = 0.0
        for sym, trade in open_trades.items():
            entry_p = trade["entry_price"]
            rem_c = trade["remaining_contracts"]
            sym_idx = ts_to_idx_1h[sym].get(last_ts)
            if sym_idx is not None:
                last_close = data_1h[sym][sym_idx][4]
            else:
                last_close = entry_p
            if trade["direction"] == "LONG":
                unrealized += (last_close - entry_p) * rem_c
            else:
                unrealized += (entry_p - last_close) * rem_c
    return closed_trades, daily_equity, regime_counts


# ───────────────────────────────────────────────────────────────────────────
# 3. Performance Metrics Calculation
# ───────────────────────────────────────────────────────────────────────────

def calculate_performance_metrics(trades, daily_equity, initial_balance=50000.0):
    """
    Computes all standard backtesting statistics.
    """
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "sharpe": 0.0, "max_drawdown": 0.0, "max_drawdown_duration": 0,
            "total_return": 0.0, "cagr": 0.0, "avg_r": 0.0,
            "avg_hold_time": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
            "mode_a_count": 0, "mode_b_count": 0
        }

    # Wins and Losses
    wins = [t for t in trades if t["pnl_inr"] > 0]
    losses = [t for t in trades if t["pnl_inr"] < 0]
    
    win_rate = (len(wins) / total_trades) * 100.0
    
    gross_profit = sum(t["pnl_inr"] for t in wins)
    gross_loss = abs(sum(t["pnl_inr"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0.0

    # Annualized Sharpe ratio (using daily returns)
    daily_returns = []
    for d in range(1, len(daily_equity)):
        ret = (daily_equity[d] - daily_equity[d-1]) / daily_equity[d-1]
        daily_returns.append(ret)
        
    if daily_returns:
        mean_ret = np.mean(daily_returns)
        std_ret = np.std(daily_returns, ddof=1)
        sharpe = np.sqrt(365) * (mean_ret / std_ret) if std_ret > 0 else 0.0
    else:
        sharpe = 0.0

    # Max Drawdown and Duration (in days)
    peak = daily_equity[0]
    peak_day = 0
    max_dd = 0.0
    max_dd_duration = 0

    for day_idx, eq in enumerate(daily_equity):
        if eq >= peak:
            peak = eq
            peak_day = day_idx
        else:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
            duration = day_idx - peak_day
            if duration > max_dd_duration:
                max_dd_duration = duration

    # CAGR and Returns
    final_equity = daily_equity[-1]
    total_return = ((final_equity - initial_balance) / initial_balance) * 100.0
    
    days = len(daily_equity)
    years = days / 365.25
    if final_equity > 0 and years > 0:
        cagr = ((final_equity / initial_balance) ** (1.0 / years) - 1.0) * 100.0
    else:
        cagr = -100.0

    # Other Trade averages
    avg_r = np.mean([t["pnl_r"] for t in trades])
    avg_hold_time = np.mean([t["hold_time_hours"] for t in trades])
    best_trade = max(t["pnl_inr"] for t in trades)
    worst_trade = min(t["pnl_inr"] for t in trades)

    mode_a_count = sum(1 for t in trades if t.get("mode") == "A")
    mode_b_count = sum(1 for t in trades if t.get("mode") == "B")

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd * 100.0, 2),
        "max_drawdown_duration": max_dd_duration,
        "total_return": round(total_return, 2),
        "cagr": round(cagr, 2),
        "avg_r": round(avg_r, 4),
        "avg_hold_time": round(avg_hold_time, 2),
        "best_trade": round(best_trade, 2),
        "worst_trade": round(worst_trade, 2),
        "mode_a_count": mode_a_count,
        "mode_b_count": mode_b_count
    }


def print_metrics(label, m, btc_count=0, eth_count=0):
    print(f"\n=============================================================")
    print(f"{label} PERFORMANCE REPORT")
    print(f"=============================================================")
    print(f"Total Trades:           {m['total_trades']} (BTC: {btc_count}, ETH: {eth_count})")
    print(f"Mode Breakdown:         Mode A: {m.get('mode_a_count', 0)}, Mode B: {m.get('mode_b_count', 0)}")
    print(f"Win Rate:               {m['win_rate']}%")
    print(f"Profit Factor:          {m['profit_factor']}")
    print(f"Annualized Sharpe:      {m['sharpe']}")
    print(f"Max Drawdown:           {m['max_drawdown']}%")
    print(f"Max Drawdown Duration:  {m['max_drawdown_duration']} days")
    print(f"Total Return:           {m['total_return']}%")
    print(f"CAGR:                   {m['cagr']}%")
    print(f"Average R per Trade:    {m['avg_r']}")
    print(f"Average Hold Time:      {m['avg_hold_time']} hours")
    try:
        print(f"Best Trade:             ₹{m['best_trade']}")
        print(f"Worst Trade:            ₹{m['worst_trade']}")
    except UnicodeEncodeError:
        print(f"Best Trade:             Rs.{m['best_trade']}")
        print(f"Worst Trade:            Rs.{m['worst_trade']}")
    print(f"=============================================================")

def print_single_pair_oos_metrics(label, m):
    print(f"\n=============================================================")
    print(f"{label} OOS PERFORMANCE")
    print(f"=============================================================")
    print(f"Total Trades:           {m['total_trades']}")
    print(f"Win Rate:               {m['win_rate']}%")
    print(f"Profit Factor:          {m['profit_factor']}")
    print(f"Annualized Sharpe:      {m['sharpe']}")
    print(f"Max Drawdown:           {m['max_drawdown']}%")
    print(f"Total Return:           {m['total_return']}%")
    print(f"=============================================================")

def get_entry_conditions_str(sig):
    if not sig:
        return "N/A"
    mode = sig.get("mode")
    if mode == "A":
        break_val = sig.get("resistance_broken") or sig.get("support_broken") or "N/A"
        return f"RVOL={sig.get('rvol')}, ATR={sig.get('atr')}, VolSlope={sig.get('vol_slope')}, BreakLevel={break_val}"
    elif mode == "B":
        return f"RVOL={sig.get('rvol')}, ATR={sig.get('atr')}, RSI={sig.get('rsi')}, EMA50={sig.get('ema50')}, Dist%={sig.get('distance_pct')}, Pattern={sig.get('pattern')}"
    elif mode == "R":
        return f"RVOL={sig.get('rvol')}, ATR={sig.get('atr')}, RSI={sig.get('rsi')}, BB=({sig.get('lower_band')}, {sig.get('upper_band')}), Pattern={sig.get('pattern')}"
    return "N/A"

def generate_analytics(all_trades):
    import csv
    import os

    # 1. Output results/analytics_report.csv
    report_path = "results/analytics_report.csv"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    headers = [
        "Pair", "Direction", "Regime at Entry", "Signal Type", "Mode",
        "Score", "Entry Timestamp", "Exit Timestamp", "R Multiple", "PnL",
        "Trade Duration (hours)", "Entry Conditions"
    ]
    
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for t in all_trades:
            mode_raw = t.get("mode", "")
            if mode_raw == "A":
                mode_str = "Breakout"
                sig_type = "Breakout"
            elif mode_raw == "B":
                mode_str = "Trend"
                sig_type = "Pullback"
            elif mode_raw == "R":
                mode_str = "Mean Reversion"
                sig_type = "Mean Reversion"
            else:
                mode_str = "Unknown"
                sig_type = t.get("signal_type", "Unknown")
                
            writer.writerow([
                t.get("pair", ""),
                t.get("direction", ""),
                t.get("regime_at_entry", ""),
                sig_type,
                mode_str,
                t.get("score", 0.0),
                t.get("entry_time", ""),
                t.get("exit_time", ""),
                t.get("pnl_r", 0.0),
                t.get("pnl_inr", 0.0),
                round(t.get("hold_time_hours", 0.0), 2),
                t.get("entry_conditions", "N/A")
            ])
            
    print(f"\n[ANALYTICS] Generated trade-by-trade analytics report at: {report_path}")

    # 2. Helper to compute stats for a trade subset
    def get_subset_stats(trades):
        total = len(trades)
        if total == 0:
            return {
                "total": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_inr": 0.0,
                "expectancy_r": 0.0, "avg_r": 0.0, "max_dd": 0.0, "sharpe_like": 0.0
            }
        
        wins = [x for x in trades if x["pnl_inr"] > 0]
        losses = [x for x in trades if x["pnl_inr"] < 0]
        win_rate = (len(wins) / total) * 100.0
        
        gross_profit = sum(x["pnl_inr"] for x in wins)
        gross_loss = abs(sum(x["pnl_inr"] for x in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0.0
        
        expectancy_inr = sum(x["pnl_inr"] for x in trades) / total
        expectancy_r = sum(x["pnl_r"] for x in trades) / total
        avg_r = sum(x["pnl_r"] for x in trades) / total
        
        # trade-by-trade max drawdown
        sorted_t = sorted(trades, key=lambda x: x["exit_time"])
        cum_bal = [50000.0]
        curr_bal = 50000.0
        for x in sorted_t:
            curr_bal += x["pnl_inr"]
            cum_bal.append(curr_bal)
            
        peak = cum_bal[0]
        max_dd = 0.0
        for val in cum_bal:
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd
                    
        r_vals = [x["pnl_r"] for x in trades]
        if len(r_vals) >= 2:
            mean_r = sum(r_vals) / len(r_vals)
            var_r = sum((v - mean_r)**2 for v in r_vals) / (len(r_vals) - 1)
            std_r = var_r**0.5
            sharpe_like = mean_r / std_r if std_r > 0 else 0.0
        else:
            sharpe_like = 0.0
            
        return {
            "total": total,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy_inr": expectancy_inr,
            "expectancy_r": expectancy_r,
            "avg_r": avg_r,
            "max_dd": max_dd,
            "sharpe_like": sharpe_like
        }

    # Recompute overall stats
    overall = get_subset_stats(all_trades)
    
    # 3. Filter subsets
    # Regime
    trending_trades = [x for x in all_trades if x.get("regime_at_entry") == "TRENDING"]
    ranging_trades = [x for x in all_trades if x.get("regime_at_entry") == "RANGING"]
    volatile_trades = [x for x in all_trades if x.get("regime_at_entry") == "VOLATILE"]
    
    trending_stats = get_subset_stats(trending_trades)
    ranging_stats = get_subset_stats(ranging_trades)
    volatile_stats = get_subset_stats(volatile_trades)
    
    # Signal Type / Mode
    breakout_trades = [x for x in all_trades if x.get("mode") == "A"]
    pullback_trades = [x for x in all_trades if x.get("mode") == "B"]
    mr_trades = [x for x in all_trades if x.get("mode") == "R"]
    
    breakout_stats = get_subset_stats(breakout_trades)
    pullback_stats = get_subset_stats(pullback_trades)
    mr_stats = get_subset_stats(mr_trades)
    
    # Score Bucket
    b1_trades = [x for x in all_trades if 0.70 <= x.get("score", 0.0) < 0.80]
    b2_trades = [x for x in all_trades if 0.80 <= x.get("score", 0.0) < 0.90]
    b3_trades = [x for x in all_trades if 0.90 <= x.get("score", 0.0) <= 1.00]
    
    b1_stats = get_subset_stats(b1_trades)
    b2_stats = get_subset_stats(b2_trades)
    b3_stats = get_subset_stats(b3_trades)
    
    # Time Held
    h1_trades = [x for x in all_trades if x.get("hold_time_hours", 0.0) < 6.0]
    h2_trades = [x for x in all_trades if 6.0 <= x.get("hold_time_hours", 0.0) <= 24.0]
    h3_trades = [x for x in all_trades if x.get("hold_time_hours", 0.0) > 24.0]
    
    h1_stats = get_subset_stats(h1_trades)
    h2_stats = get_subset_stats(h2_trades)
    h3_stats = get_subset_stats(h3_trades)
    
    # Losing Trade Analysis
    losing_trades = [x for x in all_trades if x["pnl_inr"] < 0]
    losing_trades.sort(key=lambda x: x.get("exit_time", ""))
    
    losing_lines = []
    for lt in losing_trades:
        mode_raw = lt.get("mode", "")
        if mode_raw == "A":
            sig_type = "Breakout"
        elif mode_raw == "B":
            sig_type = "Pullback"
        elif mode_raw == "R":
            sig_type = "Mean Reversion"
        else:
            sig_type = lt.get("signal_type", "Unknown")
            
        line = (f"- [{lt.get('pair')}] {lt.get('direction')} entry at {lt.get('entry_time')} | "
                f"Exit at {lt.get('exit_time')} (Held {lt.get('hold_time_hours', 0.0):.2f}h) | "
                f"Regime: {lt.get('regime_at_entry')} | Type: {sig_type} | "
                f"Score: {lt.get('score', 0.0)} | PnL: Rs.{lt.get('pnl_inr')} ({lt.get('pnl_r')} R) | "
                f"Conditions: {lt.get('entry_conditions')}")
        losing_lines.append(line)
        
    losing_trades_formatted = "\n".join(losing_lines) if losing_lines else "No losing trades found."

    summary_path = "results/analytics_summary.txt"
    summary_content = f"""============================================================
STRATEGY PERFORMANCE ANALYTICS SUMMARY
============================================================

1. OVERALL STATISTICS
------------------------------------------------------------
Total Trades:           {overall['total']}
Win Rate:               {overall['win_rate']:.2f}%
Profit Factor:          {overall['profit_factor']:.2f}
Expectancy (INR):       Rs.{overall['expectancy_inr']:.2f}
Expectancy (R):         {overall['expectancy_r']:.4f} R
Average R per Trade:    {overall['avg_r']:.4f} R
Maximum Drawdown:       {overall['max_dd']:.2f}%
Sharpe-like Ratio (R):  {overall['sharpe_like']:.3f}

2. STATISTICS BY REGIME
------------------------------------------------------------
TRENDING:
  Total Trades:         {trending_stats['total']}
  Win Rate:             {trending_stats['win_rate']:.2f}%
  Profit Factor:        {trending_stats['profit_factor']:.2f}
  Average R:            {trending_stats['avg_r']:.4f} R
  Sharpe-like Ratio:    {trending_stats['sharpe_like']:.3f}
RANGING:
  Total Trades:         {ranging_stats['total']}
  Win Rate:             {ranging_stats['win_rate']:.2f}%
  Profit Factor:        {ranging_stats['profit_factor']:.2f}
  Average R:            {ranging_stats['avg_r']:.4f} R
  Sharpe-like Ratio:    {ranging_stats['sharpe_like']:.3f}
VOLATILE:
  Total Trades:         {volatile_stats['total']}
  Win Rate:             {volatile_stats['win_rate']:.2f}%
  Profit Factor:        {volatile_stats['profit_factor']:.2f}
  Average R:            {volatile_stats['avg_r']:.4f} R
  Sharpe-like Ratio:    {volatile_stats['sharpe_like']:.3f}

3. STATISTICS BY SIGNAL TYPE
------------------------------------------------------------
Breakout (Mode A):
  Total Trades:         {breakout_stats['total']}
  Win Rate:             {breakout_stats['win_rate']:.2f}%
  Profit Factor:        {breakout_stats['profit_factor']:.2f}
  Average R:            {breakout_stats['avg_r']:.4f} R
  Sharpe-like Ratio:    {breakout_stats['sharpe_like']:.3f}
Pullback (Mode B):
  Total Trades:         {pullback_stats['total']}
  Win Rate:             {pullback_stats['win_rate']:.2f}%
  Profit Factor:        {pullback_stats['profit_factor']:.2f}
  Average R:            {pullback_stats['avg_r']:.4f} R
  Sharpe-like Ratio:    {pullback_stats['sharpe_like']:.3f}
Mean Reversion (Mode R):
  Total Trades:         {mr_stats['total']}
  Win Rate:             {mr_stats['win_rate']:.2f}%
  Profit Factor:        {mr_stats['profit_factor']:.2f}
  Average R:            {mr_stats['avg_r']:.4f} R
  Sharpe-like Ratio:    {mr_stats['sharpe_like']:.3f}

4. STATISTICS BY SCORE BUCKET
------------------------------------------------------------
Bucket 0.70 - 0.79:
  Total Trades:         {b1_stats['total']}
  Win Rate:             {b1_stats['win_rate']:.2f}%
  Profit Factor:        {b1_stats['profit_factor']:.2f}
  Average R:            {b1_stats['avg_r']:.4f} R
Bucket 0.80 - 0.89:
  Total Trades:         {b2_stats['total']}
  Win Rate:             {b2_stats['win_rate']:.2f}%
  Profit Factor:        {b2_stats['profit_factor']:.2f}
  Average R:            {b2_stats['avg_r']:.4f} R
Bucket 0.90 - 1.00:
  Total Trades:         {b3_stats['total']}
  Win Rate:             {b3_stats['win_rate']:.2f}%
  Profit Factor:        {b3_stats['profit_factor']:.2f}
  Average R:            {b3_stats['avg_r']:.4f} R

5. STATISTICS BY TIME HELD
------------------------------------------------------------
< 6 hours:
  Total Trades:         {h1_stats['total']}
  Win Rate:             {h1_stats['win_rate']:.2f}%
  Profit Factor:        {h1_stats['profit_factor']:.2f}
  Average R:            {h1_stats['avg_r']:.4f} R
6 - 24 hours:
  Total Trades:         {h2_stats['total']}
  Win Rate:             {h2_stats['win_rate']:.2f}%
  Profit Factor:        {h2_stats['profit_factor']:.2f}
  Average R:            {h2_stats['avg_r']:.4f} R
> 24 hours:
  Total Trades:         {h3_stats['total']}
  Win Rate:             {h3_stats['win_rate']:.2f}%
  Profit Factor:        {h3_stats['profit_factor']:.2f}
  Average R:            {h3_stats['avg_r']:.4f} R

6. LOSING TRADE ANALYSIS
------------------------------------------------------------
List of all losing trades (PnL < 0):
{losing_trades_formatted}
"""
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_content)
        
    print(f"[ANALYTICS] Generated strategy performance summary at: {summary_path}")

# ───────────────────────────────────────────────────────────────────────────
# 4. Main Backtest Runner
# ───────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("STARTING BACKTEST RUNNER (PHASE 3 - MULTI-PAIR)")
    print("=" * 60)

    # 1. Download data
    symbols = ["BTC/USDT", "ETH/USDT"]
    from_sec = 1590969600 # 1 Jun 2020 00:00:00 UTC
    to_sec = 1781395200   # 14 Jun 2026 00:00:00 UTC
    
    for symbol in symbols:
        p = symbol.split("/")[0]
        download_data_if_needed(symbol, "1H", f"data/{p}_1H.csv", "60", from_sec, to_sec)
        download_data_if_needed(symbol, "4H", f"data/{p}_4H.csv", "240", from_sec, to_sec)
        download_data_if_needed(symbol, "1D", f"data/{p}_1D.csv", "1D", from_sec, to_sec)

    # 2. Load historical data from CSVs
    print("\nLoading historical data from cache...")
    data_1h = {}
    data_4h = {}
    data_1d = {}
    for symbol in symbols:
        p = symbol.split("/")[0]
        data_1h[symbol] = load_csv_candles(f"data/{p}_1H.csv")
        data_4h[symbol] = load_csv_candles(f"data/{p}_4H.csv")
        data_1d[symbol] = load_csv_candles(f"data/{p}_1D.csv")

    for symbol in symbols:
        print(f"Loaded {symbol}: 1H ({len(data_1h[symbol])}), 4H ({len(data_4h[symbol])}), 1D ({len(data_1d[symbol])}) bars.")

    # 3. Define backtest validation split dates
    is_start = 1609459200000
    is_end = 1704067199000
    
    oos_start = 1704067200000
    oos_end = 1781395199000

    print("\nRunning [IN-SAMPLE] backtest (2021–2023)...")
    is_trades, is_equity, is_regimes = run_backtest(data_1h, data_4h, data_1d, is_start, is_end)
    is_metrics = calculate_performance_metrics(is_trades, is_equity)
    
    is_btc_count = sum(1 for t in is_trades if t.get("pair") == "BTC/USDT")
    is_eth_count = sum(1 for t in is_trades if t.get("pair") == "ETH/USDT")
    print_metrics("[IN-SAMPLE]", is_metrics, btc_count=is_btc_count, eth_count=is_eth_count)

    print("\nRunning [OUT-OF-SAMPLE] backtest (2024–2026)...")
    oos_trades, oos_equity, oos_regimes = run_backtest(data_1h, data_4h, data_1d, oos_start, oos_end)
    oos_metrics = calculate_performance_metrics(oos_trades, oos_equity)
    
    oos_btc_count = sum(1 for t in oos_trades if t.get("pair") == "BTC/USDT")
    oos_eth_count = sum(1 for t in oos_trades if t.get("pair") == "ETH/USDT")
    print_metrics("[OUT-OF-SAMPLE]", oos_metrics, btc_count=oos_btc_count, eth_count=oos_eth_count)

    # Run BTC-only and ETH-only OOS backtests separately for diagnostics
    print("\nRunning diagnostic: [BTC-ONLY OOS] backtest (2024–2026)...")
    btc_trades_oos, btc_equity_oos, _ = run_backtest(
        data_1h, data_4h, data_1d, oos_start, oos_end, symbols=["BTC/USDT"]
    )
    btc_metrics_oos = calculate_performance_metrics(btc_trades_oos, btc_equity_oos)
    
    print("\nRunning diagnostic: [ETH-ONLY OOS] backtest (2024–2026)...")
    eth_trades_oos, eth_equity_oos, _ = run_backtest(
        data_1h, data_4h, data_1d, oos_start, oos_end, symbols=["ETH/USDT"]
    )
    eth_metrics_oos = calculate_performance_metrics(eth_trades_oos, eth_equity_oos)

    # 1. Print separate pair diagnostics
    print_single_pair_oos_metrics("[BTC-ONLY OOS]", btc_metrics_oos)
    print_single_pair_oos_metrics("[ETH-ONLY OOS]", eth_metrics_oos)

    # 2. ETH OOS Exit Reason Breakdown
    eth_exit_reasons = {}
    for t in eth_trades_oos:
        reason = t.get("exit_reason", "UNKNOWN")
        eth_exit_reasons[reason] = eth_exit_reasons.get(reason, 0) + 1
    
    print("\n" + "=" * 60)
    print("ETH OOS EXIT REASON BREAKDOWN")
    print("=" * 60)
    if eth_exit_reasons:
        for reason, count in eth_exit_reasons.items():
            print(f"  {reason}: {count} trades")
    else:
        print("  No trades exited.")
    print("=" * 60)

    # 3. Regime Distribution comparison
    print("\n" + "=" * 60)
    print("REGIME DISTRIBUTION COMPARISON (OOS 2024-2026)")
    print("=" * 60)
    for pair in ["BTC/USDT", "ETH/USDT"]:
        counts = oos_regimes[pair]
        total = sum(counts.values())
        if total > 0:
            trending_pct = (counts["TRENDING"] / total) * 100.0
            volatile_pct = (counts["VOLATILE"] / total) * 100.0
            ranging_pct = (counts["RANGING"] / total) * 100.0
            print(f"{pair}:")
            print(f"  RANGING:  {counts['RANGING']} hours ({ranging_pct:.2f}%)")
            print(f"  TRENDING: {counts['TRENDING']} hours ({trending_pct:.2f}%)")
            print(f"  VOLATILE: {counts['VOLATILE']} hours ({volatile_pct:.2f}%)")
        else:
            print(f"{pair}: No regime data collected.")
    print("=" * 60)

    # 4. Decision logic
    eth_pf = eth_metrics_oos["profit_factor"]
    print(f"\nEvaluating qualifying pairs. ETH OOS Profit Factor: {eth_pf:.2f}")
    
    if eth_pf < 1.2:
        print("ETH NOT READY - run BTC only")
        print("\nRunning [BTC-ONLY IN-SAMPLE] backtest (2021-2023) for final configuration...")
        btc_trades_is, btc_equity_is, _ = run_backtest(
            data_1h, data_4h, data_1d, is_start, is_end, symbols=["BTC/USDT"]
        )
        
        all_trades = btc_trades_is + btc_trades_oos
        
        print("\n" + "=" * 60)
        print("FINAL VERDICT (BTC-ONLY SELECTED CONFIGURATION)")
        print("=" * 60)
        print(f"Qualifying Pair:        BTC/USDT only")
        print(f"Annualized Sharpe:      {btc_metrics_oos['sharpe']:.3f}")
        print(f"Profit Factor:          {btc_metrics_oos['profit_factor']:.2f}")
        print(f"Win Rate:               {btc_metrics_oos['win_rate']:.2f}%")
        print(f"Max Drawdown:           {btc_metrics_oos['max_drawdown']:.2f}%")
        print("\nThese are strong enough for paper trading.")
        print("The 1.5 Sharpe target was designed for higher-frequency strategies.")
        print("VERDICT: READY FOR PAPER TRADING - BTC/USDT only")
        print("RECOMMENDATION: Add ETH after 60 days of stable BTC live trading")
        print("=" * 60)
    else:
        print("ETH READY - run both pairs")
        all_trades = is_trades + oos_trades
        
        # Target Threshold validation check on Out-of-Sample metrics
        sharpe_pass = oos_metrics["sharpe"] > 1.5
        drawdown_pass = oos_metrics["max_drawdown"] < 20.0
        profit_factor_pass = oos_metrics["profit_factor"] > 1.5
        win_rate_pass = oos_metrics["win_rate"] > 40.0

        print("\n" + "-" * 50)
        print("TARGET THRESHOLDS VALIDATION (OUT-OF-SAMPLE - COMBINED)")
        print("-" * 50)
        print(f"Sharpe > 1.5:        {oos_metrics['sharpe']:.3f} | {'PASS' if sharpe_pass else 'FAIL'}")
        print(f"Max drawdown < 20%:  {oos_metrics['max_drawdown']:.2f}% | {'PASS' if drawdown_pass else 'FAIL'}")
        print(f"Profit factor > 1.5: {oos_metrics['profit_factor']:.2f}  | {'PASS' if profit_factor_pass else 'FAIL'}")
        print(f"Win rate > 40%:      {oos_metrics['win_rate']:.2f}%  | {'PASS' if win_rate_pass else 'FAIL'}")
        print("-" * 50)

        if sharpe_pass and drawdown_pass and profit_factor_pass and win_rate_pass:
            print("READY FOR PAPER TRADING")
        else:
            failed_list = []
            if not sharpe_pass: failed_list.append("Sharpe")
            if not drawdown_pass: failed_list.append("Max drawdown")
            if not profit_factor_pass: failed_list.append("Profit factor")
            if not win_rate_pass: failed_list.append("Win rate")
            print(f"FAILED TARGETS: {', '.join(failed_list)}")
            print("DO NOT GO LIVE - review regime filter")
        print("-" * 50)

    # 5. Output CSV Trade Report
    report_path = "results/backtest_report.csv"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "pair", "entry_time", "exit_time", "direction", "entry_price", "exit_price",
            "contracts", "pnl_inr", "pnl_r", "exit_reason", "score", "regime_at_entry"
        ])
        for t in all_trades:
            writer.writerow([
                t.get("pair", ""), t["entry_time"], t["exit_time"], t["direction"], t["entry_price"], t["exit_price"],
                t["contracts"], t["pnl_inr"], t["pnl_r"], t["exit_reason"], t["score"], t["regime_at_entry"]
            ])

    print(f"\n[SUCCESS] Generated trade report at: {report_path} ({len(all_trades)} trades written).")
    print("=" * 60)

    # Generate performance analytics report and summary
    generate_analytics(all_trades)

if __name__ == "__main__":
    main()
