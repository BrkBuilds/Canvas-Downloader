import os
import platform
import re
import uuid
import shutil
import html
import urllib.parse
import traceback
from pathlib import Path
from datetime import datetime, timezone
from canvasapi import Canvas
from canvasapi.exceptions import CanvasException, Unauthorized, ResourceDoesNotExist
import asyncio
import aiohttp
import aiofiles
from canvas_debug import log_debug, clear_debug_log
import logging

from sync_manager import SyncManager, CanvasFileInfo, make_secondary_id, is_secondary_id
from ui_helpers import make_long_path

logger = logging.getLogger(__name__)

# --- Constants ---
MAX_RETRIES = 5
TIMEOUT_SECONDS = 300
RETRY_DELAY = 1

# --- Secondary Content Configuration Defaults ---
# These are the settings that the UI will eventually expose as checkboxes.
# The backend operates on whatever dict it receives; defaults ensure safety.
SECONDARY_CONTENT_DEFAULTS = {
    'download_assignments': False,
    'download_syllabus': False,
    'download_announcements': False,
    'download_discussions': False,
    'download_quizzes': False,
    'download_rubrics': False,
    'download_submissions': False,
    'isolate_secondary_content': True,   # True = Mode B (subfolder), False = Mode A (inline)
}

# Maps entity types to their subfolder names (Mode B) and prefixes (Mode A)
_ENTITY_ROUTING = {
    'assignment':   {'folder': 'Assignments',   'prefix': 'Assignment'},
    'syllabus':     {'folder': 'Syllabus',      'prefix': 'Syllabus'},
    'announcement': {'folder': 'Announcements', 'prefix': 'Announcement'},
    'discussion':   {'folder': 'Discussions',   'prefix': 'Discussion'},
    'quiz':         {'folder': 'Quizzes',       'prefix': 'Quiz'},
    'rubric':       {'folder': 'Rubrics',       'prefix': 'Rubric'},
    'submission':   {'folder': 'Submissions',   'prefix': 'Submission'},
}

class DownloadError:
    """Structured error object for UI display and logging."""
    def __init__(self, course_name, item_name, error_type, message, raw_error=None, context=None):
        self.course_name = course_name
        self.item_name = item_name
        self.error_type = error_type # e.g., '401', 'Rate Limit', 'Network', 'Generic'
        self.message = message
        self.raw_error = raw_error
        self.context = context or {}
        self.timestamp = datetime.now()

    def __str__(self):
        return f"[{self.course_name}] {self.message}"

    def to_log_entry(self):
        """Format for log file"""
        ts = self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        return f"[{ts}] [{self.course_name}] [{self.error_type}] {self.item_name}: {self.message}"

