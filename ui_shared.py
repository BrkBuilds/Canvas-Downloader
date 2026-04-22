"""
Shared UI components for Download and Sync completion screens.
Extracted to ensure perfect visual parity between both modes.
"""
import streamlit as st
from pathlib import Path
from ui_helpers import open_folder, esc, short_path
from sync_manager import format_file_size
import theme
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
                           retry_total: int = 0, discovery_skipped: int = 0):
    """Render the unified completion summary card.

    Single card that absorbs all status info: success/partial/failure,
    retry results, discovery warnings, and size-skipped annotations.
    """
    from styles import inject_css
    inject_css('completion.css')

    size_skipped_files = size_skipped_files or []
    size_skipped_count = len(size_skipped_files)
    action_word = 'Downloaded' if mode == 'download' else 'Synced'
    file_word = 'file' if synced_count == 1 else 'files'

    # Determine card variant
    if synced_count == 0 and error_count > 0:
        card_class = 'failure'
        title = f'{action_word.replace("ed", "")} failed for all {error_count} files'
    elif error_count > 0:
        card_class = 'partial'
        title = f'{action_word} {synced_count} {file_word} with {error_count} {"error" if error_count == 1 else "errors"}'
    elif synced_count > 0:
        card_class = 'success'
        title = f'{action_word} {synced_count} {file_word} successfully!'
    else:
        st.success("Nothing to download - all files are up to date!")
        return

    # Summary line
    parts = [f'{format_file_size(total_bytes)} downloaded']
    if error_count > 0:
        parts.append(f'{error_count} {"error" if error_count == 1 else "errors"} - see details below')
    if size_skipped_count > 0:
        _sw = 'file' if size_skipped_count == 1 else 'files'
        parts.append(f'{size_skipped_count} {_sw} skipped (exceeds {size_limit_mb} MB limit)')
    summary = ' · '.join(parts)

    # Optional notes (retry + discovery, folded inline)
    notes_html = ''
    if retry_attempted and retry_total > 0:
        if retry_resolved == 0:
            notes_html += (
                f'<div class="retry-note">'
                f'<span class="retry-badge retry-fail">Retry</span> '
                f'Attempted for {retry_total} {"item" if retry_total == 1 else "items"}, '
                f'but {"it" if retry_total == 1 else "none"} could not be downloaded. '
                f'These files may not be available on Canvas.'
                f'</div>'
            )
        elif retry_resolved < retry_total:
            notes_html += (
                f'<div class="retry-note">'
                f'<span class="retry-badge retry-success">Retry</span> '
                f'Recovered {retry_resolved} of {retry_total} failed {"item" if retry_total == 1 else "items"}!'
                f'</div>'
            )
        else:
            notes_html += (
                f'<div class="retry-note">'
                f'<span class="retry-badge retry-success">Retry</span> '
                f'Successfully recovered all {retry_resolved} previously failed {"item" if retry_resolved == 1 else "items"}!'
                f'</div>'
            )

    if discovery_skipped > 0:
        _fw = 'file' if discovery_skipped == 1 else 'files'
        _it = 'it' if discovery_skipped == 1 else 'them'
        notes_html += (
            f'<div class="card-note">'
            f'{discovery_skipped} {_fw} could not be downloaded because Canvas did not provide '
            f'enough information to locate {_it}. Try downloading the course again to pick {_it} up.'
            f'</div>'
        )

    st.markdown(f"""
    <div class="completion-card {card_class}">
        <div class="card-title">{esc(title)}</div>
        <div class="card-summary">{summary}</div>
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


def render_folder_cards(file_details: dict, folder_paths: dict,
                        key_prefix: str = 'dl'):
    """Render per-folder cards with filetype summary and Open Folder buttons.

    Args:
        file_details: Dict mapping folder_key -> list of filenames.
        folder_paths: Dict mapping folder_key -> absolute folder path string.
        key_prefix: Unique prefix for Streamlit widget keys ('dl' or 'sync').
    """
    import os
    has_files = any(len(files) > 0 for files in file_details.values())
    if not has_files:
        return

    st.markdown('<div class="completion-section-header">Folders Updated</div>', unsafe_allow_html=True)

    for idx, (folder_key, files) in enumerate(file_details.items()):
        if not files:
            continue

        folder_path = folder_paths.get(folder_key, '')
        folder_display = short_path(folder_path) if folder_path else folder_key

        with st.container(border=True):
            st.markdown(f"""<style>
            div[data-testid="stVerticalBlock"]:has(span#{key_prefix}_folder_{idx}) {{
                padding-top: 2px !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) {{
                align-items: center !important;
                gap: 15px !important;
                min-height: 0 !important;
                margin-bottom: 0px !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) div[data-testid="stColumn"] {{
                width: auto !important;
                flex: 0 0 auto !important;
                min-width: 0 !important;
                display: flex !important;
                align-items: center !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) div[data-testid="stMarkdownContainer"] {{
                margin: 0 !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) div[data-testid="stMarkdown"] {{
                display: flex !important;
                align-items: center !important;
                overflow: visible !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) div[data-testid="stElementContainer"] {{
                margin: 0 !important;
                overflow: visible !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) p {{
                margin: 0 !important;
                line-height: 1.4 !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) button {{
                border: 1px solid rgba(255,255,255,0.3) !important;
                padding: 4px 14px !important;
                font-size: 0.85rem !important;
                line-height: 1.4 !important;
                min-height: 0 !important;
                height: auto !important;
                transform: translateY(-2px) !important;
            }}
            </style>""", unsafe_allow_html=True)

            c1, c2, c3 = st.columns([1, 1, 1], vertical_alignment="center", gap="small")
            with c1:
                st.markdown(f'<span id="{key_prefix}_folder_{idx}"></span>**{folder_display}**', unsafe_allow_html=True)  # audit-ignore: folder_display is a local filesystem path
            with c2:
                if folder_path and Path(folder_path).exists():
                    if st.button('\U0001f4c2 Open folder', key=f"{key_prefix}_open_{idx}"):
                        open_folder(folder_path)
            with c3:
                st.empty()

            # Filetype breakdown summary instead of individual file list
            _render_filetype_summary(files, f"{key_prefix}_ft_{idx}")



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
}
_FILETYPE_SVG_DEFAULT = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%234b5563'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z'/%3E%3Cpath d='M14 2v6h6' fill='%239ca3af'/%3E%3C/svg%3E"


def _render_filetype_summary(files: list, key: str):
    """Render a compact filetype breakdown as pill badges."""
    import os
    from collections import Counter
    ext_counts = Counter()
    for f in files:
        ext = os.path.splitext(f)[1].lower().lstrip('.')
        ext_counts[ext or 'other'] += 1

    # Sort by count descending
    sorted_exts = sorted(ext_counts.items(), key=lambda x: -x[1])
    total = sum(ext_counts.values())

    pills_html = ''
    for ext, count in sorted_exts:
        icon_url = _FILETYPE_SVGS.get(ext, _FILETYPE_SVG_DEFAULT)
        pills_html += (
            f'<div class="filetype-pill">'
            f'<img class="ft-icon" src="{icon_url}" alt="{ext}"/>'
            f'<span class="ft-label">{esc(ext.upper())}</span>'
            f'<span class="ft-count">{count}</span>'
            f'</div>'
        )

    st.markdown(
        f'<div style="font-size:0.82em;color:#9ca3af;margin-bottom:4px;">{total} {"file" if total == 1 else "files"} downloaded</div>'
        f'<div class="filetype-summary">{pills_html}</div>',
        unsafe_allow_html=True,
    )


# --- Error type to human-friendly message mapping ---
_ERROR_TRANSLATIONS = {
    'No URL': 'This file has no download link on Canvas',
    'LTI/Media Stream': 'This is a streamed video that cannot be downloaded directly',
    'URL Expiration': 'The download link expired and could not be refreshed',
    'Network Error': 'Network connection failed after multiple retries',
    'Write Error': 'Could not save the file to disk',
    '401 Unauthorized': 'Access denied - you may not have permission to download this file',
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
                         retry_btn_callback=None, has_retriable_errors: bool = False):
    """Render error details as a custom CSS panel with human-friendly messages.

    Args:
        error_list: List of error messages or DownloadError objects.
        error_log_paths: Optional list of Path objects to download_errors.txt files.
        dialog_fn: Optional callable; if provided, called with error_log_paths.
        key_prefix: Unique prefix for Streamlit widget keys.
        retry_btn_callback: If provided, renders the retry button inside the panel.
        has_retriable_errors: Whether retriable errors exist (controls retry btn visibility).
    """
    if not error_list:
        return

    import os
    count = len(error_list)
    display_errors = error_list[:20]

    # Build error rows HTML
    rows_html = ''
    for err in display_errors:
        if hasattr(err, 'item_name'):
            fname = err.item_name or 'Unknown file'
            reason = _friendly_error_reason(err)
            ext = os.path.splitext(fname)[1].lower().lstrip('.')
            ext_badge = f'<span class="err-ext-badge">.{esc(ext)}</span>' if ext else ''
        else:
            fname = str(err)
            reason = ''
            ext_badge = ''

        rows_html += (
            f'<div class="error-row">'
            f'<img class="err-icon" src="{_ALERT_SVG}" alt="error"/>'
            f'<div class="err-body">'
            f'<div class="err-filename">{esc(fname)}{ext_badge}</div>'
        )
        if reason:
            rows_html += f'<div class="err-reason">{esc(reason)}</div>'
        rows_html += '</div></div>'

    if count > 20:
        rows_html += f'<div class="error-row" style="justify-content:center;color:#6b7280;font-size:0.82em;">... and {count - 20} more errors</div>'

    # Footer
    footer_html = ''
    if st.session_state.get('error_log_enabled', True):
        footer_html = '<div class="error-panel-footer">Full error details are saved in <code>download_errors.txt</code> in each course folder.</div>'

    # Render the custom panel via st.html (not iframe - use markdown)
    st.markdown(f"""
    <div class="error-panel">
        <div class="error-panel-header" onclick="this.parentElement.classList.toggle('collapsed');this.querySelector('.chevron').classList.toggle('open')">
            <img class="chevron open" src="{_CHEVRON_SVG}" alt="toggle"/>
            <span class="ep-title">Error Details</span>
            <span class="ep-badge">{count}</span>
        </div>
        <div class="error-panel-body">
            {rows_html}
            {footer_html}
        </div>
    </div>
    <style>
    .error-panel.collapsed .error-panel-body {{ display: none; }}
    </style>
    """, unsafe_allow_html=True)

    # Error log viewer button
    if error_log_paths and dialog_fn:
        valid_paths = [p for p in error_log_paths if p.exists()]
        if valid_paths:
            col_log, _ = st.columns([0.3, 0.7])
            with col_log:
                if st.button("View Full Error Log", key=f"{key_prefix}_view_error_log", use_container_width=True):
                    dialog_fn(valid_paths)

    # Retry button inside the error section
    if has_retriable_errors and retry_btn_callback:
        st.markdown("<div style='margin-top: 8px; margin-bottom: 8px;'></div>", unsafe_allow_html=True)
        col_retry, _ = st.columns([0.3, 0.7])
        with col_retry:
            if st.button("Retry Failed Items", type="secondary", key=f"{key_prefix}_retry_failed_btn",
                         use_container_width=True):
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
