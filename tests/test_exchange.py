"""
test_exchange.py
================
Unit tests for exchange.py (CoinDCX CCXT subclass):
- describe() configuration
- Symbol mapping (BTC/USDT -> B-BTC_USDT)
- Timeframe validation
- Mocked successful API response parsing
- Malformed candle skipping
- Retry logic and ExchangeError on persistent failure
"""

import unittest
from unittest.mock import patch, MagicMock
import ccxt
from exchange import coindcx


class TestExchange(unittest.TestCase):
    """Test suite for exchange.py."""

    def setUp(self):
        self.ex = coindcx()

    def test_describe(self):
        desc = self.ex.describe()
        self.assertEqual(desc["id"], "coindcx")
        self.assertEqual(desc["name"], "CoinDCX")
        self.assertTrue(desc["has"]["fetchOHLCV"])

    def test_invalid_timeframe_raises_bad_request(self):
        with self.assertRaises(ccxt.BadRequest):
            self.ex.fetch_ohlcv("BTC/USDT", timeframe="15M")

    @patch("requests.get")
    def test_fetch_ohlcv_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"time": 1642622400000, "open": "41800.0", "high": "42000.0", "low": "41500.0", "close": "41900.0", "volume": "100.5"},
                {"time": 1642626000000, "open": "41900.0", "high": "42100.0", "low": "41800.0", "close": "42050.0", "volume": "150.2"},
            ]
        }
        mock_get.return_value = mock_resp

        candles = self.ex.fetch_ohlcv("BTC/USDT", timeframe="1H", limit=10)
        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0], [1642622400000, 41800.0, 42000.0, 41500.0, 41900.0, 100.5])
        self.assertEqual(candles[1][0], 1642626000000)

        # Verify symbol was mapped to futures pair B-BTC_USDT
        args, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["pair"], "B-BTC_USDT")

    @patch("requests.get")
    def test_fetch_ohlcv_skips_malformed_candles(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"time": 1000, "open": "invalid", "high": "100", "low": "90", "close": "95", "volume": "10"},
                {"time": 2000, "open": "100", "high": "105", "low": "95", "close": "102", "volume": "20"},
            ]
        }
        mock_get.return_value = mock_resp

        candles = self.ex.fetch_ohlcv("LINK/USDT", timeframe="1H", limit=5)
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0][0], 2000)

    @patch("time.sleep", return_value=None)
    @patch("requests.get")
    def test_fetch_ohlcv_retries_and_raises_exchange_error(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        with self.assertRaises(ccxt.ExchangeError):
            self.ex.fetch_ohlcv("BTC/USDT", timeframe="1H", limit=5)

        self.assertEqual(mock_get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
