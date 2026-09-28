"""Owner report 2026-09-07 #4: Today's daily sync on a session nobody confirmed.

Two incidents, one mechanism: a laptop still joining wifi, and a revoked token,
each let the headless daily sync start on an OPTIMISTICALLY restored session,
and each ended in one amber "Could not analyse ..." notice per course.

Three properties are pinned here:

* a restore records whether Canvas CONFIRMED the sign-in, and only then may the
  daily sync start (app.py's hook);
* an unconfirmed session is re-checked off the script thread, and a refusal
  routes to sign-in rather than to a cascade;
* however many courses fail, the analysis says so ONCE.
"""
from __future__ import annotations

import ast
import threading
import time
import types
from pathlib import Path

import pytest

import ui.auth as auth

ROOT = Path(__file__).resolve().parent.parent


class _SS(dict):
    """A dict that also answers attribute access, like st.session_state."""
    __getattr__ = dict.get


def _st(monkeypatch, **state):
    ss = _SS(state)
    monkeypatch.setattr(auth, "st", types.SimpleNamespace(session_state=ss))
    return ss


class _FakeCM:
    answer = (True, "Logged in as: Isabella")
    calls = 0

    def __init__(self, *_a, **_k):
        pass

    def validate_token(self):
        type(self).calls += 1
        a = type(self).answer
        if isinstance(a, Exception):
            raise a
        return a

    def refreshed_credential(self):
        return None


@pytest.fixture
def fake_cm(monkeypatch):
    _FakeCM.answer = (True, "Logged in as: Isabella")
    _FakeCM.calls = 0
    monkeypatch.setattr(auth, "CanvasManager", _FakeCM)
    return _FakeCM


def _wait(job, timeout=5.0):
    end = time.monotonic() + timeout
    while not job.get("done") and time.monotonic() < end:
        time.sleep(0.01)
    assert job.get("done"), "the re-check thread never finished"


# ── The restore records the verdict ─────────────────────────────────────────

def test_a_VALIDATED_restore_is_confirmed(monkeypatch, fake_cm):
    ss = _st(monkeypatch, api_url="https://x.instructure.com")
    assert auth._adopt_restored_credential(auth.from_token("T")) == "ok"
    assert ss[auth.SESSION_CONFIRMED_KEY] is True


def test_an_OPTIMISTIC_restore_is_NOT_confirmed(monkeypatch, fake_cm):
    fake_cm.answer = (False, "Could not connect: Max retries exceeded")
    ss = _st(monkeypatch, api_url="https://x.instructure.com",
             **{auth.SESSION_CONFIRMED_KEY: True})       # a stale True must not survive
    assert auth._adopt_restored_credential(auth.from_token("T")) == "optimistic"
    assert ss["is_authenticated"] is True, "the optimistic restore itself must stay"
    assert ss[auth.SESSION_CONFIRMED_KEY] is False


# ── The re-check ─────────────────────────────────────────────────────────────

def test_a_confirmed_session_asks_nothing(monkeypatch, fake_cm):
    _st(monkeypatch, is_authenticated=True, **{auth.SESSION_CONFIRMED_KEY: True})
    assert auth.poll_session_confirmation() is True
    assert fake_cm.calls == 0


def test_the_re_check_waits_its_INTERVAL(monkeypatch, fake_cm):
    ss = _st(monkeypatch, is_authenticated=True, api_url="u",
             _session_reconfirm_at=time.monotonic())
    assert auth.poll_session_confirmation() is False
    assert "_session_reconfirm" not in ss, "re-checked inside the interval"


def test_a_re_check_that_SUCCEEDS_confirms_on_the_next_run(monkeypatch, fake_cm):
    ss = _st(monkeypatch, is_authenticated=True, api_url="u", api_token="T")
    assert auth.poll_session_confirmation() is False          # starts the thread
    job = ss["_session_reconfirm"]
    _wait(job)
    assert auth.poll_session_confirmation() is True           # reads the answer
    assert ss[auth.SESSION_CONFIRMED_KEY] is True
    assert ss["user_name"] == "Isabella"


