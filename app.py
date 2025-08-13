print("[launcher] starting application", flush=True)
from ctypes import windll
import urllib.request
import urllib.error
import subprocess
import threading
import webview
import socket
import time
import sys
import os

IP = "http://127.0.0.1:3478"
HEALTH_URL = IP + "/health"

SERVER_PROC = None
SERVER_PORT_LOCK = 51235

def already_running() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", SERVER_PORT_LOCK))
        s.listen(1)
        globals()["_instance_lock_socket"] = s
        return False
    except OSError:
        return True

def run_flask():
    global SERVER_PROC
    if getattr(sys, "frozen", False):
        try:
            import webhost
            print("[launcher] starting backend (in-process)", flush=True)
            webhost.app.run(host="127.0.0.1", port=3478, debug=False, use_reloader=False)
        except Exception as e:
            print(f"[launcher] backend failed in-process: {e}", flush=True)
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        webhost_path = os.path.join(script_dir, "webhost.py")
        if not os.path.exists(webhost_path):
            print(f"[launcher] ERROR: {webhost_path} not found.", flush=True)
            return
        FLASK_CMD = [sys.executable, webhost_path, "--no-reload"]
        print(f"[launcher] starting backend subprocess: {FLASK_CMD}", flush=True)
        SERVER_PROC = subprocess.Popen(FLASK_CMD, cwd=script_dir, stdout=sys.stdout, stderr=sys.stderr)
        SERVER_PROC.wait()

def on_closed():
    global SERVER_PROC
    if SERVER_PROC and SERVER_PROC.poll() is None:
        try:
            SERVER_PROC.terminate()
            for _ in range(20):
                if SERVER_PROC.poll() is not None:
                    break
                time.sleep(0.1)
            if SERVER_PROC.poll() is None:
                SERVER_PROC.kill()
        except Exception:
            pass

def wait_for_health(url: str, timeout_per_try: float = 10.0, interval: float = 0.5):
    while True:
        try:
            req = urllib.request.Request(url, data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=timeout_per_try) as resp:
                if resp.status == 200:
                    print("[launcher] health OK", flush=True)
                    return
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            pass
        time.sleep(interval)

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        multiprocessing.set_start_method("spawn")
    except RuntimeError:
        pass

    FROZEN = getattr(sys, "frozen", False)

    if FROZEN and already_running():
        print("[launcher] another instance is already running; exiting.", flush=True)
        sys.exit(0)

    print("[launcher] Initializing backend server...", flush=True)
    threading.Thread(target=run_flask, daemon=True).start()

    wait_for_health(HEALTH_URL, timeout_per_try=10.0, interval=0.5)

    print("[launcher] Initializing webview...", flush=True)
    win = webview.create_window("Rately", IP, width=1080, height=800)
    win.events.closed += on_closed
    
    hwnd = windll.kernel32.GetConsoleWindow()
    if hwnd:
        windll.user32.ShowWindow(hwnd, 6)
        
    webview.start()
    
