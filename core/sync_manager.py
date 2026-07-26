"""
Sync Manager Module for Canvas LMS Batch File Downloader
Handles synchronization between Canvas courses and local files.
"""

import os
import json
import hashlib
import logging
import re
import sqlite3
import time
import uuid
import difflib
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Callable
import threading

# SQLite connection pattern used throughout this module:
#     with closing(sqlite3.connect(...)) as conn, conn:
# The inner `conn` context manager keeps sqlite3's transaction semantics
# (commit on success, rollback on exception - identical to the previous bare
# `with sqlite3.connect(...) as conn:`), while the outer closing() guarantees
# the handle is CLOSED on exit instead of lingering until garbage collection.
# On Windows a lingering handle transiently locks the .canvas_sync.db file,
# which can break folder moves/deletes and external tools between operations.

# Module-level logger
logger = logging.getLogger(__name__)

_groups_lock = threading.RLock()

# Characters CanvasManager._sanitize_filename strips when writing files to disk.
# We mirror that stripping when matching Canvas-side names (which keep these
# characters) against on-disk filenames (which had them removed), so a Canvas
# file "My:Notes.pdf" written to disk as "MyNotes.pdf" still matches itself.
_FS_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _match_key(name: str) -> str:
    """Filesystem-aware normalized key for robust filename matching.

    Combines ``robust_filename_normalize`` (unquote + NFC + lower) with the
    dangerous-character stripping the downloader applies at write time, so the
    analyzer's view and the on-disk reality always compare equal. Used by both
    auto-discovery (``analyze_course``) and ``heal_manifest``.
    """
    from shared.helpers import robust_filename_normalize
    return _FS_UNSAFE_RE.sub('', robust_filename_normalize(name))


# --- Data Classes ---

@dataclass
class CanvasFileInfo:
    """Represents file metadata from Canvas API."""
    id: int
    filename: str
    display_name: str
    size: int
    modified_at: Optional[str]  # ISO format UTC
    url: str
    md5: Optional[str] = None
    content_type: str = ""
    folder_id: Optional[int] = None  # Canvas folder ID for structure mapping
    # Signature of the SOURCE content for secondary entities (assignments,
    # announcements, ...): an md5 over the raw Canvas-side fields, computed
    # during analysis. Update detection compares it against the manifest's
    # stored content_sig, making it immune to Canvas timestamp churn AND to
    # local post-processing (HTML→MD renames the file and changes its bytes,
    # but never touches the source signature). Empty = unknown/not computed.
    content_sig: str = ""
    # True when ``filename`` is an app-CONSTRUCTED on-disk name (Mode A
    # attachment prefixes like "Assignment: X - file.pdf", category paths,
    # ...) that must be used verbatim. Blocks the display_name preference in
    # preferred_disk_name().
    name_locked: bool = False
    # Alternate synthetic id this entity may be tracked under in OLDER
    # manifests. Module Pages were historically keyed two ways: the download
    # engine records them by PAGE id (-page_id) while sync-created entries used
    # the MODULE ITEM id (-item.id) - so a downloaded course re-analyzed for
    # sync saw every page as "new" and downloaded a duplicate. Analysis now
    # emits the page id as primary and carries the module-item id here;
    # analyze_course falls back to it when only the legacy key is tracked.
    legacy_sync_id: int = 0


def preferred_disk_name(c_file) -> str:
    """The name a REGULAR Canvas file should carry on disk.

    Canvas exposes two names per file: the raw upload ``filename`` (often
    ``final_v3_REAL2.pdf``) and the teacher-curated ``display_name`` (what
    students actually see in Canvas). All other content types (pages,
    assignments, Panopto) already save under their human title, so regular
    files prefer ``display_name`` too - with guards:

      - synthetic/secondary entities (negative id) keep their constructed name;
      - ``name_locked`` names (Mode A attachment prefixes) are used verbatim;
      - a blank display_name falls back to ``filename``;
      - when display_name lacks the real extension, ``filename``'s extension
        is appended so the file still opens correctly.

    Sanitization is the caller's job (``CanvasManager._sanitize_filename``),
    exactly as it was for the raw filename.
    """
    raw = getattr(c_file, 'filename', '') or ''
    if getattr(c_file, 'id', 0) <= 0 or getattr(c_file, 'name_locked', False):
        return raw
    disp = (getattr(c_file, 'display_name', '') or '').strip()
    if not disp:
        return raw
    f_ext = Path(raw).suffix
    if f_ext and not disp.lower().endswith(f_ext.lower()):
        disp += f_ext
    return disp


def secondary_content_sig(*parts) -> str:
    """Stable md5 signature over the raw source fields of a secondary entity.

    Fed ONLY Canvas-side values (title, raw body HTML, due/points/...) - never
    locally rendered output - so the signature is independent of the HTML
    template, date formatting preferences, and post-processing conversions.
    ``None`` and missing values normalize to '' so absent fields hash stably.
    """
    h = hashlib.md5()
    for p in parts:
        h.update(str(p if p is not None else '').encode('utf-8', 'replace'))
        h.update(b'\x1f')  # unit separator so ('ab','c') != ('a','bc')
    return h.hexdigest()


@dataclass
class SyncFileInfo:
    """Represents a file in the sync manifest."""
    canvas_file_id: int
    canvas_filename: str
    local_path: str  # Relative to sync root
    canvas_updated_at: str  # ISO format from Canvas API
    downloaded_at: str      # ISO format when we grabbed it
    original_size: int
    is_ignored: bool = False
    url: str = ""         # Download URL (for re-downloads)
    target_local_path: str = "" # Pre-calculated destination for new/updated files


@dataclass
class AnalysisResult:
    """Result of analyzing Course Folder vs Canvas course."""
    new_files: list[CanvasFileInfo] = field(default_factory=list)
    updated_clean_files: list[tuple[CanvasFileInfo, SyncFileInfo]] = field(default_factory=list)
    updated_modified_files: list[tuple[CanvasFileInfo, SyncFileInfo]] = field(default_factory=list)
    ignored_files: list[SyncFileInfo] = field(default_factory=list)
    uptodate_files: list[tuple[CanvasFileInfo, SyncFileInfo]] = field(default_factory=list)
    deleted_on_canvas: list[SyncFileInfo] = field(default_factory=list)
    locally_deleted_files: list[SyncFileInfo] = field(default_factory=list)
    untracked_shortcuts: int = 0
    structural_errors: int = 0

    @property
    def updated_files(self) -> list[tuple[CanvasFileInfo, SyncFileInfo]]:
        """Union of clean + modified updates. Read-only convenience view for
        aggregation (counts, file lists, retry queues). Mutating callers must
        target ``updated_clean_files`` or ``updated_modified_files`` directly."""
        return self.updated_clean_files + self.updated_modified_files


# --- Constants ---

MANIFEST_FILENAME = ".canvas_sync_manifest.json"
DB_FILENAME = ".canvas_sync.db"
SYNC_PAIRS_FILENAME = "canvas_sync_pairs.json"
SYNC_HISTORY_FILENAME = "canvas_sync_history.json"
SAVED_GROUPS_FILENAME = "saved_sync_groups.json"

# App-generated bookkeeping files that live inside course folders but are NOT
# Canvas content. Excluded from manifest healing and untracked counting so they
# are never fuzzy-matched onto a missing Canvas file or counted as study material.
_APP_GENERATED_FILES = {
    'debug_log.txt',
    'download_errors.txt',
    '☁️ Canvas Updates & Deletions.txt',
}

# Upper bound on the file size we will hash during *interactive analysis* for
# first-link content discovery / baseline capture. Above this we fall back to
# size+extension heuristics and an empty md5 baseline (which safely biases the
# next edit-classification toward preservation). Genuine updates are still
# hashed in full by _classify_local_modification regardless of size.
_CONTENT_MATCH_MAX_BYTES = 1024 * 1024 * 1024  # 1 GB

# --- Negative ID Offset Registry for Synthetic Content ---
# Real Canvas Files have positive IDs.  Synthetic entities (Pages saved as
# .html, Assignments serialised to HTML, etc.) are tracked with *negative*
# IDs to avoid collisions.  Each content category lives in its own 10 M
# range so they can never overlap.
SECONDARY_ID_OFFSETS = {
    'module_item':   0,           # -1 to -9,999,999  (existing Pages/URLs)
    'assignment':    10_000_000,  # -10,000,001 to -19,999,999
    'syllabus':      20_000_000,  # -20,000,001 to -29,999,999
    'announcement':  30_000_000,  # -30,000,001 to -39,999,999
    'discussion':    40_000_000,  # -40,000,001 to -49,999,999
    'quiz':          50_000_000,  # -50,000,001 to -59,999,999
    'rubric':        60_000_000,  # -60,000,001 to -69,999,999
    'calendar':      70_000_000,  # -70,000,001 to -79,999,999
    'submission':    80_000_000,  # -80,000,001 to -89,999,999
    'attachment':    90_000_000,  # -90,000,001 to -99,999,999
}


# --- Archive Extension Bypass Helpers ---
# Used by the Sync Engine to silently ignore missing archives when
# convert_zip is enabled (mirrors the URL Compiler bypass pattern).
_ARCHIVE_EXTS = {'.zip', '.tar', '.gz'}

def _is_partial_artifact(filename: str) -> bool:
    """True for in-flight/crashed atomic-write artifacts (``x.ext.part`` from
    the file engines, ``x.part.ext`` from the Panopto ffmpeg downloader).
    These must never be healed onto a missing entry, auto-discovered, counted
    as untracked study material, or picked up by post-processing."""
    low = filename.lower()
    return low.endswith('.part') or '.part.' in low


def _is_archive_path(path_str: str) -> bool:
    """Check if a path string represents an archive file, including compound .tar.gz."""
    lower = path_str.lower()
    if lower.endswith('.tar.gz'):
        return True
    return Path(lower).suffix in _ARCHIVE_EXTS


def make_long_path(p: str | Path) -> str:
    """Prepend Windows long path prefix to absolute paths to prevent WinError 206."""
    s = str(p)
    if os.name == 'nt' and Path(p).is_absolute() and not s.startswith('\\\\?\\'):
        return '\\\\?\\' + s
    return s


def make_secondary_id(entity_type: str, raw_id: int) -> int:
    """Generate a unique negative canvas_file_id for a synthetic entity.

    >>> make_secondary_id('assignment', 42)
    -10000042
    """
    offset = SECONDARY_ID_OFFSETS.get(entity_type, 0)
    return -(abs(raw_id) + offset)


def is_secondary_id(canvas_file_id: int) -> bool:
    """Return True if *canvas_file_id* belongs to any synthetic content type."""
    return canvas_file_id < 0


def secondary_id_type(canvas_file_id: int) -> str:
    """Return the entity type string for a given negative synthetic ID.

    Returns 'module_item' for legacy synthetics or 'unknown' if the ID is
    positive / does not fall into any known range.

    The comparison is ``>=``, not ``>``: ``make_secondary_id(t, 0)`` yields
    exactly ``-offset``, and with a strict ``>`` that landed one range too LOW -
    e.g. ``make_secondary_id('submission', 0)`` == -80,000,000 was reported as
    'calendar'. That is not cosmetic: `sync/execution.py` and `sync_manager`
    gate real routing on ``secondary_id_type(...) == 'attachment'``, so a
    misclassified id changes how a file is synced. Only the exact boundary
    behaves differently, and only from wrong to right.
    """
    if canvas_file_id >= 0:
        return 'unknown'
    abs_id = abs(canvas_file_id)
    # Walk offsets in descending order so the first match wins.
    for etype, offset in sorted(SECONDARY_ID_OFFSETS.items(),
                                key=lambda x: x[1], reverse=True):
        if abs_id >= offset:
            return etype
    return 'module_item'


# Sentinel returned by peek_bound_course_id when a DB exists but could not be
# read (corruption / persistent lock). A dedicated constant (instead of a bare
# magic string) keeps the tri-state contract explicit at every call site:
#   int  -> bound course id     None -> no DB yet     DB_UNREADABLE -> warn user
DB_UNREADABLE = 'unreadable'


