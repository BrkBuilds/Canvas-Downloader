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
import threading
import time
import logging

from streamlit.web import cli as stcli

# Logging disabled - no debug log file needed for the launcher.
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
    except Exception:
        pass
    finally:
        # Restore the genuine signal.signal in case of reuse.
        signal.signal = _original_signal


def _wait_for_server(timeout_seconds: int = 60) -> bool:
    """Block until the Streamlit health endpoint responds 200, or timeout."""
    import urllib.request

    for _ in range(timeout_seconds * 10):
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
        # ── Windows: unchanged pywebview flow ──
        import webview
        
        # 1. Start Streamlit in a daemonized background thread.
        threading.Thread(target=_start_streamlit_server, daemon=True).start()

        # 2. Wait for the health endpoint before opening the native window.
        if not _wait_for_server():
            logging.warning("Streamlit server did not respond in time; opening window anyway.")

        # 3. Create and start the native desktop window.
        webview.create_window('Canvas Downloader', _STREAMLIT_URL, maximized=True, min_size=(1024, 700))
        webview.start()

        sys.exit(0)
