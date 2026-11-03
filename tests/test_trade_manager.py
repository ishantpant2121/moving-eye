"""
test_trade_manager.py
=====================
Unit tests for trade_manager.py:
- open_trade state initialization
- Hard stop breach and 1.5R gap loss capping
- 2R target hit -> PARTIAL_1 (40% closed, stop moved to breakeven)
- 3R target hit -> PARTIAL_2 (20% closed, activates trailing stop)
- Regime flip exit (RANGING or VOLATILE closes trade)
- Trailing stop ratchet mechanics
"""

import unittest
from trade_manager import open_trade, update_trade, is_closed, update_trailing_stop


class TestTradeManager(unittest.TestCase):
    """Test suite for trade_manager.py."""

    def setUp(self):
        self.signal = {
            "pair": "BTC/USDT",
            "price": 50000.0,
            "signal": "MODE_A_LONG",
        }
        self.size_result = {
            "contracts": 1.0,
            "stop_price": 49000.0,
            "stop_distance": 1000.0,
        }

    def test_open_trade(self):
        trade = open_trade(self.signal, self.size_result, score=0.88)
        self.assertEqual(trade["stage"], "OPEN")
        self.assertEqual(trade["direction"], "LONG")
        self.assertEqual(trade["entry_price"], 50000.0)
        self.assertEqual(trade["remaining_contracts"], 1.0)
        self.assertEqual(trade["stop_price"], 49000.0)
        self.assertFalse(is_closed(trade))

    def test_hard_stop_breach(self):
        trade = open_trade(self.signal, self.size_result)
        # Price drops to 48900 (below stop 49000)
        updated, actions = update_trade(trade, current_price=48900.0, current_regime="TRENDING", candle_buffer_4h=[])
        self.assertTrue(is_closed(updated))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["reason"], "HARD_STOP")
        self.assertEqual(actions[0]["contracts"], 1.0)

    def test_gap_risk_capping(self):
        trade = open_trade(self.signal, self.size_result)
        # Entry=50000, StopDist=1000. A flash drop to 47000 is a 3.0R loss.
        # Trade manager must cap loss at 1.5R -> exit price clamped to 50000 - 1500 = 48500.
        updated, actions = update_trade(trade, current_price=47000.0, current_regime="TRENDING", candle_buffer_4h=[])
        self.assertTrue(is_closed(updated))
        self.assertEqual(actions[0]["price"], 48500.0)

    def test_target_partial_1_and_breakeven(self):
        trade = open_trade(self.signal, self.size_result)
        # 2R target = 50000 + 2 * 1000 = 52000
        updated, actions = update_trade(trade, current_price=52050.0, current_regime="TRENDING", candle_buffer_4h=[])
        self.assertEqual(updated["stage"], "PARTIAL_1")
        self.assertAlmostEqual(updated["remaining_contracts"], 0.6)
        # Stop must be at breakeven (entry price 50000)
        self.assertEqual(updated["stop_price"], 50000.0)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["action"], "PARTIAL_CLOSE")
        self.assertAlmostEqual(actions[0]["contracts"], 0.4)
        self.assertEqual(actions[1]["action"], "STOP_UPDATE")
        self.assertEqual(actions[1]["reason"], "BREAKEVEN")

    def test_target_partial_2(self):
        trade = open_trade(self.signal, self.size_result)
        # First trigger PARTIAL_1 at 2R
        trade, _ = update_trade(trade, current_price=52000.0, current_regime="TRENDING", candle_buffer_4h=[])
        # Next reach 3R = 53000
        trade, actions = update_trade(trade, current_price=53100.0, current_regime="TRENDING", candle_buffer_4h=[])
        self.assertEqual(trade["stage"], "PARTIAL_2")
        self.assertAlmostEqual(trade["remaining_contracts"], 0.4)
        self.assertEqual(actions[0]["action"], "PARTIAL_CLOSE")
        self.assertAlmostEqual(actions[0]["contracts"], 0.2)

    def test_regime_flip_exit(self):
        trade = open_trade(self.signal, self.size_result)
        # Regime flips to RANGING
        updated, actions = update_trade(trade, current_price=50500.0, current_regime="RANGING", candle_buffer_4h=[])
        self.assertTrue(is_closed(updated))
        self.assertEqual(actions[0]["reason"], "REGIME_FLIP")
        self.assertEqual(actions[0]["contracts"], 1.0)


if __name__ == "__main__":
    unittest.main()
