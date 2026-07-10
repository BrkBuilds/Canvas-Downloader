"""
start.py - Unified application launcher for Canvas Downloader.

Architecture (both platforms, post-pivot):
  pywebview wraps the Streamlit server in a native desktop window - an
  EdgeChromium WebView2 window on Windows, a Cocoa/WebKit window on macOS.
  The main thread runs ``webview.start()`` (required by macOS Cocoa); the
  Streamlit server runs in a daemonised background thread.

Threading model:
  1. Streamlit server starts in a daemonised background thread.
     ``signal.signal`` is monkeypatched for the duration because Streamlit
     tries to register signal handlers, which raises ``ValueError`` from a
     non-main thread.
  2. A loading splash is shown immediately; ``_boot`` (run by pywebview on a
     background thread) polls the health endpoint and navigates the window
     to the Streamlit URL once it is ready.
  3. When the user closes the window the process hard-exits via ``os._exit``.

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

        from streamlit.web import cli as stcli
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

    Does NOT retry - callers handle retry policy.  ``failed_event`` remains
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


# ── Entry Point ───────────────────────────────────────────────────

if __name__ == "__main__":
    # ── Neutralize multiprocessing's resource tracker (frozen POSIX) ──
    # ROOT CAUSE of the macOS phantom-instance bug: the transcription stack
    # registers a POSIX semaphore, which makes CPython spawn a resource-tracker
    # helper by re-executing sys.executable with `-c <tracker code>` argv. In a
    # frozen windowed .app the bootloader REBUILDS argv from Apple events and
    # drops the `-c` payload (the same argv rebuild as the worker-flag bug
    # below), so the "tracker" child just re-ran start.py: before the
    # single-instance guard existed it booted a FULL second GUI (window + Dock
    # icon + Keychain prompt); with the guard it still spawned and insta-exited
    # around every transcription (the visible Dock "flick"), and multiprocessing
    # kept relaunching it - "resource_tracker: process died unexpectedly,
    # relaunching" in the worker log (2026-07-09 run). A tracker that can never
    # receive its protocol fd is pure liability, so no-op it entirely. Cost: if
    # a process dies without cleanup, a named semaphore can leak until reboot -
    # harmless, and this app never uses multiprocessing itself. Patch both the
    # module-level functions (looked up at call time by
    # multiprocessing.synchronize/shared_memory) and the class methods (in case
    # anything grabs a fresh instance). Windows has no resource tracker.
    if getattr(sys, "frozen", False) and sys.platform != "win32":
        try:
            from multiprocessing import resource_tracker as _rt
            _rt.ResourceTracker.ensure_running = lambda self: None
            _rt.ResourceTracker.register = lambda self, *a, **k: None
            _rt.ResourceTracker.unregister = lambda self, *a, **k: None
            _rt.ensure_running = lambda *a, **k: None
            _rt.register = lambda *a, **k: None
            _rt.unregister = lambda *a, **k: None
        except Exception:
            pass

    # Frozen worker re-exec: the transcription engine runs in an isolated child
    # process so a native CUDA crash can't take down the app (see
    # panopto.transcribe.transcribe_in_subprocess). In a frozen build the child
    # is THIS exe relaunched to run the worker - route it here BEFORE any
    # webview/streamlit startup, run the worker, and exit.
    #
    # Routing is via an ENVIRONMENT VARIABLE, not just a CLI flag: a macOS
    # windowed .app bundle does NOT reliably forward custom argv to sys.argv (its
    # bootloader rebuilds argv from Apple events), so the --panopto-transcribe-worker
    # flag can be silently dropped - the child then falls through to webview and
    # boots the FULL GUI (the macOS bug: a second Canvas Downloader window opened
    # for every transcription, and the next file didn't start until you closed
    # it). An env var is inherited verbatim by the execve'd child and is immune to
    # the argv rebuild, so it is the primary signal; the flag is kept as a backup
    # and for the dev `-m` path. pop() so the flag never leaks to any grandchild.
    _env_worker = os.environ.pop("CANVAS_DL_TRANSCRIBE_WORKER", "") == "1"
    if _env_worker or "--panopto-transcribe-worker" in sys.argv:
        # Record HOW we routed so the worker can log it (confirms the env-var
        # path is doing its job vs. falling back to the argv flag on some setup).
        os.environ["_CANVAS_DL_WORKER_ROUTE"] = "env" if _env_worker else "argv"
        # macOS: without this, the windowed-.app bootloader surfaces this headless
        # helper as a SECOND Dock app while it transcribes. Demote it to a
        # prohibited (background) process so it runs invisibly - one app icon,
        # no window, hands-free, exactly like the Windows build. Best-effort:
        # transcription still works if AppKit is unavailable.
        if sys.platform == "darwin":
            try:
                from AppKit import (
                    NSApplication, NSApplicationActivationPolicyProhibited)
                NSApplication.sharedApplication().setActivationPolicy_(
                    NSApplicationActivationPolicyProhibited)
            except Exception:
                pass
        try:
            from panopto.transcribe_worker import main as _worker_main
            sys.exit(_worker_main())
        except Exception:
            sys.exit(1)

    # ── Single-instance guard ─────────────────────────────────────────
    # Exactly ONE GUI instance per user. On macOS a rogue SECOND full GUI
    # instance has been observed during Panopto transcription (second window +
    # second Dock icon + a fresh Keychain permission prompt, since the new
    # instance re-reads the token at session init). Regardless of what spawns it
    # (LaunchServices resurrecting the bundle, a stray re-exec of the frozen
    # binary, a notification click, or the user double-launching), a duplicate
    # must never boot: it exits HERE, before any webview/streamlit/keyring
    # access, after best-effort focusing the already-running window. The lock is
    # an OS-level primitive (named mutex / flock) that the OS releases
    # automatically on ANY process death, so a crash can never wedge the app.
    # Transcribe workers are routed above and never reach this guard.
    # Escape hatch for debugging: CANVAS_DL_ALLOW_MULTI=1 skips the guard.

    def _instance_lock_dir() -> str:
        if sys.platform == "darwin":
            d = os.path.expanduser("~/Library/Application Support/CanvasDownloader")
        elif sys.platform == "win32":
            d = os.path.join(os.environ.get("LOCALAPPDATA")
                             or os.path.expanduser("~"), "CanvasDownloader")
        else:
            d = os.path.expanduser("~/.canvas_downloader")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d

    def _acquire_single_instance_lock():
        """Return a lock holder (kept alive for the process lifetime), or None
        if another Canvas Downloader GUI instance already holds the lock."""
        if sys.platform == "win32":
            import ctypes
            _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _kernel32.CreateMutexW.restype = ctypes.c_void_p  # HANDLE (64-bit safe)
            _kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int,
                                               ctypes.c_wchar_p)
            _kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            handle = _kernel32.CreateMutexW(None, False,
                                            "CanvasDownloader_SingleInstance")
            if not handle:
                return object()  # mutex creation failed - fail OPEN, never block launch
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                _kernel32.CloseHandle(handle)
                return None
            return handle  # keep referenced so the mutex lives with the process
        try:
            import fcntl
            f = open(os.path.join(_instance_lock_dir(), "instance.lock"), "w",
                     encoding="utf-8")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.close()
                return None
            f.write(str(os.getpid()))
            f.flush()
            return f  # keep the fd open: flock is released on process death
        except Exception:
            return object()  # locking unavailable - fail OPEN

    def _focus_running_instance() -> None:
        """Best-effort: bring the existing instance's window to the front."""
        try:
            if sys.platform == "darwin":
                from AppKit import (
                    NSRunningApplication, NSApplicationActivateIgnoringOtherApps)
                apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(
                    "com.canvasdownloader.app")
                for a in apps:
                    if a.processIdentifier() != os.getpid():
                        a.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                        break
            elif sys.platform == "win32":
                import ctypes
                _user32 = ctypes.WinDLL("user32")
                _user32.FindWindowW.restype = ctypes.c_void_p  # HWND
                _user32.FindWindowW.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
                _user32.ShowWindow.argtypes = (ctypes.c_void_p, ctypes.c_int)
                _user32.SetForegroundWindow.argtypes = (ctypes.c_void_p,)
                hwnd = _user32.FindWindowW(None, "Canvas Downloader")
                if hwnd:
                    _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    _user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _log_duplicate_launch() -> None:
        """Breadcrumb identifying WHO spawned the duplicate (pid/ppid/argv).

        The parent pid is the smoking gun for the macOS rogue-instance bug:
        ppid == a transcribe worker -> grandchild re-exec; ppid == 1 (launchd)
        -> LaunchServices launched the bundle (Dock/notification/`open`).
        """
        try:
            parent = ""
            try:
                import psutil
                p = psutil.Process(os.getppid())
                parent = f" parent='{p.name()}'"
            except Exception:
                pass
            import datetime
            with open(os.path.join(_instance_lock_dir(),
                                   "duplicate_launches.log"),
                      "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().isoformat()} duplicate GUI "
                        f"launch suppressed: pid={os.getpid()} "
                        f"ppid={os.getppid()}{parent} argv={sys.argv!r}\n")
        except Exception:
            pass

    if os.environ.get("CANVAS_DL_ALLOW_MULTI") != "1":
        _instance_lock = _acquire_single_instance_lock()  # noqa: F841 - held for process lifetime
        if _instance_lock is None:
            _log_duplicate_launch()
            _focus_running_instance()
            os._exit(0)

    # macOS: sweep DEAD-IDENTITY "Canvas Downloader" tiles out of the Dock's
    # recents section - left by System Settings' "Quit & Reopen" (the Full
    # Disk Access grant flow relaunches the app under a fresh LaunchServices
    # identity, so the old instance's tile can never merge with ours) or by a
    # previous App-Translocation launch path. Off the boot path (one
    # `defaults export`); the Dock is only restarted when a stale tile
    # actually existed. See engine.applescript_bridge.purge_stale_self_dock_tiles.
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        def _sweep_stale_dock_tiles() -> None:
            try:
                from engine.applescript_bridge import purge_stale_self_dock_tiles
                purge_stale_self_dock_tiles()
            except Exception:
                pass
        threading.Thread(target=_sweep_stale_dock_tiles, daemon=True).start()

    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    # TLS trust store for frozen builds (macOS especially): OpenSSL's default
    # cert paths inside a PyInstaller bundle point at the build machine and do
    # not exist on the user's machine, breaking every HTTPS client that relies
    # on ssl defaults. Point the standard env vars at certifi's bundled CA file
    # so ssl.create_default_context() (aiohttp, urllib, etc.) can verify peers.
    # canvas_logic.get_ssl_context() does the same explicitly for aiohttp.
    try:
        import certifi
        _ca = certifi.where()
        if os.path.isfile(_ca):
            os.environ.setdefault("SSL_CERT_FILE", _ca)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca)
    except Exception:
        pass  # certifi missing - fall back to whatever the system provides

    import platform as _platform

    # Force pywebview flow for macOS testing
    import webview

    import base64
    try:
        with open(resolve_path("assets/icon.png"), "rb") as _f:
            _icon_b64 = base64.b64encode(_f.read()).decode()
            _logo_html = '<img src="data:image/png;base64,' + _icon_b64 + '" style="width: 36px; height: 36px;" />'
    except Exception:
        _logo_html = """<svg viewBox="0 0 24 24" fill="none" stroke="#0072CE" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round" style="width:36px;height:36px;">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/>
      <line x1="12" y1="15" x2="12" y2="3"/>
    </svg>"""

    # Loading splash - shown immediately so the user never sees a raw
    # white screen while the Streamlit server is starting up.
    # NOTE: no text_select=True. Enabling it let the user rubber-band-select the
    # ENTIRE UI (labels, padding, the black gaps) - which looks broken, and is
    # easy to trigger by accident over VNC. Text selection of page chrome is
    # instead disabled in CSS (styles/global.css), while inputs/textareas stay
    # fully selectable + editable so pasting the Canvas Access Token/URL still works.
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
    """ + _logo_html + """
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
  <title>Canvas Downloader - Startup Error</title>
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

    # Show the loading splash immediately - no white screen on launch.
    # NOTE: no text_select=True. Enabling it let the user rubber-band-select the
    # ENTIRE UI (labels, padding, the black gaps) - which looks broken, and is
    # easy to trigger by accident over VNC. Text selection of page chrome is
    # instead disabled in CSS (styles/global.css), while inputs/textareas stay
    # fully selectable + editable so pasting the Canvas Access Token/URL still works.
    webview.create_window(
        'Canvas Downloader', html=_LOADING_HTML,
        maximized=True, min_size=(1024, 700),
        background_color='#0f1117'
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

    # NOTE (macOS): do NOT pass a custom `menu=[Menu('Edit', ...)]`. pywebview's
    # Cocoa backend already installs a default menu bar - "Canvas Downloader",
    # "Edit", "View" - whose Edit menu has Cut/Copy/Paste/Select All wired to the
    # standard first-responder selectors (with working ⌘X/⌘C/⌘V/⌘A) plus the
    # macOS-injected AutoFill/Dictation/Emoji items. Adding our own "Edit" menu
    # produced a SECOND, duplicate Edit title in the menu bar whose actions were
    # no-ops (they did nothing on click and broke ⌘-shortcut routing). Relying on
    # the built-in menu gives one Edit menu that actually copies and pastes.
    webview.start(_boot)
        
    # Hard-exit instead of sys.exit: a sync/analysis worker thread that is
    # mid-API-call (non-daemon ThreadPoolExecutor thread) would otherwise
    # keep the process alive for up to a minute after the window closes.
    # All durable state is already committed (per-file SQLite writes,
    # atomic .part renames), so skipping interpreter teardown is safe.
    os._exit(0)
