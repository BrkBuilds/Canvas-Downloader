"""Owner report 2026-09-12: one click, three "Download Start"s.

MEASURED 2026-09-26 in a harness: closing the page's WebSocket mid-download
(the browser reconnects on its own, as after a backgrounded tab or a wifi
blip) made Streamlit start a NEW script run in the SAME session while the old
one was still blocked inside the download - `download_course_async` started
twice, 1.6s apart, same session id. With `core.cancellation.blocking_run` the
reconnected run waits, and when the old run finished the course it is not
downloaded again. Two further facts the design rests on, both measured:

* in the stopped run, even READING `st.session_state` raises StopException -
  so the claim lives in the process, keyed by session id, not in session state;
* the old run is stopped at its first Streamlit call AFTER the blocking call
  returns, so "I finished" must be recorded before any Streamlit call.
"""
from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from core import cancellation as c

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean():
    with c._runs_lock:
        c._runs.clear(); c._completed.clear()
    yield
    with c._runs_lock:
        c._runs.clear(); c._completed.clear()


def _hold(sid, phase, unit, release: threading.Event, *, raise_inside=False):
    """Hold a claim on a thread, like a run blocked inside the download."""
    def _run():
        try:
            with c.blocking_run(phase, unit, session_id=sid):
                release.wait(5)
                if raise_inside:
                    raise RuntimeError("stopped mid-course")
        except RuntimeError:
            pass
    t = threading.Thread(target=_run, name="ScriptRunner.scriptThread", daemon=True)
    t.start()
    time.sleep(0.05)
    return t


def test_nothing_running_means_do_the_work():
    assert c.wait_for_other_blocking_run(lambda: None, session_id="S") is False


def test_a_second_run_WAITS_for_the_first_and_sees_it_FINISHED():
    release = threading.Event()
    t = _hold("S", "download", 0, release)
    beats = []
    threading.Timer(0.3, release.set).start()
    assert c.wait_for_other_blocking_run(lambda: beats.append(1), poll=0.05,
                                         session_id="S") is True
    assert not t.is_alive()
    assert beats, "no heartbeat while waiting - the screen would be deaf to Cancel"
    assert c.blocking_run_completed("download", 0, session_id="S") is True
    assert c.blocking_run_completed("download", 1, session_id="S") is False, (
        "a DIFFERENT course was reported finished")


def test_a_run_stopped_MID_WORK_is_not_reported_finished():
    """Then the course must run again - skip-existing makes that a resume."""
    release = threading.Event()
    _hold("S", "download", 0, release, raise_inside=True)
    threading.Timer(0.2, release.set).start()
    assert c.wait_for_other_blocking_run(lambda: None, poll=0.05, session_id="S") is True
    assert c.blocking_run_completed("download", 0, session_id="S") is False


def test_ANOTHER_session_is_never_waited_for():
    release = threading.Event()
    _hold("S1", "download", 0, release)
    try:
        assert c.wait_for_other_blocking_run(lambda: None, session_id="S2") is False
    finally:
        release.set()


def test_a_DEAD_thread_s_claim_blocks_nothing():
    dead = threading.Thread(target=lambda: None); dead.start(); dead.join()
    with c._runs_lock:
        c._runs["S"] = {"thread": dead, "phase": "download", "unit": 0}
    assert c.other_blocking_run("S") is None


def test_the_claim_is_released_even_when_the_work_RAISES():
    with pytest.raises(ValueError):
        with c.blocking_run("download", 0, session_id="S"):
            raise ValueError("engine crashed")
    assert "S" not in c._runs


def test_a_new_claim_forgets_the_previous_completion():
    with c.blocking_run("download", 0, session_id="S"):
        pass
    assert c.blocking_run_completed("download", 0, session_id="S")
    with c.blocking_run("download", 1, session_id="S"):
        assert not c.blocking_run_completed("download", 0, session_id="S")


# ── Census: every blocking call on the run path holds a claim ───────────────

_BLOCKING = {"download_course_async", "download_isolated_batch_async",
             "get_course_files_metadata", "run_panopto_batch"}


def _calls_outside_a_claim(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With) and any(
                isinstance(i.context_expr, ast.Call)
                and getattr(i.context_expr.func, "id", "") == "blocking_run"
                for i in node.items):
            guarded.update(id(n) for n in ast.walk(node))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in _BLOCKING and id(node) not in guarded:
                bad.append(f"{path.name}:{node.lineno} {name}")
    return bad


@pytest.mark.parametrize("rel", ["app.py", "sync_ui.py"])
def test_every_blocking_call_on_the_run_path_holds_a_claim(rel):
    bad = _calls_outside_a_claim(ROOT / rel)
    assert not bad, ("a blocking call a reconnected run could start a second "
                     "time, concurrently: " + ", ".join(bad))


def test_the_census_can_say_NO(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("import asyncio\nasyncio.run(cm.download_course_async(c))\n", encoding="utf-8")
    assert _calls_outside_a_claim(p), "the census could never fail"


def test_a_download_the_old_run_FINISHED_is_not_run_again():
    """app.py must consult the completion record before downloading."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "blocking_run_completed('download', current_idx)" in src
    assert "if not _dl_done_by_other_run:" in src
