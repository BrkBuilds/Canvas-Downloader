import collections
import logging
import os
import re
import sys
import threading
import time
import traceback as _traceback
from datetime import datetime
# Max debug log size before rotation (5 MB).
# When the file exceeds this, the oldest ~3 MB is dropped and a truncation
# marker is inserted so the tail of the log is always readable.
_MAX_LOG_BYTES = 5 * 1024 * 1024
_KEEP_TAIL_BYTES = 2 * 1024 * 1024

# Matches bare Bearer tokens in log lines so they are never written to disk.
# Covers the standard header format "Bearer <token>" case-insensitively.
_BEARER_RE = re.compile(r'(Bearer\s+)[A-Za-z0-9_\-\.~+/]+=*', re.IGNORECASE)

# Signed-URL query tokens (Canvas file URLs carry a `verifier=` token that
# grants temporary access to the file; `access_token=` may appear in some
# API URLs). Redacted so a shared debug log can't leak live download links.
_URL_TOKEN_RE = re.compile(r'((?:verifier|access_token)=)[^&\s"\'<>]+', re.IGNORECASE)


def _sanitize(message: str) -> str:
    """Strip Bearer tokens and signed-URL tokens before writing to disk."""
    message = _BEARER_RE.sub(r'\1[REDACTED]', message)
    return _URL_TOKEN_RE.sub(r'\1[REDACTED]', message)


def _lp(p) -> str:
    """The long-path form of *p*. Lazy so this module keeps no app imports.

    The debug log lives in the user's DOWNLOAD folder, not the config dir, so
    its path is exactly as deep as the destination they chose - and a log that
    cannot be written is the one thing that makes every other failure in this
    file undiagnosable.
    """
    from shared.helpers import make_long_path
    return make_long_path(p)


def _rotate_if_needed(debug_file: str) -> None:
    """If the log file exceeds _MAX_LOG_BYTES, drop the oldest data and keep
    the most recent _KEEP_TAIL_BYTES so the file stays manageable."""
    try:
        size = os.path.getsize(_lp(debug_file))
    except OSError:
        return
    if size < _MAX_LOG_BYTES:
        return
    try:
        with open(_lp(debug_file), 'rb') as f:
            f.seek(-_KEEP_TAIL_BYTES, 2)
            tail = f.read()
        marker = b'\n[... older log entries truncated to keep file under 5 MB ...]\n\n'
        with open(_lp(debug_file), 'wb') as f:
            f.write(marker)
            f.write(tail)
    except OSError:
        pass


# Every debug log actually WRITTEN TO this session.
#
# Registered here, in log_debug, rather than at the places that construct a
# path, because those are not the same set: `clear_debug_log` is called from
# only 3 sites, while `canvas_logic` builds `<save_dir>/debug_log.txt` per
# COURSE and never announces it. Registering on write is the only rule that
# cannot miss one - and a file with nothing in it is not worth reporting
# anyway, so "was written to" is also the correct definition.
#
# A plain set with `.add()`: the operation is atomic under the GIL, and this
# runs beside an open/write/close on every call, which dwarfs it. No lock.
_session_debug_files: set[str] = set()


def session_debug_files() -> list[str]:
    """Paths of every debug log written to during this session.

    Used by the app-error report on the completion screens to attach the tail
    of a real log rather than a path the developer can never reach.
    """
    return sorted(_session_debug_files)


