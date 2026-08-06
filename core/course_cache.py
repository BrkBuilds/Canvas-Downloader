"""The course list: served from cache ALWAYS, refreshed off the render path.

Why this exists
---------------
Fetching the course list is a page-render blocker, and after the navigation
overlay was fixed it was the single largest one left. Two separate problems,
measured against a real Canvas instance on 2026-07-31:

1. **It was being paid on ordinary navigations.** ``cleanup_download_state()``
   and ``cleanup_sync_state()`` each called a GLOBAL ``st.cache_resource.clear()``,
   and the sidebar nav buttons call those on every mode switch - so every
   navigation threw the course list away. That is why "-> Today" was the only
   fast navigation in the app (it is the one screen that needs no course list)
   while the rest cost 1.2-1.9 s.

2. **The fetch itself cost three sequential round-trips** - 950 ms - because
   ``canvasapi`` insists on ``GET /users/self`` before it will hand over
   ``get_favorite_courses()``. ``CanvasManager.get_courses_with_favorites()``
   now asks Canvas for ``include[]=favorites`` and gets the same answer in one
   request (432 ms, verified identical: 15 of 33 courses, same ids).

Why not ``st.cache_resource``
-----------------------------
It cannot express what is wanted here. Its TTL **expires** rather than
refreshes, so one navigation every ten minutes still pays the full round-trip;
and it cannot be populated from a background thread, which has no
``ScriptRunContext``. So the cache is ours:

===============================  =========================================
state                            behaviour
===============================  =========================================
fresh (< ``COURSES_FRESH_S``)    serve it
stale (< ``COURSES_MAX_AGE_S``)  serve it AND refresh in the background
absent / ancient                 block - there is nothing worth showing
===============================  =========================================

A render therefore never waits on Canvas once anything has been loaded. A
course that appears mid-session shows up within ``COURSES_FRESH_S`` on its own,
or immediately via the course list's Refresh button and on re-login - both of
which call :func:`clear`.

Nothing in here may touch ``st.*``: :func:`_load_courses` runs on a plain
daemon thread. ``CanvasManager`` construction and ``get_courses_with_favorites``
were both checked to be Streamlit-free.
"""

from __future__ import annotations

import logging
import threading
import time

from core.canvas_logic import CanvasManager

logger = logging.getLogger(__name__)

COURSES_FRESH_S = 600          # serve without touching the network
COURSES_MAX_AGE_S = 6 * 3600   # beyond this, a stale list is not worth showing

_cache: dict = {}              # key -> {'courses': [...], 'at': float}
_inflight: dict = {}           # key -> threading.Event
_lock = threading.Lock()

# Seam for tests: the one function that talks to the network.
_loader = None


def _load_courses(token, url):
    """The actual Canvas call. Must stay free of ``st.*`` - it runs on a thread."""
    if _loader is not None:
        return _loader(token, url)
    mgr = CanvasManager(token, url)
    courses = mgr.get_courses_with_favorites()
    courses.sort(key=lambda c: (c.name or "").lower())
    return courses


def _refresh(key, token, url):
    """Reload into the cache. Never raises - a failed refresh keeps the old list."""
    try:
        courses = _load_courses(token, url)
        with _lock:
            _cache[key] = {'courses': courses, 'at': time.time()}
    except Exception:
        logger.warning("Course refresh failed; keeping the cached list",
                       exc_info=True)
        with _lock:
            entry = _cache.get(key)
            if entry:
                # Do not retry on every rerun after a failure - let the existing
                # list go stale again at its own pace.
                entry['at'] = time.time() - COURSES_FRESH_S + 60
    finally:
        with _lock:
            event = _inflight.pop(key, None)
        if event:
            event.set()


def fetch_courses(token, url):
    """All enrolled courses, each annotated with ``.is_favorite`` (bool).

    Callers that previously filtered by fav_only should do::

        [c for c in courses if c.is_favorite]   # favorites
        courses                                  # all
    """
    key = (token, url)
    with _lock:
        entry = _cache.get(key)
        age = (time.time() - entry['at']) if entry else None
        # Claim the refresh under the same lock that read the age, so two
        # reruns landing together cannot both start one.
        mine = (entry is not None and age >= COURSES_FRESH_S
                and key not in _inflight)
        if mine:
            _inflight[key] = threading.Event()

    if entry is not None and age < COURSES_MAX_AGE_S:
        if mine:
            try:
                threading.Thread(target=_refresh, args=(key, token, url),
                                 daemon=True, name="course-refresh").start()
            except RuntimeError:
                # Thread creation can fail (resource exhaustion). The claim in
                # _inflight was made on the promise that _refresh would run and
                # pop it; if it never starts, every later call with an ancient
                # entry waits the full 90 s on an Event nothing will ever set.
                # Release the claim and just serve what we have.
                logger.warning("Could not start course refresh thread; serving "
                               "the cached list", exc_info=True)
                with _lock:
                    ev = _inflight.pop(key, None)
                if ev:
                    ev.set()
        return entry['courses']

    # Nothing usable on hand - this one has to block.
    with _lock:
        waiting = _inflight.get(key)
        if waiting is None:
            waiting = _inflight[key] = threading.Event()
            mine = True
    if mine:
        _refresh(key, token, url)
    else:
        # Another rerun is already fetching the same thing; wait for it rather
        # than opening a second connection to ask the same question.
        waiting.wait(timeout=90)

    with _lock:
        entry = _cache.get(key)
    if entry:
        return entry['courses']
    raise RuntimeError("Could not load your courses from Canvas. Check your "
                       "connection and your access token, then try again.")


def clear():
    """Drop everything - used by logout and by the course list's Refresh button.

    Attached to ``fetch_courses`` as ``.clear`` below so the existing call sites
    keep working unchanged; they were written against ``st.cache_resource``.
    """
    with _lock:
        _cache.clear()


fetch_courses.clear = clear
