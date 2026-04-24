"""
Shared UI components for Download and Sync completion screens.
Extracted to ensure perfect visual parity between both modes.
"""
import streamlit as st
from pathlib import Path
from ui_helpers import open_folder, esc, short_path
from sync_manager import format_file_size
from preset_manager import PresetManager


# --- Entity Icons for secondary content logging ---
SECONDARY_ENTITY_ICONS = {
    'assignment':   '📝',
    'quiz':         '❓',
    'discussion':   '💬',
    'announcement': '📢',
    'syllabus':     '📋',
    'rubric':       '📊',
    'page':         '📄',
}


def render_completion_card(synced_count: int, error_count: int,
                           total_bytes: int, mode: str = 'download',
                           size_skipped_files: list = None, size_limit_mb: int = 0,
                           retry_attempted: bool = False, retry_resolved: int = 0,
                           retry_total: int = 0,
                           retriable_count: int = 0,
                           unresolvable_count: int = 0,
                           courses_count: int = 0):
    """Render the unified completion summary card.

    Single card that absorbs all status info: success/partial/failure,
    retry results, discovery warnings, and size-skipped annotations.
    """
    from styles import inject_css
    inject_css('completion.css')

    size_skipped_files = size_skipped_files or []
    size_skipped_count = len(size_skipped_files)

    # Determine card variant
    if synced_count == 0 and error_count > 0:
        card_class = 'failure'
        title = 'Download Failed' if mode == 'download' else 'Sync Failed'
    elif error_count > 0:
        card_class = 'partial'
        title = 'Partial Success' if mode == 'download' else 'Sync Completed with Errors'
    elif synced_count > 0:
        card_class = 'success'
        title = 'Download Success' if mode == 'download' else 'Sync Success'
    else:
        st.html("""
        <style>
        div[class*="st-key-completion_dashboard"] {
            background-color: rgba(22, 101, 52, 0.25) !important;
            border: 1px solid rgba(74, 222, 128, 0.5) !important;
            border-radius: 10px !important;
            padding: 20px 20px 35px 20px !important;
            margin-bottom: 12px;
        }
        </style>
        """)
        _label = 'sync' if mode == 'sync' else 'download'
        st.markdown(
            "<div class='completion-card success'>"
            "<div class='card-title'>All Up to Date</div>"
            f"<p style='color:#86efac;font-size:1rem;margin:8px 0 0;'>"
            f"Nothing to {_label} — all files are up to date!"
            "</p></div>",
            unsafe_allow_html=True,
        )
        return

    # Stats grid
    file_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z'></path><polyline points='13 2 13 9 20 9'></polyline></svg>"
    error_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><line x1='12' y1='8' x2='12' y2='12'></line><line x1='12' y1='16' x2='12.01' y2='16'></line></svg>"
    size_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><ellipse cx='12' cy='5' rx='9' ry='3'></ellipse><path d='M21 12c0 1.66-4 3-9 3s-9-1.34-9-3'></path><path d='M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5'></path></svg>"
    # Slash-circle icon for unresolvable files
    slash_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><line x1='4.93' y1='4.93' x2='19.07' y2='19.07'></line></svg>"
    
    size_parts = format_file_size(total_bytes).split(" ", 1)
    size_val = size_parts[0]
    size_unit = size_parts[1] if len(size_parts) > 1 else "Bytes"
    if total_bytes == 0:
        size_unit = "MB"

    stats_html = (
'<div class="completion-stats-grid">'
    )
    if courses_count > 0:
        course_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M4 19.5A2.5 2.5 0 0 1 6.5 17H20'></path><path d='M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'></path></svg>"
        stats_html += (
'<div class="stat-card">'
f'<div class="stat-icon-wrapper">{course_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{courses_count}</div>'
f'<div class="stat-label">{"Course" if courses_count == 1 else "Courses"} {"Updated" if mode == "sync" else "Downloaded"}</div>'
'</div>'
'</div>'
        )
    stats_html += (
'<div class="stat-card">'
f'<div class="stat-icon-wrapper">{file_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{synced_count}</div>'
f'<div class="stat-label">{"File" if synced_count == 1 else "Files"} Downloaded</div>'
'</div>'
'</div>'
'<div class="stat-card">'
f'<div class="stat-icon-wrapper">{size_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{size_val}</div>'
f'<div class="stat-label">{size_unit} Downloaded</div>'
'</div>'
'</div>'
    )

    # Conditional error stat cards — split by retriable vs unresolvable
    if retriable_count > 0 or unresolvable_count > 0:
        # Show separate cards when split counts are provided
        if retriable_count > 0:
            stats_html += (
'<div class="stat-card stat-error">'
f'<div class="stat-icon-wrapper">{error_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{retriable_count}</div>'
f'<div class="stat-label">Failed {"Download" if retriable_count == 1 else "Downloads"}</div>'
'</div>'
'</div>'
            )
        if unresolvable_count > 0:
            stats_html += (
'<div class="stat-card stat-skip">'
f'<div class="stat-icon-wrapper">{slash_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{unresolvable_count}</div>'
f'<div class="stat-label">Unavailable {"File" if unresolvable_count == 1 else "Files"}</div>'
'</div>'
'</div>'
            )
    elif error_count > 0:
        # Fallback: single combined error card (backward compat)
        stats_html += (
'<div class="stat-card stat-error">'
f'<div class="stat-icon-wrapper">{error_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{error_count}</div>'
f'<div class="stat-label">{"Error" if error_count == 1 else "Errors"}</div>'
'</div>'
'</div>'
        )
        
    stats_html += '</div>'

    # Optional notes (retry + discovery, folded inline)
    notes_html = ''
    _check_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:14px;height:14px;flex-shrink:0;margin-top:1px;'><polyline points='20 6 9 17 4 12'/></svg>"
    if retry_attempted and retry_total > 0:
        if retry_resolved == 0:
            pass  # Note shown below retry button instead
        elif retry_resolved < retry_total:
            notes_html += (
                f'<div class="retry-note retry-note-success">'
                f'{_check_icon}'
                f'Recovered {retry_resolved} of {retry_total} failed {"item" if retry_total == 1 else "items"}.'
                f'</div>'
            )
        else:
            notes_html += (
                f'<div class="retry-note retry-note-success">'
                f'{_check_icon}'
                f'Successfully recovered all {retry_resolved} previously failed {"item" if retry_resolved == 1 else "items"}!'
                f'</div>'
            )

        
    if size_skipped_count > 0:
        _sw = 'file' if size_skipped_count == 1 else 'files'
        notes_html += (
            f'<div class="card-note">'
            f'{size_skipped_count} {_sw} skipped because they exceeded the {size_limit_mb} MB limit.'
            f'</div>'
        )

    if card_class == 'failure':
        bg_color = 'rgba(127, 29, 29, 0.30)'
        border_color = 'rgba(239, 68, 68, 0.45)'
    elif card_class == 'partial':
        bg_color = 'rgba(120, 80, 0, 0.22)'
        border_color = 'rgba(245, 158, 11, 0.45)'
    else:
        bg_color = 'rgba(22, 101, 52, 0.25)'
        border_color = 'rgba(74, 222, 128, 0.5)'

    st.html(f"""
    <style>
    div[class*="st-key-completion_dashboard"] {{
        background-color: {bg_color} !important;
        border: 1px solid {border_color} !important;
        border-radius: 10px !important;
        padding: 20px 20px 35px 20px !important;
        margin-bottom: 12px;
    }}
    </style>
    """)

    st.markdown(f"""
    <div class="completion-card {card_class}">
        <div class="card-title">{esc(title)}</div>
        {stats_html}
        {notes_html}
    </div>
    """, unsafe_allow_html=True)

    if size_skipped_count > 0:
        with st.expander(f"See {size_skipped_count} skipped {'file' if size_skipped_count == 1 else 'files'}"):
            st.markdown("<p style='font-size:0.8rem; color:#aaa; margin-top:-10px; margin-bottom:5px;'>These files are marked as ignored and won't appear as new during sync. You can manage them in the Sync Hub.</p>", unsafe_allow_html=True)
            for _sf in size_skipped_files:
                st.markdown(f"- {_sf}")

    if card_class == 'success':
        st.balloons()


