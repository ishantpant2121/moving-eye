"""
test_sizer.py
=============
Unit tests for sizer.py (Position Sizing Calculator):
- calculate_weekly_drawdown peak-to-trough logic
- Base sizing formula (1% risk / (1.5 * ATR))
- Long vs Short stop price direction
- Volatility regime halving (0.5x)
- Drawdown halving (>5% drawdown -> 0.5x)
- 1% hard equity risk capping
- Input validation on non-positive ATR / price / invalid signal
"""

import unittest
from sizer import calculate_size, calculate_weekly_drawdown


class TestSizer(unittest.TestCase):
    """Test suite for sizer.py."""

    def test_calculate_weekly_drawdown(self):
        # Base balance: 50,000. Peak equity reaches 52,000, then drops to 49,000.
        # Drawdown = (52000 - 49000) / 52000 = 3000 / 52000 ≈ 5.77%
        daily_pnl = [1000, 1000, -2000, -1000]
        dd = calculate_weekly_drawdown(daily_pnl, base_balance=50000.0)
        self.assertAlmostEqual(dd, (3000.0 / 52000.0) * 100.0, places=2)

    def test_calculate_size_base_long(self):
        signal = {"atr": 100.0, "price": 50000.0, "signal": "MODE_A_LONG"}
        score = {"strength": "normal"}
        res = calculate_size(signal, score, regime="TRENDING", account_balance=50000.0)

        # 1% of 50000 = 500 INR. Stop distance = 1.5 * 100 = 150.
        # Contracts = 500 / 150 ≈ 3.3333
        # Stop price = 50000 - 150 = 49850
        self.assertEqual(res["risk_inr"], 500.0)
        self.assertEqual(res["stop_distance"], 150.0)
        self.assertEqual(res["stop_price"], 49850.0)
        self.assertAlmostEqual(res["contracts"], 3.3333, places=3)
        self.assertEqual(res["multiplier_applied"], "none")

    def test_calculate_size_base_short(self):
        signal = {"atr": 100.0, "price": 50000.0, "signal": "MODE_A_SHORT"}
        score = {"strength": "normal"}
        res = calculate_size(signal, score, regime="TRENDING", account_balance=50000.0)

        # Stop price = 50000 + 150 = 50150
        self.assertEqual(res["stop_price"], 50150.0)

    def test_calculate_size_volatile_regime(self):
        signal = {"atr": 100.0, "price": 50000.0, "signal": "MODE_A_LONG"}
        score = {"strength": "normal"}
        res = calculate_size(signal, score, regime="VOLATILE", account_balance=50000.0)

        # Volatile halves size: 3.3333 * 0.5 ≈ 1.6667
        self.assertAlmostEqual(res["contracts"], 1.6667, places=3)
        self.assertIn("volatile", res["multiplier_applied"])
        self.assertAlmostEqual(res["risk_inr"], 250.0, places=1)

    def test_calculate_size_hard_max_risk_cap(self):
        signal = {"atr": 100.0, "price": 50000.0, "signal": "MODE_A_LONG"}
        score = {"strength": "strong"}
        res = calculate_size(signal, score, regime="TRENDING", account_balance=50000.0)

        # Strong attempts 1.25x, but hard risk cap clamps risk to 1% (500 INR)
        self.assertEqual(res["risk_inr"], 500.0)
        self.assertAlmostEqual(res["contracts"], 3.3333, places=3)

    def test_calculate_size_drawdown_reduction(self):
        signal = {"atr": 100.0, "price": 50000.0, "signal": "MODE_A_LONG"}
        score = {"strength": "normal"}
        res = calculate_size(signal, score, regime="TRENDING", account_balance=50000.0, weekly_drawdown=6.0)

        # >5% drawdown cuts size in half
        self.assertAlmostEqual(res["contracts"], 1.6667, places=3)
        self.assertIn("drawdown", res["multiplier_applied"])

    def test_invalid_inputs(self):
        score = {"strength": "normal"}
        with self.assertRaises(ValueError):
            calculate_size({"atr": 0, "price": 100, "signal": "LONG"}, score, "TRENDING")
        with self.assertRaises(ValueError):
            calculate_size({"atr": 10, "price": -5, "signal": "LONG"}, score, "TRENDING")
        with self.assertRaises(ValueError):
            calculate_size({"atr": 10, "price": 100, "signal": "INVALID"}, score, "TRENDING")


if __name__ == "__main__":
    unittest.main()
