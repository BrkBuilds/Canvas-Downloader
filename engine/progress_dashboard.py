"""
Progress Dashboard - Unified progress UI rendering for Canvas Downloader.

Provides shared HTML rendering functions used by both the download flow
(app.py) and the sync flow (sync_ui.py).  All Streamlit placeholders are
passed explicitly as arguments - never imported from global state.

Usage:
    from engine.progress_dashboard import (
        DashboardPlaceholders, render_progress_dashboard, render_terminal_log,
    )
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from html import escape as _html_escape

import theme

# ═══════════════════════════════════════════════
# SVG Icon Constants (inline, no emoji)
# ═══════════════════════════════════════════════

def _download_svg(color: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" '
        f'stroke-linejoin="round" style="display:inline-block;vertical-align:middle;'
        f'flex-shrink:0;margin-top:-1px">'
        f'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        f'<polyline points="7 10 12 15 17 10"/>'
        f'<line x1="12" y1="15" x2="12" y2="3"/>'
        f'</svg>'
    )

def _gear_svg(color: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round" style="display:inline-block;vertical-align:middle;'
        f'flex-shrink:0;margin-top:-1px">'
        f'<circle cx="12" cy="12" r="3"/>'
        f'<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06'
        f'a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09'
        f'A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83'
        f'l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09'
        f'A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83'
        f'l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09'
        f'a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83'
        f'l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09'
        f'a1.65 1.65 0 0 0-1.51 1z"/>'
        f'</svg>'
    )

_ACTIVE_FILE_PREFIXES = ('Downloading file: ', 'Created link: ', 'Creating link: ', 'Saved: ')

_LOG_MAX_LINES = 200


# ═══════════════════════════════════════════════
# Unified Log Line System
# ═══════════════════════════════════════════════
#
# Every log line in the app (download, sync, post-processing) is built through
# ``log_line`` / ``log_divider`` / ``log_meta`` so there is exactly ONE visual
# vocabulary.  The anatomy of a normal line is:
#
#     [status icon]  [content icon]  filename               dim detail →
#        colored        neutral       neutral white          right-aligned
#
# Color lives ONLY in the leading status glyph - the filename is always neutral.
# The status glyph IS the verb (no "Synced:"/"Recreated:"/"Converted:" prefixes).
# Meta lines (phase shifts) render as a centered divider instead of a row.

# -- Palette (status drives the single color cue) --------------------------------
_ICON_NEUTRAL = '#9aa3b2'   # content-type icons (subtle, never the focal color)
_DETAIL_COLOR = '#7d8597'   # dim right-aligned detail (sizes, retry counts, errors)
_DIVIDER_LINE = 'rgba(255,255,255,0.10)'

_STATUS_STYLE = {
    # status      -> (svg inner markup, stroke color)
    'success':   ('<circle cx="12" cy="12" r="9"/><polyline points="8.5 12.5 11 15 16 9"/>', theme.SUCCESS),
    'error':     ('<circle cx="12" cy="12" r="9"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>', theme.ERROR_LIGHT),
    'attention': ('<circle cx="12" cy="12" r="9"/><polyline points="12 7.5 12 12 15 13.5"/>', theme.WARNING),
    'skip':      ('<circle cx="12" cy="12" r="9"/><line x1="8" y1="12" x2="16" y2="12"/>', theme.TEXT_SECONDARY),
    'queued':    ('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>', theme.ACCENT_BLUE),
}

# -- Content-type icon registry (feather-style, themeable single stroke) ---------
_CONTENT_SVG = {
    'doc':          '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/>',
    'file':         '<path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/>',
    'ppt':          '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
    'excel':        '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/>',
    'video':        '<polygon points="22 7 16 12 22 17 22 7"/><rect x="2" y="5" width="14" height="14" rx="2"/>',
    'audio':        '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    'image':        '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    'archive':      '<polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/>',
    'web':          '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    'code':         '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    'link':         '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    'assignment':   '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4z"/>',
    'quiz':         '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    'discussion':   '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    'announcement': '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    'syllabus':     '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 0 3-3h7z"/>',
    'rubric':       '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
}

# File extension -> content kind.
_EXT_KIND = {
    '.pdf': 'doc', '.txt': 'doc', '.md': 'doc', '.rtf': 'doc', '.odt': 'doc',
    '.doc': 'doc', '.docx': 'doc', '.pages': 'doc',
    '.ppt': 'ppt', '.pptx': 'ppt', '.pptm': 'ppt', '.key': 'ppt', '.odp': 'ppt',
    '.xls': 'excel', '.xlsx': 'excel', '.xlsm': 'excel', '.csv': 'excel', '.ods': 'excel', '.tsv': 'excel',
    '.mp4': 'video', '.mov': 'video', '.avi': 'video', '.mkv': 'video', '.webm': 'video',
    '.m4v': 'video', '.wmv': 'video', '.flv': 'video',
    '.mp3': 'audio', '.wav': 'audio', '.m4a': 'audio', '.aac': 'audio', '.ogg': 'audio', '.flac': 'audio', '.wma': 'audio',
    '.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.gif': 'image', '.bmp': 'image',
    '.svg': 'image', '.webp': 'image', '.tiff': 'image', '.heic': 'image',
    '.zip': 'archive', '.rar': 'archive', '.7z': 'archive', '.tar': 'archive', '.gz': 'archive', '.bz2': 'archive',
    '.html': 'web', '.htm': 'web',
    '.url': 'link', '.webloc': 'link',
    '.py': 'code', '.js': 'code', '.ts': 'code', '.css': 'code', '.scss': 'code', '.java': 'code',
    '.c': 'code', '.cpp': 'code', '.h': 'code', '.cs': 'code', '.go': 'code', '.rb': 'code', '.php': 'code',
    '.json': 'code', '.xml': 'code', '.yaml': 'code', '.yml': 'code', '.sh': 'code', '.sql': 'code', '.ipynb': 'code',
}

# Canvas secondary-content entity type -> content kind.
_ENTITY_KIND = {
    'assignment': 'assignment', 'submission': 'assignment',
    'quiz': 'quiz',
    'discussion': 'discussion',
    'announcement': 'announcement',
    'syllabus': 'syllabus',
    'rubric': 'rubric',
    'page': 'doc',
    'external_url': 'link', 'url': 'link', 'link': 'link',
}


def _build_icon_svg(inner: str, color: str, size: int = 14, stroke_width: float = 2.0) -> str:
    """Assemble an inline feather-style SVG from inner markup."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'style="display:inline-block;vertical-align:middle;flex-shrink:0">{inner}</svg>'
    )


