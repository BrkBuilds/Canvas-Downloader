"""
Sync Manager Module for Canvas LMS Batch File Downloader
Handles synchronization between Canvas courses and local files.
"""

import os
import json
import logging
import sqlite3
import difflib
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Callable
from translations import get_text

# Module-level logger
logger = logging.getLogger(__name__)

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
    """Result of analyzing local folder vs Canvas course."""
    new_files: list[CanvasFileInfo] = field(default_factory=list)
    updated_files: list[tuple[CanvasFileInfo, SyncFileInfo]] = field(default_factory=list)
    missing_files: list[SyncFileInfo] = field(default_factory=list)
    ignored_files: list[SyncFileInfo] = field(default_factory=list)
    uptodate_files: list[tuple[CanvasFileInfo, SyncFileInfo]] = field(default_factory=list)
    deleted_on_canvas: list[SyncFileInfo] = field(default_factory=list)
    locally_deleted_files: list[SyncFileInfo] = field(default_factory=list)


# --- Constants ---

MANIFEST_FILENAME = ".canvas_sync_manifest.json"
DB_FILENAME = ".canvas_sync.db"
SYNC_PAIRS_FILENAME = "canvas_sync_pairs.json"
SYNC_HISTORY_FILENAME = "canvas_sync_history.json"


