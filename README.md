# ApexBot CoinDCX Trading Engine

This project is a premium quantitative trading system that integrates multi-timeframe analysis, regime classification, entry signal scanners, position sizing, risk management, and a live paper trading engine targeting CoinDCX Pro Futures.

---

## 🛠️ Windows Setup & Local Deployment Guide

Follow these exact steps to set up and run the system on your Windows PC in **Visual Studio Code (VS Code)**.

### Step 1: Install Python
1. Download and install **Python 3.10** from [python.org](https://www.python.org/downloads/release/python-3100/).
2. **IMPORTANT**: During installation, ensure you check the box that says **"Add Python to PATH"**.

### Step 2: Open Project in VS Code
1. Launch **Visual Studio Code**.
2. Go to **File** → **Open Folder...** and select this directory (`moving eye`).

### Step 3: Initialize Virtual Environment & Install Dependencies
1. Open the built-in terminal in VS Code (**Ctrl + `** or **Terminal** → **New Terminal**).
2. Create a virtual environment by running:
   ```powershell
   python -m venv .venv
   ```
3. Activate the virtual environment:
   ```powershell
   .venv\Scripts\activate
   ```
4. Install all required dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

---

## 🔑 Configuration & API Keys

You can add your credentials directly at the top of the files.

### 1. CoinDCX API Keys (Optional for Paper Trading)
By default, paper trading is configured to run using only public endpoints (no API keys required). If you wish to enable private endpoints or switch to live mode:
1. Open [paper_trader.py](file:///d:/moving%20eye/paper_trader.py).
2. Locate the credentials section at the top of the file:
   ```python
   LIVE_MODE = False  # Set to True for live order placement
   COINDCX_API_KEY = "PASTE_YOUR_KEY_HERE"
   COINDCX_SECRET  = "PASTE_YOUR_SECRET_HERE"
   ```
3. Replace the placeholder values with your real CoinDCX API credentials.

### 2. Telegram Alert Notifications (Optional)
If you want to receive real-time execution alerts on Telegram:
1. Open [telegram_bot.py](file:///d:/moving%20eye/telegram_bot.py) or [paper_trader.py](file:///d:/moving%20eye/paper_trader.py).
2. Locate the Telegram fields at the top of the file:
   ```python
   TELEGRAM_BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"
   TELEGRAM_CHAT_ID   = "PASTE_YOUR_CHAT_ID_HERE"
   ```
3. Replace the placeholders with your actual Telegram Bot Token and Chat ID.
4. If left as-is, the program will silently skip Telegram initialization and output alerts directly to the console instead.

---

## 🚀 Running the Trading Engine

Once your virtual environment is active and configured, run the following command in the terminal to start paper trading:

```powershell
python paper_trader.py
```

### What to Expect:
- **REST Seeding**: The engine will download 500 historical candles for BTC/USDT (1H, 4H, 1D) via the CCXT interface.
- **WebSocket Streaming**: It connects to `stream.coindcx.com`.
  - *If the connection is successful*, you will see `[SUCCESS] WebSocket connected to stream.coindcx.com` and receive real-time ticks.
  - *If the connection fails or drops*, it prints a warning and falls back to **REST polling mode** (requesting public candlestick updates every 60 seconds).
- **Circuit Breakers**: The engine actively monitors risk parameters (-2% daily, -5% weekly, -10% monthly) and halts execution if thresholds are breached.
- **Fills & Logging**: Simulated entries and exits include 0.05% slippage and 0.04% commission. Detailed CSV outputs are saved to `logs/paper_trades.csv` and pipeline logs are written to `logs/paper_log.txt`.
