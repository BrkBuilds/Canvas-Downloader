import os
import platform
import re
import uuid
import shutil
import html
import urllib.parse
import traceback
import unicodedata
from pathlib import Path
from datetime import datetime, timezone
from canvasapi import Canvas
from canvasapi.exceptions import CanvasException, Unauthorized, ResourceDoesNotExist
import asyncio
import aiohttp
import types
import threading
import aiofiles
from canvas_debug import log_debug, clear_debug_log
import logging
import requests
from requests.adapters import HTTPAdapter

from sync_manager import SyncManager, make_secondary_id, is_secondary_id, CanvasFileInfo
from ui_helpers import make_long_path, _err_log_lock

logger = logging.getLogger(__name__)


class _CanvasTimeoutAdapter(HTTPAdapter):
    """Injects a default (connect, read) timeout into every synchronous canvasapi request.

    Without this, course.get_modules() / course.get_files() etc. can hang
    indefinitely on high-latency or unreliable connections (e.g. cross-continent).
    The timeout causes requests.exceptions.Timeout to propagate through canvasapi,
    which then surfaces as a proper error rather than a silent hang.
    """
    def send(self, request, **kwargs):
        # 15s connect / 60s read. Slow Canvas servers on registration day may
        # exceed this; expose CANVAS_TIMEOUT env var if a user needs more time.
        kwargs.setdefault('timeout', (15, int(os.environ.get('CANVAS_TIMEOUT', 60))))
        return super().send(request, **kwargs)


# --- Global Async Locks ---
# Lock objects are event-loop-bound; only store reference counts and loop IDs
# at module level. New asyncio.Lock() objects are created per-loop to avoid
# "Task got Future attached to a different loop" across asyncio.run() calls.
_download_locks: dict = {}  # filepath -> {"lock": asyncio.Lock, "count": int, "loop_id": int}
_lock_mutex_local = threading.Lock()  # threading.Lock is loop-independent

def safe_thread_wrapper(func, current_ctx, *args, **kwargs):
    """
    Safely executes a function in a separate thread while preserving Streamlit's
    ScriptRunContext. This ensures thread-bound session_state and UI renders
    don't throw missing context exceptions.
    """
    import threading
    from streamlit.runtime.scriptrunner import add_script_run_ctx
    if current_ctx:
        add_script_run_ctx(threading.current_thread(), current_ctx)
    return func(*args, **kwargs)

from contextlib import asynccontextmanager

@asynccontextmanager
async def manage_download_lock(filepath):
    # get_running_loop() is the correct API from Python 3.7+ when called
    # from within a running coroutine (get_event_loop() is deprecated for this).
    current_loop = asyncio.get_running_loop()
    current_loop_id = id(current_loop)

    # Push threading.Lock acquisitions to the executor so they never block
    # the event loop thread if contended under high concurrency (H-16).
    def _acquire_slot():
        with _lock_mutex_local:
            entry = _download_locks.get(filepath)
            if entry is None or entry.get("loop_id") != current_loop_id:
                # Fresh entry or stale lock from a dead event loop — new Lock.
                _download_locks[filepath] = {"lock": asyncio.Lock(), "count": 0, "loop_id": current_loop_id}
            _download_locks[filepath]["count"] += 1
            return _download_locks[filepath]["lock"]

    def _release_slot():
        with _lock_mutex_local:
            entry = _download_locks.get(filepath)
            if entry:
                entry["count"] -= 1
                if entry["count"] == 0:
                    _download_locks.pop(filepath, None)

    file_lock = await current_loop.run_in_executor(None, _acquire_slot)
    try:
        async with file_lock:
            yield
    finally:
        await current_loop.run_in_executor(None, _release_slot)

# --- Constants ---
MAX_RETRIES = 5
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


def _extract_canvas_file_links(html_body):
    """Parse an HTML body and extract Canvas file download links.

    Instructors often embed file references as ``<a>`` tags inside
    assignment/announcement descriptions rather than using the Canvas
    ``attachments`` API field.  This function discovers those links.

    Returns
    -------
    list[dict]
        Each dict has ``'file_id'`` (int) and ``'link_text'`` (str).
        Deduplicated by ``file_id``.
    """
    if not html_body:
        return []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_body, 'html.parser')
    except Exception:
        return []

    seen_ids = set()
    results = []

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if '/files/' not in href:
            continue

        # Extract file_id from patterns like:
        #   /courses/123/files/456/download
        #   /files/456/download?download_frd=1
        #   /courses/123/files/456?wrap=1
        try:
            # Split on '/files/' and take the segment after it
            after_files = href.split('/files/', 1)[1]
            # The file_id is the next path segment (digits)
            file_id_str = after_files.split('/')[0].split('?')[0]
            file_id = int(file_id_str)
        except (IndexError, ValueError):
            continue

        if file_id in seen_ids:
            continue
        seen_ids.add(file_id)

        link_text = a_tag.get_text(strip=True) or f'file_{file_id}'
        results.append({'file_id': file_id, 'link_text': link_text})

    return results


# Maps entity types to their subfolder names (Mode B) and prefixes (Mode A)
_ENTITY_ROUTING = {
    'assignment':   {'folder': 'Assignments',   'prefix': 'Assignment'},
    'syllabus':     {'folder': 'Syllabus',      'prefix': 'Syllabus'},
    'announcement': {'folder': 'Announcements', 'prefix': 'Announcement'},
    'discussion':   {'folder': 'Discussions',   'prefix': 'Discussion'},
    'quiz':         {'folder': 'Quizzes',       'prefix': 'Quiz'},
    'rubric':       {'folder': 'Rubrics',       'prefix': 'Rubric'},
    'submission':   {'folder': 'Submissions',   'prefix': 'Submission'},
    'page':         {'folder': 'Pages',         'prefix': 'Page'},
    'link':         {'folder': 'Links',         'prefix': 'Link'},
}

def _format_canvas_date(date_str):
    """
    Formats ISO 8601 UTC strings from Canvas (e.g., '2025-08-26T14:07:50Z')
    into human-readable localized strings like '26th August, 2025 at 14:07'.
    When 12-hour format is enabled, uses American ordering: 'August 26th, 2025 at 2:07 PM'.
    """
    if not date_str or not isinstance(date_str, str):
        return str(date_str)
    try:
        # Convert Canvas Zulu time 'Z' to explicit UTC '+00:00' for Python parsing
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        
        # Astimezone inherently converts to the user's local operating system timezone
        local_dt = dt.astimezone()
        
        # Calculate English ordinal suffix for the day
        day = local_dt.day
        if 4 <= day <= 20 or 24 <= day <= 30:
            suffix = "th"
        else:
            suffix = ["st", "nd", "rd"][day % 10 - 1]
            
        # Format time component respecting 12h/24h preference
        try:
            import streamlit as st
            use_12h = st.session_state.get('use_12h_format', False)
        except Exception:
            use_12h = False

        if use_12h:
            time_fmt = local_dt.strftime('%I:%M %p').lstrip('0')
            # American: "August 26th, 2025 at 2:07 PM"
            return f"{local_dt.strftime('%B')} {day}{suffix}, {local_dt.year} at {time_fmt}"
        else:
            time_fmt = local_dt.strftime('%H:%M')
            # European: "26th August, 2025 at 14:07"
            return f"{day}{suffix} {local_dt.strftime('%B')}, {local_dt.year} at {time_fmt}"
    except Exception:
        return date_str

