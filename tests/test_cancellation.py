"""Tests for ``core.cancellation`` - the Cancel button's whole contract.

Why this file exists
--------------------
Cancellation is the only way out of a running download or sync, and every one
of its failure modes is SILENT:

* a cancel that does not reach the worker just looks like a slow app;
* a *stale* cancel left set from a previous run aborts the next run on its
  first poll, which looks like the app refusing to start;
* a navigation lock that is too tight traps the user on a terminal screen, and
  one that is too loose orphans a worker mid-write.

The module is ~160 lines of pure state machine and had no test at all.

The drift class this file exists to kill
----------------------------------------
``app.py`` keeps its own hand-copied ``_active_dl_statuses`` set and only calls
``reset_download_cancel()`` when the current status is NOT in it. Miss a phase
there and the reset fires *during* that phase, wiping the flag the on_click
just set - so Cancel is swallowed and the phase restarts its discovery instead
of stopping. That is precisely what happened when the Panopto phase was added
(``'panopto'`` was absent from the set), and it is invisible in review because
both files look correct on their own.

``'panopto'`` is also the reason a naive grep does not protect you: it is never
assigned as a literal anywhere. It arrives through ``_next_phase_after_courses()``,
so the guard below walks that function's returns as well as every literal
assignment in the tree.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import cancellation as C

REPO = Path(__file__).resolve().parents[1]

# Directories holding the real application source. `dist/` and `build/` contain
# frozen COPIES of an older app - scanning them would assert against code that
# is not shipping and cannot be fixed here.
SOURCE_ROOTS = ("app.py", "sync_ui.py", "start.py", "core", "ui", "sync",
                "engine", "converters", "shared", "panopto")


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_cancel_state(monkeypatch):
    """A fresh session_state AND fresh events for every test.

    The two ``threading.Event`` objects are MODULE-level globals, so without
    this a test that cancels leaks into every test after it - and the leak
    reads as "cancellation works", which is the wrong direction to be wrong in.
    """
    stub = SimpleNamespace(session_state={})
    monkeypatch.setattr(C, "st", stub)
    C._download_cancel_event.clear()
    C._sync_cancel_event.clear()
    yield stub.session_state
    C._download_cancel_event.clear()
    C._sync_cancel_event.clear()


@pytest.fixture()
def hostile_session(monkeypatch):
    """A session_state that raises on EVERY access.

    Models the background-thread case the module's try/except blocks exist for:
    a worker thread has no ScriptRunContext, so touching session_state can
    raise. The cancel signal must still get through.
    """
    class Hostile:
        def __getitem__(self, k):
            raise RuntimeError("no ScriptRunContext")

        def __setitem__(self, k, v):
            raise RuntimeError("no ScriptRunContext")

        def get(self, *a, **k):
            raise RuntimeError("no ScriptRunContext")

    monkeypatch.setattr(C, "st", SimpleNamespace(session_state=Hostile()))


# ── the basic signal ─────────────────────────────────────────────────────────

def test_nothing_is_cancelled_at_rest(isolated_cancel_state):
    assert C.is_download_cancelled() is False
    assert C.is_sync_cancelled() is False


def test_cancel_download_sets_event_and_both_flags(isolated_cancel_state):
    C.cancel_download()
    assert C._download_cancel_event.is_set()
    assert isolated_cancel_state['download_cancelled'] is True
    assert isolated_cancel_state['cancel_requested'] is True
    assert C.is_download_cancelled() is True


def test_cancel_sync_sets_event_and_both_flags(isolated_cancel_state):
    C.cancel_sync()
    assert C._sync_cancel_event.is_set()
    assert isolated_cancel_state['sync_cancelled'] is True
    assert isolated_cancel_state['sync_cancel_requested'] is True
    assert C.is_sync_cancelled() is True


def test_the_event_alone_is_enough(isolated_cancel_state):
    """The worker polls from a thread with no session_state of its own; the
    Event is the authoritative signal and must not need the mirror."""
    C._download_cancel_event.set()
    C._sync_cancel_event.set()
    assert isolated_cancel_state == {}, "precondition: no mirrored flags"
    assert C.is_download_cancelled() is True
    assert C.is_sync_cancelled() is True


def test_the_session_flag_alone_is_enough(isolated_cancel_state):
    """The reverse path: UI set the flag directly without going through the
    callback (cleanup helpers and older call sites both do this)."""
    isolated_cancel_state['download_cancelled'] = True
    assert not C._download_cancel_event.is_set()
    assert C.is_download_cancelled() is True


@pytest.mark.parametrize("key", ["sync_cancelled", "sync_cancel_requested"])
def test_either_sync_flag_counts(isolated_cancel_state, key):
    """``is_sync_cancelled`` reads TWO keys. Dropping either one silently
    halves the number of places that can stop a sync."""
    isolated_cancel_state[key] = True
    assert C.is_sync_cancelled() is True


# ── the two channels are independent ─────────────────────────────────────────

def test_cancelling_a_download_does_not_cancel_a_sync(isolated_cancel_state):
    C.cancel_download()
    assert C.is_sync_cancelled() is False


def test_cancelling_a_sync_does_not_cancel_a_download(isolated_cancel_state):
    C.cancel_sync()
    assert C.is_download_cancelled() is False


def test_reset_download_leaves_sync_cancelled(isolated_cancel_state):
    """``cleanup_download_state`` calls this. A sync cancel raised in the same
    session must survive it - state_registry says so explicitly."""
    C.cancel_sync()
    C.reset_download_cancel()
    assert C.is_sync_cancelled() is True


def test_reset_sync_leaves_download_cancelled(isolated_cancel_state):
    C.cancel_download()
    C.reset_sync_cancel()
    assert C.is_download_cancelled() is True


# ── reset clears BOTH halves ─────────────────────────────────────────────────

def test_reset_download_clears_event_and_flags(isolated_cancel_state):
    """Clearing only the Event would leave the mirrored flag set, and
    ``is_download_cancelled`` falls back to it - so the next run would abort on
    its first poll."""
    C.cancel_download()
    C.reset_download_cancel()
    assert not C._download_cancel_event.is_set()
    assert isolated_cancel_state['download_cancelled'] is False
    assert isolated_cancel_state['cancel_requested'] is False
    assert C.is_download_cancelled() is False


def test_reset_sync_clears_event_and_flags(isolated_cancel_state):
    C.cancel_sync()
    C.reset_sync_cancel()
    assert not C._sync_cancel_event.is_set()
    assert isolated_cancel_state['sync_cancelled'] is False
    assert isolated_cancel_state['sync_cancel_requested'] is False
    assert C.is_sync_cancelled() is False


def test_reset_is_idempotent(isolated_cancel_state):
    C.reset_download_cancel()
    C.reset_download_cancel()
    C.reset_sync_cancel()
    C.reset_sync_cancel()
    assert C.is_download_cancelled() is False
    assert C.is_sync_cancelled() is False


# ── background-thread robustness ─────────────────────────────────────────────

def test_cancel_still_signals_when_session_state_raises(hostile_session):
    """The whole point of the Event: an on_click that runs where session_state
    is unavailable must still stop the worker, and must not raise."""
    C.cancel_download()
    C.cancel_sync()
    assert C._download_cancel_event.is_set()
    assert C._sync_cancel_event.is_set()


def test_checkers_do_not_raise_when_session_state_raises(hostile_session):
    """A checker that raises kills the download loop it was polling from -
    turning "is the user cancelling?" into an actual crash."""
    assert C.is_download_cancelled() is False
    assert C.is_sync_cancelled() is False
    assert C.is_operation_in_progress() is False


def test_the_event_still_wins_over_a_hostile_session(hostile_session):
    """Event is checked FIRST, before session_state is touched at all - so a
    worker thread gets the signal even where the mirror is unreadable."""
    C._download_cancel_event.set()
    C._sync_cancel_event.set()
    assert C.is_download_cancelled() is True
    assert C.is_sync_cancelled() is True


def test_reset_does_not_raise_when_session_state_raises(hostile_session):
    C._download_cancel_event.set()
    C.reset_download_cancel()
    C.reset_sync_cancel()
    assert not C._download_cancel_event.is_set()


# ── the navigation lock ──────────────────────────────────────────────────────

@pytest.mark.parametrize("status", sorted(C.IN_PROGRESS_STATUSES))
def test_every_in_progress_status_locks_navigation(isolated_cancel_state, status):
    """Too loose and the sidebar lets the user change mode mid-run, orphaning
    the worker and discarding everything it has written."""
    isolated_cancel_state['download_status'] = status
    assert C.is_operation_in_progress() is True, \
        f"{status!r} is an active phase but does not lock navigation"


# Terminal + interstitial screens. Locking any of these traps the user with no
# Cancel button to press, because the run they would be cancelling is over.
@pytest.mark.parametrize("status", [
    'done', 'cancelled', 'sync_complete', 'sync_cancelled', 'sync_failed',
    'analyzed', 'select', '',
])
def test_terminal_and_review_screens_never_lock(isolated_cancel_state, status):
    isolated_cancel_state['download_status'] = status
    assert C.is_operation_in_progress() is False, \
        f"{status!r} is terminal/interstitial - locking it traps the user"


def test_an_unknown_status_does_not_lock(isolated_cancel_state):
    """Fail OPEN. An unrecognised status is a bug somewhere else; trapping the
    user in the UI is a worse outcome than letting them navigate away."""
    isolated_cancel_state['download_status'] = 'some_future_thing'
    assert C.is_operation_in_progress() is False


def test_post_processing_locks_even_on_a_terminal_status(isolated_cancel_state):
    """Conversions run AFTER the status flips to 'done'. Navigating away then
    kills the converter mid-file, so the second condition is not redundant."""
    isolated_cancel_state['download_status'] = 'done'
    isolated_cancel_state['is_post_processing'] = True
    assert C.is_operation_in_progress() is True


def test_no_status_at_all_does_not_lock(isolated_cancel_state):
    assert C.is_operation_in_progress() is False


# ── the drift guards ─────────────────────────────────────────────────────────

def _literal_set_in(path: Path, name: str) -> set:
    """Read a module-level ``name = {...}`` set of string literals via AST.

    ``app.py`` executes Streamlit calls at import time, so it can only ever be
    parsed, never imported.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return set(ast.literal_eval(node.value))
    raise AssertionError(f"{path.name} no longer defines {name}")


