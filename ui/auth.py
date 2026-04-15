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
import platform

import streamlit as st

import theme
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

                        loaded_token = ''
                        if platform.system() == 'Darwin':
                            # macOS: Avoid keychain permission prompts by loading from config json via base64
                            encoded_token = config.get('mac_api_token', '')
                            if encoded_token:
                                try:
                                    loaded_token = base64.b64decode(encoded_token.encode('utf-8')).decode('utf-8')
                                except Exception:
                                    pass
                        else:
                            # Windows: Load token from OS keyring (secure)
                            try:
                                import keyring
                                keyring_user = st.session_state['api_url'] or 'default'
                                loaded_token = keyring.get_password(KEYRING_SERVICE, keyring_user) or ''
                            except Exception:
                                pass  # Keyring unavailable, fall through to legacy check

                            # Legacy migration: if token still in JSON, migrate it to keyring
                            if not loaded_token and config.get('api_token', ''):
                                loaded_token = config['api_token']
                                # Migrate to keyring and strip from JSON
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

            # Save token — macOS vs Windows
            if platform.system() == 'Darwin':
                # TODO: Implement pyobjc SecItemAdd for native Keychain access
                # once the .app bundle is code-signed. Base64 is obfuscation,
                # not encryption — acceptable only until signing is in place.
                try:
                    encoded = base64.b64encode(st.session_state['api_token'].encode('utf-8')).decode('utf-8')
                    config_data['mac_api_token'] = encoded
                except Exception as e:
                    st.warning(f"Could not obfuscate token: {e}")
            else:
                try:
                    import keyring
                    keyring_user = st.session_state['api_url'] or 'default'
                    keyring.set_password(KEYRING_SERVICE, keyring_user, st.session_state['api_token'])
                except Exception as e:
                    st.warning(f"Could not save token to system keyring: {e}. Token will not persist across sessions.")

            try:
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f)
            except Exception as e:
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
            st.rerun()

    # Sync mode button
    if st.button('Sync Local Folders', use_container_width=True, key="nav_btn_sync"):
        if mode != 'sync':
            st.session_state['current_mode'] = 'sync'
            st.session_state['step'] = 1
            st.session_state['sync_mode'] = True
            st.session_state['sync_pairs'] = []
            st.rerun()


