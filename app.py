import streamlit as st
import tkinter as tk
from tkinter import filedialog
from canvas_logic import CanvasManager, DownloadError
import asyncio
import collections
import json
import os
import logging
import re
import sys
import time
import keyring

import theme
from version import __version__

logger = logging.getLogger(__name__)
from pathlib import Path
from sync_ui import render_sync_step1, render_sync_step4
from ui_helpers import esc, friendly_course_name, parse_cbs_metadata, render_download_wizard

# Page Config
st.set_page_config(page_title="Canvas Downloader", page_icon="assets/icon.png", layout="wide")

# Custom CSS
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
    }
    .success-text { color: #28a745; font-weight: bold; }
    .error-text { color: #dc3545; font-weight: bold; }
    .step-header { font-size: 1.5em; font-weight: bold; margin-bottom: 1em; }
    /* Hide the "Press Enter to apply" / "Press Enter to submit" hints */
    div[data-testid="InputInstructions"] { display: none !important; }
    /* Hide the blinking cursor in the language dropdown to look like a static menu */
    div[data-testid="stSelectbox"] input { caret-color: transparent; cursor: default !important; }
    div[data-testid="stSelectbox"] > div { cursor: default !important; }
    
    /* Destructive buttons (Cancel / Remove) turn red on hover */
    [class*="st-key-remove_pair"] button:hover,
    [class*="st-key-cancel_pair"] button:hover {
        border-color: #ff4b4b !important;
        color: #ff4b4b !important;
        background-color: rgba(255, 75, 75, 0.1) !important;
    }
    /* Cancel buttons — scoped to specific cancel button keys only */
    .st-key-cancel_download_btn button:hover,
    .st-key-cancel_pp_download button:hover,
    .st-key-cancel_sync_btn button:hover,
    .st-key-cancel_pp_btn button:hover {
        border-color: {theme.ERROR} !important;
        background-color: {theme.ERROR_BG} !important;
        color: {theme.ERROR} !important;
        transition: all 0.2s ease-in-out;
    }
    </style>
""", unsafe_allow_html=True)

# --- Session State Initialization ---
if 'api_token' not in st.session_state:
    st.session_state['api_token'] = ""
if 'api_url' not in st.session_state:
    st.session_state['api_url'] = ""
if 'is_authenticated' not in st.session_state:
    st.session_state['is_authenticated'] = False
if 'download_path' not in st.session_state:
    st.session_state['download_path'] = str(Path.home() / "Downloads")
if 'selected_course_ids' not in st.session_state:
    st.session_state['selected_course_ids'] = []
if 'step' not in st.session_state:
    st.session_state['step'] = 1  # 1: Select, 2: Settings, 3: Progress
if 'download_mode' not in st.session_state:
    st.session_state['download_mode'] = "modules" # 'flat' or 'modules'
if 'cancel_requested' not in st.session_state:
    st.session_state['cancel_requested'] = False
if 'download_cancelled' not in st.session_state:
    st.session_state['download_cancelled'] = False
if 'user_name' not in st.session_state:
    st.session_state['user_name'] = ""
if 'course_mb_downloaded' not in st.session_state:
    st.session_state['course_mb_downloaded'] = {}
if 'file_filter' not in st.session_state:
    st.session_state['file_filter'] = 'all' # 'all' or 'study'
# Sync mode session state
if 'sync_mode' not in st.session_state:
    st.session_state['sync_mode'] = False  # False = normal download, True = sync
if 'analysis_result' not in st.session_state:
    st.session_state['analysis_result'] = None
if 'sync_selected_files' not in st.session_state:
    st.session_state['sync_selected_files'] = {}
if 'sync_manifest' not in st.session_state:
    st.session_state['sync_manifest'] = None
if 'sync_manager' not in st.session_state:
    st.session_state['sync_manager'] = None
if 'current_mode' not in st.session_state:
    st.session_state['current_mode'] = 'download'  # 'download' or 'sync'
# Sync pairs: list of dicts with keys: local_folder, course_id, course_name
if 'sync_pairs' not in st.session_state:
    st.session_state['sync_pairs'] = []
if 'pending_sync_folder' not in st.session_state:
    st.session_state['pending_sync_folder'] = None  # Temp storage for folder picker

# NotebookLM Compatible Download toggles
if 'notebooklm_master' not in st.session_state:
    st.session_state['notebooklm_master'] = False
if 'convert_pptx' not in st.session_state:
    st.session_state['convert_pptx'] = False

# --- Helper Functions ---
def select_folder():
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes('-topmost', 1)
    try:
        root.iconbitmap(os.path.join(os.path.dirname(__file__), 'assets', 'icon.ico'))
    except Exception:
        pass
    folder_path = filedialog.askdirectory(master=root)
    root.destroy()
    if folder_path:
        st.session_state['download_path'] = folder_path

def select_sync_folder():
    """Open folder picker for sync mode and store in pending_sync_folder."""
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes('-topmost', 1)
    try:
        root.iconbitmap(os.path.join(os.path.dirname(__file__), 'assets', 'icon.ico'))
    except Exception:
        pass
    folder_path = filedialog.askdirectory(master=root)
    root.destroy()
    if folder_path:
        st.session_state['pending_sync_folder'] = folder_path

def check_cancellation():
    return st.session_state.get('cancel_requested', False) or st.session_state.get('download_cancelled', False)

def cancel_download_callback():
    """Instant on_click callback — fires before Streamlit re-enters the main loop."""
    st.session_state['download_cancelled'] = True
    st.session_state['cancel_requested'] = True

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

@st.cache_data
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

# --- Sidebar: Authentication ---
with st.sidebar:
    st.markdown("---")
    st.title('🎓 Canvas Tool')
    
    # Auth Logic
    
    def get_config_path():
        if getattr(sys, 'frozen', False):
            # Running as compiled exe
            application_path = os.path.dirname(sys.executable)
        else:
            # Running as script
            application_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(application_path, 'canvas_downloader_settings.json')

    CONFIG_FILE = get_config_path()
    KEYRING_SERVICE = "CanvasDownloader"
    
    # Auto-load token (only once)
    if 'token_loaded' not in st.session_state:
        st.session_state['token_loaded'] = True
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding='utf-8') as f:
                    config = json.load(f)
                    st.session_state['api_url'] = config.get('api_url', '')
                    
                    if 'concurrent_downloads' in config:
                        st.session_state['concurrent_downloads'] = config.get('concurrent_downloads', 5)
                        
                    if 'debug_mode' in config:
                        st.session_state['debug_mode'] = config.get('debug_mode', False)
                    
                    # Load token from OS keyring (secure)
                    loaded_token = ''
                    try:
                        keyring_user = st.session_state['api_url'] or 'default'
                        loaded_token = keyring.get_password(KEYRING_SERVICE, keyring_user) or ''
                    except Exception:
                        pass  # Keyring unavailable, fall through to legacy check
                    
                    # Legacy migration: if token still in JSON, migrate it to keyring
                    if not loaded_token and config.get('api_token', ''):
                        loaded_token = config['api_token']
                        # Migrate to keyring and strip from JSON
                        try:
                            keyring_user = st.session_state['api_url'] or 'default'
                            keyring.set_password(KEYRING_SERVICE, keyring_user, loaded_token)
                            config.pop('api_token', None)
                            with open(CONFIG_FILE, 'w', encoding='utf-8') as fw:
                                json.dump(config, fw)
                        except Exception:
                            pass  # Migration failed, will work from RAM this session
                    
                    st.session_state['api_token'] = loaded_token
                        
                    if st.session_state['api_token']:
                        cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                        valid, msg = cm.validate_token()
                        if valid:
                            st.session_state['is_authenticated'] = True
                            st.session_state['user_name'] = msg
            except Exception:
                pass

    if not st.session_state['is_authenticated']:
        st.subheader('Authentication')
        
        # Example text removed as per user request (placeholder is sufficient)
        
        # Use a form to prevent "Press Enter to apply" and standardize submission
        # We re-introduced st.form here to FIX the Chrome autofill bug.
        # Chrome autofill sometimes doesn't trigger 'change' events until interaction.
        # st.form guarantees that when the button is successfully clicked, the values are captured.
        # The CSS rule `div[data-testid="InputInstructions"] { display: none !important; }` keeps the hint hidden.
        with st.form("auth_form", clear_on_submit=False):
            # Canvas URL Input
            # NOTE: We intentionally do NOT use `value=` here.
            # Using `value=` would override Chrome autofill with the session state (empty on first run).
            # By only using `key=`, Streamlit will use the browser's autofill value if present,
            # or fall back to the session state if it exists from a previous interaction.
            url_input = st.text_input(
                'Enter Canvas URL',
                key="url_input",
                placeholder="https://your-school.instructure.com"
            )

            # API Token Input (same logic - no value= parameter)
            token_input = st.text_input(
                'Enter Canvas API Token', 
                type="password", 
                key="token_input"
            )
            
            # Log In Button
            submitted = st.form_submit_button('Log In', type="primary", use_container_width=True)

        if submitted:
            input_url = st.session_state.url_input.strip()
            input_token = st.session_state.token_input.strip()
            
            # Sync back to session state to prevent input glitching
            st.session_state['api_url'] = input_url
            st.session_state['api_token'] = input_token
            
            manager = CanvasManager(input_token, input_url)
            is_valid, message = manager.validate_token()
            
            if is_valid:
                st.session_state['api_token'] = input_token
                st.session_state['api_url'] = manager.api_url # Use potential auto-corrected URL
                st.session_state['is_authenticated'] = True
                st.session_state['user_name'] = message.split(": ")[1] if ": " in message else message
                
                # Save token to OS keyring (secure) and config to JSON
                try:
                    keyring_user = st.session_state['api_url'] or 'default'
                    keyring.set_password(KEYRING_SERVICE, keyring_user, st.session_state['api_token'])
                except Exception as e:
                    st.warning(f"Could not save token to system keyring: {e}. Token will not persist across sessions.")
                
                try:
                    config_data = {
                        'api_url': st.session_state['api_url']
                    }
                    if 'concurrent_downloads' in st.session_state:
                        config_data['concurrent_downloads'] = st.session_state['concurrent_downloads']
                        
                    if 'debug_mode' in st.session_state:
                        config_data['debug_mode'] = st.session_state['debug_mode']
                        
                    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f)
                except Exception as e:
                    st.error(f"Could not save config: {e}")
                    
                st.rerun()
            else:
                st.error(message)
        
        # Help Section
        with st.expander('How to get a Token?'):
            st.markdown('\n1. Go to **Account** -> **Settings** on Canvas.\n2. Scroll to **Approved Integrations**.\n3. Click **+ New Access Token**.\n4. Copy the long string and paste it here.\n')
        
        with st.expander('How to find your Canvas URL?'):
            # Use code block to prevent overflow and keep fixed width
            # Splitting instructions to ensure better rendering based on user feedback
            st.markdown("\n**Crucial Step:** You must input the *actual* Canvas URL, not your university's login portal.\n\n**How to find it:**\n1. Log in to Canvas in your browser.\n2. Look at the address bar **after** you have logged in.\n3. It often looks like `https://schoolname.instructure.com` (even if you typed `canvas.school.edu` to get there).\n4. Copy that URL and paste it here.\n")
    else:
        st.success(st.session_state['user_name'])
        
        # Navigation section (under logged in status)
        st.markdown("---")
        mode = st.session_state.get('current_mode', 'download')
        
        # Download mode button
        download_label = "📥 " + 'Download Courses'
        if mode == 'download':
            # Active state - light grey background, outlined style
            st.markdown(f"""
            <div style="background-color: #3a3a3a; border: 1px solid #555; border-radius: 6px; 
                        padding: 8px 16px; text-align: center; margin-bottom: 8px;">
                <span style="color: {theme.WHITE}; font-weight: 500;">{download_label}</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            if st.button(download_label, use_container_width=True, key="nav_btn_download"):
                st.session_state['current_mode'] = 'download'
                st.session_state['step'] = 1
                st.session_state['sync_mode'] = False
                st.session_state['sync_pairs'] = []  # Clear sync pairs
                st.rerun()
        
        # Sync mode button
        sync_label = "🔄 " + 'Sync Local Folders'
        if mode == 'sync':
            # Active state - light grey background, outlined style
            st.markdown(f"""
            <div style="background-color: #3a3a3a; border: 1px solid #555; border-radius: 6px; 
                        padding: 8px 16px; text-align: center; margin-bottom: 8px;">
                <span style="color: {theme.WHITE}; font-weight: 500;">{sync_label}</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            if st.button(sync_label, use_container_width=True, key="nav_btn_sync"):
                st.session_state['current_mode'] = 'sync'
                st.session_state['step'] = 1
                st.session_state['sync_mode'] = True
                st.session_state['sync_pairs'] = []  # Initialize sync pairs
                st.rerun()
                
        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        
        @st.dialog("⚙️ Settings", width="large")
        def _global_settings_dialog():
            st.markdown("""
                <style>
                    /* Maximize height of dialog content similar to course selector */
                    div.st-key-settings_scroll_container {
                        height: 65vh !important;
                        min-height: 65vh !important;
                        max-height: 65vh !important;
                        overflow-y: auto !important;
                        overflow-x: hidden !important;
                        padding-right: 5px;
                    }
                </style>
            """, unsafe_allow_html=True)
            
            with st.container(border=False, key="settings_scroll_container"):
                col1, col2 = st.columns(2, gap="large")
                
                with col1:
                    st.markdown("<h4 style='margin-bottom: 10px;'>📥 Download Settings</h4>", unsafe_allow_html=True)
                    
                    # Card 1: Concurrent Downloads
                    with st.container(border=True):
                        st.markdown("""
                            <div style='margin-bottom: -20px;'>
                                <h4 style='font-size: 1.05rem; margin: 0px 0px 2px 0px;'>Download Speed: Max Concurrent Downloads</h4>
                                <p style='font-size: 0.85rem; color: #cbd5e1; margin-top: 2px; margin-bottom: 8px;'>Controls how many files are downloaded simultaneously.</p>
                                <p style='font-size: 0.85rem; color: #fbbf24; margin-top: 0px; margin-bottom: 5px; line-height: 1.4;'>
                                    ⚠️ <b>Warning:</b> Canvas has strict rate limits. Setting this too high (e.g., 15) may cause the download/sync to crash due to server blocks. If you experience crashes or failed downloads, reduce this number and try again.
                                </p>
                                <div style='margin-top: 12px; margin-bottom: 0px;'>
                                    <span style='background-color: #1e293b; color: #94a3b8; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; border: 1px solid #334155;'>Default: 5</span>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        # Inject CSS to make the slider a bright light blue
                        st.markdown("""
                            <style>
                            div.stSlider > div[data-baseweb="slider"] > div > div > div {
                                background-color: {theme.ACCENT_LINK} !important;
                            }
                            div.stSlider > div[data-baseweb="slider"] > div > div[role="slider"] {
                                background-color: {theme.ACCENT_LINK} !important;
                                border-color: {theme.ACCENT_LINK} !important;
                            }
                            </style>
                        """, unsafe_allow_html=True)
                        
                        temp_max = st.slider("Simultaneous Files", min_value=1, max_value=15, value=st.session_state.get('concurrent_downloads', 5), key="temp_max_downloads", label_visibility="collapsed")
                        
                    # Card 2: Debug Mode
                    with st.container(border=True):
                        st.markdown("""
                            <div style='margin-bottom: -10px;'>
                                <h4 style='font-size: 1.05rem; margin-top: 0px; margin-bottom: 2px;'>Debug Mode</h4>
                                <p style='font-size: 0.85rem; color: #cbd5e1; margin-top: 2px; margin-bottom: 10px;'>Enable advanced terminal logging for troubleshooting.</p>
                            </div>
                        """, unsafe_allow_html=True)
                        temp_debug = st.checkbox("Enable Troubleshooting Mode", value=st.session_state.get('debug_mode', False), key="temp_debug_mode")

                with col2:
                    st.markdown("<h4 style='margin-bottom: 10px;'>🔄 Sync Settings</h4>", unsafe_allow_html=True)
                    
                    # Card 3: Sync Settings Placeholder
                    with st.container(border=True):
                        st.info("Future sync optimizations and configuration options will appear here.")

            st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)
            
            c_save, c_cancel = st.columns([1, 1])
            with c_save:
                if st.button("Save Settings", type="primary", use_container_width=True):
                    st.session_state['concurrent_downloads'] = temp_max
                    st.session_state['debug_mode'] = temp_debug
                    
                    # Persist to config
                    if os.path.exists(CONFIG_FILE):
                        try:
                            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                                config_data = json.load(f)
                        except Exception:
                            config_data = {}
                    else:
                        config_data = {}
                        
                    config_data['api_url'] = st.session_state.get('api_url', '')
                    config_data.pop('api_token', None)  # Never write token to JSON
                    config_data['concurrent_downloads'] = temp_max
                    config_data['debug_mode'] = temp_debug
                    
                    try:
                        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                            json.dump(config_data, f)
                    except Exception as e:
                        st.error(f"⚠️ Could not save settings to disk: {e}")
                        
                    st.rerun()
            with c_cancel:
                if st.button("Cancel", use_container_width=True):
                    st.rerun()

        # Add the settings button in the sidebar
        if st.button("⚙️ Settings", use_container_width=True, key="nav_btn_settings"):
            _global_settings_dialog()
            
        # Logout button at the very bottom
        st.markdown("---")
        st.markdown("")  # Spacer
        st.markdown("")
        if st.button('Log Out / Edit Token', use_container_width=True):
            # Wipe token from OS keyring
            try:
                keyring_user = st.session_state.get('api_url', '') or 'default'
                keyring.delete_password(KEYRING_SERVICE, keyring_user)
            except Exception:
                pass  # Token may not exist in keyring yet
            
            st.session_state['is_authenticated'] = False
            st.session_state['api_token'] = ""
            st.session_state['step'] = 1
            st.session_state['current_mode'] = 'download'
            # Clear the course cache to prevent showing old user's courses
            fetch_courses.clear()
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            st.rerun()

        # Version badge
        st.markdown(
            f"<div style='text-align:center;color:{theme.TEXT_MUTED};font-size:0.75rem;"
            f"padding:20px 0 5px 0;'>Canvas Downloader v{__version__}</div>",
            unsafe_allow_html=True,
        )

# --- Main Content ---
st.title('Canvas LMS Course Material Downloader')

if not st.session_state['is_authenticated']:
    st.info('👈 Please authenticate in the sidebar to continue.')
    st.stop()

# --- Wizard Steps ---
# Wrap in st.empty().container() to prevent stale elements from previous steps
# persisting during long-running operations (e.g., sync downloads via asyncio.run).
_main_content = st.empty()
with _main_content.container():

    # STEP 1: Different UI based on mode
    if st.session_state['step'] == 1:
        
        # ========== SYNC MODE - STEP 1 ==========
        if st.session_state['current_mode'] == 'sync':
            render_sync_step1(fetch_courses, _main_content)
        
            # ========== DOWNLOAD MODE - STEP 1 ==========
        else:
            render_download_wizard(st, 1)
            st.markdown(f'<div class="step-header">{'Step 1: Select Courses'}</div>', unsafe_allow_html=True)
            
            filter_mode = st.radio(
                'Show:',
                ['Favorites Only', 'All Courses'],
                horizontal=True
            )
            favorites_only = (filter_mode == 'Favorites Only')
            
            courses = fetch_courses(st.session_state['api_token'], st.session_state['api_url'], favorites_only)
            
            if not courses:
                st.warning('No courses found.')
            else:
                # --- CBS Filters Feature ---
                
                # Filter Toggle
                show_filters = st.toggle('Enable CBS Filters')
                
                filtered_courses = courses
                
                if show_filters:
                    # 1. Parse metadata for all courses
                    # We do this on the fly; it's fast enough for <100 courses.
                    course_meta = {}
                    all_types = set()
                    all_semesters = set()
                    all_years = set()
                    
                    for c in courses:
                        # Parse from full name (or friendly name? parser handles raw strings)
                        # We use the full name to be safe as it contains the codes
                        full_name_str = f"{c.name} ({c.course_code})" if hasattr(c, 'course_code') else c.name
                        meta = parse_cbs_metadata(full_name_str)
                        course_meta[c.id] = meta
                        
                        if meta['type']: all_types.add(meta['type'])
                        if meta['semester']: all_semesters.add(meta['semester'])
                        if meta['year_full']: all_years.add(meta['year_full'])
                    
                    # 2. Render Filter Widgets
                    with st.container(border=True):
                        st.markdown(f"**{'Filter Criteria'}**")
                        col_f1, col_f2, col_f3 = st.columns(3)
                        
                        with col_f1:
                            sel_types = st.multiselect(
                                'Class Type',
                                options=sorted(list(all_types)),
                                format_func=lambda x: x
                            )
                        with col_f2:
                            sel_sem = st.multiselect(
                                'Semester',
                                options=sorted(list(all_semesters)),
                                format_func=lambda x: x
                            )
                        with col_f3:
                            sel_years = st.multiselect(
                                'Year',
                                options=sorted(list(all_years), reverse=True)
                            )
                    
                    # 3. Apply Filters
                    if sel_types or sel_sem or sel_years:
                        filtered_courses = []
                        for c in courses:
                            meta = course_meta[c.id]
                            # Logic: AND across categories, OR within category
                            
                            # Type Check
                            match_type = True
                            if sel_types:
                                match_type = meta['type'] in sel_types
                            
                            # Semester Check
                            match_sem = True
                            if sel_sem:
                                match_sem = meta['semester'] in sel_sem
                                
                            # Year Check
                            match_year = True
                            if sel_years:
                                match_year = meta['year_full'] in sel_years
                                
                            if match_type and match_sem and match_year:
                                filtered_courses.append(c)
                        
                        if not filtered_courses:
                            st.info('No courses match the selected filters.')

                # "Select All" buttons - operate on FILTERED list
                col_sa1, col_sa2, _ = st.columns([1.3, 1.3, 10], gap="small")
                select_all_clicked = col_sa1.button('Select All', key="btn_select_all", use_container_width=True)
                clear_sel_clicked = col_sa2.button('Clear Selection', key="btn_clear_sel", use_container_width=True)
                
                # Handle button clicks - Update session state keys directly
                # IMPORTANT: Select All now only selects visible (filtered) courses!
                if select_all_clicked:
                    # Merge existing selection with visible courses
                    current_ids = set(st.session_state['selected_course_ids'])
                    visible_ids = {c.id for c in filtered_courses}
                    new_ids = current_ids.union(visible_ids)
                    st.session_state['selected_course_ids'] = list(new_ids)
                    
                    # Update widgets
                    for cid in visible_ids:
                        st.session_state[f"chk_{cid}"] = True
                    st.rerun()
                    
                if clear_sel_clicked:
                    # Remove visible courses from selection
                    # (Or clear all? Standard behavior is usually "Clear Selection" = Clear All)
                    # Let's keep it simple: Clear All (Global) or Clear Visible?
                    # "Clear Selection" usually implies resetting the state. Let's clear ALL for simplicity.
                    st.session_state['selected_course_ids'] = []
                    # Reset widgets for filtered courses

                    for c in courses: # Clear ALL widgets to be safe
                         st.session_state[f"chk_{c.id}"] = False
                    st.rerun()

                # Error container for validation messages (placed above the list)
                error_container = st.empty()

                # Course List with Checkboxes (Render Filtered List)
                selected_ids = st.session_state['selected_course_ids']
                new_selected_ids = [] # Temp list to rebuild selection from widgets
                
                # We need to preserve selections for HIDDEN courses too!
                # So `new_selected_ids` should start with ids that are SELECTED but NOT IN `filtered_courses`
                filtered_ids = {fc.id for fc in filtered_courses}

                
                # --- SORTING: Selected first, then Alphabetical ---
                # We sort the filtered_courses list in-place before rendering
                saved_selection_set = set(st.session_state['selected_course_ids'])
                
                # Key: (is_NOT_selected, name_lower)
                # selected (=True) -> not selected (=False/0) -> comes first
                filtered_courses.sort(key=lambda c: (c.id not in saved_selection_set, (c.name or "").lower()))
                
                for sid in selected_ids:
                    if sid not in filtered_ids:
                        new_selected_ids.append(sid)

                for course in filtered_courses:
                    # Logic for names
                    full_name_str = f"{esc(course.name)} ({course.course_code})" if hasattr(course, 'course_code') else course.name
                    friendly = friendly_course_name(full_name_str)
                    
                    # If friendly is same as full, don't show duplicate in parens?
                    # User asked for: "friendly course names ... followed by the full course name ... in parentheses"
                    # Even if they are substantially similar, let's follow the pattern, 
                    # but maybe avoid literal exact duplication if possible. 
                    # Assuming they will differ slightly due to stripping.
                    
                    checkbox_key = f"chk_{course.id}"
                    
                    # Columns for layout: [Checkbox] [Styled Name]
                    # Adjust ratio to keep checkbox tight
                    c1, c2 = st.columns([0.035, 0.965])
                    
                    with c1:
                        # Determine current state for value=...
                        is_checked = False
                        if checkbox_key in st.session_state:
                            # Let Streamlit handle state via key, but we can read it to sync `selected_course_ids` logic if needed?
                            # Actually, providing `value` when `key` exists in session_state triggers a warning in some versions,
                            # or is ignored. Best to rely on session_state if present.
                            # But our "Select All" logic writes to session_state.
                            pass 
                        else:
                            # Initialize from `selected_ids` list if not in session state
                            if course.id in selected_ids:
                                is_checked = True 
                                # Pre-seed session state to avoid widget value mismatch (optional but safer)
                                # st.session_state[checkbox_key] = True

                        # Render checkbox with collapsed label
                        # Note: We must fetch the result to append to `new_selected_ids`
                        # Since we set the key, `st.checkbox` will auto-read/write that key in session_state.
                        # However, for the *return value* to be correct in this run loop:
                        
                        # We use `value=is_checked` only if key not in session state?
                        # Streamlit rule: if key in session_state, value arg is ignored (mostly).
                        
                        checked = False
                        if checkbox_key in st.session_state:
                             checked = st.checkbox(friendly, key=checkbox_key, label_visibility="collapsed")
                        else:
                             checked = st.checkbox(friendly, value=is_checked, key=checkbox_key, label_visibility="collapsed")
                             
                    with c2:
                        # Styled text
                        # Vertically align with checkbox (checkbox is ~ top aligned or center?)
                        # Adding a small top margin to markdown might help align with checkbox center
                        # Checkbox is standard ~24px height. Text line height ~1.5. 
                        # This usually aligns "okay" by default, or text sits slightly high.
                        # Let's try default first.
                        # Using div with styling
                        st.markdown(
                            f'<div style="margin-top: 8px;">'
                            f'<strong>{friendly}</strong> '
                            f'<span style="color:{theme.TEXT_DIM}; font-size:0.9em;">({full_name_str})</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                    if checked:
                        new_selected_ids.append(course.id)
                
                st.session_state['selected_course_ids'] = new_selected_ids

                st.markdown("---")
                if st.button('Continue', type="primary"):
                    if not st.session_state['selected_course_ids']:
                        error_container.error('Please select at least one course.')
                    else:
                        st.session_state['step'] = 2
                        st.rerun()

    # STEP 2: DOWNLOAD SETTINGS
    elif st.session_state['step'] == 2:
        render_download_wizard(st, 2)
        # 1. Squeeze the Main "Step 2" Header
        st.markdown("<h2 style='margin-bottom: -10px;'>Step 2: Download Settings</h2>", unsafe_allow_html=True)
        step2_container = st.empty()
        with step2_container.container():
            # Removed "Download Structure" per request
            mode_options = [
                'With subfolders (Matches Canvas Modules)', 
                # 'Files (Course Folders)', # Removed per user request
                'Flat (All files in one folder)'
            ]
            
            # Determine current index
            current_mode_idx = 0
            # If mode is 'files' (legacy), default back to 0 (modules)
            if st.session_state['download_mode'] == 'flat':
                current_mode_idx = 1
                
            mode_choice = st.radio(
                'Choose how files should be organized:',
                mode_options,
                index=current_mode_idx
            )
            
            if mode_choice == 'With subfolders (Matches Canvas Modules)':
                st.session_state['download_mode'] = 'modules'
            # elif mode_choice == 'Files (Course Folders)':
            #     st.session_state['download_mode'] = 'files'
            else:
                st.session_state['download_mode'] = 'flat'
            
            # 2. File Types (Radio buttons have standard padding)
            st.markdown("<h3 style='margin-top: 15px; margin-bottom: -10px;'>File Types</h3>", unsafe_allow_html=True)
            filter_choice = st.radio(
                'File Types', # Hidden label via label_visibility if needed, but subheader is fine
                ['All Files', 'Pdf & Powerpoint only'],
                index=0 if st.session_state['file_filter'] == 'all' else 1,
                label_visibility="collapsed"
            )
            st.session_state['file_filter'] = 'all' if filter_choice == 'All Files' else 'study'
            
            # --- NotebookLM Compatible Download ---
            TOTAL_NOTEBOOK_SUBS = 8 # Update this number when adding more features later

            def _master_toggle_changed():
                # Force all sub-checkboxes to match the master toggle's new state
                st.session_state['convert_zip'] = st.session_state['notebooklm_master']
                st.session_state['convert_pptx'] = st.session_state['notebooklm_master']
                st.session_state['convert_html'] = st.session_state['notebooklm_master']
                st.session_state['convert_code'] = st.session_state['notebooklm_master']
                st.session_state['convert_urls'] = st.session_state['notebooklm_master']
                st.session_state['convert_word'] = st.session_state['notebooklm_master']
                st.session_state['convert_video'] = st.session_state['notebooklm_master']
                st.session_state['convert_excel'] = st.session_state['notebooklm_master']

            def _sub_toggle_changed():
                # Calculate how many sub-checkboxes are currently active
                active_subs = sum([st.session_state.get('convert_zip', False), st.session_state.get('convert_pptx', False), st.session_state.get('convert_html', False), st.session_state.get('convert_code', False), st.session_state.get('convert_urls', False), st.session_state.get('convert_word', False), st.session_state.get('convert_video', False), st.session_state.get('convert_excel', False)])
                # Master is only True if ALL sub-checkboxes are True
                st.session_state['notebooklm_master'] = (active_subs == TOTAL_NOTEBOOK_SUBS)

            # 1. Inject Borderless Expander + Tree-View CSS
            st.markdown("""
            <style>
            /* 1. Target ONLY the specific expander containing the master checkbox */
            [data-testid="stExpander"]:has(.st-key-notebooklm_master) details {
                border-style: none !important;
                background-color: transparent !important;
            }
            [data-testid="stExpander"]:has(.st-key-notebooklm_master) summary {
                padding-left: 0 !important;
                padding-right: 0 !important;
                background-color: transparent !important;
            }
            [data-testid="stExpander"]:has(.st-key-notebooklm_master) [data-testid="stExpanderDetails"] {
                padding-left: 0 !important;
                padding-right: 0 !important;
                padding-bottom: 0 !important;
            }
            [data-testid="stExpander"]:has(.st-key-notebooklm_master) summary p {
                font-size: 1.75rem !important;
                font-weight: 600 !important;
            }

            /* 2. Tree-view styling for nested sub-checkboxes */
            .st-key-convert_zip, .st-key-convert_pptx, .st-key-convert_word, 
            .st-key-convert_excel, .st-key-convert_html, .st-key-convert_code, 
            .st-key-convert_urls, .st-key-convert_video {
                margin-left: 28px !important;
                padding-left: 15px !important;
                border-left: 2px solid {theme.BG_CARD_HOVER} !important; 
                margin-top: -12px !important; 
                padding-top: 4px !important;
                padding-bottom: 4px !important;
            }
            .st-key-convert_zip { margin-top: 0px !important; padding-top: 8px !important; }
            .st-key-convert_video { margin-bottom: 10px !important; padding-bottom: 8px !important; }
            </style>
            """, unsafe_allow_html=True)

            notebook_sub_keys = [
                'convert_zip', 'convert_pptx', 'convert_word', 'convert_excel',
                'convert_html', 'convert_code', 'convert_urls', 'convert_video'
            ]
            TOTAL_NOTEBOOK_SUBS = len(notebook_sub_keys)
            current_active = sum(1 for k in notebook_sub_keys if st.session_state.get(k, False))

            with st.expander("🛠️ Additional Settings", expanded=False):
                # Master Toggle (always visible)
                st.checkbox(
                    f"**NotebookLM Compatible Download** &nbsp; :gray[({current_active}/{TOTAL_NOTEBOOK_SUBS})]",
                    key="notebooklm_master",
                    on_change=_master_toggle_changed,
                    help="Enable conversions to optimize files for AI processing."
                )
                
                # Sub-toggles directly underneath (Tree-view styling via CSS)
                st.checkbox(
                    "Auto-Extract Archives (.zip, .tar.gz)",
                    key="convert_zip",
                    on_change=_sub_toggle_changed,
                    help="Extracts internal files from archives so downstream tools can ingest them. Stubs the archive file to skip next sync."
                )
                st.checkbox(
                    "Convert PowerPoints (.pptx) to PDF",
                    key="convert_pptx",
                    on_change=_sub_toggle_changed,
                    help="Converts .pptx/.ppt files to PDF after download using Microsoft Office. Requires PowerPoint installed."
                )
                st.checkbox(
                    "Convert Old Word Docs (.doc, .rtf) to PDF",
                    key="convert_word",
                    on_change=_sub_toggle_changed,
                    help="Converts legacy Word documents to PDF for accurate NotebookLM ingestion using Microsoft Office. Modern .docx are ignored."
                )
                st.checkbox(
                    "Convert Excel Files (.xlsx, .xls) to PDF",
                    key="convert_excel",
                    on_change=_sub_toggle_changed,
                    help="Converts Excel workbooks to PDF. Restructures PageSetup to ensure tabular content is 1 page wide and infinitely tall."
                )
                st.checkbox(
                    "Convert Canvas Pages (HTML) to Markdown",
                    key="convert_html",
                    on_change=_sub_toggle_changed,
                    help="Converts Canvas Pages from HTML to clean Markdown formats."
                )
                st.checkbox(
                    "Convert Code & Data Files to .txt",
                    key="convert_code",
                    on_change=_sub_toggle_changed,
                    help="Appends a .txt extension to programming files (e.g., .py, .java, .csv, .json) to ensure they can be read by NotebookLM."
                )
                st.checkbox(
                    "Compile Web Links (.url) into a single list",
                    key="convert_urls",
                    on_change=_sub_toggle_changed,
                    help="Scans for downloaded web/video shortcuts and securely extracts all URLs into a master NotebookLM text file."
                )
                st.checkbox(
                    "Extract Audio (.mp3) from Videos (.mp4, .mov)",
                    key="convert_video",
                    on_change=_sub_toggle_changed,
                    help="Converts video formats (.mp4, .mov, .mkv) into .mp3 format for ingestion into Google NotebookLM. Drops original video size."
                )

            # 2. Destination (Columns have weird padding)
            st.markdown("<h3 style='margin-top: 5px; margin-bottom: -15px;'>Destination</h3>", unsafe_allow_html=True)
            
            # 3. Extreme ratio to kill dead space, small gap for a ~20px distance
            col1, col2 = st.columns([1, 6], gap="small") 

            with col1:
                # 28px spacer pushes the button down to align with the text box (ignoring the "Path" label)
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button('📂 Select Folder'):
                    select_folder()
            with col2:
                st.text_input('Path', value=st.session_state['download_path'], disabled=True)

            st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
            col_conf, col_back, _ = st.columns([1.2, 1, 5])
            with col_conf:
                # Button label changes based on mode
                button_label = 'Sync (Download) Selected Files' if st.session_state['current_mode'] == 'sync' else 'Confirm and Download'
                if st.button(button_label, type="primary", use_container_width=True):
                    try:
                        # Initialize download state
                        all_courses = fetch_courses(st.session_state['api_token'], st.session_state['api_url'], False)
                        course_map = {c.id: c for c in all_courses}
                        courses_to_download = [course_map[cid] for cid in st.session_state['selected_course_ids'] if cid in course_map]
                        
                        st.session_state['courses_to_download'] = courses_to_download
                        st.session_state['current_course_index'] = 0
                        st.session_state['cancel_requested'] = False
                        st.session_state['total_items'] = 0
                        st.session_state['downloaded_items'] = 0
                        st.session_state['course_mb_downloaded'] = {}
                        st.session_state['log_content'] = ""  # Initialize log content
                        
                        # Task 1: Save the State on Button Click (Streamlit Widget Cleanup Fix)
                        st.session_state['persistent_convert_zip'] = st.session_state.get('convert_zip', False)
                        st.session_state['persistent_convert_pptx'] = st.session_state.get('convert_pptx', False)
                        st.session_state['persistent_convert_html'] = st.session_state.get('convert_html', False)
                        st.session_state['persistent_convert_code'] = st.session_state.get('convert_code', False)
                        st.session_state['persistent_convert_urls'] = st.session_state.get('convert_urls', False)
                        st.session_state['persistent_convert_word'] = st.session_state.get('convert_word', False)
                        st.session_state['persistent_convert_video'] = st.session_state.get('convert_video', False)
                        st.session_state['persistent_convert_excel'] = st.session_state.get('convert_excel', False)
                        
                        # Clear debug log once at session start (subsequent courses append)
                        if st.session_state.get('debug_mode', False):
                            from canvas_debug import clear_debug_log
                            clear_debug_log(Path(st.session_state['download_path']) / "debug_log.txt")
                        
                        if st.session_state['current_mode'] == 'sync':
                            # Sync mode - go to Step 4 (Analysis)
                            st.session_state['download_status'] = 'analyzing'
                            st.session_state['step'] = 4
                        else:
                            # Download mode - go to Step 3 (Progress)
                            st.session_state['download_status'] = 'scanning'
                            st.session_state['step'] = 3
                        
                        # Brief pause to ensure state is saved before rerun
                        time.sleep(0.1)
                        step2_container.empty() # Clear EVERYTHING in Step 2
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error initializing: {e}")

            with col_back:
                if st.button('Back', use_container_width=True):
                    st.session_state['step'] = 1
                    st.rerun()


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
                    course_files = cm.get_course_files_metadata(course, progress_callback=analysis_progress_hook)
                    
                    # Apply file filter if needed ('study' vs 'all')
                    allowed_exts = ['.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx']
                    filtered_files = []
                    for f in course_files:
                        if st.session_state['file_filter'] == 'study':
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
                    total_mb += sum(getattr(f, 'size', 0) for f in filtered_files) / (1024 * 1024)
                    
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
                
                def render_dashboard():
                    # Calculate current progress
                    current_mb = sum(st.session_state.get('course_mb_downloaded', {}).values())
                    current_files = st.session_state.get('downloaded_items', 0) + st.session_state.get('failed_items', 0)
                    
                    if total_items > 0:
                        percent = int((current_files / total_items) * 100)
                        percent = min(100, percent) # Clamp to max 100
                        if current_files == total_items:
                            percent = 100
                    else:
                        percent = 0

                    # Calculate Speed & ETA
                    elapsed = time.time() - start_time
                    speed_mb_s = (current_mb / elapsed) if elapsed > 0 else 0.0
                    remaining_mb = max(0, total_mb - current_mb) # prevent negative remaining mb
                    eta_seconds = (remaining_mb / speed_mb_s) if speed_mb_s > 0 else 0
                    eta_string = time.strftime('%M:%S', time.gmtime(max(0, eta_seconds)))
                    
                    header_placeholder.markdown(f'''
                    <div style="margin-bottom: 0.5rem;">
                        <p style="margin: 0; font-size: 0.8rem; color: {theme.TEXT_SECONDARY}; text-transform: uppercase;">📦 Downloading Courses</p>
                        <h3 style="margin: 0; padding-top: 0.1rem; color: {theme.TEXT_PRIMARY};">{esc(course.name)}</h3>
                    </div>
                    ''', unsafe_allow_html=True)

                    progress_placeholder.markdown(f'''
                    <div style="background-color: {theme.BG_CARD}; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
                        <div style="background-color: {theme.ACCENT_BLUE}; width: {percent}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
                        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold;">
                            {percent}%
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
                    
                    metrics_placeholder.markdown(f'''
                    <div style="display: flex; justify-content: center; gap: 4rem; background-color: {theme.BG_DARK}; padding: 15px 25px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-top: 5px; margin-bottom: 15px;">
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Downloaded</span>
                            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{current_mb:.1f} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {total_mb:.1f} MB</span></span>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Speed</span>
                            <span style="color: #10B981; font-size: 1.2rem; font-weight: bold;">{speed_mb_s:.1f} <span style="font-size: 0.9rem;">MB/s</span></span>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Files</span>
                            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{current_files} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {total_items}</span></span>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Time Remaining</span>
                            <span style="color: #F59E0B; font-size: 1.2rem; font-weight: bold;">{eta_string}</span>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
                    
                    log_content = "<br>".join(reversed(list(log_deque)))
                    log_placeholder.markdown(f'''
                    <div style="background-color: {theme.BG_TERMINAL}; color: {theme.TERMINAL_TEXT}; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 0.85rem; height: 140px; border: 1px solid {theme.BORDER_TERMINAL}; line-height: 1.6; overflow-y: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">
                        {log_content}
                    </div>
                    ''', unsafe_allow_html=True)
                
                # Render initial state
                render_dashboard()
                
                def update_ui(msg, progress_type='log', **kwargs):
                    """Update UI with progress information. Wrapped in try/except for async safety."""
                    try:
                        # Exit silently if cancellation is in progress
                        if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'):
                            return
                        
                        if progress_type in ('download', 'page', 'link'):
                            st.session_state['downloaded_items'] += 1
                            if msg:
                                active_file_placeholder.markdown(f"<div style='color: {theme.ACCENT_LINK}; margin-bottom: 10px; font-weight: 500;'>🔄 Currently downloading: {msg}...</div>", unsafe_allow_html=True)
                                log_deque.append(f"[✅] Finished: {msg}")
                            render_dashboard()
                            
                        elif progress_type == 'error':
                            st.session_state['failed_items'] += 1
                            
                            if msg:
                                if isinstance(msg, DownloadError):
                                    error_obj = msg
                                else:
                                    error_obj = DownloadError(course.name, "Unknown Item", "Generic Error", str(msg))
                                
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
                    except BaseException:
                        # Silently catch Streamlit's StopException / RerunException during async teardown
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
                asyncio.run(cm.download_course_async(
                    course,
                    st.session_state['download_mode'],
                    st.session_state['download_path'],
                    progress_callback=update_ui,
                    check_cancellation=check_cancellation,
                    file_filter=st.session_state['file_filter'],
                    debug_mode=st.session_state.get('debug_mode', False),
                    post_processing_settings=_pp_settings
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
                from datetime import datetime
                from canvas_debug import log_debug

                save_dir = st.session_state['download_path']
                debug_mode = st.session_state.get('debug_mode', False)
                root_dir = Path(save_dir)
                course_name = cm._sanitize_filename(course.name)
                course_folder_for_debug = root_dir / course_name
                debug_file = (root_dir / "debug_log.txt") if debug_mode else None
                db_path = course_folder_for_debug / ".canvas_sync.db"

                # Inject course header into the global debug log (append, never overwrite)
                if debug_file:
                    try:
                        with open(debug_file, "a", encoding="utf-8") as f:
                            f.write(f"\n{'='*50}\n--- Post-Processing: {esc(course.name)} ---\n{'='*50}\n")
                    except Exception:
                        pass

                # --- Post-Download Conversion Pipeline (Shared Module) ---
                from post_processing import run_all_conversions, UIBridge
                from sync_manager import SyncManager

                course_name_sanitized = cm._sanitize_filename(course.name)
                course_folder = Path(st.session_state['download_path']) / course_name_sanitized

                if course_folder.exists():
                    _convert_keys = ['convert_zip', 'convert_pptx', 'convert_word', 'convert_excel',
                                     'convert_html', 'convert_code', 'convert_urls', 'convert_video']
                    contract = {k: st.session_state.get(f'persistent_{k}', False) for k in _convert_keys}

                    if any(contract.values()):
                        pp_sm = SyncManager(course_folder, course.id, course.name)
                        pp_ui = UIBridge(
                            header_placeholder=header_placeholder,
                            progress_placeholder=progress_placeholder,
                            metrics_placeholder=metrics_placeholder,
                            log_placeholder=log_placeholder,
                            active_file_placeholder=active_file_placeholder,
                            log_lines=log_deque,
                            is_cancelled=lambda: st.session_state.get('download_cancelled', False),
                            error_log_path=Path(st.session_state['download_path']),
                        )
                        run_all_conversions(
                            course_folder=course_folder,
                            sm=pp_sm,
                            contract=contract,
                            ui=pp_ui,
                            course_name=course.name,
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
                                f.write(f"{err}\n")
                    except Exception as e:
                        logger.error(f"Failed to write session log: {e}")
                # -------------------------------------------------------------------
        
        elif st.session_state['download_status'] == 'done':
            st.success('Download Completed Successfully!')
            # Show download location (no background color)
            st.markdown(f"**{f"You can find the downloaded files here: {st.session_state['download_path']}"}**")
            # Show final progress bar at 100%
            try:
                progress_container.markdown(f"""
                    <div style="position: relative; height: 35px; background-color: #f0f2f6; border-radius: 5px; overflow: hidden;">
                        <div style="width: 100%; height: 100%; background-color: #1f77b4;"></div>
                        <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: #333;">{'Complete!'}</div>
                    </div>
                """, unsafe_allow_html=True)
                status_text.text(f'Downloaded {total} course(s).')
            except Exception:
                pass
            
            # Check for download errors (In-Memory first, fallback to disk)
            error_messages = st.session_state.get('download_errors_list', [])
            
            # Fallback (optional): If empty, check disk (legacy/redundant if list works)
            if not error_messages:
                from pathlib import Path
                download_path = Path(st.session_state['download_path'])
                
                # Collect errors from all course folders
                for course in st.session_state['courses_to_download']:
                    cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                    course_name = cm._sanitize_filename(course.name)
                    error_file = download_path / course_name / "download_errors.txt"
                    if error_file.exists():
                        try:
                            with open(error_file, 'r', encoding='utf-8') as f:
                                errors = f.read().strip()
                                if errors:
                                    error_messages.extend(errors.split('\n'))
                        except Exception:
                            pass
            
            # Display error summary if there are errors
            if error_messages:
                st.warning(f'⚠️ {len(error_messages)} error(s) occurred during download')
                
                with st.expander('View Error Details', expanded=True):
                    # Group by course
                    errors_by_course = {}
                    for err in error_messages:
                        c_name = err.course_name if isinstance(err, DownloadError) else "Unknown"
                        if c_name not in errors_by_course: errors_by_course[c_name] = []
                        errors_by_course[c_name].append(err)
                    
                    for course_name, errs in errors_by_course.items():
                        st.markdown(f"**{course_name}** ({len(errs)})")
                        for err in errs:
                            if isinstance(err, DownloadError):
                                item_label = f"{err.item_name}: " if err.item_name else ""
                                st.markdown(f"- {item_label}{err.message}", unsafe_allow_html=True)
                            else:
                                st.text(f"  • {err}")
                    
                    st.caption('📄 Full error details are saved in `download_errors.txt` in each course folder.')

                # In-App Error Log Viewer — collect error log paths from course folders
                download_path = Path(st.session_state['download_path'])
                error_log_paths = []
                for course in st.session_state.get('courses_to_download', []):
                    cm_temp = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                    course_folder = download_path / cm_temp._sanitize_filename(course.name)
                    log_file = course_folder / "download_errors.txt"
                    if log_file.exists():
                        error_log_paths.append(log_file)
                
                if error_log_paths:
                    col_log_dl, _ = st.columns([0.3, 0.7])
                    with col_log_dl:
                        if st.button("📄 View Full Error Log", key="dl_view_error_log", use_container_width=True):
                            _download_error_log_dialog(error_log_paths)

                # Retry Button
                st.markdown("<div style='margin-top: -15px; margin-bottom: 25px;'></div>", unsafe_allow_html=True)
                retry_label = "Retry Failed Items"
                col_retry, _ = st.columns([0.25, 0.75])
                with col_retry:
                    if st.button(f"🔄 {retry_label}", type="secondary", key="retry_failed_btn", use_container_width=True):
                         st.session_state['current_course_index'] = 0
                         st.session_state['download_status'] = 'scanning'
                         st.session_state['downloaded_items'] = 0
                         st.session_state['failed_items'] = 0
                         st.session_state['download_errors_list'] = []
                         st.session_state['log_content'] = ""
                         st.rerun()
        
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
                    'sync_pairs', 'sync_pairs_loaded'
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
