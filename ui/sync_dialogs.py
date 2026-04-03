"""
ui.sync_dialogs — Sync history, filetype selector, ignored files, course settings.

Extracted from ``sync_ui.py`` (Phase 5).
Strict physical move — NO logic changes.

Contains:
  - ``render_sync_history()`` — sync history expander
  - ``render_filetype_selector()`` — filetype filter for review screen
  - ``ignored_files_dialog_inner()`` — ignored files management dialog
  - ``show_course_ignored_files()`` / ``show_course_ignored_files_inner()``
  - ``select_course_dialog_inner()`` — course selection dialog
  - ``render_pending_folder_ui()`` — pending folder pairing UI
"""

from __future__ import annotations

import json as _json
import os
import urllib.parse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import streamlit as st

import theme
from sync_manager import SyncManager, SyncHistoryManager, SavedGroupsManager, get_file_icon
from ui_helpers import (
    esc,
    friendly_course_name,
    get_config_dir,
    native_folder_picker,
    make_long_path,
)
from styles import inject_css

# Lazy imports to avoid circular dependency with sync_ui.py
def _select_sync_folder_lazy():
    """Open native folder picker and store result in pending_sync_folder."""
    from ui_helpers import native_folder_picker
    folder_path = native_folder_picker()
    if folder_path:
        import streamlit as st
        st.session_state['pending_sync_folder'] = folder_path

def _update_pair_by_signature_lazy(old_sig, new_pair):
    from sync.persistence import update_pair_by_signature
    update_pair_by_signature(old_sig, new_pair)

def _add_pair_lazy(pair):
    from sync.persistence import add_pair
    add_pair(pair)

def _remove_pairs_by_signature_lazy(sigs):
    from sync.persistence import remove_pairs_by_signature
    remove_pairs_by_signature(sigs)


def render_sync_history():
    """Render sync history in an expander at the bottom of step 1."""
    try:
        from ui_helpers import get_config_dir
        history_mgr = SyncHistoryManager(get_config_dir())
        history = history_mgr.load_history()
    except Exception:
        history = []

    if history:
        with st.expander('📜 Sync History', expanded=False):
            if not history:
                st.write('No sync history yet.')
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
                    <div style="color:{theme.TEXT_DIM};font-size:0.85em;">{time_display}</div>
                    <div style="color:#ddd;font-weight:600;font-size:0.95em;margin-top:2px;">
                        ✅ Synced {count} file{'s' if count != 1 else ''}
                    </div>
                    {courses_text}
                </div>
                """, unsafe_allow_html=True)


def render_filetype_selector(all_files, prefix, file_key_fn):
    """Bulk Selection Matrix — filetype unit checkboxes that act as remote controls.
    
    Each unit checkbox toggles ALL files of that extension on/off.
    Shows dynamic (selected/total) counters next to each extension.
    
    Args:
        all_files: List of (key, SyncFileInfo) tuples.
        prefix: Unique prefix for filetype unit session-state keys.
        file_key_fn: Function that takes a file and returns its session_state key.
    """
    # Build extension → file keys mapping
    ext_to_keys: dict[str, list[str]] = defaultdict(list)
    for fkey, f in all_files:
        ext = os.path.splitext(f.canvas_filename)[1].lower() or ".unknown"
        ext_to_keys[ext].append(fkey)

    if not ext_to_keys:
        return

    all_exts_sorted = sorted(ext_to_keys.keys())

    # CSS for compact flex-wrap pills layout
    st.markdown(f"""
    <style>
    .st-key-{prefix}_units div[data-testid="stHorizontalBlock"] {{
        flex-wrap: wrap !important;
        row-gap: 5px !important;
        column-gap: 15px !important;
    }}
    .st-key-{prefix}_units div[data-testid="stColumn"] {{
        width: auto !important;
        flex: 0 0 auto !important;
        min-width: 0 !important;
    }}
    .st-key-{prefix}_units div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] {{
        gap: 0 !important;
    }}
    .st-key-{prefix}_units label[data-baseweb="checkbox"] {{
        margin-bottom: 0 !important;
        padding-right: 0 !important;
    }}
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<p style="margin-bottom: -5px; font-size: 0.875rem; color: rgba(250,250,250,0.6);">Select by filetype:</p>', unsafe_allow_html=True)

    with st.container(key=f"{prefix}_units"):
        cols = st.columns(min(len(all_exts_sorted), 90))
        for i, ext in enumerate(all_exts_sorted):
            unit_key = f"{prefix}_unit_{ext}"
            file_keys_for_ext = ext_to_keys[ext]
            total = len(file_keys_for_ext)
            selected = sum(1 for k in file_keys_for_ext if st.session_state.get(k, False))

            # Force the session state to match reality BEFORE rendering the widget
            is_all_checked = (selected == total and total > 0)
            st.session_state[unit_key] = is_all_checked

            def _on_unit_change(ext=ext, unit_key=unit_key):
                """When user toggles a filetype unit, set all files of that type to match."""
                new_val = st.session_state[unit_key]
                for fk in ext_to_keys[ext]:
                    st.session_state[fk] = new_val

            with cols[i % len(cols)]:
                if 0 < selected < total:
                    label = f"{ext} :grey[({selected}/{total})]"
                else:
                    label = ext
                st.checkbox(
                    label,
                    key=unit_key,
                    on_change=_on_unit_change,
                )

    return all_exts_sorted, ext_to_keys


