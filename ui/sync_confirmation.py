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
from ui_shared import _FILETYPE_SVGS, _FILETYPE_SVG_DEFAULT, SVG_FOLDER_YELLOW, SVG_SAVE_COLORFUL

_PAN_FMT_LABELS = {
    "mp3": "Audio Track",
    "txt": "Transcript",
    "srt": "Subtitles",
    "mp4": "Video",
}

# ---- Confirmation dialog ----

def show_sync_confirmation_inner(sync_selections, count, size, folders, avail_mb, _total_mb, _target_folder, total_bytes):
    # --- Data Collection for Dropdowns ---
    file_items = []  # will hold tuples: (sort_name_lower, html_content)
    folder_set = set()
    modified_update_count = sum(len(s.get('updates_modified', [])) for s in sync_selections)
    # Panopto recordings selected in Review. They have no known size yet (not
    # downloaded), so they're surfaced in the subtitle + destination list rather
    # than the file dropdown / byte math.
    panopto_count = sum(len(s.get('panopto', [])) for s in sync_selections)
    for s in sync_selections:
        if not (s['new'] or s['updates'] or s['redownload'] or s.get('panopto')):
            continue
            
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
            html = (
                f"<li>"
                f'<img class="li-img" src="{icon_url}" alt="{esc(ext)}"/>'
                f"<span class='li-text'>{esc(fname)}</span>"
                f"{ext_badge}"
                f"{size_badge}"
                f"</li>"
            )
            sort_name = get_friendly_name(display_name or raw_name).lower()
            return (sort_name, html)

        for f in s['new']:
            file_items.append(_file_li(f.filename, f.display_name or f.filename, f.size))
        for f in s['updates']:
            file_items.append(_file_li(f.filename, f.display_name or f.filename, f.size))
        for f in s['redownload']:
            file_items.append(_file_li(f.canvas_filename, f.canvas_filename, f.original_size))

        # Collect selected Panopto changes
        _pan_changes = {c.video_id: c for c in (s['res_data'].get('panopto') or {}).get('changes', [])}
        for vid in s.get('panopto', []):
            c = _pan_changes.get(vid)
            if c:
                if c.bucket == 'restore':
                    formats = c.deleted_kinds or c.missing_kinds
                else:
                    formats = c.missing_kinds

                _PAN_ICON_SVG = (
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                    'stroke="rgba(255,255,255,0.85)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" '
                    'style="width:13px; height:13px; flex-shrink:0; margin-right:6px; margin-top:1px;"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M17 3v18"/><path d="M3 7.5h4"/><path d="M3 12h18"/><path d="M3 16.5h4"/><path d="M17 7.5h4"/><path d="M17 16.5h4"/></svg>'
                )
                # Recording total = sum of the outputs it will produce (formats).
                # "~" denotes an estimate (size not yet known from disk).
                _rec_sz = c.size_for(formats)
                _rec_size_badge = ""
                if _rec_sz > 0:
                    _rec_approx = "~" if c.estimated_for(formats) else ""
                    _rec_size_badge = f"<span class='li-size-badge'>{_rec_approx}{format_file_size(_rec_sz)}</span>"
                recording_html = (
                    f"<li>"
                    f"{_PAN_ICON_SVG}"
                    f"<span class='li-text' style='font-weight:600;'>{esc(c.title)}</span>"
                    f"{_rec_size_badge}"
                    f"</li>"
                )

                sub_lis = []
                for fmt in formats:
                    icon_url = _FILETYPE_SVGS.get(fmt, _FILETYPE_SVG_DEFAULT)
                    ext_badge = f"<span class='li-ext-badge'>{esc(fmt.upper())}</span>"

                    # Per-output size: real (on disk) or estimated; "~" marks an estimate.
                    _fsz = c.sizes.get(fmt)
                    if _fsz:
                        _fapprox = "~" if fmt in c.estimated else ""
                        size_badge = f"<span class='li-size-badge'>{_fapprox}{format_file_size(_fsz)}</span>"
                    else:
                        size_badge = ""

                    label = _PAN_FMT_LABELS.get(fmt, fmt.upper())
                    sub_li = (
                        f"<li class='li-sub-item'>"
                        f'<img class="li-img" src="{icon_url}" alt="{esc(fmt)}"/>'
                        f"<span class='li-text' style='font-size:0.9em;'>{esc(label)}</span>"
                        f"{ext_badge}"
                        f"{size_badge}"
                        f"</li>"
                    )
                    sub_lis.append(sub_li)
                
                combined_html = recording_html + "".join(sub_lis)
                file_items.append((c.title.lower(), combined_html))

    # Sort the tuples by display name, then extract the HTML contents
    sorted_items = [html for _, html in sorted(file_items, key=lambda x: x[0])]
    file_list_html = f"<ul style='margin:0 !important;padding:0 !important;list-style-type:none !important;display:block !important;'>{''.join(sorted_items)}</ul>"

    if count and panopto_count:
        lbl_value = f"{count} file{'s' if count != 1 else ''}, {panopto_count} recording{'s' if panopto_count != 1 else ''}"
    elif panopto_count:
        lbl_value = f"{panopto_count} recording{'s' if panopto_count != 1 else ''}"
    else:
        lbl_value = f"{count} file{'s' if count != 1 else ''}"
    sorted_folders = sorted(list(folder_set))
    _folder_lis = "".join(
        f"<li>{SVG_FOLDER_YELLOW}<span class='li-text'>" + esc(p) + "</span></li>"
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
            f'<div class="stat-left" style="display: flex; align-items: center;">{SVG_FOLDER_YELLOW} <span class="stat-label">Destination:</span></div>'
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
            f'<div style="font-weight: 600; color: #e2e8f0; white-space: nowrap; display: flex; align-items: center;">{SVG_FOLDER_YELLOW} Destination:</div>'
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
        f'div[data-testid="stDialog"] div[role="dialog"] > div:first-child {{'
        f'padding-top: 12px !important;'
        f'padding-bottom: 12px !important;'
        f'}}'
        f'div[data-testid="stDialog"] > div[data-testid="stAppViewBlockContainer"] > div > [data-testid="stVerticalBlock"] {{'
        f'gap: 0 !important;'
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
        f'height: auto !important;'
        f'min-height: 44px !important;'
        f'padding-top: 8px !important;'
        f'padding-bottom: 8px !important;'
        f'font-weight: 600 !important;'
        f'font-size: 0.95rem !important;'
        f'}}'
        f'button[data-testid="stBaseButton-secondary"] {{'
        f'background-color: #262730 !important;'
        f'border: 1px solid rgba(255, 255, 255, 0.1) !important;'
        f'color: {theme.WHITE} !important;'
        f'}}'
        f'div[data-testid="stDialog"] div.st-key-cancel_sync_dialog_btn button {{'
        f'background-color: rgba(255, 255, 255, 0.07) !important;'
        f'background-image: none !important;'
        f'border: 1px solid rgba(255, 255, 255, 0.2) !important;'
        f'color: #ffffff !important;'
        f'font-weight: 500 !important;'
        f'display: flex !important;'
        f'align-items: center !important;'
        f'justify-content: center !important;'
        f'gap: 8px !important;'
        f'transition: all 0.15s ease !important;'
        f'box-shadow: none !important;'
        f'}}'
        f'div[data-testid="stDialog"] div.st-key-cancel_sync_dialog_btn button::before {{'
        f'content: "" !important;'
        f'display: block !important;'
        f'width: 17px !important;'
        f'height: 17px !important;'
        f'min-width: 17px !important;'
        f'background-image: url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'white\' stroke-width=\'2\' stroke-linecap=\'round\' stroke-linejoin=\'round\'%3E%3Cpath d=\'M6 8L2 12L6 16\'/%3E%3Cpath d=\'M2 12H22\'/%3E%3C/svg%3E") !important;'
        f'background-size: contain !important;'
        f'background-repeat: no-repeat !important;'
        f'background-position: center !important;'
        f'flex-shrink: 0 !important;'
        f'}}'
        f'div[data-testid="stDialog"] div.st-key-cancel_sync_dialog_btn button:hover {{'
        f'background-color: rgba(255, 255, 255, 0.13) !important;'
        f'background-image: none !important;'
        f'border-color: rgba(255, 255, 255, 0.3) !important;'
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
        f'.dropdown-list ul li.li-sub-item {{'
        f'padding-left: 19px !important;'
        f'opacity: 0.85 !important;'
        f'}}'
        f'.dropdown-list ul {{ margin: 0 !important; padding: 0 !important; }}'
        f'</style>'
    )
    # Adaptive lead line: files and/or Panopto recordings.
    _dl_targets = []
    if count:
        _dl_targets.append(f'<b>{count} file{"s" if count != 1 else ""}</b> ({size})')
    if panopto_count:
        _dl_targets.append(f'<b>{panopto_count} Panopto recording{"s" if panopto_count != 1 else ""}</b>')
    _dl_phrase = " and ".join(_dl_targets) if _dl_targets else f'<b>{count} files</b> ({size})'
    html_content = (
        f'<div class="sync-subtitle">You are about to download {_dl_phrase} to <b>{folders} {"folder" if folders == 1 else "folders"}</b>.'
        + (
            f'<br><span style="color:#fcd34d;">&#9998; {modified_update_count} of these are files you\'ve edited locally - the new Canvas version will be saved alongside as <code>_NewVersion</code> so your edits are preserved.</span>'
            if modified_update_count > 0 else ''
        ) +
        '</div>'
        f'<div class="stats-card">'
        f'<div class="stat-row-dropdown">'
        f'<details>'
        f'<summary>'
        f'<div class="stat-left"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" style="width:1.45em;height:1.45em;vertical-align:-0.3em;display:inline-block;flex-shrink:0;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z" fill="rgba(255,255,255,0.85)"/><path d="M14 2v6h6" fill="rgba(255,255,255,0.4)"/></svg> <span class="stat-label">Files:</span></div>'
        f'<div class="stat-value">{lbl_value} <span class="arrow-icon"></span></div>'
        f'</summary>'
        f'<div class="dropdown-list">{file_list_html}</div>'
        f'</details>'
        f'</div>'
        f'<div class="stat-row-static">'
        f'<div class="stat-left">{SVG_SAVE_COLORFUL} <span class="stat-label">Total Size:</span></div>'
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
    st.markdown(_css_block, unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size: 1.6rem; font-weight: 700; color: #ffffff; margin-top: -70px; margin-bottom: 4px;">Confirm Sync</div>'
        + html_content,
        unsafe_allow_html=True,
    )

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

