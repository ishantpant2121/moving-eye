"""Unit and integration tests for the v5/buffer.py OHLCVBuffer class."""

import unittest
import threading
import time
from buffer import OHLCVBuffer


class TestOHLCVBuffer(unittest.TestCase):
    def test_empty_buffer(self) -> None:
        """Verify that an empty buffer initializes correctly and reports len = 0."""
        buf = OHLCVBuffer(maxlen=10)
        self.assertEqual(len(buf), 0)
        self.assertEqual(buf.get_candles(), [])
        
        # Test constructor value check
        with self.assertRaises(ValueError):
            OHLCVBuffer(maxlen=0)
        with self.assertRaises(ValueError):
            OHLCVBuffer(maxlen=-5)

    def test_initial_seeding(self) -> None:
        """Verify that seeding populates the buffer and sorts chronologically."""
        buf = OHLCVBuffer(maxlen=10)
        candles = [
            [1700000002000, 10.0, 11.0, 9.0, 10.5, 100.0],
            [1700000001000, 9.0, 10.0, 8.0, 9.5, 50.0],
            [1700000003000, 11.0, 12.0, 10.0, 11.5, 150.0]
        ]
        buf.seed(candles)
        self.assertEqual(len(buf), 3)
        
        res = buf.get_candles()
        # Verify chronological sorting by timestamp
        self.assertEqual(res[0][0], 1700000001000)
        self.assertEqual(res[1][0], 1700000002000)
        self.assertEqual(res[2][0], 1700000003000)

    def test_seeding_validation(self) -> None:
        """Verify that seed rejects bad/malformed data."""
        buf = OHLCVBuffer(maxlen=10)
        with self.assertRaises(ValueError):
            buf.seed("not a list")  # type: ignore
        with self.assertRaises(ValueError):
            buf.seed([[1, 2, 3, 4, 5]])  # length 5 instead of 6
        with self.assertRaises(ValueError):
            buf.seed([[1, 2, 3, 4, 5, "not_a_float"]])  # type: ignore

    def test_buffer_overflow(self) -> None:
        """Verify that the circular buffer discards the oldest element when maxlen is exceeded."""
        buf = OHLCVBuffer(maxlen=3)
        candles = [
            [1000, 1.0, 1.0, 1.0, 1.0, 1.0],
            [2000, 2.0, 2.0, 2.0, 2.0, 2.0],
            [3000, 3.0, 3.0, 3.0, 3.0, 3.0]
        ]
        buf.seed(candles)
        self.assertEqual(len(buf), 3)
        
        # Add active candle
        closed, closed_candle = buf.update_or_append([4000, 4.0, 4.0, 4.0, 4.0, 4.0])
        self.assertFalse(closed)
        self.assertIsNone(closed_candle)
        
        # Trigger close by adding a newer active candle
        closed2, closed_candle2 = buf.update_or_append([5000, 5.0, 5.0, 5.0, 5.0, 5.0])
        self.assertTrue(closed2)
        self.assertIsNotNone(closed_candle2)
        self.assertEqual(closed_candle2[0], 4000)  # type: ignore
        
        # Check buffer contents (should discard oldest 1000 and keep 2000, 3000, 4000)
        res = buf.get_candles()
        self.assertEqual(len(res), 3)
        self.assertEqual(res[0][0], 2000)
        self.assertEqual(res[1][0], 3000)
        self.assertEqual(res[2][0], 4000)

    def test_partial_candle_updates(self) -> None:
        """Verify that updating a candle with the same timestamp updates it in-place."""
        buf = OHLCVBuffer(maxlen=10)
        
        # Start from empty
        closed, closed_candle = buf.update_or_append([1000, 1.0, 2.0, 0.5, 1.5, 10.0])
        self.assertFalse(closed)
        self.assertIsNone(closed_candle)
        
        # Update current active candle
        closed, closed_candle = buf.update_or_append([1000, 1.0, 3.0, 0.5, 1.8, 15.0])
        self.assertFalse(closed)
        self.assertIsNone(closed_candle)
        
        # Verify active updates are not in history yet
        self.assertEqual(len(buf), 0)

        # Force a close
        closed, closed_candle = buf.update_or_append([2000, 2.0, 2.0, 2.0, 2.0, 2.0])
        self.assertTrue(closed)
        self.assertEqual(closed_candle[4], 1.8)  # type: ignore
        
        # Now update the active candle (timestamp = 2000)
        closed, closed_candle = buf.update_or_append([2000, 2.0, 3.0, 2.0, 2.5, 2.0])
        self.assertFalse(closed)
        self.assertIsNone(closed_candle)
        
        # Force another close to push the updated active candle into history
        closed, closed_candle = buf.update_or_append([3000, 3.0, 3.0, 3.0, 3.0, 3.0])
        self.assertTrue(closed)
        self.assertEqual(closed_candle[4], 2.5)  # type: ignore
        
        # Test updating the last closed candle when active_candle is None (e.g. after a seed or reset)
        buf.seed([[1000, 1.0, 1.0, 1.0, 1.0, 1.0]])
        self.assertEqual(buf.get_candles()[0][4], 1.0)
        
        # Update last candle with active_candle being None
        closed, closed_candle = buf.update_or_append([1000, 1.0, 1.0, 1.0, 1.5, 1.0])
        self.assertFalse(closed)
        self.assertIsNone(closed_candle)
        self.assertEqual(buf.get_candles()[0][4], 1.5)

    def test_out_of_order_and_duplicates(self) -> None:
        """Verify that out-of-order and stale candles are silently discarded."""
        buf = OHLCVBuffer(maxlen=10)
        buf.seed([[1000, 1.0, 1.0, 1.0, 1.0, 1.0]])
        
        # Add new active candle
        buf.update_or_append([2000, 2.0, 2.0, 2.0, 2.0, 2.0])
        
        # Send a stale candle (timestamp = 1500 < active timestamp 2000)
        closed, closed_candle = buf.update_or_append([1500, 1.5, 1.5, 1.5, 1.5, 1.5])
        self.assertFalse(closed)
        self.assertIsNone(closed_candle)
        
        # Verify it wasn't appended
        self.assertEqual(len(buf), 1)

    def test_concurrent_access_stress(self) -> None:
        """Stress test concurrent reader/writer threads to ensure lock correctness and thread safety."""
        buf = OHLCVBuffer(maxlen=100)
        num_writes = 500
        
        # Shared flags
        error_occurred = False
        
        def writer_thread() -> None:
            nonlocal error_occurred
            try:
                for i in range(num_writes):
                    # Incrementing timestamps (every iteration is a new candle)
                    buf.update_or_append([float(1000 + i), 1.0, 1.0, 1.0, 1.0, 1.0])
                    time.sleep(0.001)
            except Exception as e:
                print(f"Writer error: {e}")
                error_occurred = True

        def reader_thread() -> None:
            nonlocal error_occurred
            try:
                for _ in range(200):
                    # Verify read copy operation is thread safe without raising RuntimeError
                    candles = buf.get_candles()
                    self.assertIsInstance(candles, list)
                    time.sleep(0.002)
            except Exception as e:
                print(f"Reader error: {e}")
                error_occurred = True

        threads = [
            threading.Thread(target=writer_thread),
            threading.Thread(target=reader_thread),
            threading.Thread(target=reader_thread)
        ]
        
        for t in threads:
            t.start()
            
        for t in threads:
            t.join()
            
        self.assertFalse(error_occurred)
        self.assertGreater(len(buf), 0)


if __name__ == "__main__":
    unittest.main()