@st.dialog("🚫 All Ignored Files", width="large")
def ignored_files_dialog_inner(ignored_by_course, ):
    """Dialog to manage and restore files that were previously ignored.
    
    Architecture: Bulk Selection Matrix
    - All files always visible (no filtering/hiding)
    - Filetype unit checkboxes are remote controls that check/uncheck files
    - Default state: all files unchecked
    """

    # --- Collect all files across all courses ---
    all_items = []  # List of (session_key, cid, data, file)
    for cid, data in ignored_by_course.items():
        sm = data['sync_manager']
        for f in sm.get_ignored_files():
            key = f"ign_sel_{cid}_{f.canvas_file_id}"
            if key not in st.session_state:
                st.session_state[key] = False
            all_items.append((key, cid, data, f))

    all_file_keys = [item[0] for item in all_items]
    all_file_tuples = [(item[0], item[3]) for item in all_items]  # (key, file) for selector

    # --- 1. Filetype Selector (Bulk Selection Matrix) ---
    render_filetype_selector(all_file_tuples, "ign_all", lambda f: f)

    st.markdown("<div style='margin-top: -10px; margin-bottom: 15px; color: gray; font-size: 14px;'>Or</div>", unsafe_allow_html=True)

    # --- 2. Select All / Deselect All ---
    c1, c2, _ = st.columns([0.25, 0.25, 0.5])
    with c1:
        def _select_all():
            for k in all_file_keys:
                st.session_state[k] = True
            for ext in sorted(set(os.path.splitext(item[3].canvas_filename)[1].lower() or ".unknown" for item in all_items)):
                st.session_state[f"ign_all_unit_{ext}"] = True
        st.button("Select All", use_container_width=True, key="ign_sa", on_click=_select_all)
    with c2:
        def _deselect_all():
            for k in all_file_keys:
                st.session_state[k] = False
            for ext in sorted(set(os.path.splitext(item[3].canvas_filename)[1].lower() or ".unknown" for item in all_items)):
                st.session_state[f"ign_all_unit_{ext}"] = False
        st.button("Deselect All", use_container_width=True, key="ign_da", on_click=_deselect_all)

    # --- 3. File list — ALL files, grouped by course in expanders ---
    with st.container(height=500, border=True):
        grouped: dict = {}
        for key, cid, data, f in all_items:
            if cid not in grouped:
                grouped[cid] = {'data': data, 'items': []}
            grouped[cid]['items'].append((key, f))

        for cid, group in grouped.items():
            pair = group['data']['pair']
            friendly = friendly_course_name(pair['course_name'])
            items = group['items']
            count = len(items)
            file_word = 'file' if count == 1 else 'files'
            with st.expander(f"📁 {friendly} :grey[({count} {file_word})]", expanded=True):
                for key, f in items:
                    icon = get_file_icon(f.canvas_filename)
                    label = urllib.parse.unquote_plus(f.canvas_filename)
                    st.checkbox(f"{icon} {label}", key=key)

    # --- 4. Count + success message ---
    checked_count = sum(1 for k in all_file_keys if st.session_state.get(k, False))

    if st.session_state.get("ign_all_success"):
        st.success(st.session_state.pop("ign_all_success"))

    # --- 5. Dynamic button text ---
    if checked_count == 0:
        btn_text = "Remove files from ignored list"
    elif checked_count == 1:
        btn_text = "Remove 1 file from ignored list"
    else:
        btn_text = f"Remove {checked_count} files from ignored list"

    # --- 6. Action buttons ---
    st.markdown("""<style>
        button[data-testid="stBaseButton-primary"]:has(p:contains("Remove")) {
            background-color: {theme.ERROR_ALT} !important;
            border-color: #c0392b !important;
            color: white !important;
        }
        button[data-testid="stBaseButton-primary"]:has(p:contains("Remove")):hover {
            background-color: #c0392b !important;
        }
    </style>""", unsafe_allow_html=True)

    col_restore, col_cancel = st.columns([1, 1], vertical_alignment="bottom")
    with col_restore:
        def _on_restore_all():
            files_restored = 0
            for key, cid, data, f in all_items:
                if st.session_state.get(key):
                    sm = data['sync_manager']
                    sm.bulk_restore_files([f.canvas_file_id])
                    files_restored += 1
                    st.session_state.pop(key, None)
            if files_restored:
                file_word = 'file' if files_restored == 1 else 'files'
                st.session_state["ign_all_success"] = f"Successfully restored {files_restored} {file_word}! They will appear in your next Sync Review."

        st.button(btn_text, type="primary", disabled=(checked_count == 0),
                  use_container_width=True, on_click=_on_restore_all)

    with col_cancel:
        if st.button("Close", type="secondary", use_container_width=True, key="ign_close"):
            for k in all_file_keys:
                st.session_state.pop(k, None)
            st.rerun()


