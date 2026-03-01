import streamlit as st
import tkinter as tk
from tkinter import filedialog
from canvas_logic import CanvasManager, DownloadError
import os
from pathlib import Path
import time
import re
from translations import get_text
from sync_ui import render_sync_step1, render_sync_step4
from ui_helpers import friendly_course_name, parse_cbs_metadata, render_download_wizard

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
    [class*="st-key-cancel_pair"] button:hover,
    .st-key-cancel_download_btn button:hover,
    .st-key-sync_cancel_btn button:hover {
        border-color: #ff4b4b !important;
        color: #ff4b4b !important;
        background-color: rgba(255, 75, 75, 0.1) !important;
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
if 'user_name' not in st.session_state:
    st.session_state['user_name'] = ""
if 'language' not in st.session_state:
    st.session_state['language'] = 'en'  # Default to English
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
    except:
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
    except:
        pass
    folder_path = filedialog.askdirectory(master=root)
    root.destroy()
    if folder_path:
        st.session_state['pending_sync_folder'] = folder_path

def check_cancellation():
    return st.session_state.get('cancel_requested', False)

@st.cache_data
def fetch_courses(token, url, fav_only, language='en'):
    mgr = CanvasManager(token, url, language)
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
    # Language Switcher at top of sidebar
    lang = st.session_state['language']
    
    # Language selector
    col_lang1, col_lang2 = st.columns([1, 3])
    with col_lang1:
        st.write("🌐")
    with col_lang2:
        language_options = [get_text('english', lang), get_text('danish', lang)]
        current_lang_index = 0 if st.session_state['language'] == 'en' else 1
        selected_lang = st.selectbox(
            get_text('language', lang),
            language_options,
            index=current_lang_index,
            key="language_selector",
            label_visibility="collapsed"
        )
    
    # Update language if changed
    new_lang = 'en' if selected_lang == language_options[0] else 'da'
    if new_lang != st.session_state['language']:
        st.session_state['language'] = new_lang
        st.rerun()

    st.markdown("---")
    st.title(get_text('sidebar_title', lang))
    
    # Auth Logic
    import sys
    import json
    
    def get_config_path():
        if getattr(sys, 'frozen', False):
            # Running as compiled exe
            application_path = os.path.dirname(sys.executable)
        else:
            # Running as script
            application_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(application_path, 'canvas_downloader_settings.json')

    CONFIG_FILE = get_config_path()
    
    # Auto-load token (only once)
    if 'token_loaded' not in st.session_state:
        st.session_state['token_loaded'] = True
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding='utf-8') as f:
                    config = json.load(f)
                    st.session_state['api_url'] = config.get('api_url', '')
                    st.session_state['api_token'] = config.get('api_token', '')
                    
                    if 'concurrent_downloads' in config:
                        st.session_state['concurrent_downloads'] = config.get('concurrent_downloads', 5)
                        
                    if st.session_state['api_token']:
                        # Use default language 'en' here as session state might not be fully ready
                        cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'], st.session_state.get('language', 'en'))
                        valid, msg = cm.validate_token()
                        if valid:
                            st.session_state['is_authenticated'] = True
                            st.session_state['user_name'] = msg
            except Exception:
                pass

    if not st.session_state['is_authenticated']:
        st.subheader(get_text('auth_header', lang))
        
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
                get_text('enter_url', lang),
                key="url_input",
                placeholder="https://your-school.instructure.com"
            )

            # API Token Input (same logic - no value= parameter)
            token_input = st.text_input(
                get_text('enter_token', lang), 
                type="password", 
                key="token_input"
            )
            
            # Log In Button
            submitted = st.form_submit_button(get_text('validate_save', lang), type="primary", use_container_width=True)

        if submitted:
            input_url = st.session_state.url_input.strip()
            input_token = st.session_state.token_input.strip()
            
            # Sync back to session state to prevent input glitching
            st.session_state['api_url'] = input_url
            st.session_state['api_token'] = input_token
            
            manager = CanvasManager(input_token, input_url, lang)
            is_valid, message = manager.validate_token()
            
            if is_valid:
                st.session_state['api_token'] = input_token
                st.session_state['api_url'] = manager.api_url # Use potential auto-corrected URL
                st.session_state['is_authenticated'] = True
                st.session_state['user_name'] = message.split(": ")[1] if ": " in message else message
                
                # Save to config (JSON)
                try:
                    config_data = {
                        'api_url': st.session_state['api_url'],
                        'api_token': st.session_state['api_token']
                    }
                    if 'concurrent_downloads' in st.session_state:
                        config_data['concurrent_downloads'] = st.session_state['concurrent_downloads']
                        
                    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f)
                except Exception as e:
                    st.error(f"Could not save config: {e}")
                    
                st.rerun()
            else:
                st.error(message)
        
        # Help Section
        with st.expander(get_text('how_to_token', lang)):
            st.markdown(get_text('token_instructions', lang))
        
        with st.expander(get_text('how_to_url', lang)):
            # Use code block to prevent overflow and keep fixed width
            # Splitting instructions to ensure better rendering based on user feedback
            st.markdown(get_text('url_instructions', lang))
    else:
        st.success(st.session_state['user_name'])
        
        # Navigation section (under logged in status)
        st.markdown("---")
        mode = st.session_state.get('current_mode', 'download')
        
        # Download mode button
        download_label = "📥 " + get_text('nav_download', lang)
        if mode == 'download':
            # Active state - light grey background, outlined style
            st.markdown(f"""
            <div style="background-color: #3a3a3a; border: 1px solid #555; border-radius: 6px; 
                        padding: 8px 16px; text-align: center; margin-bottom: 8px;">
                <span style="color: #fff; font-weight: 500;">{download_label}</span>
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
        sync_label = "🔄 " + get_text('nav_sync', lang)
        if mode == 'sync':
            # Active state - light grey background, outlined style
            st.markdown(f"""
            <div style="background-color: #3a3a3a; border: 1px solid #555; border-radius: 6px; 
                        padding: 8px 16px; text-align: center; margin-bottom: 8px;">
                <span style="color: #fff; font-weight: 500;">{sync_label}</span>
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
        
        @st.dialog("⚙️ Application Settings", width="large")
        def _global_settings_dialog():
            val = st.session_state.get('concurrent_downloads', 5)
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
                col_dl, col_sync = st.columns(2, gap="large")
                
                with col_dl:
                    st.markdown("### 📥 Download Settings")
                    st.markdown("---")
                    st.markdown("#### Max Concurrent Downloads")
                    st.markdown(
                        "<div style='font-size: 0.9em; color: #aaa; margin-bottom: 15px;'>"
                        "Controls how many files are downloaded simultaneously. <br><br>"
                        "⚠️ <b>Warning:</b> Canvas has strict rate limits. Increasing this too high may cause "
                        "the server to temporarily block your connection, resulting in failed downloads. "
                        "Only increase if you have a very stable, high-speed connection."
                        "</div>",
                        unsafe_allow_html=True
                    )
                    
                    if 'concurrent_downloads' not in st.session_state:
                        st.session_state['concurrent_downloads'] = 5
                        
                    val = st.slider(
                        "Simultaneous Files",
                        min_value=2,
                        max_value=20,
                        value=st.session_state['concurrent_downloads'],
                        step=1,
                        key="slider_concurrent_dl"
                    )
                
                with col_sync:
                    st.markdown("### 🔄 Sync Settings")
                    st.markdown("---")
                    st.markdown(
                        "<div style='font-size: 0.9em; color: #aaa; margin-bottom: 15px;'>"
                        "<i>Future sync optimizations and configuration options will appear here.</i>"
                        "</div>",
                        unsafe_allow_html=True
                    )

            st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)
            
            c_save, c_cancel = st.columns([1, 1])
            with c_save:
                if st.button("Save Settings", type="primary", use_container_width=True):
                    st.session_state['concurrent_downloads'] = val
                    
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
                    config_data['api_token'] = st.session_state.get('api_token', '')
                    config_data['concurrent_downloads'] = val
                    
                    try:
                        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                            json.dump(config_data, f)
                    except Exception as e:
                        pass
                        
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
        if st.button(get_text('logout_edit', lang), use_container_width=True):
            st.session_state['is_authenticated'] = False
            st.session_state['api_token'] = ""
            st.session_state['step'] = 1
            st.session_state['current_mode'] = 'download'
            # Clear the course cache to prevent showing old user's courses
            fetch_courses.clear()
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            st.rerun()

