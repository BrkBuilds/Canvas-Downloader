"""
State Registry - Centralized session state management for Canvas Downloader.

All st.session_state key names, defaults, and cleanup functions live here.
This is the single source of truth for state initialization, preventing
scattered `if key not in st.session_state` blocks across the codebase.

Usage:
    from core.state_registry import ensure_download_state, ensure_sync_state
    ensure_download_state()   # Call once at top of app.py
    ensure_sync_state()       # Call once at top of sync_ui.py
"""

import copy
import streamlit as st
from pathlib import Path


# ═══════════════════════════════════════════════
# Key Name Constants
# ═══════════════════════════════════════════════

NOTEBOOK_SUB_KEYS = [
    'convert_zip', 'convert_pptx', 'convert_word', 'convert_excel',
    'convert_html', 'convert_code', 'convert_urls', 'convert_video',
]

SECONDARY_CONTENT_KEYS = [
    'dl_assignments', 'dl_syllabus', 'dl_announcements',
    'dl_discussions', 'dl_quizzes', 'dl_submissions',
    # 'dl_rubrics',  # temporarily disabled - see RUBRICS_ENABLED in canvas_logic.py
]

TOTAL_SECONDARY_SUBS = len(SECONDARY_CONTENT_KEYS)

# Panopto output toggles (Section 4 of the download settings page). Session-only
# and reset each app launch, EXACTLY like the Canvas Content keys above: the
# engine config (model/device/language) is the only persisted part. Ordered
# url, mp4, mp3, txt, srt (left-to-right display order), matching
# ui.download_settings.PANOPTO_OUTPUT_DEFS - which is the definition; this list
# is what RESETS them, so a key present there and missing here is a toggle that
# silently survives a run and turns itself on again in the next one.
PANOPTO_OUTPUT_KEYS = ['pan_out_url', 'pan_out_mp4', 'pan_out_mp3',
                       'pan_out_txt', 'pan_out_srt']

TOTAL_PANOPTO_OUTPUTS = len(PANOPTO_OUTPUT_KEYS)


# ═══════════════════════════════════════════════
# Default Value Dictionaries
# ═══════════════════════════════════════════════

DOWNLOAD_DEFAULTS = {
    'api_token': '',
    'api_url': '',
    'url_verified': False,
    'is_authenticated': False,
    'download_path': str(Path.home() / "Downloads"),
    'selected_course_ids': [],
    'step': 1,
    'download_mode': 'modules',
    'cancel_requested': False,
    'download_cancelled': False,
    'user_name': '',
    'course_mb_downloaded': {},
    'file_filter': 'all',
    # Settings keys (missing from earlier versions - M-15)
    'debug_mode': False,
    'error_log_enabled': False,
    'concurrent_downloads': 5,
    'use_12h_format': False,
    'skipped_discovery_errors': 0,
    '_sync_cancel_warning_shown': False,
    # Sync mode flags (shared between download and sync)
    'sync_mode': False,
    'sync_manager': None,
    'current_mode': 'download',
    'sync_pairs': [],
    'pending_sync_folder': None,
    # NotebookLM master toggle
    'notebooklm_master': False,
    # Secondary content master toggles
    'dl_secondary_master': False,
    'dl_isolate_secondary': False,
    # Panopto (Section 4) master toggle + organization layout (session-only).
    # 'pan_layout': 'match' -> alongside course files; 'separate' -> a
    # "Panopto Recordings" subfolder. Mirrors dl_isolate_secondary's role.
    'pan_master': False,
    'pan_layout': 'match',
    # Card expansion state
    'card2_expanded': False,
    'card3_expanded': False,
    'card_panopto_expanded': False,
    'token_loaded': False,
    'hub_view_mode': 'View All',
    'hub_layer': 'layer_1',
    'hub_editing_pair_idx': None,
    'hub_is_adding_new_pair': False,
    'hub_cs_selected_id': None,
    'sync_d_selected_id': None,
    'preset_hub_tab': 'user',
    'enable_cbs_filters': False,
    # File-size filter (Settings dialog)
    'max_file_size_enabled': False,
    'max_file_size_mb': 500,
    # Archive-extraction guard (Settings dialog). The zip-bomb protection in
    # converters/archive.py measures SIZE and RATIO, never COUNT, so an archive
    # of many small files passes it easily: one real course unpacked 21,630
    # files, and the deep nesting is also where the over-260-character paths
    # came from. Off by default - extraction behaviour does not change until the
    # user asks for a limit.
    'archive_max_files_enabled': False,
    'archive_max_files': 1000,
    # Persistent default download folder (Settings dialog; empty = use ~/Downloads)
    'default_download_path': '',
    # Completion sound/notification (Settings dialog)
    'notifications_enabled': True,
    # One-shot sentinel to prevent replaying the completion beep on every rerun
    'completion_beep_fired': False,
    # Quick Download mode
    'quick_download_mode': False,
    'quick_preset_id': 'quick_full',
    'quick_org_mode': 'modules',
    # L-13: Sync history retention - number of past operations to keep.
    'sync_history_retention': 50,
    # NOTE: no 'panopto_feature_enabled' / 'panopto_settings_loaded' here. Both
    # were leftovers from the era when Panopto was a standalone sidebar page;
    # nothing has read either since it became Section 4 of the download page, and
    # the Panopto config is loaded on demand from its own JSON subtree.
}

