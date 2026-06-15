"""
UI Helper utilities for Canvas LMS Batch File Downloader.
Shared helpers used by both download and sync modes.
"""

import functools
import html
import logging
import os
import re
import json
import shutil
import sys
import tempfile
import time
import platform
import subprocess
from contextlib import contextmanager
from pathlib import Path
import threading
import uuid

import urllib.parse
import base64
import unicodedata

from sync_manager import format_file_size  # re-exported for ui.sync_review / ui.sync_confirmation  # noqa: F401

_sync_pairs_lock = threading.RLock()
_err_log_lock = threading.Lock()

logger = logging.getLogger(__name__)

def resolve_path(path):
    """Resolve path for frozen (PyInstaller) vs normal execution."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), path)

@functools.lru_cache(maxsize=128)
def _get_base64_image_cached(image_path: str) -> str:
    """Cached disk read - only called on success; exceptions propagate uncached."""
    with open(resolve_path(image_path), "rb") as f:
        return base64.b64encode(f.read()).decode()


def get_base64_image(image_path) -> str:
    """Reads a local file and returns its Base64 string representation.

    Successes are cached (assets are static at runtime). Failures are NOT
    cached so that a missing asset during startup doesn't permanently break
    subsequent renders after the asset becomes available (M-20).
    """
    try:
        return _get_base64_image_cached(str(image_path))
    except Exception as e:
        logger.error(f"Failed to encode image {image_path}: {e}")
        return ""




def make_long_path(p: str | Path) -> str:
    """Prepend Windows long path prefix to absolute paths to prevent WinError 206."""
    s = str(p)
    if os.name == 'nt' and Path(p).is_absolute() and not s.startswith('\\\\?\\'):
        return '\\\\?\\' + s
    return s


# ── Temp File Shadowing for Office COM APIs ────────────────────────────

_MAX_PATH_THRESHOLD = 240  # 15-char safety margin below Win32 MAX_PATH (255)


@contextmanager
def office_safe_path(original_path: Path):
    """Shadow long Windows paths into a temp dir for Office COM APIs.

    Win32 COM APIs (PowerPoint, Word, Excel) hard-crash when given file
    paths >= 255 characters.  This context manager transparently copies
    the source file to a short temp path, yields the safe paths for COM
    to work with, and moves the generated PDF result back on exit.

    On short paths (< 240 chars) the context manager is a zero-cost
    pass-through that yields the original paths unchanged.

    Yields:
        (safe_source_path: Path, safe_pdf_target: Path, original_pdf_target: Path)
        - The first two are what COM should receive. The third is the true
          long-path destination where the PDF ultimately belongs.
    """
    resolved = original_path.resolve()
    original_pdf = original_path.with_suffix('.pdf')

    # macOS/Linux: MAX_PATH is not a concern - always pass-through.
    # This context manager exists exclusively for Win32 COM API limitations.
    if platform.system() != 'Windows':
        yield original_path, original_pdf, original_pdf
        return

    if len(str(resolved)) < _MAX_PATH_THRESHOLD:
        # Short path - pass-through, zero overhead
        yield original_path, original_pdf, original_pdf
        return

    # ── Long path detected: shadow into temp directory ──
    suffix = original_path.suffix  # e.g. '.pptx'
    short_name = f"canvas_{uuid.uuid4().hex[:12]}"
    temp_dir = Path(tempfile.gettempdir())
    temp_source = temp_dir / f"{short_name}{suffix}"
    temp_pdf = temp_dir / f"{short_name}.pdf"

    try:
        # Copy the source file to the short temp path
        shutil.copy2(str(resolved), str(temp_source))
        logger.debug(
            f"[Path Shadow] Shadowed long path ({len(str(resolved))} chars) "
            f"to temp: {temp_source.name}"
        )

        yield temp_source, temp_pdf, original_pdf

    finally:
        try:
            # ── Ghost PDF Guard: only move if COM actually produced a PDF ──
            if temp_pdf.exists():
                try:
                    # Ensure the true destination directory exists
                    original_pdf.parent.mkdir(parents=True, exist_ok=True)
                    # Cross-drive safe move with overwrite
                    shutil.move(str(temp_pdf), str(original_pdf))
                    logger.debug(
                        f"[Path Shadow] Moved PDF back: {temp_pdf.name} → "
                        f"{original_pdf.name}"
                    )
                except Exception as e:
                    logger.error(
                        f"[Path Shadow] Failed to move PDF back from temp: {e}"
                    )
            else:
                logger.debug(
                    "[Path Shadow] No temp PDF generated (COM conversion failed), "
                    "skipping move-back."
                )
        finally:
            # ── Unconditional cleanup of both temp files ──
            temp_source.unlink(missing_ok=True)
            temp_pdf.unlink(missing_ok=True)


def esc(value) -> str:
    """HTML-escape a value for safe interpolation into unsafe_allow_html markup."""
    return html.escape(str(value), quote=True)

def robust_filename_normalize(name: str) -> str:
    """Normalize filename for robust comparison (unquote, strip, lower, NFC)."""
    if not name:
        return ""
    try:
        # Handle potential non-string input safely
        val = urllib.parse.unquote_plus(str(name)).strip().lower()
    except Exception:
        val = str(name).strip().lower()
    return unicodedata.normalize('NFC', val)


# --- Pluralization ---


# --- Config Paths ---

SYNC_PAIRS_FILENAME = "canvas_sync_pairs.json"


def get_config_dir() -> str:
    """Get the directory where config files are stored.

    On macOS frozen bundles:  ~/Library/Application Support/CanvasDownloader/
    On Windows frozen EXEs:   %APPDATA%/CanvasDownloader/
    When running as script:   same directory as this source file
    """
    if getattr(sys, 'frozen', False) and platform.system() == 'Darwin':
        base = Path.home() / 'Library' / 'Application Support' / 'CanvasDownloader'
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create Darwin config directory {base}: {e}. Falling back to temp.")
            base = Path(tempfile.gettempdir()) / 'CanvasDownloader'
            base.mkdir(parents=True, exist_ok=True)
        return str(base)
    elif getattr(sys, 'frozen', False) and platform.system() == 'Windows':
        appdata = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
        base = Path(appdata) / 'CanvasDownloader'
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create Windows config directory {base}: {e}. Falling back to temp.")
            base = Path(tempfile.gettempdir()) / 'CanvasDownloader'
            base.mkdir(parents=True, exist_ok=True)
        return str(base)
    elif getattr(sys, 'frozen', False):
        # Other frozen platforms: fall back to executable directory
        return os.path.dirname(sys.executable)
    else:
        return str(Path(__file__).parent)

def format_time_display(time_str: str) -> str:
    """Format a 24-hour HH:MM time string respecting the user's 12h/24h preference.

    Reads ``st.session_state['use_12h_format']`` (default ``False`` = 24-hour).
    When the toggle is on, converts e.g. ``'14:30'`` → ``'2:30 PM'``.
    Returns the original string unchanged on parse error or when 24h is selected.
    """
    try:
        import streamlit as st
        if not st.session_state.get('use_12h_format', False):
            return time_str
    except Exception:
        return time_str

    from datetime import datetime as _dt
    try:
        parsed = _dt.strptime(time_str, '%H:%M')
        return parsed.strftime('%I:%M %p').lstrip('0')
    except Exception:
        return time_str


def format_relative_date(raw_time: str, include_time: bool = False, include_emoji: bool = False) -> str:
    """Format a timestamp string (YYYY-MM-DD HH:MM) into a friendly relative date.
    
    Conventions:
    - Under 1 hour: "15 minutes ago" (No exact time needed)
    - Same day: "Today at 14:30"
    - Previous day: "Yesterday at 09:15"
    - Within the last 7 days: "Thursday at 16:45"
    - More than 7 days ago (current year): "24 Apr at 11:20"
    - Previous year: "12 Nov 2025"
    """
    from datetime import datetime, timezone
    try:
        # Primary format written by save_manifest and _save_metadata after C-5 fix.
        # Fallback chain handles legacy UTC ISO strings that may exist in older DBs.
        dt = None
        for _fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(raw_time, _fmt)
                if dt.tzinfo is not None:
                    # Convert UTC-aware datetime to naive local time for comparison
                    dt = dt.astimezone().replace(tzinfo=None)
                break
            except ValueError:
                continue
        if dt is None:
            return raw_time
        now = datetime.now()
        
        diff_total_seconds = (now - dt).total_seconds()
        diff_days = (now.date() - dt.date()).days
        time_str = format_time_display(dt.strftime('%H:%M'))
        
        if diff_total_seconds < 3600 and diff_total_seconds >= 0:
            minutes = int(diff_total_seconds // 60)
            if minutes == 0:
                date_key = "just now"
            elif minutes == 1:
                date_key = "1 minute ago"
            else:
                date_key = f"{minutes} minutes ago"
            include_time = False
        elif diff_days == 0:
            date_key = "Today"
        elif diff_days == 1:
            date_key = "Yesterday"
        elif diff_days < 7 and diff_days > 0:
            date_key = dt.strftime('%A')
        elif dt.year == now.year:
            import streamlit as _st
            if _st.session_state.get('use_12h_format', False):
                date_key = f"{dt.strftime('%b')} {dt.day}"       # American: "Apr 24"
            else:
                date_key = f"{dt.day} {dt.strftime('%b')}"       # European: "24 Apr"
        else:
            import streamlit as _st
            if _st.session_state.get('use_12h_format', False):
                date_key = f"{dt.strftime('%b')} {dt.day}, {dt.year}"  # American: "Nov 12, 2025"
            else:
                date_key = f"{dt.day} {dt.strftime('%b')} {dt.year}"   # European: "12 Nov 2025"
            include_time = False
            
        parts = []
        if include_emoji:
            parts.append("📅")
        parts.append(date_key)
        if include_time:
            parts.append(f"at {time_str}")
            
        return " ".join(parts)
    except Exception as _frd_exc:
        import logging as _logging
        _logging.getLogger(__name__).debug(
            f"format_relative_date: could not parse %r: %s", raw_time, _frd_exc
        )
        return raw_time


# --- Persistent Sync Pairs ---

def load_sync_pairs(config_dir: str = None) -> list[dict]:
    """Load saved sync pairs from disk.
    
    Returns:
        List of dicts with keys: local_folder, course_id, course_name, last_synced
    """
    if config_dir is None:
        config_dir = get_config_dir()
    
    path = Path(config_dir) / SYNC_PAIRS_FILENAME
    
    with _sync_pairs_lock:
        if not path.exists():
            return []
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                pairs = json.load(f)
            # Validate structure
            if not isinstance(pairs, list):
                return []
            return pairs
        except (json.JSONDecodeError, IOError):
            return []


def atomic_update_sync_pairs(modifier_func: callable, config_dir: str = None) -> list[dict]:
    """Atomically update sync pairs, solving TOCTOU race conditions.
    
    Args:
        modifier_func: A callable that takes the current list of pairs and returns the new list.
        config_dir: Config directory path
        
    Returns:
        The updated list of pairs.
    """
    if config_dir is None:
        config_dir = get_config_dir()
        
    path = Path(config_dir) / SYNC_PAIRS_FILENAME
    temp_path = path.with_suffix('.tmp')
    
    with _sync_pairs_lock:
        # 1. READ
        pairs = []
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        pairs = data
            except (json.JSONDecodeError, IOError):
                pass
                
        # 2. MODIFY
        new_pairs = modifier_func(pairs)
        
        # 3. WRITE
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(new_pairs, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            return new_pairs
        except OSError as e:
            logging.getLogger(__name__).warning(f"Failed to save sync pairs: {e}")
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            # Return what's currently on disk so callers don't act on uncommitted data (M-22).
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                except Exception:
                    pass
            return pairs


# --- Disk Space ---

def check_disk_space(path: str, required_bytes: int = 0, min_free_gb: float = 1.0) -> tuple[bool, float, float]:
    """Check if there's enough disk space.
    
    Uses dynamic threshold: max(min_free_gb, required_bytes * 1.2).
    This ensures large downloads (e.g., 10GB course) are properly accounted for
    instead of only checking against a static 1GB minimum.
    
    Args:
        path: Path on the target volume
        required_bytes: Bytes needed for the download payload
        min_free_gb: Minimum free space floor in GB
        
    Returns:
        Tuple of (has_enough_space, available_mb, total_mb)
    """
    try:
        check_path = Path(path).resolve()
        # Find the first existing parent directory
        while not check_path.exists() and check_path.parent != check_path:
            check_path = check_path.parent
            
        if not check_path.exists():
            # If we still can't find an existing path (e.g. invalid drive), assume okay
            return True, -1, -1
            
        stat = shutil.disk_usage(str(check_path))
        available_mb = stat.free / (1024 * 1024)
        total_mb = stat.total / (1024 * 1024)
        # Dynamic threshold: at least min_free_gb, or payload + 20% buffer
        min_required = max(min_free_gb * 1024 * 1024 * 1024, int(required_bytes * 1.2))
        has_enough = stat.free >= min_required
        return has_enough, available_mb, total_mb
    except OSError as e:
        logger.warning(f"Could not check disk space at {path!r}: {e}")
        return True, -1, -1
    except Exception as e:
        logger.warning(f"Unexpected error checking disk space: {e}")
        return True, -1, -1


# --- Folder Opener ---

def native_folder_picker(initial_dir: str | None = None) -> str | None:
    """Open native folder picker dialog safely across threads inside Streamlit.
    Builds the Tkinter root with correct attributes, destroys it on close,
    and handles missing assets gracefully.

    Args:
        initial_dir: Preferred starting directory. Falls back to default_download_path
                     session state, then the user's Downloads folder.
    Returns:
        Absolute path to selected folder as string, or None if cancelled.
    """
    # Resolve the best starting directory: given path → session default → Downloads
    start_dir: str | None = None
    if initial_dir and os.path.isdir(initial_dir):
        start_dir = initial_dir
    if start_dir is None:
        try:
            import streamlit as st
            default = st.session_state.get('default_download_path', '') or ''
            if default and os.path.isdir(default):
                start_dir = default
        except Exception:
            pass
    if start_dir is None:
        downloads = str(Path.home() / 'Downloads')
        start_dir = downloads if os.path.isdir(downloads) else str(Path.home())

    import platform
    if platform.system() == 'Darwin':
        import subprocess
        try:
            # Escape backslash, double-quote, and newline so a path containing
            # any of these can never break out of the AppleScript string literal.
            safe_dir = (
                start_dir.replace('\\', '\\\\')
                         .replace('"', '\\"')
                         .replace('\n', ' ')
                         .replace('\r', ' ')
            )
            script = f'POSIX path of (choose folder default location (POSIX file "{safe_dir}"))'
            # No timeout: the user may take an arbitrarily long time to choose
            # a folder.  A subprocess.TimeoutExpired here would silently
            # cancel the picker mid-interaction.
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            return None
        except Exception:
            return None

    # Tkinter is mandatory for the Windows folder picker. tk.Tk() will raise
    # tkinter.TclError if no display is available (headless container, broken
    # X server on Linux, etc.). Wrap the whole construction so a missing GUI
    # surfaces as "no folder selected" instead of crashing the script thread.
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        logger.warning(f"tkinter not available for folder picker: {e}")
        return None

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)

        try:
            icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'icon.ico')
            if os.path.exists(icon_path):
                root.iconbitmap(icon_path)
        except Exception:
            pass

        folder_path = filedialog.askdirectory(master=root, initialdir=start_dir)
        return folder_path if folder_path else None
    except Exception as e:
        logger.warning(f"Folder picker failed: {e}")
        return None
    finally:
        # Always destroy the Tk root so it can never leak across Streamlit reruns.
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass

def open_folder(path: str):
    """
    Opens a folder in the native file explorer and forces it to the foreground.
    """

    path = os.path.normpath(path)
    if not os.path.exists(path):
        return

    sys_platform = platform.system()
    
    if sys_platform == "Windows":
        try:
            os.startfile(path)
        except OSError as e:
            logger.warning(f"Could not open folder {path!r}: {e}")
            return
        
        # --- HACK: Bypass Windows Focus Stealing Prevention ---
        # Windows prevents background processes (like the Streamlit backend) from 
        # stealing focus. Simulating an Alt-key press tricks the OS into allowing it.
        try:
            import ctypes
            time.sleep(0.15) # Give File Explorer a tiny fraction of a second to initialize
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0) # Alt key down
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0) # Alt key up
        except Exception:
            pass
            
    elif sys_platform == "Darwin":  # macOS
        subprocess.Popen(["open", path])
    else:  # Linux
        subprocess.Popen(["xdg-open", path])


def _windows_foreground_nudge():
    """Trick Windows out of focus-stealing prevention so a freshly launched
    Explorer / default-app window comes to the foreground. Simulates a tap of
    the Alt key (the same hack used by open_folder)."""
    try:
        import ctypes
        time.sleep(0.15)  # let the new window initialize
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)  # Alt down
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)  # Alt up
    except Exception:
        pass


def open_file(path: str) -> bool:
    """Open a single file in the OS default application and foreground it.

    Returns True if the open was dispatched, False if the file is missing or
    the OS call failed. Never raises - callers render UI from the bool.
    """
    if not path:
        return False
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        return False

    sys_platform = platform.system()
    try:
        if sys_platform == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
            _windows_foreground_nudge()
        elif sys_platform == "Darwin":
            subprocess.Popen(["open", path])
        else:  # Linux
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        logger.warning(f"Could not open file {path!r}: {e}")
        return False
    return True


def reveal_in_folder(path: str) -> bool:
    """Reveal a file in the native file manager with the file itself selected
    (Explorer /select, Finder reveal). On Linux - which has no portable
    'select' verb - falls back to opening the containing folder.

    Returns True if dispatched, False if the file is missing or the call
    failed. Never raises.
    """
    if not path:
        return False
    path = os.path.normpath(path)
    if not os.path.exists(path):
        # File moved/deleted - degrade gracefully to its parent folder.
        parent = os.path.dirname(path)
        if parent and os.path.isdir(parent):
            open_folder(parent)
            return True
        return False

    sys_platform = platform.system()
    try:
        if sys_platform == "Windows":
            # explorer.exe has non-standard command-line parsing: the list-arg
            # form (subprocess auto-quotes) makes it ignore the path and fall
            # back to opening Documents whenever the path contains spaces. Pass
            # a single command STRING so CreateProcess hands explorer exactly
            # `/select,"<path>"` - the form it actually honours. (Returns exit
            # code 1 even on success, so Popen, not check_call.)
            subprocess.Popen(f'explorer /select,"{path}"')
            _windows_foreground_nudge()
        elif sys_platform == "Darwin":
            subprocess.Popen(["open", "-R", path])
        else:  # Linux - no universal 'select'; open the parent folder instead.
            open_folder(os.path.dirname(path))
    except Exception as e:
        logger.warning(f"Could not reveal file {path!r}: {e}")
        return False
    return True


# --- Friendly Course Name ---

def friendly_course_name(raw_name: str) -> str:
    """Strip Canvas technical metadata from a course name.
    
    Canvas course names often look like:
        'Virksomhedens styring (2): Regnskab (LA F26 BINTO1057U) (BINTO1057U.LA_F26 (...))'
    
    This strips semester codes, course IDs, and duplicate bracket content to return:
        'Virksomhedens styring (2): Regnskab'
    
    Args:
        raw_name: Raw course name from Canvas API
        
    Returns:
        Clean, student-friendly course name
    """
    if not raw_name:
        return raw_name
    
    name = raw_name.strip()
    
    # Remove trailing parenthetical blocks that contain course codes or semester IDs.
    # Canvas names often look like:
    #   'Course Name (LA F26 BINTO1057U) (BINTO1057U.LA_F26 (...))'
    # Strategy: find the last balanced (...) at the end and strip it if it looks technical.
    
    found_codes = set()
    
    while True:
        stripped = name.rstrip()
        if not stripped.endswith(')'):
            break
        # Walk backwards to find the matching opening '('
        depth = 0
        open_pos = None
        for i in range(len(stripped) - 1, -1, -1):
            if stripped[i] == ')':
                depth += 1
            elif stripped[i] == '(':
                depth -= 1
                if depth == 0:
                    open_pos = i
                    break
        if open_pos is None:
            break
        paren_content = stripped[open_pos:]
        
        # Check if it contains course-code-like patterns
        has_course_code = bool(re.search(r'[A-Z]{2,}\d{2,}', paren_content))
        has_semester = bool(re.search(r'[FELS]\d{2}\b', paren_content))
        has_dots = '...' in paren_content
        
        if has_course_code or has_semester or has_dots:
            # Extract Class Codes (e.g., LA, XB) from the block being stripped
            # Matches "XA", "LA", "XB" as standalone words
            codes = re.findall(r'\b([XL][A-Z])\b', paren_content)
            if codes:
                found_codes.update(codes)
            
            name = stripped[:open_pos].strip()
        else:
            break
    
    # Clean up any trailing whitespace or stray characters
    name = name.rstrip(' -–-')
    
    # Append found group codes (e.g., " (LA)")
    if found_codes:
        # Sort to ensure deterministic order (e.g. LA, XB)
        code_str = ', '.join(sorted(found_codes))
        name = f"{name} ({code_str})"
    
    return name if name else raw_name


def get_course_display_parts(course) -> tuple[str, str]:
    """Extract a clean display name and course code from a Canvas course.

    The display name is built by applying ``friendly_course_name()`` to
    strip Canvas metadata and append class-type codes (e.g. "(LA)").

    Prefers ``friendly_name`` (user-set nickname) when present, otherwise
    falls back to ``name``.  All attribute access is guarded with
    ``getattr`` so the app never crashes on incomplete course objects.

    Returns:
        (display_name, course_code) - both guaranteed to be strings (never None).
        display_name: Cleaned name with class codes, e.g. "Regnskab (LA)"
        course_code:  Raw Canvas code, e.g. "BINTO1060U.LA_E25"
    """
    raw_name = (getattr(course, 'friendly_name', None)
                or getattr(course, 'name', '') or '')
    display_name = friendly_course_name(raw_name)
    code = getattr(course, 'course_code', '') or ''
    # Canvas often appends the course name to the code field, e.g.
    # "BINTO1078U.LA_E25 (Introduction to Information Systems)"
    # Strip everything from the first '(' to keep only the code.
    if '(' in code:
        code = code[:code.index('(')].strip()
    return display_name, code


def short_path(full_path: str) -> str:
    """Return just the folder name from a full path.
    
    Args:
        full_path: Full filesystem path
        
    Returns:
        Just the last component (folder name)
    """
    return Path(full_path).name or full_path


# --- Progress Bar Helper ---

def render_progress_bar(container, current: int, total: int,
                        mode: str = 'files', mb_current: float = 0, mb_total: float = 0,
                        custom_text: str = None):
    """Render a styled progress bar using Streamlit's st.markdown.
    
    Args:
        container: Streamlit container to render into
        current: Current count (files downloaded)
        total: Total count (files to download)
        mode: 'files' for file count, 'mb' for MB, 'complete' for finished
        mb_current: Current MB downloaded (for 'mb' mode)
        mb_total: Total MB to download (for 'mb' mode)
        custom_text: Optional override for the status text (e.g. for complete mode)
    """
    import theme

    if mode == 'complete':
        progress_pct = 100
        display_text = custom_text if custom_text else 'Done!'
        bar_color = theme.SUCCESS_ALT
    elif mode == 'complete_warning':
        progress_pct = 100
        display_text = custom_text if custom_text else 'Sync completed with errors.'
        bar_color = theme.WARNING
    elif mode == 'complete_error':
        progress_pct = 100
        display_text = custom_text if custom_text else 'Sync failed for all files.'
        bar_color = theme.ERROR_ALT
    elif mode == 'mb':
        if mb_total <= 0:
            progress_pct = 0
        else:
            progress_pct = min(100, int((mb_current / mb_total) * 100))
        display_text = f'Downloading: {mb_current:.1f} / {mb_total:.1f} MB'
        bar_color = theme.ACCENT_BLUE
    else:  # files
        if total <= 0:
            progress_pct = 0
        else:
            progress_pct = min(100, int((current / total) * 100))
        display_text = custom_text if custom_text else f'{progress_pct}%'
        bar_color = theme.ACCENT_BLUE
    
    progress_html = f'''
    <div style="background-color: {theme.BG_CARD}; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
        <div style="background-color: {bar_color}; width: {progress_pct}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold;">
            {display_text}
        </div>
    </div>
    '''
    container.html(progress_html)


# --- Step Wizard ---

# SVG icon paths (Lucide/Heroicons style, 24×24 viewBox).
# Shapes that should be filled use the placeholder __FILL__ - replaced at render time
# with the cutout colour so they appear as solid filled shapes inside the circle.
_ICON_FOLDER = (
    '<path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>'
)
_ICON_SEARCH = (
    '<circle cx="11" cy="11" r="8"/>'
    '<line x1="21" y1="21" x2="16.65" y2="16.65"/>'
)
_ICON_SYNC = (
    '<polyline points="1 4 1 10 7 10"/>'
    '<polyline points="23 20 23 14 17 14"/>'
    '<path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15"/>'
)
_ICON_CHECK_CIRCLE = (
    '<path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>'
    '<polyline points="22 4 12 14.01 9 11.01"/>'
)

_ICON_DOC = (
    '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>'
    '<polyline points="14 2 14 8 20 8"/>'
    '<line x1="16" y1="13" x2="8" y2="13"/>'
    '<line x1="16" y1="17" x2="8" y2="17"/>'
)
# _ICON_GEAR - standard 24×24 sliders icon (Feather/Lucide, fully stroke-based)
_ICON_GEAR = (
    '<line x1="4" y1="21" x2="4" y2="14"/>'
    '<line x1="4" y1="10" x2="4" y2="3"/>'
    '<line x1="12" y1="21" x2="12" y2="12"/>'
    '<line x1="12" y1="8" x2="12" y2="3"/>'
    '<line x1="20" y1="21" x2="20" y2="16"/>'
    '<line x1="20" y1="12" x2="20" y2="3"/>'
    '<line x1="1" y1="14" x2="7" y2="14"/>'
    '<line x1="9" y1="8" x2="15" y2="8"/>'
    '<line x1="17" y1="16" x2="23" y2="16"/>'
)
_ICON_DOWNLOAD = (
    '<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>'
    '<polyline points="7 10 12 15 17 10"/>'
    '<line x1="12" y1="15" x2="12" y2="3"/>'
)
# List icon: three bullet dots + horizontal lines (from user-supplied SVG)
# The x1=x2 zero-length lines render as round dots via stroke-linecap="round".
_ICON_LIST = (
    '<line x1="4" y1="6" x2="4.01" y2="6"/>'
    '<line x1="4" y1="12" x2="4.01" y2="12"/>'
    '<line x1="4" y1="18" x2="4.01" y2="18"/>'
    '<line x1="9" y1="6" x2="21" y2="6"/>'
    '<line x1="9" y1="12" x2="21" y2="12"/>'
    '<line x1="9" y1="18" x2="21" y2="18"/>'
)


def _wizard_icon_bg(icon_svg, color: str, size: int = 15, circle_bg: str = None) -> str:
    """Return a CSS background-image value for an SVG icon encoded as a base64 data URI.

    Using CSS background-image bypasses Streamlit's HTML sanitiser which strips
    inline <svg> child elements from st.html() content.

    icon_svg may be:
      - a plain string  → standard 0 0 24 24 viewBox
      - a (svg_inner, viewbox) tuple → custom viewBox (e.g. the settings-sliders icon)

    Placeholder substitutions applied to the SVG inner content:
      __FILL__      → *color*      (solid cutout colour for filled shapes)
      __CIRCLE_BG__ → *circle_bg*  (circle background colour, used for centre holes)
    """
    if isinstance(icon_svg, tuple):
        svg_inner, viewbox = icon_svg
    else:
        svg_inner, viewbox = icon_svg, '0 0 24 24'

    hole = circle_bg if circle_bg else color
    resolved = svg_inner.replace('__FILL__', color).replace('__CIRCLE_BG__', hole)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="{viewbox}" '
        f'fill="none" stroke="{color}" stroke-width="3" '
        f'stroke-linecap="round" stroke-linejoin="round">'
        f'{resolved}</svg>'
    )
    b64 = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    return f"url('data:image/svg+xml;base64,{b64}')"


def render_wizard_step(container, current_step: int, steps: list):
    """Render a horizontal step tracker.

    No circles, no pill shape.  Each step is [icon] N. Label - purely informational.
    Renders flush to the top of the page (global.css padding-top:0 on the block container).
    Separator lines flex-grow to fill full page width evenly.

    States:
      done  - soft light-blue; icon + text, slightly faded to signal "already visited"
      active - cool near-white, bold, icon slightly larger; drop-shadow glow below
      idle  - medium-dark blue-grey; visible but clearly inactive

    Args:
        container:    Streamlit container to render into.
        current_step: Current active step number.
        steps:        List of (step_num, label, svg_path) tuples.
    """
    DONE_COLOR   = '#8dbecc'   # completed - soft accent blue
    ACTIVE_COLOR = '#cce0e8'   # current    - cool near-white (slightly muted)
    IDLE_COLOR   = '#607d8b'   # future     - medium-dark blue-grey, legible but receded
    DONE_SEP     = '#3a6070'   # separator after a completed step
    IDLE_SEP     = '#1a2d3d'   # separator before a future step

    parts = [
        '<style>:host{display:block!important;margin:0!important;padding:0!important}</style>'
        '<div style="width:100%;display:flex;align-items:center;">'
    ]

    for i, (step_num, label, icon_svg) in enumerate(steps):
        if step_num < current_step:
            state = 'done'
        elif step_num == current_step:
            state = 'active'
        else:
            state = 'idle'

        if state == 'done':
            icon_size   = '13px'
            icon_color  = DONE_COLOR
            text_color  = DONE_COLOR
            font_size   = '0.87rem'
            font_weight = '500'
            opacity     = '0.75'
            extra_style = ''
        elif state == 'active':
            icon_size   = '15px'
            icon_color  = ACTIVE_COLOR
            text_color  = ACTIVE_COLOR
            font_size   = '0.92rem'
            font_weight = '700'
            opacity     = '1'
            # Centered drop-shadow glow - blurry bright spot at 37.5% opacity
            extra_style = 'filter:drop-shadow(0px 0px 14px rgba(141,190,204,0.375));'
        else:
            icon_size   = '12px'
            icon_color  = IDLE_COLOR
            text_color  = IDLE_COLOR
            font_size   = '0.83rem'
            font_weight = '400'
            opacity     = '0.65'
            extra_style = ''

        icon_bg = _wizard_icon_bg(icon_svg, icon_color)

        parts.append(
            f'<div style="display:inline-flex;align-items:center;gap:5px;'
            f'flex-shrink:0;opacity:{opacity};{extra_style}">'
            f'<div style="width:{icon_size};height:{icon_size};flex-shrink:0;'
            f'background-image:{icon_bg};background-size:contain;'
            f'background-repeat:no-repeat;background-position:center;"></div>'
            f'<span style="font-size:{font_size};color:{text_color};'
            f'font-weight:{font_weight};white-space:nowrap;letter-spacing:0.01em;">'
            f'{step_num}. {label}</span>'
            f'</div>'
        )

        if i < len(steps) - 1:
            if step_num < current_step:
                # Gradient: fades from transparent at the done end to solid at the active end
                sep_bg = f'linear-gradient(to right,{DONE_SEP}80,{DONE_SEP})'
            else:
                sep_bg = IDLE_SEP
            parts.append(
                f'<div style="flex:1;height:2px;background:{sep_bg};'
                f'margin:0 12px;min-width:8px;"></div>'
            )

    parts.append('</div>')
    container.html(''.join(parts))


def render_sync_wizard(container, current_step: int):
    """Render the wizard for the Sync flow."""
    steps = [
        (1, 'Select Courses', _ICON_LIST),
        (2, 'Review Changes',  _ICON_SEARCH),
        (3, 'Syncing',         _ICON_SYNC),
        (4, 'Complete',        _ICON_CHECK_CIRCLE),
    ]
    render_wizard_step(container, current_step, steps)


def render_download_wizard(container, current_step: int):
    """Render the wizard for the Download flow."""
    steps = [
        (1, 'Select Courses',    _ICON_LIST),
        (2, 'Download Settings', _ICON_GEAR),
        (3, 'Downloading',       _ICON_DOWNLOAD),
        (4, 'Complete',          _ICON_CHECK_CIRCLE),
    ]
    render_wizard_step(container, current_step, steps)


# --- CBS Metadata Parser ---

def parse_cbs_metadata(raw_name: str) -> dict:
    """Extract CBS-specific metadata from course name.
    
    Expected patterns in parenthetical blocks:
    - Class Type: L* (Lecture) or X* (Exercise) -> e.g. LA, XB
    - Semester/Year: E[YY] (Autumn 20YY) or F[YY] (Spring 20YY) -> e.g. E25, F26
    
    Returns:
        dict with keys: 'type', 'semester', 'year', 'year_full'
        Values are None if not found.
    """
    if not raw_name:
        return {'type': 'Other', 'semester': None, 'year': None}
        
    meta = {
        'type': 'Other', # Default to Other if no L/X found
        'semester': None,
        'year': None,
        'year_full': None
    }
    
    # Look for patterns in the whole string, but prioritized match
    # Regex for Class Type: Word boundary, starts with L or X, followed by 1 uppercase letter
    # We look for "LA", "XB", etc.
    type_match = re.search(r'\b([LX])[A-Z]\b', raw_name)
    if type_match:
        code = type_match.group(1)
        if code == 'L':
            meta['type'] = 'Lecture'
        elif code == 'X':
            meta['type'] = 'Exercise'
            
    # Regex for Semester/Year: Word boundary, starts with E or F, followed by 2 digits
    # E25 = Autumn 2025, F26 = Spring 2026
    sem_match = re.search(r'\b([EF])(\d{2})\b', raw_name)
    if sem_match:
        sem_code = sem_match.group(1)
        year_short = sem_match.group(2)
        
        meta['semester'] = 'Autumn' if sem_code == 'E' else 'Spring'
        meta['year'] = year_short
        meta['year_full'] = f"20{year_short}"
        
    return meta


