"""
ui.sync_dialogs - Sync history, filetype selector, ignored files, course settings.

Extracted from ``sync_ui.py`` (Phase 5).

Contains:
  - ``render_sync_history()`` - sync history expander
  - ``render_filetype_selector()`` - filetype filter for review screen
  - ``show_course_ignored_files()`` - per-course ignored files dialog
  - ``select_course_dialog_inner()`` - course selection dialog
  - ``render_pending_folder_ui()`` - pending folder pairing UI
"""

from __future__ import annotations

import hashlib

import os
import urllib.parse
from collections import defaultdict
from pathlib import Path
from shared.helpers import path_exists

import streamlit as st

from shared import theme
from shared.components import SVG_FOLDER_YELLOW, pad_slot_children
from core.sync_manager import SyncManager
from shared.helpers import (
    esc,
    friendly_course_name,
)

# The app's one chevron glyph, as a CSS mask so a ::before can wear it and
# inherit a single colour. Same path as shared.components._CHEVRON_SVG (the
# "Courses selected for download" expander) - kept as a mask here because these
# chevrons need to be recoloured on the checked state.
_STD_CHEVRON_MASK = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
    "fill='none' stroke='%23000' stroke-width='2' stroke-linecap='round' "
    "stroke-linejoin='round'%3E%3Cpath d='M9 18l6-6-6-6'/%3E%3C/svg%3E"
)

_PAN_REC_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' "
    "fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' "
    "stroke-linejoin='round' style='vertical-align:middle;flex-shrink:0;'>"
    "<rect x='2' y='2' width='20' height='20' rx='2.18' ry='2.18'/>"
    "<line x1='7' y1='2' x2='7' y2='22'/><line x1='17' y1='2' x2='17' y2='22'/>"
    "<line x1='2' y1='12' x2='22' y2='12'/><line x1='2' y1='7' x2='7' y2='7'/>"
    "<line x1='2' y1='17' x2='7' y2='17'/><line x1='17' y1='17' x2='22' y2='17'/>"
    "<line x1='17' y1='7' x2='22' y2='7'/></svg>"
)

# Lazy imports to avoid circular dependency with sync_ui.py
def _select_sync_folder_lazy():
    """Open the native folder picker and record the result.

    Supports selecting SEVERAL folders at once (bulk add). A single selection
    behaves exactly as before - the folder is stored and its bound course is
    auto-detected. When more than one folder comes back, the raw list is stashed
    for ``render_pending_folder_ui`` to process, because matching each folder to
    a Canvas course needs ``course_names`` (only available there).

    Editing an existing pair is single-folder by definition, so any extra
    selections are ignored in that mode.
    """
    from shared.helpers import native_folder_multi_picker
    import streamlit as st
    editing = st.session_state.get('editing_pair_idx') is not None
    folders = native_folder_multi_picker(
        initial_dir=st.session_state.get('pending_sync_folder') or None
    )
    if not folders:
        return
    if editing or len(folders) == 1:
        folder_path = folders[0]
        _prev = st.session_state.get('pending_sync_folder') or ''
        st.session_state['pending_sync_folder'] = folder_path
        # --- Auto-detect course from manifest, only if the folder CHANGED ---
        # Confirming the picker without navigating anywhere is a no-op, and it
        # must look like one. This used to run unconditionally, so Edit -> Change
        # Folder -> Choose announced "course auto-detected from this folder" for a
        # folder the user had not changed - a claim about an action that did not
        # happen, on the one screen where the user is being careful about which
        # course a folder is bound to.
        #
        # Compared through the app's one folder normaliser, so a trailing
        # separator or a case difference is not mistaken for a change. In ADD mode
        # `_prev` is empty, so the first pick always counts as a change - which is
        # exactly when auto-detect is worth having.
        from shared.helpers import norm_folder_key as _nfk
        if _nfk(folder_path) != _nfk(_prev):
            _auto_detect_course_from_manifest(folder_path)
        return
    # Multiple folders → hand off to the bulk processor on the next render.
    st.session_state['_bulk_folders_raw'] = folders

def _auto_detect_course_from_manifest(folder_path: str):
    """Read .canvas_sync.db in *folder_path* and auto-select the bound course.

    Sets ``sync_selected_course_id`` and ``sync_auto_detected_course`` flag
    when a valid match is found among the currently available Canvas courses.
    """
    import streamlit as st
    try:
        bound_id = SyncManager.peek_bound_course_id(folder_path)
        if bound_id is None:
            return
        # Verify the bound course exists in the current Canvas session.
        # sync_pairs section builds course_names *after* this callback, but
        # the courses list is fetched before step-1 renders, so we check
        # the sync_pairs or any existing course_names map.
        # Simplest: just set it; render_pending_folder_ui will validate via
        # course_names and show "Course not found" if it no longer exists.
        bound_name = SyncManager.peek_bound_course_name(folder_path)
        st.session_state['sync_selected_course_id'] = bound_id
        st.session_state['sync_auto_detected_course'] = True
    except Exception:
        # Silently ignore - manifest might be locked or corrupt.
        pass


def _update_pair_by_signature_lazy(old_sig, new_pair):
    from sync.persistence import update_pair_by_signature
    update_pair_by_signature(old_sig, new_pair)


def _retarget_saved_pair_lazy(old_course_id, old_folder, new_pair):
    """Move a standalone saved pair's NAME to a re-linked course/folder so an
    inline Edit relocates a named pair just like the hub's Edit Pair. Non-fatal:
    a hub read/write failure must never block the sync-list edit itself."""
    try:
        from core.sync_manager import SavedGroupsManager
        from shared.helpers import get_config_dir
        SavedGroupsManager(get_config_dir()).retarget_standalone_pair(
            old_course_id, old_folder, new_pair)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Could not retarget saved pair on inline re-link", exc_info=True)

def _add_pair_lazy(pair):
    from sync.persistence import add_pair
    add_pair(pair)


# ── Bulk "Add Course" (multi-folder selection) ─────────────────────────────
# Session keys used while a bulk add is in progress:
#   _bulk_folders_raw   - the raw list just picked, awaiting processing
#   _bulk_total         - how many folders need MANUAL course assignment
#   _bulk_index         - 1-based position of the folder currently in the form
#   _bulk_folder_queue  - folders still queued AFTER the current one
# All are listed in state_registry.SYNC_TRANSIENT_KEYS so navigating away clears
# them.

def _clear_bulk_state():
    for k in ('_bulk_folders_raw', '_bulk_total', '_bulk_index',
              '_bulk_folder_queue'):
        st.session_state.pop(k, None)


def _load_bulk_folder(folder: str):
    """Load one queued folder into the pending-pair form.

    No course is pre-selected - only a folder whose manifest names a course is
    trusted enough to auto-add (that happens in :func:`_process_bulk_folders`).
    Everything else lands here for the user to choose a course with the Select
    Course button, exactly like a single add.
    """
    st.session_state['pending_sync_folder'] = folder
    st.session_state['sync_selected_course_id'] = None
    st.session_state.pop('sync_auto_detected_course', None)


def _advance_bulk() -> bool:
    """Move to the next queued folder, or finish the bulk run. Returns True if a
    folder was loaded (more to do), False if the queue is now empty (form closed)."""
    queue = st.session_state.get('_bulk_folder_queue', [])
    if queue:
        nxt = queue.pop(0)
        st.session_state['_bulk_folder_queue'] = queue
        st.session_state['_bulk_index'] = st.session_state.get('_bulk_index', 1) + 1
        _load_bulk_folder(nxt)
        return True
    # Done - tear the form down.
    _clear_bulk_state()
    st.session_state['pending_sync_folder'] = None
    st.session_state.pop('sync_selected_course_id', None)
    st.session_state.pop('sync_auto_detected_course', None)
    return False


