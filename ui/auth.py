"""
ui.auth - Sidebar authentication, navigation, and global settings.

Extracted from ``app.py`` (Phase 7).
Strict physical move - NO logic changes.

Contains:
  - ``render_sidebar()`` - full sidebar: auth form, token loading,
    navigation buttons, global settings dialog, logout, version badge
"""

from __future__ import annotations

import base64
import json
import logging
import os
from html import escape as _he

import streamlit as st

from canvas_logic import CanvasManager
from version import __version__

logger = logging.getLogger(__name__)


def _get_config_path() -> str:
    """Return the path to the persistent config JSON file (lazy import)."""
    from ui_helpers import get_config_dir
    return os.path.join(get_config_dir(), 'canvas_downloader_settings.json')

# Evaluated once at first render (not at import-time of the module).
# All reads/writes use CONFIG_FILE as a stable module-level constant.
try:
    CONFIG_FILE = _get_config_path()
except Exception:
    import tempfile
    CONFIG_FILE = os.path.join(tempfile.gettempdir(), 'canvas_downloader_settings.json')
KEYRING_SERVICE = "CanvasDownloader"


def render_sidebar(fetch_courses_fn):
    """Render the full sidebar: navigation, settings, logout.

    Must be called inside ``with st.sidebar:``.

    Args:
        fetch_courses_fn: The ``@st.cache_resource``-wrapped ``fetch_courses()``
            function from app.py.  Needed so logout can call ``.clear()``.
    """
    if not st.session_state.get('is_authenticated'):
        return

    from ui_helpers import get_base64_image
    icon_b64    = get_base64_image("assets/icon.png")
    icon_dl_b64 = get_base64_image("assets/icon_download.png")
    icon_sync_b64 = get_base64_image("assets/icon_sync.png")

    # ── Single consolidated CSS block for all sidebar nav elements ──────
    st.html(f"""
<style>
/* ── Nav button containers: natural 100% width (zero side padding on parent) ── */
[data-testid="stSidebarUserContent"] div[class*="st-key-nav_btn_"]:not([class*="logout"]) > div.stButton {{
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
}}

/* ── Button geometry ── */
div[class*="st-key-nav_btn_"]:not([class*="logout"]) button {{
    background-color: transparent !important;
    border: none !important;
    border-radius: 0px !important;
    box-shadow: none !important;
    width: 100% !important;
    margin: 1px 0 !important;
    height: auto !important;
    min-height: 62px !important;
    padding: 0 !important;
    text-align: left !important;
    display: flex !important;
    justify-content: flex-start !important;
    transition: background-color 0.2s ease-in-out;
}}

/* ── Button text paragraph ── */
div[class*="st-key-nav_btn_"]:not([class*="logout"]) button p {{
    color: #9ca3af !important;
    font-weight: 500 !important;
    font-size: 1.05rem !important;
    margin: 0 !important;
    padding: 16px 1rem 16px 20px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    text-align: left !important;
    width: 100% !important;
    transition: color 0.2s ease-in-out;
}}

/* ── Icon pseudo-element ── */
div[class*="st-key-nav_btn_"]:not([class*="logout"]) button p::before {{
    content: '';
    display: inline-block;
    flex-shrink: 0;
    width: 22px;
    height: 22px;
    margin-right: 20px;
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    filter: brightness(0) invert(0.65);
    transition: filter 0.2s ease-in-out;
}}

/* ── Asset bindings ── */
div.st-key-nav_btn_download button p::before {{
    background-image: url("data:image/png;base64,{icon_dl_b64}");
}}
div.st-key-nav_btn_sync button p::before {{
    background-image: url("data:image/png;base64,{icon_sync_b64}");
}}
div.st-key-nav_btn_settings button p::before {{
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z'%3E%3C/path%3E%3Ccircle cx='12' cy='12' r='3'%3E%3C/circle%3E%3C/svg%3E");
}}

/* ── Hover ── */
div[class*="st-key-nav_btn_"]:not([class*="logout"]) button:hover {{
    background-color: rgba(255, 255, 255, 0.04) !important;
}}
div[class*="st-key-nav_btn_"]:not([class*="logout"]) button:hover p {{
    color: #b8bcc3 !important;
}}
div[class*="st-key-nav_btn_"]:not([class*="logout"]) button:hover p::before {{
    filter: brightness(0) invert(0.85);
}}

/* ── Logout button ── */
div.st-key-nav_btn_logout button {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
    width: 38px !important;
    height: 38px !important;
    min-height: 38px !important;
    padding: 0 !important;
    border-radius: 8px !important;
    margin: 0 !important;
    position: relative !important;
}}
div.st-key-nav_btn_logout button > div {{
    display: none !important;
}}
div.st-key-nav_btn_logout button::before {{
    content: '';
    position: absolute !important;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 18px;
    height: 18px;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4'%3E%3C/path%3E%3Cpolyline points='16 17 21 12 16 7'%3E%3C/polyline%3E%3Cline x1='21' y1='12' x2='9' y2='12'%3E%3C/line%3E%3C/svg%3E") !important;
    background-position: center !important;
    background-repeat: no-repeat !important;
    background-size: contain !important;
    filter: brightness(0) invert(0.65) !important;
    transition: filter 0.2s ease-in-out;
}}
div.st-key-nav_btn_logout button:hover {{
    background-color: rgba(239, 68, 68, 0.1) !important;
}}
div.st-key-nav_btn_logout button:hover::before {{
    filter: brightness(0) saturate(100%) invert(67%) sepia(51%) saturate(2321%) hue-rotate(313deg) brightness(108%) contrast(98%) !important;
}}
/* Tooltip */
div.st-key-nav_btn_logout button::after {{
    content: 'Log out';
    position: absolute;
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
    background: #1e293b;
    color: #f8fafc;
    padding: 5px 10px;
    border-radius: 6px;
    font-size: 0.8rem;
    font-family: sans-serif;
    font-weight: 500;
    white-space: nowrap;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease-in-out, bottom 0.2s ease-in-out;
    border: 1px solid rgba(255, 255, 255, 0.1);
    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    z-index: 99999;
}}
div.st-key-nav_btn_logout button:hover::after {{
    opacity: 1;
    bottom: calc(100% + 10px);
}}

</style>
""")

    with st.container(border=False, key="sidebar_top"):
        # ── Header: icon + title + separator (single HTML block) ─────────
        st.html(f"""
<div style="display: flex; align-items: center; gap: 12px; padding: 25px 1rem 25px 20px;">
    <img src="data:image/png;base64,{icon_b64}"
         style="width: 42px; height: 42px; border-radius: 8px;
                box-shadow: 0 4px 10px rgba(0,0,0,0.3); display: block;" />
    <div style="display: flex; flex-direction: column; justify-content: center; height: 42px;">
        <span style="font-weight: 700; font-size: 1.25rem; color: #f3f4f6; line-height: 1; margin: 0;">
            Canvas Downloader
        </span>
    </div>
</div>
<hr style="margin: 0 0 10px 0; border: none; border-bottom: 1px solid rgba(255,255,255,0.08);" />
""")

        _render_authenticated_nav_top()

    _render_authenticated_nav_bottom(fetch_courses_fn)



