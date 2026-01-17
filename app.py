import streamlit as st
import tkinter as tk
from tkinter import filedialog
from canvas_logic import CanvasManager
import os
from pathlib import Path
import time
import re
from translations import get_text

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

def check_cancellation():
    return st.session_state.get('cancel_requested', False)

@st.cache_data
def fetch_courses(token, url, fav_only, language='en'):
    mgr = CanvasManager(token, url, language)
    return mgr.get_courses(fav_only)

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
                    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                        json.dump({
                            'api_url': st.session_state['api_url'],
                            'api_token': st.session_state['api_token']
                        }, f)
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
        if st.button(get_text('logout_edit', lang)):
            st.session_state['is_authenticated'] = False
            st.session_state['api_token'] = ""
            st.session_state['step'] = 1
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

# STEP 1: SELECT COURSES
if st.session_state['step'] == 1:
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
        # "Select All" buttons - Fixed to work properly
        col_sa1, col_sa2 = st.columns([1, 5])
        select_all_clicked = col_sa1.button(get_text('select_all', lang), key="btn_select_all")
        clear_sel_clicked = col_sa2.button(get_text('clear_selection', lang), key="btn_clear_sel")
        
        # Handle button clicks - Update session state keys directly
        if select_all_clicked:
            st.session_state['selected_course_ids'] = [c.id for c in courses]
            # Set all checkbox widget states to True
            for course in courses:
                st.session_state[f"chk_{course.id}"] = True
            st.rerun()
            
        if clear_sel_clicked:
            st.session_state['selected_course_ids'] = []
            # Set all checkbox widget states to False
            for course in courses:
                st.session_state[f"chk_{course.id}"] = False
            st.rerun()

        # Course List with Checkboxes
        selected_ids = st.session_state['selected_course_ids']
        new_selected_ids = []
        
        for course in courses:
            c_name = f"{course.name} ({course.course_code})" if hasattr(course, 'course_code') else course.name
            checkbox_key = f"chk_{course.id}"
            
            # If key is in session_state, let Streamlit use that value. 
            # Otherwise, set default based on selected_course_ids.
            if checkbox_key in st.session_state:
                if st.checkbox(c_name, key=checkbox_key):
                    new_selected_ids.append(course.id)
            else:
                is_checked = course.id in selected_ids
                if st.checkbox(c_name, value=is_checked, key=checkbox_key):
                    new_selected_ids.append(course.id)
        
        st.session_state['selected_course_ids'] = new_selected_ids

        st.markdown("---")
        if st.button(get_text('continue_btn', lang), type="primary"):
            if not st.session_state['selected_course_ids']:
                st.error(get_text('select_one_course', lang))
            else:
                st.session_state['step'] = 2
                st.rerun()

# STEP 2: DOWNLOAD SETTINGS
elif st.session_state['step'] == 2:
    st.markdown(f'<div class="step-header">{get_text("step2_header", lang)}</div>', unsafe_allow_html=True)
    
    step2_container = st.empty()
    with step2_container.container():
        st.subheader(get_text('download_structure', lang))
        mode_choice = st.radio(
            get_text('structure_question', lang),
            [get_text('with_subfolders', lang), get_text('flat_structure', lang)],
            index=0 if st.session_state['download_mode'] == 'modules' else 1
        )
        st.session_state['download_mode'] = 'modules' if get_text('with_subfolders', lang) in mode_choice else 'flat'
        
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
        
        col_back, col_conf = st.columns([1, 1])
        with col_back:
            if st.button(get_text('back_btn', lang)):
                st.session_state['step'] = 1
                st.rerun()
        with col_conf:
            if st.button(get_text('confirm_download', lang), type="primary"):
                try:
                    # Initialize download state
                    all_courses = fetch_courses(st.session_state['api_token'], st.session_state['api_url'], False, lang)
                    course_map = {c.id: c for c in all_courses}
                    courses_to_download = [course_map[cid] for cid in st.session_state['selected_course_ids'] if cid in course_map]
                    
                    st.session_state['courses_to_download'] = courses_to_download
                    st.session_state['current_course_index'] = 0
                    st.session_state['download_status'] = 'scanning' # Start with scanning
                    st.session_state['step'] = 3
                    st.session_state['cancel_requested'] = False
                    st.session_state['total_items'] = 0
                    st.session_state['downloaded_items'] = 0
                    st.session_state['course_mb_downloaded'] = {} # Track MB per course for global total
                    
                    # Brief pause to ensure state is saved before rerun
                    time.sleep(0.1)
                    step2_container.empty() # Clear EVERYTHING in Step 2
                    st.rerun()
                except Exception as e:
                    st.error(f"Error initializing download: {e}")



