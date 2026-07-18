"""Thread-safe circular buffer implementation for storing OHLCV candles.

Utilizes collections.deque with maxlen to enforce buffer size limits
and manages active/closed candles thread-safely.
"""

from collections import deque
from threading import Lock
from typing import List, Tuple, Optional


class OHLCVBuffer:
    """A thread-safe circular buffer for storing and updating OHLCV candles.
    
    Maintains a maximum of `maxlen` closed candles in memory, tracking the
    current active (open) candle, and emitting notifications when a candle closes.
    """

    def __init__(self, maxlen: int = 500) -> None:
        """Initialize the buffer with a maximum capacity.
        
        Args:
            maxlen: The maximum number of closed candles to retain in history.
            
        Raises:
            ValueError: If maxlen is non-positive.
        """
        if maxlen <= 0:
            raise ValueError(f"Buffer maxlen must be positive, got: {maxlen}")
            
        self._maxlen: int = maxlen
        self._deque: deque[List[float]] = deque(maxlen=maxlen)
        self._lock: Lock = Lock()
        self._active_candle: Optional[List[float]] = None

    def seed(self, candles: List[List[float]]) -> None:
        """Seed the buffer with historical candles.
        
        Clears existing history and imports sorted candles.
        
        Args:
            candles: List of candles where each candle is [timestamp, open, high, low, close, volume].
            
        Raises:
            ValueError: If any candle does not meet length or type constraints.
        """
        if not isinstance(candles, list):
            raise ValueError("Input candles must be a list.")
            
        validated_candles: List[List[float]] = []
        for idx, candle in enumerate(candles):
            if not isinstance(candle, list) or len(candle) != 6:
                raise ValueError(f"Candle at index {idx} must be a list of 6 floats/ints.")
            # Convert all elements to floats for consistency
            try:
                numeric_candle = [float(val) for val in candle]
            except (ValueError, TypeError) as e:
                raise ValueError(f"Candle at index {idx} contains non-numeric values.") from e
            validated_candles.append(numeric_candle)

        with self._lock:
            self._deque.clear()
            # Sort chronologically by timestamp
            sorted_candles = sorted(validated_candles, key=lambda x: x[0])
            self._deque.extend(sorted_candles)
            self._active_candle = None

    def update_or_append(self, candle: List[float]) -> Tuple[bool, Optional[List[float]]]:
        """Update the current active candle or append a new closed candle.
        
        Tracks live candlestick updates. If the timestamp matches the active candle,
        it is updated. If the timestamp is newer, the active candle is pushed to
        history and returns closed = True.
        
        Args:
            candle: The incoming candle [timestamp, open, high, low, close, volume].
            
        Returns:
            A tuple of (candle_closed, closed_candle):
                - candle_closed (bool): True if a candle just closed.
                - closed_candle (list of float or None): The closed candle.
                
        Raises:
            ValueError: If the candle is malformed or contains non-numeric values.
        """
        if not isinstance(candle, list) or len(candle) != 6:
            raise ValueError("Candle must be a list of exactly 6 floats/ints.")
            
        try:
            numeric_candle = [float(val) for val in candle]
        except (ValueError, TypeError) as e:
            raise ValueError("Candle contains non-numeric values.") from e

        with self._lock:
            new_timestamp = numeric_candle[0]

            if self._active_candle is None:
                # If there is no active candle, check the history
                if not self._deque:
                    self._active_candle = numeric_candle
                    return False, None

                last_candle = self._deque[-1]
                last_timestamp = last_candle[0]

                if new_timestamp == last_timestamp:
                    # Update the last candle in history
                    self._deque[-1] = numeric_candle
                    return False, None
                elif new_timestamp > last_timestamp:
                    # Set the new candle as the active candle
                    self._active_candle = numeric_candle
                    return False, None
                else:
                    # Discard out-of-order/stale candle
                    return False, None
            else:
                active_timestamp = self._active_candle[0]

                if new_timestamp == active_timestamp:
                    # Update current active candle
                    self._active_candle = numeric_candle
                    return False, None
                elif new_timestamp > active_timestamp:
                    # Current active candle closes, push to history
                    closed_candle = list(self._active_candle)
                    self._deque.append(self._active_candle)
                    self._active_candle = numeric_candle
                    return True, closed_candle
                else:
                    # Discard out-of-order/stale candle
                    return False, None

    def get_candles(self) -> List[List[float]]:
        """Return a copy of all closed candles currently in the buffer.
        
        Returns:
            A new list containing the historical closed candles.
        """
        with self._lock:
            return list(self._deque)

    def __len__(self) -> int:
        """Return the count of closed candles in history."""
        with self._lock:
            return len(self._deque)
