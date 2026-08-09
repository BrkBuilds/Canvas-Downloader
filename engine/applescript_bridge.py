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


def applescript_string(text) -> str:
    """Make *text* safe to interpolate into an AppleScript string literal.

    Escapes backslashes first, then double-quotes, then flattens BOTH line
    break characters. Use as: ``display notification "{applescript_string(s)}"``.

    **This is the one implementation, and it is here because the rule had three
    - one of which was wrong.** An AppleScript string literal cannot span lines,
    so a raw ``\\n`` *or* ``\\r`` inside one is a SYNTAX error that takes the
    whole script down; a double-quote or backslash is an injection. Every
    builder in this app agreed on quotes and backslashes and then diverged on
    line breaks: this module and ``shared.helpers.native_folder_picker``
    flattened both, while ``engine.notifications._show_macos_notification``
    flattened only ``\\n`` - so a lone ``\\r`` (a Canvas course name reaches
    that one, via the daily-sync summary) produced an invalid script that
    osascript rejected, and the notification silently never appeared. Same
    divergent-primitive shape as ``make_long_path``'s duplicate in
    ``core/sync_manager.py``: the fix landed on some callers and not others
    because the rule was written more than once.

    This module imports nothing from the app, so every caller can reach it
    without a cycle.
    """
    return (str(text)
            .replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('\n', ' ')
            .replace('\r', ' '))


def _as_posix(path: Path) -> str:
    """Return a POSIX path string safe for embedding in an AppleScript string literal.

    Use inside AppleScript string literals as: ``POSIX file "{_as_posix(path)}"``

    IMPORTANT: Callers that build AppleScript ``script`` strings must use this
    function for every path interpolated into the script to prevent AppleScript
    injection via filenames containing double-quotes or backslashes.

    The line breaks matter and were missing. macOS permits every byte except
    ``/`` and NUL in a filename, so a path carrying one is reachable two ways:
    the user's own download folder (the picker returns whatever they chose), and
    an extracted archive member, whose name comes from the zip and never passes
    through ``_sanitize_filename``. The escaping itself now lives in
    :func:`applescript_string` - see there for why it is only written once.
    """
    return applescript_string(path.resolve())


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

    def _fail(category: str, detail: str) -> bool:
        """Record a conversion failure once, in both places, and return False.

        Every failure exit of this function goes through here so the health
        tally can never drift from ``_last_error`` - the alternative was a
        ``note_failure`` bolted onto each of the five ``_last_error =`` sites,
        which is exactly the shape that goes stale when a sixth is added.
        These failures otherwise reach only the OPT-IN debug log, so on a real
        user's Mac they leave no trace at all - and macOS Office automation is
        the least-tested path this app has, with no crash-telemetry channel.
        """
        global _last_error
        _last_error = (category, detail)
        try:
            from core.health_log import note_failure
            note_failure(f"osascript_{category}")
        except Exception:
            pass
        return False
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
            logger.error(f"[AppleScript] {app_name} failed ({category}): {err_msg}")
            return _fail(category, detail)
        if dst.exists():
            return True
        return _fail('other', f"Microsoft {app_name} reported success but no output file was created.")

    except FileNotFoundError:
        logger.error("[AppleScript] osascript not found (not on macOS?)")
        return _fail('other', 'osascript not found (not on macOS?)')
    except subprocess.TimeoutExpired:
        _fail('timeout', f"Conversion timed out after {timeout_s}s (Microsoft {app_name} stopped responding or the file is very large).")
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
        logger.error(f"[AppleScript] {app_name} error: {e}")
        return _fail('other', str(e))

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


# ── Dock "Suggested and Recent Apps" housekeeping ────────────────────
# macOS adds EVERY launched app to the Dock's recents list; the recents section
# shows the ~3 most recently opened unpinned apps. Our hidden Office automation
# therefore leaves its LAST-launched app (always Excel: priming/quit order is
# PowerPoint → Word → Excel) squatting visibly in the Dock after the run - the
# process is genuinely dead, the ICON is a Dock recents tile the user has to
# right-click → Remove from Dock. (This is why the round-5 "quit properly +
# escalate survivors" fix didn't clear the icon: quitting was never the issue.)
# Fix: snapshot which Office apps sat in Dock recents BEFORE the run's first
# hidden launch, and after the quit pass strip exactly the entries we added -
# never a pre-existing tile, never a running app - then restart the Dock (the
# only way it re-reads the list). The Dock is only ever restarted when a wrong
# icon would otherwise stay visible.

_OFFICE_BUNDLE_IDS = {
    "Microsoft PowerPoint": "com.microsoft.powerpoint",
    "Microsoft Word":       "com.microsoft.word",
    "Microsoft Excel":      "com.microsoft.excel",
}

