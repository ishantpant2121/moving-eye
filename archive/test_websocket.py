# test_websocket.py
import sys
import time
import requests
import websocket
import socketio

def test_http_get():
    url = "https://api.coindcx.com/exchange/ticker"
    print(f"Testing HTTP GET to {url}...")
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            print(f"HTTP GET SUCCESS (Status: {response.status_code})")
            return True
        else:
            print(f"HTTP GET FAILURE (Status: {response.status_code})")
            return False
    except Exception as e:
        print(f"HTTP GET FAILURE: {e}")
        return False

def test_raw_websocket():
    url = "wss://stream.coindcx.com"
    print(f"\nTesting raw WebSocket connection to {url}...")
    ws = websocket.WebSocket()
    ws.settimeout(10)
    try:
        ws.connect(url)
        print("Raw WebSocket SUCCESS")
        ws.close()
        return True
    except Exception as e:
        print(f"Raw WebSocket FAILURE: {e}")
        return False

def test_socketio():
    url = "https://stream.coindcx.com"
    print(f"\nTesting Socket.IO connection to {url}...")
    sio = socketio.Client()
    connected = [False]
    error_msg = [None]
    
    @sio.event
    def connect():
        connected[0] = True
        
    @sio.event
    def connect_error(data):
        error_msg[0] = str(data)

    def run():
        try:
            sio.connect(url, transports=["websocket"], wait_timeout=10)
        except Exception as e:
            error_msg[0] = str(e)
            
    thread = threading.Thread(target=run)
    thread.start()
    
    # Wait for up to 10 seconds
    start_time = time.time()
    while time.time() - start_time < 10:
        if connected[0]:
            break
        if error_msg[0] is not None:
            break
        time.sleep(0.1)
        
    if connected[0]:
        print("Socket.IO SUCCESS")
        sio.disconnect()
        return True
    else:
        err = error_msg[0] or "Timeout after 10 seconds"
        print(f"Socket.IO FAILURE: {err}")
        try:
            sio.disconnect()
        except:
            pass
        return False

if __name__ == "__main__":
    import threading
    print("=== COINDCX CONNECTIVITY TEST ===")
    http_res = test_http_get()
    ws_res = test_raw_websocket()
    sio_res = test_socketio()
    print("\n=== SUMMARY ===")
    print(f"HTTP GET: {'SUCCESS' if http_res else 'FAILURE'}")
    print(f"Raw WebSocket: {'SUCCESS' if ws_res else 'FAILURE'}")
    print(f"Socket.IO: {'SUCCESS' if sio_res else 'FAILURE'}")
