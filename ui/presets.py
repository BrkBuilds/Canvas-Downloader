"""
ui.presets — Preset system: save, load, hub dialog, and card rendering.

Extracted from ``app.py`` (Phase 6).
Strict physical move — NO logic changes.

Contains:
  - ``render_preset_buttons()``     — Step 2 header preset action buttons
  - ``_build_preset_summary()``     — dynamic grammar-correct summary
  - ``_render_preset_card()``       — single preset card inside hub
  - ``_save_config_dialog()``       — @st.dialog for saving a preset
  - ``_presets_hub_dialog()``       — @st.dialog for the hub browser
"""

from __future__ import annotations

import streamlit as st

from preset_manager import PresetManager
from ui_helpers import esc
from ui_shared import render_config_summary_badges


def _build_preset_summary(settings):
    """Build a dynamic, grammar-correct summary string for a preset's settings."""
    # 1. Organization
    mode_str = "📁 With Subfolders" if settings.get('download_mode') == 'modules' else "📁 All in One Folder"
    # 2. File Filter
    filter_str = "📦 All Files" if settings.get('file_filter') == 'all' else "📦 Presentations & PDFs"
    # 3. Canvas Content
    sec_count = sum(1 for k in PresetManager.SECONDARY_CONTENT_KEYS if settings.get(k))
    sec_total = len(PresetManager.SECONDARY_CONTENT_KEYS)
    if sec_count == sec_total:
        sec_str = "📝 All Canvas Content"
    elif sec_count > 0:
        sec_str = f"📝 {sec_count} Canvas Content"
    else:
        sec_str = ""
    # 4. Conversions — correct grammar
    conv_count = sum(1 for k in PresetManager.NOTEBOOK_SUB_KEYS if settings.get(k))
    conv_total = len(PresetManager.NOTEBOOK_SUB_KEYS)
    if conv_count == conv_total:
        conv_str = "🔧 All Conversions"
    elif conv_count == 1:
        conv_str = "🔧 1 Conversion"
    elif conv_count > 1:
        conv_str = f"🔧 {conv_count} Conversions"
    else:
        conv_str = ""
    parts = [p for p in [mode_str, filter_str, sec_str, conv_str] if p]
    return "  ·  ".join(parts)


def _render_preset_card(mgr, preset, is_builtin=False, b64_icon_builtin="", b64_icon_user=""):
    """Render a single preset as an elevated card with an expander summary."""
    with st.container(border=True, key=f"preset_card_{preset['preset_id']}"):
        name = preset['preset_name']
        desc = preset.get('description', '')
        settings = preset.get('settings', {})

        # Card header with Base64 icon
        _icon_b64 = b64_icon_builtin if is_builtin else b64_icon_user
        _icon_html = ""
        if _icon_b64:
            _icon_html = (
                f"<img src='data:image/png;base64,{_icon_b64}' "
                f"style='width:22px; height:22px; vertical-align:middle; margin-right:8px;' />"
            )
        st.markdown(f"""
<div style='margin-bottom: 4px;'>
<span style='font-size: 1.15rem; font-weight: 600;'>{_icon_html}{esc(name)}</span>
</div>
""", unsafe_allow_html=True)

        if desc:
            st.markdown(
                f"<p style='color:#aaa; font-size:0.85rem; margin-top: -8px;'>{esc(desc)}</p>",
                unsafe_allow_html=True,
            )

        # Dynamic settings summary as an expander
        _summary_label = _build_preset_summary(settings)
        with st.expander(_summary_label):
            path = str(preset.get('download_path', '')) if preset.get('include_path') else None
            _s = settings.copy()
            if path:
                _s['download_path'] = path
            st.markdown(render_config_summary_badges(_s, show_path=bool(path)), unsafe_allow_html=True)

        # Action buttons
        if is_builtin:
            col_apply, _ = st.columns([1, 2])
        else:
            col_apply, col_del, _ = st.columns([1, 1, 1])

        with col_apply:
            if st.button("Apply Preset", key=f"preset_apply_{preset['preset_id']}",
                         use_container_width=True):
                mgr.apply_preset(st.session_state, preset)

                # Auto-expand cards if preset contains matching active keys
                if any(preset.get('settings', {}).get(k) for k in PresetManager.SECONDARY_CONTENT_KEYS):
                    st.session_state['card2_expanded'] = True
                if any(preset.get('settings', {}).get(k) for k in PresetManager.NOTEBOOK_SUB_KEYS):
                    st.session_state['card3_expanded'] = True

                st.session_state['pending_toast'] = f"✅ Applied preset '{esc(name)}'"
                try:
                    st.rerun(scope="app")
                except TypeError:
                    st.rerun()

        if not is_builtin:
            with col_del:
                if st.button("🗑️ Delete", key=f"preset_delete_{preset['preset_id']}",
                             use_container_width=True):
                    mgr.delete_preset(preset['preset_id'])
                    st.session_state['preset_hub_toast'] = f"🗑️ Preset '{esc(name)}' deleted."
                    st.rerun()


