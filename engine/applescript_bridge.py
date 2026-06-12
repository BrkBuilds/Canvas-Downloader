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

# Unique sentinel baked into every staged-conversion path. It is what lets us
# later identify (and surgically purge) the Recent-files entries Office records
# for our temp files, without ever touching a real user document.
_CANVAS_TMP_MARKER = "CanvasDownloaderTmp"


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
    tmp = base / "tmp" / _CANVAS_TMP_MARKER
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

def _marker_in_value(value) -> bool:
    """True if *value* (a SQLite cell: str, bytes/UTF-16, or None) holds our marker.

    Office stores recent-file paths in the registry DB either as TEXT or as a
    UTF-16/UTF-8 BLOB depending on version, so we decode defensively rather than
    rely on a SQL ``LIKE`` (which would silently miss UTF-16-encoded paths).
    """
    if value is None:
        return False
    if isinstance(value, str):
        return _CANVAS_TMP_MARKER in value
    if isinstance(value, (bytes, bytearray)):
        for enc in ('utf-16-le', 'utf-8', 'latin-1'):
            try:
                if _CANVAS_TMP_MARKER in bytes(value).decode(enc, errors='ignore'):
                    return True
            except Exception:
                continue
    return False


def _purge_recents_sqlite() -> None:
    """Delete our staged-temp files from Office's Recent-files registry DB.

    Modern Office for Mac shows the start-screen "Recent" list from a shared
    SQLite registry (``MicrosoftRegistrationDB.reg`` under the Office group
    container), NOT from securebookmarks.plist (the old delete-the-plist trick
    stopped working). Each recent file is one ``node_id`` in
    ``HKEY_CURRENT_USER_values`` with a ``name='path'`` row holding the path.

    We find only the nodes whose path contains ``CanvasDownloaderTmp`` and delete
    exactly those nodes' rows. The marker is unique to our container staging, so a
    user's genuine recent documents can never match. Schema-introspected and fully
    best-effort: any deviation just no-ops, never corrupts the DB.
    """
    import sqlite3
    group = Path.home() / "Library" / "Group Containers" / "UBF8T346G9.Office"
    db_paths = []
    # Apple Silicon: single file at the group-container root.
    asi = group / "MicrosoftRegistrationDB.reg"
    if asi.is_file():
        db_paths.append(asi)
    # Intel: hashed filename inside a sub-folder.
    nested = group / "MicrosoftRegistrationDB"
    if nested.is_dir():
        db_paths.extend(p for p in nested.glob("MicrosoftRegistrationDB*.reg") if p.is_file())

    for db in db_paths:
        try:
            con = sqlite3.connect(str(db), timeout=2.0)
            try:
                cur = con.cursor()
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='HKEY_CURRENT_USER_values'"
                )
                if cur.fetchone() is None:
                    continue
                cur.execute(
                    "SELECT node_id, value FROM HKEY_CURRENT_USER_values WHERE name='path'"
                )
                victims = {node_id for node_id, value in cur.fetchall()
                           if _marker_in_value(value)}
                if not victims:
                    continue
                cur.executemany(
                    "DELETE FROM HKEY_CURRENT_USER_values WHERE node_id=?",
                    [(nid,) for nid in victims],
                )
                con.commit()
                logger.debug(f"[AppleScript] purged {len(victims)} Canvas temp entries from Office Recents")
            finally:
                con.close()
        except Exception as e:
            logger.debug(f"[AppleScript] Recents SQLite purge skipped for {db.name}: {e}")