def test_the_re_check_runs_OFF_the_script_thread(monkeypatch, fake_cm):
    seen = []
    gate = threading.Event()

    class _Slow(_FakeCM):
        def validate_token(self):
            seen.append(threading.current_thread().name)
            gate.wait(5)
            return (True, "Logged in as: X")

    monkeypatch.setattr(auth, "CanvasManager", _Slow)
    ss = _st(monkeypatch, is_authenticated=True, api_url="u", api_token="T")
    t0 = time.monotonic()
    assert auth.poll_session_confirmation() is False
    assert time.monotonic() - t0 < 1.0, "the check blocked the script thread"
    gate.set()
    _wait(ss["_session_reconfirm"])
    assert seen and seen[0] != threading.current_thread().name


def test_a_REFUSED_re_check_routes_to_sign_in(monkeypatch, fake_cm):
    fake_cm.answer = (False, "401 Unauthorized: Invalid access token")
    reauth = []
    monkeypatch.setattr(auth, "force_reauth", lambda reason="": reauth.append(reason))
    ss = _st(monkeypatch, is_authenticated=True, api_url="u", api_token="T")
    auth.poll_session_confirmation()
    _wait(ss["_session_reconfirm"])
    assert auth.poll_session_confirmation() is False
    assert reauth, "a revoked token was left signed in, waiting for a cascade"


def test_a_NETWORK_failure_on_re_check_just_waits(monkeypatch, fake_cm):
    fake_cm.answer = (False, "Could not connect: timed out")
    reauth = []
    monkeypatch.setattr(auth, "force_reauth", lambda reason="": reauth.append(reason))
    ss = _st(monkeypatch, is_authenticated=True, api_url="u", api_token="T")
    auth.poll_session_confirmation()
    _wait(ss["_session_reconfirm"])
    assert auth.poll_session_confirmation() is False
    assert not reauth, "an offline laptop was sent to the login page"
    assert not ss.get(auth.SESSION_CONFIRMED_KEY)


# ── app.py's hook ───────────────────────────────────────────────────────────

def test_the_daily_sync_starts_ONLY_behind_a_confirmed_session():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    starts = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and getattr(n.func, "id", "") == "start_today_sync"]
    assert len(starts) == 1, "expected exactly one auto-sync start in app.py"
    guarded = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Call)
                and getattr(node.test.func, "id", "") == "poll_session_confirmation"):
            if any(n is starts[0] for n in ast.walk(node)):
                guarded = True
    assert guarded, "the daily sync can start without Canvas having confirmed the sign-in"


# ── One notice, not one per course ──────────────────────────────────────────

class _Unauthorized(Exception):
    status_code = 401


def _report(monkeypatch, failures, analysed):
    from sync import analysis
    notices, reauth, cleaned = [], [], []
    import ui.amber_notice as amber
    import core.state_registry as reg
    monkeypatch.setattr(amber, "render_amber_notice",
                        lambda msg, **k: notices.append((msg, k.get("detail"))))
    monkeypatch.setattr(auth, "force_reauth", lambda reason="": reauth.append(reason))
    monkeypatch.setattr(reg, "cleanup_sync_state", lambda: cleaned.append(1))
    analysis._report_analysis_failures(failures, total_pairs=len(failures) + analysed,
                                       analysed=analysed)
    return notices, reauth, cleaned


def test_MANY_failing_courses_make_ONE_notice(monkeypatch):
    fails = [(f"Course {i}", RuntimeError("Could not connect: timed out")) for i in range(7)]
    notices, reauth, _ = _report(monkeypatch, fails, analysed=0)
    assert len(notices) == 1, f"{len(notices)} notices for one cause"
    assert "7 of 7" in notices[0][0]
    assert "2 more" in notices[0][1]
    assert not reauth


def test_a_REFUSED_login_on_every_course_routes_to_sign_in(monkeypatch):
    fails = [(f"Course {i}", _Unauthorized("401 Unauthorized")) for i in range(4)]
    notices, reauth, cleaned = _report(monkeypatch, fails, analysed=0)
    assert reauth and not notices
    assert cleaned, "the half-finished analysis would greet the user after signing in"


def test_auth_failures_beside_a_SUCCESS_are_not_a_dead_login(monkeypatch):
    fails = [("Course A", _Unauthorized("401 Unauthorized"))]
    notices, reauth, _ = _report(monkeypatch, fails, analysed=2)
    assert not reauth and len(notices) == 1


def test_the_analysis_loop_no_longer_announces_PER_COURSE():
    src = (ROOT / "sync" / "analysis.py").read_text(encoding="utf-8")
    assert 'f"Could not analyse \\"{display_name}\\""' not in src
    assert "_analysis_failures.append((display_name, e))" in src
