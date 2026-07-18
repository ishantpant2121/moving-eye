"""ApexBot Pro v5 Configuration Module.

This module loads project environment variables, defines key constants,
and runs validation checks on configuration integrity at system startup.
"""

import os
from typing import Dict, List


def _load_env(filepath: str = ".env") -> None:
    """Minimal .env loader — avoids the external python-dotenv dependency.
    
    Reads key-value pairs from the .env file in the current working directory
    and loads them into os.environ.
    """
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())


# Load environment variables from .env if present
_load_env()

# =====================================================================
# GLOBAL CONFIGURATION CONSTANTS
# =====================================================================

# Trading Mode
LIVE_MODE: bool = os.environ.get("LIVE_MODE", "False").lower() in ("true", "1", "yes")

# Asset & Timeframe Settings
SYMBOLS: List[str] = ["BTC/USDT", "LINK/USDT"]
BUFFER_MAX_SIZE: int = 500
TIMEFRAME_MAP: Dict[str, str] = {
    "1H": "1h",
    "4H": "4h",
    "1D": "1d"
}

# API Credentials
COINDCX_API_KEY: str = os.environ.get("COINDCX_API_KEY", "PASTE_YOUR_KEY_HERE")
COINDCX_SECRET: str = os.environ.get("COINDCX_SECRET", "PASTE_YOUR_SECRET_HERE")

# Telegram Alerts
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "PASTE_YOUR_CHAT_ID_HERE")

# Logging
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

# Risk Management Parameters
RISK_PER_TRADE_PCT: float = 0.01          # Max 1.0% account equity risk per trade
MAX_DAILY_DRAWDOWN_PCT: float = 0.05      # Max 5.0% daily account drawdown breaker

# =====================================================================
# CONFIGURATION VALIDATION
# =====================================================================

def validate_config() -> None:
    """Run verification checks on loaded configuration parameters.
    
    Raises:
        ValueError: If any parameter fails the validation rules.
    """
    if not isinstance(SYMBOLS, list) or len(SYMBOLS) == 0:
        raise ValueError("SYMBOLS must be a non-empty list of asset strings.")
        
    for symbol in SYMBOLS:
        if not isinstance(symbol, str) or "/" not in symbol:
            raise ValueError(f"Invalid asset symbol format: {symbol}. Expected format like 'BTC/USDT'.")
            
    if not isinstance(BUFFER_MAX_SIZE, int) or BUFFER_MAX_SIZE <= 0:
        raise ValueError(f"BUFFER_MAX_SIZE must be a positive integer, got: {BUFFER_MAX_SIZE}")
        
    if not isinstance(TIMEFRAME_MAP, dict) or len(TIMEFRAME_MAP) == 0:
        raise ValueError("TIMEFRAME_MAP must be a non-empty dictionary.")
        
    if not (0.0 < RISK_PER_TRADE_PCT <= 0.05):
        raise ValueError(f"RISK_PER_TRADE_PCT must be between 0.0 and 0.05, got: {RISK_PER_TRADE_PCT}")
        
    if not (0.0 < MAX_DAILY_DRAWDOWN_PCT <= 0.20):
        raise ValueError(f"MAX_DAILY_DRAWDOWN_PCT must be between 0.0 and 0.20, got: {MAX_DAILY_DRAWDOWN_PCT}")
        
    if LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ValueError(f"Invalid LOG_LEVEL: {LOG_LEVEL}")

# Execute validation on import to prevent startup with bad settings
validate_config()
