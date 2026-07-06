"""ui.panopto_page - Panopto transcription-configuration dialog.

The Panopto OUTPUT formats (mp4/mp3/txt/srt) and folder LAYOUT are now configured
per-download in Section 4 of the download settings page (and stored per-folder as
a contract for sync). This module is what remains: a compact ``@st.dialog`` for
the one-time ENGINE setup - language, compute device, GPU enablement, and the
faster-whisper model manager. It is opened from Section 4's "Set up transcription"
button (download_settings hosts it at the main script level via the
``_pan_dialog_open`` flag, so its model-download auto-rerun loop persists).
"""

from __future__ import annotations

import time
import streamlit as st

from panopto import models as pmodels
from panopto import cuda_provision
from panopto.hardware import detect_compute_hardware, device_advisory
from panopto.settings import PANOPTO_DEFAULTS, load_settings, save_settings

# session_state widget key -> settings key.
# Only the ENGINE config is persisted from this dialog now. Output formats and
# folder layout are per-run, configured in the download settings page (Section 4)
# and stored per-folder as a contract - they no longer live here.
_KEYMAP = {
    "pan_model": "model",
    "pan_language": "language",
    "pan_device": "device",
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
# Panopto purple identity (selection / active accents in this dialog).
PAN_PURPLE = "#b89dfe"
PAN_PURPLE_DARK = "#7037da"
PAN_PURPLE_URL = "%23b89dfe"
PAN_PURPLE_RGB = "176,157,254"
# Green for the "Active" (selected model) button state.
PAN_GREEN = "#22c55e"
PAN_GREEN_URL = "%2322c55e"
PAN_GREEN_RGB = "34,197,94"

_P_CPU = "%3Cpath d='M7 17h10V7H7v10zm2-8h6v6H9V9zM21 11V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2zm-4 6H7V7h10v10z'/%3E"
_P_GPU_NEW = "%3Cpath d='M2 17h18a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2H2'/%3E%3Cpath d='M2 21V3'/%3E%3Cpath d='M7 17v3a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1v-3'/%3E%3Ccircle cx='16' cy='11' r='2'/%3E%3Ccircle cx='8' cy='11' r='2'/%3E"

SVG_CPU = f"data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='%2394a3b8' xmlns='http://www.w3.org/2000/svg'%3E{_P_CPU}%3C/svg%3E"
SVG_GPU_NEW = f"data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' xmlns='http://www.w3.org/2000/svg'%3E{_P_GPU_NEW}%3C/svg%3E"
SVG_CPU_ACT = f"data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='{PAN_PURPLE_URL}' xmlns='http://www.w3.org/2000/svg'%3E{_P_CPU}%3C/svg%3E"
SVG_GPU_NEW_ACT = f"data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='none' stroke='{PAN_PURPLE_URL}' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' xmlns='http://www.w3.org/2000/svg'%3E{_P_GPU_NEW}%3C/svg%3E"

# Twin model-card meters: speed (lightning) over accuracy (target), 5 segments
# each. Replaces the old single bar + "Fastest/Slow" text.
_IC_SPEED = "data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='%23b89dfe' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M13 2 4 14h6l-1 8 9-12h-6z'/%3E%3C/svg%3E"
_IC_ACCURACY = "data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='none' stroke='%23b89dfe' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='m6 16 6-12 6 12'/%3E%3Cpath d='M8 12h8'/%3E%3Cpath d='m16 20 2 2 4-4'/%3E%3C/svg%3E"


def _twin_bars(speed: int, accuracy: int) -> str:
    """Two stacked 5-segment meters (speed icon row over accuracy icon row)."""
    def _row(icon: str, n: int) -> str:
        segs = "".join(
            "<span style='width:15px;height:5px;border-radius:2.5px;display:inline-block;"
            f"background:{PAN_PURPLE if b <= n else 'rgba(255,255,255,0.12)'};'></span>"
            for b in range(1, 6)
        )
        return (
            "<div style='display:flex;align-items:center;gap:9px;'>"
            f"<img src=\"{icon}\" width='15' height='15' style='opacity:0.9;flex-shrink:0;'/>"
            f"<span style='display:inline-flex;gap:4px;'>{segs}</span></div>"
        )
    return (
        "<div style='display:flex;flex-direction:column;gap:7px;'>"
        f"{_row(_IC_SPEED, int(speed))}{_row(_IC_ACCURACY, int(accuracy))}</div>"
    )


# ── CSS Injection (dialog-scoped) ───────────────────────────────────────────

def _inject_dialog_css() -> None:
    """Inject the transcription dialog's CSS. All selectors are scoped under
    ``div[data-testid="stDialog"]`` (the modal lives in a high-specificity portal,
    so unscoped rules silently fail there)."""
    st.html(f"""<style>
    /* Dropdown popover list border outline */
    div[data-baseweb="popover"] ul[role="listbox"],
    div[data-baseweb="popover"] ul {{
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
        border-radius: 8px !important;
        overflow: hidden !important;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6) !important;
    }}

    /* Compact dialog padding + hide native close (we provide a Done button) */
    div[data-testid="stDialog"] div[role="dialog"] > div:first-child {{
        padding-top: 1.7rem !important;
        padding-bottom: 1.2rem !important;
    }}
    div[data-testid="stDialog"] button[aria-label="Close"] {{ display: none !important; }}

    /* Language & Compute Device Cards */
    div[data-testid="stDialog"] div[class*="st-key-pan_lang_card"],
    div[data-testid="stDialog"] div[class*="st-key-pan_device_card"] {{
        background-color: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 10px !important;
        padding: 14px 14px !important;
        gap: 0 !important;
    }}

    /* Space out content inside cards to prevent overlap */
    div[data-testid="stDialog"] div[class*="st-key-pan_lang_card"] div[data-testid="stSelectbox"] {{
        margin-top: 25px !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_device_card"] div.st-key-pan_device_row {{
        margin-top: 25px !important;
    }}

    /* Language dropdown border and background styling */
    div[data-testid="stDialog"] div[class*="st-key-pan_language"] div[data-baseweb="select"] > div {{
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        border-radius: 6px !important;
        background-color: rgba(0, 0, 0, 0.12) !important;
        transition: border-color 0.2s ease !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_language"] div[data-baseweb="select"] > div:hover,
    div[data-testid="stDialog"] div[class*="st-key-pan_language"] div[data-baseweb="select"] > div:focus-within {{
        border-color: rgba(255, 255, 255, 0.3) !important;
    }}

    /* Device segmented control (CPU / GPU) */
    div[data-testid="stDialog"] div[class*="st-key-btn_dev_"] button {{
        background-color: rgba(255,255,255,0.03) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        min-height: 38px !important;
        color: #ffffff !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        position: relative !important;
        padding: 0 16px !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-btn_dev_"] button [data-testid="stMarkdownContainer"] {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-btn_dev_"] button p {{
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        color: #ffffff !important;
        font-size: 0.88rem !important;
        margin: 0 !important;
        padding-right: 0 !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-btn_dev_"] button p::before {{
        content: "" !important;
        display: inline-block !important;
        width: 15px !important;
        height: 15px !important;
        margin-right: 7px !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
        vertical-align: middle !important;
        flex-shrink: 0 !important;
    }}
    /* Circular radio button outline on the right */
    div[data-testid="stDialog"] div[class*="st-key-btn_dev_"] button::before {{
        content: "" !important;
        position: absolute !important;
        top: 50% !important;
        right: 14px !important;
        transform: translateY(-50%) !important;
        width: 16px !important;
        height: 16px !important;
        border: 2px solid rgba(255, 255, 255, 0.25) !important;
        border-radius: 50% !important;
        background-color: transparent !important;
        background-image: none !important;
        transition: all 0.2s ease !important;
        box-sizing: border-box !important;
        display: block !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-btn_dev_"] button:not([disabled]):hover::before {{
        border-color: {PAN_PURPLE} !important;
    }}
    div[data-testid="stDialog"] div.st-key-btn_dev_cpu button {{ border-radius: 6px !important; }}
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu button {{ border-radius: 6px !important; }}
    div[data-testid="stDialog"] div.st-key-btn_dev_cpu button p::before {{ background-image: url("{SVG_CPU}") !important; }}
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu button p::before {{ background-image: url("{SVG_GPU_NEW}") !important; }}
    div[data-testid="stDialog"] div[class*="st-key-btn_dev_"]:hover button {{ background-color: rgba(255,255,255,0.06) !important; }}
    div[data-testid="stDialog"] div.st-key-btn_dev_cpu button:hover p::before {{ background-image: url("{SVG_CPU_ACT}") !important; }}
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu button:not([disabled]):hover p::before {{ background-image: url("{SVG_GPU_NEW_ACT}") !important; }}
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu button[disabled],
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu button:disabled {{
        opacity: 0.38 !important; cursor: not-allowed !important;
        background-color: rgba(255,255,255,0.02) !important; border-color: rgba(255,255,255,0.08) !important;
    }}
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu button[disabled] p::before,
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu button:disabled p::before {{
        opacity: 0.35 !important;
    }}
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu button[disabled]::before,
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu button:disabled::before {{
        opacity: 0.35 !important;
    }}
    div[data-testid="stDialog"] div.st-key-btn_dev_gpu:hover button[disabled] {{ background-color: rgba(255,255,255,0.02) !important; }}

    /* Advisory slot: always rendered for stable element indexing (keeps the model
       table from remounting on a CPU<->GPU toggle). When it holds no notice,
       collapse it with display:none so it contributes NO flex gap - it stays in
       the DOM/element tree (index unaffected), it's just not laid out. */
    div[data-testid="stDialog"] div.st-key-pan_advisory_slot:not(:has([data-testid="stElementContainer"])) {{
        display: none !important;
    }}

    /* Model table - recessed panel */
    div[data-testid="stDialog"] div[class*="st-key-pan_models_table"] {{
        background-color: rgba(0,0,0,0.12) !important;
        border: 1px solid rgba(255,255,255,0.15) !important;
        border-radius: 12px !important;
        padding: 12px 10px !important;
        margin-top: 0px !important;
    }}
    div[data-testid="stDialog"] div.st-key-pan_models_table,
    div[data-testid="stDialog"] div.st-key-pan_models_table > div > [data-testid="stVerticalBlock"] {{
        gap: 10px !important;
    }}
    div[data-testid="stDialog"] div.st-key-pan_models_header [data-testid="stHorizontalBlock"] {{
        border-bottom: 1px solid rgba(255,255,255,0.08) !important;
        padding-bottom: 5px !important; margin-bottom: 2px !important;
    }}
    div[data-testid="stDialog"] .pan-th {{ color:#64748b; font-size:0.7rem; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; }}

    /* Model rows */
    div[data-testid="stDialog"] div[class*="st-key-pan_model_row_"] {{
        background-color: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 8px !important;
        padding: 4px 12px 4px 12px !important;
        margin-bottom: 0px !important;
        transition: all 0.2s ease !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_row_"]:hover {{
        background-color: rgba(255,255,255,0.07) !important; 
        border-color: rgba(255,255,255,0.12) !important;
        border-left: 3px solid rgba(255,255,255,0.12) !important;
        padding-left: 9px !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_row_"] [data-testid="stColumn"] {{
        display: flex !important; flex-direction: column !important; justify-content: center !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_row_"] p {{ margin: 0 !important; padding: 0 !important; }}

    /* Compact action buttons (tight, not full-bleed) */
    div[data-testid="stDialog"] div[class*="st-key-pan_model_"] button {{
        height: 26px !important; min-height: 26px !important;
        border-radius: 6px !important; font-size: 0.8rem !important; padding: 0 6px !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_act_"] button:not([disabled]) {{
        background-color: rgba(255,255,255,0.03) !important; border: 1px solid rgba(255,255,255,0.08) !important; color: #cbd5e1 !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_act_"] button:not([disabled]):hover {{
        background-color: rgba({PAN_PURPLE_RGB},0.12) !important; border-color: {PAN_PURPLE} !important; color: #ffffff !important;
    }}
    /* Download button - purple, compact, with download glyph */
    div[data-testid="stDialog"] div[class*="st-key-pan_model_dl_"] button {{
        background-color: {PAN_PURPLE_DARK} !important; border: none !important; color: #ffffff !important; font-weight: 600 !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_dl_"] button:hover {{ background-color: #8a4eef !important; }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_dl_"] button[disabled] {{ opacity: 0.45 !important; cursor: not-allowed !important; }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_dl_"] button p::before {{
        content: "" !important; display: inline-block !important; width: 13px !important; height: 13px !important; margin-right: 5px !important;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'%3E%3Cpath d='M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM17 13l-5 5-5-5h3V9h4v4h3z'/%3E%3C/svg%3E") !important;
        background-size: contain !important; background-repeat: no-repeat !important; background-position: center !important; vertical-align: middle !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_dl_"] button p {{ display: inline-flex !important; align-items: center !important; justify-content: center !important; }}
    /* Delete button - icon only */
    div[data-testid="stDialog"] div[class*="st-key-pan_model_del_"] button {{
        background-color: rgba(244,63,94,0.04) !important; border: 1px solid rgba(244,63,94,0.15) !important;
        border-radius: 6px !important; position: relative !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_del_"] button:hover {{ background-color: rgba(244,63,94,0.12) !important; border-color: rgba(244,63,94,0.3) !important; }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_del_"] button::after {{
        content: "" !important; position: absolute !important; top: 50% !important; left: 50% !important; transform: translate(-50%,-50%) !important;
        width: 15px !important; height: 15px !important; background-color: #f43f5e !important;
        -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='currentColor'%3E%3Cpath d='M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z'/%3E%3C/svg%3E") !important;
        -webkit-mask-repeat: no-repeat !important; -webkit-mask-position: center !important; -webkit-mask-size: contain !important;
        transition: background-color 0.2s ease !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_del_"] button:hover::after {{ background-color: #ff4d6d !important; }}

    /* Done button - purple primary */
    div[data-testid="stDialog"] div.st-key-pan_dialog_done button {{
        background-color: {PAN_PURPLE_DARK} !important; border: 1px solid {PAN_PURPLE_DARK} !important;
        color: #ffffff !important; font-weight: 600 !important;
    }}
    div[data-testid="stDialog"] div.st-key-pan_dialog_done button:hover {{ background-color: #5b29b0 !important; border-color: #5b29b0 !important; }}

    /* Cancel buttons (model download + CUDA provision) - app-style X icon, keep compact height */
    div[data-testid="stDialog"] div[class*="st-key-pan_model_cancel_"] button,
    div[data-testid="stDialog"] div.st-key-pan_cuda_cancel button {{
        background-color: rgba(255,255,255,0.07) !important;
        background-image: none !important;
        border: 1px solid rgba(255,255,255,0.3) !important;
        color: #ffffff !important;
        font-weight: 500 !important;
        gap: 6px !important;
        transition: all 0.15s ease !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_cancel_"] button::before,
    div[data-testid="stDialog"] div.st-key-pan_cuda_cancel button::before {{
        content: '' !important;
        display: block !important;
        width: 13px !important; height: 13px !important; min-width: 13px !important;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M18 6 6 18'/%3E%3Cpath d='m6 6 12 12'/%3E%3C/svg%3E") !important;
        background-size: contain !important; background-repeat: no-repeat !important; background-position: center !important;
        flex-shrink: 0 !important; transition: background-image 0.15s ease !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_cancel_"] button:hover,
    div[data-testid="stDialog"] div.st-key-pan_cuda_cancel button:hover {{
        background-color: rgba(255,75,75,0.1) !important;
        background-image: none !important;
        border-color: #ff4b4b !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_model_cancel_"] button:hover::before,
    div[data-testid="stDialog"] div.st-key-pan_cuda_cancel button:hover::before {{
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ff4b4b' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M18 6 6 18'/%3E%3Cpath d='m6 6 12 12'/%3E%3C/svg%3E") !important;
    }}

    /* Progress bar - light purple fill + bold % text */
    div[data-testid="stDialog"] [data-testid="stProgressBar"] div[style*="width"],
    div[data-testid="stDialog"] [data-testid="stProgress"] div[style*="width"] {{
        background-color: {PAN_PURPLE} !important;
        background-image: none !important;
    }}
    div[data-testid="stDialog"] [data-testid="stProgress"] p,
    div[data-testid="stDialog"] [data-testid="stProgress"] small {{
        font-weight: 700 !important;
    }}

    /* CUDA provisioning card container styling */
    div[class*="st-key-pan_cuda_card"] {{
        border: 1px solid rgba(176,157,254,0.25) !important;
        border-radius: 8px !important;
        background: rgba(176,157,254,0.06) !important;
        margin-top: 12px !important;
        padding: 12px 14px 12px 14px !important;
    }}
    div[class*="st-key-pan_cuda_card"] div[data-testid="stVerticalBlock"] {{
        padding-bottom: 0 !important;
        gap: 0 !important;
    }}
    div[class*="st-key-pan_cuda_card"] div[data-testid="stElementContainer"]:last-child {{
        margin-bottom: 0 !important;
    }}

    /* CUDA enable button style matching reference */
    div.st-key-pan_cuda_enable {{
        margin-top: 10px !important;
        margin-bottom: 2px !important;
    }}
    div.st-key-pan_cuda_enable button {{
        background: rgba(176,157,254,0.10) !important;
        border: 1px solid rgba(176,157,254,0.35) !important;
        color: #d8caff !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        border-radius: 8px !important;
        height: 32px !important;
        min-height: 32px !important;
        padding: 0 14px !important;
        transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: auto !important;
    }}
    div.st-key-pan_cuda_enable button [data-testid="stMarkdownContainer"] {{
        display: flex !important;
        align-items: center !important;
    }}
    div.st-key-pan_cuda_enable button p {{
        display: inline-flex !important;
        align-items: center !important;
        gap: 6px !important;
        margin: 0 !important;
    }}
    div.st-key-pan_cuda_enable button p::before {{
        content: "" !important;
        display: inline-block !important;
        width: 14px !important;
        height: 14px !important;
        flex-shrink: 0 !important;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23d8caff' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 15V3'/%3E%3Cpath d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/%3E%3Cpath d='m7 10 5 5 5-5'/%3E%3C/svg%3E") !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
    }}
    div.st-key-pan_cuda_enable button:hover {{
        background-color: rgba(176,157,254,0.18) !important;
        border-color: #b89dfe !important;
        color: #ffffff !important;
    }}
    div.st-key-pan_cuda_enable button:hover p::before {{
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 15V3'/%3E%3Cpath d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/%3E%3Cpath d='m7 10 5 5 5-5'/%3E%3C/svg%3E") !important;
    }}

    /* Cancel button (CUDA provision) - smaller and left-aligned */
    div.st-key-pan_cuda_cancel {{
        margin-top: 6px !important;
    }}
    div.st-key-pan_cuda_cancel button {{
        height: 30px !important;
        min-height: 30px !important;
        border-radius: 6px !important;
        font-size: 0.85rem !important;
        padding: 0 14px !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: auto !important;
    }}

    /* "Back to Settings" affordance (only present when opened from the Settings
       modal). Pull it up into the dialog's reserved invisible-title slot so it
       hugs the top edge, and shrink it to content height so it doesn't push the
       title down. Selectors are inert when the button isn't rendered. */
    div[data-testid="stDialog"] div.st-key-pan_back_to_settings {{
        margin-top: -62px !important;
        margin-bottom: 0 !important;
    }}
    div[data-testid="stDialog"] div.st-key-pan_back_to_settings button {{
        height: auto !important;
        min-height: 0 !important;
        padding: 2px 6px !important;
        color: #94a3b8 !important;
        font-size: 0.82rem !important;
        font-weight: 600 !important;
    }}
    div[data-testid="stDialog"] div.st-key-pan_back_to_settings button:hover {{
        color: #e2e8f0 !important;
    }}
    </style>""")


def _active_css() -> str:
    """Dynamic active-state CSS for the device toggle + selected model row."""
    dev = st.session_state.get("pan_device", "cpu")
    btn_key = "gpu" if dev == "cuda" else "cpu"
    active_svg = SVG_CPU_ACT if dev == "cpu" else SVG_GPU_NEW_ACT
    active_model = st.session_state.get("pan_model", "small")
    active_radio_svg = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%23b89dfe' stroke-width='3'/%3E%3Ccircle cx='12' cy='12' r='5' fill='%23b89dfe'/%3E%3C/svg%3E"

    model_active_css = ""
    if pmodels.is_installed(active_model):
        model_active_css = f"""
    div[data-testid="stDialog"] div.st-key-pan_model_row_{active_model} {{
        background-color: rgba({PAN_PURPLE_RGB},0.06) !important;
        border-color: rgba({PAN_PURPLE_RGB},0.25) !important;
        border-left: 3px solid {PAN_PURPLE} !important;
        padding-left: 9px !important;
    }}
    div[data-testid="stDialog"] div.st-key-pan_model_row_{active_model}:hover {{
        background-color: rgba({PAN_PURPLE_RGB},0.10) !important;
        border-color: rgba({PAN_PURPLE_RGB},0.40) !important;
        border-left: 3px solid {PAN_PURPLE} !important;
        padding-left: 9px !important;
    }}
        """

    return f"""<style>
    div[data-testid="stDialog"] div.st-key-btn_dev_{btn_key} button {{
        background-color: rgba({PAN_PURPLE_RGB},0.15) !important;
        border-color: {PAN_PURPLE} !important;
        z-index: 1 !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important;
    }}
    div[data-testid="stDialog"] div.st-key-btn_dev_{btn_key} button:hover {{
        background-color: rgba({PAN_PURPLE_RGB},0.15) !important; border-color: {PAN_PURPLE} !important;
    }}
    div[data-testid="stDialog"] div.st-key-btn_dev_{btn_key} button p {{
        font-weight: 600 !important;
        color: #ffffff !important;
    }}
    div[data-testid="stDialog"] div.st-key-btn_dev_{btn_key} button p::before {{
        background-image: url("{active_svg}") !important;
    }}
    div[data-testid="stDialog"] div.st-key-btn_dev_{btn_key} button::before {{
        border: none !important;
        background-color: transparent !important;
        background-image: url("{active_radio_svg}") !important;
    }}
    {model_active_css}
    </style>"""


# ── Callbacks & Persistence ─────────────────────────────────────────────────

def _collect() -> dict:
    """Build a settings dict from current engine widget values, merged OVER the
    persisted config so any stored output/layout/enabled keys are preserved."""
    out = load_settings()
    for wkey, skey in _KEYMAP.items():
        if wkey in st.session_state:
            out[skey] = st.session_state[wkey]
    return out


def _persist() -> None:
    """on_change callback: persist current engine widget values to disk."""
    save_settings(_collect())


def _seed_state(force: bool = False) -> None:
    """Seed the engine widget keys (model/language/device) from the persisted
    config. Re-seeded each time the dialog opens so it always reflects disk."""
    if st.session_state.get("_pan_loaded") and not force:
        return

    from panopto.settings import _read_full_config, SETTINGS_KEY
    stored = _read_full_config().get(SETTINGS_KEY, {})

    hw = detect_compute_hardware()
    gpu_available = bool(hw.get("gpu_available"))
    dynamic_defaults = {
        "model": "turbo" if gpu_available else "small",
        "device": "cuda" if gpu_available else "cpu",
        "language": "auto",
    }

    for wkey, skey in _KEYMAP.items():
        val = stored.get(skey, dynamic_defaults.get(skey, PANOPTO_DEFAULTS[skey]))
        st.session_state.setdefault(wkey, val)
    st.session_state["_pan_loaded"] = True


def _set_radio_card(skey: str, val: str) -> None:
    st.session_state[skey] = val
    _persist()


# ── Render ──────────────────────────────────────────────────────────────────

def _render_model_manager() -> bool:
    """Compact model table. Returns True while any model is downloading."""
    any_downloading = False

    hw = detect_compute_hardware()
    gpu_ok = bool(hw.get("gpu_available"))
    recommended_id = "turbo" if gpu_ok else "small"

    st.markdown(
        "<div style='font-weight:700;color:#e2e8f0;font-size:1.0rem;margin-bottom:1px;margin-top:15px;'>Available Models</div>"
        "<div style='color:#94a3b8;font-size:0.82rem;margin-bottom:2px;'>"
        "Download a model to enable transcription - bigger is more accurate but slower.</div>",
        unsafe_allow_html=True
    )

    with st.container(key="pan_models_table"):
        with st.container(key="pan_models_header"):
            hc1, hc2, hc3, hc4 = st.columns([0.46, 0.12, 0.22, 0.20])
            hc1.html("<div class='pan-th' style='padding-left:12px;'>Model</div>")
            hc2.html("<div class='pan-th'>Size</div>")
            hc3.html("<div class='pan-th'>Speed &amp; Accuracy</div>")
            hc4.html("<div class='pan-th'></div>")

        for i, m in enumerate(pmodels.MODEL_REGISTRY):
            mid = m["id"]
            installed = pmodels.is_installed(mid)
            dl_state = pmodels.get_download_state(mid)
            downloading = bool(dl_state and dl_state.get("status") == "downloading")
            if downloading:
                any_downloading = True

            with st.container(key=f"pan_model_row_{mid}"):
                c1, c2, c3, c4 = st.columns([0.46, 0.12, 0.22, 0.20], vertical_alignment="center")

                is_active = (st.session_state.get("pan_model") == mid and installed)
                icon_color = PAN_PURPLE_URL if is_active else "%2394a3b8"
                icon_svg = (
                    f"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='{icon_color}' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E"
                    f"%3Cpath d='M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z'/%3E"
                    f"%3Cpath d='M12 22V12'/%3E%3Cpolyline points='3.29 7 12 12 20.71 7'/%3E%3Cpath d='m7.5 4.27 9 5.15'/%3E%3C/svg%3E"
                )
                is_recommended = (mid == recommended_id)
                rec = (
                    f'<span style="background:rgba({PAN_PURPLE_RGB},0.15);color:{PAN_PURPLE};padding:1px 6px;'
                    'border-radius:4px;font-size:0.68rem;margin-left:7px;font-weight:600;">Recommended</span>'
                    if is_recommended else ""
                )
                active_bg = f"rgba({PAN_PURPLE_RGB},0.12)" if is_active else "rgba(255,255,255,0.03)"

                # m[*], rec, icon_svg, active_bg are all app-built from the static
                # MODEL_REGISTRY + trusted constants (no external/user data).
                c1.html(
                    f'<div style="display:flex;align-items:center;gap:12px;padding-left:0px;">'
                    f'<div style="background:{active_bg};padding:7px;border-radius:8px;display:flex;"><img src="{icon_svg}" width="18"></div>'
                    # audit-ignore
                    f'<div><div style="font-weight:600;color:#e2e8f0;font-size:0.9rem;">{m["label"]}{rec}</div>'
                    f'<div style="color:#94a3b8;font-size:0.76rem;margin-top:1px;">{m["note"]}</div></div>'
                    f'</div>'
                )

                size_mb = m["size_mb"]
                size_str = f"{size_mb/1024:.1f} GB" if size_mb >= 1024 else f"{size_mb} MB"
                # size_str is an app-built number string.
                # audit-ignore
                c2.html(f"<div style='color:#cbd5e1;font-size:0.82rem;'>{size_str}</div>")

                c3.html(_twin_bars(m.get("speed", 3), m.get("accuracy", 3)))

                with c4:
                    if downloading:
                        total = max(1, int(dl_state.get("total_bytes") or 1))
                        done = int(dl_state.get("downloaded_bytes") or 0)
                        pct = min(99, int(done / total * 100))
                        st.progress(pct / 100.0, text=f"{pct}%")
                        if st.button("Cancel", key=f"pan_model_cancel_{mid}", use_container_width=True):
                            pmodels.request_cancel(mid)
                            st.rerun(scope="fragment")
                    elif installed:
                        ac1, ac2 = st.columns([0.72, 0.28], gap="small")
                        with ac1:
                            if is_active:
                                st.html(
                                    f"<div style='display:flex;align-items:center;justify-content:center;"
                                    f"height:26px;border-radius:6px;background:rgba({PAN_GREEN_RGB},0.15);"
                                    f"border:1px solid {PAN_GREEN};color:{PAN_GREEN};font-size:0.8rem;"
                                    f"font-weight:600;gap:5px;box-sizing:border-box;cursor:default;'>"
                                    f"<img src=\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
                                    f"viewBox='0 0 24 24' fill='none' stroke='{PAN_GREEN_URL}' stroke-width='3' "
                                    f"stroke-linecap='round' stroke-linejoin='round'%3E"
                                    f"%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E\" "
                                    f"width='11' height='11' style='flex-shrink:0;'> Active</div>"
                                )
                            elif st.button("Activate", key=f"pan_model_act_{mid}", use_container_width=True):
                                _set_radio_card("pan_model", mid)
                                st.rerun(scope="fragment")
                        with ac2:
                            if st.button("", key=f"pan_model_del_{mid}", help="Remove model", use_container_width=True):
                                pmodels.delete_model(mid)
                                pmodels.clear_download_state(mid)
                                if st.session_state.get("pan_model") == mid:
                                    st.session_state["pan_model"] = PANOPTO_DEFAULTS["model"]
                                    _persist()
                                st.rerun(scope="fragment")
                    else:
                        disabled = not pmodels.hf_available()
                        if st.button("Download", key=f"pan_model_dl_{mid}", use_container_width=True,
                                     type="primary", disabled=disabled):
                            pmodels.start_download(mid)
                            st.rerun(scope="fragment")

            _dl_status = (dl_state or {}).get("status")
            if _dl_status == "error":
                # Surface WHY the download failed instead of silently reverting to
                # the Download button (the old behaviour cleared the state and
                # reran, so the reason never showed). Clear the module state so it
                # doesn't resurface on reopen; the local dl_state still carries the
                # message for this render, and the Download button lets them retry.
                from ui.amber_notice import render_amber_notice
                from html import escape as _esc
                _dl_err = dl_state.get("error") or "Unknown error."
                render_amber_notice(
                    f"Couldn't download the {_esc(m['label'])} model: {_esc(_dl_err)}",
                    detail="Check your internet connection and try again.",
                    margin="2px 0 6px 0",
                )
                pmodels.clear_download_state(mid)
            elif _dl_status in ("cancelled", "done"):
                pmodels.clear_download_state(mid)
                st.rerun(scope="fragment")

    return any_downloading


def _render_compute_hardware_status(hw: dict) -> None:
    """Render the detected GPU + CPU status block under the device toggle."""
    from html import escape as _esc

    def _dot(color: str) -> str:
        return (f"<span style='width:8px;height:8px;border-radius:50%;background:{color};"
                f"display:inline-block;flex-shrink:0;'></span>")

    def _row(dot_color: str, label: str, text: str) -> str:
        return (
            "<div style='display:flex;align-items:center;gap:8px;line-height:1.5;'>"
            f"{_dot(dot_color)}"
            f"<span style='color:#64748b;font-size:0.72rem;font-weight:700;"
            f"text-transform:uppercase;letter-spacing:0.04em;width:34px;flex-shrink:0;'>{label}</span>"
            f"<span style='color:#cbd5e1;font-size:0.84rem;'>{text}</span></div>"
        )

    status = hw.get("status")
    gpu_name = _esc(hw.get("gpu_name") or "")
    vram = hw.get("gpu_vram_mb")
    vram_str = f" · {vram / 1024:.0f} GB" if vram else ""

    if status == "gpu_ready":
        fp16 = "" if hw.get("cuda_has_fp16") else " · INT8 (older card)"
        gpu_row = _row("#10b981", "GPU", f"<b>{gpu_name}</b>{vram_str} · Ready (CUDA){fp16}")
    elif status == "gpu_unusable":
        gpu_row = _row("#f59e0b", "GPU",
                       f"<b>{gpu_name}</b>{vram_str} · found, but its CUDA libraries "
                       "(cuBLAS/cuDNN) aren't installed - using CPU")
    elif status == "cpu_only_mac":
        _chip = "Apple Silicon" if hw.get("is_arm_mac") else "macOS"
        gpu_row = _row("#8A91A6", "GPU", f"{_chip} - no GPU mode (the engine runs on the CPU)")
    elif status == "engine_missing":
        gpu_row = _row("#f87171", "GPU", "Transcription engine unavailable - see Available Models below")
    else:  # cpu_only
        gpu_row = _row("#8A91A6", "GPU", "No compatible NVIDIA GPU found")

    cores = hw.get("cpu_cores") or 0
    cpu_name = _esc((hw.get("cpu_name") or "").strip())
    if len(cpu_name) > 52:
        cpu_name = cpu_name[:52].rstrip() + "…"
    cpu_txt = (f"{cores}-core CPU" if cores else "CPU")
    if cpu_name:
        cpu_txt += f" · {cpu_name}"
    cpu_row = _row("#38bdf8", "CPU", cpu_txt)

    st.markdown(
        "<div style='margin-top:-6px;padding:10px 14px;background:rgba(255,255,255,0.04);"
        "border:1px solid rgba(255,255,255,0.1);border-radius:10px;display:flex;"
        "flex-direction:column;gap:5px;'>"
        "<div style='font-size:0.95rem;color:#e2e8f0;font-weight:700;margin-bottom:2px;'>Detected Hardware</div>"
        # gpu_row/cpu_row are app-built HTML; only external data (gpu/cpu name)
        # is esc()'d inside _row(), so this is safe.
        # audit-ignore
        f"{gpu_row}{cpu_row}</div>",
        unsafe_allow_html=True,
    )


def _render_gpu_enablement(hw: dict) -> bool:
    """Render the GPU fix UI under the device toggle. Returns True while a CUDA
    library download is actively running (so the dialog can auto-rerun).

    Handles the full range of GPU issues:
      * 'provision' -> NVIDIA GPU + driver present, compute libs missing: offer a
        one-click ~1.3 GB download of cuBLAS/cuDNN (the app fixes it).
      * 'driver'    -> NVIDIA GPU present but no usable CUDA driver: guide only
        (a driver install needs admin + reboot; we can't do it for them).
      * 'engine'    -> the transcription engine itself is broken/missing.
    """
    from html import escape as esc

    state = cuda_provision.get_state()
    status = state.get("status") if state else None

    # ── Active download ──
    if status in ("Finding", "downloading", "extracting"):
        total = state.get("total_bytes") or 0
        done = state.get("downloaded_bytes") or 0
        pct = int(done / total * 100) if total else 0
        phase = esc(state.get("phase") or "Working…")
        size = f" · {done / 1e6:.0f} / {total / 1e6:.0f} MB" if total else ""
        st.markdown(
            f"<div style='margin-top:12px;font-size:0.85rem;color:#cbd5e1;'>"
            # phase is esc()'d above; size is app-built float text.
            # audit-ignore
            f"{phase}{size}</div>", unsafe_allow_html=True)
        st.progress(min(99, pct) / 100.0, text=f"{pct}%")
        if st.button("Cancel", key="pan_cuda_cancel", use_container_width=False):
            cuda_provision.request_cancel()
            st.rerun(scope="fragment")
        return True

    # ── Just finished ──
    if status == "done":
        cuda_provision.clear_state()
        detect_compute_hardware(force=True)
        st.session_state["pan_device"] = "cuda"   # they opted in - select it
        _persist()
        st.rerun(scope="fragment")
        return False

    if status == "error":
        from ui.amber_notice import render_amber_notice
        render_amber_notice(
            f"GPU setup couldn't finish: {esc(state.get('error') or 'unknown error')}",
            detail="You can retry, or just keep using the CPU.",
            margin="10px 0 0 0",
        )
        cuda_provision.clear_state()
        # fall through so the Enable button shows again for a retry

    fix = hw.get("gpu_fix")

    if fix == "provision":
        with st.container(key="pan_cuda_card"):
            st.markdown(
                "<div style='color:#e2e8f0;font-size:0.88rem;font-weight:600;margin-bottom:3px;'>"
                "Enable GPU acceleration</div>"
                "<div style='color:#94a3b8;font-size:0.82rem;line-height:1.5;'>"
                "Your GPU is ready but needs NVIDIA's CUDA libraries (cuBLAS + cuDNN). "
                "The app can download and install them just for transcription - about "
                "<b>1.3&nbsp;GB</b>, one time, no further actions needed.</div>",
                unsafe_allow_html=True,
            )
            if st.button("Download CUDA libraries & enable GPU", key="pan_cuda_enable",
                         use_container_width=False):
                cuda_provision.start_provision()
                st.rerun(scope="fragment")

    elif fix == "driver":
        from ui.amber_notice import render_info_notice
        render_info_notice(
            "Your NVIDIA GPU was found, but its CUDA driver isn't available. "
            "Update to the latest NVIDIA driver (GeForce Experience or nvidia.com/drivers), "
            "then reopen this dialog - the app will offer to finish GPU setup.",
            margin="10px 0 0 0",
        )

    return False


def _close_transcription_dialog() -> None:
    """Clear the open flag so the main-level dialog host stops re-rendering it.

    Used both as the Done-button action and as the @st.dialog on_dismiss callback
    (native Escape / click-outside), so dismissing never leaves a stuck flag that
    would re-open the modal on the next rerun.
    """
    st.session_state["_pan_dialog_open"] = False
    # If this dialog was opened from the global Settings dialog, hand control back
    # to it (Settings can't open a nested dialog, so it closed first; reuse the
    # sidebar's existing reopen hook to bring it back once we're done here).
    if st.session_state.pop("_pan_return_to_settings", False):
        st.session_state["_stg_reopen_dialog"] = True


@st.dialog("\u200b", width="large",
           on_dismiss=_close_transcription_dialog)
def render_transcription_dialog() -> None:
    """Compact engine-setup dialog: language, compute device, GPU enablement, and
    the faster-whisper model manager. Output formats / layout live in Section 4 of
    the download settings, not here."""
    _seed_state(force=True)
    _inject_dialog_css()

    # Snap a stale/invalid 'cuda' selection back to CPU BEFORE the active-state
    # CSS is computed, so the toggle highlight and the disabled GPU button never
    # disagree for a frame.
    if not detect_compute_hardware().get("gpu_available") and \
            st.session_state.get("pan_device") == "cuda":
        st.session_state["pan_device"] = "cpu"
        _persist()

    st.html(_active_css())

    # When opened from the global Settings dialog this modal acts as a SUB-PAGE of
    # Settings (Streamlit forbids nested dialogs, so Settings closed first and we
    # return to it on close). All other entry points (download/sync) open this as a
    # leaf dialog with nowhere to go "back" to. Render an explicit back affordance
    # ONLY in the Settings case so the user understands they'll land back in
    # Settings - otherwise dismissing silently reopening Settings is confusing.
    _from_settings = bool(st.session_state.get("_pan_return_to_settings"))
    if _from_settings:
        if st.button("← Back to Settings", key="pan_back_to_settings",
                     type="tertiary"):
            _close_transcription_dialog()
            st.rerun(scope="app")

    # The back button (when present) is pulled up into the dialog's reserved title
    # slot via CSS; the title then follows it in normal flow with only a small
    # upward nudge (just enough to absorb the inter-element gap) so it tucks under
    # the button without overlapping it. With no back button, pull the title all
    # the way up into the reserved slot itself.
    _hdr_mt = "-10px" if _from_settings else "-70px"

    from shared.helpers import get_base64_image
    b64_pan_icon = get_base64_image("assets/pan_icon.png")
    st.html(
        f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 2px; margin-top: {_hdr_mt};">
            <img src="data:image/png;base64,{b64_pan_icon}" style="width: 36px; height: 36px;" />
            <div style="margin: 0; padding: 0; font-size: 1.75rem; font-weight: 600; color: white;">Panopto Recordings: Transcription Configuration</div>
        </div>
        <div style='color:#94a3b8;font-size:0.9rem;margin:0;'>
            Transcription runs locally on your machine - nothing is uploaded.
            Pick a language and compute device, then download a model below.
        </div>
        """
    )

    if not pmodels.whisper_available():
        from ui.amber_notice import render_info_notice
        import sys
        dev_note = " (or after `pip install faster-whisper` in dev)" if not getattr(sys, 'frozen', False) else ""
        render_info_notice(
            "The transcription engine (faster-whisper) isn't installed yet. "
            f"You can still download models and configure settings; transcription runs "
            f"once the engine is bundled{dev_note}.",
            allow_html=True,
        )

    # Transcription hardware (NVIDIA-CUDA only; macOS is always CPU).
    hw = detect_compute_hardware()
    gpu_ok = bool(hw.get("gpu_available"))

    tc1, tc2 = st.columns([0.5, 0.5])
    with tc1:
        with st.container(key="pan_lang_card"):
            st.markdown(
                '<div style="display:flex; align-items:center; gap:8px; margin-bottom:0px;">'
                '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-languages-icon lucide-languages" style="flex-shrink:0;"><path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/></svg>'
                '<span style="font-size:1.0rem; color:#e2e8f0; font-weight:700;">Language</span>'
                '</div>'
                '<div style="color:#94a3b8; font-size:0.82rem; margin-top:4px; margin-bottom:0px; line-height:1.2;">Select the primary language spoken in the video recordings.</div>',
                unsafe_allow_html=True
            )
            st.selectbox("Language", _LANG_CODES, key="pan_language",
                         format_func=lambda c: _LANG_LABEL.get(c, c), on_change=_persist,
                         label_visibility="collapsed")
    with tc2:
        with st.container(key="pan_device_card"):
            st.markdown(
                '<div style="display:flex; align-items:center; gap:8px; margin-bottom:0px;">'
                '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-binary-icon lucide-binary" style="flex-shrink:0;"><rect x="14" y="14" width="4" height="6" rx="2"/><rect x="6" y="4" width="4" height="6" rx="2"/><path d="M6 20h4"/><path d="M14 10h4"/><path d="M6 14h2v6"/><path d="M14 4h2v6"/></svg>'
                '<span style="font-size:1.0rem; color:#e2e8f0; font-weight:700;">Compute Device</span>'
                '</div>'
                '<div style="color:#94a3b8; font-size:0.82rem; margin-top:4px; margin-bottom:0px; line-height:1.2;">Choose CPU or GPU (recommended if available) for processing.</div>',
                unsafe_allow_html=True
            )
            with st.container(key="pan_device_row"):
                d1, d2 = st.columns(2, gap="small")
                with d1:
                    st.button("CPU", key="btn_dev_cpu", on_click=_set_radio_card,
                              args=("pan_device", "cpu"), use_container_width=True)
                # GPU only selectable when CTranslate2 can actually use a CUDA device.
                with d2:
                    st.button("GPU", key="btn_dev_gpu", on_click=_set_radio_card,
                              args=("pan_device", "cuda"), use_container_width=True, disabled=not gpu_ok)

    # Detected-hardware status (GPU + CPU), then GPU remediation (one-click CUDA
    # library download or driver guidance) when present-but-not-usable.
    _render_compute_hardware_status(hw)
    _render_gpu_enablement(hw)

    # Contextual advisory for the chosen device + model.
    # Wrapped in an ALWAYS-present container so switching CPU<->GPU never adds or
    # removes a sibling element here. The advisory text only appears for some
    # device/model combos; without this fixed slot, toggling the device would
    # change the element count above the model list, shifting every following
    # element's delta-path index and forcing Streamlit to fully remount (collapse
    # then rebuild) the whole model table - the dramatic flash we're avoiding.
    # The empty container is ~0px tall, so it costs nothing when there's no notice.
    with st.container(key="pan_advisory_slot"):
        _adv = device_advisory(st.session_state.get("pan_device", "cpu"),
                               st.session_state.get("pan_model", "small"), hw)
        if _adv:
            _lvl, _msg = _adv
            if _lvl == "warn":
                from ui.amber_notice import render_amber_notice
                render_amber_notice(_msg, margin="10px 0 0 0")
            else:
                from ui.amber_notice import render_info_notice
                render_info_notice(_msg, margin="10px 0 0 0")

    any_downloading = _render_model_manager()

    st.markdown("<hr style='border:none;border-top:1px solid rgba(255,255,255,0.06);margin:16px 0 12px 0;'>",
                unsafe_allow_html=True)
    if st.button("Done", key="pan_dialog_done", type="primary", use_container_width=True):
        _close_transcription_dialog()
        st.rerun(scope="app")

    # Auto-rerun while a model download OR a CUDA-library provision is running so
    # their progress bars advance live. scope="fragment" re-runs ONLY this dialog
    # (an @st.dialog is a fragment), so the background page is left untouched -
    # without this the old scope="app" tick re-ran the whole app twice a second,
    # making the page behind the modal flicker / re-trigger its loading overlay.
    if any_downloading or cuda_provision.is_running():
        time.sleep(0.5)
        st.rerun(scope="fragment")
