"""
test_buffer.py
==============
Unit tests for OHLCVBuffer in buffer.py:
- Initialization and capacity limits
- Seeding and chronological sorting
- Real-time updates vs candle closure
- Stale timestamp handling
- Defensive copying and thread safety
"""

import unittest
import threading
from buffer import OHLCVBuffer


class TestOHLCVBuffer(unittest.TestCase):
    """Test suite for root OHLCVBuffer."""

    def test_init_empty(self):
        buf = OHLCVBuffer(maxlen=10)
        self.assertEqual(len(buf), 0)
        self.assertEqual(buf.get_candles(), [])
        self.assertIsNone(buf.active_candle)

    def test_seed_ordering(self):
        buf = OHLCVBuffer(maxlen=10)
        unsorted_data = [
            [3000, 102, 105, 101, 104, 50],
            [1000, 100, 102, 99, 101, 30],
            [2000, 101, 103, 100, 102, 40],
        ]
        buf.seed(unsorted_data)
        candles = buf.get_candles()
        self.assertEqual(len(candles), 3)
        self.assertEqual([c[0] for c in candles], [1000, 2000, 3000])

    def test_seed_maxlen_eviction(self):
        buf = OHLCVBuffer(maxlen=3)
        data = [[i * 1000, 100, 105, 95, 100, 10] for i in range(1, 6)]
        buf.seed(data)
        candles = buf.get_candles()
        self.assertEqual(len(candles), 3)
        self.assertEqual([c[0] for c in candles], [3000, 4000, 5000])

    def test_update_active_candle(self):
        buf = OHLCVBuffer(maxlen=10)
        # First tick creates active candle
        closed, c = buf.update_or_append([1000, 100, 100, 100, 100, 5])
        self.assertFalse(closed)
        self.assertIsNone(c)
        self.assertEqual(len(buf), 0)

        # Same timestamp updates active candle
        closed, c = buf.update_or_append([1000, 100, 105, 98, 104, 15])
        self.assertFalse(closed)
        self.assertIsNone(c)
        self.assertEqual(buf.active_candle, [1000, 100, 105, 98, 104, 15])

    def test_append_closes_previous_candle(self):
        buf = OHLCVBuffer(maxlen=10)
        buf.update_or_append([1000, 100, 102, 99, 101, 10])

        # New timestamp closes candle 1000 and starts 2000
        closed, closed_candle = buf.update_or_append([2000, 101, 104, 100, 103, 20])
        self.assertTrue(closed)
        self.assertEqual(closed_candle, [1000, 100, 102, 99, 101, 10])
        self.assertEqual(len(buf), 1)
        self.assertEqual(buf.get_candles()[0][0], 1000)
        self.assertEqual(buf.active_candle[0], 2000)

    def test_stale_timestamp_ignored(self):
        buf = OHLCVBuffer(maxlen=10)
        buf.seed([[2000, 100, 105, 95, 100, 10]])
        buf.update_or_append([3000, 100, 105, 95, 100, 10])

        # Stale candle with timestamp 1000
        closed, c = buf.update_or_append([1000, 90, 95, 85, 90, 5])
        self.assertFalse(closed)
        self.assertIsNone(c)
        self.assertEqual(len(buf), 1)

    def test_defensive_copy(self):
        buf = OHLCVBuffer(maxlen=10)
        buf.seed([[1000, 100, 105, 95, 100, 10]])
        candles = buf.get_candles()
        candles.clear()
        self.assertEqual(len(buf), 1)

    def test_thread_safety_concurrent_updates(self):
        buf = OHLCVBuffer(maxlen=100)
        errors = []

        def worker(start_ts):
            try:
                for i in range(20):
                    buf.update_or_append([start_ts + i * 10, 100, 105, 95, 100, 1])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t * 1000,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