SYNC_DEFAULTS = {
    'sync_pairs': [],
    'pending_sync_folder': None,
    'sync_manager': None,
    'sync_mode': False,
    'sync_cancelled': False,
    'hub_view_mode': 'View All',
    'hub_layer': 'layer_1',
    'hub_editing_pair_idx': None,
    'hub_is_adding_new_pair': False,
    'preset_hub_tab': 'user',
    'hub_cs_selected_id': None,
    'sync_d_selected_id': None,
}

# Keys created transiently during download execution
DOWNLOAD_TRANSIENT_KEYS = {
    'download_status', 'courses_to_download', 'current_course_index',
    'total_items', 'downloaded_items', 'failed_items', 'total_mb',
    'download_errors_list', 'download_file_details', 'seen_error_sigs',
    'start_time', 'log_deque', 'is_post_processing',
    'pp_failure_count', 'pp_success_count',
    # Archives the file-count guard declined this run. Per-run like every
    # other post-processing tally: the download bridge APPENDS to it (one
    # entry per course), so a stale list would show the previous run's
    # archives on a completion screen where nothing was skipped.
    'pp_archives_skipped',
    # Isolated retry keys
    'isolated_retry_queue', 'retry_downloaded_items', 'retry_failed_items',
    'retry_isolated_details', 'retry_mb_tracker',
    'retry_attempted', 'retry_resolved_count', 'retry_total_attempted',
    'size_skipped_files', 'skipped_discovery_errors',
    # Panopto run state (Phase 2): per-run discovery/progress trackers.
    'panopto_mb_tracker', 'panopto_run_started',
    '_panopto_warned', 'panopto_summary',
    # Persistent convert keys (generated dynamically)
    *[f'persistent_{k}' for k in NOTEBOOK_SUB_KEYS],
    *[f'persistent_{k}' for k in SECONDARY_CONTENT_KEYS],
    'persistent_dl_isolate_secondary',
    # Per-run Panopto snapshot (mirrors the secondary content persistent keys).
    *[f'persistent_{k}' for k in PANOPTO_OUTPUT_KEYS],
    'persistent_pan_layout',
    'log_content',
    # macOS Office automation per-run sentinels (re-prime + re-quit next run).
    '_office_quit_fired', '_tcc_batch_active',
}

# Keys created transiently during sync execution
SYNC_TRANSIENT_KEYS = {
    'download_status', 'sync_analysis_results', 'sync_selections',
    'synced_count', 'synced_bytes', 'sync_cancel_requested',
    'sync_cancelled_file_count', 'sync_errors', 'sync_quick_mode',
    'is_post_processing',
    'retry_selections', 'analysis_pass',
    # Today dashboard (in-page daily/Quick Sync) run markers.
    'today_sync_active', 'today_sync_is_auto',
    'size_skipped_files', 'sync_has_ignored_files',
    # Files delivered as a "_NewVersion" sibling instead of overwriting the copy
    # already on disk - either because the user had edited it or because it was
    # open in another program. Collected so the completion screen can say a
    # second file appeared and why; without it the folder silently gains copies.
    'sync_newversion_files',
    # What the analysis actually compared, so the "all up to date" completion
    # card can say how much work it did instead of only that there was none.
    'sync_uptodate_stats',
    # sync_failed recovery keys
    'sync_worker_error', 'qs_cancel_route', 'qs_skipped',
    # Re-attachable sync worker (H-2 heartbeat pattern) - future/pool refs
    # and the cached batch outcome must never leak into the next sync run.
    'sync_worker_future', 'sync_worker_pool', 'sync_worker_result',
    'synced_details', 'synced_groups', 'pp_failure_count', 'pp_success_count',
    'pp_archives_skipped',
    # NOTE: 'today_sync_notice' is deliberately NOT transient - the dismissible
    # Today success card must survive cleanup_sync_state() (which runs the
    # moment the run finishes) until the user closes it or the next run
    # replaces it (start_today_sync pops the stale one).
    'retry_attempted', 'retry_resolved_count', 'retry_total_attempted',
    'completion_beep_fired',
    # Panopto sync-pass trackers (mirror the download-mode transient keys).
    # 'log_deque' rides along: the sync Panopto pass owns it while running
    # (recreated fresh each pass) - clearing it here stops a finished sync's
    # terminal lines from ever leaking into a later run's log.
    'panopto_mb_tracker',
    'panopto_run_started', '_panopto_warned', 'panopto_summary',
    'panopto_uptodate_total', '_sync_history_ts', 'log_deque',
    # M-8: reset per-run warning sentinels so they re-arm on the next sync
    '_sync_cancel_warning_shown',
    # macOS Office automation per-run sentinels (re-prime + re-quit next run).
    '_office_quit_fired', '_tcc_batch_active',
    # Sync history filters
    'sync_history_course', 'sync_hist_course_select', 'sync_history_filter',
    # Bulk "Add Course" (multi-folder selection) - transient while the add form
    # is open; must never survive a navigation away from the Sync page.
    '_bulk_folders_raw', '_bulk_total', '_bulk_index', '_bulk_folder_queue',
}