# --- Main Content ---
lang = st.session_state['language']
st.title(get_text('app_title', lang))

if not st.session_state['is_authenticated']:
    st.info(get_text('please_authenticate', lang))
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
            render_sync_step1(lang, fetch_courses, _main_content)
        
            # ========== DOWNLOAD MODE - STEP 1 ==========
        else:
            render_download_wizard(st, 1, lang)
            st.markdown(f'<div class="step-header">{get_text("step1_header", lang)}</div>', unsafe_allow_html=True)
            
            filter_mode = st.radio(
                get_text('show_label', lang),
                [get_text('show_favorites', lang), get_text('show_all', lang)],
                horizontal=True
            )
            favorites_only = (filter_mode == get_text('show_favorites', lang))
            
            courses = fetch_courses(st.session_state['api_token'], st.session_state['api_url'], favorites_only, lang)
            
            if not courses:
                st.warning(get_text('no_courses', lang))
            else:
                # --- CBS Filters Feature ---
                
                # Filter Toggle
                show_filters = st.toggle(get_text('enable_cbs_filters', lang, default="Enable CBS Filters"))
                
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
                        st.markdown(f"**{get_text('filter_criteria', lang, default='Filter Criteria')}**")
                        col_f1, col_f2, col_f3 = st.columns(3)
                        
                        with col_f1:
                            sel_types = st.multiselect(
                                get_text('filter_type', lang, default="Class Type"),
                                options=sorted(list(all_types)),
                                format_func=lambda x: get_text(f"type_{x.lower()}", lang, default=x)
                            )
                        with col_f2:
                            sel_sem = st.multiselect(
                                get_text('filter_semester', lang, default="Semester"),
                                options=sorted(list(all_semesters)),
                                format_func=lambda x: get_text(f"sem_{x.lower()}", lang, default=x)
                            )
                        with col_f3:
                            sel_years = st.multiselect(
                                get_text('filter_year', lang, default="Year"),
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
                            st.info(get_text('no_courses_match_filters', lang, default="No courses match the selected filters."))

                # "Select All" buttons - operate on FILTERED list
                col_sa1, col_sa2, _ = st.columns([1.3, 1.3, 10], gap="small")
                select_all_clicked = col_sa1.button(get_text('select_all', lang), key="btn_select_all", use_container_width=True)
                clear_sel_clicked = col_sa2.button(get_text('clear_selection', lang), key="btn_clear_sel", use_container_width=True)
                
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
                    full_name_str = f"{course.name} ({course.course_code})" if hasattr(course, 'course_code') else course.name
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
                            f'<span style="color:#888; font-size:0.9em;">({full_name_str})</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                    if checked:
                        new_selected_ids.append(course.id)
                
                st.session_state['selected_course_ids'] = new_selected_ids

                st.markdown("---")
                if st.button(get_text('continue_btn', lang), type="primary"):
                    if not st.session_state['selected_course_ids']:
                        error_container.error(get_text('select_one_course', lang))
                    else:
                        st.session_state['step'] = 2
                        st.rerun()

    # STEP 2: DOWNLOAD SETTINGS
    elif st.session_state['step'] == 2:
        render_download_wizard(st, 2, lang)
        st.markdown(f'<div class="step-header">{get_text("step2_header", lang)}</div>', unsafe_allow_html=True)
        
        step2_container = st.empty()
        with step2_container.container():
            st.subheader(get_text('download_structure', lang))
            mode_options = [
                get_text('with_subfolders', lang), 
                # get_text('mode_files', lang), # Removed per user request
                get_text('flat_structure', lang)
            ]
            
            # Determine current index
            current_mode_idx = 0
            # If mode is 'files' (legacy), default back to 0 (modules)
            if st.session_state['download_mode'] == 'flat':
                current_mode_idx = 1
                
            mode_choice = st.radio(
                get_text('structure_question', lang),
                mode_options,
                index=current_mode_idx
            )
            
            if mode_choice == get_text('with_subfolders', lang):
                st.session_state['download_mode'] = 'modules'
            # elif mode_choice == get_text('mode_files', lang):
            #     st.session_state['download_mode'] = 'files'
            else:
                st.session_state['download_mode'] = 'flat'
            
            st.subheader(get_text('file_filter_label', lang))
            filter_choice = st.radio(
                get_text('file_filter_label', lang), # Hidden label via label_visibility if needed, but subheader is fine
                [get_text('filter_all', lang), get_text('filter_study', lang)],
                index=0 if st.session_state['file_filter'] == 'all' else 1,
                label_visibility="collapsed"
            )
            st.session_state['file_filter'] = 'all' if filter_choice == get_text('filter_all', lang) else 'study'
            
            st.subheader(get_text('destination', lang))
            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button(get_text('select_folder', lang)):
                    select_folder()
            with col2:
                st.text_input(get_text('path_label', lang), value=st.session_state['download_path'], disabled=True)
                
            st.markdown("---")
            
            # Debug Option (Troubleshooting)
            st.checkbox("Enable Troubleshooting Mode (Debug Log)", key="debug_mode_checkbox")
            st.session_state['debug_mode'] = st.session_state.get('debug_mode_checkbox', False)
            
            st.markdown("---")
            
            # --- NotebookLM Compatible Download ---
            def _master_toggle_changed():
                st.session_state['convert_pptx'] = st.session_state['notebooklm_master']
            
            def _sub_toggle_changed():
                if not st.session_state['convert_pptx']:
                    st.session_state['notebooklm_master'] = False
            
            st.checkbox(
                "🤖 NotebookLM Compatible Download",
                key="notebooklm_master",
                on_change=_master_toggle_changed,
                help="Automatically converts downloaded files to formats compatible with Google NotebookLM."
            )
            
            with st.container():
                st.markdown("<div style='margin-left: 25px; margin-top: -10px;'>", unsafe_allow_html=True)
                st.checkbox(
                    "📊 Convert PowerPoints to PDF",
                    key="convert_pptx",
                    on_change=_sub_toggle_changed,
                    help="Converts .pptx/.ppt files to PDF after download using Microsoft Office. Requires PowerPoint installed."
                )
                st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("---")

            col_conf, col_back, _ = st.columns([1.2, 1, 5])
            with col_conf:
                # Button label changes based on mode
                button_label = get_text('sync_selected', lang) if st.session_state['current_mode'] == 'sync' else get_text('confirm_download', lang)
                if st.button(button_label, type="primary", use_container_width=True):
                    try:
                        # Initialize download state
                        all_courses = fetch_courses(st.session_state['api_token'], st.session_state['api_url'], False, lang)
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
                        st.session_state['persistent_convert_pptx'] = st.session_state.get('convert_pptx', False)
                        
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
                if st.button(get_text('back_btn', lang), use_container_width=True):
                    st.session_state['step'] = 1
                    st.rerun()


    elif st.session_state['step'] == 3:
        wiz_step = 4 if st.session_state.get('download_status') == 'done' else 3
        render_download_wizard(st, wiz_step, lang)
        
        st.markdown(f'<div class="step-header">{get_text("step3_header", lang)}</div>', unsafe_allow_html=True)
        
        # Safety check: ensure download state exists
        if 'courses_to_download' not in st.session_state or 'current_course_index' not in st.session_state:
            st.error(get_text('download_state_error', lang))
            if st.button(get_text('go_back_settings', lang)):
                st.session_state['step'] = 2
                st.rerun()
            st.stop()
        
        total = len(st.session_state['courses_to_download'])
        current_idx = st.session_state['current_course_index']
        
        # UI elements in correct order
        if st.session_state['download_status'] == 'running':
            import time
            import collections
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
            if cancel_placeholder.button(get_text('cancel_download', lang), type="secondary", key="cancel_download_btn"):
                cancel_placeholder.empty() # Clear immediately
                st.session_state['cancel_requested'] = True
                st.session_state['download_status'] = 'cancelled'
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
            if cancel_placeholder.button(get_text('cancel_download', lang), type="secondary", key="cancel_download_btn"):
                cancel_placeholder.empty() # Clear immediately
                st.session_state['cancel_requested'] = True
                st.session_state['download_status'] = 'cancelled'
                st.rerun()
            
            cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'], lang)
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
                    <div style="background-color: #1A1D27; padding: 20px; border-radius: 8px; border: 1px solid #2D3248; margin-bottom: 20px;">
                        <h4 style="color: #FFFFFF; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                        <p style="color: #8A91A6; font-size: 0.9rem;">Course {current_course_num} of {total_courses}: <b>{course.name}</b></p>
                        <p style="color: #4DA8DA; font-size: 0.8rem; margin-bottom: 5px;">{mod_status_text}</p>
                        <div style="background-color: #2D3248; border-radius: 4px; width: 100%; height: 8px; overflow: hidden;">
                            <div style="background-color: #4DA8DA; width: {mod_percent}%; height: 100%; transition: width 0.1s ease;"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Also keep the cancel button alive
                    if cancel_placeholder.button(get_text('cancel_download', lang), type="secondary", key=f"cancel_scan_{idx}_{current_mod}"):
                        st.session_state['cancel_requested'] = True
                        st.session_state['download_status'] = 'cancelled'
                        st.rerun()

                # Render initial modern loading UI
                analysis_ui_placeholder.markdown(f"""
                <div style="background-color: #1A1D27; padding: 20px; border-radius: 8px; border: 1px solid #2D3248; margin-bottom: 20px;">
                    <h4 style="color: #FFFFFF; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                    <p style="color: #8A91A6; font-size: 0.9rem;">Course {current_course_num} of {total_courses}: <b>{course.name}</b></p>
                    <div style="background-color: #2D3248; border-radius: 4px; width: 100%; height: 8px; margin-top: 10px; overflow: hidden;">
                        <div style="background-color: #4DA8DA; width: 0%; height: 100%; transition: width 0.3s ease;"></div>
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
            
            import time
            st.session_state['start_time'] = time.time() # Reset timer immediately before running loop
            
            st.rerun()

        elif st.session_state['download_status'] == 'running':
            if st.session_state['cancel_requested']:
                st.session_state['download_status'] = 'cancelled'
                st.warning(get_text('download_cancelled', lang))
            elif current_idx < total:
                import time
                import collections
                
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
                        <p style="margin: 0; font-size: 0.8rem; color: #8A91A6; text-transform: uppercase;">📦 Downloading Courses</p>
                        <h3 style="margin: 0; padding-top: 0.1rem; color: #FFFFFF;">{course.name}</h3>
                    </div>
                    ''', unsafe_allow_html=True)

                    progress_placeholder.markdown(f'''
                    <div style="background-color: #2D3248; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
                        <div style="background-color: #4DA8DA; width: {percent}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
                        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold;">
                            {percent}%
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
                    
                    metrics_placeholder.markdown(f'''
                    <div style="display: flex; justify-content: center; gap: 4rem; background-color: #1A1D27; padding: 15px 25px; border-radius: 8px; border: 1px solid #2D3248; margin-top: 5px; margin-bottom: 15px;">
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Downloaded</span>
                            <span style="color: #FFFFFF; font-size: 1.2rem; font-weight: bold;">{current_mb:.1f} <span style="font-size: 0.9rem; color: #4DA8DA;">/ {total_mb:.1f} MB</span></span>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Speed</span>
                            <span style="color: #10B981; font-size: 1.2rem; font-weight: bold;">{speed_mb_s:.1f} <span style="font-size: 0.9rem;">MB/s</span></span>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Files</span>
                            <span style="color: #FFFFFF; font-size: 1.2rem; font-weight: bold;">{current_files} <span style="font-size: 0.9rem; color: #4DA8DA;">/ {total_items}</span></span>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Time Remaining</span>
                            <span style="color: #F59E0B; font-size: 1.2rem; font-weight: bold;">{eta_string}</span>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
                    
                    log_content = "<br>".join(reversed(list(log_deque)))
                    log_placeholder.markdown(f'''
                    <div style="background-color: #0D1117; color: #A5D6FF; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 0.85rem; height: 140px; border: 1px solid #30363D; line-height: 1.6; overflow-y: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">
                        {log_content}
                    </div>
                    ''', unsafe_allow_html=True)
                
                # Render initial state
                render_dashboard()
                
                def update_ui(msg, progress_type='log', **kwargs):
                    """Update UI with progress information."""
                    if progress_type in ('download', 'page', 'link'):
                        st.session_state['downloaded_items'] += 1
                        if msg:
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
                            
                            error_text = f"[{course.name}] " + (error_obj.message if hasattr(error_obj, 'message') else str(msg))
                            log_deque.append(f"<span style='color: #FF7B72;'>[❌] Failed: {error_text}</span>")
                            
                        render_dashboard()

                    elif progress_type == 'mb_progress':
                        mb_down_course = kwargs.get('mb_downloaded', 0)
                        if 'course_mb_downloaded' not in st.session_state:
                             st.session_state['course_mb_downloaded'] = {}
                        st.session_state['course_mb_downloaded'][course.id] = mb_down_course
                        render_dashboard()
                    
                    elif msg and progress_type == 'log':
                        new_line = f"[{course.name}] {msg}"
                        log_deque.append(f"<span style='color: #8A91A6;'>[ℹ️] {new_line}</span>")
                        render_dashboard()
                

                import asyncio
                cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'], lang)
                asyncio.run(cm.download_course_async(
                    course,
                    st.session_state['download_mode'],
                    st.session_state['download_path'],
                    progress_callback=update_ui,
                    check_cancellation=check_cancellation,
                    file_filter=st.session_state['file_filter'],
                    debug_mode=st.session_state.get('debug_mode', False)
                ))
                
                # --- Post-Download: PPTX → PDF Conversion ---
                if st.session_state.get('persistent_convert_pptx', False):
                    from pdf_converter import convert_pptx_to_pdf
                    from sync_manager import SyncManager
                    
                    course_name = cm._sanitize_filename(course.name)
                    course_folder = Path(st.session_state['download_path']) / course_name
                    
                    # Gather all .pptx/.ppt files in the course folder
                    pptx_files = []
                    if course_folder.exists():
                        for f in course_folder.rglob('*'):
                            if f.suffix.lower() in ('.pptx', '.ppt') and f.is_file():
                                pptx_files.append(f)
                    
                    if pptx_files:
                        total_pptx = len(pptx_files)
                        print(f"[Post-Download] PPTX Conversion toggle is ON. Found {total_pptx} files.")
                        
                        # Custom render function to hijack the main UI placeholders
                        def render_conversion_dashboard(current_idx):
                            percent = int((current_idx / total_pptx) * 100) if total_pptx > 0 else 100
                            percent = min(100, percent)
                            
                            header_placeholder.markdown(f'''
                            <div style="margin-bottom: 0.5rem;">
                                <p style="margin: 0; font-size: 0.8rem; color: #8A91A6; text-transform: uppercase;">🪄 Post-Processing</p>
                                <h3 style="margin: 0; padding-top: 0.1rem; color: #FFFFFF;">Converting PowerPoint Files for {course.name}</h3>
                            </div>
                            ''', unsafe_allow_html=True)

                            progress_placeholder.markdown(f'''
                            <div style="background-color: #2D3248; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
                                <div style="background-color: #A5B4FC; width: {percent}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
                                <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold; text-shadow: 1px 1px 2px rgba(0,0,0,0.5);">
                                    {percent}%
                                </div>
                            </div>
                            ''', unsafe_allow_html=True)
                            
                            metrics_placeholder.markdown(f'''
                            <div style="display: flex; justify-content: center; gap: 4rem; background-color: #1A1D27; padding: 15px 25px; border-radius: 8px; border: 1px solid #2D3248; margin-top: 5px; margin-bottom: 15px;">
                                <div style="display: flex; flex-direction: column; align-items: center;">
                                    <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Converted</span>
                                    <span style="color: #FFFFFF; font-size: 1.2rem; font-weight: bold;">{current_idx} <span style="font-size: 0.9rem; color: #A5B4FC;">/ {total_pptx}</span></span>
                                </div>
                                <div style="display: flex; flex-direction: column; align-items: center;">
                                    <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Status</span>
                                    <span style="color: #A5B4FC; font-size: 1.2rem; font-weight: bold;">Processing PDF(s)</span>
                                </div>
                            </div>
                            ''', unsafe_allow_html=True)
                            
                            # Also re-render log
                            log_content = "<br>".join(reversed(list(log_deque)))
                            log_placeholder.markdown(f'''
                            <div style="background-color: #0D1117; color: #A5D6FF; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 0.85rem; height: 140px; border: 1px solid #30363D; line-height: 1.6; overflow-y: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">
                                {log_content}
                            </div>
                            ''', unsafe_allow_html=True)
                            
                        # 1. Start with 0 progress
                        render_conversion_dashboard(0)
                        
                        log_deque.append(f"<span style='color: #8A91A6;'>[ 🪄 ] Post-Processing: Converting {total_pptx} PowerPoint files to PDF for NotebookLM...</span>")
                        render_conversion_dashboard(0)
                        
                        import time
                        time.sleep(0.2)
                        
                        sm = SyncManager(course_folder, course.id, course.name, lang)
                        
                        for i, pptx_file in enumerate(pptx_files, 1):
                            pdf_path = convert_pptx_to_pdf(
                                pptx_file,
                                error_log_path=Path(st.session_state['download_path'])
                            )
                            
                            if pdf_path:
                                manifest = sm.load_manifest()
                                for file_id, info in manifest.get('files', {}).items():
                                    local_p = info.get('local_path', '')
                                    try:
                                        original_rel = pptx_file.relative_to(course_folder)
                                        if str(original_rel).replace('\\', '/') == local_p:
                                            new_rel = pdf_path.relative_to(course_folder)
                                            sm.update_file_to_pdf(int(file_id), str(new_rel).replace('\\', '/'))
                                            break
                                    except (ValueError, KeyError):
                                        pass
                                
                                log_deque.append(f"<span style='color: #4ade80;'>[ ✅ ] Converted: {pdf_path.name}</span>")
                            else:
                                log_deque.append(f"<span style='color: #f87171;'>[ ❌ ] Skipped: {pptx_file.name} (Conversion failed)</span>")
                                
                            # 2. Update progress mid-loop
                            render_conversion_dashboard(i)
                        
                        log_deque.append(f"<span style='color: #8A91A6;'>[ ✨ ] PDF conversion complete!</span>")
                        # 3. Final 100% render
                        render_conversion_dashboard(total_pptx)
                # --- End Post-Download Conversion ---
                
                # Move to next course
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
                        print(f"Failed to write session log: {e}")
                # -------------------------------------------------------------------
        
        elif st.session_state['download_status'] == 'done':
            st.success(get_text('download_complete', lang))
            # Show download location (no background color)
            st.markdown(f"**{get_text('download_location', lang, path=st.session_state['download_path'])}**")
            # Show final progress bar at 100%
            progress_container.markdown(f"""
                <div style="position: relative; height: 35px; background-color: #f0f2f6; border-radius: 5px; overflow: hidden;">
                    <div style="width: 100%; height: 100%; background-color: #1f77b4;"></div>
                    <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: #333;">{get_text('complete_text', lang)}</div>
                </div>
            """, unsafe_allow_html=True)
            status_text.text(get_text('downloaded_courses', lang, total=total))
            
            # Check for download errors (In-Memory first, fallback to disk)
            error_messages = st.session_state.get('download_errors_list', [])
            
            # Fallback (optional): If empty, check disk (legacy/redundant if list works)
            if not error_messages:
                from pathlib import Path
                download_path = Path(st.session_state['download_path'])
                
                # Collect errors from all course folders
                for course in st.session_state['courses_to_download']:
                    cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'], lang)
                    course_name = cm._sanitize_filename(course.name)
                    error_file = download_path / course_name / "download_errors.txt"
                    if error_file.exists():
                        try:
                            with open(error_file, 'r', encoding='utf-8') as f:
                                errors = f.read().strip()
                                if errors:
                                    error_messages.extend(errors.split('\n'))
                        except:
                            pass
            
            # Display error summary if there are errors
            if error_messages:
                st.warning(get_text('errors_occurred', lang, count=len(error_messages)))
                
                with st.expander(get_text('view_error_details', lang), expanded=True):
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
                    
                    st.caption(get_text('full_error_details', lang))

                # Retry Button
                st.markdown("<div style='margin-top: -15px; margin-bottom: 25px;'></div>", unsafe_allow_html=True)
                retry_label = "Retry Failed Items" if lang == 'en' else "Prøv fejlslagne elementer igen"
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
            st.warning(get_text('download_was_cancelled', lang))
            # Show partial progress
            progress_container.progress(current_idx / total if total > 0 else 0)
            status_text.text(get_text('cancelled_after', lang, current=current_idx, total=total))
        
        # Start Over / Go back button (show when done or cancelled)
        if st.session_state['download_status'] in ['done', 'cancelled']:
            # Use "Go back" for cancelled, "Go to front page" for done
            button_text = get_text('go_back', lang) if st.session_state['download_status'] == 'cancelled' else get_text('go_to_front_page', lang)
            if st.button(button_text):
                # Determine target step: 2 if cancelled (back to settings), 1 if done (front page)
                target_step = 2 if st.session_state['download_status'] == 'cancelled' else 1
                
                # Check if we should clean up ALL state (for step 1) or just download state (for step 2)
                # If step 1, we want full reset. If step 2, we want to keep course selection.
                
                keys_to_clear = ['download_status', 'current_course_index', 'total_items', 
                            'downloaded_items', 'failed_items', 'download_errors_list', 'log_content']
                
                if target_step == 1:
                     keys_to_clear.append('courses_to_download') # Maybe keep selection if step 1? 
                     # Actually standard flow is clear everything if going to front.
                     pass 

                for key in keys_to_clear:
                    if key in st.session_state:
                        del st.session_state[key]
                
                st.session_state['step'] = target_step
                st.session_state['cancel_requested'] = False
                st.rerun()


    # STEP 4: SYNC ANALYSIS (Only shown when current_mode is 'sync')
    elif st.session_state['step'] == 4:
        render_sync_step4(lang)
