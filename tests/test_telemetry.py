"""
test_telemetry.py
=================
Unit tests for telemetry.py:
- capture_exception fallback when Sentry is unconfigured
- track_event fallback when PostHog is unconfigured
- Default properties handling
"""

import unittest
from unittest.mock import patch
import telemetry


class TestTelemetry(unittest.TestCase):
    """Test suite for telemetry.py."""

    def test_capture_exception_local_logging(self):
        with patch.object(telemetry.logger, "error") as mock_log:
            exc = ValueError("Test telemetry error")
            telemetry.capture_exception(exc)
            mock_log.assert_called_once()
            self.assertIn("Test telemetry error", mock_log.call_args[0][0])

    def test_track_event_local_logging(self):
        with patch.object(telemetry.logger, "info") as mock_log:
            telemetry.track_event("test_user_1", "ORDER_FILLED", {"symbol": "BTC/USDT", "pnl": 500})
            mock_log.assert_called_once()
            self.assertIn("ORDER_FILLED", mock_log.call_args[0][0])
            self.assertIn("BTC/USDT", mock_log.call_args[0][0])

    def test_track_event_none_properties(self):
        with patch.object(telemetry.logger, "info") as mock_log:
            telemetry.track_event("test_user_2", "HEARTBEAT", None)
            mock_log.assert_called_once()
            self.assertIn("HEARTBEAT", mock_log.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