class CanvasManager:
    def __init__(self, api_key, api_url):
        self.api_key = api_key
        # Clean and validate URL
        api_url = api_url.strip()
        if not api_url:
            self.api_url = "" # Let validation fail later
        else:
            if not api_url.startswith("http"):
                api_url = "https://" + api_url
            # Remove trailing slash for consistency
            self.api_url = api_url.rstrip("/")
            
        # Initialize Canvas object
        try:
            self.canvas = Canvas(self.api_url, self.api_key)
        except Exception:
            # If URL is completely malformed, Canvas init might fail immediately
            self.canvas = None
            
        self.user = None
        self._logged_error_sigs = set()  # Dedup cache: prevents same error being logged twice in one run

    def validate_token(self):
        """Checks if the token is valid by attempting to fetch the current user."""
        if not self.api_url or not self.canvas:
            return False, 'Login failed. Please check that your Canvas URL and API Token are correct.'

        try:
            # We attempt to fetch the user. This validates both the URL and Token.
            self.user = self.canvas.get_current_user()
            return True, f'Logged in as: {self.user.name}'
        except Exception as e:
            # Return specific message if possible, else generic
            msg = str(e) if str(e) else 'Login failed. Please check that your Canvas URL and API Token are correct.'
            return False, msg

    def get_courses(self, favorites_only=True):
        """
        Fetches courses. 
        Raises exceptions for UI to handle (no silent failures).
        """
        if not self.canvas:
             raise ValueError("Canvas object not initialized (check URL).")

        if favorites_only:
            # Lazy-load user if not already set
            if self.user is None:
                self.user = self.canvas.get_current_user()
            courses = self.user.get_favorite_courses()
        else:
            # Fetch active and invited courses
            courses = self.canvas.get_courses(enrollment_state=['active', 'invited_or_pending'])
        
        # Validation/Filter loop (might raise API errors if connection drops)
        course_list = []
        for course in courses:
            if hasattr(course, 'name') and hasattr(course, 'id'):
                    course_list.append(course)
        return course_list

    def get_course_files_metadata(self, course, progress_callback=None, secondary_content_settings=None):
        """
        Fetch metadata for all files in a course using a robust Hybrid strategy.
        
        Strategy:
        1. Try to fetch all files using `course.get_files()`. This is the primary source.
           - If it fails mid-stream, we CATCH the error but KEEP the files found so far.
        2. Always run a secondary scan of Modules to find files that might be locked/hidden 
           or were missed due to the error in step 1.
        3. Deduplicate by File ID.
        4. Optionally merge metadata for secondary content entities (Assignments, etc.).
        
        Returns:
            List of CanvasFileInfo objects (unique by ID).
        """
        from sync_manager import CanvasFileInfo
        
        all_files_map = {} # ID -> CanvasFileInfo
        
        # --- Phase 1: Bulk Fetch (get_files) ---
        try:
            # We iterate manually to catch errors during pagination
            canvas_files = course.get_files()
            for file in canvas_files:
                if not getattr(file, 'url', ''):
                    continue
                try:
                    f_info = CanvasFileInfo(
                        id=file.id,
                        filename=getattr(file, 'filename', ''),
                        display_name=getattr(file, 'display_name', getattr(file, 'filename', '')),
                        size=getattr(file, 'size', 0),
                        modified_at=getattr(file, 'modified_at', None),
                        md5=getattr(file, 'md5', None),
                        url=getattr(file, 'url', ''),
                        content_type=getattr(file, 'content-type', ''),
                        folder_id=getattr(file, 'folder_id', None),
                    )
                    all_files_map[file.id] = f_info
                except Exception as e:
                    logger.warning(f"Error parsing file object {getattr(file, 'id', '?')}: {e}")
        except Exception as e:
            logger.warning(f"Error during get_course_files_metadata bulk fetch: {e}")
            # We do NOT raise here. We continue to Phase 2 to supplement what we found.
            
        # --- Phase 2: Module Scan (Supplement) ---
        try:
            module_files = self._get_files_from_modules(course, progress_callback=progress_callback,
                                                        secondary_content_settings=secondary_content_settings)
            module_only_count = 0
            for f_info in module_files:
                if f_info.id not in all_files_map:
                    all_files_map[f_info.id] = f_info
                    module_only_count += 1
            
            # Diagnostic: If bulk fetch missed items that modules found, it suggests Files tab is restricted/hidden
            if module_only_count > 0:
                logger.warning(
                    f"Hybrid Fetch: Found {module_only_count} files in Modules that were missing from 'Files' tab. "
                    f"This suggests 'Files' tab access is restricted for course {course.id}."
                )
                    
        except Exception as e:
            logger.error(f"Error during module scan fallback: {e}")

        # --- Phase 3: Secondary Content Metadata ---
        if secondary_content_settings:
            try:
                secondary_items = self.get_secondary_content_metadata(
                    course, secondary_content_settings,
                )
                for s_info in secondary_items:
                    if s_info.id not in all_files_map:
                        all_files_map[s_info.id] = s_info
            except Exception as e:
                logger.error(f"Error fetching secondary content metadata: {e}")
            
        return list(all_files_map.values())
    
    def _get_files_from_modules(self, course, progress_callback=None, secondary_content_settings=None):
        """Fallback: Get files by iterating through modules.

        Also emits mock CanvasFileInfo for secondary entity types
        (Assignment, Quiz, Discussion) when *secondary_content_settings*
        enables them.  This allows the sync analysis engine to see these
        entities without additional API calls.
        """
        from sync_manager import CanvasFileInfo
        
        files = []
        modules = list(course.get_modules())
        total_modules = len(modules)
        for idx, module in enumerate(modules):
            if progress_callback:
                progress_callback(idx + 1, total_modules, f"Scanning module: {module.name}")
            
            items = module.get_module_items()
            for item in items:
                if item.type == 'File':
                    if not hasattr(item, 'content_id') or not item.content_id:
                        continue
                    try:
                        file = course.get_file(item.content_id)
                        if not getattr(file, 'url', ''):
                            continue
                        files.append(CanvasFileInfo(
                            id=file.id,
                            filename=getattr(file, 'filename', ''),
                            display_name=getattr(file, 'display_name', getattr(file, 'filename', '')),
                            size=getattr(file, 'size', 0),
                            modified_at=getattr(file, 'modified_at', None),
                            md5=getattr(file, 'md5', None),
                            url=getattr(file, 'url', ''),
                            content_type=getattr(file, 'content-type', ''),
                            folder_id=getattr(file, 'folder_id', None),
                        ))
                    except Exception:
                        # If a specific file content_id is invalid, we skip it.
                        # This works as "best effort".
                        pass
                elif item.type in ['Page', 'ExternalUrl', 'ExternalTool']:
                    ext = ".html" if item.type == 'Page' else ".url"
                    safe_title = self._sanitize_filename(getattr(item, 'title', 'Untitled')) + ext
                    
                    actual_url = getattr(item, 'html_url', None) or getattr(item, 'external_url', None) or getattr(item, 'url', '')
                    
                    mock_info = CanvasFileInfo(
                        id=-int(item.id) if hasattr(item, 'id') else 0,
                        filename=safe_title,
                        display_name=safe_title,
                        size=0,
                        modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                        url=actual_url,
                        content_type="text/html" if item.type == 'Page' else "application/x-url"
                    )
                    files.append(mock_info)

                # --- Secondary entities found in modules ---
                elif item.type == 'Assignment' and secondary_content_settings and secondary_content_settings.get('download_assignments'):
                    safe_title = self._sanitize_filename(getattr(item, 'title', 'Untitled')) + '.html'
                    content_id = getattr(item, 'content_id', 0) or 0
                    files.append(CanvasFileInfo(
                        id=make_secondary_id('assignment', content_id),
                        filename=safe_title,
                        display_name=getattr(item, 'title', 'Untitled'),
                        size=0,
                        modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                        url=getattr(item, 'html_url', ''),
                        content_type='text/html',
                    ))
                elif item.type == 'Quiz' and secondary_content_settings and secondary_content_settings.get('download_quizzes'):
                    safe_title = self._sanitize_filename(getattr(item, 'title', 'Untitled')) + '.html'
                    content_id = getattr(item, 'content_id', 0) or 0
                    files.append(CanvasFileInfo(
                        id=make_secondary_id('quiz', content_id),
                        filename=safe_title,
                        display_name=getattr(item, 'title', 'Untitled'),
                        size=0,
                        modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                        url=getattr(item, 'html_url', ''),
                        content_type='text/html',
                    ))
                elif item.type == 'Discussion' and secondary_content_settings and secondary_content_settings.get('download_discussions'):
                    safe_title = self._sanitize_filename(getattr(item, 'title', 'Untitled')) + '.html'
                    content_id = getattr(item, 'content_id', 0) or 0
                    files.append(CanvasFileInfo(
                        id=make_secondary_id('discussion', content_id),
                        filename=safe_title,
                        display_name=getattr(item, 'title', 'Untitled'),
                        size=0,
                        modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                        url=getattr(item, 'html_url', ''),
                        content_type='text/html',
                    ))
        return files

    def get_secondary_content_metadata(self, course, settings):
        """Return CanvasFileInfo list for *standalone* secondary content.

        This covers entities that are NOT linked from any module and thus
        would not be surfaced by ``_get_files_from_modules``.  Examples:
        Announcements, Syllabus, standalone Assignments, Rubrics.

        Used by the sync analysis path to detect new/updated/missing
        secondary entities in the manifest.
        """
        from sync_manager import CanvasFileInfo

        items = []

        # Syllabus
        if settings.get('download_syllabus'):
            try:
                full_course = self.canvas.get_course(
                    course.id, include=['syllabus_body'],
                )
                if getattr(full_course, 'syllabus_body', None):
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('syllabus', course.id),
                        filename='Syllabus.html',
                        display_name='Syllabus',
                        size=0,
                        modified_at=getattr(full_course, 'updated_at', ''),
                        url='',
                        content_type='text/html',
                    ))
            except Exception:
                pass

        # Announcements
        if settings.get('download_announcements'):
            try:
                topics = course.get_discussion_topics(only_announcements=True)
                for topic in topics:
                    t_id = getattr(topic, 'id', 0)
                    title = getattr(topic, 'title', 'Announcement')
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('announcement', t_id),
                        filename=self._sanitize_filename(title) + '.html',
                        display_name=title,
                        size=0,
                        modified_at=getattr(topic, 'posted_at', ''),
                        url=getattr(topic, 'html_url', ''),
                        content_type='text/html',
                    ))
            except Exception:
                pass

        # Standalone Assignments (ones not in modules are caught here)
        if settings.get('download_assignments'):
            try:
                for assignment in course.get_assignments():
                    a_id = getattr(assignment, 'id', 0)
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('assignment', a_id),
                        filename=self._sanitize_filename(
                            getattr(assignment, 'name', 'Assignment')) + '.html',
                        display_name=getattr(assignment, 'name', 'Assignment'),
                        size=0,
                        modified_at=getattr(assignment, 'updated_at', ''),
                        url=getattr(assignment, 'html_url', ''),
                        content_type='text/html',
                    ))
            except Exception:
                pass

        # Standalone Discussions (non-announcement)
        if settings.get('download_discussions'):
            try:
                for topic in course.get_discussion_topics():
                    if getattr(topic, 'is_announcement', False):
                        continue
                    t_id = getattr(topic, 'id', 0)
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('discussion', t_id),
                        filename=self._sanitize_filename(
                            getattr(topic, 'title', 'Discussion')) + '.html',
                        display_name=getattr(topic, 'title', 'Discussion'),
                        size=0,
                        modified_at=(getattr(topic, 'last_reply_at', '')
                                     or getattr(topic, 'updated_at', '')),
                        url=getattr(topic, 'html_url', ''),
                        content_type='text/html',
                    ))
            except Exception:
                pass

        # Quizzes
        if settings.get('download_quizzes'):
            try:
                for quiz in course.get_quizzes():
                    q_id = getattr(quiz, 'id', 0)
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('quiz', q_id),
                        filename=self._sanitize_filename(
                            getattr(quiz, 'title', 'Quiz')) + '.html',
                        display_name=getattr(quiz, 'title', 'Quiz'),
                        size=0,
                        modified_at=getattr(quiz, 'updated_at', ''),
                        url=getattr(quiz, 'html_url', ''),
                        content_type='text/html',
                    ))
            except Exception:
                pass

        # Rubrics
        if settings.get('download_rubrics'):
            try:
                for rubric in course.get_rubrics():
                    r_id = getattr(rubric, 'id', 0)
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('rubric', r_id),
                        filename=self._sanitize_filename(
                            getattr(rubric, 'title', 'Rubric')) + '.md',
                        display_name=getattr(rubric, 'title', 'Rubric'),
                        size=0,
                        modified_at=getattr(rubric, 'updated_at', ''),
                        url='',
                        content_type='text/markdown',
                    ))
            except Exception:
                pass

        return items

    def get_folder_map(self, course) -> dict:
        """
        Fetch all folders in a course and return a mapping of folder_id to relative path.
        
        Returns:
            Dict mapping folder_id (int) to relative path string (e.g. 'Module 1/Sub').
            Returns empty dict on failure.
        """
        folder_map = {}
        try:
            all_folders = course.get_folders()
            for folder in all_folders:
                full_name = getattr(folder, 'full_name', '')
                if full_name.startswith("course files"):
                    rel_path = full_name[len("course files"):].strip('/')
                else:
                    rel_path = full_name
                folder_map[folder.id] = rel_path
        except Exception as e:
            logger.warning(f"Failed to fetch folder map for course: {e}")
        return folder_map


    def count_course_items(self, course, mode='modules', file_filter='all'):
        """
        Counts total number of downloadable items in a course.
        Matches the logic of download_course_async (including Hybrid Mode catch-all).
        """
        count = 0
        allowed_exts = ['.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx']
        
        try:
            if mode == 'flat':
                # 1. Count Files
                try:
                    files = list(course.get_files())
                    for f in files:
                        if file_filter == 'study':
                            ext = os.path.splitext(getattr(f, 'filename', ''))[1].lower()
                            if ext in allowed_exts:
                                count += 1
                        else:
                            count += 1
                except Exception:
                    pass # Fallback to modules will catch files if get_files failed
                
                # 2. Count non-file Module Items 
                if file_filter != 'study':
                    try:
                        modules = course.get_modules()
                        for module in modules:
                            items = module.get_module_items()
                            for item in items:
                                if item.type in ['Page', 'ExternalUrl', 'ExternalTool']:
                                    count += 1
                    except Exception:
                         pass

            else:
                # Modules Mode (Default) - Hybrid Logic
                # 1. Count Module Items
                module_file_ids = set()
                modules = course.get_modules()
                for module in modules:
                    items = module.get_module_items()
                    for item in items:
                        if item.type == 'File':
                            if hasattr(item, 'content_id'):
                                module_file_ids.add(item.content_id)
                            
                            if file_filter == 'study':
                                # We can't easily check extension of module item without file object, 
                                # but usually we count it. Accurately? 
                                # Let's assume for now if filter='study', we only count files?
                                # Ideally we'd fetch the file to check ext, but that's slow.
                                # Let's just count it for now.
                                count += 1
                            else:
                                count += 1
                                
                        elif item.type in ['Page', 'ExternalUrl', 'ExternalTool']:
                            if file_filter != 'study':
                                count += 1
                
                # 2. Count Catch-All Files (Files NOT in modules)
                try:
                    all_files = course.get_files()
                    for file in all_files:
                        if file.id in module_file_ids:
                            continue # Already counted
                        
                        if file_filter == 'study':
                            ext = os.path.splitext(getattr(file, 'filename', ''))[1].lower()
                            if ext not in allowed_exts:
                                continue
                        
                        count += 1
                except Exception:
                    pass

        except Exception:
            # Counting is "best effort" for progress bar. 
            pass
        return count
    
    def get_course_total_size_mb(self, course, mode='modules', file_filter='all'):
        """Calculate total size in MB."""
        total_bytes = 0
        allowed_exts = ['.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx']
        try:
            # Try get_files() first
            try:
                files = course.get_files()
                for file in files:
                    if file_filter == 'study':
                        ext = os.path.splitext(getattr(file, 'filename', ''))[1].lower()
                        if ext not in allowed_exts:
                            continue
                    total_bytes += getattr(file, 'size', 0)
            except Exception:
                # Fallback to modules
                modules = course.get_modules()
                for module in modules:
                    items = module.get_module_items()
                    for item in items:
                        if item.type == 'File':
                            try:
                                file_obj = course.get_file(item.content_id)
                                if file_filter == 'study':
                                    ext = os.path.splitext(getattr(file_obj, 'filename', ''))[1].lower()
                                    if ext not in allowed_exts:
                                        continue
                                total_bytes += getattr(file_obj, 'size', 0)
                            except Exception:
                                pass
        except Exception:
            pass
        return total_bytes / (1024 * 1024)

    async def download_course_async(self, course, mode, save_dir, progress_callback=None, check_cancellation=None, file_filter='all', debug_mode=False, post_processing_settings=None, secondary_content_settings=None):
        """
        Downloads content for a single course asynchronously.
        """
        course_name = self._sanitize_filename(course.name)
        base_path = Path(save_dir) / course_name
        
        # Check disk space
        if not self._check_disk_space(save_dir):
            error = DownloadError(
                course.name, 
                "Disk Check", 
                "Disk Full", 
                'Insufficient disk space. Need at least 1GB free.'
            )
            if progress_callback: progress_callback(error, progress_type='error')
            self._log_error(save_dir, error)
            return
        
        base_path.mkdir(parents=True, exist_ok=True)

        if check_cancellation and check_cancellation():
            if progress_callback: progress_callback('Download cancelled.')
            return
        
        # --- Sync Run #0: Initialize the Sync DB during the very first download ---
        # This creates .canvas_sync.db and the sync_manifest table so the Sync engine
        # inherits a perfect state when the user later clicks the Sync tab.
        sync_manager = SyncManager(base_path, course.id, course.name)
        
        debug_file = (Path(save_dir) / "debug_log.txt") if debug_mode else None
        if debug_mode:
            # Append course header (never wipe — one global log per session)
            log_debug(f"\n{'='*50}\n--- Download: {course.name} (ID: {course.id}) Mode: {mode} ---\n{'='*50}", debug_file)
            log_debug(f"Save Dir: {save_dir}", debug_file)

        downloaded_file_ids = set()
        seen_target_paths = set()  # Path-based collision tracking
        module_handled_ids = set()  # Secondary entity IDs already handled via module dispatch
        mb_tracker = {'bytes_downloaded': 0}
        
        # Determine semaphore limit from session state if available, default to 5
        import streamlit as st  # Deferred: keeps canvas_logic reusable without Streamlit dependency
        concurrent_limit = st.session_state.get('concurrent_downloads', 5)
        sem = asyncio.Semaphore(concurrent_limit)
        
        tasks = []
        timeout = aiohttp.ClientTimeout(total=None, sock_read=60, sock_connect=15)

        async with aiohttp.ClientSession(headers={'Authorization': f'Bearer {self.api_key}'}, timeout=timeout) as session:
            downloaded_files_info = []
            
            try:
                if mode == 'flat':
                    downloaded_files_info = await self._download_flat_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter, error_root_path=Path(save_dir), debug_file=debug_file, sync_manager=sync_manager)
                elif mode == 'files':
                    downloaded_files_info = await self._download_folders_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter, error_root_path=Path(save_dir), debug_file=debug_file, sync_manager=sync_manager)
                else:
                    # Modules mode
                    # 1. Fetch Modules
                    modules = None
                    for attempt in range(3):
                        try:
                            modules = course.get_modules()
                            modules = list(modules) # Force fetch
                            break
                        except Exception as e:
                            if attempt < 2:
                                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                            else:
                                raise e

                    for module in modules:
                        if check_cancellation and check_cancellation(): break
                        
                        try:
                            log_debug(f"Processing Module: {module.name} (ID: {module.id})", debug_file)
                            module_name = self._sanitize_filename(module.name)
                            target_path = base_path / module_name
                            target_path.mkdir(parents=True, exist_ok=True)

                            items = list(module.get_module_items())
                            log_debug(f"Found {len(items)} items in module '{module.name}'", debug_file)
                            for item in items:
                                if check_cancellation and check_cancellation(): break
                                
                                log_debug(f"  - Item: {getattr(item, 'title', 'unknown')} (Type: {getattr(item, 'type', 'unknown')})", debug_file)
                                
                                try:
                                    if item.type == 'File':
                                        if not hasattr(item, 'content_id') or not item.content_id:
                                            # Create Error
                                            err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing Content ID", f"Item {getattr(item, 'title', 'unknown')} missing content_id")
                                            if progress_callback: progress_callback(err, progress_type='error')
                                            self._log_error(save_dir, err)
                                            continue
                                        
                                        file_obj = course.get_file(item.content_id)
                                        # Track the ID for the catch-all phase, but DO NOT skip it here 
                                        # so files appearing in multiple modules get their respective copies.
                                        downloaded_file_ids.add(file_obj.id)
                                        
                                        # Synchronous conflict resolution to prevent data loss
                                        base_filename = self._sanitize_filename(getattr(file_obj, 'filename', 'unknown'))
                                        filepath = target_path / base_filename
                                        target_key = str(filepath).lower()

                                        if target_key in seen_target_paths:
                                            counter = 1
                                            while True:
                                                new_name = f"{filepath.stem} ({counter}){filepath.suffix}"
                                                new_filepath = target_path / new_name
                                                if str(new_filepath).lower() not in seen_target_paths:
                                                    filepath = new_filepath
                                                    target_key = str(new_filepath).lower()
                                                    break
                                                counter += 1
                                                
                                        seen_target_paths.add(target_key)
                                        log_debug(f"Module file tracked: {filepath.name} (ID: {file_obj.id})", debug_file)
                                        task = asyncio.create_task(self._download_file_async(
                                            sem, session, file_obj, target_path, progress_callback, mb_tracker, file_filter, 
                                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file,
                                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath
                                        ))
                                        tasks.append(task)
                                    
                                    elif item.type == 'Page':
                                        if file_filter == 'study': continue
                                        if not hasattr(item, 'page_url') or not item.page_url:
                                            # Error
                                            err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing Page URL", "Page has no URL")
                                            if progress_callback: progress_callback(err, progress_type='error')
                                            self._log_error(save_dir, err)
                                            continue
                                        
                                        page_obj = course.get_page(item.page_url)
                                        filepath = self._save_page(page_obj, target_path, progress_callback, error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file, sync_manager=sync_manager, course_base_path=base_path, canvas_item_id=-int(item.id) if hasattr(item, 'id') else 0)
                                        if filepath and filepath.exists():
                                            info = CanvasFileInfo(
                                                id=-int(item.id) if hasattr(item, 'id') else 0,
                                                filename=filepath.name,
                                                display_name=getattr(page_obj, 'title', filepath.name),
                                                size=0,
                                                modified_at=getattr(page_obj, 'updated_at', datetime.now(timezone.utc).isoformat()),
                                                url=getattr(item, 'html_url', ''),
                                                content_type="text/html"
                                            )
                                            downloaded_files_info.append((info, filepath))
                                    
                                    elif item.type == 'ExternalUrl':
                                        if file_filter == 'study': continue
                                        if not hasattr(item, 'external_url') or not item.external_url:
                                             # Error
                                             err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing External URL", "Link has no URL")
                                             if progress_callback: progress_callback(err, progress_type='error')
                                             self._log_error(save_dir, err)
                                             continue
                                        filepath = self._create_link(item.title, item.external_url, target_path, progress_callback, error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file, sync_manager=sync_manager, course_base_path=base_path, canvas_item_id=-int(item.id) if hasattr(item, 'id') else 0)
                                        if filepath and filepath.exists():
                                            info = CanvasFileInfo(
                                                id=-int(item.id) if hasattr(item, 'id') else 0,
                                                filename=filepath.name,
                                                display_name=item.title,
                                                size=0,
                                                modified_at=datetime.now(timezone.utc).isoformat(),
                                                url=getattr(item, 'external_url', ''),
                                                content_type="application/x-url"
                                            )
                                            downloaded_files_info.append((info, filepath))
                                    
                                    elif item.type == 'ExternalTool':
                                        if file_filter == 'study': continue
                                        url = getattr(item, 'html_url', None) or getattr(item, 'external_url', None)
                                        if not url:
                                             err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing Tool URL", "External Tool missing launch URL")
                                             if progress_callback: progress_callback(err, progress_type='error')
                                             self._log_error(save_dir, err)
                                             continue
                                        filepath = self._create_link(item.title, url, target_path, progress_callback, error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file, sync_manager=sync_manager, course_base_path=base_path, canvas_item_id=-int(item.id) if hasattr(item, 'id') else 0)
                                        if filepath and filepath.exists():
                                            info = CanvasFileInfo(
                                                id=-int(item.id) if hasattr(item, 'id') else 0,
                                                filename=filepath.name,
                                                display_name=item.title,
                                                size=0,
                                                modified_at=datetime.now(timezone.utc).isoformat(),
                                                url=url,
                                                content_type="application/x-url"
                                            )
                                            downloaded_files_info.append((info, filepath))

                                    # --- Secondary Content: Module-aware dispatch ---
                                    elif item.type == 'Assignment':
                                        if secondary_content_settings and secondary_content_settings.get('download_assignments'):
                                            if hasattr(item, 'content_id') and item.content_id:
                                                try:
                                                    isolate = secondary_content_settings.get('isolate_secondary_content', True)
                                                    assignment = course.get_assignment(item.content_id)
                                                    a_id = getattr(assignment, 'id', 0)
                                                    a_name = getattr(assignment, 'name', 'Untitled Assignment')
                                                    description = getattr(assignment, 'description', '') or ''
                                                    updated_at = getattr(assignment, 'updated_at', '') or ''

                                                    attachments = []
                                                    try:
                                                        raw_att = getattr(assignment, 'attachments', None)
                                                        if raw_att and isinstance(raw_att, list):
                                                            attachments = raw_att
                                                    except Exception:
                                                        pass

                                                    metadata = [
                                                        ('Due', getattr(assignment, 'due_at', None)),
                                                        ('Points', getattr(assignment, 'points_possible', None)),
                                                    ]
                                                    module_target = target_path if not isolate else None
                                                    self._save_secondary_entity(
                                                        'assignment', a_name, description, base_path,
                                                        course_base_path=base_path, sync_manager=sync_manager,
                                                        canvas_entity_id=a_id, canvas_updated_at=updated_at,
                                                        progress_callback=progress_callback,
                                                        debug_file=debug_file,
                                                        error_root_path=Path(save_dir),
                                                        course_name=course.name,
                                                        module_path=module_target, isolate=isolate,
                                                        has_attachments=bool(attachments),
                                                        metadata_pairs=metadata,
                                                    )
                                                    module_handled_ids.add(a_id)
                                                except Exception as ae:
                                                    log_debug(f"Module Assignment dispatch error: {ae}", debug_file)

                                    elif item.type == 'Quiz':
                                        if secondary_content_settings and secondary_content_settings.get('download_quizzes'):
                                            if hasattr(item, 'content_id') and item.content_id:
                                                try:
                                                    isolate = secondary_content_settings.get('isolate_secondary_content', True)
                                                    quiz = course.get_quiz(item.content_id)
                                                    q_id = getattr(quiz, 'id', 0)
                                                    q_title = getattr(quiz, 'title', 'Untitled Quiz')
                                                    q_desc = getattr(quiz, 'description', '') or ''
                                                    updated_at = getattr(quiz, 'updated_at', '') or ''

                                                    metadata = [
                                                        ('Points', getattr(quiz, 'points_possible', None)),
                                                        ('Due', getattr(quiz, 'due_at', None)),
                                                    ]
                                                    module_target = target_path if not isolate else None
                                                    self._save_secondary_entity(
                                                        'quiz', q_title, q_desc, base_path,
                                                        course_base_path=base_path, sync_manager=sync_manager,
                                                        canvas_entity_id=q_id, canvas_updated_at=updated_at,
                                                        progress_callback=progress_callback,
                                                        debug_file=debug_file,
                                                        error_root_path=Path(save_dir),
                                                        course_name=course.name,
                                                        module_path=module_target, isolate=isolate,
                                                        has_attachments=False,
                                                        metadata_pairs=metadata,
                                                    )
                                                    module_handled_ids.add(q_id)
                                                except Exception as qe:
                                                    log_debug(f"Module Quiz dispatch error: {qe}", debug_file)

                                    elif item.type == 'Discussion':
                                        if secondary_content_settings and secondary_content_settings.get('download_discussions'):
                                            if hasattr(item, 'content_id') and item.content_id:
                                                try:
                                                    isolate = secondary_content_settings.get('isolate_secondary_content', True)
                                                    topic = course.get_discussion_topic(item.content_id)
                                                    t_id = getattr(topic, 'id', 0)
                                                    title = getattr(topic, 'title', 'Untitled Discussion')
                                                    message = getattr(topic, 'message', '') or ''
                                                    updated_at = (getattr(topic, 'last_reply_at', '')
                                                                  or getattr(topic, 'updated_at', '') or '')

                                                    metadata = [
                                                        ('Posted', getattr(topic, 'posted_at', None)),
                                                        ('Replies', getattr(topic, 'discussion_subentry_count', None)),
                                                    ]
                                                    module_target = target_path if not isolate else None
                                                    self._save_secondary_entity(
                                                        'discussion', title, message, base_path,
                                                        course_base_path=base_path, sync_manager=sync_manager,
                                                        canvas_entity_id=t_id, canvas_updated_at=updated_at,
                                                        progress_callback=progress_callback,
                                                        debug_file=debug_file,
                                                        error_root_path=Path(save_dir),
                                                        course_name=course.name,
                                                        module_path=module_target, isolate=isolate,
                                                        has_attachments=False,
                                                        metadata_pairs=metadata,
                                                    )
                                                    module_handled_ids.add(t_id)
                                                except Exception as de:
                                                    log_debug(f"Module Discussion dispatch error: {de}", debug_file)
                                        
                                except Exception as item_e:
                                    err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Item Processing Error", str(item_e), raw_error=item_e)
                                    if progress_callback: progress_callback(err, progress_type='error')
                                    self._log_error(save_dir, err)

                        except Exception as module_e:
                             err = DownloadError(course.name, getattr(module, 'name', 'unknown'), "Module Error", str(module_e), raw_error=module_e)
                             if progress_callback: progress_callback(err, progress_type='error')
                             self._log_error(save_dir, err)
                             
                # Wait for file downloads
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            err = DownloadError(course.name, "File Task", "Async Error", str(result), raw_error=result)
                            if progress_callback: progress_callback(err, progress_type='error')
                            self._log_error(save_dir, err)
                        elif result:
                            downloaded_files_info.append(result)


                # ---- HYBRID MODE CATCH-ALL STARTED ----
                try:
                    log_debug("Starting Catch-All Phase for non-module files...", debug_file)
                    if progress_callback: progress_callback('Scanning remaining files...', progress_type='log')
                    
                    all_files = course.get_files()
                    all_files = list(all_files)
                    catch_all_tasks = []

                    for file in all_files:
                        if check_cancellation and check_cancellation(): break
                        
                        if file.id in downloaded_file_ids:
                            log_debug(f"Catch-All skipping module file: {file.filename} (ID: {file.id})", debug_file)
                            continue # Already downloaded in a module
                        
                        # Synchronous conflict resolution to prevent data loss
                        base_filename = self._sanitize_filename(getattr(file, 'filename', 'unknown'))
                        filepath = base_path / base_filename
                        target_key = str(filepath).lower()

                        if target_key in seen_target_paths:
                            counter = 1
                            while True:
                                new_name = f"{filepath.stem} ({counter}){filepath.suffix}"
                                new_filepath = base_path / new_name
                                if str(new_filepath).lower() not in seen_target_paths:
                                    filepath = new_filepath
                                    target_key = str(new_filepath).lower()
                                    break
                                counter += 1
                                
                        seen_target_paths.add(target_key)
                        log_debug(f"Catch-All found new file: {filepath.name} (ID: {file.id})", debug_file)
                        
                        # Download to course root
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, file, base_path, progress_callback, mb_tracker, file_filter, 
                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath
                        ))
                        catch_all_tasks.append(task)
                    
                    if catch_all_tasks:
                        log_debug(f"Downloading {len(catch_all_tasks)} catch-all files...", debug_file)
                        results = await asyncio.gather(*catch_all_tasks, return_exceptions=True)
                        for result in results:
                            if isinstance(result, Exception):
                                err = DownloadError(course.name, "Catch-All Task", "Async Error", str(result), raw_error=result)
                                if progress_callback: progress_callback(err, progress_type='error')
                                self._log_error(save_dir, err)
                            elif result:
                                downloaded_files_info.append(result)

                    else:
                        log_debug("No partial/non-module files found.", debug_file)

                except Exception as e:
                    log_debug(f"Catch-All Phase Error: {e}", debug_file)
                    error_msg = str(e).lower()
                    if "unauthorized" in error_msg or "401" in error_msg or "user not authorised" in error_msg:
                        # Just log it to standard console/debug, DO NOT add to user's download_errors.txt
                        print(f"Files tab restricted for {course.name}. Gracefully falling back to module scan.")
                    else:
                        # Handle actual unexpected errors
                        err = DownloadError(course.name, "Catch-All Scan", "Hybrid Mode Error", str(e), raw_error=e)
                        self._log_error(save_dir, err)
                # ---- HYBRID MODE CATCH-ALL ENDED ----

                # ---- SECONDARY CONTENT DOWNLOAD ----
                if secondary_content_settings and any(
                    secondary_content_settings.get(k)
                    for k in SECONDARY_CONTENT_DEFAULTS
                    if k.startswith('download_')
                ):
                    try:
                        await self._download_secondary_content(
                            course, base_path, sem, session,
                            progress_callback, mb_tracker, check_cancellation,
                            secondary_content_settings, Path(save_dir),
                            debug_file, sync_manager, module_handled_ids,
                        )
                    except Exception as sec_e:
                        err = DownloadError(
                            course.name, "Secondary Content",
                            "Secondary Content Error", str(sec_e),
                            raw_error=sec_e,
                        )
                        if progress_callback:
                            progress_callback(err, progress_type='error')
                        self._log_error(save_dir, err)
                # ---- SECONDARY CONTENT DOWNLOAD ENDED ----

            except Exception as e:
                 is_unauthorized = "unauthorized" in str(e).lower() or (hasattr(e, 'status_code') and e.status_code == 401)
                 if is_unauthorized and mode != 'flat':
                     # Fallback to flat
                     msg = 'Modules tab is hidden/unauthorized. Attempting to download files directly...'
                     if progress_callback: progress_callback(msg, progress_type='log')
                     # Log the partial failure
                     err = DownloadError(course.name, "Modules Access", "401 Unauthorized", "Modules locked, falling back to file scan.", raw_error=e)
                     self._log_error(save_dir, err)
                     
                     downloaded_files_info.extend(await self._download_flat_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter, error_root_path=Path(save_dir), debug_file=debug_file, sync_manager=sync_manager))
                 else:
                     err = DownloadError(course.name, "Course Download", "Processing Error", str(e), raw_error=e)
                     if progress_callback: progress_callback(err, progress_type='error')
                     self._log_error(save_dir, err)
            
            # --- Sync Run #0: Save the download mode and sync contract ---
            try:
                sync_manager._save_metadata('download_mode', mode)
                # Save the full "Sync Contract" — all settings used during this download
                if post_processing_settings:
                    import json
                    sync_manager._save_metadata('sync_contract', json.dumps(post_processing_settings))
                # Save the secondary content contract
                if secondary_content_settings:
                    import json
                    sync_manager._save_metadata('secondary_content_contract', json.dumps(secondary_content_settings))
            except Exception as e:
                log_debug(f"Warning: Could not save sync metadata: {e}", debug_file)


    async def _download_folders_async(self, course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter='all', error_root_path=None, debug_file=None, sync_manager=None):
        """Downloads files preserving actual folder structure."""
        tasks = []
        downloaded = []
        folder_map = {}
        log_debug(f"Starting Folders Download for {course.name}", debug_file)

        # 1. Fetch Folders
        try:
            if progress_callback: progress_callback('Fetching folder structure...')
            all_folders = course.get_folders()
            for folder in all_folders:
                full_name = getattr(folder, 'full_name', '')
                if full_name.startswith("course files"):
                    rel_path = full_name[len("course files"):].strip('/')
                else:
                    rel_path = full_name
                folder_map[folder.id] = rel_path
            log_debug(f"Mapped {len(folder_map)} folders.", debug_file)
        except Exception as e:
            err = DownloadError(course.name, "Folder Structure", "Fetch Error", f"Could not fetch folders: {e}", raw_error=e)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            # Continue to allow flat file download if possible?
            # If folder fetch failed, likely file fetch will too, but let's try.

        # 2. Fetch and Download Files
        try:
            if progress_callback: progress_callback('Fetching file list...')
            files = course.get_files()
            files = list(files)
            
            for file in files:
                if check_cancellation and check_cancellation(): break
                try:
                    # Calculate path
                    folder_id = getattr(file, 'folder_id', None)
                    rel_folder_path = folder_map.get(folder_id, "")
                    path_parts = [self._sanitize_filename(p) for p in rel_folder_path.split('/') if p]
                    target_path = base_path
                    for part in path_parts:
                        target_path = target_path / part
                    Path(make_long_path(target_path)).mkdir(parents=True, exist_ok=True)
                    
                    task = asyncio.create_task(self._download_file_async(
                        sem, session, file, target_path, progress_callback, mb_tracker, file_filter, 
                        error_root_path=error_root_path, course_name=course.name, debug_file=debug_file,
                        sync_manager=sync_manager, course_base_path=base_path
                    ))
                    tasks.append(task)
                except Exception as e:
                    err = DownloadError(course.name, getattr(file, 'filename', 'unknown'), "Queue Error", str(e), raw_error=e)
                    if progress_callback: progress_callback(err, progress_type='error')
                    self._log_error(error_root_path, err)
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        err = DownloadError(course.name, "File Task", "Async Error", str(result), raw_error=result)
                        if progress_callback: progress_callback(err, progress_type='error')
                        self._log_error(error_root_path, err)
                    elif result:
                        downloaded.append(result)


        except Exception as e:
            err = DownloadError(course.name, "File List", "Fetch Error", str(e), raw_error=e)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
        
        return downloaded

    async def _download_flat_async(self, course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter='all', error_root_path=None, debug_file=None, sync_manager=None):
        """Downloads all files to the root folder."""
        tasks = []
        downloaded = []
        log_debug(f"Starting Flat Download for {course.name}", debug_file)
        files_access_failed = False
        
        try:
            files = None
            for attempt in range(3):
                try:
                    files = course.get_files()
                    files = list(files) 
                    break
                except Exception as e:
                    if attempt < 2:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    else:
                        files_access_failed = True
                        files = []
                        # Log warning
                        if progress_callback: progress_callback(f"Files tab restricted, trying modules...", progress_type='log')
                        log_debug("Files tab restricted (401?), falling back to module scan.", debug_file)

            downloaded_ids = set()
            seen_flat_paths = set()  # Path-based dedup for flat mode
            for file in files:
                if check_cancellation and check_cancellation(): break
                if getattr(file, 'id', None):
                    downloaded_ids.add(file.id)
                
                # Synchronous conflict resolution to prevent data loss
                base_filename = self._sanitize_filename(getattr(file, 'filename', 'unknown'))
                filepath = base_path / base_filename
                target_key = str(filepath).lower()

                if target_key in seen_flat_paths:
                    counter = 1
                    while True:
                        new_name = f"{filepath.stem} ({counter}){filepath.suffix}"
                        new_filepath = base_path / new_name
                        if str(new_filepath).lower() not in seen_flat_paths:
                            filepath = new_filepath
                            target_key = str(new_filepath).lower()
                            break
                        counter += 1

                seen_flat_paths.add(target_key)
                try:
                    task = asyncio.create_task(self._download_file_async(
                        sem, session, file, base_path, progress_callback, mb_tracker, file_filter, 
                        error_root_path=error_root_path, course_name=course.name, debug_file=debug_file,
                        sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath
                    ))
                    tasks.append(task)
                except Exception as e:
                    err = DownloadError(course.name, getattr(file, 'filename', 'unknown'), "Queue Error", str(e), raw_error=e)
                    if progress_callback: progress_callback(err, progress_type='error')
                    self._log_error(error_root_path, err)

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        err = DownloadError(course.name, "File Task", "Async Error", str(result), raw_error=result)
                        if progress_callback: progress_callback(err, progress_type='error')
                        self._log_error(error_root_path, err)
                    elif result:
                        downloaded.append(result)

            # Module Scan Fallback
            module_tasks = []
            try:
                modules = course.get_modules()
                for module in modules:
                    if check_cancellation and check_cancellation(): break
                    items = list(module.get_module_items())
                    log_debug(f"Fallback Scan: Module {module.name} (found {len(items)} items)", debug_file)
                    for item in items:
                        if check_cancellation and check_cancellation(): break
                        
                        if item.type == 'File' and hasattr(item, 'content_id') and item.content_id in downloaded_ids: continue

                        try:
                            log_debug(f"  Fallback Item: {getattr(item, 'title', 'unknown')} (Type: {getattr(item, 'type', 'unknown')})", debug_file)
                            if item.type == 'File':
                                if not hasattr(item, 'content_id') or not item.content_id: continue
                                file_obj = course.get_file(item.content_id)
                                # Synchronous conflict resolution to prevent data loss
                                base_filename = self._sanitize_filename(getattr(file_obj, 'filename', 'unknown'))
                                filepath = base_path / base_filename
                                target_key = str(filepath).lower()

                                if target_key in seen_flat_paths:
                                    counter = 1
                                    while True:
                                        new_name = f"{filepath.stem} ({counter}){filepath.suffix}"
                                        new_filepath = base_path / new_name
                                        if str(new_filepath).lower() not in seen_flat_paths:
                                            filepath = new_filepath
                                            target_key = str(new_filepath).lower()
                                            break
                                        counter += 1

                                seen_flat_paths.add(target_key)
                                task = asyncio.create_task(self._download_file_async(
                                    sem, session, file_obj, base_path, progress_callback, mb_tracker, file_filter, 
                                    error_root_path=error_root_path, course_name=course.name, debug_file=debug_file,
                                    sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath
                                ))
                                module_tasks.append(task)
                            elif item.type == 'Page':
                                if file_filter == 'study': continue
                                if not hasattr(item, 'page_url') or not item.page_url: continue
                                page_obj = course.get_page(item.page_url)
                                filepath = self._save_page(page_obj, base_path, progress_callback, error_root_path=error_root_path, course_name=course.name, debug_file=debug_file, sync_manager=sync_manager, course_base_path=base_path, canvas_item_id=-int(item.id) if hasattr(item, 'id') else 0)
                                if filepath and filepath.exists():
                                    info = CanvasFileInfo(
                                        id=-int(item.id) if hasattr(item, 'id') else 0,
                                        filename=filepath.name,
                                        display_name=getattr(page_obj, 'title', filepath.name),
                                        size=0,
                                        modified_at=getattr(page_obj, 'updated_at', datetime.now(timezone.utc).isoformat()),
                                        url=getattr(item, 'html_url', ''),
                                        content_type="text/html"
                                    )
                                    downloaded.append((info, filepath))
                            elif item.type in ['ExternalUrl', 'ExternalTool']:
                                if file_filter == 'study': continue
                                url = getattr(item, 'external_url', None)
                                if item.type == 'ExternalTool':
                                     url = getattr(item, 'html_url', None) or url
                                if url:
                                    filepath = self._create_link(item.title, url, base_path, progress_callback, error_root_path=error_root_path, course_name=course.name, debug_file=debug_file, sync_manager=sync_manager, course_base_path=base_path, canvas_item_id=-int(item.id) if hasattr(item, 'id') else 0)
                                    if filepath and filepath.exists():
                                        info = CanvasFileInfo(
                                            id=-int(item.id) if hasattr(item, 'id') else 0,
                                            filename=filepath.name,
                                            display_name=item.title,
                                            size=0,
                                            modified_at=datetime.now(timezone.utc).isoformat(),
                                            url=url,
                                            content_type="application/x-url"
                                        )
                                        downloaded.append((info, filepath))
                        except Exception as e:
                             log_debug(f"Fallback scan item error: {getattr(item, 'title', 'unknown')}: {e}", debug_file)

                if module_tasks:
                   module_results = await asyncio.gather(*module_tasks, return_exceptions=True)
                   for result in module_results:
                       if isinstance(result, Exception):
                           err = DownloadError(course.name, "Fallback File Task", "Async Error", str(result), raw_error=result)
                           if progress_callback: progress_callback(err, progress_type='error')
                           self._log_error(error_root_path, err)
                       elif result:
                           downloaded.append(result)

            except Exception as e:
                log_debug(f"Fallback module scan failed: {e}", debug_file)

        except Exception as e:
             err = DownloadError(course.name, "Flat Download", "Fatal Error", str(e), raw_error=e)
             if progress_callback: progress_callback(err, progress_type='error')
             self._log_error(error_root_path, err)
        
        return downloaded

    async def _download_file_async(self, sem, session, file_obj, folder_path, progress_callback, mb_tracker=None, file_filter='all', error_root_path=None, course_name="Unknown", debug_file=None, sync_manager=None, course_base_path=None, explicit_filepath=None):
        async with sem:
            if explicit_filepath:
                filepath = explicit_filepath
                filename = filepath.name
            else:
                filename = self._sanitize_filename(getattr(file_obj, 'filename', 'unknown'))
                filepath = folder_path / filename

            if file_filter == 'study':
                ext = filepath.suffix.lower()
                if ext not in ['.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx']:
                    return

            # Check duplication by size
            file_size_bytes = getattr(file_obj, 'size', 0)
            if filepath.exists():
                try:
                    # We only skip if size matches. If size differs, we overwrite (update).
                    if file_size_bytes > 0 and filepath.stat().st_size == file_size_bytes:
                        log_debug(f"Skipping existing file: {filename}", debug_file)
                        # User Request: Remove skipped files from Total MB count (they don't need downloading)
                        if progress_callback:
                             progress_callback("", progress_type='skipped', file_size=file_size_bytes)
                        # Sync Run #0: Record skipped-but-existing files to the DB
                        if sync_manager and course_base_path:
                            try:
                                rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                                sync_manager.record_downloaded_file(
                                    canvas_file_id=file_obj.id,
                                    canvas_filename=getattr(file_obj, 'filename', ''),
                                    local_relative_path=rel_path,
                                    canvas_updated_at=getattr(file_obj, 'modified_at', None) or '',
                                    original_size=file_size_bytes
                                )
                            except Exception:
                                pass  # Non-fatal: don't break download for DB issues
                        return (
                            CanvasFileInfo(
                                id=file_obj.id,
                                filename=getattr(file_obj, 'filename', ''),
                                display_name=getattr(file_obj, 'display_name', getattr(file_obj, 'filename', '')),
                                size=getattr(file_obj, 'size', 0),
                                modified_at=getattr(file_obj, 'modified_at', None),
                                md5=getattr(file_obj, 'md5', None),
                                url=getattr(file_obj, 'url', ''),
                                content_type=getattr(file_obj, 'content-type', ''),
                                folder_id=getattr(file_obj, 'folder_id', None)
                            ), filepath
                        ) # Skip
                    else:
                        log_debug(f"File exists but size mismatch. Canvas: {file_size_bytes}, Local: {filepath.stat().st_size}. Re-downloading.", debug_file)
                except Exception:
                    pass

            # Only run disk-conflict resolution when the caller hasn't already
            # resolved naming via seen_flat_paths / seen_target_paths.
            if not explicit_filepath:
                filepath = self._handle_conflict(filepath)

            url = file_obj.url
            if not url:
                # Check for LTI/Media streams
                ext_lower = filepath.suffix.lower()
                media_exts = ['.mp4', '.mov', '.avi', '.mkv', '.mp3']
                if ext_lower in media_exts:
                    err = DownloadError(course_name, filename, "LTI/Media Stream", "This video is streamed via a Canvas plugin (e.g., Panopto/Studio) and cannot be directly downloaded.")
                else:
                    err = DownloadError(course_name, filename, "No URL", "File object has no URL")
                    
                if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                self._log_error(error_root_path, err)
                return

            # aiofiles is imported at module level; reference is used below

            for attempt in range(MAX_RETRIES):
                try:
                    log_debug(f"Requesting URL: {url} (Attempt {attempt+1})", debug_file)
                    async with session.get(url) as response:
                        log_debug(f"Response Status: {response.status} Content-Type: {response.headers.get('Content-Type', 'unknown')}", debug_file)
                        if response.status == 200:
                            # --- Atomic .part Pattern ---
                            import streamlit as st  # Deferred: keeps canvas_logic reusable without Streamlit
                            part_path = filepath.parent / (filepath.name + '.part')
                            download_interrupted = False
                            
                            try:
                                async with aiofiles.open(make_long_path(part_path), 'wb') as f:
                                    total_bytes = 0
                                    while True:
                                        # Instant cancel check INSIDE the chunk loop
                                        if st.session_state.get('cancel_requested', False) or st.session_state.get('download_cancelled', False):
                                            download_interrupted = True
                                            break
                                        
                                        chunk = await response.content.read(1024*1024)
                                        if not chunk: break
                                        await f.write(chunk)
                                        total_bytes += len(chunk)
                                        
                                        if mb_tracker:
                                            mb_tracker['bytes_downloaded'] += len(chunk)
                                            if progress_callback:
                                                mb_down = mb_tracker['bytes_downloaded'] / (1024 * 1024)
                                                progress_callback("", progress_type='mb_progress', mb_downloaded=mb_down)
                            except Exception as write_err:
                                download_interrupted = True
                                # Clean up .part file on write error
                                try:
                                    if Path(make_long_path(part_path)).exists():
                                        Path(make_long_path(part_path)).unlink()
                                except OSError:
                                    pass
                                raise write_err
                            
                            # Handle interrupted download: delete partial .part file
                            if download_interrupted:
                                try:
                                    if Path(make_long_path(part_path)).exists():
                                        Path(make_long_path(part_path)).unlink()
                                        log_debug(f"Cancelled: deleted partial {part_path.name}", debug_file)
                                except OSError:
                                    pass
                                return  # Cancel — do not return file info
                            
                            # Verify download completeness BEFORE rename
                            if file_size_bytes > 0 and total_bytes != file_size_bytes:
                                flexible_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.mp3', '.m4v']
                                is_flexible_media = any(filename.lower().endswith(ext) for ext in flexible_extensions)
                                
                                if is_flexible_media and total_bytes > 0:
                                    log_debug(f"Soft Warning: {filename} size mismatch (Expected {file_size_bytes}, got {total_bytes}). Bypassing for media file.", debug_file)
                                else:
                                    # Incomplete download — delete .part and raise
                                    try:
                                        if Path(make_long_path(part_path)).exists():
                                            Path(make_long_path(part_path)).unlink()
                                    except OSError:
                                        pass
                                    raise Exception(f"File system error: Download incomplete. Expected {file_size_bytes} bytes, got {total_bytes} bytes.")
                            
                            # 100% success: atomic rename .part → final path
                            try:
                                os.rename(make_long_path(part_path), make_long_path(filepath))
                            except OSError:
                                _shutil = shutil  # shutil imported at module level; alias for local clarity
                                try:
                                    _shutil.move(make_long_path(part_path), make_long_path(filepath))
                                except Exception:
                                    # Clean up partial destination file from failed cross-FS copy
                                    try:
                                        if Path(make_long_path(filepath)).exists():
                                            Path(make_long_path(filepath)).unlink()
                                    except OSError:
                                        pass
                                    raise  # Re-raise to trigger retry loop
                            
                            log_debug(f"File Saved: {filepath} ({total_bytes} bytes)", debug_file)
                            
                            # --- Sync Run #0: Record to DB AFTER successful atomic rename ---
                            # This is the safety guard: only fully-downloaded files get recorded.
                            # Cancelled/partial .part files never reach this point.
                            if sync_manager and course_base_path:
                                try:
                                    rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                                    sync_manager.record_downloaded_file(
                                        canvas_file_id=file_obj.id,
                                        canvas_filename=getattr(file_obj, 'filename', ''),
                                        local_relative_path=rel_path,
                                        canvas_updated_at=getattr(file_obj, 'modified_at', None) or '',
                                        original_size=getattr(file_obj, 'size', 0)
                                    )
                                except Exception as db_err:
                                    log_debug(f"Warning: DB record failed for {filename}: {db_err}", debug_file)
                                    # Non-fatal: download succeeded, DB write failed. File is on disk.
                            
                            if progress_callback:
                                progress_callback(f'Downloading file: {filename}', progress_type='download')
                                
                            return (
                                CanvasFileInfo(
                                    id=file_obj.id,
                                    filename=getattr(file_obj, 'filename', ''),
                                    display_name=getattr(file_obj, 'display_name', getattr(file_obj, 'filename', '')),
                                    size=getattr(file_obj, 'size', 0),
                                    modified_at=getattr(file_obj, 'modified_at', None),
                                    md5=getattr(file_obj, 'md5', None),
                                    url=getattr(file_obj, 'url', ''),
                                    content_type=getattr(file_obj, 'content-type', ''),
                                    folder_id=getattr(file_obj, 'folder_id', None)
                                ), filepath
                            )

                        elif response.status == 429: # Rate Limit
                            wait = int(response.headers.get('Retry-After', RETRY_DELAY * (2 ** attempt)))
                            await asyncio.sleep(wait)
                            continue
                        elif 500 <= response.status < 600:
                            await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
                            continue
                        else:
                            err_msg = f"Download failed with status {response.status}"
                            log_debug(f"ERROR: {err_msg}", debug_file)
                            err = DownloadError(course_name, filename, f"HTTP {response.status}", err_msg)
                            if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                            self._log_error(error_root_path, err)
                            return
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
                    else:
                        err = DownloadError(course_name, filename, "Network Error", f"Max retries exceeded: {e}", raw_error=e)
                        if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                        self._log_error(error_root_path, err)
                        return
                except Exception as e:
                    err = DownloadError(course_name, filename, "Write Error", f"File system error: {e}", raw_error=e)
                    if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                    self._log_error(error_root_path, err)
                    return

    # ═══════════════════════════════════════════════════════════════
    # SECONDARY CONTENT ENGINE
    # ═══════════════════════════════════════════════════════════════

    # --- Routing Helpers --------------------------------------------------

    def _resolve_secondary_path(self, entity_type, entity_name, base_path,
                                module_path=None, isolate=True,
                                has_attachments=False):
        """Resolve the target directory and clean/prefixed filename.

        Mode A (isolate=False):
            Uses *module_path* (or course root if flat) and prepends a
            ``"Type: "`` prefix to avoid ambiguity among study files.

        Mode B (isolate=True):
            Creates ``base_path/<Category>/`` and, if the entity has
            attachments, an additional ``<Entity Name>/`` subfolder.

        Returns:
            ``(target_dir: Path, display_name: str)``
        """
        routing = _ENTITY_ROUTING[entity_type]
        safe_name = self._sanitize_filename(entity_name)

        if isolate:
            category_folder = base_path / routing['folder']
            if has_attachments:
                entity_folder = category_folder / safe_name
                entity_folder.mkdir(parents=True, exist_ok=True)
                return entity_folder, safe_name
            else:
                category_folder.mkdir(parents=True, exist_ok=True)
                return category_folder, safe_name
        else:
            target_dir = module_path if module_path else base_path
            target_dir.mkdir(parents=True, exist_ok=True)
            prefixed_name = f"{routing['prefix']}: {safe_name}"
            return target_dir, prefixed_name

    @staticmethod
    def _build_entity_html(title, body_html, metadata_pairs=None):
        """Build a complete HTML document from a title, HTML body, and metadata.

        Parameters
        ----------
        title : str
            Entity title (will be escaped).
        body_html : str | None
            Raw HTML content from Canvas (may be None for empty entities).
        metadata_pairs : list[tuple[str, str]] | None
            ``[(label, value), ...]`` rendered as a header block.
        """
        safe_title = html.escape(title)
        meta_section = ""
        if metadata_pairs:
            items = "".join(
                f"<strong>{html.escape(str(k))}:</strong> {html.escape(str(v))}<br>"
                for k, v in metadata_pairs if v
            )
            if items:
                meta_section = (
                    f'<div style="background:#f5f5f5;padding:10px;'
                    f'margin-bottom:15px;border-radius:5px;">{items}</div>'
                )

        return (
            f"<html><head><title>{safe_title}</title>"
            f"<meta charset=\"utf-8\"></head><body>"
            f"<h1>{safe_title}</h1>{meta_section}<hr>"
            f"{body_html or '<p><em>(No content)</em></p>'}"
            f"</body></html>"
        )

    def _save_secondary_entity(self, entity_type, entity_name, body_html,
                               base_path, course_base_path, sync_manager,
                               canvas_entity_id, canvas_updated_at,
                               progress_callback=None, debug_file=None,
                               error_root_path=None, course_name="Unknown",
                               module_path=None, isolate=True,
                               has_attachments=False, metadata_pairs=None,
                               file_extension=".html"):
        """Unified save-to-disk + DB-record logic for all secondary entities.

        Returns
        -------
        ``(filepath, synthetic_id)`` on success, ``(None, None)`` on failure.
        """
        target_dir, display_name = self._resolve_secondary_path(
            entity_type, entity_name, base_path,
            module_path=module_path, isolate=isolate,
            has_attachments=has_attachments,
        )

        filename = self._sanitize_filename(display_name) + file_extension
        filepath = target_dir / filename
        filepath = self._handle_conflict(filepath)

        content = self._build_entity_html(
            entity_name, body_html, metadata_pairs=metadata_pairs,
        )

        log_debug(f"Saving {entity_type}: {entity_name} -> {filepath}", debug_file)

        try:
            with open(make_long_path(filepath), 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            err = DownloadError(
                course_name, entity_name,
                f"{entity_type.title()} Save Error", str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            return None, None

        # DB record ― synthetic negative ID
        synthetic_id = make_secondary_id(entity_type, canvas_entity_id)
        if sync_manager and course_base_path:
            try:
                rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                sync_manager.record_downloaded_file(
                    canvas_file_id=synthetic_id,
                    canvas_filename=filepath.name,
                    local_relative_path=rel_path,
                    canvas_updated_at=canvas_updated_at or '',
                    original_size=0,
                )
            except Exception:
                pass  # Non-fatal

        if progress_callback:
            progress_callback(
                f'Saving {entity_type}: {entity_name}', progress_type='page',
            )

        return filepath, synthetic_id

    # --- Entity-Specific Fetchers -----------------------------------------

    def _fetch_and_save_assignments(self, course, base_path, sem, session,
                                    progress_callback, mb_tracker,
                                    check_cancellation, settings,
                                    error_root_path, debug_file,
                                    sync_manager, module_handled_ids,
                                    download_tasks):
        """Fetch all assignments for a course and save their HTML bodies.

        Attachments on Canvas Assignments are real Canvas File objects
        ― they are queued for async download using their *true positive*
        ``file.id``, just like any normal course file.
        """
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching assignments...", debug_file)

        try:
            assignments = course.get_assignments()
            for assignment in assignments:
                if check_cancellation and check_cancellation():
                    break

                a_id = getattr(assignment, 'id', 0)
                if a_id in module_handled_ids:
                    continue  # Already saved via module dispatch

                a_name = getattr(assignment, 'name', 'Untitled Assignment')
                description = getattr(assignment, 'description', '') or ''
                updated_at = getattr(assignment, 'updated_at', '') or ''

                # Check for file attachments
                attachments = []
                try:
                    # The canvasapi Assignment may expose .attachments or
                    # we can try assignment submission_types for hints.
                    raw_attachments = getattr(assignment, 'attachments', None)
                    if raw_attachments and isinstance(raw_attachments, list):
                        attachments = raw_attachments
                except Exception:
                    pass

                has_attachments = bool(attachments)
                metadata = [
                    ('Due', getattr(assignment, 'due_at', None)),
                    ('Points', getattr(assignment, 'points_possible', None)),
                    ('Submission Types', ', '.join(
                        getattr(assignment, 'submission_types', []) or []
                    )),
                ]

                filepath, syn_id = self._save_secondary_entity(
                    'assignment', a_name, description, base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=a_id, canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    has_attachments=has_attachments,
                    metadata_pairs=metadata,
                )

                # Queue attachment downloads using their REAL positive IDs
                if filepath and attachments:
                    attach_dir = filepath.parent
                    for att in attachments:
                        att_id = att.get('id')
                        att_url = att.get('url', '')
                        att_filename = att.get('filename', att.get('display_name', 'attachment'))
                        if not att_url or not att_id:
                            continue

                        if not isolate:
                            # Mode A: prefix attachment filename
                            routing = _ENTITY_ROUTING['assignment']
                            att_filename = f"{routing['prefix']}: {self._sanitize_filename(a_name)} - {att_filename}"

                        # Build a mock file object that _download_file_async expects
                        att_file_obj = type('AttachmentObj', (), {
                            'id': att_id,
                            'url': att_url,
                            'filename': att_filename,
                            'display_name': att.get('display_name', att_filename),
                            'size': att.get('size', 0),
                            'modified_at': att.get('modified_at', updated_at),
                            'md5': None,
                            'content-type': att.get('content-type', ''),
                            'folder_id': None,
                        })()

                        att_filepath = attach_dir / self._sanitize_filename(att_filename)
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, att_file_obj, attach_dir,
                            progress_callback, mb_tracker, 'all',
                            error_root_path=error_root_path,
                            course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager,
                            course_base_path=base_path,
                            explicit_filepath=att_filepath,
                        ))
                        download_tasks.append(task)

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Assignments not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Assignments", "Secondary Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_and_save_syllabus(self, course, base_path,
                                 progress_callback, settings,
                                 error_root_path, debug_file,
                                 sync_manager):
        """Fetch the course syllabus_body and save as a single HTML file."""
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching syllabus...", debug_file)

        try:
            # Re-fetch the course object with syllabus_body included
            full_course = self.canvas.get_course(
                course.id, include=['syllabus_body'],
            )
            syllabus_body = getattr(full_course, 'syllabus_body', None)

            if not syllabus_body:
                log_debug("Syllabus body is empty, skipping.", debug_file)
                return

            updated_at = getattr(full_course, 'updated_at', '') or ''

            self._save_secondary_entity(
                'syllabus', 'Syllabus', syllabus_body, base_path,
                course_base_path=base_path, sync_manager=sync_manager,
                canvas_entity_id=course.id, canvas_updated_at=updated_at,
                progress_callback=progress_callback,
                debug_file=debug_file,
                error_root_path=error_root_path,
                course_name=course.name, isolate=isolate,
                has_attachments=False,
                metadata_pairs=[
                    ('Course', getattr(course, 'name', '')),
                    ('Course Code', getattr(full_course, 'course_code', '')),
                ],
            )

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Syllabus not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Syllabus", "Secondary Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_and_save_announcements(self, course, base_path, sem, session,
                                      progress_callback, mb_tracker,
                                      check_cancellation, settings,
                                      error_root_path, debug_file,
                                      sync_manager, download_tasks):
        """Fetch course announcements and save each as an HTML file.

        Attachments on announcements are real Canvas File objects and are
        queued for download using their true positive IDs.
        """
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching announcements...", debug_file)

        try:
            topics = course.get_discussion_topics(only_announcements=True)
            for topic in topics:
                if check_cancellation and check_cancellation():
                    break

                t_id = getattr(topic, 'id', 0)
                title = getattr(topic, 'title', 'Untitled Announcement')
                message = getattr(topic, 'message', '') or ''
                posted_at = getattr(topic, 'posted_at', '') or ''
                updated_at = posted_at  # Announcements rarely get edited

                # Date-prefix for chronological file ordering
                date_prefix = ''
                if posted_at:
                    try:
                        dt = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
                        date_prefix = dt.strftime('%Y-%m-%d') + ' - '
                    except (ValueError, TypeError):
                        pass

                # Check for attachments
                attachments = []
                try:
                    raw = getattr(topic, 'attachments', None)
                    if raw and isinstance(raw, list):
                        attachments = raw
                except Exception:
                    pass

                has_attachments = bool(attachments)
                display_name = f"{date_prefix}{title}"

                filepath, syn_id = self._save_secondary_entity(
                    'announcement', display_name, message, base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=t_id, canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    has_attachments=has_attachments,
                    metadata_pairs=[
                        ('Posted', posted_at),
                        ('Author', getattr(topic, 'user_name', None)
                                   or getattr(topic, 'author', {}).get('display_name', None)),
                    ],
                )

                # Queue attachment downloads with REAL positive IDs
                if filepath and attachments:
                    attach_dir = filepath.parent
                    for att in attachments:
                        att_id = att.get('id')
                        att_url = att.get('url', '')
                        att_filename = att.get('filename', att.get('display_name', 'attachment'))
                        if not att_url or not att_id:
                            continue

                        if not isolate:
                            routing = _ENTITY_ROUTING['announcement']
                            att_filename = f"{routing['prefix']}: {self._sanitize_filename(display_name)} - {att_filename}"

                        att_file_obj = type('AttachmentObj', (), {
                            'id': att_id,
                            'url': att_url,
                            'filename': att_filename,
                            'display_name': att.get('display_name', att_filename),
                            'size': att.get('size', 0),
                            'modified_at': att.get('modified_at', updated_at),
                            'md5': None,
                            'content-type': att.get('content-type', ''),
                            'folder_id': None,
                        })()

                        att_filepath = attach_dir / self._sanitize_filename(att_filename)
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, att_file_obj, attach_dir,
                            progress_callback, mb_tracker, 'all',
                            error_root_path=error_root_path,
                            course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager,
                            course_base_path=base_path,
                            explicit_filepath=att_filepath,
                        ))
                        download_tasks.append(task)

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Announcements not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Announcements", "Secondary Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_and_save_discussions(self, course, base_path,
                                    progress_callback, check_cancellation,
                                    settings, error_root_path, debug_file,
                                    sync_manager, module_handled_ids):
        """Fetch non-announcement discussion topics and save as HTML."""
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching discussions...", debug_file)

        try:
            topics = course.get_discussion_topics()
            for topic in topics:
                if check_cancellation and check_cancellation():
                    break

                t_id = getattr(topic, 'id', 0)
                if t_id in module_handled_ids:
                    continue

                # Skip announcements (they have is_announcement=True)
                if getattr(topic, 'is_announcement', False):
                    continue

                title = getattr(topic, 'title', 'Untitled Discussion')
                message = getattr(topic, 'message', '') or ''
                updated_at = (getattr(topic, 'last_reply_at', '')
                              or getattr(topic, 'updated_at', '')
                              or '')

                self._save_secondary_entity(
                    'discussion', title, message, base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=t_id, canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    has_attachments=False,
                    metadata_pairs=[
                        ('Posted', getattr(topic, 'posted_at', None)),
                        ('Replies', getattr(topic, 'discussion_subentry_count', None)),
                        ('Author', getattr(topic, 'user_name', None)
                                   or getattr(topic, 'author', {}).get('display_name', None)),
                    ],
                )

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Discussions not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Discussions", "Secondary Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_and_save_quizzes(self, course, base_path,
                                progress_callback, check_cancellation,
                                settings, error_root_path, debug_file,
                                sync_manager, module_handled_ids):
        """Fetch Classic Quizzes and serialise questions into structured HTML."""
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching quizzes...", debug_file)

        try:
            quizzes = course.get_quizzes()
            for quiz in quizzes:
                if check_cancellation and check_cancellation():
                    break

                q_id = getattr(quiz, 'id', 0)
                if q_id in module_handled_ids:
                    continue

                q_title = getattr(quiz, 'title', 'Untitled Quiz')
                q_description = getattr(quiz, 'description', '') or ''
                updated_at = getattr(quiz, 'updated_at', '') or ''

                # Try to fetch questions (may 403 for students)
                questions_html = ''
                try:
                    questions = quiz.get_questions()
                    q_num = 0
                    for q in questions:
                        q_num += 1
                        q_name = getattr(q, 'question_name', f'Question {q_num}')
                        q_text = getattr(q, 'question_text', '') or ''
                        q_type = getattr(q, 'question_type', 'unknown')

                        questions_html += (
                            f'<div style="margin:15px 0;padding:10px;'
                            f'border:1px solid #ddd;border-radius:5px;">'
                            f'<h3>Q{q_num}: {html.escape(q_name)}</h3>'
                            f'<p style="color:#666;font-size:0.85em;">'
                            f'Type: {html.escape(q_type)}</p>'
                            f'{q_text}'
                            f'</div>'
                        )

                        # Render answers if available
                        answers = getattr(q, 'answers', None)
                        if answers and isinstance(answers, list):
                            answers_html = '<ul>'
                            for ans in answers:
                                ans_text = ans.get('text', '') or ans.get('html', '') or ''
                                answers_html += f'<li>{ans_text}</li>'
                            answers_html += '</ul>'
                            questions_html += answers_html

                except (Unauthorized, ResourceDoesNotExist):
                    questions_html = (
                        '<p><em>Quiz questions are not accessible. '
                        'The quiz may be locked or unpublished.</em></p>'
                    )
                except Exception as qe:
                    log_debug(f"Could not fetch questions for quiz {q_id}: {qe}", debug_file)
                    questions_html = (
                        '<p><em>Could not load quiz questions.</em></p>'
                    )

                # Combine description + questions
                full_body = q_description
                if questions_html:
                    full_body += '<h2>Questions</h2>' + questions_html

                self._save_secondary_entity(
                    'quiz', q_title, full_body, base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=q_id, canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    has_attachments=False,
                    metadata_pairs=[
                        ('Points', getattr(quiz, 'points_possible', None)),
                        ('Time Limit', f"{getattr(quiz, 'time_limit', '∞')} min"),
                        ('Due', getattr(quiz, 'due_at', None)),
                        ('Allowed Attempts', getattr(quiz, 'allowed_attempts', None)),
                    ],
                )

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Quizzes not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Quizzes", "Secondary Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_and_save_rubrics(self, course, base_path,
                                progress_callback, check_cancellation,
                                settings, error_root_path, debug_file,
                                sync_manager):
        """Fetch rubrics and serialise as Markdown tables."""
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching rubrics...", debug_file)

        try:
            rubrics = course.get_rubrics()
            for rubric in rubrics:
                if check_cancellation and check_cancellation():
                    break

                r_id = getattr(rubric, 'id', 0)
                r_title = getattr(rubric, 'title', 'Untitled Rubric')
                r_description = getattr(rubric, 'description', '') or ''
                updated_at = getattr(rubric, 'updated_at', '') or ''

                # Build a structured Markdown table from criteria
                criteria = getattr(rubric, 'data', None) or []
                md_content = f"# Rubric: {r_title}\n\n"
                if r_description:
                    md_content += f"{r_description}\n\n"

                if criteria:
                    # Build table header from first criterion's ratings
                    sample_ratings = criteria[0].get('ratings', [])
                    headers = ['Criterion'] + [
                        f"{r.get('description', '?')} ({r.get('points', '?')})"
                        for r in sorted(sample_ratings,
                                        key=lambda x: x.get('points', 0),
                                        reverse=True)
                    ]
                    md_content += '| ' + ' | '.join(headers) + ' |\n'
                    md_content += '|' + '---|' * len(headers) + '\n'

                    for criterion in criteria:
                        row = [criterion.get('description', '')]
                        c_ratings = sorted(
                            criterion.get('ratings', []),
                            key=lambda x: x.get('points', 0),
                            reverse=True,
                        )
                        for rating in c_ratings:
                            long_desc = rating.get('long_description', '')
                            short_desc = rating.get('description', '')
                            row.append(long_desc or short_desc)
                        # Pad row if ratings count differs
                        while len(row) < len(headers):
                            row.append('')
                        md_content += '| ' + ' | '.join(row) + ' |\n'
                else:
                    md_content += '*No criteria data available.*\n'

                # Save as .md instead of .html
                target_dir, display_name = self._resolve_secondary_path(
                    'rubric', r_title, base_path, isolate=isolate,
                    has_attachments=False,
                )
                filename = self._sanitize_filename(display_name) + '.md'
                filepath = target_dir / filename
                filepath = self._handle_conflict(filepath)

                try:
                    with open(make_long_path(filepath), 'w', encoding='utf-8') as f:
                        f.write(md_content)
                except Exception as e:
                    err = DownloadError(
                        course.name, r_title, "Rubric Save Error",
                        str(e), raw_error=e,
                    )
                    if progress_callback:
                        progress_callback(err, progress_type='error')
                    self._log_error(error_root_path, err)
                    continue

                synthetic_id = make_secondary_id('rubric', r_id)
                if sync_manager:
                    try:
                        rel_path = str(filepath.relative_to(base_path)).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=synthetic_id,
                            canvas_filename=filepath.name,
                            local_relative_path=rel_path,
                            canvas_updated_at=updated_at,
                            original_size=0,
                        )
                    except Exception:
                        pass

                if progress_callback:
                    progress_callback(
                        f'Saving rubric: {r_title}', progress_type='page',
                    )

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Rubrics not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Rubrics", "Secondary Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    # --- Orchestrator ------------------------------------------------------

    async def _download_secondary_content(self, course, base_path, sem,
                                           session, progress_callback,
                                           mb_tracker, check_cancellation,
                                           settings, error_root_path,
                                           debug_file, sync_manager,
                                           module_handled_ids):
        """Download all secondary entities based on the settings dict.

        Called from ``download_course_async()`` AFTER file downloads complete.
        ``module_handled_ids`` contains entity IDs already processed during
        the module-item loop so they are not downloaded twice.

        Attachment download tasks are gathered at the end.
        """
        if not settings:
            return
        log_debug("=== Starting Secondary Content Download ===", debug_file)
        if progress_callback:
            progress_callback('Downloading secondary content...', progress_type='log')

        download_tasks = []  # Async tasks for attachment downloads

        # 1. Assignments
        if settings.get('download_assignments'):
            self._fetch_and_save_assignments(
                course, base_path, sem, session,
                progress_callback, mb_tracker, check_cancellation,
                settings, error_root_path, debug_file,
                sync_manager, module_handled_ids, download_tasks,
            )

        # 2. Syllabus
        if settings.get('download_syllabus'):
            self._fetch_and_save_syllabus(
                course, base_path, progress_callback, settings,
                error_root_path, debug_file, sync_manager,
            )

        # 3. Announcements
        if settings.get('download_announcements'):
            self._fetch_and_save_announcements(
                course, base_path, sem, session,
                progress_callback, mb_tracker, check_cancellation,
                settings, error_root_path, debug_file,
                sync_manager, download_tasks,
            )

        # 4. Discussions
        if settings.get('download_discussions'):
            self._fetch_and_save_discussions(
                course, base_path, progress_callback,
                check_cancellation, settings,
                error_root_path, debug_file,
                sync_manager, module_handled_ids,
            )

        # 5. Quizzes
        if settings.get('download_quizzes'):
            self._fetch_and_save_quizzes(
                course, base_path, progress_callback,
                check_cancellation, settings,
                error_root_path, debug_file,
                sync_manager, module_handled_ids,
            )

        # 6. Rubrics
        if settings.get('download_rubrics'):
            self._fetch_and_save_rubrics(
                course, base_path, progress_callback,
                check_cancellation, settings,
                error_root_path, debug_file, sync_manager,
            )

        # Gather all attachment download tasks
        if download_tasks:
            log_debug(f"Waiting for {len(download_tasks)} attachment downloads...", debug_file)
            results = await asyncio.gather(*download_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    err = DownloadError(
                        course.name, "Attachment Task", "Async Error",
                        str(result), raw_error=result,
                    )
                    if progress_callback:
                        progress_callback(err, progress_type='error')
                    self._log_error(error_root_path, err)

        log_debug("=== Secondary Content Download Complete ===", debug_file)

    def _create_link(self, title, url, folder_path, progress_callback, error_root_path=None, course_name="Unknown", debug_file=None, sync_manager=None, course_base_path=None, canvas_item_id=0):
        import xml.sax.saxutils as saxutils
        safe_title = self._sanitize_filename(title)
        
        if platform.system() == 'Darwin':
            filename = f"{safe_title}.webloc"
            filepath = folder_path / filename
            filepath = self._handle_conflict(filepath)
            content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>URL</key>
	<string>{saxutils.escape(url)}</string>
</dict>
</plist>
'''
        else:
            filename = f"{safe_title}.url"
            filepath = folder_path / filename
            filepath = self._handle_conflict(filepath)
            safe_url = url.replace('\r', '').replace('\n', '')
            content = f'[InternetShortcut]\nURL={safe_url}'

        if progress_callback:
            progress_callback(f'Creating link: {title}', progress_type='link')

        log_debug(f"Creating Link: {title} ({url}) -> {filepath}", debug_file)

        try:
            with open(make_long_path(filepath), 'w', encoding='utf-8') as f:
                f.write(content)
            # Sync Run #0: Record link/URL file to DB using deterministic canvas_item_id
            if sync_manager and course_base_path and canvas_item_id:
                try:
                    rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                    sync_manager.record_downloaded_file(
                        canvas_file_id=canvas_item_id,
                        canvas_filename=filepath.name,
                        local_relative_path=rel_path,
                        canvas_updated_at=datetime.now(timezone.utc).isoformat(),
                        original_size=0
                    )
                except Exception:
                    pass  # Non-fatal
            return filepath
        except Exception as e:
            err = DownloadError(course_name, title, "Link Creation Error", str(e), raw_error=e)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            import logging
            logging.getLogger(__name__).error(f"Error creating link: {e}")
            log_debug(f"Error creating link: {e}", debug_file)
            return None

    def _handle_conflict(self, filepath):
        if not filepath.exists():
            return filepath
        base = filepath.stem
        ext = filepath.suffix
        parent = filepath.parent
        counter = 1
        while filepath.exists() and counter < 1000:
            new_name = f"{base} ({counter}){ext}"
            filepath = parent / new_name
            counter += 1
        if counter >= 1000:
            filepath = parent / f"{base}_{uuid.uuid4().hex[:8]}{ext}"
        return filepath

    def _sanitize_filename(self, filename, replace_spaces=False, max_length=120):
        if not filename: return "untitled"
        try: filename = urllib.parse.unquote_plus(filename)
        except Exception: pass
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
        if replace_spaces: sanitized = sanitized.replace(' ', '_')
        sanitized = sanitized.lstrip(' _').rstrip('. _')
        if len(sanitized) > max_length:
            name, ext = os.path.splitext(sanitized)
            if len(ext) > 10: sanitized = sanitized[:max_length]
            else: sanitized = name[:(max_length - len(ext))] + ext
        return sanitized if sanitized else "untitled"

    def clear_error_log(self, base_path):
        """Wipe download_errors.txt to start fresh for a new run."""
        self._logged_error_sigs = set()  # Reset dedup cache
        if not base_path: return
        path = Path(base_path)
        log_file = path / "download_errors.txt"
        if log_file.exists():
            try:
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write("")  # Truncate
            except Exception:
                pass

    def _log_error(self, base_path, error):
        """Log structured error to a single file in the root path. Deduplicates by signature."""
        # Build a signature to prevent the same error being logged twice
        if isinstance(error, DownloadError):
            error_sig = f"{error.course_name}|{error.item_name}|{error.message}"
        else:
            error_sig = str(error)
        if error_sig in self._logged_error_sigs:
            return  # Already logged this exact error in this run
        self._logged_error_sigs.add(error_sig)

        # 'error' can be a DownloadError object or a string (legacy support)
        if not base_path: return
        
        path = Path(base_path)
        path.mkdir(parents=True, exist_ok=True)
        log_file = path / "download_errors.txt"
        
        try:
            entry = ""
            if isinstance(error, DownloadError):
                entry = error.to_log_entry()
            else:
                entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {error}"
                
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            # Last resort fallback if logging fails
            pass

    def _check_disk_space(self, path, min_free_gb=1, required_bytes=0):
        """Check disk space dynamically: max(min_free_gb, required_bytes * 1.2)."""
        try:
            stat = shutil.disk_usage(path)
            # Dynamic threshold: at least 1GB, or the payload size + 20% buffer
            min_required = max(min_free_gb * (1024**3), int(required_bytes * 1.2))
            return stat.free >= min_required
        except Exception:
            return True
