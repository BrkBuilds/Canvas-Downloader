"""
ui.auth — Sidebar authentication, navigation, and global settings.

Extracted from ``app.py`` (Phase 7).
Strict physical move — NO logic changes.

Contains:
  - ``render_sidebar()`` — full sidebar: auth form, token loading,
    navigation buttons, global settings dialog, logout, version badge
"""

from __future__ import annotations

import base64
import json
import logging
import os

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
CONFIG_FILE = _get_config_path()
KEYRING_SERVICE = "CanvasDownloader"


def render_sidebar(fetch_courses_fn):
    """Render the full sidebar: auth, navigation, settings, logout.

    Must be called inside ``with st.sidebar:``.

    Args:
        fetch_courses_fn: The ``@st.cache_data``-wrapped ``fetch_courses()``
            function from app.py.  Needed so logout can call ``.clear()``.
    """
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

        # ── Auto-load token (only once per session) ─────────────────────────
        if not st.session_state['token_loaded']:
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
                            # (only if the user hasn't already picked a custom path this session).
                            import os as _os
                            from pathlib import Path as _Path
                            _downloads_default = str(_Path.home() / "Downloads")
                            current_path = st.session_state.get('download_path', '')
                            if saved_default and _os.path.isdir(saved_default) and current_path == _downloads_default:
                                st.session_state['download_path'] = saved_default

                        loaded_token = ''
                        # Unified keyring load for all platforms (macOS Keychain / Windows Credential Manager)
                        try:
                            import keyring
                            keyring_user = st.session_state['api_url'] or 'default'
                            loaded_token = keyring.get_password(KEYRING_SERVICE, keyring_user) or ''
                        except Exception:
                            pass  # Keyring unavailable, fall through to legacy checks

                        # Legacy migration: macOS base64 token stored in JSON before keyring unification
                        if not loaded_token and config.get('mac_api_token', ''):
                            try:
                                loaded_token = base64.b64decode(
                                    config['mac_api_token'].encode('utf-8')
                                ).decode('utf-8')
                                # Migrate to keyring and strip insecure field from JSON
                                try:
                                    import keyring
                                    keyring_user = st.session_state['api_url'] or 'default'
                                    keyring.set_password(KEYRING_SERVICE, keyring_user, loaded_token)
                                    config.pop('mac_api_token', None)
                                    with open(CONFIG_FILE, 'w', encoding='utf-8') as fw:
                                        json.dump(config, fw)
                                except Exception:
                                    pass  # Migration failed, token still in RAM this session
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
                                pass  # Migration failed, will work from RAM this session

                        st.session_state['api_token'] = loaded_token

                        if st.session_state['api_token']:
                            cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                            valid, msg = cm.validate_token()
                            if valid:
                                st.session_state['is_authenticated'] = True
                                st.session_state['user_name'] = msg
                except Exception:
                    pass

        # ── Login form OR authenticated navigation top ────────────────────────
        if not st.session_state['is_authenticated']:
            _render_login_form()
        else:
            _render_authenticated_nav_top()

    if st.session_state['is_authenticated']:
        _render_authenticated_nav_bottom(fetch_courses_fn)



# ─── Private helpers ────────────────────────────────────────────────────