_FC_FOLDER_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'"
    " viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'"
    " stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'/%3E"
    "%3C/svg%3E"
)
_FC_CHEVRON_SVG = (
    "<svg class='ft-chevron' xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'"
    " fill='none' stroke='currentColor' stroke-width='2.5'"
    " stroke-linecap='round' stroke-linejoin='round'>"
    "<path d='M9 18l6-6-6-6'/>"
    "</svg>"
)


def render_folder_cards(file_details: dict, folder_paths: dict,
                        key_prefix: str = 'dl', show_files_expander: bool = False):
    """Render per-folder cards with filetype summary and Open Folder buttons."""
    has_files = any(len(files) > 0 for files in file_details.values())
    if not has_files:
        return

    st.markdown('<div class="completion-section-header">Folders Updated</div>', unsafe_allow_html=True)

    for idx, (folder_key, files) in enumerate(file_details.items()):
        if not files:
            continue

        folder_path = folder_paths.get(folder_key, '')
        folder_name = short_path(folder_path) if folder_path else folder_key
        file_count = len(files)
        count_label = f"{file_count} file" if file_count == 1 else f"{file_count} files"
        expand_id = f"ft-expand-{key_prefix}-{idx}"
        pills_html = _build_filetype_pills_html(files)

        header_html = (
            f'<div class="fc-wrapper">'
            f'<input type="checkbox" id="{expand_id}" class="ft-expand-toggle"/>'
            f'<div class="fc-header">'
            f'<img class="fc-folder-icon" src="{_FC_FOLDER_SVG}" alt="folder"/>'
            f'<div class="fc-title">{esc(folder_name)}</div>'
            f'<label for="{expand_id}" class="ft-expander-trigger">'
            f'{_FC_CHEVRON_SVG}'
            f'<span class="ft-label">{count_label}</span>'
            f'</label>'
            f'</div>'
            f'<div class="ft-expander-pills">{pills_html}</div>'
            f'</div>'
        )

        with st.container(border=True, key=f"{key_prefix}_fc_{idx}"):
            st.markdown(header_html, unsafe_allow_html=True)
            if show_files_expander and files:
                with st.expander("Files added"):
                    import os as _os
                    rows = []
                    for fname in sorted(files):
                        _ext = _os.path.splitext(fname)[1].lower().lstrip('.')
                        _name = _os.path.splitext(fname)[0]
                        _icon = _FILETYPE_SVGS.get(_ext, _FILETYPE_SVG_DEFAULT)
                        _badge = (
                            f"<span style='font-size:0.65rem;font-weight:700;letter-spacing:0.4px;"
                            f"color:#bababa;background:rgba(255,255,255,0.08);border-radius:3px;"
                            f"padding:1px 5px;margin-left:6px;white-space:nowrap;flex-shrink:0;'>{esc(_ext.upper())}</span>"
                        ) if _ext else ""
                        rows.append(
                            f"<div style='display:flex;align-items:center;gap:3px;padding:3px 0;flex-wrap:wrap;'>"
                            f'<img src="{_icon}" style="width:16px;height:16px;flex-shrink:0;" alt="{esc(_ext)}"/>'
                            f"<span style='font-size:0.85rem;color:#ffffff;word-break:break-word;'>{esc(_name)}</span>"
                            f"{_badge}"
                            f"</div>"
                        )
                    st.markdown(
                        "<div style='display:flex;flex-direction:column;gap:1px;'>" + "".join(rows) + "</div>",
                        unsafe_allow_html=True,
                    )
            if folder_path and Path(folder_path).exists():
                if st.button('Open Folder', key=f"{key_prefix}_open_{idx}", use_container_width=False):
                    open_folder(folder_path)



