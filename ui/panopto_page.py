"""ui.panopto_page - Panopto lecture downloader configuration / setup page."""

from __future__ import annotations

import time
import streamlit as st

import theme
from panopto import models as pmodels
from panopto.settings import (
    PANOPTO_DEFAULTS, load_settings, save_settings, wants_transcription,
)

# session_state widget key -> settings key
_KEYMAP = {
    "pan_enabled": "enabled",
    "pan_out_mp3": "output_mp3",
    "pan_out_txt": "output_txt",
    "pan_out_srt": "output_srt",
    "pan_out_mp4": "output_mp4",
    "pan_model": "model",
    "pan_language": "language",
    "pan_device": "device",
    "pan_layout": "layout",
}

_LANGUAGES = [
    ("auto", "Auto-detect"), ("da", "Danish"), ("en", "English"),
    ("de", "German"), ("sv", "Swedish"), ("no", "Norwegian"),
    ("fi", "Finnish"), ("nl", "Dutch"), ("fr", "French"),
    ("es", "Spanish"), ("it", "Italian"),
]
_LANG_CODES = [c for c, _ in _LANGUAGES]
_LANG_LABEL = dict(_LANGUAGES)


# ── Icons & Colors ──────────────────────────────────────────────────────────

def _make_icon(inner_svg: str, color_hex: str) -> str:
    color = "%23" + color_hex.lstrip("#")
    return (
        f"data:image/svg+xml,%3Csvg viewBox='0 0 32 32' xmlns='http://www.w3.org/2000/svg'%3E"
        f"%3Crect width='32' height='32' rx='8' fill='{color}' fill-opacity='0.15'/%3E"
        f"%3Cg transform='translate(4,4)' fill='{color}'%3E{inner_svg}%3C/g%3E"
        f"%3C/svg%3E"
    )

_P_AUDIO = "%3Cpath d='M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z'/%3E"
_P_TXT = "%3Cpath d='M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z'/%3E"
_P_SRT = "%3Cpath d='M19 4H5c-1.11 0-2 .9-2 2v12c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm-8 7H9.5v-.5h-2v3h2V13H11v1c0 .55-.45 1-1 1H7c-.55 0-1-.45-1-1v-4c0-.55.45-1 1-1h3c.55 0 1 .45 1 1v1zm7 0h-1.5v-.5h-2v3h2V13H18v1c0 .55-.45 1-1 1h-3c-.55 0-1-.45-1-1v-4c0-.55.45-1 1-1h3c.55 0 1 .45 1 1v1z'/%3E"
_P_MP4 = "%3Cpath d='M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z'/%3E"

_P_MATCH = "%3Cpath d='M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2zM9.5 15.5l5.5-3.5-5.5-3.5v7z'/%3E"
_P_SEP = "%3Cpath d='M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-6 10H6v-2h8v2zm4-4H6v-2h12v2z'/%3E"

_P_CPU ="%3Cpath d='M7 17h10V7H7v10zm2-8h6v6H9V9zM21 11V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2zm-4 6H7V7h10v10z'/%3E"
_P_GPU = "%3Cpath d='M15 9H9v6h6V9zm-2 4h-2v-2h2v2zm8-2V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2zm-4 6H7V7h10v10z'/%3E"

SVG_AUDIO = _make_icon(_P_AUDIO, "a855f7") # Purple
SVG_TXT   = _make_icon(_P_TXT, "10b981")   # Green
SVG_SRT   = _make_icon(_P_SRT, "3b82f6")   # Blue
SVG_MP4   = _make_icon(_P_MP4, "f43f5e")   # Red

SVG_MATCH = _make_icon(_P_MATCH, "14b8a6") # Teal
SVG_SEP   = _make_icon(_P_SEP, "f59e0b")   # Amber

SVG_CPU = f"data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='%2394a3b8' xmlns='http://www.w3.org/2000/svg'%3E{_P_CPU}%3C/svg%3E"
SVG_GPU = f"data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='%2394a3b8' xmlns='http://www.w3.org/2000/svg'%3E{_P_GPU}%3C/svg%3E"
SVG_CPU_ACT = f"data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='%233fd9ff' xmlns='http://www.w3.org/2000/svg'%3E{_P_CPU}%3C/svg%3E"
SVG_GPU_ACT = f"data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='%233fd9ff' xmlns='http://www.w3.org/2000/svg'%3E{_P_GPU}%3C/svg%3E"

