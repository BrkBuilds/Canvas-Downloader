"""
ui.sync_confirmation - Sync confirmation dialog.

Extracted from ``sync_ui.py`` (Phase 5).
Strict physical move - NO logic changes.

Contains:
  - ``show_sync_confirmation_inner()`` - confirmation dialog body
    (the @st.dialog wrapper stays in sync_ui.py)
"""

from __future__ import annotations

import json
import os
import urllib.parse
import streamlit as st

import theme
from sync_manager import SyncManager
from ui_helpers import (
    friendly_course_name,
    format_file_size,
    esc,
)
from ui_shared import _FILETYPE_SVGS, _FILETYPE_SVG_DEFAULT

# ---- Confirmation dialog ----

def show_sync_confirmation_inner(sync_selections, count, size, folders, avail_mb, _total_mb, _target_folder, total_bytes):
    # --- Data Collection for Dropdowns ---
    file_items = []
    folder_set = set()
    modified_update_count = sum(len(s.get('updates_modified', [])) for s in sync_selections)
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

        def _file_li(raw_name, display_name, size_bytes):
            ext = os.path.splitext(raw_name)[1].lower().lstrip('.')
            fname = os.path.splitext(get_friendly_name(display_name or raw_name))[0]
            icon_url = _FILETYPE_SVGS.get(ext, _FILETYPE_SVG_DEFAULT)
            ext_badge = (
                f"<span class='li-ext-badge'>{esc(ext.upper())}</span>"
            ) if ext else ""
            size_badge = f"<span class='li-size-badge'>{format_file_size(size_bytes)}</span>"
            return (
                f"<li>"
                f'<img class="li-img" src="{icon_url}" alt="{esc(ext)}"/>'
                f"<span class='li-text'>{esc(fname)}</span>"
                f"{ext_badge}"
                f"{size_badge}"
                f"</li>"
            )

        for f in s['new']:
            file_items.append(_file_li(f.filename, f.display_name or f.filename, f.size))
        for f in s['updates']:
            file_items.append(_file_li(f.filename, f.display_name or f.filename, f.size))
        for f in s['redownload']:
            file_items.append(_file_li(f.canvas_filename, f.canvas_filename, f.original_size))
    
    # Tight HTML structure - NO whitespace
    file_list_html = f"<ul style='margin:0 !important;padding:0 !important;list-style-type:none !important;display:block !important;'>{''.join(sorted(file_items))}</ul>"
    sorted_folders = sorted(list(folder_set))
    _folder_lis = "".join(
        "<li><span class='li-icon'>📁</span><span class='li-text'>" + esc(p) + "</span></li>"
        for p in sorted_folders
    )
    folder_list_html = f"<ul style='margin:0 !important;padding:0 !important;list-style-type:none !important;display:block !important;'>{_folder_lis}</ul>"
    
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
    elif len(folder_set) == 1:
        # Single folder - static row showing friendly name
        _sf0 = esc(sorted_folders[0])
        dest_html = (
            f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">'
            f'<div style="font-weight: 600; color: #e2e8f0; white-space: nowrap;">📁 Destination:</div>'
            f'<div title="{_sf0}" style="text-align: right; font-weight: 600; color: #f8fafc; max-width: 60%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">'
            f'{_sf0}'
            f'</div>'
            f'</div>'
        )
    else:
        # Defensive: empty folder_set should never happen (sync_selections
        # are guaranteed non-empty), but guard against IndexError.
        dest_html = ""

    _css_block = (
        f'<style>'
        f'/* Override modal styles */'
        f'div[data-testid="stDialog"] > div[data-testid="stAppViewBlockContainer"] > div > [data-testid="stVerticalBlock"] {{'
        f'padding: 25px !important;'
        f'gap: 0 !important;'
        f'}}'
        f'div[data-testid="stDialog"] h2 {{'
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
        f'color: #e2e8f0;'
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
        f'div[data-testid="stDialog"] .stButton > button {{'
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
        f'.li-img {{'
        f'width: 16px !important;'
        f'height: 16px !important;'
        f'flex-shrink: 0 !important;'
        f'margin-right: 2px !important;'
        f'}}'
        f'.li-text {{'
        f'word-break: break-word !important;'
        f'color: #f1f5f9 !important;'
        f'}}'
        f'.li-ext-badge {{'
        f'font-size: 0.65rem !important;'
        f'font-weight: 700 !important;'
        f'letter-spacing: 0.4px !important;'
        f'color: #bababa !important;'
        f'background: rgba(255,255,255,0.08) !important;'
        f'border-radius: 3px !important;'
        f'padding: 1px 5px !important;'
        f'white-space: nowrap !important;'
        f'flex-shrink: 0 !important;'
        f'margin-left: 3px !important;'
        f'}}'
        f'.li-size-badge {{'
        f'font-size: 0.72rem !important;'
        f'color: rgba(255,255,255,0.4) !important;'
        f'white-space: nowrap !important;'
        f'flex-shrink: 0 !important;'
        f'margin-left: 3px !important;'
        f'}}'
        f'.dropdown-list ul {{ margin: 0 !important; padding: 0 !important; }}'
        f'</style>'
    )
    html_content = (
        f'<div class="sync-subtitle">You are about to download <b>{count} files</b> ({size}) to <b>{folders} {"folder" if folders == 1 else "folders"}</b>.'
        + (
            f'<br><span style="color:#fcd34d;">&#9998; {modified_update_count} of these are files you\'ve edited locally - the new Canvas version will be saved alongside as <code>_NewVersion</code> so your edits are preserved.</span>'
            if modified_update_count > 0 else ''
        ) +
        '</div>'
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
    st.html(_css_block)
    st.markdown(html_content, unsafe_allow_html=True)

    # Amber notice when disk space is tight (download > 70% of remaining space)
    if fill_percent > 70:
        from ui.amber_notice import render_amber_notice
        render_amber_notice(
            "Your disk is getting full.",
            detail=f"This download will use {fill_percent:.0f}% of your remaining space. Make sure you have enough room.",
        )

    col_no, col_yes = st.columns([1, 1], gap="medium")
    with col_no:
        if st.button("No, Go back", use_container_width=True, key="cancel_sync_dialog_btn"):
            st.rerun(scope="app")
    with col_yes:
        if st.button("Yes, Start Sync", type="primary", use_container_width=True, key="page_nav_start_sync"):
            st.session_state['sync_selections'] = sync_selections
            st.session_state['download_status'] = 'pre_sync'

            # Load each course's individual sync_contract from SQLite.
            # M-5 fix: when no DB contract exists (first sync or unset pair),
            # seed the contract from current session state so post-processing
            # conversions are not silently skipped.
            _CONVERT_KEYS_HANDOFF = ['convert_zip', 'convert_pptx', 'convert_word', 'convert_excel',
                                      'convert_html', 'convert_code', 'convert_urls', 'convert_video']
            for _s in sync_selections:
                try:
                    _p = _s['res_data']['pair']
                    _sm = SyncManager(_p['local_folder'], _p['course_id'], _p.get('course_name', ''))
                    _raw = _sm._load_metadata('sync_contract')
                    if _raw:
                        _s['res_data']['contract'] = json.loads(_raw)
                    else:
                        # Seed from session state so conversions aren't silently disabled
                        _s['res_data']['contract'] = {
                            k: st.session_state.get(k, False) for k in _CONVERT_KEYS_HANDOFF
                        }
                except Exception:
                    _s['res_data']['contract'] = {}

            # Mirror the resolved contracts into persistent_* keys so the
            # execution pipeline's session-state fallback path also works.
            # Use a per-key OR across all pairs (any course enabling a conversion enables it).
            for k in _CONVERT_KEYS_HANDOFF:
                st.session_state[f'persistent_{k}'] = any(
                    bool(_s.get('res_data', {}).get('contract', {}).get(k, False))
                    for _s in sync_selections
                )

            st.rerun(scope="app")

