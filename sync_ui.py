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
    get_course_display_parts,
    short_path,
    get_base64_image,
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
from ui_shared import render_help_card

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


@st.dialog("\u200b", width="large")
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

    # Step wizard — must be rendered BEFORE any inject_css() calls.
    # inject_hub_global_css() calls inject_css() via st.markdown which creates a
    # 1rem ghost-box margin; rendering the wizard first pins it flush to the top.
    render_sync_wizard(st, 1)

    # Inject all Hub Dialog + Main Button CSS unconditionally
    _inject_hub_global_css()

    # --- Load Premium Assets & Hoist Sync Button CSS ---
    b64_analyze = get_base64_image("assets/icon_sync_review.png")
    b64_quick = get_base64_image("assets/icon_sync_quick.png")
    b64_add = get_base64_image("assets/icon_add.png")

    # Use st.html (not st.markdown) to avoid ghost-box 1rem margin above the stepper.
    st.html(f"""<style>
    div.st-key-btn_analyze_sync button p::before {{
        content: "" !important;
        display: inline-block !important;
        position: relative !important;
        top: 2px !important;
        width: 18px !important;
        height: 18px !important;
        margin-right: 5px !important;
        background-image: url("data:image/png;base64,{b64_analyze}") !important;
        background-repeat: no-repeat !important;
        background-size: contain !important;
    }}
    div.st-key-btn_quick_sync button p::before {{
        content: "" !important;
        display: inline-block !important;
        position: relative !important;
        top: 2px !important;
        width: 18px !important;
        height: 18px !important;
        margin-right: 5px !important;
        background-image: url("data:image/png;base64,{b64_quick}") !important;
        background-repeat: no-repeat !important;
        background-size: contain !important;
    }}

    /* Custom Analyze Review & Sync Colors - Solid Physical Volume */
    div.st-key-btn_analyze_sync button {{
        background-color: #1f77b4 !important;
        border: none !important;
        color: #ffffff !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        transition: background-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }}

    /* Analyze Sync Hover - Glow + Lighter Shift */
    div.st-key-btn_analyze_sync button:hover {{
        background-color: #2b8cbe !important;
        box-shadow: 0 4px 15px rgba(31, 119, 180, 0.2),
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }}

    /* Custom Quick Sync Colors - Dramatic Teal Gradient Physical Volume */
    div.st-key-btn_quick_sync button {{
        background: linear-gradient(135deg, #1e3a8a 0%, #06b6d4 100%) !important;
        border: none !important;
        color: #ffffff !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        transition: filter 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }}

    /* Quick Sync Hover - Glow (0.2 Opacity) + Lighter Gradient Shift via Filter */
    div.st-key-btn_quick_sync button:hover {{
        filter: brightness(1.15) !important;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.2),
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }}

    /* ===== ADD COURSE BUTTON — Base64 Icon via ::before ===== */
    div.st-key-btn_add_folder button p::before,
    div.st-key-btn_add_folder_empty button p::before {{
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
    </style>""")

    # --- Pending toast consumer (fires after dialog rerun) ---
    if 'pending_toast' in st.session_state:
        st.toast(st.session_state.pop('pending_toast'))

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
        base_name, code = get_course_display_parts(c)
        raw_name = f"{base_name} ({code})" if code else base_name
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

    # Help Card Content
    _sync_help_title = "How Sync Mode Works"
    _slbl = "font-size: 1rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; margin: 14px 0 8px 0; color: rgba(255,255,255,0.9);"
    _step_card_r = "flex: 1; min-width: 0; border: 1px solid transparent; border-radius: 14px; background: linear-gradient(#132036, #132036) padding-box, linear-gradient(150deg, #3b71b8 0%, #132036 90%) border-box; padding: 13px 14px;"
    _step_num_r = "flex-shrink: 0; width: 34px; height: 34px; border-radius: 8px; background: #1d3354; display: flex; align-items: center; justify-content: center; font-size: 1.32rem; font-weight: 800; color: #ffffff; line-height: 1;"
    _step_inner = "display: flex; align-items: flex-start; gap: 12px;"
    _step_title = "font-weight: 700; color: #ffffff; font-size: 1.075rem; margin-top: 5px; padding-bottom: 8px; margin-bottom: 8px; background: linear-gradient(to right, rgba(255,255,255,0.2) 0%, rgba(255,255,255,0) 100%) left bottom / 100% 1px no-repeat;"
    _step_body = "font-size: 0.83rem; color: rgba(255,255,255,0.88); line-height: 1.55;"
    _arr_r = "<div style='display:flex;align-items:center;flex-shrink:0;width:44px;align-self:center;margin:0 12px'><div style='flex:1;height:2.5px;background: rgba(255,255,255,0.8);border-radius:2px'></div><div style='width:0;height:0;border-top:6px solid transparent;border-bottom:6px solid transparent;border-left:10px solid rgba(255,255,255,0.8)'></div></div>"
    _cc_base = "flex: 1 1 calc(25% - 12px); min-width: 200px; border-radius: 8px; padding: 11px 12px 10px 12px; display: flex; flex-direction: column;"
    _cc_new = f"{_cc_base} background: rgba(30, 60, 90, 0.25); border: 1px solid rgba(59, 130, 246, 0.65);"
    _cc_clean = f"{_cc_base} background: rgba(20, 70, 40, 0.25); border: 1px solid rgba(34, 197, 94, 0.65);"
    _cc_edited = f"{_cc_base} background: rgba(90, 60, 20, 0.25); border: 1px solid rgba(245, 158, 11, 0.65);"
    _cc_loc_del = f"{_cc_base} background: rgba(90, 30, 35, 0.25); border: 1px solid rgba(239, 68, 68, 0.65);"
    _cc_can_del = f"{_cc_base} background: rgba(60, 30, 90, 0.25); border: 1px solid rgba(168, 85, 247, 0.65);"
    _cc_uptodate = f"{_cc_base} background: rgba(40, 45, 50, 0.25); border: 1px solid rgba(150, 150, 150, 0.5);"
    _cc_ignored = f"{_cc_base} background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(100, 116, 139, 0.65);"
    _cat_name = "font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 6px;"
    _cat_desc = "font-size: 0.83rem; color: rgba(255,255,255,0.9); line-height: 1.5; margin-bottom: 8px;"
    _cat_act = "font-size: 0.83rem; color: rgba(255,255,255,0.9); line-height: 1.5; margin-bottom: 8px;"
    _sb_checked = "font-size: 0.72rem; color: rgba(134,239,172,1); font-weight: 600; background: rgba(0,0,0,0.35); padding: 5px 9px; border-radius: 6px; display: inline-block; margin-top: auto; align-self: flex-start;"
    _sb_unchecked = "font-size: 0.72rem; color: rgba(255,255,255,0.95); font-weight: 600; background: rgba(0,0,0,0.35); padding: 5px 9px; border-radius: 6px; display: inline-block; margin-top: auto; align-self: flex-start;"
    _sb_info = "font-size: 0.72rem; color: rgba(255,255,255,0.9); font-weight: 600; background: rgba(0,0,0,0.35); padding: 5px 9px; border-radius: 6px; display: inline-block; margin-top: auto; align-self: flex-start;"
    _sync_help_text = (
        # -- Intro ---------------------------------------------------------------
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.75); margin-bottom: 10px;'>"
        "<b style='color: #e2e8f0;'>Your task on this page:</b> Add your course/folder pairs, then run a sync to keep your local files up to date with Canvas."
        "</div>"
        "<div style='margin: 6px 0; padding: 9px 12px 9px 14px; background: rgba(63,217,255,0.05); border-radius: 6px; border-left: 3px solid rgba(63,217,255,0.45);'>"
        "<div style='display: flex; align-items: center; gap: 8px; margin-bottom: 4px;'>"
        "<span style='color: #3fd9ff; background: rgba(63,217,255,0.15); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; white-space: nowrap;'>&#9889; Quick Sync</span>"
        "<b style='color: #e2e8f0; font-size: 0.85rem;'>Fast Mode</b>"
        "</div>"
        "<div style='color: rgba(255,255,255,0.7); font-size: 0.85rem;'>Scan and download in one step. Grabs all new files and clean updates only. Automatically skips anything that needs a human decision - files you edited or intentionally deleted. Perfect for between-lecture refreshes.</div>"
        "</div>"
        "<div style='margin: 6px 0; padding: 9px 12px 9px 14px; background: rgba(63,217,255,0.05); border-radius: 6px; border-left: 3px solid rgba(63,217,255,0.45);'>"
        "<div style='display: flex; align-items: center; gap: 8px; margin-bottom: 4px;'>"
        "<span style='color: #3fd9ff; background: rgba(63,217,255,0.15); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; white-space: nowrap;'>&#128269; Analyze &amp; Review</span>"
        "<b style='color: #e2e8f0; font-size: 0.85rem;'>Full Control Mode</b>"
        "</div>"
        "<div style='color: rgba(255,255,255,0.7); font-size: 0.85rem;'>Scan Canvas, then see every new, updated, and deleted file before anything downloads. Review each category, adjust checkboxes, ignore files permanently, then confirm. Nothing happens until you click Sync.</div>"
        "</div>"
        "<hr>"

        # -- Get Started: Add a Course Pair --------------------------------------
        "<div style='font-weight: 700; color: #ffffff; font-size: 1.25rem; margin-bottom: 8px;'>&#128194; Get started with syncing: Add a Course Pair</div>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65; margin-bottom: 6px;'>"
        "A <b>Course Pair</b> links one local folder on your computer to one Canvas course. The sync engine reads Canvas and writes to that folder, tracking every file in a hidden database stored inside it - this is how it knows what you already have, what you edited, and what to skip.<br><br>"
        "Click <b>Add Course</b>. In the dialog, pick your local folder (e.g. <em>C:\\Users\\You\\Documents\\CHEM101</em>), then select the matching Canvas course from the dropdown. Click Confirm. The pair is saved permanently - you only do this once per course.<br><br>"
        "One folder = one course = one database. Multiple courses cannot share the same folder."
        "</div>"
        "<hr>"

        # -- Saved Groups & Pairs ------------------------------------------------
        "<span style=\"font-weight: 700; color: #ffffff; font-size: 1.25rem;\">💾 How to use Saved Groups & Pairs</span><br>"

        "<span style=\"font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65;\">"
            "The <b>Saved Groups & Pairs</b> hub (button in the top right) lets you manage all your added Course Pairs and Groups so you only have to save them once.<br>In the Saved Groups & Pairs hub you can manage your saved groups and pairs, load them onto the Sync list, or delete them if no longer needed. <br>"
        "</span><br><br>"

        "<span style=\"font-weight: 600; color: #e2e8f0; font-size: 0.87rem;\">Save a Pair</span><br>"
        "<span style=\"font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65;\">"
            "After adding a pair to the Sync List, click the save icon 💾 on the top right of the pair card. Give it a name, and save it. It is now stored in the hub and can be loaded in a single click in any future session."
        "</span><br><br>"

        "<span style=\"font-weight: 600; color: #e2e8f0; font-size: 0.87rem;\">Save a Group</span><br>"
        "<span style=\"font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65;\">"
            "A Group is a named collection of multiple pairs - for example, all your semester courses. Add all the pairs you want on the sync page, open the hub, and click the <b>Save Group</b> button next to 'add course'. <br>Now the group, with all your course pairs, can be loaded onto the sync list in a single click next session.<br>Notice: Pairs can be saved individually AND in groups - one doesn't exclude the other. <br> You can only save groups when there are 2 or more course pairs on the Sync list. You cannot save groups that already have been saved. "
        "</span><br><br>"

        "<span style=\"font-weight: 600; color: #e2e8f0; font-size: 0.87rem;\">Load from the Hub</span><br>"
        "<span style=\"font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65;\">"
            "Click <b>Saved Groups & Pairs</b> in the top right. Browse your saved groups and individual pairs. Click any entry to load it onto the sync page instantly. You can load multiple groups one after another to build a combined list. Both Pairs and Groups can be viewed and edited (e.g. change name, update course folder path if it was changed, etc) - all from the sync hub. You can even add brand new course pairs to a group from the hub itself! The individual configuration (Download settings set initially for each course folder downloaded) is viewable in the Saved Groups & Pairs hub, for each pair."
        "</span><br><br>"


        # -- Workflow ------------------------------------------------------------
        "<div style='font-weight: 700; color: #ffffff; font-size: 1.25rem; margin-bottom: 10px;'>&#128260; The Sync process - how to sync.</div>"

        # Workflow container
        "<div style='background: #0f0f0f; border: 1px solid rgba(255,255,255,0.09); border-radius: 12px; padding: 16px 18px; margin-bottom: 8px;'>"

        # Quick Sync flow
        f"<div style='{_slbl} margin-top: 0;'>⚡ Quick Sync</div>"
        "<div style='display: flex; align-items: center; margin-bottom: 14px;'>"
        f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>1</div><div>"
        f"<div style='{_step_title}'>👆 Click Quick Sync</div>"
        f"<div style='{_step_body}'><ul><li>Starts analysis of the courses on your Sync list.</li><li>Analysis scans Canvas, compares every file to your local course folder.</li><li><b>Looks for all new or updated files.</b></li></ul></div>"
        f"</div></div></div>{_arr_r}"
        f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>2</div><div>"
        f"<div style='{_step_title}'>📥 Downloading</div>"
        f"<div style='{_step_body}'><ul><li>New files and clean updates download automatically.</li><li>Files you have edited or deleted are automatically skipped and not downloaded.</li><li>Watch the download progress on the dashboard.</li></ul></div>"
        f"</div></div></div>{_arr_r}"
        f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>3</div><div>"
        f"<div style='{_step_title}'>✅ Done</div>"
        f"<div style='{_step_body}'><b>Sync & Download complete! Your course folders are now fully up to date.</b><br><ul><li>See which files were downloaded for each course, and any errors.</li><li>Use the <b style='color: #e2e8f0;'>retry button</b> for any failed downloads.</li><li>Use the <b style='color: #e2e8f0;'>Open Folder</b> button to see the synced course folder directly</li></ul></div>"
        "</div></div></div>"
        "</div>"
        "<hr>"

        # Analyze, Review & Sync flow
        f"<div style='{_slbl}'>🔍 Analyze, Review &amp; Sync</div>"
        "<div style='display: flex; align-items: center; margin-bottom: 0;'>"
        f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>1</div><div>"
        f"<div style='{_step_title}'>👆 Click Analyze, Review & Sync</div>"
        f"<div style='{_step_body}'><ul><li>Starts analysis of the courses on your Sync list.</li><li> Analysis scans Canvas, compares every file to your local course folder.</li><li> <b>Looks for all files with changes, and sorts them into 7 categories.</b></li></ul></div>"
        f"</div></div></div>{_arr_r}"
        f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>2</div><div>"
        f"<div style='{_step_title}'>🔍 Review changes</div>"
        f"<div style='{_step_body}'><ul><li>All files that have changes are organized here by category. </li><li>Select files you want to download.</li><li>Deselect files you don't want to download</li><li>Ignore files to skip and hide in future syncs.</li><li>Click <b>Sync &amp; Download</b> to continue.</li></ul></div>"
        f"</div></div></div>{_arr_r}"
        f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>3</div><div>"
        f"<div style='{_step_title}'>👁️ Confirm &amp; Download</div>"
        f"<div style='{_step_body}'><ul><li>A pop-up shows you everything you need to know about the files that will be downloaded. </li><li>Click Confirm to download, or go back to review page and make changes.</li></ul></div>"
        f"</div></div></div>{_arr_r}"
        f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>4</div><div>"
        f"<div style='{_step_title}'>📥 Downloading</div>"
        f"<div style='{_step_body}'><ul><li>Files selected to download in the review page, will download.</li><li>Watch the download progress on the dashboard.</li></ul></div>"
        f"</div></div></div>{_arr_r}"
        f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>5</div><div>"
        f"<div style='{_step_title}'>✅ Done!</div>"
        f"<div style='{_step_body}'><b>Sync & Download complete! Your course folders are now fully up to date.</b><br><ul><li>See which files were downloaded for each course, and any errors.</li><li>Use the <b style='color: #e2e8f0;'>retry button </b>for any failed downloads.</li><li>Use the <b style='color: #e2e8f0;'>Open Folder</b> button to see the synced course folder directly</li></ul></div>"
        "</div></div></div>"
        "</div>"
        "</div>"
        "<hr>"

        # -- File Categories -----------------------------------------------------
        "<div style='font-weight: 700; color: #ffffff; font-size: 1.25rem; margin-bottom: 4px;'>&#128202; Sync Review: The 7 file categories explained.</div>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.85); margin-bottom: 10px;'>After Analyze runs, every file lands in exactly one of these categories. Understanding them tells you what the app will do - and what it won't.</div>"
        f"<div style='display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 4px;'>"
        f"<div style='{_cc_new}'>"
        f"<div style='{_cat_name}'>New Files</div>"
        f"<div style='{_cat_desc}'>Files on Canvas added by your teacher, that are not in your course folder yet.</div>"
        f"<div style='{_cat_act}'>Downloaded fresh into the correct subfolder.</div>"
        f"<div style='{_sb_checked}'>✔ Checked by default</div>"
        "</div>"
        f"<div style='{_cc_clean}'>"
        f"<div style='{_cat_name}'>Updates (Clean)</div>"
        f"<div style='{_cat_desc}'>Canvas has a newer version of a file in your course folder that is untouched.</div>"
        f"<div style='{_cat_act}'>The file will be replaced with the newest version - same name, same location.</div>"
        f"<div style='{_sb_checked}'>✔ Checked by default</div>"
        "</div>"
        f"<div style='{_cc_edited}'>"
        f"<div style='{_cat_name}'>Updates (You Edited)</div>"
        f"<div style='{_cat_desc}'>Canvas has a newer version AND your copy changed.</div>"
        f"<div style='{_cat_act}'>New version saved with '_NewVersion' alongside your original: Your edited file is untouched.</div>"
        f"<div style='{_sb_unchecked}'>☐ Unchecked by default</div>"
        "</div>"
        f"<div style='{_cc_loc_del}'>"
        f"<div style='{_cat_name}'>Locally Deleted</div>"
        f"<div style='{_cat_desc}'>You deleted a file from your course folder, but Canvas still has it.</div>"
        f"<div style='{_cat_act}'>App assumes the deletion was intentional - won't redownload it unless you check the box.</div>"
        f"<div style='{_sb_unchecked}'>☐ Unchecked by default</div>"
        "</div>"
        f"<div style='{_cc_can_del}'>"
        f"<div style='{_cat_name}'>Deleted on Canvas</div>"
        f"<div style='{_cat_desc}'>The teacher removed a file from Canvas, but it is still in your course folder.</div>"
        f"<div style='{_cat_act}'>Your local copy stays exactly where it is. The app never deletes local files.</div>"
        f"<div style='{_sb_info}'>ℹ Info only - no action</div>"
        "</div>"
        f"<div style='{_cc_ignored}'>"
        f"<div style='{_cat_name}'>Ignored Files</div>"
        f"<div style='{_cat_desc}'>Files you permanently skipped, so they never appear in future syncs.</div>"
        f"<div style='{_cat_act}'>Restore them any time in the <b>Ignored Files</b> section in Sync Review or the Sync front page.</div>"
        f"<div style='{_sb_info}'>Permanent skip</div>"
        "</div>"
        f"<div style='{_cc_uptodate}'>"
        f"<div style='{_cat_name}'>Up to Date</div>"
        f"<div style='{_cat_desc}'>File is identical on both sides: Your local file matches Canvas.</div>"
        f"<div style='{_cat_act}'>Hidden from the review screen since no action is needed.</div>"
        f"<div style='{_sb_info}'>Hidden - nothing to do</div>"
        "</div>"
        "</div>"
        "<hr>"

        # -- Quick Sync vs Analyze -----------------------------------------------
        "<div style='font-weight: 700; color: #ffffff; font-size: 1.25rem; margin-bottom: 8px;'>&#9889; Quick Sync vs Analyze &amp; Review &amp; Sync</div>"
        "<div style='font-size: 0.85rem; color: #e6e6e6; margin-bottom: 10px;'>Both modes scan Canvas - the difference is the usecase, and how much control you have over what gets downloaded.</div>"
        "<div style='display: flex; gap: 16px; margin-bottom: 16px;'>"
        "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
        "<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>⚡Quick Sync</div>"
        "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.7;'>"
        "✅ Auto-download all new files<br>"
        "✅ Auto-update unedited files that have changes in canvas<br>"
        "✅ Quick & Easy - press the button and let the app work for you<br>"
        "✅ Skips ignored, locally deleted, & Edited files with updates automatically<br>"
        "❌ Doesn't allow re-download of ignored, locally deleted, or edited files with updates<br>"
        "❌ Doesn't show any canvas/folder changes, only which files were downloaded (after quick sync finished)<br><br>"
        "<span style='color: rgba(255,255,255,0.9); font-size: 0.82rem;font-weight: 800;'>Best for:</span> "
        "<span style='color: rgba(255,255,255,0.9); font-size: 0.82rem;font-weight: 600;'>Quick everyday use between lectures, morning catch-up - whenever you need the latest files from canvas as quick as possible.</span>"
        "</div></div>"
        "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
        "<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>🔍 Analyze, Review &amp; Sync</div>"
        "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.7;'>"
        "✅ Full overview over all course folder & canvas changes over 7 different categories<br>"
        "✅ Select per-file what you want to download, and what you don't - full control<br>"
        "✅ Ignored files management: Ignore new files, or restore & download previously ignored files<br>"
        "✅ Filter by file extension for easy selection<br>"
        "✅ See all files to be downloaded and important metrics before you download<br>"
        "❌ More time-consuming than Quick-sync<br><br>"
        "<span style='color: rgba(255,255,255,0.9); font-size: 0.82rem; font-weight: 800;'>Best for:</span> "
        "<span style='color: rgba(255,255,255,0.9); font-size: 0.82rem; font-weight: 600;'>Exam prep, before a studying block, or whenever you need to see the full picture & ensure course folders on your pc are 100% up-to-date with canvas.</span>"
        "</div></div>"
        "</div>"
        "<div style='background: rgba(0,0,0,0.0); border-radius: 7px; padding: 15px 15px;'>"
        "<span style='font-size: 1rem; font-weight: 700; letter-spacing: 0.07em; margin-top: 0px; margin-bottom: 0px; color: rgba(255,255,255,0.9);'>When to use which - examples</span>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.75); line-height: 2; margin-top: 5px;'>"
        "<b style='color: #e2e8f0;'>Checking for new files between classes</b> ➜ Quick Sync<br>"
        "<b style='color: #e2e8f0;'>Start-of-week catch-up on your courses</b> ➜ Quick Sync<br>"
        "<b style='color: #e2e8f0;'>Just before an exam, you want to ensure course folders are fully up to date</b> ➜ Analyze &amp; Review<br>"
        "<b style='color: #e2e8f0;'>You have been editing files</b> ➜ Analyze &amp; Review<br>"
        "<b style='color: #e2e8f0;'>First time setting up a new course folder</b> ➜ Analyze &amp; Review"
        "</div></div>"
        "<hr>"

        # -- Safety Guarantees ---------------------------------------------------
        "<div style='font-weight: 700; color: #ffffff; font-size: 1.25rem; margin-bottom: 8px;'>🤝 Safety Guarantees</div>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.8); line-height: 2.0;'>"
        "Syncing may seem scary, but we made it totally safe. Here's what the app will <b style='color: #e2e8f0;'>never</b> do:<br>"
        "<b style='color: #e2e8f0;'>🚫 Will never overwrite a file you edited</b> - If a teacher updates (changes content & reuploads with same name) a file you edited on your pc, the edited file will be preserved, and the updated file on canvas will download with '_NewVersion' added to the name.<br>"
        "<b style='color: #e2e8f0;'>🚫 Will never delete your local files</b> - not even when the teacher removes them from Canvas. Your disk is yours. Bonus: If you ever delete a file, run a Analyze, Review & Sync to re-download it, fresh from canvas)<br>"
        "<b style='color: #e2e8f0;'>🚫 Will never re-download files you intentionally deleted</b> - unless you explicitly check the box for a given locally deleted file in the Sync Review page, your files will stay deleted.<br>"
        "<b style='color: #e2e8f0;'>🚫 Will never create duplicate files</b> - every download is tracked; re-downloads either cleanly overwrites or produces a clearly-named '_NewVersion' version of your files. We keep your course folder tidy.<br>"
        "<b style='color: #e2e8f0;'>🚫 Will never touch files outside your paired folder</b> - the Sync engine only operates inside the folders you explicitly link to a course, and only modifies files when you run a Sync"
        "</div>"
        "<hr>"

        # -- FAQ -----------------------------------------------------------------
        "<details style='margin-top: 4px;'>"
        "<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>&#10067; Frequently Asked Questions</summary>"
        "<div style='margin-top: 6px; padding-left: 12px;'>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is the difference between Sync Mode and Download Mode?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Download Mode always fetches a complete fresh copy of everything - it has no memory of what you already have. Sync Mode tracks every file you have ever downloaded in a hidden database, compares your local folder against Canvas, and only fetches what is new or changed. Use Download Mode for a first-time full backup; use Sync Mode for all ongoing maintenance."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>I renamed a file locally - will sync break or create a duplicate?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "No. Before every analysis, the engine runs a heal step that scans your folder for renamed or moved files. It uses three tiers: exact filename match, exact content fingerprint (MD5), and fuzzy name similarity (over 85% similar). If it finds a match, the internal record is updated. You can rename and reorganize freely."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>My professor updated a lecture PDF I annotated heavily. What exactly happens?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "It appears in Updates - You Edited, unchecked by default. If you check it, the corrected version is saved as <em>Lecture_3_NewVersion.pdf</em> alongside your annotated original. Your annotations are never touched. If you leave it unchecked, nothing changes. Quick Sync skips it entirely."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Will a file appear as an update if the professor only changed its description on Canvas?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Not if Canvas exposes its own MD5 hash for the file (which it usually does). The engine compares Canvas's MD5 against its stored fingerprint. If they match byte-for-byte, the file stays in Up to Date regardless of the bumped timestamp. Touch events that change nothing about the actual content generate no sync action."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is a Course Pair and do I need one per course?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Yes - one pair per course. A pair links a specific local folder to a specific Canvas course. The sync engine reads Canvas and writes to that folder, tracking everything in a hidden database stored inside it. Multiple courses cannot share a folder. Adding a pair takes about 10 seconds and is saved permanently."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is a Saved Group?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "A Group is a named collection of course pairs saved for reuse. For example, save all 5 of this semester's courses as Semester 1 2026. Next time you open Sync Mode, click that group to load all 5 pairs instantly. Groups are managed via the Saved Groups and Pairs button."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>I moved my course folder to a different drive. Will sync still work?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "You need to update the pair: click the edit icon on the affected pair and re-select the folder at its new location. The hidden .canvas_sync.db database lives inside the folder and travels with it, so all sync history and fingerprints are preserved automatically."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Can Quick Sync run all my courses at once?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Yes - add all your course pairs to the list on this page, then click Quick Sync All. Every pair is scanned and synced in sequence. New files and clean updates across all courses are downloaded in one run. If any course has edited or locally-deleted files, those are reported afterward so you can handle them in Analyze and Review."
        "</div></details>"
        "</div>"
        "</details>"
    )

    # --- (8) Bigger subheading + Help + Hub button ---
    # Snug Header Hack — H2 + Help button on one flex row
    st.html("""
        <style>
        div.st-key-sync_title_help_row [data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            gap: 0px !important;
            justify-content: flex-start !important;
        }
        div.st-key-sync_title_help_row [data-testid="column"],
        div.st-key-sync_title_help_row [data-testid="stColumn"] {
            width: auto !important;
            flex: 0 0 auto !important;
            min-width: 0px !important;
            padding: 0 !important;
        }
        div.st-key-sync_title_help_row h2 {
            margin-right: 0 !important;
            padding-right: 0 !important;
        }
        div.st-key-sync_title_help_row div[class*="st-key-sync_setup_explainer_help_btn"] {
            margin-bottom: -20px !important;
            margin-top: 10px !important;
            margin-left: 0 !important;
        }
        </style>
    """)

    col_heading, col_hub = st.columns([0.7, 0.3], vertical_alignment="center")
    with col_heading:
        with st.container(key="sync_title_help_row"):
            _c1, _c2 = st.columns([1, 10])
            with _c1:
                st.markdown(
                    '<h2 style="margin: 0; white-space: nowrap;">Canvas Courses to Sync</h2>',
                    unsafe_allow_html=True,
                )
            with _c2:
                render_help_card(
                    key_prefix="sync_setup",
                    title=_sync_help_title,
                    text_html=_sync_help_text,
                    icon="💡",
                    mode="button"
                )
    with col_hub:
        if st.button("Saved Groups & Pairs", key="btn_hub_main",
                     use_container_width=True):
            _reset_hub_state()
            _saved_groups_hub_dialog(courses, course_names)

    # Help Card Expansion (renders below the header + hub button row if open)
    render_help_card(
        key_prefix="sync_setup",
        title=_sync_help_title,
        text_html=_sync_help_text,
        icon="💡",
        mode="card"
    )

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

    # Load ignore icon for CSS injection
    _b64_icon_ignore = get_base64_image("assets/Icon_Ignore.svg")

    # Inject ignore icon CSS for "Ignored Files" buttons (needs f-string for b64 variable)
    st.html(f"""<style>
    div[class*="st-key-ignored_btn_"] button p::before {{
        content: '';
        display: inline-block;
        width: 19px;
        height: 19px;
        background-image: url('data:image/svg+xml;base64,{_b64_icon_ignore}');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: brightness(0) invert(1) opacity(0.9);
        vertical-align: middle;
        margin-right: 6px;
        flex-shrink: 0;
        position: relative;
        top: -1px;
    }}
    </style>""")

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

    /* Fix Streamlit tooltip wrappers shrinking buttons vertically */
    div[class*="st-key-open_folder_"] div[data-testid="stTooltipHoverTarget"],
    div[class*="st-key-ignored_btn_"] div[data-testid="stTooltipHoverTarget"] {
        display: block !important;
        width: 100% !important;
    }
    
    div[class*="st-key-open_folder_"] button,
    div[class*="st-key-ignored_btn_"] button,
    div[class*="st-key-edit_pair_"] button,
    div[class*="st-key-remove_pair_"] button {
        height: 42px !important;
        min-height: 42px !important;
    }

    /* Restore neutral grey hover for inline non-destructive cancel buttons in Sync UI */
    div[class*="st-key-cancel_pair"] button:hover,
    div[class*="st-key-cancel_add"] button:hover {
        border-color: rgba(255, 255, 255, 0.2) !important;
        background-color: rgba(255, 255, 255, 0.1) !important;
        color: #ffffff !important;
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

    /* 12. Sync Pair Cards Gradient Styling */
    div[class*="st-key-sync_pair_card_"] {
        background: linear-gradient(180deg, #252830 0%, #32363f 100%) !important;
        border: 1px solid rgba(255, 255, 255, 0.25) !important;
        border-radius: 8px !important;
        padding-top: 5px !important;
        padding-bottom: 20px !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25) !important;
    }

    /* Ignored Files button: match standard action button border style */

    </style>
    """, unsafe_allow_html=True)

    # --- Pre-compute ignored files per course (needed for per-course buttons) ---
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
                        "This pair is saved - go to Saved Groups & Pairs to see, rename, or edit."
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
                        st.markdown(f"""<div style="font-size:0.85em;color:rgba(255, 255, 255, 0.9);margin-top:-10px;">\U0001F4C1 {folder_display}</div>  <!-- # audit-ignore: folder_display is a local path -->
                            <div style="font-size:0.75em;color:rgba(255, 255, 255, 0.8);margin-top:2px;">\U0001F553 {ts_str}</div>""", unsafe_allow_html=True)

                # (4) Action buttons with text labels restored
                with col_open:
                    if folder_exists:
                        if st.button("📂 " + 'Open Folder',
                                     key=f"open_folder_{idx}", use_container_width=True):
                            open_folder(pair['local_folder'])
                    else:
                        st.button("📂 " + 'Open Folder',
                                     key=f"open_folder_{idx}", use_container_width=True, disabled=True,
                                     help="This folder could not be found (it may have been deleted or moved).")

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
                    ignored_help = "No files have been ignored for this course." if ignored_count == 0 else None
                    if st.button(f"Ignored Files \u00A0:gray[({ignored_count})]", key=f"ignored_btn_{idx}",
                                 disabled=(ignored_count == 0), use_container_width=True, help=ignored_help):
                        course_data = ignored_by_course.get(pair['course_id'])
                        if course_data:
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
                        border: none !important;
                        background-color: #0b5a6e !important;
                        color: #ffffff !important;
                        margin-top: -50px !important;
                        position: relative;
                        z-index: 1;
                        opacity: 1 !important;
                        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
                        transition: background-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
                    }
                    div.st-key-btn_add_folder button:hover {
                         background-color: #106e85 !important;
                         border: none !important;
                         color: #ffffff !important;
                         box-shadow: 0 4px 15px rgba(11, 90, 110, 0.25),
                                     inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
                    }
                    </style>""", unsafe_allow_html=True)
                    
                    if st.button('Add Course', key="btn_add_folder", use_container_width=True):
                        _select_sync_folder()
                        st.session_state['sync_selected_course_id'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.rerun()

                with col_save:
                    # Disable if < 2 pairs or current list matches an already saved group
                    # Reusing the existing _saved_mgr instance from the top of the render loop
                    _save_disabled = len(sync_pairs) < 2 or _saved_mgr.matches_existing_group(sync_pairs)
                    _save_group_help = "Save this exact list of courses as a group."
                    if _save_disabled:
                        _save_group_help = "You need at least 2 courses to save a group." if len(sync_pairs) < 2 else "This exact group of courses is already saved."

                    # Clean, isolated CSS for "Save List" using its Streamlit key
                    st.markdown("""<style>
                    div.st-key-btn_save_group_main div[data-testid="stTooltipHoverTarget"] {
                        margin-top: -50px !important;
                        position: relative;
                        z-index: 1;
                        display: block !important;
                        width: 100% !important;
                    }
                    div.st-key-btn_save_group_main button {
                        background-color: rgba(95, 100, 200, 0.075) !important;
                        color: #e0e7ff !important;
                        border: 1px solid rgba(95, 100, 200, 0.75) !important;
                        width: 100% !important;
                        height: 48px !important;
                        min-height: 48px !important;
                    }
                    div.st-key-btn_save_group_main button:hover {
                        background-color: rgba(95, 100, 200, 0.2) !important;
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

                    if st.button("💾 Save as Group", key="btn_save_group_main", disabled=_save_disabled, use_container_width=True, help=_save_group_help):
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
                        border: none !important;
                        background-color: #0b5a6e !important;
                        color: #ffffff !important;
                        margin-top: -15px !important;
                        opacity: 1 !important;
                        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
                        transition: background-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
                    }
                    div.st-key-btn_add_folder_empty button:hover {
                         background-color: #106e85 !important;
                         border: none !important;
                         color: #ffffff !important;
                         box-shadow: 0 4px 15px rgba(11, 90, 110, 0.25),
                                     inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
                    }
                    </style>""", unsafe_allow_html=True)
    
                    if st.button('Add Course', key="btn_add_folder_empty", use_container_width=True):
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
        if st.button('Analyze, Review & Sync', type="primary",
                     key="btn_analyze_sync",
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
        st.markdown(f"<div style='text-align:center; font-weight:bold; color:{theme.TEXT_DIM}; font-size:0.9em;'>OR</div>", unsafe_allow_html=True)

    with col_quick:
        if st.button('Quick Sync All',
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
        st.markdown("**Smart Sync keeps your local folders up-to-date without ever destroying your work.**\n\n1. **Add a Folder**: Select an existing course folder on your computer and pair it with the corresponding Canvas course.\n2. **Analyze**: We compare your local files with Canvas — including a content-hash check to detect whether you've edited anything locally.\n3. **Review**: You'll see exactly what changed:\n   - 🆕 **New Files**: Downloaded to your folder.\n   - 🔄 **Updates Available**: Your local copy hasn't been edited, so it's replaced in place with the newer Canvas version. No clutter.\n   - ✏️ **Updates Available — You've Edited These**: Canvas has a newer version but you've modified your local copy. Off by default; if you opt in, the new version is saved alongside as `_NewVersion` — your edits are never touched.\n   - ↩️ **Locally Deleted**: Files you deleted locally. Off by default — your deletion is treated as intentional.\n   - 🗑️ **Deleted on Canvas (Kept Locally)**: Files removed by the teacher are preserved safely on your computer.\n\n*Tip: Use **⚡ Quick Sync All** to skip the review and instantly download new and clean updates across all your courses. Files you've edited are always left for manual review.*")
    _render_sync_history()


def _render_sync_history():
    """Delegate to ui.sync_dialogs."""
    from ui.sync_dialogs import render_sync_history
    render_sync_history()




def _show_course_ignored_files(course_name, course_id, course_data):
    """Delegate to ui.sync_dialogs."""
    from ui.sync_dialogs import show_course_ignored_files
    show_course_ignored_files(course_name, course_id, course_data)




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
def _show_sync_confirmation(sync_selections, count, size, folders, avail_mb, _total_mb, _target_folder, total_bytes):
    """Delegate to ui.sync_confirmation."""
    from ui.sync_confirmation import show_sync_confirmation_inner
    show_sync_confirmation_inner(sync_selections, count, size, folders, avail_mb, _total_mb, _target_folder, total_bytes)


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
