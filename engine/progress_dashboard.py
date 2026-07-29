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

import math
import os
from dataclasses import dataclass
from html import escape as _html_escape

from shared import theme

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


def search_svg(color: str, size: int = 13) -> str:
    """The app's magnifying-glass icon. Public so the analysis screens can reuse
    the SAME glyph the phase stepper uses, instead of a lookalike emoji."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" '
        f'stroke-linejoin="round" style="display:inline-block;vertical-align:middle;'
        f'flex-shrink:0;margin-top:-1px">'
        f'<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>'
        f'</svg>'
    )


# Back-compat alias for the PHASE_* tables below.
_search_svg = search_svg


# NOTE: ``analyzing_heading_html`` used to live here - an h4 + search glyph that
# was the analysis screens' entire chrome. Those screens now render through
# ``render_analysis_dashboard`` (same header / bar / metrics row as every other
# phase), so the bespoke heading has no call sites left. The search glyph itself
# survives as ``search_svg``: the phase stepper and the active-file indicator
# both still use it.


def _transcribe_svg(color: str) -> str:
    # Speech / waveform glyph for the local transcription phase.
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2.3" stroke-linecap="round" '
        f'stroke-linejoin="round" style="display:inline-block;vertical-align:middle;'
        f'flex-shrink:0;margin-top:-1px">'
        f'<line x1="4" y1="10" x2="4" y2="14"/><line x1="8" y1="6" x2="8" y2="18"/>'
        f'<line x1="12" y1="9" x2="12" y2="15"/><line x1="16" y1="4" x2="16" y2="20"/>'
        f'<line x1="20" y1="10" x2="20" y2="14"/>'
        f'</svg>'
    )


# Per-phase visual identity for the active-file indicator AND progress bar.
# Each phase owns a distinct colour so the user can tell, at a glance, whether
# the app is searching, downloading regular files, downloading Panopto audio,
# transcribing, or post-processing.
#   color           label          icon builder
_PHASE_STYLE = {
    'download':    (theme.ACCENT_LINK, 'Downloading',  _download_svg),
    'postprocess': ('#f97316',         'Processing',   _gear_svg),
    'search':      ('#60a5fa',         'Searching',    _search_svg),
    'panopto':     ('#a855f7',         'Downloading',  _download_svg),
    'transcribe':  ('#2dd4bf',         'Transcribing', _transcribe_svg),
}

# Progress-bar colour per phase (kept separate so a phase can recolour the bar
# even when it does not own an active-file card).
PHASE_BAR_COLOR = {
    'download':    theme.ACCENT_BLUE,
    'postprocess': '#f97316',
    'search':      '#60a5fa',
    'panopto':     '#a855f7',
    'transcribe':  '#2dd4bf',
}

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
_DETAIL_COLOR = '#7c8496'   # dim right-aligned detail (sizes, retry counts, errors)
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

def _row_gap(last: bool) -> str:
    """The bottom margin a dashboard row carries, given whether it is the last one.

    The card sets `gap: 0` and an even 18 px inset on all four sides, so every
    row buys its own separation from the row below with a bottom margin. That is
    correct until the row IS the bottom one, at which point its margin lands on
    top of the card's padding and the card reads as bottom-heavy: the analysis
    dashboard has no terminal log, so its active-file card was the last element
    and sat 12 + 18 = 30 px off the edge against 18 px on the sides. Whichever
    row happens to be last asks for zero here instead of the card having to know
    which phase is running.
    """
    return '0' if last else '12px'


def render_active_file(placeholder, filename: str, phase: str = 'download',
                       *, label: str | None = None, last: bool = False) -> None:
    """Render the active-file indicator with SVG icon and left-accent card design.

    Replaces the old emoji-based 'Currently downloading:' label.
    phase: 'download' | 'postprocess' | 'search' | 'panopto' | 'transcribe'
    label: optional override for the small uppercase phase label.
    last:  this is the dashboard card's final row - see ``_row_gap`` below.
    Strips Canvas callback prefixes ('Downloading file: ', etc.) automatically.
    """
    clean = str(filename)
    for pfx in _ACTIVE_FILE_PREFIXES:
        if clean.startswith(pfx):
            clean = clean[len(pfx):]
            break
    clean = _html_escape(clean)

    color, default_label, icon_fn = _PHASE_STYLE.get(phase, _PHASE_STYLE['download'])
    # The phase label is app copy, never Canvas data - but it is a public
    # keyword argument, so escaping it costs nothing and makes that true by
    # construction rather than by convention.
    label_html = _html_escape(label or default_label)
    # Named _html by the repo's convention for app-authored markup: this is an
    # inline SVG built by one of the _PHASE_STYLE icon factories.
    icon_html = icon_fn(color)

    # Two depths, one card. The card itself is RAISED on the same overlay +
    # outward shadow as the metrics row, so the two read as one instrument
    # rather than as a panel and a loose strip beneath it. The filename inside
    # it is RECESSED - a darker well behind a soft inset shadow, the same
    # gesture as the terminal log below, scaled down. The result is that the
    # thing that changes every file looks set into the surface that holds it.
    placeholder.markdown(f'''
    <div style="display:flex; align-items:center; gap:10px; padding:10px 16px;
        background:rgba(255,255,255,0.055); border:1px solid rgba(255,255,255,0.08);
        border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,0.30);
        margin-bottom:{_row_gap(last)}; overflow:hidden;"><!-- # audit-ignore: _row_gap returns one of two literals -->
      {icon_html}
      <div style="overflow:hidden; min-width:0; flex:1;">
        <div style="color:{color}; font-size:0.7rem; font-weight:700;
            text-transform:uppercase; letter-spacing:0.06em; line-height:1; margin-bottom:5px;">{label_html}</div>
        <div style="color:{theme.TEXT_PRIMARY}; font-size:0.875rem; font-weight:500;
            background:rgba(0,0,0,0.22); box-shadow:inset 0 1px 3px rgba(0,0,0,0.42);
            padding:3px 9px; border-radius:5px;
            overflow:hidden; text-overflow:ellipsis; white-space:nowrap; line-height:1.5;">{clean}</div>
      </div>
    </div>
    ''', unsafe_allow_html=True)


# ═══════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════

@dataclass
class DashboardPlaceholders:
    """Encapsulates the Streamlit st.empty() slots that make up the progress
    dashboard.  Passed explicitly into every render call so the engine never
    touches global UI state.

    ``active_file`` and ``log`` are optional: the analysis dashboard shows the
    same header / bar / metrics chrome but has no per-file terminal to fill.
    """
    header: object                  # st.empty() - course name + phase label
    progress: object                # st.empty() - progress bar
    metrics: object                 # st.empty() - the metrics row
    active_file: object = None      # st.empty() - "Currently downloading: …"
    log: object = None              # st.empty() - terminal log widget


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


def render_progress_bar(placeholders: DashboardPlaceholders, percent: int,
                        *, color: str | None = None, indeterminate: bool = False,
                        label: str | None = None) -> None:
    """Render the custom HTML progress bar.

    color        : fill colour (defaults to the download blue).
    indeterminate: render an animated sweeping bar for work of unknown duration
                   (e.g. the Panopto discovery phase) instead of a % fill. The
                   ``.cd-indeterminate-*`` animation lives in styles/global.css.
    label        : optional centered text override (defaults to "{percent}%").
    """
    placeholders.progress.markdown(
        build_progress_bar_html(percent, color=color, indeterminate=indeterminate, label=label),
        unsafe_allow_html=True,
    )


def _pct(value) -> int:
    """Coerce anything a call site might hand us into a drawable 0-100 percent.

    This is not defensive padding - an out-of-range percent fails *loudly wrong*
    rather than slightly wrong, because it goes straight into ``width: N%``:

    * ``150`` overflows the fill past its rounded track;
    * ``-3`` and ``nan`` are **invalid CSS**, so the browser drops the whole
      declaration and the div falls back to ``width: auto`` - which for a block
      element is the full track. A bar that means "less than nothing happened"
      renders as a bar that means "finished".

    Clamping lives here rather than at the call sites because it has to hold for
    all of them: the sync analysis hook passed ``int(current / total * 100)``
    straight through with no ceiling at all.
    """
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(n):
        return 0
    return int(max(0.0, min(100.0, n)))


def build_progress_bar_html(percent: int, *, color: str | None = None,
                            indeterminate: bool = False, label: str | None = None) -> str:
    """Return the progress-bar HTML as a string (shared by download + sync flows)."""
    color = color or theme.ACCENT_BLUE
    percent = _pct(percent)
    if indeterminate:
        return (
            f'<div class="cd-indeterminate-track" style="background-color:{theme.BG_CARD};'
            f'border-radius:8px;width:100%;height:24px;position:relative;margin-bottom:10px;'
            f'overflow:hidden;">'
            f'<div class="cd-indeterminate-bar" style="background-color:{color};"></div>'
            f'<div style="position:absolute;top:0;left:0;width:100%;height:100%;display:flex;'
            f'align-items:center;justify-content:center;color:white;font-size:12px;'
            f'font-weight:bold;letter-spacing:0.04em;">{_html_escape(label or "Working…")}</div>'
            f'</div>'
        )
    text = label if label is not None else f"{percent}%"
    return (
        f'<div style="background-color:{theme.BG_CARD};border-radius:8px;width:100%;height:24px;'
        f'position:relative;margin-bottom:10px;">'
        f'<div style="background-color:{color};width:{percent}%;height:100%;border-radius:8px;'
        f'transition:width 0.3s ease;"></div>'
        f'<div style="position:absolute;top:0;left:0;width:100%;height:100%;display:flex;'
        f'align-items:center;justify-content:center;color:white;font-size:12px;font-weight:bold;">'
        f'{_html_escape(text)}</div>'
        f'</div>'
    )


# ═══════════════════════════════════════════════
# The Metrics Row - ONE renderer, one set of cells
# ═══════════════════════════════════════════════
#
# This row used to exist as FOUR byte-identical copies of the same markup
# (render_metrics_row, build_metrics_html, build_custom_metrics_html and
# converters/post_processing), and they drifted exactly as you would expect: a
# `cd-metrics-row` class added to three of them missed the only copy the sync
# screen actually renders, so the change looked perfect in a harness and was
# still broken in the app. There is now one renderer, ``build_metrics_row``,
# and one vocabulary of cells - every screen composes from the same parts.

@dataclass(frozen=True)
class Metric:
    """One cell of the metrics row.

    ``value`` is the large figure; ``suffix`` is the dim trailing part - a
    denominator ("/ 167"), a unit ("MB/s"), or both ("/ 849.4 MB"). Splitting
    them out is what lets every caller share one renderer: the old
    "pass pre-built HTML" contract meant each screen re-derived the suffix
    styling by hand, and each got it slightly differently. Both parts are
    escaped, so no caller can inject markup here any more.
    """
    label: str
    value: str
    suffix: str = ''
    color: str = theme.TEXT_PRIMARY
    suffix_color: str = theme.ACCENT_BLUE


def build_metrics_row(metrics, *, last: bool = False) -> str:
    """Render a metrics row from :class:`Metric` cells.

    ``cd-metrics-row`` is the hook global.css uses to strip this row's own
    surface when it renders INSIDE the run dashboard card (a bordered box
    inside a bordered box reads as two unrelated panels). Standalone callers
    keep the box.

    ``last`` drops the row's bottom margin - see :func:`_row_gap`.
    """
    # No cells means no instrument. Rendering the surface anyway leaves an empty
    # raised box on the screen, which reads as a panel that failed to load.
    if not metrics:
        return ''
    cells = ''
    for m in metrics:
        suffix = (
            f'<span style="font-size:0.9rem;color:{m.suffix_color};">'
            f'{_html_escape(m.suffix)}</span>'
        ) if m.suffix else ''
        cells += (
            '<div style="display:flex;flex-direction:column;align-items:center;">'
            f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.75rem;'
            f'font-weight:bold;text-transform:uppercase;">{_html_escape(m.label)}</span>'
            f'<span style="color:{m.color};font-size:1.2rem;font-weight:bold;">'
            f'{_html_escape(m.value)} {suffix}</span>'
            '</div>'
        )
    # A RAISED panel: lifted off whatever surface hosts it, with an outward
    # shadow - deliberately the mirror of the terminal log below it, which is
    # recessed behind an inset shadow. The numbers are the thing you look at
    # while a run is going, and they used to sit on bare card background with no
    # edge of their own.
    #
    # The lift is a white overlay rather than a palette colour so it composes
    # correctly on every host: inside the run dashboard card, inside Today's
    # own card, or standalone on the page. One base style, every mode.
    return (
        f'<div class="cd-metrics-row" style="display:flex;justify-content:center;'
        f'gap:4rem;background:rgba(255,255,255,0.055);padding:14px 26px;'
        f'border-radius:10px;border:1px solid rgba(255,255,255,0.08);'
        f'box-shadow:0 2px 8px rgba(0,0,0,0.30);margin:2px 0 {_row_gap(last)};'
        f'flex-wrap:wrap;">{cells}</div>'
    )


def render_metrics(placeholders: DashboardPlaceholders, metrics, *,
                   last: bool = False) -> None:
    """Render a metrics row into the dashboard's metrics slot."""
    placeholders.metrics.markdown(build_metrics_row(metrics, last=last),
                                  unsafe_allow_html=True)