def test_app_active_statuses_mirror_cancellation_exactly():
    """THE regression. ``app.py`` resets the cancel flag whenever the status is
    not in its own copy of this set, so a phase missing there has its cancel
    silently wiped on the very next rerun.

    Kept as an equality assertion rather than a subset one on purpose: an EXTRA
    status in app.py is just as wrong, because then a terminal screen never
    clears a stale cancel and the following run self-aborts.
    """
    app_set = _literal_set_in(REPO / "app.py", "_active_dl_statuses")
    assert app_set == C._IN_PROGRESS_DOWNLOAD_STATUSES, (
        "app.py:_active_dl_statuses has drifted from "
        "cancellation._IN_PROGRESS_DOWNLOAD_STATUSES.\n"
        f"  only in app.py:       {sorted(app_set - C._IN_PROGRESS_DOWNLOAD_STATUSES)}\n"
        f"  only in cancellation: {sorted(C._IN_PROGRESS_DOWNLOAD_STATUSES - app_set)}")


def test_panopto_is_an_active_download_phase():
    """Named explicitly because this is the one that actually shipped broken,
    and because it is the only phase never assigned as a literal - it arrives
    via ``_next_phase_after_courses()``, so a grep for it finds nothing."""
    assert 'panopto' in C._IN_PROGRESS_DOWNLOAD_STATUSES


