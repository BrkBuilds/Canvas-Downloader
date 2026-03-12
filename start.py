import sys
import os
import platform
import threading
import time
import webbrowser
import subprocess
from streamlit.web import cli as stcli
import logging

# Logging disabled - no debug log file needed
logging.disable(logging.CRITICAL)

# ── Shared Utilities ──────────────────────────────────────────────

_STREAMLIT_PORT = "8501"
_STREAMLIT_URL = f"http://localhost:{_STREAMLIT_PORT}"
_HEALTH_ENDPOINT = f"{_STREAMLIT_URL}/_stcore/health"


def resolve_path(path):
    """Resolve path for frozen (PyInstaller) vs normal execution."""
    if getattr(sys, "frozen", False):
        basedir = sys._MEIPASS
    else:
        basedir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(basedir, path)


def _start_streamlit_thread():
    """Start the Streamlit server in a daemon thread.

    Monkeypatches ``signal.signal`` because Streamlit tries to register
    signal handlers, which raises ``ValueError`` from a non-main thread.
    """
    try:
        app_path = resolve_path("app.py")
        if not os.path.exists(app_path):
            return

        sys.argv = [
            "streamlit", "run", app_path,
            "--global.developmentMode=false",
            f"--server.port={_STREAMLIT_PORT}",
            "--server.headless=true",
            "--theme.base=dark",
            "--theme.primaryColor=#0072CE",
        ]

        import signal
        if threading.current_thread() is not threading.main_thread():
            signal.signal = lambda *args, **kwargs: None

        stcli.main()
    except SystemExit:
        pass
    except Exception:
        pass


def _wait_for_server(timeout_seconds: int = 60) -> bool:
    """Block until the Streamlit health endpoint responds 200, or timeout."""
    import urllib.request

    for _ in range(timeout_seconds):
        try:
            with urllib.request.urlopen(_HEALTH_ENDPOINT, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


# ── Windows Launcher (Tkinter) ────────────────────────────────────

class CanvasLauncher:
    """Tkinter-based launcher window for Windows.

    Shows a progress bar while Streamlit boots, then displays the server
    URL and an "Open Browser" button.  Closing the window exits the app
    and kills the Streamlit daemon thread.
    """

    def __init__(self):
        import tkinter as tk
        from tkinter import ttk

        self.root = tk.Tk()
        self.root.title("Canvas Downloader")
        self.root.geometry("400x250")
        self.root.resizable(False, False)

        # Window icon
        try:
            self.root.iconbitmap(resolve_path("assets/icon.ico"))
        except Exception:
            pass

        self.style = ttk.Style()
        _font = "Segoe UI"
        self.style.configure("TLabel", font=(_font, 10))
        self.style.configure("Header.TLabel", font=(_font, 12, "bold"))

        self.main_frame = ttk.Frame(self.root, padding="20")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            self.main_frame, text="Canvas Downloader", style="Header.TLabel"
        ).pack(pady=(0, 20))

        self.status_var = tk.StringVar(value="Starting application...")
        ttk.Label(
            self.main_frame, textvariable=self.status_var, wraplength=360
        ).pack(pady=10)

        self.progress = ttk.Progressbar(self.main_frame, mode='indeterminate')
        self.progress.pack(fill=tk.X, pady=10)
        self.progress.start(10)

        ttk.Label(
            self.main_frame,
            text="Close this window to stop the application",
            foreground="gray",
        ).pack(side=tk.BOTTOM, pady=10)

        self.server_started = False

        # Background threads
        threading.Thread(target=_start_streamlit_thread, daemon=True).start()
        threading.Thread(target=self._monitor_server, daemon=True).start()

    def _monitor_server(self):
        """Poll the health endpoint and update the UI when ready."""
        if _wait_for_server():
            self.root.after(0, self._on_server_ready)

    def _on_server_ready(self):
        import tkinter as tk
        from tkinter import ttk

        if self.server_started:
            return
        self.server_started = True

        self.status_var.set(f"Application running — visit {_STREAMLIT_URL}")
        self.progress.stop()
        self.progress.pack_forget()

        ttk.Button(
            self.main_frame,
            text="Open Browser",
            command=lambda: webbrowser.open(_STREAMLIT_URL),
        ).pack(pady=5)

        webbrowser.open(_STREAMLIT_URL)

    def run(self):
        self.root.mainloop()


# ── macOS Launcher (AppleScript) ──────────────────────────────────

def _run_macos_launcher():
    """Headless launcher for macOS ``.app`` bundles.

    1. Starts Streamlit in a daemon thread.
    2. Waits for the health check, then opens the browser.
    3. Displays a native AppleScript dialog as the lifecycle controller.
       The dialog blocks the main thread — when the user clicks
       "Stop Server", Python falls through to ``sys.exit(0)`` and the
       daemon thread is killed automatically.
    """
    # 1. Start Streamlit
    threading.Thread(target=_start_streamlit_thread, daemon=True).start()

    # 2. Wait for server and open browser
    if _wait_for_server():
        webbrowser.open(_STREAMLIT_URL)

    # 3. Block main thread with a native AppleScript dialog
    #    This mirrors the Tkinter window's role on Windows — giving
    #    the user a tangible "parent" they can dismiss to stop the app.
    _applescript = (
        'tell application "System Events"\n'
        '    activate\n'
        '    display dialog "Canvas Downloader is running in your browser.\\n\\n'
        'Visit: ' + _STREAMLIT_URL + '\\n\\n'
        'Click \\"Stop Server\\" to quit the application." '
        'with title "Canvas Downloader" '
        'buttons {"Open Browser", "Stop Server"} '
        'default button "Stop Server" '
        'with icon note\n'
        'end tell'
    )

    # Loop: "Open Browser" re-shows the dialog; "Stop Server" exits.
    while True:
        try:
            result = subprocess.run(
                ['osascript', '-e', _applescript],
                capture_output=True, text=True,
            )
            # osascript returns the button text on stdout
            chosen = result.stdout.strip()
            if chosen == "button returned:Open Browser":
                webbrowser.open(_STREAMLIT_URL)
                continue  # Re-show the dialog
            else:
                # "Stop Server" or dialog was force-closed (non-zero exit)
                break
        except Exception:
            break  # osascript not available — fall through to exit


# ── Entry Point ───────────────────────────────────────────────────

if __name__ == "__main__":
    os.environ["STREAMLIT_SERVER_PORT"] = _STREAMLIT_PORT
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    if platform.system() == 'Darwin':
        _run_macos_launcher()
    else:
        app = CanvasLauncher()
        app.run()

    sys.exit(0)
