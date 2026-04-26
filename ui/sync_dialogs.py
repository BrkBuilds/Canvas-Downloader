"""
ui.sync_dialogs — Sync history, filetype selector, ignored files, course settings.

Extracted from ``sync_ui.py`` (Phase 5).

Contains:
  - ``render_sync_history()`` — sync history expander
  - ``render_filetype_selector()`` — filetype filter for review screen
  - ``show_course_ignored_files()`` — per-course ignored files dialog
  - ``select_course_dialog_inner()`` — course selection dialog
  - ``render_pending_folder_ui()`` — pending folder pairing UI
"""

from __future__ import annotations

import os
import urllib.parse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import streamlit as st

import theme
from sync_manager import SyncHistoryManager, get_file_icon
from ui_helpers import (
    esc,
    friendly_course_name,
)

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




def show_course_ignored_files(course_name, course_id, course_data):
    """Per-course ignored files dialog — Smart Select tag-button architecture.

    Uses the Zero-Width Space Hack for a custom dialog header with Base64 icon.
    Implements the same tag-button filetype selector as the Sync Review page.
    """
    from sync_manager import format_file_size
    from ui_helpers import get_base64_image

    @st.dialog("\u200b", width="large")
    def _dialog():
        sm = course_data['sync_manager']
        files = sm.get_ignored_files()
        prefix = f"cign_{course_id}"

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
            div[class*="st-key-{prefix}_restore"] button p::before {{
                content: "" !important; display: inline-block !important;
                width: 14px !important; height: 14px !important;
                background-image: url('data:image/png;base64,{b64_restore}') !important;
                background-size: contain !important; background-repeat: no-repeat !important;
                background-position: center !important; flex-shrink: 0 !important;
                margin-right: 8px !important; 
                vertical-align: middle !important;
                position: relative !important;
                top: -2px !important;
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
                        safe_len = min(len(all_exts_sorted), 90)
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
                            for k in all_keys:
                                st.session_state[k] = True
                        st.button("Select All", key=f"{prefix}_btn_sa", use_container_width=True, on_click=_select_all)
                    with col_clr:
                        def _deselect_all():
                            for k in all_keys:
                                st.session_state[k] = False
                        st.button("Deselect All", key=f"{prefix}_btn_da", use_container_width=True, on_click=_deselect_all)

        # ── 4. File list with extension + size tags ───────────────────
        with st.container(height=400, border=True, key=f"{prefix}_filelist"):
            for key, f in all_file_tuples:
                _disp_raw = urllib.parse.unquote_plus(f.canvas_filename)
                _name, _ext = os.path.splitext(_disp_raw)
                _ext_clean = f" ~{_ext[1:].upper()}~" if _ext else ""
                _size_clean = ""
                if f.original_size and f.original_size > 0:
                    _size_clean = f" `{format_file_size(f.original_size)}`"
                with st.container(key=f"ign_row_{course_id}_{f.canvas_file_id}"):
                    st.checkbox(f"{_name}{_ext_clean}{_size_clean}", key=key)

        # ── 5. Count + success feedback ───────────────────────────────
        checked_count = sum(1 for k in all_keys if st.session_state.get(k, False))

        if st.session_state.get(f"{prefix}_success"):
            st.success(st.session_state.pop(f"{prefix}_success"))

        # ── 6. Dynamic button text ────────────────────────────────────
        if checked_count == 0:
            btn_text = "Restore files"
        elif checked_count == 1:
            btn_text = "Restore 1 file"
        else:
            btn_text = f"Restore {checked_count} files"

        # ── 7. Action buttons (Cancel left, Action right) ─────────────
        col_cancel, col_restore = st.columns([1, 1])
        with col_cancel:
            if st.button("Close", type="secondary", use_container_width=True, key=f"{prefix}_close"):
                for k in all_keys:
                    st.session_state.pop(k, None)
                st.rerun(scope="app")

        with col_restore:
            def _on_restore_course():
                to_restore = [
                    f.canvas_file_id for f in files
                    if st.session_state.get(f"{prefix}_{f.canvas_file_id}")
                ]
                if to_restore:
                    sm.bulk_restore_files(to_restore)
                    fw = 'file' if len(to_restore) == 1 else 'files'
                    st.session_state[f"{prefix}_success"] = (
                        f"Successfully restored {len(to_restore)} {fw}! "
                        f"They will appear in your next Sync Review."
                    )
                    for fid in to_restore:
                        st.session_state.pop(f"{prefix}_{fid}", None)

            btn_help = "Select files to restore" if checked_count == 0 else "Remove selected files from the ignored list so they are included in future syncs"
            st.button(
                btn_text, type="primary", disabled=(checked_count == 0),
                use_container_width=True, key=f"{prefix}_restore",
                on_click=_on_restore_course,
                help=btn_help,
            )

    _dialog()



@st.dialog("Select Course to sync", width="large")
def select_course_dialog_inner(courses, current_selected_id, ):
    from ui.course_selector import inject_course_selector_css, render_cbs_filters, render_course_list, render_favorites_pill

    # Static CSS: scroll-container + compact dialog spacing
    st.html("""
        <style>
            /* Scroll container: border=True gives reliable st-key-* class.
               Strip the native border here. height:auto lets the list shrink
               to fit short Favorites lists; max-height caps growth so the
               dialog never overflows the viewport — All Courses scrolls
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
               on top would cause them to overlap. */
            div[data-testid="stVerticalBlock"]:has(div[class*="st-key-sync_d_chk_"]) {
                gap: 1rem !important;
            }
            /* Reduce dialog scrollable body top padding so content sits closer
               to the dialog title bar. */
            div[role="dialog"] [data-testid="stDialogScrollableBody"] {
                padding-top: 0.25rem !important;
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
        st.warning('No courses found.')
        if st.button("Close"):
             st.rerun(scope="app")
        return

    # 2. CBS Filters (centralized)
    filtered_courses = render_cbs_filters(visible_courses, "sync_d")

    # Initialize single-select state
    if "sync_d_selected_id" not in st.session_state or st.session_state.get("sync_d_selected_id") is None:
        st.session_state["sync_d_selected_id"] = current_selected_id

    st.html('<hr style="margin-top: 2px; margin-bottom: 4px; border-color: rgba(255,255,255,0.1);" />')

    # 3. Course list (centralized single-select)
    # border=True required so the st-key-* CSS class is reliably emitted
    # (CLAUDE.md "Border Strip" rule). The border is stripped in CSS above.
    with st.container(border=True, key="course_list_scroll_container"):
        render_course_list(filtered_courses, "sync_d", multi_select=False,
                           first_item_top_offset="-10px")

    # 4. Confirm
    st.html('<hr style="margin-top: 2px; margin-bottom: 4px; border-color: rgba(255,255,255,0.1);" />')
    if st.button("Confirm Selection", key="sync_confirm_btn", type="primary", use_container_width=True):
        st.session_state["sync_selected_return_id"] = st.session_state["sync_d_selected_id"]
        st.rerun(scope="app")


def render_pending_folder_ui(courses, course_names, course_options, ):
    """Inline UI shown while adding/editing a sync-pair — unified card."""
    pending_folder = st.session_state['pending_sync_folder']
    folder_name = Path(pending_folder).name
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
             btn_label = 'Change Course'
        else:
             btn_label = 'Select Course'
        
        # Two columns like folder row: [1, 1, 1] to keep it left-aligned
        # REVISED: [1, 1, 1] — relying on CSS flex auto-width to handle content size
        col_c_info, col_c_btn, col_c_spacer = st.columns([1, 1, 1], vertical_alignment="center", gap="small")
        
        with col_c_info:
            st.markdown(
                f'<span style="color:#8ad;font-weight:500;margin-right:8px;font-size:0.95rem;white-space:nowrap;">'
                f'{"Course: "}</span>'
                f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">{current_disp}</span>',
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
                f'{"Added Folder:"}</span>'  # audit-ignore: folder_name is a local filesystem path
                f'<span style="color:{theme.WHITE};font-weight:600;font-size:0.95rem;white-space:nowrap;">📁 {folder_name}</span>',
                unsafe_allow_html=True,
            )
        with col_change_btn:
            if st.button('Change Folder', key="btn_change_folder"):
                _select_sync_folder_lazy()
                st.rerun()
        with col_spacer:
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
        col_cancel, col_add, _ = st.columns([1, 1.5, 7.5])
        
        with col_cancel:
            if st.button('Cancel', key="cancel_pair",
                         use_container_width=True):
                st.session_state['pending_sync_folder'] = None
                st.session_state.pop('editing_pair_idx', None)
                st.session_state.pop('_prev_course_search', None)
                st.rerun()

        with col_add:
            if st.button('Confirm and Add', key="confirm_pair",
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


# ===================================================================