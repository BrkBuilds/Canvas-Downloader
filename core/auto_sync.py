"""core.auto_sync - headless daily Quick-Sync wrapper for the Today dashboard.

This deliberately REUSES the existing, proven Quick Sync pipeline (set
``sync_pairs`` + the ``sync_quick_mode`` handshake + ``step = 4``) rather than
reimplementing the sync engine. The Today dashboard hosts the run and renders
only a slim progress bar - ``sync.execution.run_sync`` honours the
``today_sync_active`` session flag and hides its metrics/log/active-file chrome.

Flow:
  launch hook / "Sync now"  ->  start_today_sync(pairs)
      -> sets quick-sync state, marks today's logical date, st.rerun()
      -> app.py step==4 -> render_sync_step4 runs analysis + run_sync (slim UI)
      -> on completion render_sync_step4 routes back to the Today dashboard,
         which shows "today's files per course" from sync history.
"""

from __future__ import annotations

import streamlit as st


def resolve_today_pairs() -> list[dict]:
    """Return the runnable course/folder pairs the user curated for daily sync.

    The curated set is stored self-contained in ``today_dashboard.json`` (imported
    from the Saved Groups & Pairs hub), so it survives edits/deletes in the hub.
    Pairs whose local folder no longer exists are dropped here so a missing folder
    can never break the run - the dashboard flags them separately.
    """
    from pathlib import Path
    from core.today_store import load_today_config

    cfg = load_today_config()
    return [
        p for p in cfg.get("pairs", [])
        if p.get("local_folder") and Path(p["local_folder"]).exists()
    ]


def should_auto_sync() -> bool:
    """True when the daily auto-sync should fire on this launch.

    Conditions: auto-sync enabled, not already run for today's logical date, and
    at least one curated pair that still resolves to a saved sync pair.
    """
    from core.today_store import load_today_config, logical_today

    cfg = load_today_config()
    if not cfg.get("auto_sync_enabled"):
        return False
    if cfg.get("last_auto_sync_date") == logical_today():
        return False
    return bool(resolve_today_pairs())


def build_today_sync_notice() -> dict:
    """Snapshot the just-finished Today run's outcome for the dismissible
    success notice on the Today page (and the daily-sync native notification).

    MUST be called from the today completion handler BEFORE
    ``cleanup_sync_state()`` - the source keys (``synced_groups``,
    ``synced_count``, ``sync_errors``) are transient and popped by cleanup.

    ``synced_groups`` already includes Panopto recordings when the run had a
    Panopto pass (the pass merges its produced files into the groups and bumps
    ``synced_count`` per artifact), so no separate recording tally is needed -
    and adding one would double-count.
    """
    from datetime import datetime
    from shared.helpers import friendly_course_name

    courses = []
    files_in_groups = 0
    for grp in st.session_state.get("synced_groups") or []:
        files = grp.get("files") or []
        if not files:
            continue
        courses.append({
            "name": friendly_course_name(grp.get("course_name", "") or "Course"),
            "count": len(files),
        })
        files_in_groups += len(files)

    total = st.session_state.get("synced_count")
    if not isinstance(total, int) or total < 0:
        total = 0
    # Group-building is best-effort (falls back to [] on failure) while
    # synced_count is the engine's own tally - trust whichever saw more.
    total = max(total, files_in_groups)

    return {
        "is_auto": bool(st.session_state.get("today_sync_is_auto")),
        "completed_at": datetime.now().strftime("%H:%M"),
        "total_files": total,
        "courses": courses,
        "errors": len(st.session_state.get("sync_errors") or []),
    }


def start_today_sync(pairs: list[dict] | None = None, is_auto: bool = False) -> None:
    """Kick off a headless Quick Sync over *pairs* and route to the slim Today
    progress view. Calls ``st.rerun()`` so it never falls through.

    ``is_auto`` distinguishes the hands-off daily auto-sync (launch hook) from a
    user-initiated "Quick Sync now" click, purely so the in-page progress card can
    title itself "Running daily sync" vs "Running Quick Sync".

    Marks today's logical date IMMEDIATELY (before the run) so a crash or a
    window-close mid-sync can never re-trigger the daily run again the same day.
    """
    from core.today_store import mark_auto_synced, logical_today

    if pairs is None:
        pairs = resolve_today_pairs()
    if not pairs:
        return

    mark_auto_synced(logical_today())

    # A fresh run makes the previous run's success notice stale - drop it now so
    # the dashboard never shows an outdated "N new files" card next to (or after)
    # the live progress card.
    st.session_state.pop("today_sync_notice", None)

    st.session_state["sync_pairs"] = list(pairs)
    # Prevent load_persistent_pairs() from overwriting our curated subset.
    st.session_state["sync_pairs_loaded"] = True
    st.session_state["sync_mode"] = True
    st.session_state["today_sync_active"] = True
    st.session_state["today_sync_is_auto"] = bool(is_auto)
    # Keep the Today nav highlighted during the run; step==4 dispatch in app.py is
    # mode-independent, so render_sync_step4 still drives the sync engine.
    st.session_state["current_mode"] = "today"

    # Mirror the Quick Sync handshake (sync_ui.py 'btn_quick_sync'): nuke stale
    # cancel flags, jump to step 4 analysis in quick mode.
    st.session_state["cancel_requested"] = False
    st.session_state["sync_cancelled"] = False
    st.session_state["sync_cancel_requested"] = False
    st.session_state["download_cancelled"] = False
    st.session_state["step"] = 4
    st.session_state["download_status"] = "analyzing"
    st.session_state["sync_quick_mode"] = True
    st.session_state["qs_cancel_route"] = True
    st.session_state["analysis_pass"] = 1
    st.rerun()
