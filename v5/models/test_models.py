"""
v5/models/test_models.py
========================
Comprehensive unit tests for v5 domain models:
- Candle invariants and property calculations
- Signal scoring thresholds
- Order fills and VWAP tracking
- Trade multi-stage scaling and realized PnL
- Portfolio equity and drawdown tracking
"""

import unittest
from v5.models.candle import Candle
from v5.models.signal import Signal, SignalMode, SignalType
from v5.models.order import Order, OrderType, OrderSide, OrderStatus
from v5.models.trade import Trade, TradeStage
from v5.models.portfolio import PortfolioState


class TestV5Models(unittest.TestCase):
    """Test suite for v5 domain models."""

    def test_candle_properties(self):
        c = Candle(
            timestamp_ms=1642622400000,
            open=100.0,
            high=115.0,
            low=95.0,
            close=110.0,
            volume=500.0,
        )
        self.assertEqual(c.range, 20.0)
        self.assertEqual(c.body, 10.0)
        self.assertTrue(c.is_bullish)
        self.assertFalse(c.is_bearish)
        self.assertEqual(c.upper_wick, 5.0)
        self.assertEqual(c.lower_wick, 5.0)
        self.assertEqual(c.to_ccxt(), [1642622400000, 100.0, 115.0, 95.0, 110.0, 500.0])

    def test_candle_validation(self):
        with self.assertRaises(ValueError):
            # High less than open
            Candle(1000, 100.0, 90.0, 80.0, 85.0, 10.0)
        with self.assertRaises(ValueError):
            # Negative volume
            Candle(1000, 100.0, 110.0, 90.0, 105.0, -1.0)

    def test_signal_properties(self):
        sig = Signal(
            symbol="BTC/USDT",
            mode=SignalMode.A,
            type=SignalType.LONG,
            price=60000.0,
            atr=500.0,
            rvol=2.5,
            timestamp_ms=1642622400000,
            score=0.88,
            mss=True,
        )
        self.assertTrue(sig.is_strong)
        self.assertTrue(sig.is_executable)
        d = sig.to_dict()
        self.assertEqual(d["signal"], "MODE_A_LONG")
        self.assertEqual(d["score"], 0.88)

    def test_order_fill_and_vwap(self):
        order = Order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=2.0,
        )
        self.assertEqual(order.status, OrderStatus.PENDING)

        # Fill 1: 1.0 @ 50,000
        order.fill(1.0, 50000.0, fee=20.0)
        self.assertEqual(order.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(order.average_fill_price, 50000.0)

        # Fill 2: 1.0 @ 52,000
        order.fill(1.0, 52000.0, fee=20.0)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.average_fill_price, 51000.0)
        self.assertEqual(order.fee_paid, 40.0)

    def test_trade_lifecycle(self):
        trade = Trade(
            symbol="BTC/USDT",
            direction="LONG",
            entry_price=50000.0,
            original_contracts=1.0,
            stop_price=49000.0,
            stop_distance=1000.0,
        )
        self.assertEqual(trade.remaining_contracts, 1.0)
        self.assertEqual(trade.stage, TradeStage.OPEN)

        # Partial close 40% at 52,000 (2R)
        pnl_1 = trade.close_partial(0.40, 52000.0, "2R_TARGET")
        self.assertEqual(pnl_1, 800.0)
        self.assertAlmostEqual(trade.remaining_contracts, 0.60)
        self.assertAlmostEqual(trade.realized_pnl, 800.0)

        # Full close remaining at 53,000
        pnl_2 = trade.close_full(53000.0, "3R_TARGET")
        self.assertEqual(pnl_2, 1800.0)
        self.assertEqual(trade.remaining_contracts, 0.0)
        self.assertEqual(trade.stage, TradeStage.CLOSED)
        self.assertAlmostEqual(trade.realized_pnl, 2600.0)
        self.assertTrue(trade.is_closed)

    def test_portfolio_equity_and_drawdown(self):
        state = PortfolioState(initial_balance=50000.0, current_balance=50000.0, peak_balance=50000.0)
        trade = Trade(
            symbol="BTC/USDT",
            direction="LONG",
            entry_price=50000.0,
            original_contracts=1.0,
            stop_price=49000.0,
            stop_distance=1000.0,
        )
        state.open_trades["BTC/USDT"] = trade

        # Price at 52,000 -> Unrealized PnL = +2,000 -> Equity = 52,000
        eq = state.equity({"BTC/USDT": 52000.0})
        self.assertEqual(eq, 52000.0)
        self.assertEqual(state.drawdown_pct({"BTC/USDT": 52000.0}), 0.0)

        # Price drops to 45,000 -> Unrealized PnL = -5,000 -> Equity = 45,000
        dd = state.drawdown_pct({"BTC/USDT": 45000.0})
        # (50000 - 45000) / 50000 = 10.0%
        self.assertEqual(dd, 10.0)


if __name__ == "__main__":
    unittest.main()
