"""
start.py - Unified application launcher for Canvas Downloader.

Architecture - platform split:
  Windows: pywebview wraps the Streamlit server in a native EdgeChromium
           desktop window.  The main thread runs ``webview.start()``.
  macOS:   CustomTkinter (macos_controller.CanvasController) shows a small
           native status window.  Chrome opens the Streamlit UI as a
           dedicated browser window.  tkinter's mainloop runs on the main
           thread (required by Cocoa).

Threading model (both platforms):
  1. Streamlit server starts in a daemonised background thread.
     ``signal.signal`` is monkeypatched for the duration because Streamlit
     tries to register signal handlers, which raises ``ValueError`` from a
     non-main thread.
  2. A second daemon thread polls the health endpoint.
  3. Once healthy, the appropriate UI is opened (pywebview window on
     Windows; Chrome + status controller on macOS).
  4. When the user closes the controller/window the process exits and the
     daemon thread is killed automatically.
"""

import sys
import os
import socket
import threading
import time
import logging

from streamlit.web import cli as stcli

logger = logging.getLogger(__name__)

# ── Port Discovery ────────────────────────────────────────────────


def _find_free_port(preferred: int = 8501) -> int:
    """Return the preferred port if free, otherwise the first free port in 8502-8519."""
    for port in [preferred, *range(8502, 8520)]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    # Last resort: let the OS assign any available port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


_STREAMLIT_PORT = str(_find_free_port())
_STREAMLIT_URL = f"http://127.0.0.1:{_STREAMLIT_PORT}"
_HEALTH_ENDPOINT = f"{_STREAMLIT_URL}/_stcore/health"

# Event set by _start_streamlit_server on fatal startup failure
_server_failed_event = threading.Event()


# ── Shared Utilities ──────────────────────────────────────────────

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
            logger.error(f"app.py not found at {app_path}; cannot start Streamlit server.")
            _server_failed_event.set()
            return

        sys.argv = [
            "streamlit", "run", app_path,
            "--global.developmentMode=false",
            f"--server.port={_STREAMLIT_PORT}",
            "--server.address=127.0.0.1",
            "--server.headless=true",
            "--theme.base=dark",
            "--theme.primaryColor=#0072CE",
            "--client.toolbarMode=minimal",
            "--browser.gatherUsageStats=false",
        ]

        # Scope the monkeypatch: Streamlit's threading.Thread context
        # cannot register signal handlers; suppress harmlessly.
        if threading.current_thread() is not threading.main_thread():
            signal.signal = lambda *_args, **_kwargs: None

        stcli.main()

    except SystemExit:
        pass
    except Exception as e:
        logger.error(f"Streamlit server encountered a fatal error: {e}")
        _server_failed_event.set()
    finally:
        # Restore the genuine signal.signal in case of reuse.
        signal.signal = _original_signal


def _wait_for_server(timeout_seconds: int = 60) -> bool:
    """Block until the Streamlit health endpoint responds 200, timeout, or server fails."""
    import urllib.request

    for _ in range(timeout_seconds * 10):
        if _server_failed_event.is_set():
            logger.error("Streamlit server failed to start; aborting wait.")
            return False
        try:
            with urllib.request.urlopen(_HEALTH_ENDPOINT, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


# ── Entry Point ───────────────────────────────────────────────────

if __name__ == "__main__":
    os.environ["STREAMLIT_SERVER_PORT"] = _STREAMLIT_PORT
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    import platform as _platform

    if _platform.system() == 'Darwin':
        # ── macOS: BYOB + CustomTkinter Controller ──
        from macos_controller import CanvasController

        # 1. Start Streamlit in daemon thread
        threading.Thread(target=_start_streamlit_server, daemon=True).start()

        # 2. Boot UI and let it handle the health check / browser launch
        controller = CanvasController(
            streamlit_url=_STREAMLIT_URL,
            on_quit=lambda: sys.exit(0),
        )

        # 3. Background health check and launch sequence
        def _boot_sequence():
            if _wait_for_server():
                controller.set_state('ready')
                # open_chrome() uses Tkinter internals; must run on the main thread (H-10).
                controller.app.after(0, controller.open_chrome)
            else:
                controller.set_state('error', 'Server failed to start', 'Please try closing and reopening the app.')

        # Let the controller restart the boot sequence if "Try Again" is clicked
        controller.retry_callback = _boot_sequence

        threading.Thread(target=_boot_sequence, daemon=True).start()

        # 4. tkinter mainloop on main thread (required by macOS Cocoa)
        controller.run()
        sys.exit(0)

    else:
        # ── Windows: pywebview flow ──
        import webview

        # 1. Start Streamlit in a daemonized background thread.
        threading.Thread(target=_start_streamlit_server, daemon=True).start()

        # 2. Wait for the health endpoint before opening the native window.
        server_ok = _wait_for_server()

        # 3. Create and start the native desktop window.
        if server_ok:
            webview.create_window('Canvas Downloader', _STREAMLIT_URL, maximized=True, min_size=(1024, 700))
        else:
            # Show a user-friendly error page instead of a blank/broken window.
            _reason = (
                'The application server encountered a fatal error during startup.'
                if _server_failed_event.is_set()
                else 'The application server did not respond in time.'
            )
            _ERROR_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Canvas Downloader — Startup Error</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f1117; color: #e0e0e0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; padding: 2rem;
    }}
    .card {{
      background: #1e2130; border: 1px solid #2d3148;
      border-radius: 12px; padding: 2.5rem 3rem;
      max-width: 560px; text-align: center;
    }}
    .icon {{ font-size: 3rem; margin-bottom: 1rem; }}
    h1 {{ font-size: 1.4rem; font-weight: 600; color: #ff6b6b; margin-bottom: 0.75rem; }}
    p  {{ font-size: 0.95rem; color: #9ca3af; line-height: 1.6; margin-bottom: 0.5rem; }}
    .hint {{ font-size: 0.8rem; color: #4b5563; margin-top: 1.25rem; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⚠️</div>
    <h1>Canvas Downloader failed to start</h1>
    <p>{_reason}</p>
    <p>Please close this window and try reopening the app.<br>
       If the problem persists, make sure no other instance is already running.</p>
    <p class="hint">Need help? Visit the support page or check the application logs.</p>
  </div>
</body>
</html>"""
            webview.create_window('Canvas Downloader', html=_ERROR_HTML, min_size=(640, 420))
            logger.error(f"Startup failed — {_reason}")

        webview.start()
        sys.exit(0)