SVG_UNCHECKED = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect x='3' y='3' width='18' height='18' rx='4' fill='rgba(255,255,255,0.05)' stroke='rgba(255,255,255,0.2)' stroke-width='2'/%3E%3C/svg%3E"
SVG_CHECKED = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect x='3' y='3' width='18' height='18' rx='4' fill='%2310b981'/%3E%3Cpath d='M9 12.5l2 2 4-5' stroke='white' stroke-width='2.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"

SVG_RADIO_OFF = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='rgba(255,255,255,0.2)' stroke-width='2'/%3E%3C/svg%3E"
SVG_RADIO_ON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%233fd9ff' stroke-width='2'/%3E%3Ccircle cx='12' cy='12' r='5' fill='%233fd9ff'/%3E%3C/svg%3E"

_ICON_MAP = {
    "pan_out_mp3": (SVG_AUDIO, "rgba(168, 85, 247, 0.4)", "rgba(168, 85, 247, 0.05)"),
    "pan_out_txt": (SVG_TXT, "rgba(16, 185, 129, 0.4)", "rgba(16, 185, 129, 0.05)"),
    "pan_out_srt": (SVG_SRT, "rgba(59, 130, 246, 0.4)", "rgba(59, 130, 246, 0.05)"),
    "pan_out_mp4": (SVG_MP4, "rgba(244, 63, 94, 0.4)", "rgba(244, 63, 94, 0.05)"),
    "pan_layout_match": (SVG_MATCH, "rgba(63, 217, 255, 0.4)", "rgba(63, 217, 255, 0.05)"),
    "pan_layout_separate": (SVG_SEP, "rgba(63, 217, 255, 0.4)", "rgba(63, 217, 255, 0.05)"),
}


def _svg(inner: str, color: str = theme.ACCENT_BLUE, size: int = 20) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="{color}" '
        f'style="display:inline-block;vertical-align:middle;flex-shrink:0">{inner}</svg>'
    )

_IC_PLAY_FILLED = '<path d="M8 5v14l11-7z"/>'
_IC_GEAR = '<path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.73 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.08.62-.08.94s.03.64.08.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .43-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.49-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>'

def _section_header(icon_inner: str, title: str, subtitle: str = "") -> None:
    sub = (
        f'<div style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;margin-top:2px;">{subtitle}</div>'
        if subtitle else ""
    )
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">'
        f'{_svg(icon_inner, color=theme.TEXT_SECONDARY, size=22)}'
        f'<div><div style="color:{theme.TEXT_PRIMARY};font-size:1.05rem;font-weight:700;">{title}</div>{sub}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── CSS Injection ───────────────────────────────────────────────────────────

