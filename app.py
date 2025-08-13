print("[launcher] starting application", flush=True)
import http.cookiejar as cookiejar
from ctypes import windll
import urllib.request
import urllib.error
import subprocess
import threading
import webview
import base64
import socket
import time
import sys
import os

IP = "http://127.0.0.1:3478"
HEALTH_URL = IP + "/health"
CONFIG_PATH = os.path.join(os.environ["LOCALAPPDATA"], "Rately", "filetypeshi")

SERVER_PROC = None
SERVER_PORT_LOCK = 51235

os.makedirs(CONFIG_PATH, exist_ok=True)
COOKIES_FILE = os.path.join(CONFIG_PATH, "cookies.txt")
COOKIE_JAR = cookiejar.MozillaCookieJar(COOKIES_FILE)
try:
    if os.path.exists(COOKIES_FILE):
        COOKIE_JAR.load(ignore_discard=True, ignore_expires=True)
except Exception:
    COOKIE_JAR = cookiejar.MozillaCookieJar(COOKIES_FILE)

URL_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))
urllib.request.install_opener(URL_OPENER)

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

def _save_cookies():
    try:
        COOKIE_JAR.save(ignore_discard=True, ignore_expires=True)
    except Exception:
        pass

def on_closed():
    global SERVER_PROC
    _save_cookies()
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

class Bridge:
    def save_file(self, suggested_name: str, b64_png: str) -> bool:
        try:
            if b64_png.startswith('data:'):
                b64_png = b64_png.split(',', 1)[1]
            data = base64.b64decode(b64_png)

            win = webview.windows[0]
            if not suggested_name.lower().endswith('.png'):
                suggested_name = suggested_name + '.png'

            path = win.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=suggested_name,
                file_types=('PNG (*.png)',)
            )
            if not path:
                return False
            out_path = path if isinstance(path, str) else path[0]
            with open(out_path, 'wb') as f:
                f.write(data)
            return True
        except Exception as e:
            print(f"[launcher] save_file failed: {e}", flush=True)
            return False

if __name__ == "__main__":
    try:
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
        win = webview.create_window("Rately", IP, width=1080, height=800, js_api=Bridge())
        win.events.closed += on_closed

        hwnd = windll.kernel32.GetConsoleWindow()
        if hwnd:
            windll.user32.ShowWindow(hwnd, 6)

        try:
            webview.start(private_mode=False, storage_path=CONFIG_PATH, debug=False)
        finally:
            _save_cookies()
    except KeyboardInterrupt:
        _save_cookies()
        sys.exit(0)