class SyncManager:
    """Manages synchronization between Canvas and local files using a SQLite database."""
    
    def __init__(self, local_path: str, course_id: int, course_name: str, language: str = 'en'):
        """
        Initialize SyncManager.
        
        Args:
            local_path: Path to the local sync folder (course folder)
            course_id: Canvas course ID
            course_name: Canvas course name (for display)
            language: Language code for translations ('en' or 'da')
        """
        self.local_path = Path(local_path)
        self.course_id = course_id
        self.course_name = course_name
        self.language = language
        self.manifest_path = self.local_path / MANIFEST_FILENAME
        self.db_path = self.local_path / DB_FILENAME
        self._init_db()
        
    def _init_db(self):
        """Initialize SQLite database for tracking synced files."""
        self.local_path.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            self._windows_unhide_file(self.db_path)
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Enable WAL mode for better concurrency and synchronous=NORMAL for speed/safety
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA synchronous=NORMAL;')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_manifest (
                    canvas_file_id INTEGER PRIMARY KEY,
                    canvas_filename TEXT,
                    local_path TEXT,
                    canvas_updated_at TEXT,
                    downloaded_at TEXT,
                    original_size INTEGER,
                    is_ignored INTEGER DEFAULT 0,
                    original_md5 TEXT DEFAULT ""
                )
            ''')
            # Handle migration for existing DBs to add original_md5
            try:
                cursor.execute('ALTER TABLE sync_manifest ADD COLUMN original_md5 TEXT DEFAULT ""')
            except sqlite3.OperationalError:
                pass  # Column already exists
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            cursor.execute('INSERT OR REPLACE INTO sync_metadata (key, value) VALUES (?, ?)', ('course_id', str(self.course_id)))
            cursor.execute('INSERT OR REPLACE INTO sync_metadata (key, value) VALUES (?, ?)', ('course_name', self.course_name))
            conn.commit()
            
        if os.name == 'nt':
            self._windows_hide_file(self.db_path)
    
    # --- Manifest Operations ---
    
    def load_manifest(self) -> dict:
        """
        Load the sync manifest from SQLite DB into an memory dictionary. 
        """
        manifest = {
            'course_id': self.course_id,
            'course_name': self.course_name,
            'files': {}
        }
        
        import time
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT canvas_file_id, canvas_filename, local_path, canvas_updated_at, downloaded_at, original_size, is_ignored, original_md5 FROM sync_manifest')
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
                            'original_md5': row[7] if row[7] is not None else ""
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
            
    def save_manifest(self, manifest: dict) -> bool:
        """Save the in-memory manifest dictionary to the SQLite DB."""
        import time
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                if os.name == 'nt':
                    self._windows_unhide_file(self.db_path)
                    
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    now_iso = datetime.now(timezone.utc).isoformat()
                    cursor.execute('INSERT OR REPLACE INTO sync_metadata (key, value) VALUES (?, ?)', ('last_sync', now_iso))
                    
                    cursor.execute('DELETE FROM sync_manifest')
                    
                    rows = []
                    for file_id_str, info in manifest.get('files', {}).items():
                        rows.append((
                            info.get('canvas_file_id', int(file_id_str)),
                            info.get('canvas_filename', ''),
                            info.get('local_path', ''),
                            info.get('canvas_updated_at', ''),
                            info.get('downloaded_at', now_iso),
                            info.get('original_size', 0),
                            1 if info.get('is_ignored') else 0,
                            info.get('original_md5', '')
                        ))
                        
                    cursor.executemany('''
                        INSERT INTO sync_manifest 
                        (canvas_file_id, canvas_filename, local_path, canvas_updated_at, downloaded_at, original_size, is_ignored, original_md5)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', rows)
                    conn.commit()
                    
                if os.name == 'nt':
                    self._windows_hide_file(self.db_path)
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
        if not filepath.exists():
            return
        try:
            import ctypes
            FILE_ATTRIBUTE_NORMAL = 0x80
            ctypes.windll.kernel32.SetFileAttributesW(
                str(filepath), FILE_ATTRIBUTE_NORMAL
            )
        except Exception:
            pass
    
    @staticmethod
    def _windows_hide_file(filepath: Path):
        """Set hidden attribute on a file on Windows."""
        if not filepath.exists():
            return
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            ctypes.windll.kernel32.SetFileAttributesW(
                str(filepath), FILE_ATTRIBUTE_HIDDEN
            )
        except Exception:
            pass
    
    # --- Heal Process ---
    
    def heal_manifest(self, manifest: dict, progress_callback: Optional[Callable] = None) -> dict:
        """
        Find moved/renamed/edited files by scanning the local folder.
        Uses a 3-tier heuristic:
        1. Exact filename match
        2. Exact MD5 hash match (for renamed files)
        3. Levenshtein distance on filename > 0.85
        """
        from ui_helpers import robust_filename_normalize
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
            progress_callback(get_text('healing_manifest', self.language))
            
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
                if filename in (MANIFEST_FILENAME, DB_FILENAME, SYNC_PAIRS_FILENAME, SYNC_HISTORY_FILENAME):
                    continue
                filepath = Path(root) / filename
                norm_str = os.path.normpath(str(filepath))
                if norm_str not in tracked_local_paths:
                    try:
                        sz = filepath.stat().st_size
                        orphaned_files.append({
                            'path': filepath,
                            'name': filename,
                            'norm_name': robust_filename_normalize(filename),
                            'size': sz,
                            'md5': None # Lazy compute
                        })
                    except OSError:
                        pass

        if not orphaned_files:
            return manifest
            
        # 3. Resolve matches (Heuristic Engine)
        for file_id, missing_info in missing_entries.items():
            orig_name = missing_info.get('canvas_filename', '')
            orig_norm_name = robust_filename_normalize(orig_name)
            orig_size = missing_info.get('original_size', -1)
            orig_md5 = missing_info.get('original_md5', '')
            
            best_match_idx = -1
            
            # TIER 1: Exact Normalized Filename Match (Handles user editing a file but keeping name)
            for idx, orphan in enumerate(orphaned_files):
                if orphan['norm_name'] == orig_norm_name:
                    best_match_idx = idx
                    break
                    
            # TIER 2: Exact MD5 Match (Handles user renaming a file but NOT editing it)
            if best_match_idx == -1 and orig_md5 and orig_size > 0:
                for idx, orphan in enumerate(orphaned_files):
                    if orphan['size'] == orig_size:
                        # Optimization: Bypass MD5 for files > 50MB and assume size match is enough
                        if orphan['size'] > 50 * 1024 * 1024:
                            best_match_idx = idx
                            # Use existing md5 if any, else just fallback to original
                            orphan['md5'] = orig_md5 
                            break
                        
                        if not orphan['md5']:
                            orphan['md5'] = self.compute_local_md5(orphan['path'])
                        if orphan['md5'] == orig_md5:
                            best_match_idx = idx
                            break
                            
            # TIER 3: Levenshtein Distance > 0.85
            if best_match_idx == -1:
                best_ratio = -1.0
                for idx, orphan in enumerate(orphaned_files):
                    ratio = difflib.SequenceMatcher(None, orphan['norm_name'], orig_norm_name).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match_idx = idx
                
                if best_ratio <= 0.85:
                    best_match_idx = -1
            
            # If we found a match via any tier, heal it
            if best_match_idx != -1:
                matched_orphan = orphaned_files.pop(best_match_idx)
                try:
                    relative_path = matched_orphan['path'].relative_to(self.local_path)
                    files_section[file_id]['local_path'] = str(relative_path).replace('\\', '/')
                    # Update the manifest with the new size/md5 if it changed due to Tier 1 matching
                    if matched_orphan['md5'] is None:
                        matched_orphan['md5'] = self.compute_local_md5(matched_orphan['path'])
                    files_section[file_id]['original_size'] = matched_orphan['size']
                    files_section[file_id]['original_md5'] = matched_orphan['md5']
                except ValueError:
                    pass
        
        manifest['files'] = files_section
        return manifest
    
    # --- Analysis ---
    
    def analyze_course(self, canvas_files: list[CanvasFileInfo], manifest: dict, 
                       cm=None, download_mode: str = 'modules') -> AnalysisResult:
        """
        Compare Canvas files with local manifest to categorize files.
        Pre-calculates target paths and performs backend deduplication (matching new files to missing ones).
        """
        result = AnalysisResult()
        files_section = manifest.get('files', {})
        
        # 0. Pre-calculate Target Paths if CanvasManager is provided
        target_paths = {}
        if cm and download_mode == 'modules':
            try:
                course = cm.canvas.get_course(self.course_id)
                modules = course.get_modules()
                for module in modules:
                    clean_module_name = cm._sanitize_filename(module.name)
                    items = module.get_module_items()
                    for item in items:
                        if item.type == 'File' and hasattr(item, 'content_id') and item.content_id:
                            target_paths[item.content_id] = clean_module_name
            except Exception as e:
                logger.warning(f"Failed to fetch module map in analyze_course: {e}")
        
        # Scan local files for discovery of "existing but untracked" files
        local_files_map = {}
        from ui_helpers import robust_filename_normalize

        for root, _, files in os.walk(self.local_path):
            for filename in files:
                if filename in (MANIFEST_FILENAME, DB_FILENAME, SYNC_PAIRS_FILENAME, SYNC_HISTORY_FILENAME):
                    continue
                filepath = Path(root) / filename
                norm_name = robust_filename_normalize(filename)
                try:
                    size = filepath.stat().st_size
                    local_files_map[norm_name] = (filepath, size)
                except OSError:
                    pass

        seen_ids = set()
        
        # Temporary lists for deduplication
        raw_new_files = []
        raw_missing_infos = []
        raw_locally_deleted = []

        for c_file in canvas_files:
            file_id = str(c_file.id)
            seen_ids.add(file_id)
            
            # Determine target path
            subfolder = target_paths.get(c_file.id, "")
            if subfolder:
                calc_path = f"{subfolder}/{c_file.filename}"
            else:
                calc_path = c_file.filename
                
            if file_id not in files_section:
                # 1. Not in manifest. Checking if it already exists locally.
                norm_name = robust_filename_normalize(c_file.filename)
                
                if norm_name in local_files_map:
                    local_path, local_size = local_files_map[norm_name]
                    if local_size == c_file.size:
                        # Auto-discover the file and count it as up-to-date
                        try:
                            rel_path = local_path.relative_to(self.local_path)
                            entry = {
                                'canvas_file_id': c_file.id,
                                'canvas_filename': c_file.filename,
                                'local_path': str(rel_path).replace('\\', '/'),
                                'canvas_updated_at': c_file.modified_at or datetime.now(timezone.utc).isoformat(),
                                'downloaded_at': datetime.now(timezone.utc).isoformat(),
                                'original_size': c_file.size,
                                'is_ignored': False,
                                'original_md5': SyncManager.compute_local_md5(local_path)
                            }
                            files_section[file_id] = entry
                            sync_info = self._dict_to_sync_info(file_id, entry, c_file)
                            sync_info.target_local_path = calc_path
                            result.uptodate_files.append((c_file, sync_info))
                            continue
                        except ValueError:
                            pass
                
                # Truly new file (add target path to c_file dynamically or create a proxy)
                c_file._target_local_path = calc_path
                raw_new_files.append(c_file)
            else:
                entry = files_section[file_id]
                local_path = self.local_path / entry.get('local_path', '')
                sync_info = self._dict_to_sync_info(file_id, entry, c_file)
                sync_info.target_local_path = calc_path
                
                if entry.get('is_ignored', False):
                    result.ignored_files.append(sync_info)
                    continue
                
                is_newer_on_canvas = self._is_canvas_newer(c_file, entry)
                
                if is_newer_on_canvas:
                    # 2. Teacher updated it
                    result.updated_files.append((c_file, sync_info))
                else:
                    # 3/4. Teacher did not update it. Trust the student.
                    if local_path.exists():
                        result.uptodate_files.append((c_file, sync_info))
                    else:
                        # Missing locally = Student deleted it
                        if entry.get('downloaded_at'):
                            # It was previously downloaded, so it's a student deletion
                            raw_locally_deleted.append(sync_info)
                        else:
                            # It was never downloaded (maybe sync crashed), so standard missing
                            raw_missing_infos.append(sync_info)
                        
        # 5. Check deletions (in manifest but not in canvas)
        for file_id, entry in files_section.items():
            if file_id not in seen_ids:
                if not entry.get('is_ignored', False):
                    sync_info = self._dict_to_sync_info(file_id, entry)
                    result.deleted_on_canvas.append(sync_info)
                    
        # --- Backend Deduplication (The Teacher Re-upload Scenario) ---
        new_name_map = {robust_filename_normalize(nf.filename): nf for nf in raw_new_files}
        final_new_files = []
        final_missing_files = []
        
        # Cross-reference missing files against new files
        for missing_info in raw_missing_infos:
            missing_norm = robust_filename_normalize(missing_info.canvas_filename)
            if missing_norm in new_name_map:
                # The teacher deleted the old Canvas file and uploaded a new one with the same name.
                # Treat this as an UPDATE, not a Delete+New. 
                matching_new_cfile = new_name_map[missing_norm]
                
                # We link the missing sync_info with the new canvas file.
                result.updated_files.append((matching_new_cfile, missing_info))
                
                # Remove from new_files list so it doesn't duplicate
                del new_name_map[missing_norm]
            else:
                final_missing_files.append(missing_info)
                
        # Check locally deleted files against re-uploads as well
        final_locally_deleted = []
        for del_info in raw_locally_deleted:
            missing_norm = robust_filename_normalize(del_info.canvas_filename)
            if missing_norm in new_name_map:
                matching_new_cfile = new_name_map[missing_norm]
                result.updated_files.append((matching_new_cfile, del_info))
                del new_name_map[missing_norm]
            else:
                final_locally_deleted.append(del_info)

        # Reconstruct the remaining new files that were not duplicates
        final_new_files = list(new_name_map.values())
        
        result.new_files = final_new_files
        result.missing_files = final_missing_files
        result.locally_deleted_files = final_locally_deleted
    
        return result

    def detect_structure(self) -> str:
        """Detect whether this course folder uses 'modules' (subfolders) or 'flat' structure."""
        manifest = self.load_manifest()
        files_section = manifest.get('files', {})
        for file_id, entry in files_section.items():
            local_path = entry.get('local_path', '')
            if os.sep in local_path or '/' in local_path:
                parts = Path(local_path).parts
                if len(parts) > 1:
                    return 'modules'
        
        if self.local_path.exists():
            for item in self.local_path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    return 'modules'
        return 'flat'

    def create_initial_manifest(self, downloaded_files: list) -> None:
        """Creates a manifest from a list of newly downloaded files."""
        manifest = {
            'course_id': self.course_id,
            'course_name': self.course_name,
            'files': {}
        }
        
        now_iso = datetime.now(timezone.utc).isoformat()
        for file_info, filepath in downloaded_files:
            try:
                filepath = Path(filepath)
                if not filepath.exists():
                    continue
                    
                rel_path = filepath.relative_to(self.local_path)
                file_id = str(getattr(file_info, 'id', ''))
                if not file_id:
                    continue

                manifest['files'][file_id] = {
                    'canvas_file_id': int(file_id),
                    'canvas_filename': getattr(file_info, 'filename', filepath.name),
                    'local_path': str(rel_path).replace('\\', '/'),
                    'canvas_updated_at': getattr(file_info, 'modified_at', now_iso) or now_iso,
                    'downloaded_at': now_iso,
                    'original_size': filepath.stat().st_size,
                    'is_ignored': False,
                    'original_md5': SyncManager.compute_local_md5(filepath)
                }
            except Exception as e:
                logger.warning(f"Failed to add file {getattr(file_info, 'filename', 'unknown')} to initial manifest: {e}")
                
        self.save_manifest(manifest)
        logger.info(f"Created initial manifest with {len(manifest['files'])} files.")

    def _is_canvas_newer(self, canvas_file: CanvasFileInfo, manifest_entry: dict) -> bool:
        """Check if Canvas version is strictly newer than manifest entry."""
        if not canvas_file.modified_at:
            return False
        
        manifest_date_str = manifest_entry.get('canvas_updated_at')
        if not manifest_date_str:
            return True
        
        try:
            canvas_dt = datetime.fromisoformat(canvas_file.modified_at.replace('Z', '+00:00'))
            manifest_dt = datetime.fromisoformat(manifest_date_str.replace('Z', '+00:00'))
            return canvas_dt > manifest_dt
        except (ValueError, TypeError):
            return False
    
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
                             local_relative_path: str, local_md5: str = "") -> dict:
        """Add or update a file entry in the manifest after successful download and save immediately to DB."""
        file_id = str(canvas_file.id)
        
        # If no MD5 is provided but file exists, compute it
        if not local_md5:
            full_path = self.local_path / local_relative_path
            if full_path.exists():
                local_md5 = SyncManager.compute_local_md5(full_path)
                
        entry = {
            'canvas_file_id': int(file_id),
            'canvas_filename': canvas_file.filename,
            'local_path': local_relative_path,
            'canvas_updated_at': canvas_file.modified_at or datetime.now(timezone.utc).isoformat(),
            'downloaded_at': datetime.now(timezone.utc).isoformat(),
            'original_size': canvas_file.size,
            'is_ignored': False,
            'original_md5': local_md5
        }
        manifest['files'][file_id] = entry
        
        # Per-file DB commit
        self._save_single_file_to_db(entry)
        
        return manifest
        
    def _save_single_file_to_db(self, info: dict) -> bool:
        """Save a single file entry to the SQLite DB."""
        import time
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                if os.name == 'nt':
                    self._windows_unhide_file(self.db_path)
                    
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR REPLACE INTO sync_manifest 
                        (canvas_file_id, canvas_filename, local_path, canvas_updated_at, downloaded_at, original_size, is_ignored, original_md5)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        info.get('canvas_file_id'),
                        info.get('canvas_filename', ''),
                        info.get('local_path', ''),
                        info.get('canvas_updated_at', ''),
                        info.get('downloaded_at', ''),
                        info.get('original_size', 0),
                        1 if info.get('is_ignored') else 0,
                        info.get('original_md5', '')
                    ))
                    conn.commit()
                    
                if os.name == 'nt':
                    self._windows_hide_file(self.db_path)
                return True
            except sqlite3.OperationalError as e:
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                else:
                    return False
            except sqlite3.Error:
                return False
        return False
    
    def mark_files_ignored(self, manifest: dict, file_ids: list) -> dict:
        """Mark files as ignored in the manifest."""
        for file_id in file_ids:
            str_id = str(file_id)
            if str_id in manifest.get('files', {}):
                manifest['files'][str_id]['is_ignored'] = True
        return manifest
        
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
        
    def unignore_files(self, file_ids: list[int]) -> bool:
        """Mark a list of file IDs as no longer ignored."""
        try:
            manifest = self.load_manifest()
            changed = False
            for fid in file_ids:
                str_id = str(fid)
                if str_id in manifest.get('files', {}):
                    manifest['files'][str_id]['is_ignored'] = False
                    changed = True
            
            if changed:
                return self.save_manifest(manifest)
            return True
        except Exception as e:
            logger.warning(f"Error unignoring files: {e}")
            return False


