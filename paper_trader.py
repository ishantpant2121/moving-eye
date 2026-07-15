# paper_trader.py
"""
Paper Trading Module — Phase 4
================================
Runs the full strategy pipeline against LIVE CoinDCX market data.
No real orders are placed. Everything is simulated in memory.

Components:
  1. PaperPortfolio  — virtual balance, P&L, drawdown tracking
  2. CircuitBreaker   — R2 risk rules (-2% daily, -5% weekly, -10% monthly)
  3. PaperTrader      — main engine: WebSocket → pipeline → simulated fills

Slippage Model:
  - Entry / non-stop exits: 0.05% adverse slippage applied to fill price
  - Stop exits (HARD_STOP, TRAILING_STOP): fill at stop price (gap-capped by trade_manager)
  - 0.04% fee on every fill (entry + each partial/full exit)

Logging:
  - logs/paper_trades.csv  — closed-trade record (same columns as backtest report)
  - logs/paper_log.txt     — timestamped pipeline log (every candle, regime, entry, exit)
"""

import os
import sys
import csv
import time
import threading
from datetime import datetime, timezone, timedelta

# ── Local project imports ────────────────────────────────────
import config
from exchange import coindcx
from buffer import OHLCVBuffer
from websocket_client import CoinDCXWebSocketClient
import regime
import mtf
import signals
import scorer
import sizer
import trade_manager
from telegram_bot import TelegramBot

# ================================================
# PAPER TRADING MODE — NO REAL ORDERS PLACED
# To switch to live trading, set LIVE_MODE = True
# and add your CoinDCX API credentials below
# ================================================
LIVE_MODE = False
COINDCX_API_KEY = "PASTE_YOUR_KEY_HERE"
COINDCX_SECRET  = "PASTE_YOUR_SECRET_HERE"
TELEGRAM_BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID   = "PASTE_YOUR_CHAT_ID_HERE"


# ── Force UTF-8 stdout on Windows ────────────────────────────
# cp1252 can't encode ₹ or → — this prevents UnicodeEncodeError.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Constants ────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

INITIAL_BALANCE = 50000.0   # INR
SLIPPAGE_PCT    = 0.0005    # 0.05 %
FEE_PCT         = 0.0004    # 0.04 %

TRADE_LOG_PATH   = "logs/paper_trades.csv"
PIPELINE_LOG_PATH = "logs/paper_log.txt"

TRADE_CSV_HEADER = [
    "pair", "entry_time", "exit_time", "direction", "entry_price",
    "exit_price", "contracts", "pnl_inr", "pnl_r", "exit_reason",
    "score", "regime_at_entry",
]


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _load_env(filepath=".env"):
    """Minimal .env loader — avoids the python-dotenv dependency."""
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())


def _apply_slippage(price: float, direction: str, is_entry: bool) -> float:
    """
    Apply 0.05 % adverse slippage to a fill price.
      Buying  (LONG entry / SHORT exit):  price goes UP   → worse for buyer
      Selling (SHORT entry / LONG exit):  price goes DOWN  → worse for seller
    """
    buying = (direction == "LONG") == is_entry  # True when we BUY
    if buying:
        return price * (1 + SLIPPAGE_PCT)
    return price * (1 - SLIPPAGE_PCT)


def _calc_fee(price: float, contracts: float) -> float:
    """0.04 % fee on notional value of a fill."""
    return abs(price * contracts) * FEE_PCT


def _now_ist() -> datetime:
    return datetime.now(IST)


def _ts_to_str(ts_ms: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts_ms / 1000.0))


# ─────────────────────────────────────────────────────────────
# PaperPortfolio
# ─────────────────────────────────────────────────────────────

class PaperPortfolio:
    """
    Virtual portfolio tracker.
    Balance changes only on realised P&L (same as the backtest engine).
    """

    def __init__(self, initial_balance: float = INITIAL_BALANCE):
        self.initial_balance   = initial_balance
        self.current_balance   = initial_balance
        self.peak_balance      = initial_balance

        self.open_trades: dict  = {}   # symbol → trade dict
        self.closed_trades: list = []

        # ── Intra-period P&L accumulators ────────────────────
        self.daily_pnl   = 0.0
        self.weekly_pnl  = 0.0
        self.trades_today = 0

        # ── Weekly Stats ─────────────────────────────────────
        self.weekly_signals_gen = 0
        self.weekly_signals_rej = 0
        self.weekly_trades_exec = 0
        self.weekly_rejections = {
            "regime": 0,
            "mtf": 0,
            "score": 0,
            "volume": 0
        }

        # ── Weekly daily P&L list (for sizer.calculate_weekly_drawdown) ──
        self.weekly_daily_pnl: list = []   # list[float]
        self._running_day_pnl  = 0.0

        # ── Period markers ───────────────────────────────────
        self.daily_start_balance   = initial_balance
        self.weekly_start_balance  = initial_balance
        self.monthly_start_balance = initial_balance

        self._last_date:  object = None   # date
        self._last_week:  int    = -1
        self._last_month: int    = -1

    def record_signal_gen(self):
        self.weekly_signals_gen += 1
        
    def record_rejection(self, reason):
        self.weekly_signals_rej += 1
        if reason in self.weekly_rejections:
            self.weekly_rejections[reason] += 1
            
    def record_trade_exec(self):
        self.weekly_trades_exec += 1
        
    def reset_weekly_stats(self):
        self.weekly_signals_gen = 0
        self.weekly_signals_rej = 0
        self.weekly_trades_exec = 0
        self.weekly_rejections = {
            "regime": 0,
            "mtf": 0,
            "score": 0,
            "volume": 0
        }

    # ── Derived metrics ──────────────────────────────────────
    def update_peak(self):
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

    def drawdown_pct(self) -> float:
        if self.peak_balance <= 0:
            return 0.0
        return (self.peak_balance - self.current_balance) / self.peak_balance * 100.0

    def daily_loss_pct(self) -> float:
        if self.daily_start_balance <= 0:
            return 0.0
        return (self.daily_start_balance - self.current_balance) / self.daily_start_balance * 100.0

    def weekly_loss_pct(self) -> float:
        if self.weekly_start_balance <= 0:
            return 0.0
        return (self.weekly_start_balance - self.current_balance) / self.weekly_start_balance * 100.0

    def monthly_loss_pct(self) -> float:
        if self.monthly_start_balance <= 0:
            return 0.0
        return (self.monthly_start_balance - self.current_balance) / self.monthly_start_balance * 100.0

    # ── Period resets ────────────────────────────────────────
    def check_resets(self, now: datetime):
        """Roll over daily / weekly / monthly accumulators as needed."""
        today  = now.date()
        week   = now.isocalendar()[1]
        month  = now.month

        # Daily
        if self._last_date is None or today != self._last_date:
            # Archive yesterday's PnL for sizer weekly-drawdown calc
            if self._last_date is not None:
                self.weekly_daily_pnl.append(self._running_day_pnl)
            self._running_day_pnl = 0.0
            self.daily_pnl = 0.0
            self.daily_start_balance = self.current_balance
            self.trades_today = 0
            self._last_date = today

        # Weekly (resets on Monday / new ISO week)
        if self._last_week < 0 or week != self._last_week:
            self.weekly_pnl = 0.0
            self.weekly_start_balance = self.current_balance
            self.weekly_daily_pnl = []
            self._last_week = week

        # Monthly
        if self._last_month < 0 or month != self._last_month:
            self.monthly_start_balance = self.current_balance
            self._last_month = month

    def record_pnl(self, amount: float):
        """Called after every realised fill."""
        self.current_balance  += amount
        self.daily_pnl        += amount
        self.weekly_pnl       += amount
        self._running_day_pnl += amount
        self.update_peak()


