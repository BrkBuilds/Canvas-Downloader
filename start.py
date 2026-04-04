"""
start.py — Unified application launcher for Canvas Downloader.

Architecture (Phase 2 macOS Parity Remediation — F-01, F-02, F-20):
  Both Windows and macOS now use ``pywebview`` for a native desktop window.
  The legacy AppleScript lifecycle dialog has been removed entirely.

Threading model:
  1. Streamlit server starts in a daemonized background thread.
  2. The main thread waits for the health endpoint, then creates
     the native ``pywebview`` window.
  3. ``webview.start()`` runs the GUI event loop on the main thread
     (required by macOS Cocoa/WebKit).
  4. When the user closes the window, ``webview.start()`` returns,
     Python falls through to ``sys.exit(0)``, and the daemon thread
     is killed automatically.
"""

import sys
import os
import threading
import time
import logging

from streamlit.web import cli as stcli

# Logging disabled — no debug log file needed for the launcher.
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


def _start_streamlit_server():
    """Start the Streamlit server (runs in a daemon thread).

    Monkeypatches ``signal.signal`` because Streamlit tries to register
    signal handlers, which raises ``ValueError`` from a non-main thread.
    The monkeypatch is scoped: the original ``signal.signal`` is saved
    and restored if this function ever returns (defensive).
    """
    import signal
    _original_signal = signal.signal

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

        # Scope the monkeypatch: Streamlit's threading.Thread context
        # cannot register signal handlers; suppress harmlessly.
        if threading.current_thread() is not threading.main_thread():
            signal.signal = lambda *_args, **_kwargs: None

        stcli.main()

    except SystemExit:
        pass
    except Exception:
        pass
    finally:
        # Restore the genuine signal.signal in case of reuse.
        signal.signal = _original_signal


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


# ── Entry Point ───────────────────────────────────────────────────

if __name__ == "__main__":
    os.environ["STREAMLIT_SERVER_PORT"] = _STREAMLIT_PORT
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    import webview

    # 1. Start Streamlit in a daemonized background thread.
    threading.Thread(target=_start_streamlit_server, daemon=True).start()

    # 2. Wait for the health endpoint before opening the native window.
    _wait_for_server()

    # 3. Create and start the native desktop window.
    #    - Windows: Uses Edge/Chromium via pywebview WinForms backend.
    #    - macOS:   Uses WebKit via pywebview Cocoa backend.
    #    webview.start() blocks the main thread (required by macOS Cocoa).
    webview.create_window('Canvas Downloader', _STREAMLIT_URL, maximized=True)
    webview.start()

    sys.exit(0)
