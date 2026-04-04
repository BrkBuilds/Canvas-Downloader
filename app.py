import streamlit as st
from canvas_logic import CanvasManager, DownloadError
from preset_manager import PresetManager
import asyncio
import base64
import collections
import json
import os
import logging
import platform
import re
import sys
import time
from datetime import datetime
import keyring

import theme
from version import __version__

logger = logging.getLogger(__name__)
from pathlib import Path
from sync_ui import render_sync_step1, render_sync_step4
from ui_helpers import esc, friendly_course_name, parse_cbs_metadata, render_download_wizard
from ui_shared import (
    render_completion_card, render_folder_cards,
    render_error_section, render_pp_warning, SECONDARY_ENTITY_ICONS,
    render_config_summary_badges
)
from styles import inject_css
from core.state_registry import (
    ensure_download_state, cleanup_download_state,
    NOTEBOOK_SUB_KEYS, SECONDARY_CONTENT_KEYS, TOTAL_SECONDARY_SUBS,
)
from core.cancellation import cancel_download, is_download_cancelled
from engine.progress_dashboard import DashboardPlaceholders, render_full_dashboard, render_terminal_log
from engine.post_processing_bridge import invoke_post_processing, build_conversion_contract

# Page Config
st.set_page_config(page_title="Canvas Downloader", page_icon="assets/icon.png", layout="wide")

# Custom CSS (extracted to styles/)
inject_css('global.css')

# Cancel button hover CSS (dynamic — requires theme variables)
st.markdown(f"""
    <style>
    .st-key-cancel_download_btn button:hover,
    .st-key-cancel_pp_download button:hover,
    .st-key-cancel_sync_btn button:hover,
    .st-key-cancel_pp_btn button:hover {{
        border-color: {theme.ERROR} !important;
        background-color: {theme.ERROR_BG} !important;
        color: {theme.ERROR} !important;
        transition: all 0.2s ease-in-out;
    }}
    </style>
""", unsafe_allow_html=True)

# Preset & Dialog CSS (extracted to styles/)
inject_css('preset_dialogs.css')

# --- Session State Initialization (centralized in core/state_registry.py) ---
ensure_download_state()