def _purge_securebookmarks() -> None:
    """Drop our staged-temp keys from each Office app's securebookmarks.plist.

    This is the per-app access-bookmark layer (separate from the SQLite display
    list). Removing our dead entries here keeps the bookmark store tidy. Format-
    preserving (binary stays binary) and marker-filtered, so it only ever removes
    Canvas Downloader temp paths and never the user's own bookmarks.
    """
    import plistlib
    for cid in _CONTAINER_IDS.values():
        plist = (Path.home() / "Library" / "Containers" / cid / "Data"
                 / "Library" / "Preferences" / f"{cid}.securebookmarks.plist")
        if not plist.is_file():
            continue
        try:
            raw = plist.read_bytes()
            is_binary = raw[:8] == b'bplist00'
            data = plistlib.loads(raw)
            if not isinstance(data, dict):
                continue
            victims = [k for k in list(data.keys()) if _CANVAS_TMP_MARKER in str(k)]
            if not victims:
                continue
            for k in victims:
                data.pop(k, None)
            fmt = plistlib.FMT_BINARY if is_binary else plistlib.FMT_XML
            with open(plist, 'wb') as fh:
                plistlib.dump(data, fh, fmt=fmt)
            logger.debug(f"[AppleScript] purged {len(victims)} temp bookmarks from {plist.name}")
        except Exception as e:
            logger.debug(f"[AppleScript] securebookmarks purge skipped for {cid}: {e}")


def _purge_canvas_recents() -> None:
    """Remove all traces of our container-staged temp files from Office Recents."""
    _purge_recents_sqlite()
    _purge_securebookmarks()


def quit_idle_office_apps() -> None:
    """Tidy up Office after a run: quit the apps we launched, then purge Recents.

    Two steps, on a single daemon thread (macOS only):

    1. Quit PowerPoint/Word/Excel — but ONLY if they have no open documents.
       Post-processing leaves them running (we deliberately never quit them
       mid-batch, to avoid relaunch churn between courses); this clears them from
       the dock once everything is done. We check via System Events that the
       process is actually RUNNING before addressing it (so we never auto-launch
       a quit target) and only quit when its document count is 0, so a user who
       has their own workbook/presentation open is never disturbed.
    2. Purge our container-staged temp files from Office's Recent-files lists
       (see ``_purge_canvas_recents``) so the conversion scratch files don't
       crowd out the user's real recent documents. Marker-filtered — only
       Canvas Downloader temp paths are ever removed.

    Best-effort throughout; any failure is swallowed.
    """
    if sys.platform != 'darwin':
        return
    import threading

    # (AppleScript app name, its document collection term)
    targets = [
        ("Microsoft PowerPoint", "presentations"),
        ("Microsoft Word", "documents"),
        ("Microsoft Excel", "workbooks"),
    ]

    def _worker():
        for app, collection in targets:
            script = (
                f'tell application "System Events"\n'
                f'    if exists (process "{app}") then\n'
                f'        try\n'
                f'            tell application "{app}"\n'
                f'                if (count of {collection}) is 0 then quit\n'
                f'            end tell\n'
                f'        end try\n'
                f'    end if\n'
                f'end tell'
            )
            try:
                subprocess.run(['osascript', '-e', script], capture_output=True, timeout=20)
            except Exception:
                pass

        # Idle apps have now been asked to quit. Give them a beat to terminate and
        # release the shared Recent-files registry DB, then surgically purge our
        # container-staged temp files from Office's Recent lists (marker-filtered,
        # so a user's real recent documents are never affected). Best-effort and
        # independent of whether anything was actually quit.
        import time as _time
        _time.sleep(1.0)
        _purge_canvas_recents()

    threading.Thread(target=_worker, daemon=True).start()


# ── Office priming state ────────────────────────────────────────────
# Which Office apps have already been launched/primed this run, and whether the
# macro-security pref has been written. Module-level (not session state) and
# reset by reset_office_priming() at the start of each download/sync run — the
# apps are quit at the previous run's completion screen, so a fresh run re-primes.
_primed_apps: set = set()
_macro_pref_written = False

# Converter key → the Office file extensions it handles. Used to scope priming to
# only the apps a run will ACTUALLY use.
_OFFICE_EXTS = {
    'convert_pptx': {'.ppt', '.pptx', '.pptm', '.pot', '.potx'},
    'convert_word': {'.doc', '.rtf', '.odt'},
    'convert_excel': {'.xlsx', '.xls', '.xlsm'},
}


def reset_office_priming() -> None:
    """Forget which Office apps were primed, so the next run launches them fresh.

    Call at the start of each download/sync run. The apps are quit at the previous
    run's completion screen, so their primed-state must be cleared or the next run
    would wrongly skip (re-)launching them.
    """
    global _macro_pref_written
    _primed_apps.clear()
    _macro_pref_written = False


