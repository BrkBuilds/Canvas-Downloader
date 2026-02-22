"""
UI Helper utilities for Canvas LMS Batch File Downloader.
Shared helpers used by both download and sync modes.
"""

import os
import re
import json
import shutil
import platform
import subprocess
from pathlib import Path
from translations import get_text

import urllib.parse
from sync_manager import format_file_size


def robust_filename_normalize(name: str) -> str:
    """Normalize filename for robust comparison (unquote, strip, lower)."""
    if not name:
        return ""
    try:
        # Handle potential non-string input safely
        return urllib.parse.unquote_plus(str(name)).strip().lower()
    except Exception:
        return str(name).strip().lower()


# --- Pluralization ---

# Word forms: (singular, plural) per language
_PLURAL_FORMS = {
    'en': {
        'file': ('file', 'files'),
        'folder': ('folder', 'folders'),
        'course': ('course', 'courses'),
        'update': ('update', 'updates'),
        'error': ('error', 'errors'),
    },
    'da': {
        'file': ('fil', 'filer'),
        'folder': ('mappe', 'mapper'),
        'course': ('kursus', 'kurser'),
        'update': ('opdatering', 'opdateringer'),
        'error': ('fejl', 'fejl'),
    },
}


def pluralize(count: int, word: str, lang: str = 'en') -> str:
    """Return the correct singular/plural form of a word.

    Args:
        count: The number to decide singular vs plural.
        word:  The word key (e.g. 'file', 'folder', 'course', 'update').
        lang:  Language code ('en' or 'da').

    Returns:
        The correct form, e.g. ``pluralize(1, 'file', 'en')`` → ``'file'``,
        ``pluralize(3, 'file', 'en')`` → ``'files'``.
    """
    forms = _PLURAL_FORMS.get(lang, _PLURAL_FORMS['en'])
    singular, plural = forms.get(word, (word, word + 's'))
    return singular if count == 1 else plural


# --- Config Paths ---

SYNC_PAIRS_FILENAME = "canvas_sync_pairs.json"


def get_config_dir() -> str:
    """Get the directory where config files are stored (same as app.py location)."""
    return str(Path(__file__).parent)


# --- Persistent Sync Pairs ---

def load_sync_pairs(config_dir: str = None) -> list[dict]:
    """Load saved sync pairs from disk.
    
    Returns:
        List of dicts with keys: local_folder, course_id, course_name, last_synced
    """
    if config_dir is None:
        config_dir = get_config_dir()
    
    path = Path(config_dir) / SYNC_PAIRS_FILENAME
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


def save_sync_pairs(pairs: list[dict], config_dir: str = None):
    """Save sync pairs to disk.
    
    Args:
        pairs: List of pair dicts
        config_dir: Config directory path
    """
    if config_dir is None:
        config_dir = get_config_dir()
    
    path = Path(config_dir) / SYNC_PAIRS_FILENAME
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(pairs, f, indent=2, ensure_ascii=False)
    except IOError as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to save sync pairs: {e}")


# --- Disk Space ---

def check_disk_space(path: str, required_bytes: int = 0, min_free_gb: float = 1.0) -> tuple[bool, float]:
    """Check if there's enough disk space.
    
    Args:
        path: Path on the target volume
        required_bytes: Additional bytes needed (on top of min_free_gb)
        min_free_gb: Minimum free space in GB
        
    Returns:
        Tuple of (has_enough_space, available_mb)
    """
    try:
        stat = shutil.disk_usage(path)
        available_mb = stat.free / (1024 * 1024)
        required_total = (min_free_gb * 1024 * 1024 * 1024) + required_bytes
        has_enough = stat.free >= required_total
        return has_enough, available_mb
    except Exception:
        # If we can't check, assume OK
        return True, -1


# --- Folder Opener ---

def open_folder(path: str):
    """Open a folder in the system file explorer and bring to foreground.
    
    Args:
        path: Path to the folder to open
    """
    try:
        path = str(Path(path).resolve())
        if not Path(path).exists():
            return False
        
        system = platform.system()
        if system == 'Windows':
            # Use explorer /select to force foreground window
            subprocess.Popen(['explorer', path])
        elif system == 'Darwin':  # macOS
            subprocess.Popen(['open', path])
        else:  # Linux
            subprocess.Popen(['xdg-open', path])
        return True
    except Exception:
        return False


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
    name = name.rstrip(' -–—')
    
    # Append found group codes (e.g., " (LA)")
    if found_codes:
        # Sort to ensure deterministic order (e.g. LA, XB)
        code_str = ', '.join(sorted(found_codes))
        name = f"{name} ({code_str})"
    
    return name if name else raw_name


def short_path(full_path: str) -> str:
    """Return just the folder name from a full path.
    
    Args:
        full_path: Full filesystem path
        
    Returns:
        Just the last component (folder name)
    """
    return Path(full_path).name or full_path


