"""
sync.completion — Sync completion, cancellation, and error display.

Extracted from ``sync_ui.py`` L5044-5298 (Phase 4).
Strict physical move — NO logic changes.

Contains:
  - ``show_sync_cancelled()``  (was ``_show_sync_cancelled``)
  - ``show_sync_complete()``   (was ``_show_sync_complete``)
  - ``view_error_log_dialog()`` (was ``_view_error_log_dialog``)
  - ``show_sync_errors()``     (was ``_show_sync_errors``)
"""

from __future__ import annotations

import streamlit as st

import theme
from sync_manager import SyncManager, SyncHistoryManager
from ui_helpers import (
    render_progress_bar,
    render_sync_wizard,
    friendly_course_name,
)
from ui_shared import (
    render_completion_card, render_folder_cards,
    render_pp_warning,
    error_log_dialog,
)
from core.state_registry import cleanup_sync_state


def show_sync_cancelled():
    """Render the sync-cancelled screen with error details."""
    render_sync_wizard(st, 3)

    cancelled_count = st.session_state.get('sync_cancelled_file_count', 0)
    total_files = sum(
        len(sel['new']) + len(sel['updates']) + len(sel['redownload'])
        for sel in st.session_state.get('sync_selections', [])
    )

    # Dynamic text: "course" during scanning, "file" during download, post-processing status
    if st.session_state.get('is_post_processing', False):
        cancel_summary_msg = "Cancelled during post-processing."
    else:
        is_file_phase = total_files > 0
        if is_file_phase:
            cancel_summary_msg = f"Cancelled after {cancelled_count} of {total_files} {'file' if total_files == 1 else 'files'}."
        else:
            cancel_summary_msg = "Cancelled during Course Analysis."

    # Premium styled cancellation card
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, {theme.ERROR_BG} 0%, {theme.BG_PAGE} 100%);
        border: 1px solid {theme.ERROR};
        border-radius: 12px;
        padding: 28px 32px;
        margin: 20px 0;
        box-shadow: 0 4px 20px rgba(239, 68, 68, 0.15);
    ">
        <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 12px;">
            <span style="font-size: 2rem;">🛑</span>
            <h2 style="margin: 0; color: {theme.ERROR}; font-size: 1.5rem; font-weight: 700;">Sync Cancelled</h2>
        </div>
        <p style="color: {theme.TEXT_LIGHT}; font-size: 1rem; margin: 0 0 8px 0;">
            {'Sync was cancelled.'}
        </p>
        <div style="
            background: rgba(239, 68, 68, 0.08);
            border-radius: 8px;
            padding: 12px 16px;
            margin-top: 12px;
            display: inline-block;
        ">
            <span style="color: {theme.ERROR_LIGHT}; font-size: 0.9rem; font-weight: 600;">
                {cancel_summary_msg}
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    show_sync_errors()

    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    if st.button("🏠 " + 'Go to front page', type="primary", use_container_width=True):
        _cleanup_sync_state()
        st.rerun()


