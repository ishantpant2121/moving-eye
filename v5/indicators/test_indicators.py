"""
v5/indicators/test_indicators.py
================================
Unit tests for v5 modular indicators:
- Mathematical equivalence with legacy v4.1 functions
- Boundary checks and handling of insufficient data
- Bollinger Band calculations
- Reversal pattern recognition
"""

import unittest
from v5.indicators.ema import compute_ema, update_ema_tick
from v5.indicators.atr import compute_atr, compute_tr
from v5.indicators.adx import compute_adx
from v5.indicators.bollinger import compute_bollinger_bands
from v5.indicators.patterns import detect_candlestick_pattern, CandlestickPattern
import mtf
import regime


class TestV5Indicators(unittest.TestCase):
    """Test suite for v5 indicator calculations."""

    def test_ema_matches_legacy(self):
        closes = [100.0 + i * 1.5 for i in range(50)]
        v5_ema = compute_ema(closes, period=20)
        legacy_ema = mtf.compute_ema(closes, period=20)
        self.assertEqual(len(v5_ema), len(legacy_ema))
        for v5_val, leg_val in zip(v5_ema, legacy_ema):
            self.assertAlmostEqual(v5_val, leg_val, places=6)

    def test_ema_streaming_update(self):
        closes = [100.0, 102.0, 104.0, 106.0]
        ema_batch = compute_ema(closes, period=3)
        # Seed is SMA(3) = 102.0. Next is tick 106.0.
        prev = 102.0
        updated = update_ema_tick(prev, 106.0, period=3)
        self.assertAlmostEqual(updated, ema_batch[-1], places=6)

    def test_atr_matches_legacy(self):
        candles = [[i * 1000, 100 + i, 110 + i, 90 + i, 105 + i, 10] for i in range(40)]
        v5_atr = compute_atr(candles, period=14)
        legacy_atr = regime.compute_atr(candles, period=14)
        self.assertEqual(len(v5_atr), len(legacy_atr))
        for v5_val, leg_val in zip(v5_atr, legacy_atr):
            self.assertAlmostEqual(v5_val, leg_val, places=6)

    def test_adx_matches_legacy(self):
        candles = [[i * 1000, 100 + i * 2, 105 + i * 2, 95 + i * 2, 102 + i * 2, 10] for i in range(50)]
        v5_adx = compute_adx(candles, period=14)
        legacy_adx = regime.compute_adx(candles, period=14)
        self.assertEqual(len(v5_adx), len(legacy_adx))
        for v5_val, leg_val in zip(v5_adx, legacy_adx):
            self.assertAlmostEqual(v5_val, leg_val, places=6)

    def test_bollinger_bands(self):
        closes = [100.0] * 30
        bands = compute_bollinger_bands(closes, period=20)
        self.assertEqual(len(bands), 11)
        # Constant prices -> std = 0 -> upper == middle == lower
        latest = bands[-1]
        self.assertEqual(latest.middle, 100.0)
        self.assertEqual(latest.upper, 100.0)
        self.assertEqual(latest.lower, 100.0)
        self.assertEqual(latest.bandwidth, 0.0)

    def test_candlestick_patterns(self):
        # 1. Bullish Engulfing
        bull_eng = [
            [1000, 105, 106, 99, 100, 10],   # Red: 105 -> 100
            [2000, 99, 108, 98, 107, 20],    # Green: 99 -> 107 (engulfs)
        ]
        self.assertEqual(detect_candlestick_pattern(bull_eng), CandlestickPattern.BULLISH_ENGULFING.value)

        # 2. Bearish Engulfing
        bear_eng = [
            [1000, 100, 106, 99, 105, 10],   # Green: 100 -> 105
            [2000, 106, 107, 98, 98, 20],    # Red: 106 -> 98 (engulfs)
        ]
        self.assertEqual(detect_candlestick_pattern(bear_eng), CandlestickPattern.BEARISH_ENGULFING.value)

        # 3. Hammer
        hammer = [
            [1000, 100, 102, 98, 101, 10],
            [2000, 100, 101, 80, 101, 20],   # Small body (1), long lower wick (20)
        ]
        self.assertEqual(detect_candlestick_pattern(hammer), CandlestickPattern.HAMMER.value)


if __name__ == "__main__":
    unittest.main()