# Office bundle ids present in Dock recents before OUR first Office launch this
# run. None = we have not launched any Office app (cleanup must then never
# touch the Dock). Reset by reset_office_priming() at each run start.
_dock_recents_before: set | None = None


def _dock_prefs_export() -> dict | None:
    """The full com.apple.dock domain as a dict (via cfprefsd), or None."""
    import plistlib
    try:
        r = subprocess.run(['defaults', 'export', 'com.apple.dock', '-'],
                           capture_output=True, timeout=10)
        if r.returncode != 0 or not r.stdout:
            return None
        return plistlib.loads(r.stdout)
    except Exception:
        return None


def _recents_entry_bundle_id(entry) -> str:
    try:
        return ((entry.get('tile-data') or {}).get('bundle-identifier') or '').lower()
    except AttributeError:
        return ''


def _office_ids_in_dock_recents(dock: dict | None) -> set:
    office = set(_OFFICE_BUNDLE_IDS.values())
    found = set()
    for entry in (dock or {}).get('recent-apps') or []:
        bid = _recents_entry_bundle_id(entry)
        if bid in office:
            found.add(bid)
    return found


def _snapshot_dock_recents() -> None:
    """Remember which Office apps were ALREADY in Dock recents pre-run.

    Called (main thread, cheap: one ``defaults export``) right before the
    run's first hidden Office launch. Only taken once per run - later priming
    calls see the snapshot in place and keep the original baseline.
    """
    global _dock_recents_before
    if sys.platform != 'darwin' or _dock_recents_before is not None:
        return
    dock = _dock_prefs_export()
    # Export failure -> treat every Office tile as pre-existing (never clean).
    _dock_recents_before = (_office_ids_in_dock_recents(dock)
                            if dock is not None else set(_OFFICE_BUNDLE_IDS.values()))


def _office_pgrep_alive(app_name: str) -> bool:
    """BSD-level liveness (pgrep) - True on any doubt (safe default)."""
    try:
        return subprocess.run(['pgrep', '-x', app_name],
                              capture_output=True, timeout=10).returncode == 0
    except Exception:
        return True


def _strip_office_recents_tiles() -> list[str]:
    """One export -> filter -> import -> ``killall Dock`` pass.

    Removes a recents tile only when ALL of these hold: it is one of the three
    Office apps, the app was NOT in recents before the run, and its process is
    not running now. Returns the bundle ids removed ([] = nothing needed, so
    the Dock was NOT restarted).
    """
    dock = _dock_prefs_export()
    if not dock:
        return []
    recents = dock.get('recent-apps')
    if not isinstance(recents, list) or not recents:
        return []
    name_by_bid = {b: n for n, b in _OFFICE_BUNDLE_IDS.items()}

    def _removable(entry) -> bool:
        bid = _recents_entry_bundle_id(entry)
        if bid not in name_by_bid or bid in _dock_recents_before:
            return False
        return not _office_pgrep_alive(name_by_bid[bid])

    kept, removed = [], []
    for entry in recents:
        (removed if _removable(entry) else kept).append(entry)
    if not removed:
        return []
    dock['recent-apps'] = kept
    import plistlib
    try:
        payload = plistlib.dumps(dock, fmt=plistlib.FMT_XML)
        p = subprocess.run(['defaults', 'import', 'com.apple.dock', '-'],
                           input=payload, capture_output=True, timeout=10)
        if p.returncode != 0:
            logger.info("[OfficeQuit] Dock recents rewrite failed (rc=%s): %s",
                        p.returncode,
                        (p.stderr or b'').decode(errors='replace')[:200])
            return []
        subprocess.run(['killall', 'Dock'], capture_output=True, timeout=10)
        removed_ids = [_recents_entry_bundle_id(e) for e in removed]
        logger.info(
            "[OfficeQuit] removed %d Office tile(s) from Dock recents (%s) "
            "and refreshed the Dock", len(removed_ids), ", ".join(removed_ids))
        return removed_ids
    except Exception as e:
        logger.debug(f"[OfficeQuit] Dock recents cleanup skipped: {e}")
        return []


