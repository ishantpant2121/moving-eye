"""
test_reset_for_trial.py
=======================
Unit tests for reset_for_trial.py:
- Verifies header synchronization across modules
- Ensures CSV reset structures are well-formed
"""

import unittest
import reset_for_trial as rft
import validation.signal_auditor as sa
import validation.report_generator as rg


class TestResetForTrial(unittest.TestCase):
    """Test suite for reset_for_trial.py."""

    def test_signal_audit_header_match(self):
        self.assertEqual(rft.SIGNAL_AUDIT_HEADER, sa.SIGNAL_AUDIT_HEADER)

    def test_daily_header_match(self):
        self.assertEqual(rft.DAILY_HEADER, rg.DAILY_HEADER)

    def test_weekly_header_match(self):
        self.assertEqual(rft.WEEKLY_HEADER, rg.WEEKLY_HEADER)

    def test_files_to_reset_dict(self):
        expected_files = {
            "logs/paper_trades.csv",
            "logs/signal_audit.csv",
            "logs/daily_summary.csv",
            "logs/weekly_summary.csv",
        }
        self.assertEqual(set(rft.files_to_reset.keys()), expected_files)


if __name__ == "__main__":
    unittest.main()