# --- Base64 SVG icons for filetype pills ---
_FILETYPE_SVGS = {
    'pdf': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23ef4444'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fca5a5'/%3E%3Ctext x='7' y='17' font-size='6' font-weight='bold' fill='white'%3EPDF%3C/text%3E%3C/svg%3E",
    'pptx': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23f97316'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fdba74'/%3E%3Ctext x='7' y='17' font-size='5' font-weight='bold' fill='white'%3EPPT%3C/text%3E%3C/svg%3E",
    'ppt': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23f97316'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fdba74'/%3E%3Ctext x='7' y='17' font-size='5' font-weight='bold' fill='white'%3EPPT%3C/text%3E%3C/svg%3E",
    'docx': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%233b82f6'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2393c5fd'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EDOC%3C/text%3E%3C/svg%3E",
    'doc': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%233b82f6'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2393c5fd'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EDOC%3C/text%3E%3C/svg%3E",
    'xlsx': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2322c55e'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2386efac'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3EXLS%3C/text%3E%3C/svg%3E",
    'xls': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2322c55e'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2386efac'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3EXLS%3C/text%3E%3C/svg%3E",
    'zip': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%238b5cf6'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23c4b5fd'/%3E%3Ctext x='7' y='17' font-size='5' font-weight='bold' fill='white'%3EZIP%3C/text%3E%3C/svg%3E",
    'html': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2306b6d4'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2367e8f9'/%3E%3Ctext x='4' y='17' font-size='5' font-weight='bold' fill='white'%3EHTML%3C/text%3E%3C/svg%3E",
    'txt': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%236b7280'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23d1d5db'/%3E%3Ctext x='7' y='17' font-size='5' font-weight='bold' fill='white'%3ETXT%3C/text%3E%3C/svg%3E",
    'jpg': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23eab308'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fde047'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3EJPG%3C/text%3E%3C/svg%3E",
    'jpeg': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23eab308'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23fde047'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3EJPG%3C/text%3E%3C/svg%3E",
    'png': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2314b8a6'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%235eead4'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EPNG%3C/text%3E%3C/svg%3E",
    'mp4': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23ec4899'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23f9a8d4'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EMP4%3C/text%3E%3C/svg%3E",
    'mp3': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23a855f7'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23d8b4fe'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EMP3%3C/text%3E%3C/svg%3E",
    'csv': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2322c55e'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%2386efac'/%3E%3Ctext x='6' y='17' font-size='5' font-weight='bold' fill='white'%3ECSV%3C/text%3E%3C/svg%3E",
    'url': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2338bdf8'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%237dd3fc'/%3E%3Ctext x='5' y='17' font-size='5' font-weight='bold' fill='white'%3EURL%3C/text%3E%3C/svg%3E",
    'other': "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2364748b'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%23cbd5e1'/%3E%3Ctext x='2' y='17' font-size='5' font-weight='bold' fill='white'%3EOTHER%3C/text%3E%3C/svg%3E",
}
_FILETYPE_SVG_DEFAULT = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%234b5563'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%239ca3af'/%3E%3C/svg%3E"


