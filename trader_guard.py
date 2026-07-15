"""
trader_guard.py
===============
Guard script invoked by the Windows Scheduled Task.

Uses a Local session named mutex to prevent multiple instances of trader_guard.py.
Launches paper_trader.py and waits for it to finish.
"""

import os
import sys
import ctypes
import subprocess
import time
from datetime import datetime

BASE_DIR = r"d:\moving eye"
PYTHON   = os.path.join(BASE_DIR, r".venv\Scripts\python.exe")
SCRIPT   = os.path.join(BASE_DIR, "paper_trader.py")
LOG_FILE = os.path.join(BASE_DIR, "logs", "stdout_stderr.log")

os.chdir(BASE_DIR)
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

def _acquire_local_mutex():
    MUTEX_NAME = "Local\\ApexBotPaperTrader_Guard_Mutex"
    ERROR_ALREADY_EXISTS = 183

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    err = kernel32.GetLastError()

    if err == ERROR_ALREADY_EXISTS:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [GUARD] Another trader_guard.py is already running. Exiting.")
        sys.stdout.flush()
        sys.exit(0)
    return handle

def _release_local_mutex(handle):
    if handle:
        kernel32 = ctypes.windll.kernel32
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)

def main():
    # Hold the mutex for the entire duration of the guard process
    _mutex_handle = _acquire_local_mutex()
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [GUARD] No duplicate guard running. Starting paper_trader.py...")
        sys.stdout.flush()

        log_fh = open(LOG_FILE, "a", encoding="utf-8", buffering=1)

        p = subprocess.Popen(
            [PYTHON, "-u", SCRIPT],
            cwd=BASE_DIR,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )

        print(f"[GUARD] Launched paper_trader.py with PID {p.pid}. Waiting for it to finish...")
        sys.stdout.flush()

        p.wait()
        
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [GUARD] paper_trader.py (PID {p.pid}) exited with code {p.returncode}.")
        sys.exit(p.returncode if p.returncode is not None else 0)
    finally:
        _release_local_mutex(_mutex_handle)
        print("[GUARD] Guard mutex released and closed.")

if __name__ == "__main__":
    main()