def show_course_ignored_files(course_name, course_id, course_data, ):
    """Dialog to manage ignored files for a specific course."""
    @st.dialog(f"🚫 Ignored Files: {esc(course_name)}", width="large")
    def _dialog():
        show_course_ignored_files_inner(course_name, course_id, course_data)
    _dialog()

def show_course_ignored_files_inner(course_name, course_id, course_data, ):
    """Per-course ignored files dialog — Bulk Selection Matrix architecture.
    
    Same paradigm as All Ignored Files, but flat list (no course expanders).
    """
    sm = course_data['sync_manager']
    files = sm.get_ignored_files()
    prefix = f"cign_{course_id}"

    # --- Initialize session state for every file (default: unchecked) ---
    all_keys = []
    all_file_tuples = []  # (key, file) for selector
    for f in files:
        key = f"{prefix}_{f.canvas_file_id}"
        if key not in st.session_state:
            st.session_state[key] = False
        all_keys.append(key)
        all_file_tuples.append((key, f))

    # --- 1. Filetype Selector (Bulk Selection Matrix) ---
    render_filetype_selector(all_file_tuples, prefix, lambda f: f)

    st.markdown("<div style='margin-top: -10px; margin-bottom: 15px; color: gray; font-size: 14px;'>Or</div>", unsafe_allow_html=True)

    # --- 2. Select All / Deselect All ---
    c1, c2, _ = st.columns([0.25, 0.25, 0.5])
    with c1:
        def _select_all():
            for k in all_keys:
                st.session_state[k] = True
            for ext in sorted(set(os.path.splitext(f.canvas_filename)[1].lower() or ".unknown" for f in files)):
                st.session_state[f"{prefix}_unit_{ext}"] = True
        st.button("Select All", use_container_width=True, key=f"{prefix}_sa", on_click=_select_all)
    with c2:
        def _deselect_all():
            for k in all_keys:
                st.session_state[k] = False
            for ext in sorted(set(os.path.splitext(f.canvas_filename)[1].lower() or ".unknown" for f in files)):
                st.session_state[f"{prefix}_unit_{ext}"] = False
        st.button("Deselect All", use_container_width=True, key=f"{prefix}_da", on_click=_deselect_all)

    # --- 3. File list — ALL files, flat list ---
    with st.container(height=500, border=True):
        for key, f in all_file_tuples:
            icon = get_file_icon(f.canvas_filename)
            label = urllib.parse.unquote_plus(f.canvas_filename)
            st.checkbox(f"{icon} {label}", key=key)

    # --- 4. Count + success message ---
    checked_count = sum(1 for k in all_keys if st.session_state.get(k, False))

    if st.session_state.get(f"{prefix}_success"):
        st.success(st.session_state.pop(f"{prefix}_success"))

    # --- 5. Dynamic button text ---
    if checked_count == 0:
        btn_text = "Remove files from ignored list"
    elif checked_count == 1:
        btn_text = "Remove 1 file from ignored list"
    else:
        btn_text = f"Remove {checked_count} files from ignored list"

    # --- 6. Action buttons ---
    st.markdown("""<style>
        button[data-testid="stBaseButton-primary"]:has(p:contains("Remove")) {
            background-color: {theme.ERROR_ALT} !important;
            border-color: #c0392b !important;
            color: white !important;
        }
        button[data-testid="stBaseButton-primary"]:has(p:contains("Remove")):hover {
            background-color: #c0392b !important;
        }
    </style>""", unsafe_allow_html=True)

    col_restore, col_cancel = st.columns([1, 1], vertical_alignment="bottom")
    with col_restore:
        def _on_restore_course():
            to_restore = [
                f.canvas_file_id for f in files
                if st.session_state.get(f"{prefix}_{f.canvas_file_id}")
            ]
            if to_restore:
                sm.bulk_restore_files(to_restore)
                file_word = 'file' if len(to_restore) == 1 else 'files'
                st.session_state[f"{prefix}_success"] = f"Successfully restored {len(to_restore)} {file_word}! They will appear in your next Sync Review."
                for fid in to_restore:
                    st.session_state.pop(f"{prefix}_{fid}", None)

        st.button(btn_text, type="primary", disabled=(checked_count == 0),
                  use_container_width=True, key=f"{prefix}_restore", on_click=_on_restore_course)

    with col_cancel:
        if st.button("Close", type="secondary", use_container_width=True, key=f"{prefix}_close"):
            for k in all_keys:
                st.session_state.pop(k, None)
            st.rerun()