def _build_filetype_pills_html(files: list) -> str:
    """Return filetype pill HTML string for a list of filenames."""
    import os
    from collections import Counter

    WHITELIST = {'pdf', 'docx', 'pptx', 'xlsx', 'zip', 'mp4', 'js', 'html', 'css', 'txt', 'sql', 'jpg', 'png', 'doc', 'ppt', 'xls', 'md', 'csv', 'json', 'py', 'java', 'c', 'cpp'}

    ext_counts = Counter()
    for f in files:
        ext = os.path.splitext(f)[1].lower().lstrip('.')
        if ext in WHITELIST:
            ext_counts[ext] += 1
        else:
            ext_counts['other'] += 1

    specific_exts = {k: v for k, v in ext_counts.items() if k != 'other'}
    sorted_specific = sorted(specific_exts.items(), key=lambda x: -x[1])

    top_4 = sorted_specific[:4]
    remaining_count = sum(v for k, v in sorted_specific[4:])
    other_count = ext_counts.get('other', 0) + remaining_count

    html = ''
    for ext, count in top_4:
        icon_url = _FILETYPE_SVGS.get(ext, _FILETYPE_SVG_DEFAULT)
        html += (
            f'<div class="filetype-pill">'
            f'<img class="ft-icon" src="{icon_url}" alt="{ext}"/>'
            f'<span class="ft-label">{esc(ext.upper())}</span>'
            f'<span class="ft-count">{count}</span>'
            f'</div>'
        )
    if other_count > 0:
        html += (
            f'<div class="filetype-pill">'
            f'<img class="ft-icon" src="{_FILETYPE_SVG_DEFAULT}" alt="other"/>'
            f'<span class="ft-label">OTHER FILES</span>'
            f'<span class="ft-count">{other_count}</span>'
            f'</div>'
        )
    return html




