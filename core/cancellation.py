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

import logging
import threading
import streamlit as st

logger = logging.getLogger(__name__)

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
    logger.info("Download cancellation requested (event set).")
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
# In-Progress Detection (used to lock navigation)
# ═══════════════════════════════════════════════

# ``download_status`` values that represent an ACTIVE, uninterruptible run. The
# field is shared between the download and sync flows; the two value-sets are
# disjoint so a single membership test is unambiguous.
#   download: scanning → running → (isolated_retry) → (panopto) → done/cancelled
#   sync:     analyzing → (pre_sync) → syncing → (sync_panopto) → sync_complete/…
# Interstitial decision screens are deliberately EXCLUDED so the user is never
# trapped on them: 'analyzed' (the sync review screen) and 'done'/'cancelled'/
# 'sync_complete'/'sync_cancelled' (terminal screens).
_IN_PROGRESS_DOWNLOAD_STATUSES = {'scanning', 'running', 'isolated_retry', 'panopto'}
_IN_PROGRESS_SYNC_STATUSES = {'analyzing', 'pre_sync', 'syncing', 'sync_panopto'}
IN_PROGRESS_STATUSES = _IN_PROGRESS_DOWNLOAD_STATUSES | _IN_PROGRESS_SYNC_STATUSES


def is_operation_in_progress() -> bool:
    """True while a download or sync is actively running (execution or post-processing).

    The app is single-operation: during a run the script thread is blocked in the
    download loop or the sync heartbeat loop, and a background worker may be
    writing files to disk. Switching modes, opening Settings, or logging out
    mid-run would orphan that worker and silently discard all progress (see the
    ``cleanup_download_state``/``cleanup_sync_state`` calls in the sidebar nav).
    This predicate lets the sidebar lock every navigation control for the duration
    of the run, leaving the operation's own Cancel button as the single, deliberate
    way out.

    Terminal and review screens are excluded (see ``IN_PROGRESS_STATUSES``) so the
    user is never trapped after a run finishes. A browser refresh also clears the
    lock: ``download_status`` is transient and is never restored from query params.
    """
    try:
        if st.session_state.get('download_status') in IN_PROGRESS_STATUSES:
            return True
        return bool(st.session_state.get('is_post_processing'))
    except Exception:
        return False


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
    # Diagnostic: clearing a SET event means a pending user cancel was just
    # discarded. That's legitimate at a fresh download start / cleanup, but if it
    # shows up DURING an active phase (e.g. 'panopto') it means a stale-reset
    # guard is swallowing the cancel (the _active_dl_statuses class of bug).
    if _download_cancel_event.is_set():
        logger.info("Download cancel event cleared (was set).")
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


# ═══════════════════════════════════════════════
# One blocking run per session (owner report 2026-09-12)
# ═══════════════════════════════════════════════
#
# MEASURED 2026-09-26: when the browser's websocket drops mid-download and the
# page reconnects on its own (the ordinary case - a backgrounded tab, a wifi
# blip), Streamlit keeps the SAME session and starts a NEW script run while the
# old one is still blocked inside the download. Both runs see
# `download_status == 'running'`, so the new one downloads the same course
# again, concurrently. Driven in a harness by closing the page's WebSocket:
# `download_course_async` started twice, 1.6s apart, same session id, both on a
# `ScriptRunner.scriptThread`. That is the reported "Download Start" three
# times from one click, and "100% with 7 minutes left" is two runs painting
# one screen.
#
# The owner-report entry guessed at a NEW session that had lost its state.
# That was measured too and is not it: a fresh tab on the same URL has no run
# state and starts nothing.
#
# THE CLAIM CANNOT LIVE IN `session_state`, and that was measured, not assumed:
# in the run Streamlit has stopped, even READING `st.session_state` raises
# StopException (the proxy checks the run's stop flag). So the run being
# replaced could never write "I finished". The claim lives here instead, in the
# process, keyed by the session id both runs share (measured: identical). It
# names the THREAD holding the phase, so a run that died without releasing it
# blocks nothing - a dead thread's claim is ignored.
#
# Not re-import proof, deliberately: a file-watcher reload (source runs only;
# the shipped app has no watcher) empties these dicts, which only disables the
# guard for a run in flight - it cannot strand anything, because nothing here
# owns an OS resource.