def show_sync_complete():
    """Render the sync-complete screen with results and retry options."""
    # Step wizard
    render_sync_wizard(st, 4)

    synced_count = st.session_state.get('synced_count', 0)
    sync_errors = st.session_state.get('sync_errors', [])
    synced_details = st.session_state.get('synced_details', {})

    custom_text = None
    if sync_errors and synced_count == 0:
        # Full failure - progress bar will be red
        mode = 'complete_error'
    elif sync_errors:
        # Partial failure - progress bar will be yellow
        mode = 'complete_warning'
    else:
        mode = 'complete'
        custom_text = 'Sync Complete'

    render_progress_bar(st, 1, 1, mode=mode, custom_text=custom_text)

    # Summary card logic
    total_bytes = st.session_state.get('synced_bytes', 0)
    
    render_completion_card(
        synced_count=synced_count,
        error_count=len(sync_errors),
        total_bytes=total_bytes,
        mode='sync'
    )

    # UN-TRAPPED QUICK SYNC WARNING:
    skipped_data = st.session_state.get('qs_skipped', {})
    local_del = skipped_data.get('local_del', 0)
    canvas_del = skipped_data.get('canvas_del', 0)

    if local_del > 0 or canvas_del > 0:
        parts = []
        if local_del > 0:
            parts.append(f"{local_del} locally deleted files")
        if canvas_del > 0:
            parts.append(f"{canvas_del} files deleted on Canvas")
            
        joined_parts = " and ".join(parts)
        st.warning(f"⚠️ Quick Sync skipped {joined_parts}. To download them, run a normal 'Analyze, Review & Sync' and select them manually.")
        
        # Cleanup
        if 'qs_skipped' in st.session_state:
            del st.session_state['qs_skipped']

    # Post-processing failure warning
    render_pp_warning(st.session_state.get('pp_failure_count', 0))

    # Surface Structural Discovery Errors gracefully
    total_structural_errors = sum(
        res['res_data']['result'].structural_errors
        for res in st.session_state.get('sync_selections', [])
        if res.get('res_data') and hasattr(res['res_data'].get('result'), 'structural_errors')
    )
    if total_structural_errors > 0:
        st.warning(
            f"⚠️ {total_structural_errors} module(s) or folder(s) could not be fetched from Canvas due to connection/server errors. Their files are consequently missing from the syncing checklist and cannot be isolated for a targeted retry. A full Rescan is recommended later.",
            icon="⚠️"
        )

    retry_selections = st.session_state.get('retry_selections', [])

    # We use sync_ui's custom show_sync_errors wrapper which sets up its own expander
    show_sync_errors()

    if sync_errors and retry_selections:
        st.markdown("<div style='margin-top: -15px; margin-bottom: 25px;'></div>", unsafe_allow_html=True)
        col_retry, _ = st.columns([0.25, 0.75])
        with col_retry:
            if st.button("🔄 Retry Failed Downloads", type="secondary", use_container_width=True):
                # Critical Re-hydration: We leave course as None, safely offloading API calls to the async pipeline
                for r_sel in retry_selections:
                    pair_info = r_sel['res_data']['pair']
                    r_sel['res_data']['course'] = None
                    try:
                        r_sel['res_data']['sync_manager'] = SyncManager(
                            local_path=pair_info['local_folder'],
                            course_id=pair_info['course_id'],
                            course_name=pair_info['course_name']
                        )
                    except Exception:
                        r_sel['res_data']['sync_manager'] = None
                
                st.session_state['sync_selections'] = retry_selections
                st.session_state['download_status'] = 'syncing'
                st.session_state['step'] = 3
                st.session_state['sync_errors'] = []
                st.session_state['sync_cancel_requested'] = False
                st.session_state['sync_cancelled'] = False
                st.rerun()

    # Folders updated — card style with dropdown
    sync_pairs = st.session_state.get('sync_pairs', [])
    sync_selections = st.session_state.get('sync_selections', [])
    
    # Translate synced_details format to match render_folder_cards API
    # synced_details holds pair_idx -> list of filenames
    file_dropdown_details = {}
    folder_paths_map = {}
    
    if sync_selections:
        for sel in sync_selections:
            pair_idx = sel['pair_idx']
            if pair_idx >= len(sync_pairs):
                continue
            pair = sync_pairs[pair_idx]
            display_name = friendly_course_name(pair['course_name'])
            
            # Use display_name suffix to avoid key collisions on similar names
            f_key = f"{display_name} ({pair_idx})"
            file_dropdown_details[f_key] = synced_details.get(pair_idx, [])
            folder_paths_map[f_key] = pair['local_folder']
            
    render_folder_cards(file_dropdown_details, folder_paths_map, key_prefix='sync_complete')

    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    if st.button("🏠 " + 'Go to front page', type="primary", use_container_width=True):
        _cleanup_sync_state()
        st.rerun()





def show_sync_errors():
    """Render sync errors in an expander with error log viewer button."""
    sync_errors = st.session_state.get('sync_errors', [])
    if sync_errors:
        # The summary card handles the warning/error banner.
        # Here we just show the details expander.
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        with st.expander("📋 " + 'View Error Details', expanded=True):
            for err in sync_errors[:20]:
                st.markdown(f"❌ {err}")
            if len(sync_errors) > 20:
                st.caption(f"  ... and {len(sync_errors) - 20} more")
            
            st.caption('📄 Full error details are saved in `download_errors.txt` in each course folder.')
        
        # In-App Error Log Viewer button
        sync_selections = st.session_state.get('sync_selections', [])
        error_log_paths = []
        for sel in sync_selections:
            try:
                sm = sel.get('res_data', {}).get('sync_manager')
                if sm and sm.local_path.exists():
                    log_file = sm.local_path / 'download_errors.txt'
                    if log_file.exists():
                        error_log_paths.append(log_file)
            except Exception:
                pass
        
        if error_log_paths:
            col_log, _ = st.columns([0.3, 0.7])
            with col_log:
                if st.button("📄 View Full Error Log", key="sync_view_error_log", use_container_width=True):
                    error_log_dialog(error_log_paths)


def _cleanup_sync_state():
    """Backward-compatible alias for cleanup_sync_state."""
    cleanup_sync_state()
