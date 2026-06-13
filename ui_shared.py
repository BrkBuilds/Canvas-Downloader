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

# --- Professional inline SVG icons for help card section headers ---
# Feather-style stroke icons. Use inside help card text_html to replace emojis.
# Sized at 18×18 with themed stroke colors for consistency.
_ICON_STYLE = 'display:inline-block;vertical-align:middle;position:relative;top:-1px;margin:0 4px;flex-shrink:0;'

# Inline SVG paths for each icon - keyed by Material icon name.
# Eliminates the Google Fonts dependency so icons work in the packaged app
# regardless of network access or font-load timing.
_MAT_SVG_INNER: dict[str, str] = {
    'lightbulb': "<line x1='9' y1='18' x2='15' y2='18'/><line x1='10' y1='22' x2='14' y2='22'/><path d='M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z'/>",
    'folder':    "<path d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'/>",
    'shield':    "<path d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/>",
    'database':  "<ellipse cx='12' cy='5' rx='9' ry='3'/><path d='M21 12c0 1.66-4 3-9 3s-9-1.34-9-3'/><path d='M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5'/>",
    'build':     "<path d='M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z'/>",
    'help':      "<circle cx='12' cy='12' r='10'/><path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3'/><line x1='12' y1='17' x2='12.01' y2='17'/>",
    'star':      "<polygon points='12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2'/>",
    'inventory_2': "<path d='M21 8V21H3V8'/><rect x='1' y='3' width='22' height='5'/><line x1='10' y1='12' x2='14' y2='12'/>",
    'check_circle': "<path d='M22 11.08V12a10 10 0 1 1-5.93-9.14'/><polyline points='22 4 12 14.01 9 11.01'/>",
    'arrow_selector_tool': "<path d='M5 3l14 9-7 1-4 7z'/>",
    'visibility': "<path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'/><circle cx='12' cy='12' r='3'/>",
    'archive':   "<polyline points='21 8 21 21 3 21 3 8'/><rect x='1' y='3' width='22' height='5'/><line x1='10' y1='12' x2='14' y2='12'/>",
    'menu':      "<line x1='3' y1='12' x2='21' y2='12'/><line x1='3' y1='6' x2='21' y2='6'/><line x1='3' y1='18' x2='21' y2='18'/>",
    'calendar_today': "<rect x='3' y='4' width='18' height='18' rx='2' ry='2'/><line x1='16' y1='2' x2='16' y2='6'/><line x1='8' y1='2' x2='8' y2='6'/><line x1='3' y1='10' x2='21' y2='10'/>",
    'error':     "<circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='12'/><line x1='12' y1='16' x2='12.01' y2='16'/>",
}

def inject_material_icons_font() -> None:
    """No-op - Material Symbols font replaced by inline SVGs (issue 2 fix)."""
    pass

def _mat(icon_name: str, color: str = '#38BDF8', size: int = 18) -> str:
    """Return an inline SVG icon. Replaces the Google Material Symbols font approach."""
    inner = _MAT_SVG_INNER.get(icon_name, _MAT_SVG_INNER['help'])
    adj = size + 4
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'width="{adj}" height="{adj}" style="{_ICON_STYLE}">'
        f'{inner}</svg>'
    )

def _img(filename, size=18):
    from ui_helpers import get_base64_image
    b64 = get_base64_image(f"assets/{filename}")
    mime = "image/svg+xml" if filename.lower().endswith('.svg') else "image/png"
    return f'<img src="data:{mime};base64,{b64}" width="{size}" height="{size}" style="{_ICON_STYLE} top: -2px;" />'

