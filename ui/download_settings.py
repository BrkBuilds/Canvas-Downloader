"""
ui.download_settings — Step 2 download settings page.

Extracted from ``app.py`` (Phase 6).
Strict physical move — NO logic changes.

Contains:
  - ``render_download_settings()`` — full Step 2: preset buttons, Card 1
    (Core Course Files), Card 2 (Canvas Content), Card 3 (AI Engine),
    Output Path, Course Summary, Confirm button.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

import streamlit as st

import theme
from ui_helpers import (
    esc,
    render_download_wizard,
    native_folder_picker,
    get_base64_image,
)
from core.state_registry import (
    SECONDARY_CONTENT_KEYS,
    NOTEBOOK_SUB_KEYS,
    TOTAL_SECONDARY_SUBS,
)


def _resolve_path(path):
    """Resolve path for frozen (PyInstaller) vs normal execution."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, path)
    return path


def _select_folder():
    """Open native folder picker and store result in download_path."""
    folder_path = native_folder_picker()
    if folder_path:
        st.session_state['download_path'] = folder_path


def _get_chevron_base64(is_expanded):
    if is_expanded:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1683 808-742 741q-19 19-45 19t-45-19L109 808q-19-19-19-45.5t19-45.5l166-165q19-19 45-19t45 19l531 531 531-531q19-19 45-19t45 19l166 165q19 19 19 45.5t-19 45.5z"></path></svg>'''
    else:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="1792" height="1792" viewBox="0 0 1792 1792" id="chevron"><path d="m1363 877-742 742q-19 19-45 19t-45-19l-166-166q-19-19-19-45t19-45l531-531-531-531q-19-19-19-45t19-45L531 45q19-19 45-19t45 19l742 742q19 19 19 45t-19 45z"></path></svg>'''
    b64_str = base64.b64encode(svg.encode('utf-8')).decode()
    return f"url('data:image/svg+xml;base64,{b64_str}')"


def render_download_settings(fetch_courses_fn):
    """Render the full Step 2 download settings page.

    Args:
        fetch_courses_fn: The cached ``fetch_courses()`` function from app.py.
    """
    # Import preset dialogs from extracted module
    from ui.presets import _save_config_dialog, _presets_hub_dialog

    render_download_wizard(st, 2)

    # Hoisted CSS Overrides for Step 2 UI Component geometry
    st.markdown("""
    <style>
    div[data-testid="stHorizontalBlock"]:has(.st-key-action_dl_back),
    div[data-testid="stHorizontalBlock"]:has(.st-key-action_dl_confirm) {
        margin-top: -15px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Consume pending toasts from preset dialogs
    if 'pending_toast' in st.session_state:
        st.toast(st.session_state.pop('pending_toast'))

    # Step 2 Header with Preset Buttons
    _hdr_left, _hdr_right = st.columns([0.6, 0.4])
    with _hdr_left:
        st.markdown("<h2 style='margin-bottom: -10px;'>Step 2: Download Settings</h2>", unsafe_allow_html=True)


    with _hdr_right:
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        _pb1, _pb2 = st.columns(2, gap="small")
        with _pb1:
            if st.button("💾 Save Preset", key="btn_save_config", use_container_width=True):
                _save_config_dialog()
        with _pb2:
            if st.button("⚙️ Presets", key="btn_presets_hub", use_container_width=True):
                _presets_hub_dialog()

    def _load_b64(path):
        import base64
        try:
            with open(_resolve_path(path), "rb") as f:
                return base64.b64encode(f.read()).decode()
        except FileNotFoundError:
            return ""

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

    /* 1. Outer Container & Crush horizontal gap */
    div[class*="st-key-include_files_segmented_wrapper"] {{
        margin-top: 5px !important;
    }}

    /* 2. Stretch column wrappers for dynamic height */
    div[class*="st-key-include_files_segmented_wrapper"] div[data-testid="column"] > div,
    div[class*="st-key-include_files_segmented_wrapper"] div[data-testid="stButton"] {{
        height: 100% !important;
    }}

    /* 3. Base Button: Flex Column + Relative Position */
    div[class*="st-key-btn_include_"] button {{
        position: relative !important;
        height: 150px !important;
        background-color: transparent !important;
        background-repeat: no-repeat !important;
        background-position: center 18px !important;
        background-size: 55px !important;
        padding-top: 85px !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        border-radius: 8px !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: flex-start !important;
        transition: all 0.2s ease-in-out !important;
        opacity: 0.75 !important;
        color: #a0a0a0 !important;
    }}

    /* 4. Primary Title Styling (The native button label) */
    div[class*="st-key-btn_include_"] button p {{
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        margin: 0 !important;
        margin-bottom: 0px !important;
        line-height: 1.2 !important;
        color: inherit !important;
    }}

    div[class*="st-key-btn_include_"] button::after {{
        margin-bottom: 0px !important;
        padding-bottom: 0px !important;
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

    /* 6.5 Hover State (Inactive Buttons) */
    div[class*="st-key-btn_include_"] button:hover {{
        border-color: #3fd9ff !important;
        background-color: rgba(255, 255, 255, 0.02) !important;
        box-shadow: inset 0 0 0 1px #3fd9ff, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
        opacity: 1 !important;
        color: #ffffff !important;
    }}

    /* 7. Active State Logic */
    div.st-key-btn_include_{active_include_key} button {{
        border: 1px solid #3fd9ff !important;
        background-color: rgba(56, 189, 248, 0.05) !important;
        box-shadow: inset 0 0 0 1px #3fd9ff, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
        opacity: 1 !important;
        color: #ffffff !important;
    }}
    /* Protect Active Blue Pill from Grey Hover Override */
    div.st-key-btn_include_{active_include_key} button:hover {{
        border: 1px solid #3fd9ff !important;
        background-color: rgba(56, 189, 248, 0.08) !important;
        box-shadow: inset 0 0 0 1px #3fd9ff, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
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

        def _get_sec_org_segmented_css():
            import base64
            import os

            def _get_b64(filepath):
                if os.path.exists(filepath):
                    with open(filepath, "rb") as f:
                        return base64.b64encode(f.read()).decode()
                return ""

            b64_inline = _get_b64("assets/icon_sec_inline.png")
            b64_sub = _get_b64("assets/icon_sec_subfolders.png")

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
            }}
            div[class*="st-key-sec_org_segmented_wrapper"] [data-testid="column"] > div, 
            div[class*="st-key-sec_org_segmented_wrapper"] div[data-testid="stButton"], 
            div[class*="st-key-sec_org_segmented_wrapper"] button {{
                height: 100% !important;
            }}
            div[class*="st-key-btn_sec_org_"] button {{
                background-color: transparent !important;
                border: 1px solid transparent !important;
                display: flex !important;
                flex-direction: column !important;
                padding: 12px 12px 12px 52px !important;
                border-radius: 8px !important;
                color: #a0a0a0 !important;
                opacity: 0.75 !important;
                transition: opacity 0.2s ease, background-color 0.2s ease, filter 0.2s ease, color 0.2s ease !important;
                position: relative !important;
                min-height: 62px !important;
            }}
            /* Nuke Streamlit's center alignment for the segmented control */
            div[class*="st-key-btn_sec_org_"] button > div,
            div[class*="st-key-btn_sec_org_"] button div[data-testid="stMarkdownContainer"] {{
                width: 100% !important;
                display: flex !important;
                justify-content: flex-start !important;
                text-align: left !important;
            }}
            div[class*="st-key-btn_sec_org_"] button p {{
                text-align: left !important;
                width: 100% !important;
                margin: 0 !important;
                font-size: 0.95rem !important;
                font-weight: 600 !important;
                line-height: 1.2 !important;
                color: inherit !important;
            }}
            div[class*="st-key-btn_sec_org_"] button {{
                background-size: 28px !important;
                background-repeat: no-repeat !important;
                background-position: 12px center !important;
            }}
            div.st-key-btn_sec_org_inline button {{ background-image: url('data:image/png;base64,{b64_inline}') !important; }}
            div.st-key-btn_sec_org_subfolders button {{ background-image: url('data:image/png;base64,{b64_sub}') !important; }}

            div[class*="st-key-btn_sec_org_"] button:hover {{
                background-color: rgba(255, 255, 255, 0.05) !important;
                border-color: #68d4a3 !important;
                opacity: 1 !important;
                color: #ffffff !important;
            }}

            /* Disabled State Overrides */
            div[class*="st-key-btn_sec_org_"] button[disabled] {{
                opacity: 0.4 !important;
                pointer-events: none !important;
                filter: grayscale(100%) !important;
            }}

            div.st-key-btn_sec_org_inline button::after {{ content: "Place Canvas Content alongside your other downloaded files." !important; }}
            div.st-key-btn_sec_org_subfolders button::after {{ content: "Create folders for each type (e.g. Assignments/, Quizzes/)" !important; }}
            div[class*="st-key-btn_sec_org_"] button::after {{
                text-align: left !important;
                width: 100% !important;
                display: block !important;
                font-size: 0.75rem !important;
                color: #a0a0a0 !important;
                margin-top: 2px !important;
                font-weight: 400 !important;
                white-space: normal !important;
                line-height: 1.2 !important;
            }}
            div.st-key-btn_sec_org_{active_key} button {{
                background-color: rgba(104, 212, 163, 0.15) !important; /* Muted Green */
                border: 1px solid rgba(104, 212, 163, 0.3) !important;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3) !important; /* Slight drop shadow for the pill */
                color: #ffffff !important;
                opacity: 1 !important;
            }}
            /* Protect Active Green Pill from Grey Hover Override */
            div.st-key-btn_sec_org_{active_key} button:hover {{
                background-color: rgba(104, 212, 163, 0.15) !important;
                border: 1px solid rgba(104, 212, 163, 0.3) !important;
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
        st.markdown("""
        <style>
        /* Tree-view styling for secondary content sub-checkboxes */
        .st-key-dl_assignments, .st-key-dl_syllabus, .st-key-dl_announcements,
        .st-key-dl_discussions, .st-key-dl_quizzes, .st-key-dl_rubrics,
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
        """, unsafe_allow_html=True)

        # Card elevation CSS — Version-Agnostic Target for Streamlit 1.51+
        c2_exp_global = st.session_state.get('card2_expanded', False)
        card2_flex_rule = """
    /* TIER 1 & TIER 2: Conditional Flex rule for Card 2 to match Card 1 height. 
       If collapsed, this is omitted so the card shrink-fits to its textual content. */
    div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-card_native_content"]) { flex: 1 !important; }
    div[class*="st-key-card_native_content"] { flex: 1 !important; }
    """ if c2_exp_global else ""

        st.markdown(f"""
    <style>
    /* 1. Target via the explicit Streamlit Keys (Most Reliable) */
    div[class*="st-key-card_core_files"],
    div[class*="st-key-card_native_content"],
    div[class*="st-key-card_ai_engine"],

    /* 2. Target via modern Streamlit 1.51+ Container ID + Trojan Class */
    div[data-testid="stContainer"]:has(.step-2-card-target) {{
        background-color: rgba(255, 255, 255, 0.04) !important;
        border-radius: 8px !important;
    }}

    /* === Card 1 ↔ Card 2: Dynamic Height Synchronization === */
    div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-card_core_files"]) {{
        flex: 1 !important;
    }}
    div[class*="st-key-card_core_files"] {{
        flex: 1 !important;
    }}

    {card2_flex_rule}

    /* Push the "Include Files" section to the bottom of Card 1 */
    div[class*="st-key-card1_include_section"] {{
        margin-top: auto !important;
    }}
    </style>
    """, unsafe_allow_html=True)

        col1, col2 = st.columns([3, 5], gap="medium")

        # --- COLUMN 1: Organization & Include Files ---
        with col1:
            with st.container(border=True, key="card_core_files"):
                b64_wf1 = _load_b64("assets/icon_workflow_1.png")
                st.markdown(f"""<div class='step-2-card-target' style='position: relative; margin-top: -10px; margin-bottom: 12px;'>
    <img src='data:image/png;base64,{b64_wf1}' style='position: absolute; width: 36px; height: 36px; top: -24px; left: -34px; z-index: 10;'>
    <div style='padding-left: 0px;'>
    <h3 style='margin: 0; line-height: 1.2;'>Core Course Files &amp; Structure</h3>
    </div>
    </div>
    <p style='font-size: 0.95rem; color: #e2e8f0; margin-top: -20px; margin-bottom: 0px;'>Select what to download and how to organize it on your computer.</p>
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
                            st.button("Presentations & PDFs", key="btn_include_study", use_container_width=True, on_click=update_include_state, args=("study",))

                st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True)

                # 2. Organization Block (Large Buttons)
                def update_org_state(mode):
                    st.session_state['download_mode'] = 'modules' if mode == 'subfolders' else mode

                st.markdown(
                    "<p style='font-size: 0.9rem; font-weight: 600; color: #cbd5e1; margin-top: 0px; margin-bottom: 0px;'>Choose how files should be organized:</p>", 
                    unsafe_allow_html=True
                )

                btn_left, btn_right = st.columns(2)
                b64_subfolders = get_base64_image("assets/icon_subfolders.png")
                b64_flat = get_base64_image("assets/icon_flat.png")

                with btn_left:
                    st.button("With Subfolders", key="btn_org_subfolders", use_container_width=True, on_click=update_org_state, args=("subfolders",))

                with btn_right:
                    st.button("All in One Folder", key="btn_org_flat", use_container_width=True, on_click=update_org_state, args=("flat",))

                active_mode = st.session_state.get('download_mode', 'modules')
                active_btn_key = "subfolders" if active_mode == 'modules' else "flat"

                try:
                    border_color = theme.PRIMARY_BLUE if hasattr(theme, 'PRIMARY_BLUE') else theme.ACCENT_LINK
                except Exception:
                    border_color = "#007bff"

                st.markdown(f'''
                <style>
                /* Base Card Styling for BOTH buttons */
                div[class*="st-key-btn_org_"] button {{
                    position: relative !important;
                    height: 150px !important;
                    background-color: transparent !important;
                    background-repeat: no-repeat !important;
                    background-position: center 18px !important;
                    background-size: 55px !important;
                    padding-top: 85px !important;
                    border: 1px solid rgba(255, 255, 255, 0.15) !important;
                    border-radius: 8px !important;
                    display: flex !important;
                    flex-direction: column !important;
                    align-items: center !important;
                    justify-content: flex-start !important;
                    transition: all 0.2s ease-in-out !important;
                    opacity: 0.75 !important;
                    color: #a0a0a0 !important;
                }}

                /* Primary Title Styling (The native button label) */
                div[class*="st-key-btn_org_"] button p {{
                    font-size: 1.1rem !important;
                    font-weight: 600 !important;
                    margin: 0 !important;
                    margin-bottom: 0px !important;
                    line-height: 1.2 !important;
                    color: inherit !important;
                }}

                div[class*="st-key-btn_org_"] button::after {{
                    margin-bottom: 0px !important;
                    padding-bottom: 0px !important;
                }}

                /* Geometry lockdown for radio pseudo-element on Card 1 */
                div[class*="st-key-btn_org_"] button::before {{
                    top: 16px !important;
                    right: 16px !important;
                    box-sizing: border-box !important;
                }}

                /* Hover State */
                div[class*="st-key-btn_org_"] button:hover {{
                    border-color: #3fd9ff !important;
                    background-color: rgba(255, 255, 255, 0.02) !important;
                    box-shadow: inset 0 0 0 1px #3fd9ff, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
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

                /* Active State Highlight */
                div.st-key-btn_org_{active_btn_key} button {{
                    border: 1px solid {border_color} !important;
                    background-color: rgba(56, 189, 248, 0.05) !important;
                    box-shadow: inset 0 0 0 1px {border_color}, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
                    opacity: 1 !important;
                    color: #ffffff !important;
                }}
                /* Protect Active State from generic Hover Overrides */
                div.st-key-btn_org_{active_btn_key} button:hover {{
                    border: 1px solid {border_color} !important;
                    background-color: rgba(56, 189, 248, 0.08) !important;
                    box-shadow: inset 0 0 0 1px {border_color}, 0 4px 12px rgba(0, 0, 0, 0.2) !important;
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

        # --- COLUMN 2: Additional Course Content ---
        with col2:
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
                c2_base_color = "#68d4a3" if c2_exp else "#64748b"
                c2_hover_color = "#86e0b8" if c2_exp else "#94a3b8"

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
                div.st-key-header_wrap_card2 > div[data-testid="element-container"] {{
                    margin-bottom: 0px !important;
                }}
                div.st-key-header_wrap_card2 > div[data-testid="element-container"]:nth-child(1) {{
                    width: 24px !important;
                    min-width: 24px !important;
                    flex: 0 0 24px !important;
                }}
                div.st-key-header_wrap_card2 > div[data-testid="element-container"]:nth-child(2) {{
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
                /* RERUN LOCK */
                div.st-key-toggle_card2 button[disabled] {{
                    box-shadow: none !important;
                    outline: none !important;
                    border: none !important;
                    background-color: {c2_base_color} !important;
                    opacity: 0.8 !important;
                }}
                </style>''', unsafe_allow_html=True)

                st.markdown(f"<div class='step-2-card-target' style='position: relative; margin-top: -25px; margin-bottom: 0px;'><img src='data:image/png;base64,{b64_wf2}' style='position: absolute; width: 36px; height: 36px; top: -34px; left: -34px; z-index: 10; filter: {c_filter}; transition: all 0.2s ease;' /></div>", unsafe_allow_html=True)

                with st.container(key="header_wrap_card2"):
                    st.button("\u200B", key="toggle_card2", on_click=toggle_card2)
                    st.markdown(f"""<div style='display: flex; align-items: center; justify-content: flex-start; gap: 12px; width: 100%; transform: translateY(-5px);'><h3 style='margin: 0px !important; padding: 0px !important; line-height: 1 !important;'>Canvas Content <span style='color: #64748b; font-size: 0.8em; font-weight: normal;'>(Optional)</span></h3><span style='background-color: {c2_tag_bg}; color: {c2_tag_col}; border: {c2_tag_bor}; font-size: 0.8rem; padding: 2px 12px; border-radius: 15px; font-weight: 600; transition: all 0.2s ease;'>{dynamic_tag}</span></div>""", unsafe_allow_html=True)

                css_blocks = []

                # Helper to safely load icon
                def safe_b64(name):
                    try:
                        res = get_base64_image(f"assets/{name}")
                        return res if res else ""
                    except:
                        return ""

                # Button data
                button_defs = [
                    ('dl_assignments', 'Assignments', 'Includes assignment descriptions and any attached files.', 'icon_assignments.png'),
                    ('dl_syllabus', 'Syllabus', 'Save the course syllabus page as HTML.', 'icon_syllabus.png'),
                    ('dl_announcements', 'Announcements', 'Save course announcements and any attached files.', 'icon_announcements.png'),
                    ('dl_discussions', 'Discussions', 'Save discussion threads as HTML.', 'icon_discussions.png'),
                    ('dl_quizzes', 'Quizzes', 'Save quiz questions and answers as HTML.', 'icon_quizzes.png'),
                    ('dl_rubrics', 'Rubrics', 'Save rubric criteria to text files.', 'icon_rubrics.png'),
                    ('dl_submissions', 'Submissions (Results)', 'Save feedback & grades from your submissions.', 'icon_submissions.png')
                ]

                css_blocks.append('''
                div.st-key-secondary_cards_grid [data-testid="stHorizontalBlock"] {
                    gap: 12px !important;
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
                    height: 58px !important;
                    min-height: 0px !important;
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
                b64_m = safe_b64('icon_select_all.png')
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
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            for key, title, _, _ in button_defs[:3]:
                                st.button(title, key=f"btn_{key}", on_click=_toggle_secondary_sub, args=(key,), use_container_width=True)
                        with c2:
                            for key, title, _, _ in button_defs[3:5]:
                                st.button(title, key=f"btn_{key}", on_click=_toggle_secondary_sub, args=(key,), use_container_width=True)
                        with c3:
                            for key, title, _, _ in button_defs[5:]:
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

                        with c1:
                            st.button(
                                "Match Course Folder structure", 
                                key="btn_sec_org_inline", 
                                on_click=_set_isolate_secondary, 
                                args=(False,), 
                                use_container_width=True,
                                disabled=is_disabled
                            )
                        with c2:
                            st.button(
                                "In Separate Folders", 
                                key="btn_sec_org_subfolders", 
                                on_click=_set_isolate_secondary, 
                                args=(True,), 
                                use_container_width=True,
                                disabled=is_disabled
                            )




        # Force a visual break between top and bottom rows
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

        # --- BOTTOM ROW: Conversion Settings / NotebookLM ---
        with st.container(border=True, key="card_ai_engine"):
            # --- Conversion Button Data ---
            conv_button_defs = [
                ('convert_zip',   'Unpack Archives',    'Auto-unzip .zip and .tar.gz archives.',        'icon_conv_zip.png'),
                ('convert_pptx',  'PowerPoint → PDF',         'Convert .pptx/.ppt to PDF.',      'icon_conv_pptx.png'),
                ('convert_word',  'Legacy Word Docs → PDF',          'Convert unsupported older formats (.doc, .rtf, .odt) to PDF.',                    'icon_conv_word.png'),
                ('convert_excel', 'Excel → PDF & AI Data',              'Export spreadsheets as visual PDFs and LLM-ready CSV sidecars.',                'icon_conv_excel.png'),
                ('convert_html',  'Canvas Pages → Plain Text',          'Convert Canvas web pages into AI-friendly text.',          'icon_conv_html.png'),
                ('convert_code',  'Code & Data → .txt',       'Append .txt extension to programming files (e.g. code.js.txt).',          'icon_conv_code.png'),
                ('convert_urls',  'Gather Web Links in .txt',        'Compile all internet shortcuts into one structured .txt file.',        'icon_conv_urls.png'),
                ('convert_video', 'Video → Audio',            'Extract .mp3 audio from video files.',          'icon_conv_video.png'),
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

            # --- Generate CSS for each button ---
            conv_css_blocks = []

            # Base styles — zero-indentation to prevent Streamlit code-block conversion
            conv_css_blocks.append(
    'div.st-key-conversion_cards_grid [data-testid="stHorizontalBlock"] { gap: 12px !important; }\n'
    'div[class*="st-key-btn_convert_"] button > div,\n'
    'div[class*="st-key-btn_convert_"] button div[data-testid="stMarkdownContainer"] {\n'
    'width: 100% !important; display: flex !important; justify-content: flex-start !important; text-align: left !important; }\n'
    'div[class*="st-key-btn_convert_"] button p { text-align: left !important; width: 100% !important; margin-top: 0px !important; margin-bottom: 0px !important; line-height: 1.2 !important; }\n'
    'div[class*="st-key-btn_convert_"] button::after { text-align: left !important; width: 100% !important; display: block !important; }\n'
    'div[class*="st-key-btn_convert_"] button {\n'
    'height: 58px !important; min-height: 0px !important;\n'
    'padding-top: 10px !important; padding-bottom: 10px !important;\n'
    'padding-right: 10px !important; padding-left: 52px !important;\n'
    'background-position: 15px center !important; background-size: 30px !important;\n'
    'background-repeat: no-repeat !important; border-radius: 12px !important;\n'
    'display: flex; flex-direction: column; -webkit-tap-highlight-color: transparent !important; }\n'
    'div.st-key-btn_convert_master button { height: 48px !important; padding-top: 0px !important; padding-bottom: 0px !important; padding-left: 50px !important; background-size: 24px !important; justify-content: center !important; }\n'
            )

            # Master (Select All) CSS
            m_active = st.session_state.get('notebooklm_master', False)
            m_bg = "rgba(255, 255, 255, 0.12)" if m_active else "rgba(255, 255, 255, 0.1)"
            m_border = "rgba(255, 255, 255, 0.1)"
            m_ledge = "#f97316" if m_active else "transparent"
            m_ledge_border = "#f97316" if m_active else m_border
            b64_conv_m = safe_b64('icon_conv_select_all.png')
            m_conv_img_rule = f"background-image: url('data:image/png;base64,{b64_conv_m}') !important;" if b64_conv_m else ""

            conv_css_blocks.append(
    f'div.st-key-btn_convert_master button {{ background-color: {m_bg} !important; border: 1px solid {m_border} !important; border-bottom: 1px solid {m_ledge_border} !important; box-shadow: inset 0 -3px 0 0 {m_ledge} !important; border-radius: 12px !important; {m_conv_img_rule} }}\n'
            )
            if not m_active:
                conv_css_blocks.append(
    'div.st-key-btn_convert_master button:hover { border-bottom: 1px solid #a64d0f !important; box-shadow: inset 0 -3px 0 0 #a64d0f !important; }\n'
                )
            if m_active:
                conv_css_blocks.append(
    '/* Master button checkbox intentionally hidden by global rule. */\n'
                )

            # Child button CSS (per-toggle)
            for conv_key, conv_title, conv_desc, conv_icon in conv_button_defs:
                is_conv_active = st.session_state.get(conv_key, False)
                c_bg = "rgba(249, 115, 22, 0.15)" if is_conv_active else "rgba(255, 255, 255, 0.02)"
                c_border = "#f97316" if is_conv_active else "rgba(255, 255, 255, 0.1)"
                b64_conv_c = safe_b64(conv_icon)
                c_conv_img_rule = f"background-image: url('data:image/png;base64,{b64_conv_c}') !important;" if b64_conv_c else ""

                if is_conv_active:
                    c_conv_check = f'''div.st-key-btn_{conv_key} button::before {{ border: none !important; background-color: transparent !important; background-image: url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\'%3E%3Cdefs%3E%3Cmask id=\'m\'%3E%3Crect width=\'24\' height=\'24\' fill=\'white\'/%3E%3Cpath d=\'M20 6L9 17l-5-5\' fill=\'none\' stroke=\'black\' stroke-width=\'4\' stroke-linecap=\'round\' stroke-linejoin=\'round\'/%3E%3C/mask%3E%3C/defs%3E%3Crect width=\'24\' height=\'24\' rx=\'4\' fill=\'%23ff9838\' mask=\'url(%23m)\'/%3E%3C/svg%3E") !important; }}\n'''
                    hover_color = "transparent"
                else:
                    c_conv_check = ""
                    hover_color = "#f97316"

                conv_css_blocks.append(
    f'div.st-key-btn_{conv_key} button {{ background-color: {c_bg} !important; border: 1px solid {c_border} !important; {c_conv_img_rule} }}\n'
    f'{c_conv_check}'
    f'div.st-key-btn_{conv_key} button::after {{ content: "{conv_desc}" !important; font-size: 0.75rem !important; color: #a0a0a0; white-space: normal !important; display: block !important; text-align: left !important; width: 100%; margin-top: -2px !important; line-height: 1.2 !important; }}\n'
    f'div.st-key-btn_{conv_key} button:hover {{ border-color: #f97316 !important; }}\n'
    f'div.st-key-btn_{conv_key} button:hover::before {{ border-color: {hover_color} !important; }}\n'
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
            c3_base_color = "#f97316" if c3_exp else "#64748b"
            c3_hover_color = "#fb923c" if c3_exp else "#94a3b8"

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
            div.st-key-header_wrap_card3 > div[data-testid="element-container"] {{
                margin-bottom: 0px !important;
            }}
            div.st-key-header_wrap_card3 > div[data-testid="element-container"]:nth-child(1) {{
                width: 24px !important;
                min-width: 24px !important;
                flex: 0 0 24px !important;
            }}
            div.st-key-header_wrap_card3 > div[data-testid="element-container"]:nth-child(2) {{
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
            /* RERUN LOCK */
            div.st-key-toggle_card3 button[disabled] {{
                box-shadow: none !important;
                outline: none !important;
                border: none !important;
                background-color: {c3_base_color} !important;
                opacity: 0.8 !important;
            }}
            </style>''', unsafe_allow_html=True)

            st.markdown(f"<div class='step-2-card-target' style='position: relative; margin-top: -25px; margin-bottom: 0px;'><img src='data:image/png;base64,{b64_wf3}' style='position: absolute; width: 36px; height: 36px; top: -34px; left: -34px; z-index: 10; filter: {c3_filter}; transition: all 0.2s ease;' /></div>", unsafe_allow_html=True)

            with st.container(key="header_wrap_card3"):
                st.button("\u200B", key="toggle_card3", on_click=toggle_card3)
                st.markdown(f"""<div style='display: flex; align-items: center; justify-content: flex-start; gap: 12px; width: 100%; transform: translateY(-5px);'><h3 style='margin: 0px !important; padding: 0px !important; line-height: 1 !important;'>Optimize for AI Tools <span style='color: #64748b; font-size: 0.8em; font-weight: normal;'>(Optional)</span></h3><span style='background-color: {c3_tag_bg}; color: {c3_tag_col}; border: {c3_tag_bor}; font-size: 0.8rem; padding: 2px 12px; border-radius: 15px; font-weight: 600; transition: all 0.2s ease;'>{conv_tag}</span></div>""", unsafe_allow_html=True)

            # --- CSS injection (separate call, zero-indentation) ---
            conv_css_html = "<style>\n" + "".join(conv_css_blocks) + "</style>"

            if c3_exp:
                st.markdown(f"""{conv_css_html}
<p style='font-size: 0.95rem; color: #e2e8f0; margin-top: -15px; margin-bottom: 0px;'>Automatically convert files into drag-and-drop ready formats, optimized for NotebookLM, ChatGPT, Claude, Gemini, and other AI tools.</p>
<hr style='border: none; border-top: 1px solid rgba(255, 255, 255, 0.15); margin-top: 15px; margin-bottom: 15px;'>""", unsafe_allow_html=True)
                st.button("Select All", key="btn_convert_master", on_click=_toggle_conv_master, use_container_width=True)

                with st.container(key="conversion_cards_grid"):
                    cols = st.columns(4)
                    for idx, (conv_key, conv_title, _, _) in enumerate(conv_button_defs):
                        col = cols[idx % 4]
                        with col:
                            st.button(conv_title, key=f"btn_{conv_key}", on_click=_toggle_conv_sub, args=(conv_key,), use_container_width=True)

        # 2. Output Card
        with st.container(border=True, key="review_output_card"):
            st.markdown("<h3 style='margin-top: -15px; margin-bottom: -35px;'>Output Path</h3>", unsafe_allow_html=True)

            dl_path = st.session_state['download_path']
            dl_path_escaped = dl_path.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;").replace('"', "&quot;")

            # Render path + button side-by-side.
            # Nuclear CSS: apply flex-direction:row at EVERY DOM depth to hit whatever
            # level Streamlit nests the element-containers at. The `> div` chain covers
            # stVerticalBlockBorderWrapper, stVerticalBlock, and any other intermediates.
            st.markdown("""<style>
    div.st-key-path_display_row,
    div.st-key-path_display_row > div,
    div.st-key-path_display_row > div > div,
    div.st-key-path_display_row > div > div > div {
        display: flex !important;
        flex-direction: row !important;
        align-items: flex-end !important;
        gap: 10px !important;
        flex-wrap: nowrap !important;
        width: auto !important;
    }
    div.st-key-path_display_row div[data-testid="element-container"],
    div.st-key-path_display_row div.stElementContainer {
        width: auto !important;
        flex: 0 0 auto !important;
        margin-bottom: 12px !important;

    }
    div.st-key-path_display_row div[data-testid="element-container"]:first-child,
    div.st-key-path_display_row div.stElementContainer:first-child {
        max-width: calc(100% - 180px) !important;
    }
    div.st-key-path_display_row button {
        white-space: nowrap !important;
        height: 42px !important;
        padding: 0 20px !important;
        margin-bottom: -8px !important;
        background-color: rgba(255, 255, 255, 0.1) !important;
        border: 1px solid rgba(255, 255, 255, 0.13) !important;
        color: rgba(255, 255, 255, 0.85) !important;
    }
    div.st-key-path_display_row button:hover {
        background-color: rgba(255, 255, 255, 0.15) !important;
        border-color: rgba(255, 255, 255, 0.18) !important;
    }
    </style>""", unsafe_allow_html=True)

            with st.container(key="path_display_row"):
                st.markdown(f"""<div>
    <label style="font-size: 0.82rem; color: rgba(250,250,250,0.6); margin-bottom: 4px; display: block;">Path</label>
    <div style="
        display: inline-block;
        max-width: 100%;
        background-color: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 0.875rem;
        color: rgba(250, 250, 250, 0.5);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.5;
        font-family: 'Source Sans Pro', sans-serif;
        box-sizing: border-box;
        cursor: default;
        user-select: none;
    ">{dl_path_escaped}</div>
    </div>""", unsafe_allow_html=True)
                st.button('📂 Select Folder', key='action_dl_folder', on_click=_select_folder)

        # --- Unified Course Summary Dropdown (full-width, native <details>) ---
        _dl_courses = st.session_state.get('courses_to_download', [])
        if not _dl_courses:
            try:
                _all_c = fetch_courses_fn(st.session_state['api_token'], st.session_state['api_url'], False)
                _sel_ids = set(st.session_state.get('selected_course_ids', []))
                _dl_courses = [c for c in _all_c if c.id in _sel_ids]
            except Exception:
                _dl_courses = []
        _dl_count = len(_dl_courses)

        _dl_list_html = "".join([
            f"<li class='course-item'><span class='num'>{i}.</span> <span class='name'>{esc(c.get('name', 'Unknown Course') if isinstance(c, dict) else getattr(c, 'name', 'Unknown Course'))}</span></li>"
            for i, c in enumerate(_dl_courses, 1)
        ])

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
    .summary-chevron {{
        color: #a0a0a0;
        font-size: 1.3rem;
        line-height: 1;
        transition: transform 0.2s ease;
    }}
    details.unified-course-dropdown[open] .summary-chevron {{
        transform: rotate(90deg);
    }}
    .summary-text {{
        color: #ffffff;
        font-size: 1.05rem;
        font-weight: 500;
    }}
    .summary-text strong {{
        font-weight: bold;
        color: #ffffff;
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
        align-items: baseline;
        gap: 5px;
        padding: 8px 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }}
    li.course-item:last-child {{
        border-bottom: none;
    }}
    li.course-item .num {{
        color: #888888;
        font-size: 0.9rem;
        min-width: 20px;
    }}
    li.course-item .name {{
        color: #ffffff;
        font-size: 0.95rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
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
    <div class="summary-chevron">▸</div>
    <div class="summary-text">Courses to be downloaded: <strong>{_dl_count}</strong></div>
    </summary>
    <div class="dropdown-body">
    <ul class="course-list-box">
    {_dl_list_html}
    </ul>
    </div>
    </details>
    """

        st.markdown(_dl_details_html, unsafe_allow_html=True)
        col_back, col_conf, _ = st.columns([0.66, 1.2, 5])
        with col_conf:
            # Button label changes based on mode
            button_label = 'Sync (Download) Selected Files' if st.session_state['current_mode'] == 'sync' else 'Confirm and Download'
            if st.button(button_label, type="primary", use_container_width=True, key='action_dl_confirm'):
                try:
                    # Initialize download state
                    all_courses = fetch_courses_fn(st.session_state['api_token'], st.session_state['api_url'], False)
                    course_map = {c.id: c for c in all_courses}
                    courses_to_download = [course_map[cid] for cid in st.session_state['selected_course_ids'] if cid in course_map]

                    st.session_state['courses_to_download'] = courses_to_download
                    st.session_state['current_course_index'] = 0
                    st.session_state['cancel_requested'] = False
                    st.session_state['total_items'] = 0
                    st.session_state['downloaded_items'] = 0
                    st.session_state['course_mb_downloaded'] = {}
                    st.session_state['log_content'] = ""  # Initialize log content
                    st.session_state['seen_error_sigs'] = set()  # Clear deduplication state for fresh download

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

                    # Clear debug log once at session start (subsequent courses append)
                    if st.session_state.get('debug_mode', False):
                        from canvas_debug import clear_debug_log
                        clear_debug_log(Path(st.session_state['download_path']) / "debug_log.txt")

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
                    st.error(f"Error initializing: {e}")

        with col_back:
            if st.button('Back', use_container_width=True, key='action_dl_back'):
                st.session_state['step'] = 1
                st.rerun()

