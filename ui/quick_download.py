"""
ui.quick_download - Quick Download preset picker (Step 2 lite).
"""
from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from shared.helpers import esc, get_base64_image, native_folder_picker, render_download_wizard
from shared.components import render_help_card, HELP_ICONS
from core.state_registry import SECONDARY_CONTENT_KEYS, NOTEBOOK_SUB_KEYS, PANOPTO_OUTPUT_KEYS


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

_QUICK_PRESETS = [
    {
        'id': 'quick_full',
        'name': 'Complete Canvas Download',
        'desc': 'All files and Canvas content, just like you see it in Canvas.',
        'icon': 'icon_preset_builtin.png',
        'settings': {
            'download_mode': 'modules', 'file_filter': 'all',
            'dl_isolate_secondary': False,
            'dl_assignments': True, 'dl_syllabus': True, 'dl_announcements': True,
            'dl_discussions': True, 'dl_quizzes': True,
            'dl_submissions': True, 'dl_secondary_master': True,
            'notebooklm_master': False,
            'convert_zip': True,  'convert_pptx': False, 'convert_word': False,
            'convert_excel': False, 'convert_html': False, 'convert_code': False,
            'convert_urls': False, 'convert_video': False,
            # Panopto: full video, saved alongside course files (modules).
            'pan_out_mp4': True, 'pan_out_mp3': False,
            'pan_out_txt': False, 'pan_out_srt': False, 'pan_layout': 'match',
        },
    },
    {
        'id': 'quick_ai',
        'name': 'Daily study pack (Optimized)',
        'desc': 'Full course with PPTX converted to PDF, for easy AI upload.',
        'icon': 'icon_preset_builtin.png',
        'settings': {
            'download_mode': 'modules', 'file_filter': 'all',
            'dl_isolate_secondary': True,
            'dl_assignments': True, 'dl_syllabus': True, 'dl_announcements': True,
            'dl_discussions': True, 'dl_quizzes': True,
            'dl_submissions': True, 'dl_secondary_master': True,
            'notebooklm_master': False,
            'convert_zip': True,  'convert_pptx': True,  'convert_word': True,
            'convert_excel': False, 'convert_html': False, 'convert_code': False,
            'convert_urls': False, 'convert_video': False,
            # Panopto: video + audio, saved alongside course files (modules).
            'pan_out_mp4': True, 'pan_out_mp3': True,
            'pan_out_txt': False, 'pan_out_srt': False, 'pan_layout': 'match',
        },
    },
    {
        'id': 'quick_notebooklm',
        'name': '100% AI & NotebookLM Ready',
        'desc': 'All files AI-Optimized, ready to drag & drop into notebookLM.',
        'icon': 'icon_preset_builtin.png',
        'settings': {
            'download_mode': 'flat', 'file_filter': 'all',
            'dl_isolate_secondary': True,
            'dl_assignments': True, 'dl_syllabus': True, 'dl_announcements': True,
            'dl_discussions': True, 'dl_quizzes': True,
            'dl_submissions': True, 'dl_secondary_master': True,
            'notebooklm_master': True,
            'convert_zip': True,  'convert_pptx': True,  'convert_word': True,
            'convert_excel': True, 'convert_html': True, 'convert_code': True,
            'convert_urls': True,  'convert_video': True,
            # Panopto: audio only, in a separate "Panopto Recordings" folder.
            'pan_out_mp4': False, 'pan_out_mp3': True,
            'pan_out_txt': False, 'pan_out_srt': False, 'pan_layout': 'separate',
        },
    },
    {
        'id': 'quick_slides',
        'name': 'Slides & PDFs Only',
        'desc': 'Download only slides and pdf files, nothing else.',
        'icon': 'icon_preset_builtin.png',
        'settings': {
            'download_mode': 'modules', 'file_filter': 'study',
            'dl_isolate_secondary': False,
            'dl_assignments': False, 'dl_syllabus': False, 'dl_announcements': False,
            'dl_discussions': False, 'dl_quizzes': False,
            'dl_submissions': False, 'dl_secondary_master': False,
            'notebooklm_master': False,
            'convert_zip': False, 'convert_pptx': False, 'convert_word': False,
            'convert_excel': False, 'convert_html': False, 'convert_code': False,
            'convert_urls': False, 'convert_video': False,
            # Panopto: none.
            'pan_out_mp4': False, 'pan_out_mp3': False,
            'pan_out_txt': False, 'pan_out_srt': False, 'pan_layout': 'match',
        },
    },
    {
        'id': 'quick_files_only',
        'name': 'Files Only',
        'desc': 'Only the files uploaded by your teacher, no Canvas Content or other distractions.',
        'icon': 'icon_preset_builtin.png',
        'settings': {
            'download_mode': 'modules', 'file_filter': 'all',
            'dl_isolate_secondary': False,
            'dl_assignments': False, 'dl_syllabus': False, 'dl_announcements': False,
            'dl_discussions': False, 'dl_quizzes': False,
            'dl_submissions': False, 'dl_secondary_master': False,
            'notebooklm_master': False,
            'convert_zip': False,  'convert_pptx': False, 'convert_word': False,
            'convert_excel': False, 'convert_html': False, 'convert_code': False,
            'convert_urls': False, 'convert_video': False,
            # Panopto: none. "Files Only" means just the teacher's uploaded files -
            # lecture recordings are a separate, opt-in content type, so this
            # preset must NOT pull multi-GB Panopto videos (matches its
            # "no distractions" promise and "Slides & PDFs Only" above).
            'pan_out_mp4': False, 'pan_out_mp3': False,
            'pan_out_txt': False, 'pan_out_srt': False, 'pan_layout': 'match',
        },
    },
]


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _select_preset_cb(preset_id: str, default_mode: str) -> None:
    st.session_state['quick_preset_id'] = preset_id
    st.session_state['quick_org_mode'] = default_mode


def _select_org_cb(mode: str) -> None:
    st.session_state['quick_org_mode'] = mode


