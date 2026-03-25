import streamlit as st
from canvas_logic import CanvasManager, DownloadError
from post_processing import run_all_conversions, UIBridge
from sync_manager import SyncManager
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
)

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
_NOTEBOOK_SUB_KEYS_INIT = [
    'convert_zip', 'convert_pptx', 'convert_word', 'convert_excel',
    'convert_html', 'convert_code', 'convert_urls', 'convert_video'
]
if 'notebooklm_master' not in st.session_state:
    st.session_state['notebooklm_master'] = False
for _nk in _NOTEBOOK_SUB_KEYS_INIT:
    if _nk not in st.session_state:
        st.session_state[_nk] = False

# Secondary (Additional Course Content) toggles — all OFF by default in Download Mode
_SECONDARY_CONTENT_KEYS = [
    'dl_assignments', 'dl_syllabus', 'dl_announcements',
    'dl_discussions', 'dl_quizzes', 'dl_rubrics', 'dl_submissions',
]
TOTAL_SECONDARY_SUBS = len(_SECONDARY_CONTENT_KEYS)
for _sck in _SECONDARY_CONTENT_KEYS:
    if _sck not in st.session_state:
        st.session_state[_sck] = False
if 'dl_secondary_master' not in st.session_state:
    st.session_state['dl_secondary_master'] = False
if 'dl_isolate_secondary' not in st.session_state:
    st.session_state['dl_isolate_secondary'] = False  # Default: inline with modules

# --- Helper Functions ---
def get_base64_image(image_path):
    """Reads a local file and returns its Base64 string representation."""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode()
    except Exception as e:
        logger.error(f"Failed to encode image {image_path}: {e}")
        return ""

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