def _inject_card_css() -> None:
    st.html(f"""<style>
    /* Stretch horizontal blocks */
    div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-btn_pan_out_"]),
    div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-btn_pan_layout_"]) {{
        flex: 1 !important;
        display: flex !important;
        flex-direction: column !important;
    }}
    div[class*="st-key-btn_pan_out_"], div[class*="st-key-btn_pan_layout_"] {{
        flex: 1 !important;
        display: flex !important;
        flex-direction: column !important;
        height: 100% !important;
    }}
    /* MAIN BUTTON STYLE */
    div[class*="st-key-btn_pan_out_"] button, div[class*="st-key-btn_pan_layout_"] button {{
        flex: 1 !important;
        height: 100% !important;
        min-height: 80px !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;
        width: 100% !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 12px !important;
        background-color: rgba(255,255,255,0.02) !important;
        padding: 14px 38px 14px 56px !important;
        background-repeat: no-repeat !important;
        background-position: 14px center !important;
        background-size: 28px !important;
        position: relative !important;
        cursor: pointer !important;
        transition: border-color 0.15s ease, background-color 0.15s ease !important;
    }}
    div[class*="st-key-btn_pan_out_"] button:hover, div[class*="st-key-btn_pan_layout_"] button:hover {{
        background-color: rgba(255,255,255,0.03) !important;
        border-color: rgba(255,255,255,0.15) !important;
    }}
    
    /* FIX STREAMLIT INNER WRAPPERS */
    div[class*="st-key-btn_pan_out_"] button > div,
    div[class*="st-key-btn_pan_layout_"] button > div,
    div[class*="st-key-btn_pan_out_"] button div[data-testid="stMarkdownContainer"],
    div[class*="st-key-btn_pan_layout_"] button div[data-testid="stMarkdownContainer"] {{
        width: 100% !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;
        text-align: left !important;
    }}
    
    div[class*="st-key-btn_pan_"] button p {{
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        color: #e2e8f0 !important;
        margin: 0 !important;
        text-align: left !important;
        line-height: 1.2 !important;
        width: 100% !important;
    }}
    div[class*="st-key-btn_pan_out_"] button::after, div[class*="st-key-btn_pan_layout_"] button::after {{
        font-size: 0.8rem !important;
        color: #94a3b8 !important;
        margin-top: 2px !important;
        text-align: left !important;
        font-weight: 400 !important;
        display: block !important;
        width: 100% !important;
    }}
    div[class*="st-key-pan_outputs_row"] [data-testid="stHorizontalBlock"],
    div[class*="st-key-pan_org_row"] [data-testid="stHorizontalBlock"],
    div[class*="st-key-pan_layout_row"] [data-testid="stHorizontalBlock"],
    div[class*="st-key-pan_device_row"] [data-testid="stHorizontalBlock"] {{
        align-items: stretch !important;
    }}
    
    /* RIGHT-SIDE CHECKBOX/RADIO (::before) */
    div[class*="st-key-btn_pan_out_"] button::before, div[class*="st-key-btn_pan_layout_"] button::before {{
        content: "" !important;
        position: absolute !important;
        right: 14px !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        width: 20px !important;
        height: 20px !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
    }}

    div[class*="st-key-btn_pan_out_"] button::before {{ background-image: url("{SVG_UNCHECKED}") !important; }}
    div[class*="st-key-btn_pan_layout_"] button::before {{ background-image: url("{SVG_RADIO_OFF}") !important; }}

    /* Specific Injections */
    div.st-key-btn_pan_out_mp3 button {{ background-image: url("{SVG_AUDIO}") !important; }}
    div.st-key-btn_pan_out_mp3 button::after {{ content: "Audio only" !important; }}
    div.st-key-btn_pan_out_txt button {{ background-image: url("{SVG_TXT}") !important; }}
    div.st-key-btn_pan_out_txt button::after {{ content: "Plain text transcript" !important; }}
    div.st-key-btn_pan_out_srt button {{ background-image: url("{SVG_SRT}") !important; }}
    div.st-key-btn_pan_out_srt button::after {{ content: "Timestamps/Subs" !important; }}
    div.st-key-btn_pan_out_mp4 button {{ background-image: url("{SVG_MP4}") !important; opacity:0.4 !important; pointer-events:none !important; }}
    div.st-key-btn_pan_out_mp4 button::after {{ content: "Coming soon" !important; }}

    div.st-key-btn_pan_layout_match button {{ background-image: url("{SVG_MATCH}") !important; }}
    div.st-key-btn_pan_layout_match button::after {{ content: "Save alongside course files" !important; }}
    div.st-key-btn_pan_layout_separate button {{ background-image: url("{SVG_SEP}") !important; }}
    div.st-key-btn_pan_layout_separate button::after {{ content: "“Panopto Recordings” folder in the course" !important; }}

    /* Master Toggle Card */
    div.st-key-pan_master_card {{
        background-color: rgba(255, 255, 255, 0.03) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        box-shadow: none !important;
        border-radius: 12px !important;
        margin-bottom: 20px !important;
        padding: 16px 20px !important;
    }}
    
    /* Right-align the toggle inside the column */
    div.st-key-pan_master_card [data-testid="column"]:nth-child(2) div[data-testid="element-container"] {{
        display: flex !important;
        justify-content: flex-end !important;
        width: 100% !important;
    }}
    
    /* Consistent margins and layout styles for cards */
    div.st-key-pan_outputs_card,
    div.st-key-pan_org_card,
    div.st-key-pan_transcription_card {{
        margin-bottom: 20px !important;
        background-color: rgba(255, 255, 255, 0.03) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 12px !important;
    }}
    
    /* Device Segmented Control */
    div.st-key-pan_device_row > div[data-testid="stHorizontalBlock"] {{ gap: 0 !important; }}
    div[class*="st-key-btn_dev_"] button {{
        background-color: rgba(255,255,255,0.03) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        min-height: 40px !important;
        padding-left: 36px !important;
        background-repeat: no-repeat !important;
        background-position: 12px center !important;
        background-size: 16px auto !important;
        color: #94a3b8 !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
        justify-content: center !important;
    }}
    div[class*="st-key-btn_dev_"] button p {{ color: inherit !important; font-size: 0.9rem !important; margin:0 !important; }}
    div.st-key-btn_dev_cpu button {{ border-radius: 6px 0 0 6px !important; border-right: none !important; background-image: url("{SVG_CPU}") !important; }}
    div.st-key-btn_dev_gpu button {{ border-radius: 0 6px 6px 0 !important; background-image: url("{SVG_GPU}") !important; }}
    div[class*="st-key-btn_dev_"]:hover button {{ background-color: rgba(255,255,255,0.06) !important; }}

    /* Dimmed Transcription */
    div.pan_dimmed {{ opacity: 0.45 !important; pointer-events: none !important; transition: opacity 0.2s ease !important; }}
    
    /* Model Table Reset & recessed styling */
    div.st-key-pan_models_table {{
        background-color: rgba(0, 0, 0, 0.12) !important;
        border: 1px solid rgba(255,255,255,0.04) !important;
        border-radius: 12px !important;
        padding: 16px 12px !important;
        margin-top: 12px !important;
    }}
    
    /* Table header line border fix */
    div.st-key-pan_models_header {{
        padding: 0 16px 10px 16px !important;
        border-bottom: none !important;
        margin-bottom: 10px !important;
    }}
    div.st-key-pan_models_header [data-testid="stHorizontalBlock"] {{
        border-bottom: 1px solid rgba(255,255,255,0.08) !important;
        padding-bottom: 8px !important;
        margin-bottom: 8px !important;
    }}
    
    /* Model rows inside the table */
    div[class*="st-key-pan_model_row_"] {{
        background-color: rgba(255,255,255,0.01) !important;
        border: 1px solid rgba(255,255,255,0.03) !important;
        border-radius: 8px !important;
        border-left: 3px solid transparent !important;
        padding: 10px 16px !important;
        margin-bottom: 8px !important;
        transition: all 0.2s ease !important;
    }}
    div[class*="st-key-pan_model_row_"]:hover {{
        background-color: rgba(255,255,255,0.02) !important;
        border-color: rgba(255,255,255,0.06) !important;
    }}
    
    /* Vertically center text in models table rows */
    div[class*="st-key-pan_model_row_"] [data-testid="stColumn"] {{
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;
    }}
    div[class*="st-key-pan_model_row_"] p {{
        margin: 0 !important;
        padding: 0 !important;
    }}
    
    /* Model row buttons */
    div[class*="st-key-pan_model_"] button {{
        height: 32px !important;
        border-radius: 6px !important;
        font-size: 0.82rem !important;
        padding: 0 8px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    
    /* Active button styling */
    div[class*="st-key-pan_model_act_"] button[disabled] {{
        background-color: rgba(16, 185, 129, 0.15) !important;
        border: 1px solid #10b981 !important;
        color: #10b981 !important;
        font-weight: 600 !important;
        opacity: 1 !important;
    }}
    
    /* Prepend checkmark to Active disabled button */
    div[class*="st-key-pan_model_act_"] button[disabled] p::before {{
        content: "" !important;
        display: inline-block !important;
        width: 12px !important;
        height: 12px !important;
        margin-right: 6px !important;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2310b981' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E") !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
        vertical-align: middle !important;
    }}
    div[class*="st-key-pan_model_act_"] button[disabled] p {{
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    
    /* Activate button styling */
    div[class*="st-key-pan_model_act_"] button:not([disabled]) {{
        background-color: rgba(255,255,255,0.03) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        color: #cbd5e1 !important;
    }}
    div[class*="st-key-pan_model_act_"] button:not([disabled]):hover {{
        background-color: rgba(255,255,255,0.06) !important;
        border-color: rgba(255,255,255,0.15) !important;
        color: #ffffff !important;
    }}
    
    /* Download button with SVG icon */
    div[class*="st-key-pan_model_dl_"] button {{
        background-color: #1f77b4 !important;
        border: none !important;
        color: #ffffff !important;
        font-weight: 600 !important;
    }}
    div[class*="st-key-pan_model_dl_"] button:hover {{
        background-color: #2b8cbe !important;
    }}
    div[class*="st-key-pan_model_dl_"] button p::before {{
        content: "" !important;
        display: inline-block !important;
        width: 14px !important;
        height: 14px !important;
        margin-right: 6px !important;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'%3E%3Cpath d='M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM17 13l-5 5-5-5h3V9h4v4h3z'/%3E%3C/svg%3E") !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
        vertical-align: middle !important;
    }}
    div[class*="st-key-pan_model_dl_"] button p {{
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    
    /* Delete button using SVG mask */
    div[class*="st-key-pan_model_del_"] button {{
        background-color: rgba(244, 63, 94, 0.04) !important;
        border: 1px solid rgba(244, 63, 94, 0.15) !important;
        border-radius: 6px !important;
        height: 32px !important;
        position: relative !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    div[class*="st-key-pan_model_del_"] button:hover {{
        background-color: rgba(244, 63, 94, 0.12) !important;
        border-color: rgba(244, 63, 94, 0.3) !important;
    }}
    div[class*="st-key-pan_model_del_"] button::after {{
        content: "" !important;
        position: absolute !important;
        top: 50% !important;
        left: 50% !important;
        transform: translate(-50%, -50%) !important;
        width: 16px !important;
        height: 16px !important;
        background-color: #f43f5e !important;
        -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='currentColor'%3E%3Cpath d='M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z'/%3E%3C/svg%3E") !important;
        -webkit-mask-repeat: no-repeat !important;
        -webkit-mask-position: center !important;
        -webkit-mask-size: contain !important;
        transition: background-color 0.2s ease !important;
    }}
    div[class*="st-key-pan_model_del_"] button:hover::after {{
        background-color: #ff4d6d !important;
    }}
    </style>""")

