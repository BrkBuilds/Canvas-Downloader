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

import base64
import logging
from pathlib import Path

import streamlit as st
from collections import defaultdict

import theme

from sync_manager import SyncManager, SavedGroupsManager
from ui_helpers import (
    open_folder,
    render_sync_wizard,
    friendly_course_name,
    short_path,
)

from core.state_registry import ensure_sync_state, cleanup_sync_state
from core.cancellation import cancel_sync
from sync.persistence import (
    load_persistent_pairs as _load_persistent_pairs_impl,
    add_pair as _add_pair_impl,
    add_pairs_batch as _add_pairs_batch_impl,
    remove_pairs_by_signature as _remove_pairs_by_signature_impl,
    update_pair_by_signature as _update_pair_by_signature_impl,
    update_last_synced_batch as _update_last_synced_batch_impl,
)
from sync.analysis import run_analysis as _run_analysis_impl
from sync.execution import run_sync as _run_sync_impl
from sync.completion import (
    show_sync_cancelled as _show_sync_cancelled_impl,
    show_sync_complete as _show_sync_complete_impl,
    show_sync_errors as _show_sync_errors_impl,
)
from ui_shared import error_log_dialog as _view_error_log_dialog_impl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cancel callback (fires INSTANTLY via on_click, before Streamlit re-enters main loop)
# ---------------------------------------------------------------------------

def cancel_process_callback():
    """Backward-compatible alias for cancel_sync (used in on_click= handlers)."""
    cancel_sync()

# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------

def _init_sync_session_state():
    """Backward-compatible alias for ensure_sync_state."""
    ensure_sync_state()


def _load_persistent_pairs():
    """Delegate to sync.persistence.load_persistent_pairs."""
    _load_persistent_pairs_impl()


def _add_pair(new_pair):
    """Delegate to sync.persistence.add_pair."""
    _add_pair_impl(new_pair)


def _add_pairs_batch(new_pairs_list):
    """Delegate to sync.persistence.add_pairs_batch."""
    _add_pairs_batch_impl(new_pairs_list)


def _remove_pairs_by_signature(signatures_to_remove):
    """Delegate to sync.persistence.remove_pairs_by_signature."""
    _remove_pairs_by_signature_impl(signatures_to_remove)


def _update_pair_by_signature(old_signature, new_pair_data):
    """Delegate to sync.persistence.update_pair_by_signature."""
    _update_pair_by_signature_impl(old_signature, new_pair_data)


def _update_last_synced_batch(updates_list):
    """Delegate to sync.persistence.update_last_synced_batch."""
    _update_last_synced_batch_impl(updates_list)


# ---------------------------------------------------------------------------
# Folder picker  (tkinter, reused from app.py)
# ---------------------------------------------------------------------------

def _select_sync_folder():
    """Open native folder picker and store result in pending_sync_folder."""
    from ui_helpers import native_folder_picker
    folder_path = native_folder_picker()
    if folder_path:
        st.session_state['pending_sync_folder'] = folder_path


# ===================================================================
# ===================================================================
# Save Group / Pair Dialog (Dual-Wrapper Pattern) — delegated to ui/hub_dialog.py
# ===================================================================

def _save_group_or_pair_inner(sync_pairs, is_pair=False, pair_data=None):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import save_group_or_pair_inner
    save_group_or_pair_inner(sync_pairs, is_pair, pair_data)


@st.dialog("\U0001F4BE Save as Group")
def _save_group_dialog(sync_pairs: list[dict]):
    """Delegate to ui.hub_dialog."""
    _save_group_or_pair_inner(sync_pairs, is_pair=False)


@st.dialog("\U0001F4BE Save as Pair")
def _save_pair_dialog(pair_data: dict):
    """Delegate to ui.hub_dialog."""
    _save_group_or_pair_inner([], is_pair=True, pair_data=pair_data)


def _hub_select_folder():
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import hub_select_folder
    hub_select_folder()


def _rescue_select_folder(pair_idx):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import rescue_select_folder
    rescue_select_folder(pair_idx)


def _change_hub_layer(target_layer, _pop_keys=None, **kwargs):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import change_hub_layer
    change_hub_layer(target_layer, _pop_keys, **kwargs)


def _delete_group_callback(mgr, group_id, group_name):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import delete_group_callback
    delete_group_callback(mgr, group_id, group_name)


