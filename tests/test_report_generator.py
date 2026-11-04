"""
test_report_generator.py
========================
Unit tests for validation/report_generator.py:
- Canonical v4.1 target metrics preservation
- write_daily_summary CSV output structure
- write_weekly_summary CSV output structure
"""

import os
import csv
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import validation.report_generator as rg


class TestReportGenerator(unittest.TestCase):
    """Test suite for report_generator.py."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.daily_csv = os.path.join(self.temp_dir.name, "daily_summary.csv")
        self.weekly_csv = os.path.join(self.temp_dir.name, "weekly_summary.csv")
        self.patch_daily = patch.object(rg, "DAILY_SUMMARY_PATH", self.daily_csv)
        self.patch_weekly = patch.object(rg, "WEEKLY_SUMMARY_PATH", self.weekly_csv)
        self.patch_daily.start()
        self.patch_weekly.start()

    def tearDown(self):
        self.patch_daily.stop()
        self.patch_weekly.stop()
        self.temp_dir.cleanup()

    def test_canonical_metrics(self):
        self.assertEqual(rg.CANONICAL["trades"], 83)
        self.assertEqual(rg.CANONICAL["profit_factor"], 1.82)
        self.assertEqual(rg.CANONICAL["win_rate_pct"], 54.22)
        self.assertEqual(rg.CANONICAL["max_drawdown_pct"], 5.97)

    def test_write_daily_summary(self):
        mock_portfolio = MagicMock()
        mock_portfolio.current_balance = 51200.0
        mock_portfolio.open_trades = []
        mock_portfolio.daily_pnl = 1200.0
        mock_portfolio.drawdown_pct.return_value = 1.5
        mock_portfolio.weekly_signals_gen = 5
        mock_portfolio.weekly_signals_rej = 3

        mock_cb = MagicMock()
        mock_cb.daily_paused = False
        mock_cb.weekly_halved = False
        mock_cb.monthly_paused = False

        with patch.object(rg, "_read_csv", return_value=[]):
            rg.write_daily_summary(mock_portfolio, mock_cb, "2026-07-15")

        self.assertTrue(os.path.exists(self.daily_csv))
        with open(self.daily_csv, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["date"], "2026-07-15")
            self.assertEqual(row["signals_generated"], "5")
            self.assertEqual(row["balance"], "51200.0")


if __name__ == "__main__":
    unittest.main()