# ═══════════════════════════════════════════════
# Initialization Functions
# ═══════════════════════════════════════════════

def ensure_download_state() -> None:
    """Ensure all download-related session state keys exist with defaults.

    Replaces the scattered `if key not in st.session_state` blocks
    in app.py (formerly L224-296).
    """
    for key, default in DOWNLOAD_DEFAULTS.items():
        if key not in st.session_state:
            # deepcopy so mutable defaults (lists, dicts) are not shared across sessions.
            st.session_state[key] = copy.deepcopy(default)

    # Per-toggle sub-keys for NotebookLM conversions
    for nk in NOTEBOOK_SUB_KEYS:
        if nk not in st.session_state:
            st.session_state[nk] = False

    # Per-toggle sub-keys for Secondary Content
    for sck in SECONDARY_CONTENT_KEYS:
        if sck not in st.session_state:
            st.session_state[sck] = False

    # Per-toggle sub-keys for Panopto outputs (session-only, like the above).
    for pk in PANOPTO_OUTPUT_KEYS:
        if pk not in st.session_state:
            st.session_state[pk] = False


def ensure_sync_state() -> None:
    """Ensure all sync-related session state keys exist with defaults.

    Replaces _init_sync_session_state() in sync_ui.py (formerly L83-97).
    """
    for key, default in SYNC_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = copy.deepcopy(default)


# ═══════════════════════════════════════════════
# Cleanup Functions
# ═══════════════════════════════════════════════

# Per-run download CONFIGURATION keys (scalar) reset to their DOWNLOAD_DEFAULTS
# value at the end of a run. The per-toggle sub-key lists (SECONDARY_CONTENT_KEYS,
# NOTEBOOK_SUB_KEYS, PANOPTO_OUTPUT_KEYS) are reset to False alongside these.
DOWNLOAD_CONFIG_KEYS = [
    'file_filter', 'download_mode',
    'dl_isolate_secondary', 'dl_secondary_master',
    'notebooklm_master', 'pan_master', 'pan_layout',
    'card2_expanded', 'card3_expanded', 'card_panopto_expanded',
]


def _reset_download_config() -> None:
    """Reset per-run download configuration to defaults for a fresh next run."""
    for key in DOWNLOAD_CONFIG_KEYS:
        st.session_state[key] = copy.deepcopy(DOWNLOAD_DEFAULTS[key])
    for key in (*SECONDARY_CONTENT_KEYS, *NOTEBOOK_SUB_KEYS, *PANOPTO_OUTPUT_KEYS):
        st.session_state[key] = False