def _select_folder_cb() -> None:
    path = native_folder_picker(initial_dir=st.session_state.get('download_path') or None)
    if path:
        st.session_state['download_path'] = path


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_quick_download(fetch_courses_fn) -> None:
    """Render the Quick Download page (Step 2 lite)."""
    from shared.components import render_config_summary_badges
    from shared.helpers import get_course_display_parts

    render_download_wizard(st, 2)

    # ── Session-state defaults ───────────────────────────────────────────
    # No preset selected on fresh entry - user must actively choose one.
    st.session_state.setdefault('quick_preset_id', None)
    st.session_state.setdefault('quick_org_mode', 'modules')

    selected_id  = st.session_state['quick_preset_id']
    selected_org = st.session_state['quick_org_mode']

    active_idx    = next((i for i, p in enumerate(_QUICK_PRESETS) if p['id'] == selected_id), None)
    active_preset = _QUICK_PRESETS[active_idx] if active_idx is not None else None
    active_org_key = 'subfolders' if selected_org == 'modules' else 'flat'
    org_is_locked  = selected_id in ('quick_notebooklm', 'quick_full')

    # ── Load base64 icons ────────────────────────────────────────────────
    b64_preset_full = get_base64_image("assets/icon_quick_dl_complete.png")
    b64_preset_ai   = get_base64_image("assets/icon_quick_dl_ai_optimized.png")
    b64_preset_nb   = get_base64_image("assets/icon_quick_dl_notebook.png")
    b64_preset_ppt  = get_base64_image("assets/icon_quick_dl_ppt_pdf.png")
    b64_preset_files = get_base64_image("assets/icon_quick_dl_all_files.png")
    
    _preset_icons = [b64_preset_full, b64_preset_ai, b64_preset_nb, b64_preset_ppt, b64_preset_files]
    
    b64_sub      = get_base64_image("assets/icon_subfolders.png")
    b64_flat_ico = get_base64_image("assets/icon_flat.png")
    b64_custom_dl = get_base64_image("assets/icon_custom_download.png")

    # ── Active state radio SVG ───────────────────────────────────────────
    _radio_svg = (
        "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' "
        "stroke='%233fd9ff' stroke-width='3'/%3E%3Ccircle cx='12' cy='12' r='5' "
        "fill='%233fd9ff'/%3E%3C/svg%3E\")"
    )

    # ── Inline SVG chevron for HTML dropdowns ────────────────────────────
    _dl_chevron = (
        "<svg width='10' height='10' viewBox='0 0 24 24' fill='none' "
        "stroke='#64748b' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'>"
        "<polyline points='9 18 15 12 9 6'></polyline></svg>"
    )

    # ── Per-preset description and icon via CSS ─────────────────────────
    _preset_desc_css = ""
    for _i, _p in enumerate(_QUICK_PRESETS):
        _preset_desc_css += (
            f"div.st-key-btn_quick_preset_{_i} button {{"
            f"  background-image: url('data:image/png;base64,{_preset_icons[_i]}'), "
            f"                    linear-gradient(160deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.02) 100%) !important;"
            f" }}\n"
            f"div.st-key-btn_quick_preset_{_i} button::after {{"
            f"  content: \"{_p['desc']}\" !important;"
            f"  display: block !important;"
            f"  font-size: 0.82rem !important;"
            f"  color: #cbd5e1 !important;"
            f"  font-weight: 400 !important;"
            f"  margin-top: 3px !important;"
            f"  white-space: normal !important;"
            f"  text-align: center !important;"
            f"  line-height: 1.35 !important;"
            f"  width: 100% !important;"
            f" }}\n"
        )

    # ── Dynamic CSS fragments ────────────────────────────────────────────
    locked_org_css = """
div[class*="st-key-btn_quick_org_"] button {
    opacity: 0.32 !important;
    pointer-events: none !important;
    cursor: not-allowed !important;
}
""" if org_is_locked else ""

    active_card_css = f"""
div.st-key-btn_quick_preset_{active_idx} button,
div.st-key-btn_quick_preset_{active_idx} button:hover {{
    border-color: rgba(63, 217, 255, 0.5) !important;
    background-image: url('data:image/png;base64,{_preset_icons[active_idx]}'),
                      linear-gradient(160deg, rgba(63,217,255,0.12) 0%, rgba(63,217,255,0.04) 100%) !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.08) !important;
    transform: none !important;
    transition: none !important;
}}
div.st-key-btn_quick_preset_{active_idx} button::before {{
    border: none !important;
    background-color: transparent !important;
    background-image: {_radio_svg} !important;
    background-size: contain !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
}}
""" if active_idx is not None else ""

    active_org_css = f"""
div.st-key-btn_quick_org_{active_org_key} button,
div.st-key-btn_quick_org_{active_org_key} button:hover {{
    background-image: url('data:image/png;base64,{b64_sub if active_org_key == 'subfolders' else b64_flat_ico}'),
                      linear-gradient(160deg, rgba(63, 217, 255, 0.12) 0%, rgba(63, 217, 255, 0.04) 100%) !important;
    background-size: 42px auto, cover !important;
    background-position: 15px center, center !important;
    background-repeat: no-repeat, no-repeat !important;
    border-color: rgba(63, 217, 255, 0.5) !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.07) !important;
    transform: none !important;
    transition: none !important;
}}
div.st-key-btn_quick_org_{active_org_key} button::before {{
    border: none !important;
    background-color: transparent !important;
    background-image: {_radio_svg} !important;
    background-size: contain !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
}}
"""

    # ── HOISTED CSS ──────────────────────────────────────────────────────
    st.html(f"""
<style>
/* Equal height for cards - Surgical fix from HACKS_AND_GUARDRAILS.md */
div[class*="st-key-qd_presets_row"] [data-testid="stHorizontalBlock"],
div[class*="st-key-qd_org_wrap"] [data-testid="stHorizontalBlock"] {{
    align-items: stretch !important;
}}

/* Target the intermediate stLayoutWrapper bottleneck */
div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-btn_quick_"]) {{
    flex: 1 !important;
    display: flex !important;
    flex-direction: column !important;
}}

/* Force the keyed element and button to fill the stretched wrapper */
div[class*="st-key-btn_quick_"] {{
    flex: 1 !important;
    display: flex !important;
    flex-direction: column !important;
    height: 100% !important;
}}

div[class*="st-key-btn_quick_"] .stButton,
div[class*="st-key-btn_quick_"] button {{
    flex: 1 !important;
    height: 100% !important;
    display: flex !important;
    flex-direction: column !important;
}}

{_preset_desc_css}

/* ═══════════════════════════════════════════════════════
   PRESET CARDS - SQUARE GRID (3 + 2)
   ═══════════════════════════════════════════════════════ */
/* ─── Preset button - the button IS the card ─── */
div[class*="st-key-btn_quick_preset_"] button {{
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: flex-start !important;
    width: 100% !important;
    min-height: 180px !important;
    
    border: 1px solid rgba(255,255,255,0.09) !important;
    border-radius: 12px !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 2px 8px rgba(0,0,0,0.15) !important;
    
    background-repeat: no-repeat, no-repeat !important;
    background-position: center 24px, center !important;
    background-size: 57px auto, cover !important;
    
    padding: 94px 14px 24px 14px !important;
    transform: none !important;
    position: relative !important;
    cursor: pointer !important;
    transition: none !important;
}}
div[class*="st-key-btn_quick_preset_"] button:hover {{
    border-color: rgba(63,217,255,0.22) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 2px 8px rgba(0,0,0,0.15) !important;
    transform: none !important;
    transition: none !important;
}}
div[class*="st-key-btn_quick_preset_"] button:active {{
    transform: none !important;
    transition: none !important;
}}

/* Inner div - center the title text */
div[class*="st-key-btn_quick_preset_"] button > div,
div[class*="st-key-btn_quick_preset_"] button div[data-testid="stMarkdownContainer"] {{
    width: 100% !important;
    display: flex !important;
    justify-content: center !important;
    text-align: center !important;
}}
div[class*="st-key-btn_quick_preset_"] button p {{
    font-size: 0.94rem !important;
    font-weight: 600 !important;
    color: #ffffff !important;
    line-height: 1.3 !important;
    text-align: center !important;
    margin: 0 !important;
    padding: 0 !important;
    width: 100% !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
}}

/* Radio ring - inactive (positioned in card top-right) */
div[class*="st-key-btn_quick_preset_"] button::before {{
    content: "" !important;
    position: absolute !important;
    top: 10px !important;
    right: 10px !important;
    transform: none !important;
    width: 16px !important;
    height: 16px !important;
    border: 2px solid rgba(255,255,255,0.18) !important;
    border-radius: 50% !important;
    box-sizing: border-box !important;
    background-color: transparent !important;
}}

/* Active card + active button */
{active_card_css}

/* ═══════════════════════════════════════════════════════
   ORGANISATION BUTTONS
   ═══════════════════════════════════════════════════════ */
div[class*="st-key-btn_quick_org_"] button {{
    background: linear-gradient(160deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.02) 100%) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.04), 0 2px 6px rgba(0,0,0,0.12) !important;
    border-radius: 12px !important;
    position: relative !important;
    padding: 16px 32px 18px 70px !important;
    min-height: 80px !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: flex-start !important;
    justify-content: center !important;
    text-align: left !important;
    transform: none !important;
    transition: none !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
}}
div[class*="st-key-btn_quick_org_"] button:hover {{
    border-color: rgba(63,217,255,0.22) !important;
    background-color: rgba(255,255,255,0.025) !important;
    transform: none !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.04), 0 2px 6px rgba(0,0,0,0.12) !important;
    transition: none !important;
}}
div[class*="st-key-btn_quick_org_"] button:active {{ transform: none !important; transition: none !important; }}
div[class*="st-key-btn_quick_org_"] button > div,
div[class*="st-key-btn_quick_org_"] button div[data-testid="stMarkdownContainer"] {{
    width: 100% !important;
    display: flex !important;
    justify-content: flex-start !important;
    text-align: left !important;
}}
div[class*="st-key-btn_quick_org_"] button p {{
    font-size: 0.98rem !important;
    font-weight: 600 !important;
    margin: 0 !important;
    color: #ffffff !important;
    text-align: left !important;
    width: 100% !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
}}
div.st-key-btn_quick_org_subfolders button::after {{ content: "Match Canvas layout. Each module becomes its own subfolder." !important; }}
div.st-key-btn_quick_org_flat button::after {{ content: "All files saved directly in the course folder." !important; }}
div[class*="st-key-btn_quick_org_"] button::after {{
    font-size: 0.82rem !important;
    color: #cbd5e1 !important;
    margin-top: 3px !important;
    white-space: normal !important;
    text-align: left !important;
    display: block !important;
    width: 100% !important;
}}
div[class*="st-key-btn_quick_org_"] button::before {{
    content: "" !important;
    position: absolute !important;
    top: 12px !important;
    right: 12px !important;
    width: 16px !important;
    height: 16px !important;
    border: 2px solid rgba(255,255,255,0.18) !important;
    border-radius: 50% !important;
    box-sizing: border-box !important;
    background-color: transparent !important;
    transform: none !important;
}}
div.st-key-btn_quick_org_subfolders button {{
    background-image: url('data:image/png;base64,{b64_sub}'),
                      linear-gradient(160deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.02) 100%) !important;
    background-repeat: no-repeat, no-repeat !important;
    background-position: 15px center, center !important;
    background-size: 42px auto, cover !important;
}}
div.st-key-btn_quick_org_flat button {{
    background-image: url('data:image/png;base64,{b64_flat_ico}'),
                      linear-gradient(160deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.02) 100%) !important;
    background-repeat: no-repeat, no-repeat !important;
    background-position: 15px center, center !important;
    background-size: 42px auto, cover !important;
}}
{active_org_css}
{locked_org_css}

/* Org columns gap override */
div.st-key-qd_org_wrap [data-testid="stHorizontalBlock"] {{
    gap: 12px !important;
}}

/* ═══════════════════════════════════════════════════════
   FOLDER / DESTINATION UI
   ═══════════════════════════════════════════════════════ */
div.st-key-qd_browse_folder button {{
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #cbd5e1 !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    height: 58px !important;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease !important;
    transform: none !important;
}}
div.st-key-qd_browse_folder button:hover {{
    background: rgba(255,255,255,0.1) !important;
    color: #ffffff !important;
    border-color: rgba(255,255,255,0.25) !important;
    transform: none !important;
}}

/* ═══════════════════════════════════════════════════════
   COURSE DROPDOWN (HTML details)
   ═══════════════════════════════════════════════════════ */
details.qd-dropdown {{
    width: 100%;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    background: transparent;
    margin-top: 8px;
}}
details.qd-dropdown[open] {{
    background: rgba(0,0,0,0.18);
    border-color: rgba(255,255,255,0.18);
}}
details.qd-dropdown summary {{
    cursor: pointer;
    padding: 11px 16px;
    list-style: none;
    user-select: none;
    outline: none;
    display: flex;
    align-items: center;
    gap: 10px;
}}
details.qd-dropdown summary::-webkit-details-marker {{ display: none; }}
.qd-dd-chevron {{
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    transition: none;
}}
details.qd-dropdown[open] .qd-dd-chevron svg {{ transform: rotate(90deg); }}
.qd-dd-title {{
    color: #e2e8f0;
    font-size: 0.92rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 9px;
    flex: 1;
}}
.qd-dd-badge {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background-color: rgba(29,78,216,0.35);
    border: 1px solid rgba(99,130,255,0.3);
    color: #a5b4fc;
    font-size: 0.8rem;
    font-weight: 700;
    min-width: 18px;
    height: 20px;
    padding: 0 7px;
    border-radius: 5px;
}}
.qd-dd-body {{
    max-height: 280px;
    overflow-y: auto;
}}
ul.qd-course-list {{ margin: 0; padding: 0 16px; list-style: none; }}
li.qd-course-item {{
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 7px 0;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}}
li.qd-course-item:last-child {{ border-bottom: none; }}
.qd-num {{ color: #64748b; font-size: 0.88rem; min-width: 18px; margin-top: 1px; flex-shrink: 0; }}
.qd-name-wrap {{ display: flex; flex-direction: column; min-width: 0; }}
.qd-name {{ color: #e2e8f0; font-size: 0.88rem; white-space: normal; line-height: 1.3; overflow-wrap: anywhere; }}
.qd-code {{ color: #64748b; font-size: 0.77rem; white-space: normal; margin-top: 1px; overflow-wrap: anywhere; }}
.qd-dd-body::-webkit-scrollbar {{ width: 5px; }}
.qd-dd-body::-webkit-scrollbar-track {{ background: transparent; }}
.qd-dd-body::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.12); border-radius: 8px; }}

/* ═══════════════════════════════════════════════════════
   CONFIG EXPANDER (st.expander styled to match qd-dropdown)
   ═══════════════════════════════════════════════════════ */
div.st-key-qd_config_wrap [data-testid="stExpander"] details,
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details {{
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    margin-top: 8px !important;
}}
div.st-key-qd_config_wrap [data-testid="stExpander"] details[open],
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details[open] {{
    background: rgba(0,0,0,0.18) !important;
    border-color: rgba(255,255,255,0.18) !important;
}}
div.st-key-qd_config_wrap [data-testid="stExpander"] details summary,
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details summary {{
    padding: 11px 16px !important;
    list-style: none !important;
    cursor: pointer !important;
    user-select: none !important;
    outline: none !important;
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    background: transparent !important;
}}
div.st-key-qd_config_wrap [data-testid="stExpander"] details summary::-webkit-details-marker,
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details summary::-webkit-details-marker {{
    display: none !important;
}}
/* Label text */
div.st-key-qd_config_wrap [data-testid="stExpander"] details summary p,
div.st-key-qd_config_wrap [data-testid="stExpander"] details summary span:not([data-testid]),
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details summary p,
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details summary span:not([data-testid]) {{
    color: #e2e8f0 !important;
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    flex: 1 !important;
    margin: 0 !important;
}}
/* Replace Streamlit's expand icon with our outline chevron */
div.st-key-qd_config_wrap [data-testid="stExpander"] details summary svg,
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details summary svg,
div.st-key-qd_config_wrap [data-testid="stExpander"] details summary [data-testid="stExpanderToggleIcon"],
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details summary [data-testid="stExpanderToggleIcon"],
div.st-key-qd_config_wrap [data-testid="stExpander"] details summary [data-testid="stIconMaterial"],
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details summary [data-testid="stIconMaterial"] {{
    display: none !important;
}}
div.st-key-qd_config_wrap [data-testid="stExpander"] details summary::before,
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details summary::before {{
    content: "" !important;
    display: inline-block !important;
    width: 14px !important;
    height: 14px !important;
    background-image: url("data:image/svg+xml,%3Csvg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round' xmlns='http://www.w3.org/2000/svg'%3E%3Cpolyline points='9 18 15 12 9 6'%3E%3C/polyline%3E%3C/svg%3E") !important;
    background-repeat: no-repeat !important;
    background-size: contain !important;
    flex-shrink: 0 !important;
    transition: none !important;
}}
div.st-key-qd_config_wrap [data-testid="stExpander"] details[open] summary::before,
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details[open] summary::before {{
    transform: rotate(90deg) !important;
}}
/* Content area */
div.st-key-qd_config_wrap [data-testid="stExpander"] details > div,
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details > div {{
    border-top: 1px solid rgba(255,255,255,0.06) !important;
    padding: 12px 16px 14px !important;
}}
/* Kill extra vertical spacing inside the expander content */
div.st-key-qd_config_wrap [data-testid="stExpander"] [data-testid="stVerticalBlock"],
div.st-key-qd_courses_dropdown [data-testid="stExpander"] [data-testid="stVerticalBlock"] {{
    gap: 0 !important;
}}
/* Style the count tag inside the courses expander summary */
div.st-key-qd_courses_dropdown [data-testid="stExpander"] details summary p code {{
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    background-color: rgba(56, 189, 248, 0.15) !important;
    border: 1px solid rgba(56, 189, 248, 0.3) !important;
    color: #ffffff !important;
    font-size: 0.9rem !important;
    font-weight: 700 !important;
    min-width: 20px !important;
    height: 24px !important;
    padding: 0 9px !important;
    border-radius: 8px !important;
    line-height: 1 !important;
    margin-left: 8px !important;
    font-family: inherit !important;
}}
/* Bottom "Customize" Button - Match Description Text */
div.st-key-qd_goto_advanced button {{
    background: transparent !important;
    border: none !important;
    color: #64748b !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    padding: 0 !important;
    text-align: left !important;
    width: auto !important;
    box-shadow: none !important;
    text-transform: none !important;
    letter-spacing: normal !important;
    line-height: 1.5 !important;
    transition: color 0.2s ease !important;
    display: flex !important;
    justify-content: flex-start !important;
    min-height: 0px !important;
}}
div.st-key-qd_goto_advanced button:hover {{
    color: #94a3b8 !important;
    background: transparent !important;
}}
div.st-key-qd_goto_advanced button p {{
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    margin: 0 !important;
    display: flex !important;
    align-items: center !important;
}}
div.st-key-qd_goto_advanced button p::before {{
    content: "";
    display: inline-block !important;
    width: 14px !important;
    height: 14px !important;
    background-image: url('data:image/png;base64,{b64_custom_dl}') !important;
    background-size: contain !important;
    opacity: 50%;
    margin-right: 8px !important;
}}


/* ═══════════════════════════════════════════════════════
   NAV BUTTONS
   ═══════════════════════════════════════════════════════ */
div.st-key-page_nav_quick_advanced button {{
    background: transparent !important;
    border: none !important;
    color: #64748b !important;
    font-weight: 400 !important;
    border-radius: 6px !important;
    height: 34px !important;
    font-size: 0.83rem !important;
    box-shadow: none !important;
    transform: none !important;
    justify-content: flex-end !important;
    padding-right: 0 !important;
}}
div.st-key-page_nav_quick_advanced button:hover {{
    background: transparent !important;
    color: #94a3b8 !important;
    box-shadow: none !important;
    transform: none !important;
}}
div.st-key-page_nav_quick_advanced button > div,
div.st-key-page_nav_quick_advanced button p {{
    text-align: right !important;
    width: 100% !important;
    justify-content: flex-end !important;
}}
div.st-key-page_nav_quick_start button {{
    background-color: #1f77b4 !important;
    border: none !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    font-size: 1.05rem !important;
    border-radius: 8px !important;
    height: 48px !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.2) !important;
    transition: background-color 0.15s ease !important;
    transform: none !important;
}}
div.st-key-page_nav_quick_start button:hover {{
    background-color: #2b8cbe !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.25) !important;
    transform: none !important;
}}
div.st-key-page_nav_quick_start button:active {{
    background-color: #1a6a9f !important;
    transform: none !important;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.2) !important;
}}

</style>
""")

    # ── Main Layout Centering ────────────────────────────────────────────
    _, main_col, _ = st.columns([1, 2.4, 1])

    with main_col:
        # ── Page header ──────────────────────────────────────────────────
        _qd_help_title = "Quick Download Guide"
        _qd_help_text = (
            "<b>Quick Download is the fastest way to get your course materials without worrying about technical settings.</b>"
            "<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>How it works</div>"
            "Instead of manually configuring dozens of options, you choose a <b>Preset</b>. "
            "A preset is a pre-packaged 'recipe' that defines exactly what gets downloaded, what conversions are run, and how your folders are organized."
            "<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>Picking the right Preset</div>"
            "<ul style='margin-top: 5px; margin-bottom: 10px; padding-left: 20px; font-size: 0.9rem; line-height: 1.5;'>"
            "<li><b>Complete Canvas Download</b>: Downloads everything (files, assignments, quizzes, etc.) keeping everything organized just like canvas, <b>including full Panopto lecture videos</b>. Best for a complete, 1:1 backup.</li>"
            "<li><b>Daily study pack (Optimized)</b>: Downloads all files, converting PowerPoints and outdated Word filetypes to PDF for best AI compatibility, <b>plus Panopto lecture video &amp; audio</b>.</li>"
            "<li><b>100% AI & NotebookLM Ready</b>: All files in one folder, everything AI-Optimized, and ready to drag into notebookLM or your favorite AI, <b>plus Panopto lecture audio</b> in a separate Recordings folder.</li>"
            "<li><b>Slides & PDFs Only</b>: Only downloads lecture slides and PDFs, skipping all other files (no Panopto recordings). Good if you want to focus only on the essentials.</li>"
            "<li><b>Files Only</b>: Pure files - only downloads teacher-uploaded files while skipping all Canvas text-based content (e.g. Assignment descriptions and announcements) and Panopto recordings.</li>"
            "</ul>"
            f"<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>{HELP_ICONS.get('video', HELP_ICONS['package'])} Panopto Lecture Recordings</div>"
            "Several presets also fetch <b>Panopto lecture recordings</b> linked in your courses - the app finds them automatically, downloads the video and/or audio, and saves them right inside the course folder (you'll see a <b>Searching for Panopto Recordings</b> step after the files finish). "
            "The configuration preview at the bottom of this page shows exactly which recording formats a preset includes. "
            "Want transcripts or subtitles too, or finer control over video vs. audio? Switch to <b>Custom Download</b>, where Card 4 lets you pick formats and set up on-device transcription."
            f"<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>{HELP_ICONS['folder']} Organization Styles</div>"
            "You can choose between <b>With Subfolders</b> (mirrors Canvas Modules exactly) or <b>All in One Folder</b> (flattens directories by placing all files in one single folder). <br>"
            "<i>Note: The Complete Canvas Download preset locks this choice to With Subfolders to preserve the layout, and the NotebookLM preset locks it to All in One Folder to ensure compatibility with NotebookLM's subfolder limitations.</i>"
            "<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>Batch Processing</div>"
            "The preset and organization style you choose will be applied to <b>ALL</b> courses you selected in the previous step. "
            "You can review your selected courses in the dropdown at the bottom of the page."
            "<hr>"
            f"<div style='font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-bottom: 8px; margin-top: 16px; display: flex; align-items: center; gap: 8px;'>{HELP_ICONS['question']} Frequently Asked Questions</div>"
            "<details style='margin-top: 8px; cursor: pointer;'>"
            "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What is a Preset?</summary>"
            "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
            "A Preset is a pre-packaged combination of download settings. It pre-selects which files to download, what folders to create, and what file conversions to perform, removing all technical hassle."
            "</div></details>"
            "<details style='margin-top: 8px; cursor: pointer;'>"
            "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Can I change the settings of a Preset?</summary>"
            "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
            "Presets are pre-configured to be simple and quick. If you need to tweak specific options (like keeping original slides instead of converting to PDF, or choosing which Canvas-native content to download), click the <b>Go to Custom Download →</b> button in the top right corner where you have full control over every single toggle."
            "</div></details>"
            "<details style='margin-top: 8px; cursor: pointer;'>"
            "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Why is the folder option locked on some presets?</summary>"
            "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
            "Some presets enforce a specific folder structure to guarantee compatibility or correctness:<br>"
            "• <b>Complete Canvas Download (1:1)</b> locks organization to <b>With Subfolders</b> to preserve the exact Canvas modules and layout.<br>"
            "• <b>100% AI & NotebookLM Ready</b> locks organization to <b>All in One Folder</b> because NotebookLM does not support subfolders when importing, ensuring all files can be selected and uploaded seamlessly."
            "</div></details>"
            "<details style='margin-top: 8px; cursor: pointer;'>"
            "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Do the file conversions (like PPTX to PDF) delete my original files?</summary>"
            "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
            "Yes - the optimized files replace the originals to keep your folder clean and ready for AI tools. If you want to keep the original PowerPoint or Excel spreadsheet files, use either the <b>Complete Canvas Download</b> preset, the <b>Files Only</b> preset, or use <b>Custom Download</b> that have conversions disabled.<br>For getting the best of both worlds, keep an AI-Optimized course folder and a non-optimized (original files) version, by running two separate downloads."
            "</div></details>"
            "<details style='margin-top: 8px; cursor: pointer;'>"
            "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>Does Quick Download update existing folders on my computer?</summary>"
            "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
            "Yes! If you select a folder that already contains downloads from a previous run, the app will safely add any new files and apply updates without deleting your existing work or custom files. However, for continuous syncing, we highly recommend using <b>Sync Mode</b> from the sidebar instead, which is optimized for tracking changes."
            "</div></details>"
            "<details style='margin-top: 8px; cursor: pointer;'>"
            "<summary style='font-weight: 500; color: #e2e8f0; margin-bottom: 4px;'>What are the Panopto lecture recordings some presets download?</summary>"
            "<div style='padding: 8px 12px; margin-top: 4px; margin-bottom: 8px; background-color: rgba(63, 217, 255, 0.05); font-size: 0.85rem; color: #d1d5db; cursor: default;'>"
            "Many courses embed lecture recordings from <b>Panopto</b>. The app detects those links, downloads the lecture video and/or audio, and stores them inside the course folder. Some presets include them by default (see each preset's badges in the preview). For transcripts (.txt) and subtitles (.srt) - generated locally on your machine, nothing uploaded - use <b>Custom Download → Card 4</b> to choose formats and download a transcription model. Recordings are also fully supported in <b>Sync Mode</b>."
            "</div></details>"
            "<hr>"
            f"<b>{HELP_ICONS['lightbulb']} Pro Tip:</b> If you need to tweak individual settings (like specific AI Optimizations, or certain Canvas Content), "
            f"click <b>Go to Custom Download'</b> in the top right corner."
        )

        # Snug Header Hack - H1 + Help button on one flex row
        st.html("""
            <style>
            div.st-key-qd_title_help_row [data-testid="stHorizontalBlock"] {
                display: flex !important;
                flex-direction: row !important;
                align-items: flex-end !important;
                gap: 10px !important;
                justify-content: flex-start !important;
            }
            div.st-key-qd_title_help_row [data-testid="column"],
            div.st-key-qd_title_help_row [data-testid="stColumn"] {
                width: auto !important;
                flex: 0 0 auto !important;
                min-width: 0px !important;
                padding: 0 !important;
            }
            div.st-key-qd_title_help_row h1 {
                margin-right: 0 !important;
                padding-right: 0 !important;
                line-height: 1 !important;
            }
            div.st-key-qd_title_help_row div[class*="st-key-quick_download_explainer_help_btn"] {
                margin-bottom: 0px !important;
                margin-left: 0 !important;
            }
            </style>
        """)

        hdr_col, adv_col = st.columns([3, 1.4], vertical_alignment="center")
        with hdr_col:
            with st.container(key="qd_title_help_row"):
                _c1, _c2 = st.columns([1, 10])
                with _c1:
                    st.markdown("<h1 style='font-size:1.8rem; font-weight:800; margin:0; color:#f8fafc; letter-spacing:-0.02em; white-space: nowrap;'>Quick Download</h1>", unsafe_allow_html=True)
                with _c2:
                    render_help_card(
                        key_prefix="quick_download_explainer",
                        title=_qd_help_title,
                        text_html=_qd_help_text,
                        icon="",
                        mode="button"
                    )
            st.markdown(
                "<p style='color:#94a3b8; font-size:0.95rem; margin:6px 0 0 0; line-height:1.4;'>"
                "Select how you want your courses downloaded. We'll handle the rest."
                "</p>",
                unsafe_allow_html=True,
            )
        with adv_col:
            if st.button("Switch to Custom Download →", key="page_nav_quick_advanced", use_container_width=True):
                st.session_state['quick_download_mode'] = False
                st.session_state['came_from_quick_dl'] = True
                st.rerun()

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

        # Help Card Expansion
        render_help_card(
            key_prefix="quick_download_explainer",
            title=_qd_help_title,
            text_html=_qd_help_text,
            icon="",
            mode="card"
        )

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

        # ── Section 1: Presets ───────────────────────────────────────────
        st.markdown(
            "<div style='display:flex; align-items:center; gap:10px; margin:0 0 10px 0;'>"
            "<div style='background:rgba(56, 189, 248, 0.5); color:#ffffff; width:26px; height:26px; border-radius:6px; "
            "display:flex; align-items:center; justify-content:center; font-weight:700; font-size:0.85rem; flex-shrink:0;'>1</div>"
            "<p style='font-size:0.8rem; font-weight:600; letter-spacing:0.04em; "
            "text-transform:uppercase; color:#e2e8f0; margin:0;'>Choose which files to download</p>"
            "</div>",
            unsafe_allow_html=True,
        )

        # Row 1 - 3 cards
        with st.container(key="qd_presets_row1"):
            r1c1, r1c2, r1c3 = st.columns(3, gap="small")
            for i, col in enumerate([r1c1, r1c2, r1c3]):
                with col:
                    st.button(
                        _QUICK_PRESETS[i]['name'],
                        key=f"btn_quick_preset_{i}",
                        use_container_width=True,
                        on_click=_select_preset_cb,
                        args=(_QUICK_PRESETS[i]['id'], _QUICK_PRESETS[i]['settings']['download_mode']),
                    )

        # Row 2 - 2 cards centered (same card width as row-1 columns)
        # [1, 2, 2, 1] → inner cols each = 2/6 = 1/3 of total (matches row-1 cards)
        with st.container(key="qd_presets_row2"):
            _, r2c1, r2c2, _ = st.columns([1, 2, 2, 1], gap="small")
            for i, col in zip([3, 4], [r2c1, r2c2]):
                with col:
                    st.button(
                        _QUICK_PRESETS[i]['name'],
                        key=f"btn_quick_preset_{i}",
                        use_container_width=True,
                        on_click=_select_preset_cb,
                        args=(_QUICK_PRESETS[i]['id'], _QUICK_PRESETS[i]['settings']['download_mode']),
                    )

        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

        # ── Section 2: Organization ──────────────────────────────────────
        _org_lock_note = (
            " <span style='font-size:0.72rem; font-weight:400; color:#64748b; "
            "text-transform:none; letter-spacing:0; margin-left:4px;'>"
            "(Locked by preset)</span>"
        ) if org_is_locked else ""
        st.markdown(
            "<div style='display:flex; align-items:center; gap:10px; margin:0 0 10px 0;'>"
            "<div style='background:rgba(56, 189, 248, 0.5); color:#ffffff; width:26px; height:26px; border-radius:6px; "
            "display:flex; align-items:center; justify-content:center; font-weight:700; font-size:0.85rem; flex-shrink:0;'>2</div>"
            f"<p style='font-size:0.8rem; font-weight:600; letter-spacing:0.04em; "
            f"text-transform:uppercase; color:#e2e8f0; margin:0;'>Choose how files are organized{_org_lock_note}</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        with st.container(key="qd_org_wrap"):
            org_c1, org_c2 = st.columns(2, gap="small")
            with org_c1:
                st.button(
                    "With Subfolders",
                    key="btn_quick_org_subfolders",
                    use_container_width=True,
                    on_click=_select_org_cb,
                    args=('modules',),
                )
            with org_c2:
                st.button(
                    "All in One Folder",
                    key="btn_quick_org_flat",
                    use_container_width=True,
                    on_click=_select_org_cb,
                    args=('flat',),
                )

        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

        # ── Section 3: Output destination ────────────────────────────────
        download_path = st.session_state.get('download_path', str(Path.home() / "Downloads"))
        st.markdown(
            "<div style='display:flex; align-items:center; gap:10px; margin:0 0 10px 0;'>"
            "<div style='background:rgba(56, 189, 248, 0.5); color:#ffffff; width:26px; height:26px; border-radius:6px; "
            "display:flex; align-items:center; justify-content:center; font-weight:700; font-size:0.85rem; flex-shrink:0;'>3</div>"
            "<p style='font-size:0.8rem; font-weight:600; letter-spacing:0.04em; "
            "text-transform:uppercase; color:#e2e8f0; margin:0;'>Verify your download destination</p>"
            "</div>",
            unsafe_allow_html=True,
        )

        f_col, btn_col = st.columns([4, 1.2], gap="small")
        with f_col:
            folder_name   = Path(download_path).name or download_path
            folder_parent = str(Path(download_path).parent)
            st.markdown(
                f"""
                <div title="{esc(download_path)}" style="
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
            st.button("Change folder", key="qd_browse_folder", use_container_width=True, on_click=_select_folder_cb)

        # ── Course dropdown ──────────────────────────────────────────────
        _dl_courses = []
        try:
            _all_c   = fetch_courses_fn(st.session_state['api_token'], st.session_state['api_url'])
            _sel_ids = set(st.session_state.get('selected_course_ids', []))
            _dl_courses = [c for c in _all_c if c.id in _sel_ids]
        except Exception:
            pass
        _dl_count = len(_dl_courses)

        def _render_course_row(idx, course):
            name, code = get_course_display_parts(course)
            code_clean = code.strip("()") if code else ""
            code_html  = f"<div class='qd-code'>{esc(code_clean)}</div>" if code_clean else ""
            return (
                f"<li class='qd-course-item'>"
                f"<span class='qd-num'>{idx}.</span>"
                f"<div class='qd-name-wrap'><div class='qd-name'>{esc(name)}</div>{code_html}</div>"
                f"</li>"
            )

        _course_rows = "".join(_render_course_row(i, c) for i, c in enumerate(_dl_courses, 1))

        with st.container(key="qd_courses_dropdown"):
            with st.expander(f"Courses selected for download  `{_dl_count}`"):
                st.html(f"<div class='qd-dd-body'><ul class='qd-course-list'>{_course_rows}</ul></div>")

        # ── See configuration (st.expander + edit button) ────────────────
        with st.container(key="qd_config_wrap"):
            with st.expander("See configuration"):
                if active_preset is not None:
                    _config_badges = render_config_summary_badges(active_preset['settings'], show_path=False)
                    st.html("<div style='color:#64748b; font-size:0.82rem; padding:0 0 10px 0; line-height:1.5;'>The badges below show the preset download configuration. (Square tag = file organization, round tag = what will be downloaded or converted).</div>")
                    st.markdown(_config_badges, unsafe_allow_html=True)
                else:
                    st.html("<div style='color:#64748b; font-size:0.82rem; padding:4px 0 8px 0;'>Select a preset above to preview its configuration.</div>")
                if st.button(
                    "Customize this configuration in Custom Download",
                    key="qd_goto_advanced",
                    use_container_width=True,
                    disabled=(active_preset is None),
                ):
                    # Pre-populate all download settings from the active preset
                    _s = dict(active_preset['settings'])  # type: ignore[index]
                    _s['download_mode'] = selected_org  # carry over org choice
                    st.session_state['download_mode']        = _s['download_mode']
                    st.session_state['file_filter']          = _s.get('file_filter', 'all')
                    st.session_state['dl_isolate_secondary'] = _s.get('dl_isolate_secondary', False)
                    st.session_state['dl_secondary_master']  = _s.get('dl_secondary_master', False)
                    st.session_state['notebooklm_master']    = _s.get('notebooklm_master', False)
                    for _k in SECONDARY_CONTENT_KEYS:
                        _v = _s.get(_k, False)
                        st.session_state[_k] = _v
                        st.session_state[f'persistent_{_k}'] = _v
                    for _k in NOTEBOOK_SUB_KEYS:
                        _v = _s.get(_k, False)
                        st.session_state[_k] = _v
                        st.session_state[f'persistent_{_k}'] = _v
                    # Panopto (Section 4): carry output formats + layout so Custom
                    # Download's Section 4 reflects the preset's recordings choice.
                    for _k in PANOPTO_OUTPUT_KEYS:
                        _v = _s.get(_k, False)
                        st.session_state[_k] = _v
                        st.session_state[f'persistent_{_k}'] = _v
                    _pl = _s.get('pan_layout', 'match')
                    st.session_state['pan_layout'] = _pl
                    st.session_state['persistent_pan_layout'] = _pl
                    st.session_state['card2_expanded'] = any(st.session_state.get(_k, False) for _k in SECONDARY_CONTENT_KEYS)
                    st.session_state['card3_expanded'] = any(st.session_state.get(_k, False) for _k in NOTEBOOK_SUB_KEYS)
                    st.session_state['card_panopto_expanded'] = any(st.session_state.get(_k, False) for _k in PANOPTO_OUTPUT_KEYS)
                    st.session_state['quick_download_mode'] = False
                    st.session_state['came_from_quick_dl'] = True
                    st.rerun()

        # ── Action buttons ───────────────────────────────────────────────
        st.markdown(
            "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:28px 0 20px 0;'>",
            unsafe_allow_html=True,
        )
        error_placeholder = st.empty()

        # ── macOS hands-off nudge (Full Disk Access) ─────────────────────
        # Presets that convert Office files (Daily study pack, AI-Optimized)
        # hit the once-per-session macOS consent dialog when the run starts -
        # surface the same dismissible guide as custom download's step 2,
        # right above the confirm button. The qdl_fda key prefix picks up the
        # download-surface CSS (right-aligned link, 15px air below). Renders
        # nothing on Windows, macOS ≤14, or once FDA is granted.
        if active_preset is not None and any(
                active_preset['settings'].get(_k, False)
                for _k in ('convert_pptx', 'convert_word', 'convert_excel')):
            from shared.components import render_fda_nudge
            render_fda_nudge("qdl_fda")

        act_back, _spacer, act_start = st.columns([1, 3.5, 1.5])
        with act_back:
            back_clicked = st.button("Go back", key="page_nav_quick_back", use_container_width=True)
        with act_start:
            start_clicked = st.button(
                "Confirm and Download", key="page_nav_quick_start", type="primary",
                use_container_width=True, disabled=(selected_id is None),
            )

        if back_clicked:
            # Reset preset so re-entering Quick Download from Course Selector starts fresh.
            st.session_state.pop('quick_preset_id', None)
            st.session_state['quick_download_mode'] = False
            st.session_state['step'] = 1
            st.rerun()

        if start_clicked:
            if not st.session_state.get('selected_course_ids'):
                error_placeholder.error("No courses selected - go back and select at least one course.")
                st.stop()

            _dl_path = Path(st.session_state['download_path'])
            try:
                _dl_path.mkdir(parents=True, exist_ok=True)
                _probe = _dl_path / '.canvas_write_probe'
                _probe.write_bytes(b'ok')
                _probe.unlink()
            except Exception as _wp_err:
                from ui.amber_notice import render_error_notice
                render_error_notice(
                    f"Cannot write to the selected folder.<br>"
                    f"<b>Reason:</b> {_wp_err}<br>"
                    f"Please choose a different folder.",
                    allow_html=True
                )
                st.stop()

            preset   = next((p for p in _QUICK_PRESETS if p['id'] == selected_id), _QUICK_PRESETS[0])
            settings = dict(preset['settings'])
            settings['download_mode'] = selected_org

            all_courses = fetch_courses_fn(
                st.session_state['api_token'],
                st.session_state['api_url'],
            )
            course_map          = {c.id: c for c in all_courses}
            courses_to_download = [
                course_map[cid]
                for cid in st.session_state['selected_course_ids']
                if cid in course_map
            ]

            st.session_state['file_filter']    = settings['file_filter']
            st.session_state['download_mode']  = settings['download_mode']
            st.session_state['dl_isolate_secondary'] = settings.get('dl_isolate_secondary', False)
            for k in SECONDARY_CONTENT_KEYS:
                st.session_state[k] = settings.get(k, False)
            for k in NOTEBOOK_SUB_KEYS:
                st.session_state[k] = settings.get(k, False)
            for k in PANOPTO_OUTPUT_KEYS:
                st.session_state[k] = settings.get(k, False)
            st.session_state['pan_layout'] = settings.get('pan_layout', 'match')

            for _stale in [
                'download_file_details', 'download_errors_list', 'failed_items',
                'downloaded_items', 'log_deque', 'skipped_discovery_errors',
                'size_skipped_files', 'pp_failure_count', 'pp_success_count',
                'log_content', 'seen_error_sigs', 'course_mb_downloaded',
                'retry_attempted', 'retry_resolved_count', 'retry_total_attempted',
                'isolated_retry_queue', 'retry_downloaded_items', 'retry_failed_items',
                'retry_isolated_details', 'retry_mb_tracker', 'is_post_processing',
                'start_time', 'total_items', 'total_mb', 'sync_has_ignored_files',
            ]:
                st.session_state.pop(_stale, None)

            from core.cancellation import reset_download_cancel
            reset_download_cancel()

            st.session_state['courses_to_download']  = courses_to_download
            st.session_state['current_course_index'] = 0
            st.session_state['cancel_requested']     = False
            st.session_state['total_items']          = 0
            st.session_state['downloaded_items']     = 0
            st.session_state['course_mb_downloaded'] = {}
            st.session_state['log_content']          = ""
            st.session_state['seen_error_sigs']      = set()

            for k in NOTEBOOK_SUB_KEYS:
                st.session_state[f'persistent_{k}'] = settings.get(k, False)
            for k in SECONDARY_CONTENT_KEYS:
                st.session_state[f'persistent_{k}'] = settings.get(k, False)
            st.session_state['persistent_dl_isolate_secondary'] = settings.get('dl_isolate_secondary', False)
            # Panopto (Section 4) per-run contract: the terminal Panopto phase
            # reads these persistent_pan_* keys via _panopto_run_contract().
            for k in PANOPTO_OUTPUT_KEYS:
                st.session_state[f'persistent_{k}'] = settings.get(k, False)
            st.session_state['persistent_pan_layout'] = settings.get('pan_layout', 'match')

            st.session_state['download_status'] = 'scanning'
            st.session_state['step']            = 3

            time.sleep(0.1)
            st.rerun()
