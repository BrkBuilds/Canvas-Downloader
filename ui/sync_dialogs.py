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

import os
import urllib.parse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import streamlit as st

import theme
from ui_shared import SVG_FOLDER_YELLOW
from sync_manager import SyncHistoryManager, SyncManager
from ui_helpers import (
    esc,
    friendly_course_name,
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
    """Open native folder picker, store result, and auto-detect bound course."""
    from ui_helpers import native_folder_picker
    import streamlit as st
    folder_path = native_folder_picker(initial_dir=st.session_state.get('pending_sync_folder') or None)
    if folder_path:
        st.session_state['pending_sync_folder'] = folder_path
        # --- Auto-detect course from manifest ---
        _auto_detect_course_from_manifest(folder_path)

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

def _add_pair_lazy(pair):
    from sync.persistence import add_pair
    add_pair(pair)

def _remove_pairs_by_signature_lazy(sigs):
    from sync.persistence import remove_pairs_by_signature
    remove_pairs_by_signature(sigs)



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




def show_course_ignored_files(course_name, course_id, course_data):
    """Per-course ignored files dialog - Smart Select tag-button architecture.

    Uses the Zero-Width Space Hack for a custom dialog header with Base64 icon.
    Implements the same tag-button filetype selector as the Sync Review page.
    """
    from sync_manager import format_file_size
    from ui_helpers import get_base64_image

    # on_dismiss="rerun": restoring files is an on_click callback that mutates
    # the manifest and invalidates _ignored_files_cache via a fragment rerun, so
    # the main-page card's "Ignored Files (N)" count + disabled state go stale.
    # Backdrop/ESC dismissal would reveal that stale render until the next click;
    # "rerun" forces a full app rerun so the card recomputes from fresh data.
    @st.dialog("\u200b", width="large", on_dismiss="rerun")
    def _dialog():
        sm = course_data['sync_manager']
        files = sm.get_ignored_files()
        prefix = f"cign_{course_id}"

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
                    if p and p.exists():
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
        bottom_padding = "14px" if is_expanded else "4px"
        filelist_height = 340 if is_expanded else 480

        _css = f"""<style>
            /* -- Dialog compact gaps -- */
            div[role="dialog"] [data-testid="stDialogScrollableBody"] > div[data-testid="stVerticalBlock"] {{
                gap: 0.25rem !important;
            }}
            /* Smart Select outer card */
            div[class*="st-key-{prefix}_filter_box"] {{
                background: rgba(255,255,255,0.03) !important;
                border: 1px solid rgba(255,255,255,0.1) !important;
                border-radius: 10px !important;
                padding: 4px 14px {bottom_padding} 14px !important;
                margin-top: -10px !important;
                margin-bottom: -10px !important;
            }}
            div[class*="st-key-{prefix}_filter_box"] > div[data-testid="stVerticalBlockBorderWrapper"] {{
                border: none !important; padding: 0 !important;
            }}
            div[class*="st-key-{prefix}_filter_box"] div[data-testid="stVerticalBlock"] {{
                gap: 0.1rem !important;
            }}
            /* -- Custom Chevron Toggle -- */
            div[class*="st-key-{prefix}_chevron"] {{
                margin: 0 !important;
            }}
            div[class*="st-key-{prefix}_chevron"] label[data-baseweb="checkbox"] {{
                padding: 2px 0 !important;
                margin: 0 !important;
                cursor: pointer !important;
                gap: 0 !important;
            }}
            div[class*="st-key-{prefix}_chevron"] label[data-baseweb="checkbox"] > span:first-child {{
                display: none !important;
            }}
            div[class*="st-key-{prefix}_chevron"] label[data-baseweb="checkbox"] > div {{
                margin-left: 0 !important;
            }}
            div[class*="st-key-{prefix}_chevron"] label p {{
                font-size: 1.05rem !important;
                font-weight: 700 !important;
                color: #fff !important;
                margin: 0 !important;
            }}
            div[class*="st-key-{prefix}_chevron"] label p::before {{
                content: "▸" !important;
                display: inline-block !important;
                font-size: 1.25rem !important;
                margin-right: 12px !important;
                color: rgba(255,255,255,0.5) !important;
            }}
            div[class*="st-key-{prefix}_chevron"]:has(input:checked) label p::before {{
                transform: rotate(90deg) !important;
            }}
            /* Filetypes flex */
            div[class*="st-key-{prefix}_ft_flex"] {{
                border: none !important; background: transparent !important;
                box-shadow: none !important; padding: 0 !important; margin-top: -6px !important;
            }}
            div[class*="st-key-{prefix}_ft_flex"] > div[data-testid="stVerticalBlockBorderWrapper"] {{
                border: none !important; padding: 0 !important;
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
            div[class*="st-key-{prefix}_bulk_btns"] > div[data-testid="stVerticalBlockBorderWrapper"] {{
                border: none !important; padding: 0 !important;
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
            /* Explicit disabled state for Restore button */
            div[data-testid="stDialog"] div[class*="st-key-{prefix}_restore"] button:disabled,
            div[data-testid="stDialog"] div[class*="st-key-{prefix}_restore"] button[disabled] {{
                background-color: rgba(255, 255, 255, 0.075) !important;
                border: 1px solid rgba(255, 255, 255, 0.075) !important;
                color: rgba(255, 255, 255, 0.2) !important;
                box-shadow: none !important;
            }}
            /* Dim the icon when disabled */
            div[data-testid="stDialog"] div[class*="st-key-{prefix}_restore"] button:disabled p::before,
            div[data-testid="stDialog"] div[class*="st-key-{prefix}_restore"] button[disabled] p::before {{
                opacity: 0.4 !important;
                filter: grayscale(100%) !important;
            }}
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
            /* Strip the inner border wrapper Streamlit adds for keyed containers */
            div[data-testid="stDialog"] div[class*="st-key-ign_row_"] > div[data-testid="stVerticalBlockBorderWrapper"] {{
                border: none !important;
                padding: 0 !important;
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
        st.html(f"""
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:0;margin-top:-70px;">
            <img src="data:image/svg+xml;base64,{b64_icon}"
                 style="width:32px;height:32px;filter:brightness(0) invert(1) opacity(0.9);" />
            <div style="margin:0;padding:0;font-size:1.75rem;font-weight:600;color:white;">
                Ignored Files
            </div>
        </div>
        <div style="color:rgba(255,255,255,0.9);font-size:1rem;font-weight:600;margin-top:4px;">
            Course: <span style="font-weight:400;color:rgba(255,255,255,0.9);">{esc(course_name)}</span>
        </div>
        <hr style="border:none;border-top:1px solid rgba(255,255,255,0.2);margin-top: 10px;" />
        """)

        # ── 2. Help text ──────────────────────────────────────────────
        st.html("<div style='font-size:0.85rem;color:rgba(255,255,255,0.5);margin-top:-10px;margin-bottom:10px;'>Select files to restore & remove from ignored list. Restored files will appear in your next sync run for this course.</div>")

        # -- 3. Smart Select Card (Collapsible chevron) -----------------
        with st.container(border=True, key=f"{prefix}_filter_box"):
            # Custom chevron toggle (checkbox styled as rotating arrow header)
            chevron_key = f"{prefix}_chevron"
            if chevron_key not in st.session_state:
                st.session_state[chevron_key] = False  # start collapsed
            st.checkbox("Smart Select", key=chevron_key)

            if st.session_state[chevron_key]:
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
        if all_file_tuples or pan_ignored:
            with st.container(height=filelist_height, border=True, key=f"{prefix}_filelist"):
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
                        _pan_contract = {
                            'output_mp4': st.session_state.get('persistent_pan_out_mp4', False),
                            'output_mp3': st.session_state.get('persistent_pan_out_mp3', False),
                            'output_txt': st.session_state.get('persistent_pan_out_txt', False),
                            'output_srt': st.session_state.get('persistent_pan_out_srt', False),
                            'layout': st.session_state.get('persistent_pan_layout', 'match'),
                        }
                    _pan_settings = _compose_pan(_pan_contract)
                    _default_kinds = []
                    if _pan_settings.get("output_mp4"):
                        _default_kinds.append("mp4")
                    if _pan_settings.get("output_mp3"):
                        _default_kinds.append("mp3")
                    if _pan_settings.get("output_txt"):
                        _default_kinds.append("txt")
                    if _pan_settings.get("output_srt"):
                        _default_kinds.append("srt")

                    for vid, title in pan_ignored.items():
                        _psz = _pan_rec_size(vid)
                        _psize = f" `{format_file_size(_psz)}`" if _psz > 0 else ""

                        # Show what is missing/actionable (i.e. configured kinds minus what is already on disk)
                        _existing_kinds = []
                        for _k, _rel in _pan_manifest.get(vid, {}).items():
                            try:
                                _p = (_pan_root / _rel) if _pan_root else None
                                if _p and _p.exists():
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

            btn_help = "Select items to restore" if checked_count == 0 else "Remove selected items from the ignored list so they are included in future syncs"
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
            /* Reduce dialog scrollable body top padding so content sits closer
               to the dialog title bar. */
            div[role="dialog"] [data-testid="stDialogScrollableBody"] {
                padding-top: 0.25rem !important;
            }
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
    pending_folder = st.session_state.get('pending_sync_folder', "")
    folder_name = Path(pending_folder).name if pending_folder else "Select Course Folder →"
    editing_idx = st.session_state.get('editing_pair_idx')

    # (1) Everything inside one bordered container
    with st.container(border=True, key="edit_form_container"):
        st.html("""<style>
            /* Reduce vertical margins between elements inside the inline edit form */
            .st-key-edit_form_container > div[data-testid="stVerticalBlock"] {
                gap: 0.25rem !important;
            }
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-edit_form_container) {
                padding: 12px 16px !important;
            }
        </style>""")
        # (3) CSS for cancel button red styling (Moved to render_sync_step1 for global scope/no flash)

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
        col_c_info, col_c_btn, col_c_spacer = st.columns([1, 1, 1], vertical_alignment="center", gap="small")

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
                select_course_dialog_inner(courses, selected_course_id)
        
        with col_c_spacer:
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

        # --- Auto-detection info notice ---
        if st.session_state.get('sync_auto_detected_course') and selected_course_id:
            from ui.amber_notice import render_info_notice
            render_info_notice(
                f"Canvas Downloader automatically matched this folder to <span style='color: white; margin-left: 2px;'>{esc(selected_course_name or 'its corresponding course')}</span>",
                detail="If you think the match was wrong, click the \"Change Course\" button above to relink it.",
                margin="4px 0 10px 0",
                allow_html=True,
                tooltip="All courses downloaded with Canvas Downloader save a tiny hidden file with the course code inside - we use this to match the canvas course to the course folder."
            )

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
            if editing_idx is not None and 0 <= editing_idx < len(st.session_state.get('sync_pairs', [])):
                 original_pair = st.session_state['sync_pairs'][editing_idx]
                 if original_pair.get('course_id') == selected_course_id and original_pair.get('local_folder') == pending_folder:
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
            if editing_idx is not None:
                # Filter out the pairing being edited so we don't warn against itself
                candidates = [p for i, p in enumerate(existing) if i != editing_idx]

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

        # (3) Confirm + Cancel - compact, side-by-side, cancel has red tint
        # Made columns narrower (10% each) to reduce button width significantly (per user request)
        col_cancel, col_add, _ = st.columns([1, 1.5, 7.5])
        
        with col_cancel:
            if st.button('Cancel', key="cancel_pair",
                         use_container_width=True):
                st.session_state['pending_sync_folder'] = None
                st.session_state.pop('editing_pair_idx', None)
                st.session_state.pop('_prev_course_search', None)
                st.session_state.pop('sync_selected_course_id', None)  # Prevent stale pre-selection on re-open
                st.session_state.pop('sync_auto_detected_course', None)
                st.rerun()

        with col_add:
            is_folder_selected = bool(pending_folder)
            is_course_selected = bool(selected_course_id)
            is_edit_mode = editing_idx is not None

            has_changes = True
            if is_edit_mode and 0 <= editing_idx < len(st.session_state.get('sync_pairs', [])):
                _orig = st.session_state['sync_pairs'][editing_idx]
                has_changes = (
                    _orig.get('course_id') != selected_course_id
                    or _orig.get('local_folder') != pending_folder
                )

            btn_label = "Save Changes" if is_edit_mode else "Confirm and Add"

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
                    st.session_state.pop('sync_auto_detected_course', None)
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


# ===================================================================