# config.py
"""
Configuration settings for the CoinDCX Pro Futures Data Ingestion Layer.
This file contains parameters for symbols, timeframes, buffer sizes,
API endpoints, heartbeats, and reconnect options.
"""

# Symbols to subscribe to. We start with BTC/USDT and LINK/USDT (Universe C).
# CoinDCX Pro futures uses 'B-BTC_USDT' internally, which we map from standard 'BTC/USDT'.
SYMBOLS = ["BTC/USDT", "LINK/USDT"]

# Strategy execution options
ENABLE_MODE_R = False

# ── Signal Pipeline Configuration (canonical engine parity) ──
# BREAKOUT_FILTER_CONFIG: set to "B" to match canonical engine (RVOL > 2.0, volume slope disabled).
# Setting to None uses signals.py default (RVOL > 1.5, volume slope enabled) — DO NOT use in production.
BREAKOUT_FILTER_CONFIG = "B"

# These bonus flags must be False to match the canonical strategy.
# The canonical engine (portfolio_validation.py) does not use any score bonuses.
REGIME_TRANSITION_BONUS = False
MODERATE_PULLBACK_BONUS = False

# Experiment A: Liquidity Sweeps
ENABLE_LIQUIDITY_SWEEPS = False  # Options: False, "bonus", "filter"
LIQUIDITY_SWEEP_BONUS = 0.10     # Range: +0.05 to +0.15
LIQUIDITY_SWEEP_MODE = "both"     # Options: "A", "B", "both"

# Experiment B: Market Structure Shift (MSS / CHOCH)
ENABLE_MSS = "filter"            # Options: False, "bonus", "filter", "trend_continuation"
MSS_BONUS = 0.10                 # Range: +0.05 to +0.15
MSS_MODE = "A"                   # Options: "A", "B", "both"

# Experiment C: Pullback Depth
ENABLE_PULLBACK_DEPTH_BONUS = False  # Options: False, True
PULLBACK_DEPTH_BONUS_VAL = 0.10      # Range: +0.05 to +0.10

# Experiment D: Regime Transition
ENABLE_REGIME_TRANSITION_BONUS = False  # Options: False, True
REGIME_TRANSITION_BONUS_VAL = 0.10      # Range: +0.05 to +0.10

# Timeframes to store and stream.
# We map each standard timeframe to:
#  - 'resolution': REST API parameter value for /market_data/candlesticks
#  - 'ws_interval': WebSocket channel parameter value (e.g. '1h' in 'B-BTC_USDT_1h-futures')
TIMEFRAME_MAP = {
    "1H": {
        "resolution": "60",       # 60 minutes
        "ws_interval": "1h"
    },
    "4H": {
        "resolution": "240",      # 240 minutes
        "ws_interval": "4h"
    },
    "1D": {
        "resolution": "1D",       # 1 day
        "ws_interval": "1d"
    }
}

# The size of our in-memory circular buffer for candles per timeframe per pair.
BUFFER_MAX_SIZE = 500

# CoinDCX API Endpoints
REST_API_URL = "https://public.coindcx.com"
WEBSOCKET_URL = "https://stream.coindcx.com"

# WebSocket keep-alive settings
# CoinDCX requires a ping event emit every 25 seconds to keep the socket connection alive.
HEARTBEAT_INTERVAL = 25.0

# WebSocket reconnection settings
RECONNECT_INITIAL_BACKOFF = 1.0   # Start with 1 second delay
RECONNECT_MAX_BACKOFF = 60.0      # Max reconnect delay of 60 seconds
RECONNECT_MULTIPLIER = 2.0        # Double the delay on each failure