@st.dialog("Select Course to sync", width="large")
def select_course_dialog_inner(courses, current_selected_id, ):
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
            ['Favorites Only', 'All Courses'],
            index=1 if not st.session_state.get('sync_filter_favorites', True) else 0,
            horizontal=True,
            label_visibility="collapsed",
            key="sync_dialog_filter_mode"
        )
    
    # Update preference
    st.session_state['sync_filter_favorites'] = (filter_mode == 'Favorites Only')
    
    # Filter by favorites
    visible_courses = courses
    if st.session_state['sync_filter_favorites']:
        visible_courses = [c for c in courses if getattr(c, 'is_favorite', False)]
        
    if not visible_courses:
        st.warning('No courses found.')
        if st.button("Close"):
             st.rerun()
        return

    # CBS Filters
    show_filters = st.toggle(f'Enable CBS Filters', key="sync_dialog_show_cbs")
    
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
             st.markdown(f"**{f'Filter Criteria'}**")
             c1, c2, c3 = st.columns(3)
             with c1:
                 sel_types = st.multiselect(f'Class Type', options=sorted(list(all_types)), key="sync_d_type")
             with c2:
                 sel_sem = st.multiselect(f'Semester', options=sorted(list(all_semesters)), key="sync_d_sem")
             with c3:
                 sel_years = st.multiselect(f'Year', options=sorted(list(all_years), reverse=True), key="sync_d_year")
        
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
                 st.info(f'No courses match the selected filters.')

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
                     f'<br><span style="color:{theme.TEXT_DIM}; font-size:0.85em;">{full_name_str}</span>'
                     f'</div>',
                     unsafe_allow_html=True
                 )
            # st.markdown("<div style='margin-bottom:5px'></div>", unsafe_allow_html=True) # Spacer

    # Use HTML hr to eradicate padding above the Confirm button separator
    st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)
    if st.button("Confirm Selection", key="sync_confirm_btn", type="primary", use_container_width=True):
        st.session_state["sync_selected_return_id"] = st.session_state["sync_dialog_selected_id"]
        st.rerun()