def office_contract_from_folder(folder, base_contract: dict) -> dict:
    """Scope *base_contract* to the Office file types ACTUALLY present in *folder*.

    Returns a contract that enables an app only when its converter is on in
    *base_contract* AND at least one matching file exists anywhere under *folder* —
    so a course containing only .pptx never launches Word or Excel. Off macOS it
    returns the contract unchanged; on a scan error it falls back to the unscoped
    contract (so we never suppress an app that's actually needed).
    """
    import os
    if sys.platform != 'darwin':
        return dict(base_contract)
    remaining = {k for k in _OFFICE_EXTS if base_contract.get(k, False)}
    if not remaining:
        return {k: False for k in _OFFICE_EXTS}
    present = {k: False for k in _OFFICE_EXTS}
    try:
        for _root, _dirs, files in os.walk(str(folder)):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                for key in list(remaining):
                    if ext in _OFFICE_EXTS[key]:
                        present[key] = True
                        remaining.discard(key)
            if not remaining:
                break
    except Exception:
        return dict(base_contract)
    return {k: bool(base_contract.get(k, False) and present[k]) for k in _OFFICE_EXTS}


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

    # Converter key → AppleScript app name. Launch an app ONLY when its converter
    # is enabled in *contract* AND it hasn't already been primed this run. Pass a
    # contract SCOPED to the files actually present (office_contract_from_folder /
    # get_synced_file_paths) so a run that only converts PowerPoint never opens
    # Word or Excel. Apps are marked immediately (main thread) so a concurrent call
    # can't double-launch the same app.
    _ALL = [
        ('convert_pptx', "Microsoft PowerPoint"),
        ('convert_word', "Microsoft Word"),
        ('convert_excel', "Microsoft Excel"),
    ]
    to_launch = []
    for key, ms in _ALL:
        if contract.get(key, False) and ms not in _primed_apps:
            _primed_apps.add(ms)
            to_launch.append(ms)
    if not to_launch:
        return

    global _macro_pref_written
    write_macro_pref = not _macro_pref_written
    if write_macro_pref:
        _macro_pref_written = True

    def _warmup():
        if write_macro_pref:
            # Kill the "this workbook contains macros" dialog suite-wide BEFORE any
            # Office app launches. The CORRECT macOS key is VisualBasicMacroExecutionState
            # (a String) on the SHARED `com.microsoft.office` domain — NOT the Windows-only
            # `VBAWarnings`, and NOT a per-app domain. (Confirmed by Microsoft's "Set
            # preferences for macro security in Office for Mac" doc.) "DisabledWithoutWarnings"
            # = macros never run and never prompt. IMPORTANT for the user's "data exactly as
            # the teacher made it" requirement: disabling macro EXECUTION does NOT blank any
            # cells — a workbook's last-saved values are what render to PDF; VBA only matters
            # if code RUNS, which we never need (a stray Workbook_Open could itself hang/prompt).
            # Written before launch because cfprefsd caches prefs for a running process.
            try:
                subprocess.run(
                    ['defaults', 'write', 'com.microsoft.office',
                     'VisualBasicMacroExecutionState', '-string', 'DisabledWithoutWarnings'],
                    capture_output=True, timeout=15,
                )
            except Exception:
                pass

        for app in to_launch:
            # Check for default installation path to prevent "Where is X?" dialogs
            if not Path(f"/Applications/{app}.app").exists():
                continue
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
            if app == "Microsoft Excel":
                # Best-effort suppression of the "this workbook contains links to
                # external sources" dialog. Done HERE, in its own isolated
                # osascript, NOT inline in the conversion script: if this Excel
                # build doesn't expose the property the statement is a COMPILE
                # error (-2741) that `try` can't catch — inline it would kill
                # every conversion. Isolated, a bad property name just no-ops.
                for _prop in ('ask to update links', 'ask to update automatic links'):
                    try:
                        subprocess.run(
                            ['osascript', '-e',
                             f'tell application "{app}" to set {_prop} to false'],
                            capture_output=True, timeout=15,
                        )
                    except Exception:
                        pass

    threading.Thread(target=_warmup, daemon=True).start()