# --- Progress Bar Helper ---

def render_progress_bar(container, current: int, total: int, lang: str, 
                        mode: str = 'files', mb_current: float = 0, mb_total: float = 0,
                        custom_text: str = None):
    """Render a styled progress bar using Streamlit's st.markdown.
    
    Args:
        container: Streamlit container to render into
        current: Current count (files downloaded)
        total: Total count (files to download)
        lang: Language code
        mode: 'files' for file count, 'mb' for MB, 'complete' for finished
        mb_current: Current MB downloaded (for 'mb' mode)
        mb_total: Total MB to download (for 'mb' mode)
        custom_text: Optional override for the status text (e.g. for complete mode)
    """
    if mode == 'complete':
        progress_pct = 100
        display_text = custom_text if custom_text else get_text('sync_complete_text', lang)
        bar_color = '#2ecc71'
    elif mode == 'complete_warning':
        progress_pct = 100
        display_text = custom_text if custom_text else get_text('sync_complete_with_errors', lang)
        bar_color = '#f1c40f'  # Yellow/Orange for warnings
    elif mode == 'complete_error':
        progress_pct = 100
        display_text = custom_text if custom_text else get_text('sync_all_failed', lang)
        bar_color = '#e74c3c'  # Red for errors
    elif mode == 'mb':
        if mb_total <= 0:
            progress_pct = 0
        else:
            progress_pct = min(100, int((mb_current / mb_total) * 100))
        display_text = get_text('sync_mb_progress', lang, current=mb_current, total=mb_total)
        bar_color = '#3498db'
    else:  # files
        if total <= 0:
            progress_pct = 0
        else:
            progress_pct = min(100, int((current / total) * 100))
        display_text = custom_text if custom_text else get_text('sync_progress_text', lang, current=current, total=total)
        bar_color = '#3498db'
    
    progress_html = f"""
    <div style="
        width: 100%;
        background: rgba(255,255,255,0.1);
        border-radius: 12px;
        overflow: hidden;
        height: 32px;
        position: relative;
        margin: 8px 0;
        border: 1px solid rgba(255,255,255,0.15);
    ">
        <div style="
            width: {progress_pct}%;
            height: 100%;
            background: linear-gradient(90deg, {bar_color}, {bar_color}dd);
            border-radius: 12px;
            transition: width 0.4s ease;
        "></div>
        <div style="
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 14px;
            text-shadow: 0 1px 2px rgba(0,0,0,0.5);
        ">{display_text}</div>
    </div>
    """
    container.markdown(progress_html, unsafe_allow_html=True)


# --- Step Wizard ---

def render_wizard_step(container, current_step: int, steps: list):
    """Render a horizontal step wizard indicator.
    
    Args:
        container: Streamlit container to render into
        current_step: Current step number
        steps: List of (step_num, label) tuples
    """
    cols = container.columns(len(steps))
    for col, (step_num, label) in zip(cols, steps):
        if step_num < current_step:
            color = "#2ecc71"
            bg = "rgba(46,204,113,0.15)"
            border = "1px solid rgba(46,204,113,0.4)"
            fw = "400"

            label = f"✓ {label}"
        elif step_num == current_step:
            color = "#3498db"
            bg = "rgba(52,152,219,0.15)"
            border = "2px solid rgba(52,152,219,0.6)"
            fw = "600"
        else:
            color = "#666"
            bg = "rgba(255,255,255,0.03)"
            border = "1px solid #444"
            fw = "400"
        
        col.markdown(
            f'<div style="text-align:center;padding:8px 4px;border-radius:8px;background:{bg};border:{border};color:{color};font-size:0.8em;font-weight:{fw};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{label}</div>',
            unsafe_allow_html=True,
        )

def render_sync_wizard(container, current_step: int, lang: str):
    """Render the wizard specifically for the Sync flow."""
    steps = [
        (1, get_text('sync_step_select_folders', lang)),
        (2, get_text('sync_step_review', lang)),
        (3, get_text('sync_step_syncing', lang)),
        (4, get_text('sync_step_complete', lang)),
    ]
    render_wizard_step(container, current_step, steps)

def render_download_wizard(container, current_step: int, lang: str):
    """Render the wizard specifically for the Download flow."""
    steps = [
        (1, "📝 " + get_text('step1_header', lang).replace('Trin 1: ', '').replace('Step 1: ', '')),
        (2, "⚙️ " + get_text('step2_header', lang).replace('Trin 2: ', '').replace('Step 2: ', '')),
        (3, "⬇️ " + get_text('step3_header', lang).replace('Trin 3: ', '').replace('Step 3: ', '')),
        (4, "✅ " + get_text('complete_text', lang)),
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


