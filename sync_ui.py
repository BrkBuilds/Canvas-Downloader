"""
Sync UI Module - All sync-related Streamlit UI logic.
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
from ui_shared import SVG_FOLDER_YELLOW, SVG_CLOCK, SVG_SAVE_COLORFUL
from sync_manager import SyncManager, SavedGroupsManager
from ui_helpers import (
    esc,
    open_folder,
    render_sync_wizard,
    friendly_course_name,
    get_course_display_parts,
    short_path,
    get_base64_image,
    format_relative_date,
    format_time_display,
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
from ui_shared import render_help_card, HELP_ICONS

logger = logging.getLogger(__name__)

# ── Module-level help card constants (computed once at import, not on every render) ──

_SYNC_HELP_TITLE = "How Sync Mode Works"
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
_cc_loc_del = f"{_cc_base} background: rgba(60, 30, 90, 0.25); border: 1px solid rgba(168, 85, 247, 0.65);"
_cc_can_del = f"{_cc_base} background: rgba(90, 30, 35, 0.25); border: 1px solid rgba(239, 68, 68, 0.65);"
_cc_uptodate = f"{_cc_base} background: rgba(40, 45, 50, 0.25); border: 1px solid rgba(150, 150, 150, 0.5);"
_cc_ignored = f"{_cc_base} background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(100, 116, 139, 0.65);"
_cat_name = "font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 6px;"
_cat_desc = "font-size: 0.83rem; color: rgba(255,255,255,0.9); line-height: 1.5; margin-bottom: 8px;"
_cat_act = "font-size: 0.83rem; color: rgba(255,255,255,0.9); line-height: 1.5; margin-bottom: 8px;"
_sb_checked = "font-size: 0.72rem; color: rgba(134,239,172,1); font-weight: 600; background: rgba(0,0,0,0.35); padding: 5px 9px; border-radius: 6px; display: inline-block; margin-top: auto; align-self: flex-start;"
_sb_unchecked = "font-size: 0.72rem; color: rgba(255,255,255,0.95); font-weight: 600; background: rgba(0,0,0,0.35); padding: 5px 9px; border-radius: 6px; display: inline-block; margin-top: auto; align-self: flex-start;"
_sb_info = "font-size: 0.72rem; color: rgba(255,255,255,0.9); font-weight: 600; background: rgba(0,0,0,0.35); padding: 5px 9px; border-radius: 6px; display: inline-block; margin-top: auto; align-self: flex-start;"
_SYNC_HELP_TEXT = (
    # -- Introduction --------------------------------------------------------
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.85); line-height: 1.7; margin-bottom: 12px;'>"
    f"Welcome to Sync Mode! This feature intelligently keeps the course folders on your PC up to date with Canvas by remembering exactly which files you downloaded for each course, and thereby only fetching files that are new or changed on Canvas. <br>To begin, link a course folder to a Canvas course to create a <b style='color: #ffffff;'>Course Pair</b>. These pairs are added to your <b style='color: #ffffff;'>Sync List</b>, which you can save as a <b style='color: #ffffff;'>Saved Group</b> (e.g., <em>Semester 1</em>), or separately as a <b style='color: #ffffff;'>Saved Pair</b> to easily load in next time. <br>When you are ready to download, use <b style='color: #3fd9ff;'>{HELP_ICONS['bolt']} Quick Sync</b> to automatically grab new files and safe updates in one click, or use <b style='color: #3fd9ff;'>{HELP_ICONS['search']} Analyze &amp; Review</b> to manually inspect every change and select what to keep."
    "</div>"
    "<hr>"

    # -- Sync Mode Fundamentals & Getting Started ----------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['folder']} Sync mode fundamentals &amp; getting started</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    
    # Introduction & How to add
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.6; margin-bottom: 12px;'>"
    "A <b style='color: #ffffff;'>Course Pair</b> permanently links a local course folder on your computer (e.g., Documents\\<b>CHEM101</b>) to its matching Canvas course.<br>"
    "Click <b style='color: #ffffff;'>+ Add Course</b> on the Sync mode's front page to add a pair to the Sync List.<br>"
    "Once linked, clicking <b style='color: #ffffff;'>Quick Sync</b> or <b style='color: #ffffff;'>Analyze</b> will automatically process every course pair currently on your Sync List."
    "</div>"

    # Vertical Sections
    "<div style='display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px;'>"
    
    # The Hidden Database
    "<div>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 4px;'>{HELP_ICONS['database']} The Hidden Database</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Inside every synced folder, the app places a tiny, hidden database file. This acts as the folder's memory, tracking what you've already downloaded, what you've edited, and what to skip.<br>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.6; margin-bottom: 12px;'>If you link a pre-existing folder, the app will scan Canvas to look for file matches and build this memory from scratch. <br><b style='color: #ffffff;'>For best results, we recommend linking folders originally downloaded via Canvas Downloader</b>.<br>"
    "<div style='display: inline-block; margin-top: 6px; padding: 4px 8px; background: rgba(147, 90, 0, 0.4); border-radius: 4px; color: rgba(255,255,255,0.9); font-size: 0.75rem; line-height: 1.4;'>"
    "<b style='color: #ffffff;'>Notice:</b> One folder = one course. Sync won't work as intended if you mix files from multiple Canvas courses into the same Course Folder."
    "</div>"
    "</div>"
    "</div>"

    # Download Configurations
    "<div>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 4px;'>{HELP_ICONS['gear']} Syncing &amp; Download settings</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "<b style='color: #ffffff;'>Courses inherit their original download settings.</b>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;margin-bottom: 8px;'>If you initially downloaded a course with AI Optimization settings enabled, the sync engine will automatically apply those same conversions to any new files that you sync &amp; download.<br>"
    "Want to change these settings? Just re-download the course into a new folder with your preferred configuration."
    "</div>"
    "</div>"

    "</div>"

    # Managing Course Pair
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 4px;'>{HELP_ICONS['wrench']} Managing your Course Pair</div>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.5; margin-bottom: 12px;'>"
    "Each course pair card on your list has inline actions to help you manage it:"
    "<ul style='margin-top: 4px; margin-bottom: 0; padding-left: 20px;'>"
    "<li><b style='color: #ffffff;'>Open folder:</b> Instantly opens the local course folder in your file explorer.</li>"
    "<li><b style='color: #ffffff;'>Edit:</b> Change the course's display name or update the folder path (e.g., if you moved the folder to a new drive).</li>"
    "<li><b style='color: #ffffff;'>Ignored files:</b> View, manage, and restore any files you permanently skipped for this course.</li>"
    "<li><b style='color: #ffffff;'>Remove:</b> Removes the course from the Sync List (this will never delete your local files).</li>"
    "</ul>"
    "</div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- Saved Groups & Pairs ------------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['sync_hub']} How to use Saved Groups &amp; Pairs</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65; margin-bottom: 14px;'>"
    "The <b style='color: #ffffff;'>Saved Groups &amp; Pairs</b> hub (button in the top right) lets you manage all your added Course Pairs and Groups so you only have to save them once.<br>"
    "In the hub, you can manage your saved groups and pairs, load them onto the Sync List, or delete them if no longer needed."
    "</div>"

    "<div style='display: flex; gap: 16px; margin-bottom: 16px;'>"
    # Save a Pair
    "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>{HELP_ICONS['sync_pair']} Save a Pair</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    f"After adding a pair to the Sync List, click the save icon {SVG_SAVE_COLORFUL} on the top right of the pair card. Give it a name and save it. <br>It is now stored in the hub and can be loaded with a single click in any future session."
    "</div>"
    "</div>"

    # Save a Group
    "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>{HELP_ICONS['sync_group']} Save a Group</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "A Group is a named collection of multiple pairs - e.g., all your semester courses. Add all the pairs you want to the Sync List, and click <b style='color: #ffffff;'>Save Group</b> next to '+ Add Course'.<br>"
    "<div style='margin-top: 8px; padding: 6px 8px; background: rgba(147, 90, 0, 0.4); border-radius: 4px; color: rgba(255,255,255,0.9); font-size: 0.75rem; line-height: 1.4;'>"
    "<b style='color: #ffffff;'>Notice:</b> Pairs can be saved individually AND in groups. You need at least 2 pairs to save a group, and you cannot save a group that has already been saved."
    "</div>"
    "</div>"
    "</div>"
    "</div>"

    # Load from the Hub
    "<div style='background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px; margin-bottom: 16px;'>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>{HELP_ICONS['sync_hub']} Load from the Hub</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Click <b style='color: #ffffff;'>Saved Groups &amp; Pairs</b> in the top right. Browse your saved groups and individual pairs. Click any entry to load it onto the Sync page instantly. You can load multiple groups one after another to build a combined list.<br><br>"
    "Both Pairs and Groups can be viewed and edited (e.g., change name, update course folder path if it was changed, etc.) - all from the Sync hub. You can even add brand new course pairs to a group from the hub itself! <br>The configuration (Download settings set initially for each course folder downloaded) is viewable in the Saved Groups &amp; Pairs hub for each pair."
    "</div>"
    "</div>"
    "</div>"
    "</details>"
    "<hr>"


    # -- Workflow ------------------------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['refresh']} The Sync process flow</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"

    # Workflow container
    "<div style='background: #0f0f0f; border: 1px solid rgba(255,255,255,0.09); border-radius: 12px; padding: 16px 18px; margin-bottom: 8px;'>"

    # Quick Sync flow
    f"<div style='{_slbl} margin-top: 0;'>{HELP_ICONS['bolt']} Quick Sync</div>"
    "<div style='display: flex; align-items: center; margin-bottom: 14px;'>"
    f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>1</div><div>"
    f"<div style='{_step_title}'>{HELP_ICONS['cursor']} Click Quick Sync</div>"
    f"<div style='{_step_body}'><ul><li>Starts analysis of the courses on your Sync List.</li><li>Analysis scans Canvas and compares every file to your local course folder.</li><li><b style='color: #ffffff;'>Looks for all new or updated files.</b></li></ul></div>"
    f"</div></div></div>{_arr_r}"
    f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>2</div><div>"
    f"<div style='{_step_title}'>{HELP_ICONS['download']} Downloading</div>"
    f"<div style='{_step_body}'><ul><li>New files and clean updates download automatically.</li><li>Files you have edited or deleted are automatically skipped and not downloaded.</li><li>Watch the download progress on the dashboard.</li></ul></div>"
    f"</div></div></div>{_arr_r}"
    f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>3</div><div>"
    f"<div style='{_step_title}'>{HELP_ICONS['check_circle']} Done</div>"
    f"<div style='{_step_body}'><b style='color: #ffffff;'>Sync &amp; Download complete! Your course folders are now fully up to date.</b><br><ul><li>See which files were downloaded for each course, and any errors.</li><li>Use the <b style='color: #ffffff;'>retry button</b> for any failed downloads.</li><li>Use the <b style='color: #ffffff;'>Open Folder</b> button to see the synced course folder directly.</li></ul></div>"
    "</div></div></div>"
    "</div>"
    "<hr>"

    # Analyze, Review & Sync flow
    f"<div style='{_slbl}'>{HELP_ICONS['search']} Analyze, Review &amp; Sync</div>"
    "<div style='display: flex; align-items: center; margin-bottom: 0;'>"
    f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>1</div><div>"
    f"<div style='{_step_title}'>{HELP_ICONS['cursor']} Click Analyze, Review & Sync</div>"
    f"<div style='{_step_body}'><ul><li>Starts analysis of the courses on your Sync List.</li><li>Analysis scans Canvas and compares every file to your local course folder.</li><li><b style='color: #ffffff;'>Looks for all files with changes and sorts them into 7 categories.</b></li></ul></div>"
    f"</div></div></div>{_arr_r}"
    f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>2</div><div>"
    f"<div style='{_step_title}'>{HELP_ICONS['search']} Review changes</div>"
    f"<div style='{_step_body}'><ul><li>All files that have changes are organized here by category.</li><li>Select files you want to download.</li><li>Deselect files you don't want to download.</li><li>Ignore files to skip and hide in future syncs.</li><li>Click <b style='color: #ffffff;'>Sync &amp; Download</b> to continue.</li></ul></div>"
    f"</div></div></div>{_arr_r}"
    f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>3</div><div>"
    f"<div style='{_step_title}'>{HELP_ICONS['eye']} Confirm &amp; Download</div>"
    f"<div style='{_step_body}'><ul><li>A pop-up shows you everything you need to know about the files that will be downloaded.</li><li>Click Confirm to download, or go back to the review page and make changes.</li></ul></div>"
    f"</div></div></div>{_arr_r}"
    f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>4</div><div>"
    f"<div style='{_step_title}'>{HELP_ICONS['download']} Downloading</div>"
    f"<div style='{_step_body}'><ul><li>Files selected for download on the review page will be downloaded.</li><li>Watch the download progress on the dashboard.</li></ul></div>"
    f"</div></div></div>{_arr_r}"
    f"<div style='{_step_card_r}'><div style='{_step_inner}'><div style='{_step_num_r}'>5</div><div>"
    f"<div style='{_step_title}'>{HELP_ICONS['check_circle']} Done!</div>"
    f"<div style='{_step_body}'><b style='color: #ffffff;'>Sync &amp; Download complete! Your course folders are now fully up to date.</b><br><ul><li>See which files were downloaded for each course, and any errors.</li><li>Use the <b style='color: #ffffff;'>retry button</b> for any failed downloads.</li><li>Use the <b style='color: #ffffff;'>Open Folder</b> button to see the synced course folder directly.</li></ul></div>"
    "</div></div></div>"
    "</div>"
    "</div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- File Categories -----------------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['search']} Sync Review: The 7 file categories explained.</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.85); margin-bottom: 10px;'>After sync analysis, every file is placed into one of these 7 categories. Read below to understand how the app sees each file category and what it does with it.</div>"
    f"<div style='display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 4px;'>"
    f"<div style='{_cc_new}'>"
    f"<div style='{_cat_name}'>{HELP_ICONS['cat_new']} New Files</div>"
    f"<div style='{_cat_desc}'>Files on Canvas added by your teacher, that are not in your course folder yet.</div>"
    f"<div style='{_cat_act}'>Downloaded fresh into the correct subfolder.</div>"
    f"<div style='{_sb_checked}'>✔ Checked by default</div>"
    "</div>"
    f"<div style='{_cc_clean}'>"
    f"<div style='{_cat_name}'>{HELP_ICONS['cat_update']} Updates (Clean)</div>"
    f"<div style='{_cat_desc}'>Canvas has a newer version, and you haven't edited your local copy.</div>"
    f"<div style='{_cat_act}'>Replaced in place with the newest version - same name, same location.</div>"
    f"<div style='{_sb_checked}'>✔ Checked by default</div>"
    "</div>"
    f"<div style='{_cc_edited}'>"
    f"<div style='{_cat_name}'>{HELP_ICONS['cat_miss']} Edited locally</div>"
    f"<div style='{_cat_desc}'>Canvas has a newer version, and you've modified your local copy (e.g., added annotations, filled in answers).</div>"
    f"<div style='{_cat_act}'>New version saved as <em>filename_NewVersion</em> alongside your original. Your edits are never touched.</div>"
    f"<div style='{_sb_unchecked}'>☐ Unchecked by default</div>"
    "</div>"
    f"<div style='{_cc_loc_del}'>"
    f"<div style='{_cat_name}'>{HELP_ICONS['cat_locdel']} Deleted Locally</div>"
    f"<div style='{_cat_desc}'>You deleted a file from your folder, but Canvas still has it.</div>"
    f"<div style='{_cat_act}'>Your deletion is respected - the file won't be redownloaded unless you explicitly check the box. Quick Sync always skips these.</div>"
    f"<div style='{_sb_unchecked}'>☐ Unchecked by default</div>"
    "</div>"
    f"<div style='{_cc_can_del}'>"
    f"<div style='{_cat_name}'>{HELP_ICONS['cat_candel']} Deleted on Canvas</div>"
    f"<div style='{_cat_desc}'>The teacher removed a file from Canvas, but it is still in your course folder.</div>"
    f"<div style='{_cat_act}'>Your local copy stays exactly where it is. The app never deletes local files.</div>"
    f"<div style='{_sb_info}'>ℹ Info only - no action</div>"
    "</div>"
    f"<div style='{_cc_ignored}'>"
    f"<div style='{_cat_name}'>{HELP_ICONS['cat_ignore']} Ignored Files</div>"
    f"<div style='{_cat_desc}'>Files you permanently skipped, so they never appear in future syncs.</div>"
    f"<div style='{_cat_act}'>Restore them at any time in the <b style='color: #ffffff;'>Ignored Files</b> section on the Sync Review page or the Sync front page.</div>"
    f"<div style='{_sb_info}'>Permanent skip</div>"
    "</div>"
    f"<div style='{_cc_uptodate}'>"
    f"<div style='{_cat_name}'>Up to Date</div>"
    f"<div style='{_cat_desc}'>File is identical on both sides: Your local file matches Canvas.</div>"
    f"<div style='{_cat_act}'>Hidden from the review screen since no action is needed.</div>"
    f"<div style='{_sb_info}'>Hidden - nothing to do</div>"
    "</div>"
    "</div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- Quick Sync vs Analyze -----------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['compare']} Quick Sync vs Analyze &amp; Review &amp; Sync</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='font-size: 0.85rem; color: #e6e6e6; margin-bottom: 10px;'>Both modes scan Canvas - the difference is the use case, and how much control you have over what gets downloaded.</div>"
    "<div style='display: flex; gap: 16px; margin-bottom: 16px;'>"
    "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>{HELP_ICONS['bolt']} Quick Sync</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.7;'>"
    "✅ Auto-download all new files<br>"
    "✅ Auto-update unedited files that have changes in Canvas<br>"
    "✅ Quick &amp; Easy - press the button and let the app work for you<br>"
    "✅ Skips ignored, locally deleted, and edited files with updates automatically.<br>"
    "❌ Doesn't allow re-downloading of ignored, locally deleted, or edited files with updates.<br>"
    "❌ Doesn't show any Canvas/folder changes, only which files were downloaded (after Quick Sync finishes).<br><br>"
    "<span style='color: rgba(255,255,255,0.9); font-size: 0.82rem;font-weight: 800;'>Best for:</span> "
    "<span style='color: rgba(255,255,255,0.9); font-size: 0.82rem;font-weight: 600;'>Quick everyday use between lectures, morning catch-up - whenever you need the latest files from Canvas as quickly as possible.</span>"
    "</div></div>"
    "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>{HELP_ICONS['search']} Analyze, Review &amp; Sync</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.7;'>"
    "✅ Full overview of all course folder &amp; Canvas changes across 7 different categories.<br>"
    "✅ Select on a per-file basis what you want to download and what you don't - full control.<br>"
    "✅ Ignored files management: Ignore new files, or restore &amp; download previously ignored files.<br>"
    "✅ Filter by file extension for easy selection.<br>"
    "✅ See all files to be downloaded and important metrics before you download.<br>"
    "❌ More time-consuming than Quick Sync.<br><br>"
    "<span style='color: rgba(255,255,255,0.9); font-size: 0.82rem; font-weight: 800;'>Best for:</span> "
    "<span style='color: rgba(255,255,255,0.9); font-size: 0.82rem; font-weight: 600;'>Exam prep, before a study session, or whenever you need to see the full picture &amp; ensure course folders on your PC are 100% up to date with Canvas.</span>"
    "</div></div>"
    "</div>"
    "<div style='background: rgba(0,0,0,0.0); border-radius: 7px; padding: 15px 15px;'>"
    "<span style='font-size: 1rem; font-weight: 700; letter-spacing: 0.07em; margin-top: 0px; margin-bottom: 0px; color: #ffffff;'>When to use which - examples</span>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.75); line-height: 2; margin-top: 5px;'>"
    "<b style='color: #ffffff;'>Checking for new files between classes</b> ➜ Quick Sync<br>"
    "<b style='color: #ffffff;'>Start-of-week catch-up on your courses</b> ➜ Quick Sync<br>"
    "<b style='color: #ffffff;'>Just before an exam, you want to ensure course folders are fully up to date</b> ➜ Analyze, Review &amp; Sync<br>"
    "<b style='color: #ffffff;'>You have been editing files</b> ➜ Analyze, Review &amp; Sync<br>"
    "<b style='color: #ffffff;'>First time setting up a new course folder</b> ➜ Analyze, Review &amp; Sync"
    "</div></div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- Sync History --------------------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['calendar']} Tracking &amp; viewing your Sync History</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65; margin-bottom: 14px;'>"
    "The <b style='color: #ffffff;'>Sync History</b> expander at the bottom of the page keeps a rolling log of your 15 most recent sync runs. "
    "It acts as your sync journal, making it easy to track exactly when and how your Course Folders were modified, or to see which files failed to download."
    "</div>"
    "<div style='display: flex; gap: 16px; margin-bottom: 16px;'>"
    "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>{HELP_ICONS['menu']} Filtering &amp; Controls</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Use the controls at the top of the history list to filter your logs:<br>"
    "<ul style='margin-top: 6px; margin-bottom: 0; padding-left: 18px;'>"
    "<li><b style='color: #ffffff;'>View All:</b> Shows every sync run across all your courses chronologically.</li>"
    "<li><b style='color: #ffffff;'>By Course:</b> Select a course from the dropdown to only see sync logs for that specific course.</li>"
    "<li><b style='color: #ffffff;'>Clear History:</b> Deletes all history entries permanently. Don't worry, it asks for confirmation first to prevent accidental clicks!</li>"
    "</ul>"
    "</div>"
    "</div>"
    "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>{HELP_ICONS['eye']} Reading the Logs</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Each entry shows the date, the courses synced, the total files downloaded, and a color-coded status badge:<br>"
    "<ul style='margin-top: 6px; margin-bottom: 0; padding-left: 18px;'>"
    "<li><span style='color: #34d399; font-weight: 600;'>Success:</span> Synced with no issues.</li>"
    "<li><span style='color: #eba834; font-weight: 600;'>Errors:</span> Some files failed to sync.</li>"
    "<li><span style='color: #8b949e; font-weight: 600;'>No Changes:</span> Everything was already fully up to date!</li>"
    "</ul>"
    "</div>"
    "</div>"
    "</div>"
    "<div style='background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px; margin-bottom: 16px;'>"
    "<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>Inspecting File Details</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Click any sync run in the list to expand it and see exactly what happened to individual files, sorted by category:<br>"
    "<ul style='margin-top: 6px; margin-bottom: 0; padding-left: 18px;'>"
    f"<li><b>{HELP_ICONS['cat_new']} New Files Added:</b> Brand new files downloaded from Canvas.</li>"
    f"<li><b>{HELP_ICONS['cat_update']} Updates Overwritten:</b> Canvas updates that cleanly replaced your unmodified local files.</li>"
    f"<li><b>{HELP_ICONS['cat_locdel']} Locally-Deleted Files Restored:</b> Files you had deleted from your local folder that you chose to re-download, restoring them from Canvas.</li>"
    f"<li><b>{HELP_ICONS['cat_miss']} Modified Files Protected:</b> Updated Canvas files that you had edited locally. The sync engine saved the new version as <em>_NewVersion</em> next to your modified copy to protect your edits!</li>"
    f"<li><b>{HELP_ICONS['error']} Skipped / Failed:</b> A list of any files that failed to sync, grouped by the exact error reason (like network timeouts) so you know exactly what manual action is needed.</li>"
    "</ul>"
    "</div>"
    "</div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- Safety Guarantees ---------------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['shield']} Safety Guarantees</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.8); line-height: 2.0;'>"
    "Syncing is designed to be totally safe. The app <b style='color: #ffffff;'>guarantees</b>:<br>"
    "<b style='color: #ffffff;'>🚫 Never overwrites your edits</b> - updated files you edited get a <em>_NewVersion</em> copy alongside your original.<br>"
    "<b style='color: #ffffff;'>🚫 Never deletes local files</b> - not even when the teacher removes them from Canvas. Your disk is yours.<br>"
    "<b style='color: #ffffff;'>🚫 Never re-downloads files you deleted</b> - unless you explicitly opt in via the review page.<br>"
    "<b style='color: #ffffff;'>🚫 Never creates duplicates</b> - every file is tracked. Re-downloads overwrite cleanly or produce a clearly-named <em>_NewVersion</em>.<br>"
    "<b style='color: #ffffff;'>🚫 Never touches files outside your course folder</b> - only operates inside folders you explicitly link."
    "</div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- FAQ -----------------------------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['question']} Frequently Asked Questions</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is the difference between Sync Mode and Download Mode?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "Download Mode fetches a complete fresh copy of everything - it has no memory of previous downloads. Sync Mode tracks every file in a hidden database, compares your Course Folder against Canvas, and only fetches what's new or changed. Use Download Mode for a first-time backup; use Sync Mode for ongoing maintenance."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>How many courses can I sync at once?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "There is no limit! You can add as many courses to your Sync List as you need. When you start a sync (whether using <b>Quick Sync</b> or <b>Analyze, Review &amp; Sync</b>), the app will process all courses in your Sync List in a single batch. <br>However, for Sync Review, too many courses at once may seem overwhelming - if that is the case for you, stick to a maximum of 3 course pairs at once."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is a Course Pair and do I need one per course?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "Yes - one pair per course. A pair links a course folder on your PC (the one with your course files in it) to a Canvas course. The app tracks everything in a hidden database inside that folder. Multiple courses cannot share the same folder."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What happens if I put my own files in my course folder, and then Sync it?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "Your personal files are completely safe! The sync engine only tracks and manages files that originate from Canvas. It completely ignores any files you add manually (like personal notes, homework drafts, or other custom documents) and will <b>never</b> delete, modify, or overwrite them."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is an ignored file? What is it used for?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "An ignored file is a file in your Canvas course that you can choose to skip and hide. <br>When you mark a file as ignored (which you can do in the <b>Sync Review</b> page), it is permanently hidden from future sync runs and will not be downloaded until you restore it. <br>Ignored files are incredibly useful for skipping large or irrelevant files (like giant video recordings, weird file uploads, or massive zip archives). <br>You can always view, manage, and restore ignored files via the <b>Ignored Files</b> button on each course pair card, or using the restore buttons on the Sync Review page."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Will Sync re-download files I already have?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "No. The app scans your existing folder and automatically recognizes files you already have using a smart algorithm. They are marked as Up to Date - no wasted bandwidth."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>I renamed or moved a file locally - will sync break?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "No. Once a file is tracked, the app follows your renames and moves automatically by matching the file's content (and size), so you can reorganize freely without creating duplicates or breaking tracking. When you first link a folder you built yourself, it also tries to recognize your existing files by content - so it won't re-download copies you already have, even if you named them differently. For the most reliable matching, folders originally downloaded with Canvas Downloader work best."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Where do newly synced files go if I organize my folder my own way?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "Brand-new files from Canvas are placed into subfolders that mirror Canvas's own module/folder structure. If you've arranged your course folder your own way, new files appear in Canvas-named subfolders alongside your existing layout - the app never mixes them into or overwrites your own folders. You're free to move them into your structure afterwards; once tracked, sync follows the move and won't re-download them."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>My professor updated a PDF I annotated. What happens?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "It appears in <b>'Updates - You Edited'</b>, unchecked by default. If you check it, the new version saves as <b>Lecture_3_NewVersion.pdf</b> alongside your annotated original. Your edited files are never touched. Quick Sync skips it entirely."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Will a file show as updated if my professor only changed its description?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "No. The app compares file content fingerprints, not just timestamps. If the actual file hasn't changed, it stays Up to Date - no phantom updates."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is a Saved Group?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "A named collection of course pairs for reuse. Save all your semester courses as one group, then load them all in a single click next session. Managed via the <em>Saved Groups &amp; Pairs</em> hub."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>I moved my course folder to a different drive. Will sync still work?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "Click the edit icon on the pair (if you have it saved, go to the Saved Groups &amp; Pairs hub and click the Edit button for the pair) and re-select the folder at its new location. The hidden database resides in the folder, so all sync history is preserved automatically."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Can Quick Sync run all my courses at once?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "Yes - Both sync modes take ALL course pairs on the Sync List, and run for each individual course in one batch."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is the '☁️ Canvas Updates &amp; Deletions.txt' file?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "The <em>☁️ Canvas Updates &amp; Deletions.txt</em> file inside each course folder is an automatic log that records every update and teacher deletion after each sync. It only appears if your teacher updated or deleted files in the course."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What about AI Optimization? Will the new files also be optimized?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "If your course was originally downloaded with AI Optimization settings (e.g., convert PowerPoints to PDF, extract archives), those same conversions are automatically applied to newly synced files. No extra configuration needed."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Can I run a sync while my course files are open in another application?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "Yes, in most cases! You can read and view your files while the sync is running. However, if a file is actively locked by another application for writing (e.g., a spreadsheet open in Microsoft Excel), the operating system might prevent the sync engine from updating it. <br>If that happens, the app will report it as a failed download, and you can simply close the file and click <b>Retry</b> to update it."
    "</div></details>"
    "<details style='margin-top: 8px; cursor: pointer;'>"
    "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What happens if my sync gets interrupted (e.g., loss of internet or app crash)?</summary>"
    "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
    "The sync engine is built to be extremely resilient. All files and tracking database updates are saved atomically. If the sync is interrupted, you can simply run it again. The app will automatically resume where it left off, skipping already-completed downloads and finishing the remaining ones safely without wasting bandwidth."
    "</div></details>"
    "</div>"
    "</details>"
)

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
    folder_path = native_folder_picker(initial_dir=st.session_state.get('pending_sync_folder') or None)
    if folder_path:
        st.session_state['pending_sync_folder'] = folder_path


# ===================================================================
# ===================================================================
# Save Group / Pair Dialog (Dual-Wrapper Pattern) - delegated to ui/hub_dialog.py
# ===================================================================

def _save_group_or_pair_inner(sync_pairs, is_pair=False, pair_data=None):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import save_group_or_pair_inner
    save_group_or_pair_inner(sync_pairs, is_pair, pair_data)


@st.dialog("\u200b")
def _save_group_dialog(sync_pairs: list[dict]):
    """Delegate to ui.hub_dialog."""
    _save_group_or_pair_inner(sync_pairs, is_pair=False)


@st.dialog("\u200b")
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


def _delete_group_callback(mgr, group_id, group_name, is_single_pair=False):
    """Delegate to ui.hub_dialog."""
    from ui.hub_dialog import delete_group_callback
    delete_group_callback(mgr, group_id, group_name, is_single_pair)


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


# on_dismiss="rerun": a dialog reruns like a fragment, so deleting/renaming
# saved groups inside the hub only reruns the dialog - the main page's floppy
# "Save as Pair" / "Save as Group" disabled states (computed from load_groups()
# when the hub opened) go stale. Dismissing via backdrop/ESC would otherwise
# reveal that stale render until the next click. "rerun" forces a full app rerun
# on dismissal so _sync_pairs_section recomputes those states from fresh data.
@st.dialog("\u200b", width="large", on_dismiss="rerun")
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




def _sync_pairs_section(courses, course_names, course_options):
    sync_pairs = st.session_state.get('sync_pairs', [])
    pairs_to_remove = []
    _deferred_save_pair = None   # Will hold pair data if inline Save is clicked
    _deferred_save_group = False # Will be True if "Save as Group" is clicked
    _deferred_ignored = None     # Will hold (course_name, course_id, course_data) if "Ignored Files" is clicked

    # Pre-compute set of already-saved (course_id, local_folder) tuples for inline Save button
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

    # Pre-compute missing-folder state once; used by both per-pair save buttons and "Save as Group"
    _any_missing_folder = any(
        not Path(p.get('local_folder', '')).exists()
        for p in sync_pairs
        if p.get('local_folder')
    )

    # Load SVG icons for CSS injection
    _b64_icon_ignore = get_base64_image("assets/Icon_Ignore.svg")
    _b64_icon_folder = get_base64_image("assets/Icon_Folder.svg")
    _b64_icon_edit   = get_base64_image("assets/Icon_Edit.svg")
    _b64_icon_trash  = get_base64_image("assets/Icon_Trash.svg")

    # Inject SVG icons, layout, hover animations, and boxes for the 4 action buttons.
    # Uses st.markdown (NOT st.html): st.html()'s shadow-root <style> block is silently
    # unmounted by Streamlit's React reconciliation during a partial rerun (e.g. opening
    # the Saved Groups @st.dialog), causing a one-frame "flash" where these buttons lose
    # their styling. st.markdown injects into the main DOM and survives the dialog rerun.
    # (CLAUDE.md "Headless Injection Rule" - ghost-box margin is killed by global.css.)
    st.markdown(f"""<style>
    /* General styling for the 4 action buttons - shared light-grey resting state */
    div[class*="st-key-open_folder_"] button,
    div[class*="st-key-edit_pair_"] button,
    div[class*="st-key-ignored_btn_"] button,
    div[class*="st-key-remove_pair_"] button {{
        border-radius: 10px !important;
        background-color: rgba(255, 255, 255, 0.07) !important;
        border: 1.5px solid rgba(255, 255, 255, 0.12) !important;
        color: rgba(255, 255, 255, 0.88) !important;
        transition: all 0.2s ease !important;
        padding: 0 12px !important;
        height: 38px !important;
        min-height: 38px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}

    /* Inner wrapper: force vertical centering via align-self (immune to Streamlit overriding button align-items) */
    div[class*="st-key-open_folder_"] button > div,
    div[class*="st-key-edit_pair_"] button > div,
    div[class*="st-key-ignored_btn_"] button > div,
    div[class*="st-key-remove_pair_"] button > div,
    div[class*="st-key-open_folder_"] button > div > span,
    div[class*="st-key-edit_pair_"] button > div > span,
    div[class*="st-key-ignored_btn_"] button > div > span,
    div[class*="st-key-remove_pair_"] button > div > span,
    div[class*="st-key-open_folder_"] button div[data-testid="stMarkdownContainer"],
    div[class*="st-key-edit_pair_"] button div[data-testid="stMarkdownContainer"],
    div[class*="st-key-ignored_btn_"] button div[data-testid="stMarkdownContainer"],
    div[class*="st-key-remove_pair_"] button div[data-testid="stMarkdownContainer"] {{
        display: flex !important;
        align-items: center !important;
        align-self: center !important;
        width: 100% !important;
    }}

    /* p is the icon+text row - inline-flex so ::before sits beside text in flow */
    div[class*="st-key-open_folder_"] button p,
    div[class*="st-key-edit_pair_"] button p,
    div[class*="st-key-ignored_btn_"] button p,
    div[class*="st-key-remove_pair_"] button p {{
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 9px !important;
        margin: 0 !important;
        line-height: 1 !important;
        width: 100% !important;
    }}

    /* Base icon: inline-block ::before (CLAUDE.md pattern for icon-beside-text buttons) */
    div[class*="st-key-open_folder_"] button p::before,
    div[class*="st-key-edit_pair_"] button p::before,
    div[class*="st-key-ignored_btn_"] button p::before,
    div[class*="st-key-remove_pair_"] button p::before {{
        content: '';
        display: inline-block;
        width: 20px;
        height: 20px;
        flex-shrink: 0;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        transition: background-color 0.2s ease;
    }}

    /* SVG Assignments - neutral white icon at rest */
    div[class*="st-key-open_folder_"] button p::before {{
        -webkit-mask-image: url('data:image/svg+xml;base64,{_b64_icon_folder}');
        -webkit-mask-size: 18px;
        background-color: rgba(255, 255, 255, 0.88);
    }}
    div[class*="st-key-edit_pair_"] button p::before {{
        -webkit-mask-image: url('data:image/svg+xml;base64,{_b64_icon_edit}');
        -webkit-mask-size: 18px;
        background-color: rgba(255, 255, 255, 0.88);
    }}
    div[class*="st-key-ignored_btn_"] button p::before {{
        -webkit-mask-image: url('data:image/svg+xml;base64,{_b64_icon_ignore}');
        -webkit-mask-size: 18px;
        background-color: rgba(255, 255, 255, 0.88);
    }}
    div[class*="st-key-remove_pair_"] button p::before {{
        -webkit-mask-image: url('data:image/svg+xml;base64,{_b64_icon_trash}');
        -webkit-mask-size: 17px;
        background-color: rgba(255, 255, 255, 0.88);
    }}

    /* ===== HOVER STATES - coloured border + icon only ===== */

    /* Open Folder -> Yellow (#facc15) */
    div[class*="st-key-open_folder_"] button:hover {{
        border-color: rgba(250, 204, 21, 0.7) !important;
        background-color: rgba(250, 204, 21, 0.08) !important;
    }}
    div[class*="st-key-open_folder_"] button:hover p::before {{
        background-color: #facc15;
    }}

    /* Edit -> Blue */
    div[class*="st-key-edit_pair_"] button:hover {{
        border-color: rgba(59, 130, 246, 0.7) !important;
        background-color: rgba(59, 130, 246, 0.08) !important;
    }}
    div[class*="st-key-edit_pair_"] button:hover p::before {{
        background-color: #93c5fd;
    }}

    /* Ignored Files -> White */
    div[class*="st-key-ignored_btn_"] button:hover {{
        border-color: rgba(255, 255, 255, 0.5) !important;
        background-color: rgba(255, 255, 255, 0.08) !important;
    }}
    div[class*="st-key-ignored_btn_"] button:hover p::before {{
        background-color: #ffffff;
    }}

    /* Remove -> Red */
    div[class*="st-key-remove_pair_"] button:hover {{
        border-color: rgba(255, 75, 75, 0.7) !important;
        background-color: rgba(255, 75, 75, 0.08) !important;
    }}
    div[class*="st-key-remove_pair_"] button:hover p::before {{
        background-color: #ff4b4b;
    }}

    /* Folder icon inside pair cards: 4px smaller than the global SVG_FOLDER_YELLOW (1.4em ≈ 19px → 15px) */
    div[class*="st-key-sync_pair_card_"] svg {{
        width: 15px !important;
        height: 15px !important;
    }}
    </style>""", unsafe_allow_html=True)

    # --- Pre-compute ignored files per course (cached to avoid N SQLite reads per rerun) ---
    # L-8: Acknowledged race: cleanup_sync_state() pops this cache while a
    # bulk_ignore_files write could be mid-flight on the sync background thread.
    # Worst case: cache rebuilds on the next rerun with stale data for one frame.
    # Acceptable - bulk_ignore writes are fast and idempotent.
    _cache_key = '_ignored_files_cache'
    ignored_by_course = st.session_state.get(_cache_key)

    if ignored_by_course is None:
        # Cache miss - query SQLite once, store result for subsequent fragment reruns
        ignored_by_course = {}
        if sync_pairs:
            for pair in sync_pairs:
                local_folder = pair.get('local_folder')
                course_id = pair.get('course_id')
                if local_folder and Path(local_folder).exists():
                    sm = SyncManager(local_folder, course_id, pair.get('course_name', ''))
                    ignored = sm.get_ignored_files()
                    if ignored:
                        ignored_by_course[course_id] = {
                            'pair': pair,
                            'files': ignored,
                            'sync_manager': sm,
                        }
        st.session_state[_cache_key] = ignored_by_course

    with st.container(border=True, key="sync_list_outline"):
        if sync_pairs:
            editing_idx = st.session_state.get('editing_pair_idx')

            for idx, pair in enumerate(sync_pairs):
                # --- If this pair is being edited, render the edit form inline ---
                if editing_idx is not None and editing_idx == idx and st.session_state.get('pending_sync_folder') is not None:
                    _render_pending_folder_ui(courses, course_names, course_options)
                    # Removed explicit spacer to match list gap via CSS margin-bottom on container
                    continue

                # Use vertical_alignment="center" (Streamlit 1.32+) or rely on CSS above
                # Adjusted ratios: Card takes space, but buttons need room for text now
                col_card, col_open, col_edit, col_ignored, col_remove = st.columns([5, 1.5, 1.1, 1.5, 1.2], gap="small", vertical_alignment="center")

                with col_card:
                    folder_exists = Path(pair['local_folder']).exists()
                    last_synced = pair.get('last_synced')
                    if not last_synced and folder_exists:
                        # Try to recover it from the folder database
                        try:
                            recovered = SyncManager.peek_last_synced(pair['local_folder'])
                            if recovered:
                                last_synced = recovered
                                # Heal the session state pair to avoid querying sqlite every frame
                                pair['last_synced'] = recovered
                        except Exception as e:
                            logger.warning(f"Could not recover last_synced from folder: {e}")

                    if last_synced:
                        friendly_ts = format_relative_date(last_synced, include_time=True, include_emoji=False)
                        ts_str = f'Last synced: {friendly_ts}'
                    else:
                        ts_str = 'Never synced'
                    
                    # Simplified card content
                    display_name = friendly_course_name(pair['course_name'])
                    folder_display = short_path(pair['local_folder'])

                    # Pre-compute save state for inline button
                    _pair_sig = (pair.get('course_id'), pair.get('local_folder', ''))
                    _pair_already_saved = _pair_sig in _saved_pair_sigs
                    
                    if not folder_exists:
                        _is_save_disabled = True
                        _save_help = "Cannot save pair: folder could not be located."
                    else:
                        _is_save_disabled = _pair_already_saved
                        _save_help = (
                            "This pair is saved - go to Saved Groups & Pairs to see, rename, or edit."
                            if _pair_already_saved
                            else "Save as Pair"
                        )

                    # Card container with Save button INSIDE
                    # Use a different key suffix for missing-folder cards so CSS can apply red border
                    _card_key = f"sync_pair_card_missing_{idx}" if not folder_exists else f"sync_pair_card_{idx}"
                    with st.container(border=True, key=_card_key):
                        # Title rendered first, naturally
                        st.markdown(f"**{'Course: '} {display_name}**")
                        # Save button rendered after - CSS absolute-positions it to top-right
                        if st.button("\u200b", key=f"save_pair_{idx}", disabled=_is_save_disabled,
                                     help=_save_help):
                            _deferred_save_pair = pair
                        st.markdown(f"""<div style="font-size:0.85em;color:rgba(255, 255, 255, 0.9);margin-top:-10px;display:flex;align-items:center;">{SVG_FOLDER_YELLOW}{folder_display}</div>  <!-- # audit-ignore: folder_display is a local path -->
                            <div style="font-size:0.75em;color:rgba(255, 255, 255, 0.8);margin-top:2px;">{SVG_CLOCK}{ts_str}</div>""", unsafe_allow_html=True)

                # (4) Action buttons with text labels restored
                with col_open:
                    if folder_exists:
                        if st.button('Open Folder',
                                     key=f"open_folder_{idx}", use_container_width=True):
                            open_folder(pair['local_folder'])
                    else:
                        st.button('Open Folder',
                                     key=f"open_folder_{idx}", use_container_width=True, disabled=True,
                                     help="This folder could not be found (it may have been deleted or moved).")

                with col_edit:
                    if st.button('Edit', 
                                 key=f"edit_pair_{idx}", use_container_width=True):
                        st.session_state['pending_sync_folder'] = pair['local_folder']
                        st.session_state['editing_pair_idx'] = idx
                        # Pre-populate selected course for editing
                        st.session_state['sync_selected_course_id'] = pair['course_id']
                        st.rerun(scope="app")

                with col_ignored:
                    ignored_count = len(ignored_by_course.get(pair['course_id'], {}).get('files', []))
                    ignored_help = "No files have been ignored for this course." if ignored_count == 0 else None
                    btn_text = f"Ignored Files\u2009:gray[({ignored_count})]" if ignored_count > 0 else "Ignored Files"
                    if st.button(btn_text, key=f"ignored_btn_{idx}",
                                 disabled=(ignored_count == 0), use_container_width=True, help=ignored_help):
                        course_data = ignored_by_course.get(pair['course_id'])
                        if course_data:
                            _deferred_ignored = (
                                friendly_course_name(pair['course_name']),
                                pair['course_id'], course_data)

                with col_remove:
                    if st.button('Remove', 
                                 key=f"remove_pair_{idx}", use_container_width=True):
                        pairs_to_remove.append(idx)
                
            if pairs_to_remove:
                signatures = [{'course_id': sync_pairs[i].get('course_id'), 'local_folder': sync_pairs[i].get('local_folder')} for i in pairs_to_remove]
                
                # Build toast message before modifying the sync_pairs array
                if len(pairs_to_remove) == 1:
                    display_name = friendly_course_name(sync_pairs[pairs_to_remove[0]].get('course_name', 'Course'))
                    st.session_state['pending_toast'] = f"Removed '{display_name}' from Sync List"
                else:
                    st.session_state['pending_toast'] = f"Removed {len(pairs_to_remove)} courses from Sync List"
                    
                _remove_pairs_by_signature(signatures)
                st.session_state.pop("_ignored_files_cache", None)
                st.rerun(scope="app")
            if st.session_state.get('pending_sync_folder') is not None and st.session_state.get('editing_pair_idx') is None:
                _render_pending_folder_ui(courses, course_names, course_options)
            else:
                # (9) "Add Course folder" + "Save List as Group" - full width.
                # Button styling lives entirely in styles/sync_hub.css (static) - NO inline
                # st.markdown(<style>) here: a <style> injection inside this container adds a
                # ghost box that inflates the gap above this row above the inter-card gap.
                _save_disabled = len(sync_pairs) < 2 or _any_missing_folder or _saved_mgr.matches_existing_group(sync_pairs)
                _save_group_help = "Save this exact list of courses as a group."
                if _save_disabled:
                    if len(sync_pairs) < 2:
                        _save_group_help = "You need at least 2 courses to save a group."
                    elif _any_missing_folder:
                        _save_group_help = "Cannot save group: one or more folders could not be located."
                    else:
                        _save_group_help = "This exact group of courses is already saved."

                col_add, col_save, _ = st.columns([2.25, 1.5, 6.25], gap="small", vertical_alignment="bottom")
                with col_add:
                    if st.button('Add Course', key="btn_add_folder", use_container_width=True):
                        st.session_state['pending_sync_folder'] = ""
                        st.session_state['sync_selected_course_id'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.rerun(scope="app")

                with col_save:
                    if st.button("Save as Group", key="btn_save_group_main", disabled=_save_disabled, use_container_width=True, help=_save_group_help):
                        _deferred_save_group = True

        else:
            # EMPTY STATE Logic (if not sync_pairs)
            if st.session_state.get('pending_sync_folder') is not None and st.session_state.get('editing_pair_idx') is None:
                _render_pending_folder_ui(courses, course_names, course_options)
            else:
                # Button styling lives in styles/sync_hub.css (static). An inline
                # <style> injection inside col_add adds a ghost box above the button,
                # pushing it down out of alignment with the container's left padding.
                col_add, _ = st.columns([2.25, 7.75])
                with col_add:
                    if st.button('Add Course', key="btn_add_folder_empty", use_container_width=True):
                        st.session_state['pending_sync_folder'] = ""
                        st.session_state['sync_selected_course_id'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.rerun(scope="app")
    
            
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
                f'Ready to sync? Add a Course Folder and map it to a Canvas course to get started!'
                f'</div></div>', 
                unsafe_allow_html=True
            )

    # --- Deferred dialog invocations (MUST be outside all column/container contexts) ---
    if _deferred_save_pair is not None:
        _save_pair_dialog(_deferred_save_pair)
    if _deferred_save_group:
        _save_group_dialog(sync_pairs)
    if _deferred_ignored is not None:
        _show_course_ignored_files(*_deferred_ignored)



def render_sync_step1(fetch_courses_fn, main_placeholder=None):
    """Render Sync Step 1: folder pairing UI."""

    # Guard clause: double check that we are in step 1.
    # This prevents ghost UI elements if app.py logic somehow leaks.
    if st.session_state.get('step') != 1:
        return

    _init_sync_session_state()
    _load_persistent_pairs()

    # Inject Google Material Symbols font once per render (M-24).
    from ui_shared import inject_material_icons_font
    inject_material_icons_font()

    # Step wizard - must be rendered BEFORE any inject_css() calls.
    # inject_hub_global_css() calls inject_css() via st.markdown which creates a
    # 1rem ghost-box margin; rendering the wizard first pins it flush to the top.
    render_sync_wizard(st, 1)

    # Inject all Hub Dialog + Main Button CSS unconditionally
    _inject_hub_global_css()

    # --- Load Premium Assets & Hoist Sync Button CSS ---
    b64_analyze = get_base64_image("assets/icon_sync_review.png")
    b64_quick = get_base64_image("assets/icon_sync_quick.png")
    b64_add = get_base64_image("assets/icon_add.png")

    st.markdown(f"""<style>
    div.st-key-btn_analyze_sync button p::before {{
        content: "" !important;
        display: inline-block !important;
        position: relative !important;
        /* rely on flex centering */
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
        /* rely on flex centering */
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

    /* Analyze Sync Disabled - clean muted grey, no washed-out color */
    div.st-key-btn_analyze_sync button:disabled {{
        background-color: #3a3a3a !important;
        color: #6b6b6b !important;
        box-shadow: none !important;
        border: 1px solid #4a4a4a !important;
    }}
    div.st-key-btn_analyze_sync button:disabled p::before {{
        filter: grayscale(100%) opacity(0.4) !important;
    }}

    /* Quick Sync Disabled - override gradient with flat grey */
    div.st-key-btn_quick_sync button:disabled {{
        background: #3a3a3a !important;
        color: #6b6b6b !important;
        box-shadow: none !important;
        border: 1px solid #4a4a4a !important;
        filter: none !important;
    }}
    div.st-key-btn_quick_sync button:disabled p::before {{
        filter: grayscale(100%) opacity(0.4) !important;
    }}

    /* ===== ADD COURSE BUTTON - Base64 Icon via ::before ===== */
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
    </style>""", unsafe_allow_html=True)

    # --- Pending toast consumer (fires after dialog rerun) ---
    if 'pending_toast' in st.session_state:
        st.toast(st.session_state.pop('pending_toast'))

    # (7) Removed "Select Folders to Sync" header - wizard is enough context.

    # Fetch courses - already edited with .is_favorite by fetch_courses()
    courses = fetch_courses_fn(
        st.session_state['api_token'],
        st.session_state['api_url'],
    )
    
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


    # --- (8) Bigger subheading + Help + Hub button ---
    # Snug Header Hack - H2 + Help button on one flex row
    st.html("""
        <style>
        div.st-key-btn_hub_main button {
            margin-top: -20px !important;
        }
        div[class*="st-key-sync_title_help_row"] {
            margin-top: -15px !important;
            margin-bottom: 15px !important;
        }
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
                    title=_SYNC_HELP_TITLE,
                    text_html=_SYNC_HELP_TEXT,
                    mode="button"
                )
    open_hub = False
    with col_hub:
        if st.button("Saved Groups & Pairs", key="btn_hub_main",
                     use_container_width=True):
            _reset_hub_state()
            open_hub = True

    if open_hub:
        _saved_groups_hub_dialog(courses, course_names)

    # Help Card Expansion (renders below the header + hub button row if open)
    render_help_card(
        key_prefix="sync_setup",
        title=_SYNC_HELP_TITLE,
        text_html=_SYNC_HELP_TEXT,
        mode="card"
    )

    # --- (4) Pair action-button CSS: Remove fixed height, let flex align handle it ---


    _sync_pairs_section(courses, course_names, course_options)

    # Read sync_pairs here so the Analyze/Quick Sync buttons below can check it.
    # The fragment may have mutated session state (add/remove via scope="app" reruns).
    sync_pairs = st.session_state.get('sync_pairs', [])

    # --- (5) Analyze + Quick Sync action buttons ---

    # ----- State-aware guardrails for Analyze / Quick Sync buttons -----
    _has_missing_folders = False
    _missing_folder_names = []
    if sync_pairs:
        for p in sync_pairs:
            if not Path(p['local_folder']).exists():
                _has_missing_folders = True
                _missing_folder_names.append(short_path(p['local_folder']))

    _can_sync = bool(sync_pairs) and not _has_missing_folders

    # Compute student-friendly help tooltips for disabled buttons
    if not sync_pairs:
        _sync_help = "Add at least one course folder to start syncing."
    elif _has_missing_folders:
        _sync_help = f"Can't sync - a folder is missing or disconnected. Fix or remove it first."
    else:
        _sync_help = None

    # --- Amber notice cards (rendered ABOVE the buttons) ---
    if sync_pairs and _has_missing_folders:
        from ui.amber_notice import render_amber_notice
        _folder_list = ", ".join(_missing_folder_names[:3])
        _extra = f" (+{len(_missing_folder_names) - 3} more)" if len(_missing_folder_names) > 3 else ""
        render_amber_notice(
            f"Folder not found: {_folder_list}{_extra}",
            detail="The folder may have been moved, renamed, or the drive is disconnected. Edit or remove the pair to continue.",
        )

    # H-3: Aggregate mismatch notice - show ALL binding mismatches at once.
    _mismatches = st.session_state.pop('sync_mismatched_pairs', [])
    if _mismatches:
        from ui.amber_notice import render_amber_notice
        _mismatch_lines = "\n".join(
            f"  • '{short_path(m['pair']['local_folder'])}' is bound to "
            f"\"{esc(m['bound_course_name'])}\" but you selected "
            f"\"{esc(m['requested_course_name'])}\""
            for m in _mismatches
        )
        render_amber_notice(
            f"{len(_mismatches)} folder{'s' if len(_mismatches) != 1 else ''} "
            f"{'are' if len(_mismatches) != 1 else 'is'} bound to a different Canvas course.",
            detail=(
                f"{_mismatch_lines}\n\n"
                "Edit each pair to point at the correct course, or remove and re-add it."
            ),
        )

    # Ratios: 0.75 is ~75% of the previous 1.0 width (relative to page)
    # gap="small" brings the OR closer
    col_analyze, col_or, col_quick, _ = st.columns([0.75, 0.16, 0.75, 2.34], gap="small", vertical_alignment="center")

    # Force identical styling for the two primary buttons in this section
    # We target specific children of these columns to ensure parity.
    st.html("""
    <style>
    /* Target buttons inside the main column containers - scoped to Analyze/Quick Sync */
    div.st-key-btn_analyze_sync button[kind="primary"],
    div.st-key-btn_quick_sync button[kind="primary"] {
        height: 3.2em !important;
        min-height: 3.2em !important;
        border-radius: 6px !important;
        width: 100% !important;
        padding: 0px 10px !important; /* Balanced vertical padding */
        float: none !important;
        margin: 0 auto !important;
    }
    /* RECURSIVE CENTERING: START - Universal child selector */
    /* This forces EVERY element inside the button to be flex-centered */
    div.st-key-btn_analyze_sync button[kind="primary"] > div,
    div.st-key-btn_analyze_sync button[kind="primary"] > div > p,
    div.st-key-btn_quick_sync button[kind="primary"] > div,
    div.st-key-btn_quick_sync button[kind="primary"] > div > p {
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
    div.st-key-btn_analyze_sync button[kind="primary"] *,
    div.st-key-btn_quick_sync button[kind="primary"] * {
        text-align: center !important;
        align-items: center !important;
        justify-content: center !important;
    }
    div.st-key-btn_analyze_sync button[kind="primary"] p,
    div.st-key-btn_quick_sync button[kind="primary"] p {
        font-size: 1rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
    }
    </style>
    """)
    
    with col_analyze:
        if st.button('Analyze, Review & Sync', type="primary",
                     key="btn_analyze_sync",
                     use_container_width=True,
                     disabled=not _can_sync,
                     help=_sync_help):
            # Nuclear reset of all cancel flags - stale flags from a previous download/sync
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
        st.markdown(f"<div style='text-align:center; font-weight:bold; color:{theme.TEXT_DIM}; font-size:0.9em; white-space:nowrap; word-break:keep-all;'>OR</div>", unsafe_allow_html=True)

    with col_quick:
        if st.button('Quick Sync',
                     key="btn_quick_sync",
                     type="primary",
                     use_container_width=True,
                     disabled=not _can_sync,
                     help=_sync_help):
            # Nuclear reset of all cancel flags - stale flags from a previous download/sync
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

    # --- (6) Sync History (bottom of page) - the single collection point;
    # every resolvable file carries inline Open / Reveal actions + its path. ---
    _render_sync_history()

    # Breathing room so the final expander/accordion is never flush against the
    # viewport bottom - this is what made history rows feel "jumpy" on expand.
    st.markdown("<div style='height: 64px;'></div>", unsafe_allow_html=True)


# Order + labels + icons for the per-run file-category sections in Sync History.
_SYNC_HISTORY_CATEGORIES = [
    ('new',       'New Files Added',                'cat_new'),
    ('updated',   'Updates Overwritten',           'cat_update'),
    ('restored',  'Locally-Deleted Files Restored', 'cat_locdel'),
    ('protected', 'Modified Files Protected',       'cat_miss'),
]


def _render_sync_history():
    """Render sync history in an expander at the bottom of step 1."""
    history_mgr = None
    try:
        from ui_helpers import get_config_dir
        from sync_manager import SyncHistoryManager
        # Always construct the manager (cheap) so it's available to the
        # "Clear History" handler below. Binding it only inside the cache-miss
        # branch caused an UnboundLocalError on the clear-history rerun, because
        # by then the cache already exists and the branch is skipped.
        history_mgr = SyncHistoryManager(get_config_dir())
        # M-1: Cache history in session state - avoids a disk read on every
        # Streamlit rerun (checkbox clicks, etc.). Invalidated by execution.py
        # after a new entry is written via st.session_state.pop('_sync_history_cache').
        if '_sync_history_cache' not in st.session_state:
            st.session_state['_sync_history_cache'] = history_mgr.load_history()
        history = st.session_state['_sync_history_cache']
    except Exception:
        history = []

    if history:
        # Key-scoped CSS is injected via st.markdown (stable across reruns).
        # st.html() <style> blocks get silently unmounted by Streamlit's React
        # reconciliation on a rerun (see CLAUDE.md) - that is what made the tab
        # buttons "lose" their styling after clicking a tab. The st.html() block
        # further down is reserved ONLY for the #sync-history-marker div, whose
        # sibling selectors need the un-wrapped DOM that st.html() provides.
        st.markdown("""
        <style>
        div[class*="st-key-sync_hist_tab_"] button {
            border-radius: 6px !important;
            /* No visible outline by default - it appears only on hover. The
               1px transparent border reserves the space so nothing shifts. */
            border: 1px solid transparent !important;
            background-color: #21262d !important;
            color: #e6edf3 !important;
            box-shadow: none !important;
            transition: all 0.2s ease !important;
            min-height: 0 !important;
            height: 38px !important;
            padding: 4px 12px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        /* Hover (either state): reveal the full outside border. */
        div[class*="st-key-sync_hist_tab_"] button:hover {
            background-color: rgba(88, 166, 255, 0.1) !important;
            color: #58a6ff !important;
            border-color: rgba(88, 166, 255, 0.4) !important;
        }
        /* Active (primary): ONLY a bottom accent border, no full outline. */
        div[class*="st-key-sync_hist_tab_"] button[kind="primary"] {
            background-color: rgba(88, 166, 255, 0.15) !important;
            border: 1px solid transparent !important;
            border-bottom: 2px solid #58a6ff !important;
            color: #ffffff !important;
        }
        /* The active tab is NOT interactive (you're already on it) - it must
           NOT react to hover/focus/click at all. Restate its resting look
           verbatim across EVERY interactive state and kill Streamlit's default
           focus/hover box-shadow + outline (that stray shadow was the "top glow"
           - my :hover rule reset the border but not the shadow). */
        div[class*="st-key-sync_hist_tab_"] button[kind="primary"]:hover,
        div[class*="st-key-sync_hist_tab_"] button[kind="primary"]:focus,
        div[class*="st-key-sync_hist_tab_"] button[kind="primary"]:focus-visible,
        div[class*="st-key-sync_hist_tab_"] button[kind="primary"]:active {
            background-color: rgba(88, 166, 255, 0.15) !important;
            border: 1px solid transparent !important;
            border-bottom: 2px solid #58a6ff !important;
            color: #ffffff !important;
            box-shadow: none !important;
            outline: none !important;
            cursor: default !important;
        }
        /* Grid SVG icon before each tab label (drawn as a ::before so the
           button-hover restyle never wipes it; inherits no colour - the icon
           colour is baked into the data-URI fill). */
        /* Centre the label box itself, then centre icon+text inside it. The
           default <p> line-height + margins were leaving the content sitting
           slightly high in the 38px button - reset them so it sits dead-centre. */
        div[class*="st-key-sync_hist_tab_"] button > div {
            display: flex !important; align-items: center !important; justify-content: center !important;
            height: 100% !important;
        }
        div[class*="st-key-sync_hist_tab_"] button p {
            display: inline-flex !important; align-items: center !important; gap: 8px !important;
            margin: 0 !important; line-height: 1 !important;
        }
        div[class*="st-key-sync_hist_tab_"] button p::before {
            content: ""; display: inline-block; width: 17px; height: 17px;
            background-repeat: no-repeat; background-position: center; background-size: contain;
        }
        /* View All = a list icon: 3 rows, each a bullet + a dash. */
        div.st-key-sync_hist_tab_all button p::before {
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23c9d1d9'%3E%3Ccircle cx='4' cy='6' r='1.7'/%3E%3Crect x='8' y='4.8' width='13' height='2.4' rx='1.2'/%3E%3Ccircle cx='4' cy='12' r='1.7'/%3E%3Crect x='8' y='10.8' width='13' height='2.4' rx='1.2'/%3E%3Ccircle cx='4' cy='18' r='1.7'/%3E%3Crect x='8' y='16.8' width='13' height='2.4' rx='1.2'/%3E%3C/svg%3E");
        }
        /* By Course = a filled folder. */
        div.st-key-sync_hist_tab_course button p::before {
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23c9d1d9'%3E%3Cpath d='M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z'/%3E%3C/svg%3E");
        }
        /* Brighten the icon on the active (primary) tab to match its white text. */
        div.st-key-sync_hist_tab_all button[kind="primary"] p::before {
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23ffffff'%3E%3Ccircle cx='4' cy='6' r='1.7'/%3E%3Crect x='8' y='4.8' width='13' height='2.4' rx='1.2'/%3E%3Ccircle cx='4' cy='12' r='1.7'/%3E%3Crect x='8' y='10.8' width='13' height='2.4' rx='1.2'/%3E%3Ccircle cx='4' cy='18' r='1.7'/%3E%3Crect x='8' y='16.8' width='13' height='2.4' rx='1.2'/%3E%3C/svg%3E");
        }
        div.st-key-sync_hist_tab_course button[kind="primary"] p::before {
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23ffffff'%3E%3Cpath d='M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z'/%3E%3C/svg%3E");
        }
        /* Clean up the selectbox input */
        div.st-key-sync_hist_course_select div[data-baseweb="select"],
        div.st-key-sync_hist_course_select div[role="combobox"],
        div.st-key-sync_hist_course_select [data-testid="stSelectbox"] > div > div:nth-child(2),
        div.st-key-sync_hist_course_select [data-testid="stSelectbox"] > div:first-of-type > div:first-of-type {
            background-color: #21262d !important;
            border: 1px solid rgba(255,255,255,0.05) !important;
            border-radius: 6px !important;
            min-height: 0 !important;
            height: 38px !important;
        }
        div.st-key-sync_hist_course_select div[data-baseweb="select"]:hover,
        div.st-key-sync_hist_course_select div[role="combobox"]:hover,
        div.st-key-sync_hist_course_select [data-testid="stSelectbox"] > div > div:nth-child(2):hover {
            border-color: rgba(255,255,255,0.2) !important;
        }
        /* Universal detached dropdown wrapper styling */
        div[data-baseweb="popover"] {
            background-color: transparent !important;
        }
        div[data-baseweb="popover"] > div,
        div[data-testid="stSelectboxVirtualDropdown"] {
            background-color: #21262d !important;
            border: 1px solid rgba(255,255,255,0.2) !important;
            border-radius: 6px !important;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5) !important;
            overflow: hidden !important;
        }
        ul[data-baseweb="menu"], ul[role="listbox"] {
            background-color: transparent !important;
            border: none !important;
            box-shadow: none !important;
            padding: 4px 0 !important;
        }
        li[role="option"] {
            color: #e6edf3 !important;
        }
        li[role="option"]:hover, li[role="option"][aria-selected="true"] {
            background-color: rgba(255,255,255,0.1) !important;
        }
        /* Ghost Danger style for clear history button */
        div.st-key-btn_sync_hist_clear button {
            min-height: 0 !important;
            height: 38px !important;
            padding: 4px 12px !important;
            transition: all 0.2s ease !important;
        }
        div.st-key-btn_sync_hist_clear button:hover {
            border-color: #ff4b4b !important;
            color: #ff4b4b !important;
            background-color: rgba(255, 75, 75, 0.1) !important;
        }
        div.st-key-btn_sync_hist_clear button p {
            padding-left: 24px !important;
            position: relative !important;
            display: inline-flex !important;
            align-items: center !important;
            margin: 0 !important;
        }
        div.st-key-btn_sync_hist_clear button p::after {
            content: '';
            position: absolute;
            left: 0;
            top: 50%;
            transform: translateY(-50%);
            width: 18px;
            height: 18px;
            background-color: currentColor !important;
            -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='currentColor'%3E%3Cpath d='M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z'/%3E%3C/svg%3E");
            -webkit-mask-repeat: no-repeat;
            -webkit-mask-position: center;
            -webkit-mask-size: contain;
            transition: background-color 0.2s ease !important;
        }
        /* Rotate chevron strictly from center */
        .sync-history-details[open] .sync-history-chevron {
            transform: rotate(90deg) !important;
        }
        </style>
        """, unsafe_allow_html=True)

        # st.html() ONLY for the marker div + its sibling selectors (these need
        # the real, un-wrapped DOM that st.markdown's <p> wrapping would break).
        st.html("""
        <style>
        /* --- SEXY SYNC HISTORY EXPANDER STYLING --- */
        /* Target the expander immediately following our hidden marker */
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] [data-testid="stExpander"] {
            margin-top: 32px !important;
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        /* Kill Streamlit's native glowing border on the details element */
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details) {
            border: none !important;
            box-shadow: none !important;
        }
        
        /* The header (summary) - flat style, same in both collapsed and expanded */
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details) > summary {
            background: #1a1e24 !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 8px !important;
            padding: 13px 20px !important;
            transition: background 0.2s ease, border-color 0.2s ease !important;
            box-shadow: none !important;
            list-style: none !important;
            display: flex !important;
            align-items: center !important;
            gap: 12px !important;
        }
        
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details) > summary::-webkit-details-marker {
            display: none !important;
        }
        
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details) > summary:hover {
            background: #1e2330 !important;
            border-color: rgba(255, 255, 255, 0.13) !important;
        }
        
        /* Title text */
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details) > summary p {
            font-size: 1.15rem !important;
            font-weight: 600 !important;
            color: #ffffff !important;
            margin: 0 !important;
            display: flex !important;
            align-items: center !important;
        }
        
        /* Custom Clock/History SVG */
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details) > summary p::before {
            content: '';
            display: inline-block;
            width: 26px;
            height: 26px;
            min-width: 26px;
            background-image: url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjYjFiYWM0IiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+PHBhdGggZD0iTTEyIDh2NGwzIDNtNi0zYTkgOSAwIDExLTE4IDAgOSA5IDAgMDExOCAweiIvPjwvc3ZnPg==');
            background-size: contain;
            background-repeat: no-repeat;
            background-position: center;
            opacity: 0.9;
            margin-right: 12px;
        }
        
        /* Style Streamlit's default chevron */
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details) > summary svg {
            color: #8b949e !important;
            width: 20px !important;
            height: 20px !important;
            opacity: 0.7 !important;
            transition: transform 0.2s ease !important;
        }
        
        /* Expanded state - only structural overrides needed, base look is identical */
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details)[open] {
            border: none !important;
        }
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details)[open] > summary {
            border-bottom-left-radius: 0 !important;
            border-bottom-right-radius: 0 !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
        }
        
        /* Content box wrapper */
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details) > div {
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-top: none !important;
            border-bottom-left-radius: 8px !important;
            border-bottom-right-radius: 8px !important;
            background-color: #0d1117 !important;
            padding: 0 24px 0px 24px !important;
        }
        /* Kill Streamlit's default 16px padding-top on the content wrapper */
        div:has(> div > #sync-history-marker) + div[data-testid="stLayoutWrapper"] details:not(.sync-history-details) > div {
            padding-top: 0 !important; 
        }
        </style>
        <div id="sync-history-marker" aria-hidden="true" style="width:0;height:0;overflow:hidden;"></div>
        """)

        # Fake-expander toggle: a manual show/hide. The outer 'Sync History'
        # cannot be a real st.expander, because each individual sync below IS a
        # real st.expander and Streamlit forbids nesting expanders. The toggle
        # keeps the section collapsible while letting every run collapse too.
        _hist_open = st.session_state.get('sync_history_open', False)
        st.markdown(
            f"""<style>
            div.st-key-sync_history_toggle button {{
                background: #1a1e24 !important;
                border: 1px solid rgba(255,255,255,0.08) !important;
                border-top-left-radius: 8px !important;
                border-top-right-radius: 8px !important;
                /* When open, square the bottom corners + keep the bottom border
                   as a divider so the panel below reads as this button's body. */
                border-bottom-left-radius: {'0' if _hist_open else '8px'} !important;
                border-bottom-right-radius: {'0' if _hist_open else '8px'} !important;
                justify-content: flex-start !important;
                padding: 16px 20px !important;
                height: auto !important;
                margin-top: 32px !important;
            }}
            div.st-key-sync_history_toggle button:hover {{
                background: #1e2330 !important;
                border-color: rgba(255,255,255,0.14) !important;
            }}
            div.st-key-sync_history_toggle button p {{
                font-size: 1.15rem !important; font-weight: 600 !important;
                color: #ffffff !important; display: flex !important; align-items: center !important;
            }}
            div.st-key-sync_history_toggle button p::before {{
                content: ""; display: inline-block; width: 22px; height: 22px; margin-right: 11px;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23b1bac4' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z'/%3E%3C/svg%3E");
                background-size: contain; background-repeat: no-repeat; background-position: center; opacity: 0.9;
            }}
            div.st-key-sync_history_toggle button::after {{
                content: ""; margin-left: auto; width: 15px; height: 15px;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238b949e' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='9 18 15 12 9 6'/%3E%3C/svg%3E");
                background-size: contain; background-repeat: no-repeat; background-position: center;
                transform: rotate({90 if _hist_open else 0}deg); transition: transform 0.2s ease;
            }}
            </style>""",
            unsafe_allow_html=True,
        )
        if st.button("Sync History", key="sync_history_toggle", use_container_width=True):
            st.session_state['sync_history_open'] = not _hist_open
            st.rerun()

        if _hist_open:
            if not history:
                st.write('No sync history yet.')
                return

            with st.container(border=True, key="synchist_box"):
                from collections import defaultdict
                from datetime import datetime
                from ui_helpers import friendly_course_name
                import theme
            
                # Action line at top of expander
                st.session_state.setdefault('sync_history_filter', 'all')
                st.session_state.setdefault('sync_history_course', None)

                st.html('<div id="sync-history-toolbar" aria-hidden="true" style="width:0;height:0;overflow:hidden;"></div>')
                col1, col2 = st.columns([3, 1])
                with col1:
                    # View all / By course
                    c1, c2, c3 = st.columns([1, 1, 2])
                    with c1:
                        st.button("View All", key="sync_hist_tab_all", use_container_width=True,
                                  type="primary" if st.session_state.sync_history_filter == 'all' else "secondary",
                                  on_click=lambda: st.session_state.update({'sync_history_filter': 'all'}))
                    with c2:
                        st.button("By Course", key="sync_hist_tab_course", use_container_width=True,
                                  type="primary" if st.session_state.sync_history_filter == 'course' else "secondary",
                                  on_click=lambda: st.session_state.update({'sync_history_filter': 'course'}))
                    with c3:
                        if st.session_state.sync_history_filter == 'course':
                            # Get all unique courses. Defensive: a corrupted /
                            # hand-edited history.json could carry a non-dict entry
                            # or a None/blank course name - either of which would
                            # otherwise blow up sorted() with a None-vs-str compare.
                            all_courses = set()
                            for entry in history:
                                if not isinstance(entry, dict):
                                    continue
                                for c in (entry.get('course_names') or []):
                                    fc = friendly_course_name(c) if c else None
                                    if isinstance(fc, str) and fc:
                                        all_courses.add(fc)
                            courses_list = sorted(all_courses, key=lambda s: s.lower())
                            if courses_list:
                                # Pre-select if previously selected
                                idx = 0
                                if st.session_state.sync_history_course in courses_list:
                                    idx = courses_list.index(st.session_state.sync_history_course)
                            
                                def on_course_change():
                                    st.session_state.sync_history_course = st.session_state.sync_hist_course_select
                            
                                st.selectbox("Select Course", courses_list, index=idx, label_visibility="collapsed", key="sync_hist_course_select", on_change=on_course_change)
            
                with col2:
                    if st.session_state.get('confirm_clear_history'):
                        cc1, cc2 = st.columns(2)
                        with cc1:
                            if st.button("No", use_container_width=True):
                                st.session_state.confirm_clear_history = False
                                st.rerun()
                        with cc2:
                            if st.button("Yes", type="primary", use_container_width=True):
                                if history_mgr is not None:
                                    history_mgr.clear_history()
                                # Invalidate the cached history so the now-empty
                                # state is re-read from disk on the next render.
                                st.session_state.pop('_sync_history_cache', None)
                                st.session_state.pop('confirm_clear_history', None)
                                st.rerun()
                        from ui.amber_notice import render_amber_notice
                        render_amber_notice("Are you sure you want to delete all sync history?", detail="This cannot be undone.")
                    else:
                        if st.button("Clear History", key="btn_sync_hist_clear", use_container_width=True):
                            st.session_state.confirm_clear_history = True
                            st.rerun()

                # Divider between action toolbar and list - extend to the box's
                # inner edges (-20px == the box's horizontal padding).
                st.html("""
                    <div style="
                        border-top: 1px solid rgba(255,255,255,0.08);
                        margin: 0px -20px 16px -20px;
                        background: rgba(255,255,255,0.02);
                        height: 1px;
                        margin-bottom: -20px;
                    "></div>
                """)

                # Filter history. Skip any non-dict entry up front so the whole
                # downstream pipeline (grouping + rendering) can assume dicts.
                filtered_history = []
                for entry in history:
                    if not isinstance(entry, dict):
                        continue
                    if st.session_state.sync_history_filter == 'course':
                        c_filter = st.session_state.get('sync_history_course')
                        if c_filter:
                            # friendly names in entry
                            entry_friendly_courses = [friendly_course_name(c) for c in (entry.get('course_names') or []) if c]
                            if c_filter not in entry_friendly_courses:
                                continue
                    filtered_history.append(entry)
                
                if not filtered_history:
                    from ui.amber_notice import render_info_notice
                    render_info_notice("No history matches your filter.")
                    return

                # Group by date
                grouped_history = defaultdict(list)
            
                def get_ordinal(n):
                    return str(n) + ("th" if 11 <= n <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))

                for entry in reversed(filtered_history[-15:]):  # Show up to 15 recent syncs
                    raw_time = entry.get('timestamp', '')
                    try:
                        dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M")
                        time_str = format_time_display(dt.strftime('%H:%M'))
                    except Exception:
                        time_str = raw_time
                        dt = None
                    
                    date_key = format_relative_date(raw_time, include_time=False, include_emoji=False)
                    
                    grouped_history[date_key].append({
                        'entry': entry,
                        'time_str': time_str,
                        'dt': dt
                    })
            
                # Per-run cards with native, per-file Open / Reveal action rows.
                # (Native widgets are required for working buttons, so each run is a
                # styled st.container - NOT a nested st.expander, which Streamlit
                # forbids inside the outer 'Sync History' expander.)
                from ui_shared import (
                    _FILETYPE_SVGS, _FILETYPE_SVG_DEFAULT,
                    inject_file_action_css, render_course_file_breakdown,
                )
                import os as _os
                from collections import defaultdict as _dd

                inject_file_action_css()
                # Style the dropdown panel + the per-run "fake expander" cards.
                st.markdown(
                    """<style>
                    /* The panel hangs directly off the bottom of the toggle
                       button (no top border/radius, pulled up to be flush) so
                       it reads as that button's body / dropdown content. */
                    div.st-key-synchist_box {
                        border: 1px solid rgba(255,255,255,0.08) !important;
                        border-top: none !important;
                        border-top-left-radius: 0 !important;
                        border-top-right-radius: 0 !important;
                        border-bottom-left-radius: 8px !important;
                        border-bottom-right-radius: 8px !important;
                        background: #0f1318 !important;
                        padding: 16px 20px 18px 20px !important;
                        margin-top: -16px !important;
                    }
                    div.st-key-synchist_runs { border: none !important; padding: 0 !important; background: transparent !important; }

                    /* ---- Per-run "fake expander" --------------------------- *
                     * A real st.expander can't show this rich two-line header
                     * while COLLAPSED (Streamlit strips HTML from labels), yet we
                     * still need native Open/Reveal buttons in the body. So each
                     * run is a card whose header is a full-width invisible button
                     * (the click target) with the rich HTML painted on top via a
                     * pointer-events:none overlay. The body renders below it.
                     *
                     * The CARD background is the DARK body/content colour; the
                     * lighter HEADER colour lives on the button, so (a) the body
                     * is visibly darker than the title, and (b) hover lightens
                     * ONLY the header (the button), never the content. */
                    div[class*="st-key-shist_run_"] {
                        position: relative !important;
                        border: 1px solid rgba(255,255,255,0.08) !important;
                        border-radius: 8px !important;
                        background: #15181e !important;            /* dark CONTENT bg */
                        box-shadow: 0 2px 8px rgba(0,0,0,0.12) !important;
                        padding: 0 !important;
                        margin-bottom: 7px !important;
                        overflow: hidden !important;
                    }
                    /* Flush header(button) <-> body. Collapse EVERY vertical-block
                       gap inside the run to 0 (descendant selector - this is the
                       form that reliably matches Streamlit 1.51's wrapper depth),
                       then re-expand the body's section spacing and the file-row
                       spacing further below. At equal specificity later source
                       order wins, so each block ends up with the gap we want:
                         - run's own block (button|overlay|body) -> 0  (flush)
                         - body content sections                 -> 9px
                         - file rows                             -> 4px  */
                    div[class*="st-key-shist_run_"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
                    /* The full-width click target = the header bar (carries the
                       lighter header colour + the ONLY hover state on the card). */
                    div[class*="st-key-shist_run_"] [data-testid="stButton"] { margin: 0 !important; }
                    div[class*="st-key-shist_run_"] [data-testid="stButton"] > button {
                        height: 60px !important; min-height: 60px !important; width: 100% !important;
                        background: #21252e !important; border: none !important;
                        box-shadow: none !important; padding: 0 !important;
                        transition: background 0.15s ease !important;
                    }
                    div[class*="st-key-shist_run_"] [data-testid="stButton"] > button:hover {
                        background: #272c37 !important;
                    }
                    div[class*="st-key-shist_run_"] [data-testid="stButton"] > button:focus,
                    div[class*="st-key-shist_run_"] [data-testid="stButton"] > button:active {
                        box-shadow: none !important; color: inherit !important;
                    }
                    /* The rich header painted on top of the button. */
                    div[class*="st-key-shist_run_"] [data-testid="stElementContainer"]:has(.shist-card) {
                        position: absolute !important; top: 0 !important; left: 0 !important; right: 0 !important;
                        height: 60px !important; margin: 0 !important;
                        pointer-events: none !important; z-index: 3 !important;
                    }
                    .shist-card { display: flex; align-items: center; gap: 13px; height: 60px; padding: 0 18px; }
                    .shist-chev { display: flex; align-items: center; flex-shrink: 0; transition: transform 0.2s ease; }
                    .shist-info { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1 1 auto; }
                    .shist-l1 { display: flex; align-items: center; gap: 9px; min-width: 0; }
                    .shist-l1 .shist-title { font-weight: 700; font-size: 0.97rem; color: #fff;
                        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
                    /* Smaller status pill - same text size, tighter padding. */
                    .shist-badge { font-size: 0.7rem; font-weight: 600; padding: 1px 6px; border-radius: 4px;
                        line-height: 1.35; border: 1px solid; white-space: nowrap; flex-shrink: 0; }
                    .shist-l2 { display: flex; align-items: center; gap: 8px; color: #c9d1d9; font-size: 0.82rem; }
                    .shist-l2 .shist-dot { color: #5c6269; }
                    .shist-l2 .shist-mode { display: inline-flex; align-items: center; gap: 5px; }
                    .shist-time { display: flex; align-items: center; gap: 5px; color: #8b949e;
                        font-size: 0.82rem; flex-shrink: 0; margin-left: 12px; }
                    /* Kill the hollow bordered box entirely. Streamlit wraps a
                       border=True container in a stVerticalBlockBorderWrapper that
                       carries a stock 1px border + ~1rem padding; THAT is the
                       "empty box that boxes in emptiness". We don't rely on knowing
                       whether the key lands on the wrapper or the inner block - we
                       strip border / shadow / radius / padding / bg from BOTH, then
                       re-apply the indent + bottom padding once on the keyed block.
                       NO divider - the darker body bg already separates it from the
                       (lighter) header, and the content sits flush under it. */
                    div[data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-shist_body_),
                    div[class*="st-key-shist_body_"] {
                        border: none !important; box-shadow: none !important;
                        border-radius: 0 !important; background: transparent !important;
                        margin: 0 !important;
                    }
                    div[data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-shist_body_) {
                        padding: 0 !important;
                    }
                    div[class*="st-key-shist_body_"] {
                        /* flush top (content pulled up under header), comfy bottom
                           (+5px breathing room from the card border), left indent
                           lines the content up with the header title. */
                        padding: 6px 18px 23px 44px !important;
                    }
                    /* Comfortable spacing between the body's content SECTIONS
                       (category headers + their file lists). The tight file rows
                       keep their own small gap - re-asserted LAST so it wins at
                       equal specificity. */
                    div[class*="st-key-shist_body_"] [data-testid="stVerticalBlock"] { gap: 9px !important; }
                    div[class*="st-key-fileactlist_"] [data-testid="stVerticalBlock"] { gap: 4px !important; }
                    </style>""",
                    unsafe_allow_html=True,
                )

                # Resolve each course's CURRENT folder so a moved folder still opens.
                current_folders = {}
                for _p in st.session_state.get('sync_pairs', []):
                    _cid = _p.get('course_id')
                    if _cid is not None:
                        current_folders[_cid] = _p.get('local_folder')

                def _as_int(v):
                    """Coerce a possibly-malformed history field to int (0 on failure)."""
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        return 0

                def _read_only_list(fnames):
                    """Read-only <ul> for legacy entries with no resolvable paths."""
                    _rows = []
                    for _fn in (fnames or []):
                        _fn = str(_fn)
                        _ext = _os.path.splitext(_fn)[1].lower().lstrip('.')
                        _icon = _FILETYPE_SVGS.get(_ext, _FILETYPE_SVG_DEFAULT)
                        _rows.append(
                            '<li style="margin-bottom:3px;list-style:none;margin-left:-28px;">'
                            f'<img src="{_icon}" style="width:14px;height:14px;vertical-align:middle;margin-top:-2px;margin-right:8px;" alt="{esc(_ext)}"/>'
                            f'{esc(_fn)}</li>'
                        )
                    return ('<ul style="margin:2px 0 0 0;padding-left:30px;color:#c9d1d9;font-size:0.84rem;">'
                            + "".join(_rows) + '</ul>')

                with st.container(border=True, key="synchist_runs"):
                    run_seq = 0
                    for date_key, items in grouped_history.items():
                        st.markdown(
                            f"<div style='color:#bac2cc;font-size:0.8rem;font-weight:600;text-transform:uppercase;"
                            f"letter-spacing:0.5px;margin:14px 2px 6px 2px;'>{HELP_ICONS['calendar']} {esc(date_key)}</div>",
                            unsafe_allow_html=True,
                        )

                        def _render_item(item, run_seq):
                            entry = item['entry']
                            # Coerce numeric/list fields defensively: a legacy or
                            # corrupt entry could carry wrong types, and a str>int
                            # compare or a None course list would crash the whole
                            # history page. (entry is guaranteed a dict by the filter.)
                            count = _as_int(entry.get('files_synced', 0))
                            courses_count = _as_int(entry.get('courses', 0))
                            course_names = entry.get('course_names') or []
                            if not isinstance(course_names, (list, tuple)):
                                course_names = [course_names]
                            errors = _as_int(entry.get('errors', 0))
                            error_details = entry.get('error_details') or []
                            synced_groups = [g for g in (entry.get('synced_groups') or [])
                                             if isinstance(g, dict) and g.get('files')]

                            if errors > 0:
                                status_bg, status_color, status_border = "rgba(235,168,52,0.1)", "#eba834", "rgba(235,168,52,0.2)"
                                status_text = f"{errors} error{'s' if errors != 1 else ''}"
                            elif count > 0:
                                status_bg, status_color, status_border = "rgba(52,211,153,0.1)", "#34d399", "rgba(52,211,153,0.2)"
                                status_text = "Success"
                            else:
                                status_bg, status_color, status_border = "rgba(255,255,255,0.03)", "#8b949e", "rgba(255,255,255,0.05)"
                                status_text = "No changes"

                            sync_mode_str = entry.get('sync_mode', 'normal')
                            sync_mode_text = (f"{HELP_ICONS['bolt_small']} Quick Sync" if sync_mode_str == 'quick'
                                              else f"{HELP_ICONS['search_small']} Analyze, Review & Sync")

                            # "Fake expander": Streamlit strips HTML from expander
                            # labels AND a real expander can't show a rich header
                            # while collapsed - so the header is a full-width
                            # invisible button (the click target) with the rich
                            # two-line HTML painted on top (pointer-events:none),
                            # and the body renders below only when open.
                            _names = [friendly_course_name(str(n)) for n in course_names if n]
                            _names = [nm for nm in _names if isinstance(nm, str) and nm]
                            _courses_plain = (", ".join(_names) if _names
                                              else (f"Across {courses_count} courses" if courses_count > 0 else "Sync"))

                            open_key = f"shist_open_{run_seq}"
                            is_open = st.session_state.get(open_key, False)

                            _clock = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
                                      "fill='none' stroke='%238b949e' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E"
                                      "%3Ccircle cx='12' cy='12' r='9'/%3E%3Cpolyline points='12 7 12 12 15 14'/%3E%3C/svg%3E")
                            _chevron = ("<svg xmlns='http://www.w3.org/2000/svg' width='15' height='15' viewBox='0 0 24 24' "
                                        "fill='none' stroke='#8b949e' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'>"
                                        "<polyline points='9 6 15 12 9 18'/></svg>")
                            header_html = (
                                "<div class='shist-card'>"
                                f"<div class='shist-chev' style='transform:rotate({90 if is_open else 0}deg);'>{_chevron}</div>"
                                "<div class='shist-info'>"
                                "<div class='shist-l1'>"
                                f"<span class='shist-title'>{esc(_courses_plain)}</span>"
                                f"<span class='shist-badge' style='color:{status_color};background:{status_bg};"
                                f"border-color:{status_border};'>{status_text}</span>"
                                "</div>"
                                "<div class='shist-l2'>"
                                f"<span>Synced {count} file{'s' if count != 1 else ''}</span>"
                                "<span class='shist-dot'>&bull;</span>"
                                f"<span class='shist-mode'>{sync_mode_text}</span>"
                                "</div>"
                                "</div>"
                                "<div class='shist-time'>"
                                f"<img src=\"{_clock}\" style='width:13px;height:13px;' alt='time'/>{esc(item['time_str'])}"
                                "</div>"
                                "</div>"
                            )

                            with st.container(border=True, key=f"shist_run_{run_seq}"):
                                if st.button("​", key=f"shist_btn_{run_seq}", use_container_width=True):
                                    st.session_state[open_key] = not is_open
                                    st.rerun()
                                st.markdown(header_html, unsafe_allow_html=True)

                                if is_open:
                                    with st.container(border=True, key=f"shist_body_{run_seq}"):
                                        if synced_groups:
                                            multi = len(synced_groups) > 1
                                            for gi, g in enumerate(synced_groups):
                                                files = g.get('files') or []
                                                course_root = g.get('local_folder') or ''
                                                if course_root and not Path(course_root).exists():
                                                    _alt = current_folders.get(g.get('course_id'))
                                                    if _alt and Path(_alt).exists():
                                                        course_root = _alt
                                                if multi:
                                                    _cname = esc(friendly_course_name(g.get('course_name', '') or 'Course'))
                                                    st.markdown(
                                                        f"<div style='margin:10px 0 2px 0;color:#cdd9e5;font-size:0.9rem;font-weight:700;'>"
                                                        f"{HELP_ICONS['folder']} {_cname}</div>",
                                                        unsafe_allow_html=True,
                                                    )
                                                render_course_file_breakdown(
                                                    files, course_root,
                                                    key_scope=f"synchist_{run_seq}_{gi}",
                                                )
                                        elif count > 0:
                                            categorized_files = entry.get('categorized_files') or {}
                                            if not isinstance(categorized_files, dict):
                                                categorized_files = {}
                                            if not categorized_files and entry.get('synced_files'):
                                                categorized_files = {'new': [], 'updated': entry.get('synced_files') or [], 'protected': []}
                                            for cat_key, cat_title, cat_icon in _SYNC_HISTORY_CATEGORIES:
                                                cf = categorized_files.get(cat_key)
                                                if not cf:
                                                    continue
                                                st.markdown(
                                                    f"<div style='color:#fff;font-size:0.85rem;font-weight:600;margin:10px 0 0 0;'>"
                                                    f"{HELP_ICONS[cat_icon]} {cat_title} "
                                                    f"<span style='color:#b1bac4;font-weight:500;'>({len(cf)})</span></div>"
                                                    + _read_only_list(cf),
                                                    unsafe_allow_html=True,
                                                )
                                        elif errors == 0:
                                            st.markdown(
                                                "<div style='color:#8b949e;font-size:0.84rem;margin-top:6px;'>Everything was up to date.</div>",
                                                unsafe_allow_html=True,
                                            )

                                        if errors > 0 and error_details:
                                            err_dict = _dd(list)
                                            for err in error_details:
                                                err = err if isinstance(err, str) else str(err)
                                                if ": " in err:
                                                    prefix, reason = err.split(": ", 1)
                                                    fname = prefix.replace("Error syncing ", "")
                                                    err_dict[reason].append(fname)
                                                else:
                                                    err_dict["Unknown error"].append(err)
                                            _eh = [f"<div style='color:#fff;font-size:0.85rem;font-weight:600;margin:10px 0 0 0;'>"
                                                   f"{HELP_ICONS['error']} Skipped / Failed "
                                                   f"<span style='color:#ff7b72;font-weight:500;'>({errors})</span></div>"]
                                            for reason, fnames in err_dict.items():
                                                _eh.append(f"<div style='color:#8b949e;font-size:0.75rem;margin-top:2px;'>({esc(reason)})</div>")
                                                _eh.append(_read_only_list(fnames))
                                            st.markdown("".join(_eh), unsafe_allow_html=True)

                        # Backstop: render each entry behind a try/except so a
                        # single malformed/corrupt history entry can never crash
                        # the whole Sync page. run_seq still advances in every
                        # case to keep the per-run widget keys unique.
                        for item in items:
                            try:
                                _render_item(item, run_seq)
                            except Exception as _entry_exc:
                                logger.warning(
                                    "Sync history: skipped an unrenderable entry (%s)",
                                    _entry_exc, exc_info=True,
                                )
                            run_seq += 1




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