def _build_help_icons() -> dict:
    return {
        'lightbulb': _mat('lightbulb'),
        'folder': _mat('folder'),
        'gear': _img('icon_custom_download.png'),
        'bolt': _img('icon_sync_quick.png'),
        'bolt_small': _img('icon_sync_quick.png', size=11),
        'search': _img('icon_sync_review.png'),
        'search_small': _img('icon_sync_review.png', size=11),
        'save': _img('icon_preset_user.png'),
        'quick_download': _img('icon_quick_download.png'),
        'shield': _mat('shield'),
        'download': _img('icon_download.png'),
        'database': _mat('database'),
        'wrench': _mat('build'),
        'question': _mat('help'),
        'star': _mat('star'),
        'warning': '⚠️',
        'package': _mat('inventory_2'),
        'check_circle': _mat('check_circle'),
        'cursor': _mat('arrow_selector_tool'),
        'eye': _mat('visibility'),
        'refresh': _img('icon_sync.png'),
        'compare': _img('icon_sync_pair.png'),
        'archive': _mat('archive'),
        'menu': _mat('menu'),
        'folder_open': _img('icon_preset_builtin.png'),
        'restore': _img('icon_restore.png', size=16),
        'calendar': _mat('calendar_today', color='#bac2cc'),
        'error': _mat('error', color='#ff7b72'),
        'sync_hub': _img('icon_sync_hub.png'),
        'sync_pair': _img('icon_sync_pair.png'),
        'sync_group': _img('icon_sync_group.png'),
        # Sync Review Category Assets
        'cat_new': _img('Icon_Sync_Review_New_File.png', size=16),
        'cat_update': _img('Icon_Sync_Review_Update.png', size=16),
        'cat_miss': _img('Icon_Sync_Review_Missing_File.png', size=16),
        'cat_locdel': _img('Icon_Sync_Review_Locally_Deleted.png', size=16),
        'cat_candel': _img('Icon_Sync_Review_Deleted_On_Canvas.png', size=16),
        'cat_ignore': _img('Icon_Ignore.svg', size=16),
        'cat_uptodate': _mat('check_circle', color='#10B981', size=16),
    }

# Lazy singleton - computed on first access so missing assets at import time
# don't permanently bake broken icons into the cache (M-23).
_HELP_ICONS_CACHE: dict | None = None

class _LazyHelpIcons:
    """Dict-like proxy that builds HELP_ICONS on first access."""
    def __getitem__(self, key: str) -> str:
        global _HELP_ICONS_CACHE
        if _HELP_ICONS_CACHE is None:
            _HELP_ICONS_CACHE = _build_help_icons()
        return _HELP_ICONS_CACHE[key]

    def get(self, key: str, default=None):
        global _HELP_ICONS_CACHE
        if _HELP_ICONS_CACHE is None:
            _HELP_ICONS_CACHE = _build_help_icons()
        return _HELP_ICONS_CACHE.get(key, default)

    def __contains__(self, key: str) -> bool:
        global _HELP_ICONS_CACHE
        if _HELP_ICONS_CACHE is None:
            _HELP_ICONS_CACHE = _build_help_icons()
        return key in _HELP_ICONS_CACHE

HELP_ICONS = _LazyHelpIcons()


