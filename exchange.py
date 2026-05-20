# exchange.py
"""
Custom CCXT exchange integration for CoinDCX.
Subclasses ccxt.Exchange to implement standard fetch_ohlcv capability 
for CoinDCX Pro Futures public candlestick API.
"""

import time
import requests
import ccxt
import config

class coindcx(ccxt.Exchange):
    """
    Custom CCXT exchange subclass for CoinDCX Pro Futures.
    Implements fetch_ohlcv to seed historical candlestick buffers.
    """

    def describe(self):
        # Merge our custom configuration with the base CCXT exchange describe config
        return self.deep_extend(super(coindcx, self).describe(), {
            "id": "coindcx",
            "name": "CoinDCX",
            "countries": ["IN"],
            "rateLimit": 1000,
            "has": {
                "fetchOHLCV": True,
            },
            "urls": {
                "api": {
                    "public": config.REST_API_URL,
                }
            }
        })

    def fetch_ohlcv(self, symbol, timeframe="1H", since=None, limit=None, params={}):
        """
        Fetches historical OHLCV candles from CoinDCX.
        Returns a list of candles in CCXT format:
        [[timestamp, open, high, low, close, volume], ...]
        """
        # Validate timeframe
        if timeframe not in config.TIMEFRAME_MAP:
            raise ccxt.BadRequest(f"Unsupported timeframe: {timeframe}. Choose from {list(config.TIMEFRAME_MAP.keys())}")

        # Map timeframe to resolution
        resolution = config.TIMEFRAME_MAP[timeframe]["resolution"]

        # Map standard symbol (e.g. BTC/USDT) to CoinDCX internal futures symbol (e.g. B-BTC_USDT)
        coindcx_symbol = symbol.replace("/", "_")
        if not coindcx_symbol.startswith("B-"):
            coindcx_symbol = f"B-{coindcx_symbol}"

        # Determine timeframe duration in seconds
        if timeframe == "1H":
            duration_sec = 3600
        elif timeframe == "4H":
            duration_sec = 4 * 3600
        elif timeframe == "1D":
            duration_sec = 24 * 3600
        else:
            duration_sec = 3600

        # Calculate time range
        now_sec = int(time.time())
        if limit is None:
            limit = config.BUFFER_MAX_SIZE

        if since is not None:
            # since is in milliseconds
            from_sec = int(since // 1000)
        else:
            # Go back enough seconds to fetch requested number of limit candles
            # Add a small buffer of 5 extra candles to ensure we get enough
            from_sec = now_sec - ((limit + 5) * duration_sec)

        to_sec = now_sec

        # API parameters
        url = f"{config.REST_API_URL}/market_data/candlesticks"
        query_params = {
            "pair": coindcx_symbol,
            "from": from_sec,
            "to": to_sec,
            "resolution": resolution,
            "pcode": "f"  # 'f' indicates futures
        }

        # Make the request with connect/read timeout and exponential backoff retry logic
        max_retries = 3
        backoff_sec = 1.0
        response = None
        last_exception = None

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(url, params=query_params, timeout=(5, 15))
                if response.status_code == 200:
                    break
                else:
                    raise ccxt.ExchangeError(f"CoinDCX API error: {response.status_code} - {response.text}")
            except (requests.exceptions.RequestException, ccxt.ExchangeError) as e:
                last_exception = e
                print(f"[WARNING] REST API request failed (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    time.sleep(backoff_sec)
                    backoff_sec *= 2.0

        if response is None or response.status_code != 200:
            raise ccxt.ExchangeError(
                f"CoinDCX API call failed after {max_retries} attempts. Last error: {last_exception}"
            )


        data = response.json()
        raw_candles = data.get("data", [])

        ohlcv = []
        for c in raw_candles:
            try:
                # CCXT structure: [timestamp_ms, open, high, low, close, volume]
                ohlcv.append([
                    int(c["time"]),
                    float(c["open"]),
                    float(c["high"]),
                    float(c["low"]),
                    float(c["close"]),
                    float(c["volume"])
                ])
            except (KeyError, ValueError) as e:
                # Skip malformed candles if any
                continue

        # Sort chronologically (oldest to newest)
        ohlcv.sort(key=lambda x: x[0])

        # Slice to the last `limit` elements if we retrieved more
        if len(ohlcv) > limit:
            ohlcv = ohlcv[-limit:]

        return ohlcv