# --- Error type to human-friendly message mapping ---
_ERROR_TRANSLATIONS = {
    'No URL': 'Canvas did not provide a download link for this file',
    'LTI/Media Stream': 'This is a streamed video that cannot be downloaded directly',
    'URL Expiration': 'The download link expired and could not be refreshed',
    'Network Error': 'Network connection failed after multiple retries',
    'Write Error': 'Could not save the file to disk — check available storage',
    '401 Unauthorized': 'Access denied — you may not have permission to download this file',
    'Missing Content ID': 'Canvas did not provide a file reference for this item',
    'Missing Page URL': 'Canvas did not provide a URL for this page',
    'Missing External URL': 'Canvas did not provide a URL for this link',
    'Missing Tool URL': 'Canvas did not provide a launch URL for this external tool',
    'Item Processing Error': 'An unexpected error occurred while processing this item',
    'Module Error': 'Could not load this module from Canvas',
    'Async Error': 'A download task failed unexpectedly',
    'Processing Error': 'An unexpected error occurred during download',
    'Hybrid Mode Error': 'An unexpected error occurred while scanning the course',
    'Secondary Content Error': 'Could not download supplementary course content',
    'Secondary Retry Error': 'Retry also failed for supplementary content',
    'Fetch Error': 'Could not load this resource from Canvas',
    'Queue Error': 'Failed to queue this file for download',
    'Legacy Entity Save Error': 'Could not save this item to disk',
}

def _friendly_error_reason(err) -> str:
    """Translate a DownloadError into a human-readable reason string."""
    if not hasattr(err, 'error_type'):
        return 'Download failed'

    error_type = err.error_type or ''

    # Direct match
    if error_type in _ERROR_TRANSLATIONS:
        return _ERROR_TRANSLATIONS[error_type]

    # HTTP status codes
    if error_type.startswith('HTTP '):
        code = error_type.replace('HTTP ', '')
        if code == '401':
            return 'Access denied - you may not have permission to download this file'
        if code == '403':
            return 'Access forbidden by Canvas'
        if code == '404':
            return 'File not found on Canvas - it may have been removed'
        return f'Canvas returned an error (HTTP {code})'

    # Check message for common patterns
    msg = (getattr(err, 'message', '') or '').lower()
    if 'unauthorized' in msg or 'not authorised' in msg:
        return 'Access denied - you may not have permission to download this file'
    if 'not found' in msg:
        return 'File not found on Canvas - it may have been removed'
    if 'timeout' in msg:
        return 'Connection timed out while downloading'

    return 'Download failed - see error log for technical details'


# SVG chevron for error panel toggle
_CHEVRON_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f87171' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9 18l6-6-6-6'/%3E%3C/svg%3E"
# SVG alert circle for error rows
_ALERT_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f87171' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cline x1='12' y1='8' x2='12' y2='12'/%3E%3Cline x1='12' y1='16' x2='12.01' y2='16'/%3E%3C/svg%3E"