def _remove_pair_from_group(mgr, group_id, pair_idx):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import remove_pair_from_group
    remove_pair_from_group(mgr, group_id, pair_idx)


def _hub_start_edit_pair(p_idx, pair):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import hub_start_edit_pair
    hub_start_edit_pair(p_idx, pair)


def _hub_cancel_edit():
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import hub_cancel_edit
    hub_cancel_edit()


def _hub_pick_folder_cb():
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import hub_pick_folder_cb
    hub_pick_folder_cb()


def _save_inline_edit_cb(mgr, gid, p_idx, new_folder, new_cid, new_cname):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import save_inline_edit_cb
    save_inline_edit_cb(mgr, gid, p_idx, new_folder, new_cid, new_cname)


def _save_inline_add_cb(mgr, gid, new_folder, new_cid, new_cname):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import save_inline_add_cb
    save_inline_add_cb(mgr, gid, new_folder, new_cid, new_cname)


def _confirm_course_selection_cb(cid, cname, course_names_map, courses_list):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import confirm_course_selection_cb
    confirm_course_selection_cb(cid, cname, course_names_map, courses_list)


@st.dialog("\U0001F4DA Saved Groups & Pairs", width="large")
def _saved_groups_hub_dialog(courses, course_names):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import saved_groups_hub_dialog_inner
    saved_groups_hub_dialog_inner(courses, course_names)


def _render_hub_config(pair):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import render_hub_config
    render_hub_config(pair)


def _reset_hub_state():
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import reset_hub_state
    reset_hub_state()


def _hub_cleanup():
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import hub_cleanup
    hub_cleanup()


def _inject_hub_global_css():
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import inject_hub_global_css
    inject_hub_global_css()


