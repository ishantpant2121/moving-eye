"""
Telegram Alert Bot
==================
Sends non-blocking alerts via the Telegram Bot API for paper trading events.
All send operations are dispatched to daemon threads so the trading pipeline
is never blocked by network latency or failures.

If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is empty, missing, or set to placeholder,
the bot operates in "disabled" mode and prints alerts to the console instead.
"""

import threading

# ── Credentials loaded from environment / .env ──────────────────
# Never hard-code real tokens here. Use a .env file instead:
#   cp .env.example .env   then fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
import os as _os
TELEGRAM_BOT_TOKEN = _os.environ.get("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID   = _os.environ.get("TELEGRAM_CHAT_ID",   "PASTE_YOUR_CHAT_ID_HERE")

try:
    import requests as _requests
except ImportError:
    _requests = None


class TelegramBot:
    """Lightweight async Telegram notifier."""

    def __init__(self, token: str = None, chat_id: str = None):
        # Fallback to module-level hardcoded values if not explicitly provided
        self.token = (token or TELEGRAM_BOT_TOKEN or "").strip()
        self.chat_id = (chat_id or TELEGRAM_CHAT_ID or "").strip()
        
        # Check if credentials are placeholders or empty
        is_placeholder = (
            self.token == "PASTE_YOUR_BOT_TOKEN_HERE" or
            self.chat_id == "PASTE_YOUR_CHAT_ID_HERE" or
            not self.token or
            not self.chat_id
        )
        self.enabled = bool(not is_placeholder and _requests)
        self.base_url = f"https://api.telegram.org/bot{self.token}"

        # If disabled because of placeholders, we skip printing warnings silently as requested.
        pass

    # ── Core send (async) ─────────────────────────────────────
    def send_message(self, text: str, parse_mode: str = None) -> bool:
        """Fire-and-forget Telegram message. Returns True if dispatch succeeded."""
        if not self.enabled:
            # Silent fallback: print alerts directly to the console
            print(f"\n[ALERT] {text}\n")
            return False

        def _send():
            try:
                payload = {"chat_id": self.chat_id, "text": text}
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                resp = _requests.post(
                    f"{self.base_url}/sendMessage",
                    json=payload,
                    timeout=10,
                )
                if resp.status_code != 200:
                    print(f"[TELEGRAM ERROR] HTTP {resp.status_code}: {resp.text[:120]}")
            except Exception as exc:
                print(f"[TELEGRAM ERROR] {exc}")

        t = threading.Thread(target=_send, daemon=True)
        t.start()
        return True

    # ── Convenience helpers ───────────────────────────────────
    def send_entry_alert(self, symbol, direction, score, mode, trade_type,
                         fill_price, stop_price, contracts, risk_inr):
        msg = (
            f"🟢 PAPER ENTRY | {symbol} {direction}\n"
            f"Score: {score:.2f} | Mode: {mode} ({trade_type})\n"
            f"Price: ${fill_price:,.2f} | Stop: ${stop_price:,.2f}\n"
            f"Size: {contracts:.4f} BTC | Risk: ₹{risk_inr:,.0f}"
        )
        return self.send_message(msg)

    def send_exit_alert(self, symbol, direction, reason,
                        entry_price, exit_price, net_pnl, hold_hours):
        emoji = "🟢" if net_pnl >= 0 else "🔴"
        pnl_str = f"+₹{net_pnl:.0f}" if net_pnl >= 0 else f"-₹{abs(net_pnl):.0f}"
        msg = (
            f"{emoji} PAPER EXIT | {symbol} {direction}\n"
            f"Reason: {reason}\n"
            f"Entry: ${entry_price:,.2f} → Exit: ${exit_price:,.2f}\n"
            f"PnL: {pnl_str} | Hold: {hold_hours:.1f}h"
        )
        return self.send_message(msg)

    def send_partial_alert(self, symbol, direction, reason,
                           entry_price, exit_price, net_pnl, contracts_closed):
        pnl_str = f"+₹{net_pnl:.0f}" if net_pnl >= 0 else f"-₹{abs(net_pnl):.0f}"
        msg = (
            f"🟡 PAPER PARTIAL | {symbol} {direction}\n"
            f"Reason: {reason}\n"
            f"Entry: ${entry_price:,.2f} → Exit: ${exit_price:,.2f}\n"
            f"PnL: {pnl_str} | Contracts closed: {contracts_closed:.4f}"
        )
        return self.send_message(msg)

    def send_daily_summary(self, trades_today, open_count, day_pnl,
                           balance, peak, drawdown_pct):
        pnl_str = f"+₹{day_pnl:.0f}" if day_pnl >= 0 else f"-₹{abs(day_pnl):.0f}"
        msg = (
            f"📊 DAILY SUMMARY\n"
            f"Trades today: {trades_today} | Open: {open_count}\n"
            f"Day PnL: {pnl_str}\n"
            f"Balance: ₹{balance:,.0f}\n"
            f"Peak: ₹{peak:,.0f} | Drawdown: {drawdown_pct:.1f}%"
        )
        return self.send_message(msg)

    def send_circuit_breaker_alert(self, cb_type, details):
        msg = f"🚨 CIRCUIT BREAKER | {cb_type}\n{details}"
        return self.send_message(msg)
