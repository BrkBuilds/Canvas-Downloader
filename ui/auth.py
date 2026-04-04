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
    st.markdown("---")
    st.title('Canvas Downloader')

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

    # ── Login form OR authenticated navigation ──────────────────────────
    if not st.session_state['is_authenticated']:
        _render_login_form()
    else:
        _render_authenticated_nav(fetch_courses_fn)


# ─── Private helpers ────────────────────────────────────────────────────


def _render_login_form():
    """Render the un-authenticated login form."""
    st.subheader('Authentication')

    with st.form("auth_form", clear_on_submit=False):
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

    # Help expanders
    with st.expander('How to get a Token?'):
        st.markdown('\n1. Go to **Account** -> **Settings** on Canvas.\n2. Scroll to **Approved Integrations**.\n3. Click **+ New Access Token**.\n4. Copy the long string and paste it here.\n')

    with st.expander('How to find your Canvas URL?'):
        st.markdown("\n**Crucial Step:** You must input the *actual* Canvas URL, not your university's login portal.\n\n**How to find it:**\n1. Log in to Canvas in your browser.\n2. Look at the address bar **after** you have logged in.\n3. It often looks like `https://schoolname.instructure.com` (even if you typed `canvas.school.edu` to get there).\n4. Copy that URL and paste it here.\n")


def _render_authenticated_nav(fetch_courses_fn):
    """Render the authenticated sidebar: user label, navigation buttons,
    settings dialog, logout, and version badge."""
    st.success(st.session_state['user_name'])

    # ── Navigation buttons ─────────────────────────────────────────
    st.markdown("---")
    mode = st.session_state.get('current_mode', 'download')

    # Download mode button
    download_label = "📥 " + 'Download Courses'
    if mode == 'download':
        st.markdown(f"""
        <div style="background-color: #3a3a3a; border: 1px solid #555; border-radius: 6px; 
                    padding: 8px 16px; text-align: center; margin-bottom: 8px;">
            <span style="color: {theme.WHITE}; font-weight: 500;">{download_label}</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        if st.button(download_label, use_container_width=True, key="nav_btn_download"):
            st.session_state['current_mode'] = 'download'
            st.session_state['step'] = 1
            st.session_state['sync_mode'] = False
            st.session_state['sync_pairs'] = []
            st.rerun()

    # Sync mode button
    sync_label = "🔄 " + 'Sync Local Folders'
    if mode == 'sync':
        st.markdown(f"""
        <div style="background-color: #3a3a3a; border: 1px solid #555; border-radius: 6px; 
                    padding: 8px 16px; text-align: center; margin-bottom: 8px;">
            <span style="color: {theme.WHITE}; font-weight: 500;">{sync_label}</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        if st.button(sync_label, use_container_width=True, key="nav_btn_sync"):
            st.session_state['current_mode'] = 'sync'
            st.session_state['step'] = 1
            st.session_state['sync_mode'] = True
            st.session_state['sync_pairs'] = []
            st.rerun()

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # ── Global Settings dialog ─────────────────────────────────────
    @st.dialog("⚙️ Settings", width="large")
    def _global_settings_dialog():
        st.markdown("""
            <style>
                div.st-key-settings_scroll_container {
                    height: 65vh !important;
                    min-height: 65vh !important;
                    max-height: 65vh !important;
                    overflow-y: auto !important;
                    overflow-x: hidden !important;
                    padding-right: 5px;
                }
            </style>
        """, unsafe_allow_html=True)

        with st.container(border=False, key="settings_scroll_container"):
            col1, col2 = st.columns(2, gap="large")

            with col1:
                st.markdown("<h4 style='margin-bottom: 10px;'>📥 Download Settings</h4>", unsafe_allow_html=True)

                # Card 1: Concurrent Downloads
                with st.container(border=True):
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
                with st.container(border=True):
                    st.markdown("""
                        <div style='margin-bottom: -10px;'>
                            <h4 style='font-size: 1.05rem; margin-top: 0px; margin-bottom: 2px;'>Debug Mode</h4>
                            <p style='font-size: 0.85rem; color: #cbd5e1; margin-top: 2px; margin-bottom: 10px;'>Enable advanced terminal logging for troubleshooting.</p>
                        </div>
                    """, unsafe_allow_html=True)
                    temp_debug = st.checkbox("Enable Troubleshooting Mode", value=st.session_state.get('debug_mode', False), key="temp_debug_mode")

            with col2:
                st.markdown("<h4 style='margin-bottom: 10px;'>🔄 Sync Settings</h4>", unsafe_allow_html=True)

                with st.container(border=True):
                    st.info("Future sync optimizations and configuration options will appear here.")

        st.markdown('<hr style="margin-top: 5px; margin-bottom: 15px; border-color: rgba(255,255,255,0.1);" />', unsafe_allow_html=True)

        c_save, c_cancel = st.columns([1, 1])
        with c_save:
            if st.button("Save Settings", type="primary", use_container_width=True):
                st.session_state['concurrent_downloads'] = temp_max
                st.session_state['debug_mode'] = temp_debug

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

                try:
                    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f)
                except Exception as e:
                    st.error(f"⚠️ Could not save settings to disk: {e}")

                st.rerun()
        with c_cancel:
            if st.button("Cancel", use_container_width=True):
                st.rerun()

    # Settings button trigger
    if st.button("⚙️ Settings", use_container_width=True, key="nav_btn_settings"):
        _global_settings_dialog()

    # ── Logout ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("")  # Spacer
    st.markdown("")
    if st.button('Log Out / Edit Token', use_container_width=True):
        # Wipe token from OS keyring
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
        # Clear the course cache to prevent showing old user's courses
        fetch_courses_fn.clear()
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                config_data.pop('api_token', None)
                config_data.pop('mac_api_token', None)
                # Atomic .tmp swap pattern — prevents disk-tearing on logout
                tmp_path = CONFIG_FILE + '.tmp'
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f)
                os.replace(tmp_path, CONFIG_FILE)
            except Exception as e:
                logger.warning(f"Could not update config on logout: {e}")
        st.rerun()

    # Version badge
    st.markdown(
        f"<div style='text-align:center;color:{theme.TEXT_MUTED};font-size:0.75rem;"
        f"padding:20px 0 5px 0;'>Canvas Downloader v{__version__}</div>",
        unsafe_allow_html=True,
    )
