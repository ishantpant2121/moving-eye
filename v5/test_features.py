"""Unit and verification tests for the v5/features.py indicators module."""

import sys
import os
import unittest
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import new MVA features module
import features

# Import legacy v4.1 modules to use as trusted reference
import mtf as legacy_mtf
import regime as legacy_regime


class TestFeatures(unittest.TestCase):
    def setUp(self) -> None:
        # Create a standard mock dataset
        np.random.seed(42)
        self.n_bars = 60
        self.closes = np.linspace(100.0, 150.0, self.n_bars) + np.random.normal(0.0, 1.0, self.n_bars)
        self.highs = self.closes + np.random.uniform(0.5, 3.0, self.n_bars)
        self.lows = self.closes - np.random.uniform(0.5, 3.0, self.n_bars)
        
        # Format as legacy candles: [timestamp, open, high, low, close, volume]
        self.legacy_candles = []
        for i in range(self.n_bars):
            self.legacy_candles.append([
                float(1000 * i),
                float(self.closes[i] - 0.2),
                float(self.highs[i]),
                float(self.lows[i]),
                float(self.closes[i]),
                100.0
            ])

    def test_ema_mathematical_equivalence(self) -> None:
        """Verify new compute_ema matches the legacy v4.1 compute_ema output exactly."""
        period = 14
        res_new = features.compute_ema(self.closes, period)
        res_legacy = legacy_mtf.compute_ema(list(self.closes), period)
        
        self.assertEqual(len(res_new), len(res_legacy))
        np.testing.assert_allclose(res_new, np.array(res_legacy), rtol=1e-12, atol=1e-12)

    def test_adx_mathematical_equivalence(self) -> None:
        """Verify new compute_adx matches the legacy v4.1 compute_adx output exactly."""
        period = 14
        res_new = features.compute_adx(self.highs, self.lows, self.closes, period)
        res_legacy = legacy_regime.compute_adx(self.legacy_candles, period)
        
        self.assertEqual(len(res_new), len(res_legacy))
        np.testing.assert_allclose(res_new, np.array(res_legacy), rtol=1e-12, atol=1e-12)

    def test_atr_mathematical_equivalence(self) -> None:
        """Verify new compute_atr matches the legacy v4.1 compute_atr output exactly."""
        period = 14
        res_new = features.compute_atr(self.highs, self.lows, self.closes, period)
        res_legacy = legacy_regime.compute_atr(self.legacy_candles, period)
        
        self.assertEqual(len(res_new), len(res_legacy))
        np.testing.assert_allclose(res_new, np.array(res_legacy), rtol=1e-12, atol=1e-12)

    def test_insufficient_data_graceful_handling(self) -> None:
        """Verify that indicators return empty float64 arrays if data length is insufficient."""
        short_closes = np.array([10.0, 11.0, 12.0])
        short_highs = np.array([11.0, 12.0, 13.0])
        short_lows = np.array([9.0, 10.0, 11.0])
        
        # EMA requires len >= period
        self.assertEqual(len(features.compute_ema(short_closes, 10)), 0)
        # ATR requires len >= period + 1
        self.assertEqual(len(features.compute_atr(short_highs, short_lows, short_closes, 5)), 0)
        # ADX requires len >= 2 * period + 1
        self.assertEqual(len(features.compute_adx(short_highs, short_lows, short_closes, 5)), 0)

    def test_boundary_conditions_and_inputs_validation(self) -> None:
        """Verify parameter bounds checking and type validations."""
        with self.assertRaises(ValueError):
            features.compute_ema(self.closes, 0)
        with self.assertRaises(ValueError):
            features.compute_ema(self.closes, -5)
        with self.assertRaises(ValueError):
            features.compute_ema(list(self.closes), 14)  # type: ignore
            
        # NaN detection
        nan_array = self.closes.copy()
        nan_array[5] = np.nan
        with self.assertRaises(ValueError):
            features.compute_ema(nan_array, 14)

    def test_constant_series(self) -> None:
        """Verify behavior on flat constant-price series."""
        flat = np.ones(50) * 100.0
        # EMA of constant series must be exactly the constant price
        res_ema = features.compute_ema(flat, 10)
        np.testing.assert_allclose(res_ema, 100.0)
        
        # ATR of constant series must be exactly zero
        res_atr = features.compute_atr(flat, flat, flat, 14)
        np.testing.assert_allclose(res_atr, 0.0)


if __name__ == "__main__":
    unittest.main()