def _get_active_css(keys_active: list[str]) -> str:
    css = ""
    for k in keys_active:
        if k in _ICON_MAP:
            main_icon, border_col, bg_col = _ICON_MAP[k]
            right_icon = SVG_CHECKED if k.startswith("pan_out_") else SVG_RADIO_ON
            
            # Use active checkmark/radio styling from custom download (vibrant colors)
            if k.startswith("pan_layout_"):
                border_col = "#3fd9ff"
                bg_col = "rgba(63, 217, 255, 0.15)"
                extra_style = "color: #ffffff !important; opacity: 1 !important; box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;"
            elif k.startswith("pan_out_"):
                if k == "pan_out_mp3":
                    border_col = "#a855f7"; bg_col = "rgba(168, 85, 247, 0.15)"
                elif k == "pan_out_txt":
                    border_col = "#10b981"; bg_col = "rgba(16, 185, 129, 0.15)"
                elif k == "pan_out_srt":
                    border_col = "#3b82f6"; bg_col = "rgba(59, 130, 246, 0.15)"
                elif k == "pan_out_mp4":
                    border_col = "#f43f5e"; bg_col = "rgba(244, 63, 94, 0.15)"
                extra_style = "color: #ffffff !important; opacity: 1 !important; box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;"
            else:
                extra_style = ""
                
            css += f"""
            div.st-key-btn_{k} button, div.st-key-btn_{k} button:hover {{
                border-color: {border_col} !important;
                background-color: {bg_col} !important;
                {extra_style}
            }}
            div.st-key-btn_{k} button::before {{
                background-image: url('{right_icon}') !important;
            }}
            """
            
    dev = st.session_state.get("pan_device", "cpu")
    btn_key = "gpu" if dev == "cuda" else "cpu"
    active_svg = SVG_CPU_ACT if dev == "cpu" else SVG_GPU_ACT
    css += f"""
    div.st-key-btn_dev_{btn_key} button {{
        background-color: rgba(63, 217, 255, 0.15) !important;
        border-color: #3fd9ff !important;
        color: #3fd9ff !important;
        background-image: url("{active_svg}") !important;
        z-index: 1 !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;
    }}
    div.st-key-btn_dev_{btn_key} button:hover {{
        background-color: rgba(63, 217, 255, 0.15) !important;
        border-color: #3fd9ff !important;
    }}
    div.st-key-btn_dev_{btn_key} button p {{ color: #3fd9ff !important; font-weight:600 !important; }}
    """
    if dev == "cpu":
        css += "div.st-key-btn_dev_gpu button { border-left: 1px solid rgba(63, 217, 255, 0.4) !important; }"
        
    active_model = st.session_state.get("pan_model", "small")
    css += f"""
    div.st-key-pan_model_row_{active_model} {{
        background-color: rgba(63, 217, 255, 0.04) !important;
        border-color: rgba(63, 217, 255, 0.18) !important;
        border-left: 3px solid #3fd9ff !important;
    }}
    """
    return f"<style>{css}</style>"