def test_the_two_phase_sets_are_disjoint():
    """``is_operation_in_progress`` does ONE membership test against the union,
    so an overlapping value would make the two flows indistinguishable - and
    the docstring claims disjointness outright."""
    overlap = C._IN_PROGRESS_DOWNLOAD_STATUSES & C._IN_PROGRESS_SYNC_STATUSES
    assert not overlap, f"download and sync phases share {sorted(overlap)}"


def test_the_union_is_the_public_set():
    assert C.IN_PROGRESS_STATUSES == (
        C._IN_PROGRESS_DOWNLOAD_STATUSES | C._IN_PROGRESS_SYNC_STATUSES)


# Every value ``download_status`` is allowed to hold. A new phase must be added
# to one of these two, which is the whole point: the test fails until someone
# decides whether it locks navigation.
_KNOWN_TERMINAL = {
    'done', 'cancelled', 'sync_complete', 'sync_cancelled', 'sync_failed',
    'analyzed', 'select', '',
}


def _assigned_download_statuses() -> dict:
    """{status: [where it is set]} for every literal assigned in the tree.

    Also walks the RETURNS of any function whose name ends
    ``_next_phase_after_courses`` - a status can reach session_state through a
    helper, and the one that broke Cancel did exactly that.
    """
    found: dict = {}

    def record(value, where):
        found.setdefault(value, []).append(where)

    def targets_download_status(node) -> bool:
        return (isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == 'download_status')

    def values_of(node):
        """Literal strings a value expression can evaluate to."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.IfExp):          # 'a' if cond else 'b'
            return values_of(node.body) + values_of(node.orelse)
        return []

    for root in SOURCE_ROOTS:
        p = REPO / root
        files = [p] if p.is_file() else sorted(p.rglob("*.py"))
        for f in files:
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            rel = f.relative_to(REPO).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    if any(targets_download_status(t) for t in node.targets):
                        for v in values_of(node.value):
                            record(v, f"{rel}:{node.lineno}")
                elif (isinstance(node, ast.FunctionDef)
                      and node.name.endswith("_next_phase_after_courses")):
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Return) and sub.value is not None:
                            for v in values_of(sub.value):
                                record(v, f"{rel}:{sub.lineno} (return)")
    return found


def test_the_scanner_still_finds_the_statuses():
    """A guard on the guard: if the assignment shape changes, the scan below
    would pass by finding nothing at all."""
    found = _assigned_download_statuses()
    assert len(found) >= 10, f"only found {sorted(found)} - the scanner is broken"
    assert 'panopto' in found, \
        "the helper-return walk stopped working; 'panopto' is only reachable that way"


def test_every_status_the_app_can_set_is_classified():
    """A new phase must be classified as active or terminal, deliberately.

    This is the test that would have caught the Panopto bug at the moment the
    phase was introduced, rather than after users reported that Cancel did
    nothing.
    """
    found = _assigned_download_statuses()
    known = C.IN_PROGRESS_STATUSES | _KNOWN_TERMINAL
    unclassified = {s: v for s, v in found.items() if s not in known}
    assert not unclassified, (
        "download_status values that are neither an active phase nor a known "
        "terminal screen:\n" + "\n".join(
            f"  {s!r} set at {', '.join(where)}"
            for s, where in sorted(unclassified.items())) +
        "\n\nAdd it to cancellation._IN_PROGRESS_*_STATUSES (so Cancel works "
        "and navigation locks) or to _KNOWN_TERMINAL in this file.")


def test_no_declared_phase_has_become_unreachable():
    """The other direction: a phase nothing can set any more is dead weight
    that keeps ``app.py``'s mirrored copy honest for no reason.

    ``pre_sync`` is reachable, ``isolated_retry`` is reachable - if one stops
    being assigned, this says so instead of leaving it to rot.
    """
    found = set(_assigned_download_statuses())
    orphans = C.IN_PROGRESS_STATUSES - found
    assert not orphans, (
        f"declared active phases nothing assigns any more: {sorted(orphans)}")