def _cleanup_dock_recents() -> None:
    """Strip OUR hidden Office launches from the Dock's recents section.

    Only runs when this run actually launched Office apps (snapshot exists)
    and the recents section is enabled. The Dock is restarted (``killall
    Dock`` - it only reads the list at startup) only when at least one tile
    was actually removed, so the one-off Dock flicker happens exactly when a
    wrong icon would otherwise stay visible.

    TIMING IS THE WHOLE GAME (2026-07-09 19:34 run): the Dock MOVES a quit
    app into its recents list when it processes the app's TERMINATION. The
    first implementation rewrote+restarted the Dock 0.4s after Excel's "quit
    sent" - Word/PPT were already dead so their tiles stayed gone, but Excel
    (always quit LAST, and the slowest to tear down: it rewrites its Recents
    registry on exit) was still terminating; the freshly restarted Dock
    watched it die and re-added its tile. So: wait until every Office process
    is BSD-dead (pgrep), give the Dock a moment to commit its own recents
    write, strip, and VERIFY once after the restart - a tile that was
    re-added by a racing termination event is stripped by the second pass.
    """
    if sys.platform != 'darwin' or _dock_recents_before is None:
        return
    # Recents section disabled -> the list is invisible; nothing to clean.
    if not _dock_recents_enabled():
        return

    import time as _t
    # 1. Wait for every Office process to be truly gone (bounded; an app kept
    # alive by the user's own documents simply stays - its tile is then
    # protected by the pgrep check inside the strip pass anyway).
    _deadline = _t.time() + 15
    while _t.time() < _deadline:
        if not any(_office_pgrep_alive(n) for n in _OFFICE_BUNDLE_IDS):
            break
        _t.sleep(0.5)
    # 2. Wait for the Dock's TERMINATION write. Tile PRESENCE is not a safe
    # signal: the Dock also writes tiles at LAUNCH, which is what satisfied
    # the previous expected-tiles poll instantly on the 21:26 run - the strip
    # still ran before Excel's termination write and the verify pass had to
    # restart the Dock a SECOND time. What is reliably observable is the
    # WRITE itself: the Dock rewrites recent-apps when it processes an app's
    # termination, 0-6s after the process dies (measured across the 21:08 /
    # 21:26 runs). So watch the list: strip only after at least one CHANGE
    # has been observed and the list has then stayed quiet for two
    # consecutive 1s samples (per-app writes usually batch into one Dock
    # pass), or after 8s if no write ever shows (it landed before our first
    # sample, or the Dock declined to add a tile). The verify pass below
    # remains the net for the outliers.
    if any(_ms in _primed_apps and _bid not in _dock_recents_before
           for _ms, _bid in _OFFICE_BUNDLE_IDS.items()):
        _prev = (_dock_prefs_export() or {}).get('recent-apps')
        _changed = False
        _quiet = 0
        _deadline = _t.time() + 8
        while _t.time() < _deadline:
            _t.sleep(1.0)
            _cur = (_dock_prefs_export() or {}).get('recent-apps')
            if _cur != _prev:
                _prev, _changed, _quiet = _cur, True, 0
                continue
            if _changed:
                _quiet += 1
                if _quiet >= 2:
                    break
    # 3. Strip; when something was removed, verify once after the restart
    # (normally a no-op now - it only acts, and only then restarts the Dock
    # again, if a tile still slipped in after the poll above).
    if not _strip_office_recents_tiles():
        return
    _t.sleep(3.0)
    if _strip_office_recents_tiles():
        logger.info("[OfficeQuit] Dock recents needed a second pass (a tile "
                    "was re-added by a racing termination event)")


# ── Self (Canvas Downloader) Dock recents housekeeping ───────────────
# Two ways a phantom "Canvas Downloader" tile (no running process, no dot)
# lands in the Dock's recents section (2026-07-10 Today-mode run, macOS 15):
#   1. Transcription re-execs THIS app's binary per recording
#      (panopto.transcribe). The PyInstaller windowed bootloader registers the
#      child with LaunchServices before start.py can demote it to a Prohibited
#      background process, and the Dock may file the child's TERMINATION
#      (normal exit, or the SIGKILL a cancel sends) as a recents tile.
#   2. System Settings' "Quit & Reopen" (the Full Disk Access grant flow)
#      relaunches the app under a fresh LaunchServices identity; the OLD
#      instance's termination files a tile that can never merge with the
#      running app's (same for a stale App-Translocation launch path).
# Same disease as the Office tiles above, same proven cure: snapshot, strip
# exactly what appeared, restart the Dock only when a tile was removed.

_OWN_BUNDLE_ID = "com.canvasdownloader.app"

# OUR recents rows (raw file-URL keys) present before this Panopto batch.
# None = no snapshot taken -> cleanup must never touch the Dock.
_own_recents_before: set | None = None