# ── Breadcrumbs: the last N debug lines, ALWAYS, in memory only ──────────────
#
# `debug_log.txt` is opt-in and OFF by default, so when the app broke on a
# user's machine there was nothing to attach - the one moment the narration
# matters is the one where it was never written down.
#
# In RAM rather than a temp file, deliberately. A file would mean disk writes
# on every run of a feature whose whole job is moving gigabytes (a 4 GB course
# sync would carry an unasked-for multi-MB log alongside it), plus a deletion
# that has to survive a crash - and a crash is exactly when it must not be
# deleted. A deque has none of that: it costs one append, it disappears with
# the process, and it can only ever leave the machine if the user clicks the
# report control on an app error.
#
# NOT sanitized on the way IN. `_sanitize` is two regex substitutions, and this
# is called on the order of 10^5 times during a large download - so the raw
# message is stored (tokens are already in memory anyway; they are in session
# state) and redaction happens once, over the ~400 surviving lines, at read
# time in `breadcrumbs()`. Identical guarantee, and measured 23x cheaper:
# 0.014s vs 0.324s per 100k appends. The whole always-on capture costs 0.028s
# per 100k calls, which is why it can be unconditional.
_BREADCRUMB_LINES = 400
_breadcrumbs: 'collections.deque[tuple[float, str]]' = collections.deque(
    maxlen=_BREADCRUMB_LINES)


def breadcrumbs() -> str:
    """The recent debug narration, sanitized, whether or not logging is on.

    Timestamps are formatted here for the same reason redaction is: a
    `strftime` per call would be paid 10^5 times, a `time.time()` float is
    nearly free.
    """
    out = []
    for stamp, msg in list(_breadcrumbs):
        try:
            when = datetime.fromtimestamp(stamp).strftime('%H:%M:%S')
        except Exception:
            when = "??:??:??"
        out.append(f"[{when}] {_sanitize(msg)}")
    return "\n".join(out)


def log_debug(message, debug_file=None):
    """Write a sanitized, timestamped message to the debug log.

    Automatically rotates the file when it exceeds 5 MB to prevent
    unbounded disk growth. Bearer tokens are stripped before writing.

    The breadcrumb append happens BEFORE the `debug_file` guard: with debug
    logging off - the default - every call to this function used to be a no-op,
    which is why a user's app error arrived with no narration at all.
    """
    msg = str(message)
    _breadcrumbs.append((time.time(), msg))
    if not debug_file:
        return
    _session_debug_files.add(str(debug_file))

    try:
        _rotate_if_needed(debug_file)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        safe_message = _sanitize(str(message))
        with open(_lp(debug_file), "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {safe_message}\n")
    except Exception as e:
        print(f"Debug logging failed: {e}")