@st.dialog("💾 Save Configuration")
def _save_config_dialog():
    from ui_helpers import get_config_dir
    mgr = PresetManager(get_config_dir())

    st.markdown(
        '<p style="color:#aaa; font-size:0.9rem; margin-bottom:10px;">'
        'Save your current Download Settings as a reusable preset.</p>',
        unsafe_allow_html=True,
    )

    preset_name = st.text_input(
        "Preset name:",
        placeholder="e.g., AI Study Pack",
        key="preset_save_name_input",
    )

    preset_desc = st.text_input(
        "Description (optional):",
        placeholder="e.g., All conversions for NotebookLM uploads",
        key="preset_save_desc_input",
    )

    include_path = st.checkbox(
        "Also save the current output folder path",
        key="preset_save_include_path",
        value=False,
    )

    # Preview current settings (collapsed)
    with st.container(key="preset_save_preview", border=False):
        with st.expander("📋 Current settings being saved"):
            _preview = mgr.capture_current_settings(st.session_state)
            path = str(st.session_state.get('download_path', '')) if include_path else None
            _p = _preview.copy()
            if path:
                _p['download_path'] = path
            st.markdown(render_config_summary_badges(_p, show_path=bool(path)), unsafe_allow_html=True)

    # Action buttons
    col_create, col_cancel = st.columns([1, 1])
    with col_create:
        create_disabled = not preset_name or not preset_name.strip()
        if st.button("Save Preset", use_container_width=True,
                     key="preset_save_create", disabled=create_disabled):
            _settings = mgr.capture_current_settings(st.session_state)
            _path = st.session_state.get('download_path', '') if include_path else ''
            mgr.save_preset(preset_name.strip(), preset_desc.strip() if preset_desc else '', _settings, include_path, _path)
            st.session_state['pending_toast'] = f"✅ Preset '{preset_name.strip()}' saved!"
            try:
                st.rerun(scope="app")
            except TypeError:
                st.rerun()
    with col_cancel:
        if st.button("Cancel", type="secondary", use_container_width=True, key="preset_cancel_save"):
            try:
                st.rerun(scope="app")
            except TypeError:
                st.rerun()


@st.dialog("⚙️ Download Presets", width="large")
def _presets_hub_dialog():
    from ui_helpers import get_config_dir
    mgr = PresetManager(get_config_dir())

    # Load Base64 icons — import helper from app scope
    def _load_b64(path):
        """Inline Base64 loader for preset icons."""
        import base64 as _b64
        try:
            with open(path, "rb") as f:
                return _b64.b64encode(f.read()).decode()
        except Exception:
            return ""

    _b64_user = _load_b64("assets/icon_preset_user.png")
    _b64_builtin = _load_b64("assets/icon_preset_builtin.png")

    # Consume in-dialog toasts
    if 'preset_hub_toast' in st.session_state:
        st.toast(st.session_state.pop('preset_hub_toast'))

    # --- Custom Tab Buttons (session-state driven) ---
    st.session_state.setdefault('preset_hub_tab', 'user')
    _active_tab = st.session_state['preset_hub_tab']

    def _set_preset_tab(tab_key):
        st.session_state['preset_hub_tab'] = tab_key

    # Inject tab-specific CSS for Base64 icons via ::before pseudo-elements
    st.markdown(f"""
<style>
div[class*="st-key-preset_tab_"] button div[data-testid="stMarkdownContainer"] p {{
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}}
div.st-key-preset_tab_user button div[data-testid="stMarkdownContainer"] p::before {{
    content: "";
    display: inline-block;
    width: 22px;
    height: 22px;
    margin-right: 8px;
    background-image: url('data:image/png;base64,{_b64_user}');
    background-size: contain;
    background-repeat: no-repeat;
}}
div.st-key-preset_tab_builtin button div[data-testid="stMarkdownContainer"] p::before {{
    content: "";
    display: inline-block;
    width: 22px;
    height: 22px;
    margin-right: 8px;
    background-image: url('data:image/png;base64,{_b64_builtin}');
    background-size: contain;
    background-repeat: no-repeat;
}}
</style>
""", unsafe_allow_html=True)

    with st.container(key="preset_tabs_row"):
        _tc1, _tc2 = st.columns(2, gap="small")
        with _tc1:
            st.button(
                "My Presets",
                key="preset_tab_user",
                type="primary" if _active_tab == 'user' else "secondary",
                use_container_width=True,
                on_click=_set_preset_tab, args=('user',),
            )
        with _tc2:
            st.button(
                "Built-in Presets",
                key="preset_tab_builtin",
                type="primary" if _active_tab == 'builtin' else "secondary",
                use_container_width=True,
                on_click=_set_preset_tab, args=('builtin',),
            )

    # --- Fixed-height scrollable card container ---
    with st.container(height=550, border=False):
        if _active_tab == 'user':
            _user_presets = mgr.load_presets()
            if not _user_presets:
                st.info("No saved presets yet. Use the '💾 Save Configuration' button to create one.")
            for _up in _user_presets:
                _render_preset_card(mgr, _up, is_builtin=False,
                                    b64_icon_builtin=_b64_builtin, b64_icon_user=_b64_user)
        else:
            for _bp in mgr.get_builtin_presets():
                _render_preset_card(mgr, _bp, is_builtin=True,
                                    b64_icon_builtin=_b64_builtin, b64_icon_user=_b64_user)

    # Close button — forces full app rerun for fresh state
    if st.button("Close", type="secondary", use_container_width=True, key="btn_preset_hub_close"):
        try:
            st.rerun(scope="app")
        except TypeError:
            st.rerun()


def render_preset_buttons(get_base64_image_fn):
    """Render the Save / Load Preset buttons at the top of Step 2.
    
    Args:
        get_base64_image_fn: callable that takes an image path and returns base64 string.
    """
    # Consume toast from preset application/save (fires once)
    if 'pending_toast' in st.session_state:
        st.toast(st.session_state.pop('pending_toast'))

    b64_save = get_base64_image_fn("assets/icon_save.png")
    b64_load = get_base64_image_fn("assets/icon_load.png")

    col_save, col_load, _ = st.columns([1, 1, 7])

    with col_save:
        if st.button("💾 Save", key="step2_save_preset_btn", use_container_width=True):
            _save_config_dialog()

    with col_load:
        if st.button("⚙️ Presets", key="step2_load_preset_btn", use_container_width=True):
            _presets_hub_dialog()
