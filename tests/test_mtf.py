"""
test_mtf.py
===========
Unit tests for mtf.py (Multi-Timeframe Trend Alignment):
- compute_ema edge cases and progression
- detect_swing_points (swing high SH, swing low SL)
- classify_market_structure (BULLISH, BEARISH, MIXED)
- check_trend_alignment safety on empty or insufficient buffers
"""

import unittest
from mtf import (
    compute_ema,
    detect_swing_points,
    classify_market_structure,
    check_trend_alignment,
)
from buffer import OHLCVBuffer


class TestMTF(unittest.TestCase):
    """Test suite for mtf.py."""

    def test_compute_ema_insufficient_length(self):
        closes = [10.0, 11.0, 12.0]
        self.assertEqual(compute_ema(closes, period=5), [])

    def test_compute_ema_exact_length(self):
        closes = [10.0, 20.0, 30.0]
        ema = compute_ema(closes, period=3)
        self.assertEqual(len(ema), 1)
        self.assertAlmostEqual(ema[0], 20.0)

    def test_compute_ema_progression(self):
        # Constant prices keep EMA constant
        closes = [100.0] * 20
        ema = compute_ema(closes, period=10)
        self.assertEqual(len(ema), 11)
        for val in ema:
            self.assertAlmostEqual(val, 100.0)

    def test_detect_swing_points(self):
        # Construct candles with clear swing high at index 2 and swing low at index 6
        # Candle format: [timestamp, open, high, low, close, volume]
        candles = [
            [1000, 10, 15, 8, 12, 1],   # i=0
            [2000, 12, 20, 10, 18, 1],  # i=1
            [3000, 18, 30, 15, 25, 1],  # i=2: SH (left=2, right=2)
            [4000, 25, 22, 16, 18, 1],  # i=3
            [5000, 18, 19, 14, 15, 1],  # i=4
            [6000, 15, 16, 10, 12, 1],  # i=5
            [7000, 12, 14, 5, 8, 1],    # i=6: SL (left=2, right=2)
            [8000, 8, 16, 7, 14, 1],    # i=7
            [9000, 14, 20, 12, 18, 1],  # i=8
        ]
        swings = detect_swing_points(candles, left=2, right=2)
        sh_points = [s for s in swings if s["type"] == "SH"]
        sl_points = [s for s in swings if s["type"] == "SL"]

        self.assertEqual(len(sh_points), 1)
        self.assertEqual(sh_points[0]["index"], 2)
        self.assertEqual(sh_points[0]["value"], 30)

        self.assertEqual(len(sl_points), 1)
        self.assertEqual(sl_points[0]["index"], 6)
        self.assertEqual(sl_points[0]["value"], 5)

    def test_classify_market_structure(self):
        # Bullish: Higher Highs + Higher Lows
        bullish_swings = [
            {"type": "SL", "value": 100},
            {"type": "SH", "value": 150},
            {"type": "SL", "value": 120},
            {"type": "SH", "value": 180},
            {"type": "SL", "value": 140},
            {"type": "SH", "value": 210},
        ]
        self.assertEqual(classify_market_structure(bullish_swings, count=5), "BULLISH")

        # Bearish: Lower Highs + Lower Lows
        bearish_swings = [
            {"type": "SH", "value": 200},
            {"type": "SL", "value": 150},
            {"type": "SH", "value": 180},
            {"type": "SL", "value": 120},
            {"type": "SH", "value": 160},
            {"type": "SL", "value": 90},
        ]
        self.assertEqual(classify_market_structure(bearish_swings, count=5), "BEARISH")

        # Mixed / Flat
        mixed_swings = [
            {"type": "SH", "value": 200},
            {"type": "SL", "value": 150},
            {"type": "SH", "value": 210},
            {"type": "SL", "value": 140},
            {"type": "SH", "value": 190},
        ]
        self.assertEqual(classify_market_structure(mixed_swings, count=5), "MIXED")

    def test_check_trend_alignment_empty_buffers(self):
        buffers = {
            "BTC/USDT": {
                "1D": OHLCVBuffer(maxlen=500),
                "4H": OHLCVBuffer(maxlen=500),
            }
        }
        res = check_trend_alignment(buffers, "BTC/USDT")
        self.assertEqual(res["bias"], "NEUTRAL")
        self.assertFalse(res["aligned"])
        self.assertIn("Not enough", res["reason"])


if __name__ == "__main__":
    unittest.main()