def render_error_section(error_list: list, error_log_paths: list = None,
                         dialog_fn=None, key_prefix: str = 'dl',
                         retry_btn_callback=None, has_retriable_errors: bool = False,
                         retry_failed: bool = False):
    """Render error details as a custom CSS panel with human-friendly messages.

    Args:
        error_list: List of error messages or DownloadError objects.
        error_log_paths: Optional list of Path objects to download_errors.txt files.
        dialog_fn: Optional callable; if provided, called with error_log_paths.
        key_prefix: Unique prefix for Streamlit widget keys.
        retry_btn_callback: If provided, renders the retry button inside the panel.
        has_retriable_errors: Whether retriable errors exist (controls retry btn visibility).
        retry_failed: True when a retry was already attempted and all items still failed.
    """
    if not error_list:
        return

    import os
    from collections import defaultdict
    count = len(error_list)

    def _err_row_html(err):
        if hasattr(err, 'item_name'):
            fname = err.item_name or 'Unknown file'
            ext = os.path.splitext(fname)[1].lower().lstrip('.')
            fname = os.path.splitext(fname)[0] if ext else fname
            ft_icon_url = _FILETYPE_SVGS.get(ext, _FILETYPE_SVG_DEFAULT)
            
            link_html = ''
            
            api_url = st.session_state.get('api_url', '').rstrip('/')
            if api_url and hasattr(err, 'context') and isinstance(err.context, dict):
                f_dict = err.context.get('file_dict', {})
                fid = f_dict.get('id')
                furl = f_dict.get('url', '')
                
                course_id = None
                if hasattr(err, 'course_name'):
                    for c in st.session_state.get('courses_to_download', []):
                        if c.name == err.course_name:
                            course_id = c.id
                            break
                    if not course_id:
                        sync_state = st.session_state.get('sync_state', {})
                        course_det = sync_state.get('course_details')
                        if course_det and getattr(course_det, 'name', '') == err.course_name:
                            course_id = course_det.id

                canvas_url = None
                if furl and ('/courses/' in furl or '/assignments/' in furl or '/discussion_topics/' in furl or '/quizzes/' in furl):
                    canvas_url = furl
                elif fid and str(fid).isdigit():
                    if course_id:
                        canvas_url = f"{api_url}/courses/{course_id}/files/{fid}"
                    else:
                        canvas_url = f"{api_url}/files/{fid}"
                    
                if canvas_url:
                    _LINK_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>'''
                    link_html = f'<a href="{canvas_url}" target="_blank" rel="noopener noreferrer" class="err-link-btn" title="Open in Canvas">{_LINK_SVG}</a>'

            return (
                f'<div class="error-row">'
                f'<img class="err-icon" src="{ft_icon_url}" alt="{ext}"/>'
                f'<div class="err-body">'
                f'<span class="err-filename">{esc(fname)}</span>'
                f'{link_html}'
                f'</div></div>'
            )
        else:
            return (
                f'<div class="error-row">'
                f'<img class="err-icon" src="{_FILETYPE_SVG_DEFAULT}" alt="file"/>'
                f'<div class="err-body">'
                f'<div class="err-filename">{esc(str(err))}</div>'
                f'</div></div>'
            )

    # Split into actionable vs unresolvable
    actionable, unresolvable = [], []
    for err in error_list[:20]:
        is_retriable = (
            hasattr(err, 'item_name')
            and isinstance(getattr(err, 'context', None), dict)
            and err.context.get('filepath')
            and getattr(err, 'error_type', '') != 'LTI/Media Stream'
        )
        if is_retriable or not hasattr(err, 'item_name'):
            actionable.append(err)
        else:
            unresolvable.append(err)

    # Build left column: "Failed to Download" (actionable / retriable errors)
    left_col_html = ''
    if actionable:
        if retry_failed:
            subtitle = "We tried to download these files again, with no success. Please try downloading these files manually via Canvas."
            subtitle_class = 'err-col-subtitle err-col-subtitle-failed'
        else:
            subtitle = "These files timed out or failed. Click the <b>Retry Failed Files</b> button below to try grabbing them again."
            subtitle_class = 'err-col-subtitle'
        rows = ''.join(_err_row_html(e) for e in actionable)
        left_col_html = (
            f'<div class="err-col">'
            f'<div class="err-col-header">'
            f'<span class="err-col-title">Failed to Download</span>'
            f'<span class="err-group-badge err-group-badge-error">{len(actionable)}</span>'
            f'</div>'
            f'<div class="{subtitle_class}">{subtitle}</div>'
            f'{rows}'
            f'</div>'
        )

    # Build right column: "Stream-Only Videos" or generic unresolvable
    right_col_html = ''
    if unresolvable:
        by_reason = defaultdict(list)
        for err in unresolvable:
            reason = _friendly_error_reason(err)
            by_reason[reason].append(err)

        lti_count = sum(1 for e in unresolvable if getattr(e, 'error_type', '') == 'LTI/Media Stream')
        if lti_count == len(unresolvable):
            col_title = 'Unavailable Files (Stream-Only)'
            col_subtitle = 'These are video streams. Canvas does not allow direct downloads for these.'
            badge_class = 'err-group-badge-neutral'
        else:
            col_title = 'Cannot Be Downloaded'
            col_subtitle = 'These files have a permanent issue and cannot be retried.'
            badge_class = 'err-group-badge-muted'

        sub_html = ''
        for reason, errs in by_reason.items():
            rows = ''.join(_err_row_html(e) for e in errs)
            if len(by_reason) > 1:
                sub_html += f'<div class="err-subgroup-reason">{esc(reason)}</div>'
            sub_html += rows

        right_col_html = (
            f'<div class="err-col">'
            f'<div class="err-col-header">'
            f'<span class="err-col-title">{col_title}</span>'
            f'<span class="err-group-badge {badge_class}">{len(unresolvable)}</span>'
            f'</div>'
            f'<div class="err-col-subtitle">{col_subtitle}</div>'
            f'{sub_html}'
            f'</div>'
        )

    body_html = f'<div class="error-columns">{left_col_html}{right_col_html}</div>'

    if count > 20:
        body_html += f'<div style="padding:6px 0;color:#6b7280;font-size:0.82em;">... and {count - 20} more errors</div>'

    # Footer
    footer_html = ''
    if st.session_state.get('error_log_enabled', True):
        footer_html = '<div class="error-panel-footer">Full error details are saved in <code>download_errors.txt</code> in each course folder.</div>'

    st.markdown(f"""
    <details class="error-panel" open>
        <summary class="error-panel-header">
            <div class="ep-header-row">
                <img class="chevron" src="{_CHEVRON_SVG}" alt="toggle"/>
                <span class="ep-title">Error Details</span>
            </div>
        </summary>
        <div class="error-panel-body">
            {body_html}
            {footer_html}
        </div>
    </details>
    """, unsafe_allow_html=True)

    # Error log viewer button
    if error_log_paths and dialog_fn:
        valid_paths = [p for p in error_log_paths if p.exists()]
        if valid_paths:
            col_log, _ = st.columns([0.3, 0.7])
            with col_log:
                if st.button("View Full Error Log", key=f"{key_prefix}_view_error_log", use_container_width=True):
                    dialog_fn(valid_paths)

    # Retry button — placed in half-width left column under the error panel
    # so it visually associates with the "Failed to Download" column only.
    if has_retriable_errors and retry_btn_callback:
        retriable_count = sum(
            1 for err in error_list
            if isinstance(getattr(err, 'context', None), dict)
            and err.context.get('filepath')
            and getattr(err, 'error_type', '') != 'LTI/Media Stream'
        )
        btn_text = "Retry Failed Files" if retry_failed else (
            f"Retry Failed Files ({retriable_count})" if retriable_count > 0 else "Retry Failed Files"
        )
        retry_tooltip = (
            "We couldn't download these files after retrying. "
            "You can find them directly on Canvas and download from there."
        ) if retry_failed else None
        st.html("<div style='padding: 4px 0 0 0;'></div>")
        col_retry, _ = st.columns(2)
        with col_retry:
            if st.button(btn_text, type="secondary", key=f"{key_prefix}_retry_failed_btn",
                         use_container_width=True, disabled=retry_failed,
                         help=retry_tooltip):
                retry_btn_callback()


def render_pp_warning(pp_failure_count: int):
    """Render post-processing failure warning if applicable."""
    if pp_failure_count > 0:
        word = "file" if pp_failure_count == 1 else "files"
        detail_hint = " Check download_errors.txt for details." if st.session_state.get('error_log_enabled', True) else ""
        st.warning(f"⚠️ {pp_failure_count} {word} failed during post-processing (conversion/extraction).{detail_hint}")

def render_config_summary_badges(settings: dict, show_path: bool = True) -> str:
    """Render a rich HTML preview of active settings using color-coded badges."""
    # Build Blue Core Badges
    _mode_disp = "With Subfolders" if settings.get('download_mode') == 'modules' else "All in One Folder"
    _filter_disp = "All Files" if settings.get('file_filter') == 'all' else "Presentations & PDFs"
    
    c_core = "#3fd9ff"
    core_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#94a3b8; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>Core Settings</div>
    <div style='width: 100%;'><span style='display:inline-flex; padding:3px 10px; background-color:rgba(63, 217, 255, 0.05); color:{c_core}; border-radius:4px; font-size:0.78rem; border:1px solid rgba(63, 217, 255, 0.7);'>📁 {_mode_disp}</span></div>
    <span style='display:inline-flex; padding:3px 10px; background-color:rgba(63, 217, 255, 0.15); color:{c_core}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(63, 217, 255, 0.3);'>{_filter_disp}</span>
</div>
"""
    
    # Build Green Canvas Content Badges
    c_canvas = "#2DFFA0"
    _sec_mode_disp = "Separate Folders" if settings.get('dl_isolate_secondary') else "Matching Core Settings"
    sec_org_badge = f"<span style='display:inline-flex; padding:3px 10px; background-color:rgba(45, 255, 160, 0.05); color:{c_canvas}; border-radius:4px; font-size:0.78rem; border:1px solid rgba(45, 255, 160, 0.7);'>📁 {_sec_mode_disp}</span>"
    
    _sec_on = [k.replace('dl_', '').replace('_', ' ').title() for k in PresetManager.SECONDARY_CONTENT_KEYS if settings.get(k)]
    if _sec_on:
        sec_badges_list = "".join([f"<span style='display:inline-flex; padding:3px 10px; background-color:rgba(45, 255, 160, 0.15); color:{c_canvas}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(45, 255, 160, 0.3);'>✓ {x}</span>" for x in _sec_on])
        sec_badges = f"<div style='width: 100%;'>{sec_org_badge}</div>{sec_badges_list}"
    else:
        sec_badges = "<div style='width: 100%;'><span style='display:inline-flex; padding:3px 10px; background-color:rgba(255, 255, 255, 0.05); color:#94a3b8; border-radius:12px; font-size:0.78rem; border:1px solid #475569;'>None selected</span></div>"
        
    content_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#94a3b8; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>Canvas Content</div>
    {sec_badges}
</div>
"""
    
    # Build Orange AI Optimization Badges
    c_ai = "#FF9838"
    conv_mapping = {
        'convert_zip': 'Unpack Archives (.zip)',
        'convert_pptx': 'PPTX ➡ PDF',
        'convert_word': 'Legacy Word ➡ PDF',
        'convert_excel': 'Excel ➡ PDF & Data',
        'convert_html': 'HTML ➡ PDF',
        'convert_code': 'Code ➡ .TXT',
        'convert_urls': 'Links ➡ TXT',
        'convert_video': 'Video ➡ MP3'
    }
    _conv_on = [conv_mapping.get(k, k) for k in PresetManager.NOTEBOOK_SUB_KEYS if settings.get(k)]
    if _conv_on:
        conv_badges = "".join([f"<span style='display:inline-flex; padding:3px 10px; background-color:rgba(255, 152, 56, 0.15); color:{c_ai}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(255, 152, 56, 0.3);'>⚡ {x}</span>" for x in _conv_on])
    else:
        conv_badges = "<span style='display:inline-flex; padding:3px 10px; background-color:rgba(255, 255, 255, 0.05); color:#94a3b8; border-radius:12px; font-size:0.78rem; border:1px solid #475569;'>None selected</span>"
        
    conv_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#94a3b8; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>AI Optimization & Conversions</div>
    {conv_badges}
</div>
"""
    
    path_html = ""
    if show_path and settings.get('download_path'):
        path_html = f"""
<div style='margin-bottom:4px;'>
    <div style='font-size:0.8rem; color:#94a3b8; font-weight:600; text-transform:uppercase; margin-bottom:4px;'>Saved Path</div>
    <div style='background-color:rgba(0,0,0,0.3); color:#cbd5e1; padding:6px 10px; border-radius:6px; font-size:0.78rem; font-family:monospace; border:none; word-break: break-all; margin-bottom:10px;'>{esc(settings.get('download_path'))}</div>
</div>
"""
    grid_container = f"""
<div style="display: grid; grid-template-columns: 0.8fr 1.1fr 1.1fr; gap: 15px; margin-bottom: 5px;">
    {core_html}
    {content_html}
    {conv_html}
</div>
"""

    return f"{grid_container}{path_html}"


@st.dialog("📄 Error Log", width="large")
def error_log_dialog(log_paths):
    """Display the contents of download_errors.txt files in a modal dialog.

    Unified dialog used by both the download completion screen (app.py)
    and the sync completion screen (sync/completion.py).
    """
    st.markdown("""
        <style>
            div.st-key-error_log_scroll_shared {
                height: 55vh !important;
                min-height: 55vh !important;
                max-height: 55vh !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
            }
        </style>
    """, unsafe_allow_html=True)

    with st.container(border=False, key="error_log_scroll_shared"):
        found_any = False
        for log_path in log_paths:
            if log_path.exists():
                try:
                    content = log_path.read_text(encoding='utf-8').strip()
                    if content:
                        found_any = True
                        st.markdown(f"**📁 {log_path.parent.name}**")
                        st.code(content, language="text")
                except Exception as e:
                    st.warning(f"Could not read {log_path}: {e}")

        if not found_any:
            st.info("No error log files found on disk.")

    if st.button("Close", type="primary", use_container_width=True):
        st.rerun(scope="app")
