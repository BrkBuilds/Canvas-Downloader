"""
engine.applescript_bridge - Shared AppleScript execution utility for macOS.

Extracted from excel_converter.py, word_converter.py, pdf_converter.py
(Phase 3 remediation - F-08) to eliminate triple-duplicated code.

Provides a single, robust ``run_applescript()`` function that all Office
converters delegate to for macOS AppleScript-based file conversion.
"""

import logging
import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Maps the human-readable app_name argument to the AppleScript application
# name and the AppleScript term for an open document in that app.
_APP_DOC_MAP = {
    "PowerPoint": ("Microsoft PowerPoint", "active presentation"),
    "Word":        ("Microsoft Word",       "active document"),
    "Excel":       ("Microsoft Excel",      "active workbook"),
}

# Sandbox container bundle identifiers for the Office apps. A sandboxed app
# always has unrestricted read/write access to its OWN container's Data dir,
# so staging conversion inputs/outputs there sidesteps the macOS "Grant File
# Access" powerbox prompt that otherwise fires for every file in ~/Downloads.
_CONTAINER_IDS = {
    "PowerPoint": "com.microsoft.Powerpoint",
    "Word":       "com.microsoft.Word",
    "Excel":      "com.microsoft.Excel",
}


def _office_container_tmp(app_name: str) -> Path | None:
    """Return a writable staging dir inside the Office app's sandbox container.

    Returns ``None`` (caller falls back to direct paths) when not on macOS, the
    app is unknown, or the container does not exist (app never launched / not
    installed). The directory is the app's own sandbox container, so both the
    Office app AND our (non-sandboxed) process can read/write it freely.
    """
    if sys.platform != 'darwin':
        return None
    cid = _CONTAINER_IDS.get(app_name)
    if not cid:
        return None
    base = Path.home() / "Library" / "Containers" / cid / "Data"
    if not base.is_dir():
        return None
    # Under Data/tmp so it can never be caught by iCloud Drive sync (which only
    # touches the container's Documents folder). The Office app has full
    # sandbox access to everything under its own Data dir.
    tmp = base / "tmp" / "CanvasDownloaderTmp"
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp
    except Exception:
        return None


