"""
engine.applescript_bridge - Shared AppleScript execution utility for macOS.

Extracted from converters/excel.py, converters/word.py, converters/pdf.py
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
    ``(src, dst)`` unchanged - behaviour is then identical to no staging
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
        # Also sweep any staged copy left open (the staged path carries the
        # CanvasDownloaderTmp marker; the exact-path close above only covers the
        # direct-path fallback). Async so a hung app can't block the next file.
        mapping = _APP_DOC_MAP.get(app_name)
        if mapping:
            _force_close_canvas_docs_async(mapping[0])
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


# (AppleScript app name, its document collection term) - shared by the idle-quit
# and the staged-document force-close helpers below.
_QUIT_TARGETS = [
    ("Microsoft PowerPoint", "presentations"),
    ("Microsoft Word", "documents"),
    ("Microsoft Excel", "workbooks"),
]


def _close_marker_docs_script(app: str, collection: str) -> str:
    """AppleScript that closes every open document staged by Canvas Downloader.

    Matches ONLY documents whose ``full name``/``path`` contains the unique
    ``CanvasDownloaderTmp`` staging marker, so a user's own files can never
    match. Closes one document per outer pass (re-fetching the live collection
    each time) because deleting from an AppleScript list while iterating it
    skips elements. Property reads are individually ``try``-wrapped: never-saved
    documents and dictionary differences between Office versions just no-op.
    """
    return f'''
        tell application "System Events"
            if not (exists process "{app}") then return
        end tell
        repeat 30 times
            set closedOne to false
            try
                tell application "{app}"
                    repeat with d in ({collection} as list)
                        set hit to false
                        try
                            if (full name of d as text) contains "{_CANVAS_TMP_MARKER}" then set hit to true
                        end try
                        if not hit then
                            try
                                if (path of d as text) contains "{_CANVAS_TMP_MARKER}" then set hit to true
                            end try
                        end if
                        if hit then
                            close d saving no
                            set closedOne to true
                            exit repeat
                        end if
                    end repeat
                end tell
            end try
            if not closedOne then exit repeat
        end repeat
    '''


def _force_close_canvas_docs_sync(only_app: str | None = None) -> None:
    """Close any Office documents still open from OUR container staging dir.

    A conversion can leave its staged document open in a hidden Office process
    when the run is cancelled mid-file or when an AppleEvent times out (pending
    TCC prompt, hung app). Those zombie documents then (a) keep the app's
    document count non-zero so the idle-quit refuses to quit it - which is why
    Excel lingered in the dock after a run with timeouts - and (b) confuse users
    who later unhide the app. Marker-matched, so only Canvas Downloader staging
    files are ever closed; user documents are untouchable. Synchronous -
    callers wrap in a thread when needed. Never launches an app (System Events
    running check inside the script).
    """
    if sys.platform != 'darwin':
        return
    for app, collection in _QUIT_TARGETS:
        if only_app and app != only_app:
            continue
        try:
            subprocess.run(
                ['osascript', '-e', _close_marker_docs_script(app, collection)],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass


def _force_close_canvas_docs_async(only_app: str | None = None) -> None:
    """Fire-and-forget thread wrapper around ``_force_close_canvas_docs_sync``."""
    if sys.platform != 'darwin':
        return
    import threading
    threading.Thread(
        target=_force_close_canvas_docs_sync, args=(only_app,), daemon=True,
    ).start()


def _idle_quit_script(app: str, collection: str) -> str:
    """AppleScript that quits *app* unless a REAL user document is open.

    Returns a human-readable status string (captured on stdout and logged) so a
    failed quit is diagnosable from debug_log.txt instead of vanishing silently
    - the old count-based quit swallowed everything, which made "Excel stayed in
    the dock" impossible to root-cause from a test run.

    A document blocks the quit only when it looks like the USER's: it has a path
    on disk, or it has unsaved changes. Pristine blanks (never saved AND
    unmodified - e.g. the empty ``Book1`` Excel sometimes auto-creates on a
    hidden launch) do NOT block: the old ``count is 0`` condition let a single
    pristine blank keep Excel in the dock forever. Quitting with only pristine
    blanks open shows no save prompt (nothing is modified), so the quit cannot
    hang on a hidden dialog. Every property read is try-wrapped (dictionary
    differences across Office versions default to "blocker" via the outer try,
    never to a wrong quit... property reads that fail leave hasPath=false/
    isSaved=true only within their inner trys, while a failure of the whole
    document loop aborts with an error status and no quit).

    The document ENUMERATION itself is also try-wrapped: Excel in its
    Workbook-Gallery-only state (no workbook open) errors on resolving the
    ``workbooks`` collection instead of returning an empty list - observed as
    ``error -1700: Can't make missing value into type number`` on the 2026-07-09
    macOS run, which aborted the whole script via the outer try and left Excel
    (and its Recents entries, which a live Excel rewrites) in the dock forever.
    An enumeration failure means the app cannot name a single open document, so
    it is treated as "no documents" - a real user workbook makes the collection
    resolve normally.
    """
    return f'''
        tell application "System Events"
            if not (exists process "{app}") then return "not running"
        end tell
        set total to 0
        set blockers to 0
        try
            tell application "{app}"
                set docList to {{}}
                try
                    set docList to ({collection} as list)
                end try
                repeat with d in docList
                    set total to total + 1
                    set pristine to false
                    try
                        set hasPath to false
                        try
                            set p to (path of d as text)
                            if p is not "" then set hasPath to true
                        end try
                        if not hasPath then
                            try
                                if (full name of d as text) contains "/" then set hasPath to true
                            end try
                        end if
                        set isSaved to true
                        try
                            set isSaved to (saved of d)
                        end try
                        if (not hasPath) and isSaved then set pristine to true
                    end try
                    if not pristine then set blockers to blockers + 1
                end repeat
                if blockers is 0 then quit
            end tell
        on error errMsg number errNum
            return "error " & errNum & ": " & errMsg
        end try
        if blockers is 0 then return "quit sent (" & total & " open doc(s), none user-owned)"
        return "kept running (" & blockers & " of " & total & " doc(s) look user-owned)"
    '''


def quit_idle_office_apps() -> None:
    """Tidy up Office after a run: quit the apps we launched, then purge Recents.

    Steps, on a single daemon thread (macOS only):

    1. Force-close any documents still open from OUR container staging dir
       (marker-matched - see ``_force_close_canvas_docs_sync``). Cancelled or
       timed-out conversions leave their staged document open in the hidden
       Office process; closing them first is what lets step 2 actually quit.
    2. Quit PowerPoint/Word/Excel - unless a REAL user document is open (a doc
       with a path on disk or unsaved changes - see ``_idle_quit_script``).
       Post-processing leaves the apps running (we deliberately never quit them
       mid-batch, to avoid relaunch churn between courses); this clears them
       from the dock once everything is done. The System Events running check
       means we never auto-launch a quit target. Each app's outcome is LOGGED.
    3. One retry pass ~3s later for any app that didn't quit (a transiently
       busy app - e.g. one still tearing down a conversion when the user
       cancelled - refuses the first Apple event and then lingered forever
       because the quit was one-shot).
    4. Purge our container-staged temp files from Office's Recent-files lists
       (see ``_purge_canvas_recents``) so the conversion scratch files don't
       crowd out the user's real recent documents. Marker-filtered - only
       Canvas Downloader temp paths are ever removed.

    Called from BOTH the completion screens and the cancelled screens (one-shot
    gated by the ``_office_quit_fired`` session sentinel in the callers).
    Best-effort throughout; any failure is swallowed (but logged).
    """
    if sys.platform != 'darwin':
        return
    import threading

    def _quit_pass(pass_no: int, targets) -> list:
        """Ask each target app to quit; return the apps that are still running."""
        still_running = []
        for app, collection in targets:
            try:
                r = subprocess.run(
                    ['osascript', '-e', _idle_quit_script(app, collection)],
                    capture_output=True, text=True, timeout=30,
                )
                status = (r.stdout or "").strip() or f"osascript rc={r.returncode}"
            except Exception as e:
                status = f"osascript failed: {e}"
            logger.info("[OfficeQuit] pass %d: %s -> %s", pass_no, app, status)
            if not status.startswith(("quit sent", "not running")):
                still_running.append((app, collection))
        return still_running

    def _wait_for_exit(apps: list, timeout: float = 12.0) -> None:
        """Poll until every app in *apps* has actually terminated (or timeout).

        The Recents purge MUST run against dead Office processes: a still-alive
        app keeps its Recent-files list in memory and rewrites the shared
        registry DB when it eventually terminates, resurrecting the very
        entries the purge just deleted (why Excel's Recents kept showing our
        CanvasDownloaderTmp files while PowerPoint's/Word's were clean - they
        had quit, Excel hadn't). A fixed 1s nap was a race; poll instead.
        """
        import time as _time
        deadline = _time.time() + timeout
        remaining = [a for a, _c in apps]
        while remaining and _time.time() < deadline:
            still = []
            for app in remaining:
                try:
                    r = subprocess.run(
                        ['osascript', '-e',
                         f'tell application "System Events" to return '
                         f'(exists process "{app}") as text'],
                        capture_output=True, text=True, timeout=10,
                    )
                    if (r.stdout or "").strip().lower() == "true":
                        still.append(app)
                except Exception:
                    pass  # can't tell - assume gone rather than stall the purge
            remaining = still
            if remaining:
                _time.sleep(0.5)
        if remaining:
            logger.info("[OfficeQuit] still running after %.0fs wait: %s "
                        "(Recents purge may not stick for these)",
                        timeout, ", ".join(remaining))

    def _worker():
        import time as _time
        # 1. Sweep our staged zombie documents first, so idle-quit can succeed.
        _force_close_canvas_docs_sync()

        # 2. + 3. Quit each app that has nothing user-owned open; retry once for
        # stragglers (after re-sweeping staged docs, in case a doc was created
        # between the sweep and the first quit attempt).
        stragglers = _quit_pass(1, _QUIT_TARGETS)
        if stragglers:
            _time.sleep(3.0)
            for app, _c in stragglers:
                _force_close_canvas_docs_sync(only_app=app)
            stragglers = _quit_pass(2, stragglers)

        # 4. Wait for the quit apps to actually DIE, then surgically purge our
        # container-staged temp files from Office's Recent-files lists (marker-
        # filtered, so a user's real recent documents are never affected).
        # Purging while an app is still alive is futile - it rewrites the
        # registry DB from memory on exit. Best-effort throughout.
        _wait_for_exit(_QUIT_TARGETS)
        _purge_canvas_recents()

    threading.Thread(target=_worker, daemon=True).start()


# ── Office priming state ────────────────────────────────────────────
# Which Office apps have already been launched/primed this run, and whether the
# macro-security pref has been written. Module-level (not session state) and
# reset by reset_office_priming() at the start of each download/sync run - the
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
    *base_contract* AND at least one matching file exists anywhere under *folder* -
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


# Converter key → (AppleScript app name, container short name). Single source of
# truth for the priming/permission helpers below.
_APP_TRIPLES = [
    ('convert_pptx', "Microsoft PowerPoint", "PowerPoint"),
    ('convert_word', "Microsoft Word", "Word"),
    ('convert_excel', "Microsoft Excel", "Excel"),
]


def _warmup_apps(apps: list, write_macro_pref: bool,
                 touch_containers: bool = False,
                 on_app_answered=None) -> None:
    """Synchronously launch + permission-prime the given Office apps, hidden.

    The shared engine behind both the per-run scoped priming and the one-time
    first-run permission batch. For each app (skipped when not installed at the
    default path): hidden launch (``open -g -j``), a harmless ``count windows``
    Apple event (this is what triggers the per-app Automation TCC prompt), a
    System Events hide (triggers the one-time System Events prompt), and the
    Excel link-dialog suppression. Optionally pre-creates our container staging
    dir (``touch_containers``) so macOS 15's "access data from other apps"
    prompt also fires HERE, at the batched moment, instead of at the first
    conversion.

    ``on_app_answered(app)`` fires only when the TCC-triggering event completed
    (Allow → rc 0, or explicit Deny → -1743) - NOT when it timed out unanswered,
    so an ignored prompt is retried on the next run. Callers run this on a
    worker thread; everything is best-effort.
    """
    if write_macro_pref:
        # Kill the "this workbook contains macros" dialog suite-wide BEFORE any
        # Office app launches. The CORRECT macOS key is VisualBasicMacroExecutionState
        # (a String) on the SHARED `com.microsoft.office` domain - NOT the Windows-only
        # `VBAWarnings`, and NOT a per-app domain. (Confirmed by Microsoft's "Set
        # preferences for macro security in Office for Mac" doc.) "DisabledWithoutWarnings"
        # = macros never run and never prompt. IMPORTANT for the user's "data exactly as
        # the teacher made it" requirement: disabling macro EXECUTION does NOT blank any
        # cells - a workbook's last-saved values are what render to PDF; VBA only matters
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

    short_by_ms = {ms: short for _k, ms, short in _APP_TRIPLES}
    for app in apps:
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
        if touch_containers:
            # Pre-create the staging dir inside the app's sandbox container so
            # the macOS 15 "Canvas Downloader would like to access data from
            # other apps" prompt fires NOW (user is at the screen) rather than
            # at the first conversion. The container exists once the app has
            # launched (we just did); a missing container simply no-ops.
            try:
                _office_container_tmp(short_by_ms.get(app, ''))
            except Exception:
                pass
        answered = False
        try:
            # Harmless Apple Event → triggers the per-app Automation TCC prompt.
            # Returns rc 0 on Allow, -1743 on Deny; raises TimeoutExpired when
            # the prompt sat unanswered - only then is the app NOT recorded as
            # answered, so the next run re-batches it.
            subprocess.run(
                ['osascript', '-e', f'tell application "{app}" to count windows'],
                capture_output=True, timeout=120,
            )
            answered = True
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
            # error (-2741) that `try` can't catch - inline it would kill
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
        if answered and on_app_answered is not None:
            try:
                on_app_answered(app)
            except Exception:
                pass


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

    # Launch an app ONLY when its converter is enabled in *contract* AND it
    # hasn't already been primed this run. Pass a contract SCOPED to the files
    # actually present (office_contract_from_folder / get_synced_file_paths) so
    # a run that only converts PowerPoint never opens Word or Excel. Apps are
    # marked immediately (main thread) so a concurrent call can't double-launch
    # the same app.
    to_launch = []
    for key, ms, _short in _APP_TRIPLES:
        if contract.get(key, False) and ms not in _primed_apps:
            _primed_apps.add(ms)
            to_launch.append(ms)
    if not to_launch:
        return

    global _macro_pref_written
    write_macro_pref = not _macro_pref_written
    if write_macro_pref:
        _macro_pref_written = True

    threading.Thread(
        target=_warmup_apps, args=(to_launch, write_macro_pref), daemon=True,
    ).start()


# ── First-run batched permission setup ──────────────────────────────
# macOS asks for each Automation (TCC) consent the FIRST time the matching
# Apple event is actually sent. Left to chance - with priming scoped to the
# files each run happens to contain - those prompts surface mid-run, one app
# at a time, possibly across different days. Worse, an UNANSWERED prompt makes
# every conversion for that app hang until AppleScript's AppleEvent timeout
# (-1712), which is exactly how a user who stepped away lost 3 Excel files.
# This batch fires every outstanding prompt ONCE, at the start of the user's
# first conversion-enabled run - the one moment they are guaranteed to be at
# the screen, because they just clicked Start.
_first_run_batch_started = False  # at most one batch per process
_PERMISSION_RECORD_FILE = 'macos_permission_setup.json'


def _permission_record_path() -> Path:
    from shared.helpers import get_config_dir
    return Path(get_config_dir()) / _PERMISSION_RECORD_FILE


def _load_permission_record() -> dict:
    """Apps whose Automation prompt has been answered (Allow OR Deny) before."""
    import json
    try:
        with open(_permission_record_path(), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _record_permission_answered(ms_name: str) -> None:
    """Persist that *ms_name*'s Automation prompt was answered (atomic write).

    A Deny is recorded too: macOS will not re-prompt a denied pair anyway, so
    re-batching would only churn app launches - the docs point denied users to
    System Settings → Privacy & Security → Automation instead.
    """
    import json
    import os
    try:
        rec = _load_permission_record()
        rec[ms_name] = True
        path = _permission_record_path()
        tmp = path.with_name(path.name + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def first_run_permission_setup(contract: dict) -> bool:
    """Batch ALL outstanding macOS Office permission prompts at run start.

    *contract* is the UNscoped converter settings (the persistent_convert_*
    toggles) - deliberately not file-scoped: the whole point is to collect the
    prompts for every app the user will EVER need in one predictable moment,
    rather than letting each app's prompt ambush a later run (where an absent
    user means -1712 timeouts and skipped files).

    For each enabled converter whose app is installed and whose Automation
    prompt has never been answered, this launches the app hidden and fires the
    TCC-triggering events (plus the container-staging touch that hoists the
    macOS 15 "access data from other apps" prompt into the same batch).
    Answered apps are recorded in the config dir, so this is one-time per
    machine - NOT per run. Returns True when a batch was actually started, so
    the caller can show a heads-up banner; False otherwise (not macOS, nothing
    outstanding, already ran this process).
    """
    global _first_run_batch_started, _macro_pref_written
    if sys.platform != 'darwin' or _first_run_batch_started:
        return False
    record = _load_permission_record()
    wanted = []
    for key, ms, _short in _APP_TRIPLES:
        if not contract.get(key, False):
            continue
        if record.get(ms):
            continue
        if not Path(f"/Applications/{ms}.app").exists():
            continue
        wanted.append(ms)
    if not wanted:
        return False
    _first_run_batch_started = True
    # Mark as primed for this run so the scoped per-course priming doesn't
    # re-launch what the batch is already warming up.
    _primed_apps.update(wanted)
    write_macro_pref = not _macro_pref_written
    _macro_pref_written = True

    import threading
    threading.Thread(
        target=_warmup_apps,
        args=(wanted, write_macro_pref),
        kwargs={'touch_containers': True, 'on_app_answered': _record_permission_answered},
        daemon=True,
    ).start()
    logger.info(f"[Setup] First-run macOS permission batch started for: {', '.join(wanted)}")
    return True

