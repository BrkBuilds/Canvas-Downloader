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
from urllib.parse import unquote_plus
import urllib.parse

import streamlit as st
import aiohttp
from collections import defaultdict
import sqlite3
import aiofiles


from translations import get_text
from canvas_logic import CanvasManager
from sync_manager import SyncManager, SyncHistoryManager, SavedGroupsManager, get_file_icon, format_file_size
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
# Cancel callback (fires INSTANTLY via on_click, before Streamlit re-enters main loop)
# ---------------------------------------------------------------------------

def cancel_process_callback():
    """Instant on_click callback — sets the cancel flag before the next loop iteration."""
    st.session_state['sync_cancelled'] = True
    st.session_state['sync_cancel_requested'] = True

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
        'sync_cancelled': False,
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
# Save Group / Pair Dialog (Dual-Wrapper Pattern)
# ===================================================================

def _save_group_or_pair_inner(sync_pairs: list[dict], is_pair: bool = False, pair_data: dict = None):
    """Shared inner logic for the Save Group/Pair dialog."""
    if is_pair:
        desc_text = (
            'Save your selected course/folder pair, to store it, '
            'enabling quick-adding to the sync list.'
        )
        input_label = "Give your pair a name:"
        input_placeholder = "e.g., Programming (for NotebookLM)"
        entity = "Pair"
    else:
        desc_text = (
            'Save your current list of course/folder pairs as a group so you can '
            'quickly switch between semesters.'
        )
        input_label = "Give your group a name:"
        input_placeholder = "e.g., 1st Semester"
        entity = "Group"

    st.markdown(
        f'<p style="color:#aaa; font-size:0.9rem; margin-bottom:10px;">'
        f'{desc_text}</p>',
        unsafe_allow_html=True,
    )
    item_name = st.text_input(
        input_label,
        placeholder=input_placeholder,
        key="save_group_name_input",
    )

    # Dialog button CSS now lives in _inject_hub_global_css() for bulletproof rendering.

    # Action buttons — Create left, Cancel right
    col_create, col_cancel = st.columns([1, 1], vertical_alignment="bottom")
    with col_create:
        create_disabled = not item_name or not item_name.strip()
        if st.button("Create", type="primary", use_container_width=True,
                     key="save_group_create", disabled=create_disabled):
            from ui_helpers import get_config_dir
            mgr = SavedGroupsManager(get_config_dir())
            if is_pair and pair_data:
                mgr.save_group(item_name.strip(), [pair_data], is_single_pair=True)
            else:
                mgr.save_group(item_name.strip(), sync_pairs)
            st.session_state['pending_toast'] = f"\u2705 {entity} '{item_name.strip()}' saved successfully!"
            st.rerun()
    with col_cancel:
        if st.button("Cancel", type="secondary", use_container_width=True, key="cancel_save_group"):
            st.rerun()


@st.dialog("\U0001F4BE Save as Group")
def _save_group_dialog(sync_pairs: list[dict]):
    """Dialog to save the current sync pairs as a reusable group."""
    _save_group_or_pair_inner(sync_pairs, is_pair=False)


@st.dialog("\U0001F4BE Save as Pair")
def _save_pair_dialog(pair_data: dict):
    """Dialog to save a single course/folder pair."""
    _save_group_or_pair_inner([], is_pair=True, pair_data=pair_data)



# ===================================================================
# Saved Groups Hub Dialog (Phase 2)
# ===================================================================

def _hub_select_folder():
    """Open native folder picker for the Hub dialog (isolated state)."""
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
        st.session_state['hub_temp_folder'] = folder_path


def _rescue_select_folder(pair_idx: int):
    """Open native folder picker for rescue mode (isolated per-pair state)."""
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
        rescue_paths = st.session_state.get('rescue_paths', {})
        rescue_paths[pair_idx] = folder_path
        st.session_state['rescue_paths'] = rescue_paths


def _change_hub_layer(target_layer, _pop_keys=None, **kwargs):
    """Callback to instantly change dialog layers and pass variables before render."""
    st.session_state['hub_layer'] = target_layer
    for k, v in kwargs.items():
        st.session_state[k] = v
    if _pop_keys:
        for k in _pop_keys:
            st.session_state.pop(k, None)


def _delete_group_callback(mgr, group_id, group_name):
    """Callback to delete a group before the dialog re-renders."""
    mgr.delete_group(group_id)
    st.session_state['pending_toast'] = f"\U0001F5D1\ufe0f Group '{group_name}' deleted."


def _remove_pair_from_group(mgr, group_id, pair_idx):
    """Callback to remove a single course pair from a group."""
    groups = mgr.load_groups()
    group = next((g for g in groups if g.get('group_id') == group_id), None)
    if group and 0 <= pair_idx < len(group.get('pairs', [])):
        popped = group['pairs'].pop(pair_idx)
        mgr.update_group(group_id, {'pairs': group['pairs']})
        st.session_state['pending_toast'] = f"\U0001F5D1\ufe0f Removed '{popped.get('course_name', 'course')}' from group."
    # Clear any active edit state that might reference stale indices
    st.session_state.pop('hub_editing_pair_idx', None)
    st.session_state.pop('hub_is_adding_new_pair', None)


def _hub_start_edit_pair(p_idx, pair):
    """Callback to enter inline edit mode for a pair."""
    st.session_state['hub_editing_pair_idx'] = p_idx
    st.session_state['hub_edit_temp_folder'] = pair.get('local_folder', '')
    st.session_state['hub_edit_temp_course_id'] = pair.get('course_id')
    st.session_state['hub_edit_temp_course_name'] = pair.get('course_name', '')
    st.session_state.pop('hub_is_adding_new_pair', None)


def _hub_cancel_edit():
    """Callback to cancel inline editing or adding."""
    st.session_state.pop('hub_editing_pair_idx', None)
    st.session_state.pop('hub_edit_temp_folder', None)
    st.session_state.pop('hub_edit_temp_course_id', None)
    st.session_state.pop('hub_edit_temp_course_name', None)
    st.session_state.pop('hub_is_adding_new_pair', None)


def _hub_pick_folder_cb():
    """Callback to open native folder picker and store result directly in edit temp state."""
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
        st.session_state['hub_edit_temp_folder'] = folder_path


def _save_inline_edit_cb(mgr, gid, p_idx, new_folder, new_cid, new_cname):
    """Callback to save an inline-edited pair without closing the dialog."""
    groups = mgr.load_groups()
    group = next((g for g in groups if g.get('group_id') == gid), None)
    if group:
        updated_pairs = list(group['pairs'])
        updated_pairs[p_idx] = {
            'local_folder': new_folder,
            'course_id': new_cid,
            'course_name': new_cname,
        }
        mgr.update_group(gid, {'pairs': updated_pairs})
        st.session_state['pending_toast'] = "\u2705 Pair updated successfully!"
    # Clear edit state
    _hub_cancel_edit()


def _save_inline_add_cb(mgr, gid, new_folder, new_cid, new_cname):
    """Callback to add a new pair to the group without closing the dialog."""
    groups = mgr.load_groups()
    group = next((g for g in groups if g.get('group_id') == gid), None)
    if group:
        updated_pairs = list(group.get('pairs', []))
        updated_pairs.append({
            'local_folder': new_folder,
            'course_id': new_cid,
            'course_name': new_cname,
        })
        mgr.update_group(gid, {'pairs': updated_pairs})
        st.session_state['pending_toast'] = f"\u2705 Added '{new_cname}' to the group!"
    # Clear add state
    _hub_cancel_edit()


def _confirm_course_selection_cb(cid, cname, course_names_map, courses_list):
    """Callback when confirming course selection in the SPA course selector."""
    if cid:
        st.session_state['hub_edit_temp_course_id'] = cid
        if cid in course_names_map:
            st.session_state['hub_edit_temp_course_name'] = course_names_map[cid]
        else:
            c_obj = next((c for c in courses_list if c.id == cid), None)
            if c_obj:
                st.session_state['hub_edit_temp_course_name'] = friendly_course_name(c_obj.name)
    # Clean up course selector state
    for k in list(st.session_state.keys()):
        if k.startswith('hub_cs_'):
            st.session_state.pop(k, None)
    # Navigate back to Layer 2
    st.session_state['hub_layer'] = 'layer_2'