@contextmanager
def office_container_stage(src: Path, dst: Path, app_name: str):
    """macOS: stage *src*/*dst* inside the Office app's sandbox container.

    Yields ``(staged_src, staged_dst)``. The Office app opens *staged_src* and
    writes *staged_dst* entirely inside its own container, so macOS never shows
    the per-folder "Grant File Access" / "Additional permissions required"
    powerbox prompt. On a clean exit the produced *staged_dst* is moved back to
    the real *dst*; the staging dir is always cleaned up.

    Degrades safely: on any platform other than macOS, when the container is
    unavailable, or if the staging copy fails, it yields the original
    ``(src, dst)`` unchanged — behaviour is then identical to no staging
    (i.e. never worse than before, only ever better).
    """
    src = Path(src)
    dst = Path(dst)

    stage_root = _office_container_tmp(app_name)
    if stage_root is None:
        yield src, dst
        return

    work = stage_root / ("cd_" + uuid.uuid4().hex[:10])
    staged_src = work / src.name
    staged_dst = work / dst.name
    try:
        work.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, staged_src)
    except Exception as e:
        logger.debug(f"[AppleScript] container staging unavailable ({e}); using direct path")
        shutil.rmtree(work, ignore_errors=True)
        yield src, dst
        return

    try:
        yield staged_src, staged_dst
        # Success path: relocate the produced PDF back to its real destination.
        if staged_dst.exists():
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    dst.unlink()
                shutil.move(str(staged_dst), str(dst))
            except Exception as e:
                # Last-ditch copy so a same-volume move quirk can't lose output.
                try:
                    shutil.copy2(staged_dst, dst)
                except Exception:
                    logger.warning(
                        f"[AppleScript] converted file produced in container but could "
                        f"not be moved back to {dst}: {e}"
                    )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _visibility_prefix(app_name: str) -> str:
    """AppleScript snippet that hides the Office app before the conversion runs.

    Hiding the process (rather than just not activating it) is what stops the
    relentless dock-bounce + window-flashing the user sees on macOS: a hidden
    app stays hidden when a document is opened via automation, as long as we
    never ``activate`` it. Wrapped in ``try`` so a missing process or a denied
    System Events Automation grant degrades to "app stays visible" instead of
    failing the conversion. Returns ``""`` off macOS / for unknown apps.
    """
    if sys.platform != 'darwin':
        return ""
    mapping = _APP_DOC_MAP.get(app_name)
    if not mapping:
        return ""
    ms_name = mapping[0]
    return (
        'tell application "System Events"\n'
        '    try\n'
        f'        set visible of (first process whose name is "{ms_name}") to false\n'
        '    end try\n'
        'end tell\n'
    )

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
    # Hide the Office app first so opening the document doesn't flash a window /
    # bounce the dock (macOS only; no-op elsewhere). Best-effort, self-trying.
    script = _visibility_prefix(app_name) + script
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
    """Launch + permission-prime the Office apps upfront, hidden, during download.

    macOS shows a blocking "Canvas Downloader wants to control X" prompt the
    first time an Apple Event is sent to each app (and, separately, to System
    Events). Firing those harmless events in a background thread during the
    download phase batches ALL of the prompts before post-processing begins,
    warms up the heavy Office processes, and crucially launches them *hidden*
    so they never bounce the dock into the foreground.
    """
    import threading
    if sys.platform != 'darwin':
        return

    # (human app name, AppleScript app name, preferences/bundle domain)
    _ALL = [
        ('convert_pptx', "PowerPoint", "Microsoft PowerPoint", _CONTAINER_IDS["PowerPoint"]),
        ('convert_word', "Word",       "Microsoft Word",       _CONTAINER_IDS["Word"]),
        ('convert_excel', "Excel",     "Microsoft Excel",      _CONTAINER_IDS["Excel"]),
    ]
    apps_to_prime = [(ms, dom) for key, _short, ms, dom in _ALL if contract.get(key, False)]

    if not apps_to_prime:
        return

    def _warmup():
        for app, domain in apps_to_prime:
            # Check for default installation path to prevent "Where is X?" dialogs
            if not Path(f"/Applications/{app}.app").exists():
                continue
            try:
                # Kill the macro-security dialog at the source: VBAWarnings=4 =
                # "Disable all macros without notification". Written BEFORE launch
                # so the fresh process reads it (a running app caches prefs via
                # cfprefsd and wouldn't pick it up). Static content still renders
                # for PDF export — the macros never need to run. Best-effort: if
                # the file already has Excel open, the prompt may still appear.
                subprocess.run(
                    ['defaults', 'write', domain, 'VBAWarnings', '-int', '4'],
                    capture_output=True, timeout=15,
                )
            except Exception:
                pass
            try:
                # Launch hidden (-j) and without foregrounding (-g) so the app is
                # already running, off-screen, by the time conversions start.
                subprocess.run(
                    ['open', '-g', '-j', '-a', app],
                    capture_output=True, timeout=60,
                )
            except Exception:
                pass
            try:
                # Harmless Apple Event → triggers the per-app Automation TCC prompt.
                subprocess.run(
                    ['osascript', '-e', f'tell application "{app}" to count windows'],
                    capture_output=True, timeout=120,
                )
            except Exception:
                pass
            try:
                # Hide it now AND trigger the one-time System Events Automation
                # prompt, so the per-file hide in run_applescript is silent later.
                subprocess.run(
                    ['osascript', '-e',
                     f'tell application "System Events" to set visible of '
                     f'(first process whose name is "{app}") to false'],
                    capture_output=True, timeout=60,
                )
            except Exception:
                pass

    threading.Thread(target=_warmup, daemon=True).start()

