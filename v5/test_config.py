"""Unit tests for the v5/config.py configuration module."""

import os
import unittest

# Set temporary environment variables before import
os.environ["LIVE_MODE"] = "True"
os.environ["COINDCX_API_KEY"] = "TEST_API_KEY"
os.environ["COINDCX_SECRET"] = "TEST_SECRET"
os.environ["TELEGRAM_BOT_TOKEN"] = "TEST_BOT_TOKEN"
os.environ["TELEGRAM_CHAT_ID"] = "TEST_CHAT_ID"
os.environ["LOG_LEVEL"] = "DEBUG"

import config


class TestConfig(unittest.TestCase):
    def test_environment_variables_loaded(self) -> None:
        """Verify that constants are successfully loaded from environment variables."""
        self.assertTrue(config.LIVE_MODE)
        self.assertEqual(config.COINDCX_API_KEY, "TEST_API_KEY")
        self.assertEqual(config.COINDCX_SECRET, "TEST_SECRET")
        self.assertEqual(config.TELEGRAM_BOT_TOKEN, "TEST_BOT_TOKEN")
        self.assertEqual(config.TELEGRAM_CHAT_ID, "TEST_CHAT_ID")
        self.assertEqual(config.LOG_LEVEL, "DEBUG")

    def test_default_values(self) -> None:
        """Verify that default settings (risk and symbols) match the specification."""
        self.assertEqual(config.SYMBOLS, ["BTC/USDT", "LINK/USDT"])
        self.assertEqual(config.BUFFER_MAX_SIZE, 500)
        self.assertEqual(config.RISK_PER_TRADE_PCT, 0.01)
        self.assertEqual(config.MAX_DAILY_DRAWDOWN_PCT, 0.05)

    def test_validation_passes(self) -> None:
        """Verify that standard configurations pass validation."""
        # Should not raise any exceptions
        config.validate_config()

    def test_validation_fails_on_bad_symbols(self) -> None:
        """Verify that validation fails if SYMBOLS is empty or malformed."""
        original_symbols = config.SYMBOLS
        try:
            config.SYMBOLS = []
            with self.assertRaises(ValueError) as ctx:
                config.validate_config()
            self.assertIn("SYMBOLS must be a non-empty list", str(ctx.exception))
            
            config.SYMBOLS = ["INVALID_SYMBOL"]
            with self.assertRaises(ValueError) as ctx:
                config.validate_config()
            self.assertIn("Invalid asset symbol format", str(ctx.exception))
        finally:
            config.SYMBOLS = original_symbols

    def test_validation_fails_on_bad_buffer_size(self) -> None:
        """Verify that validation fails if BUFFER_MAX_SIZE is zero or negative."""
        original_size = config.BUFFER_MAX_SIZE
        try:
            config.BUFFER_MAX_SIZE = 0
            with self.assertRaises(ValueError) as ctx:
                config.validate_config()
            self.assertIn("BUFFER_MAX_SIZE must be a positive integer", str(ctx.exception))
        finally:
            config.BUFFER_MAX_SIZE = original_size

    def test_validation_fails_on_bad_risk_params(self) -> None:
        """Verify that validation fails if risk settings are out of bounds."""
        original_risk = config.RISK_PER_TRADE_PCT
        try:
            config.RISK_PER_TRADE_PCT = 0.06
            with self.assertRaises(ValueError) as ctx:
                config.validate_config()
            self.assertIn("RISK_PER_TRADE_PCT must be between 0.0 and 0.05", str(ctx.exception))
        finally:
            config.RISK_PER_TRADE_PCT = original_risk


if __name__ == "__main__":
    unittest.main()
