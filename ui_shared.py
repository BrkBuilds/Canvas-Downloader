"""
Shared UI components for Download and Sync completion screens.
Extracted to ensure perfect visual parity between both modes.
"""
import streamlit as st
from pathlib import Path
from ui_helpers import open_folder, esc, short_path, friendly_course_name
from sync_manager import format_file_size
import theme
from preset_manager import PresetManager


# --- Entity Icons for secondary content logging ---
SECONDARY_ENTITY_ICONS = {
    'assignment':   '📝',
    'quiz':         '❓',
    'discussion':   '💬',
    'announcement': '📢',
    'syllabus':     '📋',
    'rubric':       '📊',
    'page':         '📄',
}


def render_completion_card(synced_count: int, error_count: int,
                           total_bytes: int, mode: str = 'download'):
    """Render the premium success/warning/error summary card.
    
    Args:
        synced_count: Number of files successfully processed.
        error_count: Number of errors encountered.
        total_bytes: Total bytes downloaded.
        mode: 'download' or 'sync' — controls label text.
    """
    action_word = 'Downloaded' if mode == 'download' else 'Synced'
    file_word = 'file' if synced_count == 1 else 'files'
    error_word = 'error' if error_count == 1 else 'errors'

    if synced_count == 0 and error_count > 0:
        # Full failure
        st.error(f'{action_word.replace("ed", "")} failed for all files.')
        return

    elif synced_count > 0 and error_count > 0:
        # Partial success — yellow card
        title = f"Partial Success! {action_word} {synced_count} {file_word} with {error_count} {error_word}"
        summary = f'{format_file_size(total_bytes)} downloaded. Please check the errors below.'
        st.markdown(f"""
        <div style="background-color:#3a2a1a;border:1px solid {theme.WARNING_ALT};border-radius:8px;padding:12px 16px;margin:8px 0;">
            <div style="color:{theme.WARNING_ALT};font-weight:600;font-size:1.05em;">
                ⚠️ {title}
            </div>
            <div style="color:#ccc;font-size:0.85em;margin-top:4px;">
                {summary}
            </div>
        </div>
        """, unsafe_allow_html=True)

    elif synced_count > 0:
        # Full success — green card
        title = f'{action_word} {synced_count} {file_word} successfully!'
        summary = f"{format_file_size(total_bytes)} downloaded."
        st.markdown(f"""
        <div style="background-color:#1a3a2a;border:1px solid {theme.SUCCESS_ALT};border-radius:8px;padding:12px 16px;margin:8px 0;">
            <div style="color:{theme.SUCCESS_ALT};font-weight:600;font-size:1.05em;">
                🎉 {title}
            </div>
            <div style="color:#aaa;font-size:0.85em;margin-top:4px;">
                {summary}
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.balloons()

    else:
        st.success("Nothing to download — all files are up to date!")


def render_folder_cards(file_details: dict, folder_paths: dict,
                        key_prefix: str = 'dl'):
    """Render per-folder cards with file list dropdowns and Open Folder buttons.
    
    Args:
        file_details: Dict mapping folder_key -> list of filenames.
        folder_paths: Dict mapping folder_key -> absolute folder path string.
        key_prefix: Unique prefix for Streamlit widget keys ('dl' or 'sync').
    """
    has_files = any(len(files) > 0 for files in file_details.values())
    if not has_files:
        return

    st.markdown("#### 📁 Folders Updated")

    for idx, (folder_key, files) in enumerate(file_details.items()):
        if not files:
            continue

        folder_path = folder_paths.get(folder_key, '')
        folder_display = short_path(folder_path) if folder_path else folder_key

        with st.container(border=True):
            # CSS: remove inner expander border & tighten spacing
            st.markdown(f"""<style>
            div[data-testid="stExpander"] {{
                border: none !important;
                box-shadow: none !important;
                padding: 0 !important;
                margin-top: 0 !important;
            }}
            div[data-testid="stVerticalBlock"]:has(span#{key_prefix}_folder_{idx}) {{
                padding-top: 5px !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) {{
                align-items: center !important;
                gap: 15px !important;
                min-height: 0 !important;
                margin-bottom: 0px !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) div[data-testid="stColumn"] {{
                width: auto !important;
                flex: 0 0 auto !important;
                min-width: 0 !important;
                display: flex !important;
                align-items: center !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) div[data-testid="stMarkdownContainer"] {{
                margin: 0 !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) div[data-testid="stMarkdown"] {{
                display: flex !important;
                align-items: center !important;
                overflow: visible !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) div[data-testid="stElementContainer"] {{
                margin: 0 !important;
                overflow: visible !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) p {{
                margin: 0 !important;
                line-height: 1.4 !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(span#{key_prefix}_folder_{idx}) button {{
                border: 1px solid rgba(255,255,255,0.3) !important;
                padding: 4px 14px !important;
                font-size: 0.85rem !important;
                line-height: 1.4 !important;
                min-height: 0 !important;
                height: auto !important;
                transform: translateY(-2px) !important;
            }}
            </style>""", unsafe_allow_html=True)

            c1, c2, c3 = st.columns([1, 1, 1], vertical_alignment="center", gap="small")
            with c1:
                st.markdown(f'<span id="{key_prefix}_folder_{idx}"></span>**📁 {folder_display}**', unsafe_allow_html=True)
            with c2:
                if folder_path and Path(folder_path).exists():
                    if st.button('📂 Open folder', key=f"{key_prefix}_open_{idx}"):
                        open_folder(folder_path)
            with c3:
                st.empty()

            with st.expander(f'See {len(files)} downloaded files'):
                for fname in files:
                    st.markdown(f"<div style='font-size:0.85em;color:#ccc;'>✅ {fname}</div>", unsafe_allow_html=True)
                st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)


def render_error_section(error_list: list, error_log_paths: list = None,
                         dialog_fn=None, key_prefix: str = 'dl'):
    """Render error details expander and optional 'View Full Error Log' button.
    
    Args:
        error_list: List of error messages or DownloadError objects.
        error_log_paths: Optional list of Path objects to download_errors.txt files.
        dialog_fn: Optional callable; if provided, called with error_log_paths.
        key_prefix: Unique prefix for Streamlit widget keys.
    """
    if not error_list:
        return

    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    with st.expander("📋 View Error Details", expanded=True):
        for err in error_list[:20]:
            if hasattr(err, 'message'):
                item_label = f"{err.item_name}: " if hasattr(err, 'item_name') and err.item_name else ""
                st.markdown(f"❌ {item_label}{err.message}", unsafe_allow_html=True)
            else:
                st.markdown(f"❌ {err}")
        if len(error_list) > 20:
            st.caption(f"  ... and {len(error_list) - 20} more")
        st.caption('📄 Full error details are saved in `download_errors.txt` in each course folder.')

    if error_log_paths and dialog_fn:
        valid_paths = [p for p in error_log_paths if p.exists()]
        if valid_paths:
            col_log, _ = st.columns([0.3, 0.7])
            with col_log:
                if st.button("📄 View Full Error Log", key=f"{key_prefix}_view_error_log", use_container_width=True):
                    dialog_fn(valid_paths)


def render_pp_warning(pp_failure_count: int):
    """Render post-processing failure warning if applicable."""
    if pp_failure_count > 0:
        word = "file" if pp_failure_count == 1 else "files"
        st.warning(f"⚠️ {pp_failure_count} {word} failed during post-processing (conversion/extraction). Check download_errors.txt for details.")

def render_config_summary_badges(settings: dict, show_path: bool = True) -> str:
    """Render a rich HTML preview of active settings using color-coded badges."""
    # Build Blue Core Badges
    _mode_disp = "With Subfolders" if settings.get('download_mode') == 'modules' else "All in One Folder"
    _filter_disp = "All Files" if settings.get('file_filter') == 'all' else "Presentations & PDFs"
    
    c_core = "#3fd9ff"
    core_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#94a3b8; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>Core Settings</div>
    <div style='width: 100%;'><span style='display:inline-flex; padding:3px 10px; background-color:rgba(63, 217, 255, 0.05); color:{c_core}; border-radius:4px; font-size:0.78rem; border:1px solid rgba(63, 217, 255, 0.7);'>📁 {_mode_disp}</span></div>
    <span style='display:inline-flex; padding:3px 10px; background-color:rgba(63, 217, 255, 0.15); color:{c_core}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(63, 217, 255, 0.3);'>{_filter_disp}</span>
</div>
"""
    
    # Build Green Canvas Content Badges
    c_canvas = "#2DFFA0"
    _sec_mode_disp = "Separate Folders" if settings.get('dl_isolate_secondary') else "Matching Core Settings"
    sec_org_badge = f"<span style='display:inline-flex; padding:3px 10px; background-color:rgba(45, 255, 160, 0.05); color:{c_canvas}; border-radius:4px; font-size:0.78rem; border:1px solid rgba(45, 255, 160, 0.7);'>📁 {_sec_mode_disp}</span>"
    
    _sec_on = [k.replace('dl_', '').replace('_', ' ').title() for k in PresetManager.SECONDARY_CONTENT_KEYS if settings.get(k)]
    if _sec_on:
        sec_badges_list = "".join([f"<span style='display:inline-flex; padding:3px 10px; background-color:rgba(45, 255, 160, 0.15); color:{c_canvas}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(45, 255, 160, 0.3);'>✓ {x}</span>" for x in _sec_on])
        sec_badges = f"<div style='width: 100%;'>{sec_org_badge}</div>{sec_badges_list}"
    else:
        sec_badges = f"<div style='width: 100%;'><span style='display:inline-flex; padding:3px 10px; background-color:rgba(255, 255, 255, 0.05); color:#94a3b8; border-radius:12px; font-size:0.78rem; border:1px solid #475569;'>None selected</span></div>"
        
    content_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#94a3b8; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>Canvas Content</div>
    {sec_badges}
</div>
"""
    
    # Build Orange AI Optimization Badges
    c_ai = "#FF9838"
    conv_mapping = {
        'convert_zip': 'Unpack Archives (.zip)',
        'convert_pptx': 'PPTX ➡ PDF',
        'convert_word': 'Legacy Word ➡ PDF',
        'convert_excel': 'Excel ➡ PDF & Data',
        'convert_html': 'HTML ➡ PDF',
        'convert_code': 'Code ➡ .TXT',
        'convert_urls': 'Links ➡ TXT',
        'convert_video': 'Video ➡ MP3'
    }
    _conv_on = [conv_mapping.get(k, k) for k in PresetManager.NOTEBOOK_SUB_KEYS if settings.get(k)]
    if _conv_on:
        conv_badges = "".join([f"<span style='display:inline-flex; padding:3px 10px; background-color:rgba(255, 152, 56, 0.15); color:{c_ai}; border-radius:12px; font-size:0.78rem; border:1px solid rgba(255, 152, 56, 0.3);'>⚡ {x}</span>" for x in _conv_on])
    else:
        conv_badges = f"<span style='display:inline-flex; padding:3px 10px; background-color:rgba(255, 255, 255, 0.05); color:#94a3b8; border-radius:12px; font-size:0.78rem; border:1px solid #475569;'>None selected</span>"
        
    conv_html = f"""
<div style='display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;'>
    <div style='width: 100%; font-size:0.8rem; color:#94a3b8; font-weight:600; text-transform:uppercase; margin-bottom:2px;'>AI Optimization & Conversions</div>
    {conv_badges}
</div>
"""
    
    path_html = ""
    if show_path and settings.get('download_path'):
        path_html = f"""
<div style='margin-bottom:4px;'>
    <div style='font-size:0.8rem; color:#94a3b8; font-weight:600; text-transform:uppercase; margin-bottom:4px;'>Saved Path</div>
    <div style='background-color:rgba(0,0,0,0.3); color:#cbd5e1; padding:6px 10px; border-radius:6px; font-size:0.78rem; font-family:monospace; border:1px dashed rgba(255,255,255,0.2); word-break: break-all;'>{esc(settings.get('download_path'))}</div>
</div>
"""
    grid_container = f"""
<div style="display: grid; grid-template-columns: 0.8fr 1.1fr 1.1fr; gap: 15px; margin-bottom: 5px;">
    {core_html}
    {content_html}
    {conv_html}
</div>
"""

    return f"{grid_container}{path_html}"
