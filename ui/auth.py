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
    icon_b64 = get_base64_image("assets/icon.png")

    st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 14px; padding: 4px 8px 12px 4px; margin-top: -24px;">
        <img src="data:image/png;base64,{icon_b64}" style="width: 36px; height: 36px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); display: block;" />
        <div style="display: flex; flex-direction: column; justify-content: center; height: 36px;">
            <span style="font-weight: 700; font-size: 1.25rem; color: #f3f4f6; line-height: 1; margin: 0; padding-top: 4px;">Canvas Downloader</span>
        </div>
    </div>
    <hr style="margin: 0px -1.5rem 12px -1.5rem; border: none; border-bottom: 1px solid rgba(255,255,255,0.08);" />
    """, unsafe_allow_html=True)

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
    # ── Navigation buttons ─────────────────────────────────────────
    mode = st.session_state.get('current_mode', 'download')

    from ui_helpers import get_base64_image
    icon_dl_b64 = get_base64_image("assets/icon_download.png")
    icon_sync_b64 = get_base64_image("assets/icon_sync.png")

    # Determine which button is active
    active_css = ""
    if mode in ['download', 'sync']:
        active_key = f"st-key-nav_btn_{mode}"
        active_css = f"""
        div.{active_key} button {{ background-color: #2a2e35 !important; }}
        div.{active_key} button p {{ color: #ffffff !important; font-weight: 600 !important; }}
        div.{active_key} button p::before,
        div.{active_key} button:hover p::before {{ filter: brightness(0) invert(1) !important; }}
        /* Ensure active item doesn't show standard hover background */
        div.{active_key} button:hover {{ background-color: #2a2e35 !important; }}
        """

    st.markdown(f"""
    <style>
    /* ── 1. Geometric Structure & Layout (Full Width Pill) ── */
    div[class*="st-key-nav_btn_"] button {{
        background: transparent !important;
        border: none !important;
        border-radius: 6px !important;
        box-shadow: none !important;
        width: 100% !important; /* Fuldt udstrakt */
        margin: 2px 0 !important;
        height: auto !important;
        min-height: 48px !important; /* Forstørret knap */
        padding: 0 !important;
        transition: all 0.2s ease-in-out;
    }}
    
    /* ── Hitbox & Flex Alignment ── */
    div[class*="st-key-nav_btn_"] button p {{
        color: #9ca3af !important;
        font-weight: 500 !important;
        font-size: 1.05rem !important; /* Forstørret tekst */
        margin: 0;
        padding: 12px 14px !important; /* Større indvendigt rum */
        display: flex !important;
        align-items: center;
        justify-content: flex-start;
        width: 100%;
        transition: all 0.2s ease-in-out;
    }}
    
    /* ── 2. Icon Injection ── */
    div[class*="st-key-nav_btn_"] button p::before {{
        content: '';
        display: inline-block;
        flex-shrink: 0;
        width: 22px; /* Forstørret ikon */
        height: 22px;
        margin-right: 14px; 
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: brightness(0) invert(0.65);
        transition: all 0.2s ease-in-out;
    }}
    
    /* ── Specific Asset Bindings ── */
    div.st-key-nav_btn_download button p::before {{
        background-image: url("data:image/png;base64,{icon_dl_b64}");
    }}
    div.st-key-nav_btn_sync button p::before {{
        background-image: url("data:image/png;base64,{icon_sync_b64}");
    }}
    div.st-key-nav_btn_settings button p::before {{
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z'%3E%3C/path%3E%3Ccircle cx='12' cy='12' r='3'%3E%3C/circle%3E%3C/svg%3E");
    }}
    div.st-key-nav_btn_logout button p::before {{
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4'%3E%3C/path%3E%3Cpolyline points='16 17 21 12 16 7'%3E%3C/polyline%3E%3Cline x1='21' y1='12' x2='9' y2='12'%3E%3C/line%3E%3C/svg%3E");
    }}
    
    /* ── 3. Hover State ── */
    div[class*="st-key-nav_btn_"] button:hover {{
        background-color: rgba(255, 255, 255, 0.05) !important;
    }}
    div[class*="st-key-nav_btn_"] button:hover p {{
        color: #d1d5db !important;
    }}
    div[class*="st-key-nav_btn_"] button:hover p::before {{
        filter: brightness(0) invert(0.85);
    }}
    
    /* ── 4. Active State (Overrides Hover) ── */
    {active_css}

    /* ── 5. Distinct Log Out Hover ── */
    div.st-key-nav_btn_logout button:hover {{
        background-color: rgba(239, 68, 68, 0.1) !important; 
    }}
    div.st-key-nav_btn_logout button:hover p {{
        color: #fca5a5 !important;
    }}
    /* Soft red filter hack using invert+sepia cascade */
    div.st-key-nav_btn_logout button:hover p::before {{
        filter: brightness(0) saturate(100%) invert(67%) sepia(51%) saturate(2321%) hue-rotate(313deg) brightness(108%) contrast(98%) !important;
    }}
    </style>
    """, unsafe_allow_html=True)

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

    st.markdown("<div style='height: calc(100vh - 475px); min-height: 60px;'></div>", unsafe_allow_html=True)

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

        c_save, c_cancel = st.columns([1, 1])
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
        with c_cancel:
            if st.button("Cancel", use_container_width=True):
                st.rerun(scope="app")

    # Settings button trigger
    if st.button("Settings", use_container_width=True, key="nav_btn_settings"):
        _global_settings_dialog()

    # ── Logout ─────────────────────────────────────────────────────
    st.markdown("<hr style='margin: 8px -1.5rem 16px -1.5rem; border: none; border-bottom: 1px solid rgba(255,255,255,0.08);' />", unsafe_allow_html=True)
    
    user_name = st.session_state.get('user_name', '')
    display_user = user_name.replace("Logged in as:", "").replace("Logged in as", "").strip()
    
    st.markdown("""
    <style>
    /* Styling for the 3-dot popover button in sidebar */
    [data-testid="stSidebar"] [data-testid="stPopover"] > button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #9ca3af !important;
        font-size: 1.4rem !important;
        line-height: 1 !important;
        width: 32px !important;
        height: 32px !important;
        min-height: 32px !important;
        padding: 0px 0px 8px 0px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        border-radius: 8px !important;
        transition: all 0.1s ease-in-out;
    }
    [data-testid="stSidebar"] [data-testid="stPopover"] > button:hover {
        color: #ffffff !important;
        background: rgba(255,255,255,0.08) !important;
    }
    /* Popover body */
    div[data-testid="stPopoverBody"] {
        background-color: #1e2530 !important;
        border: 1px solid #3e454f !important;
        border-radius: 8px !important;
        padding: 6px !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    col_text, col_dots = st.columns([0.85, 0.15], gap="small", vertical_alignment="center")
    
    with col_text:
        if display_user:
            st.markdown(f"""
            <div style="line-height: 1.4;">
                <div style="color: #6b7280; font-size: 0.85rem;">Logged in as</div>
                <div style="color: #f3f4f6; font-size: 1.0rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{display_user}</div>
            </div>
            """, unsafe_allow_html=True)
            
    with col_dots:
        with st.popover("⋯", use_container_width=True):
            if st.button('Log out', use_container_width=True, key="nav_btn_logout"):
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
        f"<hr style='margin: 16px -1.5rem 10px -1.5rem; border: none; border-bottom: 1px solid rgba(255,255,255,0.06);' />"
        f"<div style='text-align:center;color:{theme.TEXT_MUTED};font-size:0.75rem;"
        f"padding:0px 0 5px 0;'>Canvas Downloader v{__version__}</div>",
        unsafe_allow_html=True,
    )