# --- Helper Functions ---
def resolve_path(path):
    """Resolve path for frozen (PyInstaller) vs normal execution."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, path)
    return path

def get_base64_image(image_path):
    """Reads a local file and returns its Base64 string representation."""
    try:
        with open(resolve_path(image_path), "rb") as image_file:
            return base64.b64encode(image_file.read()).decode()
    except Exception as e:
        logger.error(f"Failed to encode image {image_path}: {e}")
        return ""

def _get_chevron_base64(is_expanded):
    if is_expanded:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1683 808-742 741q-19 19-45 19t-45-19L109 808q-19-19-19-45.5t19-45.5l166-165q19-19 45-19t45 19l531 531 531-531q19-19 45-19t45 19l166 165q19 19 19 45.5t-19 45.5z"></path></svg>'''
    else:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1363 877-742 742q-19 19-45 19t-45-19l-166-166q-19-19-19-45t19-45l531-531-531-531q-19-19-19-45t19-45L531 45q19-19 45-19t45 19l742 742q19 19 19 45t-19 45z"></path></svg>'''
    b64_str = base64.b64encode(svg.encode('utf-8')).decode()
    return f"url('data:image/svg+xml;base64,{b64_str}')"

def select_folder():
    from ui_helpers import native_folder_picker
    folder_path = native_folder_picker()
    if folder_path:
        st.session_state['download_path'] = folder_path

def select_sync_folder():
    """Open folder picker for sync mode and store in pending_sync_folder."""
    from ui_helpers import native_folder_picker
    folder_path = native_folder_picker()
    if folder_path:
        st.session_state['pending_sync_folder'] = folder_path

def check_cancellation():
    """Backward-compatible alias for is_download_cancelled (used by canvas_logic.py)."""
    return is_download_cancelled()

def cancel_download_callback():
    """Backward-compatible alias for cancel_download (used in on_click= handlers)."""
    cancel_download()

@st.dialog("📄 Error Log", width="large")
def _download_error_log_dialog(log_paths):
    """Display the contents of download_errors.txt files in a modal dialog."""
    st.markdown("""
        <style>
            div.st-key-error_log_scroll_dl {
                height: 55vh !important;
                min-height: 55vh !important;
                max-height: 55vh !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
            }
        </style>
    """, unsafe_allow_html=True)
    
    with st.container(border=False, key="error_log_scroll_dl"):
        found_any = False
        for log_path in log_paths:
            if log_path.exists():
                try:
                    content = log_path.read_text(encoding='utf-8').strip()
                    if content:
                        found_any = True
                        st.markdown(f"**📁 {log_path.parent.name}**")
                        st.code(content, language="text")
                except Exception as e:
                    st.warning(f"Could not read {log_path}: {e}")
        
        if not found_any:
            st.info("No error log files found on disk.")
    
    if st.button("Close", type="primary", use_container_width=True):
        st.rerun()

@st.cache_data(ttl=600)  # 10-minute TTL — new courses appear after brief wait
def fetch_courses(token, url, fav_only):
    mgr = CanvasManager(token, url)
    try:
        courses = list(mgr.get_courses(fav_only))
        # Global Alphabetical Sort
        courses.sort(key=lambda c: (c.name or "").lower())
        return courses
    except Exception as e:
        # If fetching fails (e.g. auth error), return empty list or let UI handle it. 
        # But mgr.get_courses already raises exception. We should probably let it propagate or return empty.
        # Existing code expected it to raise or return iterable. 
        # Since we wrapper it, let's just let it raise if mgr.get_courses raises.
        # But we need to handle the list conversion safely if it returns None (unlikely).
        raise e

# --- Sidebar: Authentication (delegated to ui.auth) ---
with st.sidebar:
    from ui.auth import render_sidebar
    render_sidebar(fetch_courses)



if not st.session_state['is_authenticated']:
    st.info('👈 Please authenticate in the sidebar to continue.')
    st.stop()

# --- Wizard Steps ---
# Wrap in st.empty().container() to prevent stale elements from previous steps
# persisting during long-running operations (e.g., sync downloads via asyncio.run).
_main_content = st.empty()
with _main_content.container():

    # Preset Dialogs (delegated to ui.presets)
    from ui.presets import _save_config_dialog, _presets_hub_dialog


    # ===================================================================
    # Preset Dialogs (delegated to ui.presets)
    # ===================================================================
    from ui.presets import _save_config_dialog, _presets_hub_dialog

    # STEP 1: Different UI based on mode
    if st.session_state['step'] == 1:
        
        # ========== SYNC MODE - STEP 1 ==========
        if st.session_state['current_mode'] == 'sync':
            render_sync_step1(fetch_courses, _main_content)

        
            # ========== DOWNLOAD MODE - STEP 1 ==========
        else:
            from ui.course_selector import render_course_selector
            render_course_selector(fetch_courses)


    # STEP 2: DOWNLOAD SETTINGS
    elif st.session_state['step'] == 2:
        from ui.download_settings import render_download_settings
        render_download_settings(fetch_courses)


    elif st.session_state['step'] == 3:
        wiz_step = 4 if st.session_state.get('download_status') == 'done' else 3
        render_download_wizard(st, wiz_step)
        
        current_status = st.session_state.get('download_status', 'scanning')
        
        if current_status == 'done':
            st.markdown(f'<div class="step-header">{'Step 4: Complete!'}</div>', unsafe_allow_html=True)
        elif current_status == 'cancelled':
            pass
        else:
            st.markdown(f'<div class="step-header">{'Step 3: Downloading...'}</div>', unsafe_allow_html=True)
        
        # Safety check: ensure download state exists
        if 'courses_to_download' not in st.session_state or 'current_course_index' not in st.session_state:
            st.error('Download state not initialized. Please go back and try again.')
            if st.button('Go Back to Settings'):
                st.session_state['step'] = 2
                st.rerun()
            st.stop()
        
        total = len(st.session_state['courses_to_download'])
        current_idx = st.session_state['current_course_index']
        
        # UI elements in correct order
        if st.session_state['download_status'] == 'running':
            if 'start_time' not in st.session_state:
                st.session_state['start_time'] = time.time()
            if 'log_deque' not in st.session_state:
                st.session_state['log_deque'] = collections.deque(maxlen=6)
                
            header_placeholder = st.empty()
            progress_placeholder = st.empty()
            metrics_placeholder = st.empty()
            active_file_placeholder = st.empty()
            log_placeholder = st.empty()

            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            
            cancel_placeholder = st.empty()
            cancel_placeholder.button(
                'Cancel Download',
                type="secondary",
                key="cancel_download_btn",
                on_click=cancel_download_callback,
            )
        else:
            status_text = st.empty()
            progress_container = st.empty()  # For custom progress bar with text
            mb_counter = st.empty()  # For "Downloading: X / Y MB"
            log_area = st.empty()
        
        # Handle download state
        if st.session_state['download_status'] == 'scanning':
            # Modern Course Analysis UI (Phase 1)
            total_courses = len(st.session_state['courses_to_download'])
            
            # 1. Define the UI placeholder first
            analysis_ui_placeholder = st.empty()
            
            # 2. Define the Cancel button placeholder second (so it sits below)
            cancel_placeholder = st.empty()
            
            # 3. RENDER THE GLOBAL CANCEL BUTTON ONCE, OUTSIDE THE LOOP
            cancel_placeholder.button(
                'Cancel Download',
                type="secondary",
                key="cancel_download_btn",
                on_click=cancel_download_callback,
            )
            
            cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
            total_items = 0
            total_mb = 0
            
            for idx, course in enumerate(st.session_state['courses_to_download']):
                # Check if the user clicked the global cancel button before processing the next course
                if st.session_state.get('cancel_requested', False):
                    break # Escape the loop immediately!
                    
                current_course_num = idx + 1
                percent = int((current_course_num / total_courses) * 100)
                
                # Progress Hook for granular module scanning
                def analysis_progress_hook(current_mod, total_mods, mod_status_text):
                    mod_percent = int((current_mod / total_mods) * 100) if total_mods > 0 else 0
                    analysis_ui_placeholder.markdown(f"""
                    <div style="background-color: {theme.BG_DARK}; padding: 20px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-bottom: 20px;">
                        <h4 style="color: {theme.TEXT_PRIMARY}; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                        <p style="color: {theme.TEXT_SECONDARY}; font-size: 0.9rem;">Course {current_course_num} of {total_courses}: <b>{esc(course.name)}</b></p>
                        <p style="color: {theme.ACCENT_BLUE}; font-size: 0.8rem; margin-bottom: 5px;">{mod_status_text}</p>
                        <div style="background-color: {theme.BG_CARD}; border-radius: 4px; width: 100%; height: 8px; overflow: hidden;">
                            <div style="background-color: {theme.ACCENT_BLUE}; width: {mod_percent}%; height: 100%; transition: width 0.1s ease;"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Cancel button is already rendered above with on_click callback
                    # No need to re-render inside the hook — the callback fires instantly

                # Render initial modern loading UI
                analysis_ui_placeholder.markdown(f"""
                <div style="background-color: {theme.BG_DARK}; padding: 20px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-bottom: 20px;">
                    <h4 style="color: {theme.TEXT_PRIMARY}; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                    <p style="color: {theme.TEXT_SECONDARY}; font-size: 0.9rem;">Course {current_course_num} of {total_courses}: <b>{esc(course.name)}</b></p>
                    <div style="background-color: {theme.BG_CARD}; border-radius: 4px; width: 100%; height: 8px; margin-top: 10px; overflow: hidden;">
                        <div style="background-color: {theme.ACCENT_BLUE}; width: 0%; height: 100%; transition: width 0.3s ease;"></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                
                # Use robust Hybrid file fetching logic directly, identical to actual download loop
                try:
                    # Build scanning-phase secondary settings for accurate counting
                    _scan_secondary = {
                        'download_assignments': st.session_state.get('persistent_dl_assignments', False),
                        'download_syllabus': st.session_state.get('persistent_dl_syllabus', False),
                        'download_announcements': st.session_state.get('persistent_dl_announcements', False),
                        'download_discussions': st.session_state.get('persistent_dl_discussions', False),
                        'download_quizzes': st.session_state.get('persistent_dl_quizzes', False),
                        'download_rubrics': st.session_state.get('persistent_dl_rubrics', False),
                        'isolate_secondary_content': st.session_state.get('persistent_dl_isolate_secondary', True),
                    }
                    course_files, _ = cm.get_course_files_metadata(
                        course,
                        progress_callback=analysis_progress_hook,
                        secondary_content_settings=_scan_secondary,
                        is_scanning_phase=True
                    )
                    
                    # Apply file filter if needed ('study' vs 'all')
                    allowed_exts = ['.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx']
                    filtered_files = []
                    for f in course_files:
                        if st.session_state['file_filter'] == 'study':
                            # Synthetic secondary items (negative ID) bypass the file filter
                            # Since the user specifically checked the box to download them.
                            if getattr(f, 'id', 1) < 0:
                                filtered_files.append(f)
                            else:
                                ext = os.path.splitext(getattr(f, 'filename', ''))[1].lower()
                                if ext in allowed_exts:
                                    filtered_files.append(f)
                        else:
                            filtered_files.append(f)
                            
                    total_items += len(filtered_files)
                    
                    # Add non-file items if mode is flat and filter is not study
                    if st.session_state['download_mode'] == 'flat' and st.session_state['file_filter'] != 'study':
                        try:
                            modules = course.get_modules()
                            for module in modules:
                                items = module.get_module_items()
                                for item in items:
                                    if item.type in ['Page', 'ExternalUrl', 'ExternalTool']:
                                        total_items += 1
                        except Exception:
                            pass
                            
                    # Add module items if mode is modules
                    if st.session_state['download_mode'] == 'modules':
                        try:
                            modules = course.get_modules()
                            for module in modules:
                                items = module.get_module_items()
                                for item in items:
                                    if item.type in ['Page', 'ExternalUrl', 'ExternalTool']:
                                        if st.session_state['file_filter'] != 'study':
                                            total_items += 1
                        except Exception:
                            pass
                    
                    # Guard against API returning literal None for size which breaks sum()
                    total_mb += sum((getattr(f, 'size', 0) or 0) for f in filtered_files) / (1024 * 1024)
                    
                except Exception as e:
                    # Fallback to older count_course_items if Hybrid fetch fails critically
                    total_items += cm.count_course_items(course, mode=st.session_state['download_mode'], file_filter=st.session_state['file_filter'])
                    total_mb += cm.get_course_total_size_mb(course, st.session_state['download_mode'], file_filter=st.session_state['file_filter'])
            
            # Clear UI before dashboard
            analysis_ui_placeholder.empty()
            
            st.session_state['total_items'] = total_items
            st.session_state['total_mb'] = total_mb
            st.session_state['download_status'] = 'running'
            
            st.session_state['start_time'] = time.time() # Reset timer immediately before running loop
            
            st.rerun()

        elif st.session_state['download_status'] == 'running':
            if st.session_state.get('cancel_requested', False) or st.session_state.get('download_cancelled', False):
                st.session_state['download_status'] = 'cancelled'
                st.rerun()
            elif current_idx < total:
                
                # Fetch state variables initialized up top
                start_time = st.session_state.get('start_time', time.time())
                log_deque = st.session_state.get('log_deque', collections.deque(maxlen=6))
                
                # Initialize counters if first run
                if 'downloaded_items' not in st.session_state:
                    st.session_state['downloaded_items'] = 0
                if 'failed_items' not in st.session_state:
                    st.session_state['failed_items'] = 0
                if 'download_errors_list' not in st.session_state:
                    st.session_state['download_errors_list'] = []  # Track error messages in memory
                if 'course_mb_downloaded' not in st.session_state:
                    st.session_state['course_mb_downloaded'] = {}
                    
                # Download the current course
                course = st.session_state['courses_to_download'][current_idx]
                total_items = st.session_state.get('total_items', 1)
                total_mb = st.session_state.get('total_mb', 0)
                
                # Build the shared dashboard placeholders dataclass
                _dp = DashboardPlaceholders(
                    header=header_placeholder,
                    progress=progress_placeholder,
                    metrics=metrics_placeholder,
                    active_file=active_file_placeholder,
                    log=log_placeholder,
                )

                def render_dashboard():
                    current_mb = sum(st.session_state.get('course_mb_downloaded', {}).values())
                    is_retry = st.session_state.get('download_status') == 'isolated_retry'
                    active_total = st.session_state.get('total_items', total_items)
                    active_current = st.session_state.get('retry_downloaded_items', 0) if is_retry else st.session_state.get('downloaded_items', 0)
                    active_current += st.session_state.get('retry_failed_items', 0) if is_retry else st.session_state.get('failed_items', 0)
                    render_full_dashboard(
                        _dp, log_deque,
                        header_label="📦 Downloading Courses",
                        course_name=esc(course.name),
                        current_files=active_current,
                        total_files=active_total,
                        downloaded_mb=current_mb,
                        total_mb=st.session_state.get('total_mb', total_mb),
                        start_time=start_time,
                    )
                
                # Render initial state
                render_dashboard()
                
                def _clean_display_name(raw_msg):
                    """Strip progress-callback prefixes so only the bare filename is stored."""
                    s = str(raw_msg)
                    for prefix in ('Downloading file: ', 'Created link: ', 'Saved: '):
                        if s.startswith(prefix):
                            return s[len(prefix):]
                    return s
                
                def update_ui(msg, progress_type='log', **kwargs):
                    """Update UI with progress information. Wrapped in try/except for async safety."""
                    try:
                        # Exit silently if cancellation is in progress
                        if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'):
                            return
                        
                        # Lazy-init download file details tracker
                        if 'download_file_details' not in st.session_state:
                            st.session_state['download_file_details'] = {}

                        if progress_type == 'skipped':
                            if msg:
                                st.session_state['downloaded_items'] += 1
                                log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>[⏭️] Skipped: {msg}</span>")
                                if kwargs.get('explicit_filepath'):
                                    course_key = course.name
                                    if course_key not in st.session_state['download_file_details']:
                                        st.session_state['download_file_details'][course_key] = []
                                    st.session_state['download_file_details'][course_key].append(kwargs['explicit_filepath'])
                                    st.session_state['download_file_details'] = st.session_state['download_file_details']
                            render_dashboard()

                        elif progress_type == 'attachment_discovered':
                            size = kwargs.get('size', 0)
                            st.session_state['total_mb'] = st.session_state.get('total_mb', total_mb) + (size / (1024 * 1024))
                            st.session_state['total_items'] = st.session_state.get('total_items', total_items) + 1
                            render_dashboard()

                        elif progress_type in ('page', 'link', 'secondary'):
                            # Synthetic entities bypass Phase 1, so they must scale BOTH metrics simultaneously
                            st.session_state['downloaded_items'] += 1
                            st.session_state['total_items'] = st.session_state.get('total_items', total_items) + 1
                            if msg:
                                if progress_type == 'secondary':
                                    entity_type = kwargs.get('entity_type', '')
                                    icon = SECONDARY_ENTITY_ICONS.get(entity_type, '📄')
                                    active_file_placeholder.markdown(f"<div style='color: {theme.ACCENT_LINK}; margin-bottom: 10px; font-weight: 500;'>🔄 {icon} Saving {entity_type}: {msg}...</div>", unsafe_allow_html=True)
                                    log_deque.append(f"[✅] {icon} Saved: {msg}")
                                else:
                                    active_file_placeholder.markdown(f"<div style='color: {theme.ACCENT_LINK}; margin-bottom: 10px; font-weight: 500;'>🔄 Currently downloading: {msg}...</div>", unsafe_allow_html=True)
                                    log_deque.append(f"[✅] Finished: {msg}")
                                    
                                # Track filename for completion screen
                                course_key = course.name
                                if course_key not in st.session_state['download_file_details']:
                                    st.session_state['download_file_details'][course_key] = []
                                st.session_state['download_file_details'][course_key].append(_clean_display_name(msg))
                                # Guardrail 2: Force state rebind for deep mutation
                                st.session_state['download_file_details'] = st.session_state['download_file_details']
                            render_dashboard()

                        elif progress_type in ('download', 'attachment'):
                            st.session_state['downloaded_items'] += 1
                            if msg:
                                if progress_type == 'attachment':
                                    log_deque.append(f"<span style='color: {theme.ACCENT_BLUE};'>[📎] Attachment: {msg}</span>")
                                else:
                                    active_file_placeholder.markdown(f"<div style='color: {theme.ACCENT_LINK}; margin-bottom: 10px; font-weight: 500;'>🔄 Currently downloading: {msg}...</div>", unsafe_allow_html=True)
                                    log_deque.append(f"[✅] Finished: {msg}")
                                    
                                # Track filename for completion screen
                                course_key = course.name
                                if course_key not in st.session_state['download_file_details']:
                                    st.session_state['download_file_details'][course_key] = []
                                st.session_state['download_file_details'][course_key].append(_clean_display_name(msg))
                                # Guardrail 2: Force state rebind for deep mutation
                                st.session_state['download_file_details'] = st.session_state['download_file_details']
                            render_dashboard()

                        elif progress_type == 'phase':
                            # Phase transition (e.g. "Files" → "Secondary Content")
                            phase_name = kwargs.get('phase_name', 'Processing')
                            new_total = kwargs.get('new_total', 0)
                            if new_total > 0:
                                st.session_state['total_items'] += new_total
                            log_deque.append(
                                f"<span style='color: {theme.ACCENT_BLUE};'>"
                                f"[📦] Phase: {phase_name}</span>"
                            )
                            render_dashboard()

                            
                        elif progress_type == 'error':
                            if msg:
                                if isinstance(msg, DownloadError):
                                    error_obj = msg
                                else:
                                    error_obj = DownloadError(course.name, "Unknown Item", "Generic Error", str(msg))
                                
                                sig = f"{error_obj.course_name}|{error_obj.item_name}|{error_obj.error_type}"
                                seen = st.session_state.get('seen_error_sigs', set())
                                
                                if sig not in seen:
                                    seen.add(sig)
                                    st.session_state['seen_error_sigs'] = seen
                                    st.session_state['failed_items'] += 1  # <-- STRICTLY INSIDE THE GUARD
                                    st.session_state['total_items'] = max(st.session_state.get('total_items', total_items), st.session_state.get('downloaded_items', 0) + st.session_state['failed_items'])
                                    
                                    if 'download_errors_list' not in st.session_state:
                                        st.session_state['download_errors_list'] = []
                                    st.session_state['download_errors_list'].append(error_obj)
                                    
                                    error_text = f"[{esc(course.name)}] " + (error_obj.message if hasattr(error_obj, 'message') else str(msg))
                                    log_deque.append(f"<span style='color: #FF7B72;'>[❌] Failed: {esc(error_text)}</span>")
                                    
                            render_dashboard()

                        elif progress_type == 'mb_progress':
                            mb_down_course = kwargs.get('mb_downloaded', 0)
                            if 'course_mb_downloaded' not in st.session_state:
                                 st.session_state['course_mb_downloaded'] = {}
                            st.session_state['course_mb_downloaded'][course.id] = mb_down_course
                            render_dashboard()
                        
                        elif msg and progress_type == 'log':
                            new_line = f"[{esc(course.name)}] {msg}"
                            log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>[ℹ️] {new_line}</span>")
                            render_dashboard()
                    except (KeyboardInterrupt, SystemExit):
                        raise
                    except Exception:
                        # Catch Streamlit's StopException / RerunException during async
                        # teardown without killing the download event loop. Cancellation
                        # flows via st.session_state['cancel_requested'] instead.
                        pass
                

                cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                # Build the Sync Contract — all settings for this download
                _pp_settings = {
                    'file_filter': st.session_state.get('file_filter', 'all'),
                    'convert_zip': st.session_state.get('persistent_convert_zip', False),
                    'convert_pptx': st.session_state.get('persistent_convert_pptx', False),
                    'convert_html': st.session_state.get('persistent_convert_html', False),
                    'convert_code': st.session_state.get('persistent_convert_code', False),
                    'convert_urls': st.session_state.get('persistent_convert_urls', False),
                    'convert_word': st.session_state.get('persistent_convert_word', False),
                    'convert_video': st.session_state.get('persistent_convert_video', False),
                    'convert_excel': st.session_state.get('persistent_convert_excel', False),
                }
                # Build secondary content settings from persisted state
                _secondary_settings = {
                    'download_assignments': st.session_state.get('persistent_dl_assignments', False),
                    'download_syllabus': st.session_state.get('persistent_dl_syllabus', False),
                    'download_announcements': st.session_state.get('persistent_dl_announcements', False),
                    'download_discussions': st.session_state.get('persistent_dl_discussions', False),
                    'download_quizzes': st.session_state.get('persistent_dl_quizzes', False),
                    'download_rubrics': st.session_state.get('persistent_dl_rubrics', False),
                    'download_submissions': st.session_state.get('persistent_dl_submissions', False),
                    'isolate_secondary_content': st.session_state.get('persistent_dl_isolate_secondary', True),
                }
                asyncio.run(cm.download_course_async(
                    course,
                    st.session_state['download_mode'],
                    st.session_state['download_path'],
                    progress_callback=update_ui,
                    check_cancellation=check_cancellation,
                    file_filter=st.session_state['file_filter'],
                    debug_mode=st.session_state.get('debug_mode', False),
                    post_processing_settings=_pp_settings,
                    secondary_content_settings=_secondary_settings
                ))
                
                # --- Post-Processing: Setup ---
                # Set explicitly when entering Phase 3
                st.session_state['is_post_processing'] = True
                
                # Re-render cancel button for post-processing phase
                cancel_placeholder.empty()
                pp_cancel_placeholder = st.empty()
                pp_cancel_placeholder.button(
                    "Cancel Post-Processing",
                    key="cancel_pp_download",
                    type="secondary",
                    on_click=cancel_download_callback,
                )

                # --- Post-Processing: Setup logging for NotebookLM hooks ---
                from canvas_debug import log_debug

                save_dir = st.session_state['download_path']
                debug_mode = st.session_state.get('debug_mode', False)
                root_dir = Path(save_dir)
                course_name = cm._sanitize_filename(course.name)
                course_folder_for_debug = root_dir / course_name
                debug_file = (root_dir / "debug_log.txt") if debug_mode else None

                # Inject course header into the global debug log (append, never overwrite)
                if debug_file:
                    try:
                        with open(debug_file, "a", encoding="utf-8") as f:
                            f.write(f"\n{'='*50}\n--- Post-Processing: {esc(course.name)} ---\n{'='*50}\n")
                    except Exception:
                        pass

                # --- Post-Download Conversion Pipeline (via engine) ---
                course_name_sanitized = cm._sanitize_filename(course.name)
                course_folder = Path(st.session_state['download_path']) / course_name_sanitized

                if course_folder.exists():
                    invoke_post_processing(
                        course_folder=course_folder,
                        course_id=course.id,
                        course_name=course.name,
                        placeholders=_dp,
                        log_deque=log_deque,
                        error_log_path=Path(st.session_state['download_path']),
                        mode='download',
                    )
                # --- End Post-Download Conversion Pipeline ---
                # Clear the blue status text so it doesn't linger on completion
                active_file_placeholder.empty()
                
                # Move to next course (unless cancelled)
                if st.session_state.get('download_cancelled', False):
                    st.session_state['download_status'] = 'cancelled'
                    st.rerun()
                
                st.session_state['current_course_index'] += 1
                
                # Check if we're done
                if st.session_state['current_course_index'] >= total:
                    st.session_state['download_status'] = 'done'
                    st.balloons()
                
                # Auto-rerun instantly to process next course or done screen
                st.rerun()
            else:
                # All done
                st.session_state['download_status'] = 'done'
                
                # --- NEW: Force-write session error log (Backup/Guaranteed file) ---
                if 'download_errors_list' in st.session_state and st.session_state['download_errors_list']:
                    try:
                        from pathlib import Path
                        root_path = Path(st.session_state['download_path'])
                        root_path.mkdir(parents=True, exist_ok=True)
                        session_log = root_path / "session_errors.txt"
                        with open(session_log, "w", encoding="utf-8") as f:
                            f.write(f"Session Error Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                            f.write("===================================================\n")
                            for err in st.session_state['download_errors_list']:
                                f.write(f"{err.to_log_entry()}\n")
                    except Exception as e:
                        logger.error(f"Failed to write session log: {e}")
                # -------------------------------------------------------------------
        
        elif st.session_state['download_status'] == 'isolated_retry':
            if st.session_state.get('cancel_requested', False) or st.session_state.get('download_cancelled', False):
                st.session_state['download_status'] = 'cancelled'
                st.rerun()
                
            header_placeholder = st.empty()
            progress_placeholder = st.empty()
            metrics_placeholder = st.empty()
            active_file_placeholder = st.empty()
            log_placeholder = st.empty()
            
            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            cancel_placeholder = st.empty()
            cancel_placeholder.button(
                'Cancel Retry',
                type="secondary",
                key="cancel_retry_btn",
                on_click=cancel_download_callback,
            )

            queue = st.session_state.get('isolated_retry_queue', [])

            # 1. Update total_items to reflect strictly the retry queue
            total_items = len(queue)
            st.session_state['total_items'] = total_items

            # 2. Dynamically calculate MB from the encapsulated file_dict (Object/Dict safe)
            total_bytes = 0
            for err in queue:
                # Safely handle both Object and Dict representations of the error payload
                ctx = getattr(err, 'context', None) if not isinstance(err, dict) else err.get('context')
                
                if isinstance(ctx, dict):
                    f_dict = ctx.get('file_dict', {})
                    if isinstance(f_dict, dict):
                        total_bytes += f_dict.get('size', 0)

            total_mb = total_bytes / (1024 * 1024) if total_bytes > 0 else 0.0

            # 3. Explicitly overwrite the global session state so progress metrics use the new denominator
            st.session_state['total_mb'] = total_mb
            start_time = st.session_state.get('start_time', time.time())
            log_deque = st.session_state.get('log_deque', collections.deque(maxlen=6))
            
            # Map course_name -> course object
            course_map = {c.name: c for c in st.session_state.get('courses_to_download', [])}
            
            # Group errors by course_name
            queue_by_course = {}
            for err in queue:
                queue_by_course.setdefault(err.course_name, []).append(err)
            
            # Build the retry dashboard placeholders
            _dp = DashboardPlaceholders(
                header=header_placeholder,
                progress=progress_placeholder,
                metrics=metrics_placeholder,
                active_file=active_file_placeholder,
                log=log_placeholder,
            )

            def render_dashboard(current_course_name):
                bytes_down = st.session_state.get('retry_mb_tracker', {}).get('bytes_downloaded', 0)
                current_mb = bytes_down / (1024 * 1024)
                active_total = st.session_state.get('total_items', 1)
                active_current = st.session_state.get('retry_downloaded_items', 0) + st.session_state.get('retry_failed_items', 0)
                render_full_dashboard(
                    _dp, log_deque,
                    header_label="📦 Retrying Failed Items",
                    course_name=esc(current_course_name),
                    current_files=active_current,
                    total_files=active_total,
                    downloaded_mb=current_mb,
                    total_mb=st.session_state.get('total_mb', total_mb),
                    start_time=st.session_state.get('start_time', time.time()),
                    show_total_mb=False,
                )
            
            # Use same update_ui logic to append errors/successes
            def update_ui(msg, progress_type='log', **kwargs):
                try:
                    if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'): return
                    
                    is_retry = st.session_state.get('download_status') == 'isolated_retry'
                    
                    if 'download_file_details' not in st.session_state:
                         st.session_state['download_file_details'] = {}
                    if is_retry and 'retry_isolated_details' not in st.session_state:
                         st.session_state['retry_isolated_details'] = {}
                         
                    course_name_ref = kwargs.get('course_name', 'Unknown')
                         
                    if progress_type == 'skipped':
                        if msg:
                            if is_retry:
                                st.session_state['retry_downloaded_items'] = st.session_state.get('retry_downloaded_items', 0) + 1
                            else:
                                st.session_state['downloaded_items'] += 1
                            log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>[⏭️] Skipped: {msg}</span>")
                            if kwargs.get('explicit_filepath'):
                                if is_retry:
                                    if course_name_ref not in st.session_state['retry_isolated_details']:
                                        st.session_state['retry_isolated_details'][course_name_ref] = []
                                    st.session_state['retry_isolated_details'][course_name_ref].append(kwargs['explicit_filepath'])
                                    st.session_state['retry_isolated_details'] = st.session_state['retry_isolated_details']
                                else:
                                    if course_name_ref not in st.session_state['download_file_details']:
                                        st.session_state['download_file_details'][course_name_ref] = []
                                    st.session_state['download_file_details'][course_name_ref].append(kwargs['explicit_filepath'])
                                    st.session_state['download_file_details'] = st.session_state['download_file_details']
                        render_dashboard(course_name_ref)

                    elif progress_type == 'attachment_discovered':
                        st.session_state['total_items'] = st.session_state.get('total_items', 1) + 1
                        render_dashboard(course_name_ref)

                    elif progress_type in ('download', 'page', 'link', 'secondary', 'attachment'):
                        if is_retry:
                            st.session_state['retry_downloaded_items'] = st.session_state.get('retry_downloaded_items', 0) + 1
                        else:
                            st.session_state['downloaded_items'] += 1
                        if msg:
                            active_file_placeholder.markdown(f"<div style='color: {theme.ACCENT_LINK}; margin-bottom: 10px; font-weight: 500;'>🔄 Retry success: {msg}...</div>", unsafe_allow_html=True)
                            log_deque.append(f"[✅] Finished: {msg}")
                            
                            if kwargs.get('explicit_filepath'):
                                if is_retry:
                                    if course_name_ref not in st.session_state['retry_isolated_details']:
                                        st.session_state['retry_isolated_details'][course_name_ref] = []
                                    st.session_state['retry_isolated_details'][course_name_ref].append(kwargs['explicit_filepath'])
                                    st.session_state['retry_isolated_details'] = st.session_state['retry_isolated_details']
                                else:
                                    if course_name_ref not in st.session_state['download_file_details']:
                                        st.session_state['download_file_details'][course_name_ref] = []
                                    st.session_state['download_file_details'][course_name_ref].append(kwargs['explicit_filepath'])
                                    st.session_state['download_file_details'] = st.session_state['download_file_details']
                        render_dashboard(course_name_ref)
                    
                    elif progress_type == 'error':
                        if is_retry:
                            st.session_state['retry_failed_items'] = st.session_state.get('retry_failed_items', 0) + 1
                        else:
                            st.session_state['failed_items'] += 1
                            st.session_state['total_items'] = max(st.session_state.get('total_items', 1), st.session_state.get('downloaded_items', 0) + st.session_state['failed_items'])
                        if msg:
                            if isinstance(msg, DownloadError): error_obj = msg
                            else: error_obj = DownloadError(course_name_ref, "Unknown Item", "Generic Error", str(msg))
                            
                            # Deduplicate identical errors to prevent log spam
                            sig = f"{error_obj.course_name}|{error_obj.item_name}|{error_obj.error_type}"
                            seen = st.session_state.get('seen_error_sigs', set())
                            if sig not in seen:
                                seen.add(sig)
                                st.session_state['seen_error_sigs'] = seen
                                
                                if 'download_errors_list' not in st.session_state: st.session_state['download_errors_list'] = []
                                st.session_state['download_errors_list'].append(error_obj)
                                
                                error_text = f"[{esc(course_name_ref)}] " + (error_obj.message if hasattr(error_obj, 'message') else str(msg))
                                log_deque.append(f"<span style='color: #FF7B72;'>[❌] Failed: {esc(error_text)}</span>")
                        render_dashboard(course_name_ref)
                        
                    elif msg and progress_type == 'log':
                        new_line = f"[{esc(course_name_ref)}] {msg}"
                        log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>[ℹ️] {new_line}</span>")
                        render_dashboard(course_name_ref)
                except Exception:
                    pass

            cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
            
            if 'retry_mb_tracker' not in st.session_state:
                st.session_state['retry_mb_tracker'] = {'bytes_downloaded': 0}
            
            for course_name, errors in queue_by_course.items():
                if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'): break
                course = course_map.get(course_name)
                if not course: continue
                
                render_dashboard(course.name)
                
                dropped_errors = asyncio.run(cm.download_isolated_batch_async(
                    course=course,
                    error_queue=errors,
                    save_dir=st.session_state['download_path'],
                    progress_callback=lambda msg, progress_type='log', **kwargs: update_ui(msg, progress_type, course_name=kwargs.get('course_name', course.name), **kwargs),
                    check_cancellation=check_cancellation,
                    debug_mode=st.session_state.get('debug_mode', False),
                    mb_tracker=st.session_state['retry_mb_tracker']
                ))
                if dropped_errors:
                    st.session_state['skipped_discovery_errors'] = st.session_state.get('skipped_discovery_errors', 0) + dropped_errors
            
            # --- Post-Processing Pipeline for Retry (via engine) ---
            if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'):
                if not getattr(st.session_state, '_sync_cancel_warning_shown', False):
                    st.warning("Retry cancelled. Skipping post-processing.")
                    st.session_state['_sync_cancel_warning_shown'] = True
            else:
                for course_name in queue_by_course.keys():
                    course = course_map.get(course_name)
                    if not course: continue
                    course_name_sanitized = cm._sanitize_filename(course.name)
                    course_folder = Path(st.session_state['download_path']) / course_name_sanitized
    
                    if course_folder.exists():
                        contract = build_conversion_contract()
    
                        if any(contract.values()):
                            # --- FIX: Post-Processing Overkill Pipeline Swaps ---
                            success_names = st.session_state.get('retry_isolated_details', {}).get(course.name, [])
                            if not success_names:
                                continue  # Skip post-processing entirely if nothing actually succeeded during this retry
                                
                            success_paths = []
                            for n in success_names:
                                if Path(n).is_absolute():
                                    success_paths.append(str(Path(n).resolve()))
                                else:
                                    success_paths.append(str((course_folder / cm._sanitize_filename(n)).resolve()))
                            
                            st.session_state['is_post_processing'] = True
                            invoke_post_processing(
                                course_folder=course_folder,
                                course_id=course.id,
                                course_name=course.name,
                                placeholders=_dp,
                                log_deque=log_deque,
                                error_log_path=Path(st.session_state['download_path']),
                                mode='download',
                                contract=contract,
                                explicit_files=success_paths,
                            )
            # --- End Post-Processing Pipeline ---

            # --- Success Metrics Rehydration & Error Resolution ---
            retry_success_details = st.session_state.get('retry_isolated_details', {})
            global_details = st.session_state.get('download_file_details', {})
            global_errors = st.session_state.get('download_errors_list', [])
            
            resolved_count = 0
            
            from pathlib import Path
            temp_cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
            
            for c_name, success_list in retry_success_details.items():
                # 1. Merge into global details
                if c_name not in global_details:
                    global_details[c_name] = []
                for p in success_list:
                    if p not in global_details[c_name]:
                        global_details[c_name].append(p)
                
                # 2. Iterate successes to find resolved errors
                success_basenames = {Path(p).name for p in success_list}
                resolved_for_course = []
                
                # Filter out errors that are now resolved
                new_global_errors = []
                for err in global_errors:
                    # Guardrail 2: The Serialization Trap
                    ctx = getattr(err, 'context', None) if not isinstance(err, dict) else err.get('context')
                    err_filepath = ctx.get('filepath') if isinstance(ctx, dict) else None
                    
                    err_course_name = getattr(err, 'course_name', None) if not isinstance(err, dict) else err.get('course_name')
                    err_item_name = getattr(err, 'item_name', None) if not isinstance(err, dict) else err.get('item_name')
                    
                    is_resolved = False
                    if err_filepath:
                         is_resolved = any(str(Path(p).resolve()) == str(Path(err_filepath).resolve()) for p in success_list)
                    else:
                         is_resolved = (err_course_name == c_name and err_item_name in success_basenames)
                         
                    if is_resolved:
                        resolved_for_course.append(err_item_name)
                        resolved_count += 1
                        
                        # --- FIX: Error Signature Drift ---
                        # Reconstruct the exact signature used to deduplicate the error
                        err_error_type = getattr(err, 'error_type', 'Unknown Type') if not isinstance(err, dict) else err.get('error_type', 'Unknown Type')
                        sig = f"{c_name}|{err_item_name}|{err_error_type}"
                        
                        # Safely purge from tracking buffer to prevent permanent muting
                        # CRITICAL: Use .discard() instead of .remove() to prevent KeyError crashes
                        seen = st.session_state.get('seen_error_sigs', set())
                        if sig in seen:
                            seen.discard(sig)
                            st.session_state['seen_error_sigs'] = seen
                        
                        # Guardrail 3: Safe Directory Resolution (fallback to course folder if err_filepath missing)
                        save_dir = Path(err_filepath).parent if err_filepath else Path(st.session_state['download_path']) / temp_cm._sanitize_filename(c_name)
                        log_file = save_dir / "download_errors.txt"
                        if log_file.exists():
                            try:
                                with open(log_file, "a", encoding="utf-8") as f:
                                    f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [RESOLVED] Successfully downloaded: {err_item_name}\n")
                            except Exception as e:
                                logger.error(f"Failed to write [RESOLVED] log: {e}")
                    else:
                        new_global_errors.append(err)
                global_errors = new_global_errors

            # Update session state with rehydrated metrics
            st.session_state['download_file_details'] = global_details
            st.session_state['download_errors_list'] = global_errors
            st.session_state['downloaded_items'] = st.session_state.get('downloaded_items', 0) + st.session_state.get('retry_downloaded_items', 0)
            st.session_state['failed_items'] = max(0, st.session_state.get('failed_items', 0) - resolved_count)

            # Post-retry cleanup
            # --- FIX: Cancel-to-Done Bypass ---
            if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'):
                st.session_state['download_status'] = 'cancelled'
            else:
                st.session_state['download_status'] = 'done'
                st.balloons()
            st.rerun()

        elif st.session_state['download_status'] == 'done':
            # --- Premium Completion Screen (Parity with Sync) ---
            download_errors = st.session_state.get('download_errors_list', [])
            failed_count = st.session_state.get('failed_items', 0)
            total_mb = st.session_state.get('total_mb', 0)
            total_bytes = int(total_mb * 1024 * 1024)

            # Build the set of failed filenames so we can filter them out of the
            # file-detail list. This ensures the card count matches the expander.
            _failed_names = set()
            for err in download_errors:
                if hasattr(err, 'item_name') and err.item_name:
                    _failed_names.add(err.item_name)

            file_details_raw = st.session_state.get('download_file_details', {})
            file_details = {}
            for k, paths in file_details_raw.items():
                # Present only the base name to the UI rendering loop to preserve Completion Card aesthetics
                filtered = [Path(p).name for p in paths if Path(p).name not in _failed_names]
                if filtered:
                    file_details[k] = filtered
            st.session_state['download_file_details'] = file_details

            success_count = sum(len(v) for v in file_details.values())

            # 1. Summary card
            render_completion_card(
                synced_count=success_count,
                error_count=len(download_errors),
                total_bytes=total_bytes,
                mode='download',
            )

            # Hybrid Discovery Warning (Surfaced explicitly in UI)
            skipped_discovery = st.session_state.get('skipped_discovery_errors', 0)
            if skipped_discovery > 0:
                st.warning(f"{skipped_discovery} item(s) failed during the discovery phase and could not be isolated for retry. A full course rescan is required to retry them.", icon="⚠️")


            # 2. Post-processing warning
            render_pp_warning(st.session_state.get('pp_failure_count', 0))

            # 3. Error section
            download_path = Path(st.session_state['download_path'])
            error_log_paths = []
            for c in st.session_state.get('courses_to_download', []):
                cm_temp = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                log_file = download_path / cm_temp._sanitize_filename(c.name) / "download_errors.txt"
                if log_file.exists():
                    error_log_paths.append(log_file)

            render_error_section(
                download_errors, error_log_paths,
                dialog_fn=_download_error_log_dialog,
                key_prefix='dl',
            )

            # 4. Retry button (only if errors)
            if download_errors:
                # --- FIX: Prevent Structural Error Retry Infinite Loop ---
                # Guarantee that at least one error corresponds to a physical file (has 'filepath' context)
                has_retriable_errors = any(
                    isinstance(getattr(err, 'context', None), dict) and err.context.get('filepath') and getattr(err, 'error_type', '') != 'LTI/Media Stream'
                    for err in download_errors
                )
                
                if has_retriable_errors:
                    st.markdown("<div style='margin-top: -15px; margin-bottom: 25px;'></div>", unsafe_allow_html=True)
                    col_retry, _ = st.columns([0.25, 0.75])
                    with col_retry:
                        if st.button("🔄 Retry Failed Items", type="secondary", key="retry_failed_btn",
                                     use_container_width=True):
                            # Sniper Retry: jump straight to 'isolated_retry', skipping the
                            # multi-minute Canvas analysis phase.  Queue specifically the failed items.
                            
                            # CRITICAL: Capture the existing error list into a local variable BEFORE clearing state!
                            current_errors = list(st.session_state.get('download_errors_list', []))
                            
                            retriable_queue = []
                            structural_count = 0
                            for err in current_errors:
                                ctx = getattr(err, 'context', None) if not isinstance(err, dict) else err.get('context')
                                if isinstance(ctx, dict) and ctx.get('filepath') and getattr(err, 'error_type', '') != 'LTI/Media Stream':
                                    retriable_queue.append(err)
                                else:
                                    structural_count += 1
                                    
                            st.session_state['isolated_retry_queue'] = retriable_queue
                            st.session_state['download_status'] = 'isolated_retry'
                            
                            # --- FIX: Prevent Success Amnesia ---
                            # Initialize sandboxed variables for the retry isolated UI
                            st.session_state['retry_isolated_details'] = {}
                            st.session_state['retry_downloaded_items'] = 0
                            st.session_state['retry_failed_items'] = 0
                            
                            # --- FIX: Prevent Zombie Cancel Loop ---
                            st.session_state['cancel_requested'] = False
                            st.session_state['download_cancelled'] = False
                            
                            # Note: We NO LONGER wipe global `downloaded_items`, `failed_items`, `download_errors_list`,
                            # or `download_file_details` so history is preserved if user cancels.
                            # We also keep `seen_error_sigs` intact so identical repeat errors don't flood UI.
                            st.session_state['skipped_discovery_errors'] = structural_count
                            st.session_state['pp_failure_count'] = 0
                            st.session_state['pp_success_count'] = 0
                            st.session_state['log_content'] = ""
                            st.session_state['start_time'] = time.time()
                            
                            # Set total items so the progress bar works
                            st.session_state['total_items'] = len(st.session_state['isolated_retry_queue'])
                            
                            st.rerun()

            # 5. Per-course folder cards with file dropdowns
            # file_details was already filtered above
            folder_paths = {}
            for c in st.session_state.get('courses_to_download', []):
                cm_temp = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                course_folder = download_path / cm_temp._sanitize_filename(c.name)
                folder_paths[c.name] = str(course_folder)

            render_folder_cards(file_details, folder_paths, key_prefix='dl')
        
        elif st.session_state['download_status'] == 'cancelled':
            # Premium styled cancellation card (matches sync_ui.py design)
            downloaded_count = st.session_state.get('downloaded_items', 0)
            total_items_count = st.session_state.get('total_items', 0)
            
            # Dynamic text: "course" during scanning, "file" during download, post-processing status
            if st.session_state.get('is_post_processing', False):
                cancel_summary_msg = "Cancelled during post-processing."
            else:
                is_file_phase = total_items_count > 0
                if is_file_phase:
                    cancel_summary_msg = f"Cancelled after {downloaded_count} of {total_items_count} file{'s' if total_items_count != 1 else ''}."
                else:
                    cancel_summary_msg = "Cancelled during Course Analysis."
            
            st.markdown(f"""
            <div style="
                background: linear-gradient(135deg, {theme.ERROR_BG} 0%, {theme.BG_PAGE} 100%);
                border: 1px solid {theme.ERROR};
                border-radius: 12px;
                padding: 28px 32px;
                margin: 20px 0;
                box-shadow: 0 4px 20px rgba(239, 68, 68, 0.15);
            ">
                <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 12px;">
                    <span style="font-size: 2rem;">🛑</span>
                    <h2 style="margin: 0; color: {theme.ERROR}; font-size: 1.5rem; font-weight: 700;">Download Cancelled</h2>
                </div>
                <p style="color: {theme.TEXT_LIGHT}; font-size: 1rem; margin: 0 0 8px 0;">
                    {'Download was cancelled.'}
                </p>
                <div style="
                    background: rgba(239, 68, 68, 0.08);
                    border-radius: 8px;
                    padding: 12px 16px;
                    margin-top: 12px;
                    display: inline-block;
                ">
                    <span style="color: {theme.ERROR_LIGHT}; font-size: 0.9rem; font-weight: 600;">
                        {cancel_summary_msg}
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Show errors if any
            download_errors = st.session_state.get('download_errors_list', [])
            if download_errors:
                with st.expander(f"Error Details ({len(download_errors)})", expanded=False):
                    for err in download_errors[:20]:
                        if hasattr(err, 'message'):
                            st.markdown(f"\u274c {err.message}")
                        else:
                            st.markdown(f"\u274c {err}")
                    if len(download_errors) > 20:
                        st.caption(f"  ... and {len(download_errors) - 20} more")
        
        if st.session_state['download_status'] in ['done', 'cancelled']:
            st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
            # Use "Go to front page" for both done and cancelled
            button_text = "🏠 " + 'Go to front page'
            if st.button(button_text, type="primary", use_container_width=True):
                # We want to preserve heavy network caches to prevent the 1-3 second hang
                # when returning to the front page
                keys_to_keep = {
                    'courses', 'course_names', 'api_token', 'api_url', 'api_configured',
                    'sync_pairs', 'sync_pairs_loaded',
                    'is_authenticated', 'user_name', 'token_loaded',
                    'download_path', 'current_mode',
                }

                st.session_state['sync_cancelled'] = False
                st.session_state['sync_cancel_requested'] = False
                st.session_state['cancel_requested'] = False
                st.session_state['download_cancelled'] = False

                # Nuclear cache clearing on reset to destroy dead aiohttp sessions
                st.cache_data.clear()

                # Iterate over a list of keys to allow modifying the dictionary
                for key in list(st.session_state.keys()):
                    if key not in keys_to_keep and not key.startswith('FormSubmitter:'):
                        del st.session_state[key]

                st.session_state['step'] = 1
                st.rerun()


    # STEP 4: SYNC ANALYSIS (Only shown when current_mode is 'sync')
    elif st.session_state['step'] == 4:
        render_sync_step4()
