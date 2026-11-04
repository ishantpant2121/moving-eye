"""
test_signal_auditor.py
======================
Unit tests for validation/signal_auditor.py:
- CSV header generation
- log_signal for ACCEPTED decisions
- log_signal for REJECTED decisions
- log_pre_rejection for regime, MTF, or circuit breaker blocks
"""

import os
import csv
import tempfile
import unittest
from unittest.mock import patch
import validation.signal_auditor as sa


class TestSignalAuditor(unittest.TestCase):
    """Test suite for signal_auditor.py."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_csv = os.path.join(self.temp_dir.name, "signal_audit.csv")
        self.patcher = patch.object(sa, "SIGNAL_AUDIT_PATH", self.temp_csv)
        self.patcher.start()
        sa._header_written = False

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_ensure_csv_writes_header(self):
        sa._ensure_csv()
        self.assertTrue(os.path.exists(self.temp_csv))
        with open(self.temp_csv, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            self.assertEqual(header, sa.SIGNAL_AUDIT_HEADER)

    def test_log_signal_accepted(self):
        signal = {
            "mode": "A",
            "type": "LONG",
            "rvol": 2.2,
            "atr": 500.0,
            "price": 60000.0,
            "mss": True,
        }
        alignment = {"aligned": True, "bias": "LONG"}
        score_result = {"score": 0.90, "breakdown": {"rvol": 0.20}}
        size_result = {"contracts": 0.5, "stop_price": 59250.0, "risk_inr": 500.0}

        sa.log_signal(
            timestamp_ms=1642622400000,
            symbol="BTC/USDT",
            signal=signal,
            score_result=score_result,
            alignment=alignment,
            regime="TRENDING",
            adx=32.5,
            size_res=size_result,
            balance=50000.0,
            decision="ACCEPTED",
        )

        with open(self.temp_csv, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["symbol"], "BTC/USDT")
            self.assertEqual(row["mode"], "A")
            self.assertEqual(row["decision"], "ACCEPTED")
            self.assertEqual(row["entry_price"], "60000.0")
            self.assertEqual(row["position_size"], "0.5")

    def test_log_pre_rejection(self):
        sa.log_pre_rejection(
            timestamp_ms=1642622400000,
            symbol="BTC/USDT",
            regime="RANGING",
            trend_alignment="NEUTRAL",
            adx=18.0,
            reject_reason="regime_not_trending",
        )

        with open(self.temp_csv, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["symbol"], "BTC/USDT")
            self.assertEqual(row["decision"], "REJECTED")
            self.assertEqual(row["reject_reason"], "regime_not_trending")
            self.assertEqual(row["position_size"], "")


if __name__ == "__main__":
    unittest.main()
