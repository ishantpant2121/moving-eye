"""
test_scorer.py
==============
Unit tests for scorer.py:
- Score calculations for Mode A (Breakout)
- Score calculations for Mode B (Pullback v2)
- Score calculations for Mode R (Mean Reversion)
- Strength categorization: "strong" (>= 0.85), "normal" (>= 0.70), "none" (< 0.70)
- Factor breakdown reporting
"""

import unittest
from scorer import score_signal, THRESHOLD_STRONG, THRESHOLD_NORMAL


class TestScorer(unittest.TestCase):
    """Test suite for scorer.py."""

    def test_mode_a_strong_score(self):
        signal = {
            "mode": "A",
            "type": "LONG",
            "rvol": 2.5,
            "atr_expanding": True,
            "vol_slope": 0.5,
            "pattern": "BULLISH_ENGULFING",
        }
        regime_result = {"regime": "TRENDING"}
        alignment = {"aligned": True, "bias": "LONG"}

        res = score_signal(signal, regime_result, alignment)
        self.assertGreaterEqual(res["score"], THRESHOLD_STRONG)
        self.assertEqual(res["strength"], "strong")
        self.assertTrue(res["entry"])
        self.assertIn("breakdown", res)

    def test_mode_a_below_threshold(self):
        signal = {
            "mode": "A",
            "type": "LONG",
            "rvol": 0.5,
            "atr_expanding": False,
            "vol_slope": -0.2,
            "pattern": None,
        }
        regime_result = {"regime": "RANGING"}
        alignment = {"aligned": False, "bias": "NEUTRAL"}

        res = score_signal(signal, regime_result, alignment)
        self.assertLess(res["score"], THRESHOLD_NORMAL)
        self.assertEqual(res["strength"], "none")
        self.assertFalse(res["entry"])

    def test_mode_b_pullback_scoring(self):
        signal = {
            "mode": "B",
            "type": "LONG",
            "rvol": 1.2,
            "pattern": "HAMMER",
            "atr_stable": True,
            "volume_contracting": True,
            "pullback_depth": 0.5,
        }
        regime_result = {"regime": "TRENDING"}
        alignment = {"aligned": True, "bias": "LONG"}

        res = score_signal(signal, regime_result, alignment)
        self.assertGreaterEqual(res["score"], THRESHOLD_NORMAL)
        self.assertTrue(res["entry"])

    def test_mode_r_reversion_scoring(self):
        signal = {
            "mode": "R",
            "type": "SHORT",
            "rvol": 1.8,
            "pattern": "SHOOTING_STAR",
            "rsi": 78.0,
            "bb_touch": True,
        }
        regime_result = {"regime": "RANGING"}
        alignment = {"aligned": True, "bias": "NEUTRAL"}

        res = score_signal(signal, regime_result, alignment)
        self.assertGreater(res["score"], 0.0)
        self.assertIn("rvol_strong", res["breakdown"])


if __name__ == "__main__":
    unittest.main()