class DownloadError:
    """Structured error object for UI display and logging."""
    def __init__(self, course_name, item_name, error_type, message, raw_error=None, context=None, is_app_error=False):
        self.course_name = course_name
        self.item_name = item_name
        self.error_type = error_type # e.g., '401', 'Rate Limit', 'Network', 'Generic'
        self.message = message
        self.raw_error = str(raw_error) if isinstance(raw_error, Exception) else raw_error
        self.context = context or {}
        self.is_app_error = is_app_error  # True for engine/infra failures, not individual file failures
        self.timestamp = datetime.now(timezone.utc)

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
            from urllib.parse import urlparse
            try:
                parsed = urlparse(api_url)
                # Reconstruct URL retaining strictly scheme and netloc
                self.api_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
            except Exception:
                self.api_url = api_url.rstrip("/")
            
        # Initialize Canvas object
        try:
            self.canvas = Canvas(self.api_url, self.api_key)
            # Apply a default timeout to all synchronous canvasapi requests so that
            # calls like course.get_modules() raise Timeout instead of hanging forever
            # on slow or cross-continent connections.
            try:
                _adapter = _CanvasTimeoutAdapter()
                self.canvas._Canvas__requester._session.mount('https://', _adapter)
                self.canvas._Canvas__requester._session.mount('http://', _adapter)
            except Exception as _e:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    f"Could not mount timeout adapter on canvasapi session: {_e}. "
                    "API calls will have no timeout and may hang on slow connections."
                )
        except Exception:
            # If URL is completely malformed, Canvas init might fail immediately
            self.canvas = None
            
        self.user = None
        self._logged_error_sigs = set()  # Dedup cache: prevents same error being logged twice in one run
        self.error_log_enabled = False    # Toggled via Settings; when False, download_errors.txt is not created

    def __repr__(self):
        """Redacted repr - never expose the API token in tracebacks or log output."""
        return f"CanvasManager(api_url={self.api_url!r}, api_key='****')"

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

    def get_course_files_metadata(self, course, progress_callback=None, secondary_content_settings=None, is_scanning_phase=False):
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
            Tuple of (list[CanvasFileInfo], dict, dict):
              - List of CanvasFileInfo objects (unique by ID)
              - Secondary fetch success status dict
              - Module map: content_id (int) → sanitized module folder name (str)
        """
        from sync_manager import CanvasFileInfo
        
        all_files_map = {} # ID -> CanvasFileInfo
        module_map = {}  # content_id (int) -> sanitized module folder name (str)
        
        # --- Phase 1: Bulk Fetch (get_files) ---
        try:
            # We iterate manually to catch errors during pagination
            canvas_files = course.get_files()
            for file in canvas_files:
                if not getattr(file, 'url', ''):
                    logger.debug(f"Skipping locked/restricted file: {getattr(file, 'filename', '<unknown>')} in course {getattr(course, 'name', '?')}")
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
            module_files, module_map = self._get_files_from_modules(course, progress_callback=progress_callback,
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
            if progress_callback:
                progress_callback(f"Module scan failed — some files may be missing: {e}", progress_type='log')

        # --- Phase 3: Secondary Content Metadata ---
        # Pass the module map so attachments of module-linked entities can
        # inherit their parent's module folder (Mode A path routing).
        secondary_fetch_success = {}
        if secondary_content_settings:
            try:
                secondary_items, secondary_fetch_success = self.get_secondary_content_metadata(
                    course, secondary_content_settings,
                    is_scanning_phase=is_scanning_phase,
                    module_map=module_map,
                )
                for s_info in secondary_items:
                    if s_info.id not in all_files_map:
                        all_files_map[s_info.id] = s_info
            except Exception as e:
                logger.error(f"Error fetching secondary content metadata: {e}")
                if progress_callback:
                    progress_callback(f"Secondary content scan failed — some items may be missing: {e}", progress_type='log')
            
        return list(all_files_map.values()), secondary_fetch_success, module_map
    
    def _get_files_from_modules(self, course, progress_callback=None, secondary_content_settings=None):
        """Fallback: Get files by iterating through modules.

        Also emits mock CanvasFileInfo for secondary entity types
        (Assignment, Quiz, Discussion, Page, ExternalUrl) when
        *secondary_content_settings* enables them.  This allows the sync
        analysis engine to see these entities without additional API calls.

        ``module_map`` is keyed by **both** raw positive Canvas file IDs
        (for ordinary File items) **and** synthetic negative IDs (for
        secondary content), so ``analyze_course`` can resolve a module
        subfolder for every entity that lives inside a module - which is
        what lets Mode A inline secondary content land in the right
        module subfolder during sync.

        Returns:
            Tuple of (list[CanvasFileInfo], dict):
              - List of discovered file info objects
              - Module map: ID (int, positive or synthetic-negative) →
                sanitized module folder name (str)
        """
        from sync_manager import CanvasFileInfo

        # Determine secondary-content layout mode once. Mode A (isolate=False)
        # needs filenames carrying the routing prefix so the analyzer's
        # calc_path = "<module>/Type: Foo.html" matches the on-disk layout.
        # Mode B (isolate=True) keeps basenames; _resolve_secondary_path
        # handles the actual category/folder placement at write time.
        isolate = True
        if secondary_content_settings:
            isolate = secondary_content_settings.get('isolate_secondary_content', True)

        files = []
        module_map = {}
        try:
            modules = list(course.get_modules())
        except Exception as e:
            logger.warning(f"Could not fetch module list for course {getattr(course, 'id', '?')}: {e}")
            if progress_callback:
                progress_callback(f"Could not fetch modules: {e}", progress_type='log')
            return files, module_map
        total_modules = len(modules)
        for idx, module in enumerate(modules):
            if progress_callback:
                progress_callback(idx + 1, total_modules, f"Scanning module: {module.name}")

            clean_module_name = self._sanitize_filename(module.name)
            try:
                items = list(module.get_module_items())
            except Exception as e:
                logger.warning(f"Could not fetch items for module '{getattr(module, 'name', '?')}': {e}")
                continue
            for item in items:
                if item.type == 'File':
                    if not hasattr(item, 'content_id') or not item.content_id:
                        continue
                    module_map[item.content_id] = clean_module_name
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
                    except Exception as _fetch_err:
                        logger.warning(
                            f"Could not fetch file {item.content_id} from module "
                            f"'{getattr(module, 'name', '?')}': {_fetch_err}"
                        )
                        if progress_callback:
                            progress_callback(
                                f"Could not access '{getattr(item, 'title', item.content_id)}' "
                                f"in module '{getattr(module, 'name', '?')}'",
                                progress_type='log',
                            )
                elif item.type in ['Page', 'ExternalUrl', 'ExternalTool']:
                    try:
                        ext = ".html" if item.type == 'Page' else (".webloc" if platform.system() == 'Darwin' else ".url")
                        safe_base = self._sanitize_filename(getattr(item, 'title', 'Untitled'))
                        if isolate or item.type != 'Page':
                            emitted_filename = safe_base + ext
                        else:
                            routing = _ENTITY_ROUTING['page']
                            emitted_filename = f"{routing['prefix']}: {safe_base}{ext}"

                        actual_url = getattr(item, 'html_url', None) or getattr(item, 'external_url', None) or getattr(item, 'url', '')
                        syn_id = -int(item.id) if hasattr(item, 'id') else 0
                        if syn_id and not isolate:
                            module_map[syn_id] = clean_module_name

                        mock_info = CanvasFileInfo(
                            id=syn_id,
                            filename=emitted_filename,
                            display_name=safe_base + ext,
                            size=0,
                            modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                            url=actual_url,
                            content_type="text/html" if item.type == 'Page' else "application/x-url"
                        )
                        files.append(mock_info)
                    except Exception as _item_err:
                        logger.warning(
                            f"Could not process {item.type} item "
                            f"'{getattr(item, 'title', '?')}' in module "
                            f"'{getattr(module, 'name', '?')}': {_item_err}"
                        )

                # --- Secondary entities found in modules ---
                elif item.type == 'Assignment' and secondary_content_settings and secondary_content_settings.get('download_assignments'):
                    try:
                        safe_base = self._sanitize_filename(getattr(item, 'title', 'Untitled'))
                        content_id = getattr(item, 'content_id', 0) or 0
                        syn_id = make_secondary_id('assignment', content_id)
                        if not isolate:
                            module_map[syn_id] = clean_module_name
                        if isolate:
                            emitted_filename = safe_base + '.html'
                        else:
                            routing = _ENTITY_ROUTING['assignment']
                            emitted_filename = f"{routing['prefix']}: {safe_base}.html"
                        files.append(CanvasFileInfo(
                            id=syn_id,
                            filename=emitted_filename,
                            display_name=getattr(item, 'title', 'Untitled'),
                            size=0,
                            modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                            url=getattr(item, 'html_url', ''),
                            content_type='text/html',
                        ))
                    except Exception as _item_err:
                        logger.warning(
                            f"Could not process Assignment item '{getattr(item, 'title', '?')}' "
                            f"in module '{getattr(module, 'name', '?')}': {_item_err}"
                        )
                elif item.type == 'Quiz' and secondary_content_settings and secondary_content_settings.get('download_quizzes'):
                    try:
                        safe_base = self._sanitize_filename(getattr(item, 'title', 'Untitled'))
                        content_id = getattr(item, 'content_id', 0) or 0
                        syn_id = make_secondary_id('quiz', content_id)
                        if not isolate:
                            module_map[syn_id] = clean_module_name
                        if isolate:
                            emitted_filename = safe_base + '.html'
                        else:
                            routing = _ENTITY_ROUTING['quiz']
                            emitted_filename = f"{routing['prefix']}: {safe_base}.html"
                        files.append(CanvasFileInfo(
                            id=syn_id,
                            filename=emitted_filename,
                            display_name=getattr(item, 'title', 'Untitled'),
                            size=0,
                            modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                            url=getattr(item, 'html_url', ''),
                            content_type='text/html',
                        ))
                    except Exception as _item_err:
                        logger.warning(
                            f"Could not process Quiz item '{getattr(item, 'title', '?')}' "
                            f"in module '{getattr(module, 'name', '?')}': {_item_err}"
                        )
                elif item.type == 'Discussion' and secondary_content_settings and secondary_content_settings.get('download_discussions'):
                    try:
                        safe_base = self._sanitize_filename(getattr(item, 'title', 'Untitled'))
                        content_id = getattr(item, 'content_id', 0) or 0
                        syn_id = make_secondary_id('discussion', content_id)
                        if not isolate:
                            module_map[syn_id] = clean_module_name
                        if isolate:
                            emitted_filename = safe_base + '.html'
                        else:
                            routing = _ENTITY_ROUTING['discussion']
                            emitted_filename = f"{routing['prefix']}: {safe_base}.html"
                        files.append(CanvasFileInfo(
                            id=syn_id,
                            filename=emitted_filename,
                            display_name=getattr(item, 'title', 'Untitled'),
                            size=0,
                            modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                            url=getattr(item, 'html_url', ''),
                            content_type='text/html',
                        ))
                    except Exception as _item_err:
                        logger.warning(
                            f"Could not process Discussion item '{getattr(item, 'title', '?')}' "
                            f"in module '{getattr(module, 'name', '?')}': {_item_err}"
                        )
        return files, module_map

    def get_secondary_content_metadata(self, course, settings, is_scanning_phase=False,
                                       module_map=None):
        """Return (items, fetch_success) for *standalone* secondary content.

        This covers entities that are NOT linked from any module and thus
        would not be surfaced by ``_get_files_from_modules``.  Examples:
        Announcements, Syllabus, standalone Assignments, Rubrics.

        Used by the sync analysis path to detect new/updated/missing
        secondary entities in the manifest.

        ``module_map`` is mutated in place: when an emitted attachment
        belongs to a module-linked parent entity (Assignment / Quiz /
        Discussion that already appears in ``module_map``), the
        attachment's ID is added so the analyzer can route Mode A
        attachments back into the correct module subfolder.

        Returns
        -------
        tuple[list[CanvasFileInfo], dict[str, bool]]
            ``(items, fetch_success)`` where ``fetch_success`` maps entity
            type strings to True/False indicating whether the API call
            succeeded.  The sync engine uses this to guard against false
            deletions when a fetch times out.
        """
        from sync_manager import CanvasFileInfo

        if module_map is None:
            module_map = {}

        items = []
        fetch_success = {}

        # Syllabus
        if settings.get('download_syllabus'):
            try:
                full_course = self.canvas.get_course(
                    course.id, include=['syllabus_body'],
                )
                if getattr(full_course, 'syllabus_body', None):
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['syllabus']
                    if isolate:
                        syl_filename = f"{routing['folder']}/Syllabus.html"
                    else:
                        syl_filename = f"{routing['prefix']}: Syllabus.html"
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('syllabus', course.id),
                        filename=syl_filename,
                        display_name='Syllabus',
                        size=0,
                        modified_at=getattr(full_course, 'updated_at', ''),
                        url='',
                        content_type='text/html',
                    ))
                fetch_success['syllabus'] = True
            except Exception as e:
                logger.warning(f"Fetching syllabus failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['syllabus'] = False

        # Announcements
        if settings.get('download_announcements'):
            try:
                topics = course.get_discussion_topics(only_announcements=True)
                for topic in topics:
                    t_id = getattr(topic, 'id', 0)
                    title = getattr(topic, 'title', 'Announcement')
                    posted_at = getattr(topic, 'posted_at', '') or ''
                    
                    # Date-prefix for chronological file ordering (Alignment fix)
                    date_prefix = ''
                    if posted_at:
                        try:
                            dt = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
                            date_prefix = dt.strftime('%Y-%m-%d') + ' - '
                        except (ValueError, TypeError):
                            pass
                            
                    display_name = f"{date_prefix}{title}"
                    safe_title = self._sanitize_filename(display_name)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['announcement']
                    
                    attachments = []
                    try:
                        raw_att = getattr(topic, 'attachments', None)
                        if raw_att and isinstance(raw_att, list):
                            attachments = list(raw_att)
                    except Exception:
                        pass

                    existing_att_ids = {
                        a.get('id') for a in attachments if isinstance(a, dict)
                    }

                    if not is_scanning_phase:
                        t_msg = getattr(topic, 'message', '') or ''
                        for link_info in _extract_canvas_file_links(t_msg):
                            fid = link_info['file_id']
                            if fid in existing_att_ids:
                                continue
                            try:
                                canvas_file = course.get_file(fid)
                                attachments.append({
                                    'id': canvas_file.id,
                                    'url': canvas_file.url,
                                    'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                                    'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                                    'size': getattr(canvas_file, 'size', 0),
                                    'modified_at': getattr(canvas_file, 'modified_at', ''),
                                    'content-type': getattr(canvas_file, 'content_type', ''),
                                })
                                existing_att_ids.add(canvas_file.id)
                            except Exception:
                                pass

                    has_attachments = bool(attachments)
                    
                    if isolate:
                        if has_attachments:
                            ann_filename = f"{routing['folder']}/{safe_title}/{safe_title}.html"
                        else:
                            ann_filename = f"{routing['folder']}/{safe_title}.html"
                    else:
                        ann_filename = f"{routing['prefix']}: {safe_title}.html"
                        
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('announcement', t_id),
                        filename=ann_filename,
                        display_name=title,
                        size=0,
                        modified_at=getattr(topic, 'posted_at', ''),
                        url=getattr(topic, 'html_url', ''),
                        content_type='text/html',
                    ))
                    
                    for att in attachments:
                        raw_id = att.get('id')
                        if not raw_id:
                            continue
                        from sync_manager import make_secondary_id
                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        att_raw_name = att.get('filename', att.get('display_name', 'attachment'))
                        if isolate and has_attachments:
                            att_prefixed_name = f"{routing['folder']}/{safe_title}/{att_raw_name}"
                        elif isolate:
                            att_prefixed_name = f"{routing['folder']}/{att_raw_name}"
                        else:
                            # Mode A: prefix attachment with parent entity's
                            # routing prefix so it matches the on-disk layout
                            # produced by _fetch_and_save_assignments / etc.
                            att_prefixed_name = f"{routing['prefix']}: {safe_title} - {att_raw_name}"

                        items.append(CanvasFileInfo(
                            id=att_id,
                            filename=att_prefixed_name,
                            display_name=att.get('display_name', att.get('filename', 'attachment')),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', getattr(topic, 'posted_at', '')),
                            url=att.get('url', ''),
                            content_type=att.get('content-type', ''),
                        ))
                fetch_success['announcement'] = True
            except Exception as e:
                logger.warning(f"Fetching announcements failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['announcement'] = False

        # Standalone Assignments - fetch individually for timestamp parity
        # and attachment discovery (mirrors the download path exactly).
        if settings.get('download_assignments'):
            try:
                for assignment in course.get_assignments():
                    a_id = getattr(assignment, 'id', 0)
                    a_name = getattr(assignment, 'name', 'Assignment')
                    a_updated = getattr(assignment, 'updated_at', '') or ''

                    full_assignment = None
                    if not is_scanning_phase:
                        # Full sync analysis: fetch individually for
                        # timestamp parity and attachment discovery.
                        try:
                            full_assignment = course.get_assignment(a_id)
                        except Exception:
                            full_assignment = assignment
                        a_name = getattr(full_assignment, 'name', 'Assignment')
                        a_updated = getattr(full_assignment, 'updated_at', '') or ''

                    # --- Build the correct filename path ---
                    safe_name = self._sanitize_filename(a_name)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['assignment']

                    # Discover attachments (only in full analysis mode)
                    attachments = []
                    if full_assignment is not None:
                        try:
                            raw_att = getattr(full_assignment, 'attachments', None)
                            if raw_att and isinstance(raw_att, list):
                                attachments = list(raw_att)
                        except Exception:
                            pass

                    existing_att_ids = {
                        a.get('id') for a in attachments if isinstance(a, dict)
                    }

                    if not is_scanning_phase:
                        # Inline file links from the description HTML
                        a_desc = getattr(full_assignment, 'description', '') or ''
                        for link_info in _extract_canvas_file_links(a_desc):
                            fid = link_info['file_id']
                            if fid in existing_att_ids:
                                continue
                            try:
                                canvas_file = course.get_file(fid)
                                attachments.append({
                                    'id': canvas_file.id,
                                    'url': canvas_file.url,
                                    'filename': getattr(canvas_file, 'filename',
                                                        link_info['link_text']),
                                    'display_name': getattr(canvas_file, 'display_name',
                                                            link_info['link_text']),
                                    'size': getattr(canvas_file, 'size', 0),
                                    'modified_at': getattr(canvas_file, 'modified_at', ''),
                                    'content-type': getattr(canvas_file, 'content_type', ''),
                                })
                                existing_att_ids.add(canvas_file.id)
                            except Exception:
                                pass  # Inaccessible file - skip silently

                    has_attachments = bool(attachments)

                    # Build the filename to match _resolve_secondary_path
                    if isolate:
                        if has_attachments:
                            entity_filename = f"{routing['folder']}/{safe_name}/{safe_name}.html"
                        else:
                            entity_filename = f"{routing['folder']}/{safe_name}.html"
                    else:
                        entity_filename = f"{routing['prefix']}: {safe_name}.html"

                    # 1) The Assignment HTML entity itself (negative synthetic ID)
                    parent_syn_id = make_secondary_id('assignment', a_id)
                    items.append(CanvasFileInfo(
                        id=parent_syn_id,
                        filename=entity_filename,
                        display_name=a_name,
                        size=0,
                        modified_at=a_updated,
                        url=getattr(assignment, 'html_url', ''),
                        content_type='text/html',
                    ))

                    # 2) Yield each attachment as a true CanvasFileInfo
                    parent_module = module_map.get(parent_syn_id, "")
                    for att in attachments:
                        raw_id = att.get('id')
                        if not raw_id:
                            continue
                        from sync_manager import make_secondary_id
                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        # Unify namespace: prepend the parent entity's
                        # subfolder so the filename mirrors the physical
                        # extraction layout on disk.
                        att_raw_name = att.get('filename',
                                               att.get('display_name', 'attachment'))
                        if isolate and has_attachments:
                            att_prefixed_name = f"{routing['folder']}/{safe_name}/{att_raw_name}"
                        elif isolate:
                            att_prefixed_name = f"{routing['folder']}/{att_raw_name}"
                        else:
                            # Mode A: parent assignment writes attachments as
                            # "<prefix>: <a_name> - <filename>" alongside its
                            # HTML body (see _fetch_and_save_assignments).
                            att_prefixed_name = f"{routing['prefix']}: {safe_name} - {att_raw_name}"

                        # Inherit parent module placement so analyze_course
                        # can route Mode A attachments back into the parent
                        # assignment's module subfolder.
                        if parent_module:
                            module_map[att_id] = parent_module

                        items.append(CanvasFileInfo(
                            id=att_id,
                            filename=att_prefixed_name,
                            display_name=att.get('display_name',
                                                 att.get('filename', 'attachment')),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', a_updated),
                            url=att.get('url', ''),
                            content_type=att.get('content-type', ''),
                        ))

                fetch_success['assignment'] = True
            except Exception as e:
                logger.warning(f"Fetching assignments failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['assignment'] = False

        # Standalone Discussions (non-announcement)
        if settings.get('download_discussions'):
            try:
                for topic in course.get_discussion_topics():
                    if getattr(topic, 'is_announcement', False):
                        continue
                    t_id = getattr(topic, 'id', 0)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['discussion']
                    d_title = getattr(topic, 'title', 'Discussion')
                    safe_title = self._sanitize_filename(d_title)
                    
                    attachments = []
                    try:
                        raw_att = getattr(topic, 'attachments', None)
                        if raw_att and isinstance(raw_att, list):
                            attachments = list(raw_att)
                    except Exception:
                        pass

                    existing_att_ids = {
                        a.get('id') for a in attachments if isinstance(a, dict)
                    }

                    if not is_scanning_phase:
                        t_msg = getattr(topic, 'message', '') or ''
                        for link_info in _extract_canvas_file_links(t_msg):
                            fid = link_info['file_id']
                            if fid in existing_att_ids:
                                continue
                            try:
                                canvas_file = course.get_file(fid)
                                attachments.append({
                                    'id': canvas_file.id,
                                    'url': canvas_file.url,
                                    'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                                    'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                                    'size': getattr(canvas_file, 'size', 0),
                                    'modified_at': getattr(canvas_file, 'modified_at', ''),
                                    'content-type': getattr(canvas_file, 'content_type', ''),
                                })
                                existing_att_ids.add(canvas_file.id)
                            except Exception:
                                pass

                    has_attachments = bool(attachments)
                    
                    if isolate:
                        if has_attachments:
                            disc_filename = f"{routing['folder']}/{safe_title}/{safe_title}.html"
                        else:
                            disc_filename = f"{routing['folder']}/{safe_title}.html"
                    else:
                        disc_filename = f"{routing['prefix']}: {safe_title}.html"
                        
                    parent_syn_id = make_secondary_id('discussion', t_id)
                    items.append(CanvasFileInfo(
                        id=parent_syn_id,
                        filename=disc_filename,
                        display_name=d_title,
                        size=0,
                        modified_at=getattr(topic, 'updated_at', ''),
                        url=getattr(topic, 'html_url', ''),
                        content_type='text/html',
                    ))

                    parent_module = module_map.get(parent_syn_id, "")
                    for att in attachments:
                        raw_id = att.get('id')
                        if not raw_id:
                            continue
                        from sync_manager import make_secondary_id
                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        att_raw_name = att.get('filename', att.get('display_name', 'attachment'))
                        if isolate and has_attachments:
                            att_prefixed_name = f"{routing['folder']}/{safe_title}/{att_raw_name}"
                        elif isolate:
                            att_prefixed_name = f"{routing['folder']}/{att_raw_name}"
                        else:
                            att_prefixed_name = f"{routing['prefix']}: {safe_title} - {att_raw_name}"

                        if parent_module:
                            module_map[att_id] = parent_module

                        items.append(CanvasFileInfo(
                            id=att_id,
                            filename=att_prefixed_name,
                            display_name=att.get('display_name', att.get('filename', 'attachment')),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', getattr(topic, 'updated_at', '')),
                            url=att.get('url', ''),
                            content_type=att.get('content-type', ''),
                        ))
                fetch_success['discussion'] = True
            except Exception as e:
                logger.warning(f"Fetching discussions failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['discussion'] = False

        # Quizzes
        if settings.get('download_quizzes'):
            try:
                for quiz in course.get_quizzes():
                    q_id = getattr(quiz, 'id', 0)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['quiz']
                    q_title = getattr(quiz, 'title', 'Quiz')
                    safe_title = self._sanitize_filename(q_title)
                    
                    attachments = []
                    try:
                        raw_att = getattr(quiz, 'attachments', None)
                        if raw_att and isinstance(raw_att, list):
                            attachments = list(raw_att)
                    except Exception:
                        pass

                    existing_att_ids = {
                        a.get('id') for a in attachments if isinstance(a, dict)
                    }

                    if not is_scanning_phase:
                        q_desc = getattr(quiz, 'description', '') or ''
                        for link_info in _extract_canvas_file_links(q_desc):
                            fid = link_info['file_id']
                            if fid in existing_att_ids:
                                continue
                            try:
                                canvas_file = course.get_file(fid)
                                attachments.append({
                                    'id': canvas_file.id,
                                    'url': canvas_file.url,
                                    'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                                    'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                                    'size': getattr(canvas_file, 'size', 0),
                                    'modified_at': getattr(canvas_file, 'modified_at', ''),
                                    'content-type': getattr(canvas_file, 'content_type', ''),
                                })
                                existing_att_ids.add(canvas_file.id)
                            except Exception:
                                pass

                    has_attachments = bool(attachments)
                    
                    if isolate:
                        if has_attachments:
                            quiz_filename = f"{routing['folder']}/{safe_title}/{safe_title}.html"
                        else:
                            quiz_filename = f"{routing['folder']}/{safe_title}.html"
                    else:
                        quiz_filename = f"{routing['prefix']}: {safe_title}.html"
                        
                    parent_syn_id = make_secondary_id('quiz', q_id)
                    items.append(CanvasFileInfo(
                        id=parent_syn_id,
                        filename=quiz_filename,
                        display_name=q_title,
                        size=0,
                        modified_at=getattr(quiz, 'updated_at', ''),
                        url=getattr(quiz, 'html_url', ''),
                        content_type='text/html',
                    ))

                    parent_module = module_map.get(parent_syn_id, "")
                    for att in attachments:
                        raw_id = att.get('id')
                        if not raw_id:
                            continue
                        from sync_manager import make_secondary_id
                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        att_raw_name = att.get('filename', att.get('display_name', 'attachment'))
                        if isolate and has_attachments:
                            att_prefixed_name = f"{routing['folder']}/{safe_title}/{att_raw_name}"
                        elif isolate:
                            att_prefixed_name = f"{routing['folder']}/{att_raw_name}"
                        else:
                            att_prefixed_name = f"{routing['prefix']}: {safe_title} - {att_raw_name}"

                        if parent_module:
                            module_map[att_id] = parent_module

                        items.append(CanvasFileInfo(
                            id=att_id,
                            filename=att_prefixed_name,
                            display_name=att.get('display_name', att.get('filename', 'attachment')),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', getattr(quiz, 'updated_at', '')),
                            url=att.get('url', ''),
                            content_type=att.get('content-type', ''),
                        ))
                fetch_success['quiz'] = True
            except Exception as e:
                logger.warning(f"Fetching quizzes failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['quiz'] = False

        # Rubrics
        if settings.get('download_rubrics'):
            try:
                for rubric in course.get_rubrics():
                    r_id = getattr(rubric, 'id', 0)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['rubric']
                    r_title = getattr(rubric, 'title', 'Rubric')
                    safe_title = self._sanitize_filename(r_title)
                    if isolate:
                        rubric_filename = f"{routing['folder']}/{safe_title}.md"
                    else:
                        rubric_filename = f"{routing['prefix']}: {safe_title}.md"
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('rubric', r_id),
                        filename=rubric_filename,
                        display_name=r_title,
                        size=0,
                        modified_at=getattr(rubric, 'updated_at', ''),
                        url='',
                        content_type='text/markdown',
                    ))
                fetch_success['rubric'] = True
            except Exception as e:
                logger.warning(f"Fetching rubrics failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['rubric'] = False

        return items, fetch_success

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
                            
                            if file_filter != 'study':
                                # Study mode can't verify extension without a slow file fetch;
                                # count is derived from the catch-all section below instead.
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
                    total_bytes += getattr(file, 'size', 0) or 0
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
                                total_bytes += getattr(file_obj, 'size', 0) or 0
                            except Exception:
                                pass
        except Exception:
            pass
        return total_bytes / (1024 * 1024)

    async def download_course_async(self, course, mode, save_dir, progress_callback=None, check_cancellation=None, file_filter='all', debug_mode=False, post_processing_settings=None, secondary_content_settings=None, estimated_size_mb=0):
        """
        Downloads content for a single course asynchronously.

        Args:
            estimated_size_mb: Per-course estimated payload in MB for disk-space
                check. Pass the course-specific value from the caller instead of
                relying on the aggregate ``total_mb`` session-state key, which is
                stale after the first course in a multi-course download run.
        """
        course_name = self._sanitize_filename(course.name)
        base_path = Path(save_dir) / course_name

        # Check disk space using the caller-supplied per-course estimate.
        # Fall back to the session-state aggregate only as a last resort so we
        # don't silently skip the check when no estimate was provided.
        _estimated_mb = estimated_size_mb or 0
        if not _estimated_mb:
            try:
                import streamlit as _st_disk
                _estimated_mb = _st_disk.session_state.get('total_mb', 0) or 0
            except Exception:
                _estimated_mb = 0
        _estimated_bytes = int(_estimated_mb * 1024 * 1024)
        if not self._check_disk_space(save_dir, required_bytes=_estimated_bytes):
            _free_gb = 0
            try:
                _free_gb = shutil.disk_usage(save_dir).free / (1024 ** 3)
            except Exception:
                pass
            error = DownloadError(
                course.name,
                "Disk Check",
                "Disk Full",
                f'Insufficient disk space. Estimated payload: {_estimated_mb:.0f} MB, '
                f'available: {_free_gb:.1f} GB. Need at least {max(1.0, _estimated_mb * 1.2 / 1024):.1f} GB free.',
                is_app_error=True,
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
            # Append course header (never wipe - one global log per session)
            log_debug(f"\n{'='*50}\n--- Download: {course.name} (ID: {course.id}) Mode: {mode} ---\n{'='*50}", debug_file)
            log_debug(f"Save Dir: {save_dir}", debug_file)

        downloaded_file_ids = set()
        module_file_ids = set()
        seen_target_paths = set()  # Path-based collision tracking
        module_handled_ids = set()  # Secondary entity IDs already handled via module dispatch
        mb_tracker = {'bytes_downloaded': 0}
        
        # Determine semaphore limit from session state if available, default to 5.
        # Wrapped in try/except because this async function may run on a background
        # thread where Streamlit's session context is not present.
        try:
            import streamlit as _st_sem
            concurrent_limit = int(_st_sem.session_state.get('concurrent_downloads', 5) or 5)
        except Exception:
            concurrent_limit = 5
        # Clamp to a sane range so a corrupted setting can't crash
        # asyncio.Semaphore (rejects non-positive) or fork 1000 sockets.
        concurrent_limit = max(1, min(concurrent_limit, 20))
        sem = asyncio.Semaphore(concurrent_limit)

        # Read max-file-size gate from session state once, store on the
        # manager so every _download_file_async call can apply it without
        # plumbing a parameter through ~7 dispatch sites.
        try:
            import streamlit as _st_sz
            if _st_sz.session_state.get('max_file_size_enabled', False):
                _mb = int(_st_sz.session_state.get('max_file_size_mb', 0) or 0)
                self._max_file_size_bytes = _mb * 1024 * 1024 if _mb > 0 else None
            else:
                self._max_file_size_bytes = None
        except Exception:
            self._max_file_size_bytes = None
        
        tasks = []
        timeout = aiohttp.ClientTimeout(total=3600, sock_read=60, sock_connect=15)
        connector = aiohttp.TCPConnector(limit=concurrent_limit, limit_per_host=concurrent_limit)

        async with aiohttp.ClientSession(
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=timeout,
            connector=connector
        ) as session:
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
                                        if hasattr(item, 'content_id'):
                                            module_file_ids.add(item.content_id)
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
                                        page_id = getattr(page_obj, 'page_id', getattr(page_obj, 'id', 0))
                                        filepath, _, _ = self._save_secondary_entity(
                                            'page', getattr(page_obj, 'title', 'Untitled Page'), getattr(page_obj, 'body', '') or '',
                                            base_path, course_base_path=base_path, sync_manager=sync_manager,
                                            canvas_entity_id=page_id, canvas_updated_at=getattr(page_obj, 'updated_at', '') or '',
                                            progress_callback=progress_callback, debug_file=debug_file, error_root_path=Path(save_dir) if 'save_dir' in locals() else None,
                                            course_name=course.name, module_path=target_path, isolate=False, has_attachments=False, metadata_pairs=[]
                                        )
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
                                                        ('URL', getattr(assignment, 'html_url', None)),
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
                                                    logger.warning(f"Assignment dispatch failed for '{getattr(item, 'title', '?')}': {ae}")
                                                    _ae_err = DownloadError(course.name, getattr(item, 'title', 'Assignment'), "Assignment Dispatch Error", str(ae), raw_error=ae)
                                                    if progress_callback: progress_callback(_ae_err, progress_type='error')
                                                    self._log_error(save_dir, _ae_err)

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
                                                        ('URL', getattr(quiz, 'html_url', None)),
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
                                                    logger.warning(f"Quiz dispatch failed for '{getattr(item, 'title', '?')}': {qe}")
                                                    _qe_err = DownloadError(course.name, getattr(item, 'title', 'Quiz'), "Quiz Dispatch Error", str(qe), raw_error=qe)
                                                    if progress_callback: progress_callback(_qe_err, progress_type='error')
                                                    self._log_error(save_dir, _qe_err)

                                    elif item.type == 'Discussion':
                                        if secondary_content_settings and secondary_content_settings.get('download_discussions'):
                                            if hasattr(item, 'content_id') and item.content_id:
                                                try:
                                                    isolate = secondary_content_settings.get('isolate_secondary_content', True)
                                                    topic = course.get_discussion_topic(item.content_id)
                                                    t_id = getattr(topic, 'id', 0)
                                                    title = getattr(topic, 'title', 'Untitled Discussion')
                                                    message = getattr(topic, 'message', '') or ''
                                                    message += await asyncio.to_thread(self._build_discussion_replies_html_sync, topic, debug_file)
                                                    updated_at = (getattr(topic, 'last_reply_at', '')
                                                                  or getattr(topic, 'updated_at', '') or '')

                                                    metadata = [
                                                        ('Posted', getattr(topic, 'posted_at', None)),
                                                        ('Replies', getattr(topic, 'discussion_subentry_count', None)),
                                                        ('URL', getattr(topic, 'html_url', None)),
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
                                                    logger.warning(f"Discussion dispatch failed for '{getattr(item, 'title', '?')}': {de}")
                                                    _de_err = DownloadError(course.name, getattr(item, 'title', 'Discussion'), "Discussion Dispatch Error", str(de), raw_error=de)
                                                    if progress_callback: progress_callback(_de_err, progress_type='error')
                                                    self._log_error(save_dir, _de_err)
                                        
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
                            err = DownloadError(course.name, "File Task", "Async Error", str(result), raw_error=result, is_app_error=True)
                            if progress_callback: progress_callback(err, progress_type='error')
                            self._log_error(save_dir, err)
                        elif result:
                            downloaded_files_info.append(result)


                # ---- HYBRID MODE CATCH-ALL STARTED ----
                try:
                    log_debug("Starting Catch-All Phase for non-module files...", debug_file)
                    if progress_callback: progress_callback('Scanning remaining files...', progress_type='log')
                    
                    all_files_paginator = course.get_files()
                    catch_all_tasks = []

                    # Pre-compute ID sets once - avoids O(N×M) set
                    # reconstruction on every loop iteration.
                    _downloaded_ids = {int(i) for i in downloaded_file_ids}
                    _module_ids = {int(i) for i in module_file_ids}

                    for file in all_files_paginator:
                        if check_cancellation and check_cancellation(): break
                        
                        if int(file.id) in _downloaded_ids or int(file.id) in _module_ids:
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
                                err = DownloadError(course.name, "Catch-All Task", "Async Error", str(result), raw_error=result, is_app_error=True)
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
                        # Just log it, DO NOT add to user's download_errors.txt
                        _msg = f"Files tab restricted for '{course.name}' — skipping catch-all phase."
                        logger.warning(_msg)
                        if progress_callback:
                            progress_callback(_msg, progress_type='log')
                    else:
                        # Handle actual unexpected errors
                        err = DownloadError(course.name, "Catch-All Scan", "Hybrid Mode Error", str(e), raw_error=e, is_app_error=True)
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
                            is_app_error=True,
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
                     err = DownloadError(course.name, "Course Download", "Processing Error", str(e), raw_error=e, is_app_error=True)
                     if progress_callback: progress_callback(err, progress_type='error')
                     self._log_error(save_dir, err)
            
            # --- Sync Run #0: Save the download mode and sync contract ---
            try:
                sync_manager._save_metadata('download_mode', mode)
                # Save the full "Sync Contract" - all settings used during this download
                if post_processing_settings:
                    import json
                    sync_manager._save_metadata('sync_contract', json.dumps(post_processing_settings))
                # Save the secondary content contract
                if secondary_content_settings:
                    import json
                    sync_manager._save_metadata('secondary_content_contract', json.dumps(secondary_content_settings))
            except Exception as e:
                logger.warning(f"Could not save sync contract to DB for '{course.name}': {e}")
                log_debug(f"Warning: Could not save sync metadata: {e}", debug_file)

    async def download_isolated_batch_async(self, course, error_queue, save_dir, progress_callback=None, check_cancellation=None, debug_mode=False, mb_tracker=None):
        """
        Targeted retry for specifically failed items queued in error_queue.
        """
        # Reset discovery-error counter at the start of each batch so the
        # return value reflects only this run.  Without this reset the
        # counter accumulates across reused CanvasManager instances and the
        # UI overstates skipped-discovery counts.
        self.skipped_discovery_errors = 0

        course_name = self._sanitize_filename(course.name)
        base_path = Path(save_dir) / course_name

        debug_file = (Path(save_dir) / "debug_log.txt") if debug_mode else None
        
        # We instantiate a local sync_manager so files downloaded here are logged
        try:
            sync_manager = SyncManager(base_path, course.id, course.name)
        except Exception as e:
            log_debug(f"Failed to initialize SyncManager during isolated batch: {e}", debug_file)
            sync_manager = None
        
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx, add_script_run_ctx
        
        # Streamlit Context Safety Assert:
        # Before accessing any session states or spawning sub-tasks, guarantee thread bounds.
        current_ctx = get_script_run_ctx()
        if not current_ctx:
            raise RuntimeError("CRITICAL THREAD LEAK: Streamlit ScriptRunContext is missing in download_isolated_batch_async.")

        try:
            import streamlit as _st_iso
            concurrent_limit = int(_st_iso.session_state.get('concurrent_downloads', 5) or 5)
        except Exception:
            concurrent_limit = 5
        # Final safety net: clamp to a sane range so a corrupted setting can't
        # crash asyncio.Semaphore (rejects non-positive) or fork 1000 sockets.
        concurrent_limit = max(1, min(concurrent_limit, 20))
        sem = asyncio.Semaphore(concurrent_limit)
        tasks = []
        timeout = aiohttp.ClientTimeout(total=3600, sock_read=60, sock_connect=15)

        # Mirror the size-gate setup from download_course_async so the
        # retry path honors the same limit.
        try:
            import streamlit as _st_iso_sz
            if _st_iso_sz.session_state.get('max_file_size_enabled', False):
                _mb = int(_st_iso_sz.session_state.get('max_file_size_mb', 0) or 0)
                self._max_file_size_bytes = _mb * 1024 * 1024 if _mb > 0 else None
            else:
                self._max_file_size_bytes = None
        except Exception:
            self._max_file_size_bytes = None

        if mb_tracker is None:
            mb_tracker = {'bytes_downloaded': 0}


        if debug_mode:
            log_debug(f"\n{'='*50}\n--- Isolated Retry Mode for {course.name} ---\n{'='*50}", debug_file)

        connector = aiohttp.TCPConnector(limit=concurrent_limit, limit_per_host=concurrent_limit)
        async with aiohttp.ClientSession(
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=timeout,
            connector=connector
        ) as session:
            for error_obj in error_queue:
                if check_cancellation and check_cancellation():
                    break
                
                context = getattr(error_obj, 'context', {})
                file_dict = context.get('file_dict')
                filepath_str = context.get('filepath')
                file_filter = context.get('file_filter', 'all')
                
                if file_dict and filepath_str:
                    filepath = Path(filepath_str)
                    
                    # Reconstruct lightweight CanvasFileInfo mock object safely
                    file_obj = CanvasFileInfo(
                        id=file_dict.get('id', 0),
                        filename=file_dict.get('filename', ''),
                        display_name=file_dict.get('display_name', file_dict.get('filename', '')),
                        size=file_dict.get('size', 0),
                        modified_at=file_dict.get('modified_at', None),
                        md5=file_dict.get('md5', None),
                        url=file_dict.get('url', ''),
                        content_type=file_dict.get('content-type', ''),
                        folder_id=file_dict.get('folder_id', None)
                    )
                    
                    # Ensure the explicitly passed parent directory actually exists on disk
                    # to prevent FileNotFoundError during aiofiles.open writes
                    Path(make_long_path(filepath.parent)).mkdir(parents=True, exist_ok=True)
                    
                    if file_obj.id < 0:
                        # Synthetic entity - Route differently
                        from sync_manager import secondary_id_type
                        etype = secondary_id_type(file_obj.id)
                        
                        if etype == 'module_item':
                            # Legacy synthetic entities (Pages or ExternalURLs)
                            # Synchronously write standard shortcuts/stubs to disk to prevent brittle API refetches.
                            try:
                                url_to_save = file_obj.url
                                ext = filepath.suffix.lower()
                                
                                # Write file formats based directly on extension
                                if ext == '.html':
                                    content = f'<meta http-equiv="refresh" content="0; url={html.escape(url_to_save, quote=True)}">'
                                    async with aiofiles.open(str(make_long_path(filepath)), 'w', encoding='utf-8') as f:
                                        await f.write(content)
                                elif ext == '.url':
                                    _safe_url = url_to_save.replace('\r', '').replace('\n', '%0A')
                                    content = f'[InternetShortcut]\nURL={_safe_url}'
                                    async with aiofiles.open(str(make_long_path(filepath)), 'w', encoding='utf-8') as f:
                                        await f.write(content)
                                elif ext == '.webloc':
                                    import plistlib
                                    content = plistlib.dumps(
                                        {'URL': url_to_save},
                                        fmt=plistlib.FMT_XML,
                                    )
                                    async with aiofiles.open(str(make_long_path(filepath)), 'wb') as f:
                                        await f.write(content)
                                
                                # Do NOT append a task; this item is now done synchronously. 
                                if progress_callback:
                                    progress_callback(f"Saved Link: {filepath.name}", progress_type='download', explicit_filepath=str(filepath.resolve()))
                            
                            except Exception as e:
                                err = DownloadError(course.name, getattr(file_obj, 'filename', 'unknown'), "Legacy Entity Save Error", str(e), raw_error=e)
                                if progress_callback: progress_callback(err, progress_type='error')
                                self._log_error(save_dir, err)
                        else:
                            # Modern secondary entities (actively re-fetched inside the function using raw_id)
                            secondary_settings = {'isolate_secondary_content': True}
                            try:
                                sec_filepath, sec_id, sec_attachments, canvas_updated = await asyncio.to_thread(
                                    safe_thread_wrapper,
                                    self.download_secondary_entity,
                                    current_ctx,
                                    course, file_obj, filepath.parent,
                                    sync_manager, secondary_settings,
                                    progress_callback, debug_file, Path(save_dir), course.name
                                )
                                
                                # 1. The ACID Commit
                                if sync_manager and sec_id and canvas_updated is not None and sec_filepath:
                                    try:
                                        rel_path = str(sec_filepath.relative_to(base_path)).replace('\\', '/')
                                        await asyncio.to_thread(
                                            sync_manager.record_downloaded_file,
                                            canvas_file_id=sec_id,
                                            canvas_filename=sec_filepath.name,
                                            local_path=rel_path,
                                            canvas_updated_at=canvas_updated,
                                            original_size=0
                                        )
                                    except Exception as db_err:
                                        if debug_mode: log_debug(f"DB Commit failed during retry: {db_err}", debug_file)
                                
                                # 2. Dynamic Queue Injection (Await-and-Inject)
                                if sec_attachments:
                                    attach_dir = sec_filepath.parent if sec_filepath else filepath.parent
                                    for att in sec_attachments:
                                        att_id = att.get('id')
                                        att_url = att.get('url', '')
                                        att_filename = att.get('filename', att.get('display_name', 'attachment'))
                                        if not att_url or not att_id:
                                            continue
                                            
                                        att_info = CanvasFileInfo(
                                            id=att_id,
                                            filename=att_filename,
                                            display_name=att.get('display_name', att_filename),
                                            size=att.get('size', 0),
                                            modified_at=att.get('modified_at', ''),
                                            url=att_url,
                                            content_type=att.get('content-type', '')
                                        )
                                        
                                        # Progress Bar Integrity
                                        if progress_callback:
                                            progress_callback(att_filename, progress_type='attachment_discovered', size=att.get('size', 0))
                                            
                                        att_filepath = attach_dir / self._sanitize_filename(att_filename)
                                        
                                        att_task = asyncio.create_task(self._download_file_async(
                                            sem, session, att_info, attach_dir, progress_callback, mb_tracker, file_filter, 
                                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file,
                                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=att_filepath,
                                            check_cancellation=check_cancellation
                                        ))
                                        tasks.append(att_task)

                            except Exception as sec_e:
                                err = DownloadError(course.name, getattr(file_obj, 'filename', 'unknown'), "Secondary Retry Error", str(sec_e), raw_error=sec_e)
                                if progress_callback: progress_callback(err, progress_type='error')
                                self._log_error(save_dir, err)
                    else:
                        # Refresh URL securely using the safe_thread_wrapper to preserve context for logging
                        try:
                            fetch_id = file_obj.id
                            if fetch_id < 0:
                                from sync_manager import secondary_id_type, SECONDARY_ID_OFFSETS
                                if secondary_id_type(fetch_id) == 'attachment':
                                    fetch_id = abs(fetch_id) - SECONDARY_ID_OFFSETS['attachment']
                            
                            fresh_file = await asyncio.to_thread(safe_thread_wrapper, course.get_file, current_ctx, fetch_id)
                            fresh_url = getattr(fresh_file, 'url', '')
                            if not fresh_url:
                                raise ValueError("Canvas API returned an empty URL for this item.")
                            
                            file_obj.url = fresh_url
                            if debug_mode: log_debug(f"Successfully refreshed URL for {file_obj.filename}", debug_file)
                        except Exception as e:
                            # HARD-FAIL CONSTRAINT: Do NOT fallback to stale URL. It will just trigger 403 backoff loops.
                            err = DownloadError(course.name, filepath.name, "URL Expiration", f"Could not refresh expired URL: {e}", raw_error=e)
                            if progress_callback: progress_callback(err, progress_type='error', file_size=file_obj.size)
                            self._log_error(save_dir, err)
                            continue # Skip to the next file immediately
                            
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, file_obj, filepath.parent, progress_callback, mb_tracker, file_filter, 
                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath,
                            check_cancellation=check_cancellation
                        ))
                        tasks.append(task)
                else:
                    # Discovery error. Lacks file context. Skip and tally.
                    if 'skipped_discovery_errors' not in getattr(self, '__dict__', {}):
                        self.skipped_discovery_errors = 0
                    self.skipped_discovery_errors += 1
            
            if tasks:
                _retry_results = await asyncio.gather(*tasks, return_exceptions=True)
                for _rr in _retry_results:
                    if isinstance(_rr, Exception):
                        logger.error(f"Isolated retry task failed: {_rr}")
                        if progress_callback:
                            _rr_err = DownloadError(
                                getattr(course, 'name', 'Unknown'), "Retry Task",
                                "Async Retry Error", str(_rr), raw_error=_rr,
                            )
                            progress_callback(_rr_err, progress_type='error')

            return getattr(self, 'skipped_discovery_errors', 0)

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
            err = DownloadError(course.name, "Folder Structure", "Fetch Error", f"Could not fetch folders: {e}", raw_error=e, is_app_error=True)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            # Continue to allow flat file download if possible?
            # If folder fetch failed, likely file fetch will too, but let's try.

        # 2. Fetch and Download Files
        try:
            if progress_callback: progress_callback('Fetching file list...')
            files_paginator = course.get_files()
            
            for file in files_paginator:
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
                        sync_manager=sync_manager, course_base_path=base_path, check_cancellation=check_cancellation
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
                        err = DownloadError(course.name, "File Task", "Async Error", str(result), raw_error=result, is_app_error=True)
                        if progress_callback: progress_callback(err, progress_type='error')
                        self._log_error(error_root_path, err)
                    elif result:
                        downloaded.append(result)


        except Exception as e:
            err = DownloadError(course.name, "File List", "Fetch Error", str(e), raw_error=e, is_app_error=True)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

        return downloaded

    async def _download_flat_async(self, course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter='all', error_root_path=None, debug_file=None, sync_manager=None):
        """Downloads all files to the root folder."""
        tasks = []
        downloaded = []
        log_debug(f"Starting Flat Download for {course.name}", debug_file)
        
        
        try:
            files = None
            for attempt in range(3):
                try:
                    files = course.get_files()
                    break
                except Exception:
                    if attempt < 2:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    else:
                        files = []
                        # Log warning
                        if progress_callback: progress_callback("Files tab restricted, trying modules...", progress_type='log')
                        log_debug("Files tab restricted (401?), falling back to module scan.", debug_file)

            downloaded_ids = set()
            seen_flat_paths = set()  # Path-based dedup for flat mode
            # Wrap iteration separately: course.get_files() returns a lazy PaginatedList with no
            # network I/O, so the retry loop above never actually tests connectivity.  The first
            # real HTTP request fires here when the iterator is consumed.  Without this inner
            # try the module-scan fallback below would be silently skipped on a 401/network error.
            try:
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
                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath,
                            check_cancellation=check_cancellation
                        ))
                        tasks.append(task)
                    except Exception as e:
                        err = DownloadError(course.name, getattr(file, 'filename', 'unknown'), "Queue Error", str(e), raw_error=e)
                        if progress_callback: progress_callback(err, progress_type='error')
                        self._log_error(error_root_path, err)
            except Exception as file_list_e:
                # File listing failed mid-iteration (e.g. 401, network drop).
                # Log a warning and fall through to the module-scan fallback below.
                _msg = f"Files tab listing failed, falling back to module scan: {file_list_e}"
                if progress_callback: progress_callback(_msg, progress_type='log')
                log_debug(_msg, debug_file)

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        err = DownloadError(course.name, "File Task", "Async Error", str(result), raw_error=result, is_app_error=True)
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
                                page_id = getattr(page_obj, 'page_id', getattr(page_obj, 'id', 0))
                                filepath, _, _ = self._save_secondary_entity(
                                    'page', getattr(page_obj, 'title', 'Untitled Page'), getattr(page_obj, 'body', '') or '',
                                    base_path, course_base_path=base_path, sync_manager=sync_manager,
                                    canvas_entity_id=page_id, canvas_updated_at=getattr(page_obj, 'updated_at', '') or '',
                                    progress_callback=progress_callback, debug_file=debug_file, error_root_path=error_root_path,
                                    course_name=course.name, module_path=base_path, isolate=False, has_attachments=False, metadata_pairs=[]
                                )
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
                             err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Fallback Scan Error", str(e), raw_error=e)
                             if progress_callback: progress_callback(err, progress_type='error')
                             self._log_error(error_root_path, err)
                             log_debug(f"Fallback scan item error: {getattr(item, 'title', 'unknown')}: {e}", debug_file)

                if module_tasks:
                   module_results = await asyncio.gather(*module_tasks, return_exceptions=True)
                   for result in module_results:
                       if isinstance(result, Exception):
                           err = DownloadError(course.name, "Fallback File Task", "Async Error", str(result), raw_error=result, is_app_error=True)
                           if progress_callback: progress_callback(err, progress_type='error')
                           self._log_error(error_root_path, err)
                       elif result:
                           downloaded.append(result)

            except Exception as e:
                err = DownloadError(course.name, "Fallback Module Scan", "Scan Error", str(e), raw_error=e, is_app_error=True)
                if progress_callback: progress_callback(err, progress_type='error')
                self._log_error(error_root_path, err)
                log_debug(f"Fallback module scan failed: {e}", debug_file)

        except Exception as e:
             err = DownloadError(course.name, "Flat Download", "Fatal Error", str(e), raw_error=e, is_app_error=True)
             if progress_callback: progress_callback(err, progress_type='error')
             self._log_error(error_root_path, err)
        
        return downloaded

    async def _download_file_async(self, sem, session, file_obj, folder_path, progress_callback, mb_tracker=None, file_filter='all', error_root_path=None, course_name="Unknown", debug_file=None, sync_manager=None, course_base_path=None, explicit_filepath=None, check_cancellation=None):
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

        # We save the original filepath to serve as our concurrency lock target key.
        # This resolves the race where two threads competing for the same base name
        # evaluate the path before either starts downloading.
        original_filepath = filepath

        # Check duplication by size
        file_size_bytes = getattr(file_obj, 'size', 0) or 0

        # Max-file-size gate (opt-in, configured in the Settings dialog).
        # Files over the user-specified limit are counted as successful
        # skips rather than errors - they're an intentional user choice.
        max_bytes = getattr(self, '_max_file_size_bytes', None)
        if max_bytes and file_size_bytes > max_bytes:
            size_mb_display = file_size_bytes / (1024 * 1024)
            log_debug(
                f"Skipping {filename}: {size_mb_display:.1f} MB exceeds user limit of "
                f"{max_bytes / (1024 * 1024):.0f} MB.",
                debug_file,
            )
            # Register as ignored in the sync DB so future syncs
            # don't surface these files as "new".
            if sync_manager:
                try:
                    await asyncio.to_thread(
                        sync_manager.ignore_file,
                        file_obj.id,
                        getattr(file_obj, 'filename', '')
                    )
                except Exception:
                    pass  # Non-fatal: don't break download for DB issues
            if progress_callback:
                progress_callback(
                    f"{filename} ({size_mb_display:.1f} MB)",
                    progress_type='size_skipped',
                    file_size=file_size_bytes,
                )
            return

        async with manage_download_lock(original_filepath):
            # Only run disk-conflict resolution when the caller hasn't already
            # resolved naming via seen_flat_paths / seen_target_paths.
            # Running this inside the lock eliminates the TOCTOU file conflict race.
            if not explicit_filepath:
                filepath = self._handle_conflict(filepath)
                filename = filepath.name
            # Re-check existence inside lock
            if filepath.exists():
                try:
                    # We only skip if size matches. If size differs, we overwrite (update).
                    if file_size_bytes > 0 and filepath.stat().st_size == file_size_bytes:
                        log_debug(f"Skipping existing file: {filename}", debug_file)
                        # User Request: Remove skipped files from Total MB count (they don't need downloading)
                        if progress_callback:
                             progress_callback("", progress_type='skipped', file_size=file_size_bytes, explicit_filepath=str(filepath.resolve()))
                        # Sync Run #0: Record skipped-but-existing files to the DB
                        if sync_manager and course_base_path:
                            try:
                                rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                                await asyncio.to_thread(
                                    sync_manager.record_downloaded_file,
                                    canvas_file_id=file_obj.id,
                                    canvas_filename=getattr(file_obj, 'filename', ''),
                                    local_path=rel_path,
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

            # Create lightweight dictionary for session state JSON serialization safety
            safe_file_dict = {
                'filename': getattr(file_obj, 'filename', ''),
                'id': getattr(file_obj, 'id', ''),
                'url': getattr(file_obj, 'url', ''),
                'size': getattr(file_obj, 'size', 0),
                'content-type': getattr(file_obj, 'content-type', ''),
                'display_name': getattr(file_obj, 'display_name', ''),
                'modified_at': getattr(file_obj, 'modified_at', None),
                'md5': getattr(file_obj, 'md5', None),
                'folder_id': getattr(file_obj, 'folder_id', None)
            }

            url = file_obj.url
            if not url:
                
                # Check for LTI/Media streams
                ext_lower = filepath.suffix.lower()
                media_exts = ['.mp4', '.mov', '.avi', '.mkv', '.mp3']
                if ext_lower in media_exts:
                    err = DownloadError(course_name, filename, "LTI/Media Stream", "This video is streamed via a Canvas plugin (e.g., Panopto/Studio) and cannot be directly downloaded.", context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                else:
                    err = DownloadError(course_name, filename, "No URL", "File object has no URL", context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                    
                if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                self._log_error(error_root_path, err)
                return

            # aiofiles is imported at module level; reference is used below

            for attempt in range(MAX_RETRIES):
                try:
                    # Early Cancellation Guard (API DoS fix)
                    if check_cancellation and check_cancellation():
                        return
                    
                    # Request block inside semaphore
                    async with sem:
                        if attempt == 0 and progress_callback:
                            progress_callback(filename, progress_type='downloading_start')
                        log_debug(f"Requesting URL: {url} (Attempt {attempt+1})", debug_file)
                        async with session.get(url) as response:
                            if response.status in (403, 429, 503):
                                _retry_after_raw = response.headers.get('Retry-After', '')
                                try:
                                    wait = int(_retry_after_raw)
                                except (ValueError, TypeError):
                                    wait = RETRY_DELAY * (2 ** attempt)
                                raise ValueError(f"RATE_LIMIT:{wait}")
                            elif 500 <= response.status < 600:
                                raise ValueError(f"SERVER_ERROR:{response.status}")

                            log_debug(f"Response Status: {response.status} Content-Type: {response.headers.get('Content-Type', 'unknown')}", debug_file)
                            if response.status == 200:
                                # --- Content-Type Validation ---
                                # Guards against Canvas returning HTML error pages
                                # with a 200 status (common LMS failure mode).
                                resp_ct = (response.headers.get('Content-Type', '') or '').lower().split(';')[0].strip()
                                is_html_response = resp_ct == 'text/html'
                                expects_html = filepath.suffix.lower() in ('.html', '.htm')
                                if is_html_response and not expects_html and file_size_bytes > 0:
                                    raise ValueError(
                                        f"Content-Type mismatch: server returned 'text/html' "
                                        f"but expected a binary file ({filepath.suffix}). "
                                        f"This usually means Canvas returned an error page."
                                    )
                                # --- Atomic .part Pattern ---
                                part_path = filepath.parent / (filepath.name + '.part')
                                download_interrupted = False
                                
                                try:
                                    async with aiofiles.open(make_long_path(part_path), 'wb') as f:
                                        total_bytes = 0
                                        while True:
                                            # Instant cancel check INSIDE the chunk loop via decoupled callable
                                            if check_cancellation and check_cancellation():
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
                                    return  # Cancel - do not return file info
                                
                                # Verify download completeness BEFORE rename
                                if file_size_bytes > 0 and total_bytes != file_size_bytes:
                                    flexible_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.mp3', '.m4v']
                                    is_flexible_media = any(filename.lower().endswith(ext) for ext in flexible_extensions)
                                    
                                    if is_flexible_media and total_bytes > 0:
                                        log_debug(f"Soft Warning: {filename} size mismatch (Expected {file_size_bytes}, got {total_bytes}). Bypassing for media file.", debug_file)
                                    else:
                                        # Incomplete download - delete .part and raise
                                        try:
                                            if Path(make_long_path(part_path)).exists():
                                                Path(make_long_path(part_path)).unlink()
                                        except OSError:
                                            pass
                                        raise Exception(f"File system error: Download incomplete. Expected {file_size_bytes} bytes, got {total_bytes} bytes.")
                                
                                # 100% success: atomic rename .part → final path
                                try:
                                    os.replace(make_long_path(part_path), make_long_path(filepath))
                                except PermissionError:
                                    error_msg = f"Cannot overwrite file (it may be open in another program): {filepath}"
                                    log_debug(error_msg, debug_file)
                                    try:
                                        if Path(make_long_path(part_path)).exists():
                                            Path(make_long_path(part_path)).unlink()
                                    except OSError:
                                        pass
                                    raise RuntimeError(error_msg)

                                log_debug(f"File Saved: {filepath} ({total_bytes} bytes)", debug_file)
                                
                                # --- Sync Run #0: Record to DB AFTER successful atomic rename ---
                                # This is the safety guard: only fully-downloaded files get recorded.
                                # Cancelled/partial .part files never reach this point.
                                if sync_manager and course_base_path:
                                    try:
                                        rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                                        await asyncio.to_thread(
                                            sync_manager.record_downloaded_file,
                                            canvas_file_id=file_obj.id,
                                            canvas_filename=getattr(file_obj, 'filename', ''),
                                            local_path=rel_path,
                                            canvas_updated_at=getattr(file_obj, 'modified_at', None) or '',
                                            original_size=getattr(file_obj, 'size', 0)
                                        )
                                    except Exception as db_err:
                                        log_debug(f"Warning: DB record failed for {filename}: {db_err}", debug_file)
                                        # Non-fatal: download succeeded, DB write failed. File is on disk.
                                
                                if progress_callback:
                                    progress_callback(f'Downloading file: {filename}', progress_type='download', explicit_filepath=str(filepath.resolve()))
                                    
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
                            else:
                                err_msg = f"Download failed with status {response.status}"
                                log_debug(f"ERROR: {err_msg}", debug_file)
                                err = DownloadError(course_name, filename, f"HTTP {response.status}", err_msg, context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                                if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                                self._log_error(error_root_path, err)
                                return

                except ValueError as ve:
                    msg = str(ve)
                    if msg.startswith("RATE_LIMIT:"):
                        wait_time = int(msg.split(":")[1])
                        log_debug(f"Rate limited (403/429). Sleeping {wait_time}s outside semaphore.", debug_file)
                        # Cancel-aware sleep: poll the cancel flag every second
                        # instead of blocking for the full Retry-After. Without
                        # this a long rate-limit can hold up cancellation for
                        # minutes.
                        for _ in range(max(1, int(wait_time))):
                            if check_cancellation and check_cancellation():
                                return
                            await asyncio.sleep(1)
                        continue
                    elif msg.startswith("SERVER_ERROR:"):
                        backoff = RETRY_DELAY * (2 ** attempt)
                        for _ in range(max(1, int(backoff))):
                            if check_cancellation and check_cancellation():
                                return
                            await asyncio.sleep(1)
                        continue
                    raise ve
                    
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt < MAX_RETRIES - 1:
                        # Cancel-aware backoff sleep so a hung connection
                        # can be aborted within ~1s of clicking Cancel.
                        backoff = RETRY_DELAY * (2 ** attempt)
                        for _ in range(max(1, int(backoff))):
                            if check_cancellation and check_cancellation():
                                return
                            await asyncio.sleep(1)
                    else:
                        err = DownloadError(course_name, filename, "Network Error", f"Max retries exceeded: {e}", raw_error=e, context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                        if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                        self._log_error(error_root_path, err)
                        return
                except Exception as e:
                    err = DownloadError(course_name, filename, "Write Error", f"File system error: {e}", raw_error=e, context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                    if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                    self._log_error(error_root_path, err)
                    return

            else:
                err = DownloadError(
                    course_name, filename, "Rate Limit/Server Exhausted",
                    f"Failed to download after {MAX_RETRIES} attempts due to repeated rate limits or server errors.",
                    context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter}
                )
                if progress_callback:
                    progress_callback(err, progress_type='error', file_size=file_size_bytes)
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
        
        # Build the metadata block if provided
        meta_section = ""
        if metadata_pairs:
            formatted_items = []
            for k, v in metadata_pairs:
                if not v:
                    continue
                v_str = str(v)
                # Auto-detect and format ISO 8601 strings from Canvas
                if v_str.endswith('Z') and 'T' in v_str and len(v_str) >= 19:
                    v_str = _format_canvas_date(v_str)
                
                # Render URLs as clickable links
                if v_str.startswith('http://') or v_str.startswith('https://'):
                    v_html = f'<a href="{html.escape(v_str)}" target="_blank">{html.escape(v_str)}</a>'
                else:
                    v_html = html.escape(v_str)
                
                formatted_items.append(
                    f'<div class="meta-item"><span class="meta-label">{html.escape(str(k))}:</span> <span class="meta-value">{v_html}</span></div>'
                )
            
            if formatted_items:
                meta_section = f'<div class="meta-box">{"".join(formatted_items)}</div>'

        # Inject modern styling with 60% layout parity
        css = """
        <style>
            :root {
                --bg-canvas: #f9fafb;
                --bg-card: #ffffff;
                --text-main: #374151;
                --text-heading: #111827;
                --text-muted: #6b7280;
                --border-color: #e5e7eb;
                --accent-color: #3b82f6;
                --meta-bg: #f3f4f6;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
                line-height: 1.6;
                color: var(--text-main);
                background-color: var(--bg-canvas);
                margin: 0;
                padding: 0;
            }
            .container {
                width: 60%;
                margin: 3rem auto;
                background-color: var(--bg-card);
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
                border-radius: 8px;
                padding: 40px 50px;
                box-sizing: border-box;
            }
            @media (max-width: 1200px) {
                .container { width: 80%; }
            }
            @media (max-width: 768px) {
                .container {
                    width: 95%;
                    padding: 25px 20px;
                    margin: 1.5rem auto;
                }
            }
            h1.doc-title {
                color: var(--text-heading);
                margin-top: 0;
                font-size: 2.2rem;
                line-height: 1.25;
                font-weight: 700;
                border-bottom: 2px solid var(--border-color);
                padding-bottom: 12px;
                margin-bottom: 25px;
            }
            .meta-box {
                background-color: var(--meta-bg);
                border-left: 4px solid var(--accent-color);
                padding: 16px 20px;
                margin-bottom: 30px;
                border-radius: 0 6px 6px 0;
                font-size: 0.95rem;
            }
            .meta-item {
                margin-bottom: 8px;
            }
            .meta-item:last-child {
                margin-bottom: 0;
            }
            .meta-label {
                font-weight: 600;
                color: var(--text-heading);
                display: inline-block;
                width: 160px;
            }
            .meta-value {
                color: var(--text-main);
            }
            .content-box {
                font-size: 1.05rem;
            }
            .content-box img {
                max-width: 100%;
                height: auto;
                border-radius: 6px;
                display: block;
                margin: 1.5rem 0;
            }
            .content-box table {
                border-collapse: collapse;
                width: 100%;
                margin: 1.5rem 0;
            }
            .content-box th, .content-box td {
                border: 1px solid var(--border-color);
                padding: 10px 14px;
                text-align: left;
            }
            .content-box th {
                background-color: var(--meta-bg);
                font-weight: 600;
            }
            .content-box a {
                color: var(--accent-color);
                text-decoration: none;
                word-break: break-word;
            }
            .content-box a:hover {
                text-decoration: underline;
            }
            .content-box blockquote {
                border-left: 4px solid var(--border-color);
                padding-left: 1.25rem;
                margin-left: 0;
                margin-right: 0;
                color: var(--text-muted);
                font-style: italic;
                background-color: rgba(243, 244, 246, 0.4);
                padding-top: 0.5rem;
                padding-bottom: 0.5rem;
                border-radius: 0 4px 4px 0;
            }
            .content-box pre {
                background-color: var(--meta-bg);
                padding: 1.25rem;
                border-radius: 6px;
                overflow-x: auto;
                font-size: 0.9rem;
            }
            .content-box code {
                background-color: var(--meta-bg);
                padding: 0.2rem 0.4rem;
                border-radius: 4px;
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
                font-size: 0.9em;
            }
            .content-box pre code {
                background-color: transparent;
                padding: 0;
            }
        </style>
        """

        html_out = (
            f"<!DOCTYPE html>\n"
            f"<html lang=\"en\">\n"
            f"<head>\n"
            f"<meta charset=\"utf-8\">\n"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
            f"<title>{safe_title}</title>\n"
            f"{css}\n"
            f"</head>\n"
            f"<body>\n"
            f"<div class=\"container\">\n"
            f"<h1 class=\"doc-title\">{safe_title}</h1>\n"
            f"{meta_section}\n"
            f"<div class=\"content-box\">\n"
            f"{body_html or '<p><em>(No content provided)</em></p>'}\n"
            f"</div>\n"
            f"</div>\n"
            f"</body>\n"
            f"</html>"
        )
        return html_out

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
        ``(filepath, synthetic_id, canvas_updated_at)`` on success, ``(None, None, None)`` on failure.
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

        part_path = filepath.with_suffix(filepath.suffix + '.part')
        try:
            with open(make_long_path(part_path), 'w', encoding='utf-8') as f:
                f.write(content)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(part_path, filepath)
        except Exception as e:
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
            err = DownloadError(
                course_name, entity_name,
                f"{entity_type.title()} Save Error", str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            return None, None, None  # callers unpack (filepath, syn_id, canvas_updated)

        # DB record ― synthetic negative ID
        synthetic_id = make_secondary_id(entity_type, canvas_entity_id)

        # Record in the sync manifest so subsequent syncs don't re-download this
        # entity. This is centralised here so every call-site is automatically
        # correct — including the module-dispatch loop which only calls
        # _save_secondary_entity and discards the return value.
        if sync_manager and filepath:
            try:
                rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                sync_manager.record_downloaded_file(
                    canvas_file_id=synthetic_id,
                    canvas_filename=filepath.name,
                    local_path=rel_path,
                    canvas_updated_at=canvas_updated_at or '',
                    original_size=0,
                )
            except Exception as _db_err:
                log_debug(f"DB record failed for {entity_type} '{entity_name}': {_db_err}", debug_file)

        if progress_callback:
            progress_callback(
                entity_name, progress_type='secondary',
                entity_type=entity_type, explicit_filepath=str(filepath)
            )

        return filepath, synthetic_id, canvas_updated_at or ''

    def download_secondary_entity(self, course, canvas_file_info, base_path,
                                   sync_manager, secondary_content_settings,
                                   progress_callback=None, debug_file=None,
                                   error_root_path=None, course_name="Unknown",
                                   module_path=None):
        """Fetch a single secondary entity from Canvas and save it to disk.

        This is the UNIVERSAL entry point used by both:
          - The initial download pipeline (via _download_secondary_content)
          - The sync download loop (sync_ui.py)

        Parameters
        ----------
        course : canvasapi.Course
            The Canvas course object.
        canvas_file_info : CanvasFileInfo
            Must have a negative ``.id`` in the SECONDARY_ID_OFFSETS range.
        base_path : Path
            Course root folder on disk.
        sync_manager : SyncManager
            For DB recording.
        secondary_content_settings : dict
            The active secondary content contract.
        module_path : Path | None
            Mode A only: target module subfolder. When ``isolate=False``
            and the entity is module-linked, this is the absolute path of
            the module folder where the entity should be written. The sync
            engine derives this from the analyzer's ``target_local_path``.
            Mode B (``isolate=True``) ignores this argument entirely.

        Returns
        -------
        ``(filepath: Path | None, synthetic_id: int | None, attachments: list | None)``
        Where ``attachments`` is a list of Canvas attachment dicts (each with
        ``id``, ``url``, ``filename``, ``size``) - only populated for assignments.
        """
        # Local imports to prevent circular dependency with sync_manager
        from sync_manager import (
            SECONDARY_ID_OFFSETS, is_secondary_id, secondary_id_type,
        )

        file_id = canvas_file_info.id
        if not is_secondary_id(file_id):
            return None, None, None, None

        entity_type = secondary_id_type(file_id)
        if not entity_type or entity_type in ('module_item', 'unknown'):
            return None, None, None, None

        isolate = secondary_content_settings.get('isolate_secondary_content', True)
        offset = SECONDARY_ID_OFFSETS.get(entity_type, 0)
        raw_id = abs(file_id) - offset

        try:
            if entity_type == 'assignment':
                assignment = course.get_assignment(raw_id)

                # Extract attachments BEFORE saving the HTML body
                attachments = []
                try:
                    raw_att = getattr(assignment, 'attachments', None)
                    if raw_att and isinstance(raw_att, list):
                        attachments = raw_att
                except Exception:
                    pass

                # ── Inline-link extraction (HTML body) ──
                # Instructors embed file links in the description HTML.
                # These are NOT in the attachments API field.
                a_desc = getattr(assignment, 'description', '') or ''
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(a_desc):
                    # H-5: cancel check so a 50-link description doesn't block cancel
                    try:
                        from core.cancellation import is_sync_cancelled, is_download_cancelled
                        if is_sync_cancelled() or is_download_cancelled():
                            break
                    except Exception:
                        pass
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue  # Already captured via API attachments
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                metadata = [
                    ('Due', getattr(assignment, 'due_at', None)),
                    ('Points', getattr(assignment, 'points_possible', None)),
                    ('Submission Types', ', '.join(
                        getattr(assignment, 'submission_types', []) or []
                    )),
                    ('URL', getattr(assignment, 'html_url', None)),
                ]
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'assignment',
                    getattr(assignment, 'name', 'Untitled Assignment'),
                    a_desc,
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=getattr(assignment, 'updated_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=bool(attachments),
                    metadata_pairs=metadata,
                )
                return filepath, syn_id, attachments or None, canvas_updated

            elif entity_type == 'quiz':
                quiz = course.get_quiz(raw_id)
                
                attachments = []
                try:
                    raw_att = getattr(quiz, 'attachments', None)
                    if raw_att and isinstance(raw_att, list):
                        attachments = raw_att
                except Exception:
                    pass

                q_desc = getattr(quiz, 'description', '') or ''
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(q_desc):
                    try:
                        from core.cancellation import is_sync_cancelled, is_download_cancelled
                        if is_sync_cancelled() or is_download_cancelled():
                            break
                    except Exception:
                        pass
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                metadata = [
                    ('Points', getattr(quiz, 'points_possible', None)),
                    ('Due', getattr(quiz, 'due_at', None)),
                    ('URL', getattr(quiz, 'html_url', None)),
                ]
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'quiz',
                    getattr(quiz, 'title', 'Untitled Quiz'),
                    q_desc,
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=getattr(quiz, 'updated_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=bool(attachments),
                    metadata_pairs=metadata,
                )
                return filepath, syn_id, attachments or None, canvas_updated

            elif entity_type == 'discussion':
                topic = course.get_discussion_topic(raw_id)
                
                attachments = []
                try:
                    raw_att = getattr(topic, 'attachments', None)
                    if raw_att and isinstance(raw_att, list):
                        attachments = raw_att
                except Exception:
                    pass

                t_msg = getattr(topic, 'message', '') or ''
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(t_msg):
                    try:
                        from core.cancellation import is_sync_cancelled, is_download_cancelled
                        if is_sync_cancelled() or is_download_cancelled():
                            break
                    except Exception:
                        pass
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                metadata = [
                    ('Posted', getattr(topic, 'posted_at', None)),
                    ('Replies', getattr(topic, 'discussion_subentry_count', None)),
                    ('URL', getattr(topic, 'html_url', None)),
                ]
                updated_at = (getattr(topic, 'last_reply_at', '')
                              or getattr(topic, 'updated_at', '') or '')
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'discussion',
                    getattr(topic, 'title', 'Untitled Discussion'),
                    t_msg + self._build_discussion_replies_html_sync(topic, debug_file),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=bool(attachments),
                    metadata_pairs=metadata,
                )
                return filepath, syn_id, attachments or None, canvas_updated

            elif entity_type == 'announcement':
                topic = course.get_discussion_topic(raw_id)
                
                attachments = []
                try:
                    raw_att = getattr(topic, 'attachments', None)
                    if raw_att and isinstance(raw_att, list):
                        attachments = raw_att
                except Exception:
                    pass

                t_msg = getattr(topic, 'message', '') or ''
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(t_msg):
                    try:
                        from core.cancellation import is_sync_cancelled, is_download_cancelled
                        if is_sync_cancelled() or is_download_cancelled():
                            break
                    except Exception:
                        pass
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                metadata = [
                    ('Posted', getattr(topic, 'posted_at', None)),
                    ('URL', getattr(topic, 'html_url', None)),
                ]
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'announcement',
                    getattr(topic, 'title', 'Announcement'),
                    t_msg + self._build_discussion_replies_html_sync(topic, debug_file),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=getattr(topic, 'posted_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=bool(attachments),
                    metadata_pairs=metadata,
                )
                return filepath, syn_id, attachments or None, canvas_updated

            elif entity_type == 'syllabus':
                full_course = self.canvas.get_course(
                    course.id, include=['syllabus_body'],
                )
                body = getattr(full_course, 'syllabus_body', '') or ''
                if not body:
                    return None, None, None, None
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'syllabus', 'Syllabus', body,
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=course.id,
                    canvas_updated_at=getattr(full_course, 'updated_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=False,
                    metadata_pairs=None,
                )
                return filepath, syn_id, None, canvas_updated

            elif entity_type == 'rubric':
                rubric = course.get_rubric(raw_id)
                criteria = getattr(rubric, 'data', []) or []
                body_lines = []
                for crit in criteria:
                    desc = crit.get('description', '')
                    pts = crit.get('points', '')
                    body_lines.append(f"### {desc} ({pts} pts)")
                    long_desc = crit.get('long_description', '')
                    if long_desc:
                        body_lines.append(long_desc)
                    ratings = crit.get('ratings', [])
                    for r in ratings:
                        body_lines.append(
                            f"- **{r.get('description', '')}** ({r.get('points', '')} pts)"
                        )
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'rubric',
                    getattr(rubric, 'title', 'Rubric'),
                    '\n'.join(body_lines),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=getattr(rubric, 'updated_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=False,
                    metadata_pairs=None,
                    file_extension='.md',
                )
                return filepath, syn_id, None, canvas_updated

            else:
                log_debug(f"Unknown secondary entity type: {entity_type} for ID {file_id}", debug_file)
                return None, None, None, None  # callers unpack (filepath, syn_id, attachments, canvas_updated)

        except Exception as e:
            log_debug(f"Failed to download secondary entity {entity_type} (ID {file_id}): {e}", debug_file)
            raise  # Let exceptions bubble up so the sync retry loop can handle them

    # --- Entity-Specific Fetchers -----------------------------------------

    def _build_discussion_replies_html_sync(self, topic, debug_file=None):
        """Fetch and format discussion/announcement replies synchronously."""
        from canvasapi.exceptions import Unauthorized, ResourceDoesNotExist
        from ui_helpers import esc
        from canvas_debug import log_debug
        
        try:
            entries = list(topic.get_topic_entries())
            if not entries:
                return ""
            
            html_out = ["<hr style='margin-top: 30px; border: 0; border-top: 1px solid #e4e4e7;'><h3 style='margin-bottom: 20px; color: #3f3f46;'>Replies</h3>"]
            
            def render_entry(entry, depth=0):
                margin = min(depth * 30, 150)
                author = getattr(entry, 'user_name', 'Unknown Author')
                message = getattr(entry, 'message', '') or ''
                created_at = getattr(entry, 'created_at', '')
                
                formatted_date = _format_canvas_date(created_at) if created_at else ""
                
                html_out.append(f"<div style='margin-left: {margin}px; padding: 15px; margin-bottom: 12px; background-color: #f4f4f5; border-left: 3px solid #3b82f6; border-radius: 4px;'>")
                html_out.append(f"<div style='margin-bottom: 8px;'><strong>{esc(author)}</strong> <span style='color: #71717a; font-size: 0.9em; margin-left: 8px;'>{esc(formatted_date)}</span></div>")
                
                att_list = []
                raw_atts = getattr(entry, 'attachments', [])
                if not raw_atts:
                    single_att = getattr(entry, 'attachment', None)
                    if single_att:
                        raw_atts = [single_att]
                        
                for att in raw_atts:
                    url = att.get('url', '')
                    display_name = att.get('display_name') or att.get('filename') or 'attachment'
                    if url:
                        att_list.append(f"<a href='{esc(url)}' target='_blank' style='color: #3b82f6; text-decoration: none;'>📎 {esc(display_name)}</a>")
                
                attachments_html = ""
                if att_list:
                    attachments_html = "<div style='margin-top: 10px; padding-top: 10px; border-top: 1px dashed #d4d4d8; font-size: 0.9em;'>" + "<br>".join(att_list) + "</div>"

                html_out.append(f"<div style='color: #27272a; margin-top: 8px;'>{message}</div>")
                html_out.append(attachments_html)
                
                if hasattr(entry, 'get_replies'):
                    try:
                        for sub_entry in entry.get_replies():
                            render_entry(sub_entry, depth + 1)
                    except Exception as e:
                        if debug_file:
                            log_debug(f"Could not fetch sub-replies: {e}", debug_file)
                html_out.append("</div>")

            for entry in entries:
                render_entry(entry, 0)
                
            return "\n".join(html_out)
        except (Unauthorized, ResourceDoesNotExist):
            return "<hr style='margin-top: 30px; border: 0; border-top: 1px solid #e4e4e7;'><p style='color: #71717a;'><em>Replies could not be accessed.</em></p>"
        except Exception as e:
            if debug_file:
                from canvas_debug import log_debug
                log_debug(f"Error fetching replies: {e}", debug_file)
            return ""

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
        from sync_manager import make_secondary_id
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
                # IMPORTANT: course.get_assignments() (list endpoint) does NOT
                # return the `attachments` field. We must refetch each
                # assignment individually to get full data including attached
                # files - this mirrors the sync path's download_secondary_entity.
                attachments = []
                try:
                    full_assignment = course.get_assignment(a_id)
                    # Update description/updated_at from the richer individual response
                    description = getattr(full_assignment, 'description', '') or description
                    updated_at = getattr(full_assignment, 'updated_at', '') or updated_at
                    raw_attachments = getattr(full_assignment, 'attachments', None)
                    if raw_attachments and isinstance(raw_attachments, list):
                        attachments = raw_attachments
                        log_debug(f"  Assignment '{a_name}': found {len(attachments)} API attachment(s)", debug_file)
                except Exception as att_err:
                    log_debug(f"  Could not refetch assignment {a_id} for attachments: {att_err}", debug_file)

                # ── Inline-link extraction (HTML body) ──
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(description):
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                has_attachments = bool(attachments)
                if has_attachments:
                    log_debug(f"  Assignment '{a_name}': {len(attachments)} total attachment(s) (API + inline)", debug_file)

                metadata = [
                    ('Due', getattr(assignment, 'due_at', None)),
                    ('Points', getattr(assignment, 'points_possible', None)),
                    ('Submission Types', ', '.join(
                        getattr(assignment, 'submission_types', []) or []
                    )),
                    ('URL', getattr(assignment, 'html_url', None)),
                ]

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
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

                # CRITICAL: Save the parent HTML file to the database manifest
                if filepath and sync_manager:
                    try:
                        from pathlib import Path
                        rel_path = str(Path(filepath).relative_to(Path(base_path))).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=syn_id,
                            canvas_filename=Path(filepath).name,
                            local_path=rel_path,
                            canvas_updated_at=canvas_updated,
                            original_size=0,
                        )
                    except Exception as e:
                        print(f"CRITICAL DB ERROR: {e}")

                # Queue attachment downloads using their REAL positive IDs
                if filepath and attachments:
                    attach_dir = filepath.parent
                    for att in attachments:
                        raw_id = att.get('id')
                        att_url = att.get('url', '')
                        att_filename = att.get('filename', att.get('display_name', 'attachment'))
                        if not att_url or not raw_id:
                            continue

                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        if not isolate:
                            # Mode A: prefix attachment filename
                            routing = _ENTITY_ROUTING['assignment']
                            att_filename = f"{routing['prefix']}: {self._sanitize_filename(a_name)} - {att_filename}"

                        # Build a mock file object that _download_file_async expects
                        att_file_obj = types.SimpleNamespace(
                            id=att_id,
                            url=att_url,
                            filename=att_filename,
                            display_name=att.get('display_name', att_filename),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', updated_at),
                            md5=None,
                            content_type=att.get('content-type', ''),
                            folder_id=None,
                        )

                        att_filepath = attach_dir / self._sanitize_filename(att_filename)
                        if progress_callback:
                            progress_callback(att_filename, progress_type='attachment_discovered', size=att.get('size', 0))
                        
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, att_file_obj, attach_dir,
                            progress_callback, mb_tracker, 'attachment',
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

            filepath, syn_id, canvas_updated = self._save_secondary_entity(
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
                    ('URL', getattr(full_course, 'html_url', None) or getattr(course, 'html_url', None)),
                ],
            )
            
            if filepath and sync_manager:
                try:
                    rel_path = str(filepath.relative_to(base_path)).replace('\\', '/')
                    sync_manager.record_downloaded_file(
                        canvas_file_id=syn_id,
                        canvas_filename=filepath.name,
                        local_path=rel_path,
                        canvas_updated_at=canvas_updated,
                        original_size=0,
                    )
                except Exception:
                    pass

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
        from sync_manager import make_secondary_id
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

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'announcement', display_name, message + self._build_discussion_replies_html_sync(topic, debug_file), base_path,
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
                        ('URL', getattr(topic, 'html_url', None)),
                    ],
                )

                # CRITICAL: Save the parent HTML file to the database manifest
                if filepath and sync_manager:
                    try:
                        from pathlib import Path
                        rel_path = str(Path(filepath).relative_to(Path(base_path))).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=syn_id,
                            canvas_filename=Path(filepath).name,
                            local_path=rel_path,
                            canvas_updated_at=canvas_updated,
                            original_size=0,
                        )
                    except Exception as e:
                        print(f"CRITICAL DB ERROR: {e}")

                # Queue attachment downloads with REAL positive IDs
                if filepath and attachments:
                    attach_dir = filepath.parent
                    for att in attachments:
                        raw_id = att.get('id')
                        att_url = att.get('url', '')
                        att_filename = att.get('filename', att.get('display_name', 'attachment'))
                        if not att_url or not raw_id:
                            continue

                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        if not isolate:
                            routing = _ENTITY_ROUTING['announcement']
                            att_filename = f"{routing['prefix']}: {self._sanitize_filename(display_name)} - {att_filename}"

                        att_file_obj = types.SimpleNamespace(
                            id=att_id,
                            url=att_url,
                            filename=att_filename,
                            display_name=att.get('display_name', att_filename),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', updated_at),
                            md5=None,
                            content_type=att.get('content-type', ''),
                            folder_id=None,
                        )

                        att_filepath = attach_dir / self._sanitize_filename(att_filename)
                        if progress_callback:
                            progress_callback(att_filename, progress_type='attachment_discovered', size=att.get('size', 0))

                        task = asyncio.create_task(self._download_file_async(
                            sem, session, att_file_obj, attach_dir,
                            progress_callback, mb_tracker, 'attachment',
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

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'discussion', title, message + self._build_discussion_replies_html_sync(topic, debug_file), base_path,
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
                        ('URL', getattr(topic, 'html_url', None)),
                    ],
                )
                
                if filepath and sync_manager:
                    try:
                        rel_path = str(filepath.relative_to(base_path)).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=syn_id,
                            canvas_filename=filepath.name,
                            local_path=rel_path,
                            canvas_updated_at=canvas_updated,
                            original_size=0,
                        )
                    except Exception:
                        pass

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

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
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
                        ('URL', getattr(quiz, 'html_url', None)),
                    ],
                )
                
                if filepath and sync_manager:
                    try:
                        rel_path = str(filepath.relative_to(base_path)).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=syn_id,
                            canvas_filename=filepath.name,
                            local_path=rel_path,
                            canvas_updated_at=canvas_updated,
                            original_size=0,
                        )
                    except Exception:
                        pass

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
                
                r_html_url = getattr(rubric, 'html_url', None)
                if r_html_url:
                    md_content += f"[View on Canvas]({r_html_url})\n\n"

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
                            local_path=rel_path,
                            canvas_updated_at=updated_at,
                            original_size=0,
                        )
                    except Exception:
                        pass

                if progress_callback:
                    progress_callback(
                        f'Saving rubric: {r_title}', progress_type='page',
                    )

        except (Unauthorized, ResourceDoesNotExist, CanvasException) as e:
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
            progress_callback(
                'Downloading Course Pages & Assignments...',
                progress_type='phase',
                phase_name='Secondary Content',
            )

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
        import plistlib
        safe_title = self._sanitize_filename(title)
        
        if platform.system() == 'Darwin':
            filename = f"{safe_title}.webloc"
            filepath = folder_path / filename
            filepath = self._handle_conflict(filepath)
        else:
            filename = f"{safe_title}.url"
            filepath = folder_path / filename
            filepath = self._handle_conflict(filepath)

        if progress_callback:
            progress_callback(f'Creating link: {title}', progress_type='link', explicit_filepath=str(filepath))

        log_debug(f"Creating Link: {title} ({url}) -> {filepath}", debug_file)

        try:
            if platform.system() == 'Darwin':
                # Binary-safe plist generation - plistlib handles all XML
                # escaping internally, making manual saxutils.escape() unnecessary.
                content = plistlib.dumps({'URL': url}, fmt=plistlib.FMT_XML)
                with open(make_long_path(filepath), 'wb') as f:
                    f.write(content)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
            else:
                safe_url = url.replace('\r', '').replace('\n', '')
                content = f'[InternetShortcut]\nURL={safe_url}'
                with open(make_long_path(filepath), 'w', encoding='utf-8') as f:
                    f.write(content)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
            # Sync Run #0: Record link/URL file to DB using deterministic canvas_item_id
            if sync_manager and course_base_path and canvas_item_id:
                try:
                    rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                    sync_manager.record_downloaded_file(
                        canvas_file_id=canvas_item_id,
                        canvas_filename=filepath.name,
                        local_path=rel_path,
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
            for _ in range(100):
                candidate = parent / f"{base}_{uuid.uuid4().hex[:8]}{ext}"
                if not candidate.exists():
                    filepath = candidate
                    break
            else:
                import logging as _log
                _log.getLogger(__name__).warning(
                    f"_handle_conflict: could not find a free name for {base}{ext} after UUID fallback"
                )
        return filepath

    def _sanitize_filename(self, filename, replace_spaces=False, max_length=120):
        if not filename: return "untitled"
        # Normalize to NFC and strip dangerous Unicode characters:
        # - Bidirectional overrides (e.g. U+202E Right-to-Left Override)
        # - Zero-width spaces and joiners
        # - BOM
        filename = unicodedata.normalize('NFC', filename)
        _DANGEROUS_UNICODE = (
            '‮', '‭', '‬', '‫', '‪',  # bidi overrides
            '​', '‌', '‍', '‎', '‏',  # zero-width
            '﻿',  # BOM
        )
        for ch in _DANGEROUS_UNICODE:
            filename = filename.replace(ch, '')
        try: filename = urllib.parse.unquote_plus(filename)
        except Exception: pass
        # Stripping path separators (/ and \) is what prevents directory traversal
        # — a Canvas filename like "../../evil" becomes "....evil" then gets
        # lstripped below. Do not remove these characters from the pattern.
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
        if replace_spaces: sanitized = sanitized.replace(' ', '_')
        sanitized = sanitized.lstrip(' _').rstrip('. _')
        
        base_upper = sanitized.split('.')[0].upper()
        if base_upper in ('CON', 'PRN', 'AUX', 'NUL') or \
           (len(base_upper) == 4 and base_upper[:-1] in ('COM', 'LPT') and base_upper[-1].isdigit()):
            sanitized = f"_{sanitized}"
            
        if len(sanitized) > max_length:
            name, ext = os.path.splitext(sanitized)
            if len(ext) > 10: sanitized = sanitized[:max_length]
            else: sanitized = name[:(max_length - len(ext))] + ext
        return sanitized if sanitized else "untitled"

    def clear_error_log(self, base_path):
        """Wipe download_errors.txt to start fresh for a new run."""
        self._logged_error_sigs = set()  # Reset dedup cache
        if not self.error_log_enabled:
            return
        if not base_path: return
        path = Path(base_path)
        log_file = path / "download_errors.txt"
        if log_file.exists():
            try:
                with _err_log_lock:
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
        if not self.error_log_enabled:
            return
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
                
            with _err_log_lock:
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