def cleanup_download_state() -> None:
    """Remove all transient download keys and reset cancel flags.

    Replaces the inline cleanup logic in app.py's completion/reset handler.
    """
    for key in DOWNLOAD_TRANSIENT_KEYS:
        st.session_state.pop(key, None)

    # Nuclear reset: clear threading.Event + session_state cancel flags
    from core.cancellation import reset_download_cancel
    reset_download_cancel()
    # Re-arm the completion-sound sentinel for the next run.
    st.session_state['completion_beep_fired'] = False

    # macOS: tidy away any Office apps we launched for post-processing (only if
    # they have no documents open - never disturbs the user's own work).
    try:
        from engine.applescript_bridge import quit_idle_office_apps
        quit_idle_office_apps()
    except Exception:
        pass

    # NOT cleared here: the course list cache.
    #
    # This used to call `st.cache_resource.clear()` - a GLOBAL clear, and
    # `fetch_courses` is the app's only cache_resource, so it nuked the course
    # list. That reads as "start the next run fresh", but this function is also
    # called by the SIDEBAR NAV BUTTONS on every mode switch, so every single
    # navigation threw the course list away and the next page that needed one
    # paid ~950 ms of sequential Canvas round-trips. Measured 2026-07-31: it is
    # why `-> Today` was the only fast navigation in the app (it is the one
    # screen that needs no course list) while the rest cost 1.2-1.9 s.
    #
    # Nothing about finishing a download changes which courses you are enrolled
    # in, and the two cases that genuinely need fresh data clear it explicitly:
    # logout (`ui/auth.py`) and the course list's Refresh button
    # (`ui/course_selector.py`). Everything else is handled by the background
    # refresh in `app.fetch_courses`.
    st.session_state.pop('sync_manager', None)
    st.session_state.pop('cm', None)

    # Clear course selection - download is done, start fresh for next run.
    # Course-selection checkboxes: clear both the logical ID list and the
    # per-course widget state keys (Streamlit re-binds widget keys on re-render).
    st.session_state['selected_course_ids'] = []
    for key in list(st.session_state.keys()):
        if key.startswith('dl_chk_'):
            del st.session_state[key]

    # Reset the per-run DOWNLOAD CONFIGURATION back to defaults so the next
    # download (Quick or Custom) starts fresh. These are plain config keys (not
    # in DOWNLOAD_TRANSIENT_KEYS), so without this they would silently persist
    # from one download to the next - e.g. running a Quick Download preset and
    # then opening Custom Download would show the previous run's settings already
    # applied. The ONLY intended carry-over is Quick Download's "Customize this
    # configuration in Custom Download" path, which navigates directly without a
    # completed download and therefore never reaches this cleanup.
    _reset_download_config()

    st.session_state['step'] = 1


def cleanup_sync_state() -> None:
    """Remove all transient sync keys and reset cancel flags.

    Replaces _cleanup_sync_state() in sync_ui.py (formerly L5947-5977).
    """
    for key in SYNC_TRANSIENT_KEYS:
        st.session_state.pop(key, None)

    # Nuclear reset: clear threading.Event + session_state sync cancel flags.
    # sync_cancel_requested is already removed by SYNC_TRANSIENT_KEYS pop above.
    # cancel_requested / download_cancelled are download-specific - do not reset here.
    from core.cancellation import reset_sync_cancel
    reset_sync_cancel()
    st.session_state['download_cancelled'] = False
    # Re-arm the completion-sound sentinel for the next sync run.
    st.session_state['completion_beep_fired'] = False

    # macOS: tidy away any Office apps we launched for post-processing (only if
    # they have no documents open - never disturbs the user's own work).
    try:
        from engine.applescript_bridge import quit_idle_office_apps
        quit_idle_office_apps()
    except Exception:
        pass

    # NOT cleared here: the course list cache.
    #
    # This used to call `st.cache_resource.clear()` - a GLOBAL clear, and
    # `fetch_courses` is the app's only cache_resource, so it nuked the course
    # list. That reads as "start the next run fresh", but this function is also
    # called by the SIDEBAR NAV BUTTONS on every mode switch, so every single
    # navigation threw the course list away and the next page that needed one
    # paid ~950 ms of sequential Canvas round-trips. Measured 2026-07-31: it is
    # why `-> Today` was the only fast navigation in the app (it is the one
    # screen that needs no course list) while the rest cost 1.2-1.9 s.
    #
    # Nothing about finishing a download changes which courses you are enrolled
    # in, and the two cases that genuinely need fresh data clear it explicitly:
    # logout (`ui/auth.py`) and the course list's Refresh button
    # (`ui/course_selector.py`). Everything else is handled by the background
    # refresh in `app.fetch_courses`.
    st.session_state.pop('sync_manager', None)
    st.session_state.pop('cm', None)

    # Invalidate ignored-files cache so next render re-reads from SQLite
    st.session_state.pop('_ignored_files_cache', None)

    # L-5: the review's "keep ignored expander open" latch is per-run UI state.
    st.session_state.pop('keep_ignored_open', None)

    # Clean up dynamic checkbox keys from the sync review UI, including the
    # Smart-Select filetype toggles (sync_filter_ext_*/sync_filter_btn_*) which
    # would otherwise carry stale selection state into an unrelated next sync.
    keys_to_remove = [
        k for k in st.session_state
        if k.startswith((
            'sync_new_', 'sync_upd_', 'sync_updmod_', 'sync_locdel_', 'ignore_',
            'sync_pan_', 'sync_panlocdel_',
            'sync_filter_ext_', 'sync_filter_btn_',
        ))
    ]
    for k in keys_to_remove:
        st.session_state.pop(k, None)

    st.session_state['step'] = 1