def render_completion_card(synced_count: int, error_count: int,
                           total_bytes: int, mode: str = 'download',
                           size_skipped_files: list = None, size_limit_mb: int = 0,
                           retry_attempted: bool = False, retry_resolved: int = 0,
                           retry_total: int = 0,
                           retriable_count: int = 0,
                           unresolvable_count: int = 0,
                           app_error_count: int = 0,
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
        _card_title = 'All Up to Date'
        if mode == 'sync':
            _is_qs = st.session_state.get('sync_quick_mode', False)
            _card_title = 'Quick Sync done! All files up to date' if _is_qs else 'Sync done! All files up to date'

        st.markdown(
            "<div class='completion-card success'>"
            f"<div class='card-title'>{_card_title}</div>"
            f"<p style='color:#86efac;font-size:1rem;margin:8px 0 0;'>"
            f"Nothing to {_label} - all files are up to date!"
            "</p></div>",
            unsafe_allow_html=True,
        )
        if mode == 'download':
            st.markdown(
                "<div style='"
                "display:flex;align-items:flex-start;gap:10px;"
                "background:rgba(245,158,11,0.1);"
                "border:1px solid rgba(245,158,11,0.3);"
                "border-radius:8px;padding:12px 14px;margin-top:14px;"
                "'>"
                "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
                "stroke='#f59e0b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' "
                "style='width:18px;height:18px;flex-shrink:0;margin-top:2px;'>"
                "<path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'></path>"
                "<line x1='12' y1='9' x2='12' y2='13'></line>"
                "<line x1='12' y1='17' x2='12.01' y2='17'></line>"
                "</svg>"
                "<div>"
                "<div style='color:#fbbf24;font-weight:600;font-size:0.88em;margin-bottom:3px;'>"
                "No files were found - possible connection issue"
                "</div>"
                "<p style='color:#d1d5db;font-size:0.82em;margin:0;line-height:1.5;'>"
                "Your Canvas account connected successfully, but no files or modules were returned. "
                "This can happen when your API token is geo-restricted (accessing from a different country than usual), "
                "when a firewall or VPN is affecting the connection to your university's server, "
                "or during a temporary Canvas outage. "
                "Try again on your usual network."
                "</p>"
                "</div>"
                "</div>",
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

    # Conditional error stat cards - split by retriable vs unresolvable vs app-level
    _warning_icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'></path><line x1='12' y1='9' x2='12' y2='13'></line><line x1='12' y1='17' x2='12.01' y2='17'></line></svg>"
    if retriable_count > 0 or unresolvable_count > 0 or app_error_count > 0:
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
f'<div class="stat-label">Cannot Be Downloaded</div>'
'</div>'
'</div>'
            )
        if app_error_count > 0:
            stats_html += (
'<div class="stat-card stat-app-error">'
f'<div class="stat-icon-wrapper">{_warning_icon}</div>'
'<div class="stat-info">'
f'<div class="stat-value">{app_error_count}</div>'
f'<div class="stat-label">{"App Error" if app_error_count == 1 else "App Errors"}</div>'
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



_FC_FOLDER_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'"
    " viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'"
    " stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'/%3E"
    "%3C/svg%3E"
)
_FC_CHEVRON_SVG = (
    "<svg class='ft-chevron' xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'"
    " width='16' height='16'"
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
            f'<div class="fc-folder-icon" style="font-size:1.15rem; line-height:1; display:flex; align-items:center; justify-content:center; opacity:1;">📁</div>'
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

    WHITELIST = {'pdf', 'docx', 'pptx', 'xlsx', 'zip', 'mp4', 'mp3', 'js', 'html', 'css', 'txt', 'sql', 'jpg', 'png', 'doc', 'ppt', 'xls', 'md', 'csv', 'json', 'py', 'java', 'c', 'cpp', 'webloc', 'url'}

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
            f'<span class="ft-label">Other files</span>'
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
    'SSL Certificate Error': 'Your computer could not verify the secure connection to Canvas - check for a VPN, proxy or firewall intercepting traffic, or update Canvas Downloader',
    'Write Error': 'Could not save the file to disk - check available storage',
    '401 Unauthorized': 'Access denied - you may not have permission to download this file',
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
            if api_url and not api_url.startswith(('http://', 'https://')):
                api_url = ''
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
                    link_html = f'<a href="{esc(canvas_url)}" target="_blank" rel="noopener noreferrer" class="err-link-btn" title="Open in Canvas">{_LINK_SVG}</a>'

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

    # Split into: retriable file errors / unresolvable file errors / app-level errors
    actionable, unresolvable, app_errors = [], [], []
    for err in error_list[:20]:
        if getattr(err, 'is_app_error', False):
            app_errors.append(err)
            continue
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

    # App-level errors: separate section below the file columns
    if app_errors:
        _WARN_SVG = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='width:15px;height:15px;flex-shrink:0;margin-top:1px;'><path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'/><line x1='12' y1='9' x2='12' y2='13'/><line x1='12' y1='17' x2='12.01' y2='17'/></svg>"
        app_rows_html = ''
        for err in app_errors:
            error_type = esc(getattr(err, 'error_type', 'Application Error') or 'Application Error')
            course_name = esc(getattr(err, 'course_name', '') or '')
            message = esc(getattr(err, 'message', '') or '')
            # Truncate long technical messages
            if len(message) > 220:
                message = message[:220] + '…'
            course_prefix = f'<span class="app-err-course">{course_name}</span> ' if course_name else ''
            app_rows_html += (
                f'<div class="app-error-row">'
                f'<div class="app-err-type-badge">{error_type}</div>'
                f'<div class="app-err-detail">'
                f'{course_prefix}'
                f'<span class="app-err-msg">{message}</span>'
                f'</div>'
                f'</div>'
            )
        body_html += (
            f'<div class="app-error-section">'
            f'<div class="app-error-section-header">'
            f'{_WARN_SVG}'
            f'<span class="app-error-section-title">Application Errors</span>'
            f'<span class="err-group-badge err-group-badge-warn">{len(app_errors)}</span>'
            f'</div>'
            f'<div class="app-error-section-subtitle">The download engine encountered internal errors. Check your settings and API connection, then try again.</div>'
            f'{app_rows_html}'
            f'</div>'
        )

    if count > 20:
        body_html += f'<div style="padding:6px 0;color:#6b7280;font-size:0.82em;">... and {count - 20} more errors</div>'

    # Footer
    footer_html = ''
    if st.session_state.get('error_log_enabled', False):
        footer_html = '<div class="error-panel-footer">Full error details are saved in <code>download_errors.txt</code> in each course folder.</div>'

    st.markdown(
        f'<details class="error-panel" open>'
        f'<summary class="error-panel-header">'
        f'<div class="ep-header-row">'
        f'<img class="chevron" src="{_CHEVRON_SVG}" alt="toggle"/>'
        f'<span class="ep-title">Error Details</span>'
        f'</div>'
        f'</summary>'
        f'<div class="error-panel-body">'
        f'{body_html}{footer_html}'
        f'</div>'
        f'</details>',
        unsafe_allow_html=True,
    )

    # Error log viewer button
    if error_log_paths and dialog_fn:
        valid_paths = [p for p in error_log_paths if p.exists()]
        if valid_paths:
            col_log, _ = st.columns([0.3, 0.7])
            with col_log:
                if st.button("View Full Error Log", key=f"{key_prefix}_view_error_log", use_container_width=True):
                    dialog_fn(valid_paths)

    # Retry button - placed in half-width left column under the error panel
    # so it visually associates with the "Failed to Download" column only.
    if has_retriable_errors and retry_btn_callback:
        retriable_count = sum(
            1 for err in error_list
            if not getattr(err, 'is_app_error', False)
            and isinstance(getattr(err, 'context', None), dict)
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
        from ui.amber_notice import render_amber_notice
        word = "file" if pp_failure_count == 1 else "files"
        detail_hint = "Check download_errors.txt for details." if st.session_state.get('error_log_enabled', False) else "Enable error logging in settings to capture details."
        render_amber_notice(
            f"{pp_failure_count} {word} failed during post-processing (conversion/extraction).",
            detail=detail_hint,
        )

def render_config_summary_badges(settings: dict, show_path: bool = True) -> str:
    """Render a rich HTML preview of active settings using color-coded badges."""
    # Build Blue Core Badges
    _mode_disp = "With Subfolders" if settings.get('download_mode') == 'modules' else "All in One Folder"
    _filter_disp = "All Files" if settings.get('file_filter') == 'all' else "Slides & PDFs"
    
    c_core = "#3fd9ff"
    core_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#ffffff; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>Core Settings</div>
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
    <div style='width: 100%; font-size:0.8rem; color:#ffffff; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>Canvas Content</div>
    {sec_badges}
</div>
"""
    
    # Build Orange AI Optimization Badges
    c_ai = "#FF9838"
    conv_mapping = {
        'convert_zip': 'Unpack Archives (.zip)',
        'convert_pptx': 'PPTX ➡ PDF',
        'convert_word': 'Legacy Word ➡ PDF',
        'convert_excel': 'Excel ➡ PDF & AI Data',
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
    <div style='width: 100%; font-size:0.8rem; color:#ffffff; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>AI Optimization & Conversions</div>
    {conv_badges}
</div>
"""
    
    path_html = ""
    if show_path and settings.get('download_path'):
        path_html = f"""
<div style='margin-bottom:4px;'>
    <div style='font-size:0.8rem; color:#ffffff; font-weight:600; text-transform:uppercase; margin-bottom:4px;'>Saved Path</div>
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
            div[data-testid="stDialog"] div.st-key-error_log_scroll_shared {
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


def render_help_card(key_prefix: str, title: str, text_html: str, icon: str = "", mode: str = "auto"):
    """
    Renders a unified Help Explainer Card component.
    
    Args:
        key_prefix: Unique string to namespace CSS classes and session state.
        title: Title of the explainer card.
        text_html: The HTML body content of the explainer card.
        icon: The emoji/icon prefix for the title.
        mode: "auto" (default), "button" (only trigger), or "card" (only expanded content).
    """
    import base64
    from ui_helpers import esc
    
    state_key = f"show_help_card_{key_prefix}"
    if state_key not in st.session_state:
        st.session_state[state_key] = False

    # Logic to determine what to show based on mode and state
    is_open = st.session_state[state_key]
    show_button = (mode in ["auto", "button"])
    show_card = (mode in ["auto", "card"]) and is_open

    close_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>'
    close_b64 = base64.b64encode(close_svg.encode()).decode()
    
    help_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>'
    help_b64 = base64.b64encode(help_svg.encode()).decode()

    card_key = f"{key_prefix}_explainer_card"
    close_key = f"{key_prefix}_close_explainer"
    help_btn_key = f"{key_prefix}_explainer_help_btn"
    open_key = f"{key_prefix}_open_explainer"

    if show_card:
        with st.container(key=card_key):
            if st.button("✕", key=close_key):
                st.session_state[state_key] = False
                st.rerun()
            
            # Determine icon HTML: SVG content rendered directly, empty string skipped, fallback to emoji span
            if not icon:
                _icon_html = HELP_ICONS.get('lightbulb', '')
            elif icon.strip().startswith('<svg') or icon.strip().startswith('<img'):
                _icon_html = icon
            else:
                _icon_html = f'<span style="font-size: 1.1rem; line-height: 1;">{icon}</span>'

            st.markdown(f"""
            <div>
                <p style="margin: 0 0 12px 0; font-weight: 700; color: #ffffff; font-size: 1.25rem; display: flex; align-items: center; gap: 8px;">
                    {_icon_html}{esc(title)}
                </p>
                <div style="margin: 0; font-size: 0.9rem; color: rgba(255, 255, 255, 0.92); line-height: 1.5;">
                    {text_html}
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.html(f"""<style>
        @keyframes slideDownFadeIn_{key_prefix} {{
            from {{ opacity: 0; transform: translateY(-8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        div.st-key-{card_key} {{
            background-color: rgba(255, 255, 255, 0.05) !important;
            border: 1px solid rgba(255, 255, 255, 0.15) !important;
            border-radius: 8px !important;
            padding: 16px 16px 32px 16px !important;
            margin-bottom: 15px !important;
            box-shadow: 0 12px 30px rgba(0, 0, 0, 0.4) !important;
            position: relative !important;
            animation: slideDownFadeIn_{key_prefix} 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }}
        div.st-key-{card_key} div.element-container {{
            margin-bottom: 0 !important;
        }}
        div.st-key-{card_key} p:last-child {{
            margin-bottom: 0 !important;
        }}
        div.st-key-{card_key} > div[data-testid="stVerticalBlockBorderWrapper"] {{
            border: none !important;
            padding: 0 !important;
        }}
        div.st-key-{close_key} {{
            position: absolute !important;
            top: 8px !important;
            right: 8px !important;
            z-index: 10 !important;
        }}
        div.st-key-{close_key} button {{
            background: transparent !important;
            border: none !important;
            color: #94a3b8 !important;
            font-size: 1.2rem !important;
            box-shadow: none !important;
            padding: 0 !important;
            min-height: 28px !important;
            height: 28px !important;
            width: 28px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            border-radius: 6px !important;
            transition: all 0.15s ease !important;
        }}
        div.st-key-{close_key} button:hover {{
            color: #f8fafc !important;
            background: transparent !important;
        }}
        div.st-key-{close_key} button > div {{
            display: none !important;
        }}
        div.st-key-{close_key} button::before {{
            content: "";
            display: block;
            width: 16px;
            height: 16px;
            background-color: #94a3b8;
            -webkit-mask-image: url('data:image/svg+xml;base64,{close_b64}');
            mask-image: url('data:image/svg+xml;base64,{close_b64}');
            -webkit-mask-size: contain;
            mask-size: contain;
            -webkit-mask-repeat: no-repeat;
            mask-repeat: no-repeat;
            -webkit-mask-position: center;
            mask-position: center;
            transition: background-color 0.15s ease !important;
        }}
        div.st-key-{close_key} button:hover::before {{
            background-color: #f8fafc !important;
        }}
        </style>""")
    
    if show_button:
        with st.container(key=help_btn_key):
            if st.button("Help", key=open_key, help="Click to open guide"):
                st.session_state[state_key] = not st.session_state[state_key]
                st.rerun()

        # Adjust alignment based on mode: "auto" is usually top-right (flex-end), 
        # whereas manual triggers might need flex-start.
        justify_content = "flex-end" if mode == "auto" else "flex-start"
        margin_bottom = "25px" if mode == "auto" else "0px"

        st.html(f"""<style>
        @keyframes fadeInHelp_{key_prefix} {{
            from {{ opacity: 0; transform: translateX(8px); }}
            to {{ opacity: 1; transform: translateX(0); }}
        }}
        div.st-key-{help_btn_key} {{
            margin-bottom: {margin_bottom} !important;
            display: flex !important;
            justify-content: {justify_content} !important;
            animation: fadeInHelp_{key_prefix} 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }}
        div.st-key-{help_btn_key} > div[data-testid="stVerticalBlockBorderWrapper"] {{
            border: none !important;
            padding: 0 !important;
        }}
        div.st-key-{open_key} button {{
            background: transparent !important;
            border: none !important;
            padding: 4px 8px !important;
            min-height: 24px !important;
            height: 24px !important;
            color: #a8b4c6 !important;
            font-weight: 500 !important;
            font-size: 0.9rem !important;
            transition: all 0.2s ease !important;
            box-shadow: none !important;
        }}
        div.st-key-{open_key} button:hover {{
            background: transparent !important;
            color: #f8fafc !important;
        }}
        div.st-key-{open_key} button p::before {{
            content: "";
            display: inline-block;
            width: 16px;
            height: 16px;
            margin-right: 6px;
            background-color: #a8b4c6;
            -webkit-mask-image: url('data:image/svg+xml;base64,{help_b64}');
            mask-image: url('data:image/svg+xml;base64,{help_b64}');
            -webkit-mask-size: contain;
            mask-size: contain;
            -webkit-mask-repeat: no-repeat;
            mask-repeat: no-repeat;
            -webkit-mask-position: center;
            mask-position: center;
            vertical-align: middle;
            position: relative;
            /* rely on vertical-align: middle */
            transition: background-color 0.2s ease !important;
        }}
        div.st-key-{open_key} button:hover p::before {{
            background-color: #f8fafc !important;
        }}
        </style>""")

