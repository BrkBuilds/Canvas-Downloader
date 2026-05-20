"""
ui.hub_dialog - Saved Groups Hub SPA dialog and helpers.

Extracted from ``sync_ui.py`` (Phase 5).
Strict physical move - NO logic changes.

Contains:
  - Save Group/Pair dialog inner logic
  - Hub SPA 3-layer dialog
  - All hub callbacks (edit, add, delete, course selection)
  - Hub CSS injection
  - Hub state management
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

import theme
from sync_manager import SyncManager, SavedGroupsManager
from ui_helpers import (
    esc,
    friendly_course_name,
    open_folder,
)
from styles import inject_css


# Lazy imports to avoid circular dependency with sync_ui.py
def _add_pair_lazy(pair):
    """Atomically add a pair via sync.persistence."""
    from sync.persistence import add_pair
    add_pair(pair)

def _add_pairs_batch_lazy(pairs_list):
    """Atomically add pairs batch via sync.persistence."""
    from sync.persistence import add_pairs_batch
    add_pairs_batch(pairs_list)


# Save Group / Pair Dialog (Dual-Wrapper Pattern)
# ===================================================================

def save_group_or_pair_inner(sync_pairs: list[dict], is_pair: bool = False, pair_data: dict = None):
    """Shared inner logic for the Save Group/Pair dialog."""
    if is_pair:
        desc_text = (
            'Save your selected course/folder pair to the "Saved Groups & Pairs" tab, '
            'so you can quickly add it to the sync list later.'
        )
        input_label = "Give your pair a name:"
        input_placeholder = "e.g., Programming (for NotebookLM)"
        entity = "Pair"
    else:
        desc_text = (
            'Save your current list of course/folder pairs as a group, so you can '
            'quickly bulk-add them to the sync list from "Saved Groups & Pairs".'
        )
        input_label = "Give your group a name:"
        input_placeholder = "e.g., 1st Semester"
        entity = "Group"

    st.markdown(
        f'<p style="color:#aaa; font-size:0.9rem; margin-bottom:10px;">'  # audit-ignore: desc_text is a static app string
        f'{desc_text}</p>',
        unsafe_allow_html=True,
    )
    item_name = st.text_input(
        input_label,
        placeholder=input_placeholder,
        key="save_group_name_input",
    )

    # Dialog button CSS now lives in inject_hub_global_css() for bulletproof rendering.

    # Action buttons - Cancel left, Create right
    col_cancel, col_create = st.columns([1, 1], vertical_alignment="bottom")
    with col_cancel:
        if st.button("Cancel", type="secondary", use_container_width=True, key="cancel_save_group"):
            st.rerun(scope="app")
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
            st.rerun(scope="app")



# ===================================================================
# Saved Groups Hub Dialog (Phase 2)
# ===================================================================

def hub_select_folder():
    """Open native folder picker for the Hub dialog (isolated state)."""
    from ui_helpers import native_folder_picker
    folder_path = native_folder_picker(initial_dir=st.session_state.get('hub_temp_folder') or None)
    if folder_path:
        st.session_state['hub_temp_folder'] = folder_path


def rescue_select_folder(pair_idx: int):
    """Open native folder picker for rescue mode (isolated per-pair state)."""
    from ui_helpers import native_folder_picker
    current = (st.session_state.get('rescue_paths') or {}).get(pair_idx) or None
    folder_path = native_folder_picker(initial_dir=current)
    if folder_path:
        rescue_paths = st.session_state.get('rescue_paths', {})
        rescue_paths[pair_idx] = folder_path
        st.session_state['rescue_paths'] = rescue_paths


def change_hub_layer(target_layer, _pop_keys=None, **kwargs):
    """Callback to instantly change dialog layers and pass variables before render."""
    st.session_state['hub_layer'] = target_layer
    for k, v in kwargs.items():
        st.session_state[k] = v
    if _pop_keys:
        for k in _pop_keys:
            st.session_state.pop(k, None)


def delete_group_callback(mgr, group_id, group_name):
    """Callback to delete a group before the dialog re-renders."""
    mgr.delete_group(group_id)
    st.session_state['hub_toast'] = f"🗑️ Group '{group_name}' deleted."


def remove_pair_from_group(mgr, group_id, pair_idx):
    """Callback to remove a single course pair from a group."""
    groups = mgr.load_groups()
    group = next((g for g in groups if g.get('group_id') == group_id), None)
    if group and 0 <= pair_idx < len(group.get('pairs', [])):
        popped = group['pairs'].pop(pair_idx)
        mgr.update_group(group_id, {'pairs': group['pairs']})
        st.session_state['hub_toast'] = f"🗑️ Removed '{popped.get('course_name', 'course')}' from group."
    # Clear any active edit state that might reference stale indices
    st.session_state.pop('hub_editing_pair_idx', None)
    st.session_state.pop('hub_is_adding_new_pair', None)


def hub_start_edit_pair(p_idx, pair):
    """Callback to enter inline edit mode for a pair."""
    st.session_state['hub_editing_pair_idx'] = p_idx
    st.session_state['hub_edit_temp_folder'] = pair.get('local_folder', '')
    st.session_state['hub_edit_temp_course_id'] = pair.get('course_id')
    st.session_state['hub_edit_temp_course_name'] = pair.get('course_name', '')
    st.session_state.pop('hub_is_adding_new_pair', None)


def hub_cancel_edit():
    """Callback to cancel inline editing or adding."""
    st.session_state.pop('hub_editing_pair_idx', None)
    st.session_state.pop('hub_edit_temp_folder', None)
    st.session_state.pop('hub_edit_temp_course_id', None)
    st.session_state.pop('hub_edit_temp_course_name', None)
    st.session_state.pop('hub_is_adding_new_pair', None)


def hub_pick_folder_cb():
    """Callback to open native folder picker and store result directly in edit temp state."""
    from ui_helpers import native_folder_picker
    folder_path = native_folder_picker(initial_dir=st.session_state.get('hub_edit_temp_folder') or None)
    if folder_path:
        st.session_state['hub_edit_temp_folder'] = folder_path


def save_inline_edit_cb(mgr, gid, p_idx, new_folder, new_cid, new_cname):
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
        st.session_state['hub_toast'] = "✅ Pair updated successfully!"
    # Clear edit state
    hub_cancel_edit()


def save_inline_add_cb(mgr, gid, new_folder, new_cid, new_cname):
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
        st.session_state['hub_toast'] = f"✅ Added '{new_cname}' to the group!"
    # Clear add state
    hub_cancel_edit()


def confirm_course_selection_cb(cid, cname, course_names_map, courses_list):
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


def saved_groups_hub_dialog_inner(courses, course_names):
    """3-layered SPA dialog for managing saved sync groups."""
    from ui_helpers import get_config_dir, get_base64_image

    mgr = SavedGroupsManager(get_config_dir())
    layer = st.session_state.get('hub_layer', 'layer_1')

    b64_view_all = get_base64_image("assets/icon_sync_view_all.png")
    b64_groups = get_base64_image("assets/icon_sync_group.png")
    b64_pairs = get_base64_image("assets/icon_sync_pair.png")
    b64_hub_icon = get_base64_image("assets/icon_sync_hub.png")
    b64_add = get_base64_image("assets/icon_add.png")

    # 1. Safely consume and display any pending dialog toasts
    if 'hub_toast' in st.session_state:
        st.toast(st.session_state.pop('hub_toast'))

    # --- Dialog-wide CSS ---
    st.markdown(f"""
        <style>
            /* 2. Hide only the native close 'X' button to force state-aware closing */
            div[data-testid="stDialog"] button[aria-label="Close"] {{
                display: none !important; 
            }}

            /* Dynamic Icon Injections for Tab Buttons */
            div[data-testid="stDialog"] div[class*="st-key-btn_hub_tab_"] button div[data-testid="stMarkdownContainer"] p {{
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
            }}

            /* Base styling (Default Inactive State) */
            div[data-testid="stDialog"] div[class*="st-key-btn_hub_tab_"] button {{
                font-size: 1.1rem !important;
                font-weight: 600 !important;
                padding: 6px 16px !important;
                height: auto !important;
                min-height: 40px !important;
                border-radius: 6px !important;
                background-color: transparent !important;
                border: 1px solid rgba(255, 255, 255, 0.15) !important;
                color: #e0e7ff !important;
                transition: all 0.2s ease !important;
            }}

            /* Hover State (All Tabs) - Solid Indigo */
            div[data-testid="stDialog"] div[class*="st-key-btn_hub_tab_"] button:hover {{
                background-color: rgba(95, 100, 200, 0.85) !important;
                border-color: rgba(95, 100, 200, 1) !important;
                color: #ffffff !important;
            }}

            /* Active Tab (Primary) Context styling */
            div[data-testid="stDialog"] div[class*="st-key-btn_hub_tab_"] button[kind="primary"] {{
                background-color: rgba(95, 100, 200, 0.15) !important;
                border: 1px solid rgba(255, 255, 255, 0.15) !important;
                border-bottom: 3px solid rgba(140, 150, 255, 1) !important; /* Light indigo bottom border */
                color: #ffffff !important;
            }}

            /* Maintain bottom border and border color on Active Tab hover so it doesn't jump */
            div[data-testid="stDialog"] div[class*="st-key-btn_hub_tab_"] button[kind="primary"]:hover {{
                background-color: rgba(95, 100, 200, 0.4) !important;
                border: 1px solid rgba(255, 255, 255, 0.15) !important;
                border-bottom: 3px solid rgba(140, 150, 255, 1) !important;
                color: #ffffff !important;
            }}
            div[data-testid="stDialog"] div.st-key-btn_hub_tab_view_all button div[data-testid="stMarkdownContainer"] p::before {{
                content: "";
                display: inline-block;
                width: 22px;
                height: 22px;
                margin-right: 8px;
                background-image: url('data:image/png;base64,{b64_view_all}');
                background-size: contain;
                background-repeat: no-repeat;
            }}
            div[data-testid="stDialog"] div.st-key-btn_hub_tab_groups button div[data-testid="stMarkdownContainer"] p::before {{
                content: "";
                display: inline-block;
                width: 22px;
                height: 22px;
                margin-right: 8px;
                background-image: url('data:image/png;base64,{b64_groups}');
                background-size: contain;
                background-repeat: no-repeat;
            }}
            div[data-testid="stDialog"] div.st-key-btn_hub_tab_pairs button div[data-testid="stMarkdownContainer"] p::before {{
                content: "";
                display: inline-block;
                width: 22px;
                height: 22px;
                margin-right: 8px;
                background-image: url('data:image/png;base64,{b64_pairs}');
                background-size: contain;
                background-repeat: no-repeat;
            }}

            /* Flexbox Left-Align for Inline Edit/Add Rows */
            div[class*="st-key-hub_inline_edit_row"] div[data-testid="stHorizontalBlock"] {{
                align-items: center !important;
                justify-content: flex-start !important;
                gap: 10px !important;

            }}
            div[class*="st-key-hub_inline_edit_row"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
                width: auto !important;
                flex: 0 1 auto !important;
            }}
            /* Reduce vertical space between Course row and Folder row */
            div[class*="st-key-hub_inline_edit_row_course"],
            div[class*="st-key-hub_inline_edit_row_add_course"] {{
                margin-bottom: -6px !important;
            }}

            /* Pull back buttons up to sit flush with dialog top */
            div.st-key-btn_back_to_groups,
            div.st-key-btn_hub_back_from_course_sel {{
                margin-top: -30px !important;
            }}

            /* =========================================
               COMPACT PAIR CARDS & ACTION BUTTONS
               ========================================= */
            /* Shrink the Action Buttons to 32px height */
            div[class*="st-key-hub_open_"] button,
            div[class*="st-key-hub_editp_"] button,
            div[class*="st-key-btn_hub_remove_pair_"] button,
            div[class*="st-key-hub_add_"] button,
            div[class*="st-key-hub_edit_"] button,
            div[class*="st-key-btn_hub_delete_"] button {{
                min-height: 32px !important;
                height: 32px !important;
                padding-top: 2px !important;
                padding-bottom: 2px !important;
                font-size: 0.9rem !important;
            }}

            /* Reduce vertical padding inside the Pair Cards */
            div[class*="st-key-hub_pair_card_"] {{
                padding-top: 8px !important;
                padding-bottom: 12px !important; 
                margin-bottom: 10px !important; /* Tighter gap between cards */
            }}

            /* Compact the "See Configuration" expander summary */
            div[class*="st-key-hub_pair_card_"] div[data-testid="stExpander"] details summary {{
                padding-top: 4px !important;
                padding-bottom: 4px !important;
                min-height: 0px !important;
            }}

            /* Adjust configuration expander body padding */
            div[class*="st-key-hub_pair_card_"] div[data-testid="stExpander"] details div[data-testid="stExpanderDetails"] {{
                padding-top: 10px !important;
                padding-bottom: 24px !important;
            }}

            /* Pull the action buttons closer to the text above them */
            div[class*="st-key-hub_pair_card_"] div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] {{
                margin-top: -5px !important;
                margin-bottom: 2px !important;
            }}

            /* Fix Group Name Edit Box padding to prevent height jumps */
            div.st-key-hub_edit_group_meta {{
                padding: 10px 12px !important;
                margin-bottom: 5px !important;
                background-color: rgba(255, 255, 255, 0.02) !important;
            }}
            /* Style the text input box to be distinguishable */
            div.st-key-hub_edit_name_input div[data-baseweb="input"] {{
                background-color: rgba(0, 0, 0, 0.3) !important;
                border: 1px solid rgba(255, 255, 255, 0.15) !important;
                border-radius: 6px !important;
                min-height: 48px !important;
                height: 48px !important;
            }}
            div.st-key-hub_edit_name_input div[data-baseweb="input"]:focus-within {{
                border-color: #4a90e2 !important;
            }}

            /* ===== ADD BUTTONS - Base64 Icon via ::before ===== */
            div[data-testid="stDialog"] div[class*="st-key-hub_add_"] button p::before,
            div[data-testid="stDialog"] div.st-key-btn_hub_add_new_pair button p::before {{
                content: "" !important;
                display: inline-block !important;
                position: relative !important;
                top: 2px !important;
                width: 16px !important;
                height: 16px !important;
                margin-right: 6px !important;
                background-image: url("data:image/png;base64,{b64_add}") !important;
                background-repeat: no-repeat !important;
                background-size: contain !important;
            }}
        </style>
    """, unsafe_allow_html=True)


    # =================================================================
    # LAYER 1 - Overview
    # =================================================================
    
    # Custom Dialog Header replacing the native one (Zero-Width Space Hack)
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 0px; margin-top: -70px;">
            <img src="data:image/png;base64,{b64_hub_icon}" style="width: 36px; height: 36px;" />
            <div style="margin: 0; padding: 0; font-size: 1.75rem; font-weight: 600; color: white;">Saved Groups & Pairs</div>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    if layer == 'layer_1':
        groups = mgr.load_groups()
        if not groups:
            st.info("No saved groups or pairs yet. Use the \"\U0001F4BE Save List as Group\" button or the inline \U0001F4BE button to create one.")
            if st.button("Close", type="secondary", use_container_width=True, key="hub_close_empty"):
                hub_cleanup()
                try:
                    st.rerun(scope="app")
                except TypeError:
                    st.rerun()
            return

        # --- Tab Buttons (View All / Groups / Pairs) ---
        _vm = st.session_state.get('hub_view_mode', 'View All')
        # Callback to update state BEFORE rendering
        def set_view_mode(mode):
            st.session_state.hub_view_mode = mode

        with st.container(key="hub_tabs_container"):
            t1, t2, t3 = st.columns(3)
            with t1:
                st.button("View All", 
                          key="btn_hub_tab_view_all",
                          type="primary" if _vm == "View All" else "secondary", 
                          use_container_width=True, 
                          on_click=set_view_mode, args=("View All",))
            with t2:
                st.button("Groups", 
                          key="btn_hub_tab_groups",
                          type="primary" if _vm == "Groups" else "secondary", 
                          use_container_width=True, 
                          on_click=set_view_mode, args=("Groups",))
            with t3:
                st.button("Pairs", 
                          key="btn_hub_tab_pairs",
                          type="primary" if _vm == "Pairs" else "secondary", 
                          use_container_width=True, 
                          on_click=set_view_mode, args=("Pairs",))

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

                        # Title: Base64 Pairs icon with same font size/weight as group expander summaries
                        st.markdown(f"""
                            <div style='margin-top: 0px; margin-bottom: 10px;'>
                                <div style='display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;'>
                                    <div style='font-size: 1.25rem; font-weight: 600; color: {theme.WHITE}; line-height: 1.2;'><img src='data:image/png;base64,{b64_pairs}' style='width:24px; height:24px; vertical-align:middle; margin-right:8px; margin-top:-4px;' />{esc(group['group_name'])}</div>
                                    <div style='font-size: 0.75rem; color: rgba(255, 255, 255, 0.5); font-weight: 500; letter-spacing: 0.5px; margin-top: 0px;'>Pair</div>
                                </div>
                                <div class='pair-course-subtitle'>Course: {esc(display_name)}</div>
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
                            if st.button("Add to Sync List", key=f"hub_add_{g_idx}",
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
                                        st.rerun(scope="app")
                                        return

                                # Rule B: Prevent folder collision (Same local_folder path)
                                for existing in current_list:
                                    if existing.get('local_folder') == incoming_pair.get('local_folder'):
                                        st.session_state['pending_toast'] = "\u26a0\ufe0f Folder collision: this folder is already used by another pair in your sync list."
                                        st.rerun(scope="app")
                                        return

                                # Validation passed - append
                                # Validation passed - append atomically
                                _add_pair_lazy(incoming_pair)
                                st.session_state['pending_toast'] = f"\u2705 Added '{display_name}' to sync list!"
                                hub_cleanup()
                                st.rerun(scope="app")
                        with c2:
                            st.button("\u270f\ufe0f Edit Pair", key=f"hub_edit_{g_idx}",
                                      use_container_width=True,
                                      on_click=change_hub_layer,
                                      kwargs={'target_layer': 'layer_2', 'hub_active_group_id': group['group_id']})
                        with c3:
                            st.button("\U0001F5D1\ufe0f Delete", key=f"btn_hub_delete_{group['group_id']}",
                                      use_container_width=True,
                                      on_click=delete_group_callback,
                                      args=(mgr, group['group_id'], group['group_name']))

                else:
                    # === GROUP CARD (Multi-pair group) ===
                    with st.container(border=True, key=f"hub_group_item_{g_idx}"):
                        pair_count = len(group.get('pairs', []))
                        course_word = 'course' if pair_count == 1 else 'courses'
                        
                        # 1. Custom Title HTML (Fixed top margin to align centrally, Base64 Group icon)
                        st.markdown(f"""
                            <div style='margin-top: 0px; margin-bottom: 10px;'>
                                <div style='display: flex; justify-content: space-between; align-items: flex-start;'>
                                    <div style='font-size: 1.25rem; font-weight: 600; color: {theme.WHITE}; line-height: 1.2;'><img src='data:image/png;base64,{b64_groups}' style='width:24px; height:24px; vertical-align:middle; margin-right:8px; margin-top:-4px;' />{esc(group['group_name'])}</div>
                                    <div style='font-size: 0.75rem; color: rgba(255, 255, 255, 0.5); font-weight: 500; letter-spacing: 0.5px; margin-top: 0px;'>Group</div>
                                </div>
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
                            if st.button("Add to Sync List", key=f"hub_add_{g_idx}",
                                         use_container_width=True,
                                         disabled=_group_on_list, help=_add_help_g):
                                # --- Phase 3: Pre-Flight Engine ---
                                incoming = group.get('pairs', [])
                                existing_sigs = {
                                    (p.get('course_id'), p.get('local_folder'))
                                    for p in st.session_state.get('sync_pairs', [])
                                }

                                # Task 1: Silent duplicate filtering (full signature match,
                                # consistent with persistence.add_pairs_batch dedup logic).
                                unique_pairs = [
                                    p for p in incoming
                                    if (p.get('course_id'), p.get('local_folder')) not in existing_sigs
                                ]
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
                                        # All folders exist - merge immediately using batch atomic append
                                        _add_pairs_batch_lazy(unique_pairs)

                                        # Detect same-course-different-folder overlaps for user awareness
                                        existing_course_folders = {
                                            p.get('course_id'): p.get('local_folder')
                                            for p in st.session_state.get('sync_pairs', [])
                                        }
                                        overlap_count = sum(
                                            1 for p in unique_pairs
                                            if p.get('course_id') in existing_course_folders
                                            and existing_course_folders[p.get('course_id')] != p.get('local_folder')
                                        )

                                        added = len(unique_pairs)
                                        msg = f"\u2705 Added {added} course{'s' if added != 1 else ''} to sync list!"
                                        if skipped:
                                            msg += f" (Skipped {skipped} duplicate{'s' if skipped != 1 else ''}.)"
                                        if overlap_count:
                                            msg += f" ℹ️ {overlap_count} course{'s' if overlap_count != 1 else ''} already synced to a different folder."
                                        st.session_state['pending_toast'] = msg
                                        hub_cleanup()
                                        st.rerun(scope="app")
                                    else:
                                        # Some folders missing - enter rescue mode
                                        st.session_state['hub_layer'] = 'rescue_mode'
                                        st.session_state['hub_rescue_group_id'] = group['group_id']
                                        st.session_state['hub_rescue_pairs'] = unique_pairs
                                        st.session_state['hub_rescue_missing'] = missing_indices
                                        st.session_state['hub_rescue_skipped'] = skipped
                                        st.session_state['rescue_paths'] = {}
                                        st.rerun(scope="app")
                        # NOTE: c2/c3 are at the same indent level as the
                        # if-block above. On the click-frame, st.rerun()
                        # fires before these render - by design.
                        with c2:
                            st.button("\u270f\ufe0f Edit Group", key=f"hub_edit_{g_idx}",
                                      use_container_width=True,
                                      on_click=change_hub_layer,
                                      kwargs={'target_layer': 'layer_2', 'hub_active_group_id': group['group_id']})
                        with c3:
                            st.button("\U0001F5D1\ufe0f Delete", key=f"btn_hub_delete_{group['group_id']}",
                                      use_container_width=True,
                                      on_click=delete_group_callback,
                                      args=(mgr, group['group_id'], group['group_name']))

        if st.button("Close", type="secondary", use_container_width=True, key="btn_hub_close"):
            hub_cleanup()
            try:
                st.rerun(scope="app")
            except TypeError:
                st.rerun()

    # =================================================================
    # LAYER 2 - Group Details
    # =================================================================
    elif layer == 'layer_2':
        gid = st.session_state.get('hub_active_group_id')
        groups = mgr.load_groups()
        group = next((g for g in groups if g.get('group_id') == gid), None)
        if not group:
            st.error("Group not found.")
            st.button("\u2b05\ufe0f Back", key="hub_back_l2_err", type="tertiary",
                      on_click=change_hub_layer, kwargs={'target_layer': 'layer_1'})
            return

        st.button("← Back to overview", key="btn_back_to_groups", type="tertiary",
                  on_click=change_hub_layer, kwargs={'target_layer': 'layer_1'})



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
                        <div style='margin-bottom: -5px; margin-top: -20px;'><!-- # audit-ignore: name_label is a static app string -->
                            <span style='color: rgba(255,255,255,0.5); font-size: 0.85rem; font-weight: 500;'>{name_label}</span>
                        </div>
                        <h1 style='margin: 0px; padding: 0px; font-size: 2.2rem; display: inline-block; line-height: 1;'>{group['group_name']}</h1>
                    """, unsafe_allow_html=True)
                with cv2:
                    st.button("✏️ Edit", key="btn_enable_edit_name", on_click=_toggle_edit_name)
            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True) # Spacing before cards
        else:
            # EDIT MODE (Ultra-compact to prevent dialog height jump)
            name_label = "Editing pair title:" if is_sp else "Editing group title:"
            st.markdown(f"""
                <div style='margin-bottom: 2px; margin-top: -20px;'>
                    <span style='color: rgba(255,255,255,0.5); font-size: 0.85rem; font-weight: 500;'>{name_label}</span>
                </div>
            """, unsafe_allow_html=True)
            with st.container(border=True, key="hub_edit_group_meta"):
                col_name, col_cancel, col_save = st.columns([0.6, 0.2, 0.2], vertical_alignment="bottom")
                with col_name:
                    new_name = st.text_input(f"{entity_label} Name", value=group['group_name'],
                                             key="hub_edit_name_input", label_visibility="collapsed")
                with col_cancel:
                    st.button("Cancel", use_container_width=True, key="hub_cancel_edit_name", on_click=_cancel_edit_name_cb)
                with col_save:
                    name_changed = new_name.strip() and new_name.strip() != group['group_name']
                    st.button("💾 Save", disabled=not name_changed,
                              use_container_width=True, key="hub_save_name", on_click=_save_name_cb)

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
                    with st.container(border=True, key=f"hub_compact_edit_form_{p_idx}"):
                        st.markdown("<h3 style='margin-top: -15px; margin-bottom: 5px;'>✏️ Editing Pair</h3>", unsafe_allow_html=True)

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
                                    f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">{esc(course_disp)}</span>',
                                    unsafe_allow_html=True,
                                )
                            with col_c_btn:
                                st.button("Change Course", key=f"btn_hub_compact_change_course_{p_idx}",
                                          on_click=change_hub_layer,
                                          kwargs={'target_layer': 'layer_course_selector'})

                        # --- Folder row ---
                        temp_folder = st.session_state.get('hub_edit_temp_folder', pair.get('local_folder', ''))
                        folder_display = Path(temp_folder).name if temp_folder else 'No folder selected'
                        with st.container(key=f"hub_inline_edit_row_folder_{p_idx}"):
                            col_f_info, col_f_btn = st.columns(2, vertical_alignment="center", gap="small")
                            with col_f_info:
                                st.markdown(
                                    f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                                    f'Folder:</span>'  # audit-ignore: folder_display is a local path
                                    f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">📁 {folder_display}</span>',
                                    unsafe_allow_html=True,
                                )
                            with col_f_btn:
                                st.button("Change Folder", key=f"btn_hub_compact_change_folder_{p_idx}",
                                          on_click=hub_pick_folder_cb)

                        # --- Save / Cancel ---
                        col_cancel, col_save, _ = st.columns([1, 1, 3])
                        with col_cancel:
                            st.button("Cancel", key=f"hub_cancel_edit_{p_idx}",
                                      use_container_width=True, on_click=hub_cancel_edit)
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
                                      on_click=save_inline_edit_cb,
                                      args=(mgr, gid, p_idx, final_folder, final_cid, final_cname))

                # === NORMAL VIEW MODE ===
                else:
                    with st.container(border=True, key=f"hub_pair_card_{p_idx}"):
                        display_name = friendly_course_name(pair.get('course_name', 'Unknown'))
                        folder_exists = Path(pair.get('local_folder', '')).exists()

                        st.markdown(f"""
                            <div style='margin-bottom: 12px; margin-top: 6px;'>
                                <div style='font-size: 1.25rem; font-weight: 600; color: {theme.WHITE}; line-height: 1.4; margin-bottom: 4px;'>{esc(display_name)}</div>
                                <div style='color: #a3a8b8; font-size: 14px;'>📁 {pair.get('local_folder', '')}</div><!-- # audit-ignore: local_folder is a filesystem path -->
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
                                          on_click=hub_start_edit_pair, args=(p_idx, pair))
                        else:
                            c1, c2, c3 = st.columns(3)
                            with c1:
                                if st.button("📂 Open Folder", key=f"hub_open_{p_idx}", disabled=not folder_exists, use_container_width=True):
                                    open_folder(pair['local_folder'])
                            with c2:
                                st.button("✏️ Edit Pair", key=f"hub_editp_{p_idx}", use_container_width=True,
                                          on_click=hub_start_edit_pair, args=(p_idx, pair))
                            with c3:
                                st.button("🗑️ Remove", key=f"btn_hub_remove_pair_{p_idx}", use_container_width=True,
                                          on_click=remove_pair_from_group, args=(mgr, gid, p_idx))

                        # --- Config expander ---
                        with st.expander("⚙️ See Configuration", expanded=False):
                            render_hub_config(pair)

            # === INLINE ADD NEW PAIR (Hidden for single pairs) ===
            if not is_sp and is_adding:
                with st.container(border=True, key="hub_compact_add_form"):
                    st.markdown("<h3 style='margin-top: -25px; margin-bottom: 10px !important;'>✨ Add a New Course/Folder Pair</h3>", unsafe_allow_html=True)

                    # --- Folder row ---
                    add_folder = st.session_state.get('hub_edit_temp_folder', '')
                    add_folder_display = Path(add_folder).name if add_folder else 'No folder selected'
                    with st.container(key="hub_inline_edit_row_add_folder"):
                        col_af_info, col_af_btn = st.columns(2, vertical_alignment="center", gap="small")
                        with col_af_info:
                            st.markdown(
                                f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                                f'Folder:</span>'  # audit-ignore: add_folder_display is a local path
                                f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">📁 {add_folder_display}</span>',
                                unsafe_allow_html=True,
                             )
                        with col_af_btn:
                            st.button("Select Folder", key="btn_hub_compact_change_folder_add",
                                      on_click=hub_pick_folder_cb)

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
                                f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">{esc(add_course_disp)}</span>',
                                unsafe_allow_html=True,
                            )
                        with col_ac_btn:
                            st.button("Select Course", key="btn_hub_compact_change_course_add",
                                      on_click=change_hub_layer,
                                      kwargs={'target_layer': 'layer_course_selector'})

                    # --- Add / Cancel ---
                    can_add = bool(add_folder) and bool(add_course_id)
                    add_cname_final = add_course_name if add_course_name else course_names.get(add_course_id, '')
                    col_cancel_add, col_add, _ = st.columns([1, 1, 3])
                    with col_cancel_add:
                        st.button("Cancel", key="btn_inline_new_cancel",
                                  use_container_width=True, on_click=hub_cancel_edit)
                    with col_add:
                        st.button("💾 Add to Group", use_container_width=True,
                                  key="btn_inline_new_confirm", disabled=not can_add,
                                  on_click=save_inline_add_cb,
                                  args=(mgr, gid, add_folder, add_course_id, add_cname_final))

            # --- "Add a new course" button (only when not already adding, hidden for single pairs) ---
            if not is_sp and not is_adding:
                st.markdown("")
                def _start_adding():
                    st.session_state['hub_is_adding_new_pair'] = True
                    st.session_state.pop('hub_editing_pair_idx', None)
                    st.session_state.pop('hub_edit_temp_folder', None)
                    st.session_state.pop('hub_edit_temp_course_id', None)
                    st.session_state.pop('hub_edit_temp_course_name', None)
                with st.container(key="hub_layer2_add_btn_wrapper"):
                    st.button("Add a new course to the group", key="btn_hub_add_new_pair",
                              use_container_width=True, on_click=_start_adding)

    # =================================================================
    # LAYER: COURSE SELECTOR (Premium SPA page)
    # =================================================================
    elif layer == 'layer_course_selector':
        # Determine current selection from the edit/add temp state
        current_selected_id = st.session_state.get('hub_edit_temp_course_id')

        st.button("\u2190 Back to Edit", key="btn_hub_back_from_course_sel", type="tertiary",
                  on_click=change_hub_layer, kwargs={'target_layer': 'layer_2'})
        # Use st.html() so the h3 has zero ghost-box margin (st.markdown wraps in
        # stMarkdownContainer which adds 1rem bottom margin, pushing "Show:" far down).
        st.html("<h3 style='font-size: 1.5rem; margin-top: -12px; margin-bottom: 0px;'>Select Course</h3>")

        # Compact spacing CSS for hub course selector (st.html = zero ghost-box footprint)
        st.html("""<style>
        div.st-key-hub_cs_show_cbs_filters { margin-top: 0px !important; margin-bottom: 0px !important; }
        /* Reduce stVerticalBlock gap for the course-selector layer.
           :has() guard scopes this to when the back button is present so the
           rule self-deactivates when the user navigates to other hub layers. */
        div[role="dialog"]:has(.st-key-btn_hub_back_from_course_sel) div[data-testid="stVerticalBlock"] {
            gap: 0.25rem !important;
        }
        /* Restore natural gap for checkbox rows in the course list; they already
           use margin-bottom:-10px tightening so 0.25rem would cause overlap. */
        div[role="dialog"] div[data-testid="stVerticalBlock"]:has(div[class*="st-key-hub_cs_chk_"]) {
            gap: 1rem !important;
        }
        /* Compact "Back to Edit" button - shrink to content height so it doesn't
           create a large visual gap before the "Select Course" heading. */
        div[role="dialog"]:has(.st-key-btn_hub_back_from_course_sel) div.st-key-btn_hub_back_from_course_sel button {
            height: auto !important;
            min-height: 0 !important;
            padding-top: 3px !important;
            padding-bottom: 3px !important;
        }
        /* Scroll container: height:auto lets the list shrink to fit short
           Favorites lists; max-height caps growth so the dialog never
           overflows the viewport - All Courses scrolls internally via
           overflow-y:auto once content exceeds max-height.
           border=True used for reliable st-key-* class; border stripped here. */
        div.st-key-hub_cs_scroll_container {
            border: none !important;
            border-radius: 0 !important;
            height: auto !important;
            min-height: 30vh !important;
            max-height: 40vh !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            padding: 0 !important;
            padding-right: 5px !important;
            margin-top: -0.25rem !important;
            margin-bottom: -0.25rem !important;
        }
        div.st-key-hub_cs_scroll_container > div[data-testid="stVerticalBlock"] {
            padding: 0 !important;
        }
        /* When CBS filters are expanded they add ~100px of extra chrome (filter
           box + toggle). Shrink both max-height and min-height to compensate so
           the dialog stays within the viewport. min-height must not exceed
           max-height, hence both are reduced together. */
        html:has(div.st-key-hub_cs_show_cbs_filters input:checked) div.st-key-hub_cs_scroll_container {
            max-height: 25vh !important;
            min-height: 20vh !important;
        }
        /* Reduce dialog scrollable body top padding so "Back to Edit" sits close
           to the dialog title bar. */
        div[role="dialog"] [data-testid="stDialogScrollableBody"] {
            padding-top: 0.25rem !important;
        }
        </style>""")

        # --- Favorites / All Courses pill toggle ---
        from ui.course_selector import render_favorites_pill
        favorites_only = render_favorites_pill(
            "hub_cs",
            default_favorites=st.session_state.get('hub_cs_filter_favorites', True),
            in_dialog=True,
        )
        st.session_state['hub_cs_filter_favorites'] = favorites_only

        visible_courses = courses
        if favorites_only:
            visible_courses = [c for c in courses if getattr(c, 'is_favorite', False)]

        if not visible_courses:
            st.warning("No courses found with the current filter.")
            return

        # --- CBS Filters (centralized) ---
        from ui.course_selector import inject_course_selector_css, render_cbs_filters, render_course_list
        inject_course_selector_css()
        filtered_courses = render_cbs_filters(visible_courses, "hub_cs")

        # --- Initialize single-select state ---
        if 'hub_cs_selected_id' not in st.session_state or st.session_state.get('hub_cs_selected_id') is None:
            st.session_state['hub_cs_selected_id'] = current_selected_id

        st.html('<hr style="margin-top: 2px; margin-bottom: 4px; border-color: rgba(255,255,255,0.1);" />')

        # --- Scrollable course list (centralized single-select) ---
        # border=True for reliable st-key-* class; border stripped + max-height set in CSS above.
        with st.container(border=True, key="hub_cs_scroll_container"):
            render_course_list(filtered_courses, "hub_cs", multi_select=False,
                               first_item_top_offset="-10px")

        # --- Confirm Selection ---
        st.html('<hr style="margin-top: 2px; margin-bottom: 4px; border-color: rgba(255,255,255,0.1);" />')
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
                  on_click=confirm_course_selection_cb,
                  args=(selected_cid, selected_cname, course_names, courses))

    # =================================================================
    # RESCUE MODE - Remap Missing Folders
    # =================================================================
    elif layer == 'rescue_mode':
        rescue_pairs = st.session_state.get('hub_rescue_pairs', [])
        missing_indices = st.session_state.get('hub_rescue_missing', [])
        rescue_paths = st.session_state.get('rescue_paths', {})
        skipped_count = st.session_state.get('hub_rescue_skipped', 0)
        rescue_gid = st.session_state.get('hub_rescue_group_id')

        st.button("← Back to overview", key="hub_back_rescue", type="tertiary",
                  on_click=change_hub_layer,
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
                    f"<div style='font-weight:600;'>\U0001F393 {esc(display_name)}</div>"
                    f"<div style='font-size:0.82rem; color:{theme.ERROR_LIGHT}; margin-top:2px;'>"  # audit-ignore: old_folder/new_folder are local filesystem paths
                    f"\u274c Missing: <code>{old_folder}</code></div>",
                    unsafe_allow_html=True,
                )
                if new_folder:
                    st.markdown(
                        f"<div style='font-size:0.85rem; color:{theme.SUCCESS}; margin-top:4px;'>"  # audit-ignore
                        f"\u2705 Remapped to: <code>{new_folder}</code></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    all_remapped = False
                    if st.button(f"\U0001F4C2 Locate folder for {display_name}",
                                 key=f"rescue_locate_{mi}", use_container_width=True):
                        rescue_select_folder(mi)

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

            # Merge securely into active sync list
            _add_pairs_batch_lazy(final_pairs)

            # Detect same-course-different-folder overlaps for user awareness
            existing_course_folders = {
                p.get('course_id'): p.get('local_folder')
                for p in st.session_state.get('sync_pairs', [])
            }
            overlap_count = sum(
                1 for p in final_pairs
                if p.get('course_id') in existing_course_folders
                and existing_course_folders[p.get('course_id')] != p.get('local_folder')
            )

            added = len(final_pairs)
            msg = f"\u2705 Added {added} course{'s' if added != 1 else ''} to sync list!"
            if skipped_count:
                msg += f" (Skipped {skipped_count} duplicate{'s' if skipped_count != 1 else ''}.)"
            if overlap_count:
                msg += f" ℹ️ {overlap_count} course{'s' if overlap_count != 1 else ''} already synced to a different folder."
            st.session_state['pending_toast'] = msg
            hub_cleanup()
            st.rerun(scope="app")


def render_hub_config(pair: dict):
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
        raw_secondary = sm._load_metadata('secondary_content_contract')
        
        if not raw_contract:
            st.warning("⚠️ No configuration was found. Run a sync to restore it.")
            return
        contract = _json.loads(raw_contract)
        secondary = _json.loads(raw_secondary) if raw_secondary else {}
    except Exception:
        st.warning("⚠️ Could not read configuration.")
        return

    from ui_shared import render_config_summary_badges

    normalized_settings = {}
    normalized_settings['download_mode'] = raw_mode
    normalized_settings['file_filter'] = contract.get('file_filter', 'all')
    normalized_settings['dl_isolate_secondary'] = secondary.get('isolate_secondary_content', False)
    
    for key, value in secondary.items():
        if key.startswith('download_'):
            new_key = key.replace('download_', 'dl_', 1)
            normalized_settings[new_key] = value
            
    for key, value in contract.items():
        if key.startswith('convert_'):
            normalized_settings[key] = value
            
    st.markdown(render_config_summary_badges(normalized_settings, show_path=False), unsafe_allow_html=True)

def reset_hub_state():
    """Wipes all Hub SPA state to guarantee a fresh Layer 1 start."""
    keys_to_clear = [k for k in st.session_state.keys() if k.startswith('hub_')]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state.pop('rescue_paths', None)


def hub_cleanup():
    """Reset all hub-specific session state keys."""
    for k in ['hub_layer', 'hub_active_group_id',
              'hub_temp_folder', 'hub_temp_course_id',
              'hub_editing_pair_idx', 'hub_edit_temp_folder',
              'hub_edit_temp_course_id', 'hub_edit_temp_course_name',
              'hub_is_adding_new_pair',
              'hub_edit_group_name_active',  # Prevent stale edit-name form on re-entry
              'hub_rescue_group_id', 'hub_rescue_pairs', 'hub_rescue_missing',
              'hub_rescue_skipped', 'rescue_paths']:
        st.session_state.pop(k, None)


# ===================================================================
# STEP 1 - Folder Pairing
# ===================================================================
def inject_hub_global_css():
    """Inject Hub Dialog styling: static CSS from file + dynamic theme overrides."""
    from ui_helpers import get_base64_image
    b64_hub_icon = get_base64_image("assets/icon_sync_hub.png")

    # Static CSS (extracted to styles/sync_hub.css)
    inject_css('sync_hub.css')

    # Dynamic overrides - only rules requiring Python theme variables
    # Use st.html (not st.markdown) to avoid ghost-box 1rem margin above the stepper.
    st.html(f"""<style>
    /* 1. Main Button Icon injected seamlessly next to text */
    div.st-key-btn_hub_main button div[data-testid="stMarkdownContainer"] p {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    div.st-key-btn_hub_main button div[data-testid="stMarkdownContainer"] p::before {{
        content: "";
        display: inline-block;
        width: 28px !important;
        height: 28px !important;
        margin-right: 12px !important;
        background-image: url('data:image/png;base64,{b64_hub_icon}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
    }}



    /* Primary button: theme.BLUE_PRIMARY */
    div[data-testid="stDialog"] button[kind="primary"] {{
        background-color: {theme.BLUE_PRIMARY} !important;
    }}

    /* Cancel save group hover: theme.ERROR */
    div[data-testid="stDialog"] div[class*="st-key-cancel_save_group"] button:hover {{
        background-color: #2e2f3b !important;
        border-color: #5d5e66 !important;
        color: white !important;
    }}

    /* Confirm button hover: theme.BLUE_PRIMARY */
    div[data-testid="stDialog"] div.st-key-btn_inline_new_confirm button:hover {{
        background-color: {theme.BLUE_PRIMARY} !important;
        border-color: {theme.BLUE_PRIMARY} !important;
    }}

    /* =========================================
       COMPACT HUB INLINE EDITOR (NEUTRALIZATION)
       ========================================= */
    /* Force compact dimensions for Change/Select Folder & Course buttons */
    div[data-testid="stDialog"] div[class*="st-key-btn_hub_compact_change_"] button {{
        min-height: auto !important;
        height: 34px !important;
        padding-top: 2px !important;
        padding-bottom: 2px !important;
    }}

    /* Ensure text in compact buttons is perfectly vertically centered */
    div[data-testid="stDialog"] div[class*="st-key-btn_hub_compact_change_"] button p {{
        margin: 0px !important;
        line-height: 1.2 !important;
    }}

    /* Crush vertical gaps inside the compact edit/add forms */
    div[class*="st-key-hub_compact_edit_form_"] [data-testid="stVerticalBlock"],
    div[class*="st-key-hub_compact_add_form"] [data-testid="stVerticalBlock"] {{
        gap: 8px !important; 
    }}

    /* Align row items centrally in the compact forms */
    div[class*="st-key-hub_compact_edit_form_"] [data-testid="stHorizontalBlock"],
    div[class*="st-key-hub_compact_add_form"] [data-testid="stHorizontalBlock"] {{
        align-items: center !important;
    }}

    /* Crush native top padding on the inline edit/add bordered containers */
    div[class*="st-key-hub_compact_edit_form_"],
    div[class*="st-key-hub_compact_add_form"] {{
        padding-top: 0.5rem !important;
    }}
    </style>""")

