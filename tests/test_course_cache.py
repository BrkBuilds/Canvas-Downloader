"""The course list must never block a page render twice.

The defect
----------
Measured 2026-07-31, after the navigation overlay was fixed and stopped hiding
it. Fetching the course list was the largest remaining page-render blocker, and
it was being paid on *ordinary navigations*:

* ``cleanup_download_state()`` / ``cleanup_sync_state()`` each called a GLOBAL
  ``st.cache_resource.clear()``, and the sidebar nav buttons call those on every
  mode switch. ``fetch_courses`` was the app's only ``cache_resource``, so every
  navigation threw the course list away. That is the whole reason "-> Today" was
  the only fast navigation in the app: it is the one screen that needs no course
  list. The rest cost 1.2-1.9 s.
* The fetch itself was three sequential Canvas round-trips (950 ms measured),
  because ``canvasapi``'s ``get_current_user()`` eagerly does ``GET /users/self``
  before it will hand over ``get_favorite_courses()``. ``include[]=favorites``
  answers the same question in one request (432 ms measured, and the courses it
  flagged matched the favorites endpoint exactly - 15 of 33, same ids).
* ``st.cache_resource``'s TTL **expires** rather than refreshes, so even without
  the blanket clear one navigation every ten minutes paid the full cost; and it
  cannot be filled from a background thread, which has no ScriptRunContext.

Everything here runs against the ``_loader`` seam - no network, no Streamlit.
"""

from __future__ import annotations

import pathlib
import re
import threading
import time

import pytest

from core import course_cache

REPO = pathlib.Path(__file__).resolve().parents[1]


class FakeCourse:
    def __init__(self, cid, name, fav=False):
        self.id = cid
        self.name = name
        self.is_favorite = fav


@pytest.fixture(autouse=True)
def clean_cache():
    course_cache.clear()
    with course_cache._lock:
        course_cache._inflight.clear()
    course_cache._loader = None
    yield
    course_cache.clear()
    with course_cache._lock:
        course_cache._inflight.clear()
    course_cache._loader = None


