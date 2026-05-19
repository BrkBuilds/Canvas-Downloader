"""
Cancellation - Shared cancel callbacks and checkers for Canvas Downloader.

Provides unified cancellation primitives used by both the download flow
(app.py) and the sync flow (sync_ui.py).

Threading model:
  - threading.Event objects are the authoritative cancel signal. They are
    safe to check from background threads without Streamlit context.
  - st.session_state writes are kept in sync for UI reactivity, but wrapped
    in try/except so failures on background threads never crash the caller.

Usage:
    from core.cancellation import cancel_download, cancel_sync, is_download_cancelled, is_sync_cancelled
"""

import threading
import streamlit as st

# ═══════════════════════════════════════════════
# Module-level Events (thread-safe cancel signals)
# ═══════════════════════════════════════════════

_download_cancel_event = threading.Event()
_sync_cancel_event = threading.Event()


# ═══════════════════════════════════════════════
# Cancel Callbacks (fire via on_click, BEFORE re-render)
# ═══════════════════════════════════════════════

def cancel_download() -> None:
    """Instant on_click callback for download cancellation.

    Sets the threading.Event (thread-safe) and mirrors to session_state
    for UI reactivity.
    """
    _download_cancel_event.set()
    try:
        st.session_state['download_cancelled'] = True
        st.session_state['cancel_requested'] = True
    except Exception:
        pass


def cancel_sync() -> None:
    """Instant on_click callback for sync cancellation.

    Sets the threading.Event (thread-safe) and mirrors to session_state
    for UI reactivity.
    """
    _sync_cancel_event.set()
    try:
        st.session_state['sync_cancelled'] = True
        st.session_state['sync_cancel_requested'] = True
    except Exception:
        pass


# ═══════════════════════════════════════════════
# Cancellation Checkers (polled during execution)
# ═══════════════════════════════════════════════

def is_download_cancelled() -> bool:
    """Check if a download cancellation has been requested.

    Checks the threading.Event first (always safe from any thread), then
    falls back to session_state for cases where only the UI set the flag.
    """
    if _download_cancel_event.is_set():
        return True
    try:
        return st.session_state.get('download_cancelled', False)
    except Exception:
        return False


def is_sync_cancelled() -> bool:
    """Check if a sync cancellation has been requested.

    Checks the threading.Event first (always safe from any thread), then
    falls back to session_state for cases where only the UI set the flag.
    """
    if _sync_cancel_event.is_set():
        return True
    try:
        return (
            st.session_state.get('sync_cancel_requested', False)
            or st.session_state.get('sync_cancelled', False)
        )
    except Exception:
        return False


# ═══════════════════════════════════════════════
# Reset Helpers (called from cleanup functions)
# ═══════════════════════════════════════════════

def reset_download_cancel() -> None:
    """Clear the download cancel event and reset session_state flags."""
    _download_cancel_event.clear()
    try:
        st.session_state['download_cancelled'] = False
        st.session_state['cancel_requested'] = False
    except Exception:
        pass


def reset_sync_cancel() -> None:
    """Clear the sync cancel event and reset session_state flags."""
    _sync_cancel_event.clear()
    try:
        st.session_state['sync_cancelled'] = False
        st.session_state['sync_cancel_requested'] = False
    except Exception:
        pass