def _render_login_form():
    """Render the un-authenticated login form."""
    # Suppress Streamlit's form validation flash during initial React hydration.
    # On first boot (clean machine), form components may briefly render a red
    # validation indicator before reconciliation completes.  A 300 ms fade-in
    # makes any sub-second flash invisible without hiding legitimate errors.
    st.html("""<style>
    section[data-testid="stSidebar"] [data-baseweb="notification"],
    section[data-testid="stSidebar"] [data-testid="stAlert"] {
        animation: _sidebarFadeIn 0.3s ease-in forwards;
        opacity: 0;
    }
    @keyframes _sidebarFadeIn { to { opacity: 1; } }
    </style>""")
    st.markdown("<div style='padding: 0 20px; margin-top: 10px; margin-bottom: 25px;'><span style='color: #ffffff; font-size: 1.6rem; font-weight: 700; letter-spacing: 0.02em;'>Authentication</span></div>", unsafe_allow_html=True)

    with st.form("auth_form", clear_on_submit=False, border=False):
        st.text_input(
            'Enter Canvas URL',
            key="url_input",
            placeholder="https://your-school.instructure.com"
        )

        st.text_input(
            'Enter Canvas API Token',
            type="password",
            key="token_input"
        )

        submitted = st.form_submit_button('Log In', type="primary", use_container_width=True)

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

    st.html("<hr style='margin: 10px 0 20px 0; border: none; border-bottom: 1px solid rgba(255,255,255,0.08);' />")

    # Help expanders
    with st.expander('How to get a Token?'):
        st.markdown('\n1. Go to **Account** -> **Settings** on Canvas.\n2. Scroll to **Approved Integrations**.\n3. Click **+ New Access Token**.\n4. Copy the long string and paste it here.\n')

    with st.expander('How to find your Canvas URL?'):
        st.markdown("\n**Crucial Step:** You must input the *actual* Canvas URL, not your university's login portal.\n\n**How to find it:**\n1. Log in to Canvas in your browser.\n2. Look at the address bar **after** you have logged in.\n3. It often looks like `https://schoolname.instructure.com` (even if you typed `canvas.school.edu` to get there).\n4. Copy that URL and paste it here.\n")


def _render_authenticated_nav_top():
    """Render the top part of the authenticated sidebar: navigation buttons."""
    # ── Navigation buttons ─────────────────────────────────────────
    mode = st.session_state.get('current_mode', 'download')

    # Active-state CSS is dynamic (depends on session state) — inject separately
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

    # Download mode button
    if st.button('Download Courses', use_container_width=True, key="nav_btn_download"):
        if mode != 'download':
            st.session_state['current_mode'] = 'download'
            st.session_state['step'] = 1
            st.session_state['sync_mode'] = False
            st.session_state['sync_pairs'] = []
            st.session_state.pop('sync_pairs_loaded', None)
            st.rerun()

    # Sync mode button
    if st.button('Sync Local Folders', use_container_width=True, key="nav_btn_sync"):
        if mode != 'sync':
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
            margin-right: 7px; vertical-align: middle; margin-top: -2px;
        }
        div[data-testid="stDialog"] div.st-key-stg_btn_clear button::before {
            content: ''; display: inline-block; width: 13px; height: 13px;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='18' y1='6' x2='6' y2='18'%3E%3C%2Fline%3E%3Cline x1='6' y1='6' x2='18' y2='18'%3E%3C%2Fline%3E%3C%2Fsvg%3E");
            background-size: contain; background-repeat: no-repeat;
            margin-right: 7px; vertical-align: middle; margin-top: -2px;
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
                        picked = native_folder_picker()
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
        # Settings button — also auto-reopens after native folder picker closes the dialog
        if st.button("Settings", use_container_width=True, key="nav_btn_settings"):
            _global_settings_dialog()
        elif st.session_state.pop('_stg_reopen_dialog', False):
            _global_settings_dialog()

        if st.session_state.pop('_stg_saved_toast', False):
            st.toast("✅ Settings saved")

        # Separator
        st.html("<hr style='margin: 8px 0 16px 0; border: none; border-bottom: 1px solid rgba(255,255,255,0.08);' />")

        # User info + logout — keyed container with absolute-positioned logout
        with st.container(border=False, key="user_info_row"):
            if display_user:
                first_name = display_user.split()[0] if display_user.split() else display_user
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
    <div style="display: inline-block; color: #f3f4f6; font-size: 0.9rem; font-weight: 500; padding: 2px 6px; margin-top: 3px; margin-left: -6px; background-color: rgba(255, 255, 255, 0.06); border-radius: 4px;">{first_name}</div>
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