class SyncManager:
    """Manages synchronization between Canvas and local files using a SQLite database."""

    @staticmethod
    def peek_bound_course_id(local_path: str) -> "int | None | str":
        """Read the course_id this folder's manifest is bound to, without
        instantiating SyncManager (which would write the metadata row).

        Returns the bound Canvas course_id as an int, None if no DB exists
        yet / the binding row is missing, or the module-level ``DB_UNREADABLE``
        sentinel when a DB exists but could not be read.

        Used by the analysis pipeline to detect course/folder mismatches
        before any sync work runs against the wrong manifest.
        """
        try:
            db_path = Path(local_path) / DB_FILENAME
            if not db_path.exists():
                return None
            
            row = None
            for attempt in range(3):
                try:
                    with closing(sqlite3.connect(make_long_path(db_path), timeout=10.0)) as conn, conn:
                        cursor = conn.execute(
                            'SELECT value FROM sync_metadata WHERE key = ?', ('course_id',)
                        )
                        row = cursor.fetchone()
                    break
                except sqlite3.OperationalError as e:
                    if 'locked' in str(e).lower() and attempt < 2:
                        time.sleep(0.5)
                        continue
                    raise
            
            if not row or row[0] is None:
                return None
            return int(row[0])
        except (sqlite3.Error, ValueError, TypeError):
            # M-6: Return a sentinel so callers can distinguish "no DB yet"
            # (None → accept the pair) from "DB exists but is unreadable"
            # (sentinel → warn and block the sync until the user acts).
            return DB_UNREADABLE

    @staticmethod
    def peek_bound_course_name(local_path: str) -> str | None:
        """Read the course_name last written to this folder's manifest.

        Used alongside peek_bound_course_id to give the user a friendly
        identifier for the previously-bound course in the mismatch dialog.
        """
        try:
            db_path = Path(local_path) / DB_FILENAME
            if not db_path.exists():
                return None
            
            row = None
            for attempt in range(3):
                try:
                    with closing(sqlite3.connect(make_long_path(db_path), timeout=10.0)) as conn, conn:
                        cursor = conn.execute(
                            'SELECT value FROM sync_metadata WHERE key = ?', ('course_name',)
                        )
                        row = cursor.fetchone()
                    break
                except sqlite3.OperationalError as e:
                    if 'locked' in str(e).lower() and attempt < 2:
                        time.sleep(0.5)
                        continue
                    raise
            
            return row[0] if row and row[0] else None
        except sqlite3.Error:
            return None

    @staticmethod
    def reset_folder_binding(local_path: str) -> bool:
        """Clear the course binding and all sync records from the manifest DB,
        so the folder can be re-synced against a different Canvas course.

        Uses SQL DELETE rather than file deletion to avoid Windows file-lock
        errors (WinError 32) caused by SQLite WAL mode keeping the .db file
        open between Streamlit reruns.

        Returns True on success or if no DB exists yet, False on SQL error.
        """
        try:
            db_path = Path(local_path) / DB_FILENAME
            if not db_path.exists():
                return True
            
            for attempt in range(3):
                try:
                    with closing(sqlite3.connect(make_long_path(db_path), timeout=30.0)) as conn, conn:
                        conn.execute('DELETE FROM sync_manifest')
                        conn.execute('DELETE FROM sync_metadata')
                        # Panopto records are course-specific too: keeping them
                        # after a re-bind would leak the OLD course's recording
                        # manifest + ignore list into the new course's syncs.
                        # Each in its own try: the tables may not exist in DBs
                        # created before the Panopto feature.
                        for _pan_table in ('panopto_manifest', 'panopto_ignored'):
                            try:
                                conn.execute(f'DELETE FROM {_pan_table}')
                            except sqlite3.OperationalError:
                                pass  # table absent (pre-Panopto DB)
                        conn.commit()
                    break
                except sqlite3.OperationalError as e:
                    if 'locked' in str(e).lower() and attempt < 2:
                        time.sleep(0.5)
                        continue
                    raise
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to reset folder binding at {local_path}: {e}")
            return False

    @staticmethod
    def peek_last_synced(local_path: str | Path) -> str | None:
        """Peek at the last_synced timestamp bound to this folder."""
        db_path = Path(local_path) / ".canvas_sync.db"
        if not db_path.exists():
            return None
        try:
            for attempt in range(3):
                try:
                    with closing(sqlite3.connect(make_long_path(db_path), timeout=5.0)) as conn, conn:
                        cursor = conn.execute("SELECT value FROM sync_metadata WHERE key = 'last_synced'")
                        row = cursor.fetchone()
                        return row[0] if row else None
                except sqlite3.OperationalError as e:
                    if 'locked' in str(e).lower() and attempt < 2:
                        time.sleep(0.5)
                        continue
                    raise
            return None
        except Exception:
            return None

    def __init__(self, local_path: str | Path, course_id: int, course_name: str = ""):
        """
        Initialize SyncManager.
        
        Args:
            local_path: Path to the local sync folder (course folder)
            course_id: Canvas course ID
            course_name: Canvas course name (for display)
        """
        self.local_path = Path(local_path)
        self.course_id = course_id
        self.course_name = course_name
        self.db_path = self.local_path / DB_FILENAME
        self._db_lock = threading.Lock()
        self.db_was_reset = False    # set True when corruption forces a fresh DB
        self._db_init_failed = False # set True when DB init exhausts all retries
        self._init_db()
        
    def _init_db(self, attempt=0):
        """Initialize SQLite database for tracking synced files."""
        with self._db_lock:
            self._init_db_locked(attempt)

    def _init_db_locked(self, attempt=0):
        """Internal _init_db body - must only be called while holding self._db_lock."""
        self.local_path.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            self._windows_unhide_file(self.db_path)
        
        try:
            with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                cursor = conn.cursor()
                
                # Enable WAL mode for better concurrency and synchronous=NORMAL for speed/safety
                cursor.execute('PRAGMA journal_mode=WAL;')
                cursor.execute('PRAGMA synchronous=NORMAL;')
                
                # Quick integrity check to catch corruption early
                result = cursor.execute('PRAGMA quick_check;').fetchone()
                if result and result[0] != 'ok':
                    raise sqlite3.DatabaseError(f"Integrity check failed: {result[0]}")
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sync_manifest (
                        canvas_file_id INTEGER PRIMARY KEY,
                        canvas_filename TEXT,
                        local_path TEXT,
                        canvas_updated_at TEXT,
                        downloaded_at TEXT,
                        original_size INTEGER,
                        is_ignored INTEGER DEFAULT 0,
                        original_md5 TEXT DEFAULT "",
                        content_sig TEXT DEFAULT ""
                    )
                ''')
                # Handle migration for existing DBs to add original_md5
                try:
                    cursor.execute('ALTER TABLE sync_manifest ADD COLUMN original_md5 TEXT DEFAULT ""')
                except sqlite3.OperationalError:
                    pass  # Column already exists
                # Migration: content signature for secondary-entity update
                # detection (see CanvasFileInfo.content_sig). Empty on legacy
                # rows - the analyzer treats an empty sig as "unknown" and
                # never flags an update from it, so old folders stay stable
                # until the first regenerate stamps a real signature.
                try:
                    cursor.execute('ALTER TABLE sync_manifest ADD COLUMN content_sig TEXT DEFAULT ""')
                except sqlite3.OperationalError:
                    pass  # Column already exists
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sync_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                ''')

                # Panopto recordings are tracked in a DEDICATED table, kept
                # separate from sync_manifest on purpose: Panopto videos have no
                # Canvas file id and never appear in Canvas file metadata, so
                # putting them in sync_manifest would make the Canvas-vs-local
                # analyzer flag them as "deleted on Canvas". This table records
                # what we've downloaded (for the Panopto pass + a future diff
                # view) without touching the file-sync analyzer at all.
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS panopto_manifest (
                        video_id TEXT,
                        kind TEXT,
                        local_path TEXT,
                        title TEXT,
                        downloaded_at TEXT,
                        PRIMARY KEY (video_id, kind)
                    )
                ''')

                # Recordings the user chose to permanently skip. Keyed by the
                # Panopto video GUID (a recording is ONE entity regardless of how
                # many outputs - mp4/mp3/txt/srt - it would produce), mirroring the
                # per-file ignore concept for Canvas files.
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS panopto_ignored (
                        video_id TEXT PRIMARY KEY,
                        title TEXT,
                        ignored_at TEXT
                    )
                ''')
                
                # Course-identity binding: only set course_id once. The
                # manifest's canvas_file_ids are course-specific, so the
                # folder is permanently bound to the first course it was
                # synced against. Use peek_bound_course_id() before
                # instantiating with a different course_id to detect
                # mismatch and prompt the user (handled in sync.analysis).
                cursor.execute('INSERT OR IGNORE INTO sync_metadata (key, value) VALUES (?, ?)', ('course_id', str(self.course_id)))
                # Course name can change on Canvas - always refresh.
                cursor.execute('INSERT OR REPLACE INTO sync_metadata (key, value) VALUES (?, ?)', ('course_name', self.course_name))
                conn.commit()
        except sqlite3.DatabaseError as e:
            # Database is corrupted - rescue by renaming and re-initializing
            logger.error(f"Database corrupted at {self.db_path}: {e}. Resetting to fresh database.")
            self.db_was_reset = True  # callers can surface a warning to the user
            if attempt >= 3:
                logger.error(f"Max retries reached trying to fix DB at {self.db_path}. Aborting.")
                self._db_init_failed = True
                return
            try:
                corrupted_path = self.db_path.with_name('.canvas_sync_corrupted.db')
                if corrupted_path.exists():
                    try:
                        corrupted_path.unlink()
                    except OSError as unlink_err:
                        logger.warning(f"Could not unlink previous corrupted DB: {unlink_err}")
                try:
                    self.db_path.rename(corrupted_path)
                    logger.info(f"Corrupted database backed up to {corrupted_path}")
                except OSError as rename_err:
                    logger.warning(f"Could not rename corrupted DB: {rename_err}. Deleting instead.")
                    try:
                        self.db_path.unlink(missing_ok=True)
                    except OSError as unlink_err2:
                        logger.error(f"Could not delete corrupted DB: {unlink_err2}")
            except Exception as outer_err:
                logger.error(f"Unexpected error during DB recovery: {outer_err}")
            
            # Re-init with a clean slate (already holding lock, so call locked variant directly)
            self._init_db_locked(attempt=attempt + 1)
            return

        if os.name == 'nt':
            self._windows_hide_file(self.db_path)
            # WAL mode creates sibling journal files next to the DB; hide them
            # too so users never see mystery ".canvas_sync.db-wal" files in
            # their course folder while the app is running.
            for _suffix in ('-wal', '-shm'):
                self._windows_hide_file(self.db_path.with_name(self.db_path.name + _suffix))
    
    # --- Manifest Operations ---
    
    def load_manifest(self) -> dict:
        """
        Load the sync manifest from SQLite DB into an memory dictionary.
        """
        if self._db_init_failed:
            logger.error(f"Cannot load manifest: DB initialization failed for {self.db_path}")
            raise RuntimeError(
                f"Sync database could not be initialized for '{self.course_name}'. "
                "Cannot load manifest - the sync database may be locked by another process."
            )

        manifest = {
            'course_id': self.course_id,
            'course_name': self.course_name,
            'files': {}
        }
        
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT canvas_file_id, canvas_filename, local_path, canvas_updated_at, downloaded_at, original_size, is_ignored, original_md5, content_sig FROM sync_manifest')
                    for row in cursor.fetchall():
                        file_id_str = str(row[0])
                        manifest['files'][file_id_str] = {
                            'canvas_file_id': row[0],
                            'canvas_filename': row[1],
                            'local_path': row[2],
                            'canvas_updated_at': row[3],
                            'downloaded_at': row[4],
                            'original_size': row[5],
                            'is_ignored': bool(row[6]),
                            'original_md5': row[7] if row[7] is not None else "",
                            'content_sig': row[8] if row[8] is not None else ""
                        }
                break  # Success
            except sqlite3.OperationalError as e:
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    logger.warning(f"Database locked, retrying load_manifest... ({attempt + 1}/{max_retries})")
                    time.sleep(0.5)
                else:
                    logger.error(f"Database error loading manifest. Aborting to prevent data loss: {e}")
                    raise
            except sqlite3.Error as e:
                logger.error(f"Database error loading manifest. Aborting to prevent data loss: {e}")
                raise  # UI should catch this
            
        # Migrate metadata as well if needed in the future
        return manifest
            
    def save_manifest(self, manifest: dict, update_last_synced: bool = True) -> bool:
        """Save the in-memory manifest dictionary to the SQLite DB using atomic upserts.

        Uses INSERT OR REPLACE per row instead of DELETE + reinsert.
        This ensures that a crash at any point leaves all previously-committed
        rows intact - no data loss scenario.

        Args:
            update_last_synced: When True (download path), stamp the ``last_synced``
                metadata. When False, persist only the manifest rows - used by the
                analysis phase to durably record auto-discovered/healed entries for
                an up-to-date folder WITHOUT pretending a sync just happened.
        """
        if self._db_init_failed:
            logger.error(f"Cannot save manifest: DB initialization failed for {self.db_path}")
            return False

        max_retries = 3

        for attempt in range(max_retries):
            try:

                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    cursor = conn.cursor()
                    # Use plain local-time string so format_relative_date() can parse it
                    # without special-casing UTC ISO format (C-5 fix).
                    now_plain = datetime.now().strftime('%Y-%m-%d %H:%M')
                    if update_last_synced:
                        cursor.execute('INSERT OR REPLACE INTO sync_metadata (key, value) VALUES (?, ?)', ('last_synced', now_plain))
                    
                    # Atomic upsert: INSERT ON CONFLICT per row (preserves is_ignored)
                    for file_id_str, info in manifest.get('files', {}).items():
                        cursor.execute('''
                            INSERT INTO sync_manifest
                            (canvas_file_id, canvas_filename, local_path, canvas_updated_at, downloaded_at, original_size, is_ignored, original_md5, content_sig)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(canvas_file_id) DO UPDATE SET
                                canvas_filename = excluded.canvas_filename,
                                local_path = excluded.local_path,
                                canvas_updated_at = excluded.canvas_updated_at,
                                downloaded_at = excluded.downloaded_at,
                                original_size = excluded.original_size,
                                original_md5 = excluded.original_md5,
                                content_sig = CASE
                                    WHEN excluded.content_sig != '' THEN excluded.content_sig
                                    ELSE content_sig
                                END
                        ''', (
                            info.get('canvas_file_id', int(file_id_str)),
                            info.get('canvas_filename', ''),
                            info.get('local_path', ''),
                            info.get('canvas_updated_at', ''),
                            info.get('downloaded_at', now_plain),
                            info.get('original_size', 0),
                            1 if info.get('is_ignored') else 0,
                            info.get('original_md5', ''),
                            info.get('content_sig', '')
                        ))
                    conn.commit()
                    
                return True
            except sqlite3.OperationalError as e:
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    logger.warning(f"Database locked, retrying save_manifest... ({attempt + 1}/{max_retries})")
                    time.sleep(0.5)
                else:
                    logger.warning(f"Error saving manifest to DB: {e}")
                    return False
            except sqlite3.Error as e:
                logger.warning(f"Error saving manifest to DB: {e}")
                return False
        return False
            
    def _create_empty_manifest(self) -> dict:
        """Create a new empty memory manifest structure."""
        return {
            'course_id': self.course_id,
            'course_name': self.course_name,
            'files': {}
        }
    
    # --- Windows Hidden File Helpers ---
    
    @staticmethod
    def _windows_unhide_file(filepath: Path):
        """Remove hidden attribute from a file on Windows."""
        if os.name != 'nt':
            return
        if not filepath.exists():
            return
        try:
            import ctypes
            FILE_ATTRIBUTE_NORMAL = 0x80
            ctypes.windll.kernel32.SetFileAttributesW(
                make_long_path(filepath), FILE_ATTRIBUTE_NORMAL
            )
        except Exception as e:
            logger.debug(f"_windows_unhide_file failed for '{filepath}': {e}")

    @staticmethod
    def _windows_hide_file(filepath: Path):
        """Set hidden attribute on a file on Windows."""
        if os.name != 'nt':
            return
        if not filepath.exists():
            return
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            ctypes.windll.kernel32.SetFileAttributesW(
                make_long_path(filepath), FILE_ATTRIBUTE_HIDDEN
            )
        except Exception as e:
            logger.debug(f"_windows_hide_file failed for '{filepath}': {e}")
    
    # --- Heal Process ---
    
    def heal_manifest(self, manifest: dict, progress_callback: Optional[Callable] = None) -> dict:
        """
        Find moved/renamed/edited files by scanning the Course Folder.
        Uses a 3-tier heuristic:
        1. Exact filename match
        2. Exact MD5 hash match (for renamed files)
        3. Levenshtein distance on filename > 0.85
        """
        files_section = manifest.get('files', {})

        # 1. Identify missing files
        missing_entries = {}
        for file_id, file_info in files_section.items():
            if file_info.get('is_ignored', False):
                continue
            
            local_path = self.local_path / file_info.get('local_path', '')
            if not local_path.exists():
                missing_entries[file_id] = file_info
        
        if not missing_entries:
            return manifest
            
        if progress_callback:
            progress_callback('Looking for moved/renamed files...')
            
        # 2. Gather ALL existing orphaned local files (files not currently tracked)
        # We need to build a pool of candidates to test our missing entries against.
        tracked_local_paths = {
            os.path.normpath(str(self.local_path / info.get('local_path', '')))
            for cid, info in files_section.items()
            if not info.get('is_ignored') and cid not in missing_entries
        }
        
        orphaned_files = []
        for root, _, files in os.walk(self.local_path):
            for filename in files:
                if (filename in (MANIFEST_FILENAME, DB_FILENAME, SYNC_PAIRS_FILENAME, SYNC_HISTORY_FILENAME)
                        or filename in _APP_GENERATED_FILES
                        or filename.startswith('.canvas_sync')
                        or _is_partial_artifact(filename)):
                    continue
                filepath = Path(root) / filename
                norm_str = os.path.normpath(str(filepath))
                if norm_str not in tracked_local_paths:
                    try:
                        sz = filepath.stat().st_size
                        orphaned_files.append({
                            'path': filepath,
                            'name': filename,
                            'norm_name': _match_key(filename),
                            'size': sz,
                            'md5': None # Lazy compute
                        })
                    except OSError:
                        pass

        if not orphaned_files:
            return manifest
            
        # 3. Resolve matches (Heuristic Engine)
        for file_id, missing_info in missing_entries.items():
            # The LAST on-disk name is the basename of local_path (it reflects
            # display-name preference, conflict suffixes like " (1)", and any
            # post-processing rename such as .pptx→.pdf). It is what a moved
            # file is actually called, so it drives the name tiers; the raw
            # canvas_filename is only a fallback for legacy rows.
            orig_name = (Path(missing_info.get('local_path', '')).name
                         or missing_info.get('canvas_filename', ''))
            orig_norm_name = _match_key(orig_name)
            orig_size = missing_info.get('original_size', -1)
            orig_md5 = missing_info.get('original_md5', '')

            best_match_idx = -1
            matched_tier = 0

            # TIER 1: Exact Normalized Filename Match (Handles user editing a file but keeping name)
            for idx, orphan in enumerate(orphaned_files):
                if orphan['norm_name'] == orig_norm_name:
                    best_match_idx = idx
                    matched_tier = 1
                    break

            # TIER 2: Exact MD5 Match (Handles user renaming a file but NOT editing it)
            if best_match_idx == -1 and orig_md5 and orig_size > 0:
                for idx, orphan in enumerate(orphaned_files):
                    if orphan['size'] == orig_size:
                        if not orphan['md5']:
                            orphan['md5'] = self.compute_local_md5(orphan['path'])
                        if orphan['md5'] == orig_md5:
                            best_match_idx = idx
                            matched_tier = 2
                            break

            # TIER 3: Fuzzy filename match - multiple independent guards make this
            # last-resort heuristic safe against binding the wrong file:
            #   • Extension must match (a renamed PDF is still a PDF).
            #   • Stem containment: one normalized stem must contain the other, so
            #     a rename that ADDS/removes a segment ("Intro"→"Intro_v2") matches
            #     but a single-character SUBSTITUTION ("Lecture1"→"Lecture2") does
            #     NOT - substitutions are the classic mis-heal trap.
            #   • Similarity must be >= 0.90.
            #   • Ambiguity reject: if a second candidate is nearly as similar,
            #     refuse rather than guess.
            # Anything rejected here is simply left unhealed (surfaces as
            # locally-deleted), which is always safe.
            if best_match_idx == -1:
                _orig_ext = Path(orig_name).suffix.lower()
                _orig_stem = _match_key(Path(orig_name).stem)
                scored = []
                for idx, orphan in enumerate(orphaned_files):
                    if Path(orphan['name']).suffix.lower() != _orig_ext:
                        continue
                    _orph_stem = _match_key(Path(orphan['name']).stem)
                    if not _orig_stem or not _orph_stem:
                        continue
                    _short, _long = sorted((_orig_stem, _orph_stem), key=len)
                    if _short not in _long:
                        continue  # not a contained rename → skip
                    ratio = difflib.SequenceMatcher(None, orphan['norm_name'], orig_norm_name).ratio()
                    scored.append((ratio, idx))
                scored.sort(key=lambda t: t[0], reverse=True)
                if scored and scored[0][0] >= 0.90 and (
                    len(scored) == 1 or (scored[0][0] - scored[1][0]) > 0.05
                ):
                    best_match_idx = scored[0][1]
                    matched_tier = 3

            # If we found a match via any tier, heal it
            if best_match_idx != -1:
                matched_orphan = orphaned_files.pop(best_match_idx)
                try:
                    relative_path = matched_orphan['path'].relative_to(self.local_path)
                    files_section[file_id]['local_path'] = str(relative_path).replace('\\', '/')
                    # Only refresh size/md5 for Tier 2 (content-identical rename).
                    # Tier 1/3 may represent user-edited files; preserving the original
                    # baseline lets the next sync correctly detect local modifications.
                    if matched_tier == 2:
                        files_section[file_id]['original_size'] = matched_orphan['size']
                        files_section[file_id]['original_md5'] = matched_orphan['md5']
                except ValueError as e:
                    # relative_to() raises when the matched file is not under this
                    # folder (junction/symlink, or a path from a different drive).
                    # The heal is abandoned, so the rename stays undetected and the
                    # file will be re-downloaded - worth a trace, not silence.
                    logger.warning(
                        "Rename heal abandoned for canvas_file_id=%s: '%s' is not "
                        "inside the synced folder '%s' (%s)",
                        file_id, matched_orphan.get('path'), self.local_path, e)
        
        manifest['files'] = files_section
        return manifest
    
    # --- Analysis ---
    
    def analyze_course(self, canvas_files: list[CanvasFileInfo], manifest: dict, 
                       cm=None, download_mode: str = 'modules',
                       secondary_fetch_success: dict | None = None,
                       module_map: dict | None = None) -> AnalysisResult:
        """
        Compare Canvas files with local manifest to categorize files.
        Pre-calculates target paths and performs backend deduplication (matching new files to missing ones).

        Args:
            module_map: Optional pre-built mapping of content_id → sanitized module
                folder name, produced by _get_files_from_modules during the metadata
                scan.  When provided, the redundant Canvas API fetch for module
                structure is skipped entirely.
        """
        result = AnalysisResult()
        files_section = manifest.get('files', {})
        
        # Fetch sync contract for URL Compilation bypass
        contract = self._load_metadata('sync_contract')
        try:
            contract_dict = json.loads(contract) if contract else {}
        except Exception:
            contract_dict = {}
        convert_urls_enabled = contract_dict.get('convert_urls', False)
        convert_zip_enabled = contract_dict.get('convert_zip', False)
        
        # 0. Pre-calculate Target Paths
        #    Prefer the pre-built module_map from the metadata scan (Fix 1 -
        #    eliminates ~30 redundant HTTP calls per course).  Fall back to a
        #    live API fetch only when no map was provided by the caller.
        target_paths = {}
        if module_map and download_mode == 'modules':
            target_paths = dict(module_map)
        elif cm and download_mode == 'modules':
            try:
                course = cm.canvas.get_course(self.course_id)
                modules = course.get_modules()
                for module in modules:
                    clean_module_name = cm._sanitize_filename(module.name)
                    items = module.get_module_items()
                    for item in items:
                        if item.type == 'File' and hasattr(item, 'content_id') and item.content_id:
                            # M-5: FIRST linking module wins (parity with the
                            # download engine and the pre-built module_map).
                            target_paths.setdefault(item.content_id, clean_module_name)
            except Exception as e:
                logger.warning(f"Failed to fetch module map in analyze_course: {e}")
                result.structural_errors += 1
        
        # Scan local files once for discovery of "existing but untracked" files.
        # Build two indexes over shared candidate dicts so a claim made through
        # one index is visible to the other:
        #   local_by_name : filesystem-aware match key → [candidate, ...]
        #   local_by_size : byte size → [candidate, ...]   (content-match prefilter)
        local_by_name: dict = {}
        local_by_size: dict = {}
        all_local_files = []  # Flat list for accurate untracked counting
        claimed_paths: set = set()  # M-4: a local file backs at most one canvas id

        for root, _, files in os.walk(self.local_path):
            for filename in files:
                if (filename in (MANIFEST_FILENAME, DB_FILENAME, SYNC_PAIRS_FILENAME, SYNC_HISTORY_FILENAME)
                        or filename in _APP_GENERATED_FILES
                        or filename.startswith('.')
                        or _is_partial_artifact(filename)):
                    continue
                filepath = Path(root) / filename
                try:
                    size = filepath.stat().st_size
                except OSError:
                    continue
                candidate = {'path': filepath, 'size': size, 'md5': None}
                local_by_name.setdefault(_match_key(filename), []).append(candidate)
                local_by_size.setdefault(size, []).append(candidate)
                all_local_files.append(filepath)

        def _candidate_md5(cand: dict) -> str:
            """Lazily compute (and cache) a local candidate's md5."""
            if cand['md5'] is None:
                cand['md5'] = SyncManager.compute_local_md5(cand['path']) or ''
            return cand['md5']

        def _discovery_md5(cand: dict) -> str:
            """Baseline md5 to store for an auto-discovered file. Skips hashing
            very large files during interactive analysis; an empty baseline
            safely biases the next edit-classification toward preservation."""
            if cand['size'] > _CONTENT_MATCH_MAX_BYTES:
                return ''
            return _candidate_md5(cand)

        def _claim_key(p) -> str:
            """Canonical key for the claimed-paths set (case/sep-insensitive on
            Windows so a manifest-recorded path always matches its os.walk form)."""
            return os.path.normcase(os.path.normpath(str(p)))

        # M-3 hardening: a local file that already backs a manifest entry must
        # never be auto-discovered as the body of a SECOND canvas id (that
        # would silently "up-to-date" a genuinely new file without downloading
        # it). Seed the claimed set with every tracked path up-front.
        for _entry in files_section.values():
            _lp = _entry.get('local_path', '')
            if _lp:
                claimed_paths.add(_claim_key(self.local_path / Path(_lp)))

        seen_ids = set()

        # Temporary sets/lists for deduplication
        raw_new_files = []
        raw_locally_deleted = []

        # Deduplicate canvas files by canvas_file_id.
        # Path+size dedup was dropping legitimate files that share a name/size
        # across modules (e.g. the same filename uploaded to two modules).
        unique_canvas_files = []
        seen_file_ids: set[str] = set()

        for c_file in canvas_files:
            file_id = str(c_file.id)
            seen_ids.add(file_id)
            # Entities that older manifests key differently (module Pages: see
            # CanvasFileInfo.legacy_sync_id) are "seen on Canvas" under BOTH
            # ids, so a legacy-keyed row is never mistaken for a deletion.
            _legacy = int(getattr(c_file, 'legacy_sync_id', 0) or 0)
            if _legacy:
                seen_ids.add(str(_legacy))

            # Determine target path. ``target_paths`` may key on positive
            # Canvas file IDs *or* synthetic negative IDs (Pages, Assignments,
            # Quizzes, Discussions, ExternalUrls - populated by the modules
            # scan in canvas_logic._get_files_from_modules).  This is what
            # lets Mode A inline secondary content land in the right module
            # subfolder during sync.
            #
            # The path component uses preferred_disk_name (display-name
            # preference for regular files) so the analyzer's expected layout
            # matches what the download engine actually writes to disk.
            subfolder = target_paths.get(c_file.id, "")
            _disk_name = preferred_disk_name(c_file)
            if subfolder:
                calc_path = f"{subfolder}/{_disk_name}"
            else:
                calc_path = _disk_name

            if file_id not in seen_file_ids:
                seen_file_ids.add(file_id)
                unique_canvas_files.append((c_file, calc_path))

        for c_file, calc_path in unique_canvas_files:
            file_id = str(c_file.id)

            # Legacy-id bridge: when the entity isn't tracked under its primary
            # id but IS tracked under its legacy alias (module Pages synced by
            # older versions were keyed by -item.id instead of -page_id), use
            # the legacy row - the entry, its healed local_path, content_sig
            # comparison and any future update all stay on the existing key,
            # so nothing re-downloads or forks a duplicate.
            _legacy = int(getattr(c_file, 'legacy_sync_id', 0) or 0)
            if _legacy and file_id not in files_section \
                    and str(_legacy) in files_section:
                file_id = str(_legacy)

            if file_id not in files_section:
                # Not in manifest - try to recognize a file the student already
                # has on disk so we never re-download a duplicate. Three tiers:
                #   (a) name match (filesystem-aware; size must match for real
                #       files, synthetic entities match on name alone),
                #   (b) content match by md5 when Canvas exposes a hash and the
                #       file was renamed - the key win for student-built folders,
                #   (c) unambiguous size+extension fallback when md5 is absent or
                #       the file is too large to hash interactively.
                #
                # Name tier checks BOTH the display-derived on-disk name and
                # the raw Canvas filename: new downloads write the display
                # name, while folders downloaded by older versions (or built
                # by the student from Canvas's raw names) carry the filename.
                _name_keys = []
                for _nm in (preferred_disk_name(c_file), c_file.filename):
                    _k = _match_key(_nm)
                    if _k and _k not in _name_keys:
                        _name_keys.append(_k)
                matched_cand = None
                _matched_tier = ''

                # (a) Name match
                for _nk in _name_keys:
                    for cand in local_by_name.get(_nk, []):
                        if _claim_key(cand['path']) in claimed_paths:
                            continue
                        # Synthetic secondary entities are stored with size=0 but the
                        # HTML on disk has content - match negatives on name alone.
                        if c_file.id < 0 or cand['size'] == c_file.size:
                            matched_cand = cand
                            _matched_tier = 'name'
                            break
                    if matched_cand is not None:
                        break

                # (b)/(c) Content / size+ext match - real files only (synthetic
                # entities have size 0 and are handled by the name tier above).
                if matched_cand is None and c_file.id >= 0:
                    size_pool = [
                        cand for cand in local_by_size.get(c_file.size, [])
                        if _claim_key(cand['path']) not in claimed_paths
                    ]
                    c_md5 = getattr(c_file, 'md5', None)
                    c_ext = Path(c_file.filename).suffix.lower()
                    if c_md5 and c_file.size <= _CONTENT_MATCH_MAX_BYTES:
                        for cand in size_pool:
                            if _candidate_md5(cand) == c_md5:
                                matched_cand = cand
                                _matched_tier = 'md5'
                                break
                    if matched_cand is None and c_ext:
                        # Exactly one same-size, same-extension orphan is almost
                        # certainly this file under a new name. Uniqueness is
                        # required so we never bind a coincidentally same-sized file.
                        ext_pool = [
                            cand for cand in size_pool
                            if Path(cand['path']).suffix.lower() == c_ext
                        ]
                        if len(ext_pool) == 1:
                            matched_cand = ext_pool[0]
                            _matched_tier = 'size_ext'

                if matched_cand is not None:
                    # Auto-discover the file and count it as up-to-date.
                    try:
                        local_path = matched_cand['path']
                        rel_path = local_path.relative_to(self.local_path)
                        # Baseline md5: tier (c) is the weakest heuristic - if
                        # its binding is ever wrong, a stored hash would later
                        # green-light a clean in-place OVERWRITE of the user's
                        # unrelated file. Store an empty baseline instead so a
                        # future update forks to _NewVersion (preserving the
                        # local copy) - the safe default. Tiers (a)/(b) carry
                        # strong evidence (name+size / content) and keep the
                        # real hash for precise clean-vs-edited routing.
                        entry = {
                            'canvas_file_id': c_file.id,
                            'canvas_filename': c_file.filename,
                            'local_path': str(rel_path).replace('\\', '/'),
                            'canvas_updated_at': c_file.modified_at or datetime.now(timezone.utc).isoformat(),
                            'downloaded_at': datetime.now(timezone.utc).isoformat(),
                            'original_size': c_file.size,
                            'is_ignored': False,
                            'original_md5': ('' if _matched_tier == 'size_ext'
                                             else _discovery_md5(matched_cand)),
                            'content_sig': getattr(c_file, 'content_sig', '') or '',
                        }
                        files_section[file_id] = entry
                        claimed_paths.add(_claim_key(local_path))
                        sync_info = self._dict_to_sync_info(file_id, entry, c_file)
                        sync_info.target_local_path = calc_path
                        result.uptodate_files.append((c_file, sync_info))
                        continue
                    except ValueError as e:
                        # relative_to() raises when the matched candidate sits
                        # outside this folder. Adoption is abandoned and the file
                        # falls through to "new", i.e. it gets re-downloaded even
                        # though a copy exists. Rare, but never silent.
                        logger.warning(
                            "Auto-discovery adoption abandoned for canvas_file_id="
                            "%s ('%s'): candidate '%s' is not inside '%s' (%s). "
                            "The file will be re-downloaded.",
                            file_id, getattr(c_file, 'filename', '?'),
                            matched_cand.get('path'), self.local_path, e)

                # Truly new file (stamp target path for the download router)
                c_file._target_local_path = calc_path
                raw_new_files.append(c_file)
            else:
                entry = files_section[file_id]
                local_path = self.local_path / entry.get('local_path', '')
                sync_info = self._dict_to_sync_info(file_id, entry, c_file)
                sync_info.target_local_path = calc_path

                # Pre-calculate intrinsic state for UI routing (restoring ignored files)
                _origin_category = 'uptodate_files'
                _original_item = (c_file, sync_info)
                _mod_state = 'clean'  # 'clean' vs 'modified' - only meaningful for updates

                if not entry.get('downloaded_at') and not entry.get('canvas_updated_at'):
                    # Orphan manifest entry (stub with no timestamps) - treat as new download.
                    c_file._target_local_path = calc_path
                    _origin_category = 'new_files'
                    _original_item = c_file
                elif not local_path.exists():
                    # Local file is gone: respect the user's deletion regardless
                    # of Canvas's update timestamp. (Was previously split across
                    # a dedicated "Phase 1 Existence Guard" and the post-update
                    # branch below; merged here so the same file_id can never
                    # land in two result buckets simultaneously.)
                    _calc_path_p = Path(calc_path)
                    if convert_urls_enabled and _calc_path_p.suffix.lower() in {'.url', '.webloc'}:
                        # URL Compiler bypass: file was post-processed away on disk.
                        _origin_category = 'uptodate_files'
                        _original_item = (c_file, sync_info)
                    elif convert_zip_enabled and _is_archive_path(calc_path):
                        # Archive Extraction bypass: archive was extracted & deleted.
                        _origin_category = 'uptodate_files'
                        _original_item = (c_file, sync_info)
                    elif entry.get('downloaded_at'):
                        _origin_category = 'locally_deleted_files'
                        _original_item = sync_info
                    else:
                        # Manifest stub with no prior download → semantically a new file.
                        c_file._target_local_path = calc_path
                        _origin_category = 'new_files'
                        _original_item = c_file
                elif self._is_canvas_newer(c_file, entry):
                    # Skip the expensive MD5 classification for ignored files;
                    # mod_state is irrelevant until the user explicitly un-ignores them.
                    if not entry.get('is_ignored', False):
                        _mod_state = self._classify_local_modification(
                            local_path, entry.get('original_md5', '')
                        )
                    _origin_category = (
                        'updated_modified_files' if _mod_state == 'modified'
                        else 'updated_clean_files'
                    )
                    _original_item = (c_file, sync_info)
                # else: uptodate (defaults already set)

                if entry.get('is_ignored', False):
                    sync_info.origin_category = _origin_category
                    sync_info.original_item = _original_item
                    result.ignored_files.append(sync_info)
                    continue

                if _origin_category == 'updated_clean_files':
                    result.updated_clean_files.append((c_file, sync_info))
                elif _origin_category == 'updated_modified_files':
                    result.updated_modified_files.append((c_file, sync_info))
                elif _origin_category == 'uptodate_files':
                    result.uptodate_files.append((c_file, sync_info))
                elif _origin_category == 'locally_deleted_files':
                    raw_locally_deleted.append(sync_info)
                elif _origin_category == 'new_files':
                    raw_new_files.append(c_file)
                        
        # 5. Check deletions (in manifest but not in canvas)
        # Path-ownership map for the case-B phantom prune below: which rows
        # currently claim each on-disk path.
        _path_owner_map: dict = {}
        for _own_fid, _own_entry in files_section.items():
            _own_lp = _own_entry.get('local_path', '') or ''
            if _own_lp:
                _path_owner_map.setdefault(os.path.normcase(_own_lp), set()).add(_own_fid)
        _superseded_candel_ids: list = []

        for file_id, entry in files_section.items():
            if file_id not in seen_ids:
                if not entry.get('is_ignored', False):
                    int_id = int(file_id)
                    sync_info = self._dict_to_sync_info(file_id, entry)
                    
                    # Attach target path (as_posix gives forward slashes on
                    # all platforms - the old .replace('\\\\','/') matched two
                    # literal backslashes and never normalized anything).
                    sync_info.target_local_path = Path(entry.get('local_path', '')).parent.as_posix()
                    if sync_info.target_local_path == '.':
                        sync_info.target_local_path = ''
                        
                    local_path = self.local_path / entry.get('local_path', '')
                    
                    # 1. ALWAYS check local existence unconditionally first!
                    if not local_path.exists():
                        # URL Compiler Bypass (Step 5)
                        if convert_urls_enabled and str(entry.get('local_path', '')).lower().endswith(('.url', '.webloc')):
                            pass # Pure deletion bypass
                        # Archive Extraction Bypass (Step 5)
                        elif convert_zip_enabled and _is_archive_path(str(entry.get('local_path', ''))):
                            pass  # Archive extraction bypass
                        elif entry.get('downloaded_at'):
                            raw_locally_deleted.append(sync_info)
                        # else: orphan manifest row (never downloaded, no longer on
                        # Canvas, no local file) - drop silently, nothing to sync.
                        continue # Successfully caught local deletion, move to next file
                    
                    # 2. If it exists locally, process Canvas API failure guards
                    if int_id <= -(SECONDARY_ID_OFFSETS['assignment']) and secondary_fetch_success:
                        etype = secondary_id_type(int_id)
                        if etype and etype not in ('module_item', 'unknown'):
                            if not secondary_fetch_success.get(etype, True):
                                continue  # Skip - API failed for this type
                                
                    # 3. Guard B: Bypass synthetic entities from Canvas deletion
                    if int_id < 0:
                        continue
                        
                    # 4. Standard file deleted on canvas.
                    #    Phantom-prune (case B of the re-upload cleanup): when
                    #    the file at this row's path is ALSO owned by a
                    #    DIFFERENT row whose id is live on Canvas, this row is
                    #    the superseded half of a teacher delete-and-re-upload
                    #    that was already re-downloaded - listing it as
                    #    "Deleted on Canvas" forever is pure noise (the bytes
                    #    on disk ARE current, under the new id). Prune the row.
                    _lp_norm = os.path.normcase(entry.get('local_path', '') or '')
                    if _lp_norm:
                        _owners = _path_owner_map.get(_lp_norm, set()) - {file_id}
                        if any(_o in seen_ids for _o in _owners):
                            _superseded_candel_ids.append(int_id)
                            continue
                    result.deleted_on_canvas.append(sync_info)

        # Case-B phantom rows detected above: hard-delete them (gone from
        # Canvas + their path is owned by a live replacement row).
        if _superseded_candel_ids:
            logger.info(f"Pruning {len(_superseded_candel_ids)} superseded manifest row(s) "
                        f"(re-upload already re-downloaded): {_superseded_candel_ids}")
            for _pid in _superseded_candel_ids:
                files_section.pop(str(_pid), None)
            self.delete_manifest_rows(_superseded_candel_ids)

        # --- Backend Deduplication (The Teacher Re-upload Scenario) ---
        # When a teacher deletes a Canvas file and re-uploads one with the same
        # name (new ID), naively it looks like Delete+New. Two cases:
        #
        #   - The user still HAS the old file (it went through the entry branch
        #     as uptodate/updated): the new same-named file is genuinely new
        #     and both stay as they are.
        #   - The user DELETED the old file locally AND the old id is gone from
        #     Canvas: this is the true re-upload shape. M-6 policy: the user's
        #     deletion is RESPECTED - the pair routes to "Deleted Locally"
        #     (unchecked by default, skipped by Quick Sync) instead of a
        #     default-checked clean update that would silently resurrect a file
        #     they deliberately removed. The NEW canvas file rides along on the
        #     SyncFileInfo so a user-selected redownload fetches the live
        #     re-uploaded object directly.
        #
        # Secondary content (negative IDs - assignments, quizzes, pages, etc.)
        # is excluded from the name-based dedup because:
        #   (a) The re-upload loop below skips negative IDs.
        #   (b) Two assignments with the same sanitized name are distinct entities
        #       and must both sync.  We add a (1)/(2)/... suffix to the local path
        #       of the later duplicate so they land as separate files on disk.
        regular_new_files = [nf for nf in raw_new_files if nf.id >= 0]
        secondary_new_files = [nf for nf in raw_new_files if nf.id < 0]

        _sec_name_counts: dict = {}
        for nf in secondary_new_files:
            norm = _match_key(nf.filename)
            count = _sec_name_counts.get(norm, 0)
            _sec_name_counts[norm] = count + 1
            if count > 0:
                _tp = Path(getattr(nf, '_target_local_path', nf.filename))
                nf._target_local_path = str(_tp.with_stem(f"{_tp.stem} ({count})"))

        # Key new files by BOTH the raw canvas filename and the display-derived
        # on-disk name, so a re-upload matches regardless of which form the
        # (possibly legacy) manifest row recorded.
        new_name_map = {}
        for nf in regular_new_files:
            for _nm in (nf.filename, preferred_disk_name(nf)):
                _k = _match_key(_nm)
                if _k:
                    new_name_map.setdefault(_k, nf)

        # Check locally deleted files against re-uploads
        final_locally_deleted = []
        dedup_loc_del_ids = set()
        for del_info in raw_locally_deleted:
            raw_id_str = str(del_info.canvas_file_id)
            if raw_id_str in dedup_loc_del_ids:
                continue
            dedup_loc_del_ids.add(raw_id_str)

            # --- CRITICAL PATCH: Type-Safe Shield ---
            try:
                check_id = int(del_info.canvas_file_id)
            except (TypeError, ValueError):
                check_id = 1

            if check_id < 0:
                final_locally_deleted.append(del_info)
                continue
            # ----------------------------------------

            missing_norm = _match_key(del_info.canvas_filename)
            _is_true_reupload = raw_id_str not in seen_ids  # old id gone from Canvas
            if _is_true_reupload and missing_norm in new_name_map:
                matching_new_cfile = new_name_map[missing_norm]
                # Remove ALL keys pointing at this new file (raw + display form)
                for _k in [k for k, v in new_name_map.items() if v is matching_new_cfile]:
                    del new_name_map[_k]
                # Respect the deletion: ride the new file on the SyncFileInfo
                # and adopt its canonical target so a user-selected redownload
                # lands where the new file belongs.
                del_info._reupload_new_file = matching_new_cfile
                _new_target = getattr(matching_new_cfile, '_target_local_path', '')
                if _new_target:
                    del_info.target_local_path = _new_target
                final_locally_deleted.append(del_info)
            else:
                final_locally_deleted.append(del_info)

        # Deduplicate new files that were registered under two name keys
        _new_seen_ids: set = set()
        _unique_new = []
        for nf in new_name_map.values():
            if id(nf) not in _new_seen_ids:
                _new_seen_ids.add(id(nf))
                _unique_new.append(nf)

        # --- Phantom-row pruning (post re-upload cleanup) ---
        # Once a re-upload has been downloaded under its NEW id, the OLD id's
        # manifest row lingers: not on Canvas, no local file - it would
        # resurface as "Deleted Locally" on EVERY future sync even though its
        # replacement is tracked and present on disk. Detect exactly that
        # shape (canvas-gone + locally-gone + a same-named DIFFERENT tracked
        # entry whose file exists) and delete the stale row. Entries whose id
        # is still live on Canvas are genuine local deletions and never pruned.
        _prunable = [d for d in final_locally_deleted
                     if str(d.canvas_file_id) not in seen_ids and d.canvas_file_id > 0]
        _prunable_obj_ids = {id(d) for d in _prunable}
        if _prunable:
            _live_name_keys: dict = {}
            for _fid2, _e2 in files_section.items():
                _lp2 = _e2.get('local_path', '')
                if not _lp2:
                    continue
                try:
                    if not (self.local_path / _lp2).exists():
                        continue
                except OSError:
                    continue
                for _nm2 in (Path(_lp2).name, _e2.get('canvas_filename', '')):
                    _k2 = _match_key(_nm2)
                    if _k2:
                        _live_name_keys.setdefault(_k2, set()).add(str(_fid2))

            _pruned_ids = []
            _kept = []
            for del_info in final_locally_deleted:
                if id(del_info) not in _prunable_obj_ids:
                    _kept.append(del_info)
                    continue
                _did = str(del_info.canvas_file_id)
                _keys = {
                    _match_key(Path(del_info.local_path).name) if del_info.local_path else '',
                    _match_key(del_info.canvas_filename),
                }
                _superseded = any(
                    (_live_name_keys.get(_k3, set()) - {_did})
                    for _k3 in _keys if _k3
                )
                if _superseded:
                    _pruned_ids.append(del_info.canvas_file_id)
                    files_section.pop(_did, None)
                else:
                    _kept.append(del_info)
            final_locally_deleted = _kept
            if _pruned_ids:
                logger.info(f"Pruning {len(_pruned_ids)} superseded manifest row(s) "
                            f"(teacher re-upload cleanup): {_pruned_ids}")
                self.delete_manifest_rows(_pruned_ids)

        # Reconstruct the remaining new files that were not duplicates
        result.new_files = _unique_new + secondary_new_files
        result.locally_deleted_files = final_locally_deleted
        
        # Count ALL untracked local files so they reflect in the "up to date" UI
        # This ensures the student's Course Folder count matches what the app reports
        tracked_local_paths = {
            os.path.normpath(str(self.local_path / entry.get('local_path', '')))
            for entry in files_section.values()
        }
        
        untracked_count = 0
        for filepath in all_local_files:
            if os.path.normpath(str(filepath)) not in tracked_local_paths:
                # We count all untracked files (shortcuts, pages, personal notes, etc.)
                # except the internal sync log
                if not filepath.name.endswith("Canvas Updates & Deletions.txt") and filepath.name != "download_errors.txt":
                    untracked_count += 1
                    
        result.untracked_shortcuts = untracked_count
    
        return result

    def detect_structure(self) -> str:
        """Detect whether this course folder uses 'modules' (subfolders) or 'flat' structure.
        
        Priority:
        1. Check sync_metadata for saved download_mode (set during initial download / Sync Run #0)
        2. Inspect manifest paths for subdirectory separators
        3. Fall back to filesystem scan
        """
        # 1. Check saved metadata first (authoritative if present)
        saved_mode = self._load_metadata('download_mode')
        if saved_mode in ('flat', 'modules', 'files'):
            # 'files' (folder-structure) is treated as 'modules' for sync purposes
            return 'modules' if saved_mode in ('modules', 'files') else 'flat'

        # 2. Inspect manifest paths
        manifest = self.load_manifest()
        files_section = manifest.get('files', {})
        for file_id, entry in files_section.items():
            local_path = entry.get('local_path', '')
            if os.sep in local_path or '/' in local_path:
                parts = Path(local_path).parts
                if len(parts) > 1:
                    return 'modules'
        
        # 3. Filesystem heuristic
        if self.local_path.exists():
            for item in self.local_path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    return 'modules'
        return 'flat'

    def _save_metadata(self, key: str, value: str) -> bool:
        """Save a key-value pair to the sync_metadata table."""
        for attempt in range(3):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    conn.execute(
                        'INSERT OR REPLACE INTO sync_metadata (key, value) VALUES (?, ?)',
                        (key, value)
                    )
                    conn.commit()
                return True
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < 2:
                    time.sleep(0.5)
                    continue
                logger.warning(f"Error saving metadata '{key}': {e}")
                return False
            except sqlite3.Error as e:
                logger.warning(f"Error saving metadata '{key}': {e}")
                return False
        return False

    def _load_metadata(self, key: str) -> str | None:
        """Load a value from the sync_metadata table. Returns None if not found."""
        try:
            with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                cursor = conn.execute(
                    'SELECT value FROM sync_metadata WHERE key = ?', (key,)
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.Error:
            return None

    def get_manifest_baseline(self, canvas_file_id: int) -> tuple[str, str] | None:
        """Return ``(original_md5, local_path)`` for one manifest row, or None.

        Lightweight single-row read used by the DOWNLOAD engine's overwrite
        guard: before replacing an on-disk file whose size no longer matches
        Canvas, the engine checks whether the local bytes still equal the
        original download (safe to overwrite) or were edited by the user
        (must be preserved as a ``_NewVersion`` sibling). Never raises.
        """
        try:
            with closing(sqlite3.connect(make_long_path(self.db_path), timeout=10.0)) as conn, conn:
                row = conn.execute(
                    'SELECT original_md5, local_path FROM sync_manifest WHERE canvas_file_id = ?',
                    (int(canvas_file_id),)
                ).fetchone()
            if row is None:
                return None
            return (row[0] or '', row[1] or '')
        except (sqlite3.Error, ValueError, TypeError):
            return None

    def backfill_baseline_md5(self, manifest: dict,
                              progress_callback: Optional[Callable] = None) -> int:
        """One-time repair for manifests written before MD5-on-download existed.

        Older download runs (and any path that recorded a file without a hash)
        left ``original_md5`` empty. The sync engine keys three behaviours off
        that baseline: never-overwrite-your-edits classification, clean-vs-edited
        update routing, and content-based rename matching. Empty baselines are
        SAFE (the engine biases to "preserve the local copy") but imprecise -
        every genuine update is treated as a local edit and forked to a
        ``_NewVersion`` copy instead of a clean in-place overwrite.

        This walks the manifest and fills the missing baselines from the bytes
        currently on disk. SAFETY GUARD: for real files we only backfill when
        the on-disk size still matches the recorded ``original_size``. A size
        match means the bytes are almost certainly the untouched original
        download, so adopting today's hash as the baseline is correct. If the
        user has edited a file its size has (nearly always) changed, so we skip
        it and leave the conservative empty-md5 behaviour intact - we never want
        to capture an edited file as its own "original" (that would green-light
        overwriting the user's work on the next Canvas update). Synthetic
        HTML/URL entities store ``original_size == 0`` and are regenerated every
        sync, so any current bytes are a valid baseline.

        Mutates the in-memory ``manifest`` dict in place (so the caller's
        analysis sees the fresh baselines) and persists in one transaction.
        Returns the number of entries updated.
        """
        files_section = manifest.get('files', {})
        if not files_section:
            return 0

        pending = []  # (md5, canvas_file_id) for the UPDATE
        for file_id, info in files_section.items():
            if info.get('original_md5'):
                continue
            rel = info.get('local_path', '')
            if not rel:
                continue
            full = self.local_path / rel
            if not full.exists():
                continue
            try:
                actual_size = full.stat().st_size
            except OSError:
                continue
            try:
                recorded_size = int(info.get('original_size', 0) or 0)
            except (TypeError, ValueError):
                recorded_size = 0
            # Real files: require an exact size match (pristine heuristic).
            # Synthetic entities (size 0) are always safe to (re)baseline.
            if recorded_size and actual_size != recorded_size:
                continue
            md5 = self.compute_local_md5(full)
            if not md5:
                continue
            info['original_md5'] = md5  # keep the in-memory manifest in sync
            try:
                pending.append((md5, int(file_id)))
            except (TypeError, ValueError):
                continue

        if not pending:
            return 0

        if progress_callback:
            progress_callback(f'Repairing {len(pending)} MD5 baseline(s)...')

        # UPDATE (not UPSERT) so we touch only original_md5 and never disturb
        # is_ignored / timestamps / other columns.
        for attempt in range(3):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    conn.executemany(
                        'UPDATE sync_manifest SET original_md5 = ? WHERE canvas_file_id = ?',
                        pending,
                    )
                    conn.commit()
                return len(pending)
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < 2:
                    time.sleep(0.5)
                    continue
                logger.warning(f"backfill_baseline_md5 DB write failed: {e}")
                return 0
            except sqlite3.Error as e:
                logger.warning(f"backfill_baseline_md5 DB write failed: {e}")
                return 0
        return 0

    def record_downloaded_file(self, canvas_file_id: int, canvas_filename: str,
                                local_path: str, canvas_updated_at: str,
                                original_size: int, local_md5: str = "",
                                content_sig: str = "",
                                clear_ignored: bool = False) -> bool:
        """Record a single downloaded file directly to the SQLite DB.

        This is the 'Sync Run #0' entry point - called from the Download engine
        immediately after each successful file write. Bypasses the in-memory
        manifest dict entirely to avoid race conditions in async/concurrent code.

        Uses INSERT OR REPLACE so re-downloads of the same file_id are idempotent.
        The is_ignored flag is preserved via a sub-query to avoid overwriting
        user ignore decisions from a prior partial download.

        ``content_sig`` (secondary entities only): signature of the raw Canvas
        source fields - stored so the analyzer can detect real content changes
        without relying on churn-prone timestamps.

        ``clear_ignored=True`` is passed ONLY by fresh-byte download paths (a
        file the user explicitly chose to download again): the stale is_ignored
        flag is cleared so the file doesn't sit in the Ignored bucket while
        being freshly present on disk. Skip-existing re-records keep the
        default (False) and continue to preserve user ignore choices.

        MD5 baseline: the sync engine's modification detection ("never overwrite
        your edits"), clean-vs-edited update routing, and content-based rename
        matching all key off original_md5. Canvas's API does not expose a usable
        file hash, so the fresh-download path hashes bytes inline and passes
        local_md5. Callers that can't (skip-existing files, secondary HTML/URL
        entities) leave it empty - compute it from the on-disk file here so the
        baseline is never silently dropped. compute_local_md5 returns None on a
        locked/unreadable file; coerce to "" so the DB always stores a string.
        """
        if not local_md5:
            full_path = self.local_path / local_path
            if full_path.exists():
                local_md5 = SyncManager.compute_local_md5(full_path) or ""
        info = {
            'canvas_file_id': canvas_file_id,
            'canvas_filename': canvas_filename,
            'local_path': local_path,
            'canvas_updated_at': canvas_updated_at or datetime.now(timezone.utc).isoformat(),
            'downloaded_at': datetime.now(timezone.utc).isoformat(),
            'original_size': original_size,
            'is_ignored': False,
            'original_md5': local_md5,
            'content_sig': content_sig or ''
        }
        return self._save_single_file_to_db(info, clear_ignored=clear_ignored)

    # ── Panopto manifest (dedicated, decoupled from sync_manifest) ──
    def record_panopto_file(self, video_id: str, kind: str, local_path: str,
                            title: str = "") -> bool:
        """Record a downloaded Panopto artifact (mp3/txt/srt) for tracking.

        Idempotent per (video_id, kind) via INSERT OR REPLACE. ``local_path``
        should be relative to this folder when possible (absolute is tolerated).
        Never raises into the caller - returns False on failure.
        """
        try:
            for attempt in range(3):
                try:
                    with closing(sqlite3.connect(make_long_path(self.db_path), timeout=10.0)) as conn, conn:
                        conn.execute(
                            '''INSERT OR REPLACE INTO panopto_manifest
                               (video_id, kind, local_path, title, downloaded_at)
                               VALUES (?, ?, ?, ?, ?)''',
                            (str(video_id), str(kind), str(local_path), str(title),
                             datetime.now(timezone.utc).isoformat()),
                        )
                        conn.commit()
                    return True
                except sqlite3.OperationalError as e:
                    if 'locked' in str(e).lower() and attempt < 2:
                        import time as _t
                        _t.sleep(0.3 * (attempt + 1))
                        continue
                    raise
        except Exception as e:
            logger.debug(f"record_panopto_file failed ({video_id}/{kind}): {e}")
        return False

    def get_panopto_manifest(self) -> dict:
        """Return {video_id: {kind: local_path}} for all tracked Panopto files."""
        out: dict = {}
        try:
            with closing(sqlite3.connect(make_long_path(self.db_path), timeout=10.0)) as conn, conn:
                rows = conn.execute(
                    'SELECT video_id, kind, local_path FROM panopto_manifest'
                ).fetchall()
            for vid, kind, lp in rows:
                out.setdefault(vid, {})[kind] = lp
        except Exception as e:
            logger.debug(f"get_panopto_manifest failed: {e}")
        return out

    def ignore_panopto(self, video_id: str, title: str = "") -> bool:
        """Mark a Panopto recording as permanently ignored (UPSERT).

        Keyed by video GUID - the whole recording is skipped, regardless of how
        many outputs it would produce. Idempotent; never raises into the caller.
        """
        for attempt in range(3):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    conn.execute(
                        '''INSERT INTO panopto_ignored (video_id, title, ignored_at)
                           VALUES (?, ?, ?)
                           ON CONFLICT(video_id) DO UPDATE SET title = excluded.title''',
                        (str(video_id), str(title or ""),
                         datetime.now(timezone.utc).isoformat()),
                    )
                    conn.commit()
                return True
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < 2:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                logger.warning(f"ignore_panopto failed ({video_id}): {e}")
            except sqlite3.Error as e:
                logger.warning(f"ignore_panopto failed ({video_id}): {e}")
                break
        return False

    def restore_panopto(self, video_id: str) -> bool:
        """Remove a recording from the ignored list. Never raises."""
        return self.bulk_restore_panopto([video_id])

    def bulk_restore_panopto(self, video_ids: list) -> bool:
        """Un-ignore multiple recordings in one transaction. Never raises."""
        if not video_ids:
            return True
        rows = [(str(v),) for v in video_ids]
        for attempt in range(3):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    conn.executemany(
                        'DELETE FROM panopto_ignored WHERE video_id = ?', rows)
                    conn.commit()
                return True
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < 2:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                logger.warning(f"bulk_restore_panopto failed: {e}")
            except sqlite3.Error as e:
                logger.warning(f"bulk_restore_panopto failed: {e}")
                break
        return False

    def get_ignored_panopto(self) -> dict:
        """Return {video_id: title} for all ignored Panopto recordings."""
        out: dict = {}
        try:
            with closing(sqlite3.connect(make_long_path(self.db_path), timeout=10.0)) as conn, conn:
                rows = conn.execute(
                    'SELECT video_id, title FROM panopto_ignored'
                ).fetchall()
            for vid, title in rows:
                out[str(vid)] = title or ""
        except Exception as e:
            logger.debug(f"get_ignored_panopto failed: {e}")
        return out

    def _is_canvas_newer(self, canvas_file: CanvasFileInfo, manifest_entry: dict) -> bool:
        """Check if Canvas version is strictly newer than manifest entry.

        Secondary entities (negative IDs, non-attachment) are compared by
        CONTENT SIGNATURE, never by timestamp: Canvas bumps ``updated_at`` on
        events that don't change the body (grade postings, publish toggles,
        course-level churn for the syllabus), and local post-processing
        (HTML→MD) renames the file - both made timestamp diffing produce
        endless phantom updates. The signature is an md5 over the raw
        Canvas-side source fields, computed during analysis and stored at
        save time, so it only moves when the actual content changed. When
        either side lacks a signature (legacy rows, restricted fetches) we
        return False - stability over false positives; the signature is
        stamped on the next regenerate and detection self-heals from there.

        MD5 short-circuit (real files): if both Canvas and the manifest expose
        the same md5 hash, the file content is byte-identical regardless of
        what the timestamp says. Teachers frequently "touch" files (permission
        changes, metadata edits) without altering content, so comparing
        timestamps alone produces phantom updates. Trust the hash when we
        have it on both sides.
        """
        if canvas_file.id < 0:
            # Attachment-range synthetic IDs are REAL Canvas files (Mode B):
            # let them flow through the normal md5/timestamp/size logic below
            # so a teacher replacing an attachment's bytes is detected as an
            # update. All OTHER synthetic entities use the content signature.
            if secondary_id_type(canvas_file.id) != 'attachment':
                fresh_sig = getattr(canvas_file, 'content_sig', '') or ''
                stored_sig = manifest_entry.get('content_sig', '') or ''
                if fresh_sig and stored_sig:
                    return fresh_sig != stored_sig
                return False

        canvas_md5 = getattr(canvas_file, 'md5', None)
        manifest_md5 = manifest_entry.get('original_md5', '')
        if canvas_md5 and manifest_md5 and canvas_md5 == manifest_md5:
            return False

        if not canvas_file.modified_at:
            return False

        manifest_date_str = manifest_entry.get('canvas_updated_at')
        if not manifest_date_str:
            return True

        try:
            canvas_dt = datetime.fromisoformat(canvas_file.modified_at.replace('Z', '+00:00'))
            manifest_dt = datetime.fromisoformat(manifest_date_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return False

        if canvas_dt <= manifest_dt:
            return False

        # Canvas timestamp is newer. When we have NO md5 on either side to confirm
        # a real content change, teachers frequently "touch" a file (re-publish,
        # permission/metadata edits) without altering bytes - producing phantom
        # updates. Use file size as a cheap tie-breaker: if the byte count is
        # unchanged, treat it as a metadata touch (not newer). A genuine content
        # change almost always changes the size. This only applies when md5 is
        # unavailable, so the md5 fast-paths above are never weakened.
        if not (canvas_md5 and manifest_md5):
            try:
                manifest_size = int(manifest_entry.get('original_size', -1))
            except (TypeError, ValueError):
                manifest_size = -1
            canvas_size = getattr(canvas_file, 'size', None)
            if (
                canvas_size is not None
                and manifest_size >= 0
                and int(canvas_size) == manifest_size
            ):
                return False

        return True

    @staticmethod
    def _classify_local_modification(local_path: Path, original_md5: str) -> str:
        """Decide whether a local file is byte-identical to what we downloaded.

        Returns:
            ``'clean'``    - md5 matches the stored original → safe to overwrite.
            ``'modified'`` - md5 differs, missing, or unreadable → preserve via
                             ``_NewVersion`` on update.

        We ALWAYS hash, regardless of file size. A previous 50 MB short-circuit
        returned ``'clean'`` for large files without verifying their content,
        which silently overwrote student edits on big annotated PDFs/scans and
        broke the "never overwrites your edits" guarantee. This method is only
        reached when ``_is_canvas_newer`` already returned True and the file is
        not ignored, so hashing runs solely for genuinely-updated files - the
        I/O cost is bounded and correctness is paramount. If the hash cannot be
        computed (locked/unreadable file) we bias to ``'modified'`` so the local
        copy is always preserved.
        """
        if not local_path.exists():
            return 'clean'
        if not original_md5:
            return 'modified'
        current_md5 = compute_local_md5(local_path)
        if not current_md5:
            return 'modified'
        return 'clean' if current_md5 == original_md5 else 'modified'
    
    def _dict_to_sync_info(self, file_id: str, entry: dict, 
                           canvas_file: Optional[CanvasFileInfo] = None) -> SyncFileInfo:
        """Convert manifest entry dict to SyncFileInfo dataclass."""
        return SyncFileInfo(
            canvas_file_id=int(file_id),
            canvas_filename=entry.get('canvas_filename', ''),
            local_path=entry.get('local_path', ''),
            canvas_updated_at=entry.get('canvas_updated_at', ''),
            downloaded_at=entry.get('downloaded_at', ''),
            original_size=entry.get('original_size', 0),
            is_ignored=entry.get('is_ignored', False),
            url=canvas_file.url if canvas_file else entry.get('url', ''),
        )
    
    # --- Manifest Update Helpers ---
    
    def add_file_to_manifest(self, manifest: dict, canvas_file: CanvasFileInfo,
                             local_path: str, local_md5: str = "") -> dict:
        """Add or update a file entry in the manifest after successful download and save immediately to DB.

        Callers on the fresh-download path hash the bytes inline and pass
        ``local_md5`` (avoids a second full read of the file); when omitted the
        hash is computed from disk here so the baseline is never dropped.

        This is always a fresh-byte download (the sync engine only calls it
        after a successful atomic write), so a stale is_ignored flag is
        cleared - the user explicitly chose to download this file again.
        """
        file_id = str(canvas_file.id)

        # If no MD5 is provided but file exists, compute it.
        # compute_local_md5 returns None on PermissionError - coerce to "" so
        # the DB always gets a string (NULL causes type ambiguity on read-back).
        if not local_md5:
            full_path = self.local_path / local_path
            if full_path.exists():
                local_md5 = SyncManager.compute_local_md5(full_path) or ""

        entry = {
            'canvas_file_id': int(file_id),
            'canvas_filename': canvas_file.filename,
            'local_path': local_path,
            'canvas_updated_at': canvas_file.modified_at or datetime.now(timezone.utc).isoformat(),
            'downloaded_at': datetime.now(timezone.utc).isoformat(),
            'original_size': canvas_file.size,
            'is_ignored': False,
            'original_md5': local_md5,
            'content_sig': getattr(canvas_file, 'content_sig', '') or ''
        }
        manifest['files'][file_id] = entry

        # Per-file DB commit
        self._save_single_file_to_db(entry, clear_ignored=True)

        return manifest
        
    def _save_single_file_to_db(self, info: dict, clear_ignored: bool = False) -> bool:
        """Save a single file entry to the SQLite DB.

        Uses INSERT ... ON CONFLICT to preserve is_ignored flag.
        The UPDATE clause deliberately omits is_ignored so that
        re-downloads and sync-run-0 writes never wipe user choices.

        ``clear_ignored=True`` (fresh-byte downloads only) additionally resets
        is_ignored to 0 on conflict: a file the user explicitly downloaded
        again must not linger in the Ignored bucket. content_sig uses a CASE
        guard so an empty (unknown) signature never clobbers a stored one.
        """
        max_retries = 3

        _ignore_clause = ",\n                            is_ignored = 0" if clear_ignored else ""

        for attempt in range(max_retries):
            try:

                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    cursor = conn.cursor()
                    cursor.execute(f'''
                        INSERT INTO sync_manifest
                        (canvas_file_id, canvas_filename, local_path, canvas_updated_at, downloaded_at, original_size, is_ignored, original_md5, content_sig)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(canvas_file_id) DO UPDATE SET
                            canvas_filename = excluded.canvas_filename,
                            local_path = excluded.local_path,
                            canvas_updated_at = excluded.canvas_updated_at,
                            downloaded_at = excluded.downloaded_at,
                            original_size = excluded.original_size,
                            original_md5 = excluded.original_md5,
                            content_sig = CASE
                                WHEN excluded.content_sig != '' THEN excluded.content_sig
                                ELSE content_sig
                            END{_ignore_clause}
                    ''', (
                        info.get('canvas_file_id'),
                        info.get('canvas_filename', ''),
                        info.get('local_path', ''),
                        info.get('canvas_updated_at', ''),
                        info.get('downloaded_at', ''),
                        info.get('original_size', 0),
                        1 if info.get('is_ignored') else 0,
                        info.get('original_md5', ''),
                        info.get('content_sig', '')
                    ))
                    conn.commit()

                return True
            except sqlite3.OperationalError as e:
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                else:
                    # Never silent: this row is how the folder remembers it has the
                    # file. Losing it is survivable (analyze_course's three-tier
                    # auto-discovery re-adopts an on-disk file), but a systematic
                    # failure - corrupt DB, full disk, read-only folder - would
                    # otherwise leave no trace anywhere.
                    logger.warning(
                        "Manifest write failed for canvas_file_id=%s (%s): %s",
                        info.get('canvas_file_id'), info.get('local_path', ''), e)
                    return False
            except sqlite3.Error as e:
                logger.warning(
                    "Manifest write failed for canvas_file_id=%s (%s): %s",
                    info.get('canvas_file_id'), info.get('local_path', ''), e)
                return False
        return False
    
    def update_converted_file(self, canvas_file_id: int, new_file_path: str) -> bool:
        """
        Update a manifest entry after converting a downloaded file (e.g. PPTX->PDF, HTML->MD).
        
        Only updates local_path, original_size, and original_md5.
        Leaves canvas_filename untouched so the sync engine can still
        match by canvas_file_id against the Canvas API's original filename.
        """
        
        full_new_path = self.local_path / new_file_path
        if not full_new_path.exists():
            logger.warning(f"Converted file not found for DB update: {full_new_path}")
            return False
        
        new_size = full_new_path.stat().st_size
        new_md5 = SyncManager.compute_local_md5(full_new_path) or ""
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    conn.execute(
                        '''UPDATE sync_manifest 
                           SET local_path = ?, original_size = ?, original_md5 = ?
                           WHERE canvas_file_id = ?''',
                        (new_file_path, new_size, new_md5, canvas_file_id)
                    )
                    conn.commit()
                
                # H-7: remember which file this entry's conversion PRODUCED.
                # The ownership rule "a converter may overwrite an existing
                # target only if it is this entry's own previous product" is
                # what protects teacher-provided X.pdf (and the user's own
                # files) from being clobbered by an X.pptx→X.pdf conversion,
                # while still letting the NEXT update of the same source
                # overwrite its own product in place (no ' (1)' churn).
                try:
                    self._record_conversion_product(canvas_file_id, new_file_path)
                except Exception as _prod_err:
                    logger.debug(f"conversion-product record failed: {_prod_err}")

                logger.info(f"Updated manifest entry {canvas_file_id} to new file: {new_file_path}")
                return True
            except sqlite3.OperationalError as e:
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                else:
                    logger.warning(f"Error updating converted file in DB: {e}")
                    return False
            except sqlite3.Error as e:
                logger.warning(f"Error updating converted file in DB: {e}")
                return False
        return False

    _CONVERSION_PRODUCTS_KEY = 'conversion_products'

    def get_conversion_products(self) -> dict:
        """Return {str(canvas_file_id): rel_product_path} for every entry whose
        downloaded file was post-processed into another file (H-7)."""
        try:
            raw = self._load_metadata(self._CONVERSION_PRODUCTS_KEY)
            data = json.loads(raw) if raw else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _record_conversion_product(self, canvas_file_id: int, rel_path: str) -> None:
        """Merge one entry's conversion-product path into the metadata map."""
        products = self.get_conversion_products()
        products[str(canvas_file_id)] = rel_path
        self._save_metadata(self._CONVERSION_PRODUCTS_KEY, json.dumps(products))

    def get_ignored_files(self) -> list[SyncFileInfo]:
        """Return a list of all files currently marked as ignored in the DB."""
        ignored = []
        try:
            manifest = self.load_manifest()
            for fid, info in manifest.get('files', {}).items():
                if info.get('is_ignored'):
                    ignored.append(self._dict_to_sync_info(fid, info))
        except Exception as e:
            logger.warning(f"Error getting ignored files: {e}")
        return ignored

    def ignore_file(self, canvas_file_id: int, canvas_filename: str = "", original_size: int = 0) -> bool:
        """Mark a file as ignored in the SQLite DB using UPSERT.

        If the file already exists in the manifest, UPDATE its is_ignored flag.
        If the file is brand-new (not yet downloaded), INSERT a stub row with is_ignored=1.
        """
        success = False
        for attempt in range(3):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    conn.execute(
                        '''INSERT INTO sync_manifest
                           (canvas_file_id, canvas_filename, local_path, canvas_updated_at, downloaded_at, original_size, is_ignored, original_md5)
                           VALUES (?, ?, '', '', '', ?, 1, '')
                           ON CONFLICT(canvas_file_id) DO UPDATE SET is_ignored = 1''',
                        (canvas_file_id, canvas_filename, original_size)
                    )
                    conn.commit()
                success = True
                break
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < 2:
                    time.sleep(0.5)
                    continue
                logger.warning(f"Error ignoring file {canvas_file_id}: {e}")
            except sqlite3.Error as e:
                logger.warning(f"Error ignoring file {canvas_file_id}: {e}")
                break
                
        return success

    def restore_file(self, canvas_file_id: int) -> bool:
        """Mark a file as no longer ignored directly in the SQLite DB.

        M-11: If the row is a stub created by bulk_ignore_files (no local_path,
        no downloaded_at), DELETE it entirely rather than just clearing the flag.
        Stubs accumulate over time if left, because orphan rows get re-analysed
        as phantom new files on every subsequent sync.
        """
        success = False
        for attempt in range(3):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    # Delete stub rows (nothing was ever downloaded)
                    conn.execute(
                        """DELETE FROM sync_manifest
                           WHERE canvas_file_id = ?
                             AND (downloaded_at = '' OR downloaded_at IS NULL)
                             AND (local_path = '' OR local_path IS NULL)""",
                        (canvas_file_id,)
                    )
                    # Clear the flag for real rows that existed before ignoring
                    conn.execute(
                        'UPDATE sync_manifest SET is_ignored = 0 WHERE canvas_file_id = ?',
                        (canvas_file_id,)
                    )
                    conn.commit()
                success = True
                break
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < 2:
                    time.sleep(0.5)
                    continue
                logger.warning(f"Error restoring file {canvas_file_id}: {e}")
            except sqlite3.Error as e:
                logger.warning(f"Error restoring file {canvas_file_id}: {e}")
                break

        return success

    def delete_manifest_rows(self, canvas_file_ids: list[int]) -> bool:
        """Hard-delete manifest rows (used by phantom-row pruning after a
        teacher re-upload has been superseded by its replacement entry).

        Deliberately NOT exposed in any UI path - the analyzer calls it only
        for rows that are simultaneously gone from Canvas, gone from disk, and
        superseded by a same-named tracked file. Never raises.
        """
        if not canvas_file_ids:
            return True
        rows = [(int(fid),) for fid in canvas_file_ids]
        for attempt in range(3):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    conn.executemany(
                        'DELETE FROM sync_manifest WHERE canvas_file_id = ?', rows)
                    conn.commit()
                return True
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < 2:
                    time.sleep(0.5)
                    continue
                logger.warning(f"delete_manifest_rows failed: {e}")
                break
            except sqlite3.Error as e:
                logger.warning(f"delete_manifest_rows failed: {e}")
                break
        return False

    def bulk_ignore_files(self, file_ids_and_names: list) -> bool:
        """Mark multiple files as ignored in the SQLite DB using UPSERT.
        
        Args:
            file_ids_and_names: List of (canvas_file_id, canvas_filename) tuples,
                                OR list of plain ints (legacy compat - filename defaults to '').
        """
        if not file_ids_and_names:
            return True
            
        # Normalize input: accept list[int], list[(id, name)], or list[(id, name, size)]
        rows = []
        for item in file_ids_and_names:
            if isinstance(item, (list, tuple)):
                rows.append((item[0], item[1] if len(item) > 1 else '', item[2] if len(item) > 2 else 0))
            else:
                rows.append((item, '', 0))

        success = False
        for attempt in range(3):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    conn.executemany(
                        '''INSERT INTO sync_manifest
                           (canvas_file_id, canvas_filename, local_path, canvas_updated_at, downloaded_at, original_size, is_ignored, original_md5)
                           VALUES (?, ?, '', '', '', ?, 1, '')
                           ON CONFLICT(canvas_file_id) DO UPDATE SET is_ignored = 1''',
                        rows
                    )
                    conn.commit()
                success = True
                break
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < 2:
                    time.sleep(0.5)
                    continue
                logger.warning(f"Error bulk ignoring files: {e}")
                break
            except sqlite3.Error as e:
                logger.warning(f"Error bulk ignoring files: {e}")
                break
                
        return success

    def bulk_restore_files(self, file_ids: list[int]) -> bool:
        """Mark multiple files as no longer ignored directly in the SQLite DB within a transaction."""
        if not file_ids:
            return True
            
        success = False
        for attempt in range(3):
            try:
                with closing(sqlite3.connect(make_long_path(self.db_path), timeout=30.0)) as conn, conn:
                    conn.executemany(
                        'UPDATE sync_manifest SET is_ignored = 0 WHERE canvas_file_id = ?', 
                        [(fid,) for fid in file_ids]
                    )
                    conn.commit()
                success = True
                break
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < 2:
                    time.sleep(0.5)
                    continue
                logger.warning(f"Error bulk restoring files: {e}")
                break
            except sqlite3.Error as e:
                logger.warning(f"Error bulk restoring files: {e}")
                break
                
        return success

    @staticmethod
    def compute_local_md5(filepath: Path) -> str:
        """Compute MD5 hash of a file efficiently by reading in chunks."""
        return compute_local_md5(filepath)


# --- Sync History Manager ---

class SyncHistoryManager:
    """Manages a log of past sync operations."""

    def __init__(self, config_dir: str):
        """
        Args:
            config_dir: Directory where config files are stored
        """
        self.history_path = Path(config_dir) / SYNC_HISTORY_FILENAME
        self._lock = threading.Lock()
    
    def load_history(self) -> list[dict]:
        """Load sync history from disk. Always returns a list, never raises.

        Guards against a corrupt/hand-edited file: bad JSON, invalid encoding
        (UnicodeDecodeError - a ValueError that the old narrow except missed),
        or a non-list top-level value all degrade to an empty history rather
        than propagating up and breaking the whole Sync page / add_entry().
        """
        if not self.history_path.exists():
            return []
        try:
            with open(self.history_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []
    
    def add_entry(self, entry: dict):
        """Add a sync history entry and save.

        Uses a threading.Lock + atomic temp-file + os.replace() to prevent
        concurrent writes from producing a corrupt or truncated history file.

        Args:
            entry: Dict with keys like 'timestamp', 'courses', 'files_synced', 'errors', 'categories'
        """
        with self._lock:
            history = self.load_history()
            history.append(entry)
            # L-13: Use user-configured retention; default 50.
            try:
                import streamlit as _st
                _retention = int(_st.session_state.get('sync_history_retention', 50))
            except Exception:
                _retention = 50
            if len(history) > _retention:
                history = history[-_retention:]
            tmp_path = self.history_path.with_suffix('.tmp')
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=2, ensure_ascii=False)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                # Atomic replace - prevents corrupt JSON on crash-during-write
                os.replace(str(tmp_path), str(self.history_path))
            except OSError as e:
                logger.warning(f"Error saving sync history: {e}")
                # Clean up orphaned tmp file on failure
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass

    def amend_last_entry(self, *, timestamp=None, add_files_synced=0,
                         add_categorized=None, add_synced_files=None,
                         synced_groups=None) -> bool:
        """Merge extra results into an existing history entry.

        The terminal Panopto pass runs AFTER the file-sync history entry is
        written, so its recordings would otherwise be missing from history. This
        bumps ``files_synced``, extends ``categorized_files`` / ``synced_files``,
        and replaces ``synced_groups`` (the caller passes the now-complete list).

        Targets the entry whose ``timestamp`` matches (else the most recent).
        Returns False if there is no entry to amend (caller then creates one).
        Best-effort, atomic write; never raises.
        """
        with self._lock:
            history = self.load_history()
            if not history:
                return False
            target = None
            if timestamp is not None:
                for e in reversed(history):
                    if e.get('timestamp') == timestamp:
                        target = e
                        break
            if target is None:
                target = history[-1]

            if add_files_synced:
                target['files_synced'] = int(target.get('files_synced', 0) or 0) + int(add_files_synced)
            if add_categorized:
                cats = target.setdefault(
                    'categorized_files',
                    {'new': [], 'updated': [], 'restored': [], 'protected': []},
                )
                for k, v in add_categorized.items():
                    if v:
                        cats.setdefault(k, []).extend(v)
            if add_synced_files:
                target.setdefault('synced_files', []).extend(add_synced_files)
            if synced_groups is not None:
                target['synced_groups'] = synced_groups

            tmp_path = self.history_path.with_suffix('.tmp')
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=2, ensure_ascii=False)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                os.replace(str(tmp_path), str(self.history_path))
                return True
            except OSError as e:
                logger.warning(f"Error amending sync history: {e}")
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
                return False

    def clear_history(self):
        """Clear all sync history."""
        with self._lock:
            try:
                if self.history_path.exists():
                    self.history_path.unlink()
            except IOError as e:
                import logging
                logging.warning(f"Error clearing sync history: {e}")


# --- Saved Sync Groups Manager ---

class SavedGroupsManager:
    """Manages saved sync groups (reusable sets of course/folder pairs).
    
    Persists groups to a JSON file so users can swap between semesters
    without reconfiguring folders.
    """
    
    def __init__(self, config_dir: str):
        """
        Args:
            config_dir: Directory where config files are stored
        """
        self.groups_path = Path(config_dir) / SAVED_GROUPS_FILENAME
    
    def load_groups(self) -> list[dict]:
        """Load all saved groups from disk.
        
        Returns:
            List of group dicts with keys: group_id, group_name, pairs
        """
        with _groups_lock:
            if not self.groups_path.exists():
                return []
            try:
                with open(self.groups_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    logger.warning(f"Sync groups file has invalid root type: {type(data)}")
                    return []
                groups = data.get('groups', [])
                if not isinstance(groups, list):
                    return []
                return groups
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading sync groups: {e}")
                return []
    
    def _save_all(self, groups: list[dict]):
        """Atomically persist the full groups list to disk.

        Pattern: write to ``.tmp``, fsync, then ``os.replace``.
        Matches the atomic write convention used by ``PresetManager``,
        ``SyncHistoryManager``, and ``save_sync_pairs``.
        """
        tmp_path = self.groups_path.with_suffix('.tmp')
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump({'groups': groups}, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp_path), str(self.groups_path))
        except IOError as e:
            logger.warning(f"Error saving sync groups: {e}")
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
    
    def save_group(self, name: str, pairs: list[dict], is_single_pair: bool = False) -> dict:
        """Save a new group (or single pair).
        
        Args:
            name: Human-readable group name (e.g. 'Fall 2025')
            pairs: List of pair dicts with keys: local_folder, course_id, course_name
            is_single_pair: If True, flags this as a saved single pair (not a multi-course group)
        
        Returns:
            The newly created group dict
        """
        with _groups_lock:
            groups = self.load_groups()
            new_group = {
                'group_id': f"grp_{uuid.uuid4().hex}",
                'group_name': name.strip(),
                'pairs': [
                    {
                        'local_folder': p.get('local_folder', ''),
                        'course_id': p.get('course_id'),
                        'course_name': p.get('course_name', ''),
                    }
                    for p in pairs
                ],
            }
            if is_single_pair:
                new_group['is_single_pair'] = True
            groups.append(new_group)
            self._save_all(groups)
            return new_group
    
    def delete_group(self, group_id: str) -> bool:
        """Delete a group by its ID.
        
        Returns:
            True if found and deleted, False otherwise
        """
        with _groups_lock:
            groups = self.load_groups()
            original_len = len(groups)
            groups = [g for g in groups if g.get('group_id') != group_id]
            if len(groups) == original_len:
                return False
            self._save_all(groups)
            return True
    
    def update_group(self, group_id: str, new_data: dict) -> bool:
        """Update an existing group's name and/or pairs.
        
        Args:
            group_id: The ID of the group to update
            new_data: Dict with optional keys 'group_name', 'pairs', 'is_single_pair'
        
        Returns:
            True if found and updated, False otherwise
        """
        with _groups_lock:
            groups = self.load_groups()
            for g in groups:
                if g.get('group_id') == group_id:
                    if 'group_name' in new_data:
                        g['group_name'] = new_data['group_name'].strip()
                    if 'pairs' in new_data:
                        g['pairs'] = [
                            {
                                'local_folder': p.get('local_folder', ''),
                                'course_id': p.get('course_id'),
                                'course_name': p.get('course_name', ''),
                            }
                            for p in new_data['pairs']
                        ]
                    if 'is_single_pair' in new_data:
                        g['is_single_pair'] = new_data['is_single_pair']
                    self._save_all(groups)
                    return True
            return False
    
    def matches_existing_group(self, pairs: list[dict]) -> bool:
        """Check if the given pairs exactly match any saved group.

        Comparison is based on sorted (course_id, local_folder) tuples,
        ignoring course_name and ordering.
        """
        current_sig = self._pairs_signature(pairs)
        with _groups_lock:
            for group in self.load_groups():
                if self._pairs_signature(group.get('pairs', [])) == current_sig:
                    return True
        return False
    
    @staticmethod
    def _pairs_signature(pairs: list[dict]) -> frozenset:
        """Create a hashable signature from a pairs list for comparison."""
        return frozenset(
            (p.get('course_id'), p.get('local_folder', ''))
            for p in pairs
        )


# --- Utility Functions ---

def compute_local_md5(filepath: Path) -> str | None:
    """Compute MD5 hash of a file efficiently by reading in 1 MB chunks.

    Returns:
        hex digest string - file was readable and hashed successfully.
        ""  (empty string) - file does not exist (no hash available).
        None - file exists but could not be read (PermissionError / locked).

    Callers that only care about availability can treat both falsy values the
    same way (``if not result``).  Callers that need to distinguish a missing
    file from an unreadable one should check ``result is None``.
    """
    if not filepath.exists():
        return ""
    h = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None
        
# compute_local_md5 is now a proper @staticmethod on SyncManager (see class body)


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