@st.dialog("\U0001F4DA Saved Groups & Pairs", width="large")
def _saved_groups_hub_dialog(courses, course_names):
    """3-layered SPA dialog for managing saved sync groups."""
    from ui_helpers import get_config_dir
    import json as _json

    mgr = SavedGroupsManager(get_config_dir())
    layer = st.session_state.get('hub_layer', 'layer_1')

    # --- Dialog-wide CSS ---
    st.markdown("""
        <style>
            /* Flexbox Left-Align for Inline Edit/Add Rows */
            div[class*="st-key-hub_inline_edit_row"] div[data-testid="stHorizontalBlock"] {
                align-items: center !important;
                justify-content: flex-start !important;
                gap: 10px !important;
            }
            div[class*="st-key-hub_inline_edit_row"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
                width: auto !important;
                flex: 0 1 auto !important;
            }
            /* Reduce vertical space between Folder row and Course row */
            div[class*="st-key-hub_inline_edit_row_folder"],
            div[class*="st-key-hub_inline_edit_row_add_folder"] {
                margin-bottom: -6px !important;
            }

            /* Pull back buttons up to sit flush with dialog top */
            div.st-key-btn_back_to_groups,
            div.st-key-btn_hub_back_from_course_sel {
                margin-top: -30px !important;
            }

            /* =========================================
               COMPACT PAIR CARDS & ACTION BUTTONS
               ========================================= */
            /* Shrink the Action Buttons (Open, Edit, Remove) to 32px height */
            div[class*="st-key-hub_open_"] button,
            div[class*="st-key-hub_editp_"] button,
            div[class*="st-key-btn_hub_remove_pair_"] button {
                min-height: 32px !important;
                height: 32px !important;
                padding-top: 2px !important;
                padding-bottom: 2px !important;
                font-size: 0.9rem !important;
            }

            /* Reduce vertical padding inside the Pair Cards */
            div[class*="st-key-hub_pair_card_"] {
                padding-top: 8px !important;
                padding-bottom: 12px !important; 
                margin-bottom: 10px !important; /* Tighter gap between cards */
            }

            /* Compact the "See Configuration" expander summary */
            div[class*="st-key-hub_pair_card_"] div[data-testid="stExpander"] details summary {
                padding-top: 4px !important;
                padding-bottom: 4px !important;
                min-height: 0px !important;
            }

            /* Pull the action buttons closer to the text above them */
            div[class*="st-key-hub_pair_card_"] div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] {
                margin-top: -5px !important;
                margin-bottom: 2px !important;
            }

            /* Fix Group Name Edit Box padding to prevent height jumps */
            div.st-key-hub_edit_group_meta {
                padding: 8px 12px !important;
                margin-bottom: 5px !important;
            }
        </style>
    """, unsafe_allow_html=True)


    # =================================================================
    # LAYER 1 — Overview
    # =================================================================
    if layer == 'layer_1':
        groups = mgr.load_groups()
        if not groups:
            st.info("No saved groups or pairs yet. Use the \"\U0001F4BE Save List as Group\" button or the inline \U0001F4BE button to create one.")
            if st.button("Close", type="secondary", use_container_width=True, key="hub_close_empty"):
                _hub_cleanup()
                st.rerun()
            return

        # --- Tab Buttons (View All / Groups / Pairs) ---
        if 'hub_view_mode' not in st.session_state:
            st.session_state.hub_view_mode = "View All"
        _vm = st.session_state.hub_view_mode
        # Wrap in a container with a specific key for CSS targeting
        with st.container(key="hub_tabs_container"):
            t1, t2, t3 = st.columns(3)
            with t1:
                if st.button("View All", key="hub_tab_all",
                             type="primary" if _vm == "View All" else "secondary",
                             use_container_width=True):
                    st.session_state.hub_view_mode = "View All"
                    # Removed st.rerun() - button clicks natively refresh dialogs
            with t2:
                if st.button("Groups", key="hub_tab_groups",
                             type="primary" if _vm == "Groups" else "secondary",
                             use_container_width=True):
                    st.session_state.hub_view_mode = "Groups"
            with t3:
                if st.button("Pairs", key="hub_tab_pairs",
                             type="primary" if _vm == "Pairs" else "secondary",
                             use_container_width=True):
                    st.session_state.hub_view_mode = "Pairs"

        # --- Filter Logic ---
        if _vm == "Groups":
            filtered_groups = [g for g in groups if not g.get('is_single_pair')]
        elif _vm == "Pairs":
            filtered_groups = [g for g in groups if g.get('is_single_pair')]
        else:
            filtered_groups = groups

        if not filtered_groups:
            st.info(f"No {'pairs' if _vm == 'Pairs' else 'groups'} saved yet.")

        # NEW: Scrollable fixed-height container for the groups
        with st.container(height=560, border=False):
            for g_idx, group in enumerate(filtered_groups):
                is_sp = group.get('is_single_pair', False)

                if is_sp:
                    # === PAIR CARD (Single Pair) ===
                    with st.container(border=True, key=f"hub_pair_item_{g_idx}"):
                        pair = group.get('pairs', [{}])[0] if group.get('pairs') else {}
                        display_name = friendly_course_name(pair.get('course_name', group['group_name']))

                        # Title: 🏷️ with same font size/weight as group expander summaries
                        st.markdown(f"""
                            <div style='margin-top: 0px; margin-bottom: 10px;'>
                                <div style='font-size: 1.25rem; font-weight: 600; color: #ffffff; line-height: 1.2;'>\U0001F3F7\ufe0f {group['group_name']}</div>
                                <div style='color: #a3a8b8; font-size: 0.85rem; margin-top: 3px;'>\U0001F393 {display_name}</div>
                            </div>
                        """, unsafe_allow_html=True)

                        # Smart disable check: is this pair already on the sync list?
                        _current_sync = st.session_state.get('sync_pairs', [])
                        _pair_on_list = any(
                            sp.get('course_id') == pair.get('course_id')
                            and sp.get('local_folder') == pair.get('local_folder')
                            for sp in _current_sync
                        )
                        _add_help_sp = "This pair is already on the sync list." if _pair_on_list else None

                        # Pair action buttons (same as groups)
                        c1, c2, c3 = st.columns([1, 1, 1], gap="small")
                        with c1:
                            if st.button("\u2795 Add to Sync List", key=f"hub_add_{g_idx}",
                                         use_container_width=True,
                                         disabled=_pair_on_list, help=_add_help_sp):
                                # --- Single Pair Append Logic (Step 5) ---
                                incoming_pair = pair
                                current_list = _current_sync

                                # Rule A: Prevent exact duplicates (Same course_id AND local_folder)
                                for existing in current_list:
                                    if (existing.get('course_id') == incoming_pair.get('course_id')
                                            and existing.get('local_folder') == incoming_pair.get('local_folder')):
                                        st.session_state['pending_toast'] = "\u26a0\ufe0f This exact pair is already in your sync list."
                                        st.rerun()
                                        return

                                # Rule B: Prevent folder collision (Same local_folder path)
                                for existing in current_list:
                                    if existing.get('local_folder') == incoming_pair.get('local_folder'):
                                        st.session_state['pending_toast'] = "\u26a0\ufe0f Folder collision: this folder is already used by another pair in your sync list."
                                        st.rerun()
                                        return

                                # Validation passed — append
                                st.session_state['sync_pairs'].append(incoming_pair)
                                _persist_current_pairs()
                                st.session_state['pending_toast'] = f"\u2705 Added '{display_name}' to sync list!"
                                _hub_cleanup()
                                st.rerun()
                        with c2:
                            st.button("\u270f\ufe0f Edit Pair", key=f"hub_edit_{g_idx}",
                                      use_container_width=True,
                                      on_click=_change_hub_layer,
                                      kwargs={'target_layer': 'layer_2', 'hub_active_group_id': group['group_id']})
                        with c3:
                            st.button("\U0001F5D1\ufe0f Delete", key=f"btn_hub_delete_{group['group_id']}",
                                      use_container_width=True,
                                      on_click=_delete_group_callback,
                                      args=(mgr, group['group_id'], group['group_name']))

                else:
                    # === GROUP CARD (Multi-pair group) ===
                    with st.container(border=True, key=f"hub_overview_group_card_{g_idx}"):
                        pair_count = len(group.get('pairs', []))
                        course_word = 'course' if pair_count == 1 else 'courses'
                        
                        # 1. Custom Title HTML (Fixed top margin to align centrally)
                        st.markdown(f"""
                            <div style='margin-top: 0px; margin-bottom: 10px;'>
                                <div style='font-size: 1.25rem; font-weight: 600; color: #ffffff; line-height: 1.2;'>\U0001F5C2\ufe0f {group['group_name']}</div>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        # 2. Borderless Expander for Courses
                        with st.expander(f"{pair_count} {course_word}"):
                            bullet_points = []
                            for p in group.get('pairs', []):
                                fname = friendly_course_name(p.get('course_name', 'Unknown'))
                                bullet_points.append(f"- {fname}")
                            
                            if bullet_points:
                                st.markdown("\n".join(bullet_points))
                            else:
                                st.markdown("*No courses in this group*")

                        # Smart disable check: are ALL pairs already on the sync list?
                        _current_sync_g = st.session_state.get('sync_pairs', [])
                        _current_sigs = {
                            (sp.get('course_id'), sp.get('local_folder'))
                            for sp in _current_sync_g
                        }
                        _group_on_list = all(
                            (gp.get('course_id'), gp.get('local_folder')) in _current_sigs
                            for gp in group.get('pairs', [])
                        ) if group.get('pairs') else False
                        _add_help_g = "All pairs in this group are already on the sync list." if _group_on_list else None

                        # Spacer removed to make buttons compact against the expander
                        c1, c2, c3 = st.columns([1, 1, 1], gap="small")
                        with c1:
                            if st.button("\u2795 Add to Sync List", key=f"hub_add_{g_idx}",
                                         use_container_width=True,
                                         disabled=_group_on_list, help=_add_help_g):
                                # --- Phase 3: Pre-Flight Engine ---
                                incoming = group.get('pairs', [])
                                existing_ids = {p.get('course_id') for p in st.session_state.get('sync_pairs', [])}

                                # Task 1: Silent duplicate filtering
                                unique_pairs = [p for p in incoming if p.get('course_id') not in existing_ids]
                                skipped = len(incoming) - len(unique_pairs)

                                if not unique_pairs:
                                    st.session_state['pending_toast'] = f"\u26a0\ufe0f All {len(incoming)} courses are already in your sync list."
                                    st.rerun()
                                else:
                                    # Task 2: Folder existence pre-flight
                                    missing_indices = [
                                        i for i, p in enumerate(unique_pairs)
                                        if not Path(p.get('local_folder', '')).exists()
                                    ]

                                    if not missing_indices:
                                        # All folders exist — merge immediately
                                        st.session_state['sync_pairs'] = st.session_state.get('sync_pairs', []) + unique_pairs
                                        _persist_current_pairs()
                                        added = len(unique_pairs)
                                        msg = f"\u2705 Added {added} course{'s' if added != 1 else ''} to sync list!"
                                        if skipped:
                                            msg += f" (Skipped {skipped} duplicate{'s' if skipped != 1 else ''}.)"
                                        st.session_state['pending_toast'] = msg
                                        _hub_cleanup()
                                        st.rerun()
                                    else:
                                        # Some folders missing — enter rescue mode
                                        st.session_state['hub_layer'] = 'rescue_mode'
                                        st.session_state['hub_rescue_group_id'] = group['group_id']
                                        st.session_state['hub_rescue_pairs'] = unique_pairs
                                        st.session_state['hub_rescue_missing'] = missing_indices
                                        st.session_state['hub_rescue_skipped'] = skipped
                                        st.session_state['rescue_paths'] = {}
                                        st.rerun()
                        with c2:
                            st.button("\u270f\ufe0f Edit Group", key=f"hub_edit_{g_idx}",
                                      use_container_width=True,
                                      on_click=_change_hub_layer,
                                      kwargs={'target_layer': 'layer_2', 'hub_active_group_id': group['group_id']})
                        with c3:
                            st.button("\U0001F5D1\ufe0f Delete", key=f"btn_hub_delete_{group['group_id']}",
                                      use_container_width=True,
                                      on_click=_delete_group_callback,
                                      args=(mgr, group['group_id'], group['group_name']))

        if st.button("Close", type="secondary", use_container_width=True, key="btn_hub_close"):
            _hub_cleanup()
            st.rerun()

    # =================================================================
    # LAYER 2 — Group Details
    # =================================================================
    elif layer == 'layer_2':
        gid = st.session_state.get('hub_active_group_id')
        groups = mgr.load_groups()
        group = next((g for g in groups if g.get('group_id') == gid), None)
        if not group:
            st.error("Group not found.")
            st.button("\u2b05\ufe0f Back", key="hub_back_l2_err", type="tertiary",
                      on_click=_change_hub_layer, kwargs={'target_layer': 'layer_1'})
            return

        st.button("← Back to Groups", key="btn_back_to_groups", type="tertiary",
                  on_click=_change_hub_layer, kwargs={'target_layer': 'layer_1'})

        # Detect single pair for conditional UI
        is_sp = group.get('is_single_pair', False)
        entity_label = "Pair" if is_sp else "Group"

        # --- Dynamic Group/Pair Name (View/Edit Modes) ---
        edit_mode_active = st.session_state.get('hub_edit_group_name_active', False)
        
        def _toggle_edit_name():
            st.session_state['hub_edit_group_name_active'] = not st.session_state.get('hub_edit_group_name_active', False)

        def _cancel_edit_name_cb():
            st.session_state['hub_edit_group_name_active'] = False

        def _save_name_cb():
            val = st.session_state.get("hub_edit_name_input", "").strip()
            if val and val != group['group_name']:
                mgr.update_group(gid, {'group_name': val})
                st.session_state['pending_toast'] = f"✅ {entity_label} renamed to '{val}'"
            st.session_state['hub_edit_group_name_active'] = False

        if not edit_mode_active:
            # VIEW MODE (Dominant H1 with tight label spacing)
            with st.container(key="hub_group_name_view_row"):
                cv1, cv2 = st.columns([0.8, 0.2], vertical_alignment="bottom")
                with cv1:
                    name_label = "Pair name:" if is_sp else "Group name:"
                    st.markdown(f"""
                        <div style='margin-bottom: -5px; margin-top: -20px;'>
                            <span style='color: rgba(255,255,255,0.5); font-size: 0.85rem; font-weight: 500;'>{name_label}</span>
                        </div>
                        <h1 style='margin: 0px; padding: 0px; font-size: 2.2rem; display: inline-block; line-height: 1;'>{group['group_name']}</h1>
                    """, unsafe_allow_html=True)
                with cv2:
                    st.button("✏️ Edit", key="btn_enable_edit_name", on_click=_toggle_edit_name)
            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True) # Spacing before cards
        else:
            # EDIT MODE (Ultra-compact to prevent dialog height jump)
            with st.container(border=True, key="hub_edit_group_meta"):
                col_name, col_save, col_cancel = st.columns([0.6, 0.2, 0.2], vertical_alignment="bottom")
                with col_name:
                    new_name = st.text_input(f"{entity_label} Name", value=group['group_name'],
                                             key="hub_edit_name_input", label_visibility="collapsed")
                with col_save:
                    name_changed = new_name.strip() and new_name.strip() != group['group_name']
                    st.button("💾 Save", disabled=not name_changed,
                              use_container_width=True, key="hub_save_name", on_click=_save_name_cb)
                with col_cancel:
                    st.button("Cancel", use_container_width=True, key="hub_cancel_edit_name", on_click=_cancel_edit_name_cb)

        st.markdown("")

        # --- Pair cards (Wrapped in a scrollable container matching Layer 1) ---
        with st.container(height=580, border=False):
            pairs = group.get('pairs', [])
            editing_idx = st.session_state.get('hub_editing_pair_idx')
            is_adding = st.session_state.get('hub_is_adding_new_pair', False)

            if not pairs and not is_adding:
                st.info("No courses in this group yet. Add one below.")

            for p_idx, pair in enumerate(pairs):
                # === INLINE EDIT MODE ===
                if editing_idx is not None and editing_idx == p_idx:
                    with st.container(border=True, key=f"hub_pair_card_{p_idx}"):
                        st.markdown("<div style='font-size: 1.25rem; font-weight: 600; margin-top: 5px; margin-bottom: -10px;'>\u270f\ufe0f Editing Pair</div>", unsafe_allow_html=True)

                        # --- Folder row ---
                        temp_folder = st.session_state.get('hub_edit_temp_folder', pair.get('local_folder', ''))
                        folder_display = Path(temp_folder).name if temp_folder else 'No folder selected'
                        with st.container(key=f"hub_inline_edit_row_folder_{p_idx}"):
                            col_f_info, col_f_btn = st.columns(2, vertical_alignment="center", gap="small")
                            with col_f_info:
                                st.markdown(
                                    f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                                    f'Folder:</span>'
                                    f'<span style="color:#fff;font-weight:600;font-size:0.95rem;white-space:nowrap;">📁 {folder_display}</span>',
                                    unsafe_allow_html=True,
                                )
                            with col_f_btn:
                                st.button("Change Folder", key=f"hub_edit_change_folder_{p_idx}",
                                          on_click=_hub_pick_folder_cb)

                        # --- Course row ---
                        temp_course_id = st.session_state.get('hub_edit_temp_course_id')
                        temp_course_name = st.session_state.get('hub_edit_temp_course_name', '')
                        course_disp = temp_course_name or 'No course selected'
                        if temp_course_id and temp_course_id in course_names:
                            course_disp = course_names[temp_course_id]

                        with st.container(key=f"hub_inline_edit_row_course_{p_idx}"):
                            col_c_info, col_c_btn = st.columns(2, vertical_alignment="center", gap="small")
                            with col_c_info:
                                st.markdown(
                                    f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                                    f'Course:</span>'
                                    f'<span style="color:#fff;font-weight:600;font-size:0.95rem;white-space:nowrap;">{course_disp}</span>',
                                    unsafe_allow_html=True,
                                )
                            with col_c_btn:
                                st.button("Change Course", key=f"hub_edit_change_course_{p_idx}",
                                          on_click=_change_hub_layer,
                                          kwargs={'target_layer': 'layer_course_selector'})

                        # --- Save / Cancel ---
                        col_save, col_cancel, _ = st.columns([1, 1, 3])
                        with col_save:
                            final_folder = st.session_state.get('hub_edit_temp_folder', pair.get('local_folder', ''))
                            final_cid = st.session_state.get('hub_edit_temp_course_id', pair.get('course_id'))
                            final_cname = st.session_state.get('hub_edit_temp_course_name', pair.get('course_name', ''))
                            has_changes = (
                                final_folder != pair.get('local_folder', '')
                                or final_cid != pair.get('course_id')
                            )
                            st.button("💾 Save Changes", type="primary", use_container_width=True,
                                      key=f"hub_save_edit_{p_idx}", disabled=not has_changes,
                                      on_click=_save_inline_edit_cb,
                                      args=(mgr, gid, p_idx, final_folder, final_cid, final_cname))
                        with col_cancel:
                            st.button("Cancel", key=f"hub_cancel_edit_{p_idx}",
                                      use_container_width=True, on_click=_hub_cancel_edit)

                # === NORMAL VIEW MODE ===
                else:
                    with st.container(border=True, key=f"hub_pair_card_{p_idx}"):
                        display_name = friendly_course_name(pair.get('course_name', 'Unknown'))
                        folder_exists = Path(pair.get('local_folder', '')).exists()

                        st.markdown(f"""
                            <div style='margin-bottom: 12px; margin-top: 6px;'>
                                <div style='font-size: 1.25rem; font-weight: 600; color: #ffffff; line-height: 1.4; margin-bottom: 4px;'>{display_name}</div>
                                <div style='color: #a3a8b8; font-size: 14px;'>📁 {pair.get('local_folder', '')}</div>
                            </div>
                        """, unsafe_allow_html=True)

                        if is_sp:
                            # Single pair: 2 columns (no Remove button)
                            c1, c2 = st.columns([0.5, 0.5])
                            with c1:
                                if st.button("📂 Open Folder", key=f"hub_open_{p_idx}", disabled=not folder_exists, use_container_width=True):
                                    open_folder(pair['local_folder'])
                            with c2:
                                st.button("✏️ Edit Pair", key=f"hub_editp_{p_idx}", use_container_width=True,
                                          on_click=_hub_start_edit_pair, args=(p_idx, pair))
                        else:
                            c1, c2, c3 = st.columns(3)
                            with c1:
                                if st.button("📂 Open Folder", key=f"hub_open_{p_idx}", disabled=not folder_exists, use_container_width=True):
                                    open_folder(pair['local_folder'])
                            with c2:
                                st.button("✏️ Edit Pair", key=f"hub_editp_{p_idx}", use_container_width=True,
                                          on_click=_hub_start_edit_pair, args=(p_idx, pair))
                            with c3:
                                st.button("🗑️ Remove", key=f"btn_hub_remove_pair_{p_idx}", use_container_width=True,
                                          on_click=_remove_pair_from_group, args=(mgr, gid, p_idx))

                        # --- Config expander ---
                        with st.expander("⚙️ See Configuration", expanded=False):
                            _render_hub_config(pair)

            # === INLINE ADD NEW PAIR (Hidden for single pairs) ===
            if not is_sp and is_adding:
                with st.container(border=True, key="hub_add_new_pair_card"):
                    st.markdown("<div style='font-size: 1.25rem; font-weight: 600; margin-bottom: 10px;'>\u2795 Add a New Course/Folder Pair</div>", unsafe_allow_html=True)

                    # --- Folder row ---
                    add_folder = st.session_state.get('hub_edit_temp_folder', '')
                    add_folder_display = Path(add_folder).name if add_folder else 'No folder selected'
                    with st.container(key="hub_inline_edit_row_add_folder"):
                        col_af_info, col_af_btn = st.columns(2, vertical_alignment="center", gap="small")
                        with col_af_info:
                            st.markdown(
                                f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                                f'Folder:</span>'
                                f'<span style="color:#fff;font-weight:600;font-size:0.95rem;white-space:nowrap;">📁 {add_folder_display}</span>',
                                unsafe_allow_html=True,
                            )
                        with col_af_btn:
                            st.button("Select Folder", key="btn_inline_new_folder",
                                      on_click=_hub_pick_folder_cb)

                    # --- Course row ---
                    add_course_id = st.session_state.get('hub_edit_temp_course_id')
                    add_course_name = st.session_state.get('hub_edit_temp_course_name', '')
                    add_course_disp = add_course_name or 'No course selected'
                    if add_course_id and add_course_id in course_names:
                        add_course_disp = course_names[add_course_id]

                    with st.container(key="hub_inline_edit_row_add_course"):
                        col_ac_info, col_ac_btn = st.columns(2, vertical_alignment="center", gap="small")
                        with col_ac_info:
                            st.markdown(
                                f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                                f'Course:</span>'
                                f'<span style="color:#fff;font-weight:600;font-size:0.95rem;white-space:nowrap;">{add_course_disp}</span>',
                                unsafe_allow_html=True,
                            )
                        with col_ac_btn:
                            st.button("Select Course", key="btn_inline_new_course",
                                      on_click=_change_hub_layer,
                                      kwargs={'target_layer': 'layer_course_selector'})

                    # --- Add / Cancel ---
                    can_add = bool(add_folder) and bool(add_course_id)
                    add_cname_final = add_course_name if add_course_name else course_names.get(add_course_id, '')
                    col_add, col_cancel_add, _ = st.columns([1, 1, 3])
                    with col_add:
                        st.button("💾 Add to Group", use_container_width=True,
                                  key="btn_inline_new_confirm", disabled=not can_add,
                                  on_click=_save_inline_add_cb,
                                  args=(mgr, gid, add_folder, add_course_id, add_cname_final))
                    with col_cancel_add:
                        st.button("Cancel", key="btn_inline_new_cancel",
                                  use_container_width=True, on_click=_hub_cancel_edit)

            # --- "Add a new course" button (only when not already adding, hidden for single pairs) ---
            if not is_sp and not is_adding:
                st.markdown("")
                def _start_adding():
                    st.session_state['hub_is_adding_new_pair'] = True
                    st.session_state.pop('hub_editing_pair_idx', None)
                    st.session_state.pop('hub_edit_temp_folder', None)
                    st.session_state.pop('hub_edit_temp_course_id', None)
                    st.session_state.pop('hub_edit_temp_course_name', None)
                st.button("➕ Add a new course to the group", key="btn_hub_add_new_pair",
                          use_container_width=True, on_click=_start_adding)

    # =================================================================
    # LAYER: COURSE SELECTOR (Premium SPA page)
    # =================================================================
    elif layer == 'layer_course_selector':
        # Determine current selection from the edit/add temp state
        current_selected_id = st.session_state.get('hub_edit_temp_course_id')

        st.button("\u2190 Back to Edit", key="btn_hub_back_from_course_sel", type="tertiary",
                  on_click=_change_hub_layer, kwargs={'target_layer': 'layer_2'})
        st.markdown("<h3 style='font-size: 1.5rem; margin-top: 0px;'>Select Course</h3>", unsafe_allow_html=True)

        # --- Filters (Favorites / All) ---
        col_filters, _ = st.columns([0.7, 0.3])
        with col_filters:
            filter_mode = st.radio(
                "Filter Mode",
                ["Favorites", "All Courses"],
                index=0 if st.session_state.get('hub_cs_filter_favorites', True) else 1,
                horizontal=True,
                label_visibility="collapsed",
                key="hub_cs_filter_mode"
            )
        st.session_state['hub_cs_filter_favorites'] = (filter_mode == "Favorites")

        visible_courses = courses
        if st.session_state['hub_cs_filter_favorites']:
            visible_courses = [c for c in courses if getattr(c, 'is_favorite', False)]

        if not visible_courses:
            st.warning("No courses found with the current filter.")
            return

        # --- CBS Filters ---
        show_filters = st.toggle("Enable CBS Filters", key="hub_cs_show_cbs")

        filtered_courses = visible_courses

        if show_filters:
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

            with st.container(border=True, key="hub_cs_cbs_container"):
                st.markdown("**Filter Criteria**")
                c1, c2, c3 = st.columns(3)
                with c1:
                    sel_types = st.multiselect("Class Type", options=sorted(list(all_types)), key="hub_cs_type")
                with c2:
                    sel_sem = st.multiselect("Semester", options=sorted(list(all_semesters)), key="hub_cs_sem")
                with c3:
                    sel_years = st.multiselect("Year", options=sorted(list(all_years), reverse=True), key="hub_cs_year")

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
                    st.info("No courses match the selected filters.")

        # --- Sorting: selected first, then alphabetical ---
        active_selection = st.session_state.get('hub_cs_selected_id', current_selected_id)
        filtered_courses.sort(key=lambda c: (0 if c.id == active_selection else 1, (c.name or "").lower()))

        st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)

        # --- Initialize single-select state ---
        if 'hub_cs_selected_id' not in st.session_state:
            st.session_state['hub_cs_selected_id'] = current_selected_id

        # --- Scrollable course list ---
        with st.container(height=400, border=False, key="hub_cs_scroll_container"):
            for course in filtered_courses:
                full_name_str = f"{course.name} ({course.course_code})" if hasattr(course, 'course_code') else course.name
                friendly = friendly_course_name(full_name_str)
                is_checked = (st.session_state['hub_cs_selected_id'] == course.id)

                c1, c2 = st.columns([0.05, 0.95])
                with c1:
                    st.session_state[f"hub_cs_chk_{course.id}"] = is_checked

                    def _hub_course_toggled(cid):
                        if st.session_state.get(f"hub_cs_chk_{cid}"):
                            st.session_state['hub_cs_selected_id'] = cid
                        elif st.session_state.get('hub_cs_selected_id') == cid:
                            st.session_state['hub_cs_selected_id'] = None

                    st.checkbox(
                        "Select",
                        key=f"hub_cs_chk_{course.id}",
                        on_change=_hub_course_toggled,
                        args=(course.id,),
                        label_visibility="collapsed"
                    )

                with c2:
                    st.markdown(
                        f'<div style="margin-top: -2px; width: 100%;">'
                        f'<strong>{friendly}</strong> '
                        f'<br><span style="color:#888; font-size:0.85em;">{full_name_str}</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

        # --- Confirm Selection ---
        st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)
        selected_cid = st.session_state.get('hub_cs_selected_id')
        selected_cname = ''
        if selected_cid:
            if selected_cid in course_names:
                selected_cname = course_names[selected_cid]
            else:
                c_obj = next((c for c in courses if c.id == selected_cid), None)
                if c_obj:
                    selected_cname = friendly_course_name(c_obj.name)
        st.button("Confirm Selection", key="hub_cs_confirm_btn", type="primary",
                  use_container_width=True, disabled=not bool(selected_cid),
                  on_click=_confirm_course_selection_cb,
                  args=(selected_cid, selected_cname, course_names, courses))

    # =================================================================
    # RESCUE MODE — Remap Missing Folders
    # =================================================================
    elif layer == 'rescue_mode':
        rescue_pairs = st.session_state.get('hub_rescue_pairs', [])
        missing_indices = st.session_state.get('hub_rescue_missing', [])
        rescue_paths = st.session_state.get('rescue_paths', {})
        skipped_count = st.session_state.get('hub_rescue_skipped', 0)
        rescue_gid = st.session_state.get('hub_rescue_group_id')

        st.button("← Back to Groups", key="hub_back_rescue", type="tertiary",
                  on_click=_change_hub_layer,
                  kwargs={'target_layer': 'layer_1',
                          '_pop_keys': ['hub_rescue_group_id', 'hub_rescue_pairs',
                                        'hub_rescue_missing', 'hub_rescue_skipped', 'rescue_paths']})

        st.warning(
            "\u26a0\ufe0f Some folders could not be found. They may have been "
            "moved or deleted. Please remap them to continue."
        )

        all_remapped = True
        for mi in missing_indices:
            if mi >= len(rescue_pairs):
                continue
            pair = rescue_pairs[mi]
            display_name = friendly_course_name(pair.get('course_name', 'Unknown'))
            old_folder = pair.get('local_folder', '')
            new_folder = rescue_paths.get(mi)

            with st.container(border=True):
                st.markdown(
                    f"<div style='font-weight:600;'>\U0001F393 {display_name}</div>"
                    f"<div style='font-size:0.82rem; color:#f87171; margin-top:2px;'>"
                    f"\u274c Missing: <code>{old_folder}</code></div>",
                    unsafe_allow_html=True,
                )
                if new_folder:
                    st.markdown(
                        f"<div style='font-size:0.85rem; color:#4ade80; margin-top:4px;'>"
                        f"\u2705 Remapped to: <code>{new_folder}</code></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    all_remapped = False
                    if st.button(f"\U0001F4C2 Locate folder for {display_name}",
                                 key=f"rescue_locate_{mi}", use_container_width=True):
                        _rescue_select_folder(mi)

        st.markdown("")
        confirm_disabled = not all_remapped
        if st.button("\u2705 Confirm & Add Group", type="primary",
                     use_container_width=True, key="hub_rescue_confirm",
                     disabled=confirm_disabled):
            # Apply remapped paths to the pairs
            final_pairs = list(rescue_pairs)
            for mi, new_path in rescue_paths.items():
                if mi < len(final_pairs):
                    final_pairs[mi] = {
                        **final_pairs[mi],
                        'local_folder': new_path,
                    }

            # Also update the saved group JSON with the new paths
            if rescue_gid:
                groups = mgr.load_groups()
                group = next((g for g in groups if g.get('group_id') == rescue_gid), None)
                if group:
                    updated_group_pairs = list(group.get('pairs', []))
                    for mi, new_path in rescue_paths.items():
                        # Find the matching pair in the original group by course_id
                        if mi < len(final_pairs):
                            target_cid = final_pairs[mi].get('course_id')
                            for gp in updated_group_pairs:
                                if gp.get('course_id') == target_cid:
                                    gp['local_folder'] = new_path
                                    break
                    mgr.update_group(rescue_gid, {'pairs': updated_group_pairs})

            # Merge into active sync list
            st.session_state['sync_pairs'] = st.session_state.get('sync_pairs', []) + final_pairs
            _persist_current_pairs()

            added = len(final_pairs)
            msg = f"\u2705 Added {added} course{'s' if added != 1 else ''} to sync list!"
            if skipped_count:
                msg += f" (Skipped {skipped_count} duplicate{'s' if skipped_count != 1 else ''}.)"
            st.session_state['pending_toast'] = msg
            _hub_cleanup()
            st.rerun()


def _render_hub_config(pair: dict):
    import json as _json
    from pathlib import Path
    local_folder = pair.get('local_folder', '')
    course_id = pair.get('course_id', 0)
    db_path = Path(local_folder) / '.canvas_sync.db'

    if not db_path.exists():
        st.warning("⚠️ Not synced yet / No configuration found.")
        return

    try:
        sm = SyncManager(local_folder, course_id, pair.get('course_name', ''))
        raw_contract = sm._load_metadata('sync_contract')
        raw_mode = sm._load_metadata('download_mode') # Load download_mode directly
        
        if not raw_contract:
            st.warning("⚠️ No sync contract stored. Run a sync to save settings.")
            return
        contract = _json.loads(raw_contract)
    except Exception:
        st.warning("⚠️ Could not read configuration.")
        return

    # --- PERFECTED HTML/CSS RENDERING ---
    st.markdown("""
    <style>
    .cfg-header { font-weight: 600; color: #ffffff; margin-bottom: 8px; font-size: 1.05rem; margin-left: 15px; }
    .cfg-cb { display: flex; align-items: flex-start; margin-bottom: 6px; font-size: 0.95rem; line-height: 1.3; pointer-events: none; margin-left: 15px; }
    .cfg-cb input { margin-right: 8px; margin-top: 4px; accent-color: #3b82f6; width: 15px; height: 15px; }
    .cfg-cb.checked { opacity: 1.0; color: #ffffff; }
    .cfg-cb.unchecked { opacity: 0.65; color: #a3a8b8; }
    .cfg-indent { margin-left: 37px; } 
    </style>
    """, unsafe_allow_html=True)

    def cb(label, is_checked, indent=False):
        state = "checked" if is_checked else "unchecked"
        chk = "checked" if is_checked else ""
        indent_cls = "cfg-indent" if indent else ""
        return f"<div class='cfg-cb {state} {indent_cls}'><input type='checkbox' {chk}><span>{label}</span></div>"

    c1, c2, c3 = st.columns([1, 1.1, 1.1], gap="small")

    # LOGIC FIX 1: Evaluate flat vs subfolders from raw_mode
    is_flat = (raw_mode == 'flat')
    is_all = contract.get('file_filter', 'all') == 'all'

    # LOGIC FIX 2: Evaluate NotebookLM status based on all sub-settings being true
    conversion_keys = ['convert_zip', 'convert_pptx', 'convert_word', 'convert_excel', 
                       'convert_html', 'convert_code', 'convert_urls', 'convert_video']
    is_notebook_lm = all(contract.get(k, False) for k in conversion_keys)

    with c1:
        st.markdown("<div class='cfg-header' style='margin-top: -15px;'>Folder Download Structure:</div>", unsafe_allow_html=True)
        st.markdown(cb("With subfolders (matches Canvas Modules)", not is_flat), unsafe_allow_html=True)
        st.markdown(cb("Flat (All files in one folder)", is_flat), unsafe_allow_html=True)

        st.markdown("<div class='cfg-header' style='margin-top: 15px;'>File types downloaded:</div>", unsafe_allow_html=True)
        st.markdown(cb("All Files", is_all), unsafe_allow_html=True)
        st.markdown(cb("Pdf & Powerpoint only", not is_all), unsafe_allow_html=True)

    with c2:
        st.markdown("<div class='cfg-header' style='margin-top: -15px;'>Additional settings:</div>", unsafe_allow_html=True)
        st.markdown(cb("NotebookLM Compatible Download", is_notebook_lm), unsafe_allow_html=True) # Uses derived boolean
        st.markdown(cb("Auto-extract Archives (.zip, .tar.gz)", contract.get('convert_zip', False), indent=True), unsafe_allow_html=True)
        st.markdown(cb("Convert Powerpoints (pptx.) to PDF", contract.get('convert_pptx', False), indent=True), unsafe_allow_html=True)
        st.markdown(cb("Convert Old Word Docs (.doc, .rtf) to PDF", contract.get('convert_word', False), indent=True), unsafe_allow_html=True)
        st.markdown(cb("Convert Excel Files (.xlsx, .xls) to PDF", contract.get('convert_excel', False), indent=True), unsafe_allow_html=True)

    with c3:
        st.markdown("<div class='cfg-header' style='visibility: hidden; margin-top: -15px;'>Spacer</div>", unsafe_allow_html=True) 
        st.markdown("<div class='cfg-cb' style='visibility: hidden;'><input type='checkbox'><span>Spacer</span></div>", unsafe_allow_html=True)
        st.markdown(cb("Convert Canvas Pages (HTML) to Markdown", contract.get('convert_html', False), indent=True), unsafe_allow_html=True)
        st.markdown(cb("Convert Code & Data Files to .txt", contract.get('convert_code', False), indent=True), unsafe_allow_html=True)
        st.markdown(cb("Compile Web Links (.url) into a single list", contract.get('convert_urls', False), indent=True), unsafe_allow_html=True)
        st.markdown(cb("Extract Audio (.mp3) from Videos (.mp4, .mov)", contract.get('convert_video', False), indent=True), unsafe_allow_html=True)

    st.markdown("<div style='margin-bottom: -10px;'></div>", unsafe_allow_html=True)


def _hub_cleanup():
    """Reset all hub-specific session state keys."""
    for k in ['hub_layer', 'hub_active_group_id',
              'hub_temp_folder', 'hub_temp_course_id',
              'hub_editing_pair_idx', 'hub_edit_temp_folder',
              'hub_edit_temp_course_id', 'hub_edit_temp_course_name',
              'hub_is_adding_new_pair',
              'hub_rescue_group_id', 'hub_rescue_pairs', 'hub_rescue_missing',
              'hub_rescue_skipped', 'rescue_paths']:
        st.session_state.pop(k, None)


# ===================================================================
# STEP 1 — Folder Pairing
# ===================================================================
def _inject_hub_global_css():
    """Unconditionally inject all styling for the Hub Dialog and Main Button."""
    st.markdown("""
    <style>
    /* ---------------------------------------------------------
       ALL HUB BUTTON CSS (Previously in col_hub)
       --------------------------------------------------------- */
    /* 1. Strip default margins from the Hub button so it aligns with the <h3> heading */
    div.st-key-btn_hub_main {
        margin-top: 0px !important;
        margin-bottom: 0px !important;
    }

    /* 2. Target the specific row (stHorizontalBlock) containing the Hub button 
          and kill its bottom margin/padding */
    div[data-testid="stHorizontalBlock"]:has(.st-key-btn_hub_main) {
        margin-bottom: -15px !important;
        padding-bottom: 0px !important;
    }

    /* 3. Pull the main sync list container UP towards the button/heading */
    div.st-key-sync_list_outline {
        margin-top: -10px !important; /* Tweaked to achieve the 2-5px visual gap */
    }

    /* Dusty Slate-Indigo theme for Group features */
    div.st-key-btn_save_group_main button,
    div.st-key-btn_hub_main button {
        background-color: rgba(95, 100, 200, 0.35) !important; /* Desaturated indigo, higher base opacity */
        color: #e0e7ff !important; 
        border: 1px solid rgba(95, 100, 200, 0.6) !important; 
    }

    div.st-key-btn_save_group_main button:hover,
    div.st-key-btn_hub_main button:hover {
        background-color: rgba(95, 100, 200, 0.55) !important; /* Lighter on hover */
        border-color: rgba(95, 100, 2000, 0.9) !important; 
        color: #ffffff !important;
        transition: all 0.2s ease-in-out;
    }

    /* Disabled state for Save Group button */
    div.st-key-btn_save_group_main button[disabled] {
        background-color: rgba(95, 100, 200, 0.15) !important; /* Very dim when disabled */
        border: 1px solid rgba(95, 100, 200, 0.3) !important;
        color: rgba(255, 255, 255, 0.3) !important;
        cursor: not-allowed !important;
    }

    /* ---------------------------------------------------------
       ALL DIALOG CSS (Layer 1, Layer 2, action buttons, etc.)
       IMPORTANT: All button selectors MUST include
       div[data-testid="stDialog"] to beat Streamlit's defaults.
       --------------------------------------------------------- */
       
    /* =========================================
       LAYER 1: EXPANDER BULLET LIST ALIGNMENT (V2)
       ========================================= */
    /* Target the specific Markdown containers to kill Streamlit's native offsets */
    div[data-testid="stDialog"] div[data-testid="stExpanderDetails"] div[data-testid="stMarkdownContainer"] ul,
    div[data-testid="stDialog"] div[data-testid="stExpanderDetails"] .stMarkdown ul {
        padding-left: 1.5rem !important; /* Increased from 1.2rem to nudge right */
        margin-left: 0px !important;
        margin-inline-start: 0px !important; /* Kills the browser's native text indent */
        margin-top: -5px !important;     
        margin-bottom: 5px !important;
    }
    
    div[data-testid="stDialog"] div[data-testid="stExpanderDetails"] div[data-testid="stMarkdownContainer"] ul li,
    div[data-testid="stDialog"] div[data-testid="stExpanderDetails"] .stMarkdown ul li {
        padding-left: 0.2rem !important;
        margin-left: 0px !important;
    }
       
    /* =========================================
       LAYER 1: EXPANDER TITLE STYLING
       ========================================= */
    /* Target the paragraph/span inside the summary to bold the text without breaking the arrow icon */
    div[data-testid="stDialog"] div[data-testid="stExpander"] details summary p,
    div[data-testid="stDialog"] div[data-testid="stExpander"] details summary span {
        font-size: 1.05rem !important;
        font-weight: 600 !important;
        color: #ffffff !important; 
    }
       
    /* Primary button: blue */
    div[data-testid="stDialog"] button[kind="primary"] {
        background-color: #3b82f6 !important;
        color: white !important;
        border: none !important;
    }
    div[data-testid="stDialog"] button[kind="primary"]:hover {
        background-color: #60a5fa !important;
    }
    div[data-testid="stDialog"] button[kind="primary"][disabled] {
        background-color: #1e3a8a !important;
        opacity: 1 !important;
        color: rgba(255, 255, 255, 0.5) !important;
        cursor: not-allowed !important;
    }

    /* Secondary button baseline: ensures ALL dialog secondary buttons
       have a sane default before per-key overrides refine them */
    div[data-testid="stDialog"] button[kind="secondary"] {
        background-color: #262730 !important;
        color: white !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
    }
    div[data-testid="stDialog"] button[kind="secondary"]:hover {
        border: 1px solid rgba(255, 255, 255, 0.35) !important;
        transition: all 0.2s ease-in-out;
    }

    /* Cancel buttons inside dialog */
    div[data-testid="stDialog"] div[class*="st-key-cancel_save_group"] button:hover {
        background-color: #ef4444 !important;
        border-color: #ef4444 !important;
        color: white !important;
    }

    /* Close Button (Normal Hover - Lighter Border) */
    div[data-testid="stDialog"] div.st-key-btn_hub_close button {
        background-color: #262730 !important;
        color: white !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
    }
    div[data-testid="stDialog"] div.st-key-btn_hub_close button:hover {
        background-color: #262730 !important;
        color: white !important;
        border: 1px solid rgba(255, 255, 255, 0.35) !important;
        transition: all 0.2s ease-in-out;
    }

    /* =========================================
       LAYER 1: GROUP CARD BUTTONS HIERARCHY
       All selectors scoped under stDialog for
       guaranteed specificity over Streamlit defaults.
       ========================================= */

    /* 1. Default state for "Add to Sync List" & "Edit Group" (Light Grey) */
    div[data-testid="stDialog"] div[class*="st-key-hub_add_"] button,
    div[data-testid="stDialog"] div[class*="st-key-hub_edit_"] button {
        background-color: rgba(255, 255, 255, 0.1) !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        color: #ffffff !important;
    }

    /* 2. Hover state for "Edit Group" (Lighter Grey) */
    div[data-testid="stDialog"] div[class*="st-key-hub_edit_"] button:hover {
        background-color: rgba(255, 255, 255, 0.18) !important;
        border-color: rgba(255, 255, 255, 0.4) !important;
        transition: all 0.2s ease-in-out;
    }

    /* 3. Hover state for "Add to Sync List" (Indigo Theme) */
    div[data-testid="stDialog"] div[class*="st-key-hub_add_"] button:hover {
        background-color: rgba(95, 100, 200, 0.4) !important; 
        border-color: rgba(95, 100, 200, 1) !important; 
        color: #ffffff !important;
        transition: all 0.2s ease-in-out;
    }

    /* 4. Default state for "Delete" (Dark Grey / Recessed) */
    div[data-testid="stDialog"] div[class*="st-key-btn_hub_delete_"] button {
        background-color: rgba(0, 0, 0, 0.25) !important; /* Darker than the card background */
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
        color: rgba(255, 255, 255, 1) !important;
    }

    /* 5. Hover state for "Delete" (Danger Red) */
    div[data-testid="stDialog"] div[class*="st-key-btn_hub_delete_"] button:hover {
        background-color: rgba(255, 75, 75, 0.15) !important;
        border-color: #ff4b4b !important;
        color: #ff4b4b !important;
        transition: all 0.2s ease-in-out;
    }

    /* Compact cards inside Layer 2 */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        padding: 12px 15px !important; 
    }
    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] {
        gap: 0.3rem !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] button {
        min-height: 35px !important;
        padding-top: 0.2rem !important;
        padding-bottom: 0.2rem !important;
    }

    /* Clean positioning for Back buttons (No negative margins needed without the separator) */
    div.st-key-btn_back_to_groups, 
    div.st-key-btn_cancel_add_pair,
    div.st-key-hub_back_l3 {
        margin-bottom: 10px !important; /* Just a little breathing room below them */
        margin-top: -30px !important;
    }

    /* Clean Tertiary Buttons (Universal Lowkey Style) */
    div[data-testid="stDialog"] button[kind="tertiary"] {
        color: rgba(255, 255, 255, 0.75) !important;
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding-left: 0px !important; /* Pull tight to left edge */
    }
    div[data-testid="stDialog"] button[kind="tertiary"]:hover {
        color: rgba(255, 255, 255, 1) !important;
        background-color: transparent !important;
        border: none !important;
    }

    /* Kill the massive margins on the Course Titles (h3) */
    div[data-testid="stDialog"] h3 {
        margin-top: 0px !important;
        margin-bottom: 2px !important;
        padding-bottom: 0px !important;
    }

    /* Pull the folder path text closer to the title and buttons */
    /* Targeting the paragraph that contains our colored span */
    div[data-testid="stDialog"] p:has(span[style*="color: #a3a8b8"]) {
        margin-top: 0px !important;
        margin-bottom: 10px !important; /* Small gap before the action buttons */
    }

    /* Restore breathing room around Add New Course button */
    div[data-testid="stDialog"] div.st-key-btn_hub_add_new_pair {
        margin-top: 25px !important;
        margin-bottom: 10px !important;
    }

    /* 1. Edit Group Meta Box: Subtle grey-yellow background to separate settings from content */
    div.st-key-hub_edit_group_meta {
        background-color: rgba(220, 210, 180, 0.08) !important; /* Soft grey-yellow tint */
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        margin-bottom: 25px !important; /* Extra 10px spacing before the course cards start */
        padding: 15px !important;
    }

    /* =========================================
       LAYER 2: PAIR CARDS & BUTTON HIERARCHY
       ========================================= */

    /* 1. Pair Cards Background (Slightly lighter than before) */
    div[class*="st-key-hub_pair_card_"] {
        background-color: rgba(255, 255, 255, 0.05) !important; /* Elevated base brightness */
        box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.5) !important; 
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        margin-bottom: 15px !important; 
        padding-top: 8px !important; /* Reduced from default padding */
    }

    /* 2. Open Folder & Edit Pair Buttons (Lighter than card) */
    div[data-testid="stDialog"] div[class*="st-key-hub_open_"] button,
    div[data-testid="stDialog"] div[class*="st-key-hub_editp_"] button {
        background-color: rgba(255, 255, 255, 0.08) !important; /* Pops slightly from the 0.05 card */
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        color: #ffffff !important;
    }
    div[data-testid="stDialog"] div[class*="st-key-hub_open_"] button:hover,
    div[data-testid="stDialog"] div[class*="st-key-hub_editp_"] button:hover {
        background-color: rgba(255, 255, 255, 0.16) !important; /* Brighter on hover */
        border-color: rgba(255, 255, 255, 0.4) !important;
        transition: all 0.2s ease-in-out;
    }

    /* 3. Expander (See Configuration) matching Open/Edit buttons */

    /* The outer box gets the border and rounded corners */
    div[class*="st-key-hub_pair_card_"] div[data-testid="stExpander"] details {
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
        border-radius: 6px !important;
        background-color: transparent !important;
        overflow: hidden !important; /* Ensures the summary background respects the rounded corners */
    }

    /* The clickable header gets the button background color, but no outer border */
    div[class*="st-key-hub_pair_card_"] div[data-testid="stExpander"] details summary {
        background-color: rgba(255, 255, 255, 0.09) !important; /* Matches Open/Edit */
        color: #ffffff !important;
        border: none !important; /* Outer details handles the border */
        border-radius: 6px !important;
    }

    /* Hover state for the header */
    div[class*="st-key-hub_pair_card_"] div[data-testid="stExpander"] details summary:hover {
        background-color: rgba(255, 255, 255, 0.16) !important; /* Matches Open/Edit hover */
        transition: all 0.2s ease-in-out;
    }

    /* Subtle separator line between the summary and the content when opened */
    div[class*="st-key-hub_pair_card_"] div[data-testid="stExpander"] details[open] summary {
        border-bottom: 1px solid rgba(255, 255, 255, 0.3) !important;
    }

    /* 4. Remove Button (Recessed Dark Default, Danger on Hover) */
    div[data-testid="stDialog"] div[class*="st-key-btn_hub_remove_pair_"] button {
        background-color: rgba(0, 0, 0, 0.3) !important; /* Darker than the card background */
        color: rgba(255, 255, 255, 1) !important;
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
    }
    div[data-testid="stDialog"] div[class*="st-key-btn_hub_remove_pair_"] button:hover {
        border-color: #ff4b4b !important;
        color: #ff4b4b !important;
        background-color: rgba(255, 75, 75, 0.15) !important;
        transition: all 0.2s ease-in-out;
    }

    /* 5. Add New Course Button: Main theme style but highly transparent */
    div[data-testid="stDialog"] div.st-key-btn_hub_add_new_pair button {
        background-color: rgba(59, 130, 246, 0.1) !important; /* Very faint blue/indigo */
        border: 1px solid rgba(59, 130, 246, 0.3) !important;
        color: #93c5fd !important; /* Light blue text */
        margin-top: 10px !important;
    }
    div[data-testid="stDialog"] div.st-key-btn_hub_add_new_pair button:hover {
        background-color: rgba(59, 130, 246, 0.25) !important;
        border-color: rgba(59, 130, 246, 0.6) !important;
        color: #ffffff !important;
        transition: all 0.2s ease-in-out;
    }

    /* Shrink-wrap the View Mode columns for dynamic 10px spacing */
    div.st-key-hub_group_name_view_row div[data-testid="stHorizontalBlock"] {
        align-items: flex-end !important; /* Bottom align for baseline matching */
        gap: 15px !important; 
    }
    div.st-key-hub_group_name_view_row div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:first-child {
        width: auto !important;
        flex: 0 1 auto !important; /* Fit to text width */
    }
    div.st-key-hub_group_name_view_row div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(2) {
        width: auto !important;
        flex: 0 0 auto !important; /* Fit to button width */
        margin-bottom: -16px !important; /* Push button down 16px to perfectly align with h1 text baseline */
    }

    /* Style the small View Mode Edit button */
    div[data-testid="stDialog"] div.st-key-btn_enable_edit_name button {
        background-color: transparent !important;
        border: 1px solid rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
        opacity: 1 !important;
        padding: 2px 12px !important;
        min-height: 0px !important;
        height: 32px !important; 
    }
    div[data-testid="stDialog"] div.st-key-btn_enable_edit_name button:hover {
        background-color: rgba(255, 255, 255, 0.1) !important;
        color: #ffffff !important;
    }

    /* Elevate Layer 1 Group Cards: Subtle yellowish tint and soft drop shadow */
    div[class*="st-key-hub_overview_group_card_"] {
        background-color: rgba(255, 230, 150, 0.1) !important; /* Warm, subtle yellow tint */
        box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.25) !important; /* Soft depth shadow */
        border: 1px solid rgba(255, 230, 150, 0.3) !important;
        margin-bottom: 15px !important; 
        border-radius: 8px !important; /* Slightly rounded corners for a modern look */
    }

    /* Layer 1 Group Cards Top Padding Fix */
    div[class*="st-key-hub_overview_group_card_"] {
        padding-top: 10px !important; 
    }

    /* =========================================
       LAYER 1: BORDERLESS EXPANDER (Courses List)
       ========================================= */
    /* Remove borders and background from the expander wrapper */
    div[class*="st-key-hub_overview_group_card_"] div[data-testid="stExpander"] details {
        border: none !important;
        background: transparent !important;
        margin-bottom: -5px !important; /* Pull buttons closer to expander */
    }
    
    /* Perfect vertical alignment for arrow and text */
    div[class*="st-key-hub_overview_group_card_"] div[data-testid="stExpander"] details summary {
        padding: 0px !important;
        min-height: 0px !important;
        background: transparent !important;
        border: none !important;
        display: flex !important;
        align-items: center !important; 
        gap: 5px !important; /* Tight 5px gap between arrow and text */
    }
    
    /* Remove native margin that pushes text below the arrow */
    div[class*="st-key-hub_overview_group_card_"] div[data-testid="stExpander"] details summary p {
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        color: #e0e0e0 !important;
        margin: 0px !important; /* Kills the misalignment */
    }
    
    div[class*="st-key-hub_overview_group_card_"] div[data-testid="stExpander"] details summary:hover p {
        color: #ffffff !important;
    }
    
    div[class*="st-key-hub_overview_group_card_"] div[data-testid="stExpander"] details[open] summary {
        border-bottom: none !important;
    }
    
    /* Fix Expanded Content (Top-Left aligned, Solid White text) */
    div[class*="st-key-hub_overview_group_card_"] div[data-testid="stExpander"] details div[data-testid="stExpanderDetails"] {
        padding-left: 0px !important; 
        padding-top: 5px !important;  /* Tighten space below 'x courses' */
        padding-bottom: 15px !important;
    }
    
    div[class*="st-key-hub_overview_group_card_"] div[data-testid="stExpander"] details div[data-testid="stMarkdownContainer"] {
        color: #ffffff !important; /* Force solid white text */
        font-size: 0.9rem !important;
    }
    
    /* Pull bullets left and remove vertical margins */
    div[class*="st-key-hub_overview_group_card_"] div[data-testid="stExpander"] details ul {
        margin-top: 0px !important;
        margin-bottom: 0px !important;
        padding-left: 18px !important; /* Just enough indent to show the bullet */
    }
    /* =========================================
       INLINE ADD CARD BUTTONS (Fixing CSS Specificity)
       ========================================= */
    /* 1. Folder, Course, and Cancel Buttons: Gray default, light gray hover */
    div[data-testid="stDialog"] div.st-key-btn_inline_new_folder button,
    div[data-testid="stDialog"] div.st-key-btn_inline_new_course button,
    div[data-testid="stDialog"] div.st-key-btn_inline_new_cancel button {
        background-color: rgba(255, 255, 255, 0.08) !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        color: #ffffff !important;
    }
    div[data-testid="stDialog"] div.st-key-btn_inline_new_folder button:hover,
    div[data-testid="stDialog"] div.st-key-btn_inline_new_course button:hover,
    div[data-testid="stDialog"] div.st-key-btn_inline_new_cancel button:hover {
        background-color: rgba(255, 255, 255, 0.16) !important;
        border-color: rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }

    /* 2. Add to Group Button: Gray default, Solid Blue hover */
    div[data-testid="stDialog"] div.st-key-btn_inline_new_confirm button {
        background-color: rgba(255, 255, 255, 0.1) !important;
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
        color: #ffffff !important;
    }
    div[data-testid="stDialog"] div.st-key-btn_inline_new_confirm button:hover {
        background-color: #3b82f6 !important; /* Solid Blue */
        border-color: #3b82f6 !important;
        color: #ffffff !important;
    }
    div[data-testid="stDialog"] div.st-key-btn_inline_new_confirm button[disabled] {
        background-color: rgba(0, 0, 0, 0.3) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: rgba(255, 255, 255, 0.3) !important;
    }

    /* (Segmented control CSS removed — replaced by native tab buttons) */

    /* =========================================
       LAYER 1: PAIR CARDS (Single Pairs)
       ========================================= */
    /* Desaturated cool-gray tint (distinct from warm group cards) */
    div[class*="st-key-hub_pair_item_"] {
        background-color: rgba(180, 200, 220, 0.08) !important;
        box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.25) !important;
        border: 1px solid rgba(255, 255, 255, 0.25) !important;
        margin-bottom: 15px !important;
        border-radius: 8px !important;
        padding-top: 10px !important;
    }

    /* =========================================
       INLINE SAVE PAIR BUTTON (ABSOLUTE POSITION)
       ========================================= */
    /* Rip the button out of the layout flow and pin it top-right */
    div[class*="st-key-save_pair_"] {
        position: absolute !important;
        top: 15px !important;
        right: 16px !important;
        margin: 0 !important;
        padding: 0 !important;
        width: auto !important;
        height: 0 !important;          /* Collapse the flex slot */
        overflow: visible !important;   /* But keep the emoji visible */
        z-index: 99;
    }
    
    /* Strip all Streamlit chrome to leave just the emoji */
    div[class*="st-key-save_pair_"] button {
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        min-height: 0 !important;
        height: auto !important;
        font-size: 1.3rem !important;
        line-height: 1 !important;
        transition: transform 0.2s ease;
    }
    
    div[class*="st-key-save_pair_"] button:hover {
        transform: scale(1.15);
        background-color: transparent !important;
        border: none !important;
        color: inherit !important;
    }
    
    div[class*="st-key-save_pair_"] button:disabled {
        opacity: 0.3 !important;
        filter: grayscale(100%);
    }

    /* =========================================
       TAB NAVIGATION STYLING
       ========================================= */
    div.st-key-hub_tabs_container button {
        min-height: 32px !important;
        height: 32px !important;
        padding-top: 2px !important;
        padding-bottom: 2px !important;
        background-color: transparent !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 6px !important;
    }
    div.st-key-hub_tabs_container button p {
        font-size: 0.95rem !important;
    }
    div.st-key-hub_tabs_container button[kind="primary"] {
        background-color: rgba(59, 130, 246, 0.15) !important; /* Soft blue tint */
        border-bottom: 3px solid #3b82f6 !important; /* Classic tab underline */
        color: #ffffff !important;
    }

    /* =========================================
       MAIN SYNC LIST: PAIR CARD CONTAINERS
       ========================================= */
    div[class*="st-key-sync_pair_card_"] {
        background-color: #2d2d2d !important;
        border: 1px solid #444 !important;
        border-radius: 8px !important;
        padding: 5px 12px 20px 12px !important; /* 5px top, 20px bottom for room */
        overflow: visible !important;     /* Prevent text clipping at border */
        position: relative;               /* Anchor for absolute-positioned save button */
    }
    /* Small gap between title and folder/sync text */
    div[class*="st-key-sync_pair_card_"][data-testid="stVerticalBlock"] {
        gap: 10px !important;
        justify-content: flex-start !important;  /* Push content to top */
        align-items: stretch !important;
    }
    /* Missing folder: red border override */
    div[class*="st-key-sync_pair_card_missing_"] {
        border-color: #c0392b !important;
    }

    </style>
    """, unsafe_allow_html=True)


def render_sync_step1(lang: str, fetch_courses_fn, main_placeholder=None):
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
    render_sync_wizard(st, 1, lang)
    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

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

    # --- (8) Bigger subheading + Hub button ---
    col_heading, col_hub = st.columns([0.7, 0.3], vertical_alignment="center")
    with col_heading:
        st.markdown(
            f'<h3 style="margin-top: -10px; margin-bottom: 0px; padding-bottom: 0px;">{get_text("sync_courses_to_sync", lang)}</h3>',
            unsafe_allow_html=True,
        )
    with col_hub:
        if st.button("\U0001F4DA Saved Groups & Pairs", key="btn_hub_main",
                     use_container_width=True):
            st.session_state.setdefault('hub_layer', 'layer_1')
            _saved_groups_hub_dialog(courses, course_names)

    sync_pairs = st.session_state.get('sync_pairs', [])
    pairs_to_remove = []

    # Pre-compute set of already-saved (course_id, local_folder) tuples for inline 💾 button
    from ui_helpers import get_config_dir as _get_config_dir
    _saved_mgr = SavedGroupsManager(_get_config_dir())
    _all_saved_groups = _saved_mgr.load_groups()
    _saved_pair_sigs = set()
    for _sg in _all_saved_groups:
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
        color: #ffffff !important;
        opacity: 1 !important;
    }
    div[class*="st-key-ignored_btn_"] button:not([disabled]) p,
    div[class*="st-key-ignored_btn_"] button:not([disabled]) span {
        color: #ffffff !important;
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
        color: #fff !important;
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
                sm = SyncManager(local_folder, course_id, pair.get('course_name', ''), lang)
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
                    _render_pending_folder_ui(courses, course_names, course_options, lang)
                    # Removed explicit spacer to match list gap via CSS margin-bottom on container
                    continue

                # Use vertical_alignment="center" (Streamlit 1.32+) or rely on CSS above
                # Adjusted ratios: Card takes space, but buttons need room for text now
                col_card, col_open, col_edit, col_ignored, col_remove = st.columns([5, 1.5, 1.1, 1.5, 1.2], gap="small", vertical_alignment="center")

                with col_card:
                    folder_exists = Path(pair['local_folder']).exists()
                    last_synced = pair.get('last_synced')
                    ts_str = (
                        get_text('sync_last_synced', lang, time=last_synced) if last_synced
                        else get_text('sync_never_synced', lang)
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
                        else "Save Pair: Go to 'Saved Groups & Pairs' to quickly add this pair to the sync list in the future"
                    )

                    # Card container with 💾 button INSIDE
                    # Use a different key suffix for missing-folder cards so CSS can apply red border
                    _card_key = f"sync_pair_card_missing_{idx}" if not folder_exists else f"sync_pair_card_{idx}"
                    with st.container(border=True, key=_card_key):
                        # Title rendered first, naturally
                        st.markdown(f"**{get_text('sync_course_prefix', lang)} {display_name}**")
                        # Save button rendered after — CSS absolute-positions it to top-right
                        if st.button("\U0001F4BE", key=f"save_pair_{idx}", disabled=_pair_already_saved,
                                     help=_save_help):
                            _save_pair_dialog(pair)
                        st.markdown(f"""<div style="font-size:0.85em;color:#ccc;margin-top:-5px;">\U0001F4C1 {folder_display}</div>
                            <div style="font-size:0.75em;color:#888;margin-top:2px;">\U0001F553 {ts_str}</div>""", unsafe_allow_html=True)

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

                with col_ignored:
                    ignored_count = len(ignored_by_course.get(pair['course_id'], {}).get('files', []))
                    if st.button(f"🚫 Ignored Files ({ignored_count})", key=f"ignored_btn_{idx}",
                                 disabled=(ignored_count == 0), use_container_width=True):
                        course_data = ignored_by_course[pair['course_id']]
                        _show_course_ignored_files(
                            friendly_course_name(pair['course_name']),
                            pair['course_id'], course_data, lang
                        )

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
                # (9) "Add Course folder" + "Save List as Group" — full width
                col_add, col_save, _ = st.columns([1.5, 1.5, 7], gap="small", vertical_alignment="bottom") 
                with col_add:
                    # Clean, isolated CSS for "Add Course" using its Streamlit key
                    st.markdown("""<style>
                    div.st-key-btn_add_folder button {
                        border: 1px solid #4a7a9b !important;
                        background-color: #2a3a4a !important;
                        color: #cde !important;
                        margin-top: -45px !important;
                        position: relative;
                        z-index: 1;
                    }
                    div.st-key-btn_add_folder button:hover {
                         background-color: #3a4a5a !important;
                         border-color: #6a9abb !important;
                         color: #fff !important;
                    }
                    </style>""", unsafe_allow_html=True)
                    
                    if st.button("➕ " + get_text('sync_add_course_folder', lang), key="btn_add_folder", use_container_width=True):
                        _select_sync_folder()
                        st.session_state['sync_selected_course_id'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.rerun()

                with col_save:
                    # Disable if < 2 pairs or current list matches an already saved group
                    from ui_helpers import get_config_dir
                    _gm = SavedGroupsManager(get_config_dir())
                    _save_disabled = len(sync_pairs) < 2 or _gm.matches_existing_group(sync_pairs)

                    # Clean, isolated CSS for "Save List" using its Streamlit key
                    st.markdown("""<style>
                    div.st-key-btn_save_group_main button {
                        background-color: rgba(95, 100, 200, 0.1) !important;
                        color: #e0e7ff !important;
                        border: 1px solid rgba(95, 100, 200, 0.75) !important;
                    }
                    div.st-key-btn_save_group_main button:hover {
                        background-color: rgba(95, 100, 200, 0.4) !important;
                        border-color: rgba(95, 100, 200, 1) !important;
                        color: #ffffff !important;
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
                _render_pending_folder_ui(courses, course_names, course_options, lang)
            else:
                col_add, _ = st.columns([0.25, 0.75]) 
                with col_add:
                    st.markdown("""
                    <style>
                    /* Scoped to the button's own key — NO :has() to prevent
                       leaking into dialog portals via ancestor climbing */
                    div.st-key-btn_add_folder_empty button {
                        border: 1px solid #4a7a9b !important;
                        background-color: #2a3a4a !important;
                        color: #cde !important;
                    }
                    div.st-key-btn_add_folder_empty button:hover {
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
    # ignored_by_course already computed above the course row loop
    if total_ignored > 0:
        if st.button(f"🚫 Manage All Ignored Files ({total_ignored})", key="btn_manage_ignored", use_container_width=True):
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
            # Nuclear reset of all cancel flags — stale flags from a previous download/sync
            # would break the analysis loop on the very first iteration, producing zero results.
            st.session_state['cancel_requested'] = False
            st.session_state['sync_cancelled'] = False
            st.session_state['sync_cancel_requested'] = False
            st.session_state['download_cancelled'] = False
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


def _render_filetype_selector(all_files, prefix, file_key_fn):
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
def _ignored_files_dialog(ignored_by_course, lang):
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
    _render_filetype_selector(all_file_tuples, "ign_all", lambda f: f)

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
            background-color: #e74c3c !important;
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


def _show_course_ignored_files(course_name, course_id, course_data, lang):
    """Dialog to manage ignored files for a specific course."""
    @st.dialog(f"🚫 Ignored Files: {course_name}", width="large")
    def _dialog():
        _show_course_ignored_files_inner(course_name, course_id, course_data, lang)
    _dialog()

def _show_course_ignored_files_inner(course_name, course_id, course_data, lang):
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
    _render_filetype_selector(all_file_tuples, prefix, lambda f: f)

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
            background-color: #e74c3c !important;
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
        _run_sync(lang)
    elif status == 'sync_cancelled':
        _show_sync_cancelled(lang)
    elif status == 'sync_complete':
        _show_sync_complete(lang)


# ---- Analysis phase ----

def _run_analysis(lang, sync_pairs):
    # Step wizard
    render_sync_wizard(st, 2, lang)

    # Check if only syncing a single pair
    single_idx = st.session_state.get('sync_single_pair_idx')
    if single_idx is not None:
        sync_pairs = [sync_pairs[single_idx]]

    cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'], lang)
    all_results = []
    total_pairs = len(sync_pairs)

    # Clean progress display — no stale cards
    analysis_ui_placeholder = st.empty()
    
    # RENDER GLOBAL CANCEL ABOVE THE ANALYSIS LOOP
    cancel_analysis_placeholder = st.empty()
    if cancel_analysis_placeholder.button(get_text('cancel_download', lang), type="secondary", key="cancel_analysis_btn"):
        cancel_analysis_placeholder.empty()
        st.session_state['cancel_requested'] = True
        st.session_state['download_status'] = 'sync_cancelled'
        st.rerun()

    for pair_num, pair in enumerate(sync_pairs, 1):
        # CHECK FOR CANCEL INSIDE THE LOOP
        if st.session_state.get('cancel_requested', False):
            break
            
        # Folder-not-found guard
        if not Path(pair['local_folder']).exists():
            st.error(get_text('sync_folder_not_found', lang, path=pair['local_folder']))
            continue

        display_name = friendly_course_name(pair['course_name'])
        
        # Define the granular hook for this specific course
        def sync_progress_hook(current, total, status_text):
            try:
                if st.session_state.get('cancel_requested') or st.session_state.get('sync_cancelled'):
                    return
                percent = int((current / total) * 100) if total > 0 else 0
                analysis_ui_placeholder.markdown(f"""
                <div style="background-color: #1A1D27; padding: 20px; border-radius: 8px; border: 1px solid #2D3248; margin-top: 20px; margin-bottom: 20px;">
                    <h4 style="color: #FFFFFF; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                    <p style="color: #8A91A6; font-size: 0.9rem;">Course {pair_num} of {total_pairs}: <b>{display_name}</b></p>
                    <p style="color: #4DA8DA; font-size: 0.8rem; margin-bottom: 5px;">{status_text}</p>
                    <div style="background-color: #2D3248; border-radius: 4px; width: 100%; height: 8px; overflow: hidden;">
                        <div style="background-color: #4DA8DA; width: {percent}%; height: 100%; transition: width 0.1s ease;"></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            except BaseException:
                pass

        local_folder = pair['local_folder']
        course_id = pair['course_id']
        course_name = pair['course_name']

        try:
            sync_progress_hook(0, 1, "Connecting to Canvas API...")
            course = cm.canvas.get_course(course_id)

            sync_mgr = SyncManager(str(local_folder), course_id, course_name, lang)

            sync_progress_hook(0, 1, "Loading local sync manifest...")
            manifest = sync_mgr.load_manifest()
                
            sync_progress_hook(0, 1, "Fetching files from Canvas...")
            canvas_files = cm.get_course_files_metadata(course, progress_callback=sync_progress_hook)
            
            sync_progress_hook(1, 1, "Healing local sync manifest...")
            manifest = sync_mgr.heal_manifest(manifest)
            
            sync_progress_hook(1, 1, "Comparing files...")
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
        except Exception as e:
            import traceback
            import logging
            logger = logging.getLogger(__name__)
            traceback.print_exc()
            logger.error(f"Sync Analysis Error: {str(e)}")
            st.error(f"Error accessing course {display_name}: {e}")
            continue

    # Clean up the UI when all courses are done analyzing
    analysis_ui_placeholder.empty()
    
    st.session_state['sync_analysis_results'] = all_results

    # Quick Sync mode — skip review and go straight to sync
    if st.session_state.get('sync_quick_mode'):
        
        def apply_file_filter(file_list, filter_mode, is_tuple=False):
            if filter_mode == 'all':
                return file_list
            elif filter_mode == 'study':
                allowed_exts = {'.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx'}
                filtered = []
                for item in file_list:
                    # updated_files is a list of tuples: (canvas_file, local_file)
                    f = item[0] if is_tuple else item
                    
                    if hasattr(f, 'canvas_filename'):
                        fname = f.canvas_filename
                    elif hasattr(f, 'filename'):
                        fname = getattr(f, 'display_name', '') or getattr(f, 'filename', '')
                    else:
                        fname = getattr(f, 'display_name', '')
                        
                    if Path(fname).suffix.lower() in allowed_exts:
                        filtered.append(item)
                return filtered
            return file_list

        # Auto-select all new, updated, locally deleted, and missing files
        sync_selections = []
        for idx, res_data in enumerate(all_results):
            result = res_data['result']
            cid = res_data['pair']['course_id']
            
            # --- Load Sync Contract from DB for post-processing settings ---
            # Extract contract for *this specific course*
            _contract = {}
            try:
                _sm = res_data['sync_manager']
                _raw = _sm._load_metadata('sync_contract')
                if _raw:
                    import json
                    _contract = json.loads(_raw)
            except Exception:
                pass  # Fall back to session_state defaults
                
            current_filter = _contract.get('file_filter', 'all')
            
            # Apply the gatekeeper BEFORE execution
            actionable_new = apply_file_filter(result.new_files, current_filter, is_tuple=False)
            actionable_missing = apply_file_filter(result.missing_files, current_filter, is_tuple=False)
            actionable_updated = apply_file_filter(result.updated_files, current_filter, is_tuple=True)
            actionable_del = apply_file_filter(result.locally_deleted_files, current_filter, is_tuple=False)
            
            # Set session state keys for UI consistency (if user goes back)
            # Use cid (course_id) to match the normal Review flow's key pattern
            for f in actionable_new:
                st.session_state[f'sync_new_{cid}_{f.id}'] = True
            for f, _ in actionable_updated:
                st.session_state[f'sync_upd_{cid}_{f.id}'] = True
            for mf in actionable_missing:
                st.session_state[f'sync_miss_{cid}_{mf.canvas_file_id}'] = True
            for si in actionable_del:
                st.session_state[f'sync_locdel_{cid}_{si.canvas_file_id}'] = True
            
            # Combine missing + locally deleted into 'redownload', mirroring the normal
            # Review flow at lines 2299-2304 (selected_miss.extend(selected_locdel))
            redownload_list = list(actionable_missing) + list(actionable_del)
            
            sync_selections.append({
                'pair_idx': idx,
                'res_data': res_data,
                'new': list(actionable_new),
                # Note: updated_files is list of tuples (canvas_file, local_file)
                'updates': [f for f, _ in actionable_updated],
                'redownload': redownload_list,
                'ignore': [],
            })
            
            # -------------------------------------------------------------
            # IMPORTANT: Quick Sync also needs to restore the convert flags 
            # for THIS course into the final execution pipeline. Since we 
            # execute courses sequentially, we need to load them into 
            # persistent_convert_* state vars.
            # 
            # Note: The legacy behavior loaded the contract for the FIRST course 
            # only, which was a bug for multi-course quick sync. We leave the 
            # global state set to the *last* course processed here, since we 
            # don't have per-course post-processing execution logic yet.
            # -------------------------------------------------------------
            
            st.session_state['persistent_convert_zip'] = _contract.get('convert_zip', st.session_state.get('convert_zip', False))
            st.session_state['persistent_convert_pptx'] = _contract.get('convert_pptx', st.session_state.get('convert_pptx', False))
            st.session_state['persistent_convert_html'] = _contract.get('convert_html', st.session_state.get('convert_html', False))
            st.session_state['persistent_convert_code'] = _contract.get('convert_code', st.session_state.get('convert_code', False))
            st.session_state['persistent_convert_urls'] = _contract.get('convert_urls', st.session_state.get('convert_urls', False))
            st.session_state['persistent_convert_word'] = _contract.get('convert_word', st.session_state.get('convert_word', False))
            st.session_state['persistent_convert_video'] = _contract.get('convert_video', st.session_state.get('convert_video', False))
            st.session_state['persistent_convert_excel'] = _contract.get('convert_excel', st.session_state.get('convert_excel', False))
            
        total_count = sum(len(s['new']) + len(s['updates']) + len(s['redownload']) for s in sync_selections)
        
        if total_count == 0:
            # If nothing to sync, just go to analyzed (review) screen to show "Nothing to sync" message
            st.session_state.pop('sync_quick_mode', None)
            st.session_state['download_status'] = 'analyzed'
        else:
            print(f"[DEBUG-QS] total_count={total_count} → jumping to 'syncing'!")
            st.session_state['sync_selections'] = sync_selections
            # Clear the quick-mode flag and jump straight to sync (no confirmation dialog needed)
            st.session_state.pop('sync_quick_mode', None)
            st.session_state['download_status'] = 'syncing'
    else:
        st.session_state['download_status'] = 'analyzed'

    st.rerun()


# ---- Analysis review ----

def _show_analysis_review(lang):
    # Step wizard
    render_sync_wizard(st, 2, lang)

    st.markdown(f"<h3 style='margin-bottom: -15px; margin-top: 10px;'>🔍 {get_text('step4_header', lang)}</h3>", unsafe_allow_html=True)

    from sync_manager import SyncFileInfo, SyncManager

    def handle_ignore(pair_idx, canvas_file_id, source_list_name, item):
        pair_data = st.session_state['sync_analysis_results'][pair_idx]
        sm = SyncManager(pair_data['pair']['local_folder'], pair_data['pair']['course_id'], pair_data['pair']['course_name'])
        # Extract filename for UPSERT (works for new files not yet in DB)
        if isinstance(item, tuple):
            fname = item[0].display_name or item[0].filename if hasattr(item[0], 'filename') else ''
        elif hasattr(item, 'canvas_filename'):
            fname = item.canvas_filename
        elif hasattr(item, 'filename'):
            fname = item.display_name or item.filename
        else:
            fname = ''
        sm.ignore_file(canvas_file_id, fname)
        
        # 1. Safely remove from origin list
        source_list = getattr(pair_data['result'], source_list_name)
        def get_id(x):
            if isinstance(x, tuple): return x[0].id
            elif hasattr(x, 'canvas_file_id'): return x.canvas_file_id
            return x.id
            
        setattr(pair_data['result'], source_list_name, [x for x in source_list if get_id(x) != canvas_file_id])

        if isinstance(item, tuple):
            sync_info = item[1]
        elif hasattr(item, 'canvas_file_id'):
            sync_info = item
        else:
            sync_info = SyncFileInfo(
                canvas_file_id=item.id,
                canvas_filename=item.display_name or item.filename,
                local_path="", canvas_updated_at="", downloaded_at="", original_size=item.size
            )
        sync_info.is_ignored = True
        setattr(sync_info, 'origin_category', source_list_name)
        setattr(sync_info, 'original_item', item)
        
        if not hasattr(pair_data['result'], 'ignored_files'):
            pair_data['result'].ignored_files = []
            
        # 2. Append to ignored list ONLY if not already there
        if not any(f.canvas_file_id == canvas_file_id for f in pair_data['result'].ignored_files):
            pair_data['result'].ignored_files.append(sync_info)

    def handle_restore(pair_idx, sync_info):
        pair_data = st.session_state['sync_analysis_results'][pair_idx]
        sm = SyncManager(pair_data['pair']['local_folder'], pair_data['pair']['course_id'], pair_data['pair']['course_name'])
        sm.restore_file(sync_info.canvas_file_id)
        
        sync_info.is_ignored = False
        
        # 1. Safely remove from ignored_files list
        if hasattr(pair_data['result'], 'ignored_files'):
            pair_data['result'].ignored_files = [f for f in pair_data['result'].ignored_files if f.canvas_file_id != sync_info.canvas_file_id]
            
        origin = getattr(sync_info, 'origin_category', 'missing_files')
        dest_list = getattr(pair_data['result'], origin, pair_data['result'].missing_files)
        original_item = getattr(sync_info, 'original_item', sync_info)
        
        def get_id(x):
            if isinstance(x, tuple): return x[0].id
            elif hasattr(x, 'canvas_file_id'): return x.canvas_file_id
            return x.id
            
        # 2. Append to destination list ONLY if not already there
        if not any(get_id(x) == sync_info.canvas_file_id for x in dest_list):
            dest_list.append(original_item)
        
        prefixes = {
            'new_files': 'sync_new',
            'updated_files': 'sync_upd',
            'missing_files': 'sync_miss',
            'locally_deleted_files': 'sync_locdel'
        }
        prefix = prefixes.get(origin, 'sync_miss')
        st.session_state[f'{prefix}_{pair_data["pair"]["course_id"]}_{sync_info.canvas_file_id}'] = True
        st.session_state['keep_ignored_open'] = True

    def handle_restore_all(pair_idx):
        pair_data = st.session_state['sync_analysis_results'][pair_idx]
        sm = SyncManager(pair_data['pair']['local_folder'], pair_data['pair']['course_id'], pair_data['pair']['course_name'])
        
        if not hasattr(pair_data['result'], 'ignored_files') or not pair_data['result'].ignored_files:
            return
            
        file_ids = [f.canvas_file_id for f in pair_data['result'].ignored_files]
        sm.bulk_restore_files(file_ids)
        
        def get_id(x):
            if isinstance(x, tuple): return x[0].id
            elif hasattr(x, 'canvas_file_id'): return x.canvas_file_id
            return x.id
        
        for sync_info in list(pair_data['result'].ignored_files):
            sync_info.is_ignored = False
            origin = getattr(sync_info, 'origin_category', 'missing_files')
            dest_list = getattr(pair_data['result'], origin, pair_data['result'].missing_files)
            original_item = getattr(sync_info, 'original_item', sync_info)
            
            # append safely
            if not any(get_id(x) == sync_info.canvas_file_id for x in dest_list):
                dest_list.append(original_item)
            
            prefixes = {
                'new_files': 'sync_new',
                'updated_files': 'sync_upd',
                'missing_files': 'sync_miss',
                'locally_deleted_files': 'sync_locdel'
            }
            prefix = prefixes.get(origin, 'sync_miss')
            st.session_state[f'{prefix}_{pair_data["pair"]["course_id"]}_{sync_info.canvas_file_id}'] = True
            
        pair_data['result'].ignored_files.clear()
        st.session_state['keep_ignored_open'] = True

    def handle_sweep(pair_idx, source_list_name, item_key_prefix):
        pair_data = st.session_state['sync_analysis_results'][pair_idx]
        source_list = getattr(pair_data['result'], source_list_name)
        
        def get_id(x):
            if isinstance(x, tuple): return x[0].id
            elif hasattr(x, 'canvas_file_id'): return x.canvas_file_id
            return x.id

        def get_fname(x):
            if isinstance(x, tuple):
                return x[0].display_name or x[0].filename if hasattr(x[0], 'filename') else ''
            elif hasattr(x, 'canvas_filename'):
                return x.canvas_filename
            elif hasattr(x, 'filename'):
                return x.display_name or x.filename
            return ''
            
        items_to_ignore = []
        file_ids_and_names = []
        
        for item in list(source_list):
            fid = get_id(item)
            chk_key = f"{item_key_prefix}_{pair_data['pair']['course_id']}_{fid}"
            if not st.session_state.get(chk_key, True):
                items_to_ignore.append(item)
                file_ids_and_names.append((fid, get_fname(item)))
                
        if not items_to_ignore:
            return
            
        sm = SyncManager(pair_data['pair']['local_folder'], pair_data['pair']['course_id'], pair_data['pair']['course_name'])
        sm.bulk_ignore_files(file_ids_and_names)
        
        if not hasattr(pair_data['result'], 'ignored_files'):
            pair_data['result'].ignored_files = []
        
        # Build lookup set of IDs being ignored (Fix: was undefined — NameError)
        file_ids_to_ignore = {get_id(item) for item in items_to_ignore}
            
        # Rebuild origin list directly safely
        setattr(pair_data['result'], source_list_name, [x for x in source_list if get_id(x) not in file_ids_to_ignore])
            
        for item in items_to_ignore:
            fid = get_id(item)
            if isinstance(item, tuple):
                sync_info = item[1]
            elif hasattr(item, 'canvas_file_id'):
                sync_info = item
            else:
                sync_info = SyncFileInfo(
                    canvas_file_id=item.id,
                    canvas_filename=item.display_name or item.filename,
                    local_path="", canvas_updated_at="", downloaded_at="", original_size=item.size
                )
            sync_info.is_ignored = True
            setattr(sync_info, 'origin_category', source_list_name)
            setattr(sync_info, 'original_item', item)
            
            # append safely
            if not any(f.canvas_file_id == fid for f in pair_data['result'].ignored_files):
                pair_data['result'].ignored_files.append(sync_info)

    st.markdown('''
        <style>
        /* Force Streamlit modal to vertically center */
        div[data-testid="stModal"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            background-color: rgba(0, 0, 0, 0.7) !important;
        }
        div[data-testid="stModal"] > div[role="dialog"] {
            position: relative !important;
            top: 0 !important;
            left: 0 !important;
            transform: none !important;
            margin: auto !important;
            max-width: 480px !important;
            width: 90vw !important;
            border-radius: 20px !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.8) !important;
            background-color: #1a1c1e !important;
            padding: 0 !important;
            overflow: hidden !important;
        }
        /* Make the bulk action buttons inside expanders slightly shorter and subtle */
        [data-testid="stExpanderDetails"] button[kind="secondary"] {
            min-height: 2rem !important;
            padding-top: 0.25rem !important;
            padding-bottom: 0.25rem !important;
        }
        /* Reduce divider vertical margins */
        hr {
            margin-top: 0.5rem !important;
            margin-bottom: 0.5rem !important;
        }
        /* Tightly align the caption */
        .tight-caption p {
            margin-top: 0px !important;
            padding-top: 0px !important;
        }
        </style>
    ''', unsafe_allow_html=True)

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
    total_ignored = sum(len(r['result'].ignored_files) if hasattr(r['result'], 'ignored_files') else 0 for r in all_results)

    st.markdown("""
    <style>
    /* Color-coded expander backgrounds */
    div[class*="st-key-cat_new"] div[data-testid="stExpander"] details summary { background-color: rgba(59, 130, 246, 0.1) !important; }
    div[class*="st-key-cat_update"] div[data-testid="stExpander"] details summary { background-color: rgba(16, 185, 129, 0.1) !important; }
    div[class*="st-key-cat_missing"] div[data-testid="stExpander"] details summary { background-color: rgba(245, 158, 11, 0.1) !important; }
    div[class*="st-key-cat_deleted_local"] div[data-testid="stExpander"] details summary { background-color: rgba(139, 92, 246, 0.1) !important; }
    div[class*="st-key-cat_deleted_canvas"] div[data-testid="stExpander"] details summary { background-color: rgba(239, 68, 68, 0.1) !important; }

    div[class*="st-key-cat_new"] div[data-testid="stExpander"] details { border: 1px solid rgba(59, 130, 246, 0.4) !important; }
    div[class*="st-key-cat_update"] div[data-testid="stExpander"] details { border: 1px solid rgba(16, 185, 129, 0.4) !important; }
    div[class*="st-key-cat_missing"] div[data-testid="stExpander"] details { border: 1px solid rgba(245, 158, 11, 0.4) !important; }
    div[class*="st-key-cat_deleted_local"] div[data-testid="stExpander"] details { border: 1px solid rgba(167, 139, 250, 0.4) !important; } 
    div[class*="st-key-cat_deleted_canvas"] div[data-testid="stExpander"] details { border: 1px solid rgba(239, 68, 68, 0.4) !important; }

    /* The 'Guy in the Corner' Ignored Files styling */
    div[class*="st-key-cat_ignored"] div[data-testid="stExpander"] details summary { 
        background-color: rgba(20, 20, 20, 0.3) !important; 
        border: 1px dashed #4B5563 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Summary logic
    if total_new > 0 or total_upd > 0 or total_miss > 0 or total_del > 0 or total_loc_del > 0 or total_ignored > 0:
        
        sum_cols = st.columns([3, 2])
        with sum_cols[0]:
            c1, c2, c3, c4, c5 = st.columns(5)
            
            # Determine labels safely based on lang
            lbl_new = get_text('new_files', lang) if 'new_files' in get_text.__code__.co_consts else ("Nye filer" if lang == 'da' else "New files")
            lbl_upd = "Opdateringer" if lang == 'da' else "Updates available"
            lbl_miss = "Manglende filer" if lang == 'da' else "Missing files"
            lbl_loc_del = "Slettet lokalt" if lang == 'da' else "Deleted locally"
            lbl_del = "Slettet på Canvas" if lang == 'da' else "Deleted on Canvas"

            def _render_metric_card(val, lbl, icon, hex_start, hex_end, shadow_color):
                base_card_css = "border-radius:12px; padding:18px 14px; position:relative; overflow:hidden; min-height: 95px; transition: all 0.2s ease-in-out;"
                
                if val > 0:
                    bg_style = f"background: linear-gradient(135deg, {hex_start}, {hex_end}); box-shadow: 0 10px 20px -5px {shadow_color}; border: 1px solid transparent;"
                    text_opacity = "1"
                    icon_bg = "rgba(0,0,0,0.15)"
                else:
                    # Muted state: 10% opacity gradient, 25% opacity border, 50% text opacity
                    bg_style = f"background: linear-gradient(135deg, {hex_start}1A, {hex_end}1A); border: 1px solid {hex_start}40; box-shadow: none;"
                    text_opacity = "0.5"
                    icon_bg = f"{hex_start}26"

                icon_css = f"position:absolute; top:14px; right:14px; background:{icon_bg}; border-radius:10px; width:42px; height:42px; display:flex; align-items:center; justify-content:center; font-size:1.5em; opacity: {text_opacity};"
                num_css = f"font-size:2.7em; font-weight:700; color:rgba(255,255,255,{text_opacity}); line-height:1;"
                lbl_css = f"font-size:0.95em; color:rgba(255,255,255,{text_opacity}); font-weight:500; margin-top:8px; line-height:1.2; word-wrap:break-word;"

                return f'''
                <div style="{base_card_css} {bg_style}">
                    <div style="{num_css}">{val}</div>
                    <div style="{lbl_css}">{lbl}</div>
                    <div style="{icon_css}">{icon}</div>
                </div>
                '''

            with c1:
                st.markdown(_render_metric_card(total_new, lbl_new, "📄", "#4a90e2", "#2980b9", "rgba(74, 144, 226, 0.35)"), unsafe_allow_html=True)
            with c2:
                st.markdown(_render_metric_card(total_upd, lbl_upd, "🔄", "#2ecc71", "#27ae60", "rgba(46, 204, 113, 0.35)"), unsafe_allow_html=True)
            with c3:
                st.markdown(_render_metric_card(total_miss, lbl_miss, "⚠️", "#f1c40f", "#e67e22", "rgba(241, 196, 15, 0.35)"), unsafe_allow_html=True)
            with c4:
                st.markdown(_render_metric_card(total_loc_del, lbl_loc_del, "✂️", "#9b59b6", "#8e44ad", "rgba(155, 89, 182, 0.35)"), unsafe_allow_html=True)
            with c5:
                st.markdown(_render_metric_card(total_del, lbl_del, "🗑️", "#e74c3c", "#c0392b", "rgba(231, 76, 60, 0.35)"), unsafe_allow_html=True)
                
        st.markdown("<div style='margin-bottom: 25px;'></div>", unsafe_allow_html=True)

        # --- NotebookLM Compatible Download Toggle (Sync Mode) ---
        TOTAL_NOTEBOOK_SUBS = 8



    # Nothing to sync
    if total_new == 0 and total_upd == 0 and total_miss == 0 and total_del == 0 and total_loc_del == 0 and total_ignored == 0:
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
        cid = res_data['pair']['course_id']
        for f in res.new_files:
            ext = os.path.splitext(f.filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_new_{cid}_{f.id}')
        for f, _ in res.updated_files:
            ext = os.path.splitext(f.filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_upd_{cid}_{f.id}')
        for si in res.missing_files:
            ext = os.path.splitext(si.canvas_filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_miss_{cid}_{si.canvas_file_id}')
        for si in res.locally_deleted_files:
            ext = os.path.splitext(si.canvas_filename)[1].lower() or "Unknown"
            all_extensions.add(ext)
            files_by_ext[ext].append(f'sync_locdel_{cid}_{si.canvas_file_id}')

    if all_extensions:
        all_exts_sorted = sorted(list(all_extensions))
        
        if 'sync_filter_all_exts' not in st.session_state:
            st.session_state['sync_filter_all_exts'] = True

        def toggle_all_exts():
            if st.session_state.get('sync_filter_all_exts', True):
                for ext in all_exts_sorted:
                    st.session_state[f"sync_filter_ext_{ext}"] = True
                    for file_key in files_by_ext[ext]:
                        if file_key.startswith('sync_'):
                            st.session_state[file_key] = True
        
        def toggle_single_ext(ext_name):
            new_state = st.session_state.get(f'sync_filter_ext_{ext_name}', True)
            ext_files = [k for k in files_by_ext[ext_name] if k.startswith('sync_')]
            for file_key in ext_files:
                st.session_state[file_key] = new_state
            
            if not new_state:
                st.session_state['sync_filter_all_exts'] = False

        st.markdown("""
        <style>
        /* 1. Squeeze the row boundaries to absolute minimums */
        div[class*="st-key-sync_review_file_list"] div[data-testid="stHorizontalBlock"] {
            border-bottom: 1px dashed #3A415A !important;
            padding-top: 0px !important;      
            padding-bottom: 2px !important;   
            margin-bottom: 0px !important;    
            min-height: 0px !important;
            align-items: center !important; 
        }

        /* 2. Completely eliminate gap between rows */
        div[class*="st-key-sync_review_file_list"] > div[data-testid="stVerticalBlock"] {
            gap: 0px !important; 
        }

        /* 3. OVERRIDE STREAMLIT'S INVISIBLE MIN-HEIGHTS ON WIDGETS */
        div[class*="st-key-sync_review_file_list"] div[data-testid="stHorizontalBlock"] div[data-testid="stElementContainer"],
        div[class*="st-key-sync_review_file_list"] div[data-testid="stHorizontalBlock"] div[data-testid="stMarkdownContainer"],
        div[class*="st-key-sync_review_file_list"] div[data-testid="stHorizontalBlock"] div[data-testid="stCheckbox"],
        div[class*="st-key-sync_review_file_list"] div[data-testid="stHorizontalBlock"] label {
            margin: 0 !important;
            padding: 0 !important;
            min-height: 0 !important; /* Kills the dead space forcing the row open */
        }

        /* 4. Compress the button's vertical footprint */
        div[class*="st-key-sync_review_file_list"] div[data-testid="stHorizontalBlock"] button {
            margin: 0 !important;
            min-height: 1.8rem !important; /* Shrinks the button's invisible boundary */
            padding-top: 0 !important;
            padding-bottom: 0 !important;
        }

        /* Original 1. Remove border and padding from the container */
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
            margin-top: -3px !important;
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
                st.markdown("<h3 style='margin-top: 0px; margin-bottom: 15px;'>Bulk Selection Tools</h3>", unsafe_allow_html=True)
                include_all = st.checkbox("Include ALL filetypes", key="sync_filter_all_exts", on_change=toggle_all_exts)
                
                if all_exts_sorted:
                    st.markdown("<hr style='margin-top: 10px; margin-bottom: 15px; border-color: #2D3248;' />", unsafe_allow_html=True)
                    st.markdown("<div style='font-size: 0.95em; padding-bottom: 10px; margin-top: 12px; font-weight: bold;'>Or select specific types:</div>", unsafe_allow_html=True)
                    
                    with st.container(border=True, key="filetypes_flex_box"):
                        safe_len = min(len(all_exts_sorted), 90)
                        cols = st.columns(safe_len)
                        for i, ext in enumerate(all_exts_sorted):
                            col_idx = i % safe_len
                            ext_files = [k for k in files_by_ext[ext] if k.startswith('sync_')]
                            total_ext_files = len(ext_files)
                            
                            if total_ext_files > 0:
                                selected_ext_files = sum(1 for k in ext_files if st.session_state.get(k, True))
                                expected_val = True if selected_ext_files > 0 else False
                                
                                if 0 < selected_ext_files < total_ext_files:
                                    ext_label = f"{ext} :gray[({selected_ext_files}/{total_ext_files})]"
                                else:
                                    ext_label = f"{ext}"
                            else:
                                expected_val = False
                                ext_label = f"{ext}"
                                
                            ext_key = f"sync_filter_ext_{ext}"
                            if ext_key not in st.session_state or st.session_state[ext_key] != expected_val:
                                st.session_state[ext_key] = expected_val
                                
                            with cols[col_idx]:
                                st.checkbox(ext_label, key=ext_key, disabled=include_all, on_change=toggle_single_ext, kwargs={'ext_name': ext})

                # Global Select All / Deselect All
                st.markdown("""
                <style>
                /* Force top margin on the button row wrapper */
                .st-key-bulk_action_buttons {
                    margin-top: 10px !important;
                }
                </style>
                """, unsafe_allow_html=True)

                with st.container(key="bulk_action_buttons"):
                    btn_col1, btn_col2 = st.columns(2)
                    with btn_col1:
                        if st.button("Select All Files", type="primary", use_container_width=True):
                            for k in sum(files_by_ext.values(), []):
                                if k.startswith('sync_locdel_'):
                                    ignore_key = k.replace('sync_locdel_', 'ignore_')
                                    if st.session_state.get(ignore_key, False):
                                        continue
                                st.session_state[k] = True
                            st.rerun()
                    with btn_col2:
                        if st.button("Deselect All Files", use_container_width=True):
                            for k in sum(files_by_ext.values(), []):
                                st.session_state[k] = False
                            st.rerun()

    # Per-folder results
    for idx, res_data in enumerate(all_results):
        with st.container(border=True):
            pair = res_data['pair']
            result = res_data['result']

            display_name = friendly_course_name(pair['course_name'])
            folder_display = short_path(pair['local_folder'])

            has_changes = result.new_files or result.updated_files or result.missing_files or result.deleted_on_canvas or result.locally_deleted_files
            
            # Build up-to-date status
            # Strictly use uptodate_files only — do NOT add untracked_shortcuts
            # as those are already counted in new_files or other actionable categories
            uptodate_count = len(result.uptodate_files)
            status_pill = ""
            if uptodate_count:
                uptodate_label = get_text('sync_files_uptodate_count', lang, count=uptodate_count,
                                          file_word=pluralize(uptodate_count, 'file', lang))
                uptodate_label = uptodate_label.lstrip('✅ ')
                status_pill = f'<span style="font-size: 0.75rem; color: #4ade80; background-color: rgba(74, 222, 128, 0.1); padding: 2px 8px; border-radius: 4px; margin-left: 12px; font-weight: normal;">✅ {uptodate_label}</span>'

            # 2. THE FLUSH HEADER BAND (Negative Margin Bleed Trick)
            header_html = f"""
            <div style="
                margin: -16px -16px 4px -16px; /* Reduced bottom margin from 16px to 4px to pull expanders UP */
                padding: 10px 16px; /* Tightened vertical padding to make the header slimmer */
                background-color: #2A2E3D; 
                border: 1px solid #4B5563; 
                border-bottom: 1px solid #4B5563; 
                border-radius: 8px 8px 0 0;
            ">
                <h4 style="margin: 0px 0px 2px 0px; font-weight: 600; font-size: 1.05rem; color: #ffffff;">
                    <span style="color: #60A5FA; margin-right: 4px;">{idx + 1}.</span>📁 {display_name} 
                    {status_pill}
                </h4>
                <p style="margin: 0px; color: #8A91A6; font-size: 0.8rem;">{folder_display}</p>
            </div>
            """
            st.markdown(header_html, unsafe_allow_html=True)

            has_new = bool(result.new_files)
            has_updated = bool(result.updated_files)
            has_missing = bool(result.missing_files)
            has_locally_deleted = bool(result.locally_deleted_files)
            has_ignored = hasattr(result, 'ignored_files') and bool(result.ignored_files)

            if not any([has_new, has_updated, has_missing, has_locally_deleted]) and not has_ignored:
                st.success(get_text('sync_no_changes_course', lang))
                continue



            # New files — always starts OPEN
            if result.new_files:
                total_new = len(result.new_files)
                selected_new = sum(1 for f in result.new_files if st.session_state.get(f"sync_new_{pair['course_id']}_{f.id}", True))
                
                st.markdown(f"""
                <style>
                div[class*="st-key-cat_new_{pair['course_id']}"] div[data-testid="stExpander"] details summary p::after {{
                    content: "\\00a0\\00a0 {selected_new} / {total_new} selected";
                    color: #8A91A6;
                    font-weight: normal;
                    font-size: 0.9rem;
                }}
                </style>
                """, unsafe_allow_html=True)

                with st.container(key=f"cat_new_{pair['course_id']}"):
                    with st.expander(f"🆕 {get_text('new_files', lang)}"):
                        st.button("🧹 Ignore Unchecked", key=f"sweep_new_{pair['course_id']}", use_container_width=True, on_click=handle_sweep, args=(idx, 'new_files', 'sync_new'), help="Ignore all files in this section that are currently unchecked")
                        
                        with st.container(key=f"sync_review_file_list_{idx}_new"):
                            for file in result.new_files:
                                ext = os.path.splitext(file.filename)[1].lower() or "Unknown"
                                icon = get_file_icon(file.filename)
                                size = format_file_size(file.size) if file.size else ""
                                key = f"sync_new_{pair['course_id']}_{file.id}"
                                if key not in st.session_state:
                                    st.session_state[key] = True
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    st.checkbox(f"{icon} {unquote_plus(file.display_name or file.filename)} ({size})", key=key)
                                with col2:
                                    st.button("🚫", key=f"ign_new_{pair['course_id']}_{file.id}", help="Ignore this file", on_click=handle_ignore, args=(idx, file.id, 'new_files', file))

            # Updated files — always starts OPEN
            if result.updated_files:
                total_upd = len(result.updated_files)
                selected_upd = sum(1 for f, _ in result.updated_files if st.session_state.get(f"sync_upd_{pair['course_id']}_{f.id}", True))
                
                st.markdown(f"""
                <style>
                div[class*="st-key-cat_update_{pair['course_id']}"] div[data-testid="stExpander"] details summary p::after {{
                    content: "\\00a0\\00a0 {selected_upd} / {total_upd} selected";
                    color: #8A91A6;
                    font-weight: normal;
                    font-size: 0.9rem;
                }}
                </style>
                """, unsafe_allow_html=True)

                with st.container(key=f"cat_update_{pair['course_id']}"):
                    with st.expander(f"🔄 {get_text('updated_files', lang)}"):
                        st.button("🧹 Ignore Unchecked", key=f"sweep_upd_{pair['course_id']}", use_container_width=True, on_click=handle_sweep, args=(idx, 'updated_files', 'sync_upd'), help="Ignore all files in this section that are currently unchecked")
                        
                        with st.container(key=f"sync_review_file_list_{idx}_upd"):
                            for canvas_file, sync_info in result.updated_files:
                                ext = os.path.splitext(canvas_file.filename)[1].lower() or "Unknown"
                                icon = get_file_icon(canvas_file.filename)
                                size = format_file_size(canvas_file.size) if canvas_file.size else ""
                                key = f"sync_upd_{pair['course_id']}_{canvas_file.id}"
                                if key not in st.session_state:
                                    st.session_state[key] = True
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    st.checkbox(f"{icon} {unquote_plus(canvas_file.display_name or canvas_file.filename)} ({size})", key=key)
                                with col2:
                                    st.button("🚫", key=f"ign_upd_{pair['course_id']}_{canvas_file.id}", help="Ignore this file", on_click=handle_ignore, args=(idx, canvas_file.id, 'updated_files', (canvas_file, sync_info)))

            # Missing files — always starts OPEN
            if result.missing_files:
                total_miss = len(result.missing_files)
                selected_miss = sum(1 for f in result.missing_files if st.session_state.get(f"sync_miss_{pair['course_id']}_{f.canvas_file_id}", True))
                
                st.markdown(f"""
                <style>
                div[class*="st-key-cat_missing_{pair['course_id']}"] div[data-testid="stExpander"] details summary p::after {{
                    content: "\\00a0\\00a0 {selected_miss} / {total_miss} selected";
                    color: #8A91A6;
                    font-weight: normal;
                    font-size: 0.9rem;
                }}
                </style>
                """, unsafe_allow_html=True)

                with st.container(key=f"cat_missing_{pair['course_id']}"):
                    with st.expander(f"📦 {get_text('missing_files', lang)}"):
                        st.button("🧹 Ignore Unchecked", key=f"sweep_miss_{pair['course_id']}", use_container_width=True, on_click=handle_sweep, args=(idx, 'missing_files', 'sync_miss'), help="Ignore all files in this section that are currently unchecked")
                        
                        with st.container(key=f"sync_review_file_list_{idx}_miss"):
                            for sync_info in result.missing_files:
                                ext = os.path.splitext(sync_info.canvas_filename)[1].lower() or "Unknown"
                                icon = get_file_icon(sync_info.canvas_filename)
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    key = f"sync_miss_{pair['course_id']}_{sync_info.canvas_file_id}"
                                    if key not in st.session_state:
                                        st.session_state[key] = True
                                    st.checkbox(f"{icon} {unquote_plus(sync_info.canvas_filename)}", key=key)
                                with col2:
                                    st.button("🚫", key=f"ign_miss_{pair['course_id']}_{sync_info.canvas_file_id}", help="Ignore this file", on_click=handle_ignore, args=(idx, sync_info.canvas_file_id, 'missing_files', sync_info))

            # Locally Deleted Files (Student deleted locally to save space)
            if result.locally_deleted_files:
                total_locdel = len(result.locally_deleted_files)
                selected_locdel = sum(1 for f in result.locally_deleted_files if st.session_state.get(f"sync_locdel_{pair['course_id']}_{f.canvas_file_id}", True))
                
                st.markdown(f"""
                <style>
                div[class*="st-key-cat_deleted_local_{pair['course_id']}"] div[data-testid="stExpander"] details summary p::after {{
                    content: "\\00a0\\00a0 {selected_locdel} / {total_locdel} selected";
                    color: #8A91A6;
                    font-weight: normal;
                    font-size: 0.9rem;
                }}
                </style>
                """, unsafe_allow_html=True)

                with st.container(key=f"cat_deleted_local_{pair['course_id']}"):
                    with st.expander("✂️ Locally Deleted"):
                        st.button("🧹 Ignore Unchecked", key=f"sweep_locdel_{pair['course_id']}", use_container_width=True, on_click=handle_sweep, args=(idx, 'locally_deleted_files', 'sync_locdel'), help="Ignore all files in this section that are currently unchecked")
                        
                        with st.container(key=f"sync_review_file_list_{idx}_locdel"):
                            for sync_info in result.locally_deleted_files:
                                ext = os.path.splitext(sync_info.canvas_filename)[1].lower() or "Unknown"
                                icon = get_file_icon(sync_info.canvas_filename)
                                key = f"sync_locdel_{pair['course_id']}_{sync_info.canvas_file_id}"
                                
                                if key not in st.session_state:
                                    st.session_state[key] = True
                                    
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    st.checkbox(f"{icon} {unquote_plus(sync_info.canvas_filename)}", key=key)
                                with col2:
                                    st.button("🚫", key=f"ign_locdel_{pair['course_id']}_{sync_info.canvas_file_id}", help="Ignore this file", on_click=handle_ignore, args=(idx, sync_info.canvas_file_id, 'locally_deleted_files', sync_info))

            # Deleted files — always starts OPEN
            if result.deleted_on_canvas:
                lbl_del = "Slettet på Canvas (Ignoreret)" if lang == 'da' else "Deleted on Canvas (Ignored)"
                total_del_canvas = len(result.deleted_on_canvas)
                
                st.markdown(f"""
                <style>
                div[class*="st-key-cat_deleted_canvas_{pair['course_id']}"] div[data-testid="stExpander"] details summary p::after {{
                    content: "\\00a0\\00a0 ({total_del_canvas})";
                    color: #8A91A6;
                    font-weight: normal;
                    font-size: 0.9rem;
                }}
                </style>
                """, unsafe_allow_html=True)

                with st.container(key=f"cat_deleted_canvas_{pair['course_id']}"):
                    with st.expander(f"🗑️ {lbl_del}"):
                        st.caption("These files were deleted by the teacher on Canvas. They are preserved locally for your safety.")
                        for sync_info in result.deleted_on_canvas:
                            icon = get_file_icon(sync_info.canvas_filename)
                            st.markdown(f"<div style='color:#8A91A6; font-size:0.9em; padding:4px 0;'>{icon} &nbsp; {unquote_plus(sync_info.canvas_filename)}</div>", unsafe_allow_html=True)

            # Ignored files Bucket
            if hasattr(result, 'ignored_files') and result.ignored_files:
                is_ignored_open = st.session_state.get('keep_ignored_open', False)
                st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True) # The physical isolation gap
                with st.container(key=f"cat_ignored_{pair['course_id']}"):
                    with st.expander(f"🚫 Ignored files &nbsp; :gray[({len(result.ignored_files)})]", expanded=is_ignored_open):
                        st.session_state['keep_ignored_open'] = False
                        st.button("↩️ Restore All Ignored Files", key=f"restore_all_{pair['course_id']}", use_container_width=True, on_click=handle_restore_all, args=(idx,))
                        st.caption("These files are safely ignored and will not be synced.")
                        with st.container(key=f"sync_review_file_list_{idx}_ign"):
                            for sync_info in result.ignored_files:
                                icon = get_file_icon(sync_info.canvas_filename)
                                col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")
                                with col1:
                                    st.markdown(f"<div style='color:#8A91A6; font-size:0.9em; padding:4px 0;'>{icon} &nbsp; {unquote_plus(sync_info.canvas_filename)}</div>", unsafe_allow_html=True)
                                with col2:
                                    st.button("↩️", key=f"restore_{pair['course_id']}_{sync_info.canvas_file_id}", help="Restore this file to the sync queue", on_click=handle_restore, args=(idx, sync_info))
            
            # Inject 20px gap BETWEEN courses, inside the loop but outside the course's content
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    
    # --- Load Sync Contract defaults for first render ---
    # Only pre-fill if the convert_* keys haven't been set yet in this session.
    # This ensures the checkboxes reflect the DB contract on first load,
    # but user changes within the session are preserved across reruns.
    if '_sync_contract_loaded' not in st.session_state:
        _review_contract = {}
        try:
            if all_results:
                _first_pair = all_results[0]['pair']
                _sm = SyncManager(_first_pair['local_folder'], _first_pair['course_id'], _first_pair['course_name'])
                _raw_contract = _sm._load_metadata('sync_contract')
                if _raw_contract:
                    import json
                    _review_contract = json.loads(_raw_contract)
        except Exception:
            pass
        if _review_contract:
            for _key in ['convert_zip', 'convert_pptx', 'convert_html', 'convert_code',
                         'convert_urls', 'convert_word', 'convert_video', 'convert_excel']:
                # Overwrite directly to wipe any leftover state from previous syncs
                st.session_state[_key] = _review_contract.get(_key, False)
            st.session_state['file_filter'] = _review_contract.get('file_filter', 'all')
            # Also sync the master toggle
            _any_active = any(st.session_state.get(k, False) for k in
                              ['convert_zip', 'convert_pptx', 'convert_html', 'convert_code',
                               'convert_urls', 'convert_word', 'convert_video', 'convert_excel'])
            st.session_state['notebooklm_master'] = all(
                st.session_state.get(k, False) for k in
                ['convert_zip', 'convert_pptx', 'convert_html', 'convert_code',
                 'convert_urls', 'convert_word', 'convert_video', 'convert_excel']
            )
        st.session_state['_sync_contract_loaded'] = True

    TOTAL_NOTEBOOK_SUBS = 8

    def _sync_master_toggle_changed():
        st.session_state['convert_zip'] = st.session_state['notebooklm_master']
        st.session_state['convert_pptx'] = st.session_state['notebooklm_master']
        st.session_state['convert_html'] = st.session_state['notebooklm_master']
        st.session_state['convert_code'] = st.session_state['notebooklm_master']
        st.session_state['convert_urls'] = st.session_state['notebooklm_master']
        st.session_state['convert_word'] = st.session_state['notebooklm_master']
        st.session_state['convert_video'] = st.session_state['notebooklm_master']
        st.session_state['convert_excel'] = st.session_state['notebooklm_master']
    
    def _sync_sub_toggle_changed():
        active_subs = sum([st.session_state.get('convert_zip', False), st.session_state.get('convert_pptx', False), st.session_state.get('convert_html', False), st.session_state.get('convert_code', False), st.session_state.get('convert_urls', False), st.session_state.get('convert_word', False), st.session_state.get('convert_video', False), st.session_state.get('convert_excel', False)])
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
        border-left: 2px solid #3E4353 !important; 
        margin-top: -12px !important; 
        padding-top: 4px !important;
        padding-bottom: 4px !important;
    }
    .st-key-convert_zip { margin-top: 0px !important; padding-top: 8px !important; }
    .st-key-convert_video { margin-bottom: 10px !important; padding-bottom: 8px !important; }
    </style>
    """, unsafe_allow_html=True)

    # Use the existing translation key but prepend the emoji
    expander_title = "🛠️ File Format Sync Settings"
    with st.expander(expander_title, expanded=False):
        current_active = sum([st.session_state.get('convert_zip', False), st.session_state.get('convert_pptx', False), st.session_state.get('convert_html', False), st.session_state.get('convert_code', False), st.session_state.get('convert_urls', False), st.session_state.get('convert_word', False), st.session_state.get('convert_video', False), st.session_state.get('convert_excel', False)])

        st.checkbox(
            f"**NotebookLM Compatible Sync** &nbsp; :gray[({current_active}/{TOTAL_NOTEBOOK_SUBS})]",
            key="notebooklm_master",
            on_change=_sync_master_toggle_changed,
            help="Automatically converts downloaded files to formats compatible with Google NotebookLM."
        )
        
        st.checkbox(
            "Auto-Extract Archives (.zip, .tar.gz)",
            key="convert_zip",
            on_change=_sync_sub_toggle_changed,
            help="Extracts internal files from archives so downstream tools can ingest them. Stubs the archive file to skip next sync."
        )
        st.checkbox(
            "Convert PowerPoints to PDF",
            key="convert_pptx",
            on_change=_sync_sub_toggle_changed,
            help="Converts .pptx/.ppt files to PDF after sync using Microsoft Office. Requires PowerPoint installed."
        )
        st.checkbox(
            "Convert Old Word Docs (.doc, .rtf) to PDF",
            key="convert_word",
            on_change=_sync_sub_toggle_changed,
            help="Converts legacy Word documents to PDF for accurate NotebookLM ingestion using Microsoft Office. Modern .docx are ignored."
        )
        st.checkbox(
            "Convert Excel Files (.xlsx, .xls) to PDF",
            key="convert_excel",
            on_change=_sync_sub_toggle_changed,
            help="Converts Excel workbooks to PDF. Restructures PageSetup to ensure tabular content is 1 page wide and infinitely tall."
        )
        st.checkbox(
            "Convert Canvas Pages (HTML) to Markdown",
            key="convert_html",
            on_change=_sync_sub_toggle_changed,
            help="Converts Canvas Pages from HTML to clean Markdown formats."
        )
        st.checkbox(
            "Convert Code & Data Files to .txt",
            key="convert_code",
            on_change=_sync_sub_toggle_changed,
            help="Appends a .txt extension to programming files (e.g., .py, .java, .csv, .json) to ensure they can be read by NotebookLM."
        )
        st.checkbox(
            "Compile Web Links (.url) into a single list",
            key="convert_urls",
            on_change=_sync_sub_toggle_changed,
            help="Scans for downloaded web/video shortcuts and securely extracts all URLs into a master NotebookLM text file."
        )
        st.checkbox(
            "Extract Audio (.mp3) from Videos (.mp4, .mov)",
            key="convert_video",
            on_change=_sync_sub_toggle_changed,
            help="Converts video formats (.mp4, .mov, .mkv) into .mp3 format for ingestion into Google NotebookLM. Drops original video size."
        )

    st.markdown("""
        <hr style="
            margin-top: 25px; 
            margin-bottom: 30px; 
            border: 0; 
            border-top: 1px solid #475569;
        ">
    """, unsafe_allow_html=True)

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    # --- Action buttons (Sync left, Back right) ---
    total_active_files = sum(len(pd['result'].new_files) + len(pd['result'].updated_files) + len(pd['result'].missing_files) + len(pd['result'].locally_deleted_files) for pd in all_results)
    
    if total_active_files == 0:
        st.success("All pending files have been addressed or ignored. You are fully up to date!")
        if st.button("Done - Return to Front Page", type="primary", use_container_width=True):
            _cleanup_sync_state()
            st.rerun()
    else:

        col_sync, col_back, _ = st.columns([1.2, 1, 5])
        with col_sync:
            if st.button(get_text('sync_selected', lang), type="primary", use_container_width=True):
                # Collect selections
                sync_selections = []
                for idx, res_data in enumerate(all_results):
                    result = res_data['result']
                    cid = res_data['pair']['course_id']
                    selected_new = [
                        f for f in result.new_files
                        if st.session_state.get(f'sync_new_{cid}_{f.id}', True)
                    ]
                    selected_upd = [
                        f for f, _ in result.updated_files
                        if st.session_state.get(f'sync_upd_{cid}_{f.id}', True)
                    ]
                    selected_miss = [
                        si for si in result.missing_files
                        if st.session_state.get(f'sync_miss_{cid}_{si.canvas_file_id}', False)
                    ]
                    selected_locdel = [
                        si for si in result.locally_deleted_files
                        if st.session_state.get(f'sync_locdel_{cid}_{si.canvas_file_id}', False)
                    ]
                    # Combine both missing and locally deleted files that the user opted to redownload
                    selected_miss.extend(selected_locdel)
                                       
                    sync_selections.append({
                        'pair_idx': idx,
                        'res_data': res_data,
                        'new': selected_new,
                        'updates': selected_upd,
                        'redownload': selected_miss,
                        'ignore': [], # Let it pass empty, ignore was handled by immediate DB updates
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
            # Replace + with space using unquote_plus
            unquoted = urllib.parse.unquote_plus(name)
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
            f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">'
            f'<div style="font-weight: 600; color: #e2e8f0; white-space: nowrap;">📁 Destination:</div>'
            f'<div title="{sorted_folders[0]}" style="text-align: right; font-weight: 600; color: #f8fafc; max-width: 60%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">'
            f'{sorted_folders[0]}'
            f'</div>'
            f'</div>'
        )

    html_content = (
        f'<style>'
        f'/* Override modal styles */'
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
            # Task 1: Save the State on Button Click (Streamlit Widget Cleanup Fix)
            st.session_state['persistent_convert_zip'] = st.session_state.get('convert_zip', False)
            st.session_state['persistent_convert_pptx'] = st.session_state.get('convert_pptx', False)
            st.session_state['persistent_convert_html'] = st.session_state.get('convert_html', False)
            st.session_state['persistent_convert_code'] = st.session_state.get('convert_code', False)
            st.session_state['persistent_convert_urls'] = st.session_state.get('convert_urls', False)
            st.session_state['persistent_convert_word'] = st.session_state.get('convert_word', False)
            st.session_state['persistent_convert_video'] = st.session_state.get('convert_video', False)
            st.session_state['persistent_convert_excel'] = st.session_state.get('convert_excel', False)
            # Save the updated Sync Contract back to ALL courses' sync_metadata
            try:
                import json
                _updated_contract = json.dumps({
                    'file_filter': st.session_state.get('file_filter', 'all'),
                    'convert_zip': st.session_state.get('convert_zip', False),
                    'convert_pptx': st.session_state.get('convert_pptx', False),
                    'convert_html': st.session_state.get('convert_html', False),
                    'convert_code': st.session_state.get('convert_code', False),
                    'convert_urls': st.session_state.get('convert_urls', False),
                    'convert_word': st.session_state.get('convert_word', False),
                    'convert_video': st.session_state.get('convert_video', False),
                    'convert_excel': st.session_state.get('convert_excel', False),
                })
                for _s in sync_selections:
                    _p = _s['res_data']['pair']
                    _sm = SyncManager(_p['local_folder'], _p['course_id'], _p['course_name'])
                    _sm._save_metadata('sync_contract', _updated_contract)
            except Exception:
                pass  # Non-fatal
            st.session_state.pop('_sync_contract_loaded', None)
            st.rerun()
    with col_no:
        if st.button("No, Go back", use_container_width=True, key="cancel_sync_dialog_btn"):
            st.rerun()


# ---- Sync execution ----

def _run_sync(lang):
    # Initialize phase flags explicitly at start of run — but ONLY if not already cancelled.
    # If a Phase 3 cancel triggered the rerun, we must preserve is_post_processing=True
    # so that _show_sync_cancelled can read it for the correct status message.
    if not st.session_state.get('sync_cancel_requested', False) and not st.session_state.get('sync_cancelled', False):
        st.session_state['is_post_processing'] = False

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
    metrics_dashboard = st.empty()
    active_file_placeholder = st.empty()
    log_container = st.empty()

    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    cancel_placeholder = st.empty()
    cancel_placeholder.button(
        get_text('sync_cancel', lang),
        key="cancel_sync_btn",
        type="secondary",
        on_click=cancel_process_callback,
    )

    # --- Inject red hover CSS for cancel buttons (scoped) ---
    st.markdown("""
    <style>
    .st-key-cancel_download_btn button:hover,
    .st-key-cancel_pp_download button:hover,
    .st-key-cancel_sync_btn button:hover,
    .st-key-cancel_pp_btn button:hover {
        border-color: #ef4444 !important;
        background-color: #2c1616 !important;
        color: #ef4444 !important;
        transition: all 0.2s ease-in-out;
    }
    </style>
    """, unsafe_allow_html=True)

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

    # --- Task 2 Fix: Wipe error state at start of every sync run ---
    st.session_state['sync_errors'] = []

    # Format helpers for the injected HTML UI
    def format_time(seconds):
        if seconds < 0 or seconds > 86400: return "--:--"
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"

    def render_metrics_html(current_file_idx, total_files, d_mb, t_mb, speed_mb_s, eta_string):
        return f"""
        <div style="display: flex; justify-content: center; gap: 4rem; background-color: #1A1D27; padding: 15px 25px; border-radius: 8px; border: 1px solid #2D3248; margin-top: 5px; margin-bottom: 15px;">
            <div style="display: flex; flex-direction: column; align-items: center;">
                <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Downloaded</span>
                <span style="color: #FFFFFF; font-size: 1.2rem; font-weight: bold;">{d_mb:.1f} <span style="font-size: 0.9rem; color: #4DA8DA;">/ {t_mb:.1f} MB</span></span>
            </div>
            <div style="display: flex; flex-direction: column; align-items: center;">
                <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Speed</span>
                <span style="color: #10B981; font-size: 1.2rem; font-weight: bold;">{speed_mb_s:.1f} <span style="font-size: 0.9rem;">MB/s</span></span>
            </div>
            <div style="display: flex; flex-direction: column; align-items: center;">
                <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Files</span>
                <span style="color: #FFFFFF; font-size: 1.2rem; font-weight: bold;">{current_file_idx} <span style="font-size: 0.9rem; color: #4DA8DA;">/ {total_files}</span></span>
            </div>
            <div style="display: flex; flex-direction: column; align-items: center;">
                <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Time Remaining</span>
                <span style="color: #F59E0B; font-size: 1.2rem; font-weight: bold;">{eta_string}</span>
            </div>
        </div>
        """
        
    def render_terminal_html(lines):
        joined = "<br>".join(reversed(lines)) if lines else "<span style='color: #666;'>Waiting for files...</span>"
        return f"""
        <div style="background: #0e1117; border: 1px solid #222; border-radius: 6px; padding: 10px 14px; font-family: monospace; font-size: 0.85em; color: #bbb; line-height: 1.5; min-height: 200px; max-height: 250px; overflow-y: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">
            {joined}
        </div>
        """

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
            
            # Setup Tracking Variables
            import time
            from collections import deque
            start_time = time.time()
            last_ui_update = 0
            terminal_log = deque(maxlen=10)
            
            # Initial UI Draw
            metrics_dashboard.markdown(render_metrics_html(0, total_files, 0.0, total_mb, 0.0, "--:--"), unsafe_allow_html=True)
            active_file_placeholder.markdown("<p style='color: #A5D6FF; font-size: 0.9rem;'>🔄 Preparing sync...</p>", unsafe_allow_html=True)
            log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
            progress_container.progress(0, text="0%")

            for pair_idx, sel in enumerate(sync_selections):
                if st.session_state.get('sync_cancel_requested', False):
                    break
                
                failed_files_for_pair = []

                res_data = sel['res_data']
                sync_mgr = res_data['sync_manager']
                manifest = res_data['manifest']
                canvas_files_map = {f.id: f for f in res_data['canvas_files']}
                pair = res_data['pair']

                course_name = friendly_course_name(pair['course_name'])
                header_html = f"""
                <div style="margin-bottom: 0.5rem;">
                    <p style="margin: 0; font-size: 0.8rem; color: #8A91A6; text-transform: uppercase;">📦 Course {pair_idx + 1} of {total_pairs}</p>
                    <h3 style="margin: 0; padding-top: 0.1rem; color: #FFFFFF;">{course_name}</h3>
                </div>
                """
                status_text.markdown(header_html, unsafe_allow_html=True)

                # Task 4: State Leakage Fix
                # We save the auto-healed manifest + any newly ignored files only ONCE per folder, 
                # exactly when the sync is executing (after user confirmation)
                if sel['ignore']:
                    manifest = sync_mgr.mark_files_ignored(manifest, sel['ignore'])
                # Selective persist: only save ignored/healed entries to DB before download
                # (NOT the full auto-discovered manifest, to avoid premature commit)
                for file_id_str, entry in manifest.get('files', {}).items():
                    if entry.get('is_ignored'):
                        sync_mgr._save_single_file_to_db(entry)

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
                    
                    # UNCONDITIONAL status text update — fires instantly for every file (no throttle)
                    active_file_placeholder.markdown(f"<div style='color: #38bdf8; margin-bottom: 10px; font-weight: 500;'>🔄 Currently downloading: {display_file_name}...</div>", unsafe_allow_html=True)
                    
                    # Throttled progress update (Prevent Streamlit from choking on rapid tiny files)
                    curr_time = time.time()
                    if curr_time - last_ui_update > 0.4:
                        pct = min(1.0, (current_file - 1) / total_files) if total_files > 0 else 0.0
                        progress_container.progress(pct, text=f"{int(pct * 100)}%")
                        log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
                        last_ui_update = curr_time

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

                        if getattr(file, 'id', 0) < 0:
                            # It's a synthetic shortcut. Recreate it directly
                            filepath.parent.mkdir(parents=True, exist_ok=True)
                            
                            is_url_ext = filepath.name.lower().endswith('.url')
                            is_html_ext = filepath.name.lower().endswith('.html')
                            
                            if is_url_ext:
                                shortcut_content = f"[InternetShortcut]\nURL={file.url}\n"
                                filepath.write_text(shortcut_content, encoding='utf-8')
                            elif is_html_ext:
                                html_content = f"<html><body><script>window.location.href='{file.url}';</script></body></html>"
                                filepath.write_text(html_content, encoding='utf-8')
                            
                            if is_url_ext or is_html_ext:
                                rel_path = filepath.relative_to(local_path)
                                sync_mgr.add_file_to_manifest(manifest, file, str(rel_path))
                                synced_counter[0] += 1
                                st.session_state['sync_cancelled_file_count'] = synced_counter[0]
                                synced_details[pair_idx].append(display_file_name)
                                terminal_log.append(f"<span style='color:#2ecc71'>[✅] Recreated: </span> {display_file_name}")
                                log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
                                continue

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
                                # --- Retry constants (mirrors canvas_logic.py) ---
                                SYNC_MAX_RETRIES = 5
                                SYNC_RETRY_DELAY = 2  # Base delay in seconds
                                
                                for attempt in range(SYNC_MAX_RETRIES):
                                    if st.session_state.get('sync_cancel_requested', False):
                                        break
                                    
                                    try:
                                        async with session.get(download_url) as response:
                                            if response.status == 200:
                                                # --- Atomic .part Pattern ---
                                                part_path = filepath.parent / (filepath.name + '.part')
                                                download_interrupted = False
                                                atomic_rename_done = False
                                                
                                                try:
                                                    try:
                                                        async with aiofiles.open(part_path, 'wb') as f:
                                                            while True:
                                                                # Instant cancel check INSIDE the chunk loop
                                                                if st.session_state.get('sync_cancel_requested', False) or st.session_state.get('sync_cancelled', False):
                                                                    download_interrupted = True
                                                                    break
                                                                
                                                                chunk = await response.content.read(1024 * 1024)
                                                                if not chunk:
                                                                    break
                                                                await f.write(chunk)
                                                                chunk_size = len(chunk)
                                                                downloaded_mb += chunk_size / (1024 * 1024)
                                                                synced_counter[1] += chunk_size
                                                            
                                                                # Throttled UI math update
                                                                c_t = time.time()
                                                                if c_t - last_ui_update > 0.4:
                                                                    # Calculate Speed & ETA
                                                                    elapsed = c_t - start_time
                                                                    speed = downloaded_mb / elapsed if elapsed > 0 else 0
                                                                    
                                                                    rem_mb = max(0, total_mb - downloaded_mb)
                                                                    eta_sec = rem_mb / speed if speed > 0 else 0
                                                                    
                                                                    # Apply to UI
                                                                    metrics_dashboard.markdown(render_metrics_html(
                                                                        current_file, total_files, downloaded_mb, total_mb, speed, format_time(eta_sec)
                                                                    ), unsafe_allow_html=True)
                                                                    
                                                                    pct = min(1.0, current_file / total_files) if total_files > 0 else 0.0
                                                                    progress_container.progress(pct, text=f"{int(pct * 100)}%")
                                                                    last_ui_update = c_t
                                                    except Exception as write_err:
                                                        download_interrupted = True
                                                        raise write_err
                                                    
                                                    # Handle interrupted download: delete partial file
                                                    if download_interrupted:
                                                        continue  # Skip to next file (outer cancel guard will catch)
                                                    
                                                    # 100% success: atomic rename .part → final path
                                                    try:
                                                        part_path.rename(filepath)
                                                    except OSError:
                                                        # Fallback: If rename fails (cross-device), use replace
                                                        import shutil
                                                        shutil.move(str(part_path), str(filepath))
                                                    atomic_rename_done = True
                                                    
                                                    # Only commit to DB AFTER file is physically complete on disk
                                                    rel_path = filepath.relative_to(local_path)
                                                    sync_mgr.add_file_to_manifest(manifest, file, str(rel_path))
                                                    synced_counter[0] += 1
                                                    st.session_state['sync_cancelled_file_count'] = synced_counter[0]
                                                    
                                                    # Track success for UI dropdown
                                                    synced_details[pair_idx].append(display_file_name)
                                                    terminal_log.append(f"<span style='color:#2ecc71'>[✅] Finished: </span> {display_file_name}")
                                                    log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
                                                finally:
                                                    # GUARD: Always clean up .part if rename didn't complete
                                                    # Catches: write errors, network drops, disk-full, any exception
                                                    if not atomic_rename_done:
                                                        try:
                                                            if part_path.exists():
                                                                part_path.unlink()
                                                        except OSError:
                                                            pass
                                                
                                                break  # Success — exit retry loop
                                            
                                            elif response.status == 429:
                                                # Rate limited — respect Retry-After header
                                                wait = int(response.headers.get('Retry-After', SYNC_RETRY_DELAY * (2 ** attempt)))
                                                terminal_log.append(f"<span style='color:#f59e0b'>[⏳] Rate limited: </span> {display_file_name} <span style='color:#666'>(retry in {wait}s)</span>")
                                                log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
                                                await asyncio.sleep(wait)
                                                continue  # Retry
                                            
                                            elif 500 <= response.status < 600:
                                                # Server error — retry with exponential backoff
                                                wait = SYNC_RETRY_DELAY * (2 ** attempt)
                                                if attempt < SYNC_MAX_RETRIES - 1:
                                                    terminal_log.append(f"<span style='color:#f59e0b'>[⏳] Server error ({response.status}): </span> {display_file_name} <span style='color:#666'>(retry {attempt + 1}/{SYNC_MAX_RETRIES})</span>")
                                                    log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
                                                    await asyncio.sleep(wait)
                                                    continue  # Retry
                                                else:
                                                    # Max retries exhausted for 5xx
                                                    failed_files_for_pair.append(file)
                                                    error_list.append(get_text('sync_error_file', lang,
                                                        filename=display_file_name, error=f"HTTP {response.status} after {SYNC_MAX_RETRIES} retries"))
                                                    terminal_log.append(f"<span style='color:#e74c3c'>[❌] Failed: </span> {display_file_name} <span style='color:#666'>(HTTP {response.status} after {SYNC_MAX_RETRIES} retries)</span>")
                                                    log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
                                                    break
                                            
                                            else:
                                                # Non-retryable HTTP error (4xx except 429)
                                                failed_files_for_pair.append(file)
                                                error_list.append(get_text('sync_error_file', lang,
                                                    filename=display_file_name, error=f"HTTP {response.status}"))
                                                terminal_log.append(f"<span style='color:#e74c3c'>[❌] Failed: </span> {display_file_name} <span style='color:#666'>(HTTP {response.status})</span>")
                                                log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
                                                break  # Don't retry client errors
                                    
                                    except (aiohttp.ClientError, asyncio.TimeoutError) as net_err:
                                        # Network error — retry with backoff
                                        if attempt < SYNC_MAX_RETRIES - 1:
                                            wait = SYNC_RETRY_DELAY * (2 ** attempt)
                                            terminal_log.append(f"<span style='color:#f59e0b'>[⏳] Network error: </span> {display_file_name} <span style='color:#666'>(retry {attempt + 1}/{SYNC_MAX_RETRIES})</span>")
                                            log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
                                            await asyncio.sleep(wait)
                                        else:
                                            failed_files_for_pair.append(file)
                                            error_list.append(get_text('sync_error_file', lang,
                                                filename=display_file_name, error=f"Network error: {net_err}"))
                                            terminal_log.append(f"<span style='color:#e74c3c'>[❌] Failed: </span> {display_file_name} <span style='color:#666'>(Network error after {SYNC_MAX_RETRIES} retries)</span>")
                                            log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
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
                            terminal_log.append(f"<span style='color:#e74c3c'>[❌] Skipped: </span> {display_file_name} <span style='color:#666'>({err_msg})</span>")
                            log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)

                    except Exception as e:
                        failed_files_for_pair.append(file)
                        error_list.append(get_text('sync_error_file', lang,
                            filename=display_file_name, error=str(e)))
                        str_err = str(e).replace('<', '&lt;').replace('>', '&gt;')
                        terminal_log.append(f"<span style='color:#e74c3c'>[❌] Error: </span> {display_file_name} <span style='color:#666'>({str_err})</span>")
                        log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)
                        

                
                if failed_files_for_pair:
                    retry_selections.append({
                        'pair_idx': pair_idx,
                        'res_data': sel['res_data'],
                        'new': failed_files_for_pair,
                        'updates': [],
                        'redownload': [],
                        'ignore': []
                    })
                        
            # Final 100% UI Paint after the loop
            elapsed_final = time.time() - start_time
            speed_final = (downloaded_mb / elapsed_final) if elapsed_final > 0 else 0
            render_progress_bar(progress_container, total_files, total_files, lang)
            metrics_dashboard.markdown(render_metrics_html(synced_counter[0], total_files, downloaded_mb, total_mb, speed_final, "00:00"), unsafe_allow_html=True)
            active_file_placeholder.markdown("<p style='color: #A5D6FF; font-size: 0.9rem;'>✨ Sync Finalizing...</p>", unsafe_allow_html=True)
            log_container.markdown(render_terminal_html(terminal_log), unsafe_allow_html=True)

            # CANCEL GUARD: Skip all post-download state mutations if cancelled
            if st.session_state.get('sync_cancelled', False) or st.session_state.get('sync_cancel_requested', False):
                st.session_state['download_status'] = 'sync_cancelled'
                st.rerun()

            for sel in sync_selections:
                res_data = sel['res_data']
                sync_mgr = res_data['sync_manager']
                manifest = res_data['manifest']
                local_path = sync_mgr.local_path

                sync_mgr.save_manifest(manifest)
                
                # Setup updates reference explicitly to fix `updates is not defined` NameError traceback
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
                
        return synced_details, retry_selections, list(terminal_log)

    synced_details, retry_selections, _download_log_history = asyncio.run(download_sync_files_batch())

    # --- Shared post-processing helpers ---
    def get_synced_file_paths(target_exts):
        """Return list of (Path, sync_mgr, pair_idx) for synced files matching target_exts."""
        results = []
        for sel in sync_selections:
            pair_idx = sel['pair_idx']
            res_data = sel['res_data']
            sm = res_data['sync_manager']
            for fname in synced_details.get(pair_idx, []):
                if Path(fname).suffix.lower() in target_exts:
                    matches = list(sm.local_path.rglob(fname))
                    for m in matches:
                        if m.is_file() and not m.name.startswith('._') and "__MACOSX" not in m.parts:
                            results.append((m, sm, pair_idx))
        return results

    def update_synced_detail(pair_idx, old_name, new_name):
        """Update a filename in synced_details so the final success screen shows the converted extension."""
        details = synced_details.get(pair_idx, [])
        for i, fname in enumerate(details):
            if fname == old_name:
                details[i] = new_name
                break

    # ==========================================
    # SECONDARY GUARD (defense-in-depth): Catch any cancel that slipped past the primary guard above save_manifest
    # ==========================================
    if st.session_state.get('sync_cancelled', False) or st.session_state.get('sync_cancel_requested', False):
        st.session_state['download_status'] = 'sync_cancelled'
        st.rerun()

    # ==========================================
    # POST-PROCESSING UI SETUP
    # ==========================================
    import time as _time

    # 1. Clear the Phase 2 download UI to prevent stacking
    cancel_placeholder.empty()
    active_file_placeholder.empty()

    # 2. The cancel button will be rendered further down to prevent being overwritten

    # 3. Inject red hover CSS for cancel buttons (scoped)
    st.markdown("""
    <style>
    .st-key-cancel_download_btn button:hover,
    .st-key-cancel_pp_download button:hover,
    .st-key-cancel_sync_btn button:hover,
    .st-key-cancel_pp_btn button:hover,
    .st-key-cancel_pp_btn_sync_phase3 button:hover {
        border-color: #ef4444 !important;
        background-color: #2c1616 !important;
        color: #ef4444 !important;
        transition: all 0.2s ease-in-out;
    }
    </style>
    """, unsafe_allow_html=True)

    # 4. Inherit the terminal log history from the download phase (seamless continuity)
    pp_log = _download_log_history

    def pp_terminal(msg=None):
        """Append msg (if given) to the post-processing terminal, then render into the EXISTING log_container."""
        try:
            if st.session_state.get('sync_cancel_requested') or st.session_state.get('sync_cancelled'):
                return
            if msg:
                pp_log.append(msg)
            log_container.markdown(render_terminal_html(pp_log), unsafe_allow_html=True)
            _time.sleep(0.05)
        except BaseException:
            pass

    # 3. Rich conversion dashboard — renders into the EXISTING Phase 2 containers
    #    Color map per conversion type for visual distinction
    _COLOR_MAP = {
        'Archives':           '#a78bfa',  # violet
        'PowerPoint files':   '#f97316',  # orange
        'HTML files':         '#34D399',  # emerald
        'Code files':         '#FBBF24',  # amber
        'Legacy Word files':  '#3b82f6',  # blue
        'Excel files':        '#22c55e',  # green
        'Video files':        '#f59e0b',  # amber-orange
    }

    def render_conversion_dashboard(current, total, task_name):
        """Overwrite the Phase 2 progress bar and metrics dashboard with conversion-specific UI."""
        try:
            if st.session_state.get('sync_cancel_requested') or st.session_state.get('sync_cancelled'):
                return
            accent = _COLOR_MAP.get(task_name, '#4ade80')
            pct = int((current / total) * 100) if total > 0 else 0
            pct = min(100, pct)

            # Overwrite the Phase 1 status header
            status_text.markdown(f"""
            <div style="margin-bottom: 0.5rem;">
                <p style="margin: 0; font-size: 0.8rem; color: #8A91A6; text-transform: uppercase;">🪄 Post-Processing</p>
                <h3 style="margin: 0; padding-top: 0.1rem; color: #FFFFFF;">Converting {task_name}</h3>
            </div>
            """, unsafe_allow_html=True)

            # Overwrite the progress bar
            progress_container.markdown(f"""
            <div style="background-color: #2D3248; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
                <div style="background-color: {accent}; width: {pct}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
                <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: #ffffff; font-size: 12px; font-weight: bold; text-shadow: 0px 0px 2px rgba(0,0,0,0.5);">
                    {pct}%
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Overwrite the metrics dashboard
            metrics_dashboard.markdown(f"""
            <div style="display: flex; justify-content: center; gap: 4rem; background-color: #1A1D27; padding: 15px 25px; border-radius: 8px; border: 1px solid #2D3248; margin-top: 5px; margin-bottom: 15px;">
                <div style="display: flex; flex-direction: column; align-items: center;">
                    <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Converted</span>
                    <span style="color: #FFFFFF; font-size: 1.2rem; font-weight: bold;">{current} <span style="font-size: 0.9rem; color: {accent};">/ {total}</span></span>
                </div>
                <div style="display: flex; flex-direction: column; align-items: center;">
                    <span style="color: #8A91A6; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Type</span>
                    <span style="color: {accent}; font-size: 1.2rem; font-weight: bold;">{task_name}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            _time.sleep(0.05)
        except BaseException:
            pass
    # ==========================================
    
    st.session_state['is_post_processing'] = True

    # 1. Reuse the immune cancel_placeholder from Phase 2 (it sits above the CSS marker in the DOM)
    cancel_placeholder.button(
        "Cancel Post-Processing",
        key="cancel_pp_btn_sync_phase3",  # Unique key to avoid conflicts with Phase 2
        type="secondary",
        on_click=cancel_process_callback
    )
        
    # 2. FORCE RENDER FLUSH before heavy COM operations
    import time
    time.sleep(0.3)  # Increased sleep to guarantee rendering before COM locks the thread

    # --- Post-Sync: Archive Extraction (Zip/Tar) ---
    if getattr(st.session_state, 'persistent_convert_zip', False):
        from archive_extractor import extract_and_stub
        import sqlite3
        import os
        
        archive_files_to_convert = get_synced_file_paths({'.zip', '.tar', '.tar.gz', '.gz'})
        extra_targz = []
        for sel in sync_selections:
            pair_idx = sel['pair_idx']
            sm = sel['res_data']['sync_manager']
            for fname in synced_details.get(pair_idx, []):
                if fname.lower().endswith('.tar.gz'):
                    matches = list(sm.local_path.rglob(fname))
                    for m in matches:
                        if m.is_file() and (m, sm, pair_idx) not in archive_files_to_convert:
                            extra_targz.append((m, sm, pair_idx))
        archive_files_to_convert.extend(extra_targz)
        
        if archive_files_to_convert:
            total_archives = len(archive_files_to_convert)
            print(f"[Post-Sync] Archive Extraction toggle is ON. Found {total_archives} Archive files.")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total_archives} Archive files for extraction...</span>")
            render_conversion_dashboard(0, total_archives, "Archives")
            _time.sleep(0.2)
            
            for i, (archive_file, sm, pair_idx) in enumerate(archive_files_to_convert, 1):
                if st.session_state.get('sync_cancelled', False):
                    pp_terminal("<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                    break
                old_name = archive_file.name
                active_file_placeholder.markdown(f"<div style='color: #38bdf8; margin-bottom: 10px; font-weight: 500;'>⚙️ Currently processing: {old_name}</div>", unsafe_allow_html=True)
                render_conversion_dashboard(i, total_archives, "Archives")
                new_stub_path_str = extract_and_stub(archive_file)
                
                if new_stub_path_str:
                    new_stub_path = Path(new_stub_path_str)
                    manifest = sm.load_manifest()
                    for file_id, info in manifest.get('files', {}).items():
                        local_p = info.get('local_path', '')
                        try:
                            original_rel = archive_file.relative_to(sm.local_path)
                            if str(original_rel).replace('\\', '/') == local_p:
                                new_rel = new_stub_path.relative_to(sm.local_path)
                                sm.update_converted_file(int(file_id), str(new_rel).replace('\\', '/'))
                                break
                        except (ValueError, KeyError):
                            pass
                    
                    update_synced_detail(pair_idx, old_name, new_stub_path.name)
                    pp_terminal(f"<span style='color: #4ade80;'>[ ✅ ] Extracted: {old_name}</span>")
                else:
                    pp_terminal(f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Extraction failed)</span>")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ ✨ ] Archive extraction complete!</span>")
    # --- End Post-Sync Conversion (Archive) ---

    # --- Post-Download: PPTX → PDF Conversion ---
    if st.session_state.get('persistent_convert_pptx', False):
        from pdf_converter import PowerPointToPDF
        
        all_pptx_files = get_synced_file_paths({'.ppt', '.pptx', '.pptm', '.pot', '.potx'})
        
        if all_pptx_files:
            total_pptx = len(all_pptx_files)
            print(f"[Post-Download] PPTX Conversion toggle is ON. Found {total_pptx} files in Sync mode.")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ 🪄 ] Converting {total_pptx} PowerPoint files to PDF...</span>")
            render_conversion_dashboard(0, total_pptx, "PowerPoint files")
            _time.sleep(0.2)
            
            with PowerPointToPDF(error_log_path=all_pptx_files[0][1].local_path) as converter:
                for i, (pptx_file, sync_mgr, pair_idx) in enumerate(all_pptx_files, 1):
                    if st.session_state.get('sync_cancelled', False):
                        pp_terminal("<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                        break
                    old_name = pptx_file.name
                    active_file_placeholder.markdown(f"<div style='color: #38bdf8; margin-bottom: 10px; font-weight: 500;'>⚙️ Currently processing: {old_name}</div>", unsafe_allow_html=True)
                    render_conversion_dashboard(i, total_pptx, "PowerPoint files")
                    pdf_path_str = converter.convert(pptx_file)
                    
                    if pdf_path_str:
                        pdf_path = Path(pdf_path_str)
                        manifest = sync_mgr.load_manifest()
                        for file_id, info in manifest.get('files', {}).items():
                            local_p = info.get('local_path', '')
                            try:
                                original_rel = pptx_file.relative_to(sync_mgr.local_path)
                                if str(original_rel).replace('\\', '/') == local_p:
                                    new_rel = pdf_path.relative_to(sync_mgr.local_path)
                                    sync_mgr.update_converted_file(int(file_id), str(new_rel).replace('\\', '/'))
                                    break
                            except (ValueError, KeyError):
                                pass
                        
                        update_synced_detail(pair_idx, old_name, pdf_path.name)
                        pp_terminal(f"<span style='color: #4ade80;'>[ ✅ ] Converted: {old_name} -> PDF</span>")
                    else:
                        pp_terminal(f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Conversion failed)</span>")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ ✨ ] PDF conversion complete!</span>")
        
    # --- Post-Sync: HTML → MD Conversion ---
    if getattr(st.session_state, 'persistent_convert_html', False):
        from md_converter import convert_html_to_md
        
        html_files_to_convert = get_synced_file_paths({'.html'})
        
        if html_files_to_convert:
            total_html = len(html_files_to_convert)
            print(f"[Post-Sync] HTML Conversion toggle is ON. Found {total_html} HTML files.")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total_html} HTML files for Markdown conversion...</span>")
            render_conversion_dashboard(0, total_html, "HTML files")
            _time.sleep(0.2)
            
            for i, (html_file, sm, pair_idx) in enumerate(html_files_to_convert, 1):
                if st.session_state.get('sync_cancelled', False):
                    pp_terminal("<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                    break
                old_name = html_file.name
                active_file_placeholder.markdown(f"<div style='color: #38bdf8; margin-bottom: 10px; font-weight: 500;'>⚙️ Currently processing: {old_name}</div>", unsafe_allow_html=True)
                render_conversion_dashboard(i, total_html, "HTML files")
                md_path = convert_html_to_md(html_file)
                
                if md_path:
                    manifest = sm.load_manifest()
                    for file_id, info in manifest.get('files', {}).items():
                        local_p = info.get('local_path', '')
                        try:
                            original_rel = html_file.relative_to(sm.local_path)
                            if str(original_rel).replace('\\', '/') == local_p:
                                new_rel = md_path.relative_to(sm.local_path)
                                sm.update_converted_file(int(file_id), str(new_rel).replace('\\', '/'))
                                break
                        except (ValueError, KeyError):
                            pass
                    
                    update_synced_detail(pair_idx, old_name, md_path.name)
                    pp_terminal(f"<span style='color: #4ade80;'>[ ✅ ] Converted: {md_path.name}</span>")
                else:
                    pp_terminal(f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Conversion failed)</span>")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ ✨ ] Markdown conversion complete!</span>")
    # --- End Post-Sync Conversion ---
    
    # --- Post-Sync: Code → TXT Conversion ---
    if getattr(st.session_state, 'persistent_convert_code', False):
        from code_converter import convert_code_to_txt, CODE_EXTENSIONS
        
        code_files_to_convert = get_synced_file_paths(CODE_EXTENSIONS)
        
        if code_files_to_convert:
            total_code = len(code_files_to_convert)
            print(f"[Post-Sync] Code Conversion toggle is ON. Found {total_code} Code files.")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total_code} Code & Data files for TXT conversion...</span>")
            render_conversion_dashboard(0, total_code, "Code files")
            _time.sleep(0.2)
            
            for i, (code_file, sm, pair_idx) in enumerate(code_files_to_convert, 1):
                if st.session_state.get('sync_cancelled', False):
                    pp_terminal("<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                    break
                old_name = code_file.name
                active_file_placeholder.markdown(f"<div style='color: #38bdf8; margin-bottom: 10px; font-weight: 500;'>⚙️ Currently processing: {old_name}</div>", unsafe_allow_html=True)
                render_conversion_dashboard(i, total_code, "Code files")
                txt_path_str = convert_code_to_txt(code_file)
                
                if txt_path_str:
                    txt_path = Path(txt_path_str)
                    manifest = sm.load_manifest()
                    for file_id, info in manifest.get('files', {}).items():
                        local_p = info.get('local_path', '')
                        try:
                            original_rel = code_file.relative_to(sm.local_path)
                            if str(original_rel).replace('\\', '/') == local_p:
                                new_rel = txt_path.relative_to(sm.local_path)
                                sm.update_converted_file(int(file_id), str(new_rel).replace('\\', '/'))
                                break
                        except (ValueError, KeyError):
                            pass
                    
                    update_synced_detail(pair_idx, old_name, txt_path.name)
                    pp_terminal(f"<span style='color: #4ade80;'>[ ✅ ] Converted: {old_name} -> TXT</span>")
                else:
                    pp_terminal(f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Conversion failed)</span>")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ ✨ ] Code to TXT conversion complete!</span>")
    # --- End Post-Sync Conversion (Code) ---
    
    # --- Post-Sync: NotebookLM Link Compiler ---
    if getattr(st.session_state, 'persistent_convert_urls', False):
        from url_compiler import compile_urls_to_txt
        
        pp_terminal(f"<span style='color: #8A91A6;'>[ 🪄 ] Scanning downloaded modules for .url shortcuts...</span>")
        
        processed_roots = set()
        
        for sel in st.session_state.get('sync_selections', []):
            if st.session_state.get('sync_cancelled', False):
                pp_terminal("<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                break
            sm = sel.get('res_data', {}).get('sync_manager')
            if sm and sm.local_path.exists():
                course_root = sm.local_path
                if course_root not in processed_roots:
                    processed_roots.add(course_root)
                    
                    compiled_path = compile_urls_to_txt(course_root, sm.course_name)
                    if compiled_path:
                        pp_terminal(f"<span style='color: #4ade80;'>[ ✅ ] Compiled links for '{sm.course_name}' into: NotebookLM_External_Links.txt</span>")
                        
    # --- End Post-Sync Link Compiler ---
    
    # --- Post-Sync: Legacy Word → PDF Conversion ---
    if getattr(st.session_state, 'persistent_convert_word', False):
        from word_converter import WordToPDF
        
        word_files_to_convert = get_synced_file_paths({'.doc', '.rtf', '.odt'})
        
        if word_files_to_convert:
            total_word = len(word_files_to_convert)
            print(f"[Post-Sync] Word Conversion toggle is ON. Found {total_word} Legacy Word files.")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total_word} Legacy Word files for PDF conversion...</span>")
            render_conversion_dashboard(0, total_word, "Legacy Word files")
            _time.sleep(0.2)
            
            with WordToPDF() as converter:
                for i, (word_file, sm, pair_idx) in enumerate(word_files_to_convert, 1):
                    if st.session_state.get('sync_cancelled', False):
                        pp_terminal("<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                        break
                    old_name = word_file.name
                    active_file_placeholder.markdown(f"<div style='color: #38bdf8; margin-bottom: 10px; font-weight: 500;'>⚙️ Currently processing: {old_name}</div>", unsafe_allow_html=True)
                    render_conversion_dashboard(i, total_word, "Legacy Word files")
                    pdf_path_str = converter.convert(word_file)
                    
                    if pdf_path_str:
                        pdf_path = Path(pdf_path_str)
                        manifest = sm.load_manifest()
                        for file_id, info in manifest.get('files', {}).items():
                            local_p = info.get('local_path', '')
                            try:
                                original_rel = word_file.relative_to(sm.local_path)
                                if str(original_rel).replace('\\', '/') == local_p:
                                    new_rel = pdf_path.relative_to(sm.local_path)
                                    sm.update_converted_file(int(file_id), str(new_rel).replace('\\', '/'))
                                    break
                            except (ValueError, KeyError):
                                pass
                        
                        update_synced_detail(pair_idx, old_name, pdf_path.name)
                        pp_terminal(f"<span style='color: #4ade80;'>[ ✅ ] Converted: {old_name} -> PDF</span>")
                    else:
                        pp_terminal(f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Conversion failed)</span>")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ ✨ ] Legacy Word to PDF conversion complete!</span>")
    # --- End Post-Sync Conversion (Word) ---
    
    # --- Post-Sync: Excel to PDF Conversion ---
    if getattr(st.session_state, 'persistent_convert_excel', False):
        from excel_converter import ExcelToPDF
        import sqlite3
        import os
        
        excel_files_to_convert = get_synced_file_paths({'.xlsx', '.xls', '.xlsm'})
        
        if excel_files_to_convert:
            total_excel = len(excel_files_to_convert)
            print(f"[Post-Sync] Excel Conversion toggle is ON. Found {total_excel} Excel files.")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total_excel} Excel files for PDF conversion...</span>")
            render_conversion_dashboard(0, total_excel, "Excel files")
            _time.sleep(0.2)
            
            with ExcelToPDF() as converter:
                for i, (excel_file, sm, pair_idx) in enumerate(excel_files_to_convert, 1):
                    if st.session_state.get('sync_cancelled', False):
                        pp_terminal("<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                        break
                    old_name = excel_file.name
                    active_file_placeholder.markdown(f"<div style='color: #38bdf8; margin-bottom: 10px; font-weight: 500;'>⚙️ Currently processing: {old_name}</div>", unsafe_allow_html=True)
                    render_conversion_dashboard(i, total_excel, "Excel files")
                    abs_path = str(excel_file.absolute())
                    new_pdf_path, excel_error_msg = converter.convert(abs_path)
                    
                    if new_pdf_path:
                        old_rel_path = os.path.relpath(abs_path, sm.local_path)
                        new_rel_path = os.path.relpath(new_pdf_path, sm.local_path)
                        
                        db_path = sm.db_path
                        if db_path.exists():
                            conn = sqlite3.connect(db_path)
                            c = conn.cursor()
                            c.execute("SELECT canvas_file_id FROM sync_manifest WHERE local_path = ?", (old_rel_path,))
                            row = c.fetchone()
                            if row:
                                sm.update_converted_file(row[0], new_rel_path)
                            conn.close()
                        
                        update_synced_detail(pair_idx, old_name, Path(new_pdf_path).name)
                        pp_terminal(f"<span style='color: #4ade80;'>[ ✅ ] Converted: {old_name} -> PDF</span>")
                    else:
                        pp_terminal(f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} ({excel_error_msg})</span>")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ ✨ ] Excel to PDF conversion complete!</span>")
    # --- End Post-Sync Conversion (Excel) ---
    
    # --- Post-Sync: Video to MP3 Conversion ---
    if getattr(st.session_state, 'persistent_convert_video', False):
        from video_converter import convert_video_to_mp3
        
        video_files_to_convert = get_synced_file_paths({'.mp4', '.mov', '.mkv', '.avi', '.m4v'})
        
        if video_files_to_convert:
            total_video = len(video_files_to_convert)
            print(f"[Post-Sync] Video Conversion toggle is ON. Found {total_video} Video files.")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ 🪄 ] Queueing {total_video} Video files for audio extraction...</span>")
            render_conversion_dashboard(0, total_video, "Video files")
            _time.sleep(0.2)
            
            for i, (video_file, sm, pair_idx) in enumerate(video_files_to_convert, 1):
                if st.session_state.get('sync_cancelled', False):
                    pp_terminal("<span style='color: #ef4444;'>[ 🛑 ] Process cancelled by user.</span>")
                    break
                old_name = video_file.name
                active_file_placeholder.markdown(f"<div style='color: #38bdf8; margin-bottom: 10px; font-weight: 500;'>⚙️ Currently processing: {old_name}</div>", unsafe_allow_html=True)
                render_conversion_dashboard(i, total_video, "Video files")
                mp3_path_str = convert_video_to_mp3(video_file)
                
                if mp3_path_str:
                    mp3_path = Path(mp3_path_str)
                    manifest = sm.load_manifest()
                    for file_id, info in manifest.get('files', {}).items():
                        local_p = info.get('local_path', '')
                        try:
                            original_rel = video_file.relative_to(sm.local_path)
                            if str(original_rel).replace('\\', '/') == local_p:
                                new_rel = mp3_path.relative_to(sm.local_path)
                                sm.update_converted_file(int(file_id), str(new_rel).replace('\\', '/'))
                                break
                        except (ValueError, KeyError):
                            pass
                    
                    update_synced_detail(pair_idx, old_name, mp3_path.name)
                    pp_terminal(f"<span style='color: #4ade80;'>[ ✅ ] Extracted Audio: {old_name} -> MP3</span>")
                else:
                    pp_terminal(f"<span style='color: #f87171;'>[ ❌ ] Skipped: {old_name} (Audio extraction failed)</span>")
            
            pp_terminal(f"<span style='color: #8A91A6;'>[ ✨ ] Video to MP3 conversion complete!</span>")
    # --- End Post-Sync Conversion (Video) ---
    # --- End Post-Download Conversion ---




    # --- Organize files into module folders (if requested) ---

    # Clear the blue status text so it doesn't linger on completion
    active_file_placeholder.empty()

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

    if st.session_state.get('sync_cancel_requested', False) or st.session_state.get('sync_cancelled', False):
        st.session_state['download_status'] = 'sync_cancelled'
        st.session_state['sync_cancelled_file_count'] = synced_counter[0]
    else:
        st.session_state['download_status'] = 'sync_complete'
        
    st.session_state['step'] = 4
    st.rerun()


# ---- Cancelled ----

def _show_sync_cancelled(lang):
    render_sync_wizard(st, 3, lang)

    cancelled_count = st.session_state.get('sync_cancelled_file_count', 0)
    total_files = sum(
        len(sel['new']) + len(sel['updates']) + len(sel['redownload'])
        for sel in st.session_state.get('sync_selections', [])
    )

    # Dynamic text: "course" during scanning, "file" during download, post-processing status
    if st.session_state.get('is_post_processing', False):
        cancel_summary_msg = "Cancelled during post-processing."
    else:
        is_file_phase = total_files > 0
        if is_file_phase:
            cancel_summary_msg = f"Cancelled after {cancelled_count} of {total_files} {'file' if total_files == 1 else 'files'}."
        else:
            cancel_summary_msg = "Cancelled during Course Analysis."

    # Premium styled cancellation card
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, #2c1616 0%, #1a1a2e 100%);
        border: 1px solid #ef4444;
        border-radius: 12px;
        padding: 28px 32px;
        margin: 20px 0;
        box-shadow: 0 4px 20px rgba(239, 68, 68, 0.15);
    ">
        <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 12px;">
            <span style="font-size: 2rem;">🛑</span>
            <h2 style="margin: 0; color: #ef4444; font-size: 1.5rem; font-weight: 700;">Sync Cancelled</h2>
        </div>
        <p style="color: #d1d5db; font-size: 1rem; margin: 0 0 8px 0;">
            {get_text('sync_cancelled', lang)}
        </p>
        <div style="
            background: rgba(239, 68, 68, 0.08);
            border-radius: 8px;
            padding: 12px 16px;
            margin-top: 12px;
            display: inline-block;
        ">
            <span style="color: #f87171; font-size: 0.9rem; font-weight: 600;">
                {cancel_summary_msg}
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    _show_sync_errors(lang)

    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    if st.button("🏠 " + get_text('go_to_front_page', lang), type="primary", use_container_width=True):
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
        'sync_cancelled', 'is_post_processing', '_sync_contract_loaded'
    ]:
        st.session_state.pop(key, None)

    # Nuclear reset: force all cancel flags to False to prevent ghost aborts
    st.session_state['sync_cancelled'] = False
    st.session_state['sync_cancel_requested'] = False
    st.session_state['cancel_requested'] = False
    st.session_state['download_cancelled'] = False
    
    # Nuclear cache clearing on reset to destroy dead aiohttp sessions
    st.cache_data.clear()
    st.session_state.pop('sync_manager', None)
    st.session_state.pop('cm', None)

    # Also clean up any dynamic checkbox keys
    keys_to_remove = [k for k in st.session_state if k.startswith(('sync_new_', 'sync_upd_', 'sync_miss_', 'ignore_'))]
    for k in keys_to_remove:
        st.session_state.pop(k, None)

    st.session_state['step'] = 1