def _wait_idle(timeout=5.0):
    """Block until no refresh is in flight.

    Synchronising on the CALL COUNT is a race and it hid two real mutations:
    the fake loader records its call *before* it raises, so the count reaches
    its target while ``_refresh``'s failure handling - the part under test -
    has not run yet.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        with course_cache._lock:
            if not course_cache._inflight:
                return True
        time.sleep(0.01)
    return False


def _install(delay=0.0, counter=None, boom=False):
    """Install a fake loader; returns the list of call timestamps."""
    calls = counter if counter is not None else []

    def loader(token, url):
        calls.append(time.time())
        if delay:
            time.sleep(delay)
        if boom:
            raise RuntimeError("canvas is down")
        return [FakeCourse(1, f"Course {len(calls)}")]

    course_cache._loader = loader
    return calls


# --------------------------------------------------------------------------
# The cache itself
# --------------------------------------------------------------------------

def test_cold_fetch_blocks_and_populates():
    calls = _install()
    got = course_cache.fetch_courses("t", "u")
    assert len(calls) == 1 and len(got) == 1


def test_a_fresh_cache_never_touches_the_network():
    calls = _install()
    first = course_cache.fetch_courses("t", "u")
    for _ in range(20):
        assert course_cache.fetch_courses("t", "u") is first
    assert len(calls) == 1, (
        "A warm course list must be served without a Canvas round-trip. This is "
        "the whole point: the fetch is ~950 ms and it sat on the render path."
    )


def test_a_stale_cache_is_served_instantly_and_refreshed_behind_it():
    calls = _install()
    first = course_cache.fetch_courses("t", "u")
    with course_cache._lock:
        course_cache._cache[("t", "u")]["at"] = time.time() - course_cache.COURSES_FRESH_S - 5

    t0 = time.perf_counter()
    served = course_cache.fetch_courses("t", "u")
    elapsed = (time.perf_counter() - t0) * 1000

    assert served is first, "a stale list must still be served, not awaited"
    assert elapsed < 50, (
        f"the stale path took {elapsed:.0f} ms - it must not block. Expiring "
        f"instead of refreshing is exactly what st.cache_resource's TTL does, "
        f"and why it could not be used here."
    )
    assert _wait_idle(), "the background refresh never finished"
    assert len(calls) == 2, "the background refresh never ran"
    assert course_cache.fetch_courses("t", "u") is not first, (
        "the refreshed list was never swapped in")


def test_an_ancient_cache_blocks_rather_than_showing_it():
    calls = _install()
    course_cache.fetch_courses("t", "u")
    with course_cache._lock:
        course_cache._cache[("t", "u")]["at"] = time.time() - course_cache.COURSES_MAX_AGE_S - 5
    course_cache.fetch_courses("t", "u")
    assert len(calls) == 2, (
        "Past COURSES_MAX_AGE_S the list is too old to be worth showing, so the "
        "fetch must block instead of serving it.")


def test_concurrent_cold_fetches_are_deduped():
    """Two reruns landing together must not open two connections."""
    calls = _install(delay=0.25)
    out = []
    threads = [threading.Thread(target=lambda: out.append(
        course_cache.fetch_courses("t", "u"))) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert len(calls) == 1, (
        f"{len(calls)} concurrent fetches of the same list. The in-flight "
        f"registry must make the others wait on the first.")
    assert all(o is out[0] for o in out)


def test_a_failed_refresh_keeps_the_old_list():
    calls = _install()
    first = course_cache.fetch_courses("t", "u")
    _install(counter=calls, boom=True)
    with course_cache._lock:
        course_cache._cache[("t", "u")]["at"] = time.time() - course_cache.COURSES_FRESH_S - 5
    assert course_cache.fetch_courses("t", "u") is first
    assert _wait_idle(), "the background refresh never finished"
    assert len(calls) == 2, "the background refresh never ran"
    assert course_cache.fetch_courses("t", "u") is first, (
        "A failed background refresh must leave the working list in place - "
        "losing it would turn a transient Canvas blip into an empty course "
        "list on screen.")


def test_a_failed_refresh_does_not_retry_on_every_rerun():
    calls = _install()
    course_cache.fetch_courses("t", "u")
    _install(counter=calls, boom=True)
    with course_cache._lock:
        course_cache._cache[("t", "u")]["at"] = time.time() - course_cache.COURSES_FRESH_S - 5
    course_cache.fetch_courses("t", "u")
    assert _wait_idle(), "the background refresh never finished"
    before = len(calls)
    for _ in range(10):
        course_cache.fetch_courses("t", "u")
    _wait_idle()
    assert len(calls) == before, (
        "A failing refresh re-armed itself immediately, so every rerun starts "
        "another doomed thread. The retry must be pushed out.")


def test_cold_failure_propagates():
    _install(boom=True)
    with pytest.raises(Exception):
        course_cache.fetch_courses("t", "u")


def test_clear_is_attached_to_the_function():
    """Two call sites use ``fetch_courses_fn.clear()`` - logout and Refresh."""
    assert callable(getattr(course_cache.fetch_courses, "clear", None)), (
        "fetch_courses.clear is gone. ui/auth.py (logout) and "
        "ui/course_selector.py (the Refresh button) both call it; they were "
        "written against st.cache_resource and must keep working.")
    calls = _install()
    course_cache.fetch_courses("t", "u")
    course_cache.fetch_courses.clear()
    course_cache.fetch_courses("t", "u")
    assert len(calls) == 2


# --------------------------------------------------------------------------
# The call sites that made it a render blocker
# --------------------------------------------------------------------------

def test_cleanup_state_no_longer_nukes_the_course_cache():
    """The sidebar nav buttons call these on every mode switch."""
    src = (REPO / "core" / "state_registry.py").read_text(encoding="utf-8")
    body = re.sub(r"#[^\n]*", "", src)          # a comment may name it
    assert "st.cache_resource.clear()" not in body, (
        "cleanup_download_state()/cleanup_sync_state() clear the global "
        "cache_resource store again. fetch_courses is no longer in it, so this "
        "would be dead rather than harmful - but it is the exact line that made "
        "every sidebar navigation pay a ~950 ms Canvas round-trip, and it should "
        "not come back."
    )


def test_the_two_legitimate_clears_are_still_there():
    """Removing the blanket clear must not have removed the real ones."""
    auth = (REPO / "ui" / "auth.py").read_text(encoding="utf-8")
    sel = (REPO / "ui" / "course_selector.py").read_text(encoding="utf-8")
    assert "fetch_courses_fn.clear()" in auth, (
        "Logout no longer clears the course list - the next user would see the "
        "previous user's courses.")
    assert "fetch_courses_fn.clear()" in sel, (
        "The course list's Refresh button no longer clears the cache, so it "
        "cannot do anything. It is the user's only way to force fresh data "
        "before COURSES_FRESH_S elapses.")


def test_app_uses_the_cache_module_not_a_streamlit_cache():
    app = (REPO / "app.py").read_text(encoding="utf-8")
    assert "from core.course_cache import fetch_courses" in app
    assert not re.search(r"@st\.cache_resource[^\n]*\ndef fetch_courses", app), (
        "fetch_courses is back on st.cache_resource. Its TTL expires rather "
        "than refreshes, and it cannot be populated from a background thread - "
        "both of which are the point of core/course_cache.py.")


# --------------------------------------------------------------------------
# One request, not three
# --------------------------------------------------------------------------

def test_favorites_come_from_the_courses_call_itself():
    src = (REPO / "core" / "canvas_logic.py").read_text(encoding="utf-8")
    assert "def get_courses_with_favorites" in src
    fn = src[src.index("def get_courses_with_favorites"):]
    fn = fn[: fn.index("def get_course_files_metadata")]
    assert "include=['favorites']" in fn, (
        "The one-request path is gone. Fetching the favorites separately costs "
        "TWO extra round-trips, because canvasapi's get_current_user() does an "
        "eager GET /users/self first - measured at 950 ms against 432 ms.")
    assert "all(hasattr(c, 'is_favorite') for c in courses)" in fn, (
        "The result must be VERIFIED, not assumed. Canvas silently IGNORES an "
        "include[] value it does not know, so an instance without support "
        "returns courses with no is_favorite attribute at all - and every "
        "course would then look like a non-favorite.")
    assert "favorites_only=True" in fn, (
        "The three-call fallback is gone. It is what keeps this working on a "
        "Canvas instance that does not honour include[]=favorites.")
