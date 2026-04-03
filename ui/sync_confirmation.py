"""
ui.sync_confirmation — Sync confirmation dialog.

Extracted from ``sync_ui.py`` (Phase 5).
Strict physical move — NO logic changes.

Contains:
  - ``show_sync_confirmation_inner()`` — confirmation dialog body
    (the @st.dialog wrapper stays in sync_ui.py)
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import streamlit as st

import theme
from sync_manager import SyncManager, get_file_icon
from ui_helpers import (
    esc,
    render_sync_wizard,
    friendly_course_name,
    format_file_size,
)

# ---- Confirmation dialog ----

def show_sync_confirmation_inner(sync_selections, count, size, folders, avail_mb, total_mb, target_folder, total_bytes):
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
        for f in s['updates']:
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
        f'color: {theme.WHITE} !important;'
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
        f'details summary:hover {{ color: {theme.WHITE}; }}'
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
        f'color: {theme.WHITE};'
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
        f'details[open] summary .arrow-icon::before {{ content: "▾"; color: {theme.WHITE}; }}'
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
        f'color: {theme.WHITE} !important;'
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

            # Load each course's individual sync_contract from SQLite
            for _s in sync_selections:
                try:
                    _p = _s['res_data']['pair']
                    _sm = SyncManager(_p['local_folder'], _p['course_id'], _p.get('course_name', ''))
                    _raw = _sm._load_metadata('sync_contract')
                    _s['res_data']['contract'] = json.loads(_raw) if _raw else {}
                except Exception:
                    _s['res_data']['contract'] = {}

            # Set safe persistent_convert_* defaults (per-course contracts are authoritative)
            _CONVERT_KEYS_HANDOFF = ['convert_zip', 'convert_pptx', 'convert_word', 'convert_excel',
                                      'convert_html', 'convert_code', 'convert_urls', 'convert_video']
            for k in _CONVERT_KEYS_HANDOFF:
                st.session_state[f'persistent_{k}'] = False

            st.rerun()
    with col_no:
        if st.button("No, Go back", use_container_width=True, key="cancel_sync_dialog_btn"):
            st.rerun()

