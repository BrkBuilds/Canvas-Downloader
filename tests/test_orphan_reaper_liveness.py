"""``_reap_recorded_orphans`` kills processes. It must be certain the session
that recorded them is over.

``clean_exit: False`` does NOT mean "that session crashed" - it is what the
state file says for the whole time a session is RUNNING (``_save_state`` writes
it on every sample; only ``session_end`` clears it). So a second instance
booting beside a live first one reads the first one's CURRENT children and, with
nothing else to stop it, kills them: the running window's WebView2 process, or
the ffmpeg / transcription worker of a sync in flight.

Reproduced directly against the real function before the fix - a live child was
recorded, reaped, and dead in a single call.

``start.py``'s single-instance guard normally prevents a second instance, but it
fails OPEN by design (mutex creation failure, the ``CANVAS_DL_ALLOW_MULTI``
escape hatch, any exception on the flock path) and its Windows mutex is
session-local, so two Terminal Services sessions for one user share ``%APPDATA%``
but not the mutex. A reaper that can destroy a live session must not rest on a
guard that is allowed to let a second instance through.
"""
import subprocess
import sys
import time

import pytest

psutil = pytest.importorskip("psutil")

from core import health_log


def _spawn_child():
    """A harmless stand-in for a WebView2 / ffmpeg / transcribe-worker child."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    time.sleep(0.4)
    p = psutil.Process(proc.pid)
    record = {"pid": proc.pid, "name": p.name(),
              "created": round(p.create_time(), 3), "mb": 10.0}
    return proc, record


def _state(pid, children):
    """What a session's ``session_state.json`` looks like on disk."""
    return {"pid": pid, "clean_exit": False, "phase": "idle",
            "peak_self_mb": 1, "peak_tree_mb": 2, "children": children,
            "failures": {}, "webview_runtime": "", "uptime_s": 5, "env": {}}


def _dead_pid():
    """A pid that is definitely not running: start a process and reap it."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    for _ in range(50):
        if not psutil.pid_exists(p.pid):
            return p.pid
        time.sleep(0.05)
    pytest.skip("could not obtain a reliably-dead pid on this machine")


# ── The bug ───────────────────────────────────────────────────────────────────

def test_a_live_sessions_children_are_never_killed():
    proc, record = _spawn_child()
    try:
        # os.getpid() is alive by definition - it is this very process.
        import os
        killed, names = health_log._reap_recorded_orphans(_state(os.getpid(), [record]))
        time.sleep(0.3)
        assert (killed, names) == (0, [])
        assert proc.poll() is None, "the reaper killed a LIVE session's child"
    finally:
        proc.kill()


def test_the_guard_is_the_pid_being_alive_not_the_clean_exit_flag():
    """clean_exit is False in both cases; only liveness separates them."""
    proc, record = _spawn_child()
    try:
        import os
        alive = _state(os.getpid(), [record])
        assert alive["clean_exit"] is False
        assert health_log._reap_recorded_orphans(alive) == (0, [])
        assert proc.poll() is None
    finally:
        proc.kill()


# ── The behaviour it must not break ───────────────────────────────────────────

def test_a_genuinely_dead_sessions_orphan_is_still_reaped():
    """The whole point of the module: pre-fix builds strand these, and a
    newly-updated app should clear the damage it did before."""
    proc, record = _spawn_child()
    try:
        killed, names = health_log._reap_recorded_orphans(_state(_dead_pid(), [record]))
        time.sleep(0.5)
        assert killed == 1, "a real orphan was not reaped"
        assert proc.poll() is not None
    finally:
        try:
            proc.kill()
        except Exception:
            pass


def test_a_recycled_child_pid_is_still_rejected_on_creation_time():
    """The pre-existing identity proof must survive the new guard: same pid and
    same name, but created later, is a DIFFERENT process."""
    proc, record = _spawn_child()
    try:
        record = dict(record, created=record["created"] - 60.0)   # claims to be older
        killed, _ = health_log._reap_recorded_orphans(_state(_dead_pid(), [record]))
        time.sleep(0.3)
        assert killed == 0
        assert proc.poll() is None, "a recycled pid was killed on pid+name alone"
    finally:
        proc.kill()


# ── Degradation ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pid", [None, 0, "", "not-a-pid", [], {}])
def test_a_missing_pid_falls_through_to_the_identity_proofs(pid):
    """Refusing outright here LOOKS safer and is not.

    ``_save_state`` has written ``pid`` beside ``children`` since this module
    existed, so a record with children and no pid cannot have come from a live
    session - which is the only thing the liveness guard defends against.
    Refusing would instead disable the sweep for a damaged file (the very leak
    this module exists to clear) and, worse, would make the sparing tests in
    ``test_health_log.py`` vacuous: they pass no pid, so they would then pass
    with the identity proofs deleted.
    """
    proc, record = _spawn_child()
    try:
        killed, _ = health_log._reap_recorded_orphans(_state(pid, [record]))
        time.sleep(0.4)
        assert killed == 1, "a damaged record should still reach the identity proofs"
        assert proc.poll() is not None
    finally:
        try:
            proc.kill()
        except Exception:
            pass


def test_a_missing_pid_does_not_bypass_the_identity_proofs(pid=None):
    """The fall-through must be to the proofs, not around them."""
    proc, record = _spawn_child()
    try:
        record = dict(record, created=record["created"] - 60.0)
        killed, _ = health_log._reap_recorded_orphans(_state(None, [record]))
        time.sleep(0.3)
        assert killed == 0
        assert proc.poll() is None
    finally:
        proc.kill()


def test_a_child_recorded_under_a_different_image_name_is_not_killed():
    """The pre-existing name proof, pinned directly. pid + creation time alone
    would already accept this; the name is the independent second signal."""
    proc, record = _spawn_child()
    try:
        record = dict(record, name="definitely-not-that-process.exe")
        killed, _ = health_log._reap_recorded_orphans(_state(_dead_pid(), [record]))
        time.sleep(0.3)
        assert killed == 0
        assert proc.poll() is None
    finally:
        proc.kill()


def test_no_children_recorded_is_a_no_op():
    assert health_log._reap_recorded_orphans({}) == (0, [])
    assert health_log._reap_recorded_orphans({"pid": 1, "children": []}) == (0, [])
