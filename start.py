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

Port-race handling (M-4):
  _find_free_port() probes a port and immediately releases the socket, so
  there is a TOCTOU window before Streamlit binds it.  On Windows the
  launcher retries automatically (up to _MAX_LAUNCH_ATTEMPTS times) with a
  freshly-probed port if the health check times out.  On macOS the user can
  click "Try Again" in the controller window.
"""

import sys
import os
import socket
import threading
import time
import logging

from streamlit.web import cli as stcli

logger = logging.getLogger(__name__)

_MAX_LAUNCH_ATTEMPTS = 3   # Windows auto-retry limit
_HEALTH_TIMEOUT_SECS  = 60 # seconds to wait for each attempt


# ── Port Discovery ────────────────────────────────────────────────

def _find_free_port(preferred: int = 8501) -> int:
    """Return the preferred port if free, otherwise the first free port in 8502-8600."""
    for port in [preferred, *range(8502, 8601)]:
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


# ── Shared Utilities ──────────────────────────────────────────────

def resolve_path(path):
    """Resolve path for frozen (PyInstaller) vs normal execution."""
    if getattr(sys, "frozen", False):
        basedir = sys._MEIPASS
    else:
        basedir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(basedir, path)


def _start_streamlit_server(port: str, failed_event: threading.Event) -> None:
    """Start the Streamlit server (runs in a daemon thread).

    Monkeypatches ``signal.signal`` because Streamlit tries to register
    signal handlers, which raises ``ValueError`` from a non-main thread.
    The monkeypatch is scoped: the original ``signal.signal`` is saved
    and restored when this function returns.

    Sets ``failed_event`` on any fatal error so callers can detect
    failure without polling sys.exit.
    """
    import signal
    _original_signal = signal.signal

    try:
        app_path = resolve_path("app.py")
        if not os.path.exists(app_path):
            logger.error(f"app.py not found at {app_path}; cannot start Streamlit server.")
            failed_event.set()
            return

        sys.argv = [
            "streamlit", "run", app_path,
            "--global.developmentMode=false",
            f"--server.port={port}",
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
        failed_event.set()
    finally:
        signal.signal = _original_signal


def _wait_for_server(health_url: str, failed_event: threading.Event,
                     timeout_seconds: int = _HEALTH_TIMEOUT_SECS) -> bool:
    """Block until the Streamlit health endpoint responds 200, the server
    signals failure, or the timeout expires."""
    import urllib.request

    # Bypass any system/corporate proxy for the 127.0.0.1 health check.
    # University VPN/proxy setups that lack a localhost exception would
    # otherwise route the probe through the proxy and report a phantom
    # "failed to start" even though the local server is healthy.
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    for _ in range(timeout_seconds * 10):
        if failed_event.is_set():
            logger.error("Streamlit server failed to start; aborting wait.")
            return False
        try:
            with _opener.open(health_url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def _launch_streamlit(port: int | None = None) -> tuple[bool, str, threading.Event]:
    """Probe a free port, start Streamlit, and return (ok, base_url, failed_event).

    Does NOT retry — callers handle retry policy.  ``failed_event`` remains
    accessible so callers can distinguish a port-race timeout from a true crash.
    """
    if port is None:
        port = _find_free_port()
    port_str = str(port)
    url = f"http://127.0.0.1:{port_str}"
    health_url = f"{url}/_stcore/health"
    failed_event = threading.Event()

    os.environ["STREAMLIT_SERVER_PORT"] = port_str

    threading.Thread(
        target=_start_streamlit_server,
        args=(port_str, failed_event),
        daemon=True,
    ).start()

    ok = _wait_for_server(health_url, failed_event)
    return ok, url, failed_event


# ── Platform launch helpers ───────────────────────────────────────

def _run_macos() -> None:
    """macOS launch: CustomTkinter controller + Chrome browser window.

    All mutable boot-state lives in local variables so that the nested
    _retry_boot_sequence can rebind them via ``nonlocal`` (which requires
    an enclosing *function* scope — an ``if`` block is not sufficient).
    """
    try:
        from macos_controller import CanvasController
    except ImportError as _import_err:
        # CustomTkinter or the controller module is missing — show a native
        # Tkinter error dialog so the user gets a readable message rather than
        # a raw traceback in the console.
        logger.error(f"Failed to import macos_controller: {_import_err}")
        try:
            import tkinter as _tk
            import tkinter.messagebox as _mb
            _root = _tk.Tk()
            _root.withdraw()
            _mb.showerror(
                "Canvas Downloader — Startup Error",
                f"A required UI component could not be loaded:\n\n{_import_err}\n\n"
                "Please reinstall Canvas Downloader or contact support.",
            )
            _root.destroy()
        except Exception:
            pass  # If tkinter itself is missing, nothing we can do
        sys.exit(1)

    # Probe a port; the controller's "Try Again" path re-probes with a fresh
    # port via _retry_boot_sequence if the first attempt fails.
    port       = _find_free_port()
    url        = f"http://127.0.0.1:{port}"
    health_url = f"{url}/_stcore/health"
    failed_ev  = threading.Event()

    os.environ["STREAMLIT_SERVER_PORT"] = str(port)
    threading.Thread(
        target=_start_streamlit_server,
        args=(str(port), failed_ev),
        daemon=True,
    ).start()

    controller = CanvasController(
        streamlit_url=url,
        # os._exit: same rationale as the Windows exit path — a non-daemon
        # worker thread mid-API-call must not keep the app alive after quit.
        # The controller destroys its Tk window before invoking on_quit.
        on_quit=lambda: os._exit(0),
    )

    def _boot_sequence() -> None:
        """Health-check the current server attempt and open Chrome when ready."""
        if _wait_for_server(health_url, failed_ev):
            controller.set_state('ready')
            # open_chrome() touches Tkinter internals — must run on main thread.
            controller.app.after(0, controller.open_chrome)
        else:
            controller.set_state(
                'error',
                'Server failed to start',
                'Please try closing and reopening the app.',
            )

    def _retry_boot_sequence() -> None:
        """Re-probe a free port and restart Streamlit for the 'Try Again' button."""
        nonlocal port, url, health_url, failed_ev
        port       = _find_free_port()
        url        = f"http://127.0.0.1:{port}"
        health_url = f"{url}/_stcore/health"
        failed_ev  = threading.Event()
        controller.url = url
        os.environ["STREAMLIT_SERVER_PORT"] = str(port)
        threading.Thread(
            target=_start_streamlit_server,
            args=(str(port), failed_ev),
            daemon=True,
        ).start()
        _boot_sequence()

    controller.retry_callback = _retry_boot_sequence
    threading.Thread(target=_boot_sequence, daemon=True).start()

    # tkinter mainloop must run on the main thread (macOS Cocoa requirement).
    controller.run()


# ── Entry Point ───────────────────────────────────────────────────

if __name__ == "__main__":
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    import platform as _platform

    if _platform.system() == 'Darwin':
        _run_macos()
        sys.exit(0)

    else:
        # ── Windows: pywebview flow with splash screen + auto-retry ──
        import webview

        # Loading splash — shown immediately so the user never sees a raw
        # white screen while the Streamlit server is starting up.
        _LOADING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Canvas Downloader</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0f1117;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; flex-direction: column; gap: 28px;
    }
    .logo {
      width: 64px; height: 64px;
      background: rgba(0,114,206,0.18);
      border-radius: 16px;
      display: flex; align-items: center; justify-content: center;
    }
    .logo svg { width: 36px; height: 36px; }
    .label {
      font-size: 1.05rem; font-weight: 600;
      color: rgba(255,255,255,0.55);
      letter-spacing: 0.01em;
    }
    .spinner {
      width: 36px; height: 36px;
      border: 3px solid rgba(255,255,255,0.08);
      border-top-color: #0072CE;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="logo">
    <svg viewBox="0 0 24 24" fill="none" stroke="#0072CE" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/>
      <line x1="12" y1="15" x2="12" y2="3"/>
    </svg>
  </div>
  <div class="label">Starting Canvas Downloader…</div>
  <div class="spinner"></div>
</body>
</html>"""

        def _make_error_html(reason: str) -> str:
            return f"""<!DOCTYPE html>
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
    <div class="icon">&#9888;&#65039;</div>
    <h1>Canvas Downloader failed to start</h1>
    <p>{reason}</p>
    <p>Please close this window and try reopening the app.<br>
       If the problem persists, make sure no other instance is already running.</p>
    <p class="hint">Need help? Visit the support page or check the application logs.</p>
  </div>
</body>
</html>"""

        # Show the loading splash immediately — no white screen on launch.
        webview.create_window(
            'Canvas Downloader', html=_LOADING_HTML,
            maximized=True, min_size=(1024, 700),
        )

        def _boot() -> None:
            """Start the Streamlit server and navigate the window once ready.

            Called by pywebview in a background thread after the GUI starts,
            so blocking here does not freeze the window.
            """
            for _attempt in range(1, _MAX_LAUNCH_ATTEMPTS + 1):
                logger.info(f"Streamlit launch attempt {_attempt}/{_MAX_LAUNCH_ATTEMPTS}...")
                ok, url, failed = _launch_streamlit()

                if ok:
                    webview.windows[0].load_url(url)
                    return

                if failed.is_set():
                    logger.warning(
                        f"Attempt {_attempt} failed (server error). "
                        f"{'Retrying...' if _attempt < _MAX_LAUNCH_ATTEMPTS else 'Giving up.'}"
                    )
                else:
                    logger.warning(
                        f"Attempt {_attempt} timed out. "
                        f"{'Retrying with a new port...' if _attempt < _MAX_LAUNCH_ATTEMPTS else 'Giving up.'}"
                    )

            _reason = (
                f'The application server did not respond after {_MAX_LAUNCH_ATTEMPTS} attempts. '
                'This can happen if another application is using the required network port.'
            )
            logger.error(f"Startup failed after {_MAX_LAUNCH_ATTEMPTS} attempts.")
            webview.windows[0].load_html(_make_error_html(_reason))

        webview.start(_boot)
        # Hard-exit instead of sys.exit: a sync/analysis worker thread that is
        # mid-API-call (non-daemon ThreadPoolExecutor thread) would otherwise
        # keep the process alive for up to a minute after the window closes.
        # All durable state is already committed (per-file SQLite writes,
        # atomic .part renames), so skipping interpreter teardown is safe.
        os._exit(0)