def status_icon_svg(status: str, size: int = 14) -> str:
    """Return the colored status glyph for one of: success/error/attention/skip/queued."""
    inner, color = _STATUS_STYLE.get(status, _STATUS_STYLE['success'])
    return _build_icon_svg(inner, color, size, stroke_width=2.3)


def file_icon_svg(filename: str, size: int = 14, color: str = _ICON_NEUTRAL) -> str:
    """Return a neutral content-type icon derived from a filename's extension."""
    ext = os.path.splitext(str(filename))[1].lower()
    kind = _EXT_KIND.get(ext, 'file')
    return _build_icon_svg(_CONTENT_SVG[kind], color, size)


def entity_icon_svg(entity_type: str, size: int = 14, color: str = _ICON_NEUTRAL) -> str:
    """Return a neutral content-type icon for a Canvas secondary entity type."""
    kind = _ENTITY_KIND.get(str(entity_type).lower().strip(), 'file')
    return _build_icon_svg(_CONTENT_SVG[kind], color, size)


def log_line(status: str, text: str, *, icon: str | None = None, detail: str | None = None,
             escape: bool = True) -> str:
    """Build one unified log row.

    status  : 'success' | 'error' | 'attention' | 'skip' | 'queued'
    text    : primary text (filename) - rendered neutral, escaped by default.
    icon    : optional pre-built content-type SVG (file_icon_svg / entity_icon_svg).
    detail  : optional dim, right-aligned suffix (size, "retry 2/3", "HTTP 503", ...).
    """
    safe = _html_escape(str(text)) if escape else str(text)
    content_svg = icon or ''
    detail_html = ''
    if detail:
        d = _html_escape(str(detail)) if escape else str(detail)
        detail_html = (
            f'<span style="padding-left:8px;color:{_DETAIL_COLOR};'
            f'font-size:0.82em;white-space:nowrap;flex-shrink:0">{d}</span>'
        )
    return (
        f'<div style="display:flex;align-items:center;gap:8px;padding:1px 2px;line-height:1.5;">'
        f'{status_icon_svg(status)}{content_svg}'
        f'<span style="color:{theme.TERMINAL_TEXT};overflow:hidden;text-overflow:ellipsis;'
        f'white-space:nowrap;min-width:0;flex:0 1 auto;">{safe}</span>'
        f'{detail_html}</div>'
    )


