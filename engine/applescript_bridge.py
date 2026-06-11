"""
engine.applescript_bridge - Shared AppleScript execution utility for macOS.

Extracted from excel_converter.py, word_converter.py, pdf_converter.py
(Phase 3 remediation - F-08) to eliminate triple-duplicated code.

Provides a single, robust ``run_applescript()`` function that all Office
converters delegate to for macOS AppleScript-based file conversion.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Maps the human-readable app_name argument to the AppleScript application
# name and the AppleScript term for an open document in that app.
_APP_DOC_MAP = {
    "PowerPoint": ("Microsoft PowerPoint", "active presentation"),
    "Word":        ("Microsoft Word",       "active document"),
    "Excel":       ("Microsoft Excel",      "active workbook"),
}

# ── Last-error reporting ────────────────────────────────────────────
# Post-processing runs conversions sequentially, so a single module-level
# slot is sufficient. Callers read this after run_applescript() returns
# False to show the user the REAL reason (TCC denial, app missing, timeout)
# instead of a generic "Conversion failed".
#
# Categories:
#   'permission'  - macOS Automation (TCC) denied (-1743). FATAL for the
#                   whole phase: every subsequent file will fail identically.
#   'app_missing' - Office app not installed / can't be launched. FATAL.
#   'timeout'     - this file took too long (huge deck, hung app). Per-file.
#   'other'       - anything else (corrupt file, sandbox denial, ...). Per-file.
_last_error: tuple[str, str] | None = None

# Categories that doom every remaining file in a conversion phase.
FATAL_CATEGORIES = ('permission', 'app_missing')


def get_last_error() -> tuple[str, str] | None:
    """Return (category, detail) for the most recent failed run_applescript()."""
    return _last_error


def _classify_stderr(err_msg: str) -> str:
    """Map an osascript stderr message to an error category."""
    low = err_msg.lower()
    if '-1743' in err_msg or 'not authorized to send apple events' in low:
        return 'permission'
    if (
        '-600' in err_msg or '-10810' in err_msg
        or "application can't be found" in low
        or "can't get application" in low
        or 'unable to find application' in low
        or "isn't running" in low
    ):
        return 'app_missing'
    return 'other'


def _timeout_for(src: Path, base: int = 180) -> int:
    """Size-scaled osascript timeout.

    The old fixed 120s killed conversions of large lecture decks (a 50 MB
    pptx legitimately takes minutes on first launch while Office warms up
    and macOS shows the one-time Automation prompt). Scale with file size:
    base + 8s per MB, capped at 10 minutes.
    """
    try:
        size_mb = src.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0
    return min(600, int(base + size_mb * 8))


def _as_posix(path: Path) -> str:
    """Return a POSIX path string safe for embedding in an AppleScript string literal.

    Escapes backslashes first, then double-quotes. Use inside AppleScript
    string literals as: ``POSIX file "{_as_posix(path)}"``

    IMPORTANT: Callers that build AppleScript ``script`` strings must use this
    function for every path interpolated into the script to prevent AppleScript
    injection via filenames containing double-quotes or backslashes.
    """
    return str(path.resolve()).replace('\\', '\\\\').replace('"', '\\"')


def _try_close_document_after_timeout(app_name: str, posix_src: str) -> None:
    """Best-effort: close the document that was left open after an osascript
    timeout.  Runs a short-timeout osascript so a hung Office app cannot block
    the next conversion indefinitely.

    We close only the specific document (by POSIX path) rather than quitting
    the whole application, so we don't disturb any files the user had open
    independently of Canvas Downloader.
    """
    mapping = _APP_DOC_MAP.get(app_name)
    if not mapping:
        logger.warning(
            f"[AppleScript] _try_close_document_after_timeout: unknown app_name {app_name!r}; "
            "open document may need to be closed manually."
        )
        return
    ms_app_name, doc_term = mapping

    # Build a targeted close script for the specific file path.
    # Falls back gracefully if the document is not found (e.g., never opened).
    close_script = f'''
        try
            tell application "{ms_app_name}"
                set posixTarget to POSIX file "{posix_src}" as text
                close (every document whose file = posixTarget) saving no
            end tell
        end try
    '''
    try:
        subprocess.run(
            ['osascript', '-e', close_script],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass  # Best-effort only - don't let cleanup failures surface


def run_applescript(src: Path, dst: Path, app_name: str, script: str) -> bool:
    """Execute an AppleScript via ``osascript`` to convert a file.

    This is the single source of truth for all AppleScript-based
    Office automation (Excel, Word, PowerPoint) on macOS.

    Args:
        src: Source file path (used only for context logging; the actual
             POSIX path is baked into *script*).
        dst: Expected output path - checked for existence after execution.
        app_name: Human-readable application name for log messages
                  (e.g. ``"Excel"``, ``"Word"``, ``"PowerPoint"``).
        script: The complete AppleScript source to execute.

    Returns:
        ``True`` if ``osascript`` exited cleanly **and** *dst* exists
        on disk; ``False`` otherwise.

    IMPORTANT: All POSIX paths embedded in *script* must be escaped using
    ``_as_posix(path)`` from this module to prevent AppleScript injection
    via filenames containing double-quotes or backslashes.
    """
    global _last_error
    _last_error = None
    timeout_s = _timeout_for(src)
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=timeout_s,
        )
        if result.returncode != 0:
            err_msg = result.stderr.strip()
            category = _classify_stderr(err_msg)
            if category == 'permission':
                detail = (
                    f"macOS blocked Canvas Downloader from controlling Microsoft {app_name} "
                    f"(Automation permission denied). Enable it in System Settings → "
                    f"Privacy & Security → Automation → Canvas Downloader."
                )
            elif category == 'app_missing':
                detail = f"Microsoft {app_name} is not installed or could not be launched."
            else:
                detail = err_msg or f"Microsoft {app_name} returned an unknown error."
            _last_error = (category, detail)
            logger.error(f"[AppleScript] {app_name} failed ({category}): {err_msg}")
            return False
        if dst.exists():
            return True
        _last_error = ('other', f"Microsoft {app_name} reported success but no output file was created.")
        return False

    except FileNotFoundError:
        _last_error = ('other', 'osascript not found (not on macOS?)')
        logger.error("[AppleScript] osascript not found (not on macOS?)")
        return False
    except subprocess.TimeoutExpired:
        _last_error = ('timeout', f"Conversion timed out after {timeout_s}s (Microsoft {app_name} stopped responding or the file is very large).")
        logger.error(
            f"[AppleScript] {app_name} conversion timed out after {timeout_s}s - "
            "attempting to close the open document to recover"
        )
        posix_src = _as_posix(src)
        _try_close_document_after_timeout(app_name, posix_src)
        return False
    except Exception as e:
        _last_error = ('other', str(e))
        logger.error(f"[AppleScript] {app_name} error: {e}")
        return False

def prime_office_automation(contract: dict) -> None:
    """Trigger macOS TCC permission prompts for Office apps upfront.
    
    macOS displays a blocking "Canvas Downloader wants to control X" prompt 
    the first time an Apple Event is sent. By firing a harmless event in a 
    background thread during the download phase, we batch the prompts upfront 
    and warm up the heavy Office processes before post-processing begins.
    """
    import sys
    import threading
    if sys.platform != 'darwin':
        return
        
    apps_to_prime = []
    if contract.get('convert_pptx', False):
        apps_to_prime.append("Microsoft PowerPoint")
    if contract.get('convert_word', False):
        apps_to_prime.append("Microsoft Word")
    if contract.get('convert_excel', False):
        apps_to_prime.append("Microsoft Excel")
        
    if not apps_to_prime:
        return
        
    def _warmup():
        for app in apps_to_prime:
            # Check for default installation path to prevent "Where is X?" dialogs
            if not Path(f"/Applications/{app}.app").exists():
                continue
            try:
                # This harmless command launches the app (if closed) and triggers TCC
                subprocess.run(
                    ['osascript', '-e', f'tell application "{app}" to count windows'],
                    capture_output=True, timeout=120
                )
            except Exception:
                pass

    threading.Thread(target=_warmup, daemon=True).start()

