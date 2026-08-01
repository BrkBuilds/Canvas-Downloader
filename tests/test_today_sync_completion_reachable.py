"""A FINISHED sync must always be able to reach its completion handler.

The bug this locks down (frozen build, 2026-07-31)
--------------------------------------------------
A Today Quick Sync over four courses downloaded all 203 files, wrote its history
entry, and then sat on **"No course folders found - this can happen after a page
refresh."** for as long as the user left it there. The run was over and had
succeeded; the screen said its courses had gone missing.

Two independent defects had to line up, and each is guarded separately:

1. ``sync.persistence.update_last_synced_batch`` (called by the ENGINE, at the
   very end of every run) assigned the PERSISTED pair list over
   ``st.session_state['sync_pairs']``. The Today dashboard runs with a curated
   subset published from ``today_dashboard.json`` which is never written to
   ``canvas_sync_pairs.json``, so for a user who only ever used Saved Groups &
   Pairs - i.e. an empty pairs file - the running sync's own pair list was
   replaced with ``[]`` by its own completion. Guarded in
   ``tests/test_sync_persistence.py``.

2. ``render_sync_step4``'s empty-``sync_pairs`` notice ended in ``st.stop()``
   and sat ABOVE the terminal-state routing, so the handler that writes the
   Today completion notice and calls ``cleanup_sync_state()`` was unreachable.
   Nothing could clear the state that caused it, so every rerun landed on the
   same screen. That is what turned a recoverable glitch into a dead end, and it
   is what this file guards.

The invariant: the notice may only refuse to render a phase that actually READS
the pair list. Only the analysis does.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import sync_ui  # noqa: E402

SRC = (REPO / "sync_ui.py").read_text(encoding="utf-8")

# Every download_status render_sync_step4 dispatches on, terminal ones last.
TERMINAL = ("sync_complete", "sync_cancelled", "sync_failed")
POST_ANALYSIS = ("analyzed", "pre_sync", "syncing", "sync_panopto", *TERMINAL)


class _Stopped(Exception):
    """st.stop() - the notice refused to render the page."""


class _Reran(Exception):
    """st.rerun() - the branch under test was reached and handed off."""


@pytest.fixture()
def st_stub(monkeypatch):
    """Drive the real ``render_sync_step4`` with the smallest stub that lets its
    control flow run. Everything stubbed here is a COLLABORATOR of the guard,
    never the guard itself."""
    calls: list = []

    def _stop():
        raise _Stopped()

    def _rerun(*_a, **_k):
        raise _Reran()

    stub = SimpleNamespace(
        session_state={},
        stop=_stop,
        rerun=_rerun,
        button=lambda *a, **k: False,
        markdown=lambda *a, **k: None,
        html=lambda *a, **k: None,
        empty=lambda *a, **k: SimpleNamespace(button=lambda *a, **k: False),
        toast=lambda *a, **k: None,
    )
    monkeypatch.setattr(sync_ui, "st", stub)

    # Page chrome + the completion handler's own collaborators. The handler
    # being REACHED is what this file asserts; what it then does is covered by
    # tests/test_auto_sync.py.
    import styles
    import ui.sync_review
    import ui.amber_notice
    import core.state_registry
    import core.auto_sync
    monkeypatch.setattr(styles, "inject_css", lambda *a, **k: None)
    monkeypatch.setattr(ui.sync_review, "inject_dynamic_sync_review_css",
                        lambda *a, **k: None)
    monkeypatch.setattr(ui.amber_notice, "render_amber_notice",
                        lambda *a, **k: calls.append("amber"))
    monkeypatch.setattr(core.state_registry, "cleanup_sync_state",
                        lambda *a, **k: calls.append("cleanup"))
    monkeypatch.setattr(core.auto_sync, "build_today_sync_notice",
                        lambda *a, **k: {"is_auto": False, "total_files": 203})

    stub.calls = calls
    return stub


# ── the reported failure, end to end ─────────────────────────────────────────

def test_a_completed_today_sync_with_no_pairs_still_completes(st_stub):
    """The exact stuck state, reconstructed from the frozen build's diagnostics
    (``phase: sync_complete``) and config dir (``canvas_sync_pairs.json`` == [],
    four courses in ``today_dashboard.json``)."""
    st_stub.session_state.update({
        "sync_pairs": [],                 # wiped by update_last_synced_batch
        "download_status": "sync_complete",
        "today_sync_active": True,
        "synced_count": 203,
    })

    with pytest.raises(_Reran):
        sync_ui.render_sync_step4()

    assert "amber" not in st_stub.calls, (
        "a FINISHED sync was refused with 'No course folders found'. The notice "
        "must not gate a phase that never reads the pair list.")
    assert "cleanup" in st_stub.calls, "cleanup_sync_state() was never reached"
    assert st_stub.session_state.get("today_sync_notice"), \
        "the Today completion notice was never built"
    assert "today_sync_active" not in st_stub.session_state


def test_a_cancelled_today_sync_with_no_pairs_still_completes(st_stub):
    """Same dead end, other terminal state - and the one a user hits by pressing
    Cancel, so it must not need a pair list either."""
    st_stub.session_state.update({
        "sync_pairs": [],
        "download_status": "sync_cancelled",
        "today_sync_active": True,
    })

    with pytest.raises(_Reran):
        sync_ui.render_sync_step4()

    assert "amber" not in st_stub.calls
    assert "cleanup" in st_stub.calls


# ── the notice still does its actual job ─────────────────────────────────────

def test_the_notice_still_fires_when_the_analysis_has_nothing_to_analyze(st_stub):
    """Narrowing the guard must not silence it where it is right: a refresh that
    drops the pairs BEFORE analysis leaves nothing to run, and saying so is the
    only useful thing left to do."""
    st_stub.session_state.update({"sync_pairs": [], "download_status": "analyzing"})

    with pytest.raises(_Stopped):
        sync_ui.render_sync_step4()

    assert "amber" in st_stub.calls


def test_the_notice_still_fires_on_an_unknown_status(st_stub):
    """No status at all is the post-refresh case the notice was written for."""
    st_stub.session_state.update({"sync_pairs": []})

    with pytest.raises(_Stopped):
        sync_ui.render_sync_step4()

    assert "amber" in st_stub.calls


# ── the allow-list matches what the code actually needs ──────────────────────

def test_every_post_analysis_status_is_exempt():
    missing = [s for s in POST_ANALYSIS if s not in sync_ui._STATUSES_NOT_NEEDING_PAIRS]
    assert not missing, (
        f"{missing} would be blocked by the empty-pairs notice, but read nothing "
        f"from the pair list. Blocking a terminal status strands a finished run.")


def test_analysis_is_NOT_exempt():
    """It is the one consumer - exempting it would hand run_analysis an empty
    list and produce an empty review screen instead of an explanation."""
    for s in ("analyzing", ""):
        assert s not in sync_ui._STATUSES_NOT_NEEDING_PAIRS


def test_the_pair_list_is_read_by_the_analysis_branch_and_nothing_else():
    """The allow-list is only correct while this stays true. If a later phase
    starts reading sync_pairs, it must come OFF the list (or stop reading it) -
    and this is what will say so, since nothing else would notice.
    """
    fn = next(n for n in ast.walk(ast.parse(SRC))
              if isinstance(n, ast.FunctionDef) and n.name == "render_sync_step4")

    # The dispatch chain: `if status == 'analyzing': ... elif ...`. Walk to it,
    # then check which arms mention the local `sync_pairs`.
    def _reads_pairs(node) -> bool:
        return any(isinstance(n, ast.Name) and n.id == "sync_pairs"
                   for n in ast.walk(node))

    dispatch = None
    for node in ast.walk(fn):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "status"
                and isinstance(node.test.comparators[0], ast.Constant)
                and node.test.comparators[0].value == "analyzing"):
            dispatch = node
            break
    assert dispatch is not None, "the status dispatch moved; update this guard"

    offenders = []
    tail = dispatch.orelse
    while tail:
        arm = tail[0]
        if not isinstance(arm, ast.If):
            break
        if _reads_pairs(arm.test) or any(_reads_pairs(b) for b in arm.body):
            label = getattr(arm.test.comparators[0], "value", "?") \
                if isinstance(arm.test, ast.Compare) else "?"
            offenders.append(label)
        tail = arm.orelse

    assert not offenders, (
        f"phase(s) {offenders} now read sync_pairs but are exempt from the "
        f"empty-pairs notice - they would render against an empty list.")
