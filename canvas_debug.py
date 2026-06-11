import logging
import os
import re
import sys
import threading
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


def _rotate_if_needed(debug_file: str) -> None:
    """If the log file exceeds _MAX_LOG_BYTES, drop the oldest data and keep
    the most recent _KEEP_TAIL_BYTES so the file stays manageable."""
    try:
        size = os.path.getsize(debug_file)
    except OSError:
        return
    if size < _MAX_LOG_BYTES:
        return
    try:
        with open(debug_file, 'rb') as f:
            f.seek(-_KEEP_TAIL_BYTES, 2)
            tail = f.read()
        marker = b'\n[... older log entries truncated to keep file under 5 MB ...]\n\n'
        with open(debug_file, 'wb') as f:
            f.write(marker)
            f.write(tail)
    except OSError:
        pass


def log_debug(message, debug_file=None):
    """Write a sanitized, timestamped message to the debug log.

    Automatically rotates the file when it exceeds 5 MB to prevent
    unbounded disk growth. Bearer tokens are stripped before writing.
    """
    if not debug_file:
        return

    try:
        _rotate_if_needed(debug_file)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        safe_message = _sanitize(str(message))
        with open(debug_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {safe_message}\n")
    except Exception as e:
        print(f"Debug logging failed: {e}")


def clear_debug_log(debug_file=None):
    """Clear the debug log and write a fresh session header."""
    if not debug_file:
        return
    try:
        with open(debug_file, "w", encoding="utf-8") as f:
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
# evaporated — the debug log ended at "Post-Processing:" and 27
# conversion failures left no trace.
#
# Fix: a per-run "active debug file" registry plus a logging.Handler
# that mirrors app log records into it. Registering happens at
# download/sync/analysis start (where the debug file path is known);
# everything any app module logs from then on lands in debug_log.txt
# with a [LEVEL] [module] prefix — no plumbing through call stacks.
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
    'engine', 'sync', 'ui', 'core',
)


class _DebugFileBridge(logging.Handler):
    """Mirrors logging records into the active debug file (if any)."""

    def emit(self, record: logging.LogRecord) -> None:
        debug_file = get_active_debug_file()
        if not debug_file:
            return
        top_name = record.name.split('.')[0]
        is_app_logger = top_name in _APP_LOGGER_PREFIXES
        # App modules: INFO and up. Everything else: WARNING and up.
        if record.levelno < (logging.INFO if is_app_logger else logging.WARNING):
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
        if _active_debug_file and not _bridge_installed:
            bridge = _DebugFileBridge(level=logging.INFO)
            logging.getLogger().addHandler(bridge)
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
    WHAT failed but not WHERE — the 'secondary_id_type' UnboundLocalError
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

    Version, OS/arch, frozen state, Python, and CA-bundle health — the
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
            f"  App: Canvas Downloader v{_ver} | frozen={bool(getattr(sys, 'frozen', False))}",
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