def log_divider(label: str) -> str:
    """Build a centered divider row (used for phase shifts / section breaks)."""
    safe = _html_escape(str(label))
    rule = f'<span style="flex:1;height:1px;background:{_DIVIDER_LINE};"></span>'
    return (
        f'<div style="display:flex;align-items:center;gap:10px;padding:6px 2px 5px;">'
        f'{rule}'
        f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.7rem;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.07em;white-space:nowrap;">{safe}</span>'
        f'{rule}</div>'
    )


def log_meta(text: str) -> str:
    """Build a quiet, centered meta line (transient notes: connecting, info)."""
    safe = _html_escape(str(text))
    return (
        f'<div style="display:flex;align-items:center;justify-content:center;padding:2px;">'
        f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.8em;font-style:italic;'
        f'opacity:0.9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{safe}</span>'
        f'</div>'
    )


# ═══════════════════════════════════════════════
# Active File Indicator
# ═══════════════════════════════════════════════

def render_active_file(placeholder, filename: str, phase: str = 'download') -> None:
    """Render the active-file indicator with SVG icon and left-accent card design.

    Replaces the old emoji-based 'Currently downloading:' label.
    phase: 'download' | 'postprocess'
    Strips Canvas callback prefixes ('Downloading file: ', etc.) automatically.
    """
    clean = str(filename)
    for pfx in _ACTIVE_FILE_PREFIXES:
        if clean.startswith(pfx):
            clean = clean[len(pfx):]
            break
    clean = _html_escape(clean)

    if phase == 'postprocess':
        color = '#f97316'
        label = 'Processing'
        icon = _gear_svg(color)
    else:
        color = theme.ACCENT_LINK
        label = 'Downloading'
        icon = _download_svg(color)

    placeholder.markdown(f'''
    <div style="display:flex; align-items:center; gap:10px; padding:8px 14px;
        background:rgba(255,255,255,0.04);
        border-radius:6px; margin-bottom:12px; overflow:hidden;">
      {icon}
      <div style="overflow:hidden; min-width:0; flex:1;">
        <div style="color:{color}; font-size:0.7rem; font-weight:700;
            text-transform:uppercase; letter-spacing:0.06em; line-height:1; margin-bottom:4px;">{label}</div>
        <div style="color:{theme.TEXT_PRIMARY}; font-size:0.875rem; font-weight:500;
            background:rgba(255,255,255,0.05); padding:2px 8px; border-radius:4px;
            overflow:hidden; text-overflow:ellipsis; white-space:nowrap; line-height:1.5;">{clean}</div>
      </div>
    </div>
    ''', unsafe_allow_html=True)


# ═══════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════

@dataclass
class DashboardPlaceholders:
    """Encapsulates the five Streamlit st.empty() slots that make up the
    progress dashboard.  Passed explicitly into every render call so the
    engine never touches global UI state.
    """
    header: object          # st.empty() - course name + phase label
    progress: object        # st.empty() - progress bar
    metrics: object         # st.empty() - 4-metric row (downloaded/speed/files/eta)
    active_file: object     # st.empty() - "Currently downloading: …"
    log: object             # st.empty() - terminal log widget


