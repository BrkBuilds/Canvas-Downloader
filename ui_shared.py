"""
Shared UI components for Download and Sync completion screens.
Extracted to ensure perfect visual parity between both modes.
"""
import streamlit as st
from pathlib import Path
from ui_helpers import open_folder, esc, short_path, friendly_course_name
from sync_manager import format_file_size
import theme


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