def _process_bulk_folders(raw: list[str], course_names: dict):
    """Partition freshly picked folders and set up the bulk add.

    Manifest-matched folders (their ``.canvas_sync.db`` is bound to a course
    that still exists in Canvas) are added straight away - the binding is
    authoritative. Everything else is queued for one-at-a-time confirmation with
    a fuzzy course guess pre-filled. Folders already on the sync list are
    skipped. A summary is queued as a toast.
    """
    from sync.persistence import add_pairs_batch
    sync_pairs = st.session_state.get('sync_pairs', [])
    existing_folders = {p.get('local_folder') for p in sync_pairs}

    auto_pairs: list[dict] = []
    queue: list[str] = []
    skipped = 0
    seen: set = set()
    for folder in raw:
        if not folder or folder in seen:
            continue
        seen.add(folder)
        if folder in existing_folders:
            skipped += 1
            continue
        cid = None
        try:
            cid = SyncManager.peek_bound_course_id(folder)
        except Exception:
            cid = None
        if cid and cid in course_names:
            auto_pairs.append({
                'local_folder': folder,
                'course_id': cid,
                'course_name': course_names[cid],
                'last_synced': None,
            })
            existing_folders.add(folder)
        else:
            queue.append(folder)

    if auto_pairs:
        add_pairs_batch(auto_pairs)

    parts = []
    if auto_pairs:
        n = len(auto_pairs)
        parts.append(f"{n} folder{'s' if n != 1 else ''} auto-matched and added")
    if skipped:
        parts.append(f"{skipped} already on your list")
    if parts:
        st.session_state['pending_toast'] = " · ".join(parts)

    if queue:
        st.session_state['_bulk_total'] = len(queue)
        st.session_state['_bulk_index'] = 1
        first = queue.pop(0)
        st.session_state['_bulk_folder_queue'] = queue
        _load_bulk_folder(first)
    else:
        # Everything was handled automatically - close the form.
        _clear_bulk_state()
        st.session_state['pending_sync_folder'] = None
        st.session_state.pop('sync_selected_course_id', None)


