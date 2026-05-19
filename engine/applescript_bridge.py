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
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            err_msg = result.stderr.strip()
            if "-1743" in err_msg:
                logger.error(
                    f"[AppleScript Security] TCC Automation Permission Denied (error -1743). "
                    f"Please verify that Canvas Downloader has 'Automation' permissions enabled "
                    f"to control Microsoft {app_name} in macOS System Settings > Privacy & Security > Automation."
                )
            else:
                logger.error(
                    f"[AppleScript] {app_name} failed: {err_msg}"
                )
            return False
        return dst.exists()

    except FileNotFoundError:
        logger.error("[AppleScript] osascript not found (not on macOS?)")
        return False
    except subprocess.TimeoutExpired:
        logger.error(
            f"[AppleScript] {app_name} conversion timed out after 120s - "
            "attempting to close the open document to recover"
        )
        posix_src = _as_posix(src)
        _try_close_document_after_timeout(app_name, posix_src)
        return False
    except Exception as e:
        logger.error(f"[AppleScript] {app_name} error: {e}")
        return False
