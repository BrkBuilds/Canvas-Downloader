"""
Sync UI Module — All sync-related Streamlit UI logic.
Comprehensive overhaul with:
  - Fixed Select All / Deselect All buttons
  - Open Folder buttons inside pair cards
  - Friendly course names (no technical metadata)
  - Step wizard indicator
  - Course search/filter in dropdown
  - Confirmation dialog before sync
  - Quick Sync All for returning users
  - Sync history UI
  - Per-course sync option
  - Clean analysis & sync screens (no stale content)
  - Consistent card design throughout
"""

import os
import time
import asyncio
import logging
from pathlib import Path
from datetime import datetime
import urllib.parse

import streamlit as st
import aiohttp
from collections import defaultdict
import sqlite3
import aiofiles


from translations import get_text
from canvas_logic import CanvasManager
from sync_manager import SyncManager, SyncHistoryManager, get_file_icon, format_file_size
from ui_helpers import (
    load_sync_pairs,
    save_sync_pairs,
    check_disk_space,
    open_folder,
    render_progress_bar,
    render_sync_wizard,
    friendly_course_name,
    short_path,
    pluralize,
    robust_filename_normalize,
    parse_cbs_metadata,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------

def _init_sync_session_state():
    """Ensure all sync-related session-state keys exist."""
    defaults = {
        'sync_pairs': [],
        'pending_sync_folder': None,
        'analysis_result': None,
        'sync_selected_files': {},
        'sync_manifest': None,
        'sync_manager': None,
        'sync_mode': False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _load_persistent_pairs():
    """Load persistent pairs from disk into session state (once)."""
    if 'sync_pairs_loaded' not in st.session_state:
        saved = load_sync_pairs()
        if saved and not st.session_state.get('sync_pairs'):
            st.session_state['sync_pairs'] = saved
        st.session_state['sync_pairs_loaded'] = True


def _persist_current_pairs():
    """Save the current session-state pairs to disk."""
    save_sync_pairs(st.session_state.get('sync_pairs', []))


# ---------------------------------------------------------------------------
# Folder picker  (tkinter, reused from app.py)
# ---------------------------------------------------------------------------

def _select_sync_folder():
    """Open native folder picker and store result in pending_sync_folder."""
    import tkinter as tk
    from tkinter import filedialog
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


# ===================================================================
# STEP 1 — Folder Pairing
# ===================================================================

def render_sync_step1(lang: str, fetch_courses_fn, main_placeholder=None):
    """Render Sync Step 1: folder pairing UI."""
    # Guard clause: double check that we are in step 1.
    # This prevents ghost UI elements if app.py logic somehow leaks.
    if st.session_state.get('step') != 1:
        return

    _init_sync_session_state()
    _load_persistent_pairs()

    # Step wizard
    render_sync_wizard(st, 1, lang)

    # (7) Removed "Select Folders to Sync" header — wizard is enough context.

    # Fetch courses (needed by pair cards and the add-folder UI)
    courses = fetch_courses_fn(
        st.session_state['api_token'],
        st.session_state['api_url'],
        False,
        lang,
    )
    
    # Pre-fetch and flag favorites to fix "Favorites Only" modal filter
    try:
        fav_courses = fetch_courses_fn(
            st.session_state['api_token'],
            st.session_state['api_url'],
            True,
            lang,
        )
        fav_ids = {c.id for c in fav_courses}
    except Exception:
        fav_ids = set()

    for c in courses:
        setattr(c, 'is_favorite', c.id in fav_ids)
    
    # 1. Generate base friendly names
    # We want "Friendly Name" usually, but if two courses have same friendly name,
    # we must disambiguate so the user can select the right one.
    
    temp_names = {}
    name_counts = defaultdict(int)
    
    for c in courses:
        raw_name = f"{c.name} ({c.course_code})" if hasattr(c, 'course_code') else c.name
        friendly = friendly_course_name(raw_name)
        temp_names[c.id] = {'friendly': friendly, 'raw': raw_name}
        name_counts[friendly] += 1
    
    # 2. Build final unique map
    course_names = {}
    for c in courses:
        entry = temp_names[c.id]
        if name_counts[entry['friendly']] > 1:
             # Collision: use raw name to disambiguate
             course_names[c.id] = entry['raw']
        else:
             course_names[c.id] = entry['friendly']

    # Sort solely by the display name for the dropdown
    sorted_course_names = sorted(course_names.values(), key=lambda x: x.lower())
    course_options = ["-- " + get_text('sync_select_course', lang) + " --"] + sorted_course_names

    # --- (8) Bigger subheading ---
    st.markdown(
        f'<h3 style="margin:1em 0 -0.8rem 0;">{get_text("sync_courses_to_sync", lang)}</h3>',
        unsafe_allow_html=True,
    )

    sync_pairs = st.session_state.get('sync_pairs', [])
    pairs_to_remove = []

    # --- (4) Pair action-button CSS: Remove fixed height, let flex align handle it ---
    st.markdown("""
    <style>
    div[data-testid="column"] { display: flex; flex-direction: column; justify-content: center; }

    /* Cancel button styling */
    button[data-testid="stBaseButton-secondary"]#cancel_pair {
        /* Styled via app.py global CSS now */
    }

    /* ===== SYNC FOLDER ROW COMPACT LAYOUT =====
     * Scoped to .st-key-edit_form_container (the bordered container key)
     * so rules NEVER leak to page-level stVerticalBlocks.
     */
    
    /* 0. Remove top margin from the edit form container itself to match list spacing */
    .st-key-edit_form_container {
        margin-top: 0px !important; /* Match bottom spacing (10px) exactly */
        margin-bottom: 10px !important; /* Ensure consistent bottom spacing */
    }

    /* 1. Compact padding & gap on the bordered container ONLY */
    .st-key-edit_form_container > div[data-testid="stVerticalBlock"] {
        padding: 8px 15px !important;
        gap: 4px !important;
    }

    /* 2. RESET: Inner stVerticalBlocks inside columns back to 0 */
    .st-key-edit_form_container div[data-testid="stColumn"] div[data-testid="stVerticalBlock"] {
        padding: 0 !important;
        gap: 0 !important;
    }

    /* 3. Hide ONLY the first child (CSS style block) & empty spacers */
    .st-key-edit_form_container > div[data-testid="stVerticalBlock"]
    > div[data-testid="stElementContainer"]:has(div:empty:only-child) {
         display: none !important;
    }

    /* 4. Folder/Course row: center items vertically, controlled gap */
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_change_folder),
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_open_course_dialog) {
        align-items: center !important;
        gap: 10px !important;
        min-height: 0 !important;
    }

    /* 5. Columns in folder/course row: shrink-wrap, center contents */
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_change_folder) div[data-testid="stColumn"],
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_open_course_dialog) div[data-testid="stColumn"] {
        width: auto !important;
        flex: 0 0 auto !important;
        min-width: 0 !important;
        display: flex !important;
        align-items: center !important;
    }

    /* 6. Fix stMarkdownContainer negative bottom margin that clips text */
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_change_folder) div[data-testid="stMarkdownContainer"],
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_open_course_dialog) div[data-testid="stMarkdownContainer"] {
        margin: 0 !important;
    }

    /* 7. stMarkdown wrapper: flex-center for true vertical alignment */
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_change_folder) div[data-testid="stMarkdown"],
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_open_course_dialog) div[data-testid="stMarkdown"] {
        display: flex !important;
        align-items: center !important;
        overflow: visible !important;
    }

    /* 8. Element containers in folder/course row: no margin, visible overflow */
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_change_folder) div[data-testid="stElementContainer"],
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_open_course_dialog) div[data-testid="stElementContainer"] {
        margin: 0 !important;
        overflow: visible !important;
    }

    /* 9. Kill paragraph margins & normalize line height */
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_change_folder) p,
    .st-key-edit_form_container div[data-testid="stHorizontalBlock"]:has(.st-key-btn_open_course_dialog) p {
        margin: 0 !important;
        line-height: 1.4 !important;
    }

    /* 10. Change Folder/Course button: compact styling */
    .st-key-btn_change_folder button,
    .st-key-btn_open_course_dialog button {
        border: 1px solid rgba(255,255,255,0.3) !important;
        padding: 4px 14px !important;
        font-size: 0.85rem !important;
        line-height: 1.4 !important;
        height: auto !important;
    }

    /* 11. Sync list container minimum height */
    .st-key-sync_list_outline {
        min-height: 50vh !important;
    }
    </style>
    """, unsafe_allow_html=True)

    with st.container(border=True, key="sync_list_outline"):
        if sync_pairs:
            editing_idx = st.session_state.get('editing_pair_idx')

            for idx, pair in enumerate(sync_pairs):
                # --- If this pair is being edited, render the edit form inline ---
                if editing_idx is not None and editing_idx == idx and st.session_state.get('pending_sync_folder'):
                    _render_pending_folder_ui(courses, course_names, course_options, lang)
                    # Removed explicit spacer to match list gap via CSS margin-bottom on container
                    continue

                # Use vertical_alignment="center" (Streamlit 1.32+) or rely on CSS above
                # Adjusted ratios: Card takes space, but buttons need room for text now
                col_card, col_open, col_edit, col_remove = st.columns([5, 1.5, 1.1, 1.2], gap="small", vertical_alignment="center")

                with col_card:
                    folder_exists = Path(pair['local_folder']).exists()
                    border_color = "#444" if folder_exists else "#c0392b"
                    last_synced = pair.get('last_synced')
                    ts_str = (
                        get_text('sync_last_synced', lang, time=last_synced) if last_synced
                        else get_text('sync_never_synced', lang)
                    )
                    
                    # Simplified card content
                    display_name = friendly_course_name(pair['course_name'])
                    folder_display = short_path(pair['local_folder'])
                    
                    st.markdown(f"""
                    <div style="background-color:#2d2d2d;border:1px solid {border_color};border-radius:8px;padding:8px 12px;">
                        <div style="font-weight:600;font-size:1em;color:#fff;">
                            {get_text('sync_course_prefix', lang)} {display_name}
                        </div>
                        <div style="font-size:0.85em;color:#ccc;margin-top:2px;">
                             📁 {folder_display}
                        </div>
                        <div style="font-size:0.75em;color:#888;margin-top:2px;">
                             🕓 {ts_str}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                # (4) Action buttons with text labels restored
                with col_open:
                    if folder_exists:
                        if st.button("📂 " + get_text('sync_open_folder_action', lang),
                                     key=f"open_folder_{idx}", use_container_width=True):
                            open_folder(pair['local_folder'])

                with col_edit:
                    if st.button("✏️ " + get_text('sync_edit_pair', lang), 
                                 key=f"edit_pair_{idx}", use_container_width=True):
                        st.session_state['pending_sync_folder'] = pair['local_folder']
                        st.session_state['editing_pair_idx'] = idx
                        # Pre-populate selected course for editing
                        st.session_state['sync_selected_course_id'] = pair['course_id']
                        st.rerun()

                with col_remove:
                    if st.button("🗑️ " + get_text('sync_remove_pair', lang), 
                                 key=f"remove_pair_{idx}", use_container_width=True):
                        pairs_to_remove.append(idx)
                
                # Add vertical spacing between blocks
                st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)

            if pairs_to_remove:
                st.session_state['sync_pairs'] = [p for i, p in enumerate(sync_pairs) if i not in pairs_to_remove]
                _persist_current_pairs()
                st.rerun()
            if st.session_state.get('pending_sync_folder') and st.session_state.get('editing_pair_idx') is None:
                _render_pending_folder_ui(courses, course_names, course_options, lang)
            else:
                # (9) "Add Course folder" — compact
                col_add, _ = st.columns([0.25, 0.75]) 
                with col_add:
                    st.markdown("""<span id="add_folder_proxy"></span>
                    <style>
                    div:has(span#add_folder_proxy) ~ div button[data-testid="stBaseButton-secondary"] {
                        border: 1px solid #4a7a9b !important;
                        background-color: #2a3a4a !important;
                        color: #cde !important;
                        margin-top: -35px !important;
                        position: relative;
                        z-index: 1;
                    }
                    div:has(span#add_folder_proxy) ~ div button[data-testid="stBaseButton-secondary"]:hover {
                         background-color: #3a4a5a !important;
                         border-color: #6a9abb !important;
                         color: #fff !important;
                    }
                    </style>""", unsafe_allow_html=True)
    
                    if st.button("➕ " + get_text('sync_add_course_folder', lang), key="btn_add_folder"):
                        _select_sync_folder()
                        st.session_state['sync_selected_course_id'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.rerun()

        else:
            # EMPTY STATE Logic (if not sync_pairs)
            if st.session_state.get('pending_sync_folder') and st.session_state.get('editing_pair_idx') is None:
                _render_pending_folder_ui(courses, course_names, course_options, lang)
            else:
                col_add, _ = st.columns([0.25, 0.75]) 
                with col_add:
                    st.markdown("""<span id="add_folder_proxy_empty"></span>
                    <style>
                    div:has(span#add_folder_proxy_empty) ~ div button[data-testid="stBaseButton-secondary"] {
                        border: 1px solid #4a7a9b !important;
                        background-color: #2a3a4a !important;
                        color: #cde !important;
                    }
                    div:has(span#add_folder_proxy_empty) ~ div button[data-testid="stBaseButton-secondary"]:hover {
                         background-color: #3a4a5a !important;
                         border-color: #6a9abb !important;
                         color: #fff !important;
                    }
                    </style>""", unsafe_allow_html=True)
    
                    if st.button("➕ " + get_text('sync_add_course_folder', lang), key="btn_add_folder_empty"):
                        _select_sync_folder()
                        st.session_state['sync_selected_course_id'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.rerun()
    
            import base64
            
            # Helper to optionally load icon
            logo_html = ""
            icon_path = Path(__file__).parent / "assets" / "icon.png"
            if icon_path.exists():
                try:
                    with open(icon_path, "rb") as f:
                        b64_logo = base64.b64encode(f.read()).decode("utf-8")
                        logo_html = f'<div style="text-align: center; opacity: 0.5; margin-bottom: 20px;"><img src="data:image/png;base64,{b64_logo}" width="120" style="filter: grayscale(100%);" alt="Canvas Downloader Logo"/></div>'
                except Exception:
                    pass
            
            st.markdown(
                f'<div style="padding: 20px 10px 40px 10px; display: flex; flex-direction: column; align-items: center; justify-content: center;">'
                f'{logo_html}'
                f'<div style="color: #bbb; font-size: 1.1rem; text-align: center; max-width: 400px; line-height: 1.5;">'
                f'Ready to sync? Add a local folder and map it to a Canvas course to get started!'
                f'</div></div>', 
                unsafe_allow_html=True
            )

    # --- (5) Analyze + Quick Sync action buttons ---
    # Task 1: Check for ignored files
    total_ignored = 0
    ignored_by_course = {}
    if sync_pairs:
        for pair in sync_pairs:
            local_folder = pair.get('local_folder')
            course_id = pair.get('course_id')
            if local_folder and Path(local_folder).exists():
                sm = SyncManager(local_folder, course_id, pair.get('course_name', ''), lang)
                ignored = sm.get_ignored_files()
                if ignored:
                    ignored_by_course[pair['course_id']] = {
                        'pair': pair,
                        'files': ignored,
                        'sync_manager': sm
                    }
                    total_ignored += len(ignored)
                    
    if total_ignored > 0:
        if st.button(f"🗑️ Manage Ignored Files ({total_ignored})", key="btn_manage_ignored", use_container_width=True):
            _ignored_files_dialog(ignored_by_course, lang)

    if sync_pairs:
        invalid = [p for p in sync_pairs if not Path(p['local_folder']).exists()]
        if invalid:
            st.warning(get_text('sync_folder_not_found', lang, path=invalid[0]['local_folder']))

    # Ratios: 0.75 is ~75% of the previous 1.0 width (relative to page)
    # gap="small" brings the OR closer
    col_analyze, col_or, col_quick, _ = st.columns([0.75, 0.12, 0.75, 2.38], gap="small", vertical_alignment="center")

    # Force identical styling for the two primary buttons in this section
    # We target specific children of these columns to ensure parity.
    st.markdown("""
    <style>
    /* Target buttons inside the main column containers */
    div[data-testid="column"] button[kind="primary"] {
        height: 3.2em !important;
        min-height: 3.2em !important;
        border-radius: 6px !important;
        width: 100% !important;
        padding: 0px 10px !important;
        float: none !important;
        margin: 0 auto !important;
    }
    /* RECURSIVE CENTERING: START - Universal child selector */
    /* This forces EVERY element inside the button to be flex-centered */
    div[data-testid="column"] button[kind="primary"] > div,
    div[data-testid="column"] button[kind="primary"] > div > p {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-align: center !important;
        width: 100% !important;
        height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    /* Extra safety: Target * recursive if above fails */
    div[data-testid="column"] button[kind="primary"] * {
        text-align: center !important;
        align-items: center !important;
        justify-content: center !important;
    }
    div[data-testid="column"] button[kind="primary"] p {
        font-size: 1rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
    }
    div[data-testid="column"] > div[data-testid="stMarkdown"] > div > div {
         height: 100%;
         align-content: center;
    }
    </style>
    """, unsafe_allow_html=True)
    
    with col_analyze:
        # Added key for symmetry and potential state stability
        if st.button("🔍" + get_text('sync_start_analysis', lang), type="primary",
                     key="btn_analyze",
                     use_container_width=True,
                     disabled=not bool(sync_pairs)):
            st.session_state['step'] = 4
            st.session_state['download_status'] = 'analyzing'
            st.session_state.pop('sync_single_pair_idx', None)
            if main_placeholder:
                main_placeholder.empty()
            st.rerun()

    with col_or:
        # Removed manual margin-top hack, relying on vertical_alignment="center" and flex CSS above
        st.markdown(f"<div style='text-align:center; font-weight:bold; color:#888; font-size:0.9em;'>OR</div>", unsafe_allow_html=True)

    with col_quick:
        # Removed help=... to prevent tooltip wrapper from breaking layout parity with the other button
        if st.button("⚡" + get_text('sync_quick_sync', lang),
                     key="btn_quick_sync",
                     type="primary",
                     use_container_width=True,
                     disabled=not bool(sync_pairs)):
            st.session_state['step'] = 4
            st.session_state['download_status'] = 'analyzing'
            st.session_state['sync_quick_mode'] = True
            st.session_state.pop('sync_single_pair_idx', None)
            if main_placeholder:
                main_placeholder.empty()
            st.rerun()

    # --- (6) Tutorial + Sync History — grouped at bottom below separator ---
    st.markdown("---")
    with st.expander(get_text('sync_tutorial_title', lang), expanded=False):
        st.markdown(get_text('sync_tutorial_text', lang))
    _render_sync_history(lang)


def _render_sync_history(lang):
    """Render sync history in an expander at the bottom of step 1."""
    try:
        from ui_helpers import get_config_dir
        history_mgr = SyncHistoryManager(get_config_dir())
        history = history_mgr.load_history()
    except Exception:
        history = []

    if history:
        with st.expander(get_text('sync_history_title', lang), expanded=False):
            if not history:
                st.write(get_text('sync_history_empty', lang))
                return
                
            # Show most recent first, limit to 10
            for entry in reversed(history[-10:]):
                count = entry.get('files_synced', 0)
                courses_count = entry.get('courses', 0)
                course_names = entry.get('course_names', [])
                
                # Format the time beautifully
                raw_time = entry.get('timestamp', '')
                time_display = raw_time
                try:
                    dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M")
                    now = datetime.now()
                    diff = now - dt
                    
                    if diff.days == 0:
                        if diff.seconds < 3600:
                            mins = diff.seconds // 60
                            time_display = f"⏳ {mins} minute{'s' if mins != 1 else ''} ago ({dt.strftime('%H:%M')})"
                        else:
                            hrs = diff.seconds // 3600
                            time_display = f"⏳ {hrs} hour{'s' if hrs != 1 else ''} ago ({dt.strftime('%H:%M')})"
                    elif diff.days == 1:
                        time_display = f"📅 Yesterday at {dt.strftime('%H:%M')}"
                    elif diff.days < 7:
                        time_display = f"📅 {diff.days} days ago ({dt.strftime('%A')} at {dt.strftime('%H:%M')})"
                    else:
                        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                        month_name = months[dt.month - 1]
                        
                        day_suffix = "th"
                        if 11 <= dt.day <= 13:
                            pass
                        elif dt.day % 10 == 1:
                            day_suffix = "st"
                        elif dt.day % 10 == 2:
                            day_suffix = "nd"
                        elif dt.day % 10 == 3:
                            day_suffix = "rd"
                            
                        time_display = f"📅 {diff.days} days ago ({dt.day}{day_suffix} of {month_name} at {dt.strftime('%H:%M')})"
                except Exception:
                    time_display = f"⏳ {raw_time}"
                
                # Course names display
                courses_text = ""
                if course_names:
                    # Filter and format course names
                    # (Already friendly from backend update, but safe to wrap again)
                    formatted_names = [friendly_course_name(name) for name in course_names if name]
                    if formatted_names:
                        courses_text = f"<div style='font-size:0.9em;color:#aaa;margin-top:4px;'>📚 <i>{', '.join(formatted_names)}</i></div>"
                elif courses_count > 0:
                    courses_text = f"<div style='font-size:0.9em;color:#aaa;margin-top:4px;'>📚 <i>Across {courses_count} course{'s' if courses_count != 1 else ''}</i></div>"

                # Render HTML card inside the expander (Vertical stack layout)
                st.markdown(f"""
                <div style="background-color:#2a2b30;border-left:3px solid #3498db;border-radius:4px;padding:12px 14px;margin-bottom:12px;display:flex;flex-direction:column;gap:2px;">
                    <div style="color:#888;font-size:0.85em;">{time_display}</div>
                    <div style="color:#ddd;font-weight:600;font-size:0.95em;margin-top:2px;">
                        ✅ Synced {count} file{'s' if count != 1 else ''}
                    </div>
                    {courses_text}
                </div>
                """, unsafe_allow_html=True)


@st.dialog("Ignored Files", width="large")
def _ignored_files_dialog(ignored_by_course, lang):
    """Dialog to manage and restore files that were previously ignored."""
    st.markdown("""
        <style>
            div.st-key-ignored_list_scroll_container {
                height: 55vh !important;
                min-height: 55vh !important;
                max-height: 55vh !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
                padding-right: 5px;
            }
        </style>
    """, unsafe_allow_html=True)

    # Initialize state for all ignored files if not present
    for cid, data in ignored_by_course.items():
        for f in data['files']:
            key = f"unignore_{cid}_{f.canvas_file_id}"
            if key not in st.session_state:
                st.session_state[key] = False

    # Collect keys
    all_unignore_keys = [
        f"unignore_{cid}_{f.canvas_file_id}"
        for cid, data in ignored_by_course.items()
        for f in data['files']
    ]

    # Global Controls
    c1, c2, _ = st.columns([0.25, 0.25, 0.5])
    with c1:
        if st.button("Select All", use_container_width=True, key="ign_sa"):
            for k in all_unignore_keys:
                st.session_state[k] = True
            st.rerun()
    with c2:
        if st.button("Clear Selection", use_container_width=True, key="ign_ca"):
            for k in all_unignore_keys:
                st.session_state[k] = False
            st.rerun()

    st.markdown("---")

    # List items
    with st.container(border=False, key="ignored_list_scroll_container"):
        for cid, data in ignored_by_course.items():
            pair = data['pair']
            friendly = friendly_course_name(pair['course_name'])
            raw_name = pair['course_name']
            
            with st.expander(f"📁 {friendly} ({raw_name})", expanded=True):
                for f in data['files']:
                    key = f"unignore_{cid}_{f.canvas_file_id}"
                    icon = get_file_icon(f.canvas_filename)
                    st.checkbox(f"{icon} {f.canvas_filename}", key=key)

    # Count checked
    checked_count = sum(1 for k in all_unignore_keys if st.session_state.get(k, False))
    
    st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)

    # Action Button
    col_restore, col_cancel = st.columns([1, 1])
    with col_restore:
        # Dynamic Red button
        btn_text = f"Remove {checked_count} file(s) from ignored list"
        
        # Inject CSS to make primary button red if active
        if checked_count > 0:
            st.markdown("""<style>
                button[data-testid="stBaseButton-primary"]:has(p:contains("Remove")) {
                    background-color: #e74c3c !important;
                    border-color: #c0392b !important;
                    color: white !important;
                }
                button[data-testid="stBaseButton-primary"]:has(p:contains("Remove")):hover {
                    background-color: #c0392b !important;
                }
            </style>""", unsafe_allow_html=True)
            
        if st.button(btn_text, type="primary", disabled=(checked_count == 0), use_container_width=True):
            # Process un-ignore
            files_restored = 0
            for cid, data in ignored_by_course.items():
                sm = data['sync_manager']
                to_restore = []
                for f in data['files']:
                    if st.session_state.get(f"unignore_{cid}_{f.canvas_file_id}"):
                        to_restore.append(f.canvas_file_id)
                if to_restore:
                    sm.unignore_files(to_restore)
                    files_restored += len(to_restore)
                    
            st.success(f"Successfully restored {files_restored} file(s)!")
            # Clean state
            for k in all_unignore_keys:
                st.session_state.pop(k, None)
            time.sleep(1)
            st.rerun()

    with col_cancel:
        if st.button("Close", use_container_width=True):
            for k in all_unignore_keys:
                st.session_state.pop(k, None)
            st.rerun()


@st.dialog("Select Course to sync", width="large")
def select_course_dialog(courses, current_selected_id, lang):
    # We use a purely static CSS string so React NEVER unmounts it during re-renders.
    # Instead, we use the CSS `:has()` pseudo-class to sniff the native HTML checkbox state 
    # of the Streamlit toggle and shift the height instantly, completely bypassing the Python backend rendering lag.
    st.markdown("""
        <style>
            /* Default closed state: 65vh */
            div.st-key-course_list_scroll_container {
                height: 65vh !important;
                min-height: 65vh !important;
                max-height: 65vh !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
                padding-right: 5px; /* Leave room for scrollbar */
            }
            
            /* Open state: Sniff the native toggle checkbox. If checked, force 55vh instantly! */
            html:has(div.st-key-sync_dialog_show_cbs input:checked) div.st-key-course_list_scroll_container {
                height: 55vh !important;
                min-height: 55vh !important;
                max-height: 55vh !important;
            }
            
            /* Trim dead space beneath the standard CBS Filter toggle */
            div.st-key-sync_dialog_show_cbs {
                margin-bottom: -15px !important;
            }
            
            /* Trim dead space beneath the active CBS Filter selection grid container */
            div.st-key-sync_dialog_cbs_container {
                margin-bottom: -15px !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # 1. Filters similar to main app
    col_filters, _ = st.columns([0.7, 0.3])
    with col_filters:
        filter_mode = st.radio(
            "Filter Mode",
            [get_text('show_favorites', lang), get_text('show_all', lang)],
            index=1 if not st.session_state.get('sync_filter_favorites', True) else 0,
            horizontal=True,
            label_visibility="collapsed",
            key="sync_dialog_filter_mode"
        )
    
    # Update preference
    st.session_state['sync_filter_favorites'] = (filter_mode == get_text('show_favorites', lang))
    
    # Filter by favorites
    visible_courses = courses
    if st.session_state['sync_filter_favorites']:
        visible_courses = [c for c in courses if getattr(c, 'is_favorite', False)]
        
    if not visible_courses:
        st.warning(get_text('no_courses', lang))
        if st.button("Close"):
             st.rerun()
        return

    # CBS Filters
    show_filters = st.toggle(get_text('enable_cbs_filters', lang, default="Enable CBS Filters"), key="sync_dialog_show_cbs")
    
    filtered_courses = visible_courses
    
    if show_filters:
        # metadata parsing
        course_meta = {}
        all_types = set()
        all_semesters = set()
        all_years = set()
        
        for c in visible_courses:
             full_name_str = f"{c.name} ({c.course_code})" if hasattr(c, 'course_code') else c.name
             meta = parse_cbs_metadata(full_name_str)
             course_meta[c.id] = meta
             if meta['type']: all_types.add(meta['type'])
             if meta['semester']: all_semesters.add(meta['semester'])
             if meta['year_full']: all_years.add(meta['year_full'])

        # Render Widgets
        with st.container(border=True, key="sync_dialog_cbs_container"):
             st.markdown(f"**{get_text('filter_criteria', lang, default='Filter Criteria')}**")
             c1, c2, c3 = st.columns(3)
             with c1:
                 sel_types = st.multiselect(get_text('filter_type', lang, default="Class Type"), options=sorted(list(all_types)), key="sync_d_type")
             with c2:
                 sel_sem = st.multiselect(get_text('filter_semester', lang, default="Semester"), options=sorted(list(all_semesters)), key="sync_d_sem")
             with c3:
                 sel_years = st.multiselect(get_text('filter_year', lang, default="Year"), options=sorted(list(all_years), reverse=True), key="sync_d_year")
        
        # Apply Logic
        if sel_types or sel_sem or sel_years:
             temp_filtered = []
             for c in visible_courses:
                 meta = course_meta[c.id]
                 match_type = meta['type'] in sel_types if sel_types else True
                 match_sem = meta['semester'] in sel_sem if sel_sem else True
                 match_year = meta['year_full'] in sel_years if sel_years else True
                 
                 if match_type and match_sem and match_year:
                     temp_filtered.append(c)
             filtered_courses = temp_filtered
             
             if not filtered_courses:
                 st.info(get_text('no_courses_match_filters', lang, default="No courses match."))

    # Sorting
    # current selection first (weight 0), then alphabetical (weight 1)
    active_selection = st.session_state.get("sync_dialog_selected_id", current_selected_id)
    filtered_courses.sort(key=lambda c: (0 if c.id == active_selection else 1, (c.name or "").lower()))
    
    # We use a raw HTML line instead of st.markdown("---") to eradicate Streamlit's implicit Markdown wrapper padding that generates massive dead space above it.
    st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)
    
    # Render List
    # We implement "Single Select" by using a session state key that acts as the single source of truth
    # key: "sync_dialog_selected_id"
    
    # Initialize if not set
    if "sync_dialog_selected_id" not in st.session_state:
        st.session_state["sync_dialog_selected_id"] = current_selected_id

    # We need to be able to Unselect? Or just switch? 
    # Usually strictly one course is good.
    
    with st.container(border=False, key="course_list_scroll_container"):
        for course in filtered_courses:
            # Calculate display names
            full_name_str = f"{course.name} ({course.course_code})" if hasattr(course, 'course_code') else course.name
            friendly = friendly_course_name(full_name_str)
            
            # Determine if checked
            is_checked = (st.session_state["sync_dialog_selected_id"] == course.id)
            
            # Layout
            c1, c2 = st.columns([0.05, 0.95])
            with c1:
                 # Checkbox that behaves like radio
                 
                 # Ensure widget state matches our single source of truth before rendering
                 st.session_state[f"sync_chk_{course.id}"] = is_checked

                 def course_toggled(cid):
                     if st.session_state.get(f"sync_chk_{cid}"):
                         st.session_state["sync_dialog_selected_id"] = cid
                     elif st.session_state.get("sync_dialog_selected_id") == cid:
                         st.session_state["sync_dialog_selected_id"] = None

                 st.checkbox(
                     "Select",
                     key=f"sync_chk_{course.id}",
                     on_change=course_toggled,
                     args=(course.id,),
                     label_visibility="collapsed"
                 )

            with c2:
                 # Styled Text (appended immediately after checkbox as an inline-block)
                 st.markdown(
                     f'<div style="margin-top: -2px; width: 100%;">'
                     f'<strong>{friendly}</strong> '
                     f'<br><span style="color:#888; font-size:0.85em;">{full_name_str}</span>'
                     f'</div>',
                     unsafe_allow_html=True
                 )
            # st.markdown("<div style='margin-bottom:5px'></div>", unsafe_allow_html=True) # Spacer

    # Use HTML hr to eradicate padding above the Confirm button separator
    st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)
    if st.button("Confirm Selection", key="sync_confirm_btn", type="primary", use_container_width=True):
        st.session_state["sync_selected_return_id"] = st.session_state["sync_dialog_selected_id"]
        st.rerun()


def _render_pending_folder_ui(courses, course_names, course_options, lang):
    """Inline UI shown while adding/editing a sync-pair — unified card."""
    pending_folder = st.session_state['pending_sync_folder']
    folder_name = Path(pending_folder).name
    editing_idx = st.session_state.get('editing_pair_idx')

    # (1) Everything inside one bordered container
    # (1) Everything inside one bordered container
    with st.container(border=True, key="edit_form_container"):
        # (3) CSS for cancel button red styling (Moved to render_sync_step1 for global scope/no flash)

        # Two auto-width columns + spacer, vertically centered
        col_folder_info, col_change_btn, col_spacer = st.columns(
            [1, 1, 1], vertical_alignment="center", gap="small"
        )

        with col_folder_info:
            st.markdown(
                f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                f'{get_text("sync_adding_folder", lang)}</span>'
                f'<span style="color:#fff;font-weight:600;font-size:0.95rem;white-space:nowrap;">📁 {folder_name}</span>',
                unsafe_allow_html=True,
            )
        with col_change_btn:
            if st.button(get_text('sync_change_folder', lang), key="btn_change_folder"):
                _select_sync_folder()
                st.rerun()
        with col_spacer:
            st.empty()

        # --- Course Selection (Pop-up Dialog) ---
        
        # Determine current display
        current_disp = get_text('sync_select_course', lang) # Default "Select Canvas Course"
        
        # Get current selected course ID from session state (for editing or new)
        selected_course_id = st.session_state.get('sync_selected_course_id')
        selected_course_name = None # Will be derived from ID or set by dialog

        # Try to find friendly name for selected ID
        if selected_course_id and selected_course_id in course_names:
             # course_names mapped ID -> Friendly (since we reverted to friendly-only)
             # Note: ensure course_names is available here. It is passed as arg.
             current_disp = course_names[selected_course_id]
             selected_course_name = course_names[selected_course_id]
        elif selected_course_id: # If ID exists but not in current course_names (e.g., course deleted)
             current_disp = f"ID: {selected_course_id} (Course not found)"
        
        # Determine button label based on mode
        if editing_idx is not None:
             btn_label = get_text('sync_change_course', lang, default="Change Course")
        else:
             btn_label = get_text('sync_select_course_btn', lang, default="Select Course")
        
        # Two columns like folder row: [1, 1, 1] to keep it left-aligned
        # REVISED: [1, 1, 1] — relying on CSS flex auto-width to handle content size
        col_c_info, col_c_btn, col_c_spacer = st.columns([1, 1, 1], vertical_alignment="center", gap="small")
        
        with col_c_info:
            st.markdown(
                f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                f'{get_text("sync_course_prefix", lang)}</span>'
                f'<span style="color:#fff;font-weight:600;font-size:0.95rem;white-space:nowrap;">{current_disp}</span>',
                unsafe_allow_html=True
            )
            
        with col_c_btn:
            if st.button(btn_label, key="btn_open_course_dialog"):
                st.session_state["sync_dialog_selected_id"] = selected_course_id
                select_course_dialog(courses, selected_course_id, lang)
        
        with col_c_spacer:
            st.empty()

        # Check for return value from dialog
        if "sync_selected_return_id" in st.session_state:
            ret_id = st.session_state["sync_selected_return_id"]
            # Consume it
            del st.session_state["sync_selected_return_id"]
            
            # Update session state for the sync pair
            selected_course_id = ret_id
            
            if ret_id and ret_id in course_names:
                selected_course_name = course_names[ret_id]
            elif ret_id:
                 # Find obj
                 c_obj = next((c for c in courses if c.id == ret_id), None)
                 if c_obj:
                     selected_course_name = friendly_course_name(c_obj.name) # Best effort
            else:
                 selected_course_name = None

            # Persist to editing pair if in edit mode
            if editing_idx is not None and 0 <= editing_idx < len(st.session_state.get('sync_pairs', [])):
                 st.session_state['sync_pairs'][editing_idx]['course_id'] = selected_course_id
                 st.session_state['sync_pairs'][editing_idx]['course_name'] = selected_course_name
            
            # Persist to temp state for new pair
            st.session_state['sync_selected_course_id'] = selected_course_id
            st.rerun()

        # --- Warnings ---
        # Mismatch warning
        if selected_course_name:
            # Determine if this is the original course selection
            is_same_as_original = False
            if editing_idx is not None and 0 <= editing_idx < len(st.session_state.get('sync_pairs', [])):
                 original_pair = st.session_state['sync_pairs'][editing_idx]
                 if original_pair.get('course_id') == selected_course_id:
                     is_same_as_original = True
                 elif original_pair.get('course_name') == selected_course_name:
                     is_same_as_original = True
            
            folder_lower = folder_name.lower()
            course_lower = selected_course_name.lower()
            course_words = [w for w in course_lower.replace('(', ' ').replace(')', ' ').split() if len(w) > 3]
            folder_words = [w for w in folder_lower.replace('(', ' ').replace(')', ' ').split() if len(w) > 3]
            has_match = (
                any(cw in folder_lower for cw in course_words)
                or any(fw in course_lower for fw in folder_words)
            )
            
            # Mismatch warning: Only if not the original selection (user changed it)
            if not has_match and not is_same_as_original:
                st.warning(get_text('sync_mismatch_warning', lang))

            # Duplicate pair detection
            existing = st.session_state.get('sync_pairs', [])
            candidates = existing
            if editing_idx is not None:
                # Filter out the pairing being edited so we don't warn against itself
                candidates = [p for i, p in enumerate(existing) if i != editing_idx]

            for cid, cname in course_names.items():
                if cname == selected_course_name:
                    if any(p['local_folder'] == pending_folder and p['course_id'] == cid for p in candidates):
                        st.warning(get_text('sync_duplicate_pair', lang))
                    break



        # Error container Relocated HERE (Below dropdown/warnings, Above buttons)
        error_container = st.empty()

        # (3) Confirm + Cancel — compact, side-by-side, cancel has red tint
        # Made columns narrower (10% each) to reduce button width significantly (per user request)
        col_add, col_cancel, _ = st.columns([1, 1, 8])
        with col_add:
            if st.button("✓ " + get_text('sync_confirm_add', lang), key="confirm_pair",
                         type="primary", use_container_width=True):
                if selected_course_name and selected_course_name != course_options[0]:
                    selected_course_id = None
                    for cid, cname in course_names.items():
                        if cname == selected_course_name:
                            selected_course_id = cid
                            break
                    if selected_course_id:
                        new_pair = {
                            'local_folder': pending_folder,
                            'course_id': selected_course_id,
                            'course_name': course_names[selected_course_id],
                            'last_synced': None,
                        }

                        # Check if we are updating or adding
                        edit_idx = st.session_state.get('editing_pair_idx')
                        if edit_idx is not None and 0 <= edit_idx < len(st.session_state['sync_pairs']):
                            # Update existing
                            old_pair = st.session_state['sync_pairs'][edit_idx]
                            if old_pair.get('course_id') == selected_course_id:
                                new_pair['last_synced'] = old_pair.get('last_synced')
                            
                            st.session_state['sync_pairs'][edit_idx] = new_pair
                        else:
                            # Append new
                            st.session_state['sync_pairs'].append(new_pair)

                        st.session_state['pending_sync_folder'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.session_state.pop('_prev_course_search', None)
                        _persist_current_pairs()
                        st.rerun()
                else:
                    # Custom error message with lower height (compact)
                    error_msg = get_text('sync_error_no_course', lang)
                    error_container.markdown(
                        f"""
                        <div style="
                            padding: 8px 12px;
                            margin-bottom: 10px;
                            background-color: rgba(255, 75, 75, 0.15);
                            color: #ff4b4b;
                            border: 1px solid rgba(255, 75, 75, 0.2);
                            border-radius: 4px;
                            font-size: 0.9em;
                            font-weight: 500;
                            display: flex;
                            align-items: center;
                            gap: 8px;
                        ">
                            ⚠️ {error_msg}
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
        with col_cancel:
            if st.button(get_text('cancel', lang), key="cancel_pair",
                         use_container_width=True):
                st.session_state['pending_sync_folder'] = None
                st.session_state.pop('editing_pair_idx', None)
                st.session_state.pop('_prev_course_search', None)
                st.rerun()


# ===================================================================
# STEP 4 — Analysis + Syncing + Completion
# ===================================================================

def render_sync_step4(lang: str):
    """Render the entire sync Step 4: analysis → review → sync → done."""
    sync_pairs = st.session_state.get('sync_pairs', [])
    if not sync_pairs:
        st.error(get_text('sync_no_pairs', lang))
        if st.button(get_text('back_btn', lang)):
            st.session_state['step'] = 1
            st.rerun()
        st.stop()

    status = st.session_state.get('download_status', '')

    if status == 'analyzing':
        _run_analysis(lang, sync_pairs)
    elif status == 'analyzed':
        _show_analysis_review(lang)
    elif status == 'pre_sync':
        st.session_state['download_status'] = 'syncing'
        st.rerun()
    elif status == 'syncing':
        _run_sync(lang)
    elif status == 'sync_cancelled':
        _show_sync_cancelled(lang)
    elif status == 'sync_complete':
        _show_sync_complete(lang)


# ---- Analysis phase ----

def _run_analysis(lang, sync_pairs):
    # Step wizard
    render_sync_wizard(st, 2, lang)

    st.markdown(
        f'<div class="step-header">{get_text("step4_header", lang)}</div>',
        unsafe_allow_html=True,
    )

    # Check if only syncing a single pair
    single_idx = st.session_state.get('sync_single_pair_idx')
    if single_idx is not None:
        sync_pairs = [sync_pairs[single_idx]]

    cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'], lang)
    all_results = []
    total_pairs = len(sync_pairs)

    # Clean progress display — no stale cards
    progress_container = st.empty()
    status_container = st.empty()

    for pair_num, pair in enumerate(sync_pairs, 1):
        # Folder-not-found guard
        if not Path(pair['local_folder']).exists():
            st.error(get_text('sync_folder_not_found', lang, path=pair['local_folder']))
            continue

        display_name = friendly_course_name(pair['course_name'])
        status_container.markdown(get_text('sync_analyzing_progress', lang, current=pair_num, total=total_pairs))
        render_progress_bar(progress_container, pair_num, total_pairs, lang, 
                            custom_text=get_text('sync_analyzing_progress', lang, current=pair_num, total=total_pairs))

        local_folder = pair['local_folder']
        course_id = pair['course_id']
        course_name = pair['course_name']

        try:
            course = cm.canvas.get_course(course_id)
        except Exception as e:
            st.error(f"Error accessing course {display_name}: {e}")
            continue

        sync_mgr = SyncManager(str(local_folder), course_id, course_name, lang)
        try:
            manifest = sync_mgr.load_manifest()
        except sqlite3.Error as e:
            st.error(get_text('sync_error_db_locked', lang, default=f"Database error for {display_name}: {e}. Please try again later."))
            continue
            
        canvas_files = cm.get_course_files_metadata(course)
        manifest = sync_mgr.heal_manifest(manifest)
        detected = sync_mgr.detect_structure()
        # Pass canvas manager to analyze_course for backend structure pre-calculation
        result = sync_mgr.analyze_course(canvas_files, manifest, cm=cm, download_mode=detected)

        # Do NOT save manifest here! Fixes Verify-Then-Commit state leakage if user hits Back.
        
        all_results.append({
            'pair': pair,
            'result': result,
            'manifest': manifest,
            'sync_manager': sync_mgr,
            'canvas_files': canvas_files,
            'course': course,
            'detected_structure': detected,
        })

    st.session_state['sync_analysis_results'] = all_results

    # Quick Sync mode — skip review and go straight to sync
    if st.session_state.get('sync_quick_mode'):
        # Auto-select all new, updated, and MISSING files
        sync_selections = []
        for idx, res_data in enumerate(all_results):
            result = res_data['result']
            
            # Set session state keys for UI consistency (if user goes back)
            for f in result.new_files:
                st.session_state[f'sync_new_{idx}_{f.id}'] = True
            for f, _ in result.updated_files:
                st.session_state[f'sync_upd_{idx}_{f.id}'] = True
            for mf in result.missing_files:
                st.session_state[f'sync_miss_{idx}_{mf.canvas_file_id}'] = True
            
            sync_selections.append({
                'pair_idx': idx,
                'res_data': res_data,
                'new': list(result.new_files),
                # Note: updated_files is list of tuples (canvas_file, local_file)
                'updates': [f for f, _ in result.updated_files],
                'redownload': list(result.missing_files),
                'ignore': [],
            })
            
        total_count = sum(len(s['new']) + len(s['updates']) + len(s['redownload']) for s in sync_selections)
        
        if total_count == 0:
            # If nothing to sync, just go to analyzed (review) screen to show "Nothing to sync" message
            st.session_state.pop('sync_quick_mode', None)
            st.session_state['download_status'] = 'analyzed'
        else:
            st.session_state['sync_selections'] = sync_selections
            # Skip 'confirming' step too? 
            # User said "then download progress bar comes up".
            # So we skip confirm and go to 'syncing'.
            st.session_state['download_status'] = 'syncing'
    else:
        st.session_state['download_status'] = 'analyzed'

    st.rerun()


# ---- Analysis review ----

def _show_analysis_review(lang):
    # Step wizard
    render_sync_wizard(st, 2, lang)

    st.markdown(
        f'<div class="step-header">{get_text("step4_header", lang)}</div>',
        unsafe_allow_html=True,
    )

    all_results = st.session_state.get('sync_analysis_results', [])
    if not all_results:
        st.error("Analysis failed. Please try again.")
        if st.button(get_text('back_btn', lang)):
            st.session_state['step'] = 1
            st.rerun()
        st.stop()

    total_new = sum(len(r['result'].new_files) for r in all_results)
    total_upd = sum(len(r['result'].updated_files) for r in all_results)
    total_miss = sum(len(r['result'].missing_files) for r in all_results)
    total_loc_del = sum(len(r['result'].locally_deleted_files) for r in all_results)
    total_del = sum(len(r['result'].deleted_on_canvas) for r in all_results)
    total_uptodate = sum(len(r['result'].uptodate_files) + getattr(r['result'], 'untracked_shortcuts', 0) for r in all_results)

    # Summary logic
    if total_new > 0 or total_upd > 0 or total_miss > 0 or total_del > 0 or total_loc_del > 0:
        st.markdown("<div style='margin-bottom: 10px; font-weight: 600; font-size: 1.1em;'>Analysis found:</div>", unsafe_allow_html=True)
        
        sum_cols = st.columns([3, 2])
        with sum_cols[0]:
            c1, c2, c3, c4, c5 = st.columns(5)
            
            # Determine labels safely based on lang
            lbl_new = get_text('new_files', lang) if 'new_files' in get_text.__code__.co_consts else ("Nye filer" if lang == 'da' else "New files")
            lbl_upd = "Opdateringer" if lang == 'da' else "Updates available"
            lbl_miss = "Manglende filer" if lang == 'da' else "Missing files"
            lbl_loc_del = "Slettet lokalt" if lang == 'da' else "Deleted locally"
            lbl_del = "Slettet på Canvas" if lang == 'da' else "Deleted on Canvas"

            card_css = "border-radius:12px; padding:18px 14px; position:relative; overflow:hidden; min-height: 95px;"
            icon_css = "position:absolute; top:14px; right:14px; background:rgba(0,0,0,0.15); border-radius:10px; width:42px; height:42px; display:flex; align-items:center; justify-content:center; font-size:1.5em;"
            num_css = "font-size:2.7em; font-weight:700; color:white; line-height:1;"
            lbl_css = "font-size:0.95em; color:rgba(255,255,255,1); font-weight:500; margin-top:8px; line-height:1.2; word-wrap:break-word;"

            with c1:
                st.markdown(f"""
                <div style="{card_css} background: linear-gradient(135deg, #4a90e2, #2980b9); box-shadow: 0 10px 20px -5px rgba(74, 144, 226, 0.35);">
                    <div style="{num_css}">{total_new}</div>
                    <div style="{lbl_css}">{lbl_new}</div>
                    <div style="{icon_css}">📄</div>
                </div>
                """, unsafe_allow_html=True)
            with c2:
                st.markdown(f"""
                <div style="{card_css} background: linear-gradient(135deg, #2ecc71, #27ae60); box-shadow: 0 10px 20px -5px rgba(46, 204, 113, 0.35);">
                    <div style="{num_css}">{total_upd}</div>
                    <div style="{lbl_css}">{lbl_upd}</div>
                    <div style="{icon_css}">🔄</div>
                </div>
                """, unsafe_allow_html=True)
            with c3:
                st.markdown(f"""
                <div style="{card_css} background: linear-gradient(135deg, #f1c40f, #e67e22); box-shadow: 0 10px 20px -5px rgba(241, 196, 15, 0.35);">
                    <div style="{num_css}">{total_miss}</div>
                    <div style="{lbl_css}">{lbl_miss}</div>
                    <div style="{icon_css}">⚠️</div>
                </div>
                """, unsafe_allow_html=True)
            with c4:
                st.markdown(f"""
                <div style="{card_css} background: linear-gradient(135deg, #9b59b6, #8e44ad); box-shadow: 0 10px 20px -5px rgba(155, 89, 182, 0.35);">
                    <div style="{num_css}">{total_loc_del}</div>
                    <div style="{lbl_css}">{lbl_loc_del}</div>
                    <div style="{icon_css}">✂️</div>
                </div>
                """, unsafe_allow_html=True)
            with c5:
                st.markdown(f"""
                <div style="{card_css} background: linear-gradient(135deg, #e74c3c, #c0392b); box-shadow: 0 10px 20px -5px rgba(231, 76, 60, 0.35);">
                    <div style="{num_css}">{total_del}</div>
                    <div style="{lbl_css}">{lbl_del}</div>
                    <div style="{icon_css}">🗑️</div>
                </div>
                """, unsafe_allow_html=True)
                
        st.markdown("<div style='margin-bottom: 25px;'></div>", unsafe_allow_html=True)

    # Nothing to sync
    if total_new == 0 and total_upd == 0 and total_miss == 0 and total_del == 0 and total_loc_del == 0:
        if total_uptodate:
            st.info(get_text('sync_files_uptodate_count', lang, count=total_uptodate,
                             file_word=pluralize(total_uptodate, 'file', lang)))
        st.success(get_text('nothing_to_sync', lang))
        if st.button(get_text('go_to_front_page', lang), type="primary"):
            _cleanup_sync_state()
            st.rerun()
        st.stop()


    # Feature 1: Advanced filtering & Global Selection
    all_extensions = set()
    from collections import defaultdict
    files_by_ext = defaultdict(list)
    
    for idx, res_data in enumerate(all_results):
        res = res_data['result']
        for f in res.new_files:
            ext = os.path.splitext(f.filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_new_{idx}_{f.id}')
        for f, _ in res.updated_files:
            ext = os.path.splitext(f.filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_upd_{idx}_{f.id}')
        for si in res.missing_files:
            ext = os.path.splitext(si.canvas_filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_miss_{idx}_{si.canvas_file_id}')
        for si in res.locally_deleted_files:
            ext = os.path.splitext(si.canvas_filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_locdel_{idx}_{si.canvas_file_id}')

    if all_extensions:
        all_exts_sorted = sorted(list(all_extensions))
        
        # 1. Compute current state bottom-up based on the actual individual file checkboxes
        ext_state = {}
        all_files_checked = True

        for ext in all_exts_sorted:
            keys = files_by_ext[ext]
            if not keys: continue
            
            # Default to True for files if they aren't in session_state yet
            checked_count = sum(1 for k in keys if st.session_state.get(k, True))
            is_fully_checked = (checked_count == len(keys))
            ext_state[ext] = is_fully_checked
            if not is_fully_checked:
                all_files_checked = False
                
        # 2. Sync computed state into session_state BEFORE widget render to match UI logic seamlessly
        st.session_state['sync_filter_all_exts'] = all_files_checked
        for ext in all_exts_sorted:
            st.session_state[f'sync_filter_ext_{ext}'] = ext_state[ext]
            
        def _apply_filter_to_files(exts, match_val):
            for ext in exts:
                for k in files_by_ext[ext]:
                    # Do not check a locally deleted file if it is currently set to ignored
                    if match_val and k.startswith('sync_locdel_'):
                        ignore_key = k.replace('sync_locdel_', 'ignore_')
                        if st.session_state.get(ignore_key, False):
                            continue
                    st.session_state[k] = match_val

        def toggle_all_exts():
            val = st.session_state.get('sync_filter_all_exts', True)
            _apply_filter_to_files(all_exts_sorted, val)
        
        def toggle_single_ext(ext_name):
            val = st.session_state.get(f'sync_filter_ext_{ext_name}', True)
            _apply_filter_to_files([ext_name], val)

        st.markdown(f'<div class="step-header" style="margin-bottom: 15px;">Select files to sync</div>', unsafe_allow_html=True)
        
        st.markdown("""
        <style>
        /* 1. Remove border and padding from the container */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-filetypes_flex_box),
        .st-key-filetypes_flex_box {
            border: none !important;
            box-shadow: none !important;
            padding: 0 !important;
            background: transparent !important;
        }
        
        /* 2. Target the horizontal block created by st.columns and force wrap */
        .st-key-filetypes_flex_box div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
            row-gap: 5px !important;
            column-gap: 15px !important;
        }
        
        /* 3. Shrink-wrap the columns */
        .st-key-filetypes_flex_box div[data-testid="stColumn"] {
            width: auto !important;
            flex: 0 0 auto !important;
            min-width: 0 !important;
        }
        
        /* 4. Remove inner gap of the column's vertical block so it's tight */
        .st-key-filetypes_flex_box div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] {
            gap: 0 !important;
        }
        
        /* 5. Fix checkbox label margins */
        .st-key-filetypes_flex_box label[data-baseweb="checkbox"] {
            margin-bottom: 0 !important;
            padding-right: 0 !important;
        }

        /* 6. Tighten the outer filter box container */
        .st-key-sync_filter_box_outer > div[data-testid="stVerticalBlock"] {
            padding-top: 5px !important;
            padding-bottom: 5px !important;
            gap: 0 !important;
        }

        /* 7. Aggressively pull elements up */
        .st-key-sync_filter_box_outer div[data-testid="stElementContainer"] {
            margin-top: -12px !important;
        }
        /* Add gap between label and the filetype checkboxes container */
        .st-key-sync_filter_box_outer div[data-testid="stElementContainer"]:has(.st-key-filetypes_flex_box) {
            margin-top: 5px !important;
        }
        /* Pull the toggle (first child) to the very top */
        .st-key-sync_filter_box_outer div[data-testid="stElementContainer"]:first-child {
            margin-top: -15px !important;
        }

        /* 8. Tighten separator and labels */
        .st-key-sync_filter_box_outer hr {
            margin-top: -8px !important;
            margin-bottom: 0 !important;
            border-color: rgba(255,255,255,0.1) !important;
        }
        .st-key-sync_filter_box_outer div[data-testid="stMarkdownContainer"] p {
            margin-bottom: 0 !important;
        }
        </style>
        """, unsafe_allow_html=True)

        col_main, _ = st.columns([3.5, 8.5])
        with col_main:
            with st.container(border=True, key="sync_filter_box_outer"):
                include_all = st.checkbox("Include ALL filetypes", key="sync_filter_all_exts", on_change=toggle_all_exts)
                
                if all_exts_sorted:
                    st.markdown("<hr />", unsafe_allow_html=True)
                    st.markdown("<div style='font-size: 0.95em; padding-bottom: 10px;'>Or select specific types:</div>", unsafe_allow_html=True)
                    
                    with st.container(border=True, key="filetypes_flex_box"):
                        safe_len = min(len(all_exts_sorted), 90)
                        cols = st.columns(safe_len)
                        for i, ext in enumerate(all_exts_sorted):
                            col_idx = i % safe_len
                            with cols[col_idx]:
                                st.checkbox(ext, key=f"sync_filter_ext_{ext}", disabled=include_all, on_change=toggle_single_ext, kwargs={'ext_name': ext})

            st.markdown("<div style='height: 5px;'></div>", unsafe_allow_html=True)
            
            # Global Select All / Deselect All
            col_sa, col_da = st.columns([1, 1])
            with col_sa:
                if st.button("Select All", type="primary", use_container_width=True):
                    for k in sum(files_by_ext.values(), []):
                        if k.startswith('sync_locdel_'):
                            ignore_key = k.replace('sync_locdel_', 'ignore_')
                            if st.session_state.get(ignore_key, False):
                                continue
                        st.session_state[k] = True
                    st.rerun()
            with col_da:
                if st.button("Deselect All", use_container_width=True):
                    for k in sum(files_by_ext.values(), []):
                        st.session_state[k] = False
                    st.rerun()

        st.markdown("---")

    # Per-folder results
    for idx, res_data in enumerate(all_results):
        pair = res_data['pair']
        result = res_data['result']

        display_name = friendly_course_name(pair['course_name'])
        folder_display = short_path(pair['local_folder'])

        has_changes = result.new_files or result.updated_files or result.missing_files or result.deleted_on_canvas or result.locally_deleted_files
        header_border = "#3498db" if has_changes else "#2ecc71"

        # Build a small up-to-date pill to show inside the card header
        uptodate_count = len(result.uptodate_files) + getattr(result, 'untracked_shortcuts', 0)
        uptodate_html = ""
        if uptodate_count:
            uptodate_label = get_text('sync_files_uptodate_count', lang, count=uptodate_count,
                                      file_word=pluralize(uptodate_count, 'file', lang))
            # Strip the ✅ emoji since the card already has context
            uptodate_label = uptodate_label.lstrip('✅ ')
            uptodate_html = f'<span style="color:#2ecc71;font-size:0.75em;margin-left:12px;">✅ {uptodate_label}</span>'

        st.markdown(f"""
        <div style="background-color:#2d2d2d;border:1px solid {header_border};border-radius:8px;padding:10px 14px;margin:12px 0 8px 0;">
            <div style="color:#fff;font-weight:600;font-size:1em;">
                📁 {display_name}{uptodate_html}
            </div>
            <div style="color:#666;font-size:0.75em;margin-top:2px;">
                {pair['local_folder']}
            </div>
        </div>
        """, unsafe_allow_html=True)

        if not has_changes:
            st.success(get_text('sync_no_changes_course', lang))
            continue



        # New files — always starts OPEN
        if result.new_files:
            with st.expander(f"🆕 {get_text('new_files', lang)} ({len(result.new_files)})", expanded=True):
                st.caption(get_text('new_files_desc', lang))
                for file in result.new_files:
                    ext = os.path.splitext(file.filename)[1].lower() or "Unknown"
                    icon = get_file_icon(file.filename)
                    size = format_file_size(file.size) if file.size else ""
                    key = f'sync_new_{idx}_{file.id}'
                    if key not in st.session_state:
                        st.session_state[key] = True
                    st.checkbox(f"{icon} {file.display_name or file.filename} ({size})", key=key)

        # Updated files — always starts OPEN
        if result.updated_files:
            with st.expander(f"🔄 {get_text('updated_files', lang)} ({len(result.updated_files)})", expanded=True):
                st.caption(get_text('updated_files_desc', lang))
                for canvas_file, sync_info in result.updated_files:
                    ext = os.path.splitext(canvas_file.filename)[1].lower() or "Unknown"
                    icon = get_file_icon(canvas_file.filename)
                    size = format_file_size(canvas_file.size) if canvas_file.size else ""
                    key = f'sync_upd_{idx}_{canvas_file.id}'
                    if key not in st.session_state:
                        st.session_state[key] = True
                    st.checkbox(f"{icon} {canvas_file.display_name or canvas_file.filename} ({size})", key=key)

        # Missing files — always starts OPEN
        if result.missing_files:
            with st.expander(f"📦 {get_text('missing_files', lang)} ({len(result.missing_files)})", expanded=True):
                st.caption(get_text('missing_files_desc', lang))
                for sync_info in result.missing_files:
                    ext = os.path.splitext(sync_info.canvas_filename)[1].lower() or "Unknown"
                    icon = get_file_icon(sync_info.canvas_filename)
                    col_chk, col_ign = st.columns([3, 1])
                    with col_chk:
                        key = f'sync_miss_{idx}_{sync_info.canvas_file_id}'
                        if key not in st.session_state:
                            st.session_state[key] = False
                        st.checkbox(f"{icon} {sync_info.canvas_filename}", key=key)
                    with col_ign:
                        ign_key = f'ignore_{idx}_{sync_info.canvas_file_id}'
                        st.checkbox(get_text('ignore_forever', lang), key=ign_key)

        # Locally Deleted Files (Student deleted locally to save space)
        if result.locally_deleted_files:
            with st.expander(f"✂️ Locally Deleted ({len(result.locally_deleted_files)})", expanded=True):
                st.markdown(
                    "<div style='background-color: rgba(184, 134, 11, 0.15); border: 1px solid rgba(184, 134, 11, 0.3); border-radius: 6px; padding: 12px; margin-bottom: 5px; color: #e6c229; font-size: 0.95em;'>"
                    "You deleted these files locally. Do you want to redownload them (adds them back to sync), or ignore them? (Ignored files won't appear as missing in future syncs; you can un-ignore them later in settings)."
                    "</div>",
                    unsafe_allow_html=True
                )
                
                st.markdown("""
                <style>
                /* Global styling for locally deleted cards */
                .locdel-card-active {
                    background-color: #262730 !important;
                }
                .locdel-card-ignored {
                    background-color: transparent !important;
                    opacity: 0.6;
                }
                
                /* Aggressively compact padding for the card container */
                div[data-testid="stVerticalBlock"]:has(> div > div > div > .locdel-card-marker),
                div[data-testid="stVerticalBlockBorderWrapper"]:has(.locdel-card-marker) > div > div[data-testid="stVerticalBlock"] {
                    padding: 0px 10px 0px 10px !important;
                    gap: 0px !important; /* Bring row 1 and row 2 closer together */
                }

                /* Reduce gap between individual file cards */
                /* Target the parent stVerticalBlock that contains the file cards directly to override Streamlit's 1rem gap */
                div[data-testid="stVerticalBlock"]:has(> div > div[data-testid="stVerticalBlockBorderWrapper"]:has(.locdel-card-marker)) {
                    gap: 0.3rem !important;
                }

                /* --- ROW 1: Checkbox + Filename --- */
                div[data-testid="stHorizontalBlock"]:has(.locdel-row1-marker) {
                    align-items: flex-start !important;
                    gap: 6px !important; /* Minimal gap between checkbox and text */
                    justify-content: flex-start !important;
                    margin-bottom: -6px !important; /* Reduce gap between text and buttons */
                    margin-top: -24px !important; /* Pull content up against card padding */
                }
                /* Shrink wrap columns so checkbox is tight to text */
                div[data-testid="stHorizontalBlock"]:has(.locdel-row1-marker) > div[data-testid="stColumn"] {
                    width: auto !important;
                    flex: 0 0 auto !important;
                    min-width: 0 !important;
                    display: flex !important;
                    align-items: flex-start !important;
                }
                div[data-testid="stHorizontalBlock"]:has(.locdel-row1-marker) p {
                    margin: 0 !important;
                    padding: 0 !important;
                }
                /* Text wrapping container fix for flex-start alignment */
                div[data-testid="stHorizontalBlock"]:has(.locdel-row1-marker) div[data-testid="stMarkdownContainer"] {
                    margin-top: 1px !important; /* Tiny adjustment to perfectly align text baseline with checkbox box */
                }
                /* Remove bottom/top margin inside row 1 containers */
                div[data-testid="stHorizontalBlock"]:has(.locdel-row1-marker) div[data-testid="stElementContainer"] {
                    margin-bottom: 0 !important;
                    margin-top: 0 !important;
                }
                div[data-testid="stHorizontalBlock"]:has(.locdel-row1-marker) div[data-testid="stVerticalBlock"] {
                    padding-bottom: 0 !important;
                    gap: 0 !important;
                }

                /* --- ROW 2: Buttons --- */
                div[data-testid="stHorizontalBlock"]:has(.locdel-row2-marker) {
                    align-items: flex-start !important;
                    gap: 6px !important;
                    justify-content: flex-start !important;
                    margin-top: -6px !important; /* Pull up next row */
                    margin-bottom: -6px !important; /* Harmonize bottom border */
                }
                /* Shrink wrap button columns */
                div[data-testid="stHorizontalBlock"]:has(.locdel-row2-marker) > div[data-testid="stColumn"] {
                    width: auto !important;
                    flex: 0 0 auto !important;
                    min-width: 0 !important;
                    display: flex !important;
                    align-items: flex-start !important;
                }
                /* Indent spacer for row 2 to perfectly match checkbox width (approx 24px) */
                div[data-testid="stHorizontalBlock"]:has(.locdel-row2-marker) > div[data-testid="stColumn"]:first-child {
                    width: 30px !important; /* Align buttons underneath the emoji icon */
                }
                /* Remove top margins inside row 2 containers to stay close to row 1 */
                div[data-testid="stHorizontalBlock"]:has(.locdel-row2-marker) div[data-testid="stElementContainer"] {
                    margin-top: 0 !important;
                }
                div[data-testid="stHorizontalBlock"]:has(.locdel-row2-marker) div[data-testid="stVerticalBlock"] {
                    padding-top: 0 !important;
                    gap: 0 !important;
                }
                div[data-testid="stHorizontalBlock"]:has(.locdel-row2-marker) button {
                    padding: 2px 14px !important;
                    min-height: 28px !important;
                    height: 28px !important;
                    font-size: 0.85em !important;
                    line-height: 1.2 !important;
                    margin: 0 !important;
                }
                </style>
                """, unsafe_allow_html=True)

                for sync_info in result.locally_deleted_files:
                    icon = get_file_icon(sync_info.canvas_filename)
                    key_redownload = f'sync_locdel_{idx}_{sync_info.canvas_file_id}'
                    key_ignore = f'ignore_{idx}_{sync_info.canvas_file_id}'
                    
                    if key_redownload not in st.session_state:
                        st.session_state[key_redownload] = False
                    if key_ignore not in st.session_state:
                        st.session_state[key_ignore] = False
                        
                    is_redownload = st.session_state[key_redownload]
                    is_ignore = st.session_state[key_ignore]
                    
                    card_class = "locdel-card-ignored" if is_ignore else "locdel-card-active"
                    
                    # Create the card container
                    with st.container(border=True, key=f"locdel_container_{idx}_{sync_info.canvas_file_id}"):
                        # Inject marker to style the parent container via CSS :has()
                        st.markdown(f"<span class='locdel-card-marker {card_class}' style='display:none;'></span>", unsafe_allow_html=True)
                        
                        # --- Row 1: Checkbox & Filename ---
                        # We use [1, 1] instead of percentages because CSS auto-width will override it and wrap the content.
                        col_chk, col_name = st.columns([1, 1], gap="small")
                        with col_chk:
                            st.markdown("<span class='locdel-row1-marker' style='display:none;'></span>", unsafe_allow_html=True)
                            def on_checkbox_change(kr=key_redownload, ki=key_ignore):
                                if st.session_state[kr]:
                                    st.session_state[ki] = False
                            st.checkbox(" ", key=key_redownload, disabled=is_ignore, on_change=on_checkbox_change, label_visibility="collapsed")
                        with col_name:
                            text_color = "#888" if is_ignore else "inherit"
                            text_decor = "text-decoration: line-through;" if is_ignore else ""
                            st.markdown(f"<div style='color:{text_color};{text_decor}; font-size:1em;'>{icon} {sync_info.canvas_filename}</div>", unsafe_allow_html=True)

                        # --- Row 2: Action Buttons ---
                        # First column acts as fixed-width spacer (set via CSS), others shrink wrap.
                        col_indent, col_btn1, col_btn2 = st.columns([1, 1, 1], gap="small")
                        with col_indent:
                            st.markdown("<span class='locdel-row2-marker' style='display:none;'></span>", unsafe_allow_html=True)
                        with col_btn1:
                            def toggle_redownload(kr=key_redownload, ki=key_ignore):
                                st.session_state[kr] = not st.session_state.get(kr, False)
                                if st.session_state[kr]:
                                    st.session_state[ki] = False
                            st.button(
                                "Redownload", 
                                key=f"btn_redl_{idx}_{sync_info.canvas_file_id}", 
                                type="primary" if is_redownload else "secondary", 
                                use_container_width=False,
                                on_click=toggle_redownload,
                                disabled=is_ignore
                            )
                        with col_btn2:
                            def toggle_ignore(kr=key_redownload, ki=key_ignore):
                                st.session_state[ki] = not st.session_state.get(ki, False)
                                if st.session_state[ki]:
                                    st.session_state[kr] = False
                            st.button(
                                "Ignore this file", 
                                key=f"btn_ign_{idx}_{sync_info.canvas_file_id}", 
                                type="primary" if is_ignore else "secondary", 
                                use_container_width=False,
                                on_click=toggle_ignore
                            )

        # Deleted files — always starts OPEN
        if result.deleted_on_canvas:
            lbl_del = "Slettet på Canvas (Ignoreret)" if lang == 'da' else "Deleted on Canvas (Ignored)"
            with st.expander(f"🗑️ {lbl_del} ({len(result.deleted_on_canvas)})", expanded=True):
                st.caption("These files were deleted by the teacher on Canvas. They are preserved locally for your safety.")
                for sync_info in result.deleted_on_canvas:
                    icon = get_file_icon(sync_info.canvas_filename)
                    st.markdown(f"<div style='color:#bbb; font-size:0.9em; padding:4px 0;'>{icon} &nbsp; <s>{sync_info.canvas_filename}</s></div>", unsafe_allow_html=True)


    # --- Action buttons (Sync left, Back right) ---
    st.markdown("---")
    col_sync, col_back, _ = st.columns([1.2, 1, 5])
    with col_sync:
        if st.button(get_text('sync_selected', lang), type="primary", use_container_width=True):
            # Collect selections
            sync_selections = []
            for idx, res_data in enumerate(all_results):
                result = res_data['result']
                selected_new = [
                    f for f in result.new_files
                    if st.session_state.get(f'sync_new_{idx}_{f.id}', True)
                ]
                selected_upd = [
                    f for f, _ in result.updated_files
                    if st.session_state.get(f'sync_upd_{idx}_{f.id}', True)
                ]
                selected_miss = [
                    si for si in result.missing_files
                    if st.session_state.get(f'sync_miss_{idx}_{si.canvas_file_id}', False)
                ]
                selected_locdel = [
                    si for si in result.locally_deleted_files
                    if st.session_state.get(f'sync_locdel_{idx}_{si.canvas_file_id}', False)
                ]
                # Combine both missing and locally deleted files that the user opted to redownload
                selected_miss.extend(selected_locdel)
                
                files_to_ignore = [si.canvas_file_id for si in result.missing_files
                                   if st.session_state.get(f'ignore_{idx}_{si.canvas_file_id}', False)]
                files_to_ignore.extend([si.canvas_file_id for si in result.locally_deleted_files
                                   if st.session_state.get(f'ignore_{idx}_{si.canvas_file_id}', False)])
                                   
                sync_selections.append({
                    'pair_idx': idx,
                    'res_data': res_data,
                    'new': selected_new,
                    'updates': selected_upd,
                    'redownload': selected_miss,
                    'ignore': files_to_ignore,
                })

            # Total count & size for confirmation
            total_count = sum(len(s['new']) + len(s['updates']) + len(s['redownload']) for s in sync_selections)
            # Compute total byte size — new and updated CanvasFileInfo have .size,
            # redownload items are SyncInfo; look up their size from canvas_files
            total_bytes = 0
            for s in sync_selections:
                total_bytes += sum(f.size for f in s['new'] if hasattr(f, 'size'))
                total_bytes += sum(f[0].size for f in s['updates'] if hasattr(f[0], 'size'))
                # redownload items are SyncInfo objects — look up size via canvas_files_map
                canvas_files_map = {f.id: f for f in s['res_data']['canvas_files']}
                for si in s['redownload']:
                    cf = canvas_files_map.get(si.canvas_file_id)
                    if cf:
                        total_bytes += getattr(cf, 'size', 0) or 0

            if total_count == 0:
                st.info(get_text('nothing_to_sync', lang))
                st.stop()

            # Disk space check (use first pair's folder)
            first_folder = sync_selections[0]['res_data']['pair']['local_folder']
            has_space, avail_mb, total_mb = check_disk_space(first_folder, required_bytes=total_bytes)
            if not has_space:
                st.error(get_text('sync_insufficient_space', lang))
                st.stop()

            folders_count = len(set(
                s['res_data']['pair']['local_folder'] for s in sync_selections
                if s['new'] or s['updates'] or s['redownload']
            ))
            
            # Extract destination folder from the first selection
            dest_folder = "Multiple folders"
            if folders_count == 1:
                # Find the single folder used
                for s in sync_selections:
                    if s['new'] or s['updates'] or s['redownload']:
                        dest_folder = short_path(s['res_data']['pair']['local_folder'])
                        break
            
            _show_sync_confirmation(lang, sync_selections, total_count, format_file_size(total_bytes), folders_count, avail_mb, total_mb, dest_folder, total_bytes)

    with col_back:
        if st.button(get_text('back_btn', lang), use_container_width=True):
            _cleanup_sync_state()
            st.rerun()


# ---- Confirmation dialog ----

@st.dialog("Confirm Sync")
def _show_sync_confirmation(lang, sync_selections, count, size, folders, avail_mb, total_mb, target_folder, total_bytes):
    # --- Data Collection for Dropdowns ---
    file_items = []
    folder_set = set()
    for s in sync_selections:
        # Get the friendly course name for the folder
        pair = s['res_data']['pair']
        course_display = friendly_course_name(pair.get('course_name', 'Unknown'))
        folder_set.add(course_display)
        
        # Helper to format filename friendly
        def get_friendly_name(name):
            # Replace + with space and unquote
            unquoted = urllib.parse.unquote(name).replace('+', ' ')
            return unquoted

        # Collect files from all categories with emojis and friendly names
        # Use structured spans for hanging indent
        for f in s['new']:
            icon = get_file_icon(f.filename)
            fname = get_friendly_name(f.display_name or f.filename)
            file_items.append(f"<li><span class='li-icon'>{icon}</span><span class='li-text'>{fname} <span style='color:rgba(255,255,255,0.4);'>({format_file_size(f.size)})</span></span></li>")
        for f, _ in s['updates']:
            icon = get_file_icon(f.filename)
            fname = get_friendly_name(f.display_name or f.filename)
            file_items.append(f"<li><span class='li-icon'>{icon}</span><span class='li-text'>{fname} <span style='color:rgba(255,255,255,0.4);'>({format_file_size(f.size)})</span></span></li>")
        for f in s['redownload']:
            icon = get_file_icon(f.canvas_filename)
            fname = get_friendly_name(f.canvas_filename)
            file_items.append(f"<li><span class='li-icon'>{icon}</span><span class='li-text'>{fname} <span style='color:rgba(255,255,255,0.4);'>({format_file_size(f.original_size)})</span></span></li>")
    
    # Tight HTML structure - NO whitespace
    file_list_html = f"<ul style='margin:0 !important;padding:0 !important;list-style-type:none !important;display:block !important;'>{''.join(sorted(file_items))}</ul>"
    sorted_folders = sorted(list(folder_set))
    folder_list_html = f"<ul style='margin:0 !important;padding:0 !important;list-style-type:none !important;display:block !important;'>{''.join(f'<li><span class=\'li-icon\'>📁</span><span class=\'li-text\'>{p}</span></li>' for p in sorted_folders)}</ul>"
    
    # --- UI Logic ---
    avail_bytes = avail_mb * 1024 * 1024
    
    # VISUAL PROGRESS CALCULATION
    # User feedback: if < 1% show 1%, else show linearly.
    real_ratio = total_bytes / avail_bytes if avail_bytes > 0 else 0
    real_pct = real_ratio * 100
    
    # Apply 1% floor for visibility, but keep it linear otherwise
    if total_bytes > 0:
        fill_percent = min(100, max(1, real_pct))
    else:
        fill_percent = 0
    
    # Conditional Destination Row
    if len(folder_set) > 1:
        dest_html = (
            f'<div class="stat-row-dropdown">'
            f'<details>'
            f'<summary>'
            f'<div class="stat-left">📁 <span class="stat-label">Destination:</span></div>'
            f'<div class="stat-value">{len(folder_set)} courses <span class="arrow-icon"></span></div>'
            f'</summary>'
            f'<div class="dropdown-list">{folder_list_html}</div>'
            f'</details>'
            f'</div>'
        )
    else:
        # Single folder - static row showing friendly name
        dest_html = (
            f'<div class="stat-row-static">'
            f'<div class="stat-left">📁 <span class="stat-label">Destination:</span></div>'
            f'<div class="stat-value">{sorted_folders[0]}</div>'
            f'</div>'
        )

    html_content = (
        f'<style>'
        f'div[data-testid="stModal"] {{'
        f'display: flex !important;'
        f'align-items: center !important;'
        f'justify-content: center !important;'
        f'background-color: rgba(0, 0, 0, 0.7) !important;'
        f'}}'
        f'div[data-testid="stModal"] > div[role="dialog"] {{'
        f'position: relative !important;'
        f'top: 0 !important;'
        f'left: 0 !important;'
        f'transform: none !important;'
        f'margin: auto !important;'
        f'max-width: 480px !important;'
        f'width: 90vw !important;'
        f'border-radius: 20px !important;'
        f'border: 1px solid rgba(255, 255, 255, 0.1) !important;'
        f'box-shadow: 0 25px 50px rgba(0, 0, 0, 0.8) !important;'
        f'background-color: #1a1c1e !important;'
        f'padding: 0 !important;'
        f'overflow: hidden !important;'
        f'}}'
        f'div[data-testid="stModal"] [data-testid="stVerticalBlock"] {{'
        f'padding: 25px !important;'
        f'gap: 0 !important;'
        f'}}'
        f'div[data-testid="stModal"] h2 {{'
        f'margin: 0 0 12px 0 !important;'
        f'font-size: 1.6rem !important;'
        f'font-weight: 700 !important;'
        f'color: #ffffff !important;'
        f'}}'
        f'.sync-subtitle {{'
        f'color: rgba(255, 255, 255, 0.6);'
        f'font-size: 0.85rem;'
        f'margin-bottom: 22px;'
        f'line-height: 1.4;'
        f'}}'
        f'.stats-card {{'
        f'background-color: #121416;'
        f'border: 1px solid rgba(255, 255, 255, 0.05);'
        f'border-radius: 14px;'
        f'padding: 18px;'
        f'margin-bottom: 20px;'
        f'}}'
        f'.stat-row-dropdown {{'
        f'margin-bottom: 12px;'
        f'}}'
        f'details summary {{'
        f'display: flex;'
        f'align-items: center;'
        f'justify-content: space-between;'
        f'cursor: pointer;'
        f'list-style: none;'
        f'color: rgba(255, 255, 255, 0.9);'
        f'font-size: 0.95rem;'
        f'outline: none;'
        f'transition: color 0.2s;'
        f'}}'
        f'details summary:hover {{ color: #ffffff; }}'
        f'details summary::-webkit-details-marker {{ display: none; }}'
        f'.stat-left {{'
        f'display: flex;'
        f'align-items: center;'
        f'gap: 10px;'
        f'}}'
        f'.stat-label {{'
        f'font-weight: 500;'
        f'}}'
        f'.stat-value {{'
        f'color: #ffffff;'
        f'font-weight: 600;'
        f'text-align: right;'
        f'font-size: 0.95rem;'
        f'display: flex;'
        f'align-items: center;'
        f'gap: 8px;'
        f'}}'
        f'.arrow-icon {{'
        f'font-size: 0.75rem;'
        f'color: rgba(255, 255, 255, 0.4);;'
        f'margin-left: 2px;'
        f'}}'
        f'.arrow-icon::before {{ content: "▸"; }}'
        f'details[open] summary .arrow-icon::before {{ content: "▾"; color: #ffffff; }}'
        f'.dropdown-list {{'
        f'background: rgba(0, 0, 0, 0.3);'
        f'border-radius: 8px;'
        f'padding: 6px 10px !important;'
        f'margin-top: 8px;'
        f'max-height: 150px;'
        f'overflow-y: auto;'
        f'font-size: 0.8rem;'
        f'color: rgba(255, 255, 255, 0.6);'
        f'border: 1px solid rgba(255, 255, 255, 0.03);'
        f'display: block;'
        f'}}'
        f'.stat-row-static {{'
        f'display: flex;'
        f'align-items: center;'
        f'justify-content: space-between;'
        f'margin-bottom: 12px;'
        f'}}'
        f'.progress-divider {{'
        f'border-top: 1px solid rgba(255, 255, 255, 0.08);'
        f'margin: 12px 0 15px 0;'
        f'}}'
        f'.custom-progress-bg {{'
        f'background-color: #2a2d31;'
        f'border-radius: 10px;'
        f'height: 8px;'
        f'width: 100%;'
        f'margin-bottom: 10px;'
        f'overflow: hidden;'
        f'}}'
        f'.custom-progress-fill {{'
        f'background-color: #3498db;'
        f'height: 100%;'
        f'border-radius: 10px;'
        f'transition: width 0.3s ease-out;'
        f'}}'
        f'.metrics-line {{'
        f'display: flex;'
        f'justify-content: space-between;'
        f'color: rgba(255, 255, 255, 0.45);'
        f'font-size: 0.75rem;'
        f'font-weight: 500;'
        f'}}'
        f'div[data-testid="stModal"] .stButton > button {{'
        f'border-radius: 8px !important;'
        f'height: 44px !important;'
        f'font-weight: 600 !important;'
        f'font-size: 0.95rem !important;'
        f'}}'
        f'button[data-testid="stBaseButton-secondary"] {{'
        f'background-color: #262730 !important;'
        f'border: 1px solid rgba(255, 255, 255, 0.1) !important;'
        f'color: #ffffff !important;'
        f'}}'
        f'/* Direct Left alignment and hanging indent for dropdown lists */'
        f'.dropdown-list ul li {{'
        f'margin: 0 0 4px 0 !important;'
        f'padding: 0 !important;'
        f'line-height: 1.3 !important;'
        f'text-align: left !important;'
        f'list-style: none !important;'
        f'display: flex !important;'
        f'align-items: flex-start !important;'
        f'min-height: 0 !important;'
        f'}}'
        f'.dropdown-list ul li:last-child {{ margin-bottom: 0 !important; }}'
        f'.li-icon {{'
        f'width: 24px !important;'
        f'flex-shrink: 0 !important;'
        f'display: inline-block !important;'
        f'}}'
        f'.li-text {{'
        f'flex: 1 !important;'
        f'word-break: break-word !important;'
        f'}}'
        f'.dropdown-list ul {{ margin: 0 !important; padding: 0 !important; }}'
        f'</style>'
        f'<div class="sync-subtitle">You are about to download <b>{count} files</b> ({size}) to <b>{folders} {"folder" if folders == 1 else "folders"}</b>.</div>'
        f'<div class="stats-card">'
        f'<div class="stat-row-dropdown">'
        f'<details>'
        f'<summary>'
        f'<div class="stat-left">📄 <span class="stat-label">Files:</span></div>'
        f'<div class="stat-value">{count} files <span class="arrow-icon"></span></div>'
        f'</summary>'
        f'<div class="dropdown-list">{file_list_html}</div>'
        f'</details>'
        f'</div>'
        f'<div class="stat-row-static">'
        f'<div class="stat-left">💾 <span class="stat-label">Total Size:</span></div>'
        f'<div class="stat-value">{size}</div>'
        f'</div>'
        f'{dest_html}'
        f'<div class="progress-divider"></div>'
        f'<div class="custom-progress-bg">'
        f'<div class="custom-progress-fill" style="width: {fill_percent}%;"></div>'
        f'</div>'
        f'<div class="metrics-line">'
        f'<div>{size} of {format_file_size(avail_bytes)}</div>'
        f'<div>Available Disk Space: {format_file_size(avail_bytes)}</div>'
        f'</div>'
        f'</div>'
    )
    st.markdown(html_content, unsafe_allow_html=True)

    col_yes, col_no = st.columns([1, 1], gap="medium")
    with col_yes:
        if st.button("Yes, Start Sync", type="primary", use_container_width=True):
            st.session_state['sync_selections'] = sync_selections
            st.session_state['download_status'] = 'pre_sync'
            st.rerun()
    with col_no:
        if st.button("No, Go back", use_container_width=True, key="cancel_sync_dialog_btn"):
            st.rerun()


# ---- Sync execution ----

def _run_sync(lang):
    # Step wizard
    render_sync_wizard(st, 3, lang)

    st.markdown(
        f'<div class="step-header">{get_text("sync_progress_header", lang)}</div>',
        unsafe_allow_html=True,
    )

    sync_selections = st.session_state.get('sync_selections', [])
    if not sync_selections:
        st.session_state['download_status'] = 'sync_complete'
        st.session_state['synced_count'] = 0
        st.rerun()

    status_text = st.empty()
    progress_container = st.empty()
    mb_counter = st.empty()
    log_area = st.empty()

    cancel_placeholder = st.empty()
    if cancel_placeholder.button(get_text('sync_cancel', lang), type="secondary", key="sync_cancel_btn"):
        cancel_placeholder.empty()
        st.session_state['sync_cancel_requested'] = True
        st.session_state['download_status'] = 'sync_cancelled'

    # --- Hide stale UI elements from previous step ---
    # During the blocking asyncio.run() download below, Streamlit cannot
    # clean up leftover ("stale") elements from the previous step's render.
    # This CSS rule hides any sibling elements that appear after this marker.
    st.markdown(
        """<style>
        [data-testid="stVerticalBlock"] > div:has(.sync-progress-end-marker) ~ div {
            display: none !important;
        }
        </style><div class="sync-progress-end-marker"></div>""",
        unsafe_allow_html=True,
    )

    synced_counter = [0, 0]  # [count, bytes]
    error_list = []

    async def download_sync_files_batch():
        cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'], lang)
        timeout = aiohttp.ClientTimeout(total=300)
        
        # Respect global concurrency limit from session state
        concurrent_limit = st.session_state.get('concurrent_downloads', 5)
        sem = asyncio.Semaphore(concurrent_limit)
        
        # Track synced files per pair for the results screen dropdowns
        # Key: pair_idx (int), Value: list of strings (filenames)
        synced_details = defaultdict(list)
        retry_selections = []
        
        async with aiohttp.ClientSession(
            headers={'Authorization': f'Bearer {cm.api_key}'}, timeout=timeout
        ) as session:
            total_files = sum(
                len(sel['new']) + len(sel['updates']) + len(sel['redownload'])
                for sel in sync_selections
            )
            total_mb = 0.0
            for sel in sync_selections:
                total_mb += sum(getattr(f, 'size', 0) or 0 for f in sel['new'])
                total_mb += sum(getattr(f, 'size', 0) or 0 for f in sel['updates'])
                cfmap = {f.id: f for f in sel['res_data']['canvas_files']}
                for si in sel['redownload']:
                    cf = cfmap.get(si.canvas_file_id)
                    if cf:
                        total_mb += getattr(cf, 'size', 0) or 0
            total_mb /= (1024 * 1024)

            current_file = 0
            downloaded_mb = 0.0
            total_pairs = len(sync_selections)

            render_progress_bar(progress_container, 0, total_files, lang)
            if total_mb > 0:
                mb_counter.markdown(get_text('sync_mb_progress', lang, current=0.0, total=total_mb))

            for pair_idx, sel in enumerate(sync_selections):
                if st.session_state.get('sync_cancel_requested', False):
                    break
                
                failed_files_for_pair = []

                res_data = sel['res_data']
                sync_mgr = res_data['sync_manager']
                manifest = res_data['manifest']
                canvas_files_map = {f.id: f for f in res_data['canvas_files']}
                pair = res_data['pair']

                display_name = friendly_course_name(pair['course_name'])
                status_text.text(get_text('sync_progress_course', lang,
                    current=pair_idx + 1, total=total_pairs, course=display_name))

                # Task 4: State Leakage Fix
                # We save the auto-healed manifest + any newly ignored files only ONCE per folder, 
                # exactly when the sync is executing (after user confirmation)
                if sel['ignore']:
                    manifest = sync_mgr.mark_files_ignored(manifest, sel['ignore'])
                sync_mgr.save_manifest(manifest)

                all_files = list(sel['new']) + list(sel['updates'])
                for sync_info in sel['redownload']:
                    if sync_info.canvas_file_id in canvas_files_map:
                        all_files.append(canvas_files_map[sync_info.canvas_file_id])
                    else:
                        # Fallback: Try to match by filename (handle URL encoding + vs space, case insensitivity)
                        # Files may be re-uploaded (new ID) but keep same name.
                        target_name = robust_filename_normalize(sync_info.canvas_filename)
                        found_file = None
                        
                        for f in res_data['canvas_files']:
                            # Compare robustly
                            if robust_filename_normalize(f.filename) == target_name:
                                found_file = f
                                break
                        
                        if found_file:
                            # Prevent duplicates: If file is already in 'new' list (new ID) but matched here via fallback
                            if found_file not in all_files:
                                all_files.append(found_file)
                        else:
                            # Log error if file is truly gone
                            error_list.append(get_text('sync_file_removed_from_canvas', lang,
                                                       filename=sync_info.canvas_filename))

                local_path = sync_mgr.local_path
                local_path.mkdir(parents=True, exist_ok=True)

                for file in all_files:
                    if st.session_state.get('sync_cancel_requested', False):
                        break

                    current_file += 1
                    display_file_name = file.display_name or file.filename

                    render_progress_bar(progress_container, current_file, total_files, lang)
                    log_area.text(get_text('sync_downloading_file', lang, filename=display_file_name))

                    try:
                        filename = cm._sanitize_filename(file.filename)
                        
                        # Task 4: Target Path Resolution
                        target_dir = local_path
                        calc_path = getattr(file, '_target_local_path', '')
                        
                        # Fallback to sync_info properties explicitly
                        if not calc_path:
                            for f, info in sel['res_data']['result'].updated_files:
                                if f == file:
                                    calc_path = info.target_local_path
                                    break
                            
                        if not calc_path:
                            for info in sel['redownload']:
                                if info.canvas_file_id == file.id or info.canvas_file_id == getattr(file, 'id', None):
                                    calc_path = info.target_local_path
                                    break
                                    
                        if calc_path:
                            calc_dir = Path(calc_path).parent
                            if str(calc_dir) != '.':
                                target_dir = local_path / calc_dir
                                
                        target_dir.mkdir(parents=True, exist_ok=True)
                        
                        filepath = target_dir / filename

                        is_update = file in sel['updates']
                        if is_update and filepath.exists():
                            base = filepath.stem
                            ext = filepath.suffix
                            filepath = local_path / f"{base}{get_text('new_version_suffix', lang)}{ext}"
                            filepath = cm._handle_conflict(filepath)
                        elif filepath.exists():
                            filepath = cm._handle_conflict(filepath)

                        # Refresh download URL from Canvas API (signed URLs expire quickly)
                        download_url = file.url
                        try:
                            course = res_data['course']
                            fresh_file = course.get_file(file.id)
                            fresh_url = getattr(fresh_file, 'url', '')
                            if fresh_url:
                                download_url = fresh_url
                        except Exception:
                            pass  # Keep original URL as fallback

                        if download_url:
                            async with sem:
                                async with session.get(download_url) as response:
                                    if response.status == 200:
                                        async with aiofiles.open(filepath, 'wb') as f:
                                            while True:
                                                chunk = await response.content.read(1024 * 1024)
                                                if not chunk:
                                                    break
                                                await f.write(chunk)
                                                chunk_size = len(chunk)
                                                downloaded_mb += chunk_size / (1024 * 1024)
                                                # Track actual byte count for summary
                                                synced_counter[1] += chunk_size
                                            
                                                if total_mb > 0:
                                                    mb_counter.markdown(get_text('sync_mb_progress', lang,
                                                        current=downloaded_mb, total=total_mb))

                                        rel_path = filepath.relative_to(local_path)
                                        sync_mgr.add_file_to_manifest(manifest, file, str(rel_path))
                                        synced_counter[0] += 1
                                        
                                        # Track success for UI dropdown
                                        synced_details[pair_idx].append(display_file_name)
                                    else:
                                        failed_files_for_pair.append(file)
                                        error_list.append(get_text('sync_error_file', lang,
                                            filename=display_file_name, error=f"HTTP {response.status}"))
                        else:
                            # Check for LTI/Media streams
                            ext_lower = filepath.suffix.lower()
                            media_exts = ['.mp4', '.mov', '.avi', '.mkv', '.mp3']
                            if ext_lower in media_exts:
                                err_msg = "LTI/Media Stream (Cannot directly download)"
                            else:
                                err_msg = "No download URL"
                            
                            failed_files_for_pair.append(file)
                            error_list.append(get_text('sync_error_file', lang,
                                filename=display_file_name, error=err_msg))

                    except Exception as e:
                        failed_files_for_pair.append(file)
                        error_list.append(get_text('sync_error_file', lang,
                            filename=display_file_name, error=str(e)))

                sync_mgr.save_manifest(manifest)
                
                # Check for updates and deletions to write log file
                updates = sel['updates']
                deletions = res_data['result'].deleted_on_canvas
                if updates or deletions:
                    log_file_path = local_path / "☁️ Canvas Updates & Deletions.txt"
                    try:
                        with open(log_file_path, "a", encoding="utf-8") as lf:
                            lf.write(f"\n--- Sync on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                            if updates:
                                lf.write("UPDATED FILES (New versions downloaded, check local folder for numbered copies):\n")
                                for f in updates:
                                    lf.write(f"  - {f.filename}\n")
                            if deletions:
                                lf.write("DELETED ON CANVAS (These were preserved locally but removed by teacher):\n")
                                for si in deletions:
                                    lf.write(f"  - {si.canvas_filename}\n")
                            lf.write("\n")
                    except Exception as e:
                        import logging
                        logging.warning(f"Failed to write updates log: {e}")
                
                if failed_files_for_pair:
                    retry_selections.append({
                        'pair_idx': sel['pair_idx'],
                        'res_data': sel['res_data'],
                        'new': failed_files_for_pair,
                        'updates': [],
                        'redownload': [],
                        'ignore': []
                    })
                
        return synced_details, retry_selections

    synced_details, retry_selections = asyncio.run(download_sync_files_batch())

    # --- Organize files into module folders (if requested) ---


    st.session_state['synced_count'] = synced_counter[0]
    st.session_state['synced_bytes'] = synced_counter[1]
    st.session_state['sync_errors'] = error_list
    # Store detailed synced files for the completion screen dropdowns
    # synced_details is a dict: { pair_idx: [ "filename1", "filename2", ... ] }
    st.session_state['synced_details'] = dict(synced_details)
    st.session_state['retry_selections'] = retry_selections

    # Update last_synced timestamps
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    pairs = st.session_state.get('sync_pairs', [])
    for sel in sync_selections:
        pair_idx = sel['pair_idx']
        if pair_idx < len(pairs):
            pairs[pair_idx]['last_synced'] = now_str
    st.session_state['sync_pairs'] = pairs
    _persist_current_pairs()

    # Record sync history
    if synced_counter[0] > 0:
        try:
            from ui_helpers import get_config_dir
            history_mgr = SyncHistoryManager(get_config_dir())
            
            # Extract names of courses that actually had files synced
            synced_course_names = []
            for sel in sync_selections:
                if sel['pair_idx'] in synced_details and len(synced_details[sel['pair_idx']]) > 0:
                    synced_course_names.append(sel['res_data']['pair']['course_name'])

            history_mgr.add_entry({
                'timestamp': now_str,
                'files_synced': synced_counter[0],
                'courses': len(sync_selections),
                'course_names': synced_course_names,
                'errors': len(error_list),
            })
        except Exception as e:
            logger.error(f"Failed to record sync history: {e}")

    if st.session_state.get('sync_cancel_requested', False):
        st.session_state['download_status'] = 'sync_cancelled'
        st.session_state['sync_cancelled_file_count'] = synced_counter[0]
    else:
        st.session_state['download_status'] = 'sync_complete'
    st.rerun()


# ---- Cancelled ----

def _show_sync_cancelled(lang):
    render_sync_wizard(st, 3, lang)

    st.warning(get_text('sync_cancelled', lang))
    cancelled_count = st.session_state.get('sync_cancelled_file_count', 0)
    total_files = sum(
        len(sel['new']) + len(sel['updates']) + len(sel['redownload'])
        for sel in st.session_state.get('sync_selections', [])
    )
    st.info(get_text('sync_cancelled_after', lang, current=cancelled_count, total=total_files,
                     file_word=pluralize(total_files, 'file', lang)))

    _show_sync_errors(lang)

    if st.button(get_text('go_back', lang)):
        _cleanup_sync_state()
        st.rerun()


# ---- Complete ----

def _show_sync_complete(lang):
    # Step wizard
    render_sync_wizard(st, 4, lang)

    synced_count = st.session_state.get('synced_count', 0)
    sync_errors = st.session_state.get('sync_errors', [])
    synced_details = st.session_state.get('synced_details', {})

    custom_text = None
    if sync_errors and synced_count == 0:
        # Full failure - progress bar will be red
        mode = 'complete_error'
    elif sync_errors:
        # Partial failure - progress bar will be yellow
        mode = 'complete_warning'
    else:
        mode = 'complete'
        custom_text = get_text('sync_complete_bar', lang)

    render_progress_bar(st, 1, 1, lang, mode=mode, custom_text=custom_text)

    # Summary card logic
    # We want to be very clear about what happened.
    # Scenarios:
    # 1. Full Failure: 0 synced, >0 errors -> RED Error, NO Success card.
    # 3. Success: >0 synced, 0 errors -> GREEN Success card.
    # 4. Nothing to sync (should be caught earlier, but just in case): Info.

    total_bytes = st.session_state.get('synced_bytes', 0)
    sync_selections = st.session_state.get('sync_selections', [])
    
    # Calculate breakdown of what was actually downloaded
    total_upd = sum(len(s.get('updates', [])) for s in sync_selections)
    # This might be slightly off if some updates failed, but close enough for summary unless we track per-file success type.
    # Let's rely on synced_count.
    # Heuristic: We don't know exactly which files failed (update vs new), so we'll just display totals if possible,
    # or simplify the message.
    
    file_word = pluralize(synced_count, 'file', lang)
    error_word = pluralize(len(sync_errors), 'error', lang)

    if synced_count == 0 and sync_errors:
        # Scenario 1: Full Failure
        st.error(get_text('sync_all_failed', lang))
        # No green card.
    
    elif synced_count > 0 and sync_errors:
        # Scenario 2: Partial Success
        # Yellow card
        success_title = get_text('sync_partial_title', lang, 
                                count=synced_count, 
                                file_word=file_word, 
                                error_count=len(sync_errors))
        summary_text = get_text('sync_partial_desc', lang, size=format_file_size(total_bytes))
        
        st.markdown(f"""
        <div style="background-color:#3a2a1a;border:1px solid #f1c40f;border-radius:8px;padding:12px 16px;margin:8px 0;">
            <div style="color:#f1c40f;font-weight:600;font-size:1.05em;">
                ⚠️ {success_title}
            </div>
            <div style="color:#ccc;font-size:0.85em;margin-top:4px;">
                {summary_text}
            </div>
        </div>
        """, unsafe_allow_html=True)
        # st.balloons() # Maybe no balloons for partial?

    elif synced_count > 0:
        # Scenario 3: Success
        # Green card
        success_title = get_text('sync_success_title', lang, count=synced_count, file_word=file_word)
        summary_text = f"{format_file_size(total_bytes)} downloaded."

        st.markdown(f"""
        <div style="background-color:#1a3a2a;border:1px solid #2ecc71;border-radius:8px;padding:12px 16px;margin:8px 0;">
            <div style="color:#2ecc71;font-weight:600;font-size:1.05em;">
                🎉 {success_title}
            </div>
            <div style="color:#aaa;font-size:0.85em;margin-top:4px;">
                {summary_text}
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.balloons()
    

    
    else:
        # synced_count == 0 and no errors? (Nothing to sync?)
        st.info("Nothing was synced.")

    retry_selections = st.session_state.get('retry_selections', [])

    _show_sync_errors(lang)

    if sync_errors and retry_selections:
        st.markdown("<div style='margin-top: -15px; margin-bottom: 25px;'></div>", unsafe_allow_html=True)
        col_retry, _ = st.columns([0.25, 0.75])
        with col_retry:
            if st.button("🔄 Retry Failed Downloads", type="secondary", use_container_width=True):
                st.session_state['sync_selections'] = retry_selections
                st.session_state['download_status'] = 'syncing'
                st.session_state['sync_errors'] = []
                st.session_state['sync_cancel_requested'] = False
                st.rerun()

    # Folders updated — card style with dropdown
    sync_pairs = st.session_state.get('sync_pairs', [])
    
    # Filter to show only pairs that actually had synced files (or we can show all attempted)
    # User said: "Folders updated should have a dropdown inside showing the files added"
    # We'll show all pairs that were part of the selection, but only list files if they exist.
    
    sync_selections = st.session_state.get('sync_selections', [])
    
    # Only show "Folders Updated" if we actually synced something
    has_synced_files = any(len(files) > 0 for files in synced_details.values())

    if sync_selections and has_synced_files:
        st.markdown("#### 📁 " + get_text('sync_folders_updated', lang))

        for sel in sync_selections:
            pair_idx = sel['pair_idx']
            if pair_idx >= len(sync_pairs):
                continue

            pair = sync_pairs[pair_idx]
            display_name = friendly_course_name(pair['course_name'])
            folder_display = short_path(pair['local_folder'])

            # Get synced files for this pair
            files_synced = synced_details.get(pair_idx, [])

            if not files_synced:
                continue

            # Wrap folder header + Open button + file list in a visual card.
            # Use a bordered container with CSS overrides to remove the nested
            # expander border and tighten spacing so the dropdown sits right
            # below the folder title.
            with st.container(border=True):
                # CSS: remove inner expander border & tighten horizontal row
                st.markdown(f"""<style>
                /* Remove border from expanders nested inside bordered containers */
                div[data-testid="stExpander"] {{
                    border: none !important;
                    box-shadow: none !important;
                    padding: 0 !important;
                    margin-top: 0 !important; /* Reset out the negative margin previously used */
                }}
                /* Tighten the parent container padding to reduce top dead space */
                div[data-testid="stVerticalBlock"]:has(span#folder_row_{pair_idx}) {{
                    padding-top: 5px !important;
                }}
                /* Tight horizontal column layouts for the folder display */
                div[data-testid="stHorizontalBlock"]:has(span#folder_row_{pair_idx}) {{
                    align-items: center !important;
                    gap: 15px !important; /* Increased gap between course name and button */
                    min-height: 0 !important;
                    margin-bottom: 0px !important; /* Reduced expander gap to 0px */
                }}
                div[data-testid="stHorizontalBlock"]:has(span#folder_row_{pair_idx}) div[data-testid="stColumn"] {{
                    width: auto !important;
                    flex: 0 0 auto !important;
                    min-width: 0 !important;
                    display: flex !important;
                    align-items: center !important;
                }}
                /* Fix negative margins that clip text and break flex alignment */
                div[data-testid="stHorizontalBlock"]:has(span#folder_row_{pair_idx}) div[data-testid="stMarkdownContainer"] {{
                    margin: 0 !important;
                }}
                div[data-testid="stHorizontalBlock"]:has(span#folder_row_{pair_idx}) div[data-testid="stMarkdown"] {{
                    display: flex !important;
                    align-items: center !important;
                    overflow: visible !important;
                }}
                div[data-testid="stHorizontalBlock"]:has(span#folder_row_{pair_idx}) div[data-testid="stElementContainer"] {{
                    margin: 0 !important;
                    overflow: visible !important;
                }}
                /* Kill paragraph margins & normalize line height to allow perfect alignment */
                div[data-testid="stHorizontalBlock"]:has(span#folder_row_{pair_idx}) p {{
                    margin: 0 !important;
                    line-height: 1.4 !important;
                }}
                /* Target the specific Open Folder button to adjust height/padding and vertical position */
                div[data-testid="stHorizontalBlock"]:has(span#folder_row_{pair_idx}) button {{
                    border: 1px solid rgba(255,255,255,0.3) !important;
                    padding: 4px 14px !important;
                    font-size: 0.85rem !important;
                    line-height: 1.4 !important;
                    min-height: 0 !important;
                    height: auto !important;
                    /* Translate is more reliable than margin inside a flex container */
                    transform: translateY(-2px) !important; 
                }}
                </style>""", unsafe_allow_html=True)

                c1, c2, c3 = st.columns([1, 1, 1], vertical_alignment="center", gap="small")
                with c1:
                    st.markdown(f'<span id="folder_row_{pair_idx}"></span>**📁 {folder_display}**', unsafe_allow_html=True)
                with c2:
                    if Path(pair['local_folder']).exists():
                        if st.button(get_text('sync_open_folder_btn', lang), key=f"open_complete_{pair_idx}"):
                            open_folder(pair['local_folder'])
                with c3:
                    st.empty()

                with st.expander(get_text('sync_see_synced_files', lang, count=len(files_synced))):
                    for fname in files_synced:
                        st.markdown(f"<div style='font-size:0.85em;color:#ccc;'>✅ {fname}</div>", unsafe_allow_html=True)
                    st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    if st.button("🏠 " + get_text('go_to_front_page', lang), type="primary", use_container_width=True):
        _cleanup_sync_state()
        st.rerun()


# ---- Shared helpers ----

def _show_sync_errors(lang):
    sync_errors = st.session_state.get('sync_errors', [])
    if sync_errors:
        # The summary card handles the warning/error banner.
        # Here we just show the details expander.
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        with st.expander("📋 " + get_text('view_error_details', lang), expanded=True):
            for err in sync_errors[:20]:
                st.markdown(f"❌ {err}")
            if len(sync_errors) > 20:
                st.caption(f"  ... and {len(sync_errors) - 20} more")


def _cleanup_sync_state():
    """Remove all transient sync keys from session state."""
    for key in [
        'download_status', 'sync_analysis_results', 'sync_selections',
        'synced_count', 'synced_bytes', 'sync_cancel_requested', 'sync_cancelled_file_count',
        'sync_errors', 'sync_quick_mode', 'sync_single_pair_idx',
        'sync_confirm_count', 'sync_confirm_size', 'sync_confirm_folders',
    ]:
        st.session_state.pop(key, None)

    # Also clean up any dynamic checkbox keys
    keys_to_remove = [k for k in st.session_state if k.startswith(('sync_new_', 'sync_upd_', 'sync_miss_', 'ignore_'))]
    for k in keys_to_remove:
        st.session_state.pop(k, None)

    st.session_state['step'] = 1
