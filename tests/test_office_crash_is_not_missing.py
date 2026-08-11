"""A crashed Office app is not an uninstalled one.

THE DEFECT, measured on the 2026-08-11 download matrix (course 43660), three
log lines three seconds apart::

    21:29:47  PowerPoint failed (other): ... Parameter error. (-50)
    21:29:50  PowerPoint failed (app_missing): ... Application isn't running. (-600)
    21:29:50  ... skipping remaining 57 PowerPoint file(s)

PowerPoint crashed. ``-600`` is ``procNotFound`` - "not running *right now*" -
which is exactly what a crash leaves behind, and the next ``tell application``
relaunches the app. But `_classify_stderr` mapped it to ``app_missing``, which
is in ``FATAL_CATEGORIES``, so the phase aborted: **57 files abandoned for the
rest of the run**, and the user told an app they had just watched convert forty
files "is not installed or could not be launched".

The fix splits ``-600`` into its own ``app_crashed`` category which is
per-file, retried once, and NOT fatal. A crash that is genuinely unrecoverable
still ends the phase - through ``SYSTEMIC_REPEAT_THRESHOLD``, after three
consecutive failures, which is the mechanism that can actually tell "one bad
deck" from "the app is gone".
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import engine.applescript_bridge as AB  # noqa: E402

#: The SHIPPED pause, captured at import - before the autouse fixture below
#: monkeypatches it to 0 to keep these tests instant. Reading it through `AB`
#: inside a test reads the zero and asserts nothing.
SHIPPED_RELAUNCH_PAUSE_S = AB._CRASH_RELAUNCH_PAUSE_S


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------

CRASH_MESSAGES = [
    # THE REAL ONE, copied byte for byte out of the run's debug log. Note the
    # TYPOGRAPHIC apostrophe: Office writes U+2019, so the pre-existing
    # `"isn't running"` test (straight quote) never matched and the whole
    # classification rested on the `-600` substring alone.
    "710:716: execution error: Microsoft PowerPoint got an error: "
    "Application isn’t running. (-600)",
    "execution error: Microsoft Word got an error: Application isn't running. (-600)",
]

MISSING_MESSAGES = [
    "execution error: Can't get application \"Microsoft Excel\". (-1728) -10814",
    "execution error: Application can't be found. (-10814)",
    "execution error: unable to launch (-10810)",
]


@pytest.mark.parametrize("msg", CRASH_MESSAGES)
def test_a_crash_is_classified_as_a_crash(msg):
    assert AB._classify_stderr(msg) == "app_crashed"


@pytest.mark.parametrize("msg", MISSING_MESSAGES)
def test_a_genuinely_absent_app_is_still_app_missing(msg):
    """The fix must not make real absence recoverable - that would retry, then
    fail three times, then abort with a worse message than before."""
    assert AB._classify_stderr(msg) == "app_missing"


@pytest.mark.parametrize("apostrophe", ["’", "'"])
def test_the_wording_alone_is_enough_in_either_apostrophe(apostrophe):
    """WITHOUT the -600 code, because a future Office build could reword it.

    Both spellings need their own case with no error number in it. The first
    version of this file only had the curly one plus a straight-apostrophe
    message that ALSO carried -600 - so deleting the straight-apostrophe clause
    survived the mutation pass, classified by the number the test happened to
    include.
    """
    assert AB._classify_stderr(
        f"Microsoft PowerPoint got an error: Application isn{apostrophe}t running.") \
        == "app_crashed"


def test_a_crash_is_not_fatal_but_a_missing_app_is():
    assert "app_crashed" not in AB.FATAL_CATEGORIES
    assert "app_missing" in AB.FATAL_CATEGORIES
    assert "permission" in AB.FATAL_CATEGORIES


# --------------------------------------------------------------------------
# the retry
# --------------------------------------------------------------------------

class _Result:
    def __init__(self, rc, stderr=""):
        self.returncode, self.stderr, self.stdout = rc, stderr, ""


@pytest.fixture(autouse=True)
def _fast_and_isolated(monkeypatch):
    """No real sleeping, and never touch the health log or a real app."""
    monkeypatch.setattr(AB, "_CRASH_RELAUNCH_PAUSE_S", 0)
    monkeypatch.setattr(AB.sys, "platform", "darwin", raising=False)
    AB._repeat_key, AB._repeat_count = None, 0
    yield
    AB._repeat_key, AB._repeat_count = None, 0


def _run(calls, dst_exists_after):
    """Drive run_applescript with a scripted sequence of osascript results."""
    seq = list(calls)
    seen = {"n": 0}

    def fake_run(_cmd, **_kw):
        seen["n"] += 1
        return seq[min(seen["n"] - 1, len(seq) - 1)]

    dst = mock.Mock(spec=Path)
    dst.exists.side_effect = lambda: seen["n"] >= dst_exists_after
    src = mock.Mock(spec=Path)
    src.name = "lecture.pptx"
    src.stat.return_value = mock.Mock(st_size=1024)

    with mock.patch.object(AB.subprocess, "run", side_effect=fake_run), \
         mock.patch.object(AB, "_timeout_for", return_value=60):
        ok = AB.run_applescript(src, dst, "PowerPoint", "tell app ...")
    return ok, seen["n"]


CRASH = _Result(1, CRASH_MESSAGES[0])


def test_a_crash_is_retried_once_and_can_succeed():
    """The whole point: one crash costs one retry, not the rest of the phase."""
    ok, calls = _run([CRASH, _Result(0)], dst_exists_after=2)
    assert ok is True
    assert calls == 2, "the crashed file must be retried exactly once"


def test_a_successful_retry_clears_the_wedge_counter():
    """Otherwise three scattered crashes across a long phase would accumulate
    into a systemic abort of a run that is converting everything else."""
    AB._repeat_key, AB._repeat_count = "PowerPoint|other", 2
    _run([CRASH, _Result(0)], dst_exists_after=2)
    assert AB.systemic_failure() is None
    assert AB._repeat_count == 0


def test_the_retry_is_bounded_at_one():
    """A file that reliably crashes the app must not loop forever."""
    ok, calls = _run([CRASH, CRASH], dst_exists_after=99)
    assert ok is False
    assert calls == 2, f"expected exactly one retry, made {calls} attempts"


def test_a_crash_that_does_not_recover_reports_honestly():
    """It must not say 'is not installed' about an app that converted forty
    files a minute ago - that was the whole user-facing defect."""
    _run([CRASH, CRASH], dst_exists_after=99)
    category, detail = AB.get_last_error()
    assert category == "app_crashed"
    assert "not installed" not in detail.lower()
    assert "stopped running" in detail.lower()
    assert "lecture.pptx" in detail


def test_repeated_crashes_still_end_the_phase():
    """Not fatal is not the same as unbounded. Three in a row is systemic, and
    that is the mechanism that can tell one bad deck from a dead app."""
    for _ in range(AB.SYSTEMIC_REPEAT_THRESHOLD):
        _run([CRASH, CRASH], dst_exists_after=99)
    got = AB.systemic_failure()
    assert got is not None and got[0] == "PowerPoint"


def test_a_missing_app_is_not_retried():
    """Retrying an app that is not installed just delays an honest error."""
    ok, calls = _run([_Result(1, MISSING_MESSAGES[1])], dst_exists_after=99)
    assert ok is False
    assert calls == 1
    assert AB.get_last_error()[0] == "app_missing"


def test_the_retry_is_classified_on_its_OWN_error():
    """A relaunched app can fail for a completely different reason.

    If the retry hits an Automation denial, reporting the original
    ``app_crashed`` would be wrong twice over: the message would blame a crash,
    and - because ``app_crashed`` is deliberately not fatal - the phase would
    grind through every remaining file re-triggering a denial that will never
    resolve itself, instead of stopping with the one actionable sentence about
    System Settings.
    """
    ok, calls = _run([CRASH, _Result(1, "not authorized to send apple events (-1743)")],
                     dst_exists_after=99)
    assert ok is False
    assert calls == 2
    category, detail = AB.get_last_error()
    assert category == "permission", f"the retry's own error was ignored ({category})"
    assert "Automation" in detail


def test_the_relaunch_pause_is_real_but_small():
    """It exists so macOS can reap the dead process (and Microsoft Error
    Reporting can take its turn) before we ask for a new one - an immediate
    retry tends to inherit the same corpse. Pinned in BOTH directions: zero
    makes the retry pointless, and a large value would be paid per crashed
    file. The tests above run with it monkeypatched to 0 for speed, so without
    this assertion nothing would notice it becoming 0 for real - which is why
    it reads the value captured at IMPORT, not through `AB`.
    """
    assert 0 < SHIPPED_RELAUNCH_PAUSE_S <= 10


def test_a_permission_denial_is_not_retried():
    ok, calls = _run([_Result(1, "not authorized to send apple events (-1743)")],
                     dst_exists_after=99)
    assert ok is False
    assert calls == 1
    assert AB.get_last_error()[0] == "permission"
