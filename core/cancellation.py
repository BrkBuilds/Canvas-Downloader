"""
Cancellation — Shared cancel callbacks and checkers for Canvas Downloader.

Provides unified cancellation primitives used by both the download flow
(app.py) and the sync flow (sync_ui.py).

Usage:
    from core.cancellation import cancel_download, cancel_sync, is_download_cancelled, is_sync_cancelled
"""

import streamlit as st


# ═══════════════════════════════════════════════
# Cancel Callbacks (fire via on_click, BEFORE re-render)
# ═══════════════════════════════════════════════

def cancel_download() -> None:
    """Instant on_click callback for download cancellation.

    Sets both download cancel flags before Streamlit re-enters the main loop.
    Replaces cancel_download_callback() in app.py (formerly L338-341).
    """
    st.session_state['download_cancelled'] = True
    st.session_state['cancel_requested'] = True


def cancel_sync() -> None:
    """Instant on_click callback for sync cancellation.

    Sets both sync cancel flags before Streamlit re-enters the main loop.
    Replaces cancel_process_callback() in sync_ui.py (formerly L74-77).
    """
    st.session_state['sync_cancelled'] = True
    st.session_state['sync_cancel_requested'] = True


# ═══════════════════════════════════════════════
# Cancellation Checkers (polled during execution)
# ═══════════════════════════════════════════════

def is_download_cancelled() -> bool:
    """Check if a download cancellation has been requested.

    Replaces check_cancellation() in app.py (formerly L335-336).
    """
    return (
        st.session_state.get('cancel_requested', False)
        or st.session_state.get('download_cancelled', False)
    )


def is_sync_cancelled() -> bool:
    """Check if a sync cancellation has been requested.

    Consolidates inline `st.session_state.get('sync_cancel_requested', False)`
    checks scattered throughout sync_ui.py.
    """
    return (
        st.session_state.get('sync_cancel_requested', False)
        or st.session_state.get('sync_cancelled', False)
    )
