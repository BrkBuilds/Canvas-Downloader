import os
import platform
import re
import uuid
import shutil
import html
import urllib.parse
from pathlib import Path
from canvasapi import Canvas
from canvasapi.exceptions import CanvasException
import asyncio
import aiohttp
from translations import get_text

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
        # Note: We don't catch initialization errors here, they usually happen on first request
        try:
            self.canvas = Canvas(self.api_url, self.api_key)
        except Exception:
            # If URL is completely malformed, Canvas init might fail
            self.canvas = None
            
        self.user = None

    def validate_token(self):
        """Checks if the token is valid by attempting to fetch the current user."""
        if not self.api_url or not self.canvas:
            return False, get_text('login_failed', self.language)

        try:
            # We attempt to fetch the user. This validates both the URL (connectivity)
            # and the Token (authentication) in one go.
            self.user = self.canvas.get_current_user()
            return True, get_text('logged_in_as', self.language, name=self.user.name)
        except Exception:
            # As requested: One unified error message for any failure (URL or Token)
            return False, get_text('login_failed', self.language)

    def get_courses(self, favorites_only=True):
        """Fetches courses. If favorites_only is True, fetches only favorite courses."""
        try:
            if favorites_only:
                # Lazy-load user if not already set (avoids redundant validation API call)
                if self.user is None:
                    self.user = self.canvas.get_current_user()
                # get_favorite_courses returns a PaginatedList
                courses = self.user.get_favorite_courses()
            else:
                # Optimize: Only fetch active and invited courses to speed up loading
                # Fetching 'completed' (past) courses can be very slow if there are many.
                courses = self.canvas.get_courses(enrollment_state=['active', 'invited_or_pending'])
            
            # Convert to list to ensure we can iterate easily and filter out restricted access
            course_list = []
            for course in courses:
                # Some courses might be restricted or not have a name
                if hasattr(course, 'name') and hasattr(course, 'id'):
                     course_list.append(course)
            return course_list
        except Exception as e:
            print(f"Error fetching courses: {e}")
            return []

    def count_course_items(self, course, file_filter='all'):
        """
        Counts total number of downloadable items in a course.
        This iterates through modules to count files, pages, and external links.
        """
        count = 0
        try:
            modules = course.get_modules()
            for module in modules:
                items = module.get_module_items()
                for item in items:
                    if file_filter == 'study':
                        # Strict filter: Only PDF/PPT files. Skip Pages, Links, Tools.
                        if item.type == 'File':
                            # We can't check extension easily without fetching file info, 
                            # but we can try to guess from title or content_id if needed.
                            # For accuracy, we might need to fetch file obj, but that's slow.
                            # Optimization: Just count it for now, actual filter happens at download.
                            # Or better: Don't count Pages/Links/Tools.
                            count += 1
                    elif item.type in ['File', 'Page', 'ExternalUrl', 'ExternalTool']:
                        count += 1
        except Exception as e:
            print(f"Error counting items for {course.name}: {e}")
        return count
    
    def get_course_total_size_mb(self, course, mode='modules', file_filter='all'):
        """Calculate total size in MB of all files in a course.
        Optimized to use get_files() which is faster than iterating modules.
        """
        total_bytes = 0
        allowed_exts = ['.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx']
        try:
            # Always use get_files() for size calculation as it's much faster (O(1) paginated vs O(N) modules)
            # This avoids timeouts on large courses just to get the size.
            try:
                files = course.get_files()
                for file in files:
                    if file_filter == 'study':
                        ext = os.path.splitext(getattr(file, 'filename', ''))[1].lower()
                        if ext not in allowed_exts:
                            continue
                    file_size = getattr(file, 'size', 0)
                    total_bytes += file_size
            except Exception as e:
                # Fallback to modules if get_files() is restricted (401)
                print(f"get_files() failed (likely restricted), falling back to modules: {e}")
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
                                file_size = getattr(file_obj, 'size', 0)
                                total_bytes += file_size
                            except:
                                pass
        except Exception as e:
            print(f"Error calculating course size: {e}")
        return total_bytes / (1024 * 1024)  # Convert to MB

    async def download_course_async(self, course, mode, save_dir, progress_callback=None, check_cancellation=None, file_filter='all'):
        """
        Downloads content for a single course asynchronously.
        """
        course_name = self._sanitize_filename(course.name)
        base_path = Path(save_dir) / course_name
        
        # Check disk space before starting
        # Check disk space before starting
        if not self._check_disk_space(save_dir):
            error_msg = get_text('insufficient_space', self.language)
            if progress_callback: progress_callback(error_msg)
            self._log_error(Path(save_dir), error_msg)
            return
        
        base_path.mkdir(parents=True, exist_ok=True)

        if check_cancellation and check_cancellation():
            if progress_callback: progress_callback(get_text('download_cancelled_msg', self.language))
            return
        
        # Track total MB downloaded for this course
        mb_tracker = {'bytes_downloaded': 0}

        # Semaphore to limit concurrency (Reduced to 2 for robustness)
        sem = asyncio.Semaphore(2) 
        tasks = []

        # Set timeout for all requests (5 minutes per file)
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(headers={'Authorization': f'Bearer {self.api_key}'}, timeout=timeout) as session:
            try:
                if mode == 'flat':
                    await self._download_flat_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter)
                else:
                    # Modules mode
                    # Note: get_modules is synchronous, but we can process items async
                    try:
                        # Retry logic for fetching modules (handle transient 500/timeouts)
                        modules = None
                        for attempt in range(3):
                            try:
                                modules = course.get_modules()
                                # Force iteration to trigger potential API errors immediately
                                modules = list(modules)
                                break
                            except Exception as e:
                                if attempt < 2:
                                    await asyncio.sleep(2 * (attempt + 1))
                                else:
                                    raise e

                        for module in modules:
                            if check_cancellation and check_cancellation(): break
                            
                            try:
                                module_name = self._sanitize_filename(module.name)
                                target_path = base_path / module_name
                                target_path.mkdir(parents=True, exist_ok=True)

                                items = module.get_module_items()
                                for item in items:
                                    if check_cancellation and check_cancellation(): break
                                    
                                    try:
                                        if item.type == 'File':
                                            # Validate content_id exists
                                            if not hasattr(item, 'content_id') or not item.content_id:
                                                self._log_error(base_path, get_text('missing_content_id', self.language, title=getattr(item, 'title', 'unknown')))
                                                continue
                                            # We need the file object for the URL. 
                                            # This part is still sync because canvasapi doesn't support async
                                            # But we can offload the actual download
                                            file_obj = course.get_file(item.content_id)
                                            task = asyncio.create_task(self._download_file_async(sem, session, file_obj, target_path, progress_callback, mb_tracker, file_filter))
                                            tasks.append(task)
                                        elif item.type == 'Page':
                                            if file_filter == 'study': continue # Skip pages in study mode
                                            # Validate page_url exists
                                            if not hasattr(item, 'page_url') or not item.page_url:
                                                self._log_error(base_path, get_text('missing_page_url', self.language, title=getattr(item, 'title', 'unknown')))
                                                continue
                                            page_obj = course.get_page(item.page_url)
                                            self._save_page(page_obj, target_path, progress_callback)
                                        elif item.type == 'ExternalUrl':
                                            if file_filter == 'study': continue # Skip links in study mode
                                            # Validate external_url exists
                                            if not hasattr(item, 'external_url') or not item.external_url:
                                                self._log_error(base_path, get_text('missing_external_url', self.language, title=getattr(item, 'title', 'unknown')))
                                                continue
                                            self._create_link(item.title, item.external_url, target_path, progress_callback)
                                        elif item.type == 'ExternalTool':
                                            if file_filter == 'study': continue # Skip tools in study mode
                                            # For ExternalTool (e.g. Panopto), the 'external_url' is often an LTI launch URL
                                            # which requires a POST request with signed parameters (OAuth).
                                            # A simple GET request or shortcut to this URL will fail (as seen by the user).
                                            # The best workaround is to use the 'html_url' which points to the Canvas page
                                            # where the tool is embedded. Canvas handles the LTI launch when the user visits this page.
                                            
                                            url = getattr(item, 'html_url', None)
                                            if not url:
                                                # Fallback to external_url if html_url is missing (unlikely for standard items)
                                                url = getattr(item, 'external_url', None)
                                            
                                            if not url:
                                                # Log detailed debug info
                                                try:
                                                    debug_info = {k: v for k, v in item.__dict__.items() if not k.startswith('_')}
                                                except:
                                                    debug_info = "Could not retrieve item attributes"
                                                self._log_error(base_path, f"ExternalTool '{getattr(item, 'title', 'unknown')}' missing URL. Debug info: {debug_info}")
                                                continue
                                            self._create_link(item.title, url, target_path, progress_callback)
                                    except Exception as item_e:
                                        self._log_error(base_path, get_text('error_processing_item', self.language, title=getattr(item, 'title', 'unknown'), module=module.name, error=item_e))
                            except Exception as module_e:
                                 self._log_error(base_path, get_text('error_processing_module', self.language, name=getattr(module, 'name', 'unknown'), error=module_e))
                    except Exception as e:
                        # Check for Unauthorized (401)
                        is_unauthorized = "unauthorized" in str(e).lower() or (hasattr(e, 'status_code') and e.status_code == 401)
                        
                        if is_unauthorized:
                            # Fallback to flat download
                            self._log_error(base_path, get_text('modules_unauthorized_fallback', self.language) + f" (Error: {e})")
                            if progress_callback:
                                progress_callback(get_text('modules_unauthorized_fallback', self.language))
                            
                            # Attempt flat download
                            await self._download_flat_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter)
                        else:
                            self._log_error(base_path, get_text('error_module_list', self.language, error=e))

                # Wait for all downloads to complete
                if tasks:
                    # Use return_exceptions to prevent one failure from cancelling all downloads
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    # Log any exceptions that occurred
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            self._log_error(base_path, get_text('task_failed', self.language, i=i, error=result))

            except Exception as e:
                 if "unauthorized" in str(e).lower():
                     self._log_error(base_path, get_text('course_unauthorized', self.language))
                 else:
                     self._log_error(base_path, get_text('error_processing_course', self.language, course=course_name, error=e))

    async def _download_flat_async(self, course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter='all'):
        """Helper to download files in flat structure with retry logic for 401s."""
        tasks = []
        files_access_failed = False
        
        try:
            # Retry logic for fetching file list (in case of transient 401/429)
            files = None
            for attempt in range(3):
                try:
                    files = course.get_files()
                    # Force iteration to trigger potential API errors immediately
                    files = list(files) 
                    break
                except Exception as e:
                    if attempt < 2:
                        await asyncio.sleep(2 * (attempt + 1))
                    else:
                        # If get_files fails (e.g. Access Denied), we set a flag and continue
                        # The module scan below will pick up the files instead.
                        # Suppress error log (don't create download_errors.txt for a successful fallback)
                        print(f"Could not access 'Files' tab directly (Restricted?). Falling back to Module scan. Error: {e}")
                        files_access_failed = True
                        files = [] # Empty list to skip the loop below

            for file in files:
                if check_cancellation and check_cancellation(): break
                try:
                    task = asyncio.create_task(self._download_file_async(sem, session, file, base_path, progress_callback, mb_tracker, file_filter))
                    tasks.append(task)
                except Exception as e:
                    self._log_error(base_path, f"Error queuing file {getattr(file, 'filename', 'unknown')}: {e}")
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        self._log_error(base_path, get_text('task_failed', self.language, i=i, error=result))

            # NEW: Also scan modules for non-file items (Pages, Links, ExternalTools)
            # This ensures Flat Mode includes everything, not just files.
            # AND if files_access_failed is True, we also pick up files here.
            module_tasks = []
            try:
                modules = course.get_modules()
                for module in modules:
                    if check_cancellation and check_cancellation(): break
                    try:
                        items = module.get_module_items()
                        for item in items:
                            if check_cancellation and check_cancellation(): break
                            
                            # Skip Files unless we failed to access them directly
                            if item.type == 'File' and not files_access_failed:
                                continue
                                
                            try:
                                if item.type == 'File':
                                    # Fallback for restricted files
                                    if not hasattr(item, 'content_id') or not item.content_id: continue
                                    # Need to fetch file obj individually (slower but works)
                                    file_obj = course.get_file(item.content_id)
                                    task = asyncio.create_task(self._download_file_async(sem, session, file_obj, base_path, progress_callback, mb_tracker, file_filter))
                                    module_tasks.append(task)
                                    
                                elif item.type == 'Page':
                                    if file_filter == 'study': continue
                                    if not hasattr(item, 'page_url') or not item.page_url: continue
                                    page_obj = course.get_page(item.page_url)
                                    self._save_page(page_obj, base_path, progress_callback) # Save to base_path (Flat)
                                    
                                elif item.type == 'ExternalUrl':
                                    if file_filter == 'study': continue
                                    if not hasattr(item, 'external_url') or not item.external_url: continue
                                    self._create_link(item.title, item.external_url, base_path, progress_callback)
                                    
                                elif item.type == 'ExternalTool':
                                    if file_filter == 'study': continue
                                    # Use html_url for robust Panopto handling
                                    url = getattr(item, 'html_url', None)
                                    if not url: url = getattr(item, 'external_url', None)
                                    
                                    if not url:
                                        # Log debug info but don't crash
                                        try:
                                            debug_info = {k: v for k, v in item.__dict__.items() if not k.startswith('_')}
                                        except:
                                            debug_info = "Could not retrieve item attributes"
                                        self._log_error(base_path, f"ExternalTool '{getattr(item, 'title', 'unknown')}' missing URL. Debug info: {debug_info}")
                                        continue
                                    self._create_link(item.title, url, base_path, progress_callback)
                                    
                            except Exception as item_e:
                                # Log but continue
                                self._log_error(base_path, get_text('error_processing_item', self.language, title=getattr(item, 'title', 'unknown'), module=module.name, error=item_e))
                                
                    except Exception as module_e:
                        self._log_error(base_path, get_text('error_processing_module', self.language, name=getattr(module, 'name', 'unknown'), error=module_e))
                
                # Await all module tasks
                if module_tasks:
                    results = await asyncio.gather(*module_tasks, return_exceptions=True)
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            self._log_error(base_path, get_text('task_failed', self.language, i=i, error=result))

            except Exception as e:
                # If module access fails (e.g. 401), just log it. 
                # We already got the files, so it's a partial success.
                self._log_error(base_path, f"Could not scan modules for extra items: {e}")

        except Exception as e:
            # If flat download also fails with unauthorized, then it's truly inaccessible
            is_unauthorized = "unauthorized" in str(e).lower() or (hasattr(e, 'status_code') and e.status_code == 401)
            if is_unauthorized:
                self._log_error(base_path, get_text('course_unauthorized', self.language))
            else:
                self._log_error(base_path, get_text('error_processing_course', self.language, course=course.name, error=e))

    async def _download_file_async(self, sem, session, file_obj, folder_path, progress_callback, mb_tracker=None, file_filter='all'):
        async with sem:
            filename = self._sanitize_filename(file_obj.filename)
            filepath = folder_path / filename

            # Filter check
            if file_filter == 'study':
                ext = filepath.suffix.lower()
                if ext not in ['.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx']:
                    return # Skip

            # Duplicate Prevention: Check if file exists and size matches
            file_size_bytes = getattr(file_obj, 'size', 0)
            if filepath.exists():
                try:
                    if file_size_bytes > 0 and filepath.stat().st_size == file_size_bytes:
                        # File exists and size matches - SKIP
                        return
                except:
                    pass # If stat fails, proceed to conflict handling/download

            # Conflict handling
            filepath = self._handle_conflict(filepath)
            
            # Get file size for logging
            file_size_mb = file_size_bytes / (1024 * 1024) if file_size_bytes > 0 else 0

            if progress_callback:
                progress_callback(get_text('downloading_file', self.language, filename=filename), progress_type='download')

            url = file_obj.url
            # Validate URL
            if not url or url.strip() == '':
                self._log_error(folder_path.parent, get_text('skipping_no_url', self.language, filename=filename))
                return

            # Retry logic with exponential backoff
            max_retries = 5
            base_delay = 1
            
            for attempt in range(max_retries):
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            bytes_downloaded = 0
                            with open(filepath, 'wb') as f:
                                while True:
                                    chunk = await response.content.read(1024*1024) # 1MB chunks
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    bytes_downloaded += len(chunk)  # Track bytes for this file
                                    
                                    # Update course-level MB tracker
                                    if mb_tracker is not None:
                                        mb_tracker['bytes_downloaded'] += len(chunk)
                                        if progress_callback:
                                            mb_down = mb_tracker['bytes_downloaded'] / (1024 * 1024)
                                            progress_callback("", progress_type='mb_progress', mb_downloaded=mb_down)
                            return # Success!
                        
                        elif response.status == 429: # Too Many Requests
                            wait_time = base_delay * (2 ** attempt)
                            # Check for Retry-After header
                            if 'Retry-After' in response.headers:
                                try:
                                    wait_time = int(response.headers['Retry-After'])
                                except:
                                    pass
                            await asyncio.sleep(wait_time)
                            continue # Retry
                            
                        elif 500 <= response.status < 600: # Server Error
                            wait_time = base_delay * (2 ** attempt)
                            await asyncio.sleep(wait_time)
                            continue # Retry
                            
                        else:
                            # Other errors (404, 403, etc.) - do not retry
                            self._log_error(folder_path.parent, get_text('download_failed_http', self.language, filename=filename, status=response.status))
                            return

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt < max_retries - 1:
                        wait_time = base_delay * (2 ** attempt)
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        import traceback
                        error_details = traceback.format_exc()
                        self._log_error(folder_path.parent, get_text('download_failed_exc', self.language, filename=filename, error_type=type(e).__name__, error=f"{e}\n{error_details}"))
                        return
                except Exception as e:
                    # Non-network errors (e.g. file write) - do not retry
                    import traceback
                    error_details = traceback.format_exc()
                    self._log_error(folder_path.parent, get_text('download_failed_exc', self.language, filename=filename, error_type=type(e).__name__, error=f"{e}\n{error_details}"))
                    return

    # Keep sync versions for non-file items or fallback
    def _save_page(self, page_obj, folder_path, progress_callback):
        # Define safe_title first for use in callbacks and file operations
        safe_title = html.escape(page_obj.title) if hasattr(page_obj, 'title') else 'Untitled'
        filename = self._sanitize_filename(page_obj.title if hasattr(page_obj, 'title') else 'Untitled') + ".html"
        filepath = folder_path / filename
        filepath = self._handle_conflict(filepath)

        if progress_callback:
            progress_callback(get_text('saving_page', self.language, title=safe_title), progress_type='page')

        try:
            # Basic HTML wrapper with escaped title
            body_content = page_obj.body if hasattr(page_obj, 'body') else ''
            content = f"<html><head><title>{safe_title}</title></head><body><h1>{safe_title}</h1>{body_content}</body></html>"
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            self._log_error(folder_path.parent, get_text('save_page_failed', self.language, title=safe_title, error=e))

    def _create_link(self, title, url, folder_path, progress_callback):
        safe_title = self._sanitize_filename(title)
        
        if platform.system() == 'Darwin': # macOS
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
        else: # Windows and others
            filename = f"{safe_title}.url"
            filepath = folder_path / filename
            filepath = self._handle_conflict(filepath)
            content = f'[InternetShortcut]\nURL={url}'

        if progress_callback:
            progress_callback(get_text('creating_link', self.language, title=title), progress_type='link')

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            self._log_error(folder_path.parent, get_text('create_link_failed', self.language, title=title, error=e))

    def _handle_conflict(self, filepath):
        if not filepath.exists():
            return filepath
        
        # If exists, rename to "Name (1).ext"
        base = filepath.stem
        ext = filepath.suffix
        parent = filepath.parent
        counter = 1
        max_attempts = 1000  # Prevent infinite loop
        
        while filepath.exists() and counter < max_attempts:
            new_name = f"{base} ({counter}){ext}"
            filepath = parent / new_name
            counter += 1
        
        # If we hit max attempts, use UUID to avoid any conflict
        if counter >= max_attempts:
            unique_id = str(uuid.uuid4())[:8]
            new_name = f"{base}_{unique_id}{ext}"
            filepath = parent / new_name
        
        return filepath

    def _sanitize_filename(self, filename, replace_spaces=False, max_length=120):
        """Removes illegal characters from filenames while preserving Unicode.
        
        Args:
            filename: The filename to sanitize (may be URL-encoded)
            replace_spaces: If True, replace spaces with underscores for better readability
            max_length: Maximum length of the filename (default 120 to prevent Windows MAX_PATH issues)
        """
        if not filename:
            return "untitled"
        
        # URL-decode the filename to handle Canvas API encoding
        # %C3%98 -> Ø, + -> space, etc.
        try:
            filename = urllib.parse.unquote_plus(filename)
        except Exception:
            pass  # If decoding fails, use original filename
        
        # Only remove characters that are truly invalid in Windows/Unix: <>:"/\|?*
        # Also remove control characters
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
        
        # Replace spaces with underscores if requested (better readability)
        if replace_spaces:
            sanitized = sanitized.replace(' ', '_')
        
        sanitized = sanitized.strip('. _')  # Remove leading/trailing dots, spaces, and underscores
        
        # Truncate to max_length (preserving extension if possible)
        if len(sanitized) > max_length:
            name, ext = os.path.splitext(sanitized)
            # If extension is too long, just truncate the whole thing
            if len(ext) > 10:
                sanitized = sanitized[:max_length]
            else:
                # Truncate name part, keep extension
                max_name_len = max_length - len(ext)
                sanitized = name[:max_name_len] + ext
                
        return sanitized if sanitized else "untitled"

    def _log_error(self, base_path, message):
        error_file = base_path / "download_errors.txt"
        try:
            with open(error_file, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception as e:
            # Print to stderr as fallback if we can't write to file
            print(f"Error logging failed: {e}. Original message: {message}", file=__import__('sys').stderr)
    
    def _check_disk_space(self, path, min_free_gb=1):
        """Check if there's enough disk space available."""
        try:
            stat = shutil.disk_usage(path)
            free_gb = stat.free / (1024**3)
            return free_gb >= min_free_gb
        except Exception:
            # If we can't check, assume there's enough space
            return True