# ─────────────────────────────────────────────────────────────
# CircuitBreaker (R2 rules)
# ─────────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    -2 % daily  → pause entries for the rest of the day.
    -5 % weekly → halve all position sizes.
    -10 % monthly drawdown → pause all entries for rest of month.
    """

    def __init__(self):
        self.daily_paused   = False
        self.weekly_halved  = False
        self.monthly_paused = False

    def evaluate(self, portfolio: PaperPortfolio):
        """Returns (can_trade, size_multiplier, list[alerts])."""
        alerts: list = []

        # Monthly -10 %
        if portfolio.monthly_loss_pct() >= 10.0 and not self.monthly_paused:
            self.monthly_paused = True
            alerts.append(("MONTHLY_PAUSE",
                           f"Monthly drawdown {portfolio.monthly_loss_pct():.2f}% ≥ 10 %. ENTRIES PAUSED."))

        # Weekly -5 %
        if portfolio.weekly_loss_pct() >= 5.0 and not self.weekly_halved:
            self.weekly_halved = True
            alerts.append(("WEEKLY_HALVE",
                           f"Weekly loss {portfolio.weekly_loss_pct():.2f}% ≥ 5 %. Sizes HALVED."))

        # Daily -2 %
        if portfolio.daily_loss_pct() >= 2.0 and not self.daily_paused:
            self.daily_paused = True
            alerts.append(("DAILY_PAUSE",
                           f"Daily loss {portfolio.daily_loss_pct():.2f}% ≥ 2 %. Entries PAUSED today."))

        can_trade = not self.daily_paused and not self.monthly_paused
        size_mult = 0.5 if self.weekly_halved else 1.0
        return can_trade, size_mult, alerts

    # Called by portfolio.check_resets indirectly via the timer thread
    def reset_daily(self):
        self.daily_paused = False

    def reset_weekly(self):
        self.weekly_halved = False

    def reset_monthly(self):
        self.monthly_paused = False


# ─────────────────────────────────────────────────────────────
# PaperTrader — Main Engine
# ─────────────────────────────────────────────────────────────

class PaperTrader:
    """
    Runs the full pipeline live:
      seed buffers → WebSocket stream → on every closed candle:
        4H → regime classify + trailing-stop update
        1H → trade update → new entry scan (pipeline)
    """

    def __init__(self):
        _load_env()

        # ── Single-instance protection ──
        import socket
        try:
            # Bind to a high random port to ensure only one instance is active.
            # Python automatically cleans up the socket when the process exits.
            self._lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._lock_socket.bind(("127.0.0.1", 53905))
        except socket.error:
            print("\n[FATAL] Another instance of paper_trader.py is already running!")
            sys.exit(1)

        # Check live mode credentials if active
        if LIVE_MODE:
            api_key = COINDCX_API_KEY if COINDCX_API_KEY != "PASTE_YOUR_KEY_HERE" else os.environ.get("COINDCX_API_KEY", "")
            secret = COINDCX_SECRET if COINDCX_SECRET != "PASTE_YOUR_SECRET_HERE" else os.environ.get("COINDCX_SECRET", "")
            if not api_key or not secret:
                print("\n[FATAL] LIVE_MODE is set to True, but CoinDCX API credentials are not set!")
                print("Please update COINDCX_API_KEY and COINDCX_SECRET at the top of paper_trader.py.")
                sys.exit(1)
            print("\n[INFO] Running in LIVE TRADING MODE (using real credentials).")
        else:
            print("\n[INFO] Running in PAPER TRADING MODE (using public endpoints only).")

        self.portfolio = PaperPortfolio()
        self.circuit_breaker = CircuitBreaker()
        self.portfolio_lock = threading.Lock()
        self.state_lock = threading.Lock()

        # Telegram
        bot_token = TELEGRAM_BOT_TOKEN if TELEGRAM_BOT_TOKEN != "PASTE_YOUR_BOT_TOKEN_HERE" else os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID != "PASTE_YOUR_CHAT_ID_HERE" else os.environ.get("TELEGRAM_CHAT_ID", "")
        self.telegram = TelegramBot(bot_token, chat_id)

        # Buffers — same structure as main.py
        self.buffers: dict = {}
        for symbol in config.SYMBOLS:
            self.buffers[symbol] = {}
            for tf in config.TIMEFRAME_MAP:
                self.buffers[symbol][tf] = OHLCVBuffer(maxlen=config.BUFFER_MAX_SIZE)

        # Latest regime and ADX per symbol
        self.latest_regime: dict = {s: "RANGING" for s in config.SYMBOLS}
        self.latest_adx: dict = {s: 0.0 for s in config.SYMBOLS}
        self.regime_history: dict = {s: [(int(time.time() * 1000), "RANGING")] for s in config.SYMBOLS}

        # ── Logging ──────────────────────────────────────────
        os.makedirs("logs", exist_ok=True)
        self._ensure_trade_csv()

        # ── Validation: initialise audit CSV ─────────────────
        from validation.signal_auditor import initialise as _audit_init
        _audit_init()

        # Daily-summary tracking
        self._last_summary_date = None

        # Load state
        self.load_state()

    def save_state(self):
        """Serializes current portfolio, open trade states, and regime history to logs/portfolio_state.json."""
        import json
        with self.state_lock:
            state = {
                "current_balance": self.portfolio.current_balance,
                "peak_balance": self.portfolio.peak_balance,
                "daily_pnl": self.portfolio.daily_pnl,
                "weekly_pnl": self.portfolio.weekly_pnl,
                "trades_today": self.portfolio.trades_today,
                "weekly_signals_gen": self.portfolio.weekly_signals_gen,
                "weekly_signals_rej": self.portfolio.weekly_signals_rej,
                "weekly_trades_exec": self.portfolio.weekly_trades_exec,
                "weekly_rejections": self.portfolio.weekly_rejections,
                "weekly_daily_pnl": self.portfolio.weekly_daily_pnl,
                "_running_day_pnl": self.portfolio._running_day_pnl,
                "daily_start_balance": self.portfolio.daily_start_balance,
                "weekly_start_balance": self.portfolio.weekly_start_balance,
                "monthly_start_balance": self.portfolio.monthly_start_balance,
                "_last_date": self.portfolio._last_date.isoformat() if self.portfolio._last_date else None,
                "_last_week": self.portfolio._last_week,
                "_last_month": self.portfolio._last_month,
                "open_trades": self.portfolio.open_trades,
                "latest_regime": self.latest_regime,
                "latest_adx": self.latest_adx,
                "regime_history": self.regime_history,
                "circuit_breaker": {
                    "daily_paused": self.circuit_breaker.daily_paused,
                    "weekly_halved": self.circuit_breaker.weekly_halved,
                    "monthly_paused": self.circuit_breaker.monthly_paused
                }
            }
            try:
                os.makedirs("logs", exist_ok=True)
                with open("logs/portfolio_state.json", "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=4)
            except Exception as e:
                self._log(f"[ERROR] Failed to save state: {e}")

    def load_state(self):
        """Deserializes portfolio, open trade states, and regime history from logs/portfolio_state.json."""
        import json
        path = "logs/portfolio_state.json"
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.portfolio.current_balance = state["current_balance"]
            self.portfolio.peak_balance = state["peak_balance"]
            self.portfolio.daily_pnl = state["daily_pnl"]
            self.portfolio.weekly_pnl = state["weekly_pnl"]
            self.portfolio.trades_today = state["trades_today"]
            self.portfolio.weekly_signals_gen = state["weekly_signals_gen"]
            self.portfolio.weekly_signals_rej = state["weekly_signals_rej"]
            self.portfolio.weekly_trades_exec = state["weekly_trades_exec"]
            self.portfolio.weekly_rejections = state["weekly_rejections"]
            self.portfolio.weekly_daily_pnl = state["weekly_daily_pnl"]
            self.portfolio._running_day_pnl = state["_running_day_pnl"]
            self.portfolio.daily_start_balance = state["daily_start_balance"]
            self.portfolio.weekly_start_balance = state["weekly_start_balance"]
            self.portfolio.monthly_start_balance = state["monthly_start_balance"]
            
            last_date_str = state.get("_last_date")
            if last_date_str:
                from datetime import datetime
                self.portfolio._last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            else:
                self.portfolio._last_date = None
                
            self.portfolio._last_week = state["_last_week"]
            self.portfolio._last_month = state["_last_month"]
            self.portfolio.open_trades = state["open_trades"]
            
            self.latest_regime = state.get("latest_regime", self.latest_regime)
            self.latest_adx = state.get("latest_adx", self.latest_adx)
            
            loaded_history = state.get("regime_history")
            if loaded_history:
                # Convert back to tuples (timestamp_ms, regime)
                self.regime_history = {}
                for sym, history_list in loaded_history.items():
                    self.regime_history[sym] = [tuple(item) for item in history_list]
            
            cb_state = state.get("circuit_breaker", {})
            self.circuit_breaker.daily_paused = cb_state.get("daily_paused", False)
            self.circuit_breaker.weekly_halved = cb_state.get("weekly_halved", False)
            self.circuit_breaker.monthly_paused = cb_state.get("monthly_paused", False)
            
            self._log(f"[STATE] Successfully loaded state from {path}.")
            return True
        except Exception as e:
            self._log(f"[ERROR] Failed to load state: {e}")
            return False

    # ── Logging helpers ──────────────────────────────────────

    def _ensure_trade_csv(self):
        if not os.path.exists(TRADE_LOG_PATH):
            with open(TRADE_LOG_PATH, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(TRADE_CSV_HEADER)

    def _log(self, msg: str):
        ts = _now_ist().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        sys.stdout.flush()
        try:
            with open(PIPELINE_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass

    def _log_trade_csv(self, rec: dict):
        with open(TRADE_LOG_PATH, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow([rec.get(c, "") for c in TRADE_CSV_HEADER])

    # ── Daily summary / period reset timer ───────────────────

    def _start_background_timer(self):
        """60-second background tick: period resets + daily summary at 21:00 IST."""
        def _tick():
            while True:
                try:
                    now = _now_ist()
                    send_summary = False
                    send_weekly = False
                    
                    with self.portfolio_lock:
                        # Period resets + circuit-breaker resets
                        prev_date  = self.portfolio._last_date
                        prev_week  = self.portfolio._last_week
                        prev_month = self.portfolio._last_month

                        self.portfolio.check_resets(now)

                        if prev_date is not None and now.date() != prev_date:
                            self.circuit_breaker.reset_daily()
                        if prev_week >= 0 and now.isocalendar()[1] != prev_week:
                            self.circuit_breaker.reset_weekly()
                        if prev_month >= 0 and now.month != prev_month:
                            self.circuit_breaker.reset_monthly()

                        # 21:00 IST daily summary check
                        if now.hour == 21 and 0 <= now.minute < 2:
                            today = now.date()
                            if self._last_summary_date != today:
                                self._last_summary_date = today
                                send_summary = True
                                trades_today = self.portfolio.trades_today
                                open_cnt = len(self.portfolio.open_trades)
                                daily_pnl = self.portfolio.daily_pnl
                                current_balance = self.portfolio.current_balance
                                peak_balance = self.portfolio.peak_balance
                                dd = self.portfolio.drawdown_pct()

                        # Sunday 21:00 IST weekly stats check
                        if now.weekday() == 6 and now.hour == 21 and 0 <= now.minute < 2:
                            today = now.date()
                            if not hasattr(self, "_last_weekly_stats_date") or self._last_weekly_stats_date != today:
                                self._last_weekly_stats_date = today
                                send_weekly = True
                                closed_count = len(self.portfolio.closed_trades)
                                wins = sum(1 for t in self.portfolio.closed_trades if t.get("pnl_inr", 0.0) > 0.0)
                                win_rate = (wins / closed_count * 100.0) if closed_count > 0 else 0.0
                                weekly_signals_gen = self.portfolio.weekly_signals_gen
                                weekly_signals_rej = self.portfolio.weekly_signals_rej
                                weekly_trades_exec = self.portfolio.weekly_trades_exec
                                rejections = dict(self.portfolio.weekly_rejections)
                                self.portfolio.reset_weekly_stats()

                        self.save_state()

                    if send_summary:
                        self.telegram.send_daily_summary(
                            trades_today, open_cnt, daily_pnl,
                            current_balance, peak_balance, dd,
                        )
                        self._log(
                            f"[DAILY SUMMARY] Balance: ₹{current_balance:,.0f} | "
                            f"Day PnL: ₹{daily_pnl:,.0f} | DD: {dd:.1f}%"
                        )
                        # ── Validation: persist daily summary row ──
                        try:
                            from validation.report_generator import write_daily_summary
                            write_daily_summary(
                                self.portfolio,
                                self.circuit_breaker,
                                now.date().isoformat(),
                            )
                        except Exception as _rep_exc:
                            self._log(f"[VALIDATION] daily_summary write error: {_rep_exc}")

                    if send_weekly:
                        stats_str = (
                            "============================================================\n"
                            "  WEEKLY PERFORMANCE STATS (Sunday 9:00 PM IST)\n"
                            "============================================================\n"
                            f"Signals Generated: {weekly_signals_gen}\n"
                            f"Signals Rejected:  {weekly_signals_rej}\n"
                            f"Trades Executed:   {weekly_trades_exec}\n"
                            f"Win Rate:          {win_rate:.2f}% (Total Closed: {closed_count})\n"
                            "------------------------------------------------------------\n"
                            "Rejection Reason Breakdown:\n"
                            f"  - Regime:          {rejections['regime']}\n"
                            f"  - MTF:             {rejections['mtf']}\n"
                            f"  - Score:           {rejections['score']}\n"
                            f"  - Volume (RVOL):   {rejections['volume']}\n"
                            "============================================================\n"
                        )
                        print(stats_str)
                        sys.stdout.flush()
                        self.telegram.send_message(f"📊 {stats_str}")
                        # ── Validation: persist weekly summary row ──
                        try:
                            from validation.report_generator import write_weekly_summary
                            write_weekly_summary(
                                self.portfolio,
                                list(self.portfolio.closed_trades),
                                now.isocalendar(),
                            )
                        except Exception as _rep_exc:
                            self._log(f"[VALIDATION] weekly_summary write error: {_rep_exc}")

                except Exception as exc:
                    print(f"[TIMER ERROR] {exc}")
                time.sleep(60)

        t = threading.Thread(target=_tick, daemon=True)
        t.start()

    def _log_pipeline(self, symbol, timestamp_ms, current_regime, bias, signal_name, score, decision):
        if timestamp_ms is None:
            self._log(f"[WARNING] {symbol} pipeline log has no timestamp. Skipping logging.")
            return
        candle_time = datetime.fromtimestamp(timestamp_ms/1000, tz=timezone.utc).astimezone(IST).strftime('%H:%M')
        sym_prefix = symbol.split("/")[0]
        
        score_str = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
        sig_str = signal_name if signal_name else "None"
        
        pipe_line = f"[PIPE] {candle_time} {sym_prefix} | {current_regime} | {bias} | {sig_str} | {score_str} | {decision}"
        self._log(pipe_line)

    def record_rejection(self, symbol, reason):
        self.portfolio.record_rejection(reason)
        import telemetry
        telemetry.track_event(symbol, "signal_rejected", {"reason": reason})

    # ── Simulated fills ──────────────────────────────────────

    def _sim_entry(self, signal, score_res, size_res, current_regime):
        """Open a paper trade with slippage + entry fee."""
        symbol    = signal["pair"]
        direction = "LONG" if "LONG" in signal["signal"].upper() else "SHORT"
        raw_price = signal["price"]

        # Fill price with adverse slippage
        fill_price = _apply_slippage(raw_price, direction, is_entry=True)

        # Create trade dict via trade_manager (uses raw signal price for
        # stop/target maths — slippage is accounted for in P&L at exit).
        trade = trade_manager.open_trade(signal, size_res, score=score_res["score"])

        # Attach paper-trading metadata
        trade["entry_timestamp"]  = int(time.time() * 1000)
        trade["regime_at_entry"]  = current_regime
        trade["actual_fill_price"] = round(fill_price, 2)
        trade["mode"]             = signal.get("mode", "")
        trade["type"]             = signal.get("type", "")
        trade["exits"]            = []

        # Entry fee deducted immediately
        entry_fee = _calc_fee(fill_price, size_res["contracts"])
        self.portfolio.record_pnl(-entry_fee)

        self.portfolio.open_trades[symbol] = trade
        self.portfolio.trades_today += 1

        import telemetry
        telemetry.track_event(symbol, "trade_entered", {
            "direction": direction,
            "mode": signal.get("mode", ""),
            "type": signal.get("type", ""),
            "entry_price": fill_price,
            "contracts": size_res["contracts"],
            "risk_inr": size_res["risk_inr"],
            "score": score_res["score"]
        })

        self.telegram.send_entry_alert(
            symbol, direction, score_res["score"],
            signal.get("mode", "?"), signal.get("type", ""),
            fill_price, size_res["stop_price"],
            size_res["contracts"], size_res["risk_inr"],
        )
        self._log(
            f"[PAPER ENTRY] {symbol} {direction} @ ${fill_price:,.2f} | "
            f"Contracts: {size_res['contracts']:.4f} | "
            f"Stop: ${size_res['stop_price']:,.2f} | "
            f"Score: {score_res['score']:.2f} | Mode: {signal.get('mode', '')} "
            f"({signal.get('type', '')})"
        )
        self.save_state()
        return trade

    def _process_exit(self, symbol, trade, action):
        """
        Process a single PARTIAL_CLOSE or FULL_CLOSE action from trade_manager.
        Returns the net P&L of this fill.
        """
        direction   = trade["direction"]
        contracts   = action["contracts"]
        reason      = action["reason"]
        raw_exit_p  = action["price"]
        is_full     = action["action"] == "FULL_CLOSE"

        # Fill price: stops fill at their price, market exits get slippage
        if reason in ("HARD_STOP", "TRAILING_STOP"):
            fill_price = raw_exit_p   # already gap-capped by trade_manager
        else:
            fill_price = _apply_slippage(raw_exit_p, direction, is_entry=False)

        # Gross P&L
        entry_fill = trade.get("actual_fill_price", trade["entry_price"])
        if direction == "LONG":
            gross_pnl = (fill_price - entry_fill) * contracts
        else:
            gross_pnl = (entry_fill - fill_price) * contracts

        # Fees: exit fee only (entry fee already deducted at entry time)
        exit_fee = _calc_fee(fill_price, contracts)
        net_pnl  = gross_pnl - exit_fee

        # Update portfolio
        self.portfolio.record_pnl(net_pnl)

        # Record exit detail on the trade
        trade["exits"].append({
            "time": int(time.time() * 1000),
            "price": round(fill_price, 2),
            "contracts": contracts,
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "reason": reason,
        })

        # Base risk for R-multiple calculation
        base_risk = trade["original_contracts"] * trade["stop_distance"]

        # Calculate metrics for full exits first to prevent NameError in telemetry
        if is_full:
            all_exits   = trade["exits"]
            total_c     = sum(e["contracts"] for e in all_exits)
            if total_c > 0:
                w_exit = sum(e["price"] * e["contracts"] for e in all_exits) / total_c
            else:
                w_exit = fill_price
            total_net   = sum(e["net_pnl"] for e in all_exits)
            total_gross = sum(e["gross_pnl"] for e in all_exits)
            total_r     = total_gross / base_risk if base_risk > 0 else 0.0
            hold_h      = (time.time() * 1000 - trade["entry_timestamp"]) / 3_600_000

        # Telemetry event tracking
        import telemetry
        if is_full:
            if reason in ("HARD_STOP", "TRAILING_STOP"):
                telemetry.track_event(symbol, "stop_loss_hit", {
                    "direction": direction,
                    "entry_price": entry_fill,
                    "exit_price": fill_price if reason == "TRAILING_STOP" else w_exit,
                    "net_pnl": total_net,
                    "pnl_r": total_r,
                    "reason": reason,
                    "is_partial": False
                })
            elif reason in ("2R_TARGET", "3R_TARGET"):
                telemetry.track_event(symbol, "target_hit", {
                    "direction": direction,
                    "entry_price": entry_fill,
                    "exit_price": w_exit,
                    "net_pnl": total_net,
                    "pnl_r": total_r,
                    "reason": reason,
                    "is_partial": False
                })
        else:
            if reason in ("2R_TARGET", "3R_TARGET"):
                telemetry.track_event(symbol, "target_hit", {
                    "direction": direction,
                    "entry_price": entry_fill,
                    "exit_price": fill_price,
                    "net_pnl": net_pnl,
                    "reason": reason,
                    "contracts": contracts,
                    "is_partial": True
                })

        if is_full:
            # ── Full close: log + alert + archive ────────────
            rec = {
                "pair":           symbol,
                "entry_time":     _ts_to_str(trade["entry_timestamp"]),
                "exit_time":      time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                "direction":      direction,
                "entry_price":    trade.get("actual_fill_price", trade["entry_price"]),
                "exit_price":     round(w_exit, 2),
                "contracts":      trade["original_contracts"],
                "pnl_inr":        round(total_net, 2),
                "pnl_r":          round(total_r, 4),
                "exit_reason":    reason,
                "score":          trade["score"],
                "regime_at_entry": trade["regime_at_entry"],
            }
            self.portfolio.closed_trades.append(rec)
            self._log_trade_csv(rec)
            self.portfolio.open_trades.pop(symbol, None)

            self.telegram.send_exit_alert(
                symbol, direction, reason,
                trade.get("actual_fill_price", trade["entry_price"]),
                round(w_exit, 2), total_net, hold_h,
            )
            self._log(
                f"[PAPER EXIT] {symbol} {direction} | {reason} | "
                f"Entry: ${trade.get('actual_fill_price', trade['entry_price']):,.2f} → "
                f"Exit: ${w_exit:,.2f} | PnL: ₹{total_net:,.2f} ({total_r:+.2f}R) | "
                f"Hold: {hold_h:.1f}h"
            )
        else:
            # ── Partial close ────────────────────────────────
            pnl_r = gross_pnl / base_risk if base_risk > 0 else 0.0
            self.telegram.send_partial_alert(
                symbol, direction, reason,
                trade.get("actual_fill_price", trade["entry_price"]),
                round(fill_price, 2), net_pnl, contracts,
            )
            self._log(
                f"[PAPER PARTIAL] {symbol} {direction} | {reason} | "
                f"Closed {contracts:.4f} @ ${fill_price:,.2f} | "
                f"PnL: ₹{net_pnl:,.2f} ({pnl_r:+.2f}R)"
            )

        self.save_state()
        return net_pnl

    def _run_diagnostic_step(self, symbol, c, current_regime, timestamp_ms):
        if timestamp_ms is None:
            print(f"[WARNING] {symbol} diagnostic step has no timestamp. Skipping.")
            return False
        # Format time to IST
        candle_time = datetime.fromtimestamp(timestamp_ms/1000, tz=timezone.utc).astimezone(IST).strftime('%Y-%m-%d %H:%M')
        print(f"[CANDLE] {candle_time} | {symbol} | Close={c}")
        
        # Check regime
        adx_val = self.latest_adx.get(symbol, 0.0)
        if current_regime not in ("TRENDING", "VOLATILE", "RANGING"):
            print(f"[REGIME] {current_regime} (ADX={adx_val}) → BLOCKED")
            sys.stdout.flush()
            return False
        print(f"[REGIME] {current_regime} (ADX={adx_val}) → PASS")
            
        # Check MTF
        alignment = mtf.check_trend_alignment(self.buffers, symbol)
        bias = alignment.get("bias", "NEUTRAL")
        if current_regime in ("TRENDING", "VOLATILE"):
            if not alignment.get("aligned", False) or bias == "NEUTRAL":
                print(f"[MTF] Bias={bias} → BLOCKED")
                sys.stdout.flush()
                return False
        print(f"[MTF] Bias={bias} → PASS")
            
        # Check Signal
        sig = signals.scan_entry(self.buffers, symbol, current_regime, alignment)
        if sig is None:
            if current_regime == "RANGING":
                print(f"[SIGNAL] Ranging Mean Reversion failed: BB/RSI/Pattern conditions not met.")
            else:
                h1_candles = self.buffers[symbol]["1H"].get_candles()
                h1_closes = [cand[4] for cand in h1_candles]
                current_close = h1_closes[-1]
                ema50_vals = mtf.compute_ema(h1_closes, 50)
                current_ema50 = ema50_vals[-1] if ema50_vals else 0.0
                distance_pct = abs(current_close - current_ema50) / current_ema50 * 100.0 if current_ema50 else 0.0
                rsi_vals = signals.compute_rsi(h1_closes, 14)
                current_rsi = rsi_vals[-1] if rsi_vals else 0.0
                print(f"[SIGNAL] Mode B failed: distance={distance_pct:.1f}% (need 0.8%), RSI={current_rsi:.1f}")
            sys.stdout.flush()
            return False
        print(f"[SIGNAL] Mode {sig.get('mode', '?')} passed: {sig.get('signal', '?')}")
            
        # Check Scorer
        reg_res = {"regime": current_regime}
        result = scorer.score_signal(sig, reg_res, alignment)
        if not result["entry"]:
            print(f"[SCORE] {result['score']:.2f} → BLOCKED (need {scorer.THRESHOLD_NORMAL:.2f})")
            sys.stdout.flush()
            return False
        print(f"[ENTRY] Score={result['score']:.2f} → PASS")
        sys.stdout.flush()
        return True

    # ── WebSocket candle callback ────────────────────────────
    def _on_candle_update(self, symbol, timeframe, candle):
        """Invoked by CoinDCXWebSocketClient on every candle tick."""
        if symbol not in self.buffers:
            return

        # Print first tick received for this pair/timeframe to confirm live ingestion
        if not hasattr(self, "_received_first_tick"):
            self._received_first_tick = set()
        tick_key = (symbol, timeframe)
        if tick_key not in self._received_first_tick:
            self._received_first_tick.add(tick_key)
            print(f"[LIVE TICK] Received first tick for {symbol} ({timeframe}) | Price: {candle[4]:.2f} | Time: {datetime.fromtimestamp(candle[0]/1000, tz=timezone.utc).astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')}")
            sys.stdout.flush()

        buf = self.buffers[symbol][timeframe]
        closed, closed_candle = buf.update_or_append(candle)
        if not closed or not closed_candle:
            return

        timestamp_ms = closed_candle[0]
        if timestamp_ms is None:
            self._log(f"[WARNING] {symbol} ({timeframe}) closed candle has no timestamp. Skipping processing.")
            return

        c = closed_candle[4]  # close price

        self._log(
            f"[CANDLE CLOSED] {symbol} ({timeframe}) | "
            f"O:{closed_candle[1]:.2f} H:{closed_candle[2]:.2f} "
            f"L:{closed_candle[3]:.2f} C:{c:.2f} V:{closed_candle[5]:.4f}"
        )

        with self.portfolio_lock:
            # ────── 4H close: regime + trailing stop ─────────────
            if timeframe == "4H":
                try:
                    reg = regime.classify_regime(self.buffers, symbol)
                    old_reg = self.latest_regime.get(symbol, "RANGING")
                    new_reg = reg["regime"]
                    self.latest_regime[symbol] = new_reg
                    self.latest_adx[symbol] = reg["adx"]
                    self._log(f"  [REGIME] {symbol} | {new_reg} (ADX={reg['adx']})")
                    
                    # Check for transition
                    if old_reg != new_reg:
                        import telemetry
                        telemetry.track_event(symbol, "regime_change", {
                            "old_regime": old_reg,
                            "new_regime": new_reg,
                            "adx": reg["adx"]
                        })
                        
                    self.regime_history[symbol].append((timestamp_ms, new_reg))
                except Exception as exc:
                    self._log(f"  [REGIME ERROR] {exc}")
                    import telemetry
                    telemetry.capture_exception(exc)

                # Trailing-stop update for PARTIAL_2 trades
                if symbol in self.portfolio.open_trades:
                    trade = self.portfolio.open_trades[symbol]
                    if trade["stage"] == "PARTIAL_2":
                        try:
                            action = trade_manager.update_trailing_stop(
                                trade, self.buffers[symbol]["4H"]
                            )
                            if action:
                                self._log(
                                    f"  [TRAILING STOP] {symbol} new stop: "
                                    f"${action['new_stop']:,.2f}"
                                )
                        except Exception as exc:
                            self._log(f"  [TRAILING STOP ERROR] {exc}")
                            import telemetry
                            telemetry.capture_exception(exc)
                self.save_state()

            # ────── 1H close: full pipeline ──────────────────────
            if timeframe == "1H":
                current_regime = self.latest_regime.get(symbol, "RANGING")
                
                # Print diagnostic on every closed 1H candle
                self._run_diagnostic_step(symbol, c, current_regime, closed_candle[0])

                # 1. Update existing trade ────────────────────────
                if symbol in self.portfolio.open_trades:
                    trade = self.portfolio.open_trades[symbol]
                    if not trade_manager.is_closed(trade):
                        mgr_regime = "TRENDING" if current_regime == "VOLATILE" else current_regime
                        try:
                            updated, actions = trade_manager.update_trade(
                                trade, c, mgr_regime, self.buffers[symbol]["4H"]
                            )
                            self.portfolio.open_trades[symbol] = updated

                            for act in actions:
                                if act["action"] == "STOP_UPDATE":
                                    self._log(
                                        f"  [STOP UPDATE] {symbol} → "
                                        f"${act['new_stop']:,.2f} ({act['reason']})"
                                    )
                                elif act["action"] in ("PARTIAL_CLOSE", "FULL_CLOSE"):
                                    self._process_exit(symbol, updated, act)
                        except Exception as exc:
                            self._log(f"  [TRADE UPDATE ERROR] {exc}")
                            import telemetry
                            telemetry.capture_exception(exc)

                # 2. Block if still in an open trade on this symbol ──
                if symbol in self.portfolio.open_trades and \
                   not trade_manager.is_closed(self.portfolio.open_trades[symbol]):
                    self._log_pipeline(symbol, timestamp_ms, current_regime, "NEUTRAL", "None", "-", "BLOCKED:open_trade")
                    try:
                        from validation.signal_auditor import log_pre_rejection
                        log_pre_rejection(timestamp_ms, symbol, current_regime, "NEUTRAL",
                                          self.latest_adx.get(symbol, 0.0), "open_trade")
                    except Exception:
                        pass
                    return

                # 2b. Portfolio-level max-2-position cap ──────────────
                # Count only genuinely open (non-CLOSED) trades across ALL symbols
                open_count = sum(
                    1 for t in self.portfolio.open_trades.values()
                    if not trade_manager.is_closed(t)
                )
                if open_count >= 2:
                    self._log_pipeline(symbol, timestamp_ms, current_regime, "NEUTRAL", "None", "-", "BLOCKED:max_positions")
                    try:
                        from validation.signal_auditor import log_pre_rejection
                        log_pre_rejection(timestamp_ms, symbol, current_regime, "NEUTRAL",
                                          self.latest_adx.get(symbol, 0.0), "max_positions")
                    except Exception:
                        pass
                    return

                # Freshness check for entries (Gap Protection)
                now_ms = time.time() * 1000
                close_time_ms = closed_candle[0] + 3600000
                is_fresh = abs(now_ms - close_time_ms) <= 600000  # 10 minutes

                if not is_fresh:
                    self._log(f"  [GAP PROTECTION] Skipping new entry scan for stale candle closed at {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(close_time_ms/1000.0))} (Age: {abs(now_ms - close_time_ms)/1000.0/60.0:.1f} mins)")
                    self._log_pipeline(symbol, timestamp_ms, current_regime, "NEUTRAL", "None", "-", "BLOCKED:stale_candle")
                    try:
                        from validation.signal_auditor import log_pre_rejection
                        log_pre_rejection(timestamp_ms, symbol, current_regime, "NEUTRAL",
                                          self.latest_adx.get(symbol, 0.0), "stale_candle")
                    except Exception:
                        pass
                    return

                # 3. Circuit-breaker gate ─────────────────────────
                can_trade, size_mult, cb_alerts = self.circuit_breaker.evaluate(
                    self.portfolio
                )
                for cb_type, cb_msg in cb_alerts:
                    self._log(f"  [CIRCUIT BREAKER] {cb_type}: {cb_msg}")
                    self.telegram.send_circuit_breaker_alert(cb_type, cb_msg)

                if not can_trade:
                    self._log("  [BLOCKED] Entries paused by circuit breaker.")
                    self._log_pipeline(symbol, timestamp_ms, current_regime, "NEUTRAL", "None", "-", "BLOCKED:circuit_breaker")
                    return

                # 4. Regime gate ──────────────────────────────────
                if current_regime not in ("TRENDING", "VOLATILE", "RANGING"):
                    self._log_pipeline(symbol, timestamp_ms, current_regime, "NEUTRAL", "None", "-", "BLOCKED:regime")
                    self.record_rejection(symbol, "regime")
                    return

                # 5. Full pipeline: MTF → signal → score → size → entry
                try:
                    alignment = mtf.check_trend_alignment(self.buffers, symbol)
                    bias = alignment.get("bias", "NEUTRAL")
                    
                    # If trending/volatile, check MTF alignment
                    if current_regime in ("TRENDING", "VOLATILE"):
                        if not alignment.get("aligned", False) or bias == "NEUTRAL":
                            self._log_pipeline(symbol, timestamp_ms, current_regime, bias, "None", "-", "BLOCKED:mtf")
                            self.record_rejection(symbol, "mtf")
                            try:
                                from validation.signal_auditor import log_pre_rejection
                                log_pre_rejection(timestamp_ms, symbol, current_regime, bias,
                                                  self.latest_adx.get(symbol, 0.0), "mtf")
                            except Exception:
                                pass
                            return

                    regime_trans_bonus = getattr(config, "REGIME_TRANSITION_BONUS", True)
                    mod_pb_bonus = getattr(config, "MODERATE_PULLBACK_BONUS", True)
                    filter_config = getattr(config, "BREAKOUT_FILTER_CONFIG", None)

                    sig = signals.scan_entry(
                        self.buffers, symbol, current_regime, alignment,
                        on_reject_cb=lambda r: self.record_rejection(symbol, r),
                        regime_transition_bonus=regime_trans_bonus,
                        moderate_pullback_bonus=mod_pb_bonus,
                        breakout_filter_config=filter_config,
                        regime_history=self.regime_history[symbol]
                    )
                    if sig is None:
                        self._log_pipeline(symbol, timestamp_ms, current_regime, bias, "None", "-", "BLOCKED:no_signal")
                        try:
                            from validation.signal_auditor import log_pre_rejection
                            log_pre_rejection(timestamp_ms, symbol, current_regime, bias,
                                              self.latest_adx.get(symbol, 0.0), "no_signal")
                        except Exception:
                            pass
                        return

                    # Signal successfully generated
                    self.portfolio.record_signal_gen()
                    import telemetry
                    telemetry.track_event(symbol, "signal_generated", {
                        "signal": sig.get("signal", ""),
                        "mode": sig.get("mode", ""),
                        "price": sig.get("price", 0.0),
                        "rsi": sig.get("rsi"),
                        "rvol": sig.get("rvol", 0.0)
                    })

                    reg_res = {"regime": current_regime}
                    result = scorer.score_signal(sig, reg_res, alignment)

                    if not result["entry"]:
                        self._log_pipeline(symbol, timestamp_ms, current_regime, bias, sig["signal"], result["score"], "BLOCKED:score")
                        self.portfolio.record_rejection("score")
                        # ── Validation: log rejected signal ──
                        try:
                            from validation.signal_auditor import log_signal
                            log_signal(
                                timestamp_ms=timestamp_ms,
                                symbol=symbol,
                                signal=sig,
                                score_result=result,
                                alignment=alignment,
                                regime=current_regime,
                                adx=self.latest_adx.get(symbol, 0.0),
                                size_res=None,
                                balance=self.portfolio.current_balance,
                                decision="REJECTED",
                                reject_reason="score",
                            )
                        except Exception:
                            pass
                        return

                    # Position sizing
                    size_res = sizer.calculate_size(
                        sig, result, current_regime,
                        account_balance=self.portfolio.current_balance,
                        daily_pnl=self.portfolio.weekly_daily_pnl,
                    )

                    # Apply ranging trade size multiplier (0.75)
                    if sig.get("mode") == "R":
                        size_res["contracts"] = round(size_res["contracts"] * 0.75, 4)
                        size_res["risk_inr"] = round(size_res["risk_inr"] * 0.75, 2)
                        size_res["multiplier_applied"] = (
                            size_res["multiplier_applied"] + ", ranging_override"
                            if size_res["multiplier_applied"] != "none"
                            else "ranging_override"
                        )

                    # Apply circuit-breaker size multiplier
                    if size_mult < 1.0:
                        size_res["contracts"] = round(
                            size_res["contracts"] * size_mult, 4
                        )
                        size_res["risk_inr"] = round(
                            size_res["risk_inr"] * size_mult, 2
                        )
                        size_res["multiplier_applied"] = (
                            size_res["multiplier_applied"] + ", cb_multiplier"
                            if size_res["multiplier_applied"] != "none"
                            else "cb_multiplier"
                        )

                    self._sim_entry(sig, result, size_res, current_regime)
                    
                    # Log pipeline success
                    self._log_pipeline(symbol, timestamp_ms, current_regime, bias, f"{sig['signal']} {result['score']:.2f}", result["score"], "ENTRY")
                    self.portfolio.record_trade_exec()
                    # ── Validation: log accepted signal ──
                    try:
                        from validation.signal_auditor import log_signal
                        log_signal(
                            timestamp_ms=timestamp_ms,
                            symbol=symbol,
                            signal=sig,
                            score_result=result,
                            alignment=alignment,
                            regime=current_regime,
                            adx=self.latest_adx.get(symbol, 0.0),
                            size_res=size_res,
                            balance=self.portfolio.current_balance,
                            decision="ACCEPTED",
                            reject_reason="",
                        )
                    except Exception:
                        pass

                except ValueError as exc:
                    self._log(f"  [SIZE ERROR] {exc}")
                except Exception as exc:
                    self._log(f"  [PIPELINE ERROR] {exc}")
                self.save_state()

    # ── Main run loop ────────────────────────────────────────

    def run(self):
        print("=" * 60)
        print("  STARTING PAPER TRADER — Phase 4")
        print("  Pair: BTC/USDT | Balance: ₹{:,.0f}".format(INITIAL_BALANCE))
        print("=" * 60)

        # 1. Seed buffers via REST
        print("\nConnecting to CoinDCX Pro via CCXT Exchange class...")
        if LIVE_MODE:
            api_key = COINDCX_API_KEY if COINDCX_API_KEY != "PASTE_YOUR_KEY_HERE" else os.environ.get("COINDCX_API_KEY", "")
            secret = COINDCX_SECRET if COINDCX_SECRET != "PASTE_YOUR_SECRET_HERE" else os.environ.get("COINDCX_SECRET", "")
            exchange_client = coindcx({
                'apiKey': api_key,
                'secret': secret,
            })
        else:
            exchange_client = coindcx()

        print("\nSeeding historical data via REST API...")
        for symbol in config.SYMBOLS:
            for tf in config.TIMEFRAME_MAP:
                print(f"  Fetching last {config.BUFFER_MAX_SIZE} bars "
                      f"for {symbol} ({tf})...")
                try:
                    candles = exchange_client.fetch_ohlcv(
                        symbol, tf, limit=config.BUFFER_MAX_SIZE
                    )
                    self.buffers[symbol][tf].seed(candles)
                    print(f"    → Seeded {len(self.buffers[symbol][tf])} bars.")
                except Exception as exc:
                    print(f"    → [FATAL] Seed failed: {exc}")
                    sys.exit(1)

        print("\n[OK] All buffers seeded.")

        # 2. Initial regime classification
        for symbol in config.SYMBOLS:
            try:
                reg = regime.classify_regime(self.buffers, symbol)
                self.latest_regime[symbol] = reg["regime"]
                self.latest_adx[symbol] = reg["adx"]
                print(f"  Initial regime for {symbol}: "
                      f"{reg['regime']} (ADX={reg['adx']})")
            except Exception as exc:
                print(f"  [WARN] Regime init failed for {symbol}: {exc}")

        # Run startup diagnostic on the last 10 closed 1H candles
        print("\n=== STARTING STARTUP DIAGNOSTIC (LAST 10 CLOSED 1H CANDLES) ===")
        for symbol in config.SYMBOLS:
            h1_candles = self.buffers[symbol]["1H"].get_candles()
            if len(h1_candles) >= 10:
                for idx in range(-10, 0):
                    c_item = h1_candles[idx]
                    self._run_diagnostic_step(symbol, c_item[4], self.latest_regime.get(symbol, "RANGING"), c_item[0])
        print("================================================================\n")

        # 3. Initialize period tracking
        self.portfolio.check_resets(_now_ist())

        # 4. Start background timer (resets + daily summary)
        self._start_background_timer()

        # 5. Telegram startup message
        symbols_str = " | ".join(config.SYMBOLS)
        self.telegram.send_message(
            f"ApexBot PAPER TRADER started\n"
            f"Pairs: {symbols_str}\n"
            f"Balance: Rs{self.portfolio.current_balance:,.0f}\n"
            f"Regime: BTC={self.latest_regime.get('BTC/USDT', '?')} | LINK={self.latest_regime.get('LINK/USDT', '?')}"
        )

        self._log("Paper trader initialised. Waiting for live candle data...")

        # 6. Start WebSocket
        print("\nInitializing WebSocket connection...")
        ws = CoinDCXWebSocketClient(on_candle_update_cb=self._on_candle_update)
        ws.start()

        print("\n" + "=" * 60)
        print("  PAPER TRADER IS NOW LIVE!")
        print("  Buffers seeded | WebSocket streaming | Pipeline active")
        print("  Press Ctrl+C to stop.")
        print("=" * 60 + "\n")
        sys.stdout.flush()

        # 7. Keep main thread alive
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nShutdown signal received (Ctrl+C)...")
        finally:
            ws.stop()
            with self.portfolio_lock:
                self.save_state()
            self._log("Paper trader stopped.")
            print("Paper trader shutdown complete. Goodbye!")


# ─────────────────────────────────────────────────────────────
# Single-instance guard (Local session named mutex)
# ─────────────────────────────────────────────────────────────
def _acquire_single_instance_mutex():
    """
    Create a Local named session mutex to prevent duplicate instances of paper_trader.py.
    """
    import ctypes

    MUTEX_NAME = "Local\\ApexBotPaperTrader_Trader_Mutex"
    ERROR_ALREADY_EXISTS = 183

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    err = kernel32.GetLastError()

    if err == ERROR_ALREADY_EXISTS:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"[{ts}] [SINGLE-INSTANCE] Another paper_trader.py is already running. Exiting."
        print(msg)
        sys.stdout.flush()
        try:
            os.makedirs("logs", exist_ok=True)
            with open(PIPELINE_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        except Exception:
            pass
        sys.exit(0)
    return handle


def _release_single_instance_mutex(handle):
    """
    Release ownership and close the handle of the single instance named mutex.
    """
    if handle:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _mutex_handle = _acquire_single_instance_mutex()
    try:
        trader = PaperTrader()
        trader.run()
    finally:
        _release_single_instance_mutex(_mutex_handle)
        print("[INFO] Single-instance mutex handle closed.")


