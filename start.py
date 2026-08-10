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
    """Return the preferred port if free, otherwise the first free port in 8502-8600.

    ``SO_REUSEADDR`` is set on POSIX only, and that asymmetry is load-bearing.
    On Windows the flag does not mean "reuse a TIME_WAIT port" as it does on
    Unix - it means "bind even if another socket is actively LISTENING there",
    so the probe reported an occupied port as free.  Measured 2026-07-27: with a
    server already on 8501, this returned 8501, Streamlit bound it a second time,
    and the health check was answered by the OTHER server - the window then
    loaded whatever that process was serving.  Tornado itself skips SO_REUSEADDR
    on Windows for exactly this reason (``netutil.bind_sockets``), so probing
    without it also makes the probe agree with what the server can actually bind.
    """
    for port in [preferred, *range(8502, 8601)]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if os.name != 'nt':
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

        # A packaged app's sources cannot change while it runs, so Streamlit's
        # source watcher is pure overhead here: it installs a watchdog observer
        # per local module and re-walks sys.modules after every rerun. Left ON
        # only for the dev `python start.py` path, where hot reload is useful.
        if getattr(sys, "frozen", False):
            sys.argv.append("--server.fileWatcherType=none")

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


# ── Cold-start prewarm ────────────────────────────────────────────
#
# Nothing here changes what the app does - it only moves work off the critical
# path.  The startup is three serial waits: the server has to boot before the
# window can navigate, the 7 MB frontend bundle has to load before a session can
# open, and the app's whole module graph has to import before the first script
# run can render.  The middle two are I/O the process is otherwise idle for, and
# on a fresh install (Microsoft Store) every one of those reads is uncached and
# pays a first-run virus scan - which is where 10-20 seconds comes from.
#
# Both prewarms are daemon threads started once the splash is already on screen,
# so any CPU they steal is invisible, and both are best-effort: a failure here
# can only cost the time it was meant to save.

# What script run #1 needs. Ordered roughly by cost; `app.py` itself is NEVER
# imported (it calls st.set_page_config at module level and belongs to the
# ScriptRunner). Verified 2026-07-27: no module-level st.* calls anywhere in the
# package graph, and zero module-level import cycles across 68 modules - so
# importing this concurrently with the ScriptRunner can only ever make the
# second thread WAIT on a per-module lock, never deadlock.
_PREWARM_CRITICAL = (
    "shared.helpers", "shared.components", "shared.legal", "styles",
    "core.state_registry", "core.cancellation", "core.canvas_logic",
    "core.course_cache",
    "engine.estimation", "engine.progress_dashboard",
    "engine.post_processing_bridge", "engine.notifications",
    "sync_ui", "ui.auth", "ui.course_selector",
)

# The screens one click away. Imported after the critical set so they can never
# delay it.
_PREWARM_SECONDARY = (
    "ui.download_settings", "ui.quick_download", "ui.today_dashboard",
    "ui.presets", "ui.sync_review", "ui.sync_confirmation",
)


def _prewarm_app_modules() -> None:
    """Import the app's module graph while the server is still booting."""
    t0 = time.perf_counter()
    for group in (_PREWARM_CRITICAL, _PREWARM_SECONDARY):
        for name in group:
            try:
                __import__(name)
            except Exception as e:
                logger.debug(f"prewarm: {name} failed ({e})")
    logger.info(f"prewarm: app modules ready in {time.perf_counter() - t0:.2f}s")


def _prewarm_frontend_assets() -> None:
    """Pull Streamlit's static bundle into the OS page cache.

    The WebView requests a 7 MB entry bundle the instant it navigates. Reading
    the files here means that request is served from memory instead of from a
    cold read of the install directory. Frozen builds only - a dev machine has
    had these pages cached since the first `streamlit run`.
    """
    if not getattr(sys, "frozen", False):
        return
    static_dir = resolve_path(os.path.join("streamlit", "static"))
    index_html = os.path.join(static_dir, "index.html")
    if not os.path.isfile(index_html):
        return
    t0 = time.perf_counter()

    def _read(path: str) -> int:
        try:
            with open(path, "rb") as fh:
                n = 0
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        return n
                    n += len(chunk)
        except OSError:
            return 0

    # The entry bundle and stylesheet index.html names are the files that block
    # React from mounting, so warm those FIRST - the WebView may well start
    # asking for them before this walk finishes.
    ordered: list[str] = [index_html]
    try:
        import re
        html = open(index_html, "r", encoding="utf-8", errors="replace").read()
        for rel in re.findall(r'(?:src|href)="\./([^"]+\.(?:js|css))"', html):
            p = os.path.join(static_dir, rel.replace("/", os.sep))
            if os.path.isfile(p):
                ordered.append(p)
    except OSError:
        pass
    for root, _dirs, files in os.walk(static_dir):
        ordered.extend(os.path.join(root, fn) for fn in files)

    read = 0
    seen: set[str] = set()
    budget = 64 * 1024 * 1024          # never churn the disk for a runaway dir
    for path in ordered:
        if path in seen:
            continue
        seen.add(path)
        read += _read(path)
        if read >= budget:
            break
    logger.info(f"prewarm: {read / 1e6:.1f} MB of frontend assets "
                f"in {time.perf_counter() - t0:.2f}s")