# ── Callbacks & Persistence ─────────────────────────────────────────────────

def _collect() -> dict:
    """Build a settings dict from current session_state widget values."""
    out = dict(PANOPTO_DEFAULTS)
    for wkey, skey in _KEYMAP.items():
        if wkey in st.session_state:
            out[skey] = st.session_state[wkey]
    return out

def _persist() -> None:
    """on_change callback: persist current widget values to disk."""
    s = _collect()
    save_settings(s)
    st.session_state["panopto_enabled"] = bool(s.get("enabled"))

def _seed_state() -> None:
    if st.session_state.get("_pan_loaded"):
        return
    s = load_settings()
    for wkey, skey in _KEYMAP.items():
        st.session_state.setdefault(wkey, s.get(skey, PANOPTO_DEFAULTS[skey]))
    st.session_state["panopto_enabled"] = bool(s.get("enabled"))
    st.session_state["_pan_loaded"] = True

def _toggle_card(skey: str) -> None:
    st.session_state[skey] = not st.session_state.get(skey, False)
    _persist()

def _set_radio_card(skey: str, val: str) -> None:
    st.session_state[skey] = val
    _persist()


# ── Render ──────────────────────────────────────────────────────────────────

def _render_model_manager() -> bool:
    any_downloading = False

    st.markdown(
        "<div style='font-weight:700;color:#e2e8f0;font-size:1.05rem;margin-bottom:2px;'>Available Models</div>"
        "<div style='color:#94a3b8;font-size:0.85rem;margin-bottom:12px;'>"
        "Download a model to enable transcription. Bigger models are more accurate but slower.</div>", 
        unsafe_allow_html=True
    )
                
    with st.container(key="pan_models_table"):
        # Header
        with st.container(key="pan_models_header"):
            hc1, hc2, hc3, hc4 = st.columns([0.42, 0.13, 0.25, 0.20])
            hc1.markdown("<div style='color:#64748b;font-size:0.75rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;padding-left:4px;'>Model</div>", unsafe_allow_html=True)
            hc2.markdown("<div style='color:#64748b;font-size:0.75rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;'>Size</div>", unsafe_allow_html=True)
            hc3.markdown("<div style='color:#64748b;font-size:0.75rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;'>Speed / Accuracy</div>", unsafe_allow_html=True)
        
        for i, m in enumerate(pmodels.MODEL_REGISTRY):
            mid = m["id"]
            installed = pmodels.is_installed(mid)
            dl_state = pmodels.get_download_state(mid)
            downloading = bool(dl_state and dl_state.get("status") == "downloading")
            if downloading: any_downloading = True
            
            with st.container(key=f"pan_model_row_{mid}"):
                c1, c2, c3, c4 = st.columns([0.42, 0.13, 0.25, 0.20], vertical_alignment="center")
                
                is_active = (st.session_state.get("pan_model") == mid)
                active_color = "%233fd9ff" if is_active else "%2394a3b8"
                icon_svg = f"data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='{active_color}' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z'/%3E%3C/svg%3E"
                rec = '<span style="background:rgba(63,217,255,0.15);color:#3fd9ff;padding:2px 6px;border-radius:4px;font-size:0.7rem;margin-left:8px;font-weight:600;">Recommended</span>' if m.get("recommended") else ""
                
                active_bg = "rgba(63,217,255,0.08)" if is_active else "rgba(255,255,255,0.03)"
                
                c1.markdown(
                    f'<div style="display:flex;align-items:center;gap:14px;padding-left:4px;">'
                    f'<div style="background:{active_bg};padding:8px;border-radius:8px;display:flex;"><img src="{icon_svg}" width="20"></div>'
                    f'<div><div style="font-weight:600;color:#e2e8f0;font-size:0.92rem;">{m["label"]}{rec}</div>'
                    f'<div style="color:#94a3b8;font-size:0.78rem;margin-top:2px;">{m["note"]}</div></div>'
                    f'</div>', unsafe_allow_html=True
                )
                
                size_mb = m["size_mb"]
                size_str = f"{size_mb/1024:.1f} GB" if size_mb >= 1024 else f"{size_mb} MB"
                c2.markdown(f"<div style='color:#cbd5e1;font-size:0.83rem;'>{size_str}</div>", unsafe_allow_html=True)
                
                if size_mb <= 75: speed = "Fastest"; bars = 1
                elif size_mb <= 150: speed = "Fast"; bars = 2
                elif size_mb <= 500: speed = "Balanced"; bars = 3
                elif size_mb <= 1500: speed = "Slower"; bars = 4
                else: speed = "Slow"; bars = 5
                
                bar_html = ""
                for b in range(1, 6):
                    color = "#3fd9ff" if b <= bars else "rgba(255,255,255,0.1)"
                    bar_html += f"<div style='width:12px;height:4px;border-radius:2px;background:{color};display:inline-block;margin-right:4px;'></div>"
                c3.markdown(f"<div style='display:flex;align-items:center;gap:12px;'><span style='color:#cbd5e1;font-size:0.83rem;width:55px;'>{speed}</span><div style='display:flex;'>{bar_html}</div></div>", unsafe_allow_html=True)
                
                with c4:
                    if downloading:
                        total = max(1, int(dl_state.get("total_bytes") or 1))
                        done = int(dl_state.get("downloaded_bytes") or 0)
                        pct = min(99, int(done / total * 100))
                        st.progress(pct / 100.0, text=f"{pct}%")
                        if st.button("Cancel", key=f"pan_model_cancel_{mid}", use_container_width=True):
                            pmodels.request_cancel(mid)
                            st.rerun()
                    elif installed:
                        ac1, ac2 = st.columns([0.76, 0.24], gap="small")
                        with ac1:
                            if is_active:
                                st.button("Active", key=f"pan_model_act_{mid}", disabled=True, use_container_width=True)
                            else:
                                if st.button("Activate", key=f"pan_model_act_{mid}", use_container_width=True):
                                    _set_radio_card("pan_model", mid)
                                    st.rerun()
                        with ac2:
                            if st.button("", key=f"pan_model_del_{mid}", help="Remove model", use_container_width=True):
                                pmodels.delete_model(mid)
                                pmodels.clear_download_state(mid)
                                st.rerun()
                    else:
                        disabled = not pmodels.hf_available()
                        if st.button("Download", key=f"pan_model_dl_{mid}", use_container_width=True, type="primary", disabled=disabled):
                            pmodels.start_download(mid)
                            st.rerun()
                            
            if dl_state and dl_state.get("status") in ("error", "cancelled", "done"):
                pmodels.clear_download_state(mid)
                st.rerun()
                
            if i < len(pmodels.MODEL_REGISTRY) - 1:
                pass # CSS margin-bottom handles spacing now instead of hr

    return any_downloading