_runs_lock = threading.Lock()
_runs: dict = {}      # session id -> {'thread', 'phase', 'unit'}
_completed: dict = {} # session id -> (phase, unit) of the last NORMAL exit


def _session_id() -> "str | None":
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return getattr(get_script_run_ctx(), 'session_id', None)
    except Exception:                                              # noqa: BLE001
        return None


def other_blocking_run(session_id: "str | None" = None) -> "threading.Thread | None":
    """The live thread of ANOTHER run of this session inside a blocking phase."""
    sid = session_id or _session_id()
    if sid is None:
        return None
    with _runs_lock:
        rec = _runs.get(sid)
    thread = rec.get('thread') if rec else None
    if (thread is None or thread is threading.current_thread()
            or not thread.is_alive()):
        return None
    return thread


class blocking_run:
    """Claim a blocking phase (scan, download, retry, Panopto, sync) for this run.

    Use as ``with blocking_run('download', unit=idx):`` around the call that
    blocks. Released on the way out only if this thread still holds it.

    **A NORMAL exit records (phase, unit) as completed, and that is load-bearing.**
    Streamlit stops the replaced run at its FIRST Streamlit call after the
    blocking call returns - measured: the course finished, the index was never
    advanced, and the waiting run downloaded it again. This record is a plain
    dict in the process, so it survives the stop, and `blocking_run_completed`
    lets the waiting run carry on from it instead of repeating the work.
    """

    def __init__(self, phase: str, unit=None, *, session_id: "str | None" = None):
        self.phase = phase
        self.unit = unit
        self.sid = session_id

    def __enter__(self):
        self.sid = self.sid or _session_id()
        if self.sid is not None:
            with _runs_lock:
                _completed.pop(self.sid, None)
                _runs[self.sid] = {'thread': threading.current_thread(),
                                   'phase': self.phase, 'unit': self.unit}
        return self

    def __exit__(self, exc_type, *_exc):
        if self.sid is None:
            return False
        with _runs_lock:
            rec = _runs.get(self.sid)
            if rec and rec.get('thread') is threading.current_thread():
                if exc_type is None:
                    _completed[self.sid] = (self.phase, self.unit)
                _runs.pop(self.sid, None)
        return False


def blocking_run_completed(phase: str, unit=None, *,
                           session_id: "str | None" = None) -> bool:
    """Did the run this one replaced FINISH *phase* for *unit*?"""
    sid = session_id or _session_id()
    with _runs_lock:
        return sid is not None and _completed.get(sid) == (phase, unit)


def wait_for_other_blocking_run(heartbeat, *, poll: float = 0.4,
                                session_id: "str | None" = None) -> bool:
    """If another run of this session holds a blocking phase, wait for it.

    Answers True when it waited and False when nothing else was running, in
    which case the caller does the work itself. After a True, ask
    `blocking_run_completed` whether that run finished the unit.

    *heartbeat* must be a Streamlit call (an empty ``markdown``): Streamlit only
    delivers a pending click - Cancel included - at a Streamlit call, so a
    silent sleep here would make the screen deaf until the other run ended.
    Cancel works while waiting because the cancel signal is the process-global
    Event above, which the other run's engine polls.
    """
    sid = session_id or _session_id()
    thread = other_blocking_run(sid)
    if thread is None:
        return False
    with _runs_lock:
        phase = (_runs.get(sid) or {}).get('phase', '?')
    logger.info("A reconnected run found the %s phase still running in another "
                "run of this session; waiting for it instead of starting again.",
                phase)
    while thread.is_alive():
        heartbeat()
        thread.join(poll)
    return True
