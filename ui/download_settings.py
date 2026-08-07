"""
ui.download_settings - Step 2 download settings page.

Extracted from ``app.py`` (Phase 6).
Strict physical move - NO logic changes.

Contains:
  - ``render_download_settings()`` - full Step 2: preset buttons, Card 1
    (Core Course Files), Card 2 (Canvas Content), Card 3 (AI Engine),
    Output Path, Course Summary, Confirm button.
"""

from __future__ import annotations

import base64
import functools
import logging
import os
import sys
import time
from pathlib import Path

import streamlit as st

# Module level, never inside a function: `import logging` in a function body
# makes the name local to that whole function, so any earlier reference raises
# UnboundLocalError - silently, whenever an enclosing handler catches it.
logger = logging.getLogger(__name__)

from shared import theme
from shared.helpers import (
    esc,
    get_course_display_parts,
    render_download_wizard,
    native_folder_picker,
    get_base64_image,
)
from core.state_registry import (
    SECONDARY_CONTENT_KEYS,
    NOTEBOOK_SUB_KEYS,
    TOTAL_SECONDARY_SUBS,
    PANOPTO_OUTPUT_KEYS,
)
from shared.components import render_help_card, HELP_ICONS, SVG_SAVE_COLORFUL
from shared.legal import (
    DISCLAIMER_URL, clear_panopto_skip, require_panopto_notice,
)