def render_sync_step1(fetch_courses_fn, main_placeholder=None):
    """Render Sync Step 1: folder pairing UI."""

    # Guard clause: double check that we are in step 1.
    # This prevents ghost UI elements if app.py logic somehow leaks.
    if st.session_state.get('step') != 1:
        return

    _init_sync_session_state()
    _load_persistent_pairs()

    # Inject all Hub Dialog + Main Button CSS unconditionally
    _inject_hub_global_css()

    # --- Pending toast consumer (fires after dialog rerun) ---
    if 'pending_toast' in st.session_state:
        st.toast(st.session_state.pop('pending_toast'))

    # Step wizard
    render_sync_wizard(st, 1)
    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

    # (7) Removed "Select Folders to Sync" header — wizard is enough context.

    # Fetch courses (needed by pair cards and the add-folder UI)
    courses = fetch_courses_fn(
        st.session_state['api_token'],
        st.session_state['api_url'],
        False
    )
    
    # Pre-fetch and flag favorites to fix "Favorites Only" modal filter
    try:
        fav_courses = fetch_courses_fn(
            st.session_state['api_token'],
            st.session_state['api_url'],
            True
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
    course_options = ["-- " + 'Select Canvas Course' + " --"] + sorted_course_names

    # --- (8) Bigger subheading + Hub button ---
    col_heading, col_hub = st.columns([0.7, 0.3], vertical_alignment="center")
    with col_heading:
        st.markdown(
            f'<h3 style="margin-top: -10px; margin-bottom: 0px; padding-bottom: 0px;">{'Canvas Courses to Sync'}</h3>',
            unsafe_allow_html=True,
        )
    with col_hub:
        if st.button("\U0001F4DA Saved Groups & Pairs", key="btn_hub_main",
                     use_container_width=True):
            _reset_hub_state()
            _saved_groups_hub_dialog(courses, course_names)

    sync_pairs = st.session_state.get('sync_pairs', [])
    pairs_to_remove = []

    # Pre-compute set of already-saved (course_id, local_folder) tuples for inline 💾 button
    from ui_helpers import get_config_dir as _get_config_dir
    _saved_mgr = SavedGroupsManager(_get_config_dir())
    _all_saved_groups = _saved_mgr.load_groups()
    _saved_pair_sigs = set()
    for _sg in _all_saved_groups:
        # ONLY look at standalone pairs, ignore pairs nested inside groups
        if not _sg.get('is_single_pair', False):
            continue
        for _sp in _sg.get('pairs', []):
            _saved_pair_sigs.add((_sp.get('course_id'), _sp.get('local_folder', '')))

    # --- (4) Pair action-button CSS: Remove fixed height, let flex align handle it ---
    st.markdown("""
    <style>
    div[data-testid="column"] { display: flex; flex-direction: column; justify-content: center; }

    /* Universal disabled button dimming */
    button[disabled] {
        opacity: 0.4 !important;
        filter: grayscale(100%) !important;
        cursor: not-allowed !important;
    }

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

    /* Enabled state (White text) */
    div[class*="st-key-ignored_btn_"] button:not([disabled]) {
        border: 1px dashed rgba(255, 255, 255, 0.4) !important;
        background-color: transparent !important;
        color: {theme.WHITE} !important;
        opacity: 1 !important;
    }
    div[class*="st-key-ignored_btn_"] button:not([disabled]) p,
    div[class*="st-key-ignored_btn_"] button:not([disabled]) span {
        color: {theme.WHITE} !important;
        opacity: 1 !important;
    }

    /* Disabled state (Grey text) */
    div[class*="st-key-ignored_btn_"] button[disabled] {
        border: 1px dashed rgba(255, 255, 255, 0.2) !important;
        background-color: transparent !important;
        color: rgba(255, 255, 255, 0.4) !important; /* Dimmed grey text */
        opacity: 0.7 !important;
    }
    div[class*="st-key-ignored_btn_"] button[disabled] p,
    div[class*="st-key-ignored_btn_"] button[disabled] span {
        color: rgba(255, 255, 255, 0.4) !important;
        opacity: 0.7 !important;
    }
    div[class*="st-key-ignored_btn_"] button:hover {
        border-color: rgba(255, 255, 255, 0.6) !important;
        color: {theme.WHITE} !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # --- Pre-compute ignored files per course (needed for per-course buttons AND global button) ---
    total_ignored = 0
    ignored_by_course = {}
    if sync_pairs:
        for pair in sync_pairs:
            local_folder = pair.get('local_folder')
            course_id = pair.get('course_id')
            if local_folder and Path(local_folder).exists():
                sm = SyncManager(local_folder, course_id, pair.get('course_name', ''))
                ignored = sm.get_ignored_files()
                if ignored:
                    ignored_by_course[pair['course_id']] = {
                        'pair': pair,
                        'files': ignored,
                        'sync_manager': sm
                    }
                    total_ignored += len(ignored)

    with st.container(border=True, key="sync_list_outline"):
        if sync_pairs:
            editing_idx = st.session_state.get('editing_pair_idx')

            for idx, pair in enumerate(sync_pairs):
                # --- If this pair is being edited, render the edit form inline ---
                if editing_idx is not None and editing_idx == idx and st.session_state.get('pending_sync_folder'):
                    _render_pending_folder_ui(courses, course_names, course_options)
                    # Removed explicit spacer to match list gap via CSS margin-bottom on container
                    continue

                # Use vertical_alignment="center" (Streamlit 1.32+) or rely on CSS above
                # Adjusted ratios: Card takes space, but buttons need room for text now
                col_card, col_open, col_edit, col_ignored, col_remove = st.columns([5, 1.5, 1.1, 1.5, 1.2], gap="small", vertical_alignment="center")

                with col_card:
                    folder_exists = Path(pair['local_folder']).exists()
                    last_synced = pair.get('last_synced')
                    ts_str = (
                        f'Last synced: {last_synced}' if last_synced
                        else 'Never synced'
                    )
                    
                    # Simplified card content
                    display_name = friendly_course_name(pair['course_name'])
                    folder_display = short_path(pair['local_folder'])

                    # Pre-compute save state for inline button
                    _pair_sig = (pair.get('course_id'), pair.get('local_folder', ''))
                    _pair_already_saved = _pair_sig in _saved_pair_sigs
                    _save_help = (
                        "This pair is saved \u2014 go to Saved Groups & Pairs to see, rename, or edit."
                        if _pair_already_saved
                        else "Save as Pair"
                    )

                    # Card container with 💾 button INSIDE
                    # Use a different key suffix for missing-folder cards so CSS can apply red border
                    _card_key = f"sync_pair_card_missing_{idx}" if not folder_exists else f"sync_pair_card_{idx}"
                    with st.container(border=True, key=_card_key):
                        # Title rendered first, naturally
                        st.markdown(f"**{'Course: '} {display_name}**")
                        # Save button rendered after — CSS absolute-positions it to top-right
                        if st.button("\U0001F4BE", key=f"save_pair_{idx}", disabled=_pair_already_saved,
                                     help=_save_help):
                            _save_pair_dialog(pair)
                        st.markdown(f"""<div style="font-size:0.85em;color:#ccc;margin-top:-5px;">\U0001F4C1 {folder_display}</div>
                            <div style="font-size:0.75em;color:{theme.TEXT_DIM};margin-top:2px;">\U0001F553 {ts_str}</div>""", unsafe_allow_html=True)

                # (4) Action buttons with text labels restored
                with col_open:
                    if folder_exists:
                        if st.button("📂 " + 'Open Folder',
                                     key=f"open_folder_{idx}", use_container_width=True):
                            open_folder(pair['local_folder'])

                with col_edit:
                    if st.button("✏️ " + 'Edit', 
                                 key=f"edit_pair_{idx}", use_container_width=True):
                        st.session_state['pending_sync_folder'] = pair['local_folder']
                        st.session_state['editing_pair_idx'] = idx
                        # Pre-populate selected course for editing
                        st.session_state['sync_selected_course_id'] = pair['course_id']
                        st.rerun()

                with col_ignored:
                    ignored_count = len(ignored_by_course.get(pair['course_id'], {}).get('files', []))
                    if st.button(f"🚫 Ignored Files ({ignored_count})", key=f"ignored_btn_{idx}",
                                 disabled=(ignored_count == 0), use_container_width=True):
                        course_data = ignored_by_course[pair['course_id']]
                        _show_course_ignored_files(
                            friendly_course_name(pair['course_name']),
                            pair['course_id'], course_data)

                with col_remove:
                    if st.button("🗑️ " + 'Remove', 
                                 key=f"remove_pair_{idx}", use_container_width=True):
                        pairs_to_remove.append(idx)
                
            if pairs_to_remove:
                signatures = [{'course_id': sync_pairs[i].get('course_id'), 'local_folder': sync_pairs[i].get('local_folder')} for i in pairs_to_remove]
                _remove_pairs_by_signature(signatures)
                st.rerun()
            if st.session_state.get('pending_sync_folder') and st.session_state.get('editing_pair_idx') is None:
                _render_pending_folder_ui(courses, course_names, course_options)
            else:
                # (9) "Add Course folder" + "Save List as Group" — full width
                col_add, col_save, _ = st.columns([2.25, 1.5, 6.25], gap="small", vertical_alignment="bottom") 
                with col_add:
                    # Clean, isolated CSS for "Add Course" using its Streamlit key
                    st.markdown("""<style>
                    div.st-key-btn_add_folder button {
                        border: 1px solid #4a7a9b !important;
                        background-color: #2a3a4a !important;
                        color: #cde !important;
                        margin-top: -50px !important;
                        position: relative;
                        z-index: 1;
                    }
                    div.st-key-btn_add_folder button:hover {
                         background-color: #3a4a5a !important;
                         border-color: #6a9abb !important;
                         color: {theme.WHITE} !important;
                    }
                    </style>""", unsafe_allow_html=True)
                    
                    if st.button("➕ " + 'Add Course folder to Sync', key="btn_add_folder", use_container_width=True):
                        _select_sync_folder()
                        st.session_state['sync_selected_course_id'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.rerun()

                with col_save:
                    # Disable if < 2 pairs or current list matches an already saved group
                    # Reusing the existing _saved_mgr instance from the top of the render loop
                    _save_disabled = len(sync_pairs) < 2 or _saved_mgr.matches_existing_group(sync_pairs)

                    # Clean, isolated CSS for "Save List" using its Streamlit key
                    st.markdown("""<style>
                    div.st-key-btn_save_group_main button {
                        background-color: rgba(95, 100, 200, 0.1) !important;
                        color: #e0e7ff !important;
                        border: 1px solid rgba(95, 100, 200, 0.75) !important;
                        margin-top: -50px !important;
                        position: relative;
                        z-index: 1;
                    }
                    div.st-key-btn_save_group_main button:hover {
                        background-color: rgba(95, 100, 200, 0.4) !important;
                        border-color: rgba(95, 100, 200, 1) !important;
                        color: {theme.WHITE} !important;
                        transition: all 0.2s ease-in-out;
                    }
                    div.st-key-btn_save_group_main button[disabled] {
                        background-color: rgba(95, 100, 200, 0.1) !important;
                        border: 1px solid rgba(95, 100, 200, 0.3) !important;
                        color: rgba(255, 255, 255, 0.3) !important;
                        cursor: not-allowed !important;
                    }
                    </style>""", unsafe_allow_html=True)

                    if st.button("💾 Save List as Group", key="btn_save_group_main", disabled=_save_disabled, use_container_width=True):
                        _save_group_dialog(sync_pairs)

        else:
            # EMPTY STATE Logic (if not sync_pairs)
            if st.session_state.get('pending_sync_folder') and st.session_state.get('editing_pair_idx') is None:
                _render_pending_folder_ui(courses, course_names, course_options)
            else:
                col_add, _ = st.columns([2.25, 7.75]) 
                with col_add:
                    st.markdown("""
                    <style>
                    /* Scoped to the button's own key — NO :has() to prevent
                       leaking into dialog portals via ancestor climbing */
                    div.st-key-btn_add_folder_empty button {
                        border: 1px solid #4a7a9b !important;
                        background-color: #2a3a4a !important;
                        color: #cde !important;
                        margin-top: -15px !important;
                    }
                    div.st-key-btn_add_folder_empty button:hover {
                         background-color: #3a4a5a !important;
                         border-color: #6a9abb !important;
                         color: {theme.WHITE} !important;
                    }
                    </style>""", unsafe_allow_html=True)
    
                    if st.button("➕ " + 'Add Course folder to Sync', key="btn_add_folder_empty", use_container_width=True):
                        _select_sync_folder()
                        st.session_state['sync_selected_course_id'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.rerun()
    
            
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
    # ignored_by_course already computed above the course row loop
    if total_ignored > 0:
        if st.button(f"🚫 Manage All Ignored Files ({total_ignored})", key="btn_manage_ignored", use_container_width=True):
            _ignored_files_dialog(ignored_by_course)

    if sync_pairs:
        invalid = [p for p in sync_pairs if not Path(p['local_folder']).exists()]
        if invalid:
            st.warning(f"❌ Folder not found: {invalid[0]['local_folder']}. It may have been deleted, renamed, or the drive is disconnected.")

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
        if st.button("🔍" + 'Analyze, Review & Sync', type="primary",
                     key="btn_analyze",
                     use_container_width=True,
                     disabled=not bool(sync_pairs)):
            # Nuclear reset of all cancel flags — stale flags from a previous download/sync
            # would break the analysis loop on the very first iteration, producing zero results.
            st.session_state['cancel_requested'] = False
            st.session_state['sync_cancelled'] = False
            st.session_state['sync_cancel_requested'] = False
            st.session_state['download_cancelled'] = False
            st.session_state['step'] = 4
            st.session_state['download_status'] = 'analyzing'
            st.session_state['analysis_pass'] = 1
            st.session_state.pop('sync_quick_mode', None)
            st.session_state.pop('qs_cancel_route', None)
            st.session_state.pop('sync_single_pair_idx', None)
            if main_placeholder:
                main_placeholder.empty()
            st.rerun()

    with col_or:
        # Removed manual margin-top hack, relying on vertical_alignment="center" and flex CSS above
        st.markdown(f"<div style='text-align:center; font-weight:bold; color:{theme.TEXT_DIM}; font-size:0.9em;'>OR</div>", unsafe_allow_html=True)

    with col_quick:
        # Removed help=... to prevent tooltip wrapper from breaking layout parity with the other button
        if st.button("⚡" + 'Quick Sync All',
                     key="btn_quick_sync",
                     type="primary",
                     use_container_width=True,
                     disabled=not bool(sync_pairs)):
            # Nuclear reset of all cancel flags — stale flags from a previous download/sync
            # would break the analysis loop on the very first iteration, producing zero results
            # and causing Quick Sync to silently fall back to the Review page.
            st.session_state['cancel_requested'] = False
            st.session_state['sync_cancelled'] = False
            st.session_state['sync_cancel_requested'] = False
            st.session_state['download_cancelled'] = False
            st.session_state['step'] = 4
            st.session_state['download_status'] = 'analyzing'
            st.session_state['sync_quick_mode'] = True
            st.session_state['qs_cancel_route'] = True
            st.session_state['analysis_pass'] = 1
            st.session_state.pop('sync_single_pair_idx', None)
            if main_placeholder:
                main_placeholder.empty()
            st.rerun()

    # --- (6) Tutorial + Sync History — grouped at bottom below separator ---
    st.markdown("---")
    with st.expander('📖 How Smart Sync Works', expanded=False):
        st.markdown("**Smart Sync keeps your local folders up-to-date without overwriting your work.**\n\n1. **Add a Folder**: Select an existing course folder on your computer and pair it with the corresponding Canvas course.\n2. **Analyze**: We compare your local files with Canvas.\n3. **Review**: You'll see exactly what changed:\n   - 🆕 **New Files**: Downloaded to your folder.\n   - 🔄 **Updated Files**: Saved as a copy (e.g., `file_NewVersion.pdf`) so your notes aren't overwritten.\n   - 📦 **Missing Files**: Re-download files you accidentally deleted, or ignore them forever.\n   - 🗑️ **Deleted on Canvas**: Files removed by the teacher are preserved safely on your computer.\n\n*Tip: Use **⚡ Quick Sync All** to skip the review and instantly download all new and updated files across all your courses!*")
    _render_sync_history()


def _render_sync_history():
    """Delegate to ui.sync_dialogs."""
    from ui.sync_dialogs import render_sync_history
    render_sync_history()


def _render_filetype_selector(all_files, prefix, file_key_fn):
    """Delegate to ui.sync_dialogs."""
    from ui.sync_dialogs import render_filetype_selector
    return render_filetype_selector(all_files, prefix, file_key_fn)


@st.dialog("Ignored Files", width="large")
def _ignored_files_dialog(ignored_by_course):
    """Delegate to ui.sync_dialogs."""
    from ui.sync_dialogs import ignored_files_dialog_inner
    ignored_files_dialog_inner(ignored_by_course)


def _show_course_ignored_files(course_name, course_id, course_data):
    """Delegate to ui.sync_dialogs."""
    from ui.sync_dialogs import show_course_ignored_files
    show_course_ignored_files(course_name, course_id, course_data)


def _show_course_ignored_files_inner(course_name, course_id, course_data):
    """Delegate to ui.sync_dialogs."""
    from ui.sync_dialogs import show_course_ignored_files_inner
    show_course_ignored_files_inner(course_name, course_id, course_data)


@st.dialog("Select Course", width="large")
def select_course_dialog(courses, current_selected_id):
    """Delegate to ui.sync_dialogs."""
    from ui.sync_dialogs import select_course_dialog_inner
    select_course_dialog_inner(courses, current_selected_id)


def _render_pending_folder_ui(courses, course_names, course_options):
    """Delegate to ui.sync_dialogs."""
    from ui.sync_dialogs import render_pending_folder_ui
    render_pending_folder_ui(courses, course_names, course_options)


# STEP 4 — Analysis + Syncing + Completion
# ===================================================================

def render_sync_step4( main_placeholder=None):
    """Render the entire sync Step 4: analysis → review → sync → done."""
    from styles import inject_css
    from ui.sync_review import inject_dynamic_sync_review_css
    
    inject_css('sync_review.css')
    inject_dynamic_sync_review_css()

    sync_pairs = st.session_state.get('sync_pairs', [])
    if not sync_pairs:
        st.error('No folders added yet. Click "Add Course folder" to get started.')
        if st.button('Back'):
            st.session_state['step'] = 1
            st.rerun()
        st.stop()

    status = st.session_state.get('download_status', '')

    if status == 'analyzing':
        current_pass = st.session_state.get('analysis_pass', 1)
        
        if current_pass == 1:
            # 1. ALWAYS DRAW THE BASE UI FIRST
            st.markdown(f"""
            <div style="background-color: {theme.BG_DARK}; padding: 20px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-top: 20px; margin-bottom: 20px;">
                <h4 style="color: {theme.TEXT_PRIMARY}; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                <p style="color: {theme.TEXT_SECONDARY}; font-size: 0.9rem;">Please wait a moment while Canvas is queried.</p>
                <div style="background-color: {theme.BG_CARD}; border-radius: 4px; width: 100%; height: 8px; overflow: hidden;">
                    <div style="background-color: {theme.ACCENT_BLUE}; width: 5%; height: 100%;"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # The target button
            if st.button("START_PASS_2_NOW", key="hidden_pass2_trigger"):
                st.session_state['analysis_pass'] = 2
                st.rerun()
                
            # JS Auto-hider and clicker
            import streamlit.components.v1 as components
            components.html("""
            <script>
            var doc = window.parent.document;
            var buttons = Array.from(doc.querySelectorAll('button'));
            var target = buttons.find(b => b.innerText.includes('START_PASS_2_NOW'));
            if(target) {
                // Find Streamlit's outer button wrapper and hide it instantly
                var wrapper = target.closest('div[data-testid="stButton"]');
                if(wrapper) { wrapper.style.display = 'none'; }
                
                // Click after a brief paint delay
                setTimeout(() => target.click(), 100);
            }
            </script>
            """, height=0)
        else:
            # Pass 2: The browser has successfully painted the clean UI. 
            # Safe to lock the main thread with heavy synchronous work.
            _run_analysis(sync_pairs, main_placeholder)
            
            # Optional: cleanup the flag when done
            if 'analysis_pass' in st.session_state:
                del st.session_state['analysis_pass']
                
            # CRITICAL FIX: Force rerun to transition to 'analyzed' or 'pre_sync'
            st.rerun()
    elif status == 'analyzed':
        _show_analysis_review()
    elif status == 'pre_sync':
        st.markdown("<div style='text-align:center; padding: 40px;'><h3 style='color:#3498db;'>Initializing sync engine...</h3><p>Please wait a moment.</p></div>", unsafe_allow_html=True)
        # We must let this render loop FINISH completely so the frontend can tear down the `st.dialog` DOM elements.
        # Otherwise, if we immediately string together long-running tasks or `st.rerun()`, the Streamlit backend
        # never yields to the WebSocket, and the modal gets permanently stuck on screen visually over the progress bars.
        # We inject a tiny JS script that waits 100ms for React to unmount the modal, then clicks a hidden button to start the actual sync loop.
        import streamlit.components.v1 as components
        components.html("""
        <script>
        setTimeout(function() {
            var doc = window.parent.document;
            var buttons = Array.from(doc.querySelectorAll('button'));
            var target = buttons.find(b => b.innerText.includes('START_SYNC_ROUTINE_NOW'));
            if(target) {
                target.click();
            }
        }, 200);
        </script>
        """, height=0)
        
        # Hidden button to catch the JS click
        st.markdown("<div style='display:none;'>", unsafe_allow_html=True)
        if st.button("START_SYNC_ROUTINE_NOW", key="hidden_trigger_sync"):
            st.session_state['download_status'] = 'syncing'
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    elif status == 'syncing':
        _run_sync()
    elif status == 'sync_cancelled':
        _show_sync_cancelled()
    elif status == 'sync_complete':
        _show_sync_complete()


# ---- Analysis phase ----

def _run_analysis(sync_pairs, main_placeholder=None):
    """Delegate to sync.analysis.run_analysis."""
    _run_analysis_impl(sync_pairs, main_placeholder)


# ---- Analysis review ----

def _show_analysis_review():
    """Delegate to ui.sync_review."""
    from ui.sync_review import show_analysis_review
    show_analysis_review(_show_sync_confirmation)


# ---- Confirmation dialog ----

@st.dialog("Confirm Sync")
def _show_sync_confirmation(sync_selections, count, size, folders, avail_mb, total_mb, target_folder, total_bytes):
    """Delegate to ui.sync_confirmation."""
    from ui.sync_confirmation import show_sync_confirmation_inner
    show_sync_confirmation_inner(sync_selections, count, size, folders, avail_mb, total_mb, target_folder, total_bytes)


# ---- Sync execution ----

def _run_sync():
    """Delegate to sync.execution.run_sync."""
    _run_sync_impl()


# ---- Cancelled ----

def _show_sync_cancelled():
    """Delegate to sync.completion.show_sync_cancelled."""
    _show_sync_cancelled_impl()


# ---- Complete ----

def _show_sync_complete():
    """Delegate to sync.completion.show_sync_complete."""
    _show_sync_complete_impl()


# ---- Shared helpers ----

def _view_error_log_dialog(log_paths):
    """Delegate to sync.completion.view_error_log_dialog."""
    _view_error_log_dialog_impl(log_paths)

def _show_sync_errors():
    """Delegate to sync.completion.show_sync_errors."""
    _show_sync_errors_impl()


def _cleanup_sync_state():
    """Backward-compatible alias for cleanup_sync_state."""
    cleanup_sync_state()