def _terminate_child_processes(grace: float = 2.0, kill_wait: float = 1.5) -> None:
    """Take the whole process tree down with us before the hard exit.

    ``os._exit`` skips interpreter teardown, and Windows does not kill a
    process's children when it dies - so anything still running when we exit is
    ORPHANED, permanently.  Three things can be in flight:

      * **the WebView2 browser process** (Windows).  This is the one that was
        actually biting.  A Store user's 2026-07-15 hang (WER MoAppHangXProc
        against ``BrkBuilds.CanvasDownloader_2.0.0.0_x64``) is
        msedgewebview2.exe stuck FOREVER on its own shutdown::

            Windows_Media!dllmain_crt_process_detach
              -> ucrtbase!execute_onexit_table
                -> ComPtr<..ClosedCaptioning..IClosedCaptionBrokerStatics>::InternalRelease
                  -> combase!CStdMarshal::Disconnect -> RemoteReleaseRifRef
                    -> win32u!NtUserMsgWaitForMultipleObjectsEx   <- blocked

        Windows.Media.dll releases a cached WinRT activation factory from its
        DLL_PROCESS_DETACH handler.  Under MSIX that factory is **brokered**, so
        the release is a cross-process COM call to the package's RuntimeBroker
        (spawned in the same second as the browser process - PID 28936 in the
        dump, still alive and still not answering 2h later), made while the
        loader lock is held and with exactly ONE thread left in the process
        (``CrBrowserMain``).  It never returns.  Calling COM from DllMain is a
        documented deadlock and Windows.Media.dll is not ours to fix - but a
        process that is TERMINATED never runs DLL_PROCESS_DETACH at all, so
        reaping it here removes the hang, the ~75 MB it strands until reboot,
        and the failure report filed against our package.

        This is packaged-build-only: unpackaged there is no package RuntimeBroker
        and the release resolves locally.  Measured 2026-07-27 on the dev build,
        a healthy close has already torn all six WebView2 processes down by the
        time ``webview.start()`` returns, so the grace loop below finds nothing
        and costs nothing.  It only spends time on the broken path.
      * **a Panopto transcription worker** - holding a whole Whisper model,
        gigabytes, which would keep running to the end of the recording.
      * **an ffmpeg remux/extract** (``panopto.stream``, ``converters.video``).

    pywebview does give the browser process 3s of its own
    (``edgechromium.clear_user_data`` -> ``Dispose()`` + ``WaitForExit(3000)``,
    private mode only) but then simply walks away from whatever is left, which
    is exactly how the hung process came to be orphaned.

    Best-effort by construction: every failure path falls through to the exit.
    """
    try:
        import psutil
    except Exception:
        return

    try:
        # Snapshot while we are still their parent - once os._exit runs the
        # ppid links walked here are gone.  psutil.Process pins the pid's
        # creation time, so a pid recycled between now and the kill below is
        # recognised as a different process and left alone.
        doomed = psutil.Process().children(recursive=True)
    except Exception:
        return
    if not doomed:
        return

    try:
        _exited, alive = psutil.wait_procs(doomed, timeout=grace)
        if not alive:
            return
        names = []
        for proc in alive:
            try:
                names.append(proc.name())     # read BEFORE the kill
            except Exception:
                names.append("?")
            try:
                proc.kill()                   # TerminateProcess: no DLL_PROCESS_DETACH
            except Exception:
                pass
        psutil.wait_procs(alive, timeout=kill_wait)
        logger.info("shutdown: force-terminated %d orphaned child process(es): %s",
                    len(alive), ", ".join(sorted(set(names))))
    except Exception:
        pass


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
        #
        # SKIP the demotion when running as the CONSOLE worker binary
        # (Canvas_Downloader_Worker, preferred by _worker_command): its
        # bootloader never touches LaunchServices, and calling
        # NSApplication.sharedApplication() here would CREATE the very
        # registration the console build exists to avoid (macOS 15 files a
        # registered child's termination as a phantom Dock recents tile).
        if (sys.platform == "darwin"
                and "worker" not in os.path.basename(sys.executable).lower()):
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
      background: #0d1117;
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
      /* px + explicit line-height so this is byte-for-byte the same box as the
         boot overlay the Streamlit page paints when we navigate away from here
         (scripts/patch_streamlit_boot.py). Any difference between the two shows
         up as the label twitching at the hand-off. */
      font-size: 16.8px; line-height: normal; font-weight: 600;
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
      background: #0d1117; color: #e0e0e0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; padding: 2rem;
    }}
    .card {{
      background: #1e2130; border: 1px solid #2d3248;
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
    _main_window = webview.create_window(
        'Canvas Downloader', html=_LOADING_HTML,
        maximized=True, min_size=(1024, 700),
        background_color='#0d1117'
    )

    def _boot() -> None:
        """Start the Streamlit server and navigate the window once ready.

        Called by pywebview in a background thread after the GUI starts,
        so blocking here does not freeze the window.
        """
        # Open the health record: reports on how the LAST session ended (the
        # Store buckets our failures as "Uncategorized" with no stack, so this
        # local file is the only post-mortem we actually get), clears any
        # WebView2 process a pre-fix build stranded, and starts memory
        # sampling. Runs here - on pywebview's background thread, after the
        # splash is already up - so it cannot cost a single frame at launch.
        try:
            from core.health_log import session_start
            session_start()
        except Exception:
            pass

        # Overlap the two big cold-start reads with the server boot. Started
        # here rather than before webview.start() so they cannot compete with
        # getting the splash on screen.
        for _fn in (_prewarm_frontend_assets, _prewarm_app_modules):
            threading.Thread(target=_fn, daemon=True).start()

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
    # macOS: the `finally` below NEVER RUNS on a normal quit.
    #
    # Cmd-Q / the Quit menu send a Quit Apple event, and Cocoa terminates the
    # process from inside its own run loop without unwinding the Python stack -
    # so `webview.start()` does not return and nothing after it happens.
    # Measured on the packaged app 2026-08-10: launch, quit with
    # `tell application "Canvas Downloader" to quit`, and the state file still
    # said `clean_exit=False, exit_reason=None`. Three launches in one hour each
    # logged "PREVIOUS SESSION DID NOT EXIT CLEANLY", one of them for a session
    # that had been quit gracefully after 788s idle.
    #
    # That costs the two things this block exists for: the health record's clean
    # marker - "the absence of that marker is the entire signal the health log
    # carries", and macOS is the platform CLAUDE.md calls out as having no other
    # crash-telemetry channel - and the child reap that is supposed to happen
    # before the hard exit.
    #
    # pywebview's `closed` event fires from the Cocoa delegate, which is a path
    # the Quit event DOES take. `_shutdown` is idempotent, so the ordinary
    # window-close route (where `start()` does return and the finally also runs)
    # closes the record exactly once.
    _shutdown_done = threading.Event()

    def _shutdown(reason: str) -> None:
        if _shutdown_done.is_set():
            return
        _shutdown_done.set()
        try:
            from core.health_log import session_end
            session_end(reason)
        except Exception:
            pass
        _terminate_child_processes()

    try:
        _main_window.events.closed += lambda: _shutdown("clean")
    except Exception as _e:                        # pragma: no cover - defensive
        logger.debug(f"Could not hook the window close event: {_e}")

    _exit_reason = "clean"
    try:
        webview.start(_boot)
    # BaseException is the POINT here, and nothing is swallowed: this re-raises
    # on the next line. SystemExit and KeyboardInterrupt derive from
    # BaseException, not Exception (the same reason RerunException slips past
    # `except Exception` elsewhere in this codebase), so catching only Exception
    # would let a Ctrl-C or a sys.exit() record itself as a CLEAN shutdown - and
    # the absence of that marker is the entire signal the health log carries.
    except BaseException:  # audit-ignore - deliberate, and re-raised immediately
        _exit_reason = "crashed"
        raise
    finally:
        # Through _shutdown, NOT a second direct call - that is what makes the
        # idempotence claimed above actually true.
        #
        # This block used to call session_end() and _terminate_child_processes()
        # itself, bypassing the _shutdown_done guard entirely, so the ordinary
        # window-close route ran the whole shutdown TWICE: `events.closed` fires
        # first, then `webview.start()` returns and the finally repeats it.
        # Measured in the packaged 2.0.2 app on a real window close - two
        # identical `SESSION END (clean)` lines for one SESSION START, one second
        # apart (uptime=169s in both, peak_self 220.1 then 220.2 MB). Harmless
        # for the clean_exit flag, which is idempotent, but it breaks the
        # one-START-one-END shape the log is read for and reaps the process tree
        # a second time for nothing.
        #
        # _shutdown keeps the ordering this block documented: the health record
        # is closed FIRST, while the children are still alive and measurable -
        # that marker is what the next launch reads to decide whether the app
        # died or exited - and the tree is reaped BEFORE the hard exit below (see
        # _terminate_child_processes' docstring for the Store hang that fixes).
        # Being in the `finally` is what stops a crash inside webview.start()
        # stranding a WebView2/ffmpeg/transcription child; on that path the
        # exception still propagates normally rather than being swallowed.
        _shutdown(_exit_reason)

    # Hard-exit instead of sys.exit: a sync/analysis worker thread that is
    # mid-API-call (non-daemon ThreadPoolExecutor thread) would otherwise
    # keep the process alive for up to a minute after the window closes.
    # All durable state is already committed (per-file SQLite writes,
    # atomic .part renames), so skipping interpreter teardown is safe.
    os._exit(0)
