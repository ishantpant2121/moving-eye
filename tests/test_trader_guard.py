"""
test_trader_guard.py
====================
Unit tests for trader_guard.py:
- Windows named mutex acquisition and release
- Duplicate instance detection
- Configuration paths
"""

import os
import unittest
from unittest.mock import patch, MagicMock
import trader_guard


class TestTraderGuard(unittest.TestCase):
    """Test suite for trader_guard.py."""

    def test_paths(self):
        self.assertTrue(trader_guard.SCRIPT.endswith("paper_trader.py"))
        self.assertTrue(trader_guard.LOG_FILE.endswith("stdout_stderr.log"))

    @patch("ctypes.windll.kernel32.CreateMutexW")
    @patch("ctypes.windll.kernel32.GetLastError")
    def test_acquire_mutex_success(self, mock_err, mock_create):
        mock_create.return_value = 12345
        mock_err.return_value = 0

        handle = trader_guard._acquire_local_mutex()
        self.assertEqual(handle, 12345)

    @patch("ctypes.windll.kernel32.CreateMutexW")
    @patch("ctypes.windll.kernel32.GetLastError")
    def test_acquire_mutex_duplicate_exits(self, mock_err, mock_create):
        mock_create.return_value = 12345
        mock_err.return_value = 183  # ERROR_ALREADY_EXISTS

        with self.assertRaises(SystemExit) as cm:
            trader_guard._acquire_local_mutex()
        self.assertEqual(cm.exception.code, 0)

    @patch("ctypes.windll.kernel32.ReleaseMutex")
    @patch("ctypes.windll.kernel32.CloseHandle")
    def test_release_mutex(self, mock_close, mock_release):
        trader_guard._release_local_mutex(12345)
        mock_release.assert_called_once_with(12345)
        mock_close.assert_called_once_with(12345)


if __name__ == "__main__":
    unittest.main()