# --- Sync History Manager ---

class SyncHistoryManager:
    """Manages a log of past sync operations."""
    
    def __init__(self, config_dir: str):
        """
        Args:
            config_dir: Directory where config files are stored
        """
        self.history_path = Path(config_dir) / SYNC_HISTORY_FILENAME
    
    def load_history(self) -> list[dict]:
        """Load sync history from disk."""
        if not self.history_path.exists():
            return []
        try:
            with open(self.history_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    
    def add_entry(self, entry: dict):
        """Add a sync history entry and save.
        
        Args:
            entry: Dict with keys like 'timestamp', 'courses', 'files_synced', 'errors', 'categories'
        """
        history = self.load_history()
        history.append(entry)
        # Keep last 50 entries
        if len(history) > 50:
            history = history[-50:]
        try:
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.warning(f"Error saving sync history: {e}")


# --- Utility Functions ---

def get_file_icon(filename: str) -> str:
    """Get an emoji icon based on file extension."""
    ext = Path(filename).suffix.lower()
    
    icon_map = {
        # Documents
        '.pdf': '📄',
        '.doc': '📝', '.docx': '📝',
        '.ppt': '📊', '.pptx': '📊', '.pptm': '📊',
        '.xls': '📈', '.xlsx': '📈',
        '.txt': '📃',
        # Media
        '.mp4': '🎬', '.mov': '🎬', '.avi': '🎬', '.mkv': '🎬',
        '.mp3': '🎵', '.wav': '🎵', '.m4a': '🎵',
        '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️',
        # Code/Data
        '.zip': '📦', '.rar': '📦', '.7z': '📦',
        '.html': '🌐', '.htm': '🌐',
        '.py': '🐍', '.js': '📜', '.css': '🎨',
    }
    
    return icon_map.get(ext, '📁')

def compute_local_md5(filepath: Path) -> str:
    """Compute MD5 hash of a file efficiently by reading in chunks."""
    import hashlib
    if not filepath.exists():
        return ""
    h = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""
        
# Add compute_local_md5 to SyncManager namespace for easier class-relative calling
SyncManager.compute_local_md5 = staticmethod(compute_local_md5)


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