def render_filetype_selector(all_files, prefix, file_key_fn):
    """Bulk Selection Matrix - filetype unit checkboxes that act as remote controls.
    
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
        cols = st.columns(min(len(all_exts_sorted), 10))
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




def show_course_ignored_files(course_name, course_id, course_data, pair_sig=None):
    """Per-course ignored files dialog - Smart Select tag-button architecture.

    Uses the Zero-Width Space Hack for a custom dialog header with Base64 icon.
    Implements the same tag-button filetype selector as the Sync Review page.
    """
    from core.sync_manager import format_file_size
    from shared.helpers import get_base64_image

    # on_dismiss="rerun": restoring files is an on_click callback that mutates
    # the manifest and invalidates _ignored_files_cache via a fragment rerun, so
    # the main-page card's "Ignored Files (N)" count + disabled state go stale.
    # Backdrop/ESC dismissal would reveal that stale render until the next click;
    # "rerun" forces a full app rerun so the card recomputes from fresh data.
    @st.dialog("\u200b", width="large", on_dismiss="rerun")
    def _dialog():
        sm = course_data['sync_manager']
        files = sm.get_ignored_files()
        # PER-PAIR prefix, not per-course. Ignored files belong to ONE folder's
        # manifest, and the same course can be synced into two folders - with a
        # course-only prefix both dialogs shared every checkbox key, so ticking a
        # file in one pair pre-ticked "the same" file in the other. Derived from
        # the caller's pair key (course_id + normalised folder) and hashed so the
        # value is short, stable across reruns, and safe in a CSS selector - the
        # prefix is interpolated into `st-key-` selectors throughout this dialog.
        _sig = pair_sig if pair_sig is not None else (course_id,)
        _disc = hashlib.sha1(repr(_sig).encode("utf-8")).hexdigest()[:8]
        prefix = f"cign_{course_id}_{_disc}"

        # Ignored Panopto recordings (the whole recording entity). Sized from the
        # manifest's on-disk outputs when present (this management dialog runs
        # outside analysis, so there's no duration probe / estimate here).
        pan_ignored = sm.get_ignored_panopto()
        _pan_manifest = sm.get_panopto_manifest() if pan_ignored else {}
        try:
            _pan_root = sm.local_path
        except Exception:
            _pan_root = None

        def _pan_rec_size(vid: str) -> int:
            total = 0
            for rel in (_pan_manifest.get(vid) or {}).values():
                try:
                    p = (_pan_root / rel) if _pan_root else None
                    if p and path_exists(p):
                        total += p.stat().st_size
                except OSError:
                    pass
            return total

        pan_keys = [f"{prefix}_pan_{vid}" for vid in pan_ignored]
        for k in pan_keys:
            st.session_state.setdefault(k, False)

        # ── Build data structures ──────────────────────────────────────
        all_keys: list[str] = []
        all_file_tuples: list[tuple[str, object]] = []
        ext_to_keys: dict[str, list[str]] = defaultdict(list)

        for f in files:
            key = f"{prefix}_{f.canvas_file_id}"
            if key not in st.session_state:
                st.session_state[key] = False
            all_keys.append(key)
            all_file_tuples.append((key, f))
            ext = os.path.splitext(f.canvas_filename)[1].lower() or ".unknown"
            ext_to_keys[ext].append(key)

        for vid in pan_ignored:
            key = f"{prefix}_pan_{vid}"
            ext_to_keys['panopto'].append(key)

        all_exts_sorted = sorted(ext_to_keys.keys())

        # ── Static CSS Hoisting ────────────────────────────────────────
        b64_icon = get_base64_image("assets/Icon_Ignore.svg")
        b64_select_all = get_base64_image("assets/icon_select_all.png")
        b64_clear = get_base64_image("assets/icon_clear_selection.png")
        b64_restore = get_base64_image("assets/icon_restore.png")

        # Per-extension CSS is computed inline after buttons render
        # (mirrors sync_review.py pattern for reliable styling).

        is_expanded = st.session_state.get(f"{prefix}_chevron", False)
        # Symmetric on all four sides. The card used to run 4px on top against
        # 14px on the sides and bottom, so the title sat visibly closer to the
        # top edge than anything else was to its own edge.
        card_pad_y = 14 if is_expanded else 12
        # Collapsed: the strip IS the card, so round all four corners and leave
        # no gap under it. Expanded: round only the top and leave air before the
        # filetype pills.
        header_radius = "10px" if not is_expanded else "10px 10px 0 0"
        header_gap = 0 if not is_expanded else 8
        filelist_height = 340 if is_expanded else 480

        _css = f"""<style>
            /* (Removed: a 0.25rem "dialog compact gaps" rule keyed off
               stDialogScrollableBody, which 1.51 does not render. The dialog's
               gaps come from the live rules below and in sync_review.css.) */
            /* Smart Select outer card */
            div[class*="st-key-{prefix}_filter_box"] {{
                background: rgba(255,255,255,0.03) !important;
                border: 1px solid rgba(255,255,255,0.1) !important;
                border-radius: 10px !important;
                padding: {card_pad_y}px 14px {card_pad_y}px 14px !important;
                margin-top: -10px !important;
                margin-bottom: -10px !important;
            }}
            div[class*="st-key-{prefix}_filter_box"] div[data-testid="stVerticalBlock"] {{
                gap: 0.1rem !important;
            }}
            /* COLLAPSED: the card must be exactly as tall as the strip that
               toggles it. The header label bleeds out over the card's TOP
               padding (negative margin) and recreates it as its own padding, so
               that half is clickable - but the card's BOTTOM padding sits below
               the label and is not, which left a dead band roughly a fifth of
               the card's height under the only thing you can click. Reported
               2026-08-11 as "+20% of extra unclickable space below the area
               that's supposed to be clickable".
               Driven off the checkbox's own state so no Python round-trip is
               involved: `:has(... input:not(:checked))` is the collapsed card. */
            div[class*="st-key-{prefix}_filter_box"]:has(div[class*="st-key-{prefix}_chevron"] input:not(:checked)) {{
                padding-bottom: 0 !important;
            }}

            /* -- Custom Chevron Toggle -- */
            /* The full width chain is load-bearing for the hit area below:
               1.51 gives a checkbox's element-container a CONTENT-based
               explicit width, so `width: 100%` on the label alone resolved
               against a 155px box and the clickable strip stayed the width of
               the words (measured: label 155px inside an 1184px card). */
            div[class*="st-key-{prefix}_chevron"],
            div[class*="st-key-{prefix}_chevron"] [data-testid="stCheckbox"] {{
                width: 100% !important;
                max-width: 100% !important;
            }}
            div[class*="st-key-{prefix}_chevron"] {{
                margin: 0 !important;
            }}
            /* The WHOLE header strip is the hit target, not just the words.
               The label is bled out over the card's own padding with matched
               negative margins, so clicking anywhere on that band toggles it:
               when collapsed the card contains nothing else, so the entire card
               is clickable; when expanded only the title band is. Same trick
               the other expanders in the app use. */
            div[class*="st-key-{prefix}_chevron"] label[data-baseweb="checkbox"] {{
                margin: -{card_pad_y}px -14px {header_gap}px -14px !important;
                padding: {card_pad_y}px 14px {card_pad_y}px 14px !important;
                width: calc(100% + 28px) !important;
                border-radius: {header_radius} !important;
                cursor: pointer !important;
                gap: 0 !important;
                transition: background-color 0.15s ease !important;
            }}
            div[class*="st-key-{prefix}_chevron"] label[data-baseweb="checkbox"]:hover {{
                background-color: rgba(255,255,255,0.04) !important;
            }}
            div[class*="st-key-{prefix}_chevron"] label[data-baseweb="checkbox"] > span:first-child {{
                display: none !important;
            }}
            div[class*="st-key-{prefix}_chevron"] label[data-baseweb="checkbox"] > div {{
                margin-left: 0 !important;
            }}
            /* Flex row so the masked chevron below sits on the text's optical
               centre instead of its baseline (an inline-block box would). */
            div[class*="st-key-{prefix}_chevron"] label p {{
                font-size: 1.05rem !important;
                font-weight: 700 !important;
                color: #fff !important;
                margin: 0 !important;
                display: flex !important;
                align-items: center !important;
            }}
            /* The app's standard chevron glyph (same SVG as the "Courses
               selected for download" expander), NOT the "▸" text character it
               used to be - that rendered in whatever the system font had, at a
               different weight and baseline from every other chevron in the
               app. Masked so it inherits a single colour and can be sized in px. */
            div[class*="st-key-{prefix}_chevron"] label p::before {{
                content: "" !important;
                display: inline-block !important;
                width: 14px !important;
                height: 14px !important;
                flex-shrink: 0 !important;
                margin-right: 10px !important;
                background-color: rgba(255,255,255,0.55) !important;
                -webkit-mask-image: url("{_STD_CHEVRON_MASK}");
                mask-image: url("{_STD_CHEVRON_MASK}");
                -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
                -webkit-mask-position: center;  mask-position: center;
                -webkit-mask-size: contain;    mask-size: contain;
                transition: transform 0.18s ease !important;
            }}
            div[class*="st-key-{prefix}_chevron"]:has(input:checked) label p::before {{
                transform: rotate(90deg) !important;
                background-color: #ffffff !important;
            }}
            /* Filetypes flex */
            div[class*="st-key-{prefix}_ft_flex"] {{
                border: none !important; background: transparent !important;
                box-shadow: none !important; padding: 0 !important; margin-top: -6px !important;
            }}
            div[class*="st-key-{prefix}_ft_flex"] div[data-testid="stHorizontalBlock"] {{
                flex-wrap: wrap !important; row-gap: 6px !important; column-gap: 6px !important;
                margin-bottom: -12px !important;
            }}
            div[class*="st-key-{prefix}_ft_flex"] div[data-testid="stColumn"] {{
                width: auto !important; flex: 0 0 auto !important; min-width: 0 !important;
                padding-bottom: 12px !important;
            }}
            div[class*="st-key-{prefix}_ft_flex"] div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] {{
                gap: 0 !important;
            }}
            /* Bulk buttons row */
            div[class*="st-key-{prefix}_bulk_btns"] {{
                border: none !important; background: transparent !important;
                box-shadow: none !important; padding: 0 !important; margin: 0 !important;
            }}
            div[class*="st-key-{prefix}_bulk_btns"] > div[data-testid="stVerticalBlock"] {{
                gap: 0 !important; padding-bottom: 0 !important;
            }}
            /* Select All / Deselect All */
            div[class*="st-key-{prefix}_btn_sa"] button, div[class*="st-key-{prefix}_btn_da"] button {{
                background-color: rgba(255,255,255,0.07) !important; border: none !important;
                border-radius: 8px !important; color: #fff !important;
                height: 35px !important; min-height: 35px !important;
                padding-left: 12px !important; padding-right: 14px !important;
                white-space: nowrap !important; width: 100% !important;
                transition: background-color 0.15s ease !important;
            }}
            div[class*="st-key-{prefix}_btn_sa"] button:hover, div[class*="st-key-{prefix}_btn_da"] button:hover {{
                background-color: rgba(255,255,255,0.15) !important;
            }}
            div[class*="st-key-{prefix}_btn_sa"] button p, div[class*="st-key-{prefix}_btn_da"] button p {{
                display: flex !important; align-items: center !important; gap: 10px !important;
                margin: 0 !important; line-height: 1 !important; white-space: nowrap !important;
            }}
            div[class*="st-key-{prefix}_btn_sa"] button p::before, div[class*="st-key-{prefix}_btn_da"] button p::before {{
                content: "" !important; display: inline-block !important;
                width: 16px !important; height: 16px !important;
                background-size: contain !important; background-repeat: no-repeat !important;
                background-position: center !important; flex-shrink: 0 !important;
            }}
            div[class*="st-key-{prefix}_btn_sa"] button p::before {{
                background-image: url('data:image/png;base64,{b64_select_all}') !important;
            }}
            div[class*="st-key-{prefix}_btn_da"] button p::before {{
                background-image: url('data:image/png;base64,{b64_clear}') !important;
            }}
            /* Restore button icon */
            div[class*="st-key-{prefix}_restore"] button p {{
                display: flex !important; align-items: center !important;
                justify-content: center !important; gap: 8px !important;
                margin: 0 !important; line-height: 1 !important;
            }}
            div[class*="st-key-{prefix}_restore"] button p::before {{
                content: "" !important; display: inline-block !important;
                width: 18px !important; height: 18px !important;
                background-image: url('data:image/png;base64,{b64_restore}') !important;
                background-size: contain !important; background-repeat: no-repeat !important;
                background-position: center !important; flex-shrink: 0 !important;
            }}
            /* Action Buttons Explicit Match */
            div[class*="st-key-{prefix}_close"] button,
            div[class*="st-key-{prefix}_restore"] button {{
                height: 48px !important;
                min-height: 48px !important;
                border-radius: 8px !important;
            }}
            /* Disabled Restore button: no rules here - global.css's
               `button[disabled]` recipe owns it and dims the ::before icon in
               the same pass. The flat rgba(255,255,255,0.075) slab this used to
               paint was exactly the "second unrelated off-style" the single
               recipe exists to eliminate. */
            /* File list tags */
            div[class*="st-key-{prefix}_filelist"] del {{
                text-decoration: none !important; background-color: rgba(255,255,255,0.1) !important;
                color: #fff !important; padding: 2px 6px !important; border-radius: 4px !important;
                font-size: 0.70rem !important; font-weight: 500 !important; margin-left: 6px !important;
            }}
            div[class*="st-key-{prefix}_filelist"] code {{
                background-color: rgba(0,0,0,0.25) !important; color: #9ca3af !important;
                padding: 2px 6px !important; border-radius: 4px !important;
                font-size: 0.70rem !important; font-weight: 500 !important;
                border: none !important; margin-left: 6px !important;
            }}
            /* Clickable rows for ignored files list */
            div[data-testid="stDialog"] div[class*="st-key-ign_row_"] {{
                border-radius: 8px !important;
                transition: background-color 0.2s ease !important;
                padding: 0px 12px !important;
                margin-top: -6px !important;
                margin-bottom: -6px !important;
            }}
            div[data-testid="stDialog"] div[class*="st-key-ign_row_"]:hover {{
                background-color: rgba(255, 255, 255, 0.04) !important;
                cursor: pointer !important;
            }}
            div[data-testid="stDialog"] div[class*="st-key-ign_row_"]:has(input[type="checkbox"]:checked) {{
                background-color: rgba(56, 189, 248, 0.06) !important;
            }}
            /* Force the stElementContainer (checkbox wrapper) to fill the row width */
            div[data-testid="stDialog"] div[class*="st-key-ign_row_"] .stElementContainer:has([data-testid="stCheckbox"]) {{
                width: 100% !important;
            }}
            div[data-testid="stDialog"] div[class*="st-key-ign_row_"] [data-testid="stCheckbox"] {{
                width: 100% !important;
            }}
            /* Move vertical padding INTO the label so the entire row height is clickable */
            div[data-testid="stDialog"] div[class*="st-key-ign_row_"] label[data-baseweb="checkbox"] {{
                width: 100% !important;
                cursor: pointer !important;
                padding-top: 8px !important;
                padding-bottom: 8px !important;
            }}