def _render_authenticated_nav_bottom(fetch_courses_fn):
    """Render the bottom part of the authenticated sidebar"""
    import os
    import json
    import platform


    # ── Global Settings dialog ─────────────────────────────────────
    @st.dialog("⚙️ Settings", width="large")
    def _global_settings_dialog():
        # ── Dark grey card CSS (scoped to dialog) ──────────────────
        st.markdown("""<style>
            div[data-testid="stDialog"] div[class*="st-key-settings_card_"] {
                background-color: rgba(255, 255, 255, 0.04) !important;
            }
            div.st-key-settings_scroll_container {
                height: 65vh !important;
                min-height: 65vh !important;
                max-height: 65vh !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
                padding-right: 5px;
            }
        </style>""", unsafe_allow_html=True)

        with st.container(border=False, key="settings_scroll_container"):
            # ── Download Settings ───────────────────────────────────
            st.markdown("<h4 style='margin-bottom: 10px;'>📥 Download Settings</h4>", unsafe_allow_html=True)

            # Card 1: Concurrent Downloads
            with st.container(border=True, key="settings_card_speed"):
                st.markdown("""
                    <div style='margin-bottom: -20px;'>
                        <h4 style='font-size: 1.05rem; margin: 0px 0px 2px 0px;'>Download Speed: Max Concurrent Downloads</h4>
                        <p style='font-size: 0.85rem; color: #cbd5e1; margin-top: 2px; margin-bottom: 8px;'>Controls how many files are downloaded simultaneously.</p>
                        <p style='font-size: 0.85rem; color: #fbbf24; margin-top: 0px; margin-bottom: 5px; line-height: 1.4;'>
                            ⚠️ <b>Warning:</b> Canvas has strict rate limits. Setting this too high (e.g., 15) may cause the download/sync to crash due to server blocks. If you experience crashes or failed downloads, reduce this number and try again.
                        </p>
                        <div style='margin-top: 12px; margin-bottom: 0px;'>
                            <span style='background-color: #1e293b; color: #94a3b8; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; border: 1px solid #334155;'>Default: 5</span>
                        </div>
                    </div>
                """, unsafe_allow_html=True)

                st.markdown("""
                    <style>
                    div.stSlider > div[data-baseweb="slider"] > div > div > div {
                        background-color: {theme.ACCENT_LINK} !important;
                    }
                    div.stSlider > div[data-baseweb="slider"] > div > div[role="slider"] {
                        background-color: {theme.ACCENT_LINK} !important;
                        border-color: {theme.ACCENT_LINK} !important;
                    }
                    </style>
                """, unsafe_allow_html=True)

                temp_max = st.slider("Simultaneous Files", min_value=1, max_value=15, value=st.session_state.get('concurrent_downloads', 5), key="temp_max_downloads", label_visibility="collapsed")

            # Card 2: Debug Mode
            with st.container(border=True, key="settings_card_debug"):
                st.markdown("""
                    <div style='margin-bottom: -10px;'>
                        <h4 style='font-size: 1.05rem; margin-top: 0px; margin-bottom: 2px;'>Debug Mode</h4>
                        <p style='font-size: 0.85rem; color: #cbd5e1; margin-top: 2px; margin-bottom: 10px;'>Enable advanced terminal logging for troubleshooting.</p>
                    </div>
                """, unsafe_allow_html=True)
                temp_debug = st.checkbox("Enable Troubleshooting Mode", value=st.session_state.get('debug_mode', False), key="temp_debug_mode")

            # ── UI Settings ─────────────────────────────────────────
            st.markdown("<h4 style='margin-bottom: 10px; margin-top: 20px;'>🖥️ UI Settings</h4>", unsafe_allow_html=True)

            # Card 3: CBS Filter Toggle
            with st.container(border=True, key="settings_card_cbs"):
                st.markdown("""
                    <div style='margin-bottom: -5px;'>
                        <h4 style='font-size: 1.05rem; margin-top: 0px; margin-bottom: 2px;'>CBS Course Filters</h4>
                        <p style='font-size: 0.85rem; color: #cbd5e1; margin-top: 2px; margin-bottom: 10px;'>
                            Enable Copenhagen Business School specific metadata filtering in course lists.<br>
                            When enabled, a filter toggle appears in all course selection views allowing you to
                            filter by Class Type (LA/XB), Semester (E/F), and Year.
                        </p>
                    </div>
                """, unsafe_allow_html=True)
                temp_cbs = st.checkbox("Enable CBS Filters", value=st.session_state.get('enable_cbs_filters', False), key="temp_cbs_filters")

        st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)

        c_cancel, c_save = st.columns([1, 1])
        with c_cancel:
            if st.button("Cancel", use_container_width=True):
                st.rerun(scope="app")
        with c_save:
            if st.button("Save Settings", type="primary", use_container_width=True):
                st.session_state['concurrent_downloads'] = temp_max
                st.session_state['debug_mode'] = temp_debug
                st.session_state['enable_cbs_filters'] = temp_cbs

                # Persist to config
                if os.path.exists(CONFIG_FILE):
                    try:
                        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                    except Exception:
                        config_data = {}
                else:
                    config_data = {}

                config_data['api_url'] = st.session_state.get('api_url', '')
                config_data.pop('api_token', None)  # Never write token to JSON
                config_data['concurrent_downloads'] = temp_max
                config_data['debug_mode'] = temp_debug
                config_data['enable_cbs_filters'] = temp_cbs

                try:
                    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f)
                except Exception as e:
                    st.error(f"⚠️ Could not save settings to disk: {e}")

                st.rerun(scope="app")

    user_name = st.session_state.get('user_name', '')
    display_user = user_name.replace("Logged in as:", "").replace("Logged in as", "").strip()

    with st.container(border=False, key="sidebar_bottom_block"):
        # Settings button
        if st.button("Settings", use_container_width=True, key="nav_btn_settings"):
            _global_settings_dialog()

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
                if platform.system() != 'Darwin':
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
