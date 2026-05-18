"""
sync.completion - Sync completion, cancellation, and error display.

Extracted from ``sync_ui.py`` L5044-5298 (Phase 4).
Strict physical move - NO logic changes.

Contains:
  - ``show_sync_cancelled()``  (was ``_show_sync_cancelled``)
  - ``show_sync_complete()``   (was ``_show_sync_complete``)
  - ``view_error_log_dialog()`` (was ``_view_error_log_dialog``)
  - ``show_sync_errors()``     (was ``_show_sync_errors``)
"""

from __future__ import annotations

import streamlit as st

import theme
from sync_manager import SyncManager
from ui_helpers import (
    render_sync_wizard,
    friendly_course_name,
)
from ui_shared import (
    render_completion_card, render_folder_cards,
    render_pp_warning, render_error_section,
    error_log_dialog,
)
from core.state_registry import cleanup_sync_state
from engine.notifications import play_completion_beep


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
    col_front, _ = st.columns([0.35, 0.65])
    with col_front:
        if st.button('Go to front page', key="page_nav_front_page_sync", type="primary", use_container_width=True):
            _cleanup_sync_state()
            st.rerun()


def show_sync_complete():
    """Render the sync-complete screen with results and retry options."""
    # Completion beep - fired exactly once per sync via session sentinel.
    # cleanup_sync_state() resets this flag, so the next sync rearms it.
    if (
        st.session_state.get('notifications_enabled', True)
        and not st.session_state.get('completion_beep_fired', False)
    ):
        _sync_count = st.session_state.get('synced_count', 0)
        if _sync_count == 0:
            _is_qs = st.session_state.get('sync_quick_mode', False)
            _notif_mode = 'quick_sync_uptodate' if _is_qs else 'sync_uptodate'
            play_completion_beep(mode=_notif_mode, summary='All files are up to date - nothing to download.')
        else:
            _sync_courses = len(st.session_state.get('sync_selections', []))
            _sync_summary = f"Synced {_sync_count} file{'s' if _sync_count != 1 else ''} across {_sync_courses} course{'s' if _sync_courses != 1 else ''}."
            play_completion_beep(mode='sync', summary=_sync_summary)
        st.session_state['completion_beep_fired'] = True

    # Step wizard
    render_sync_wizard(st, 4)
    st.markdown('<h2 class="step-header">Sync Complete!</h2>', unsafe_allow_html=True)

    synced_count = st.session_state.get('synced_count', 0)
    sync_errors = st.session_state.get('sync_errors', [])
    synced_details = st.session_state.get('synced_details', {})
    sync_selections = st.session_state.get('sync_selections', [])
    sync_pairs = st.session_state.get('sync_pairs', [])

    # Summary card logic
    total_bytes = st.session_state.get('synced_bytes', 0)
    
    size_skipped = st.session_state.get('size_skipped_files', [])
    limit_mb = st.session_state.get('max_file_size_mb', 0)

    with st.container(border=True, key='completion_dashboard'):
        # Sync errors are plain strings - classify by checking for LTI/stream markers
        _sync_retriable = sum(
            1 for err in sync_errors
            if hasattr(err, 'error_type') and isinstance(getattr(err, 'context', None), dict)
            and err.context.get('filepath')
            and getattr(err, 'error_type', '') != 'LTI/Media Stream'
        ) if sync_errors else 0
        # For sync errors that are plain strings, treat all as retriable
        _sync_unresolvable = 0
        if sync_errors:
            _plain_str_count = sum(1 for e in sync_errors if isinstance(e, str))
            _obj_count = len(sync_errors) - _plain_str_count
            if _obj_count > 0:
                _sync_unresolvable = _obj_count - _sync_retriable
            # Plain strings are retriable (generic errors)
            _sync_retriable += _plain_str_count

        _retry_attempted = st.session_state.get('retry_attempted', False)
        _retry_total = st.session_state.get('retry_total_attempted', 0)
        _retry_resolved = st.session_state.get('retry_resolved_count', 0)

        render_completion_card(
            synced_count=synced_count,
            error_count=len(sync_errors),
            total_bytes=total_bytes,
            mode='sync',
            size_skipped_files=size_skipped,
            size_limit_mb=limit_mb,
            retriable_count=_sync_retriable,
            unresolvable_count=_sync_unresolvable,
            courses_count=len(sync_selections),
            retry_attempted=_retry_attempted,
            retry_resolved=_retry_resolved,
            retry_total=_retry_total,
        )

        # UN-TRAPPED QUICK SYNC WARNING:
        skipped_data = st.session_state.get('qs_skipped', {})
        local_del = skipped_data.get('local_del', 0)
        canvas_del = skipped_data.get('canvas_del', 0)
        edited = skipped_data.get('edited', 0)

        if local_del > 0 or canvas_del > 0 or edited > 0:
            parts = []
            if edited > 0:
                parts.append(f"{edited} {'file' if edited == 1 else 'files'} you edited locally")
            if local_del > 0:
                parts.append(f"{local_del} {'file' if local_del == 1 else 'files'} deleted locally")
            if canvas_del > 0:
                parts.append(f"{canvas_del} {'file' if canvas_del == 1 else 'files'} deleted on Canvas")

            joined_parts = " and ".join(parts)
            from ui.amber_notice import render_amber_notice
            render_amber_notice(
                f"Quick Sync skipped {joined_parts}.",
                icon="⚠️",
                detail="To download them, run a normal 'Analyze, Review & Sync' and select them manually.",
            )

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
                f"{total_structural_errors} module(s) or folder(s) could not be fetched from Canvas due to connection/server errors. Their files are consequently missing from the syncing checklist and cannot be isolated for a targeted retry. A full Rescan is recommended later.",
                icon="⚠️"
            )

        retry_selections = st.session_state.get('retry_selections', [])

        # Ignored files note
        if st.session_state.get('sync_has_ignored_files'):
            from ui.amber_notice import render_amber_notice
            render_amber_notice(
                "Some files were ignored and not synced.",
                detail="You can manage ignored files from the Sync Hub.",
            )

        # Build error log paths for the error section
        _sync_error_log_paths = []
        for sel in st.session_state.get('sync_selections', []):
            try:
                sm = sel.get('res_data', {}).get('sync_manager')
                if sm and sm.local_path.exists():
                    log_file = sm.local_path / 'download_errors.txt'
                    if log_file.exists():
                        _sync_error_log_paths.append(log_file)
            except Exception:
                pass

        # Retry callback
        def _do_sync_retry():
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

        _has_sync_retry = bool(sync_errors and retry_selections)
        _sync_retry_failed = _retry_attempted and _retry_total > 0 and _retry_resolved == 0

        render_error_section(
            sync_errors, _sync_error_log_paths,
            dialog_fn=error_log_dialog,
            key_prefix='sync_complete',
            retry_btn_callback=_do_sync_retry if _has_sync_retry else None,
            has_retriable_errors=_has_sync_retry,
            retry_failed=_sync_retry_failed,
        )

        # Amber notice when all retries exhausted - guide user to manual download
        if _sync_retry_failed:
            from ui.amber_notice import render_amber_notice
            render_amber_notice(
                "Retry didn't work - these files may be temporarily unavailable.",
                detail="Check your internet connection and try again later, or download them directly from Canvas.",
            )

    # Folders updated - card style with filetype summary
    file_dropdown_details = {}
    folder_paths_map = {}

    if sync_selections:
        for sel in sync_selections:
            pair_idx = sel['pair_idx']
            if pair_idx >= len(sync_pairs):
                continue
            pair = sync_pairs[pair_idx]
            display_name = friendly_course_name(pair['course_name'])

            f_key = f"{display_name} ({pair_idx})"
            file_dropdown_details[f_key] = synced_details.get(pair_idx, [])
            folder_paths_map[f_key] = pair['local_folder']

    render_folder_cards(file_dropdown_details, folder_paths_map, key_prefix='sync_complete', show_files_expander=True)

    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    col_front, _ = st.columns([0.35, 0.65])
    with col_front:
        if st.button('Go to front page', key='page_nav_front_page_sync_complete', type="primary", use_container_width=True):
            _cleanup_sync_state()
            st.rerun()





def show_sync_errors():
    """Render sync errors in an expander with error log viewer button."""
    # Size-skipped files are now rendered inside render_completion_card

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
            
            if st.session_state.get('error_log_enabled', False):
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
