import sys
import os
import traceback
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import mtf
import signals
import scorer
import sizer
import trade_manager
from paper_trader import PaperTrader, IST

def test_full_pipeline_flow():
    print("=========================================================")
    print("STARTING FULL PIPELINE VERIFICATION TEST")
    print("=========================================================")
    
    trader = PaperTrader()
    
    # Mock log function to print to stdout so we can inspect
    trader._log = lambda msg: print(f"[LOG] {msg}")
    
    # 1. Seed buffers with dummy historical data
    print("\n[STEP 1] Seeding buffers...")
    dummy_candles_1h = []
    dummy_candles_4h = []
    dummy_candles_1d = []
    
    start_ts = int((datetime.now(timezone.utc) - timedelta(hours=1000)).timestamp() * 1000)
    
    for i in range(500):
        ts = start_ts + i * 3600000
        dummy_candles_1h.append([ts, 64000.0, 64100.0, 63900.0, 64000.0, 10.0])
        
    for i in range(500):
        ts = start_ts + i * 14400000
        dummy_candles_4h.append([ts, 64000.0, 64200.0, 63800.0, 64000.0, 40.0])
        
    for i in range(500):
        ts = start_ts + i * 86400000
        dummy_candles_1d.append([ts, 64000.0, 64500.0, 63500.0, 64000.0, 240.0])
        
    for symbol in config.SYMBOLS:
        trader.buffers[symbol]["1H"].seed(dummy_candles_1h)
        trader.buffers[symbol]["4H"].seed(dummy_candles_4h)
        trader.buffers[symbol]["1D"].seed(dummy_candles_1d)
        trader.latest_regime[symbol] = "TRENDING"
        trader.latest_adx[symbol] = 30.0

    print("Buffers seeded.")

    # 2. Mock indicators and signals to guarantee a LONG breakout signal
    print("\n[STEP 2] Mocking trend alignment and scan_entry...")
    original_check_trend_alignment = mtf.check_trend_alignment
    original_scan_entry = signals.scan_entry
    
    mtf.check_trend_alignment = lambda buffers, symbol: {"aligned": True, "bias": "LONG"}
    
    mock_signal = {
        "signal": "LONG_A",
        "mode": "A",
        "type": "BREAKOUT",
        "pair": "BTC/USDT",
        "price": 64000.0,
        "atr": 400.0,
        "rvol": 2.0,
        "rsi": None,
        "vol_slope": 0.5,
        "resistance_broken": 63900.0
    }
    
    # We will return the mock signal on the first two scans (diagnostic scan and pipeline scan)
    scan_count = [0]
    def mock_scan(*args, **kwargs):
        if scan_count[0] < 2:
            scan_count[0] += 1
            return mock_signal
        return None
    
    signals.scan_entry = mock_scan

    # 3. Trigger candle closed update (1H) to execute entry
    last_seeded_ts = dummy_candles_1h[-1][0]
    next_candle_ts = last_seeded_ts + 3600000
    test_candle = [next_candle_ts + 5000, 64000.0, 64150.0, 63950.0, 64100.0, 15.0]
    
    print(f"\n[STEP 3] Triggering candle closed at {next_candle_ts} (should enter trade)...")
    try:
        trader._on_candle_update("BTC/USDT", "1H", test_candle)
    except Exception as e:
        print("CRITICAL EXCEPTION IN ENTRY:")
        traceback.print_exc()
        return

    # Check if trade is in open trades
    if "BTC/USDT" in trader.portfolio.open_trades:
        print("SUCCESS: Trade opened successfully!")
        trade = trader.portfolio.open_trades["BTC/USDT"]
        print(f"Opened trade details: Direction={trade['direction']}, EntryPrice=${trade['entry_price']:.2f}, Contracts={trade['original_contracts']:.4f}")
    else:
        print("FAILURE: Trade was not opened.")
        return

    # 4. Trigger subsequent candle closes to test trade updates
    # We will simulate price rising to 64500 (not hitting SL/target)
    next_candle_ts_2 = next_candle_ts + 3600000
    test_candle_2 = [next_candle_ts_2 + 5000, 64100.0, 64600.0, 64050.0, 64500.0, 12.0]
    
    print(f"\n[STEP 4] Triggering subsequent candle update at {next_candle_ts_2} (should update trade)...")
    try:
        trader._on_candle_update("BTC/USDT", "1H", test_candle_2)
    except Exception as e:
        print("CRITICAL EXCEPTION IN UPDATE:")
        traceback.print_exc()
        return

    # 5. Trigger a candle close that hits stop loss
    # Stop distance was 1.5 * atr = 600. So SL is 64000 - 600 = 63400.
    # Let's drop price to 63000 to hit SL
    next_candle_ts_3 = next_candle_ts_2 + 3600000
    test_candle_3 = [next_candle_ts_3 + 5000, 64500.0, 64500.0, 62900.0, 63000.0, 30.0]
    
    print(f"\n[STEP 5] Sending candle with price drop to 63000...")
    try:
        trader._on_candle_update("BTC/USDT", "1H", test_candle_3)
    except Exception as e:
        print("CRITICAL EXCEPTION IN EXIT:")
        traceback.print_exc()
        return

    # Now close test_candle_3 by sending a new candle period
    next_candle_ts_4 = next_candle_ts_3 + 3600000
    test_candle_4 = [next_candle_ts_4 + 5000, 63000.0, 63100.0, 62900.0, 63000.0, 10.0]
    
    print(f"\n[STEP 6] Triggering candle update at {next_candle_ts_4} to close the 63000 candle (should trigger exit)...")
    try:
        trader._on_candle_update("BTC/USDT", "1H", test_candle_4)
    except Exception as e:
        print("CRITICAL EXCEPTION IN EXIT:")
        traceback.print_exc()
        return

    if "BTC/USDT" not in trader.portfolio.open_trades:
        print("SUCCESS: Trade exited and removed from open trades successfully!")
        if trader.portfolio.closed_trades:
            last_closed = trader.portfolio.closed_trades[-1]
            print(f"Closed trade details: ExitReason={last_closed['exit_reason']}, ExitPrice=${last_closed['exit_price']:.2f}, PnL=₹{last_closed['pnl_inr']:.2f}")
    else:
        print("FAILURE: Trade was not closed.")

    # Restore original functions
    mtf.check_trend_alignment = original_check_trend_alignment
    signals.scan_entry = original_scan_entry
    print("\nVerification completed successfully!")

if __name__ == "__main__":
    test_full_pipeline_flow()
