import os
import re
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