# STEP 3: PROGRESS
elif st.session_state['step'] == 3:
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
    status_text = st.empty()
    progress_container = st.empty()  # For custom progress bar with text
    mb_counter = st.empty()  # For "Downloading: X / Y MB"
    log_area = st.empty()
    
    # Cancel Button - only show when download is running or scanning
    cancel_placeholder = st.empty()
    if st.session_state['download_status'] in ['running', 'scanning']:
        if cancel_placeholder.button(get_text('cancel_download', lang), type="secondary"):
            cancel_placeholder.empty() # Clear immediately
            st.session_state['cancel_requested'] = True
            st.session_state['download_status'] = 'cancelled'
    
    # Handle download state
    if st.session_state['download_status'] == 'scanning':
        # Scanning phase - count total items
        status_text.text(get_text('scanning_files', lang, current=0, total=total))
        
        cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'], lang)
        total_items = 0
        total_mb = 0
        
        for idx, course in enumerate(st.session_state['courses_to_download']):
            if st.session_state['cancel_requested']:
                st.session_state['download_status'] = 'cancelled'
                st.rerun()
            
            # Update scanning status
            status_text.text(get_text('scanning_files', lang, current=idx + 1, total=total))
            # Simple progress bar for scanning
            progress_container.progress((idx + 1) / total)
            
            # Count items and calculate size
            count = cm.count_course_items(course, file_filter=st.session_state['file_filter'])
            course_size_mb = cm.get_course_total_size_mb(course, st.session_state['download_mode'], file_filter=st.session_state['file_filter'])
            total_items += count
            total_mb += course_size_mb
        
        st.session_state['total_items'] = total_items
        st.session_state['total_mb'] = total_mb
        st.session_state['download_status'] = 'running'
        st.rerun()

    elif st.session_state['download_status'] == 'running':
        if st.session_state['cancel_requested']:
            st.session_state['download_status'] = 'cancelled'
            st.warning(get_text('download_cancelled', lang))
        elif current_idx < total:
            # Download the current course
            course = st.session_state['courses_to_download'][current_idx]
            
            # Update progress bar with file counter text inside
            total_items = st.session_state.get('total_items', 1)
            current_items = st.session_state.get('downloaded_items', 0)
            progress_value = min(current_items / total_items, 1.0) if total_items > 0 else 0
            progress_pct = int(progress_value * 100)
            
            # Custom progress bar with text inside
            progress_text = get_text('downloading_progress_text', lang, current=current_items, total=total_items)
            progress_container.markdown(f"""
                <div style="position: relative; height: 35px; background-color: #f0f2f6; border-radius: 5px; overflow: hidden;">
                    <div style="width: {progress_pct}%; height: 100%; background-color: #1f77b4; transition: width 0.3s;"></div>
                    <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: #333;">{progress_text}</div>
                </div>
            """, unsafe_allow_html=True)
            
            status_text.text(get_text('processing', lang, current=current_idx + 1, total=total, course=course.name))
            
            # Initialize MB counter immediately (left-aligned)
            total_mb = st.session_state.get('total_mb', 0)
            
            # Calculate current total downloaded MB
            current_total_mb = sum(st.session_state.get('course_mb_downloaded', {}).values())
            
            if total_mb > 0:
                mb_text = get_text('mb_progress_text', lang, current=current_total_mb, total=total_mb)
                mb_counter.markdown(mb_text)
            
            def update_ui(msg, progress_type='log', **kwargs):
                """Update UI with progress information.
                Args:
                    msg: Message to display
                    progress_type: Type of progress update
                    **kwargs: Additional data (mb_downloaded for MB tracking)
                """
                if progress_type in ('download', 'page', 'link'):
                    st.session_state['downloaded_items'] += 1
                    current = st.session_state['downloaded_items']
                    total_items = st.session_state.get('total_items', 1)
                    progress_value = min(current / total_items, 1.0) if total_items > 0 else 0
                    progress_pct = int(progress_value * 100)
                    
                    # Update custom progress bar with file counter
                    progress_container.markdown(f"""
                        <div style="position: relative; height: 35px; background-color: #f0f2f6; border-radius: 5px; overflow: hidden;">
                            <div style="width: {progress_pct}%; height: 100%; background-color: #1f77b4; transition: width 0.3s;"></div>
                            <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: #333;">{get_text('downloading_progress_text', lang, current=current, total=total_items)}</div>
                        </div>
                    """, unsafe_allow_html=True)
                
                elif progress_type == 'mb_progress':
                    # Update MB counter (left-aligned)
                    mb_down_course = kwargs.get('mb_downloaded', 0)
                    
                    # Update global tracker
                    if 'course_mb_downloaded' not in st.session_state:
                         st.session_state['course_mb_downloaded'] = {}
                    st.session_state['course_mb_downloaded'][course.id] = mb_down_course
                    
                    current_total_mb = sum(st.session_state['course_mb_downloaded'].values())
                    total_mb = st.session_state.get('total_mb', 0)
                    
                    if total_mb > 0:
                        mb_text = get_text('mb_progress_text', lang, current=current_total_mb, total=total_mb)
                        mb_counter.markdown(mb_text)
                    return  # Don't update log_area for MB progress
                
                # Only update log if there's a message
                if msg:
                    log_area.text(f"[{course.name}] {msg}")
            

            import asyncio
            cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'], lang)
            asyncio.run(cm.download_course_async(
                course,
                st.session_state['download_mode'],
                st.session_state['download_path'],
                progress_callback=update_ui,
                check_cancellation=check_cancellation,
                file_filter=st.session_state['file_filter']
            ))
            
            # Move to next course
            st.session_state['current_course_index'] += 1
            
            # Check if we're done
            if st.session_state['current_course_index'] >= total:
                st.session_state['download_status'] = 'done'
                st.balloons()
                status_text.text(get_text('all_complete', lang))
            # Ensure 100% at the end
            progress_container.markdown(f"""
                <div style="position: relative; height: 35px; background-color: #f0f2f6; border-radius: 5px; overflow: hidden;">
                    <div style="width: 100%; height: 100%; background-color: #1f77b4;"></div>
                    <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: #333;">{get_text('downloading_progress_text', lang, current=total, total=total)}</div>
                </div>
            """, unsafe_allow_html=True)
            
            # Auto-rerun to process next course
            time.sleep(0.1)  # Brief pause to see the update
            st.rerun()
        else:
            # All done
            st.session_state['download_status'] = 'done'
    
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
        
        # Check for download errors
        from pathlib import Path
        error_messages = []
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
                # Categorize errors
                no_url_errors = [e for e in error_messages if 'No download URL' in e]
                # Check for 429 or "Rate Limit" in the error string
                rate_limit_errors = [e for e in error_messages if '429' in e or 'Rate Limit' in e]
                # Check for 401 or "Unauthorized" or "Access Denied"
                unauthorized_errors = [e for e in error_messages if '401' in e or 'Unauthorized' in e or 'Access Denied' in e or 'Adgang Nægtet' in e]
                
                http_errors = [e for e in error_messages if 'HTTP' in e and 'No download URL' not in e and e not in rate_limit_errors and e not in unauthorized_errors]
                other_errors = [e for e in error_messages if e not in no_url_errors and e not in http_errors and e not in rate_limit_errors and e not in unauthorized_errors]
                
                if no_url_errors:
                    st.markdown(get_text('no_url_header', lang))
                    for error in no_url_errors[:10]:  # Show first 10
                        st.text(f"  • {error}")
                    if len(no_url_errors) > 10:
                        st.caption(f"  ... and {len(no_url_errors) - 10} more")
                    st.info(get_text('no_url_explanation', lang))
                
                if rate_limit_errors:
                    st.markdown(f"**⚠️ {get_text('rate_limit_error', lang).split(':')[0]}**") # Use title part of error
                    for error in rate_limit_errors[:5]:
                        st.text(f"  • {get_text('rate_limit_error', lang)}")
                    st.warning(get_text('rate_limit_error', lang))

                if unauthorized_errors:
                    st.markdown(f"**🚫 {get_text('course_unauthorized', lang).split(':')[0]}**")
                    for error in unauthorized_errors[:5]:
                        st.text(f"  • {get_text('course_unauthorized', lang)}")
                
                if http_errors:
                    st.markdown(get_text('http_error_header', lang))
                    for error in http_errors[:10]:
                        st.text(f"  • {error}")
                    if len(http_errors) > 10:
                        st.caption(f"  ... and {len(http_errors) - 10} more")
                    st.info(get_text('http_error_explanation', lang))
                
                if other_errors:
                    st.markdown(get_text('other_error_header', lang))
                    for error in other_errors[:10]:
                        st.text(f"  • {error}")
                    if len(other_errors) > 10:
                        st.caption(f"  ... and {len(other_errors) - 10} more")
                
                st.caption(get_text('full_error_details', lang))
    
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
            # Clean up download state
            for key in ['download_status', 'current_course_index', 'courses_to_download', 'total_items', 'downloaded_items']:
                if key in st.session_state:
                    del st.session_state[key]
            st.session_state['step'] = 1
            st.session_state['cancel_requested'] = False
            st.rerun()