# --- Sidebar: Authentication ---
with st.sidebar:
    st.markdown("---")
    st.title('Canvas Downloader')
    
    # Auth Logic
    
    def get_config_path():
        from ui_helpers import get_config_dir
        return os.path.join(get_config_dir(), 'canvas_downloader_settings.json')

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
                    # platform and base64 imported at module level
                    
                    loaded_token = ''
                    if platform.system() == 'Darwin':
                        # macOS: Avoid keychain permission prompts by loading from config json via base64
                        encoded_token = config.get('mac_api_token', '')
                        if encoded_token:
                            try:
                                loaded_token = base64.b64decode(encoded_token.encode('utf-8')).decode('utf-8')
                            except Exception:
                                pass
                    else:
                        # Windows: Load token from OS keyring (secure)
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
                
                # platform and base64 imported at module level
                
                # Setup base config data
                config_data = {}
                if os.path.exists(CONFIG_FILE):
                    try:
                        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                    except Exception:
                        pass
                        
                config_data['api_url'] = st.session_state['api_url']
                if 'concurrent_downloads' in st.session_state:
                    config_data['concurrent_downloads'] = st.session_state['concurrent_downloads']
                if 'debug_mode' in st.session_state:
                    config_data['debug_mode'] = st.session_state['debug_mode']
                
                # Save token tracking macOS vs Windows
                if platform.system() == 'Darwin':
                    # macOS: Save to JSON obfuscated to avoid keychain prompts
                    try:
                        encoded = base64.b64encode(st.session_state['api_token'].encode('utf-8')).decode('utf-8')
                        config_data['mac_api_token'] = encoded
                    except Exception as e:
                        st.warning(f"Could not obfuscate token: {e}")
                else:
                    # Windows: Save to OS keyring (secure)
                    try:
                        keyring_user = st.session_state['api_url'] or 'default'
                        keyring.set_password(KEYRING_SERVICE, keyring_user, st.session_state['api_token'])
                    except Exception as e:
                        st.warning(f"Could not save token to system keyring: {e}. Token will not persist across sessions.")
                
                try:
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
            # platform imported at module level
            
            # Wipe token from OS keyring
            if platform.system() != 'Darwin':
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
                try:
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    config_data.pop('api_token', None)
                    config_data.pop('mac_api_token', None)  # Remove macOS token
                    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f)
                except Exception as e:
                    logger.warning(f"Could not update config on logout: {e}")
            st.rerun()

        # Version badge
        st.markdown(
            f"<div style='text-align:center;color:{theme.TEXT_MUTED};font-size:0.75rem;"
            f"padding:20px 0 5px 0;'>Canvas Downloader v{__version__}</div>",
            unsafe_allow_html=True,
        )


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

        def _load_b64(path):
            import base64
            try:
                with open(path, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except FileNotFoundError:
                return ""

        b64_icon_all = _load_b64("assets/icon_all_files.png")
        b64_icon_study = _load_b64("assets/icon_study_files.png")
        active_include = st.session_state.get('file_filter', 'all')
        active_include_key = "all" if active_include == 'all' else "study"
        try:
            import theme
            bg_color_active = theme.BG_CARD_HOVER if hasattr(theme, 'BG_CARD_HOVER') else "rgba(0, 123, 255, 0.1)"
        except Exception:
            bg_color_active = "rgba(0, 123, 255, 0.1)"

        st.markdown(f'''
<style>
/* 1. Outer Container & Crush horizontal gap */
div[class*="st-key-include_files_segmented_wrapper"] {{
    background-color: rgba(0, 0, 0, 0.25) !important;
    border: 1px solid rgba(255, 255, 255, 0.05) !important;
    border-radius: 12px !important;
    padding: 4px !important;
    margin-top: 5px !important;
}}
div[class*="st-key-include_files_segmented_wrapper"] [data-testid="stHorizontalBlock"] {{
    gap: 4px !important;
}}

/* 2. Stretch column wrappers for dynamic height */
div[class*="st-key-include_files_segmented_wrapper"] div[data-testid="column"] > div,
div[class*="st-key-include_files_segmented_wrapper"] div[data-testid="stButton"] {{
    height: 100% !important;
}}

/* 3. Base Button: Flex Column + Relative Position */
div[class*="st-key-btn_include_"] button {{
    background-color: transparent !important;
    border: 1px solid transparent !important;
    height: 100% !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-items: flex-start !important;
    position: relative !important;
    padding: 12px 12px 12px 48px !important;
    border-radius: 8px !important;
    color: #a0a0a0 !important;
    transition: all 0.2s ease-in-out !important;
}}

/* 4. Force strict left alignment on inner Streamlit wrappers */
div[class*="st-key-btn_include_"] button > div {{
    text-align: left !important;
    width: 100% !important;
    display: block !important;
    margin: 0 !important;
}}
div[class*="st-key-btn_include_"] button p {{
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    margin: 0 !important;
    line-height: 1.2 !important;
    color: inherit !important;
    text-align: left !important;
    width: 100% !important;
}}

/* 5. Independent Icon Layer (::before) - Defaults to Monochrome */
div[class*="st-key-btn_include_"] button::before {{
    content: "" !important;
    position: absolute !important;
    left: 12px !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
    width: 24px !important;
    height: 24px !important;
    background-size: contain !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    filter: grayscale(25%) opacity(50%) !important;
    transition: all 0.2s ease-in-out !important;
}}
div.st-key-btn_include_all button::before {{
    background-image: url('data:image/png;base64,{b64_icon_all}') !important;
}}
div.st-key-btn_include_study button::before {{
    background-image: url('data:image/png;base64,{b64_icon_study}') !important;
}}

/* 6. Descriptions (::after) */
div.st-key-btn_include_all button::after {{
    content: "Download everything!" !important;
    display: block !important;
    font-size: 0.75rem !important;
    color: #a0a0a0 !important;
    margin-top: 4px !important;
    font-weight: normal !important;
    line-height: 1.2 !important;
    text-align: left !important;
    white-space: normal !important;
    width: 100% !important;
}}
div.st-key-btn_include_study button::after {{
    content: "Only the essentials" !important;
    display: block !important;
    font-size: 0.75rem !important;
    color: #a0a0a0 !important;
    margin-top: 4px !important;
    font-weight: normal !important;
    line-height: 1.2 !important;
    text-align: left !important;
    white-space: normal !important;
    width: 100% !important;
}}
/* 6.5 Hover State (Inactive Buttons) */
div[class*="st-key-btn_include_"] button:hover {{
    background-color: rgba(255, 255, 255, 0.00) !important;
}}

/* Protect Active State from Hover Overrides */
div.st-key-btn_include_{active_include_key} button:hover {{
    background-color: {bg_color_active} !important;
}}
div.st-key-btn_include_{active_include_key} button:hover::before {{
    filter: grayscale(0%) opacity(100%) !important;
}}
/* 7. Active State Logic */
div.st-key-btn_include_{active_include_key} button {{
    background-color: rgba(56, 189, 248, 0.15) !important; /* Muted Canvas Blue */
    border: 1px solid rgba(56, 189, 248, 0.3) !important;
    box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important; /* Slight drop shadow for the pill */
    color: #ffffff !important;
}}
/* Protect Active Blue Pill from Grey Hover Override */
div.st-key-btn_include_{active_include_key} button:hover {{
    background-color: rgba(56, 189, 248, 0.15) !important;
    border: 1px solid rgba(56, 189, 248, 0.3) !important;
}}
div.st-key-btn_include_{active_include_key} button p {{
    color: #ffffff !important;
}}
div.st-key-btn_include_{active_include_key} button::before {{
    filter: grayscale(0%) opacity(100%) !important;
}}
</style>
''', unsafe_allow_html=True)

        step2_container = st.empty()
        with step2_container.container():
            # HOISTED CALLBACKS
            def _toggle_secondary_sub(target_key):
                st.session_state[target_key] = not st.session_state.get(target_key, False)
                active = sum(st.session_state.get(k, False) for k in _SECONDARY_CONTENT_KEYS)
                st.session_state['dl_secondary_master'] = (active == TOTAL_SECONDARY_SUBS)

            def _toggle_secondary_master():
                new_state = not st.session_state.get('dl_secondary_master', False)
                st.session_state['dl_secondary_master'] = new_state
                for k in _SECONDARY_CONTENT_KEYS:
                    st.session_state[k] = new_state

            def _set_isolate_secondary(is_subfolders: bool):
                """Sets the secondary content organization mode."""
                st.session_state['dl_isolate_secondary'] = is_subfolders

            def _get_sec_org_segmented_css():
                import base64
                import os

                def _get_b64(filepath):
                    if os.path.exists(filepath):
                        with open(filepath, "rb") as f:
                            return base64.b64encode(f.read()).decode()
                    return ""

                b64_inline = _get_b64("assets/icon_sec_inline.png")
                b64_sub = _get_b64("assets/icon_sec_subfolders.png")
                
                is_sub = st.session_state.get('dl_isolate_secondary', False)
                active_key = "subfolders" if is_sub else "inline"
                
                # Use current theme colors
                bg_active = theme.BG_CARD_HOVER if hasattr(theme, 'BG_CARD_HOVER') else "rgba(104, 212, 163, 0.15)"
                border_active = "#68d4a3"
                
                return f"""
                <style>
                div[class*="st-key-sec_org_segmented_wrapper"] {{
                    background-color: rgba(0, 0, 0, 0.25) !important;
                    border: 1px solid rgba(255, 255, 255, 0.05) !important;
                    border-radius: 12px !important;
                    padding: 4px !important;
                    margin-top: 5px !important;
                }}
                div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="stHorizontalBlock"] {{
                    gap: 4px !important;
                }}
                div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="column"] > div, 
                div[class*="st-key-sec_org_segmented_wrapper"] div[data-testid="stButton"], 
                div[class*="st-key-sec_org_segmented_wrapper"] button {{
                    height: 100% !important;
                }}
                div[class*="st-key-btn_sec_org_"] button {{
                    background-color: transparent !important;
                    border: 1px solid transparent !important;
                    display: flex !important;
                    flex-direction: column !important;
                    padding: 12px 12px 12px 48px !important;
                    border-radius: 8px !important;
                    color: #a0a0a0 !important;
                    transition: all 0.2s ease-in-out !important;
                    position: relative !important;
                }}
                /* Nuke Streamlit's center alignment for the segmented control */
                div[class*="st-key-btn_sec_org_"] button > div,
                div[class*="st-key-btn_sec_org_"] button div[data-testid="stMarkdownContainer"] {{
                    width: 100% !important;
                    display: flex !important;
                    justify-content: flex-start !important;
                    text-align: left !important;
                }}
                div[class*="st-key-btn_sec_org_"] button p {{
                    text-align: left !important;
                    width: 100% !important;
                    margin: 0 !important;
                    font-size: 0.95rem !important;
                    font-weight: 600 !important;
                    line-height: 1.2 !important;
                    color: inherit !important;
                }}
                div[class*="st-key-btn_sec_org_"] button::before {{
                    content: "" !important;
                    position: absolute !important;
                    left: 12px !important;
                    top: 50% !important;
                    transform: translateY(-50%) !important;
                    width: 24px !important;
                    height: 24px !important;
                    background-size: contain !important;
                    background-repeat: no-repeat !important;
                    background-position: center !important;
                    filter: grayscale(25%) opacity(50%) !important;
                    transition: all 0.2s ease-in-out !important;
                }}
                div.st-key-btn_sec_org_inline button::before {{ background-image: url('data:image/png;base64,{b64_inline}') !important; }}
                div.st-key-btn_sec_org_subfolders button::before {{ background-image: url('data:image/png;base64,{b64_sub}') !important; }}
                div.st-key-btn_sec_org_inline button::after {{ content: "Places content inline with module files using a type prefix." !important; }}
                div.st-key-btn_sec_org_subfolders button::after {{ content: "Creates dedicated folders (e.g. Assignments/, Quizzes/)." !important; }}
                div[class*="st-key-btn_sec_org_"] button::after {{
                    text-align: left !important;
                    width: 100% !important;
                    display: block !important;
                    font-size: 0.75rem !important;
                    color: #a0a0a0 !important;
                    margin-top: 2px !important;
                    font-weight: 400 !important;
                    white-space: normal !important;
                    line-height: 1.2 !important;
                }}
                div.st-key-btn_sec_org_{active_key} button {{
                    background-color: rgba(104, 212, 163, 0.15) !important; /* Muted Green */
                    border: 1px solid rgba(104, 212, 163, 0.3) !important;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important; /* Slight drop shadow for the pill */
                    color: #ffffff !important;
                }}
                /* Protect Active Green Pill from Grey Hover Override */
                div.st-key-btn_sec_org_{active_key} button:hover {{
                    background-color: rgba(104, 212, 163, 0.15) !important;
                    border: 1px solid rgba(104, 212, 163, 0.3) !important;
                }}
                div.st-key-btn_sec_org_{active_key} button p {{ color: #ffffff !important; }}
                div.st-key-btn_sec_org_{active_key} button::before {{ filter: grayscale(0%) opacity(100%) !important; }}
                </style>
                """

            notebook_sub_keys = [
                'convert_zip', 'convert_pptx', 'convert_word', 'convert_excel',
                'convert_html', 'convert_code', 'convert_urls', 'convert_video'
            ]
            TOTAL_NOTEBOOK_SUBS = len(notebook_sub_keys)

            def _toggle_conv_master():
                # If master is currently True (or all subs are True), turn everything off. Otherwise, turn all on.
                current_master = st.session_state.get('notebooklm_master', False)
                new_state = not current_master
                st.session_state['notebooklm_master'] = new_state
                for k in notebook_sub_keys:
                    st.session_state[k] = new_state

            def _toggle_conv_sub(key):
                # Flip the specific sub-toggle
                st.session_state[key] = not st.session_state.get(key, False)
                # Re-evaluate the master toggle based on the sum of active subs
                active_count = sum(1 for k in notebook_sub_keys if st.session_state.get(k, False))
                st.session_state['notebooklm_master'] = (active_count == TOTAL_NOTEBOOK_SUBS)

            # HOISTED CSS
            st.markdown("""
            <style>
            /* Tree-view styling for secondary content sub-checkboxes */
            .st-key-dl_assignments, .st-key-dl_syllabus, .st-key-dl_announcements,
            .st-key-dl_discussions, .st-key-dl_quizzes, .st-key-dl_rubrics,
            .st-key-dl_submissions {
                margin-left: 28px !important;
                padding-left: 15px !important;
                border-left: 2px solid """ + theme.BG_CARD_HOVER + """ !important;
                margin-top: -12px !important;
                padding-top: 4px !important;
                padding-bottom: 4px !important;
            }
            .st-key-dl_assignments { margin-top: 0px !important; padding-top: 8px !important; }
            .st-key-dl_submissions { margin-bottom: 10px !important; padding-bottom: 8px !important; }


            </style>
            """, unsafe_allow_html=True)

            col1, col2 = st.columns([3, 5], gap="large")

            # --- COLUMN 1: Organization & Include Files ---
            with col1:
                with st.container(border=True):
                    st.markdown("<h3 style='margin-top: 20px; margin-bottom: -10px;'>File Organization</h3>", unsafe_allow_html=True)
                    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
                    
                    def update_org_state(mode):
                        st.session_state['download_mode'] = 'modules' if mode == 'subfolders' else mode

                    btn_left, btn_right = st.columns(2)
                    b64_subfolders = get_base64_image("assets/icon_subfolders.png")
                    b64_flat = get_base64_image("assets/icon_flat.png")
                    
                    with btn_left:
                        st.button("Subfolders", key="btn_org_subfolders", use_container_width=True, on_click=update_org_state, args=("subfolders",))
                            
                    with btn_right:
                        st.button("Flat", key="btn_org_flat", use_container_width=True, on_click=update_org_state, args=("flat",))

                    active_mode = st.session_state.get('download_mode', 'modules')
                    active_btn_key = "subfolders" if active_mode == 'modules' else "flat"
                    
                    try:
                        border_color = theme.PRIMARY_BLUE if hasattr(theme, 'PRIMARY_BLUE') else theme.ACCENT_LINK
                        bg_color = theme.BG_CARD_HOVER if hasattr(theme, 'BG_CARD_HOVER') else "rgba(0, 123, 255, 0.1)"
                    except Exception:
                        border_color = "#007bff"
                        bg_color = "rgba(0, 123, 255, 0.1)"
                        
                    st.markdown(f'''
                    <style>
                    /* Base Card Styling for BOTH buttons */
                    div[class*="st-key-btn_org_"] button {{
                        height: 170px !important;
                        background-color: transparent !important;
                        background-repeat: no-repeat !important;
                        background-position: center 15px !important;
                        background-size: 64px !important;
                        padding-top: 85px !important;
                        border: 1px solid rgba(255, 255, 255, 0.1) !important;
                        border-radius: 8px !important;
                        display: flex !important;
                        flex-direction: column !important;
                        align-items: center !important;
                        justify-content: flex-start !important;
                        transition: all 0.2s ease-in-out !important;
                    }}

                    /* Primary Title Styling (The native button label) */
                    div[class*="st-key-btn_org_"] button p {{
                        font-size: 1.1rem !important;
                        font-weight: 600 !important;
                        margin: 0 !important;
                        line-height: 1.2 !important;
                        color: #ffffff !important;
                    }}

                    /* Hover State */
                    div[class*="st-key-btn_org_"] button:hover {{
                        border-color: rgba(255, 255, 255, 0.3) !important;
                        background-color: rgba(255, 255, 255, 0.02) !important;
                    }}

                    /* ----- SUBFOLDERS SPECIFIC ----- */
                    div.st-key-btn_org_subfolders button {{
                        background-image: url('data:image/png;base64,{b64_subfolders}') !important;
                    }}
                    div.st-key-btn_org_subfolders button::after {{
                        content: "Group files in subfolders, matching Canvas Modules" !important;
                        font-size: 0.85rem !important;
                        color: #a0a0a0 !important;
                        margin-top: 4px !important;
                        font-weight: 400 !important;
                    }}

                    /* ----- FLAT SPECIFIC ----- */
                    div.st-key-btn_org_flat button {{
                        background-image: url('data:image/png;base64,{b64_flat}') !important;
                    }}
                    div.st-key-btn_org_flat button::after {{
                        content: "Place all files together in the course folder" !important;
                        font-size: 0.85rem !important;
                        color: #a0a0a0 !important;
                        margin-top: 4px !important;
                        font-weight: 400 !important;
                    }}

                    /* Active State Highlight */
                    div.st-key-btn_org_{active_btn_key} button {{
                        border: 2px solid {border_color} !important;
                        background-color: rgba(56, 189, 248, 0.05) !important;
                    }}
                    /* Protect Active State from generic Hover Overrides */
                    div.st-key-btn_org_{active_btn_key} button:hover {{
                        border: 2px solid {border_color} !important;
                        background-color: rgba(56, 189, 248, 0.08) !important;
                    }}
                    </style>
                    ''', unsafe_allow_html=True)
                    
                    # 2. Include Files (Radio buttons replaced with Segmented Control)
                    st.markdown("<h3 style='margin-top: 15px; margin-bottom: -10px;'>Include Files:</h3>", unsafe_allow_html=True)
                    
                    def update_include_state(mode):
                        st.session_state['file_filter'] = mode

                    with st.container(key="include_files_segmented_wrapper"):
                        inc_left, inc_right = st.columns(2, gap="small")
                        with inc_left:
                            st.button("All Files (default)", key="btn_include_all", use_container_width=True, on_click=update_include_state, args=("all",))
                        with inc_right:
                            st.button("PDF & PPTX Only", key="btn_include_study", use_container_width=True, on_click=update_include_state, args=("study",))

            # --- COLUMN 2: Additional Course Content ---
            with col2:
                with st.container(border=True):
                    _sec_active = sum(1 for k in _SECONDARY_CONTENT_KEYS if st.session_state.get(k, False))
                    if _sec_active == 0:
                        dynamic_tag = "None selected"
                    elif _sec_active == TOTAL_SECONDARY_SUBS:
                        dynamic_tag = "Everything included in download"
                    else:
                        dynamic_tag = f"{_sec_active} Included in download"

                    header_html = f"""
                    <div style='display: flex; align-items: center; gap: 10px; margin-top: 20px; margin-bottom: 15px;'>
                        <h3 style='margin: 0;'>Additional Course Content</h3>
                        <span style='background-color: rgba(104, 212, 163, 0.15); color: #68d4a3; font-size: 0.8rem; padding: 2px 8px; border-radius: 4px; font-weight: 600;'>{dynamic_tag}</span>
                    </div>
                    """

                    # Helper to safely load icon
                    def safe_b64(name):
                        try:
                            res = get_base64_image(f"assets/{name}")
                            return res if res else ""
                        except:
                            return ""

                    # Button data
                    button_defs = [
                        ('dl_assignments', 'Assignments', 'Download assignment descriptions and any attached files.', 'icon_assignments.png'),
                        ('dl_syllabus', 'Syllabus', 'Download the course syllabus page as HTML.', 'icon_syllabus.png'),
                        ('dl_announcements', 'Announcements', 'Download course announcements and any attached files.', 'icon_announcements.png'),
                        ('dl_discussions', 'Discussions', 'Download discussion topic prompts as HTML.', 'icon_discussions.png'),
                        ('dl_quizzes', 'Quizzes', 'Download quiz questions and answers as structured HTML.', 'icon_quizzes.png'),
                        ('dl_rubrics', 'Rubrics', 'Download rubric criteria as Markdown tables.', 'icon_rubrics.png'),
                        ('dl_submissions', 'Submissions (metadata)', 'Download submission metadata (grades, timestamps). Content files are not included.', 'icon_submissions.png')
                    ]

                    # Generate CSS
                    css_blocks = []
                    css_blocks.append('''
                    div.st-key-secondary_cards_grid [data-testid="stHorizontalBlock"] {
                        gap: 12px !important;
                    }
                    /* Nuke Streamlit's center alignment */
                    div[class*="st-key-btn_dl_"] button > div,
                    div[class*="st-key-btn_dl_"] button div[data-testid="stMarkdownContainer"] {
                        width: 100% !important;
                        display: flex !important;
                        justify-content: flex-start !important;
                        text-align: left !important;
                    }
                    div[class*="st-key-btn_dl_"] button p {
                        text-align: left !important;
                        width: 100% !important;
                        margin: 0 !important;
                    }
                    div[class*="st-key-btn_dl_"] button::after {
                        text-align: left !important;
                        width: 100% !important;
                        display: block !important;
                    }
                    div[class*="st-key-btn_dl_"] button {
                        height: 72px !important;
                        min-height: 0px !important;
                        padding-top: 0px !important;
                        padding-bottom: 0px !important;
                        padding-right: 10px !important;
                        padding-left: 50px !important;
                        background-position: 15px center !important;
                        background-size: 24px !important;
                        background-repeat: no-repeat !important;
                        border-radius: 12px !important;
                        display: flex;
                        flex-direction: column;
                        justify-content: center;
                    }
                    div.st-key-btn_dl_secondary_master button {
                        height: 64px !important;
                        padding-top: 5px !important;
                        padding-bottom: 5px !important;
                    }
                    ''')

                    # Master CSS
                    m_active = st.session_state.get('dl_secondary_master', False)
                    m_bg = "rgba(255, 255, 255, 0.08)" if m_active else "rgba(255, 255, 255, 0.06)"
                    m_border = "rgba(255, 255, 255, 0.05)"
                    m_ledge = "#68d4a3" if m_active else "transparent"
                    b64_m = safe_b64('icon_select_all.png')
                    m_img_rule = f"background-image: url('data:image/png;base64,{b64_m}') !important;" if b64_m else ""
                    m_icon_filter = "grayscale(0%) opacity(100%)" if m_active else "grayscale(25%) opacity(50%)"
                    
                    css_blocks.append(f'''
                    div.st-key-btn_dl_secondary_master button {{
                        background-color: {m_bg} !important;
                        border: 1px solid {m_border} !important;
                        border-bottom: 4px solid {m_ledge} !important;
                        border-radius: 12px !important;
                        {m_img_rule}
                    }}
                    div.st-key-btn_dl_secondary_master button:hover {{
                        border-bottom: 4px solid {m_ledge} !important;
                    }}
                    div.st-key-btn_dl_secondary_master button::before {{ 
                        filter: {m_icon_filter} !important; 
                    }}
                    div.st-key-btn_dl_secondary_master button::after {{
                        content: "Include all supplementary materials in the download." !important;
                        font-size: 0.75rem !important; color: #a0a0a0; white-space: normal !important;
                        display: block !important; text-align: left !important; width: 100%; margin-top: 2px; line-height: 1.2 !important;
                    }}
                    ''')

                    # Child CSS
                    for key, title, desc, icon in button_defs:
                        is_active = st.session_state.get(key, False)
                        c_bg = "rgba(104, 212, 163, 0.15)" if is_active else "rgba(255, 255, 255, 0.02)"
                        c_border = "#68d4a3" if is_active else "rgba(255, 255, 255, 0.1)"
                        b64_c = safe_b64(icon)
                        c_img_rule = f"background-image: url('data:image/png;base64,{b64_c}') !important;" if b64_c else ""
                        
                        css_blocks.append(f'''
                        div.st-key-btn_{key} button {{
                            background-color: {c_bg} !important;
                            border: 1px solid {c_border} !important;
                            {c_img_rule}
                        }}
                        div.st-key-btn_{key} button::after {{
                            content: "{desc}" !important;
                            font-size: 0.75rem !important; color: #a0a0a0; white-space: normal !important;
                            display: block !important; text-align: left !important; width: 100%; margin-top: 2px; line-height: 1.2 !important;
                        }}
                        div.st-key-btn_{key} button:hover {{
                            border-color: #68d4a3 !important;
                        }}
                        ''')

                    final_html = f"""
                    {header_html}
                    <style>
                    {''.join(css_blocks)}
                    </style>
                    """
                    st.markdown(final_html, unsafe_allow_html=True)

                    st.markdown("<p style='font-size: 0.9rem; color: #a3a8b8; margin-bottom: 10px; margin-top: 5px;'>Select what to include in download:</p>", unsafe_allow_html=True)
                    st.button("Select All", key="btn_dl_secondary_master", on_click=_toggle_secondary_master, use_container_width=True)
                    
                    with st.container(key="secondary_cards_grid"):
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            for key, title, _, _ in button_defs[:3]:
                                st.button(title, key=f"btn_{key}", on_click=_toggle_secondary_sub, args=(key,), use_container_width=True)
                        with c2:
                            for key, title, _, _ in button_defs[3:5]:
                                st.button(title, key=f"btn_{key}", on_click=_toggle_secondary_sub, args=(key,), use_container_width=True)
                        with c3:
                            for key, title, _, _ in button_defs[5:]:
                                st.button(title, key=f"btn_{key}", on_click=_toggle_secondary_sub, args=(key,), use_container_width=True)

                    # --- Section 2: Conditional radio (only if ≥1 checkbox is active) ---
                    if _sec_active > 0:
                        # Zero-Div-Bloat: Label and CSS in single markdown call
                        st.markdown(f"""
                        <p style='font-size: 0.9rem; margin-bottom: 5px; color: #FAFAFA;'>Organize Additional Course Content by:</p>
                        {_get_sec_org_segmented_css()}
                        """, unsafe_allow_html=True)

                        with st.container(key="sec_org_segmented_wrapper"):
                            c1, c2 = st.columns(2, gap="small")
                            
                            with c1:
                                st.button(
                                    "In Course Folder/Modules (Default)", 
                                    key="btn_sec_org_inline", 
                                    on_click=_set_isolate_secondary, 
                                    args=(False,), 
                                    use_container_width=True
                                )
                            with c2:
                                st.button(
                                    "In Subfolders", 
                                    key="btn_sec_org_subfolders", 
                                    on_click=_set_isolate_secondary, 
                                    args=(True,), 
                                    use_container_width=True
                                )

            # Force a visual break between top and bottom rows
            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

            # --- BOTTOM ROW: Conversion Settings / NotebookLM ---
            col_bottom, _bottom_spacer = st.columns([6, 2], gap="medium")
            with col_bottom:
                with st.container(border=True):
                    # --- Conversion Button Data ---
                    conv_button_defs = [
                        ('convert_zip',   'Auto-Extract Archives',    'Extracts files from .zip and .tar.gz archives.',        'icon_conv_zip.png'),
                        ('convert_pptx',  'PowerPoint → PDF',         'Converts .pptx/.ppt to PDF via Microsoft Office.',      'icon_conv_pptx.png'),
                        ('convert_word',  'Word Docs → PDF',          'Converts legacy .doc, .rtf to PDF.',                    'icon_conv_word.png'),
                        ('convert_excel', 'Excel → PDF',              'Converts .xlsx, .xls workbooks to PDF.',                'icon_conv_excel.png'),
                        ('convert_html',  'HTML → Markdown',          'Converts Canvas Pages from HTML to Markdown.',          'icon_conv_html.png'),
                        ('convert_code',  'Code & Data → .txt',       'Appends .txt extension to programming files.',          'icon_conv_code.png'),
                        ('convert_urls',  'Compile Web Links',        'Aggregates .url/.webloc shortcuts into a list.',        'icon_conv_urls.png'),
                        ('convert_video', 'Video → Audio',            'Extracts .mp3 audio tracks from video files.',          'icon_conv_video.png'),
                    ]

                    # --- Dynamic Tag Counter ---
                    _conv_active = sum(1 for k in notebook_sub_keys if st.session_state.get(k, False))
                    if _conv_active == 0:
                        conv_tag = "None selected"
                    elif _conv_active == TOTAL_NOTEBOOK_SUBS:
                        conv_tag = "All enabled"
                    else:
                        conv_tag = f"{_conv_active} enabled"

                    # --- Generate CSS for each button ---
                    conv_css_blocks = []

                    # Base styles — zero-indentation to prevent Streamlit code-block conversion
                    conv_css_blocks.append(
'div.st-key-conversion_cards_grid [data-testid="stHorizontalBlock"] { gap: 12px !important; }\n'
'div[class*="st-key-btn_convert_"] button > div,\n'
'div[class*="st-key-btn_convert_"] button div[data-testid="stMarkdownContainer"] {\n'
'width: 100% !important; display: flex !important; justify-content: flex-start !important; text-align: left !important; }\n'
'div[class*="st-key-btn_convert_"] button p { text-align: left !important; width: 100% !important; margin: 0 !important; }\n'
'div[class*="st-key-btn_convert_"] button::after { text-align: left !important; width: 100% !important; display: block !important; }\n'
'div[class*="st-key-btn_convert_"] button {\n'
'height: 72px !important; min-height: 0px !important;\n'
'padding-top: 0px !important; padding-bottom: 0px !important;\n'
'padding-right: 10px !important; padding-left: 52px !important;\n'
'background-position: 15px center !important; background-size: 30px !important;\n'
'background-repeat: no-repeat !important; border-radius: 12px !important;\n'
'display: flex; flex-direction: column; justify-content: center; }\n'
'div.st-key-btn_convert_master button { height: 64px !important; padding-top: 5px !important; padding-bottom: 5px !important; padding-left: 50px !important; background-size: 24px !important; }\n'
                    )

                    # Master (Select All) CSS
                    m_active = st.session_state.get('notebooklm_master', False)
                    m_bg = "rgba(255, 255, 255, 0.08)" if m_active else "rgba(255, 255, 255, 0.06)"
                    m_border = "rgba(255, 255, 255, 0.05)"
                    m_ledge = "#f97316" if m_active else "transparent"
                    b64_conv_m = safe_b64('icon_conv_select_all.png')
                    m_conv_img_rule = f"background-image: url('data:image/png;base64,{b64_conv_m}') !important;" if b64_conv_m else ""
                    m_conv_icon_filter = "none" if m_active else "grayscale(100%) opacity(40%)"

                    conv_css_blocks.append(
f'div.st-key-btn_convert_master button {{ background-color: {m_bg} !important; border: 1px solid {m_border} !important; border-bottom: 4px solid {m_ledge} !important; border-radius: 12px !important; {m_conv_img_rule} }}\n'
f'div.st-key-btn_convert_master button:hover {{ border-bottom: 4px solid {m_ledge} !important; }}\n'
f'div.st-key-btn_convert_master button::before {{ filter: {m_conv_icon_filter} !important; }}\n'
f'div.st-key-btn_convert_master button::after {{ content: "Enable all conversions to optimize files for AI processing." !important; font-size: 0.75rem !important; color: #a0a0a0; white-space: normal !important; display: block !important; text-align: left !important; width: 100%; margin-top: 2px; line-height: 1.2 !important; }}\n'
                    )

                    # Child button CSS (per-toggle)
                    for conv_key, conv_title, conv_desc, conv_icon in conv_button_defs:
                        is_conv_active = st.session_state.get(conv_key, False)
                        c_bg = "rgba(249, 115, 22, 0.15)" if is_conv_active else "rgba(255, 255, 255, 0.02)"
                        c_border = "#f97316" if is_conv_active else "rgba(255, 255, 255, 0.1)"
                        c_icon_filter = "none" if is_conv_active else "grayscale(100%) opacity(40%)"
                        b64_conv_c = safe_b64(conv_icon)
                        c_conv_img_rule = f"background-image: url('data:image/png;base64,{b64_conv_c}') !important;" if b64_conv_c else ""

                        conv_css_blocks.append(
f'div.st-key-btn_{conv_key} button {{ background-color: {c_bg} !important; border: 1px solid {c_border} !important; {c_conv_img_rule} }}\n'
f'div.st-key-btn_{conv_key} button::before {{ filter: {c_icon_filter} !important; }}\n'
f'div.st-key-btn_{conv_key} button::after {{ content: "{conv_desc}" !important; font-size: 0.75rem !important; color: #a0a0a0; white-space: normal !important; display: block !important; text-align: left !important; width: 100%; margin-top: 2px; line-height: 1.2 !important; }}\n'
f'div.st-key-btn_{conv_key} button:hover {{ border-color: #f97316 !important; }}\n'
                        )

                    # --- Header HTML (separate injection) ---
                    conv_header_html = f"""<div style='display: flex; align-items: center; gap: 10px; margin-top: 20px; margin-bottom: 15px;'><h3 style='margin: 0;'>Conversion Settings</h3><span style='background-color: rgba(249, 115, 22, 0.15); color: #f97316; font-size: 0.8rem; padding: 2px 8px; border-radius: 4px; font-weight: 600;'>{conv_tag}</span></div>"""
                    st.markdown(conv_header_html, unsafe_allow_html=True)

                    # --- CSS injection (separate call, zero-indentation) ---
                    conv_css_html = "<style>\n" + "".join(conv_css_blocks) + "</style>"
                    st.markdown(conv_css_html, unsafe_allow_html=True)

                    st.markdown("<p style='font-size: 0.9rem; color: #a3a8b8; margin-bottom: 10px; margin-top: 5px;'>Enable conversions for AI:</p>", unsafe_allow_html=True)
                    st.button("Select All", key="btn_convert_master", on_click=_toggle_conv_master, use_container_width=True)

                    with st.container(key="conversion_cards_grid"):
                        cols = st.columns(4)
                        for idx, (conv_key, conv_title, _, _) in enumerate(conv_button_defs):
                            col = cols[idx % 4]
                            with col:
                                st.button(conv_title, key=f"btn_{conv_key}", on_click=_toggle_conv_sub, args=(conv_key,), use_container_width=True)

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
                        st.session_state['seen_error_sigs'] = set()  # Clear deduplication state for fresh download
                        
                        # Task 1: Save the State on Button Click (Streamlit Widget Cleanup Fix)
                        st.session_state['persistent_convert_zip'] = st.session_state.get('convert_zip', False)
                        st.session_state['persistent_convert_pptx'] = st.session_state.get('convert_pptx', False)
                        st.session_state['persistent_convert_html'] = st.session_state.get('convert_html', False)
                        st.session_state['persistent_convert_code'] = st.session_state.get('convert_code', False)
                        st.session_state['persistent_convert_urls'] = st.session_state.get('convert_urls', False)
                        st.session_state['persistent_convert_word'] = st.session_state.get('convert_word', False)
                        st.session_state['persistent_convert_video'] = st.session_state.get('convert_video', False)
                        st.session_state['persistent_convert_excel'] = st.session_state.get('convert_excel', False)
                        
                        # Task 1b: Save secondary content state on button click
                        for _sck in _SECONDARY_CONTENT_KEYS:
                            st.session_state[f'persistent_{_sck}'] = st.session_state.get(_sck, False)
                        st.session_state['persistent_dl_isolate_secondary'] = st.session_state.get('dl_isolate_secondary', True)

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
                
                def render_dashboard():
                    # Calculate current progress
                    current_mb = sum(st.session_state.get('course_mb_downloaded', {}).values())
                    current_files = st.session_state.get('downloaded_items', 0) + st.session_state.get('failed_items', 0)
                    
                    is_retry = st.session_state.get('download_status') == 'isolated_retry'
                    active_total = st.session_state.get('total_items', total_items)
                    active_current = st.session_state.get('retry_downloaded_items', current_files) if is_retry else st.session_state.get('downloaded_items', current_files)
                    active_current += st.session_state.get('retry_failed_items', 0) if is_retry else st.session_state.get('failed_items', 0)
                    active_total_mb = st.session_state.get('total_mb', total_mb)

                    if active_total > 0:
                        percent = int((active_current / active_total) * 100)
                        percent = min(100, percent) # Clamp to max 100
                        if active_current >= active_total:
                            percent = 100
                    else:
                        percent = 0

                    # Calculate Speed & ETA
                    elapsed = time.time() - start_time
                    speed_mb_s = (current_mb / elapsed) if elapsed > 0 else 0.0
                    remaining_mb = max(0, active_total_mb - current_mb) # prevent negative remaining mb
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
                            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{current_mb:.1f} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {active_total_mb:.1f} MB</span></span>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Speed</span>
                            <span style="color: #10B981; font-size: 1.2rem; font-weight: bold;">{speed_mb_s:.1f} <span style="font-size: 0.9rem;">MB/s</span></span>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Files</span>
                            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{active_current} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {active_total}</span></span>
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

                    if any(contract.values()) and not (st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled')):
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
                        # Track post-processing failures for the completion screen (M-7)
                        st.session_state['pp_failure_count'] = st.session_state.get('pp_failure_count', 0) + pp_ui.pp_failure_count
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
            
            def render_dashboard(current_course_name):
                # Calculate current progress
                current_files = st.session_state.get('retry_downloaded_items', 0) + st.session_state.get('retry_failed_items', 0)
                
                is_retry = st.session_state.get('download_status') == 'isolated_retry'
                active_total = st.session_state.get('total_items', 1)
                active_current = st.session_state.get('retry_downloaded_items', current_files) if is_retry else st.session_state.get('downloaded_items', current_files)
                active_current += st.session_state.get('retry_failed_items', 0) if is_retry else st.session_state.get('failed_items', 0)
                
                percent = int((active_current / max(1, active_total)) * 100)
                percent = min(100, percent)
                if active_current >= active_total:
                    percent = 100
                
                # Metrics Extraction for Parity
                bytes_down = st.session_state.get('retry_mb_tracker', {}).get('bytes_downloaded', 0)
                current_mb = bytes_down / (1024 * 1024)
                elapsed = time.time() - st.session_state.get('start_time', time.time())
                speed_mb_s = current_mb / elapsed if elapsed > 0 else 0

                header_placeholder.markdown(f'''
                <div style="margin-bottom: 0.5rem;">
                    <p style="margin: 0; font-size: 0.8rem; color: {theme.TEXT_SECONDARY}; text-transform: uppercase;">📦 Retrying Failed Items</p>
                    <h3 style="margin: 0; padding-top: 0.1rem; color: {theme.TEXT_PRIMARY};">{esc(current_course_name)}</h3>
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
                        <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{current_mb:.1f} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">MB</span></span>
                    </div>
                    <div style="display: flex; flex-direction: column; align-items: center;">
                        <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Speed</span>
                        <span style="color: #10B981; font-size: 1.2rem; font-weight: bold;">{speed_mb_s:.1f} <span style="font-size: 0.9rem;">MB/s</span></span>
                    </div>
                    <div style="display: flex; flex-direction: column; align-items: center;">
                        <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Files Processed</span>
                        <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{active_current} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {active_total}</span></span>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
                
                log_content = "<br>".join(reversed(list(log_deque)))
                log_placeholder.markdown(f'''
                <div style="background-color: {theme.BG_TERMINAL}; color: {theme.TERMINAL_TEXT}; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 0.85rem; height: 140px; border: 1px solid {theme.BORDER_TERMINAL}; line-height: 1.6; overflow-y: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">
                    {log_content}
                </div>
                ''', unsafe_allow_html=True)
            
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
            
            # --- NEW Post-Processing Pipeline for Retry ---
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
                        _convert_keys = ['convert_zip', 'convert_pptx', 'convert_word', 'convert_excel',
                                         'convert_html', 'convert_code', 'convert_urls', 'convert_video']
                        contract = {k: st.session_state.get(f'persistent_{k}', False) for k in _convert_keys}
    
                        if any(contract.values()):
                            # --- FIX: Post-Processing Overkill Pipeline Swaps ---
                            success_names = st.session_state.get('retry_isolated_details', {}).get(course.name, [])
                            if not success_names:
                                continue  # Skip post-processing entirely if nothing actually succeeded during this retry
                                
                            from pathlib import Path
                            success_paths = []
                            for n in success_names:
                                if Path(n).is_absolute():
                                    success_paths.append(str(Path(n).resolve()))
                                else:
                                    success_paths.append(str((course_folder / cm._sanitize_filename(n)).resolve()))
                            
                            st.session_state['is_post_processing'] = True
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
                                explicit_files=success_paths
                            )
                            st.session_state['pp_failure_count'] = st.session_state.get('pp_failure_count', 0) + pp_ui.pp_failure_count
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