def _dock_recents_enabled() -> bool:
    """False only when the Dock's recents section is explicitly disabled."""
    try:
        r = subprocess.run(['defaults', 'read', 'com.apple.dock', 'show-recents'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and (r.stdout or '').strip().lower() in ('0', 'false', 'no'):
            return False
    except Exception:
        pass
    return True


def _recents_entry_url(entry) -> str:
    """The raw _CFURLString of a recents row ('' when absent)."""
    try:
        return (((entry.get('tile-data') or {}).get('file-data') or {})
                .get('_CFURLString') or '')
    except AttributeError:
        return ''


def _recents_entry_path(entry) -> str:
    """A recents row's bundle path, normalized for comparison ('' when absent)."""
    import os
    from urllib.parse import unquote, urlparse
    url = _recents_entry_url(entry)
    if not url:
        return ''
    path = unquote(urlparse(url).path) if url.startswith('file:') else url
    return os.path.realpath(path.rstrip('/')) if path else ''


def _own_bundle_path() -> str:
    """The RUNNING instance's .app bundle path ('' when not bundled, e.g. dev)."""
    import os
    exe = os.path.realpath(sys.executable)
    idx = exe.rfind('.app/Contents/')
    return exe[:idx + 4] if idx > 0 else ''


def _own_recents_rows(dock: dict | None) -> set:
    """Raw file-URL keys of every recents row carrying OUR bundle id."""
    return {
        _recents_entry_url(entry)
        for entry in (dock or {}).get('recent-apps') or []
        if _recents_entry_bundle_id(entry) == _OWN_BUNDLE_ID
    }


def _commit_dock_recents(dock: dict, kept: list, removed: list, tag: str) -> int:
    """defaults-import the filtered recent-apps + restart the Dock.

    Returns the number of rows removed (0 = nothing written, Dock untouched).
    """
    if not removed:
        return 0
    dock['recent-apps'] = kept
    import plistlib
    try:
        payload = plistlib.dumps(dock, fmt=plistlib.FMT_XML)
        p = subprocess.run(['defaults', 'import', 'com.apple.dock', '-'],
                           input=payload, capture_output=True, timeout=10)
        if p.returncode != 0:
            logger.info("[%s] Dock recents rewrite failed (rc=%s): %s", tag,
                        p.returncode,
                        (p.stderr or b'').decode(errors='replace')[:200])
            return 0
        subprocess.run(['killall', 'Dock'], capture_output=True, timeout=10)
        logger.info(
            "[%s] removed %d phantom Canvas Downloader tile(s) from Dock "
            "recents (%s) and refreshed the Dock", tag, len(removed),
            ", ".join(_recents_entry_url(e) or '<no url>' for e in removed))
        return len(removed)
    except Exception as e:
        logger.debug(f"[{tag}] Dock recents cleanup skipped: {e}")
        return 0


def snapshot_own_dock_recents() -> None:
    """Remember OUR pre-batch Dock-recents rows (Panopto batch start, darwin).

    Re-taken per batch (batch scope, unlike the once-per-run Office snapshot).
    Export failure -> None -> cleanup never touches the Dock (fail-safe).
    """
    global _own_recents_before
    if sys.platform != 'darwin':
        return
    dock = _dock_prefs_export()
    _own_recents_before = _own_recents_rows(dock) if dock is not None else None


def _strip_own_recents_tiles() -> int:
    """Remove OUR rows that were NOT in the snapshot. Returns rows removed."""
    if _own_recents_before is None:
        return 0
    dock = _dock_prefs_export()
    recents = (dock or {}).get('recent-apps')
    if not isinstance(recents, list) or not recents:
        return 0
    kept, removed = [], []
    for entry in recents:
        if (_recents_entry_bundle_id(entry) == _OWN_BUNDLE_ID
                and _recents_entry_url(entry) not in _own_recents_before):
            removed.append(entry)
        else:
            kept.append(entry)
    return _commit_dock_recents(dock, kept, removed, 'SelfDock')


def cleanup_own_dock_recents() -> None:
    """Strip the phantom Canvas Downloader tiles this Panopto batch added.

    Called (daemon thread) when the batch ends - every exit path, including
    cancel, which SIGKILLs the live worker and is the likeliest tile filer.
    Timing mirrors _cleanup_dock_recents: the Dock files a tile when it
    processes a TERMINATION, 0-6s after the process dies; the last worker
    exits right before the batch returns. So watch recent-apps until a write
    has been observed and the list stays quiet for two 1s samples (8s cap),
    strip, and verify once after 3s for a racing write.
    """
    global _own_recents_before
    if sys.platform != 'darwin' or _own_recents_before is None:
        return
    if not _dock_recents_enabled():
        _own_recents_before = None
        return
    import time as _t
    _prev = (_dock_prefs_export() or {}).get('recent-apps')
    _changed = False
    _quiet = 0
    _deadline = _t.time() + 8
    while _t.time() < _deadline:
        _t.sleep(1.0)
        _cur = (_dock_prefs_export() or {}).get('recent-apps')
        if _cur != _prev:
            _prev, _changed, _quiet = _cur, True, 0
            continue
        if _changed:
            _quiet += 1
            if _quiet >= 2:
                break
    if _strip_own_recents_tiles():
        _t.sleep(3.0)
        if _strip_own_recents_tiles():
            logger.info("[SelfDock] recents needed a second pass (a tile was "
                        "re-added by a racing termination event)")
    _own_recents_before = None


def purge_stale_self_dock_tiles() -> None:
    """Strip DEAD-IDENTITY Canvas Downloader tiles from Dock recents (boot).

    A recents row carrying our bundle id whose bundle path is not the RUNNING
    bundle's is a dead LaunchServices identity - left by System Settings'
    "Quit & Reopen" (Full Disk Access grant) or by a previous session's
    App-Translocation path. It can never merge with the running app's tile,
    so it squats in the Dock as a second Canvas Downloader with no process
    behind it. The row from a NORMAL previous quit has the SAME path as the
    running bundle and is deliberately kept (stripping it would restart the
    Dock on every boot for nothing). Runs once at GUI boot, off-thread.
    """
    if sys.platform != 'darwin' or not _dock_recents_enabled():
        return
    own = _own_bundle_path()
    if not own:
        return  # not running from an .app bundle (dev) - identity unknowable
    dock = _dock_prefs_export()
    recents = (dock or {}).get('recent-apps')
    if not isinstance(recents, list) or not recents:
        return
    kept, removed = [], []
    for entry in recents:
        if (_recents_entry_bundle_id(entry) == _OWN_BUNDLE_ID
                and _recents_entry_path(entry) != own):
            removed.append(entry)
        else:
            kept.append(entry)
    _commit_dock_recents(dock, kept, removed, 'SelfDock/boot')


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

    Structured as three PHASE-TAGGED stages so the returned status pinpoints
    exactly where a failure happened (Excel's gallery-state ``-1700: Can't
    make missing value into type number`` survived two earlier fixes because
    the single "error N" status could not say WHAT threw):

      "enum failed (error N)"     resolving ``{collection} as list`` threw
      "doc scan failed (error N)" reading the documents' properties threw
      "kept running (...)"        a user-owned document blocks the quit
      "quit failed (error N)"     zero user docs, but the quit verb threw
      "quit sent (...)" / "not running"

    Two hard-won structural rules:
      1. The ``repeat`` loop lives OUTSIDE any ``tell application`` block.
         Inside an application tell, ``repeat with x in someList`` dispatches
         its implicit ``count`` command TO THE APP - and Excel's gallery
         state can throw -1700 on events a local evaluation handles fine.
         Each property read targets the app explicitly, per statement.
      2. The quit verb is ``quit saving no`` FIRST (plain ``quit`` as the
         error retry). A plain ``quit`` never errors when a document has
         unsaved changes - the app just shows a (hidden) save sheet and
         waits forever, while the Apple event returns fine and we log
         "quit sent". That is exactly what the 2026-07-09 round-5 run
         showed: Excel answered "quit sent (1 open doc)" and was STILL
         alive with that doc 5 minutes later. ``saving no`` is prompt-free
         and safe here: it is only reached after zero user-owned documents
         were counted.

    The Python caller escalates on the failure statuses: "quit failed"
    certifies no user documents, and for enum/scan failures a separate
    document-count probe (see ``_probe_open_docs``) certifies the app is
    empty before it is force-terminated. Additionally, any app whose status
    carried the "none user-owned" certificate but which SURVIVES the
    post-quit exit wait is terminated - so a save-sheet-stuck or otherwise
    lingering Excel can no longer squat in the dock and resurrect its
    Recents entries.
    """
    return f'''
        tell application "System Events"
            if not (exists process "{app}") then return "not running"
        end tell
        set docList to {{}}
        try
            tell application "{app}" to set docList to ({collection} as list)
        on error errMsg number errNum
            return "enum failed (error " & errNum & "): " & errMsg
        end try
        set total to 0
        set blockers to 0
        try
            repeat with d in docList
                set total to total + 1
                set pristine to false
                try
                    set hasPath to false
                    try
                        tell application "{app}" to set p to (path of d as text)
                        if p is not "" then set hasPath to true
                    end try
                    if not hasPath then
                        try
                            tell application "{app}" to set fn to (full name of d as text)
                            if fn contains "/" then set hasPath to true
                        end try
                    end if
                    set isSaved to true
                    try
                        tell application "{app}" to set isSaved to (saved of d)
                    end try
                    if (not hasPath) and isSaved then set pristine to true
                end try
                if not pristine then set blockers to blockers + 1
            end repeat
        on error errMsg number errNum
            return "doc scan failed (error " & errNum & "): " & errMsg
        end try
        if blockers > 0 then return "kept running (" & blockers & " of " & total & " doc(s) look user-owned)"
        try
            tell application "{app}" to quit saving no
        on error
            try
                tell application "{app}" to quit
            on error errMsg number errNum
                return "quit failed (error " & errNum & "): " & errMsg & " [" & total & " open doc(s), none user-owned]"
            end try
        end try
        return "quit sent (" & total & " open doc(s), none user-owned)"
    '''


def _probe_open_docs(app: str, collection: str) -> str:
    """Ask *app* how many documents it has open - the kill-safety certificate.

    Returns "gone", "docs N", "count failed (error N)" or "probe failed: ...".
    The semantics that make this a safe gate: an Office app with a REAL open
    document answers ``count of <collection>`` reliably; the pathological
    gallery/no-document state is precisely where the count (like the
    enumeration) throws. So "docs 0" and "count failed" both certify that no
    user document exists, while "docs N>0" or a timeout (possible modal
    dialog) mean the app must be left alone.
    """
    script = f'''
        tell application "System Events"
            if not (exists process "{app}") then return "gone"
        end tell
        try
            tell application "{app}" to set n to (count of {collection})
            return "docs " & n
        on error errMsg number errNum
            return "count failed (error " & errNum & ")"
        end try
    '''
    try:
        r = subprocess.run(['osascript', '-e', script],
                           capture_output=True, text=True, timeout=15)
        return (r.stdout or "").strip() or f"probe failed: rc={r.returncode}"
    except Exception as e:
        return f"probe failed: {e}"


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

    def _quit_pass(pass_no: int, targets) -> tuple[list, dict]:
        """Ask each target app to quit.

        Returns ``(still_running, statuses)`` - the targets whose quit did not
        go through, plus each app's raw status string so the caller can pick
        the right escalation ("quit failed" = zero user-owned docs certified
        by the script but the quit verb errored → force-terminate is safe;
        "kept running"/"error" = leave the app alone).
        """
        still_running = []
        statuses: dict = {}
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
            statuses[app] = status
            if not status.startswith(("quit sent", "not running")):
                still_running.append((app, collection))
        return still_running, statuses

    def _terminate_gallery_stuck(app: str) -> None:
        """Terminate *app* after its scripted quit failed WITH the certificate
        that no user document is open (a "quit failed" status or a passing
        ``_probe_open_docs`` gate).

        Tries one last graceful ``quit saving no`` (harmless: nothing to
        discard), then SIGTERMs if the process is still alive. The SIGTERM
        path also skips the app's exit-time rewrite of the shared Recents
        registry DB, so the marker purge below sticks.
        """
        import time as _t
        try:
            subprocess.run(
                ['osascript', '-e', f'tell application "{app}" to quit saving no'],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass
        _t.sleep(1.0)
        try:
            still = subprocess.run(['pgrep', '-x', app], capture_output=True, timeout=10)
            if still.returncode == 0:
                subprocess.run(['pkill', '-x', app], capture_output=True, timeout=10)
                logger.info(
                    "[OfficeQuit] force-terminated %s (no user documents open)", app)
            else:
                logger.info(
                    "[OfficeQuit] %s exited on the final 'quit saving no'", app)
        except Exception as e:
            logger.info("[OfficeQuit] force-terminate of %s failed: %s", app, e)

    def _wait_for_exit(apps: list, timeout: float = 12.0) -> list:
        """Poll until every app in *apps* has actually terminated (or timeout).

        Returns the apps STILL RUNNING at the deadline so the caller can
        escalate (round 5 showed Excel answering "quit sent" and then simply
        never exiting - a hidden save sheet stalls a quit without any error).

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
            logger.info("[OfficeQuit] still running after %.0fs wait: %s",
                        timeout, ", ".join(remaining))
        return remaining

    def _worker():
        import time as _time
        # 1. Sweep our staged zombie documents first, so idle-quit can succeed.
        _force_close_canvas_docs_sync()

        # 2. + 3. Quit each app that has nothing user-owned open; retry once for
        # stragglers (after re-sweeping staged docs, in case a doc was created
        # between the sweep and the first quit attempt).
        stragglers, statuses = _quit_pass(1, _QUIT_TARGETS)
        if stragglers:
            _time.sleep(3.0)
            for app, _c in stragglers:
                _force_close_canvas_docs_sync(only_app=app)
            stragglers, _retry_statuses = _quit_pass(2, stragglers)
            statuses.update(_retry_statuses)

        # 3b. Escalation for the failure statuses. Two certified-safe paths:
        #   - "quit failed": the script itself counted zero user-owned docs
        #     before the quit verb threw -> terminate directly.
        #   - "enum failed"/"doc scan failed" (Excel's gallery-state -1700
        #     pathology): the script could not inspect the documents, so ask
        #     for a document COUNT first (_probe_open_docs). "docs 0" and
        #     "count failed" both certify the empty/gallery state (a real
        #     open workbook answers the count); anything else - including a
        #     timeout, which can mean a modal dialog - leaves the app alone.
        _terminated = []
        _certified_safe = set()   # apps certified to hold no user documents
        for app, coll in stragglers:
            st = statuses.get(app, "")
            if st.startswith("quit failed"):
                _certified_safe.add(app)
                _terminate_gallery_stuck(app)
                _terminated.append((app, coll))
            elif "failed" in st or st.startswith("error"):
                probe = _probe_open_docs(app, coll)
                logger.info("[OfficeQuit] %s document probe -> %s", app, probe)
                if probe == "gone":
                    continue
                if probe == "docs 0" or probe.startswith("count failed"):
                    _certified_safe.add(app)
                    _terminate_gallery_stuck(app)
                    _terminated.append((app, coll))
                else:
                    logger.info(
                        "[OfficeQuit] leaving %s running (cannot certify it "
                        "has no user documents open)", app)

        # 4. Wait for the quit apps to actually DIE, then surgically purge our
        # container-staged temp files from Office's Recent-files lists (marker-
        # filtered, so a user's real recent documents are never affected).
        # Purging while an app is still alive is futile - it rewrites the
        # registry DB from memory on exit. Only apps we actually asked to exit
        # are waited on, so a legitimately busy app ("kept running") no longer
        # stalls the purge for the full timeout.
        #
        # Escalation on survivors: "quit sent" only means the Apple event was
        # DELIVERED - an app can then stall its own quit forever on a hidden
        # sheet (round 5: Excel answered "quit sent (1 open doc, none
        # user-owned)" and was still alive, doc and all, 5 minutes later,
        # squatting in the dock). Every status that reached the quit verb
        # carries the "none user-owned" certificate, so terminating a
        # survivor is provably safe - and SIGTERM also skips the app's
        # exit-time Recents rewrite, which is what lets the purge stick.
        _expected_exits = [
            (app, coll) for app, coll in _QUIT_TARGETS
            if statuses.get(app, "").startswith(("quit sent", "quit failed"))
        ]
        for pair in _terminated:
            if pair not in _expected_exits:
                _expected_exits.append(pair)
        for app, _coll in _expected_exits:
            if "none user-owned" in statuses.get(app, ""):
                _certified_safe.add(app)
        if _expected_exits:
            _survivors = _wait_for_exit(_expected_exits)
            _escalated = []
            for app in _survivors:
                if app in _certified_safe:
                    logger.info(
                        "[OfficeQuit] %s survived the exit wait despite '%s' "
                        "- escalating to terminate", app, statuses.get(app, ""))
                    _terminate_gallery_stuck(app)
                    _escalated.append((app, None))
                else:
                    logger.info(
                        "[OfficeQuit] %s survived the exit wait without a "
                        "no-user-docs certificate - leaving it alone", app)
            if _escalated:
                _wait_for_exit(_escalated, timeout=6.0)
        _purge_canvas_recents()
        # 5. Drop OUR hidden launches from the Dock's "Suggested and Recent
        # Apps" section - the process being dead does not remove its recents
        # tile (the "Excel still in the Dock after the run" report), and the
        # Dock only re-reads the list on restart. Snapshot-scoped: only tiles
        # our own priming added this run are ever touched.
        _cleanup_dock_recents()

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
    global _macro_pref_written, _dock_recents_before
    _primed_apps.clear()
    _macro_pref_written = False
    _dock_recents_before = None


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

    Also re-touches our container staging dirs (``touch_containers=True``):
    the macOS 15+ App Data consent is TRANSIENT (process lifetime - see
    arm_app_data_access), so unlike the Automation grants it must be re-armed
    every session, not just in the one-time first-run batch. The touch is
    silent when the session's consent already exists; when it doesn't, the
    prompt fires here (mid-download, user recently clicked Start) instead of
    hanging the first conversion.
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

    # Baseline the Dock recents BEFORE the first hidden launch, so the
    # completion-screen cleanup can tell our tiles from pre-existing ones.
    _snapshot_dock_recents()

    threading.Thread(
        target=_warmup_apps, args=(to_launch, write_macro_pref),
        kwargs={'touch_containers': True}, daemon=True,
    ).start()


def arm_app_data_access(contract: dict) -> None:
    """Fire this session's macOS 15+ "access data from other apps" prompt NOW.

    Conversions stage files inside the Office apps' own sandbox containers
    (office_container_stage), which macOS 15+ gates behind the App Data
    consent. Unlike the Automation grants, that consent is TRANSIENT: Apple
    DTS classifies the privilege as "transient, process lifetime" (dev forums
    thread 742147), so macOS forgets it the moment the app quits and re-asks
    once per app instance - no recording, signing identity, or first-run batch
    can make it stick. (Full Disk Access is the only durable bypass; the
    mac-setup guide documents it.)

    So the best available UX is to make the session's single prompt fire at
    RUN START - the user just clicked Start and is at the screen - by touching
    our staging dir inside every already-existing Office container. Consent is
    granted app-wide per instance, so one Allow covers all later staging AND
    the quit-time Recents purge in the Office group container. Runs on a
    daemon thread: a pending TCC consent BLOCKS the touching syscall until the
    user answers, and that must never freeze the run itself. Idempotent and
    silent when this session's consent (or Full Disk Access) already exists;
    containers that don't exist yet are skipped here and covered instead by
    the touch inside per-run priming, which runs right after the app launches.
    """
    if sys.platform != 'darwin':
        return
    if not any(contract.get(key, False) for key, _ms, _short in _APP_TRIPLES):
        return
    import threading

    def _touch_all():
        # The TCC dialog itself is invisible to us; the only observable is that
        # the first touch BLOCKS until the user answers. Log the duration so
        # debug_log.txt shows whether (and how long) the prompt was up.
        import time as _t
        t0 = _t.time()
        for _key, _ms, short in _APP_TRIPLES:
            try:
                _office_container_tmp(short)
            except Exception:
                pass
        took = _t.time() - t0
        logger.info(
            f"[Setup] App Data container arming finished in {took:.1f}s"
            + (" (consent prompt was likely shown)" if took > 2 else "")
        )

    threading.Thread(target=_touch_all, daemon=True).start()


# ── Full Disk Access (the permanent App Data silence) ───────────────
# FDA-granted apps are exempt from the macOS 15+ App Data check entirely - the
# only DURABLE way to kill the once-per-session "access data from other apps"
# prompt (see arm_app_data_access). These helpers back the Today page's
# "make it fully hands-off" nudge.

_FDA_SETTINGS_URL = (
    'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'
)


def is_macos_15_plus() -> bool:
    """True on macOS 15 Sequoia or newer - where App Data protection exists."""
    if sys.platform != 'darwin':
        return False
    try:
        import platform
        return int((platform.mac_ver()[0] or '0').split('.')[0]) >= 15
    except Exception:
        return False


def has_full_disk_access() -> bool:
    """Best-effort: does this app currently hold Full Disk Access?

    Reads one byte of the user TCC database - a file readable ONLY with FDA
    (kTCCServiceSystemPolicyAllFiles). Probing is silent by construction: FDA
    has no consent prompt (grants live solely in System Settings), so this can
    never pop a dialog. Un-cached on purpose - the user can flip the toggle in
    System Settings mid-session and the next rerun should notice. Any failure
    reports False (worst case: a granted user sees a dismissible nudge).
    """
    if sys.platform != 'darwin':
        return False
    try:
        tcc_db = (Path.home() / 'Library' / 'Application Support'
                  / 'com.apple.TCC' / 'TCC.db')
        with open(tcc_db, 'rb') as fh:
            fh.read(1)
        return True
    except Exception:
        return False


def open_full_disk_access_settings() -> None:
    """Open System Settings directly on Privacy & Security → Full Disk Access.

    The legacy prefpane anchor URL still deep-links correctly in the new
    System Settings (Ventura through Tahoe). Falls back to plainly launching
    System Settings if the anchor is ever rejected. Best-effort, never raises.
    """
    if sys.platform != 'darwin':
        return
    try:
        r = subprocess.run(['open', _FDA_SETTINGS_URL],
                           capture_output=True, timeout=15)
        if r.returncode == 0:
            return
    except Exception:
        pass
    try:
        subprocess.run(['open', '-b', 'com.apple.systempreferences'],
                       capture_output=True, timeout=15)
    except Exception:
        pass


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
    macOS 15 "access data from other apps" prompt into the same batch - but
    NOTE: that consent is transient per app instance and re-armed each session
    by arm_app_data_access / per-run priming; only the Automation grants are
    what this batch settles durably). Answered apps are recorded in the config
    dir, so this is one-time per machine - NOT per run. Returns True when a batch was actually started, so
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

    # Baseline the Dock recents BEFORE the first hidden launch (see
    # _snapshot_dock_recents) - the batch is about to launch every wanted app.
    _snapshot_dock_recents()

    import threading
    threading.Thread(
        target=_warmup_apps,
        args=(wanted, write_macro_pref),
        kwargs={'touch_containers': True, 'on_app_answered': _record_permission_answered},
        daemon=True,
    ).start()
    logger.info(f"[Setup] First-run macOS permission batch started for: {', '.join(wanted)}")
    return True