def render_panopto_page() -> None:
    _seed_state()
    _inject_card_css()
    
    # Constrain width to matches quick download page
    _, main_col, _ = st.columns([0.4, 3.2, 0.4])
    with main_col:
        # Dynamic active states
        active_keys = []
        if st.session_state.get("pan_out_mp3"): active_keys.append("pan_out_mp3")
        if st.session_state.get("pan_out_txt"): active_keys.append("pan_out_txt")
        if st.session_state.get("pan_out_srt"): active_keys.append("pan_out_srt")
        active_keys.append(f"pan_layout_{st.session_state.get('pan_layout', 'match')}")
        st.html(_get_active_css(active_keys))

        st.markdown(
            f'<div style="display:flex;align-items:center;gap:14px;margin:4px 0 18px 0;">'
            f'{_svg(_IC_PLAY_FILLED, color=theme.ACCENT_BLUE, size=32)}'
            f'<div>'
            f'<div style="display:flex;align-items:center;gap:10px;">'
            f'<span style="font-size:1.7rem;font-weight:800;color:{theme.TEXT_PRIMARY};">Panopto Lectures</span>'
            f'<span style="font-size:0.75rem;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;'
            f'color:{theme.ACCENT_BLUE};background:rgba(77,168,218,0.14);padding:3px 8px;border-radius:6px;">Premium</span>'
            f'</div>'
            f'<div style="color:{theme.TEXT_SECONDARY};font-size:0.95rem;margin-top:2px;">'
            f'Download and transcribe your Canvas Panopto lecture recordings locally.</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        # 1. Master enable toggle
        with st.container(border=True, key="pan_master_card"):
            c1, c2 = st.columns([0.88, 0.12], vertical_alignment="center")
            with c1:
                st.markdown(
                    f'<div style="font-weight:700;color:{theme.TEXT_PRIMARY};font-size:1.1rem;">'
                    f'Include Panopto lectures in Download &amp; Sync</div>'
                    f'<div style="color:{theme.TEXT_SECONDARY};font-size:0.88rem;margin-top:3px;">'
                    f'When on, your selected courses automatically fetch their Panopto lectures.</div>',
                    unsafe_allow_html=True,
                )
            with c2:
                st.toggle("Enable", key="pan_enabled", on_change=_persist, label_visibility="collapsed")

        enabled = st.session_state.get("pan_enabled", False)

        # 2. Output Formats
        with st.container(border=True, key="pan_outputs_card"):
            _section_header(_IC_PLAY_FILLED, "Output Formats", "Select what files you want to keep for each lecture.")
            with st.container(key="pan_outputs_row"):
                oc1, oc2, oc3, oc4 = st.columns(4, gap="small")
                with oc1: st.button("Audio", key="btn_pan_out_mp3", on_click=_toggle_card, args=("pan_out_mp3",), use_container_width=True)
                with oc2: st.button("Transcript", key="btn_pan_out_txt", on_click=_toggle_card, args=("pan_out_txt",), use_container_width=True)
                with oc3: st.button("Subtitles", key="btn_pan_out_srt", on_click=_toggle_card, args=("pan_out_srt",), use_container_width=True)
                with oc4: st.button("Video", key="btn_pan_out_mp4", use_container_width=True, disabled=True)

        # 3. Organization & Routing
        with st.container(border=True, key="pan_org_card"):
            _section_header(_IC_GEAR, "Organization & Routing", "How files are saved in your folder.")
            
            st.markdown('<div style="font-size:0.88rem; font-weight:600; color:#e2e8f0; margin-bottom: 8px;">Folder Layout</div>', unsafe_allow_html=True)
            with st.container(key="pan_layout_row"):
                lc1, lc2 = st.columns(2, gap="small")
                with lc1: st.button("Match Course Structure", key="btn_pan_layout_match", on_click=_set_radio_card, args=("pan_layout", "match"), use_container_width=True)
                with lc2: st.button("Separate Panopto Folder", key="btn_pan_layout_separate", on_click=_set_radio_card, args=("pan_layout", "separate"), use_container_width=True)

            # Both layouts keep lectures INSIDE the course folder.
            if st.session_state.get("pan_layout") == "separate":
                _layout_note = ('Lectures are saved in a <b>“Panopto Recordings”</b> folder inside each '
                                'course folder, with one subfolder per lecture.')
            else:
                _layout_note = ('Lectures are saved alongside your course files — in each module’s '
                                'folder, or the course root for flat downloads.')
            st.markdown(
                f'<div style="margin-top:12px; padding:10px 14px; background:rgba(255,255,255,0.03); '
                f'border:1px solid rgba(255,255,255,0.08); border-radius:8px;">'
                f'<div style="color:{theme.TEXT_PRIMARY};font-size:0.88rem;line-height:1.5;">{_layout_note}</div>'
                f'</div>', unsafe_allow_html=True
            )

        # 4. Transcription Engine
        transcription_active = enabled and wants_transcription(_collect())
        dim_class = "" if transcription_active else ' class="pan_dimmed"'
        
        st.markdown(f'<div{dim_class}>', unsafe_allow_html=True)
        with st.container(border=True, key="pan_transcription_card"):
            st.markdown(
                f'<div style="font-weight:700;color:{theme.TEXT_PRIMARY};font-size:1.05rem;">Transcription</div>'
                f'<div style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;margin-top:2px;margin-bottom:12px;">'
                f'Runs locally on your machine — nothing is uploaded.</div>',
                unsafe_allow_html=True,
            )
            
            if not pmodels.whisper_available():
                from ui.amber_notice import render_info_notice
                render_info_notice(
                    "The transcription engine (faster-whisper) isn't installed yet. "
                    "You can still download models and configure settings; transcription runs once the engine is bundled (or after `pip install faster-whisper` in dev).",
                    allow_html=True,
                )
            
            tc1, tc2 = st.columns([0.5, 0.5])
            with tc1:
                st.selectbox("Language", _LANG_CODES, key="pan_language", format_func=lambda c: _LANG_LABEL.get(c, c), on_change=_persist)
                
                if transcription_active:
                    chosen = st.session_state.get("pan_model", "small")
                    if not pmodels.is_installed(chosen):
                        from ui.amber_notice import render_amber_notice
                        m = pmodels.get_model(chosen)
                        render_amber_notice(
                            f"Model “{m['label'] if m else chosen}” isn't installed yet",
                            detail="Audio will still download, but transcription is skipped until you install the model.",
                            margin="0 0 10px 0",
                        )
            
            with tc2:
                st.markdown('<div style="font-size:0.88rem; color:#cbd5e1; margin-bottom: 4px;">Compute Device</div>', unsafe_allow_html=True)
                with st.container(key="pan_device_row"):
                    d1, d2 = st.columns(2, gap="small")
                    with d1: st.button("CPU", key="btn_dev_cpu", on_click=_set_radio_card, args=("pan_device", "cpu"), use_container_width=True)
                    with d2: st.button("GPU", key="btn_dev_gpu", on_click=_set_radio_card, args=("pan_device", "cuda"), use_container_width=True)
            
            st.markdown("<hr style='border:none;border-top:1px solid rgba(255,255,255,0.06);margin:24px 0 16px 0;'>", unsafe_allow_html=True)
            any_downloading = _render_model_manager()
        st.markdown('</div>', unsafe_allow_html=True)

    if 'any_downloading' in locals() and any_downloading:
        time.sleep(0.5)
        st.rerun()
