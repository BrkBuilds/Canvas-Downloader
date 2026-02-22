import os
import platform
import re
import uuid
import shutil
import html
import urllib.parse
import traceback
from pathlib import Path
from datetime import datetime
from canvasapi import Canvas
from canvasapi.exceptions import CanvasException, Unauthorized, ResourceDoesNotExist
import asyncio
import aiohttp
from translations import get_text
from canvas_debug import log_debug, clear_debug_log
import logging

from sync_manager import SyncManager, CanvasFileInfo

logger = logging.getLogger(__name__)

# --- Constants ---
MAX_RETRIES = 5
TIMEOUT_SECONDS = 300
RETRY_DELAY = 1

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
    def __init__(self, api_key, api_url, language='en'):
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
            
        self.language = language
        # Initialize Canvas object
        try:
            self.canvas = Canvas(self.api_url, self.api_key)
        except Exception:
            # If URL is completely malformed, Canvas init might fail immediately
            self.canvas = None
            
        self.user = None

    def validate_token(self):
        """Checks if the token is valid by attempting to fetch the current user."""
        if not self.api_url or not self.canvas:
            return False, get_text('login_failed', self.language)

        try:
            # We attempt to fetch the user. This validates both the URL and Token.
            self.user = self.canvas.get_current_user()
            return True, get_text('logged_in_as', self.language, name=self.user.name)
        except Exception as e:
            # Return specific message if possible, else generic
            msg = str(e) if str(e) else get_text('login_failed', self.language)
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

    def get_course_files_metadata(self, course):
        """
        Fetch metadata for all files in a course using a robust Hybrid strategy.
        
        Strategy:
        1. Try to fetch all files using `course.get_files()`. This is the primary source.
           - If it fails mid-stream, we CATCH the error but KEEP the files found so far.
        2. Always run a secondary scan of Modules to find files that might be locked/hidden 
           or were missed due to the error in step 1.
        3. Deduplicate by File ID.
        
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
            module_files = self._get_files_from_modules(course)
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
            # If BOTH failed and wfe have 0 files, we might want to raise, 
            # but usually returning empty list is safer for UI than crashing.
            
        return list(all_files_map.values())
    
    def _get_files_from_modules(self, course):
        """Fallback: Get files by iterating through modules."""
        from sync_manager import CanvasFileInfo
        
        files = []
        modules = course.get_modules()
        for module in modules:
            items = module.get_module_items()
            for item in items:
                if item.type == 'File':
                    if not hasattr(item, 'content_id') or not item.content_id:
                        continue
                    try:
                        file = course.get_file(item.content_id)
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
        return files

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
                            except:
                                pass
        except Exception:
            pass
        return total_bytes / (1024 * 1024)

    async def download_course_async(self, course, mode, save_dir, progress_callback=None, check_cancellation=None, file_filter='all', debug_mode=False):
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
                get_text('insufficient_space', self.language)
            )
            if progress_callback: progress_callback(error, progress_type='error')
            self._log_error(save_dir, error)
            return
        
        base_path.mkdir(parents=True, exist_ok=True)

        if check_cancellation and check_cancellation():
            if progress_callback: progress_callback(get_text('download_cancelled_msg', self.language))
            return
        
        debug_file = (Path(save_dir) / "debug_log.txt") if debug_mode else None
        if debug_mode:
            clear_debug_log(debug_file)
            log_debug(f"Starting download for course: {course.name} (ID: {course.id}) Mode: {mode}", debug_file)
            log_debug(f"Save Dir: {save_dir}", debug_file)

        downloaded_file_ids = set()
        mb_tracker = {'bytes_downloaded': 0}
        
        # Determine semaphore limit from session state if available, default to 5
        import streamlit as st
        concurrent_limit = st.session_state.get('concurrent_downloads', 5)
        sem = asyncio.Semaphore(concurrent_limit)
        
        tasks = []
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)

        async with aiohttp.ClientSession(headers={'Authorization': f'Bearer {self.api_key}'}, timeout=timeout) as session:
            downloaded_files_info = []
            
            try:
                if mode == 'flat':
                    downloaded_files_info = await self._download_flat_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter, error_root_path=Path(save_dir), debug_file=debug_file)
                elif mode == 'files':
                    downloaded_files_info = await self._download_folders_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter, error_root_path=Path(save_dir), debug_file=debug_file)
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
                                            err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing Content ID", get_text('missing_content_id', self.language, title=getattr(item, 'title', 'unknown')))
                                            if progress_callback: progress_callback(err, progress_type='error')
                                            self._log_error(save_dir, err)
                                            continue
                                        
                                        file_obj = course.get_file(item.content_id)
                                        downloaded_file_ids.add(file_obj.id)
                                        log_debug(f"Module file tracked: {file_obj.filename} (ID: {file_obj.id})", debug_file)
                                        task = asyncio.create_task(self._download_file_async(
                                            sem, session, file_obj, target_path, progress_callback, mb_tracker, file_filter, 
                                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file
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
                                        self._save_page(page_obj, target_path, progress_callback, error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file)
                                    
                                    elif item.type == 'ExternalUrl':
                                        if file_filter == 'study': continue
                                        if not hasattr(item, 'external_url') or not item.external_url:
                                             # Error
                                             err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing External URL", "Link has no URL")
                                             if progress_callback: progress_callback(err, progress_type='error')
                                             self._log_error(save_dir, err)
                                             continue
                                        self._create_link(item.title, item.external_url, target_path, progress_callback, error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file)
                                    
                                    elif item.type == 'ExternalTool':
                                        if file_filter == 'study': continue
                                        url = getattr(item, 'html_url', None) or getattr(item, 'external_url', None)
                                        if not url:
                                             err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing Tool URL", "External Tool missing launch URL")
                                             if progress_callback: progress_callback(err, progress_type='error')
                                             self._log_error(save_dir, err)
                                             continue
                                        self._create_link(item.title, url, target_path, progress_callback, error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file)
                                        
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
                    if progress_callback: progress_callback(get_text('scanning_remaining_files', self.language), progress_type='log')
                    
                    all_files = course.get_files()
                    all_files = list(all_files)
                    catch_all_tasks = []

                    for file in all_files:
                        if check_cancellation and check_cancellation(): break
                        
                        if file.id in downloaded_file_ids:
                            log_debug(f"Catch-All skipping module file: {file.filename} (ID: {file.id})", debug_file)
                            continue # Already downloaded in a module
                        
                        log_debug(f"Catch-All found new file: {file.filename} (ID: {file.id})", debug_file)
                        
                        # Download to course root
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, file, base_path, progress_callback, mb_tracker, file_filter, 
                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file
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
                     err = DownloadError(course.name, "Catch-All Scan", "Hybrid Mode Error", str(e), raw_error=e)
                     self._log_error(save_dir, err)
                # ---- HYBRID MODE CATCH-ALL ENDED ----

            except Exception as e:
                 is_unauthorized = "unauthorized" in str(e).lower() or (hasattr(e, 'status_code') and e.status_code == 401)
                 if is_unauthorized and mode != 'flat':
                     # Fallback to flat
                     msg = get_text('modules_unauthorized_fallback', self.language)
                     if progress_callback: progress_callback(msg, progress_type='log')
                     # Log the partial failure
                     err = DownloadError(course.name, "Modules Access", "401 Unauthorized", "Modules locked, falling back to file scan.", raw_error=e)
                     self._log_error(save_dir, err)
                     
                     downloaded_files_info.extend(await self._download_flat_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter, error_root_path=Path(save_dir), debug_file=debug_file))
                 else:
                     err = DownloadError(course.name, "Course Download", "Processing Error", str(e), raw_error=e)
                     if progress_callback: progress_callback(err, progress_type='error')
                     self._log_error(save_dir, err)
            
            # --- Generate Manifest ---
            try:
                log_debug(f"Manifest generation: {len(downloaded_files_info)} files collected.", debug_file)
                
                if downloaded_files_info:
                    sm = SyncManager(base_path, course.id, course.name, self.language)
                    sm.create_initial_manifest(downloaded_files_info)
                    log_debug(f"Manifest created successfully with {len(downloaded_files_info)} entries.", debug_file)
                else:
                    log_debug("WARNING: No downloaded files info collected. Manifest skipped.", debug_file)
            except Exception as e:
                logger.error(f"Failed to create initial manifest: {e}")
                log_debug(f"ERROR creating manifest: {e}", debug_file)


    async def _download_folders_async(self, course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter='all', error_root_path=None, debug_file=None):
        """Downloads files preserving actual folder structure."""
        tasks = []
        downloaded = []
        folder_map = {}
        log_debug(f"Starting Folders Download for {course.name}", debug_file)

        # 1. Fetch Folders
        try:
            if progress_callback: progress_callback(get_text('fetching_folders', self.language))
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
            if progress_callback: progress_callback(get_text('fetching_files_list', self.language))
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
                    target_path.mkdir(parents=True, exist_ok=True)
                    
                    task = asyncio.create_task(self._download_file_async(
                        sem, session, file, target_path, progress_callback, mb_tracker, file_filter, 
                        error_root_path=error_root_path, course_name=course.name, debug_file=debug_file
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

    async def _download_flat_async(self, course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter='all', error_root_path=None, debug_file=None):
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

            for file in files:
                if check_cancellation and check_cancellation(): break
                try:
                    task = asyncio.create_task(self._download_file_async(
                        sem, session, file, base_path, progress_callback, mb_tracker, file_filter, 
                        error_root_path=error_root_path, course_name=course.name, debug_file=debug_file
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
                        
                        if item.type == 'File' and not files_access_failed: continue

                        try:
                            log_debug(f"  Fallback Item: {getattr(item, 'title', 'unknown')} (Type: {getattr(item, 'type', 'unknown')})", debug_file)
                            if item.type == 'File':
                                if not hasattr(item, 'content_id') or not item.content_id: continue
                                file_obj = course.get_file(item.content_id)
                                task = asyncio.create_task(self._download_file_async(
                                    sem, session, file_obj, base_path, progress_callback, mb_tracker, file_filter, 
                                    error_root_path=error_root_path, course_name=course.name, debug_file=debug_file
                                ))
                                module_tasks.append(task)
                            elif item.type == 'Page':
                                if file_filter == 'study': continue
                                if not hasattr(item, 'page_url') or not item.page_url: continue
                                page_obj = course.get_page(item.page_url)
                                self._save_page(page_obj, base_path, progress_callback, error_root_path=error_root_path, course_name=course.name, debug_file=debug_file)
                            elif item.type in ['ExternalUrl', 'ExternalTool']:
                                if file_filter == 'study': continue
                                url = getattr(item, 'external_url', None)
                                if item.type == 'ExternalTool':
                                     url = getattr(item, 'html_url', None) or url
                                if url:
                                    self._create_link(item.title, url, base_path, progress_callback, error_root_path=error_root_path, course_name=course.name, debug_file=debug_file)
                        except Exception as e:
                             pass # Logging every single item error in fallback scan might spam? 
                             # Let's log unique ones? 
                             # For flat scan, we want to know failures.
                             # err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Fallback Scan Error", str(e))
                             # if progress_callback: progress_callback(err, progress_type='error')
                             # self._log_error(error_root_path, err)

                if module_tasks:
                   module_results = await asyncio.gather(*module_tasks, return_exceptions=True)
                   for result in module_results:
                       if isinstance(result, Exception):
                           err = DownloadError(course.name, "Fallback File Task", "Async Error", str(result), raw_error=result)
                           if progress_callback: progress_callback(err, progress_type='error')
                           self._log_error(error_root_path, err)
                       elif result:
                           downloaded.append(result)

            except Exception:
                pass # Module scan failed

        except Exception as e:
             err = DownloadError(course.name, "Flat Download", "Fatal Error", str(e), raw_error=e)
             if progress_callback: progress_callback(err, progress_type='error')
             self._log_error(error_root_path, err)
        
        return downloaded

    async def _download_file_async(self, sem, session, file_obj, folder_path, progress_callback, mb_tracker=None, file_filter='all', error_root_path=None, course_name="Unknown", debug_file=None):
        async with sem:
            filename = self._sanitize_filename(file_obj.filename)
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
                except:
                    pass

            filepath = self._handle_conflict(filepath)
            
            if progress_callback:
                progress_callback(get_text('downloading_file', self.language, filename=filename), progress_type='download')

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

            import aiofiles

            for attempt in range(MAX_RETRIES):
                try:
                    log_debug(f"Requesting URL: {url} (Attempt {attempt+1})", debug_file)
                    async with session.get(url) as response:
                        log_debug(f"Response Status: {response.status} Content-Type: {response.headers.get('Content-Type', 'unknown')}", debug_file)
                        if response.status == 200:
                            try:
                                async with aiofiles.open(filepath, 'wb') as f:
                                    total_bytes = 0
                                    while True:
                                        chunk = await response.content.read(1024*1024)
                                        if not chunk: break
                                        await f.write(chunk)
                                        total_bytes += len(chunk)
                                        
                                        if mb_tracker:
                                            mb_tracker['bytes_downloaded'] += len(chunk)
                                            if progress_callback:
                                                mb_down = mb_tracker['bytes_downloaded'] / (1024 * 1024)
                                                progress_callback("", progress_type='mb_progress', mb_downloaded=mb_down)
                                    
                                    # Verify download completeness
                                    if file_size_bytes > 0 and total_bytes != file_size_bytes:
                                        # Incomplete download
                                        raise Exception(f"Download incomplete. Expected {file_size_bytes} bytes, got {total_bytes} bytes.")
                                        
                                    log_debug(f"File Saved: {filepath} ({total_bytes} bytes)", debug_file)
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

                            except Exception as e:
                                # Cleanup partial file
                                if filepath.exists():
                                    try:
                                        filepath.unlink()
                                        log_debug(f"Deleted partial file: {filepath}", debug_file)
                                    except:
                                        pass
                                raise e

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

    def _save_page(self, page_obj, folder_path, progress_callback, error_root_path=None, course_name="Unknown", debug_file=None):
        safe_title = html.escape(page_obj.title) if hasattr(page_obj, 'title') else 'Untitled'
        filename = self._sanitize_filename(page_obj.title if hasattr(page_obj, 'title') else 'Untitled') + ".html"
        filepath = folder_path / filename
        filepath = self._handle_conflict(filepath)

        if progress_callback:
            progress_callback(get_text('saving_page', self.language, title=safe_title), progress_type='page')
        
        log_debug(f"Saving Page: {safe_title} -> {filepath}", debug_file)

        try:
            body_content = page_obj.body if hasattr(page_obj, 'body') else ''
            content = f"<html><head><title>{safe_title}</title></head><body><h1>{safe_title}</h1>{body_content}</body></html>"
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            err = DownloadError(course_name, safe_title, "Page Save Error", str(e), raw_error=e)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            log_debug(f"Error saving page: {e}", debug_file)

    def _create_link(self, title, url, folder_path, progress_callback, error_root_path=None, course_name="Unknown", debug_file=None):
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
	<string>{url}</string>
</dict>
</plist>
'''
        else:
            filename = f"{safe_title}.url"
            filepath = folder_path / filename
            filepath = self._handle_conflict(filepath)
            content = f'[InternetShortcut]\nURL={url}'

        if progress_callback:
            progress_callback(get_text('creating_link', self.language, title=title), progress_type='link')

        log_debug(f"Creating Link: {title} ({url}) -> {filepath}", debug_file)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            err = DownloadError(course_name, title, "Link Creation Error", str(e), raw_error=e)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            log_debug(f"Error creating link: {e}", debug_file)

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
        except: pass
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
        if replace_spaces: sanitized = sanitized.replace(' ', '_')
        sanitized = sanitized.strip('. _')
        if len(sanitized) > max_length:
            name, ext = os.path.splitext(sanitized)
            if len(ext) > 10: sanitized = sanitized[:max_length]
            else: sanitized = name[:(max_length - len(ext))] + ext
        return sanitized if sanitized else "untitled"

    def _log_error(self, base_path, error):
        """Log structured error to a single file in the root path."""
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
        except:
            # Last resort fallback if logging fails
            pass

    def _check_disk_space(self, path, min_free_gb=1):
        try:
            stat = shutil.disk_usage(path)
            return (stat.free / (1024**3)) >= min_free_gb
        except:
            return True
