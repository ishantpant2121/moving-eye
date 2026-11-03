"""
test_regime.py
==============
Unit tests for regime.py (Market Regime Classifier):
- compute_adx calculations and boundary safety (0 <= ADX <= 100)
- compute_atr calculations
- Insufficient data handling (graceful fallback to RANGING)
- Regime classification with real BTC 4H historical buffer
"""

import os
import unittest
import pandas as pd
from regime import compute_adx, compute_atr, classify_regime
from buffer import OHLCVBuffer


class TestRegime(unittest.TestCase):
    """Test suite for regime.py."""

    def test_compute_adx_short_data(self):
        candles = [[i * 1000, 100, 105, 95, 100, 10] for i in range(20)]
        self.assertEqual(compute_adx(candles, period=14), [])

    def test_compute_atr_short_data(self):
        candles = [[i * 1000, 100, 105, 95, 100, 10] for i in range(10)]
        self.assertEqual(compute_atr(candles, period=14), [])

    def test_compute_atr_positive(self):
        candles = [[i * 1000, 100, 110, 90, 105, 10] for i in range(30)]
        atr_values = compute_atr(candles, period=14)
        self.assertGreater(len(atr_values), 0)
        for a in atr_values:
            self.assertGreater(a, 0.0)

    def test_compute_adx_range_bounds(self):
        # Create 50 trending candles
        candles = [[i * 1000, 100 + i * 2, 105 + i * 2, 98 + i * 2, 104 + i * 2, 100] for i in range(60)]
        adx_values = compute_adx(candles, period=14)
        self.assertGreater(len(adx_values), 0)
        for adx in adx_values:
            self.assertGreaterEqual(adx, 0.0)
            self.assertLessEqual(adx, 100.0)

    def test_classify_regime_insufficient_data(self):
        buffers = {"BTC/USDT": {"4H": OHLCVBuffer(maxlen=500)}}
        res = classify_regime(buffers, "BTC/USDT")
        self.assertEqual(res["regime"], "RANGING")
        self.assertIn("Insufficient 4H data", res["details"]["error"])

    def test_classify_regime_with_historical_candles(self):
        data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "BTC_4H.csv"))
        if not os.path.exists(data_path):
            self.skipTest("data/BTC_4H.csv not found")

        df = pd.read_csv(data_path).iloc[:300]
        candles = df[["timestamp", "open", "high", "low", "close", "volume"]].values.tolist()

        buf = OHLCVBuffer(maxlen=500)
        buf.seed(candles)
        buffers = {"BTC/USDT": {"4H": buf}}

        res = classify_regime(buffers, "BTC/USDT")
        self.assertIn(res["regime"], {"TRENDING", "RANGING", "VOLATILE"})
        self.assertGreaterEqual(res["adx"], 0.0)
        self.assertIn("latest_atr", res["details"])


if __name__ == "__main__":
    unittest.main()
