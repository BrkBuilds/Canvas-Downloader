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
_STREAMLIT_URL = f"http://127.0.0.1:{_STREAMLIT_PORT}"
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
            "--server.address=127.0.0.1",
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
        import webview
        
        # Start Streamlit in the background
        threading.Thread(target=_start_streamlit_thread, daemon=True).start()
        
        # Wait for Streamlit to be ready
        _wait_for_server()
        
        # Create and start the native window
        webview.create_window('Canvas Downloader', _STREAMLIT_URL, maximized=True)
        webview.start()

    sys.exit(0)
