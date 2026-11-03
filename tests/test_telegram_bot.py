"""
test_telegram_bot.py
====================
Unit tests for telegram_bot.py:
- Placeholder detection and silent disabled fallback
- Asynchronous daemon message dispatch
- Alert formatters (entry, exit, partial, summary, circuit breaker)
"""

import io
import time
import unittest
from unittest.mock import patch, MagicMock
from telegram_bot import TelegramBot


class TestTelegramBot(unittest.TestCase):
    """Test suite for TelegramBot."""

    def test_disabled_on_placeholder_credentials(self):
        bot = TelegramBot(token="PASTE_YOUR_BOT_TOKEN_HERE", chat_id="PASTE_YOUR_CHAT_ID_HERE")
        self.assertFalse(bot.enabled)

    def test_disabled_fallback_output(self):
        bot = TelegramBot(token="", chat_id="")
        self.assertFalse(bot.enabled)
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            res = bot.send_message("Test Console Alert")
            self.assertFalse(res)
            self.assertIn("Test Console Alert", mock_stdout.getvalue())

    @patch("requests.post")
    def test_enabled_send_message_dispatches_post(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        bot = TelegramBot(token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", chat_id="987654321")
        self.assertTrue(bot.enabled)

        res = bot.send_message("Unit test alert text")
        self.assertTrue(res)

        # Allow daemon thread a moment to fire
        time.sleep(0.05)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("123456:ABC-DEF", args[0])
        self.assertEqual(kwargs["json"]["chat_id"], "987654321")
        self.assertEqual(kwargs["json"]["text"], "Unit test alert text")

    def test_alert_formatters(self):
        bot = TelegramBot(token="", chat_id="")
        with patch.object(bot, "send_message", return_value=True) as mock_send:
            # 1. Entry alert
            bot.send_entry_alert("BTC/USDT", "LONG", 0.90, "A", "Breakout", 60000.0, 59000.0, 0.5, 500.0)
            mock_send.assert_called_with(
                "🟢 PAPER ENTRY | BTC/USDT LONG\nScore: 0.90 | Mode: A (Breakout)\nPrice: $60,000.00 | Stop: $59,000.00\nSize: 0.5000 BTC | Risk: ₹500"
            )

            # 2. Exit alert
            bot.send_exit_alert("BTC/USDT", "LONG", "2R_TARGET", 60000.0, 62000.0, 1000.0, 4.5)
            self.assertIn("🟢 PAPER EXIT | BTC/USDT LONG", mock_send.call_args[0][0])
            self.assertIn("PnL: +₹1000", mock_send.call_args[0][0])

            # 3. Circuit breaker alert
            bot.send_circuit_breaker_alert("DAILY_DRAWDOWN", "Breached -2.0% limit")
            self.assertIn("🚨 CIRCUIT BREAKER | DAILY_DRAWDOWN", mock_send.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