def render_pending_folder_ui(courses, course_names, course_options, ):
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
                f'{'Added Folder:'}</span>'
                f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">📁 {folder_name}</span>',
                unsafe_allow_html=True,
            )
        with col_change_btn:
            if st.button('Change Folder', key="btn_change_folder"):
                _select_sync_folder_lazy()
                st.rerun()
        with col_spacer:
            st.empty()

        # --- Course Selection (Pop-up Dialog) ---
        
        # Determine current display
        current_disp = 'Select Canvas Course' # Default "Select Canvas Course"
        
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
             btn_label = f'Change Course'
        else:
             btn_label = f'Select Course'
        
        # Two columns like folder row: [1, 1, 1] to keep it left-aligned
        # REVISED: [1, 1, 1] — relying on CSS flex auto-width to handle content size
        col_c_info, col_c_btn, col_c_spacer = st.columns([1, 1, 1], vertical_alignment="center", gap="small")
        
        with col_c_info:
            st.markdown(
                f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                f'{'Course: '}</span>'
                f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">{current_disp}</span>',
                unsafe_allow_html=True
            )
            
        with col_c_btn:
            if st.button(btn_label, key="btn_open_course_dialog"):
                st.session_state["sync_dialog_selected_id"] = selected_course_id
                select_course_dialog_inner(courses, selected_course_id)
        
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
                st.warning("⚠️ Warning: The folder name doesn't seem to match the selected course. Are you sure this is the correct folder for this course?")

            # Duplicate pair detection
            existing = st.session_state.get('sync_pairs', [])
            candidates = existing
            if editing_idx is not None:
                # Filter out the pairing being edited so we don't warn against itself
                candidates = [p for i, p in enumerate(existing) if i != editing_idx]

            for cid, cname in course_names.items():
                if cname == selected_course_name:
                    if any(p['local_folder'] == pending_folder and p['course_id'] == cid for p in candidates):
                        st.warning('⚠️ This folder is already paired with this course.')
                    break



        # Error container Relocated HERE (Below dropdown/warnings, Above buttons)
        error_container = st.empty()

        # (3) Confirm + Cancel — compact, side-by-side, cancel has red tint
        # Made columns narrower (10% each) to reduce button width significantly (per user request)
        col_add, col_cancel, _ = st.columns([1.5, 1, 7.5])
        with col_add:
            if st.button("✓ " + 'Confirm and Add', key="confirm_pair",
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
                            old_sig = {'course_id': old_pair.get('course_id'), 'local_folder': old_pair.get('local_folder')}
                            if old_pair.get('course_id') == selected_course_id:
                                new_pair['last_synced'] = old_pair.get('last_synced')
                            _update_pair_by_signature_lazy(old_sig, new_pair)
                        else:
                            # Append new
                            _add_pair_lazy(new_pair)

                        st.session_state['pending_sync_folder'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.session_state.pop('_prev_course_search', None)
                        st.rerun()
                else:
                    # Custom error message with lower height (compact)
                    error_msg = 'Please select a course.'
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
            if st.button('Cancel', key="cancel_pair",
                         use_container_width=True):
                st.session_state['pending_sync_folder'] = None
                st.session_state.pop('editing_pair_idx', None)
                st.session_state.pop('_prev_course_search', None)
                st.rerun()


# ===================================================================