def _resolve_path(path):
    """Resolve path for frozen (PyInstaller) vs normal execution."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, path)
    return path


@functools.lru_cache(maxsize=64)
def _load_b64_cached(path):
    """Cached disk read - only reached on success; exceptions propagate uncached."""
    with open(_resolve_path(path), "rb") as f:
        return base64.b64encode(f.read()).decode()


def _load_b64(path):
    """Load an asset and base64-encode it, or "" if it cannot be read.

    Split into a cached inner + an uncached guard, mirroring
    ``shared.helpers.get_base64_image``. The single cached function this
    replaced had both problems that pattern exists to avoid:

    * it caught only ``FileNotFoundError``, so a ``PermissionError`` - the
      realistic one, since these assets live in PyInstaller's ``_MEIxxxx`` temp
      directory, which Windows antivirus is known to lock transiently -
      propagated out of a page render as a traceback;
    * the handler sat INSIDE the ``lru_cache``, so a momentary failure was
      cached and the icon stayed missing for the rest of the session. That is
      the M-20 bug ``get_base64_image`` documents having fixed, recurring here.
    """
    try:
        return _load_b64_cached(path)
    except Exception as e:
        logger.warning("Could not load asset %s: %s", path, e)
        return ""


def safe_b64(name):
    """Load an asset PNG by name and return base64 string, or "" on failure.

    Cached via the underlying ``get_base64_image`` lru_cache, so repeated
    calls during reruns are free.
    """
    try:
        res = get_base64_image(f"assets/{name}")
        return res if res else ""
    except Exception:
        return ""


def _select_folder():
    """Open native folder picker and store result in download_path."""
    folder_path = native_folder_picker(initial_dir=st.session_state.get('download_path') or None)
    if folder_path:
        st.session_state['download_path'] = folder_path


# ── Panopto Section 4 ───────────────────────────────────────────────────────
# Purple theme tokens (the new Panopto icons ship in two tones; #b89dfe reads
# best as the active accent on the dark cards, mirroring Card 2's green accent).
PAN_ACCENT = "#b89dfe"          # light purple - active borders / checkmarks / text
PAN_ACCENT_DARK = "#7037da"     # dark purple - reserved for solid fills
PAN_ACTIVE_BG = "rgba(176, 157, 254, 0.15)"
# Gear/settings icon for the transcription-config button (Heroicons solid cog).
_PAN_GEAR_SVG = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='%23d8caff'%3E"
                 "%3Cpath fill-rule='evenodd' d='M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948"
                 "c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978"
                 "a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947"
                 "c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106"
                 "a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287"
                 "c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z'"
                 " clip-rule='evenodd' /%3E%3C/svg%3E")

# (session key, label, description, asset icon) for the five output toggles,
# ordered left-to-right: url, mp4, mp3, txt, srt.
#
# Shortcut comes FIRST because it is the cheapest thing on the card - no
# download, no disk, no wait - and because it is the answer for the user who
# does not want a 2 GB video but does want to get back to the lecture. It is
# also the only output here that is not a copy of the recording, which is why
# its description says where it goes rather than what format it is.
#
# This list is the ONLY definition of that order and of the key names; keep
# core.state_registry.PANOPTO_OUTPUT_KEYS in step with it (a test asserts they
# match, because a key that exists in one and not the other is a toggle whose
# state is never reset between runs).
PANOPTO_OUTPUT_DEFS = [
    ('pan_out_url', 'Shortcut',  'Link to the recording online', 'pan_url.png'),
    ('pan_out_mp4', 'Video',     'Full lecture video (MP4)', 'pan_mp4.png'),
    ('pan_out_mp3', 'Audio',     'Audio only (MP3)',         'pan_mp3.png'),
    ('pan_out_txt', 'Transcript', 'Plain-text transcript',    'pan_txt.png'),
    ('pan_out_srt', 'Subtitles', 'Subtitles & timestamps',   'pan_srt.png'),
]
# Outputs that require a transcription model (disabled until one is installed).
PANOPTO_TRANSCRIPT_KEYS = {'pan_out_txt', 'pan_out_srt'}


def _panopto_transcription_ready() -> tuple[bool, bool, str, bool]:
    """Return ``(ready, engine_available, model_id, any_installed)`` for the Section 4 banner.

    ``ready`` is True only when the local transcription engine is importable AND
    the currently-selected model is installed - the exact condition the runner
    uses before it will produce txt/srt. Drives the disabled state of the
    Transcript/Subtitles toggles. ``any_installed`` is True when at least one
    model exists on disk (regardless of which is active). Never raises.

    Thin adapter over the shared ``panopto.models.transcription_status`` (single
    source of truth, also used by the sync-review setup notice).
    """
    from panopto import models as pmodels
    s = pmodels.transcription_status()
    return s['ready'], s['engine_available'], s['model_id'], s['any_installed']


def _panopto_selectable_keys(ready: bool) -> list[str]:
    """Output keys the user can actually toggle (txt/srt gated on a model)."""
    return [k for k, *_ in PANOPTO_OUTPUT_DEFS
            if ready or k not in PANOPTO_TRANSCRIPT_KEYS]


def _get_pan_layout_segmented_css() -> str:
    """Purple segmented-control CSS for the Panopto organization choice.

    A direct sibling of ``_get_sec_org_segmented_css`` (Canvas Content), re-themed
    purple with the ``pan_matching`` / ``pan_separate_folders`` icons and keyed to
    ``btn_pan_layout_match`` / ``btn_pan_layout_separate``.
    """
    b64_match = _load_b64("assets/pan_matching.png")
    b64_sep = _load_b64("assets/pan_separate_folders.png")
    is_sep = st.session_state.get('pan_layout', 'match') == 'separate'
    active_key = "separate" if is_sep else "match"
    return f"""
    <style>
    div[class*="st-key-pan_layout_segmented_wrapper"] {{
        background-color: rgba(0, 0, 0, 0.25) !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 12px !important;
        padding: 4px !important;
        margin-top: 5px !important;
    }}
    div[class*="st-key-pan_layout_segmented_wrapper"] [data-testid="stHorizontalBlock"] {{
        gap: 4px !important;
        align-items: stretch !important;
    }}
    div[class*="st-key-pan_layout_segmented_wrapper"] [data-testid="stColumn"] {{
        display: flex !important;
        flex-direction: column !important;
    }}
    div[class*="st-key-pan_layout_segmented_wrapper"] [data-testid="stColumn"] [data-testid="stVerticalBlock"],
    div[class*="st-key-pan_layout_segmented_wrapper"] [data-testid="stColumn"] [data-testid="stElementContainer"],
    div[class*="st-key-pan_layout_segmented_wrapper"] [data-testid="stColumn"] div[data-testid="stButton"] {{
        display: flex !important;
        flex-direction: column !important;
        flex: 1 1 auto !important;
    }}
    div[class*="st-key-pan_layout_segmented_wrapper"] [data-testid="stColumn"] button {{
        flex: 1 1 auto !important;
        height: 100% !important;
    }}
    /* Base segment: tall content (icon top, title, desc) inside the pill */
    div[class*="st-key-btn_pan_layout_"] button {{
        position: relative !important;
        min-height: 140px !important;
        background-color: transparent !important;
        border: 1px solid transparent !important;
        background-repeat: no-repeat !important;
        background-position: center 18px !important;
        background-size: 50px !important;
        padding: 80px 14px 16px 14px !important;
        border-radius: 8px !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: center !important;
        transition: all 0.2s ease-in-out !important;
        opacity: 0.75 !important;
        color: #a0a0a0 !important;
    }}
    /* Circular radio pseudo-element (top-right) */
    div[class*="st-key-btn_pan_layout_"] button::before {{
        top: 16px !important;
        right: 16px !important;
        border-radius: 50% !important;
        box-sizing: border-box !important;
    }}
    div[class*="st-key-btn_pan_layout_"] button > div,
    div[class*="st-key-btn_pan_layout_"] button div[data-testid="stMarkdownContainer"] {{
        width: 100% !important;
        display: flex !important;
        justify-content: center !important;
        text-align: center !important;
    }}
    div[class*="st-key-btn_pan_layout_"] button p {{
        text-align: center !important;
        width: 100% !important;
        margin: 0 !important;
        padding-right: 0 !important;
        font-size: 1.05rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
        color: inherit !important;
    }}
    div.st-key-btn_pan_layout_match button {{ background-image: url('data:image/png;base64,{b64_match}') !important; }}
    div.st-key-btn_pan_layout_separate button {{ background-image: url('data:image/png;base64,{b64_sep}') !important; }}
    div[class*="st-key-btn_pan_layout_"] button:hover {{
        background-color: rgba(255, 255, 255, 0.05) !important;
        border-color: {PAN_ACCENT} !important;
        opacity: 1 !important;
        color: #ffffff !important;
    }}
    /* Disabled State (no Panopto output selected): global.css's
       `button[disabled]` recipe owns the paint, and because it is an attribute
       selector on the button it still outranks nothing - it simply applies to
       BOTH pills, including the active 'match' one, which is the intent.
       The local `filter: grayscale(100%)` used to REPLACE the shared filter
       (filter is one property) and flatten these to grey slabs. */
    div.st-key-btn_pan_layout_match button::after {{ content: "Save recordings alongside your course files." !important; }}
    /* Literal curly quotes, NOT \\201C / \\201D escapes: a CSS hex escape consumes
       one following whitespace as its terminator, so "\\201D folder" rendered as
       "folder with no space before the word. */
    div.st-key-btn_pan_layout_separate button::after {{ content: "A “Panopto Recordings” folder in each course." !important; }}
    div[class*="st-key-btn_pan_layout_"] button::after {{
        text-align: center !important;
        width: 100% !important;
        display: block !important;
        padding-right: 0 !important;
        font-size: 0.8rem !important;
        color: #a0a0a0 !important;
        margin-top: 5px !important;
        font-weight: 400 !important;
        white-space: normal !important;
        line-height: 1.25 !important;
    }}
    div.st-key-btn_pan_layout_{active_key} button {{
        background-color: {PAN_ACTIVE_BG} !important;
        border: 1px solid {PAN_ACCENT} !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;
        color: #ffffff !important;
        opacity: 1 !important;
    }}
    div.st-key-btn_pan_layout_{active_key} button:hover {{
        background-color: {PAN_ACTIVE_BG} !important;
        border: 1px solid {PAN_ACCENT} !important;
        opacity: 1 !important;
    }}
    div[class*="st-key-btn_pan_layout_"] button:hover::before {{ border-color: {PAN_ACCENT} !important; }}
    div.st-key-btn_pan_layout_{active_key} button:hover::before {{ border-color: transparent !important; }}
    div.st-key-btn_pan_layout_{active_key} button p {{ color: #ffffff !important; }}
    div.st-key-btn_pan_layout_{active_key} button::before {{
        border: none !important;
        background-color: transparent !important;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%23b89dfe' stroke-width='3'/%3E%3Ccircle cx='12' cy='12' r='5' fill='%23b89dfe'/%3E%3C/svg%3E") !important;
    }}
    </style>
    """


def _get_chevron_base64(is_expanded):
    if is_expanded:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1683 808-742 741q-19 19-45 19t-45-19L109 808q-19-19-19-45.5t19-45.5l166-165q19-19 45-19t45 19l531 531 531-531q19-19 45-19t45 19l166 165q19 19 19 45.5t-19 45.5z"></path></svg>'''
    else:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1363 877-742 742q-19 19-45 19t-45-19l-166-166q-19-19-19-45t19-45l531-531-531-531q-19-19-19-45t19-45L531 45q19-19 45-19t45 19l742 742q19 19 19 45t-19 45z"></path></svg>'''
    b64_str = base64.b64encode(svg.encode('utf-8')).decode()
    return f"url('data:image/svg+xml;base64,{b64_str}')"


def _dl_settings_go_back():
    """Leave Configure Download for the course list.

    ONE handler for both ways out of this page - the Go back button and the step
    tracker's "Select Courses" - so the ``came_from_quick_dl`` hand-back can
    never be honoured by one and dropped by the other. Mutates session state
    only: it runs as an ``on_click`` callback, before the rerun the click
    already scheduled.
    """
    if st.session_state.get('came_from_quick_dl', False):
        st.session_state['quick_download_mode'] = True
        st.session_state.pop('came_from_quick_dl', None)
    else:
        st.session_state['step'] = 1


def render_download_settings(fetch_courses_fn):
    """Render the full Step 2 download settings page.

    Args:
        fetch_courses_fn: The cached ``fetch_courses()`` function from app.py.
    """
    # Import preset dialogs from extracted module
    from ui.presets import _save_config_dialog, _presets_hub_dialog

    # The tracker's "1. Select Courses" is a live back-link, wired to the SAME
    # handler as the Go back button at the bottom of the page - the quick-download
    # branch included - so a click here can never reach a state the button could
    # not. ``on_click`` and not ``if st.button()``: the click already schedules a
    # rerun, and a second one loses the browser's scroll anchor.
    render_download_wizard(st, 'configure', nav={'select': _dl_settings_go_back})

    # Pre-warm Panopto hardware detection in background so the transcription
    # dialog opens without the ~5s delay on first click. backend_import_ok()
    # does `import faster_whisper` on first call which is slow; this warms the
    # _CACHE while the user is reading the settings page.
    if not st.session_state.get('_pan_hw_prewarm_done'):
        import threading as _t
        def _prewarm_hw():
            try:
                from panopto.hardware import detect_compute_hardware as _dhw
                _dhw()
            except Exception:
                pass
        _t.Thread(target=_prewarm_hw, daemon=True).start()
        st.session_state['_pan_hw_prewarm_done'] = True

    # Hoisted CSS Overrides for Step 2 UI Component geometry
    # Use st.html (not st.markdown) to avoid ghost-box 1rem margin below the stepper.
    st.html("""<style>
    div[data-testid="stHorizontalBlock"]:has(.st-key-action_dl_back),
    div[data-testid="stHorizontalBlock"]:has(.st-key-action_dl_confirm) {
        margin-top: -15px !important;
    }
    </style>""")

    # Consume pending toasts from preset dialogs
    if 'pending_toast' in st.session_state:
        st.toast(st.session_state.pop('pending_toast'))

    # NOTE: The Panopto transcription-config dialog is hosted centrally in app.py
    # (it can be opened from any page or the Settings dialog). Setting
    # st.session_state['_pan_dialog_open'] = True + an app-scoped rerun opens it.

    # Step 2 Header with Preset Buttons
    _hdr_left, _hdr_right = st.columns([0.6, 0.4])
    
    # Define Help Content
    help_title = "Download Settings Guide"
    # Inner setting buttons: grey bg, white text, themed border; answer divs: dark bg, white text
    _b1 = "padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(63,217,255,0.4); border-radius: 5px; user-select: none; list-style: none;"
    _b2 = "padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(104,212,163,0.42); border-radius: 5px; user-select: none; list-style: none;"
    _b3 = "padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(249,115,22,0.42); border-radius: 5px; user-select: none; list-style: none;"
    _ans1 = "padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(63,217,255,0.5); margin-top: 1px; line-height: 1.6; cursor: default;"
    _ans2 = "padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(104,212,163,0.5); margin-top: 1px; line-height: 1.6; cursor: default;"
    _ans3 = "padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(249,115,22,0.5); margin-top: 1px; line-height: 1.6; cursor: default;"
    _row = "margin: 5px 0; border-radius: 5px; overflow: hidden;"
    _lbl = "font-size: 0.73rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; margin: 13px 0 5px 0; color: rgba(255,255,255,0.9);"
    # Shared badge styles (inline, placed after title text in HTML)
    _tag1 = "color: #3fd9ff; background: rgba(63,217,255,0.15); padding: 1px 8px; border-radius: 4px; font-size: 0.74rem; font-weight: 700; margin-left: 8px; vertical-align: middle;"
    _tag2 = "color: #68d4a3; background: rgba(104,212,163,0.18); padding: 1px 8px; border-radius: 4px; font-size: 0.74rem; font-weight: 700; margin-left: 8px; vertical-align: middle;"
    _tag3 = "color: #f97316; background: rgba(249,115,22,0.18); padding: 1px 8px; border-radius: 4px; font-size: 0.74rem; font-weight: 700; margin-left: 8px; vertical-align: middle;"
    help_text = (
        # ── Intro ─────────────────────────────────────────────────────────────
        "<div style='margin: 6px 0; padding: 9px 12px 9px 14px; background: rgba(63,217,255,0.05); border-radius: 6px; border-left: 3px solid rgba(63,217,255,0.45);'>"
        "<div style='display: flex; align-items: center; gap: 8px; margin-bottom: 4px;'>"
        "<span style='color: #3fd9ff; background: rgba(63,217,255,0.15); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; white-space: nowrap;'>Card 1</span>"
        "<b style='color: #e2e8f0; font-size: 0.85rem;'>Course files &amp; organization</b>"
        "</div>"
        "<div style='color: rgba(255,255,255,0.7); font-size: 0.85rem;'>Required. Choose how your course folder and files should be organized and whether to download ALL teacher-uploaded files, or only slides and PDFs.</div>"
        "</div>"
        "<div style='margin: 6px 0; padding: 9px 12px 9px 14px; background: rgba(104,212,163,0.05); border-radius: 6px; border-left: 3px solid rgba(104,212,163,0.45);'>"
        "<div style='display: flex; align-items: center; gap: 8px; margin-bottom: 4px;'>"
        "<span style='color: #68d4a3; background: rgba(104,212,163,0.18); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; white-space: nowrap;'>Card 2</span>"
        "<b style='color: #e2e8f0; font-size: 0.85rem;'>Canvas Content</b>"
        "</div>"
        "<div style='color: rgba(255,255,255,0.7); font-size: 0.85rem;'>Optional. Download all the things you see on Canvas (web pages) that aren't teacher-uploaded files - assignments and their files, announcements, quizzes, graded feedback, etc.</div>"
        "</div>"
        "<div style='margin: 6px 0; padding: 9px 12px 9px 14px; background: rgba(249,115,22,0.05); border-radius: 6px; border-left: 3px solid rgba(249,115,22,0.45);'>"
        "<div style='display: flex; align-items: center; gap: 8px; margin-bottom: 4px;'>"
        "<span style='color: #f97316; background: rgba(249,115,22,0.18); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; white-space: nowrap;'>Card 3</span>"
        "<b style='color: #e2e8f0; font-size: 0.85rem;'>AI Optimization</b>"
        "</div>"
        "<div style='color: rgba(255,255,255,0.7); font-size: 0.85rem;'>Optional. When toggled, the app will automatically convert your files into the formats that work best with your favorite AI, specifically NotebookLM. Runs after files are downloaded.</div>"
        "</div>"
        "<div style='margin: 6px 0; padding: 9px 12px 9px 14px; background: rgba(184,157,254,0.05); border-radius: 6px; border-left: 3px solid rgba(184,157,254,0.55);'>"
        "<div style='display: flex; align-items: center; gap: 8px; margin-bottom: 4px;'>"
        "<span style='color: #b89dfe; background: rgba(184,157,254,0.18); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; white-space: nowrap;'>Card 4</span>"
        "<b style='color: #e2e8f0; font-size: 0.85rem;'>Panopto Lecture Recordings</b>"
        "</div>"
        "<div style='color: rgba(255,255,255,0.7); font-size: 0.85rem;'>Optional. Finds Panopto lecture recordings linked in your courses and saves them inside the course folder. Choose any combination of <b>Video (MP4)</b>, <b>Audio (MP3)</b>, <b>Transcript (.txt)</b> and <b>Subtitles (.srt)</b>. Video &amp; audio download and sync with no setup; <b>transcripts &amp; subtitles need a one-time transcription model</b> - they're generated locally on your machine (nothing is uploaded). Click <b>Set up transcription</b> to download one.</div>"
        "</div>"
        "<hr>"

        # ── Section title ─────────────────────────────────────────────────────
        f"<div style='font-weight: 700; color: #ffffff; font-size: 1.25rem; margin-bottom: 8px; margin-top: 16px;'>{HELP_ICONS['gear']} Settings Explained in Detail</div>"

        # ── Card 1 ────────────────────────────────────────────────────────────
        "<details style='margin: 4px 0 8px 0; border: 1px solid rgba(255,255,255,0.13); border-radius: 7px; overflow: hidden;'>"
        f"<summary style='padding: 10px 14px; cursor: pointer; background: rgba(255,255,255,0.08); user-select: none;'><span style='color: #ffffff; font-weight: 600; font-size: 0.87rem;'>Course Files &amp; Organization</span><span style='{_tag1}'>Card 1</span></summary>"

        "<div style='padding: 10px 14px 14px 14px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03);'>"
        "<p style='font-size: 0.85rem; color: rgba(255,255,255,0.65); margin: 0 0 10px 0;'>Click any setting below to read what it does.</p>"

        f"<div style='{_lbl}'>Choose which files to download</div>"
        f"<details style='{_row}'><summary style='{_b1}'>All Files</summary>"
        f"<div style='{_ans1}'>Downloads every file your teacher uploaded to Canvas: PDFs, PowerPoint slides, Word documents, images, videos, spreadsheets, ZIP archives, and more. Choose this if you want a complete copy of your course.</div></details>"
        f"<details style='{_row}'><summary style='{_b1}'>Slides &amp; PDFs</summary>"
        f"<div style='{_ans1}'>Downloads <b>only</b> PowerPoint files and PDF documents. Choose this if you only need the core study materials, and want to skip everything else.</div></details>"
        f"<div style='{_lbl}'>Choose how files should be organized</div>"
        f"<details style='{_row}'><summary style='{_b1}'>With Subfolders</summary>"
        f"<div style='{_ans1}'>Mirrors the Canvas module layout on your computer (where files are organized under a title - e.g., 'Week 1'). Each module becomes a folder - for example: CHEM101 / <b>Week 3 - Thermodynamics</b> / lecture.pdf. Choose this if your course has a lot of files, or you simply like your files organized neatly.</div></details>"
        f"<details style='{_row}'><summary style='{_b1}'>All in One Folder</summary>"
        f"<div style='{_ans1}'>Puts every file directly in the course folder with no subfolders - all in one. Choose this if you want the ability to see all your files at once, or if you don't like 'hiding' files inside folders. Can get cluttered for larger courses. Note: Remember that you can always organize the files yourself after the download. ;)</div></details>"
        "</div></details>"

        # ── Card 2 ────────────────────────────────────────────────────────────
        "<details style='margin: 4px 0 8px 0; border: 1px solid rgba(255,255,255,0.13); border-radius: 7px; overflow: hidden;'>"
        f"<summary style='padding: 10px 14px; cursor: pointer; background: rgba(255,255,255,0.08); user-select: none;'><span style='color: #ffffff; font-weight: 600; font-size: 0.87rem;'>Canvas Content</span><span style='{_tag2}'>Card 2</span></summary>"
        "<div style='padding: 10px 14px 14px 14px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03);'>"
        "<p style='font-size: 0.85rem; color: rgba(255,255,255,0.65); margin: 0 0 10px 0;'>These exist only as web pages in Canvas - Canvas Downloader converts them into local files you can open and look at. Click any item below to read more.</p>"
        f"<details style='{_row}'><summary style='{_b2}'>Assignments</summary>"
        f"<div style='{_ans2}'>Saves each assignment's full text instructions, due date, etc. as a file you can open in any browser. <b>Also saves any files attached to the assignment</b>. <br>Eliminates the need for having Canvas open with the teacher's assignment notes while writing the assignment. Enables easy upload to AI tools.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Syllabus</summary>"
        f"<div style='{_ans2}'>Saves the course syllabus page, including grading policies, office hours, and weekly schedules if your teacher set those up in Canvas.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Announcements</summary>"
        f"<div style='{_ans2}'>Saves all course announcements. Also saves responses and follow-ups. Great for finding deadline changes, course material notes, or last-minute reminders your teacher posted.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Discussions</summary>"
        f"<div style='{_ans2}'>Saves discussion threads. Useful if your teacher posts key content there, or if you want to review classmates' responses when studying.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Quizzes</summary>"
        f"<div style='{_ans2}'>Saves quiz Q/A choices. What is visible depends on your teacher's configured privacy settings in Canvas.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>Submissions (Results)</summary>"
        f"<div style='{_ans2}'>Saves feedback and grades you received on your own submitted work: teacher comments, grading scores, and the grade per assignment. Note: Your teacher is not notified. It does not download your submitted file.</div></details>"

        f"<div style='{_lbl}'>Choose how Canvas Content should be organized</div>"
        f"<details style='{_row}'><summary style='{_b2}'>Match Course Folder Structure</summary>"
        f"<div style='{_ans2}'>Places Canvas Content files alongside your teacher-uploaded files, according to the file organization method you chose in Card 1 under 'Choose how files should be organized'.<br>When toggled, Canvas Content files will be <b>named according to their types</b> - e.g., 'Assignment - FirstAssignmentSemester2'.</div></details>"
        f"<details style='{_row}'><summary style='{_b2}'>In Separate Folders</summary>"
        f"<div style='{_ans2}'>Creates a dedicated subfolder for each Canvas Content type (Assignments, Quizzes, Discussions, etc.) inside the course folder, separate from your regular files. <br>Choose this if you want to keep Canvas Content separate from teacher-uploaded files.</div></details>"
        "</div></details>"

        # ── Card 3 ────────────────────────────────────────────────────────────
        "<details style='margin: 4px 0 8px 0; border: 1px solid rgba(255,255,255,0.13); border-radius: 7px; overflow: hidden;'>"
        f"<summary style='padding: 10px 14px; cursor: pointer; background: rgba(255,255,255,0.08); user-select: none;'><span style='color: #ffffff; font-weight: 600; font-size: 0.87rem;'>AI Optimization</span><span style='{_tag3}'>Card 3</span></summary>"
        "<div style='padding: 10px 14px 14px 14px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03);'>"
        "<p style='font-size: 0.85rem; color: rgba(255,255,255,0.65); margin: 0 0 10px 0;'>These run after downloading finishes. Each only touches the file types it handles - all others are left unchanged. <br><b>Note: All conversions replace the original file with the optimized file</b> - e.g., a PowerPoint file, optimized with 'PPTX -> PDF', will be replaced by the PDF, inheriting the exact name and content.<br>Click any item to read more.</p>"
        f"<details style='{_row}'><summary style='{_b3}'>Unpack Archives</summary>"
        f"<div style='{_ans3}'>Extracts ZIP files after downloading, so the contents are immediately accessible. Most AI tools cannot read ZIP files directly.<br><b>Note:</b> nothing <i>inside</i> an archive is converted. The zip is unpacked and its contents are left exactly as your teacher packed them - so a code project comes out as a working project. <br> - Example: You have ZIP extraction and PowerPoint to PDF toggled on, and your teacher's ZIP archive contains a PPTX file. The .zip is extracted into a regular folder, and the PPTX inside it stays a PPTX. <br>This is deliberate: most conversions <b>delete the original</b>, and one real lecture archive unpacked 21,824 files - rewriting them would have renamed 11,818 and broken 9,730 by pushing them past Windows' path-length limit. Sync follows the identical rule.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>PowerPoint to PDF</summary>"
        f"<div style='{_ans3}'>Converts PowerPoint files (all types) to PDF. Most AI tools handle PDF better than PowerPoint and have a smaller file size. <br>Requires the Microsoft PowerPoint desktop app (Windows or Mac).</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Legacy Word Docs to PDF</summary>"
        f"<div style='{_ans3}'>Converts old Word document formats (.doc, .rtf, .odt) to PDF. Modern .docx files are not affected. <br>Requires the Microsoft Word desktop app (Windows or Mac).</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Excel to PDF &amp; AI Data</summary>"
        f"<div style='{_ans3}'>Converts Excel spreadsheets into two files: a PDF (preserves layout, charts, and formatting) and a structured plain text 'data file' optimized for AI. They inherit the name of the original spreadsheet, and the data file is suffixed with '_Data' - e.g. <b>Budget.xlsx</b> becomes <b>Budget.pdf</b> + <b>Budget_Data.txt</b>. <br>The data file includes a cell coordinate grid (A1, B2...) that matches the PDF, formula annotations showing the math behind calculated cells, and supports merged cell values and formulas. It is tested, and your AI loves the PDF & Data file combination. ;)<br> <b>Note:</b> The original spreadsheet is replaced by the PDF. If you want to download it, run a new download without this AI Optimization toggled.<br><b>Note:</b> The AI data file is generated only for modern Excel formats (.xlsx, .xlsm). Legacy .xls files are converted to PDF only. <br>Requires Microsoft Excel.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Canvas Pages to Plain Text</summary>"
        f"<div style='{_ans3}'>Converts Canvas web pages downloaded via Card 2 (Canvas Content) into clean plain text files, stripping all web formatting. Makes them easy to paste into or upload to AI tools.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Code &amp; Data to .txt</summary>"
        f"<div style='{_ans3}'>Turns programming and data files into .txt so you can upload them to AI tools that only accept plain text. The dot in the extension becomes an underscore - <b>index.js</b> becomes <b>index_js.txt</b> - which keeps the original type visible in the name and guarantees it can't collide with a .txt that was already sitting there. A short header naming the original file is added at the top; the code itself is unchanged.<br>Covers 50+ formats (.py, .js, .sql, .json, .csv, .yaml and more). <b>Note:</b> the original file is replaced.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Gather Web Links</summary>"
        f"<div style='{_ans3}'>Collects all website shortcut files across your course folder and combines them into a single text file per course. Useful for keeping track of every external link your teacher added. <br>Cleans up your course folder, so no .url or .webloc files appear, preventing NotebookLM from throwing an error, as NotebookLM will happily accept a list of links.</div></details>"
        f"<details style='{_row}'><summary style='{_b3}'>Video to Audio</summary>"
        f"<div style='{_ans3}'>Extracts the audio track from video files and saves it as an MP3. Lecture recordings become much smaller (typically 10 to 20 times smaller) and most AI tools support audio upload. The original video is <b>replaced</b> by the MP3.</div></details>"
        "<div style='background-color: rgba(245,158,11,0.1); border-left: 3px solid #f59e0b; padding: 8px 12px; border-radius: 0 4px 4px 0; margin-top: 10px; font-size: 0.85rem;'>"
        f"<span style='color: #fbd38d; font-weight: 600;'>{HELP_ICONS['warning']} Required software:</span> PowerPoint and Word PDF conversions require the matching Microsoft Office desktop app (PowerPoint / Word). <br>Excel PDF conversion requires Microsoft Excel, and the Excel AI data file extraction works for .xlsx/.xlsm only <b>(not legacy .xls)</b>. <br>If the required app is not installed, that step is silently skipped and your original file is kept."
        "</div>"
        "</div></details>"

        # ── Section 4: Panopto ─────────────────────────────────────────────────
        "<details style='margin: 4px 0 8px 0; border: 1px solid rgba(184,157,254,0.25); border-radius: 7px; overflow: hidden;'>"
        "<summary style='padding: 10px 14px; cursor: pointer; background: rgba(255,255,255,0.08); user-select: none;'><span style='color: #ffffff; font-weight: 600; font-size: 0.87rem;'>Panopto Lecture Recordings</span><span style='color: #b89dfe; background: rgba(184,157,254,0.18); padding: 1px 8px; border-radius: 4px; font-size: 0.74rem; font-weight: 700; margin-left: 8px; vertical-align: middle;'>Card 4</span></summary>"
        "<div style='padding: 10px 14px 14px 14px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03);'>"
        "<p style='font-size: 0.85rem; color: rgba(255,255,255,0.65); margin: 0 0 10px 0;'>The app scans each course for embedded <b>Panopto</b> lecture links and saves the recordings inside the course folder. Pick any mix of the four outputs below - each is written per recording. Click an item to read more.</p>"
        "<details style='margin: 5px 0; border-radius: 5px; overflow: hidden;'><summary style='padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(184,157,254,0.4); border-radius: 5px; user-select: none; list-style: none;'>Video (MP4)</summary>"
        "<div style='padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(184,157,254,0.5); margin-top: 1px; line-height: 1.6;'>Downloads the full lecture video (the combined screen + camera stream) as an MP4. Best when you want to watch the lecture offline. Note: video files can be large.</div></details>"
        "<details style='margin: 5px 0; border-radius: 5px; overflow: hidden;'><summary style='padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(184,157,254,0.4); border-radius: 5px; user-select: none; list-style: none;'>Audio (MP3)</summary>"
        "<div style='padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(184,157,254,0.5); margin-top: 1px; line-height: 1.6;'>Downloads just the lecture audio as an MP3 - far smaller than video and perfect for re-listening or uploading to AI tools.</div></details>"
        "<details style='margin: 5px 0; border-radius: 5px; overflow: hidden;'><summary style='padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(184,157,254,0.4); border-radius: 5px; user-select: none; list-style: none;'>Transcript (.txt) &amp; Subtitles (.srt)</summary>"
        "<div style='padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(184,157,254,0.5); margin-top: 1px; line-height: 1.6;'>Generates a written transcript and/or timestamped subtitles <b>locally on your own computer</b> using on-device speech recognition - nothing is uploaded. You must download a transcription model once via <b>Set up transcription</b>; pick your language and (if you have an NVIDIA GPU on Windows) enable GPU acceleration for a big speed-up. On Macs transcription runs on the CPU.</div></details>"
        "<div style='font-size: 0.73rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; margin: 13px 0 5px 0; color: rgba(255,255,255,0.9);'>Choose how recordings should be organized</div>"
        "<details style='margin: 5px 0; border-radius: 5px; overflow: hidden;'><summary style='padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(184,157,254,0.4); border-radius: 5px; user-select: none; list-style: none;'>Match Course Folder structure</summary>"
        "<div style='padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(184,157,254,0.5); margin-top: 1px; line-height: 1.6;'>Saves each recording alongside your course files (in its module subfolder when using subfolders, or the course root when flat).</div></details>"
        "<details style='margin: 5px 0; border-radius: 5px; overflow: hidden;'><summary style='padding: 8px 12px; cursor: pointer; font-weight: 600; font-size: 0.85rem; color: #e2e8f0; background: rgba(255,255,255,0.08); border: 1px solid rgba(184,157,254,0.4); border-radius: 5px; user-select: none; list-style: none;'>In Separate Folders</summary>"
        "<div style='padding: 9px 13px 11px 13px; font-size: 0.85rem; color: #e2e8f0; background: rgba(0,0,0,0.32); border-left: 2px solid rgba(184,157,254,0.5); margin-top: 1px; line-height: 1.6;'>Groups all recordings into a dedicated &ldquo;Panopto Recordings&rdquo; folder inside the course folder, one subfolder per recording - keeps lectures separate from your files.</div></details>"
        "<div style='background-color: rgba(184,157,254,0.1); border-left: 3px solid #b89dfe; padding: 8px 12px; border-radius: 0 4px 4px 0; margin-top: 10px; font-size: 0.85rem;'>"
        f"<span style='color: #cbb8ff; font-weight: 600;'>{HELP_ICONS['lightbulb']} Privacy:</span> Transcription is 100% local (faster-whisper). Your lectures never leave your computer. Recordings are discovered first, then downloaded, then transcribed - you'll see each phase on the progress screen."
        "</div>"
        "</div></details>"

        # ── Output Folder ─────────────────────────────────────────────────────
        "<hr>"
        f"<div style='font-weight: 700; color: #ffffff; font-size: 1.25rem; margin-bottom: 6px; margin-top: 16px;'>{HELP_ICONS['folder']} Output Folder</div>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.8);'>"
        "The folder where all downloaded courses are saved. Each course will be created as its own folder inside the output folder, and have all course files inside it.<br>Click <b>Select Folder</b> to change the destination path."
        "</div>"
        "<hr>"

        # ── Presets ───────────────────────────────────────────────────────────
        f"<div style='font-weight: 700; color: #ffffff; font-size: 1.25rem; margin-bottom: 8px; margin-top: 16px;'>{HELP_ICONS['save']} Download Settings Presets</div>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.8); margin-bottom: 10px;'>"
        "A Preset saves your entire Card 1, 2, and 3 configuration, and optionally also the output folder path, under a name and description that you choose. Once saved, you can import your saved download configuration in one click, instead of re-configuring everything from scratch."
        "</div>"
        "<div style='display: flex; gap: 10px; margin-bottom: 10px;'>"
        "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 7px; padding: 11px 13px;'>"
        f"<div style='font-weight: 700; color: #e2e8f0; font-size: 0.85rem; margin-bottom: 7px;'>{HELP_ICONS['save']} Saving a preset</div>"
        "<div style='color: rgba(255,255,255,0.75); font-size: 0.85rem; line-height: 1.6;'>"
        f"1. Configure the download settings (and optionally also the output folder), then click <b style='color: #e2e8f0;'>{SVG_SAVE_COLORFUL} Save Preset</b> in the top right. <br>2. Give it a name (required) and a description (optional), and click <b>Save Preset</b>. <br><b>Note:</b> Settings are stored locally on your computer."
        "</div>"
        "</div>"
        "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 7px; padding: 11px 13px;'>"
        f"<div style='font-weight: 700; color: #e2e8f0; font-size: 0.85rem; margin-bottom: 7px;'>{HELP_ICONS['folder_open']} Loading a preset</div>"
        "<div style='color: rgba(255,255,255,0.75); font-size: 0.85rem; line-height: 1.6;'>"
        "1. Click the <b>Presets</b> button in the top right. The Preset Hub opens. <br>2. Look through your saved presets, or navigate to the built-in presets using the tabs at the top. <br>3. Click the <b>Apply Preset</b> button to instantly apply the settings to the toggles on this page."
        "</div>"
        "</div>"
        "</div>"
        "<div style='background: rgba(255,255,255,0.04); border-radius: 7px; padding: 10px 13px;'>"
        "<div style='font-size: 0.73rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: rgba(255,255,255,0.4); margin-bottom: 7px;'>Built-in presets to get you started</div>"
        "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.75); line-height: 1.7;'>"
        "&#8226; <b style='color: #e2e8f0;'>1:1 Full Canvas Course Download</b> - All your course files organized as they are in Canvas. Canvas Content downloaded alongside teacher-uploaded files. ZIP extraction enabled for your ease of use.<br>"
        "&#8226; <b style='color: #e2e8f0;'>AI Power-User Student</b> - All your course files organized as they are in Canvas. Canvas Content downloaded into separate folders. ZIP extraction ON, and PowerPoint + Legacy Word files converted to PDF, for everyday AI use.<br>"
        "&#8226; <b style='color: #e2e8f0;'>NotebookLM Optimized (Drag-and-Drop)</b> - Downloads all teacher-uploaded files AND Canvas Content, and places everything in the course folder, no subfolders. ALL AI Optimizations on, ready to Ctrl/Command + A and drag into NotebookLM."
        "</div>"
        "</div>"
        "<hr>"

        # ── FAQ ───────────────────────────────────────────────────────────────
        "<details style='margin-top: 4px;'>"
        f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['question']} Frequently Asked Questions</summary>"
        "<div style='margin-top: 6px; padding-left: 12px;'>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is the difference between All Files and Slides &amp; PDFs?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "<b>All Files</b> grabs everything your teacher uploaded - PDFs, slides, Word documents, images, videos, spreadsheets, ZIP archives, and more. <b>Slides &amp; PDFs</b> only grabs lecture slides and PDF files. Use the latter if you want to skip all other course materials, otherwise <b>All Files</b> is the go-to."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What does With Subfolders actually look like on my computer?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Each course gets a folder, and inside it, Canvas modules (the title you see above a group of files in Canvas) become subfolders. For example: <em>Downloads / CHEM101 / <b>Week 3 - Thermodynamics</b> / lecture.pdf</em>. With All in One Folder: <em>Downloads / <b>CHEM101</b> / lecture.pdf</em> - every file at the same level with no subfolders."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is Canvas Content and why would I want to download it?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Canvas Content covers information that only exists as web pages inside Canvas - assignment instructions, announcements, discussion threads, quiz questions. These usually contain valuable information regarding your course that would be relevant to give to, e.g., NotebookLM for it to get the full picture. <br>The app converts Canvas Content web pages into local documents you can read offline or upload to AI tools. Your regular course files are always downloaded regardless of the Canvas Content settings."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>If I enable PowerPoint to PDF, does the original file get deleted?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Yes - all AI Optimization conversions replace the 'un-optimized' file (e.g., PowerPoint) with the optimized file (e.g., PDF). If you need to keep the original file formats, run another download where you ensure the AI Optimization toggles are OFF, so you get the original file formats as your teacher uploaded them."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What does Submissions (Results) save, and will my teacher know?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "It saves the feedback and grades you received on your own submitted assignments - teacher comments, grading scores, and your grade per assignment. This is your personal data - your teacher is not notified. It does NOT download any submitted files (you have these on your PC already)."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Do I have to re-download everything every time, or can I just get new files?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Use <b>Sync Mode</b> (available from the navigation sidebar: 'Sync Course Folders') for that. Download Mode always downloads a fresh copy of everything. Sync Mode tracks what is already on your computer and only fetches files that are new or updated since your last sync. <br>Sync Mode allows you to organize your course folder &amp; files exactly how you want them, and <b>sync</b> anytime you want to download only the new files added to the course on Canvas."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Why would I use Video to Audio instead of keeping the full video file?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "Lecture videos are often hundreds of megabytes each, and most AI tools like NotebookLM do not support video uploads. Converting to audio gives a much smaller file (typically 10 to 20 times smaller) you can upload to AI tools. Additionally, video recordings are usually paired with a PowerPoint. If you want to download and watch the video your teacher uploaded, leave this setting disabled."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Do the AI Optimization conversions work on all computers?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        "It depends on the conversion. PowerPoint, Word, and Excel PDF conversions require the matching <b>Microsoft Office</b> desktop app. Unpacking archives, converting Canvas pages, adding .txt to code files, gathering web links, video-to-audio, and Excel AI data extraction all work on any computer with no extra software."
        "</div></details>"
        "<details style='margin-top: 8px; cursor: pointer;'>"
        "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is a Preset and should I use one?</summary>"
        "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63,217,255,0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
        f"A Preset saves your current applied settings under a name, so you can reload them instantly next time. Click <b>{HELP_ICONS['save']} Save Preset</b> after configuring, and the <b>Presets</b> button to open the Preset Hub and apply a saved one."
        "</div></details>"
        "</div>"
        "</details>"
    )

    # Both header dialogs are invoked at the very END of this function - see the
    # comment at that call site. Flags, not direct calls, because a dialog body
    # is a fragment whose rerun rewinds the EVENT container to its CALL SITE.
    _open_save_config = False
    _open_presets_hub = False

    with _hdr_left:
        # Title + Help Tag in a Snug Flex Row
        st.html("""
            <style>
            /* Force the column container to justify left and have a tight gap */
            div.st-key-title_help_row [data-testid="stHorizontalBlock"] {
                display: flex !important;
                flex-direction: row !important;
                align-items: center !important;
                gap: 0px !important;
                justify-content: flex-start !important;
            }
            /* Force columns to hug their content instead of using percentages */
            div.st-key-title_help_row [data-testid="column"],
            div.st-key-title_help_row [data-testid="stColumn"] {
                width: auto !important;
                flex: 0 0 auto !important;
                min-width: 0px !important;
                padding: 0 !important;
            }
            /* Move it LEFT by ensuring the H2 has no trailing margin */
            div.st-key-title_help_row h2 {
                margin-right: 0 !important;
                padding-right: 0 !important;
            }
            /* Move it DOWN to align its bottom with the H2 baseline */
            div.st-key-title_help_row div[class*="st-key-download_settings_explainer_help_btn"] {
                margin-bottom: -20px !important;
                margin-top: 10px !important;
                margin-left: 0 !important;
            }
            </style>
        """)
        with st.container(key="title_help_row"):
            _c1, _c2 = st.columns([1, 10]) # Ratio doesn't matter much with width:auto
            with _c1:
                st.markdown("<h2 style='margin: 0; white-space: nowrap;'>Custom Download</h2>", unsafe_allow_html=True)
            with _c2:
                render_help_card(
                    key_prefix="download_settings",
                    title=help_title,
                    text_html=help_text,
                    mode="button"
                )


    with _hdr_right:
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        # Hoist Base64 icon CSS for the Presets button BEFORE it renders (Static Hoisting)
        _b64_preset_btn_icon = get_base64_image("assets/icon_preset_user.png")
        if _b64_preset_btn_icon:
            st.html(f"""<style>
            div.st-key-btn_presets_hub button div[data-testid="stMarkdownContainer"] p {{
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
            }}
            div.st-key-btn_presets_hub button div[data-testid="stMarkdownContainer"] p::before {{
                content: "";
                display: inline-block;
                width: 20px;
                height: 20px;
                min-width: 20px;
                margin-right: 6px;
                background-image: url('data:image/png;base64,{_b64_preset_btn_icon}');
                background-size: contain;
                background-repeat: no-repeat;
            }}
            </style>""")
        _pb1, _pb2 = st.columns([3, 5], gap="small")
        with _pb1:
            if st.button("Save Preset", key="btn_save_config", use_container_width=True):
                _open_save_config = True
        with _pb2:
            if st.button("Presets", key="btn_presets_hub", use_container_width=True):
                _open_presets_hub = True

    # Help Card Expansion (renders below the header row if open)
    render_help_card(
        key_prefix="download_settings",
        title=help_title,
        text_html=help_text,
        mode="card"
    )

    # NOTE: Card 1 dynamic CSS (active include button state) is injected
    # inside `_card1_fragment` so it re-emits on Card 1 fragment-only reruns.

    step2_container = st.empty()
    with step2_container.container():
        # HOISTED CALLBACKS
        def _toggle_secondary_sub(target_key):
            st.session_state[target_key] = not st.session_state.get(target_key, False)
            active = sum(st.session_state.get(k, False) for k in SECONDARY_CONTENT_KEYS)
            st.session_state['dl_secondary_master'] = (active == TOTAL_SECONDARY_SUBS)

        def _toggle_secondary_master():
            new_state = not st.session_state.get('dl_secondary_master', False)
            st.session_state['dl_secondary_master'] = new_state
            for k in SECONDARY_CONTENT_KEYS:
                st.session_state[k] = new_state

        def _set_isolate_secondary(is_subfolders: bool):
            """Sets the secondary content organization mode."""
            st.session_state['dl_isolate_secondary'] = is_subfolders

        # ── Panopto (Section 4) callbacks ──
        def _pan_recompute_master():
            ready, _, _, _ = _panopto_transcription_ready()
            sel = _panopto_selectable_keys(ready)
            active = sum(1 for k in sel if st.session_state.get(k, False))
            st.session_state['pan_master'] = bool(sel) and active == len(sel)

        def _toggle_pan_sub(target_key):
            st.session_state[target_key] = not st.session_state.get(target_key, False)
            _pan_recompute_master()

        def _toggle_pan_master():
            ready, _, _, _ = _panopto_transcription_ready()
            sel = _panopto_selectable_keys(ready)
            # If every selectable output is on, clear all; otherwise select all
            # selectable outputs (a disabled transcript output stays off).
            all_on = bool(sel) and all(st.session_state.get(k, False) for k in sel)
            new_state = not all_on
            for k, *_ in PANOPTO_OUTPUT_DEFS:
                st.session_state[k] = new_state and (k in sel)
            st.session_state['pan_master'] = new_state and bool(sel)

        def _toggle_pan_info():
            # Collapse/expand the transcription status card. A CALLBACK, not
            # `if st.button(): ...; st.rerun()` - the click already schedules a
            # rerun, and an explicit one renders the page twice and drops the
            # browser's scroll anchor. It also means the chevron's rotation is
            # correct on the first pass instead of drawing its old state once.
            st.session_state['pan_info_open'] = not bool(
                st.session_state.get('pan_info_open', True))

        def _set_pan_layout(value: str):
            st.session_state['pan_layout'] = value if value in ('match', 'separate') else 'match'

        def _get_sec_org_segmented_css():
            b64_inline = _load_b64("assets/icon_sec_inline.png")
            b64_sub = _load_b64("assets/icon_sec_subfolders.png")

            is_sub = st.session_state.get('dl_isolate_secondary', False)
            active_key = "subfolders" if is_sub else "inline"

            return f"""
            <style>
            div[class*="st-key-sec_org_segmented_wrapper"] {{
                background-color: rgba(0, 0, 0, 0.25) !important;
                border: 1px solid rgba(255, 255, 255, 0.05) !important;
                border-radius: 12px !important;
                padding: 4px !important;
                margin-top: 5px !important;
            }}
            div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="stHorizontalBlock"] {{
                gap: 4px !important;
                align-items: stretch !important;
            }}
            /* Equal-height segments even when descriptions wrap to different line counts.
               Flex-grow chain from stColumn down to the button so the shorter segment
               stretches to match the taller (wrapping) one. (testid is stColumn here.) */
            div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="stColumn"] {{
                display: flex !important;
                flex-direction: column !important;
            }}
            div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="stColumn"] [data-testid="stVerticalBlock"],
            div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="stColumn"] [data-testid="stElementContainer"],
            div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="stColumn"] div[data-testid="stButton"] {{
                display: flex !important;
                flex-direction: column !important;
                flex: 1 1 auto !important;
            }}
            div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="stColumn"] button {{
                flex: 1 1 auto !important;
                height: 100% !important;
            }}
            /* Base Segment: tall content (icon top, title, desc) inside the pill */
            div[class*="st-key-btn_sec_org_"] button {{
                position: relative !important;
                min-height: 140px !important;
                background-color: transparent !important;
                border: 1px solid transparent !important;
                background-repeat: no-repeat !important;
                background-position: center 18px !important;
                background-size: 50px !important;
                padding: 80px 14px 16px 14px !important;
                border-radius: 8px !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: center !important;
                justify-content: center !important;
                transition: all 0.2s ease-in-out !important;
                opacity: 0.75 !important;
                color: #a0a0a0 !important;
            }}
            /* Radio pseudo-element (top-right corner) */
            div[class*="st-key-btn_sec_org_"] button::before {{
                top: 16px !important;
                right: 16px !important;
                box-sizing: border-box !important;
            }}
            /* Center the native label */
            div[class*="st-key-btn_sec_org_"] button > div,
            div[class*="st-key-btn_sec_org_"] button div[data-testid="stMarkdownContainer"] {{
                width: 100% !important;
                display: flex !important;
                justify-content: center !important;
                text-align: center !important;
            }}
            div[class*="st-key-btn_sec_org_"] button p {{
                text-align: center !important;
                width: 100% !important;
                margin: 0 !important;
                padding-right: 0 !important;
                font-size: 1.05rem !important;
                font-weight: 600 !important;
                line-height: 1.2 !important;
                color: inherit !important;
            }}
            div.st-key-btn_sec_org_inline button {{ background-image: url('data:image/png;base64,{b64_inline}') !important; }}
            div.st-key-btn_sec_org_subfolders button {{ background-image: url('data:image/png;base64,{b64_sub}') !important; }}

            div[class*="st-key-btn_sec_org_"] button:hover {{
                background-color: rgba(255, 255, 255, 0.05) !important;
                border-color: #68d4a3 !important;
                opacity: 1 !important;
                color: #ffffff !important;
            }}

            /* Disabled State: global.css's `button[disabled]` recipe owns it
               (the local `filter: grayscale(100%)` replaced the shared filter
               rather than adding to it). */

            div.st-key-btn_sec_org_inline button::after {{ content: "Place Canvas Content alongside your other downloaded files." !important; }}
            div.st-key-btn_sec_org_subfolders button::after {{ content: "Create folders for each type (e.g. Assignments/, Quizzes/)" !important; }}
            div[class*="st-key-btn_sec_org_"] button::after {{
                text-align: center !important;
                width: 100% !important;
                display: block !important;
                padding-right: 0 !important;
                font-size: 0.8rem !important;
                color: #a0a0a0 !important;
                margin-top: 5px !important;
                font-weight: 400 !important;
                white-space: normal !important;
                line-height: 1.25 !important;
            }}
            div.st-key-btn_sec_org_{active_key} button {{
                background-color: rgba(104, 212, 163, 0.15) !important; /* Muted Green */
                border: 1px solid #68d4a3 !important;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important; /* Slight drop shadow for the pill */
                color: #ffffff !important;
                opacity: 1 !important;
            }}
            /* Protect Active Green Pill from Grey Hover Override */
            div.st-key-btn_sec_org_{active_key} button:hover {{
                background-color: rgba(104, 212, 163, 0.15) !important;
                border: 1px solid #68d4a3 !important;
                opacity: 1 !important;
            }}
            div[class*="st-key-btn_sec_org_"] button:hover::before {{ border-color: #68d4a3 !important; }}
            div.st-key-btn_sec_org_{active_key} button:hover::before {{ border-color: transparent !important; }}
            div.st-key-btn_sec_org_{active_key} button p {{ color: #ffffff !important; }}
            div.st-key-btn_sec_org_{active_key} button::before {{
                border: none !important;
                background-color: transparent !important;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%2368d4a3' stroke-width='3'/%3E%3Ccircle cx='12' cy='12' r='5' fill='%2368d4a3'/%3E%3C/svg%3E") !important;
            }}
            </style>
            """

        notebook_sub_keys = NOTEBOOK_SUB_KEYS
        TOTAL_NOTEBOOK_SUBS = len(notebook_sub_keys)

        def _toggle_conv_master():
            # If master is currently True (or all subs are True), turn everything off. Otherwise, turn all on.
            current_master = st.session_state.get('notebooklm_master', False)
            new_state = not current_master
            st.session_state['notebooklm_master'] = new_state
            for k in notebook_sub_keys:
                st.session_state[k] = new_state

        def _toggle_conv_sub(key):
            # Flip the specific sub-toggle
            st.session_state[key] = not st.session_state.get(key, False)
            # Re-evaluate the master toggle based on the sum of active subs
            active_count = sum(1 for k in notebook_sub_keys if st.session_state.get(k, False))
            st.session_state['notebooklm_master'] = (active_count == TOTAL_NOTEBOOK_SUBS)

        # HOISTED CSS
        st.html("""
        <style>
        /* Tree-view styling for secondary content sub-checkboxes */
        .st-key-dl_assignments, .st-key-dl_syllabus, .st-key-dl_announcements,
        .st-key-dl_discussions, .st-key-dl_quizzes,
        .st-key-dl_submissions {
            margin-left: 28px !important;
            padding-left: 15px !important;
            border-left: 2px solid """ + theme.BG_CARD_HOVER + """ !important;
            margin-top: -12px !important;
            padding-top: 4px !important;
            padding-bottom: 4px !important;
        }
        .st-key-dl_assignments { margin-top: 0px !important; padding-top: 8px !important; }
        .st-key-dl_submissions { margin-bottom: 10px !important; padding-bottom: 8px !important; }


        </style>
        """)

        # Card elevation CSS - Version-Agnostic Target for Streamlit 1.51+
        # NOTE: The conditional Card 2 flex rule (depends on `card2_expanded`)
        # is re-injected inside `_card2_fragment` so the height-sync updates
        # when only Card 2 reruns.
        st.html("""
    <style>
    /* 1. Target via the explicit Streamlit Keys (Most Reliable) */
    div[class*="st-key-card_core_files"],
    div[class*="st-key-card_native_content"],
    div[class*="st-key-card_ai_engine"],
    div[class*="st-key-card_panopto"],

    /* 2. Target via modern Streamlit 1.51+ Container ID + Trojan Class */
    div[data-testid="stContainer"]:has(.step-2-card-target) {
        background-color: rgba(255, 255, 255, 0.04) !important;
        border-radius: 8px !important;
    }

    /* === Card 1 ↔ Card 2: Height Synchronization ===
       Both cards get flex:1 unconditionally so the headers stay aligned
       whether Card 2 is collapsed or expanded. (Earlier the Card 2 rule
       was conditional on `card2_expanded`, which made the Canvas Content
       header drift upward when Card 2 collapsed.) */
    div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-card_core_files"]),
    div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-card_native_content"]) {
        flex: 1 !important;
    }
    div[class*="st-key-card_core_files"],
    div[class*="st-key-card_native_content"] {
        flex: 1 !important;
    }

    /* ...but flex:1 on the card and its immediate wrapper is NOT enough. Measured
       2026-07-26 (1309px, Card 2 expanded): both stColumns were 789px - the row is
       align-items:stretch, so the COLUMNS were already equal - yet Card 1 rendered
       676px against Card 2's 774px. The break was two levels up: the intermediate
       stLayoutWrapper between the column's vertical block and the card carries
       `flex: 0 1 auto`, so it sized to its content (692px) inside the 789px column.
       Card 2 only looked right because its content happened to fill the column.

       EVERY wrapper between the column and the card has to grow, not just the
       innermost one. The descendant `:has()` (no `>`) is deliberate here - it
       matches the whole ancestor chain, which is exactly what is needed. Scoped to
       `stColumn` so it cannot leak past the row.

       CARD 1 ONLY. Card 2 sets the height and must stay content-sized: applying
       the same rule to card_native_content made the COLLAPSED Canvas Content card
       stretch from a slim 74px header into a ~590px empty box. Card 1 growing is
       enough, because the column is sized by whichever card is taller.

       Verified 0px bottom-edge delta at zoom 0.67 / 0.8 / 1 / 1.25 / 1.5 and at
       1000px / 1309px / 1455px wide, with Card 2 both collapsed and expanded. */
    div[data-testid="stColumn"] div[data-testid="stLayoutWrapper"]:has(div[class*="st-key-card_core_files"]),
    div[data-testid="stColumn"] div[data-testid="stVerticalBlock"]:has(div[class*="st-key-card_core_files"]) {
        flex: 1 1 auto !important;
    }

    /* Vertical alignment shim - Card 2's trojan div has a more aggressive
       negative margin-top (-25px) than Card 1's (-10px), which makes its
       outer container collapse 15px higher up. Use padding-top (not margin-top)
       so Card 2's flex box still fills the full column height - margin would
       shrink the box and leave Card 2's bottom edge 15px short of Card 1's. */
    div[class*="st-key-card_native_content"] {
        margin-top: 15px !important;
    }

    </style>
    """)

        col1, col2 = st.columns([3, 5], gap="medium")

        # --- COLUMN 1: Organization & Include Files ---
        @st.fragment
        def _render_card1():
            # Card 1 dynamic CSS (active include + global button base).
            # Lives inside the fragment so the active-state CSS re-injects on
            # Card 1 fragment-only reruns (toggling include keeps the rest of
            # the page from rerunning, which is the whole point of fragments).
            b64_icon_all = _load_b64("assets/icon_all_files.png")
            b64_icon_study = _load_b64("assets/icon_study_files.png")
            active_include = st.session_state.get('file_filter', 'all')
            active_include_key = "all" if active_include == 'all' else "study"
            st.markdown(f'''
            <style>
            /* GLOBAL CHECKBOX PSEUDO-ELEMENT BASE */
            div[class*="st-key-btn_"] button::before {{
                content: "" !important;
                position: absolute !important;
                top: 10px !important;
                right: 10px !important;
                width: 16px !important;
                height: 16px !important;
                border: 2px solid rgba(255, 255, 255, 0.2) !important;
                border-radius: 4px !important;
                background-color: transparent !important;
                background-size: contain !important;
                background-repeat: no-repeat !important;
                background-position: center !important;
                transition: all 0.2s ease-in-out !important;
                box-sizing: border-box !important;
            }}
            /* Hide Checkboxes on Action Buttons & Master Toggles */
            div.st-key-btn_save_config button::before,
            div.st-key-btn_presets_hub button::before,
            div.st-key-btn_dl_secondary_master button::before,
            div.st-key-btn_convert_master button::before,
            div.st-key-btn_preset_hub_close button::before {{
                display: none !important;
            }}
            /* Circular Mutually Exclusive Toggles */
            div[class*="st-key-btn_include_"] button::before,
            div[class*="st-key-btn_org_"] button::before,
            div[class*="st-key-btn_sec_org_"] button::before {{
                border-radius: 50% !important;
            }}
            /* Apply generic buffer so text avoids the absolute checkboxes */
            div[class*="st-key-btn_"] button p,
            div[class*="st-key-btn_"] button::after {{
                padding-right: 16px !important;
                box-sizing: border-box !important;
            }}
            /* Exclude Organization Master Buttons from Text Buffer */
            div.st-key-btn_org_all button p, div.st-key-btn_org_all button::after,
            div.st-key-btn_org_modules button p, div.st-key-btn_org_modules button::after {{
                padding-right: 0px !important;
            }}

            /* 1. Outer Container: segmented-control pill shell */
            div[class*="st-key-include_files_segmented_wrapper"] {{
                background-color: rgba(0, 0, 0, 0.25) !important;
                border: 1px solid rgba(255, 255, 255, 0.05) !important;
                border-radius: 12px !important;
                padding: 4px !important;
                margin-top: 5px !important;
            }}
            div[class*="st-key-include_files_segmented_wrapper"] [data-testid="stHorizontalBlock"] {{
                gap: 4px !important;
                align-items: stretch !important;
            }}

            /* 2. Equal-height segments: flex-grow chain from stColumn down to the button */
            div[class*="st-key-include_files_segmented_wrapper"] [data-testid="stColumn"] {{
                display: flex !important;
                flex-direction: column !important;
            }}
            div[class*="st-key-include_files_segmented_wrapper"] [data-testid="stColumn"] [data-testid="stVerticalBlock"],
            div[class*="st-key-include_files_segmented_wrapper"] [data-testid="stColumn"] [data-testid="stElementContainer"],
            div[class*="st-key-include_files_segmented_wrapper"] [data-testid="stColumn"] div[data-testid="stButton"] {{
                display: flex !important;
                flex-direction: column !important;
                flex: 1 1 auto !important;
            }}
            div[class*="st-key-include_files_segmented_wrapper"] [data-testid="stColumn"] button {{
                flex: 1 1 auto !important;
                height: 100% !important;
            }}

            /* 3. Base Segment: tall content (icon top, title, desc) inside the pill */
            div[class*="st-key-btn_include_"] button {{
                position: relative !important;
                min-height: 140px !important;
                background-color: transparent !important;
                background-repeat: no-repeat !important;
                background-position: center 18px !important;
                background-size: 50px !important;
                padding: 80px 14px 16px 14px !important;
                border: 1px solid transparent !important;
                border-radius: 8px !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: center !important;
                justify-content: center !important;
                transition: all 0.2s ease-in-out !important;
                opacity: 0.75 !important;
                color: #a0a0a0 !important;
            }}

            /* 4. Primary Title Styling (The native button label) */
            div[class*="st-key-btn_include_"] button p {{
                font-size: 1.05rem !important;
                font-weight: 600 !important;
                margin: 0 !important;
                margin-bottom: 0px !important;
                line-height: 1.2 !important;
                color: inherit !important;
                width: 100% !important;
                text-align: center !important;
                padding-right: 0 !important;
            }}

            div[class*="st-key-btn_include_"] button::after {{
                margin-bottom: 0px !important;
                padding-bottom: 0px !important;
                width: 100% !important;
                text-align: center !important;
                padding-right: 0 !important;
            }}

            /* 5. Geometry lockdown for radio pseudo-element on Card 1 */
            div[class*="st-key-btn_include_"] button::before {{
                top: 16px !important;
                right: 16px !important;
                box-sizing: border-box !important;
            }}

            /* Icon Layer (native background) */
            div.st-key-btn_include_all button {{ background-image: url('data:image/png;base64,{b64_icon_all}') !important; }}
            div.st-key-btn_include_study button {{ background-image: url('data:image/png;base64,{b64_icon_study}') !important; }}

            /* 6. Descriptions (::after) */
            div.st-key-btn_include_all button::after {{
                content: "Includes everything from the Canvas folder" !important;
                font-size: 0.85rem !important;
                line-height: 1.1 !important;
                color: #a0a0a0 !important;
                margin-top: -1px !important;
                font-weight: 400 !important;
            }}
            div.st-key-btn_include_study button::after {{
                content: "Download PDFs & PowerPoints only" !important;
                font-size: 0.85rem !important;
                line-height: 1.1 !important;
                color: #a0a0a0 !important;
                margin-top: -1px !important;
                font-weight: 400 !important;
            }}

            /* 6.5 Hover State (Inactive Buttons) - matches Card 2 segmented styling */
            div[class*="st-key-btn_include_"] button:hover {{
                border-color: #3fd9ff !important;
                background-color: rgba(255, 255, 255, 0.05) !important;
                opacity: 1 !important;
                color: #ffffff !important;
            }}

            /* 7. Active State Logic - matches Card 2 (bg 0.15 + 0.3-alpha border + drop shadow) */
            div.st-key-btn_include_{active_include_key} button {{
                background-color: rgba(63, 217, 255, 0.15) !important;
                border: 1px solid #3fd9ff !important;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;
                opacity: 1 !important;
                color: #ffffff !important;
            }}
            /* Protect Active Blue Pill from Grey Hover Override */
            div.st-key-btn_include_{active_include_key} button:hover {{
                background-color: rgba(63, 217, 255, 0.15) !important;
                border: 1px solid #3fd9ff !important;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;
                opacity: 1 !important;
                color: #ffffff !important;
            }}

            div[class*="st-key-btn_include_"] button:hover::before {{ border-color: #3fd9ff !important; }}
            div.st-key-btn_include_{active_include_key} button:hover::before {{ border-color: transparent !important; }}
            div.st-key-btn_include_{active_include_key} button::before {{
                border: none !important;
                background-color: transparent !important;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%233fd9ff' stroke-width='3'/%3E%3Ccircle cx='12' cy='12' r='5' fill='%233fd9ff'/%3E%3C/svg%3E") !important;
            }}
            </style>
            ''', unsafe_allow_html=True)

            with st.container(border=True, key="card_core_files"):
                b64_wf1 = _load_b64("assets/icon_workflow_1.png")
                st.markdown(f"""<div class='step-2-card-target' style='position: relative; margin-top: -10px; margin-bottom: 12px;'>
    <img src='data:image/png;base64,{b64_wf1}' style='position: absolute; width: 36px; height: 36px; top: -24px; left: -34px; z-index: 10;'>
    <div style='padding-left: 0px;'>
    <h3 style='margin: 0; line-height: 1.2;'>Course Files &amp; Organization</h3>
    </div>
    </div>
    <p style='font-size: 0.95rem; color: #e2e8f0; margin-top: -20px; margin-bottom: 0px;'>Manage how teacher-uploaded files should be downloaded. </p>
    <hr style='border: none; border-top: 1px solid rgba(255, 255, 255, 0.15); margin-top: 15px; margin-bottom: 15px;'>""", unsafe_allow_html=True)

                # 1. Include Files Block (Segmented Control)
                def update_include_state(mode):
                    st.session_state['file_filter'] = mode

                with st.container(key="card1_include_section"):
                    st.markdown(
                        "<p style='font-size: 0.9rem; font-weight: 600; color: #cbd5e1; margin-top: 0px; margin-bottom: 0px;'>Choose which files to download:</p>", 
                        unsafe_allow_html=True
                    )
                    with st.container(key="include_files_segmented_wrapper"):
                        inc_left, inc_right = st.columns(2, gap="small")
                        with inc_left:
                            st.button("All Files (default)", key="btn_include_all", use_container_width=True, on_click=update_include_state, args=("all",))
                        with inc_right:
                            st.button("Slides & PDFs", key="btn_include_study", use_container_width=True, on_click=update_include_state, args=("study",))

                st.html("<div style='padding-bottom: 0px;'></div>")

                # 2. Organization Block (Large Buttons)
                def update_org_state(mode):
                    st.session_state['download_mode'] = 'modules' if mode == 'subfolders' else mode

                st.markdown(
                    "<p style='font-size: 0.9rem; font-weight: 600; color: #cbd5e1; margin-top: 0px; margin-bottom: 0px;'>Choose how files should be organized:</p>", 
                    unsafe_allow_html=True
                )

                b64_subfolders = get_base64_image("assets/icon_subfolders.png")
                b64_flat = get_base64_image("assets/icon_flat.png")

                with st.container(key="org_segmented_wrapper"):
                    btn_left, btn_right = st.columns(2)
                    with btn_left:
                        st.button("With Subfolders", key="btn_org_subfolders", use_container_width=True, on_click=update_org_state, args=("subfolders",))
                    with btn_right:
                        st.button("All in One Folder", key="btn_org_flat", use_container_width=True, on_click=update_org_state, args=("flat",))

                active_mode = st.session_state.get('download_mode', 'modules')
                active_btn_key = "subfolders" if active_mode == 'modules' else "flat"

                # NOTE: this line used to read `theme.PRIMARY_BLUE if hasattr(...)
                # else theme.ACCENT_LINK`. There is no PRIMARY_BLUE token - the
                # token is BLUE_PRIMARY - so the hasattr never passed and this has
                # ALWAYS rendered ACCENT_LINK. Kept as ACCENT_LINK deliberately:
                # that is the colour this control is signed off with, and the two
                # blues are 20.6 CIEDE2000 apart, so "fixing" the name would be a
                # visible restyle, not a repair. Switch to theme.BLUE_PRIMARY only
                # as an intentional design change.
                border_color = theme.ACCENT_LINK

                st.markdown(f'''
                <style>
                /* Outer Container: segmented-control pill shell */
                div[class*="st-key-org_segmented_wrapper"] {{
                    background-color: rgba(0, 0, 0, 0.25) !important;
                    border: 1px solid rgba(255, 255, 255, 0.05) !important;
                    border-radius: 12px !important;
                    padding: 4px !important;
                    margin-top: 5px !important;
                }}
                div[class*="st-key-org_segmented_wrapper"] [data-testid="stHorizontalBlock"] {{
                    gap: 4px !important;
                    align-items: stretch !important;
                }}
                /* Equal-height segments: flex-grow chain from stColumn down to the button */
                div[class*="st-key-org_segmented_wrapper"] [data-testid="stColumn"] {{
                    display: flex !important;
                    flex-direction: column !important;
                }}
                div[class*="st-key-org_segmented_wrapper"] [data-testid="stColumn"] [data-testid="stVerticalBlock"],
                div[class*="st-key-org_segmented_wrapper"] [data-testid="stColumn"] [data-testid="stElementContainer"],
                div[class*="st-key-org_segmented_wrapper"] [data-testid="stColumn"] div[data-testid="stButton"] {{
                    display: flex !important;
                    flex-direction: column !important;
                    flex: 1 1 auto !important;
                }}
                div[class*="st-key-org_segmented_wrapper"] [data-testid="stColumn"] button {{
                    flex: 1 1 auto !important;
                    height: 100% !important;
                }}

                /* Base Segment: tall content (icon top, title, desc) inside the pill */
                div[class*="st-key-btn_org_"] button {{
                    position: relative !important;
                    min-height: 140px !important;
                    background-color: transparent !important;
                    background-repeat: no-repeat !important;
                    background-position: center 18px !important;
                    background-size: 50px !important;
                    padding: 80px 14px 16px 14px !important;
                    border: 1px solid transparent !important;
                    border-radius: 8px !important;
                    display: flex !important;
                    flex-direction: column !important;
                    align-items: center !important;
                    justify-content: center !important;
                    transition: all 0.2s ease-in-out !important;
                    opacity: 0.75 !important;
                    color: #a0a0a0 !important;
                }}

                /* Primary Title Styling (The native button label) */
                div[class*="st-key-btn_org_"] button p {{
                    font-size: 1.05rem !important;
                    font-weight: 600 !important;
                    margin: 0 !important;
                    margin-bottom: 0px !important;
                    line-height: 1.2 !important;
                    color: inherit !important;
                    width: 100% !important;
                    text-align: center !important;
                    padding-right: 0 !important;
                }}

                div[class*="st-key-btn_org_"] button::after {{
                    margin-bottom: 0px !important;
                    padding-bottom: 0px !important;
                    width: 100% !important;
                    text-align: center !important;
                    padding-right: 0 !important;
                }}

                /* Geometry lockdown for radio pseudo-element on Card 1 */
                div[class*="st-key-btn_org_"] button::before {{
                    top: 16px !important;
                    right: 16px !important;
                    box-sizing: border-box !important;
                }}

                /* Hover State - matches Card 2 segmented styling */
                div[class*="st-key-btn_org_"] button:hover {{
                    border-color: #3fd9ff !important;
                    background-color: rgba(255, 255, 255, 0.05) !important;
                    opacity: 1 !important;
                    color: #ffffff !important;
                }}

                /* ----- SUBFOLDERS SPECIFIC ----- */
                div.st-key-btn_org_subfolders button {{
                    background-image: url('data:image/png;base64,{b64_subfolders}') !important;
                }}
                div.st-key-btn_org_subfolders button::after {{
                    content: "Organize files exactly as they appear in Canvas." !important;
                    font-size: 0.85rem !important;
                    line-height: 1.1 !important;
                    color: #a0a0a0 !important;
                    margin-top: -1px !important;
                    font-weight: 400 !important;
                }}

                /* ----- FLAT SPECIFIC ----- */
                div.st-key-btn_org_flat button {{
                    background-image: url('data:image/png;base64,{b64_flat}') !important;
                }}
                div.st-key-btn_org_flat button::after {{
                    content: "Place all files together in the course folder." !important;
                    font-size: 0.85rem !important;
                    line-height: 1.1 !important;
                    color: #a0a0a0 !important;
                    margin-top: -1px !important;
                    font-weight: 400 !important;
                }}

                /* Active State Highlight - matches Card 2 (bg 0.15 + 0.3-alpha border + drop shadow) */
                div.st-key-btn_org_{active_btn_key} button {{
                    background-color: rgba(63, 217, 255, 0.15) !important;
                    border: 1px solid #3fd9ff !important;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;
                    opacity: 1 !important;
                    color: #ffffff !important;
                }}
                /* Protect Active State from generic Hover Overrides */
                div.st-key-btn_org_{active_btn_key} button:hover {{
                    background-color: rgba(63, 217, 255, 0.15) !important;
                    border: 1px solid #3fd9ff !important;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;
                    opacity: 1 !important;
                    color: #ffffff !important;
                }}
                div[class*="st-key-btn_org_"] button:hover::before {{ border-color: #3fd9ff !important; }}
                div.st-key-btn_org_{active_btn_key} button:hover::before {{ border-color: transparent !important; }}
                div.st-key-btn_org_{active_btn_key} button::before {{
                    border: none !important;
                    background-color: transparent !important;
                    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%233fd9ff' stroke-width='3'/%3E%3Ccircle cx='12' cy='12' r='5' fill='%233fd9ff'/%3E%3C/svg%3E") !important;
                }}
                </style>
                ''', unsafe_allow_html=True)

        with col1:
            _render_card1()

        # --- COLUMN 2: Additional Course Content ---
        @st.fragment
        def _render_card2():
            with st.container(border=True, key="card_native_content"):
                m_active = st.session_state.get('dl_secondary_master', False)
                _sec_active = sum(1 for k in SECONDARY_CONTENT_KEYS if st.session_state.get(k, False))
                has_active_items2 = _sec_active > 0 or m_active

                _c2_is_exp = st.session_state.get('card2_expanded', False)
                c2_tag_bg = "rgba(104, 212, 163, 0.15)"
                c2_tag_col = "#68d4a3"
                c2_tag_bor = "1px solid transparent"

                if _sec_active == 0:
                    c2_tag_bg = "rgba(255, 255, 255, 0.05)"
                    c2_tag_col = "#94a3b8"
                    c2_tag_bor = "1px solid rgba(255, 255, 255, 0.1)"
                    if not _c2_is_exp:
                        dynamic_tag = "<strong>OFF</strong>"
                    else:
                        dynamic_tag = "<strong>OFF</strong>  |  None selected"
                elif _sec_active == TOTAL_SECONDARY_SUBS:
                    dynamic_tag = "<strong>ON</strong>  |  All selected"
                else:
                    dynamic_tag = f"<strong>ON</strong>  |  {_sec_active} selected"

                def toggle_card2():
                    st.session_state['card2_expanded'] = not st.session_state.get('card2_expanded', False)

                c2_exp = st.session_state.get('card2_expanded', False)
                chr_svg = _get_chevron_base64(c2_exp)
                b64_wf2 = _load_b64("assets/icon_workflow_2.png")
                c_filter = "grayscale(0%) brightness(100%)" if has_active_items2 else "grayscale(100%) brightness(60%)"

                # Compute chevron colors BEFORE the button renders
                c2_base_color = "#94a3b8" if c2_exp else "#64748b"
                c2_hover_color = "#cbd5e1" if c2_exp else "#94a3b8"

                # THE FIX: Inject chevron CSS BEFORE the button to prevent ghost flash
                st.markdown(f'''<style>
                div.st-key-header_wrap_card2 {{
                    display: flex !important;
                    flex-direction: row !important;
                    align-items: center !important;
                    justify-content: flex-start !important;
                    gap: 12px !important;
                    padding-top: 0px !important;
                    padding-bottom: 0px !important;
                    margin-top: -35px !important;
                }}
                div.st-key-header_wrap_card2 > div[data-testid="stElementContainer"] {{
                    margin-bottom: 0px !important;
                }}
                div.st-key-header_wrap_card2 > div[data-testid="stElementContainer"]:nth-child(1) {{
                    width: 24px !important;
                    min-width: 24px !important;
                    flex: 0 0 24px !important;
                }}
                div.st-key-header_wrap_card2 > div[data-testid="stElementContainer"]:nth-child(2) {{
                    flex: 1 1 auto !important;
                    width: 100% !important;
                }}
                /* Kill focus rings on the parent wrappers */
                div.st-key-toggle_card2 div[data-testid="stButton"]:focus-within,
                div.st-key-toggle_card2 div[data-testid="stBaseButton-secondary"]:focus-within {{
                    box-shadow: none !important;
                    outline: none !important;
                    background: transparent !important;
                }}
                /* Kill focus rings on the button itself during focus shifts */
                div.st-key-toggle_card2 button:focus-visible,
                div.st-key-toggle_card2 button:focus:not(:active),
                div.st-key-toggle_card2 button:focus {{
                    box-shadow: none !important;
                    outline: none !important;
                    border: none !important;
                    background-color: {c2_base_color} !important; 
                }}
                /* Ensure the inner markdown div remains completely hidden */
                div.st-key-toggle_card2 button > div {{
                    display: none !important;
                }}
                /* BASE MASK STATE */
                div.st-key-toggle_card2 button {{
                    all: unset !important;
                    display: inline-block !important;
                    cursor: pointer !important;
                    width: 24px !important;
                    height: 24px !important;
                    position: relative !important;
                    top: 5px !important;
                    -webkit-mask-image: {chr_svg} !important;
                    -webkit-mask-size: contain !important;
                    -webkit-mask-repeat: no-repeat !important;
                    -webkit-mask-position: center !important;
                    background-color: {c2_base_color} !important;
                    transition: background-color 0.2s ease !important;
                    box-shadow: none !important;
                    outline: none !important;
                    border: none !important;
                    -webkit-tap-highlight-color: transparent !important;
                }}
                /* HOVER STATE */
                div.st-key-toggle_card2 button:hover {{ background-color: {c2_hover_color} !important; box-shadow: none !important; }}
                /* ACTIVE KILLER */
                div.st-key-toggle_card2 button:active {{
                    box-shadow: none !important;
                    outline: none !important;
                    border: none !important;
                    transform: none !important;
                }}
                /* RERUN LOCK - the sanctioned exemption from global.css's
                   `button[disabled]` recipe. This button IS the card header's
                   surface, and it is only `disabled` for the duration of a
                   rerun, so the shared brightness(0.5) filter would flash the
                   whole card header dark on every toggle. It is a lock, not an
                   affordance the user reads as unavailable. */
                div.st-key-toggle_card2 button[disabled] {{
                    box-shadow: none !important;
                    outline: none !important;
                    border: none !important;
                    background-color: {c2_base_color} !important;
                    opacity: 0.8 !important;
                    filter: none !important;
                }}
                </style>''', unsafe_allow_html=True)

                st.markdown(f"<div class='step-2-card-target' style='position: relative; margin-top: -25px; margin-bottom: 0px;'><img src='data:image/png;base64,{b64_wf2}' style='position: absolute; width: 36px; height: 36px; top: -24px; left: -34px; z-index: 10; filter: {c_filter}; transition: all 0.2s ease;' /></div>", unsafe_allow_html=True)

                with st.container(key="header_wrap_card2"):
                    st.button("\u200B", key="toggle_card2", on_click=toggle_card2)
                    st.markdown(f"""<div style='display: flex; align-items: center; justify-content: space-between; padding-right: 10px; width: 100%; transform: translateY(-5px);'><h3 style='margin: 0px !important; padding: 0px !important; line-height: 1 !important;'>Canvas Content <span style='color: #64748b; font-size: 0.8em; font-weight: normal;'>(Optional)</span></h3><span style='background-color: {c2_tag_bg}; color: {c2_tag_col}; border: {c2_tag_bor}; font-size: 0.8rem; padding: 2px 12px; border-radius: 15px; font-weight: 600; transition: all 0.2s ease;'>{dynamic_tag}</span></div>""", unsafe_allow_html=True)

                css_blocks = []

                # Button data
                button_defs = [
                    ('dl_assignments', 'Assignments', 'Includes assignment descriptions and any attached files.', 'icon_assignments.png'),
                    ('dl_announcements', 'Announcements', 'Save course announcements and any attached files.', 'icon_announcements.png'),
                    ('dl_quizzes', 'Quizzes', 'Save quiz questions and answers as HTML.', 'icon_quizzes.png'),
                    ('dl_syllabus', 'Syllabus', 'Save the course syllabus page as HTML.', 'icon_syllabus.png'),
                    ('dl_discussions', 'Discussions', 'Save discussion threads as HTML.', 'icon_discussions.png'),
                    ('dl_submissions', 'Submissions (Results)', 'Save grades, rubric scores and teacher comments. Not your own uploaded files.', 'icon_submissions.png')
                ]

                css_blocks.append('''
                div[class*="st-key-secondary_cards_grid"] {
                    display: grid !important;
                    grid-template-columns: repeat(3, 1fr) !important;
                    grid-auto-rows: 1fr !important;
                    gap: 12px !important;
                }
                div[class*="st-key-secondary_cards_grid"] > div[data-testid="stElementContainer"] {
                    margin-bottom: 0px !important;
                    width: 100% !important;
                }
                div[class*="st-key-secondary_cards_grid"] > div[data-testid="stElementContainer"],
                div[class*="st-key-secondary_cards_grid"] > div[data-testid="stElementContainer"] div[data-testid="stButton"],
                div[class*="st-key-secondary_cards_grid"] > div[data-testid="stElementContainer"] button {
                    height: 100% !important;
                }
                @media (max-width: 900px) {
                    div[class*="st-key-secondary_cards_grid"] {
                        grid-template-columns: repeat(2, 1fr) !important;
                    }
                }
                @media (max-width: 600px) {
                    div[class*="st-key-secondary_cards_grid"] {
                        grid-template-columns: 1fr !important;
                    }
                }
                /* Nuke Streamlit's center alignment */
                div[class*="st-key-btn_dl_"] button > div,
                div[class*="st-key-btn_dl_"] button div[data-testid="stMarkdownContainer"] {
                    width: 100% !important;
                    display: flex !important;
                    justify-content: flex-start !important;
                    text-align: left !important;
                }
                div[class*="st-key-btn_dl_"] button p {
                    text-align: left !important;
                    width: 100% !important;
                    margin-top: 0px !important;
                    margin-bottom: 0px !important;
                    line-height: 1.2 !important;
                }
                div[class*="st-key-btn_dl_"] button::after {
                    text-align: left !important;
                    width: 100% !important;
                    display: block !important;
                }
                div[class*="st-key-btn_dl_"] button {
                    min-height: 58px !important;
                    height: auto !important;
                    padding-top: 10px !important;
                    padding-bottom: 10px !important;
                    padding-right: 10px !important;
                    padding-left: 50px !important;
                    background-position: 15px center !important;
                    background-size: 24px !important;
                    background-repeat: no-repeat !important;
                    border-radius: 12px !important;
                    display: flex;
                    flex-direction: column;
                    -webkit-tap-highlight-color: transparent !important;
                }
                div.st-key-btn_dl_secondary_master button {
                    height: 48px !important;
                    padding-top: 0px !important;
                    padding-bottom: 0px !important;
                    justify-content: center !important;
                }
                ''')

                # Master CSS
                # Master CSS
                m_bg = "rgba(255, 255, 255, 0.12)" if m_active else "rgba(255, 255, 255, 0.1)"
                m_border = "rgba(255, 255, 255, 0.1)"
                m_ledge = "#68d4a3" if m_active else "transparent"
                m_ledge_border = "#68d4a3" if m_active else m_border
                b64_m = safe_b64('icon_canvas_content_select_all.png')
                m_img_rule = f"background-image: url('data:image/png;base64,{b64_m}') !important;" if b64_m else ""

                css_blocks.append(f'''
                div.st-key-btn_dl_secondary_master button {{
                    background-color: {m_bg} !important;
                    border: 1px solid {m_border} !important;
                    border-bottom: 1px solid {m_ledge_border} !important;
                    box-shadow: inset 0 -3px 0 0 {m_ledge} !important;
                    border-radius: 12px !important;
                    {m_img_rule}
                }}
                ''')

                if not m_active:
                    css_blocks.append('''
                    div.st-key-btn_dl_secondary_master button:hover {
                        border-bottom: 1px solid #3e8162 !important;
                        box-shadow: inset 0 -3px 0 0 #3e8162 !important;
                    }
                    ''')

                if m_active:
                    css_blocks.append('''
                    /* Master button checkbox intentionally hidden by global rule. Left empty here for compatibility. */
                    ''')

                # Child CSS
                for key, title, desc, icon in button_defs:
                    is_active = st.session_state.get(key, False)
                    c_bg = "rgba(104, 212, 163, 0.15)" if is_active else "rgba(255, 255, 255, 0.02)"
                    c_border = "#68d4a3" if is_active else "rgba(255, 255, 255, 0.1)"
                    b64_c = safe_b64(icon)
                    c_img_rule = f"background-image: url('data:image/png;base64,{b64_c}') !important;" if b64_c else ""

                    if is_active:
                        c_check = f'''
                        div.st-key-btn_{key} button::before {{
                            border: none !important;
                            background-color: transparent !important;
                            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cdefs%3E%3Cmask id='m'%3E%3Crect width='24' height='24' fill='white'/%3E%3Cpath d='M20 6L9 17l-5-5' fill='none' stroke='black' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/mask%3E%3C/defs%3E%3Crect width='24' height='24' rx='4' fill='%2368d4a3' mask='url(%23m)'/%3E%3C/svg%3E") !important;
                        }}
                        div.st-key-btn_{key} button:hover::before {{ border-color: transparent !important; }}
                        '''
                    else:
                        c_check = ""

                    css_blocks.append(f'''
                    div.st-key-btn_{key} button {{
                        background-color: {c_bg} !important;
                        border: 1px solid {c_border} !important;
                        {c_img_rule}
                    }}
                    div.st-key-btn_{key} button::after {{
                        content: "{desc}" !important;
                        font-size: 0.75rem !important; color: #a0a0a0; white-space: normal !important;
                        display: block !important; text-align: left !important; width: 100%; margin-top: -2px !important; line-height: 1.2 !important;
                    }}
                    div.st-key-btn_{key} button:hover {{
                        border-color: #68d4a3 !important;
                    }}
                    div.st-key-btn_{key} button:hover::before {{
                        border-color: #68d4a3 !important;
                    }}
                    {c_check}
                    ''')

                final_html = f"<style>{''.join(css_blocks)}</style>"

                if c2_exp:
                    st.markdown(f"""{final_html}
<p style='font-size: 0.95rem; color: #e2e8f0; margin-top: -15px; margin-bottom: 0px;'>Save information, pages and other content from Canvas to your local Course folder.</p>
<hr style='border: none; border-top: 1px solid rgba(255, 255, 255, 0.15); margin-top: 15px; margin-bottom: 15px;'>""", unsafe_allow_html=True)
                    st.button("Select All", key="btn_dl_secondary_master", on_click=_toggle_secondary_master, use_container_width=True)

                    with st.container(key="secondary_cards_grid"):
                        for key, title, _, _ in button_defs:
                            st.button(title, key=f"btn_{key}", on_click=_toggle_secondary_sub, args=(key,), use_container_width=True)

                    # --- Section 2: Canvas-Native Content Organization ---
                    # Dim the label if no secondary content is active
                    sec_org_label_color = "#cbd5e1" if _sec_active > 0 else "#475569"

                    st.markdown(f"""
                    <p style='font-size: 0.9rem; font-weight: 600; color: {sec_org_label_color}; margin-top: 15px; margin-bottom: 0px;'>Choose how Canvas Content should be organized:</p>
                    {_get_sec_org_segmented_css()}
                    """, unsafe_allow_html=True)

                    with st.container(key="sec_org_segmented_wrapper"):
                        c1, c2 = st.columns(2, gap="small")

                        is_disabled = (_sec_active == 0)
                        # Only while disabled - see _NAV_LOCKED_HELP note in ui/auth.py.
                        _sec_org_help = ("Select at least one Canvas Content type above "
                                         "to choose how it is organized.") if is_disabled else None

                        with c1:
                            st.button(
                                "Match Course Folder structure", 
                                key="btn_sec_org_inline", 
                                on_click=_set_isolate_secondary, 
                                args=(False,), 
                                use_container_width=True,
                                disabled=is_disabled,
                                help=_sec_org_help,
                            )
                        with c2:
                            st.button(
                                "In Separate Folders", 
                                key="btn_sec_org_subfolders", 
                                on_click=_set_isolate_secondary, 
                                args=(True,), 
                                use_container_width=True,
                                disabled=is_disabled,
                                help=_sec_org_help,
                            )




        with col2:
            _render_card2()

        # Force a visual break between top and bottom rows
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

        # --- BOTTOM ROW: Conversion Settings / NotebookLM ---
        @st.fragment
        def _render_card3_inner():
            # --- Conversion Button Data ---
            conv_button_defs = [
                # The tooltip states a real limit, not a nicety: every other
                # converter here applies to whatever it can reach, and this one
                # deliberately stops at the archive's edge. Without saying so,
                # a user who turns on "Code & Data" and "Unpack Archives"
                # together has every reason to expect the code inside the zip to
                # be converted, and no way to find out that it will not be.
                ('convert_zip',   'Unpack Archives',    'Auto-unzip .zip and .tar.gz archives.',        'icon_conv_zip.png',
                 'The files inside an archive are left exactly as they are - no other conversion is applied to them, so code projects and their folder structure stay intact.'),
                ('convert_pptx',  'PowerPoint ⭢ PDF',         'Convert .pptx/.ppt to PDF.',      'icon_conv_pptx.png', 'Requires the Microsoft PowerPoint desktop app'),
                ('convert_word',  'Legacy Word Docs ⭢ PDF',          'Convert unsupported older formats (.doc, .rtf, .odt) to PDF.',                    'icon_conv_word.png', 'Requires the Microsoft Word desktop app'),
                ('convert_excel', 'Excel ⭢ PDF & AI Data',              'Export each spreadsheet as PDF + structured .txt with all cell data.',                'icon_conv_excel.png', 'Requires Microsoft Excel. AI data file only for .xlsx/.xlsm (not .xls)'),
                ('convert_html',  'Canvas Pages ⭢ Plain Text',          'Convert Canvas web pages into AI-friendly text.',          'icon_conv_html.png', None),
                # The example has to match what converters/code.py actually
                # writes: the dot before the extension becomes an underscore
                # (`code.js` -> `code_js.txt`), it is not a suffix append. The
                # old copy promised `code.js.txt`, which is a filename that
                # never exists - a user searching for it finds nothing.
                ('convert_code',  'Code & Data ⭢ .txt',       'Rewrite code and data files as readable .txt (e.g. code_js.txt).',          'icon_conv_code.png', None),
                ('convert_urls',  'Gather Web Links in .txt',        'Compile all internet shortcuts into one structured .txt file.',        'icon_conv_urls.png', None),
                ('convert_video', 'Video ⭢ Audio',            'Extract .mp3 audio from video files.',          'icon_conv_video.png', None),
            ]

            # --- Dynamic Tag Counter ---
            _conv_active = sum(1 for k in notebook_sub_keys if st.session_state.get(k, False))

            _c3_is_exp = st.session_state.get('card3_expanded', False)
            c3_tag_bg = "rgba(249, 115, 22, 0.15)"
            c3_tag_col = "#f97316"
            c3_tag_bor = "1px solid transparent"

            if _conv_active == 0:
                c3_tag_bg = "rgba(255, 255, 255, 0.05)"
                c3_tag_col = "#94a3b8"
                c3_tag_bor = "1px solid rgba(255, 255, 255, 0.1)"
                if not _c3_is_exp:
                    conv_tag = "<strong>OFF</strong>"
                else:
                    conv_tag = "<strong>OFF</strong>  |  None selected"
            elif _conv_active == TOTAL_NOTEBOOK_SUBS:
                conv_tag = "<strong>ON</strong>  |  All selected"
            else:
                conv_tag = f"<strong>ON</strong>  |  {_conv_active} selected"

            # --- Dynamic CSS only ---
            # Static layout/geometry/description/hover rules live in
            # styles/global.css (under "Card 3 - static button styling").
            # Here we only emit the parts that depend on session state:
            # icon URLs and active-state coloring + active checkmark SVG.
            conv_css_blocks = []

            # Master (Select All) - dynamic active state + icon
            m_active = st.session_state.get('notebooklm_master', False)
            b64_conv_m = safe_b64('icon_conv_select_all.png')
            m_conv_img_rule = f"background-image: url('data:image/png;base64,{b64_conv_m}') !important;" if b64_conv_m else ""

            if m_active:
                conv_css_blocks.append(
                    f'div.st-key-btn_convert_master button {{ background-color: rgba(255, 255, 255, 0.12) !important; border-bottom: 1px solid #f97316 !important; box-shadow: inset 0 -3px 0 0 #f97316 !important; {m_conv_img_rule} }}\n'
                )
            else:
                conv_css_blocks.append(
                    f'div.st-key-btn_convert_master button {{ {m_conv_img_rule} }}\n'
                    'div.st-key-btn_convert_master button:hover { border-bottom: 1px solid #a64d0f !important; box-shadow: inset 0 -3px 0 0 #a64d0f !important; }\n'
                )

            # Child buttons - icon (always) + active state colors + active checkmark
            ACTIVE_CHECK_SVG = (
                "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cdefs%3E%3Cmask id='m'%3E%3Crect width='24' height='24' fill='white'/%3E%3Cpath d='M20 6L9 17l-5-5' fill='none' stroke='black' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/mask%3E%3C/defs%3E%3Crect width='24' height='24' rx='4' fill='%23ff9838' mask='url(%23m)'/%3E%3C/svg%3E\")"
            )
            for conv_key, _conv_title, _conv_desc, conv_icon, _conv_req in conv_button_defs:
                is_conv_active = st.session_state.get(conv_key, False)
                b64_conv_c = safe_b64(conv_icon)
                c_conv_img_rule = f"background-image: url('data:image/png;base64,{b64_conv_c}') !important;" if b64_conv_c else ""

                if is_conv_active:
                    conv_css_blocks.append(
                        f'div.st-key-btn_{conv_key} button {{ background-color: rgba(249, 115, 22, 0.15) !important; border: 1px solid #f97316 !important; {c_conv_img_rule} }}\n'
                        f'div.st-key-btn_{conv_key} button::before {{ border: none !important; background-color: transparent !important; background-image: {ACTIVE_CHECK_SVG} !important; }}\n'
                        f'div.st-key-btn_{conv_key} button:hover::before {{ border-color: transparent !important; }}\n'
                    )
                else:
                    # Inactive - only the icon; defaults come from global.css
                    conv_css_blocks.append(
                        f'div.st-key-btn_{conv_key} button {{ {c_conv_img_rule} }}\n'
                    )

            # --- Header HTML (separate injection) ---
            def toggle_card3():
                st.session_state['card3_expanded'] = not st.session_state.get('card3_expanded', False)

            c3_exp = st.session_state.get('card3_expanded', False)
            chr3_svg = _get_chevron_base64(c3_exp)
            b64_wf3 = _load_b64("assets/icon_workflow_3.png")

            m_conv_active = st.session_state.get('notebooklm_master', False)
            has_active_items3 = _conv_active > 0 or m_conv_active
            c3_filter = "grayscale(0%) brightness(100%)" if has_active_items3 else "grayscale(100%) brightness(60%)"
            c3_base_color = "#94a3b8" if c3_exp else "#64748b"
            c3_hover_color = "#cbd5e1" if c3_exp else "#94a3b8"

            # THE FIX: Inject chevron CSS BEFORE the button to prevent ghost flash
            st.markdown(f'''<style>
            div.st-key-header_wrap_card3 {{
                display: flex !important;
                flex-direction: row !important;
                align-items: center !important;
                justify-content: flex-start !important;
                gap: 12px !important;
                padding-top: 0px !important;
                padding-bottom: 0px !important;
                margin-top: -35px !important;
            }}
            div.st-key-header_wrap_card3 > div[data-testid="stElementContainer"] {{
                margin-bottom: 0px !important;
            }}
            div.st-key-header_wrap_card3 > div[data-testid="stElementContainer"]:nth-child(1) {{
                width: 24px !important;
                min-width: 24px !important;
                flex: 0 0 24px !important;
            }}
            div.st-key-header_wrap_card3 > div[data-testid="stElementContainer"]:nth-child(2) {{
                flex: 1 1 auto !important;
                width: 100% !important;
            }}
            /* Kill focus rings on the parent wrappers */
            div.st-key-toggle_card3 div[data-testid="stButton"]:focus-within,
            div.st-key-toggle_card3 div[data-testid="stBaseButton-secondary"]:focus-within {{
                box-shadow: none !important;
                outline: none !important;
                background: transparent !important;
            }}
            /* Kill focus rings on the button itself during focus shifts */
            div.st-key-toggle_card3 button:focus-visible,
            div.st-key-toggle_card3 button:focus:not(:active),
            div.st-key-toggle_card3 button:focus {{
                box-shadow: none !important;
                outline: none !important;
                border: none !important;
                background-color: {c3_base_color} !important;
            }}
            /* Ensure the inner markdown div remains completely hidden */
            div.st-key-toggle_card3 button > div {{
                display: none !important;
            }}
            /* BASE MASK STATE */
            div.st-key-toggle_card3 button {{
                all: unset !important;
                display: inline-block !important;
                cursor: pointer !important;
                width: 24px !important;
                height: 24px !important;
                position: relative !important;
                top: 5px !important;
                -webkit-mask-image: {chr3_svg} !important;
                -webkit-mask-size: contain !important;
                -webkit-mask-repeat: no-repeat !important;
                -webkit-mask-position: center !important;
                background-color: {c3_base_color} !important;
                transition: background-color 0.2s ease !important;
                box-shadow: none !important;
                outline: none !important;
                border: none !important;
                -webkit-tap-highlight-color: transparent !important;
            }}
            /* HOVER STATE */
            div.st-key-toggle_card3 button:hover {{ background-color: {c3_hover_color} !important; box-shadow: none !important; }}
            /* ACTIVE KILLER */
            div.st-key-toggle_card3 button:active {{
                box-shadow: none !important;
                outline: none !important;
                border: none !important;
                transform: none !important;
            }}
            /* RERUN LOCK - sanctioned exemption from the shared
               `button[disabled]` recipe; see the Card 2 note. */
            div.st-key-toggle_card3 button[disabled] {{
                box-shadow: none !important;
                outline: none !important;
                border: none !important;
                background-color: {c3_base_color} !important;
                opacity: 0.8 !important;
                filter: none !important;
            }}
            </style>''', unsafe_allow_html=True)

            st.markdown(f"<div class='step-2-card-target' style='position: relative; margin-top: -25px; margin-bottom: 0px;'><img src='data:image/png;base64,{b64_wf3}' style='position: absolute; width: 36px; height: 36px; top: -24px; left: -34px; z-index: 10; filter: {c3_filter}; transition: all 0.2s ease;' /></div>", unsafe_allow_html=True)

            with st.container(key="header_wrap_card3"):
                st.button("\u200B", key="toggle_card3", on_click=toggle_card3)
                st.markdown(f"""<div style='display: flex; align-items: center; justify-content: space-between; padding-right: 10px; width: 100%; transform: translateY(-5px);'><h3 style='margin: 0px !important; padding: 0px !important; line-height: 1 !important;'>Optimize for AI Tools <span style='color: #64748b; font-size: 0.8em; font-weight: normal;'>(Optional)</span></h3><span style='background-color: {c3_tag_bg}; color: {c3_tag_col}; border: {c3_tag_bor}; font-size: 0.8rem; padding: 2px 12px; border-radius: 15px; font-weight: 600; transition: all 0.2s ease;'>{conv_tag}</span></div>""", unsafe_allow_html=True)

            # --- CSS injection (separate call, zero-indentation) ---
            conv_css_html = "<style>\n" + "".join(conv_css_blocks) + "</style>"

            if c3_exp:
                st.markdown(f"""{conv_css_html}
<p style='font-size: 0.95rem; color: #e2e8f0; margin-top: -15px; margin-bottom: 0px;'>Automatically convert files into drag-and-drop ready formats, optimized for NotebookLM, ChatGPT, Claude, Gemini, and other AI tools.</p>
<hr style='border: none; border-top: 1px solid rgba(255, 255, 255, 0.15); margin-top: 15px; margin-bottom: 15px;'>""", unsafe_allow_html=True)
                st.button("Select All", key="btn_convert_master", on_click=_toggle_conv_master, use_container_width=True)

                with st.container(key="conversion_cards_grid"):
                    for conv_key, conv_title, _, _, conv_req in conv_button_defs:
                        if conv_req:
                            st.button(conv_title, key=f"btn_{conv_key}", on_click=_toggle_conv_sub, args=(conv_key,), use_container_width=True, help=conv_req)
                        else:
                            st.button(conv_title, key=f"btn_{conv_key}", on_click=_toggle_conv_sub, args=(conv_key,), use_container_width=True)

            # ── FDA nudge slot sync ──────────────────────────────────────
            # The hands-off notice above Confirm-and-Download is gated on the
            # office converters, but its slot lives OUTSIDE this fragment - a
            # toggle click repaints only this card, so the notice used to
            # appear/disappear one full-page rerun too late (user report: it
            # only showed after opening Settings). When a toggle flips the
            # slot's visibility, escalate to a full-page rerun - and ONLY
            # then: Windows / macOS ≤14 / FDA-granted machines never rerun,
            # so the usual toggle stays flash-free. Record BEFORE rerunning:
            # this fragment renders before the slot in DOM order, so on a
            # fresh page the sentinel is still unset here - rerunning without
            # recording first would loop forever on macOS 15+.
            _fda_conv_now = any(
                st.session_state.get(_k, st.session_state.get(f'persistent_{_k}', False))
                for _k in ('convert_pptx', 'convert_word', 'convert_excel'))
            if _fda_conv_now != st.session_state.get('_dl_fda_conv_on'):
                st.session_state['_dl_fda_conv_on'] = _fda_conv_now
                from shared.components import fda_nudge_applies
                if fda_nudge_applies():
                    st.rerun(scope="app")

        with st.container(border=True, key="card_ai_engine"):
            _render_card3_inner()

        # Spacer between Card 3 and the full-width Panopto section.
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

        # --- SECTION 4: Panopto Recordings (full-width, collapsible) ---
        @st.fragment
        def _render_card_panopto():
            with st.container(border=True, key="card_panopto"):
                ready, engine_avail, model_id, any_installed = _panopto_transcription_ready()
                selectable = _panopto_selectable_keys(ready)
                # Self-heal unavailable outputs: an applied preset (or a restored
                # sync contract) can carry pan_out_txt/srt = True even though the
                # transcription model was deleted since it was saved. Those outputs
                # are no longer selectable, so clear them here BEFORE anything reads
                # them - keeps the card, the master toggle, and the run contract
                # (persisted on Confirm) consistent with what's actually available.
                for _pk in PANOPTO_OUTPUT_KEYS:
                    if _pk not in selectable and st.session_state.get(_pk):
                        st.session_state[_pk] = False
                _pan_active = sum(1 for k in selectable if st.session_state.get(k, False))
                has_active = _pan_active > 0
                _is_exp = st.session_state.get('card_panopto_expanded', False)

                # NO acceptable-use prompt here, deliberately (removed
                # 2026-07-31). Ticking an output is configuration, not intent to
                # download - the same misjudgement the notice would make if it
                # fired when a course is added to the daily-sync list. It also
                # produced a second prompt for anyone who ticked a box and then
                # pressed Start. The run-start guards are the only triggers, and
                # they cover every path a recording can actually be fetched
                # through; the permanent note at the bottom of this card carries
                # the information while the user configures.

                # Header ON/OFF tag (purple), mirroring Card 2's behaviour.
                if _pan_active == 0:
                    tag_bg = "rgba(255, 255, 255, 0.05)"
                    tag_col = "#94a3b8"
                    tag_bor = "1px solid rgba(255, 255, 255, 0.1)"
                    dynamic_tag = "<strong>OFF</strong>" if not _is_exp else "<strong>OFF</strong>  |  None selected"
                elif _pan_active == len(selectable):
                    tag_bg = PAN_ACTIVE_BG
                    tag_col = PAN_ACCENT
                    tag_bor = "1px solid transparent"
                    dynamic_tag = "<strong>ON</strong>  |  All selected"
                else:
                    tag_bg = PAN_ACTIVE_BG
                    tag_col = PAN_ACCENT
                    tag_bor = "1px solid transparent"
                    dynamic_tag = f"<strong>ON</strong>  |  {_pan_active} selected"

                def toggle_panopto():
                    st.session_state['card_panopto_expanded'] = not st.session_state.get('card_panopto_expanded', False)

                p_exp = _is_exp
                chrp_svg = _get_chevron_base64(p_exp)
                b64_panicon = _load_b64("assets/icon_workflow_4.png")
                cp_filter = "grayscale(0%) brightness(100%)" if has_active else "grayscale(100%) brightness(60%)"
                cp_base_color = "#94a3b8" if p_exp else "#64748b"
                cp_hover_color = "#cbd5e1" if p_exp else "#94a3b8"

                # Chevron CSS injected BEFORE the button (prevents ghost flash) -
                # same proven pattern as Card 2/3.
                st.markdown(f'''<style>
                div.st-key-header_wrap_panopto {{
                    display: flex !important;
                    flex-direction: row !important;
                    align-items: center !important;
                    justify-content: flex-start !important;
                    gap: 12px !important;
                    padding-top: 0px !important;
                    padding-bottom: 0px !important;
                    margin-top: -35px !important;
                }}
                div.st-key-header_wrap_panopto > div[data-testid="stElementContainer"] {{ margin-bottom: 0px !important; }}
                div.st-key-header_wrap_panopto > div[data-testid="stElementContainer"]:nth-child(1) {{
                    width: 24px !important; min-width: 24px !important; flex: 0 0 24px !important;
                }}
                div.st-key-header_wrap_panopto > div[data-testid="stElementContainer"]:nth-child(2) {{
                    flex: 1 1 auto !important; width: 100% !important;
                }}
                div.st-key-toggle_panopto div[data-testid="stButton"]:focus-within,
                div.st-key-toggle_panopto div[data-testid="stBaseButton-secondary"]:focus-within {{
                    box-shadow: none !important; outline: none !important; background: transparent !important;
                }}
                div.st-key-toggle_panopto button:focus-visible,
                div.st-key-toggle_panopto button:focus:not(:active),
                div.st-key-toggle_panopto button:focus {{
                    box-shadow: none !important; outline: none !important; border: none !important;
                    background-color: {cp_base_color} !important;
                }}
                div.st-key-toggle_panopto button > div {{ display: none !important; }}
                div.st-key-toggle_panopto button {{
                    all: unset !important;
                    display: inline-block !important;
                    cursor: pointer !important;
                    width: 24px !important;
                    height: 24px !important;
                    position: relative !important;
                    top: 5px !important;
                    -webkit-mask-image: {chrp_svg} !important;
                    -webkit-mask-size: contain !important;
                    -webkit-mask-repeat: no-repeat !important;
                    -webkit-mask-position: center !important;
                    background-color: {cp_base_color} !important;
                    transition: background-color 0.2s ease !important;
                    box-shadow: none !important; outline: none !important; border: none !important;
                    -webkit-tap-highlight-color: transparent !important;
                }}
                div.st-key-toggle_panopto button:hover {{ background-color: {cp_hover_color} !important; box-shadow: none !important; }}
                div.st-key-toggle_panopto button:active {{ box-shadow: none !important; outline: none !important; border: none !important; transform: none !important; }}
                /* RERUN LOCK - sanctioned exemption from the shared
                   `button[disabled]` recipe; see the Card 2 note. */
                div.st-key-toggle_panopto button[disabled] {{
                    box-shadow: none !important; outline: none !important; border: none !important;
                    background-color: {cp_base_color} !important; opacity: 0.8 !important;
                    filter: none !important;
                }}
                </style>''', unsafe_allow_html=True)

                st.markdown(f"<div class='step-2-card-target' style='position: relative; margin-top: -25px; margin-bottom: 0px;'><img src='data:image/png;base64,{b64_panicon}' style='position: absolute; width: 36px; height: 36px; top: -24px; left: -34px; z-index: 10; filter: {cp_filter}; transition: all 0.2s ease;' /></div>", unsafe_allow_html=True)

                with st.container(key="header_wrap_panopto"):
                    st.button("​", key="toggle_panopto", on_click=toggle_panopto)
                    st.markdown(f"""<div style='display: flex; align-items: center; justify-content: space-between; padding-right: 10px; width: 100%; transform: translateY(-5px);'><h3 style='margin: 0px !important; padding: 0px !important; line-height: 1 !important;'>Panopto Recordings <span style='color: #64748b; font-size: 0.8em; font-weight: normal;'>(Optional)</span></h3><span style='background-color: {tag_bg}; color: {tag_col}; border: {tag_bor}; font-size: 0.8rem; padding: 2px 12px; border-radius: 15px; font-weight: 600; transition: all 0.2s ease;'>{dynamic_tag}</span></div>""", unsafe_allow_html=True)

                if not p_exp:
                    return

                # Keep the "Select All" highlight (pan_master) in sync with the
                # actual selected outputs on every render. The toggle callbacks
                # recompute it too, but applying a preset / arriving from Quick
                # Download sets pan_out_* directly without touching pan_master.
                _pan_recompute_master()

                # ── Dynamic format-toggle CSS (icons + active states + disabled) ──
                pan_css = []
                pan_css.append('''
                div[class*="st-key-panopto_outputs_grid"] {
                    display: grid !important;
                    grid-template-columns: repeat(5, 1fr) !important;
                    grid-auto-rows: 1fr !important;
                    gap: 12px !important;
                }
                div[class*="st-key-panopto_outputs_grid"] [data-testid="stElementContainer"] {
                    margin-bottom: 0px !important;
                    width: 100% !important;
                }
                div[class*="st-key-panopto_outputs_grid"] [data-testid="stElementContainer"],
                div[class*="st-key-panopto_outputs_grid"] [data-testid="stButton"],
                div[class*="st-key-panopto_outputs_grid"] [data-testid="stButton"] > div:first-child,
                div[class*="st-key-panopto_outputs_grid"] [data-testid="stTooltipIcon"],
                div[class*="st-key-panopto_outputs_grid"] [data-testid="stTooltipHoverTarget"],
                div[class*="st-key-panopto_outputs_grid"] button {
                    height: 100% !important;
                }
                /* Five across needs one more step down than four did: at 1100px
                   a five-column row gives each card ~130px, of which 50 is the
                   icon gutter, and every description wraps to three lines. */
                @media (max-width: 1250px) {
                    div[class*="st-key-panopto_outputs_grid"] {
                        grid-template-columns: repeat(3, 1fr) !important;
                    }
                }
                @media (max-width: 1100px) {
                    div[class*="st-key-panopto_outputs_grid"] {
                        grid-template-columns: repeat(2, 1fr) !important;
                    }
                }
                @media (max-width: 600px) {
                    div[class*="st-key-panopto_outputs_grid"] {
                        grid-template-columns: 1fr !important;
                    }
                }
                div.st-key-btn_pan_master button > div,
                div.st-key-btn_pan_master button div[data-testid="stMarkdownContainer"],
                div[class*="st-key-btn_pan_out_"] button > div,
                div[class*="st-key-btn_pan_out_"] button div[data-testid="stMarkdownContainer"] {
                    width: 100% !important; display: flex !important; justify-content: flex-start !important; text-align: left !important;
                }
                div.st-key-btn_pan_master button p,
                div[class*="st-key-btn_pan_out_"] button p {
                    text-align: left !important; width: 100% !important; margin-top: 0px !important; margin-bottom: 0px !important; line-height: 1.2 !important;
                }
                div[class*="st-key-btn_pan_out_"] button::after {
                    text-align: left !important; width: 100% !important; display: block !important;
                    font-size: 0.75rem !important; color: #a0a0a0; white-space: normal !important; margin-top: -2px !important; line-height: 1.2 !important;
                }
                div[class*="st-key-btn_pan_out_"] button {
                    min-height: 58px !important; height: auto !important;
                    padding: 10px 10px 10px 50px !important;
                    background-position: 15px center !important; background-size: 24px !important; background-repeat: no-repeat !important;
                    border-radius: 12px !important; display: flex; flex-direction: column;
                    -webkit-tap-highlight-color: transparent !important;
                }
                div.st-key-btn_pan_master button::before { display: none !important; }
                div.st-key-btn_pan_master button {
                    height: 48px !important; padding-top: 0px !important; padding-bottom: 0px !important; justify-content: center !important;
                    display: flex !important; flex-direction: column !important;
                }
                ''')

                # Master "Select All" - purple bottom-ledge when active.
                pm_active = st.session_state.get('pan_master', False)
                pm_bg = "rgba(255, 255, 255, 0.12)" if pm_active else "rgba(255, 255, 255, 0.1)"
                pm_ledge = PAN_ACCENT if pm_active else "transparent"
                pm_ledge_border = PAN_ACCENT if pm_active else "rgba(255, 255, 255, 0.1)"
                b64_pan_m = safe_b64('icon_pan_select_all.png')
                pm_img_rule = f"background-image: url('data:image/png;base64,{b64_pan_m}') !important;" if b64_pan_m else ""
                pan_css.append(f'''
                div.st-key-btn_pan_master button {{
                    background-color: {pm_bg} !important;
                    border: 1px solid rgba(255, 255, 255, 0.1) !important;
                    border-bottom: 1px solid {pm_ledge_border} !important;
                    box-shadow: inset 0 -3px 0 0 {pm_ledge} !important;
                    border-radius: 12px !important;
                    padding-left: 50px !important;
                    background-position: 15px center !important;
                    background-size: 24px !important;
                    background-repeat: no-repeat !important;
                    {pm_img_rule}
                }}
                ''')
                if not pm_active:
                    pan_css.append(f'''
                    div.st-key-btn_pan_master button:hover {{
                        border-bottom: 1px solid {PAN_ACCENT_DARK} !important;
                        box-shadow: inset 0 -3px 0 0 {PAN_ACCENT_DARK} !important;
                    }}
                    ''')

                # Per-output icon + active colours + active purple checkmark.
                _check_svg = (
                    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cdefs%3E%3Cmask id='m'%3E%3Crect width='24' height='24' fill='white'/%3E%3Cpath d='M20 6L9 17l-5-5' fill='none' stroke='black' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/mask%3E%3C/defs%3E%3Crect width='24' height='24' rx='4' fill='%23b89dfe' mask='url(%23m)'/%3E%3C/svg%3E\")"
                )
                for key, _title, desc, icon in PANOPTO_OUTPUT_DEFS:
                    is_active = st.session_state.get(key, False)
                    b64_i = safe_b64(icon)
                    img_rule = f"background-image: url('data:image/png;base64,{b64_i}') !important;" if b64_i else ""
                    c_bg = PAN_ACTIVE_BG if is_active else "rgba(255, 255, 255, 0.02)"
                    c_border = PAN_ACCENT if is_active else "rgba(255, 255, 255, 0.1)"
                    if is_active:
                        check = (
                            f'div.st-key-btn_{key} button::before {{ border: none !important; background-color: transparent !important; background-image: {_check_svg} !important; }}\n'
                            f'div.st-key-btn_{key} button:hover::before {{ border-color: transparent !important; }}\n'
                        )
                    else:
                        check = ""
                    pan_css.append(f'''
                    div.st-key-btn_{key} button {{
                        background-color: {c_bg} !important; border: 1px solid {c_border} !important; {img_rule}
                    }}
                    div.st-key-btn_{key} button::after {{ content: "{desc}" !important; }}
                    div.st-key-btn_{key} button:hover {{ border-color: {PAN_ACCENT} !important; }}
                    div.st-key-btn_{key} button:hover::before {{ border-color: {PAN_ACCENT} !important; }}
                    {check}
                    ''')

                # No `if not ready:` disabled block any more. When the engine
                # isn't set up, Transcript/Subtitles render with `disabled=True`
                # and global.css's single `button[disabled]` recipe paints them.
                # The rule that used to live here declared its own
                # `filter: grayscale(85%)`, which REPLACED the shared filter
                # (filter is one property) and flattened both pills to grey.

                # Info card as a COLLAPSIBLE card whose open/closed state PERSISTS.
                # It is NOT an st.expander: `expanded=` is a render-time value with
                # no state behind it and Streamlit gives no callback on an expander,
                # so a collapse was undone by the very next rerun (toggling an output,
                # changing the layout, ...). Instead the header is a native st.button
                # with an `on_click` toggle - a callback, never `if st.button(): ...;
                # st.rerun()`, which renders twice and drops the scroll anchor.
                #
                # The body is ALWAYS rendered and hidden with CSS when collapsed.
                # Removing it from the tree instead would shorten this section by one
                # element on every collapse, and Streamlit reconciles by position - the
                # keyed containers below would inherit each other's nodes and children.
                # A hidden `display: none` body also can't be clicked, so the action
                # button inside it is genuinely unreachable while collapsed.
                _pan_dot = "#22c55e" if ready else ("#f59e0b" if any_installed else "#ef4444")
                _pan_dot_glow = (
                    "rgba(34,197,94,0.5)" if ready else
                    ("rgba(245,158,11,0.5)" if any_installed else "rgba(239,68,68,0.5)")
                )
                _pan_info_open = bool(st.session_state.get('pan_info_open', True))
                pan_css.append(f'''
                /* ── pan_info_card: collapsible card shell ─────────────────── */
                /* The keyed wrapper IS the card surface. The header button and the
                   body sit inside it carrying no chrome of their own, so there is
                   one border and one background - and therefore no hairline
                   between the header and the body. */
                div[class*="st-key-pan_info_card"] {{
                    margin-bottom: 0px !important;
                    border: 1px solid rgba(176,157,254,0.28) !important;
                    border-radius: 10px !important;
                    background: rgba(176,157,254,0.06) !important;
                    box-shadow: none !important;
                    padding: 0 !important;
                    gap: 0 !important;
                    overflow: hidden !important;
                }}
                /* ── Header row: a native st.button styled as the summary ──── */
                div.st-key-pan_info_hdr {{ margin: 0 !important; }}
                div.st-key-pan_info_hdr button {{
                    width: 100% !important;
                    background: transparent !important;
                    border: none !important;
                    border-radius: 10px !important;
                    box-shadow: none !important;
                    padding: 8px 14px !important;
                    min-height: 0 !important;
                    height: auto !important;
                    display: flex !important;
                    flex-direction: row !important;
                    align-items: center !important;
                    justify-content: flex-start !important;
                    text-align: left !important;
                    cursor: pointer !important;
                }}
                div.st-key-pan_info_hdr button:hover {{
                    background: rgba(176,157,254,0.10) !important;
                }}
                /* The purple chevron, rotated when the card is open. It is a
                   normal in-flow flex item, which is safe here only because the
                   row is left-aligned - on a CENTRED button a leading icon shifts
                   the label off the button's axis. */
                div.st-key-pan_info_hdr button::before {{
                    content: "" !important;
                    display: inline-block !important;
                    width: 0.85em !important;
                    height: 0.85em !important;
                    margin-right: 8px !important;
                    flex-shrink: 0 !important;
                    background-color: #b89dfe !important;
                    -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23000' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m9 18 6-6-6-6'/%3E%3C/svg%3E") !important;
                    mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23000' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m9 18 6-6-6-6'/%3E%3C/svg%3E") !important;
                    -webkit-mask-repeat: no-repeat !important;
                    mask-repeat: no-repeat !important;
                    -webkit-mask-position: center !important;
                    mask-position: center !important;
                    -webkit-mask-size: contain !important;
                    mask-size: contain !important;
                    transform: rotate({90 if _pan_info_open else 0}deg) !important;
                    transition: transform 0.18s ease !important;
                }}
                /* Label + status dot. A plain-text button label renders with NO
                   <p> in 1.51 - the text sits directly in stMarkdownContainer -
                   so the layout and the dot both hang off the container, never
                   off `p`. The `p` rule below only covers a label that happens
                   to contain inline markup. */
                div.st-key-pan_info_hdr button [data-testid="stMarkdownContainer"] {{
                    display: inline-flex !important;
                    align-items: center !important;
                    gap: 10px !important;
                    font-size: 0.88rem !important;
                    font-weight: 600 !important;
                    color: #e2e8f0 !important;
                    line-height: 1.3 !important;
                    margin: 0 !important;
                }}
                div.st-key-pan_info_hdr button [data-testid="stMarkdownContainer"] p {{
                    margin: 0 !important;
                    font-size: 0.88rem !important;
                    font-weight: 600 !important;
                    color: #e2e8f0 !important;
                    line-height: 1.3 !important;
                }}
                /* Status dot. Colour is dynamic per render. */
                div.st-key-pan_info_hdr button [data-testid="stMarkdownContainer"]::after {{
                    content: "" !important;
                    display: inline-block !important;
                    width: 10px !important;
                    height: 10px !important;
                    border-radius: 50% !important;
                    background: {_pan_dot} !important;
                    box-shadow: 0 0 6px {_pan_dot_glow} !important;
                    flex-shrink: 0 !important;
                }}
                /* ── Collapsible body ─────────────────────────────────────── */
                /* Always rendered; hidden with `display: none` when collapsed so
                   the element count of this section never changes. */
                div[class*="st-key-pan_info_body"] {{
                    display: {"flex" if _pan_info_open else "none"} !important;
                    padding: 0 15px 12px 15px !important;
                    gap: 0 !important;
                }}
                /* Streamlit's stMarkdownContainer carries margin-bottom: -16px.
                   With the body's gap at 0 that pulled the action button UP into
                   the description line and the two overlapped. Cancel it here so
                   the button's own margin-top is the only spacing that lands. */
                div[class*="st-key-pan_info_body"] div[data-testid="stMarkdownContainer"] {{
                    margin-bottom: 0 !important;
                }}
                div[class*="st-key-pan_info_body"] div[data-testid="stElementContainer"]:last-child {{
                    margin-bottom: 0 !important;
                }}
                /* ── Action button inside the body ────────────────────────── */
                /* The body's own padding-bottom is the space under the button -
                   a margin here would stack on top of it and the gap under the
                   button would no longer match the card's other insets. */
                div.st-key-pan_open_dialog_btn {{
                    margin-left: 0px !important;
                    margin-top: 8px !important;
                    margin-bottom: 0px !important;
                }}
                div.st-key-pan_open_dialog_btn button {{
                    background: rgba(176,157,254,0.10) !important;
                    border: 1px solid rgba(176,157,254,0.35) !important;
                    color: #d8caff !important; font-weight: 600 !important;
                    font-size: 0.85rem !important;
                    border-radius: 8px !important;
                    justify-content: center !important;
                    align-items: center !important;
                    transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
                    height: 32px !important; min-height: 32px !important;
                    min-width: 220px !important;
                    padding: 0 14px !important;
                }}
                div.st-key-pan_open_dialog_btn button [data-testid="stMarkdownContainer"] {{
                    display: flex !important;
                    align-items: center !important;
                }}
                div.st-key-pan_open_dialog_btn button p {{
                    display: inline-flex !important;
                    align-items: center !important;
                    gap: 6px !important;
                    margin: 0 !important;
                }}
                div.st-key-pan_open_dialog_btn button p::before {{
                    content: "" !important;
                    display: inline-block !important;
                    width: 14px !important; height: 14px !important;
                    flex-shrink: 0 !important;
                    background-image: url("{_PAN_GEAR_SVG}") !important;
                    background-size: contain !important;
                    background-repeat: no-repeat !important;
                    background-position: center !important;
                }}
                div.st-key-pan_open_dialog_btn button:hover {{
                    background-color: rgba(176,157,254,0.18) !important;
                    border-color: #b89dfe !important; color: #ffffff !important;
                }}
                ''')

                pan_css_html = "<style>" + "".join(pan_css) + "</style>"
                st.markdown(f"""{pan_css_html}
<p style='font-size: 0.95rem; color: #e2e8f0; margin-top: -15px; margin-bottom: 12px;'>Download your Canvas Panopto lecture recordings - as video, audio, transcripts or subtitles - saved into your course folders like every other file. Or save just a shortcut, so you can jump straight back to the lecture without downloading it.</p>""", unsafe_allow_html=True)

                # ── Element 0: transcription status card (collapsible) ──
                # Header button shows the status headline + CSS-injected dot; the
                # body has the full description and the action button. Open by
                # default so setup guidance is visible on a first visit; after
                # that the user's choice persists in `pan_info_open`.
                with st.container(key="pan_info_card"):
                    if ready:
                        _m = None
                        try:
                            from panopto import models as _pm
                            _m = _pm.get_model(model_id)
                        except Exception:
                            _m = None
                        _mlabel = (_m or {}).get('label', model_id)
                        # A button label is markdown, not HTML - esc() here would
                        # print a literal "&amp;" rather than escaping anything.
                        _exp_label = f"Transcription ready \u2013 {_mlabel} model"
                        _dlg_label = "Manage transcription models"
                    else:
                        _exp_label = "Transcripts & Subtitles need a one-time setup"
                        _dlg_label = "Set up transcription"

                    st.button(_exp_label, key="pan_info_hdr",
                              on_click=_toggle_pan_info, use_container_width=True)

                    with st.container(key="pan_info_body"):
                        # Detail text inside the collapsible body.
                        if ready:
                            st.markdown(
                                f"<div style='color:#cbd5e1; font-size:0.84rem; line-height:1.45; margin-top:0;'>"
                                f"Using the <b style='color:#e2e8f0;'>{esc(_mlabel)}</b> model. "
                                f"Transcript &amp; Subtitles are available.</div>",
                                unsafe_allow_html=True)
                        else:
                            if not engine_avail:
                                _why = "The local transcription engine isn't available yet."
                            elif any_installed:
                                _why = "A model is installed but not activated yet."
                            else:
                                _why = "No transcription model is installed yet."
                            st.markdown(
                                f"<div style='color:#94a3b8; font-size:0.84rem; line-height:1.45; margin-top:0;'>"
                                f"{esc(_why)} Download a transcription model to unlock the "
                                f"<b>Transcript</b> &amp; <b>Subtitles</b> formats. "
                                f"Video &amp; Audio work without it.</div>",
                                unsafe_allow_html=True)

                        # Action button at the bottom of the body.
                        if st.button(_dlg_label, key="pan_open_dialog_btn", use_container_width=False):
                            st.session_state['_pan_dialog_open'] = True
                            st.rerun(scope="app")

                # ── Element 1: separator + choose what to download ──
                # The <hr> is merged into the same st.markdown so it shares one flex
                # slot with the label - prevents a double flex-gap below the card.
                st.markdown(
                    "<hr style='border: none; border-top: 1px solid rgba(255, 255, 255, 0.15); margin-top: 6px; margin-bottom: 10px;'>"
                    "<p style='font-size: 0.9rem; font-weight: 600; color: #cbd5e1; margin-top: 0; margin-bottom: 10px;'>Choose what to download <span style='color:#64748b; font-weight:400;'>(select one or more):</span></p>",
                    unsafe_allow_html=True,
                )
                st.button("Select All", key="btn_pan_master", on_click=_toggle_pan_master, use_container_width=True)
                with st.container(key="panopto_outputs_grid"):
                    for key, title, _desc, _icon in PANOPTO_OUTPUT_DEFS:
                        _disabled = (key in PANOPTO_TRANSCRIPT_KEYS and not ready)
                        st.button(
                            title, key=f"btn_{key}", on_click=_toggle_pan_sub,
                            args=(key,), use_container_width=True, disabled=_disabled,
                            help=("Install a transcription model to enable this output."
                                  if _disabled else None),
                        )

                # ── Element 2: choose how to organize ──
                # Disabled until at least one output is selected (mirrors Canvas
                # Content): dim the label and the segmented control.
                _pan_layout_disabled = not has_active
                _pan_org_label_color = "#cbd5e1" if has_active else "#475569"
                st.markdown(f"""
                <p style='font-size: 0.9rem; font-weight: 600; color: {_pan_org_label_color}; margin-top: 15px; margin-bottom: 0px;'>Choose how to organize Panopto Recordings:</p>
                {_get_pan_layout_segmented_css()}
                """, unsafe_allow_html=True)
                _pan_layout_help = ("Select at least one Panopto output above to choose "
                                    "how recordings are organized.") if _pan_layout_disabled else None
                with st.container(key="pan_layout_segmented_wrapper"):
                    _pl1, _pl2 = st.columns(2, gap="small")
                    with _pl1:
                        st.button("Match Course Folder structure", key="btn_pan_layout_match",
                                  on_click=_set_pan_layout, args=("match",), use_container_width=True,
                                  disabled=_pan_layout_disabled, help=_pan_layout_help)
                    with _pl2:
                        st.button("In Separate Folders", key="btn_pan_layout_separate",
                                  on_click=_set_pan_layout, args=("separate",), use_container_width=True,
                                  disabled=_pan_layout_disabled, help=_pan_layout_help)

                # ── Permanent acceptable-use reminder ──
                # NOT gated behind help_text_enabled(): this is operational copy
                # (it states what the app does and does not check), not tuition
                # about the UI, so "Show help text" must never hide it. Styling
                # lives in global.css because a style injection INSIDE a bordered
                # container occupies a real flex slot and would inflate the
                # card's spacing (see CLAUDE.md, ghost-box-inside-container).
                st.markdown(
                    '<div class="cd-pan-usage-note">'
                    'Recordings are saved for your personal study. You are '
                    'responsible for following your institution&#39;s rules, and '
                    'for not sharing or republishing them. '
                    f'<a href="{esc(DISCLAIMER_URL)}" target="_blank" '
                    'rel="noopener noreferrer">Details</a>'
                    '</div>',
                    unsafe_allow_html=True,
                )

        _render_card_panopto()

        # Separator above Output Folder section
        st.markdown(
            "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:28px 0 20px 0;'>",
            unsafe_allow_html=True,
        )

        st.markdown(
            "<div style='font-size: 1.15rem; font-weight: 700; color: #ffffff; margin-top: 10px; margin-bottom: 12px; display: flex; align-items: center; gap: 10px;'>"
            "Verify your download destination"
            "</div>",
            unsafe_allow_html=True,
        )

        dl_path = st.session_state['download_path']
        
        st.html("""<style>
div.st-key-review_browse_folder button {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #cbd5e1 !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    height: 58px !important;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease !important;
    transform: none !important;
}
div.st-key-review_browse_folder button:hover {
    background: rgba(255,255,255,0.1) !important;
    color: #ffffff !important;
    border-color: rgba(255,255,255,0.25) !important;
    transform: none !important;
}
</style>""")

        f_col, btn_col = st.columns([4, 0.8], gap="small")
        with f_col:
            folder_name   = Path(dl_path).name or dl_path
            folder_parent = str(Path(dl_path).parent)
            st.markdown(
                f"""
                <div title="{esc(dl_path)}" style="
                    background: linear-gradient(160deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.02) 100%);
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 8px;
                    padding: 8px 16px;
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    min-height: 58px;
                    box-sizing: border-box;
                    cursor: default;">
                    <svg width="18" height="18" fill="none" stroke="#94a3b8" viewBox="0 0 24 24" style="flex-shrink:0;">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                    </svg>
                    <div style="flex:1; min-width:0;">
                        <div style="font-weight:600; color:#ffffff; font-size:0.98rem; line-height:1.15;
                                    white-space:normal; overflow-wrap:anywhere;">
                            {esc(folder_name)}
                        </div>
                        <div style="font-size:0.83rem; color:#94a3b8; line-height:1.15;
                                    white-space:normal; overflow-wrap:anywhere; margin-top: 0px;">
                            {esc(folder_parent)}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with btn_col:
            st.button("Change folder", key="review_browse_folder", use_container_width=True, on_click=_select_folder)

        # --- Unified Course Summary Dropdown (full-width, native <details>) ---
        _dl_courses = st.session_state.get('courses_to_download', [])
        if not _dl_courses:
            try:
                _all_c = fetch_courses_fn(st.session_state['api_token'], st.session_state['api_url'])
                _sel_ids = set(st.session_state.get('selected_course_ids', []))
                _dl_courses = [c for c in _all_c if c.id in _sel_ids]
            except Exception:
                _dl_courses = []
        _dl_count = len(_dl_courses)

        def _render_course_item(i, c):
            name, code = get_course_display_parts(c)
            code_clean = code.strip("()") if code else ""
            if code_clean:
                code_html = f"<div class='code'>{esc(code_clean)}</div>"
            else:
                code_html = ""
            return f"<li class='course-item'><span class='num'>{i}.</span> <div class='name-wrap'><div class='name'>{esc(name)}</div>{code_html}</div></li>"

        _dl_list_html = "".join([_render_course_item(i, c) for i, c in enumerate(_dl_courses, 1)])

        _dl_details_html = f"""
    <style>
    details.unified-course-dropdown {{
        margin-top: 0px;
        margin-bottom: 60px;
        width: 100%;
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 6px;
        background: transparent;
        transition: background 0.2s ease, border-color 0.2s ease;
    }}
    details.unified-course-dropdown[open] {{
        background: #111418;
        border-color: rgba(255, 255, 255, 0.2);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }}
    details.unified-course-dropdown summary {{
        cursor: pointer;
        padding: 12px 16px;
        list-style: none;
        user-select: none;
        outline: none;
        display: flex;
        align-items: center;
        justify-content: flex-start;
        gap: 12px;
    }}
    details.unified-course-dropdown summary::-webkit-details-marker {{
        display: none;
    }}
    /* The chevron comes from global.css's `summary::before` (a masked lucide
       glyph that rotates on [open]) - this panel must NOT draw its own. It used
       to hard-code a "\\25B8" div, which since the global chevron system landed
       rendered TWO chevrons side by side: the stroke-style one plus a blunt
       Unicode triangle. `currentColor` makes the masked glyph inherit this
       colour, so setting it on the summary tints the chevron. */
    details.unified-course-dropdown summary {{
        color: #a0a0a0;
    }}
    .summary-text {{
        color: #ffffff;
        font-size: 0.92rem;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 10px;
    }}
    .count-tag {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background-color: rgba(56, 189, 248, 0.15) !important;
        border: 1px solid rgba(56, 189, 248, 0.3) !important;
        color: #ffffff !important;
        font-size: 0.9rem;
        font-weight: 700;
        min-width: 20px;
        height: 24px;
        padding: 0 9px;
        border-radius: 8px;
        line-height: 1;
    }}
    .dropdown-body {{
        border-top: 1px solid rgba(255, 255, 255, 0.1);
        padding: 8px 0 10px 0;
        max-height: 300px;
        overflow-y: auto;
    }}
    ul.course-list-box {{
        margin: 0;
        padding: 0 16px 0 16px;
        list-style-type: none;
    }}
    li.course-item {{
        display: flex;
        align-items: flex-start;
        gap: 5px;
        padding: 8px 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }}
    li.course-item:last-child {{
        border-bottom: none;
    }}
    li.course-item .num {{
        color: #888888;
        font-size: 1.05rem;
        min-width: 20px;
        margin-top: 1px;
    }}
    li.course-item .name-wrap {{
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }}
    li.course-item .name {{
        color: #ffffff;
        font-size: 1.05rem;
        font-weight: 400;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.2;
    }}
    li.course-item .code {{
        color: #94a3b8;
        font-size: 0.85rem;
        font-weight: 400;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-top: 0px;
    }}
    .dropdown-body::-webkit-scrollbar {{
        width: 6px;
    }}
    .dropdown-body::-webkit-scrollbar-track {{
        background: transparent;
    }}
    .dropdown-body::-webkit-scrollbar-thumb {{
        background-color: rgba(255, 255, 255, 0.15);
        border-radius: 10px;
    }}
    .dropdown-body::-webkit-scrollbar-thumb:hover {{
        background-color: rgba(255, 255, 255, 0.25);
    }}
    </style>

    <details class="unified-course-dropdown">
    <summary>
    <div class="summary-text">Courses selected for download <span class="count-tag">{_dl_count}</span></div>
    </summary>
    <div class="dropdown-body">
    <ul class="course-list-box">
    {_dl_list_html}
    </ul>
    </div>
    </details>

    <style>
    /* Custom Confirm and Download Colors - Solid Physical Volume */
    </style>
    """

        st.markdown(_dl_details_html, unsafe_allow_html=True)

        # ── macOS hands-off nudge (Full Disk Access) ─────────────────────
        # Office→PDF conversion is about to run for this download (custom
        # config or an applied quick-download preset both land here), so this
        # is the moment the once-per-session macOS consent dialog becomes
        # relevant - surface the dismissible guide right at the decision
        # point. Same shared component + persisted dismissal as the Today
        # page; renders nothing on Windows, macOS ≤14, or once FDA is granted.
        _fda_conv_on = any(
            st.session_state.get(_k, st.session_state.get(f'persistent_{_k}', False))
            for _k in ('convert_pptx', 'convert_word', 'convert_excel'))
        # Card 3's fragment compares against this to detect a converter toggle
        # flipping this slot's visibility (the slot lives HERE, outside the
        # fragment, so the fragment escalates to a full rerun when it changes).
        st.session_state['_dl_fda_conv_on'] = _fda_conv_on
        if _fda_conv_on:
            from shared.components import render_fda_nudge
            render_fda_nudge("dl_fda")

        col_back, _, col_conf = st.columns([1, 5, 1.5])
        with col_conf:
            # Button label changes based on mode
            button_label = 'Sync (Download) Selected Files' if st.session_state['current_mode'] == 'sync' else 'Confirm and Download'
            if st.button(button_label, type="primary", use_container_width=True, key='action_dl_confirm'):
                try:
                    # ── PRE-FLIGHT: Writability probe ──
                    # Fail fast with a clear message if the download folder is
                    # read-only, missing, or otherwise unwritable - before the
                    # user wastes minutes on the course scanning phase.
                    _dl_path = Path(st.session_state.get('download_path', ''))
                    try:
                        _dl_path.mkdir(parents=True, exist_ok=True)
                        _probe = _dl_path / '.canvas_write_probe'
                        _probe.write_bytes(b'ok')
                        _probe.unlink()
                    except Exception as _wp_err:
                        from ui.amber_notice import render_error_notice
                        render_error_notice(
                            f"Cannot write to the selected download folder.<br><br>"
                            f"<b>Path:</b> <code>{_dl_path}</code><br><br>"
                            f"<b>Reason:</b> {_wp_err}<br><br>"
                            f"Please select a different folder with write permissions.",
                            allow_html=True
                        )
                        st.stop()

                    # Initialize download state
                    from shared.components import resolve_courses_or_stop
                    all_courses = resolve_courses_or_stop(fetch_courses_fn, retry_key="dl_start_conn_retry")
                    course_map = {c.id: c for c in all_courses}
                    courses_to_download = [course_map[cid] for cid in st.session_state['selected_course_ids'] if cid in course_map]

                    # ── RESET all transient download state before starting fresh ──
                    # Without this, data from the PREVIOUS download (file lists,
                    # error counts, discovery warnings) bleeds into the new one.
                    for _stale_key in [
                        'download_file_details', 'download_errors_list', 'failed_items',
                        'downloaded_items', 'log_deque', 'skipped_discovery_errors',
                        'size_skipped_files', 'pp_failure_count', 'pp_success_count',
                        'log_content', 'seen_error_sigs', 'course_mb_downloaded',
                        'retry_attempted', 'retry_resolved_count', 'retry_total_attempted',
                        'isolated_retry_queue', 'retry_downloaded_items', 'retry_failed_items',
                        'retry_isolated_details', 'retry_mb_tracker', 'is_post_processing',
                        'start_time', 'total_items', 'total_mb',
                        'sync_has_ignored_files', 'sync_newversion_files',
                    ]:
                        st.session_state.pop(_stale_key, None)

                    st.session_state['courses_to_download'] = courses_to_download
                    st.session_state['current_course_index'] = 0
                    st.session_state['cancel_requested'] = False
                    st.session_state['total_items'] = 0
                    st.session_state['downloaded_items'] = 0
                    st.session_state['course_mb_downloaded'] = {}
                    st.session_state['log_content'] = ""  # Initialize log content
                    st.session_state['seen_error_sigs'] = set()

                    # Task 1: Save the State on Button Click (Streamlit Widget Cleanup Fix)
                    st.session_state['persistent_convert_zip'] = st.session_state.get('convert_zip', False)
                    st.session_state['persistent_convert_pptx'] = st.session_state.get('convert_pptx', False)
                    st.session_state['persistent_convert_html'] = st.session_state.get('convert_html', False)
                    st.session_state['persistent_convert_code'] = st.session_state.get('convert_code', False)
                    st.session_state['persistent_convert_urls'] = st.session_state.get('convert_urls', False)
                    st.session_state['persistent_convert_word'] = st.session_state.get('convert_word', False)
                    st.session_state['persistent_convert_video'] = st.session_state.get('convert_video', False)
                    st.session_state['persistent_convert_excel'] = st.session_state.get('convert_excel', False)

                    # Task 1b: Save secondary content state on button click
                    for _sck in SECONDARY_CONTENT_KEYS:
                        st.session_state[f'persistent_{_sck}'] = st.session_state.get(_sck, False)
                    st.session_state['persistent_dl_isolate_secondary'] = st.session_state.get('dl_isolate_secondary', True)

                    # Task 1c: Save Panopto (Section 4) output formats + layout. The
                    # runtime reads these persistent_* keys to build the run contract.
                    for _pk in PANOPTO_OUTPUT_KEYS:
                        st.session_state[f'persistent_{_pk}'] = st.session_state.get(_pk, False)
                    st.session_state['persistent_pan_layout'] = st.session_state.get('pan_layout', 'match')

                    # Debug log clear + header + bridge install now happen once at
                    # the run's first step-3/step-4 render (shared by quick and
                    # custom download, and ahead of the scan phase). Reset the
                    # per-run guard so that init fires fresh for this run.
                    st.session_state.pop('_dl_debug_run_inited', None)

                    from core.cancellation import reset_download_cancel, reset_sync_cancel
                    reset_download_cancel()
                    reset_sync_cancel()

                    # Acceptable-use notice, ACTIVE trigger. Read from the
                    # persistent_* keys just written above, which ARE the run
                    # contract - so this asks the same question the engine will.
                    #
                    # No early return: the rest of Step 2 must still render, or
                    # its element indices shift under the modal and Streamlit
                    # reconciles the page behind it with its neighbours'
                    # stylesheets. Skipping the status change is enough to hold
                    # the run - nothing downstream starts without it.
                    _pan_wanted = any(
                        st.session_state.get(f'persistent_{_pk}', False)
                        for _pk in PANOPTO_OUTPUT_KEYS
                    )
                    # Resume payload: a declined notice must still start the run
                    # the user asked for, minus recordings. Both branches are
                    # spelled out because the transition differs by mode.
                    _resume = (
                        {'download_status': 'analyzing', 'step': 4}
                        if st.session_state['current_mode'] == 'sync'
                        else {'download_status': 'scanning', 'step': 3}
                    )
                    if _pan_wanted and not require_panopto_notice(resume=_resume):
                        pass
                    else:
                        clear_panopto_skip()
                        if st.session_state['current_mode'] == 'sync':
                            # Sync mode - go to Step 4 (Analysis)
                            st.session_state['download_status'] = 'analyzing'
                            st.session_state['step'] = 4
                        else:
                            # Download mode - go to Step 3 (Progress)
                            st.session_state['download_status'] = 'scanning'
                            st.session_state['step'] = 3

                        # Brief pause to ensure state is saved before rerun
                        time.sleep(0.1)
                        step2_container.empty() # Clear EVERYTHING in Step 2
                        st.rerun()
                except Exception as e:
                    from ui.amber_notice import render_error_notice
                    render_error_notice(f"Error initializing: {e}")

        with col_back:
            if st.button('Go back', use_container_width=True, key='action_dl_back'):
                _dl_settings_go_back()
                st.rerun()

    # --- The two header dialogs - invoked LAST, and that is load-bearing.
    # A dialog body is a FRAGMENT, and streamlit/runtime/fragment.py snapshots
    # ctx.cursors at the CALL SITE and restores it on every fragment rerun,
    # rewinding the EVENT root container's write index. That container is one
    # global, index-addressed list holding BOTH st.toast and every style-only
    # st.html(). So a fragment rerun that emits one more event element than the
    # run that opened the dialog silently OVERWRITES whatever the main script
    # wrote to that container after the call site.
    #
    # Invoked from their buttons in the header (~line 650), the writes at risk
    # were the help card's stylesheet three lines below plus the Card 2 / Card 4
    # stylesheets and the FDA nudge - and ui/presets.py toasts on apply and on
    # delete. This is the same defect that made the sync page's help card unfold
    # itself behind the open hub (see sync_ui.py's matching comment).
    #
    # Rendering last costs nothing - a dialog is a portal, so its call-site
    # position does not affect where it appears. The only direct exits below the
    # old site (st.stop at 2737, st.rerun at 2811/2819) are inside
    # `if st.button(...)` handlers for Start Download / Go back, which cannot
    # fire on the same frame as a Save Preset / Presets click.
    if _open_save_config:
        _save_config_dialog()
    elif _open_presets_hub:
        # elif, not a second if: Streamlit allows only ONE dialog open per run.
        _presets_hub_dialog()

