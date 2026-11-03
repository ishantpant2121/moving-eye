"""
test_websocket_client.py
========================
Unit tests for websocket_client.py:
- Client initialization
- Candlestick event payload deserialization and normalization
- Handling of corrupt or empty socket frames
- Channel subscription on connect event
- REST polling fallback start/stop state management
"""

import json
import unittest
from unittest.mock import MagicMock, patch
from websocket_client import CoinDCXWebSocketClient


class TestCoinDCXWebSocketClient(unittest.TestCase):
    """Test suite for CoinDCXWebSocketClient."""

    def setUp(self):
        self.callback = MagicMock()
        self.client = CoinDCXWebSocketClient(on_candle_update_cb=self.callback)

    def tearDown(self):
        self.client.stop()

    def test_init_state(self):
        self.assertTrue(self.client.should_connect)
        self.assertFalse(self.client.polling_active)
        self.assertIsNotNone(self.client.sio)

    def test_on_candlestick_valid_payload(self):
        # Format matching CoinDCX WebSocket payload
        inner_data = {
            "i": "1h",
            "data": [
                {
                    "pair": "B-BTC_USDT",
                    "open_time": 1642622400,  # in seconds
                    "open": "41800.5",
                    "high": "42100.0",
                    "low": "41750.0",
                    "close": "42050.0",
                    "volume": "123.45",
                }
            ]
        }
        raw_msg = {"data": json.dumps(inner_data)}

        self.client._on_candlestick(raw_msg)

        self.callback.assert_called_once()
        symbol, timeframe, candle = self.callback.call_args[0]
        self.assertEqual(symbol, "BTC/USDT")
        self.assertEqual(timeframe, "1H")
        self.assertEqual(candle[0], 1642622400000)  # ms converted
        self.assertEqual(candle[1], 41800.5)
        self.assertEqual(candle[2], 42100.0)
        self.assertEqual(candle[3], 41750.0)
        self.assertEqual(candle[4], 42050.0)
        self.assertEqual(candle[5], 123.45)

    def test_on_candlestick_empty_or_corrupt_payload(self):
        self.client._on_candlestick(None)
        self.client._on_candlestick({})
        self.client._on_candlestick({"data": "not valid json"})
        self.callback.assert_not_called()

    def test_on_candlestick_unsupported_interval(self):
        inner_data = {
            "i": "15m",  # unsupported interval
            "data": [{"pair": "B-BTC_USDT", "open_time": 1000, "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"}]
        }
        self.client._on_candlestick({"data": json.dumps(inner_data)})
        self.callback.assert_not_called()

    def test_on_connect_subscribes(self):
        mock_sio = MagicMock()
        self.client.sio = mock_sio

        self.client._on_connect()

        self.assertTrue(self.client.connected_event.is_set())
        mock_sio.start_background_task.assert_called_once()
        # Verify emit("join", ...) was called
        emitted_channels = [call[0][1]["channelName"] for call in mock_sio.emit.call_args_list if call[0][0] == "join"]
        self.assertIn("B-BTC_USDT_1h-futures", emitted_channels)
        self.assertIn("B-LINK_USDT_1h-futures", emitted_channels)

    def test_start_and_stop_rest_polling(self):
        with patch.object(self.client, "_rest_polling_loop"):
            self.client._start_rest_polling()
            self.assertTrue(self.client.polling_active)
            self.client._stop_rest_polling()
            self.assertFalse(self.client.polling_active)


if __name__ == "__main__":
    unittest.main()
