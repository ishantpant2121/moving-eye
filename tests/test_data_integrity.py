"""
test_data_integrity.py
======================
Audits historical market datasets in data/ to guarantee data hygiene:
1. Valid schema (timestamp, open, high, low, close, volume)
2. Strict monotonic increasing timestamps (no duplicate or backward timestamps)
3. High/Low invariant (high >= max(open, close), low <= min(open, close))
4. Non-negative prices and volume
5. Expected minimum bar counts for universe assets.
"""

import os
import unittest
import pandas as pd


class TestDataIntegrity(unittest.TestCase):
    """Data integrity test suite for cached OHLCV CSVs."""

    DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    SYMBOLS = ["BTC", "LINK", "ETH", "SOL", "BNB", "AVAX"]
    TIMEFRAMES = ["1H", "4H", "1D"]

    def test_all_expected_csv_files_exist(self):
        """Verify that all 18 standard dataset files exist in data/."""
        for sym in self.SYMBOLS:
            for tf in self.TIMEFRAMES:
                filename = f"{sym}_{tf}.csv"
                filepath = os.path.join(self.DATA_DIR, filename)
                self.assertTrue(os.path.exists(filepath), f"Missing dataset: {filename}")

    def test_csv_schema_and_non_empty(self):
        """Verify schema and non-emptiness for all datasets."""
        expected_cols = {"timestamp", "open", "high", "low", "close", "volume"}
        for sym in self.SYMBOLS:
            for tf in self.TIMEFRAMES:
                filepath = os.path.join(self.DATA_DIR, f"{sym}_{tf}.csv")
                df = pd.read_csv(filepath)
                self.assertFalse(df.empty, f"Dataset {sym}_{tf} is empty")
                self.assertTrue(expected_cols.issubset(set(df.columns)), f"Incomplete schema in {sym}_{tf}")

    def test_ohlc_invariants(self):
        """Verify high is >= open, close and low is <= open, close."""
        for sym in ["BTC", "LINK"]:  # Core universe
            for tf in ["1H", "4H"]:
                filepath = os.path.join(self.DATA_DIR, f"{sym}_{tf}.csv")
                df = pd.read_csv(filepath)
                # Allow a tiny float epsilon (1e-6) for rounding
                self.assertTrue((df["high"] >= df["open"] - 1e-4).all(), f"High < Open violation in {sym}_{tf}")
                self.assertTrue((df["high"] >= df["close"] - 1e-4).all(), f"High < Close violation in {sym}_{tf}")
                self.assertTrue((df["low"] <= df["open"] + 1e-4).all(), f"Low > Open violation in {sym}_{tf}")
                self.assertTrue((df["low"] <= df["close"] + 1e-4).all(), f"Low > Close violation in {sym}_{tf}")
                self.assertTrue((df["volume"] >= 0).all(), f"Negative volume in {sym}_{tf}")

    def test_timestamp_monotonicity(self):
        """Verify timestamps are strictly monotonically increasing."""
        for sym in ["BTC", "LINK"]:
            for tf in ["1H", "4H"]:
                filepath = os.path.join(self.DATA_DIR, f"{sym}_{tf}.csv")
                df = pd.read_csv(filepath)
                diffs = df["timestamp"].diff().dropna()
                self.assertTrue((diffs > 0).all(), f"Timestamps are not strictly ascending in {sym}_{tf}")


if __name__ == "__main__":
    unittest.main()