def render_login_page(fetch_courses_fn):
    """Render the full-page, premium login portal in the main page body."""
    if st.session_state.get('is_authenticated'):
        return

    # ── Auto-load token (only once per session) ─────────────────────────
    if not st.session_state.get('token_loaded'):
        st.session_state['token_loaded'] = True
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding='utf-8') as f:
                    config = json.load(f)
                    st.session_state['api_url'] = config.get('api_url', '')

                    if 'concurrent_downloads' in config:
                        st.session_state['concurrent_downloads'] = config.get('concurrent_downloads', 5)

                    if 'debug_mode' in config:
                        st.session_state['debug_mode'] = config.get('debug_mode', False)

                    if 'enable_cbs_filters' in config:
                        st.session_state['enable_cbs_filters'] = config.get('enable_cbs_filters', False)

                    if 'error_log_enabled' in config:
                        st.session_state['error_log_enabled'] = config.get('error_log_enabled', False)

                    if 'max_file_size_enabled' in config:
                        st.session_state['max_file_size_enabled'] = config.get('max_file_size_enabled', False)
                    if 'max_file_size_mb' in config:
                        st.session_state['max_file_size_mb'] = int(config.get('max_file_size_mb', 500))

                    if 'notifications_enabled' in config:
                        st.session_state['notifications_enabled'] = config.get('notifications_enabled', True)

                    if 'use_12h_format' in config:
                        st.session_state['use_12h_format'] = config.get('use_12h_format', False)

                    if 'default_download_path' in config:
                        saved_default = config.get('default_download_path', '') or ''
                        st.session_state['default_download_path'] = saved_default
                        # Pre-fill download_path with the saved default on fresh session
                        import os as _os
                        from pathlib import Path as _Path
                        _downloads_default = str(_Path.home() / "Downloads")
                        current_path = st.session_state.get('download_path', '')
                        if saved_default and _os.path.isdir(saved_default) and current_path == _downloads_default:
                            st.session_state['download_path'] = saved_default

                    loaded_token = ''
                    # Unified keyring load for all platforms
                    try:
                        import keyring
                        keyring_user = st.session_state['api_url'] or 'default'
                        loaded_token = keyring.get_password(KEYRING_SERVICE, keyring_user) or ''
                    except Exception:
                        pass

                    # Legacy migration: macOS base64 token stored in JSON
                    if not loaded_token and config.get('mac_api_token', ''):
                        try:
                            loaded_token = base64.b64decode(
                                config['mac_api_token'].encode('utf-8')
                            ).decode('utf-8')
                            try:
                                import keyring
                                keyring_user = st.session_state['api_url'] or 'default'
                                keyring.set_password(KEYRING_SERVICE, keyring_user, loaded_token)
                                config.pop('mac_api_token', None)
                                with open(CONFIG_FILE, 'w', encoding='utf-8') as fw:
                                    json.dump(config, fw)
                            except Exception:
                                pass
                        except Exception:
                            pass

                    # Legacy migration: Windows plain-JSON token
                    if not loaded_token and config.get('api_token', ''):
                        loaded_token = config['api_token']
                        try:
                            import keyring
                            keyring_user = st.session_state['api_url'] or 'default'
                            keyring.set_password(KEYRING_SERVICE, keyring_user, loaded_token)
                            config.pop('api_token', None)
                            with open(CONFIG_FILE, 'w', encoding='utf-8') as fw:
                                json.dump(config, fw)
                        except Exception:
                            pass

                    st.session_state['api_token'] = loaded_token

                    if st.session_state['api_token']:
                        cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                        valid, msg = cm.validate_token()
                        if valid:
                            st.session_state['is_authenticated'] = True
                            st.session_state['user_name'] = msg.split(": ")[1] if ": " in msg else msg
                            st.rerun()
            except Exception:
                pass

    from ui_helpers import get_base64_image

    icon_b64 = get_base64_image("assets/icon.png")

    # Scoped physical volume styles for the main page login card
    st.html("""<style>
    /* Centered portal container */
    .login-portal-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        max-width: 480px;
        margin: 40px auto 0 auto;
        padding: 0 10px;
    }

    /* Branded Header */
    .login-brand-header {
        text-align: center;
        margin-bottom: 25px;
    }

    .login-brand-logo {
        width: 68px;
        height: 68px;
        border-radius: 14px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45), inset 0 1px 1px rgba(255, 255, 255, 0.15);
        margin-bottom: 12px;
        display: inline-block;
    }

    .login-brand-title {
        font-size: 1.8rem;
        font-weight: 800;
        color: #f1f5f9;
        letter-spacing: -0.02em;
        line-height: 1.1;
    }

    .login-brand-subtitle {
        font-size: 0.9rem;
        color: #64748b;
        margin-top: 6px;
    }

    /* The "Physical Volume" card tray */
    div[class*="st-key-login_card_wrapper"] {
        background: #151c24 !important; /* Shade or two lighter than #0e1117, teal-ish blue */
        border: none !important;
        border-radius: 12px !important;
        box-shadow: 0 0px 50px rgba(0, 0, 0, 0.5) !important;
        padding: 30px 24px !important;
        width: 100% !important;
    }

    div[class*="st-key-login_card_wrapper"] > div[data-testid="stVerticalBlockBorderWrapper"],
    div[class*="st-key-login_card_wrapper"] > div[data-testid="stVerticalBlock"] {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        padding: 0 !important;
    }

    /* Add borders around the input fields inside the card */
    div[class*="st-key-login_card_wrapper"] div[data-testid="stTextInput"] [data-baseweb="input"] {
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        background-color: rgba(0, 0, 0, 0.2) !important;
        border-radius: 6px !important;
        transition: border-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stTextInput"] [data-baseweb="input"]:focus-within {
        border-color: #1f77b4 !important;
        box-shadow: 0 0 0 2px rgba(31, 119, 180, 0.2) !important;
    }

    /* Style Streamlit's native help trigger button/icon next to the label */
    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] {
        display: flex !important;
        justify-content: flex-start !important;
        align-items: center !important;
        gap: 6px !important;
        width: 100% !important;
        position: relative !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] label {
        margin: 0 !important;
        flex: 0 0 auto !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: 0 !important;
        flex: 0 0 auto !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        margin: 0 !important;
        min-height: unset !important;
        min-width: unset !important;
        height: auto !important;
        width: auto !important;
        display: flex !important;
        align-items: center !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button [data-testid="stIconMaterial"],
    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button svg {
        display: none !important; /* Hide native icon */
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button::before {
        content: "";
        display: inline-block;
        width: 16px;
        height: 16px;
        background-color: rgba(255, 255, 255, 0.4) !important;
        -webkit-mask-image: url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPScxNicgaGVpZ2h0PScxNicgdmlld0JveD0nMCAwIDI0IDI0JyBmaWxsPSdub25lJyBzdHJva2U9J2N1cnJlbnRDb2xvcicgc3Ryb2tlLXdpZHRoPScyLjUnIHN0cm9rZS1saW5lY2FwPSdyb3VuZCcgc3Ryb2tlLWxpbmVqb2luPSdyb3VuZCc+PGNpcmNsZSBjeD0nMTInIGN5PScxMicgcj0nMTAnPjwvY2lyY2xlPjxwYXRoIGQ9J005LjA5IDlhMyAzIDAgMCAxIDUuODMgMWMwIDItMyAzLTMgMyc+PC9wYXRoPjxsaW5lIHgxPScxMicgeTE9JzE3JyB4Mj0nMTIuMDEnIHkyPScxNyc+PC9saW5lPjwvc3ZnPg==') !important;
        mask-image: url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPScxNicgaGVpZ2h0PScxNicgdmlld0JveD0nMCAwIDI0IDI0JyBmaWxsPSdub25lJyBzdHJva2U9J2N1cnJlbnRDb2xvcicgc3Ryb2tlLXdpZHRoPScyLjUnIHN0cm9rZS1saW5lY2FwPSdyb3VuZCcgc3Ryb2tlLWxpbmVqb2luPSdyb3VuZCc+PGNpcmNsZSBjeD0nMTInIGN5PScxMicgcj0nMTAnPjwvY2lyY2xlPjxwYXRoIGQ9J005LjA5IDlhMyAzIDAgMCAxIDUuODMgMWMwIDItMyAzLTMgMyc+PC9wYXRoPjxsaW5lIHgxPScxMicgeTE9JzE3JyB4Mj0nMTIuMDEnIHkyPScxNyc+PC9saW5lPjwvc3ZnPg==') !important;
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
        transition: background-color 0.15s ease !important;
    }

    div[class*="st-key-login_card_wrapper"] div[data-testid="stWidgetLabel"] div[data-testid="stTooltipHoverTarget"] button:hover::before {
        background-color: #60a5fa !important; /* Thicker and lighter blue color on hover */
    }

    /* Native Streamlit Tooltip Overrides */
    div[data-baseweb="tooltip"],
    div[data-baseweb="popover"] {
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        margin: 0 !important;
        max-height: none !important;
        height: auto !important;
        overflow: visible !important;
    }

    div[role="tooltip"] {
        background-color: #181c20 !important; /* Neutral dark grey */
        border: 1px solid rgba(255, 255, 255, 0.15) !important; /* Clean white border */
        border-radius: 8px !important;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5) !important;
        padding: 20px !important; /* Uniform, harmonious padding on all sides */
        width: 320px !important; /* Fixed elegant width */
        box-sizing: border-box !important;
        max-height: none !important;
        height: auto !important;
        overflow: visible !important;
    }

    div[role="tooltip"] * {
        max-height: none !important;
        height: auto !important;
        overflow: visible !important;
    }

    div[role="tooltip"] div,
    div[role="tooltip"] span {
        margin: 0 !important;
        padding: 0 !important;
    }

    div[role="tooltip"] p {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 0.85rem !important;
        line-height: 1.5 !important;
        color: #ffffff !important;
        margin: 0 !important; /* Reset margins on text lines for absolute symmetry */
        padding: 0 !important;
    }

    div[role="tooltip"] p + p {
        margin-top: 14px !important; /* Spacing between sections */
    }

    .login-brand-header-separator {
        width: 160px !important;
        height: 1px !important;
        background-color: rgba(255, 255, 255, 0.12) !important;
        margin: 16px auto 12px auto !important;
    }

    .login-github-header-tag {
        margin-top: 0px !important;
        margin-bottom: 28px !important; /* Spacing below the github tag to the login form */
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 16px !important; /* Spacing between the tags */
        width: 100% !important;
    }

    .github-link {
        display: inline-flex !important;
        align-items: center !important;
        gap: 6px !important;
        color: #64748b !important;
        text-decoration: none !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        transition: color 0.2s ease-in-out !important;
    }

    .github-link:hover {
        color: #f1f5f9 !important;
    }

    .github-icon {
        opacity: 0.85 !important;
    }

    .login-page-security-footer {
        font-size: 0.84rem !important;
        color: #64748b !important;
        text-align: center !important;
        margin-top: 36px !important;
        margin-bottom: 4px !important;
        max-width: 480px !important;
        margin-left: auto !important;
        margin-right: auto !important;
        line-height: 1.55 !important;
        display: flex !important;
        align-items: flex-start !important;
        justify-content: center !important;
        gap: 8px !important;
    }

    .security-shield-icon {
        color: #8a99ad !important;
        flex-shrink: 0 !important;
        margin-top: 2px !important;
        opacity: 0.8 !important;
    }

    .login-form-title {
        font-size: 1.3rem;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: 20px;
        letter-spacing: -0.01em;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        padding-bottom: 12px;
    }

    /* Submit Button styling: Solid Blue Physical Volume matching Analyze, Review & Sync */
    div.st-key-login_submit_btn button {
        background-color: #1f77b4 !important;
        border: none !important;
        border-radius: 6px !important;
        color: #ffffff !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        height: 3.2em !important;
        min-height: 3.2em !important;
        width: 100% !important;
        transition: background-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }

    div.st-key-login_submit_btn button:hover {
        background-color: #2b8cbe !important;
        box-shadow: 0 4px 15px rgba(31, 119, 180, 0.2),
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }

    /* RECURSIVE CENTERING: START - Universal child selector */
    div.st-key-login_submit_btn button > div,
    div.st-key-login_submit_btn button > div > p {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-align: center !important;
        width: 100% !important;
        height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div.st-key-login_submit_btn button p {
        font-size: 1rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
    }

    /* Scoped styling for help expanders */
    div[class*="st-key-login_help_expanders"] {
        max-width: 480px !important;
        margin: 0 auto !important;
        width: 100% !important;
    }

    /* Remove borders, backgrounds, and shadows from expanders inside this container */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        margin-bottom: 0px !important;
        padding: 0 !important;
    }

    /* Target details and summary to remove all borders/backgrounds */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] details {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        padding-left: 0px !important;
        padding-right: 0px !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 8px !important;
        width: 100% !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary > * {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        flex-grow: 0 !important;
        width: auto !important;
        margin: 0 !important;
        gap: 8px !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary > * > * {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        flex-grow: 0 !important;
        width: auto !important;
        margin: 0 !important;
    }

    /* Style the summary text inside modern Streamlit expander */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary p {
        color: #94a3b8 !important; /* Elegant muted color */
        font-weight: 500 !important;
        transition: color 0.2s ease-in-out !important;
        text-align: center !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary:hover p {
        color: #f1f5f9 !important; /* Brighter on hover */
    }

    /* Style the chevron arrow inside help expanders to match the grey text */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary svg {
        color: #94a3b8 !important;
        transition: color 0.1s ease-in-out !important;
    }

    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] summary:hover svg {
        color: #f1f5f9 !important;
    }

    /* Turn header text & chevron white when help expanders are open/expanded */
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] details[open] summary p {
        color: #ffffff !important;
    }
    div[class*="st-key-login_help_expanders"] div[data-testid="stExpander"] details[open] summary svg {
        color: #ffffff !important;
    }

    /* Reset Streamlit flex block gap inside the footer container for precise spacing control */
    div[class*="st-key-login_footer_container"] div[data-testid="stVerticalBlock"] {
        gap: 0px !important;
    }

    /* Scoped styling for the privacy expander */
    div[class*="st-key-login_privacy_expander"] {
        max-width: 420px !important;
        margin: 0 auto !important;
        width: 100% !important;
    }

    .login-privacy-separator {
        width: 160px !important;
        height: 1px !important;
        background-color: rgba(255, 255, 255, 0.08) !important;
        margin: 18px auto !important; 
    }

    .login-privacy-separator-bottom {
        margin-top: 0px !important; /* Pull visually closer to the privacy expander above it */
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        margin-bottom: 0px !important;
        padding: 0 !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] details {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        padding-left: 0px !important;
        padding-right: 0px !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 8px !important;
        width: 100% !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary > * {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        flex-grow: 0 !important;
        width: auto !important;
        margin: 0 !important;
        gap: 8px !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary > * > * {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        flex-grow: 0 !important;
        width: auto !important;
        margin: 0 !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary p {
        font-size: 0.86rem !important;
        color: #64748b !important; /* Elegant muted slate color */
        font-weight: 600 !important; /* Semi-bold */
        transition: color 0.2s ease-in-out !important;
        text-align: center !important;
        width: 100% !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary p::before {
        content: "" !important;
        display: inline-block !important;
        width: 14px !important;
        height: 14px !important;
        margin-right: 6px !important;
        background-color: currentColor !important;
        -webkit-mask: url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2024%2024%22%3E%3Cpath%20d%3D%22M12%2022s8-4%208-10V5l-8-3-8%203v7c0%206%208%2010%208%2010z%22%2F%3E%3C%2Fsvg%3E') no-repeat center / contain !important;
        mask: url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2024%2024%22%3E%3Cpath%20d%3D%22M12%2022s8-4%208-10V5l-8-3-8%203v7c0%206%208%2010%208%2010z%22%2F%3E%3C%2Fsvg%3E') no-repeat center / contain !important;
        flex-shrink: 0 !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary:hover p {
        color: #f1f5f9 !important; /* Brighter slate on hover */
    }

    /* Style the chevron arrow inside the privacy expander to match the grey text */
    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary svg {
        color: #64748b !important;
        transition: color 0.1s ease-in-out !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] summary:hover svg {
        color: #f1f5f9 !important;
    }

    /* Turn header text, mask shield icon, & chevron white when privacy expander is open/expanded */
    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] details[open] summary p {
        color: #ffffff !important;
    }
    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] details[open] summary svg {
        color: #ffffff !important;
    }

    div[class*="st-key-login_privacy_expander"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] {
        font-size: 0.88rem !important;
        line-height: 1.55 !important;
        color: #b8c5d6 !important;
    }

    /* Custom styles for precise list items and spacing */
    .privacy-list-item {
        display: flex !important;
        align-items: flex-start !important;
        justify-content: flex-start !important;
        gap: 8px !important;
        margin-bottom: 12px !important;
        text-align: left !important;
    }
    .privacy-list-icon {
        color: #8a99ad !important;
        flex-shrink: 0 !important;
        margin-top: 3px !important;
        width: 14px !important;
        height: 14px !important;
        overflow: visible !important;
    }
    .privacy-list-content {
        flex: 1 !important;
    }
    .privacy-list-title {
        font-weight: 700 !important;
        color: #b8c5d6 !important; /* Soft grey aesthetic */
        font-size: 0.88rem !important;
        margin-bottom: 1px !important;
    }
    .privacy-list-desc {
        font-size: 0.88rem !important;
        line-height: 1.45 !important;
        color: #b8c5d6 !important; /* Matches title color precisely */
    }
    .privacy-list-desc a {
        color: #1f77b4 !important;
        text-decoration: none !important;
        font-weight: 600 !important;
        transition: color 0.2s ease-in-out !important;
    }
    .privacy-list-desc a:hover {
        color: #2ba2ec !important;
        text-decoration: underline !important;
    }
    .login-student-signature {
        text-align: center !important;
        font-size: 0.78rem !important;
        color: #475569 !important; /* Soft, very muted slate color */
        margin-top: 0px !important; /* Matches exactly the 18px bottom margin of the separator above it */
        margin-bottom: 20px !important;
        font-weight: 500 !important;
        letter-spacing: 0.01em !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 6px !important;
        transition: color 0.2s ease-in-out !important;
    }
    .login-student-signature:hover {
        color: #64748b !important; /* Slightly brighter on hover */
    }
    .signature-heart-icon {
        color: #f97316 !important; /* Premium warm orange colored heart */
        opacity: 0.8 !important;
        flex-shrink: 0 !important;
        overflow: visible !important;
        transition: transform 0.2s ease-in-out, opacity 0.2s ease-in-out !important;
    }
    .login-student-signature:hover .signature-heart-icon {
        transform: scale(1.1) !important; /* Delicate heart scale pulse on hover */
        opacity: 1 !important;
    }
    </style>""")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        # Portal container
        st.markdown(f"""
        <div class="login-portal-container">
            <div class="login-brand-header">
                <img class="login-brand-logo" src="data:image/png;base64,{icon_b64}"/>
                <div class="login-brand-title">Canvas Downloader</div>
                <div class="login-brand-subtitle">Your Canvas courses.<br/>Downloaded. Up to date. Optimized for AI.</div>
                <div class="login-brand-header-separator"></div>
                <div class="login-github-header-tag">
                    <a href="https://github.com/birkls/Canvas_LMS_batch_file_downloader" target="_blank" class="github-link">
                        <svg class="github-icon" viewBox="0 0 16 16" width="14" height="14"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                        View Source Code on GitHub
                    </a>
                    <a href="https://birkls.github.io/Canvas_LMS_batch_file_downloader/" target="_blank" class="github-link">
                        <svg class="github-icon" viewBox="0 0 16 16" width="14" height="14"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                        Go to website
                    </a>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.container(key="login_card_wrapper"):
            st.markdown('<div class="login-form-title">Log in to Canvas Downloader</div>', unsafe_allow_html=True)
            
            with st.form("auth_form", clear_on_submit=False, border=False):
                st.text_input(
                    'Your Canvas URL',
                    key="url_input",
                    placeholder="https://your-school.instructure.com"
                )

                st.text_input(
                    'Your Canvas API Token',
                    type="password",
                    key="token_input",
                    help=(
                        "**Why is this needed?**  \n"
                        "This token acts as a private key that allows the app to fetch your course files directly from your school's Canvas instance, which it connects to.\n\n"
                        "**Is it safe?**  \n"
                        "Yes! Your token is stored securely on your device, in your operating system."
                    )
                )

                submitted = st.form_submit_button('Log In', type="primary", use_container_width=True, key="login_submit_btn")

            if submitted:
                input_url = st.session_state.url_input.strip()
                input_token = st.session_state.token_input.strip()

                st.session_state['api_url'] = input_url
                st.session_state['api_token'] = input_token

                manager = CanvasManager(input_token, input_url)
                is_valid, message = manager.validate_token()

                if is_valid:
                    st.session_state['api_token'] = input_token
                    st.session_state['api_url'] = manager.api_url
                    st.session_state['is_authenticated'] = True
                    st.session_state['user_name'] = message.split(": ")[1] if ": " in message else message

                    # Setup base config data
                    config_data = {}
                    if os.path.exists(CONFIG_FILE):
                        try:
                            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                                config_data = json.load(f)
                        except Exception:
                            pass

                    config_data['api_url'] = st.session_state['api_url']
                    if 'concurrent_downloads' in st.session_state:
                        config_data['concurrent_downloads'] = st.session_state['concurrent_downloads']
                    if 'debug_mode' in st.session_state:
                        config_data['debug_mode'] = st.session_state['debug_mode']

                    # Save token to OS keyring (macOS Keychain / Windows Credential Manager)
                    try:
                        import keyring
                        keyring_user = st.session_state['api_url'] or 'default'
                        keyring.set_password(KEYRING_SERVICE, keyring_user, st.session_state['api_token'])
                        # Ensure no legacy insecure fields remain in the config JSON
                        config_data.pop('mac_api_token', None)
                        config_data.pop('api_token', None)
                    except Exception as e:
                        st.warning(f"Could not save token to system keyring: {e}. Token will not persist across sessions.")

                    try:
                        _tmp_config = CONFIG_FILE + '.tmp'
                        with open(_tmp_config, 'w', encoding='utf-8') as f:
                            json.dump(config_data, f)
                            f.flush()
                            os.fsync(f.fileno())
                        os.replace(_tmp_config, CONFIG_FILE)
                    except Exception as e:
                        # Clean up orphaned temp file on failure
                        try:
                            if os.path.exists(_tmp_config):
                                os.unlink(_tmp_config)
                        except OSError:
                            pass
                        st.error(f"Could not save config: {e}")

                    st.rerun()
                else:
                    st.error(message)

            pass

        # Standardized expandable help vertically below the card
        st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
        with st.container(key="login_help_expanders"):
            with st.expander('How to find your true Canvas URL?'):
                st.markdown(
                    "**Crucial Step:** You must input the *actual* Canvas URL, not your university's login portal.\n\n"
                    "**How to find it:**\n"
                    "1. Log in to Canvas in your web browser.\n"
                    "2. Examine the address bar **after** logging in.\n"
                    "3. It often looks like `https://schoolname.instructure.com` (even if you typed `canvas.school.edu` to get there).\n"
                    "4. Copy the base portion of the URL (e.g., `https://school.instructure.com`) and paste it here.\n"
                )

            with st.expander('How to get an API Access Token?'):
                st.markdown(
                    "1. Log into Canvas and click on your **Account** in the left navigation.\n"
                    "2. Select **Settings** from the account menu.\n"
                    "3. Scroll down to the **Approved Integrations** section.\n"
                    "4. Click the button labeled **+ New Access Token**.\n"
                    "5. Set a purpose (e.g., 'Canvas Downloader') and click **Generate Token**.\n"
                    "6. Copy the long generated string immediately (it will only be displayed once) and paste it here.\n"
                )

        # Open a unified footer container to completely eliminate nested Streamlit block gaps!
        with st.container(key="login_footer_container"):
            # Elegant subtle separator between help section and security footer
            st.markdown("<div class='login-privacy-separator'></div>", unsafe_allow_html=True)

            with st.container(key="login_privacy_expander"):
                with st.expander('100% Local & Secure'):
                    st.markdown(
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Native Encryption</div>"
                        "<div class='privacy-list-desc'>Your API token is securely stored in your operating system's native keychain (Windows Credential Manager / macOS Keychain), never in plain text.</div>"
                        "</div>"
                        "</div>"
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Direct Connection</div>"
                        "<div class='privacy-list-desc'>The app communicates exclusively and directly with the Canvas URL you provide. No proxies or intermediaries. Requests are sent to Canvas to read and fetch files from your Canvas courses, nothing else.</div>"
                        "</div>"
                        "</div>"
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8 0-1.85.63-3.55 1.69-4.9L16.9 18.31C15.55 19.37 13.85 20 12 20zm6.31-4.69L7.69 4.69C9.04 3.63 10.74 3 12 3c4.41 0 8 3.59 8 8 0 1.85-.63 3.55-1.69 4.9z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Zero Telemetry</div>"
                        "<div class='privacy-list-desc'>No tracking, no analytics, and absolutely no third-party data collection.</div>"
                        "</div>"
                        "</div>"
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-6 10H6v-2h8v2zm4-4H6v-2h12v2z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Isolated File Access</div>"
                        "<div class='privacy-list-desc'>The application acts as a one-way street. It only downloads course materials into the specific destination folder you choose. It does not scan, read, or upload any personal files from your computer. Your credentials and data remain entirely under your control and are never shared with external servers.</div>"
                        "</div>"
                        "</div>"
                        "<div class='privacy-list-item'>"
                        "<svg class='privacy-list-icon' viewBox='-2 -2 28 28' width='14' height='14'><path fill='currentColor' d='M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z'/></svg>"
                        "<div class='privacy-list-content'>"
                        "<div class='privacy-list-title'>Open Source & Verifiable</div>"
                        "<div class='privacy-list-desc'>Trust shouldn't be blind. The source code is entirely public, allowing anyone to independently verify these security standards. "
                        "<a href='https://github.com/birkls/Canvas_LMS_batch_file_downloader' target='_blank'>View Source Code on GitHub</a></div>"
                        "</div>"
                        "</div>",
                        unsafe_allow_html=True
                    )

            # Elegant subtle separator between security footer and student footer
            st.markdown("<div class='login-privacy-separator login-privacy-separator-bottom'></div>", unsafe_allow_html=True)

            # Delicate humanized student footer with SVG heart hover micro-animation
            st.markdown(
                "<div class='login-student-signature'>"
                "For students, by a student"
                "<svg class='signature-heart-icon' viewBox='-2 -2 28 28' width='14' height='14'>"
                "<path fill='currentColor' d='M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z'/>"
                "</svg>"
                "</div>",
                unsafe_allow_html=True
            )


# ─── Private helpers ────────────────────────────────────────────────────


def _render_authenticated_nav_top():
    """Render the top part of the authenticated sidebar: navigation buttons."""
    # ── Navigation buttons ─────────────────────────────────────────
    mode = st.session_state.get('current_mode', 'download')
    step = st.session_state.get('step', 1)

    # Expose current mode+step for the JS overlay logic (read via doc.getElementById).
    st.html(f"<span id='cdp_nav_state' data-mode='{mode}' data-step='{step}' style='display:none;position:absolute;pointer-events:none'></span>")

    # Active-state CSS is dynamic (depends on session state) - inject separately
    if mode in ['download', 'sync']:
        active_key = f"st-key-nav_btn_{mode}"
        st.html(f"""<style>
        section[data-testid="stSidebar"] div.{active_key} button {{ background-color: rgba(255, 255, 255, 0.10) !important; }}
        section[data-testid="stSidebar"] div.{active_key} button p {{ color: #ffffff !important; font-weight: 600 !important; }}
        section[data-testid="stSidebar"] div.{active_key} button p::before,
        section[data-testid="stSidebar"] div.{active_key} button:hover p::before {{ filter: brightness(0) invert(1) !important; }}
        section[data-testid="stSidebar"] div.{active_key} button:hover {{ background-color: rgba(255, 255, 255, 0.10) !important; cursor: default !important; }}
        section[data-testid="stSidebar"] div.{active_key} button:hover p {{ color: #ffffff !important; }}
        </style>""")

    # Download mode button — always navigates to download step 1.
    if st.button('Download Courses', use_container_width=True, key="nav_btn_download"):
        if mode != 'download' or step != 1:
            from core.state_registry import cleanup_download_state
            cleanup_download_state()
            st.session_state['current_mode'] = 'download'
            st.session_state['sync_mode'] = False
            st.session_state['sync_pairs'] = []
            st.session_state.pop('sync_pairs_loaded', None)
            st.rerun()

    # Sync mode button — always navigates to sync step 1.
    if st.button('Sync Local Folders', use_container_width=True, key="nav_btn_sync"):
        if mode != 'sync' or step != 1:
            from core.state_registry import cleanup_sync_state
            cleanup_sync_state()
            st.session_state['current_mode'] = 'sync'
            st.session_state['step'] = 1
            st.session_state['sync_mode'] = True
            st.session_state['sync_pairs'] = []
            st.session_state.pop('sync_pairs_loaded', None)
            st.rerun()


def _render_authenticated_nav_bottom(fetch_courses_fn):
    """Render the bottom part of the authenticated sidebar"""
    import os
    import json
    import platform


    # ── Global Settings dialog ─────────────────────────────────────
    def _stg_ico(path_d):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{path_d}" fill="#a0aec0"/></svg>'
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

    _stg_i_speed  = _stg_ico("M7 2v11h3v9l7-12h-4l4-8z")
    _stg_i_filter = _stg_ico("M4.25 5.61C6.27 8.2 10 13 10 13v6c0 .55.45 1 1 1h2c.55 0 1-.45 1-1v-6s3.72-4.8 5.74-7.39c.51-.66.04-1.61-.79-1.61H5.04c-.83 0-1.3.95-.79 1.61z")
    _stg_i_folder = _stg_ico("M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z")
    _stg_i_bell   = _stg_ico("M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z")
    _stg_i_grad   = _stg_ico("M5 13.18v4L12 21l7-3.82v-4L12 17l-7-3.82zM12 3L1 9l11 6 9-4.91V17h2V9L12 3z")
    _stg_i_errlog = _stg_ico("M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 9h-2v2h2v2h-2v2h-2v-2H9v-2h2v-2H9V9h2V7h2v2h2v2zM13 9V3.5L18.5 9H13z")
    _stg_i_clock  = _stg_ico("M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z")

    @st.dialog("\u200b", width="large")
    def _global_settings_dialog():
        st.html("""<style>
        div[data-testid="stDialog"] button[aria-label="Close"] { display: none !important; }

        /* Tight dialog body padding */
        div[data-testid="stDialog"] [data-testid="stDialogScrollableBody"] {
            padding-top: 0.1rem !important; padding-bottom: 0.25rem !important;
        }
        /* Tight global vertical gap */
        div[data-testid="stDialog"] [data-testid="stVerticalBlock"] { gap: 0.3rem !important; }

        /* ── Cards ── */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] [data-testid="stVerticalBlockBorderWrapper"] {
            background: #2D3248 !important;
            border: 1px solid rgba(255,255,255,0.14) !important;
            border-radius: 10px !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.35) !important;
            position: relative !important;
            padding: 11px !important;
        }
        div[data-testid="stDialog"] div[class*="st-key-stg_card_"] [data-testid="stVerticalBlock"] {
            gap: 0.25rem !important;
        }

        /* ── Equal height download cards (HACKS doc flex chain) ── */
        div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-stg_card_speed"]) { flex: 1 !important; }
        div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-stg_card_maxsize"]) { flex: 1 !important; }
        div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-stg_card_errlog"]) { flex: 1 !important; }
        div[class*="st-key-stg_card_speed"] { flex: 1 !important; display: flex !important; flex-direction: column !important; }
        div[class*="st-key-stg_card_maxsize"] { flex: 1 !important; display: flex !important; flex-direction: column !important; }
        div[class*="st-key-stg_card_errlog"] { flex: 1 !important; display: flex !important; flex-direction: column !important; }
        div[class*="st-key-stg_card_speed"] [data-testid="stVerticalBlockBorderWrapper"],
        div[class*="st-key-stg_card_maxsize"] [data-testid="stVerticalBlockBorderWrapper"],
        div[class*="st-key-stg_card_errlog"] [data-testid="stVerticalBlockBorderWrapper"] { height: 100% !important; }
        div[data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has([class*="st-key-stg_card_speed"]) {
            align-items: stretch !important;
        }

        /* ── Equal height preference cards ── */
        div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-stg_card_sound"]) { flex: 1 !important; }
        div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-stg_card_cbs"]) { flex: 1 !important; }
        div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-stg_card_time"]) { flex: 1 !important; }
        div[class*="st-key-stg_card_sound"] { flex: 1 !important; display: flex !important; flex-direction: column !important; }
        div[class*="st-key-stg_card_cbs"] { flex: 1 !important; display: flex !important; flex-direction: column !important; }
        div[class*="st-key-stg_card_time"] { flex: 1 !important; display: flex !important; flex-direction: column !important; }
        div[class*="st-key-stg_card_sound"] [data-testid="stVerticalBlockBorderWrapper"],
        div[class*="st-key-stg_card_cbs"] [data-testid="stVerticalBlockBorderWrapper"],
        div[class*="st-key-stg_card_time"] [data-testid="stVerticalBlockBorderWrapper"] { height: 100% !important; }
        div[data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has([class*="st-key-stg_card_sound"]) {
            align-items: stretch !important;
        }

        /* ── Toggles ── */
        div[data-testid="stDialog"] [data-testid="stToggle"] { width: 100% !important; }
        div[data-testid="stDialog"] [data-testid="stToggle"] label {
            display: flex !important; flex-direction: row-reverse !important;
            justify-content: space-between !important; align-items: center !important;
            width: 100% !important; padding: 2px 0 0 0 !important; cursor: pointer !important;
            font-size: 0.66rem !important; color: #64748b !important; font-weight: 400 !important;
        }
        div[data-testid="stDialog"] [data-testid="stToggle"] label > div,
        div[data-testid="stDialog"] [data-testid="stToggle"] label > div p,
        div[data-testid="stDialog"] [data-testid="stToggle"] label p,
        div[data-testid="stDialog"] [data-testid="stToggle"] label > p,
        div[data-testid="stDialog"] [data-testid="stToggle"] p {
            font-size: 0.66rem !important; color: #64748b !important;
            font-weight: 400 !important; margin: 0 !important; line-height: 1.3 !important;
        }

        /* ── Number input ── */
        div[data-testid="stDialog"] [data-testid="stNumberInput"] { margin-top: 4px !important; }
        div[data-testid="stDialog"] [data-testid="stNumberInput"] label p {
            font-size: 0.78rem !important; color: #64748b !important;
        }
        /* Dim the whole number input block when disabled (Skip large files toggle off) */
        div[data-testid="stDialog"] div[class*="st-key-stg_card_maxsize"] [data-testid="stNumberInput"]:has(input:disabled) {
            opacity: 0.35 !important;
            pointer-events: none !important;
        }

        /* ── Folder buttons ── */
        div[data-testid="stDialog"] div.st-key-stg_btn_pick button,
        div[data-testid="stDialog"] div.st-key-stg_btn_clear button {
            background: rgba(255,255,255,0.04) !important;
            border: 1px solid rgba(255,255,255,0.10) !important;
            min-height: unset !important;
            height: auto !important;
            padding-top: 5px !important;
            padding-bottom: 5px !important;
            font-size: 0.8rem !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_pick button:hover,
        div[data-testid="stDialog"] div.st-key-stg_btn_clear button:hover {
            background: rgba(255,255,255,0.08) !important;
            border-color: rgba(255,255,255,0.18) !important;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_pick button::before {
            content: ''; display: inline-block; width: 14px; height: 14px;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'%3E%3C%2Fpath%3E%3C%2Fsvg%3E");
            background-size: contain; background-repeat: no-repeat;
            margin-right: 7px; vertical-align: middle;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_clear button::before {
            content: ''; display: inline-block; width: 13px; height: 13px;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='18' y1='6' x2='6' y2='18'%3E%3C%2Fline%3E%3Cline x1='6' y1='6' x2='18' y2='18'%3E%3C%2Fline%3E%3C%2Fsvg%3E");
            background-size: contain; background-repeat: no-repeat;
            margin-right: 7px; vertical-align: middle;
        }
        </style>""")

        st.markdown("""
<div style="display:flex;align-items:center;gap:10px;margin-top:-70px;">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#e2e8f0" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
<span style="font-size:1.6rem;font-weight:600;color:#f1f5f9;letter-spacing:-0.01em;">Settings</span>
</div>
""", unsafe_allow_html=True)

        with st.container(height=620, border=False):

            # ── DOWNLOAD ──────────────────────────────────────────────
            st.html("""<div style="padding:2px 0 1px 0;"><span style="font-size:0.7rem;font-weight:800;text-transform:uppercase;letter-spacing:0.12em;color:#e2e8f0;">DOWNLOAD</span></div>""")

            _dc1, _dc2, _dc3 = st.columns(3)
            with _dc1:
                with st.container(border=True, key="stg_card_speed"):
                    st.html(f"""<div style="padding:0 0 4px 0;"><div style="display:flex;align-items:center;gap:7px;margin-bottom:3px;margin-top:-5px;"><img src="{_stg_i_speed}" width="18" height="18" style="flex-shrink:0;"><span style="font-size:1.1rem;font-weight:600;color:#e2e8f0;">Simultaneous downloads</span></div><div style="font-size:0.78rem;color:#94a3b8;line-height:1.4;margin-bottom:4px;">Choose how many files download at once. Higher values may increase download speed.</div><div style="font-size:0.75rem;color:#f59e0b;line-height:1.3;">Lower this if you encounter download issues.<br>Default = 5.</div></div>""")
                    temp_max = st.slider("Speed", min_value=1, max_value=15, value=st.session_state.get('concurrent_downloads', 5), key="temp_max_downloads", label_visibility="collapsed")
            with _dc2:
                with st.container(border=True, key="stg_card_maxsize"):
                    st.html(f"""<div style="padding:0 0 4px 0;"><div style="display:flex;align-items:center;gap:7px;margin-bottom:3px;margin-top:-5px;"><img src="{_stg_i_filter}" width="18" height="18" style="flex-shrink:0;"><span style="font-size:1.1rem;font-weight:600;color:#e2e8f0;">Skip large files</span></div><div style="font-size:0.78rem;color:#94a3b8;line-height:1.4;">Skip files above a set size - ensures quick downloads and prevents large files from bloating your drive.</div></div>""")
                    temp_size_enabled = st.toggle("Enable limit", value=st.session_state.get('max_file_size_enabled', False), key="temp_max_size_enabled")
                    temp_size_mb = st.number_input("Max size (MB)", min_value=1, max_value=100000, step=50, value=int(st.session_state.get('max_file_size_mb', 500)), key="temp_max_size_mb", disabled=not temp_size_enabled)
            with _dc3:
                with st.container(border=True, key="stg_card_errlog"):
                    st.html(f"""<div style="padding:0 0 4px 0;"><div style="display:flex;align-items:center;gap:7px;margin-bottom:3px;margin-top:-5px;"><img src="{_stg_i_errlog}" width="18" height="18" style="flex-shrink:0;"><span style="font-size:1.1rem;font-weight:600;color:#e2e8f0;">Error log file</span></div><div style="font-size:0.78rem;color:#94a3b8;line-height:1.4;">Create a <code style="font-size:0.72rem;background:rgba(255,255,255,0.08);padding:1px 4px;border-radius:3px;">download_errors.txt</code> summarizing any failed downloads or conversion errors in the output folder.</div></div>""")
                    temp_error_log = st.toggle("Create error log", value=st.session_state.get('error_log_enabled', False), key="temp_error_log_enabled")

            # ── SAVE FOLDER ───────────────────────────────────────────
            st.html("""<div style="padding:8px 0 1px 0;"><span style="font-size:0.7rem;font-weight:800;text-transform:uppercase;letter-spacing:0.12em;color:#e2e8f0;">SAVE FOLDER</span></div>""")

            with st.container(border=True, key="stg_card_path"):
                st.html(f"""<div style="padding:0 0 4px 0;"><div style="display:flex;align-items:center;gap:7px;margin-bottom:3px;margin-top:-5px;"><img src="{_stg_i_folder}" width="18" height="18" style="flex-shrink:0;"><span style="font-size:1.1rem;font-weight:600;color:#e2e8f0;">Default save location</span></div><div style="font-size:0.78rem;color:#94a3b8;line-height:1.4;">Pick the default output folder for all downloads, so you don't have to change it manually every time. Application default = Downloads folder.</div></div>""")

                if '_temp_default_path' not in st.session_state:
                    st.session_state['_temp_default_path'] = st.session_state.get('default_download_path', '') or ''

                _display_path = st.session_state['_temp_default_path'] or "Set to default: Downloads folder"
                _esc_path = (_display_path.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;").replace('"', "&quot;"))
                st.html(f"""<div style="padding:0 0 6px 0;"><div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.1);border-radius:7px;padding:6px 12px;font-size:0.79rem;color:rgba(255,255,255,0.45);font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.5;">{_esc_path}</div></div>""")

                _pc1, _pc2 = st.columns([3, 1])
                with _pc1:
                    if st.button("Choose Folder", key="stg_btn_pick", use_container_width=True):
                        from ui_helpers import native_folder_picker
                        picked = native_folder_picker(initial_dir=st.session_state.get('_temp_default_path') or None)
                        if picked:
                            st.session_state['_temp_default_path'] = picked
                            st.session_state['_stg_reopen_dialog'] = True
                            st.rerun(scope="app")
                with _pc2:
                    if st.button("Clear", key="stg_btn_clear", use_container_width=True,
                                 disabled=not st.session_state['_temp_default_path']):
                        st.session_state['_temp_default_path'] = ''
                        st.rerun(scope="app")

            # ── PREFERENCES ───────────────────────────────────────────
            st.html("""<div style="padding:8px 0 1px 0;"><span style="font-size:0.7rem;font-weight:800;text-transform:uppercase;letter-spacing:0.12em;color:#e2e8f0;">PREFERENCES</span></div>""")

            _p1, _p2, _p3 = st.columns(3)
            with _p1:
                with st.container(border=True, key="stg_card_sound"):
                    st.html(f"""<div style="padding:0 0 4px 0;"><div style="display:flex;align-items:center;gap:7px;margin-bottom:3px;margin-top:-5px;"><img src="{_stg_i_bell}" width="18" height="18" style="flex-shrink:0;"><span style="font-size:1.1rem;font-weight:600;color:#e2e8f0;">Notifications</span></div><div style="font-size:0.78rem;color:#94a3b8;line-height:1.4;">Get a sound and a native notification when a download or sync finishes, so you can focus on what matters.</div></div>""")
                    temp_notifications = st.toggle("Enable notifications", value=st.session_state.get('notifications_enabled', True), key="temp_notifications_enabled")
            with _p2:
                with st.container(border=True, key="stg_card_cbs"):
                    st.html(f"""<div style="padding:0 0 4px 0;"><div style="display:flex;align-items:center;gap:7px;margin-bottom:3px;margin-top:-5px;"><img src="{_stg_i_grad}" width="18" height="18" style="flex-shrink:0;"><span style="font-size:1.1rem;font-weight:600;color:#e2e8f0;">CBS filters</span></div><div style="font-size:0.78rem;color:#94a3b8;line-height:1.4;">Adds course type, semester, and year filters to all course lists. Only relevant for CBS students.</div></div>""")
                    temp_cbs = st.toggle("Enable CBS filters", value=st.session_state.get('enable_cbs_filters', False), key="temp_cbs_filters")
            with _p3:
                with st.container(border=True, key="stg_card_time"):
                    st.html(f"""<div style="padding:0 0 4px 0;"><div style="display:flex;align-items:center;gap:7px;margin-bottom:3px;margin-top:-5px;"><img src="{_stg_i_clock}" width="18" height="18" style="flex-shrink:0;"><span style="font-size:1.1rem;font-weight:600;color:#e2e8f0;">Time format</span></div><div style="font-size:0.78rem;color:#94a3b8;line-height:1.4;">Display all times in 12-hour AM/PM format instead of the default 24-hour clock.</div></div>""")
                    temp_time_12h = st.toggle("Use 12-hour format", value=st.session_state.get('use_12h_format', False), key="temp_use_12h_format")

        # ── Sticky footer ─────────────────────────────────────────────
        st.html("""<div style="padding:6px 0 0 0;"><hr style="margin:0;border:none;border-top:1px solid rgba(255,255,255,0.08);"/></div><div style="padding:6px 0 0 0;"></div>""")

        c_cancel, c_save = st.columns([1, 1])
        with c_cancel:
            if st.button("Cancel", use_container_width=True):
                st.session_state.pop('_temp_default_path', None)
                st.rerun(scope="app")
        with c_save:
            if st.button("Save Settings", type="primary", use_container_width=True):
                new_default_path = st.session_state.get('_temp_default_path', '') or ''
                prev_default_path = st.session_state.get('default_download_path', '') or ''

                _changed = (
                    temp_max != st.session_state.get('concurrent_downloads', 5)
                    or temp_cbs != st.session_state.get('enable_cbs_filters', False)
                    or temp_size_enabled != st.session_state.get('max_file_size_enabled', False)
                    or int(temp_size_mb) != int(st.session_state.get('max_file_size_mb', 500))
                    or temp_notifications != st.session_state.get('notifications_enabled', True)
                    or temp_error_log != st.session_state.get('error_log_enabled', False)
                    or temp_time_12h != st.session_state.get('use_12h_format', False)
                    or new_default_path != prev_default_path
                )

                st.session_state['concurrent_downloads'] = temp_max
                st.session_state['enable_cbs_filters'] = temp_cbs
                st.session_state['max_file_size_enabled'] = temp_size_enabled
                st.session_state['max_file_size_mb'] = int(temp_size_mb)
                st.session_state['notifications_enabled'] = temp_notifications
                st.session_state['error_log_enabled'] = temp_error_log
                st.session_state['use_12h_format'] = temp_time_12h
                st.session_state['default_download_path'] = new_default_path

                from pathlib import Path as _Path
                _downloads_default = str(_Path.home() / "Downloads")
                live_path = st.session_state.get('download_path', '')
                if new_default_path and live_path in (prev_default_path, _downloads_default, ''):
                    st.session_state['download_path'] = new_default_path

                if os.path.exists(CONFIG_FILE):
                    try:
                        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                    except Exception:
                        config_data = {}
                else:
                    config_data = {}

                config_data['api_url'] = st.session_state.get('api_url', '')
                config_data.pop('api_token', None)
                config_data['concurrent_downloads'] = temp_max
                config_data['enable_cbs_filters'] = temp_cbs
                config_data['max_file_size_enabled'] = bool(temp_size_enabled)
                config_data['max_file_size_mb'] = int(temp_size_mb)
                config_data['notifications_enabled'] = bool(temp_notifications)
                config_data['error_log_enabled'] = bool(temp_error_log)
                config_data['use_12h_format'] = bool(temp_time_12h)
                config_data['default_download_path'] = new_default_path

                try:
                    _tmp_config = CONFIG_FILE + '.tmp'
                    with open(_tmp_config, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(_tmp_config, CONFIG_FILE)
                except Exception as e:
                    # Clean up orphaned temp file on failure
                    try:
                        if os.path.exists(_tmp_config):
                            os.unlink(_tmp_config)
                    except OSError:
                        pass
                    st.error(f"Could not save settings: {e}")

                st.session_state.pop('_temp_default_path', None)
                if _changed:
                    st.session_state['_stg_saved_toast'] = True
                st.rerun(scope="app")

    user_name = st.session_state.get('user_name', '')
    display_user = user_name.replace("Logged in as:", "").replace("Logged in as", "").strip()

    with st.container(border=False, key="sidebar_bottom_block"):
        # Settings button - also auto-reopens after native folder picker closes the dialog
        if st.button("Settings", use_container_width=True, key="nav_btn_settings"):
            _global_settings_dialog()
        elif st.session_state.pop('_stg_reopen_dialog', False):
            _global_settings_dialog()

        if st.session_state.pop('_stg_saved_toast', False):
            st.toast("✅ Settings saved")

        # Separator
        st.html("<hr style='margin: 8px 0 16px 0; border: none; border-bottom: 1px solid rgba(255,255,255,0.08);' />")

        # User info + logout - keyed container with absolute-positioned logout
        with st.container(border=False, key="user_info_row"):
            if display_user:
                first_name = display_user.split()[0] if display_user.split() else display_user
                safe_first_name = _he(first_name)
                # Calculate logout button left offset dynamically:
                # "Logged in as" at 0.75rem ≈ 65px, name at 0.9rem ≈ 8px/char
                name_px = len(first_name) * 8
                logged_in_px = 65  # "Logged in as" at 0.75rem is ~65px
                max_text_px = max(name_px, logged_in_px)
                logout_left = 20 + max_text_px + 5  # 20px pad + text + 5px gap
                st.html(f"""
<style>
section[data-testid="stSidebar"] div[class*="st-key-user_info_row"] div.st-key-nav_btn_logout {{
    left: {logout_left}px !important;
}}
</style>
<div style="line-height: 1.2; padding: 0 0 0 20px;">
    <div style="color: #9ca3af; font-size: 0.75rem; padding-bottom: 3px;">Logged in as</div>
    <div style="display: inline-block; color: #f3f4f6; font-size: 0.9rem; font-weight: 500; padding: 2px 6px; margin-top: 3px; margin-left: -6px; background-color: rgba(255, 255, 255, 0.06); border-radius: 4px;">{safe_first_name}</div>
</div>""")
            if st.button('\u200b', use_container_width=False, key="nav_btn_logout"):
                try:
                    import keyring
                    keyring_user = st.session_state.get('api_url', '') or 'default'
                    keyring.delete_password(KEYRING_SERVICE, keyring_user)
                except Exception:
                    pass

                st.session_state['is_authenticated'] = False
                st.session_state['api_token'] = ""
                st.session_state['token_loaded'] = False
                st.session_state['user_name'] = ''
                st.session_state['step'] = 1
                st.session_state['current_mode'] = 'download'
                fetch_courses_fn.clear()
                if os.path.exists(CONFIG_FILE):
                    try:
                        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                        config_data.pop('api_token', None)
                        config_data.pop('mac_api_token', None)
                        tmp_path = CONFIG_FILE + '.tmp'
                        with open(tmp_path, 'w', encoding='utf-8') as f:
                            json.dump(config_data, f)
                            f.flush()
                            os.fsync(f.fileno())
                        os.replace(tmp_path, CONFIG_FILE)
                    except Exception as e:
                        logger.warning(f"Could not update config on logout: {e}")
                st.rerun()

        # Version badge
        st.html(
            f"<hr style='margin: 8px 0 0 0; border: none; border-bottom: 1px solid rgba(255,255,255,0.06);' />"
            f"<div style='text-align:left; color:#9ca3af; font-size:0.75rem; padding: 15px 0 0 20px;'>"
            f"Canvas Downloader v{__version__}</div>"
        )
