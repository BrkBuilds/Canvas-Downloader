"""
State Registry — Centralized session state management for Canvas Downloader.

All st.session_state key names, defaults, and cleanup functions live here.
This is the single source of truth for state initialization, preventing
scattered `if key not in st.session_state` blocks across the codebase.

Usage:
    from core.state_registry import ensure_download_state, ensure_sync_state
    ensure_download_state()   # Call once at top of app.py
    ensure_sync_state()       # Call once at top of sync_ui.py
"""

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
    'dl_discussions', 'dl_quizzes', 'dl_rubrics', 'dl_submissions',
]

TOTAL_SECONDARY_SUBS = len(SECONDARY_CONTENT_KEYS)


# ═══════════════════════════════════════════════
# Default Value Dictionaries
# ═══════════════════════════════════════════════

DOWNLOAD_DEFAULTS = {
    'api_token': '',
    'api_url': '',
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
    # Sync mode flags (shared between download and sync)
    'sync_mode': False,
    'analysis_result': None,
    'sync_selected_files': {},
    'sync_manifest': None,
    'sync_manager': None,
    'current_mode': 'download',
    'sync_pairs': [],
    'pending_sync_folder': None,
    # NotebookLM master toggle
    'notebooklm_master': False,
    # Secondary content master toggles
    'dl_secondary_master': False,
    'dl_isolate_secondary': False,
    # Card expansion state
    'card2_expanded': False,
    'card3_expanded': False,
}

SYNC_DEFAULTS = {
    'sync_pairs': [],
    'pending_sync_folder': None,
    'analysis_result': None,
    'sync_selected_files': {},
    'sync_manifest': None,
    'sync_manager': None,
    'sync_mode': False,
    'sync_cancelled': False,
}

# Keys created transiently during download execution
DOWNLOAD_TRANSIENT_KEYS = {
    'download_status', 'courses_to_download', 'current_course_index',
    'total_items', 'downloaded_items', 'failed_items', 'total_mb',
    'download_errors_list', 'download_file_details', 'seen_error_sigs',
    'start_time', 'log_deque', 'is_post_processing',
    'pp_failure_count', 'pp_success_count',
    # Isolated retry keys
    'isolated_retry_queue', 'retry_downloaded_items', 'retry_failed_items',
    'retry_isolated_details', 'retry_mb_tracker',
    # Persistent convert keys (generated dynamically)
    *[f'persistent_{k}' for k in NOTEBOOK_SUB_KEYS],
    *[f'persistent_{k}' for k in SECONDARY_CONTENT_KEYS],
}

# Keys created transiently during sync execution
SYNC_TRANSIENT_KEYS = {
    'download_status', 'sync_analysis_results', 'sync_selections',
    'synced_count', 'synced_bytes', 'sync_cancel_requested',
    'sync_cancelled_file_count', 'sync_errors', 'sync_quick_mode',
    'sync_single_pair_idx', 'sync_confirm_count', 'sync_confirm_size',
    'sync_confirm_folders', 'is_post_processing',
    'retry_selections', 'analysis_pass',
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
            st.session_state[key] = default

    # Per-toggle sub-keys for NotebookLM conversions
    for nk in NOTEBOOK_SUB_KEYS:
        if nk not in st.session_state:
            st.session_state[nk] = False

    # Per-toggle sub-keys for Secondary Content
    for sck in SECONDARY_CONTENT_KEYS:
        if sck not in st.session_state:
            st.session_state[sck] = False


def ensure_sync_state() -> None:
    """Ensure all sync-related session state keys exist with defaults.

    Replaces _init_sync_session_state() in sync_ui.py (formerly L83-97).
    """
    for key, default in SYNC_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


# ═══════════════════════════════════════════════
# Cleanup Functions
# ═══════════════════════════════════════════════

def cleanup_download_state() -> None:
    """Remove all transient download keys and reset cancel flags.

    Replaces the inline cleanup logic in app.py's completion/reset handler.
    """
    for key in DOWNLOAD_TRANSIENT_KEYS:
        st.session_state.pop(key, None)

    # Nuclear reset: force all cancel flags to False
    st.session_state['cancel_requested'] = False
    st.session_state['download_cancelled'] = False

    # Nuclear cache clearing to destroy dead aiohttp sessions
    st.cache_data.clear()
    st.session_state.pop('sync_manager', None)
    st.session_state.pop('cm', None)

    st.session_state['step'] = 1


def cleanup_sync_state() -> None:
    """Remove all transient sync keys and reset cancel flags.

    Replaces _cleanup_sync_state() in sync_ui.py (formerly L5947-5977).
    """
    for key in SYNC_TRANSIENT_KEYS:
        st.session_state.pop(key, None)

    # Nuclear reset: force all cancel flags to False
    st.session_state['sync_cancelled'] = False
    st.session_state['sync_cancel_requested'] = False
    st.session_state['cancel_requested'] = False
    st.session_state['download_cancelled'] = False

    # Nuclear cache clearing to destroy dead aiohttp sessions
    st.cache_data.clear()
    st.session_state.pop('sync_manager', None)
    st.session_state.pop('cm', None)

    # Clean up dynamic checkbox keys from the sync review UI
    keys_to_remove = [
        k for k in st.session_state
        if k.startswith(('sync_new_', 'sync_upd_', 'sync_miss_', 'ignore_'))
    ]
    for k in keys_to_remove:
        st.session_state.pop(k, None)

    st.session_state['step'] = 1