# ── Standard cells ──────────────────────────────────────────────────────────
# Named so that "Downloaded" means the same thing, and looks the same, on every
# screen that shows it.
#
# Every cell coerces its input through ``_num``. These builders are called from
# inside repaint loops that run *while a download is in flight*, and several of
# those call sites are not wrapped in a try/except - so a counter that is
# momentarily ``None`` between phases, or an ``inf`` from a divide against a
# zero denominator, would not merely mis-render a cell: it would raise out of
# the repaint and take the run's progress UI with it. The values arriving here
# come from a dozen different counters maintained by different subsystems, and
# the row is the one place that has to tolerate all of them.

def _num(value, default: float = 0.0) -> float:
    """A finite float, or ``default`` for None / NaN / inf / non-numeric."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return n if math.isfinite(n) else default


def metric_transferred(done_bytes: float, total_bytes: float | None = None, *,
                       label: str = 'Downloaded', accent: str = theme.ACCENT_BLUE) -> Metric:
    """MB moved, with an optional "/ total MB" denominator.

    ``total_bytes=None`` drops the denominator - used where a total is not
    meaningful (the retry pass, Panopto media whose size is unknown until each
    stream resolves).
    """
    done_mb = max(0.0, _num(done_bytes)) / (1024 * 1024)
    total_mb = None if total_bytes is None else max(0.0, _num(total_bytes)) / (1024 * 1024)
    # A denominator of zero is not a denominator. A re-run where every file is
    # already on disk has nothing to transfer, and "0.0 / 0.0 MB" reads as a
    # broken counter rather than as "nothing to fetch" - which is exactly how it
    # was reported. Drop the fraction and just state the megabytes.
    if total_mb is None or total_mb < 0.05:
        suffix = "MB"
    else:
        suffix = f"/ {total_mb:.1f} MB"
    return Metric(label, f"{done_mb:.1f}", suffix, theme.TEXT_PRIMARY, accent)


def metric_speed(bytes_per_sec: float) -> Metric:
    return Metric('Speed', f"{max(0.0, _num(bytes_per_sec)) / (1024 * 1024):.1f}",
                  'MB/s', theme.SUCCESS_STAT, theme.SUCCESS_STAT)


def metric_count(label: str, done, total=None, *,
                 accent: str = theme.ACCENT_BLUE, color: str = theme.TEXT_PRIMARY) -> Metric:
    """A "done / total" count.

    The denominator is never allowed below the numerator. Synthetic items raise
    both counters, and the two do not always land in the same tick, so the row
    could read "236 / 233" - which is not a rounding artefact to a reader, it
    just looks broken. The estimator applies the same floor internally.

    A denominator of zero is dropped for the same reason ``metric_transferred``
    drops "/ 0.0 MB": "0 / 0" describes nothing, and on a run with nothing to do
    it is the whole row saying so in the language of a broken counter.
    """
    done = int(max(0.0, _num(done)))
    total_n = None if total is None else int(max(0.0, _num(total)))
    suffix = f"/ {max(total_n, done)}" if total_n else ''
    return Metric(label, f"{done}", suffix, color, accent)


def metric_eta(text: str) -> Metric:
    return Metric('Time Remaining', text, '', theme.WARNING)


def metric_elapsed(seconds: float) -> Metric:
    from engine.estimation import format_elapsed
    return Metric('Elapsed', format_elapsed(_num(seconds)), '', theme.WARNING)


def metric_value(label: str, value: str, color: str = theme.TEXT_PRIMARY) -> Metric:
    return Metric(label, value, '', color)


def transfer_metrics(estimator, *, done_files: int, total_files: int,
                     done_bytes: float, total_bytes: float | None,
                     files_label: str = 'Files',
                     accent: str = theme.ACCENT_BLUE) -> list[Metric]:
    """The canonical Downloaded / Speed / Files / Time Remaining row.

    Every byte-moving phase in the app renders exactly this, reading the speed
    and the ETA off the same :class:`~engine.estimation.ProgressEstimator` -
    so the two numbers can never disagree about how fast the run is going,
    which is precisely what happened when each screen derived them separately.
    """
    return [
        metric_transferred(done_bytes, total_bytes, accent=accent),
        metric_speed(estimator.bytes_per_sec),
        metric_count(files_label, done_files, total_files, accent=accent),
        metric_eta(estimator.eta_text()),
    ]


def render_terminal_log(placeholders: DashboardPlaceholders, log_deque) -> None:
    """Render the terminal-style log widget from a deque of unified log-line HTML."""
    if placeholders.log is None:
        return
    placeholders.log.markdown(build_terminal_html(log_deque), unsafe_allow_html=True)


# ═══════════════════════════════════════════════
# Analysis Dashboard
# ═══════════════════════════════════════════════

def analysis_percent(courses_done: float, courses_total: float,
                     sub_done: float = 0.0, sub_total: float = 0.0) -> int:
    """Overall analysis progress: whole courses plus the current one's fraction.

    The bar and the metrics row have to be measuring the same thing. They were
    not: the bar took the *sub-step's* ratio straight from the scan hook while
    the row counted *courses*, so the instant a sub-step finished the card read
    a 100% bar above "COURSES 0 / 2". Two numbers in one card disagreeing about
    whether the work is done is worse than either being slightly coarse.

    Folding the sub-step in as a fraction of one course keeps the fine-grained
    movement that made the bar worth watching, and makes it monotonic across the
    whole analysis instead of resetting per course.
    """
    total = _num(courses_total)
    if total <= 0:
        return 0
    done = max(0.0, _num(courses_done))
    sub_t = _num(sub_total)
    frac = min(1.0, max(0.0, _num(sub_done) / sub_t)) if sub_t > 0 else 0.0
    return _pct((done + frac) / total * 100.0)


def render_analysis_dashboard(
    placeholders: DashboardPlaceholders,
    *,
    course_label: str,
    course_name: str,
    status_text: str,
    percent: int = 0,
    indeterminate: bool = False,
    metrics=None,
) -> None:
    """Render the scan/analysis phase using the SAME chrome as the run dashboard.

    Analysis used to draw its own card - a heading, two paragraphs and an 8 px
    hairline bar - hand-copied into three places (download scan, sync analysis,
    and the seed paint). It carried no metrics at all, so the first screen of
    every run looked like it belonged to a different application than the one
    that appeared ten seconds later, and told the user nothing about how long
    the wait would be. It is the same phase label, the same course name, the
    same progress bar and the same metrics row as everything else now.

    ``indeterminate`` covers the sub-steps that report no meaningful total
    (most of them report ``total=1``), where a bar frozen near 0% reads as a
    hang and a sweeping bar reads as work.
    """
    # This card has no terminal log, so whichever row comes last here is the
    # card's final row and must not add its own margin on top of the card's
    # bottom padding (see ``_row_gap``).
    _has_active = placeholders.active_file is not None and bool(status_text)

    render_progress_header(placeholders, course_label, course_name)
    render_progress_bar(placeholders, percent, color=PHASE_BAR_COLOR['search'],
                        indeterminate=indeterminate,
                        label="Analyzing…" if indeterminate else None)
    if metrics:
        render_metrics(placeholders, metrics, last=not _has_active)
    if _has_active:
        render_active_file(placeholders.active_file, status_text,
                           phase='search', label='Analyzing', last=True)


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
    downloaded_bytes: float,
    total_bytes: float | None,
    estimator,
    files_label: str = 'Files',
    bar_color: str | None = None,
) -> None:
    """One-call render of the whole byte-moving dashboard.

    ``estimator`` is a :class:`~engine.estimation.ProgressEstimator` the caller
    keeps for the run and has already fed this tick's progress. Speed and time
    remaining both come off it, so they are always two views of one model
    rather than two independent guesses.
    """
    _done_n, _total_n = _num(current_files), _num(total_files)
    percent = int(_done_n / _total_n * 100) if _total_n > 0 else 0
    # Hold the bar off 100% while work is still arriving. Synthetic items raise
    # both counters together, so the ratio pins at 100% for the whole trailing
    # stretch of shortcut/page files - half a minute of work behind a bar that
    # says it is over.
    if percent >= 100 and getattr(estimator, 'is_open_ended', False):
        percent = 99

    render_progress_header(placeholders, header_label, course_name)
    render_progress_bar(placeholders, percent, color=bar_color)
    render_metrics(placeholders, transfer_metrics(
        estimator,
        done_files=current_files, total_files=total_files,
        done_bytes=downloaded_bytes, total_bytes=total_bytes,
        files_label=files_label,
    ))
    render_terminal_log(placeholders, log_deque)


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