"""
        tag_css_blocks = []
        if all_exts_sorted:
            for ext in all_exts_sorted:
                safe_ext = ext.replace('.', '')
                btn_key = f"{prefix}_filter_btn_{safe_ext}"
                ext_keys = ext_to_keys[ext]
                total = len(ext_keys)
                selected = sum(1 for k in ext_keys if st.session_state.get(k, False))
                if selected == 0:
                    # Depth-ramp tiers, deliberately near their tokens - see
                    # styles/sync_history_cards.css.  # audit-ignore
                    bg, bg_h = "#11141a", "#1a1e28"
                    bd, bd_h = "rgba(255,255,255,0.25)", "rgba(255,255,255,0.4)"
                elif selected == total:
                    bg, bg_h = "#1f486b", "#285b86"
                    bd, bd_h = "#3498db", "#5dade2"
                else:
                    bg, bg_h = "#0d1b2a", "#142838"
                    bd, bd_h = "#3498db", "#5dade2"
                _k_low = btn_key.lower()
                _k_hyp = btn_key.lower().replace('_', '-')
                tag_css_blocks.append(f"""
            div[data-testid="stDialog"] div.st-key-{_k_low} button, div[role="dialog"] div[class*="st-key-{_k_low}"] button,
            div[class*="st-key-{_k_low}"] button, div[class*="st-key-{_k_hyp}"] button {{
                background-color: {bg} !important; border: 1px solid {bd} !important;
                color: #ffffff !important; padding: 2px 14px !important;
                min-height: 28px !important; height: 28px !important;
                border-radius: 6px !important; transition: all 0.15s ease !important;
                box-shadow: none !important;
            }}
            div[data-testid="stDialog"] div.st-key-{_k_low} button:hover, div[role="dialog"] div[class*="st-key-{_k_low}"] button:hover,
            div[class*="st-key-{_k_low}"] button:hover, div[class*="st-key-{_k_hyp}"] button:hover {{
                background-color: {bg_h} !important; border-color: {bd_h} !important;
            }}
            div[data-testid="stDialog"] div.st-key-{_k_low} button p, div[role="dialog"] div[class*="st-key-{_k_low}"] button p,
            div[class*="st-key-{_k_low}"] button p, div[class*="st-key-{_k_hyp}"] button p {{
                font-size: 0.8rem !important; font-weight: 500 !important; margin: 0 !important;
            }}
            div[data-testid="stDialog"] div.st-key-{_k_low} button p span, div[role="dialog"] div[class*="st-key-{_k_low}"] button p span,
            div[class*="st-key-{_k_low}"] button p span, div[class*="st-key-{_k_hyp}"] button p span {{
                font-size: 0.7rem !important; font-weight: 400 !important;
                color: rgba(255,255,255,0.55) !important;
                margin-left: 3px !important; letter-spacing: 0.3px !important;
            }}""")

        _css += "".join(tag_css_blocks) + "</style>"
        st.html(_css)

        # ── 1. Custom Header ──────────────────────────────────────────
        # The course sits ON the title line as a blue tag, not as a "Course:"
        # label underneath it - the dialog is always about exactly one course,
        # so that is scope, not content. The paragraph below answers the three
        # questions the old one-liner left open: what "ignored" actually does,
        # what happens to a file you restore, and where it turns up afterwards.
        st.html(f"""
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:0;margin-top:-70px;flex-wrap:wrap;">
            <img src="data:image/svg+xml;base64,{b64_icon}"
                 style="width:32px;height:32px;filter:brightness(0) invert(1) opacity(0.9);" />
            <div style="margin:0;padding:0;font-size:1.75rem;font-weight:600;color:white;">
                Ignored Files
            </div>
            <span style="background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.22);
                         color:#e2e8f0;font-size:1.0rem;font-weight:600;line-height:1.25;
                         padding:6px 14px;border-radius:8px;white-space:nowrap;margin-left:6px;
                         max-width:100%;overflow:hidden;text-overflow:ellipsis;">{esc(course_name)}</span>
        </div>
        <hr style="border:none;border-top:1px solid rgba(255,255,255,0.2);margin-top: 12px;" />
        """)

        # ── 2. Help text ──────────────────────────────────────────────
        # Deliberately unstyled emphasis: an earlier version bolded the key
        # phrases in near-white against a 0.55-alpha body, which inverted the
        # reading order - the highlights were legible and the sentence they
        # belonged to sank into the background. One brightness, no bold, and
        # short enough to actually be read.
        st.html(
            # No max-width. A `ch`-based cap looks sensible in the abstract and
            # in a 1370px dialog it wrapped this to barely half the width, which
            # reads as a broken column rather than a comfortable measure.
            "<div style='font-size:0.86rem;color:rgba(255,255,255,0.78);"
            "line-height:1.6;margin-top:-10px;margin-bottom:12px;'>"
            "Ignored files are skipped by every sync of this course and are never "
            "re-downloaded - the copies on your computer are untouched. Restore "
            "one and it comes back in the next sync review, where you can decide "
            "whether to download it."
            "</div>"
        )

        # -- 3. Smart Select Card (Collapsible chevron) -----------------
        with st.container(border=True, key=f"{prefix}_filter_box"):
            # Custom chevron toggle (checkbox styled as rotating arrow header)
            chevron_key = f"{prefix}_chevron"
            if chevron_key not in st.session_state:
                st.session_state[chevron_key] = False  # start collapsed
            st.checkbox("Smart Select", key=chevron_key)

            if st.session_state[chevron_key]:
                if not all_exts_sorted and not pan_ignored:
                    # Nothing left to select. Before this the expander opened onto
                    # a bare divider and two dead bulk buttons, which reads as a
                    # component that failed to load rather than as an empty set -
                    # and it is reachable in one click, by restoring the last
                    # ignored file with Smart Select already open.
                    from ui.amber_notice import render_info_notice
                    render_info_notice(
                        "No ignored files to select from.",  # audit-ignore: literal
                        key=f"{prefix}_smart_empty")
                if all_exts_sorted:
                    st.html("<div style='font-size:0.72em;padding:0;color:rgba(255,255,255,0.45);font-weight:400;margin-top:-15px;margin-bottom:-5px;'>By filetype</div>")

                    with st.container(border=True, key=f"{prefix}_ft_flex"):
                        safe_len = min(len(all_exts_sorted), 10)
                        cols = st.columns(safe_len)
                        for i, ext in enumerate(all_exts_sorted):
                            safe_ext = ext.replace('.', '')
                            btn_key = f"{prefix}_filter_btn_{safe_ext}"
                            ext_keys = ext_to_keys[ext]
                            total = len(ext_keys)
                            selected = sum(1 for k in ext_keys if st.session_state.get(k, False))
                            ext_label = ext[1:].upper() if ext.startswith('.') else ext.upper()
                            if selected == 0:
                                final_label = f"{ext_label} :grey[(none)]"
                            elif selected == total:
                                final_label = f"{ext_label} :grey[(all)]"
                            else:
                                final_label = f"{ext_label} :grey[({selected}/{total})]"

                            def _on_tag_click(ext_name=ext):
                                ek = ext_to_keys[ext_name]
                                tot = len(ek)
                                sel = sum(1 for k in ek if st.session_state.get(k, False))
                                new_val = False if sel == tot else True
                                for k in ek:
                                    st.session_state[k] = new_val

                            with cols[i % safe_len]:
                                st.button(final_label, key=btn_key, on_click=_on_tag_click)

                st.html("<div style='padding:0; margin-top:-5px; margin-bottom:-5px;'><hr style='border:none;border-top:1px solid rgba(255,255,255,0.08);margin:0;' /></div>")

                with st.container(border=True, key=f"{prefix}_bulk_btns"):
                    col_sel, col_clr = st.columns([1, 1])
                    with col_sel:
                        def _select_all():
                            for k in all_keys + pan_keys:
                                st.session_state[k] = True
                        st.button("Select All", key=f"{prefix}_btn_sa", use_container_width=True, on_click=_select_all)
                    with col_clr:
                        def _deselect_all():
                            for k in all_keys + pan_keys:
                                st.session_state[k] = False
                        st.button("Deselect All", key=f"{prefix}_btn_da", use_container_width=True, on_click=_deselect_all)

        # ── 4. File list with extension + size tags ───────────────────
        # THE CONTENT AREA IS ALWAYS RENDERED, empty or not. It carries an explicit
        # height, so keeping it is what stops the dialog collapsing to a sliver
        # when the last ignored file is restored - and the empty state then sits
        # where the list was, which is the only place it makes sense.
        #
        # An earlier attempt put `min-height` on `div[role="dialog"] > div:first-child`
        # instead. That is NOT the padded body: measured in Chrome, the dialog has
        # three children and the first is a chrome wrapper, so the rule inflated it
        # into a 300px empty band ABOVE the title. Do not put a height on the
        # dialog itself - put it on the region that holds content.
        with st.container(height=filelist_height, border=True, key=f"{prefix}_filelist"):
            if not (all_file_tuples or pan_ignored):
                from ui.amber_notice import render_info_notice
                render_info_notice(
                    "Nothing is ignored for this course any more.",
                    detail="You can close this dialog. To ignore files again, use "
                           "\u201cMove deselected files to Ignored\u201d on the next "
                           "Sync Review.",
                    margin="4px 0 0 0", key=f"{prefix}_all_restored")
            if all_file_tuples or pan_ignored:
                # Render normal files
                if all_file_tuples:
                    for key, f in all_file_tuples:
                        _disp_raw = urllib.parse.unquote_plus(f.canvas_filename)
                        _name, _ext = os.path.splitext(_disp_raw)
                        _ext_clean = f" ~{_ext[1:].upper()}~" if _ext else ""
                        _size_clean = ""
                        if f.original_size and f.original_size > 0:
                            _size_clean = f" `{format_file_size(f.original_size)}`"
                        with st.container(key=f"ign_row_{course_id}_{f.canvas_file_id}"):
                            st.checkbox(f"{_name}{_ext_clean}{_size_clean}", key=key)

                # Render Panopto recordings inside the same list
                if pan_ignored:
                    st.markdown(
                        "<div style='margin:10px 0 6px 0; padding-top:10px; "
                        "border-top:1px solid rgba(255,255,255,0.10); color:rgba(255,255,255,0.6); "
                        "font-size:0.85rem; font-weight:600; display:flex; align-items:center; gap:7px;'>"
                        f"{_PAN_REC_SVG}<span>Panopto Recordings</span></div>",
                        unsafe_allow_html=True,
                    )
                    # Per-folder contract (output formats) drives which kinds count
                    # as "configured"; fall back to the current Section 4 session
                    # toggles when this folder has no stored contract yet.
                    from panopto.settings import compose_settings as _compose_pan
                    _pan_raw = None
                    try:
                        _pan_raw = sm._load_metadata('panopto_contract')
                    except Exception:
                        _pan_raw = None
                    _pan_contract = None
                    if _pan_raw:
                        try:
                            import json as _json_pan
                            _pan_contract = _json_pan.loads(_pan_raw)
                        except Exception:
                            _pan_contract = None
                    if _pan_contract is None:
                        from panopto.settings import contract_from_ui_state as _pan_from_state
                        _pan_contract = _pan_from_state(st.session_state)
                    _pan_settings = _compose_pan(_pan_contract)
                    # The configured kinds, in the app's one display order.
                    # Hand-listing them here is what let this dialog fall a
                    # format behind the card that configures them.
                    from panopto.sync_plan import wanted_kinds as _pan_wanted
                    _default_kinds = _pan_wanted(_pan_settings)

                    for vid, title in pan_ignored.items():
                        _psz = _pan_rec_size(vid)
                        _psize = f" `{format_file_size(_psz)}`" if _psz > 0 else ""

                        # Show what is missing/actionable (i.e. configured kinds minus what is already on disk)
                        _existing_kinds = []
                        for _k, _rel in _pan_manifest.get(vid, {}).items():
                            try:
                                _p = (_pan_root / _rel) if _pan_root else None
                                if _p and path_exists(_p):
                                    _existing_kinds.append(_k)
                            except OSError:
                                pass

                        _kinds = [k for k in _default_kinds if k not in _existing_kinds]
                        if not _kinds:
                            _kinds = _default_kinds

                        _badges_clean = " ".join(f"~{k.upper()}~" for k in _kinds)
                        _badges_sep = "  " if _badges_clean else ""

                        with st.container(key=f"ign_row_{course_id}_pan_{vid}"):
                            st.checkbox(f"{title or 'Untitled recording'}{_badges_sep}{_badges_clean}{_psize}",
                                        key=f"{prefix}_pan_{vid}")

        # ── 5. Count + success feedback ───────────────────────────────
        checked_files = sum(1 for k in all_keys if st.session_state.get(k, False))
        checked_pan = sum(1 for k in pan_keys if st.session_state.get(k, False))
        checked_count = checked_files + checked_pan

        if st.session_state.get(f"{prefix}_success"):
            from ui.amber_notice import render_success_notice
            render_success_notice(st.session_state.pop(f"{prefix}_success"), margin="10px 0 10px 0")


        # ── 6. Dynamic button text ────────────────────────────────────
        if checked_count == 0:
            btn_text = "Restore"
        elif checked_count == 1:
            btn_text = "Restore 1 item"
        else:
            btn_text = f"Restore {checked_count} items"

        # ── 7. Action buttons (Cancel left, Action right) ─────────────
        col_cancel, col_restore = st.columns([1, 1])
        with col_cancel:
            if st.button("Close", type="secondary", use_container_width=True, key=f"{prefix}_close"):
                for k in all_keys + pan_keys:
                    st.session_state.pop(k, None)
                st.rerun(scope="app")

        with col_restore:
            def _on_restore_course():
                to_restore = [
                    f.canvas_file_id for f in files
                    if st.session_state.get(f"{prefix}_{f.canvas_file_id}")
                ]
                pan_to_restore = [
                    vid for vid in pan_ignored
                    if st.session_state.get(f"{prefix}_pan_{vid}")
                ]
                n = len(to_restore) + len(pan_to_restore)
                if n:
                    if to_restore:
                        sm.bulk_restore_files(to_restore)
                    if pan_to_restore:
                        sm.bulk_restore_panopto(pan_to_restore)
                    fw = 'item' if n == 1 else 'items'
                    st.session_state[f"{prefix}_success"] = (
                        f"Successfully restored {n} {fw}! "
                        f"They will appear in your next Sync Review."
                    )
                    for fid in to_restore:
                        st.session_state.pop(f"{prefix}_{fid}", None)
                    for vid in pan_to_restore:
                        st.session_state.pop(f"{prefix}_pan_{vid}", None)
                    # Invalidate the ignored-files cache so the sync list
                    # re-queries SQLite and reflects the restored items.
                    st.session_state.pop('_ignored_files_cache', None)

            btn_help = "Select items to restore." if checked_count == 0 else "Remove selected items from the ignored list so they are included in future syncs."
            st.button(
                btn_text, type="primary", disabled=(checked_count == 0),
                use_container_width=True, key=f"{prefix}_restore",
                on_click=_on_restore_course,
                help=btn_help,
            )

    _dialog()



@st.dialog("Select Course to sync", width="large")
def select_course_dialog_inner(courses, current_selected_id, ):
    from ui.course_selector import (
        inject_course_selector_css, render_cbs_filters, render_course_list,
        render_favorites_pill, render_course_search, _filter_and_rank_courses,
        _render_search_empty_notice,
    )

    # Static CSS: scroll-container + compact dialog spacing
    st.html("""
        <style>
            /* Scroll container: border=True gives reliable st-key-* class.
               Strip the native border here. height:auto lets the list shrink
               to fit short Favorites lists; max-height caps growth so the
               dialog never overflows the viewport - All Courses scrolls
               internally via overflow-y:auto once content exceeds max-height. */
            div[class*="st-key-course_list_scroll_container"] {
                border: none !important;
                border-radius: 0 !important;
                height: auto !important;
                min-height: 30vh !important;
                max-height: 45vh !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
                padding: 0 !important;
                padding-right: 5px !important;
                margin-top: -0.4rem !important;
                margin-bottom: -0.4rem !important;
            }
            /* Strip padding from the inner stVerticalBlock so the first/last
               course item sits flush against the container edges. */
            div[class*="st-key-course_list_scroll_container"] > div[data-testid="stVerticalBlock"] {
                padding: 0 !important;
            }
            /* When CBS filters are expanded they take up ~80px above the list;
               shrink the max-height by the same amount to keep dialog within viewport. */
            html:has(div[class*="st-key-sync_d_show_cbs_filters"] input:checked) div[class*="st-key-course_list_scroll_container"] {
                max-height: 35vh !important;
            }
            /* Compact dialog: reduce stVerticalBlock gap between chrome elements
               (favorites pill, CBS toggle, hr, list, hr, Confirm button) from
               Streamlit's default ~1rem to 0.4rem. */
            div[role="dialog"] div[data-testid="stVerticalBlock"] {
                gap: 0.4rem !important;
            }
            /* Restore natural gap for the checkbox rows inside the course list.
               The rows already use margin-bottom:-10px tightening; a 0.4rem gap
               on top would cause them to overlap.
               CRITICAL: use :has(> ...) (DIRECT child), not :has(...) (descendant).
               A descendant :has() also matches every ANCESTOR block containing a
               checkbox - including the dialog's top-level block - so the 1rem gap
               leaks onto the whole dialog, inflating spacing and breaking the
               scroll container's -0.4rem flush-margins (CLAUDE.md JS/CSS rules). */
            div[data-testid="stVerticalBlock"]:has(> div[class*="st-key-sync_d_chk_"]) {
                gap: 1rem !important;
            }
            /* (Removed: a padding-top:0.25rem on stDialogScrollableBody - 1.51
               renders no padded body wrapper. Not migrated to
               `div[role="dialog"] > div:first-child`, whose top padding must stay
               >= ~1.5rem or the -70px custom header clips. See CLAUDE.md.) */
            /* Hide native X close button - closing without selecting would
               leave pending_sync_folder in a stale state. */
            div[data-testid="stDialog"] button[aria-label="Close"] {
                display: none !important;
            }
        </style>
    """)

    inject_course_selector_css()

    # 1. Favorites / All Courses pill toggle
    favorites_only = render_favorites_pill(
        "sync_d",
        default_favorites=st.session_state.get('sync_filter_favorites', True),
        in_dialog=True,
    )
    st.session_state['sync_filter_favorites'] = favorites_only

    visible_courses = courses
    if favorites_only:
        visible_courses = [c for c in courses if getattr(c, 'is_favorite', False)]

    if not visible_courses:
        from ui.amber_notice import render_amber_notice
        render_amber_notice('No courses found.')
        if st.button("Close"):
             st.rerun(scope="app")
        return

    # 2. CBS Filters (centralized)
    filtered_courses = render_cbs_filters(visible_courses, "sync_d")

    # 2b. Search box (live, relevance-ranked) - refines the CBS-filtered set.
    query = render_course_search("sync_d", in_dialog=True)
    displayed_courses = _filter_and_rank_courses(filtered_courses, query)

    # Initialize single-select state.
    # NOTE: Only check key *existence*, not value.  When the user deselects
    # a course inside the dialog, _on_toggle sets the value to None; if we
    # also guarded on "is None" here, every rerun would snap it back to
    # current_selected_id, making deselection impossible.
    if "sync_d_selected_id" not in st.session_state:
        st.session_state["sync_d_selected_id"] = current_selected_id

    st.html('<hr style="margin-top: 2px; margin-bottom: 4px; border-color: rgba(255,255,255,0.1);" />')

    # 3. Course list (centralized single-select)
    # border=True required so the st-key-* CSS class is reliably emitted
    # (CLAUDE.md "Border Strip" rule). The border is stripped in CSS above.
    with st.container(border=True, key="course_list_scroll_container"):
        if displayed_courses:
            render_course_list(displayed_courses, "sync_d", multi_select=False,
                               first_item_top_offset="-10px",
                               sort=not query.strip())
        elif query.strip():
            _render_search_empty_notice(
                query, favorites_only, visible_courses, filtered_courses, courses)
        else:
            # No query - let the list render its own "no filter matches" notice.
            render_course_list(displayed_courses, "sync_d", multi_select=False,
                               first_item_top_offset="-10px")

    # 4. Confirm
    st.html('<hr style="margin-top: 2px; margin-bottom: 4px; border-color: rgba(255,255,255,0.1);" />')
    _sel_id = st.session_state.get("sync_d_selected_id")
    _confirm_disabled = not bool(_sel_id)
    _confirm_help = "Select a course to continue." if _confirm_disabled else None
    if st.button("Confirm Selection", key="sync_confirm_btn", type="primary",
                 use_container_width=True, disabled=_confirm_disabled,
                 help=_confirm_help):
        st.session_state["sync_selected_return_id"] = _sel_id
        st.rerun(scope="app")


def render_pending_folder_ui(courses, course_names, course_options, ):
    """Inline UI shown while adding/editing a sync-pair - unified card."""
    # A pending BULK selection is processed here (not in the picker callback)
    # because matching folders to courses needs course_names. It reruns itself,
    # so the code below never sees a half-processed list.
    if '_bulk_folders_raw' in st.session_state:
        raw = st.session_state.pop('_bulk_folders_raw')
        _process_bulk_folders(raw, course_names)
        st.rerun(scope="app")

    pending_folder = st.session_state.get('pending_sync_folder', "")
    folder_name = Path(pending_folder).name if pending_folder else "Select Course Folder →"
    editing_idx = st.session_state.get('editing_pair_idx')

    # WHICH pair is being edited, resolved by LINK and not by position.
    #
    # `editing_pair_idx` is an index into `st.session_state['sync_pairs']`, and
    # the list can change while this form is open - the form replaces its own
    # row, but every OTHER row keeps a live Remove button, and "remove all"
    # exists. Indexing at save time therefore had two silent wrong outcomes:
    #
    #   [A,B,C]   edit C (idx 2), remove A -> len 2, so `0 <= 2 < 2` fails and
    #             Save Changes APPENDED a duplicate pair instead of editing.
    #   [A,B,C,D] edit C (idx 2), remove A -> idx 2 is now D, so Save Changes
    #             repointed D at the folder/course chosen for C AND moved D's
    #             user-given name onto that link (_retarget_saved_pair_lazy),
    #             leaving C untouched.
    #
    # Same identity-by-position class as the ignored-files cache keyed on
    # course_id. `pair_key` is the app's one answer to "which link is this?".
    _edit_sig = st.session_state.get('editing_pair_sig')
    _edit_pair = None
    if _edit_sig is not None:
        from core.pair_labels import pair_key as _pk
        _edit_pair = next(
            (p for p in st.session_state.get('sync_pairs', [])
             if _pk(p.get('course_id'), p.get('local_folder')) == _edit_sig),
            None)

    # Bulk add is only meaningful when creating pairs (never editing) and with a
    # folder actually loaded - the pending_folder guard stops a stale queue key
    # from dressing an empty add form as a bulk step.
    _bulk_active = (
        bool(st.session_state.get('_bulk_total'))
        and editing_idx is None
        and bool(pending_folder)
    )
    _bulk_queue_remaining = bool(st.session_state.get('_bulk_folder_queue'))

    # (1) Everything inside one bordered container.
    #
    # This form must be STRUCTURALLY ISOMORPHIC to the sync-list row it replaces:
    # ONE top-level slot, and FIVE children. Streamlit reconciles by index and
    # only prunes the previous run's nodes when the script run FINISHES, so both
    # numbers matter and they fail in different ways:
    #   * more or fewer SLOTS than a row shifts every item below it, and the tail
    #     of the old render stays on screen until the run ends (measured: a
    #     duplicated "Add Course" row for ~25ms when cancelling out of the form);
    #   * fewer CHILDREN than the row's five columns leaves the inherited extras
    #     in place, because addBlock hands a new block the children of whatever
    #     block sat at its index and only the ones our own elements overwrite go
    #     away (measured: the row's red "Remove" button sitting inside the open
    #     edit form, form 247px instead of 193px).
    # Together those two were the reported "the old grey card shifts below the
    # edit form and then disappears" and, from the Add Course button, "an empty
    # box with only the Add Course button in it". See the trailing st.empty().
    with st.container(border=True, key="edit_form_container"):
        # A style-only st.html() setting `gap: 0.25rem` used to sit here. It was
        # a DUPLICATE - global.css already declares `gap: 4px !important` on the
        # identical selector (see "SYNC FOLDER ROW COMPACT LAYOUT"), which is the
        # same 4px - so removing it changes no computed style. Worth removing
        # anyway: a style-only st.html goes to Streamlit's EVENT container, one
        # more slot in the index-addressed list that a dialog's fragment rerun
        # rewinds (CLAUDE.md, "A style-only st.html() after a dialog CALL SITE
        # gets DELETED"). The static file is where this rule belongs.
        # (3) CSS for cancel button red styling (Moved to render_sync_step1 for global scope/no flash)

        # --- Bulk-add progress banner ---
        # Rendered as the form's FIRST child while stepping through a multi-folder
        # selection. Kept inside the form container (not a new top-level slot) so
        # the "ONE top-level slot" isomorphism with the sync-list row still holds.
        if _bulk_active:
            _b_idx = st.session_state.get('_bulk_index', 1)
            _b_total = st.session_state.get('_bulk_total', 1)
            _hint = "Pick this folder's Canvas course, then continue."
            st.html(
                '<div style="background: rgba(56,139,253,0.10); '
                'border: 1px solid rgba(56,139,253,0.45); border-radius: 6px; '
                'padding: 8px 12px; margin: 0 0 6px 0; font-size: 0.9rem; line-height: 1.45;">'
                f'<span style="color:#79c0ff; font-weight:700;">Bulk add · folder {_b_idx} of {_b_total}</span>'
                f'<span style="color:#c9d1d9;"> - {esc(_hint)}</span>'
                '</div>'
            )

        # --- Course Selection (Pop-up Dialog) ---

        # Determine current display
        current_disp = 'Select Canvas Course →'
        
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
        # Show "Change Course" when editing OR when auto-detected a match
        if editing_idx is not None or selected_course_id:
             btn_label = 'Change Course'
        else:
             btn_label = 'Select Course'

        # Two columns like folder row: [1, 1, 1] to keep it left-aligned
        # REVISED: [1, 1, 1] - relying on CSS flex auto-width to handle content size
        col_c_info, col_c_btn, col_c_notice = st.columns([1, 1, 1], vertical_alignment="center", gap="small")

        with col_c_info:
            st.markdown(
                f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                f'{"Course: "}</span>'
                f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">{esc(current_disp)}</span>',
                unsafe_allow_html=True
            )
            
        with col_c_btn:
            if st.button(btn_label, key="btn_open_course_dialog"):
                st.session_state["sync_d_selected_id"] = selected_course_id
                # FLAG, not a call. Opening the dialog here would open it from
                # the middle of the sync page - and a dialog body is a fragment
                # whose rerun rewinds the EVENT container to its call site,
                # destroying every style-only st.html() the page emits after
                # this point (the Analyze / Quick Sync button stylesheet among
                # them). sync_ui.render_sync_step1 opens it at the very end;
                # _sync_pairs_section clears this flag at the start of each run
                # so a stale one can never open the dialog by itself.
                st.session_state["_sync_open_course_dialog"] = True
        
        with col_c_notice:
            if st.session_state.get('sync_auto_detected_course') and selected_course_id:
                st.markdown(
                    f'<span style="color:#a6eaff;font-size:0.85rem;font-weight:500;display:inline-flex;align-items:center;margin-left:8px;white-space:nowrap;">'
                    f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-wand-sparkles-icon lucide-wand-sparkles" style="margin-right:4px;flex-shrink:0;"><path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72"/><path d="m14 7 3 3"/><path d="M5 6v4"/><path d="M19 14v4"/><path d="M10 2v2"/><path d="M7 8H3"/><path d="M21 16h-4"/><path d="M11 3H9"/></svg>'
                    f'Course auto-selected: A matching course was registered in the folder</span>',
                    unsafe_allow_html=True
                )
            else:
                st.empty()

        # Two auto-width columns + spacer, vertically centered
        col_folder_info, col_change_btn, col_spacer = st.columns(
            [1, 1, 1], vertical_alignment="center", gap="small"
        )

        with col_folder_info:
            st.markdown(
                f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                f'{"Added Folder:" if pending_folder else "Folder:"}</span>'  # audit-ignore: folder_name is a local filesystem path
                f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">{SVG_FOLDER_YELLOW if pending_folder else ""}{folder_name}</span>',
                unsafe_allow_html=True,
            )
        with col_change_btn:
            btn_label = 'Change Folder' if pending_folder else 'Select Folder'
            if st.button(btn_label, key="btn_change_folder"):
                _select_sync_folder_lazy()
                st.rerun()
        with col_spacer:
            st.empty()

        # Check for return value from dialog
        if "sync_selected_return_id" in st.session_state:
            ret_id = st.session_state["sync_selected_return_id"]
            # Consume it
            del st.session_state["sync_selected_return_id"]
            
            # User manually confirmed a course - clear auto-detect flag
            st.session_state.pop('sync_auto_detected_course', None)

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

            # Persist only to the inline-form temp state. Do NOT mutate
            # st.session_state['sync_pairs'][editing_idx] here - the pair's
            # original course_id is the signature used by
            # update_pair_by_signature on Confirm. Mutating it in-memory
            # poisoned the signature lookup, so the disk-side replace
            # silently no-op'd and the pair reverted to the old course on
            # the next reload.
            st.session_state['sync_selected_course_id'] = selected_course_id
            st.rerun()

        # Pre-compute manifest rebind state so the name-mismatch warning can be
        # suppressed when the more informative rebind notice will already be shown.
        _manifest_rebind_needed = False
        _bound_name = _new_name = None
        if pending_folder and selected_course_id:
            _bound_id = SyncManager.peek_bound_course_id(pending_folder)
            if _bound_id is not None and _bound_id != selected_course_id:
                _manifest_rebind_needed = True
                _bound_name = friendly_course_name(
                    SyncManager.peek_bound_course_name(pending_folder) or f"course #{_bound_id}"
                )
                _new_name = friendly_course_name(selected_course_name or f"course #{selected_course_id}")

        # --- Warnings ---
        is_duplicate_pair = False
        # Mismatch warning
        if selected_course_name and pending_folder:
            # Determine if this is the original course selection
            is_same_as_original = False
            # By link, like the save below - an index here would compare against
            # whatever pair now sits at that position and suppress (or invent) the
            # course/folder mismatch warning for the wrong pair.
            if _edit_pair is not None:
                 if _edit_pair.get('course_id') == selected_course_id and _edit_pair.get('local_folder') == pending_folder:
                     is_same_as_original = True

            folder_lower = folder_name.lower()
            course_lower = selected_course_name.lower()
            course_words = [w for w in course_lower.replace('(', ' ').replace(')', ' ').replace('-', ' ').replace('_', ' ').split() if len(w) >= 2]
            folder_words = [w for w in folder_lower.replace('(', ' ').replace(')', ' ').replace('-', ' ').replace('_', ' ').split() if len(w) >= 2]
            has_match = (
                any(cw in folder_lower for cw in course_words)
                or any(fw in course_lower for fw in folder_words)
            )

            # Suppress name-mismatch when the rebind notice is already shown - it
            # conveys the same information (wrong course) with more detail.
            if not has_match and not is_same_as_original and not _manifest_rebind_needed:
                from ui.amber_notice import render_amber_notice
                render_amber_notice(
                    "The folder name doesn't seem to match the selected course.",
                    detail="Are you sure this is the correct folder for this course?",
                )

            # Duplicate pair detection
            existing = st.session_state.get('sync_pairs', [])
            candidates = existing
            if _edit_pair is not None:
                # Exclude the pair being edited so it cannot be reported as a
                # duplicate of ITSELF - by identity, not by index. Excluding a
                # position meant that once the list shifted the wrong pair was
                # excluded, which both hides a real duplicate and can block a
                # legitimate save with "this pair is already on your sync list".
                candidates = [p for p in existing if p is not _edit_pair]

            for cid, cname in course_names.items():
                if cname == selected_course_name:
                    if any(p['local_folder'] == pending_folder and p['course_id'] == cid for p in candidates):
                        is_duplicate_pair = True
                        from ui.amber_notice import render_amber_notice
                        render_amber_notice(
                            'This folder is already on your sync list for this course.',
                            detail='To update its settings, use the edit button on the existing pair instead.',
                        )
                    break

        # --- Manifest binding notice ---
        # Shown when the chosen folder already has a .canvas_sync.db bound to
        # a DIFFERENT course (e.g. user re-directed an existing pair).
        if _manifest_rebind_needed:
            st.html(f"""
            <div style="
                background: rgba(234, 179, 8, 0.12);
                border: 1px solid rgba(234, 179, 8, 0.55);
                border-radius: 6px;
                padding: 10px 14px;
                margin: 4px 0 8px 0;
                font-size: 0.9rem;
                line-height: 1.5;
            ">
                <div style="color:#fbbf24; font-weight:700; margin-bottom:3px;">
                    🔗 This folder is already linked to a different course
                </div>
                <div style="color:#fde68a;">
                    <b>Currently linked to:</b> <span style="color:white;">{esc(_bound_name)}</span><br>
                    <b>You've selected:</b> <span style="color:white;">{esc(_new_name)}</span>
                </div>
                <div style="color:rgba(253,230,138,0.75); margin-top:5px; font-size:0.85rem;">
                    Clicking <b>{"Save Changes" if editing_idx is not None else "Confirm and Add"}</b> will re-link this folder to the new course. Your files on disk won't be deleted.<br>
                    If you meant to sync to a different course, change the course with the <b>Select Course</b> button above.
                </div>
            </div>
            """)

        # Error container Relocated HERE (Below dropdown/warnings, Above buttons)
        error_container = st.empty()

        # (3) Confirm + Cancel - compact, side-by-side, cancel has red tint.
        # In bulk mode a "Skip" button appears between them (still ONE child - a
        # single horizontal block - so the form's child count is unchanged).
        if _bulk_active:
            col_cancel, col_skip, col_add, _ = st.columns([1.2, 1, 1.6, 6.2])
        else:
            col_cancel, col_add, _ = st.columns([1, 1.5, 7.5])
            col_skip = None

        with col_cancel:
            _cancel_label = 'Cancel all' if _bulk_active else 'Cancel'
            _cancel_help = ("Stop the bulk add and discard the remaining folders."
                            if _bulk_active else None)
            if st.button(_cancel_label, key="cancel_pair",
                         use_container_width=True, help=_cancel_help):
                _clear_bulk_state()
                st.session_state['pending_sync_folder'] = None
                st.session_state.pop('editing_pair_idx', None)
                st.session_state.pop('editing_pair_sig', None)
                st.session_state.pop('_prev_course_search', None)
                st.session_state.pop('sync_selected_course_id', None)  # Prevent stale pre-selection on re-open
                st.session_state.pop('sync_auto_detected_course', None)
                st.rerun()

        if col_skip is not None:
            with col_skip:
                _skip_label = 'Skip' if _bulk_queue_remaining else 'Skip & finish'
                if st.button(_skip_label, key="bulk_skip_pair",
                             use_container_width=True,
                             help="Don't add this folder; go to the next one."):
                    _advance_bulk()
                    st.session_state.pop('_prev_course_search', None)
                    st.rerun(scope="app")

        with col_add:
            is_folder_selected = bool(pending_folder)
            is_course_selected = bool(selected_course_id)
            is_edit_mode = editing_idx is not None

            has_changes = True
            if is_edit_mode and _edit_pair is not None:
                has_changes = (
                    _edit_pair.get('course_id') != selected_course_id
                    or _edit_pair.get('local_folder') != pending_folder
                )

            if is_edit_mode:
                btn_label = "Save Changes"
            elif _bulk_active:
                btn_label = "Add & next" if _bulk_queue_remaining else "Add & finish"
            else:
                btn_label = "Confirm and Add"

            if is_duplicate_pair:
                btn_disabled = True
                btn_tooltip = "This pair is already on your sync list - cancel to go back."
            elif is_folder_selected and is_course_selected:
                if is_edit_mode and not has_changes:
                    btn_disabled = True
                    btn_tooltip = None
                else:
                    btn_disabled = False
                    btn_tooltip = None
            elif is_folder_selected and not is_course_selected:
                btn_disabled = True
                btn_tooltip = "Select a course to continue."
            elif not is_folder_selected and is_course_selected:
                btn_disabled = True
                btn_tooltip = "Select a folder to continue."
            else:
                btn_disabled = True
                btn_tooltip = "Select a Canvas course, and its corresponding course folder on your pc to continue."

            if st.button(btn_label, key="confirm_pair",
                         type="primary", use_container_width=True,
                         disabled=btn_disabled, help=btn_tooltip):
                if not pending_folder:
                    error_msg = 'Please select a folder.'
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
                elif selected_course_id and selected_course_id in course_names:
                    # Direct lookup - no need to scan by name, the ID is
                    # authoritative from the course selector.

                    # If the folder's manifest was bound to a different
                    # course, wipe it now so the next sync starts clean
                    # against the newly chosen course.
                    if _manifest_rebind_needed:
                        SyncManager.reset_folder_binding(pending_folder)

                    new_pair = {
                        'local_folder': pending_folder,
                        'course_id': selected_course_id,
                        'course_name': course_names[selected_course_id],
                        'last_synced': None,
                    }

                    # Check if we are updating or adding. In EDIT mode the pair
                    # is the one this form was opened on, found by link - never
                    # "whatever is at that index now". If it is gone (removed from
                    # another row while this form was open) we must NOT fall
                    # through to the append branch: that silently created a
                    # duplicate pair out of an edit.
                    if is_edit_mode and _edit_pair is None:
                        error_container.markdown(
                            "<div style=\"padding: 8px 12px; margin-bottom: 10px; "
                            "background-color: rgba(255, 75, 75, 0.15); color: #ff4b4b; "
                            "border: 1px solid rgba(255, 75, 75, 0.2); border-radius: 4px; "
                            "font-size: 0.9em; font-weight: 500;\">"
                            "\u26a0\ufe0f This pair was removed from the sync list while you "
                            "were editing it, so there is nothing to save. Cancel to go "
                            "back, then add it again if you still want it.</div>",
                            unsafe_allow_html=True)
                        st.stop()
                    if _edit_pair is not None:
                        # Update existing
                        old_pair = _edit_pair
                        old_sig = {'course_id': old_pair.get('course_id'), 'local_folder': old_pair.get('local_folder')}
                        if old_pair.get('course_id') == selected_course_id:
                            new_pair['last_synced'] = old_pair.get('last_synced')
                        _update_pair_by_signature_lazy(old_sig, new_pair)
                        # If the course/folder link actually changed, carry any
                        # standalone saved pair's NAME to the new link so an
                        # inline re-link relocates a named pair like the hub does.
                        if (old_pair.get('course_id'), old_pair.get('local_folder')) != \
                                (new_pair.get('course_id'), new_pair.get('local_folder')):
                            _retarget_saved_pair_lazy(
                                old_pair.get('course_id'),
                                old_pair.get('local_folder'),
                                new_pair)
                    else:
                        # Append new
                        _add_pair_lazy(new_pair)

                    st.session_state.pop('_prev_course_search', None)
                    st.session_state.pop('sync_auto_detected_course', None)
                    if _bulk_active:
                        # Advance to the next queued folder (or close if done).
                        # _advance_bulk owns pending_sync_folder / selection state.
                        _advance_bulk()
                    else:
                        st.session_state['pending_sync_folder'] = None
                        st.session_state.pop('editing_pair_idx', None)
                        st.session_state.pop('editing_pair_sig', None)
                    st.rerun(scope="app")
                elif selected_course_id and selected_course_id not in course_names:
                    # Course exists in saved pair but was archived/removed from Canvas
                    error_msg = 'This course is no longer available in Canvas. Please select a different course.'
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
                else:
                    # No course selected at all
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

        # This form renders at an index a sync-list row occupied, so it must
        # present the same number of children as every other occupant of that
        # slot - see shared.components.pad_slot_children for the measurements
        # in both directions. The form's own four are: course row, folder row,
        # the hidden notice slot, and the button row - plus the bulk banner as a
        # fifth when a multi-folder add is in progress.
        pad_slot_children(5 if _bulk_active else 4)


# ===================================================================