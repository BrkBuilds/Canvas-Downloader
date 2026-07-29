"""Always-on session health log - the record the Store never gives us.

Why this exists
---------------
The Microsoft Store Health report bucketed 5 of this app's 6 failures as
**"Uncategorized"**, with the tooltip "detailed diagnostic data is not currently
available".  That is not a setup problem on our side - it is a known and
widely-reported Partner Center limitation (microsoft/WindowsAppSDK#5306), and
for a low-volume app those failures may *never* be symbolised.  Waiting for
Microsoft to hand over a stack is therefore not a plan.

So the app keeps its own record.  This module is deliberately NOT the existing
``debug_log.txt``:

    debug_log.txt          this module
    ------------------     -----------------------------------------------
    opt-in (Settings)      ALWAYS on - a crash gives no chance to opt in
    per OUTPUT folder      one file in the config dir, found without knowing
                           which course folder was being written at the time
    verbose, MB-scale      a few hundred bytes per session
    request/response noise environment + lifecycle + memory high-water only

What it captures, and why each line earns its place
---------------------------------------------------
* **Unclean shutdown.**  The single highest-value signal.  ``start.py`` writes a
  clean-exit marker immediately before ``os._exit(0)``; if the next launch finds
  no marker, the previous session died some other way (crash, OOM kill, Task
  Manager, power loss) and that is reported with the phase it was in and the
  memory it was using.  An invisible Store "Uncategorized" failure becomes a
  local line of text.
* **Environment.**  OS build, architecture, total RAM, WebView2 runtime version,
  app version, frozen/packaged.  The Store data pins every crash to OS build
  10.0.26100 and the one hang to 10.0.26220 - dimensions we can only act on if
  we can see them locally too.
* **Memory high-water** for the host process *and* the whole child tree,
  sampled in the background.  This is what tests the "memory failure" theory
  directly rather than by argument.
* **Orphaned WebView2 processes** left by a previous run.  Pre-fix builds of
  2.0.0 are already installed and already leaking these (see
  ``start._terminate_child_processes``); this both reports and clears them.

Privacy
-------
Numbers, versions and lifecycle only.  No tokens, no URLs, no course names, no
file names, no paths outside the app's own config dir.  Nothing here is
transmitted anywhere - it is a local file the user can read, and the Settings
dialog shows them where it is.

Safety
------
Diagnostics must never be able to break the app: **every public function
swallows every exception**.  The sampler is a daemon thread.  psutil is optional.
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import threading
import time
from datetime import datetime, timezone

_MAX_LOG_BYTES = 512 * 1024      # a few hundred sessions; rotates by halving
_SAMPLE_SECONDS = 5.0

_lock = threading.Lock()
# Latched by session_end: after that point NOTHING may rewrite the state file.
_closed = threading.Event()
_state: dict = {
    "phase": "startup",
    "peak_self_mb": 0.0,
    "peak_tree_mb": 0.0,
    "children": [],
    "webview_runtime": "",
    "sampler": None,
    "stop": None,
    "started_monotonic": time.monotonic(),
}

# msedgewebview2.exe lives at ...\EdgeWebView\Application\<version>\msedgewebview2.exe
_WV_VERSION_RE = re.compile(r"[\\/]Application[\\/]([0-9][0-9.]+)[\\/]", re.IGNORECASE)
_UDD_RE = re.compile(r'--user-data-dir(?:=|\s+)("[^"]+"|\S+)', re.IGNORECASE)


# ── Where the files live ─────────────────────────────────────────────────────

def _diag_dir() -> str:
    """``<config dir>/diagnostics``.

    Imports ``shared.helpers`` lazily and falls back to a stdlib-only guess:
    this module is reached from ``start.py`` during boot, and a diagnostics
    helper must never be the reason the app fails to start.  The rule for where
    config lives is NOT duplicated here - get_config_dir() stays the one owner
    of it, and the fallback is only for the case where importing it failed.
    """
    base = None
    try:
        from shared.helpers import get_config_dir
        base = get_config_dir()
    except Exception:
        if sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support/CanvasDownloader")
        elif sys.platform == "win32":
            base = os.path.join(os.environ.get("APPDATA")
                                or os.path.expanduser("~"), "CanvasDownloader")
        else:
            base = os.path.expanduser("~/.canvas_downloader")
    d = os.path.join(base, "diagnostics")
    os.makedirs(d, exist_ok=True)
    return d


def health_log_path() -> str:
    """Absolute path of the health log, or '' if it cannot be resolved."""
    try:
        return os.path.join(_diag_dir(), "health.log")
    except Exception:
        return ""


def _state_path() -> str:
    return os.path.join(_diag_dir(), "session_state.json")


# ── Writing ──────────────────────────────────────────────────────────────────

def _write(line: str) -> None:
    try:
        path = health_log_path()
        if not path:
            return
        try:
            if os.path.getsize(path) > _MAX_LOG_BYTES:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    tail = fh.read()[-(_MAX_LOG_BYTES // 2):]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("... (older entries trimmed)\n" + tail)
        except OSError:
            pass
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp}  {line}\n")
    except Exception:
        pass


# ── Environment snapshot ─────────────────────────────────────────────────────

def _total_ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / 2 ** 30, 1)
    except Exception:
        return 0.0


def _app_version() -> str:
    try:
        from version import __version__
        return str(__version__)
    except Exception:
        return "?"


def _is_rosetta() -> bool:
    """True when a macOS build is running x86_64-translated on Apple Silicon.

    Worth one sysctl: this app ships native wheels (ctranslate2, numpy, pyobjc)
    pinned for a specific macOS/arch, and a bundle that lands under Rosetta
    fails in ways that look like nothing else - so it must be visible in the
    record rather than deduced. ``platform.machine()`` cannot tell you: under
    translation it reports the *emulated* x86_64, not the real hardware.
    """
    if sys.platform != "darwin":
        return False
    try:
        import ctypes
        libc = ctypes.CDLL("libc.dylib")
        out = ctypes.c_int(0)
        size = ctypes.c_size_t(ctypes.sizeof(out))
        rc = libc.sysctlbyname(b"sysctl.proc_translated", ctypes.byref(out),
                               ctypes.byref(size), None, 0)
        return rc == 0 and bool(out.value)
    except Exception:
        return False


def environment() -> dict:
    """OS/app dimensions, matching what a crash report would slice by.

    ``build`` is deliberately the same KEY on every platform but the
    platform's own notion of a version: "10.0.26100" on Windows (what the Store
    Health report groups by - all our crashes landed on one build) and "14.6" on
    macOS. ``platform.version()`` is not a substitute: on macOS it returns the
    Darwin kernel banner, which nothing groups by.
    """
    try:
        if sys.platform == "win32":
            os_name = f"Windows {platform.release()}"
            build = platform.win32_ver()[1] or platform.version()
        elif sys.platform == "darwin":
            build = platform.mac_ver()[0] or "?"
            os_name = f"macOS {build}"
        else:
            os_name = f"{platform.system()} {platform.release()}"
            build = platform.version()
        env = {
            "app": _app_version(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "packaged": bool(os.environ.get("MSIX_PACKAGE_ID")
                             or "WindowsApps" in (sys.executable or "")),
            "os": os_name,
            "build": build,
            "arch": platform.machine(),
            "python": platform.python_version(),
            "ram_gb": _total_ram_gb(),
            "cpus": os.cpu_count() or 0,
        }
        if _is_rosetta():
            env["rosetta"] = True
        return env
    except Exception:
        return {}


# ── The child-process picture ────────────────────────────────────────────────

def _scan_children() -> tuple[float, float, list[dict], str]:
    """(self_mb, tree_mb, children, webview_runtime_version).

    Records EVERY child, not just WebView2, because the orphan risk is not the
    same shape on both platforms.  On Windows it is the WebView2 browser process
    (see ``start._terminate_child_processes``).  On macOS there is no separate
    browser process at all - WKWebView runs in-process - and the things that can
    be left behind holding real memory are the Panopto transcription worker and
    ffmpeg.  A Windows-only scan would have made the macOS record silent about
    exactly the processes that matter there.

    Each child carries ``created`` (psutil's process creation time).  That is
    what makes the sweep in ``_reap_recorded_orphans`` safe on both platforms: a
    pid alone is not an identity, and a recycled pid pointing at an innocent
    process is the one outcome that would be worse than the leak being cleaned
    up.  For WebView2 the per-launch ``--user-data-dir`` is captured as a second,
    independent proof - pywebview hands it a fresh temp folder every launch
    (``winforms.init_storage`` -> ``tempfile.TemporaryDirectory().name``), and
    several unrelated WebView2 hosts (Teams, WhatsApp, Widgets, Phone Link) are
    normally running on the same machine.
    """
    self_mb = tree_mb = 0.0
    children: list[dict] = []
    runtime = ""
    try:
        import psutil
        me = psutil.Process()
        self_mb = me.memory_info().rss / 1048576
        tree_mb = self_mb
        for child in me.children(recursive=True):
            try:
                rss = child.memory_info().rss / 1048576
                tree_mb += rss
                name = child.name()
                entry = {"pid": child.pid, "name": name,
                         "created": round(child.create_time(), 3),
                         "mb": round(rss, 1)}
                if name.lower() == "msedgewebview2.exe":
                    m = _UDD_RE.search(" ".join(child.cmdline() or []))
                    if m:
                        entry["udd"] = m.group(1).strip('"')
                    if not runtime:
                        m = _WV_VERSION_RE.search(child.exe() or "")
                        if m:
                            runtime = m.group(1)
                children.append(entry)
            except Exception:
                continue
    except Exception:
        pass
    return round(self_mb, 1), round(tree_mb, 1), children, runtime


# ── Sampler ──────────────────────────────────────────────────────────────────

def _sampler_loop(stop: threading.Event) -> None:
    while not stop.wait(_SAMPLE_SECONDS):
        try:
            self_mb, tree_mb, children, runtime = _scan_children()
            with _lock:
                _state["peak_self_mb"] = max(_state["peak_self_mb"], self_mb)
                _state["peak_tree_mb"] = max(_state["peak_tree_mb"], tree_mb)
                if children:
                    _state["children"] = children
                if runtime:
                    _state["webview_runtime"] = runtime
            _save_state()
        except Exception:
            continue


def _save_state() -> None:
    """Persist the live session so the NEXT launch can tell what happened.

    Written every sample rather than at exit, because the whole point is to
    survive an exit that never runs any of our code.

    Refuses to write once ``session_end`` has closed the record.  Without that
    guard there is a live race that corrupts the one signal this module exists
    for: ``session_end`` sets the sampler's stop event, but a sampler already
    PAST its ``wait()`` and inside ``_scan_children()`` goes on to call this
    afterwards and rewrites ``clean_exit`` back to ``False`` - so a perfectly
    normal shutdown gets reported as a crash on the next launch.
    """
    if _closed.is_set():
        return
    try:
        with _lock:
            snap = {
                "pid": os.getpid(),
                "clean_exit": False,
                "phase": _state["phase"],
                "peak_self_mb": _state["peak_self_mb"],
                "peak_tree_mb": _state["peak_tree_mb"],
                "children": list(_state["children"]),
                "failures": dict(_state.get("failures") or {}),
                "webview_runtime": _state["webview_runtime"],
                "uptime_s": round(time.monotonic() - _state["started_monotonic"]),
                "env": environment(),
            }
        tmp = _state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snap, fh)
        os.replace(tmp, _state_path())     # atomic: never a half-written state
    except Exception:
        pass


# ── Previous-session post-mortem ─────────────────────────────────────────────

def _reap_recorded_orphans(prev: dict) -> tuple[int, list[str]]:
    """Kill child processes the PREVIOUS session recorded as its own.

    Returns ``(count, names)``.

    Cross-platform by design: on Windows the leftover is the wedged WebView2
    browser process, on macOS it is a transcription worker (holding a whole
    Whisper model) or an ffmpeg.  Pre-fix builds are already installed and
    already stranding these, so a newly-updated app should clear the damage it
    did before, not merely stop adding to it.

    **Identity is proven, never assumed.**  A pid is not an identity - the OS
    recycles them, and killing an innocent process that happened to inherit one
    would be far worse than the leak.  So a process is only killed when the live
    process agrees with the record on *all* of:

      * pid,
      * image name, and
      * **creation time** (to the millisecond) - which a recycled pid cannot
        match, because it was by definition created later.

    WebView2 entries add a fourth, independent proof: the per-launch
    ``--user-data-dir`` must still be present in the live command line.
    """
    recorded = prev.get("children") or []
    if not recorded:
        return 0, []
    killed: list[str] = []
    try:
        import psutil
        for entry in recorded:
            try:
                pid = int(entry.get("pid", 0))
                name = (entry.get("name") or "").lower()
                created = entry.get("created")
                if not pid or not name or created is None:
                    continue
                proc = psutil.Process(pid)
                if proc.name().lower() != name:
                    continue
                if abs(proc.create_time() - float(created)) > 0.05:
                    continue        # pid was recycled - different process
                udd = entry.get("udd")
                if udd and udd not in " ".join(proc.cmdline() or []):
                    continue
                proc.kill()
                killed.append(proc.name())
            except Exception:
                continue
    except Exception:
        return 0, []
    return len(killed), sorted(set(killed))


def _post_mortem() -> None:
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            prev = json.load(fh)
    except Exception:
        return
    try:
        if prev.get("clean_exit"):
            return
        _write(
            "PREVIOUS SESSION DID NOT EXIT CLEANLY  "
            f"pid={prev.get('pid')} phase={prev.get('phase')!r} "
            f"uptime={prev.get('uptime_s')}s "
            f"peak_self={prev.get('peak_self_mb')}MB "
            f"peak_tree={prev.get('peak_tree_mb')}MB"
            # "exited uncleanly during conversion, after 14 osascript timeouts"
            # is a diagnosis; the phase alone is only half of one.
            + (f" failures={prev['failures']}" if prev.get("failures") else "")
        )
        killed, names = _reap_recorded_orphans(prev)
        if killed:
            _write(f"  reaped {killed} orphaned process(es) left behind by that "
                   f"session: {', '.join(names)}")
    except Exception:
        pass


# ── Public API ───────────────────────────────────────────────────────────────

def session_start() -> None:
    """Log the environment, report on the previous session, start sampling."""
    try:
        _closed.clear()
        # SESSION START first, THEN the post-mortem: the file is read top-down
        # by a human, and "this session started / by the way the last one died"
        # is the order that makes sense. Reversed, the verdict on the previous
        # session appears to belong to the session above it.
        env = environment()
        env.update(_macos_signals())
        _write("SESSION START  " + "  ".join(f"{k}={v}" for k, v in env.items()))
        _post_mortem()
        with _lock:
            if _state["sampler"] is None:
                stop = threading.Event()
                thread = threading.Thread(target=_sampler_loop, args=(stop,),
                                          daemon=True, name="cd-health-sampler")
                _state["stop"] = stop
                _state["sampler"] = thread
                thread.start()
        _save_state()
    except Exception:
        pass


def note_failure(kind: str) -> None:
    """Tally a recoverable subsystem failure (``osascript_timeout``, ...).

    macOS-motivated: Office conversions go through ``osascript`` and are the
    least-tested path this app has, and today those failures are swallowed into
    the OPT-IN ``debug_log.txt`` - so on a user's machine they leave no trace at
    all.  A count is not a stack trace, but "this session had 14 osascript
    timeouts and then exited uncleanly during conversion" is a diagnosis, and it
    costs one integer.
    """
    try:
        with _lock:
            fails = _state.setdefault("failures", {})
            fails[str(kind)[:40]] = fails.get(str(kind)[:40], 0) + 1
    except Exception:
        pass


def _macos_signals() -> dict:
    """macOS-only state that explains failures nothing else records.

    All three are read cheaply and never raise.  They exist because macOS is the
    least-tested platform this ships on AND has no crash-telemetry channel at
    all - there is no Partner Center equivalent, so anything not written here is
    simply lost.
    """
    out: dict = {}
    if sys.platform != "darwin":
        return out
    try:
        # Office conversions depend on this; it is the top macOS support
        # question, and an unclean exit during conversion means something very
        # different depending on whether it was granted.
        from engine.applescript_bridge import has_full_disk_access
        out["fda"] = bool(has_full_disk_access())
    except Exception:
        pass
    try:
        # The phantom-instance bug: start.py already records every suppressed
        # duplicate GUI launch (pid/ppid/argv). Surfacing the COUNT here means a
        # recurrence shows up without having to ask the user for a second file.
        dup = os.path.join(os.path.dirname(_diag_dir()), "duplicate_launches.log")
        if os.path.isfile(dup):
            with open(dup, encoding="utf-8", errors="replace") as fh:
                n = sum(1 for line in fh if line.strip())
            if n:
                out["duplicate_launches"] = n
    except Exception:
        pass
    return out


def note_phase(phase: str) -> None:
    """Record what the app is doing, so an unclean exit names the phase."""
    try:
        with _lock:
            if _state["phase"] == phase:
                return
            _state["phase"] = str(phase)[:60]
        _save_state()
    except Exception:
        pass


def session_end(reason: str = "clean") -> None:
    """Close the session record. Called immediately before ``os._exit``.

    Only ``reason == "clean"`` writes the clean-exit marker.  Anything else
    leaves the state file saying the session never finished, which is exactly
    what ``_post_mortem`` reports on next launch - a crash inside
    ``webview.start()`` must not be able to log itself as a tidy shutdown just
    because the ``finally`` that calls this still runs.
    """
    try:
        with _lock:
            stop = _state.get("stop")
            self_peak = _state["peak_self_mb"]
            tree_peak = _state["peak_tree_mb"]
            runtime = _state["webview_runtime"]
            uptime = round(time.monotonic() - _state["started_monotonic"])
        if stop is not None:
            stop.set()
        # Latch BEFORE the final write: a sampler already past its wait() and
        # inside _scan_children() must not be able to land a stale, unclean
        # snapshot on top of the marker written below.
        _closed.set()
        # One last sample: a short session may never have ticked.
        self_mb, tree_mb, _children, rt = _scan_children()
        self_peak = max(self_peak, self_mb)
        tree_peak = max(tree_peak, tree_mb)
        runtime = runtime or rt
        with _lock:
            fails = dict(_state.get("failures") or {})
        _write(f"SESSION END ({reason})  uptime={uptime}s "
               f"peak_self={round(self_peak,1)}MB peak_tree={round(tree_peak,1)}MB "
               f"webview2={runtime or '?'}"
               + (f" failures={fails}" if fails else ""))
        try:
            with open(_state_path(), encoding="utf-8") as fh:
                snap = json.load(fh)
        except Exception:
            snap = {}
        snap["clean_exit"] = (reason == "clean")
        snap["end_reason"] = reason
        tmp = _state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snap, fh)
        os.replace(tmp, _state_path())
    except Exception:
        pass