@dataclass
class DashboardMetrics:
    """Pure-data container holding all values needed to render a single
    frame of the dashboard.
    """
    current_files: int = 0
    total_files: int = 1
    downloaded_mb: float = 0.0
    total_mb: float = 0.0
    speed_mb_s: float = 0.0
    eta_string: str = "--:--"
    percent: int = 0
    # Header content
    header_label: str = "Downloading Courses"
    course_name: str = ""


# ═══════════════════════════════════════════════
# Render Functions
# ═══════════════════════════════════════════════

def render_progress_header(placeholders: DashboardPlaceholders, label: str, course_name: str) -> None:
    """Render the header section (phase label + course name)."""
    placeholders.header.markdown(f'''
    <div style="margin-bottom: 0.5rem;"><!-- # audit-ignore: label is app-controlled phase text -->
        <p style="margin: 0; font-size: 0.8rem; color: {theme.TEXT_SECONDARY}; text-transform: uppercase;">{label}</p>
        <h3 style="margin: 0; padding-top: 0.1rem; color: {theme.TEXT_PRIMARY};">{_html_escape(course_name)}</h3>
    </div>
    ''', unsafe_allow_html=True)


def render_progress_bar(placeholders: DashboardPlaceholders, percent: int) -> None:
    """Render the custom HTML progress bar."""
    placeholders.progress.markdown(f'''
    <div style="background-color: {theme.BG_CARD}; border-radius: 8px; width: 100%; height: 24px; position: relative; margin-bottom: 10px;">
        <div style="background-color: {theme.ACCENT_BLUE}; width: {percent}%; height: 100%; border-radius: 8px; transition: width 0.3s ease;"></div>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold;">
            {percent}%
        </div>
    </div>
    ''', unsafe_allow_html=True)


def render_metrics_row(
    placeholders: DashboardPlaceholders,
    downloaded_mb: float,
    total_mb: float,
    speed_mb_s: float,
    current_files: int,
    total_files: int,
    eta_string: str,
    *,
    show_total_mb: bool = True,
) -> None:
    """Render the 4-metric row (Downloaded / Speed / Files / ETA).

    When ``show_total_mb`` is False the "Downloaded" column omits the
    "/ X.X MB" denominator (used by the retry dashboard where total_mb
    is not always meaningful).
    """
    mb_display = (
        f"{downloaded_mb:.1f} <span style=\"font-size: 0.9rem; color: {theme.ACCENT_BLUE};\">/ {total_mb:.1f} MB</span>"
        if show_total_mb
        else f"{downloaded_mb:.1f} <span style=\"font-size: 0.9rem; color: {theme.ACCENT_BLUE};\">MB</span>"
    )

    placeholders.metrics.markdown(f'''
    <div style="display: flex; justify-content: center; gap: 4rem; background-color: {theme.BG_DARK}; padding: 15px 25px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-top: 5px; margin-bottom: 15px;">
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Downloaded</span>
            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{mb_display}</span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Speed</span>
            <span style="color: #10B981; font-size: 1.2rem; font-weight: bold;">{speed_mb_s:.1f} <span style="font-size: 0.9rem;">MB/s</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Files</span>
            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{current_files} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {total_files}</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Time Remaining</span>
            <span style="color: #F59E0B; font-size: 1.2rem; font-weight: bold;">{eta_string}</span>
        </div>
    </div>
    ''', unsafe_allow_html=True)


def render_terminal_log(placeholders: DashboardPlaceholders, log_deque) -> None:
    """Render the terminal-style log widget from a deque of unified log-line HTML."""
    placeholders.log.markdown(build_terminal_html(log_deque), unsafe_allow_html=True)


# ═══════════════════════════════════════════════
# Convenience: Full Dashboard Render
# ═══════════════════════════════════════════════