# STEP 4 - Analysis + Syncing + Completion
# ===================================================================

def render_sync_step4( main_placeholder=None):
    """Render the entire sync Step 4: analysis → review → sync → done."""
    from styles import inject_css
    from ui.sync_review import inject_dynamic_sync_review_css
    
    inject_css('sync_review.css')
    inject_dynamic_sync_review_css()

    sync_pairs = st.session_state.get('sync_pairs', [])
    if not sync_pairs:
        from ui.amber_notice import render_amber_notice
        render_amber_notice(
            "No course folders found - this can happen after a page refresh.",
            detail="Go back and add your courses again to continue.",
        )
        if st.button('Go back', key="page_nav_back"):
            st.session_state['step'] = 1
            st.rerun()
        st.stop()

    status = st.session_state.get('download_status', '')

    # Normalize sync_failed → sync_complete: inject the crash message into
    # sync_errors so the completion screen's existing error UI surfaces it.
    if status == 'sync_failed':
        _worker_err = st.session_state.pop('sync_worker_error', 'Unknown sync engine error')
        _errs = list(st.session_state.get('sync_errors', []))
        _errs.insert(0, f"Sync engine error: {_worker_err}")
        st.session_state['sync_errors'] = _errs
        st.session_state['download_status'] = 'sync_complete'
        status = 'sync_complete'

    if status == 'analyzing':
        current_pass = st.session_state.get('analysis_pass', 1)

        if current_pass == 1:
            # M-7: Server-side fallback - if JS click never fires (CSP, iframe
            # sandbox, screen-reader nav), force-advance to pass 2 after 5s.
            import time as _time
            if 'analysis_pass1_started_at' not in st.session_state:
                st.session_state['analysis_pass1_started_at'] = _time.time()
            elif _time.time() - st.session_state['analysis_pass1_started_at'] > 5:
                st.session_state['analysis_pass'] = 2
                st.session_state.pop('analysis_pass1_started_at', None)
                st.rerun()
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
            st.session_state.pop('analysis_pass1_started_at', None)
            _run_analysis(sync_pairs, main_placeholder)
            
            # Optional: cleanup the flag when done
            if 'analysis_pass' in st.session_state:
                del st.session_state['analysis_pass']
                
            # CRITICAL FIX: Force rerun to transition to 'analyzed' or 'pre_sync'
            st.rerun()
    elif status == 'analyzed':
        _show_analysis_review()
    elif status == 'pre_sync':
        # Server-side fallback (parity with the analysis pass-1 fix): if the
        # JS auto-click below never fires (CSP, iframe sandbox, screen-reader
        # nav), force-advance to 'syncing' after 5s instead of stranding the
        # user on this screen forever.
        import time as _ps_time
        if 'pre_sync_started_at' not in st.session_state:
            st.session_state['pre_sync_started_at'] = _ps_time.time()
        elif _ps_time.time() - st.session_state['pre_sync_started_at'] > 5:
            st.session_state.pop('pre_sync_started_at', None)
            st.session_state['download_status'] = 'syncing'
            st.rerun()
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
            st.session_state.pop('pre_sync_started_at', None)
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

@st.dialog("​")
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