def clear_debug_log(debug_file=None):
    """Clear the debug log and write a fresh session header."""
    if not debug_file:
        return
    try:
        with open(_lp(debug_file), "w", encoding="utf-8") as f:
            f.write(f"--- Debug Log Started: {datetime.now()} ---\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Active debug file + logging bridge
#
# Problem this solves (seen in the 2026-06-11 macOS field test): large
# parts of the app report problems via the Python `logging` module
# (converters, applescript_bridge, post_processing's _log_msg mirror...).
# In a frozen build there is no console, so all of that evidence
# evaporated - the debug log ended at "Post-Processing:" and 27
# conversion failures left no trace.
#
# Fix: a per-run "active debug file" registry plus a logging.Handler
# that mirrors app log records into it. Registering happens at
# download/sync/analysis start (where the debug file path is known);
# everything any app module logs from then on lands in debug_log.txt
# with a [LEVEL] [module] prefix - no plumbing through call stacks.
# ═══════════════════════════════════════════════════════════════════

_active_lock = threading.Lock()
_active_debug_file: str | None = None
_bridge_installed = False

# Loggers mirrored at INFO level (our own modules). Third-party loggers
# (urllib3, streamlit, asyncio...) stay at their default WARNING so the
# log captures their genuine problems without their routine chatter.
_APP_LOGGER_PREFIXES = (
    'app', 'canvas_logic', 'sync_manager', 'sync_ui', 'post_processing',
    'pdf_converter', 'word_converter', 'excel_converter', 'video_converter',
    'md_converter', 'code_converter', 'archive_extractor', 'url_compiler',
    'preset_manager', 'ui_helpers', 'ui_shared', 'theme',
    'engine', 'sync', 'ui', 'core', 'panopto',
    # 'shared' was missing until 2026-07-31, so every INFO line from
    # shared/legal.py, shared/helpers.py and shared/components.py was dropped
    # from debug_log.txt (the bridge only keeps WARNING+ for non-app loggers).
    # That silently hid the Panopto consent decisions - exactly the records you
    # need when a user reports "it didn't download my lectures".
    'shared',
)


#: Exception types that mean ONLY "the browser tab went away".
#:
#: MEASURED on the product owner's own download log, 2026-09-13: **37,360 of
#: 49,250 lines (76%) were these**, as 3,736 full tracebacks. His app's actual
#: content was 62 INFO lines, 2 locked-file errors and one warning. An earlier
#: log the same week was 4.7 MB with the app's own lines at 0.4%.
#:
#: The mechanism is that the bridge is installed on the ROOT logger, so
#: `asyncio`'s "Task exception was never retrieved" - an ERROR, from a
#: non-app logger, therefore passed by the level rule below - arrives carrying
#: a chained `StreamClosedError` -> `WebSocketClosedError` every time Streamlit
#: fails to push a repaint to a socket the browser has already closed. A long
#: download with a backgrounded tab produces thousands.
#:
#: This is the file a user attaches when something goes wrong, so drowning it
#: is not untidiness - it is the diagnostic being destroyed by the framework's
#: bookkeeping. Note the app's OWN loggers are exempt: a `ConnectionResetError`
#: from a Canvas download is a real fact about a real transfer.
_BROWSER_DISCONNECTS = ('WebSocketClosedError', 'StreamClosedError')

#: How often to say the suppression is happening. NOT silent: the first one is
#: kept in full so the reader can see what it is, and a counted line follows
#: every N, so "nothing was hidden from you" stays true.
_DISCONNECT_NOTE_EVERY = 250

_disconnect_noise = 0


def _is_browser_disconnect(record: logging.LogRecord) -> bool:
    """Whether this record is only "the page that was watching us went away".

    Walks the `__cause__` / `__context__` chain, because the record's own
    exception is the outer one: the measured shape is a `StreamClosedError`
    raised while handling a `WebSocketClosedError`, and which of the two is
    outermost is tornado's business, not ours.
    """
    exc = record.exc_info[1] if record.exc_info else None
    seen = 0
    while exc is not None and seen < 10:          # bounded: cycles are possible
        if type(exc).__name__ in _BROWSER_DISCONNECTS:
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


class _DebugFileBridge(logging.Handler):
    """Mirrors logging records into the active debug file, and into breadcrumbs.

    No longer returns early when there is no active debug file: `log_debug`
    breadcrumbs unconditionally now, and a WARNING or a traceback logged while
    debug logging is off is exactly the line worth keeping.
    """

    def emit(self, record: logging.LogRecord) -> None:
        debug_file = get_active_debug_file()
        top_name = record.name.split('.')[0]
        is_app_logger = top_name in _APP_LOGGER_PREFIXES
        # App modules: INFO and up. Everything else: WARNING and up.
        if record.levelno < (logging.INFO if is_app_logger else logging.WARNING):
            return
        # A framework logger reporting a closed browser socket says nothing
        # about this run. Keep the FIRST in full, then count them: the reader
        # learns what is happening once and is told how often, instead of
        # losing the log to it. See `_BROWSER_DISCONNECTS`.
        if not is_app_logger and _is_browser_disconnect(record):
            global _disconnect_noise
            with _active_lock:
                _disconnect_noise += 1
                count = _disconnect_noise
            if count > 1:
                if count % _DISCONNECT_NOTE_EVERY == 0:
                    log_debug(
                        f"[INFO] [canvas_debug] {count} browser-connection "
                        f"notices so far this run; only the first is kept in "
                        f"full. They mean the page stopped listening (a "
                        f"background tab, a reload) and say nothing about the "
                        f"download.", debug_file)
                return
        try:
            msg = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                msg += '\n' + ''.join(_traceback.format_exception(*record.exc_info)).rstrip()
            log_debug(f"[{record.levelname}] [{record.name}] {msg}", debug_file)
        except Exception:
            pass  # logging must never take the app down


def set_active_debug_file(debug_file) -> None:
    """Register the debug log for the current run and install the bridge.

    Call at the start of every debug-enabled download/sync/analysis run.
    Pass None to detach (mirroring stops; explicit log_debug calls still work).
    """
    global _active_debug_file, _bridge_installed
    with _active_lock:
        _active_debug_file = str(debug_file) if debug_file else None
        if _active_debug_file:
            root = logging.getLogger()
            # Purge any bridge left on the root logger by a previous install.
            # Streamlit's file-watcher re-imports this module on edits, which
            # resets `_bridge_installed` to False and defines a NEW
            # `_DebugFileBridge` class, while the OLD bridge stays attached to
            # the process-wide root logger. Without this cleanup those stale
            # bridges accumulate and every mirrored record is written 2×, 3×,
            # … per reload. Dedupe by class NAME (not isinstance) so it matches
            # bridges from earlier module incarnations too, then install exactly
            # one. Idempotent: safe to call once per run / per course.
            for _h in list(root.handlers):
                if type(_h).__name__ == '_DebugFileBridge':
                    root.removeHandler(_h)
            root.addHandler(_DebugFileBridge(level=logging.INFO))
            # Named loggers default to the root's WARNING effective level,
            # which would filter INFO records before they ever reach the
            # bridge. Open our own modules up to INFO; third-party loggers
            # keep their defaults.
            for prefix in _APP_LOGGER_PREFIXES:
                _lg = logging.getLogger(prefix)
                if _lg.getEffectiveLevel() > logging.INFO:
                    _lg.setLevel(logging.INFO)
            _bridge_installed = True


def get_active_debug_file() -> str | None:
    """Return the currently registered debug file path (or None)."""
    with _active_lock:
        return _active_debug_file


def log_debug_exc(message, debug_file=None, exc: BaseException | None = None):
    """log_debug + the full traceback of the given (or current) exception.

    Use for every unexpected-exception handler: `str(e)` alone identifies
    WHAT failed but not WHERE - the 'secondary_id_type' UnboundLocalError
    took a code-dive to localize because no traceback was logged.
    Falls back to the active debug file when *debug_file* is None.
    """
    debug_file = debug_file or get_active_debug_file()
    if not debug_file:
        return
    if exc is not None:
        tb = ''.join(_traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        tb = _traceback.format_exc()
    tb = tb.rstrip()
    if tb and tb != 'NoneType: None':
        log_debug(f"{message}\n--- traceback ---\n{tb}\n-----------------", debug_file)
    else:
        log_debug(message, debug_file)


def log_session_header(debug_file, context: str = '') -> None:
    """Write an environment header so a shared log identifies the setup.

    Version, OS/arch, frozen state, Python, and CA-bundle health - the
    macOS SSL failure would have been diagnosable from this header alone.
    """
    if not debug_file:
        return
    try:
        import platform as _pf
        try:
            from version import __version__ as _ver
        except Exception:
            _ver = '?'
        try:
            import certifi
            _ca_state = 'ok' if os.path.isfile(certifi.where()) else 'MISSING'
        except Exception as e:
            _ca_state = f'unavailable ({e})'
        lines = [
            "=== Session Environment ===",
            f"  App: Canvas Downloader v{_ver} | frozen={bool(getattr(sys, 'frozen', False))} | pid={os.getpid()}",
            f"  OS: {_pf.system()} {_pf.release()} | {_pf.platform()} | arch={_pf.machine()}",
            f"  Python: {_pf.python_version()}",
            f"  CA bundle (certifi): {_ca_state}",
        ]
        if context:
            lines.append(f"  Context: {context}")
        lines.append("===========================")
        log_debug('\n'.join(lines), debug_file)
    except Exception:
        pass
