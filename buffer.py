# buffer.py
"""
Thread-safe circular buffer implementation for storing OHLCV candles.
Utilizes collections.deque with maxlen to enforce buffer constraints.
"""

from collections import deque
import threading

class OHLCVBuffer:
    """
    A thread-safe circular buffer for OHLCV candles.
    Maintains a maximum of `maxlen` candles.
    """

    def __init__(self, maxlen=500):
        self.maxlen = maxlen
        # deque automatically discards the oldest item when it reaches maxlen and a new item is appended.
        self.deque = deque(maxlen=maxlen)
        self.lock = threading.Lock()
        self.active_candle = None

    def seed(self, candles):
        """
        Seeds the buffer with historical candles.
        Expected format: list of [timestamp, open, high, low, close, volume]
        """
        with self.lock:
            self.deque.clear()
            # Sort chronologically to make sure they are in order
            sorted_candles = sorted(candles, key=lambda x: x[0])
            self.deque.extend(sorted_candles)
            self.active_candle = None

    def update_or_append(self, candle):
        """
        Updates the current open candle or appends a new one.
        `candle` format: [timestamp, open, high, low, close, volume]
        
        Returns:
            (candle_closed, closed_candle)
            - candle_closed (bool): True if a new candle started and the previous candle closed.
            - closed_candle (list or None): The candle that just closed, or None.
        """
        with self.lock:
            if self.active_candle is None:
                if not self.deque:
                    self.active_candle = candle
                    return False, None

                last_candle = self.deque[-1]
                last_timestamp = last_candle[0]
                new_timestamp = candle[0]

                if new_timestamp == last_timestamp:
                    self.deque[-1] = candle
                    return False, None
                elif new_timestamp > last_timestamp:
                    self.active_candle = candle
                    return False, None
                else:
                    return False, None
            else:
                active_timestamp = self.active_candle[0]
                new_timestamp = candle[0]

                if new_timestamp == active_timestamp:
                    self.active_candle = candle
                    return False, None
                elif new_timestamp > active_timestamp:
                    closed_candle = list(self.active_candle)
                    self.deque.append(self.active_candle)
                    self.active_candle = candle
                    return True, closed_candle
                else:
                    return False, None

    def get_candles(self):
        """
        Returns a copy of all candles currently in the buffer as a list.
        """
        with self.lock:
            return list(self.deque)

    def __len__(self):
        with self.lock:
            return len(self.deque)

