# websocket_client.py
"""
WebSocket client for streaming real-time candlestick data from CoinDCX.
Manages Socket.IO connection, channel subscription, heartbeats.
If WebSocket connection fails or hangs, falls back to REST API polling.
"""

import time
import json
import threading
import socketio
import config

class CoinDCXWebSocketClient:
    """
    WebSocket client wrapper for CoinDCX using python-socketio with a REST polling fallback.
    """

    def __init__(self, on_candle_update_cb):
        """
        Initializes the WebSocket client.
        :param on_candle_update_cb: Callback function invoked on candle update.
                                     Signature: callback(symbol, timeframe, candle)
                                     where candle is [timestamp_ms, open, high, low, close, volume]
        """
        self.on_candle_update_cb = on_candle_update_cb
        
        self.should_connect = True
        self.connection_thread = None
        self.polling_thread = None
        self.connected_event = threading.Event()
        
        self.polling_lock = threading.Lock()
        self.polling_active = False
        
        self.sio = None
        self._recreate_sio()

    def _recreate_sio(self):
        if self.sio:
            try:
                self.sio.disconnect()
            except Exception:
                pass
        self.sio = socketio.Client(reconnection=False)
        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("connect_error", self._on_connect_error)
        self.sio.on("candlestick", self._on_candlestick)

    def start(self):
        """
        Starts the background connection thread.
        """
        self.should_connect = True
        self.connection_thread = threading.Thread(target=self._connection_loop, daemon=True)
        self.connection_thread.start()

    def stop(self):
        """
        Stops the connection loop, REST polling, and disconnects from the server.
        """
        self.should_connect = False
        self._stop_rest_polling()
        if self.sio and self.sio.connected:
            try:
                self.sio.disconnect()
            except Exception:
                pass
        print("WebSocket client stopped.")

    def _connection_loop(self):
        """
        Background loop managing the connection state.
        Tries WebSocket connection with a 10 second timeout first.
        Falls back to REST polling if the connection fails or drops.
        Periodically tests the WebSocket connection to automatically restore it.
        """
        while self.should_connect:
            self.connected_event.clear()

            if self.sio and self.sio.connected:
                # WebSocket is connected! Monitor it.
                while self.should_connect and self.sio.connected:
                    time.sleep(1.0)
                if not self.should_connect:
                    break
                print("[WARNING] WebSocket connection lost. Switching to REST polling fallback...")
                self._start_rest_polling()

            if not self.should_connect:
                break

            print("[INFO] Attempting to connect to WebSocket...")
            self._recreate_sio()

            def attempt_connect():
                try:
                    self.sio.connect(config.WEBSOCKET_URL, transports=["websocket"], wait_timeout=10)
                except Exception as e:
                    print(f"[ERROR] WebSocket connect exception: {e}")
                    import telemetry
                    telemetry.capture_exception(e)

            connect_thread = threading.Thread(target=attempt_connect, daemon=True)
            connect_thread.start()

            # Wait up to 10 seconds for the connect event
            success = self.connected_event.wait(timeout=10.0)
            time.sleep(0.5)

            if success and self.sio.connected:
                print("[SUCCESS] Connected/Reconnected to WebSocket successfully.")
                self._stop_rest_polling()
            else:
                print("[ERROR] WebSocket connection failed to establish.")
                try:
                    self.sio.disconnect()
                except Exception:
                    pass

                # If REST polling is not yet running, start it
                self._start_rest_polling()

                # Sleep/Wait for 120 seconds before attempting reconnection, checking should_connect
                print("[INFO] WebSocket client will retry connecting in 120 seconds...")
                for _ in range(120):
                    if not self.should_connect:
                        break
                    time.sleep(1.0)

    def _start_rest_polling(self):
        """
        Starts the REST API polling fallback thread.
        """
        with self.polling_lock:
            if self.polling_active:
                return
            self.polling_active = True
            print("[FALLBACK] Using REST polling mode - 60s intervals")
            self.polling_thread = threading.Thread(target=self._rest_polling_loop, daemon=True)
            self.polling_thread.start()

    def _stop_rest_polling(self):
        """
        Stops the REST API polling fallback thread.
        """
        with self.polling_lock:
            if not self.polling_active:
                return
            self.polling_active = False
            print("[INFO] Stopping REST polling fallback...")

    def _rest_polling_loop(self):
        """
        Polls the REST API every 60 seconds to fetch and push candle updates.
        """
        from exchange import coindcx
        try:
            exchange_client = coindcx()
        except Exception as e:
            print(f"[ERROR] Failed to instantiate exchange client for polling: {e}")
            import telemetry
            telemetry.capture_exception(e)
            return

        while self.should_connect:
            with self.polling_lock:
                if not self.polling_active:
                    break

            start_time = time.time()
            for symbol in config.SYMBOLS:
                for tf in config.TIMEFRAME_MAP:
                    with self.polling_lock:
                        if not self.polling_active:
                            break
                    try:
                        # Fetch the last 5 candles to cover gaps and update the ongoing/latest candle
                        candles = exchange_client.fetch_ohlcv(symbol, tf, limit=5)
                        for candle in candles:
                            with self.polling_lock:
                                if not self.polling_active:
                                    break
                            self.on_candle_update_cb(symbol, tf, candle)
                    except Exception as e:
                        print(f"[ERROR] REST Polling failed for {symbol} ({tf}): {e}")
                        import telemetry
                        telemetry.capture_exception(e)

            # Wait for 60 seconds, checking active flag frequently
            elapsed = time.time() - start_time
            sleep_time = max(1.0, 60.0 - elapsed)
            for _ in range(int(sleep_time)):
                with self.polling_lock:
                    if not self.polling_active or not self.should_connect:
                        break
                time.sleep(1.0)

    def _on_connect(self):
        """
        Event handler triggered when connection is successfully established.
        """
        print("[SUCCESS] WebSocket connected to stream.coindcx.com")
        self.connected_event.set()
        
        # Start the background heartbeat ping loop
        self.sio.start_background_task(self._ping_loop)
        
        # Subscribe to channels for all configured symbols and timeframes
        for symbol in config.SYMBOLS:
            coindcx_symbol = symbol.replace("/", "_")
            if not coindcx_symbol.startswith("B-"):
                coindcx_symbol = f"B-{coindcx_symbol}"
                
            for tf, tf_info in config.TIMEFRAME_MAP.items():
                ws_interval = tf_info["ws_interval"]
                channel_name = f"{coindcx_symbol}_{ws_interval}-futures"
                
                # Emit join event to subscribe to the channel
                self.sio.emit("join", {"channelName": channel_name})
                print(f"Subscribed to channel: {channel_name}")

    def _on_disconnect(self):
        """
        Event handler triggered on connection loss.
        """
        print("[WARNING] WebSocket disconnected from server.")

    def _on_connect_error(self, data):
        """
        Event handler triggered on connection error.
        """
        print(f"[ERROR] WebSocket connection error: {data}")
        import telemetry
        telemetry.capture_exception(RuntimeError(f"WebSocket connection error: {data}"))

    def _ping_loop(self):
        """
        Sends application-level ping messages to the server every 25 seconds 
        to keep the Socket.IO channels alive.
        """
        print("Heartbeat ping loop started.")
        # Wait a small moment to ensure sio.connected is fully set to True
        self.sio.sleep(1.0)
        while self.sio.connected:
            try:
                self.sio.emit("ping", {"data": "Ping message"})
            except Exception as e:
                print(f"[ERROR] Failed to send heartbeat ping: {e}")
                import telemetry
                telemetry.capture_exception(e)
            self.sio.sleep(config.HEARTBEAT_INTERVAL)
        print("Heartbeat ping loop stopped.")

    def _on_candlestick(self, data):
        """
        Event handler triggered when candlestick updates are pushed.
        Parses raw CoinDCX socket data and invokes callback.
        """
        try:
            if not data or "data" not in data:
                return

            # The socket data is structured with a nested JSON string in 'data' field
            payload = json.loads(data["data"])
            raw_candles = payload.get("data", [])
            if not raw_candles:
                return

            # Take the latest candle update from the payload list
            candle_info = raw_candles[0]

            # Map the pair identifier back to standard symbol (e.g. B-BTC_USDT -> BTC/USDT)
            coindcx_pair = candle_info["pair"]
            symbol = coindcx_pair.replace("B-", "").replace("_", "/")

            # Resolve the timeframe from the interval field
            interval = payload.get("i")
            timeframe = None
            for tf, tf_info in config.TIMEFRAME_MAP.items():
                if tf_info["ws_interval"] == interval:
                    timeframe = tf
                    break

            if timeframe is None:
                return  # Unsupported timeframe

            # Normalize values. 
            timestamp_ms = int(candle_info["open_time"] * 1000)
            o = float(candle_info["open"])
            h = float(candle_info["high"])
            l = float(candle_info["low"])
            c = float(candle_info["close"])
            v = float(candle_info["volume"])

            normalized_candle = [timestamp_ms, o, h, l, c, v]

            # Trigger callback with parsed candle data
            self.on_candle_update_cb(symbol, timeframe, normalized_candle)

        except Exception as e:
            print(f"[ERROR] Exception in WebSocket candlestick parsing: {e}")
            import telemetry
            telemetry.capture_exception(e)