def render_full_dashboard(
    placeholders: DashboardPlaceholders,
    log_deque,
    *,
    header_label: str,
    course_name: str,
    current_files: int,
    total_files: int,
    downloaded_mb: float,
    total_mb: float,
    start_time: float,
    show_total_mb: bool = True,
) -> None:
    """One-call convenience that renders header + progress bar + metrics + log.

    Computes percent, speed, and ETA from the provided raw values.
    """
    # Percent
    if total_files > 0:
        percent = int((current_files / total_files) * 100)
        percent = min(100, percent)
        if current_files >= total_files:
            percent = 100
    else:
        percent = 0

    # Speed & ETA
    elapsed = time.time() - start_time
    speed_mb_s = (downloaded_mb / elapsed) if elapsed > 0 else 0.0
    remaining_mb = max(0, total_mb - downloaded_mb)
    eta_seconds = (remaining_mb / speed_mb_s) if speed_mb_s > 0 else 0
    eta_string = time.strftime('%M:%S', time.gmtime(max(0, eta_seconds)))

    render_progress_header(placeholders, header_label, course_name)
    render_progress_bar(placeholders, percent)
    render_metrics_row(
        placeholders,
        downloaded_mb=downloaded_mb,
        total_mb=total_mb,
        speed_mb_s=speed_mb_s,
        current_files=current_files,
        total_files=total_files,
        eta_string=eta_string,
        show_total_mb=show_total_mb,
    )
    render_terminal_log(placeholders, log_deque)


# ═══════════════════════════════════════════════
# Sync-specific HTML helpers (return strings instead of writing to placeholders)
# ═══════════════════════════════════════════════

def build_metrics_html(
    current_files: int,
    total_files: int,
    downloaded_mb: float,
    total_mb: float,
    speed_mb_s: float,
    eta_string: str,
) -> str:
    """Return the metrics-row HTML as a string (for sync_ui.py which uses
    placeholder.markdown(html) directly).
    """
    return f"""
    <div style="display: flex; justify-content: center; gap: 4rem; background-color: {theme.BG_DARK}; padding: 15px 25px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-top: 5px; margin-bottom: 15px;">
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Downloaded</span>
            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{downloaded_mb:.1f} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {total_mb:.1f} MB</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Speed</span>
            <span style="color: #10B981; font-size: 1.2rem; font-weight: bold;">{speed_mb_s:.1f} <span style="font-size: 0.9rem;">MB/s</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Files</span>
            <span style="color: {theme.TEXT_PRIMARY}; font-size: 1.2rem; font-weight: bold;">{current_files} <span style="font-size: 0.9rem; color: {theme.ACCENT_BLUE};">/ {total_files}</span></span>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center;">
            <span style="color: {theme.TEXT_SECONDARY}; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;">Time Remaining</span>
            <span style="color: #F59E0B; font-size: 1.2rem; font-weight: bold;">{eta_string}</span>
        </div>
    </div>
    """


def build_terminal_html(lines) -> str:
    """Return the terminal-log HTML as a string (single source of truth for all flows).

    Lines are unified log-line HTML (block flex rows / dividers) built via
    ``log_line`` / ``log_divider`` / ``log_meta``, stacked newest-first with no
    ``<br>`` separators (each row is already a block element).
    """
    if lines:
        body = "".join(reversed(list(lines)[-_LOG_MAX_LINES:]))
    else:
        body = (
            f"<div style='display:flex;align-items:center;justify-content:center;height:100%;"
            f"color:{theme.TEXT_SECONDARY};font-style:italic;'>Waiting for files…</div>"
        )
    return (
        f'<div style="background:{theme.BG_TERMINAL}; border:1px solid {theme.BORDER_TERMINAL}; '
        f'border-radius:8px; padding:13px 15px; '
        f"font-family:'Inter', system-ui, -apple-system, sans-serif; font-size:0.85rem; "
        f'color:{theme.TERMINAL_TEXT}; height:160px; overflow:hidden; '
        f'box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);">{body}</div>'
    )
