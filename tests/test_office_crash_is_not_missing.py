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


# ---------------------------------------------------------------------------
# The wording clauses are LOCALE-FRAGILE, and three of the four were dead
# ---------------------------------------------------------------------------
#
# Measured on macOS 26.6.1 (2026-08-20) by making osascript actually fail:
#
#     Can’t get application "NoSuchApp12345XYZ". (-1728)
#     Not authorised to send Apple events to System Events. (-1743)
#
# Two independent ways the clauses missed, both the SAME class this file already
# documents for ``isn't running`` - a fix that landed on one clause and not its
# neighbours:
#
# 1. macOS writes a TYPOGRAPHIC apostrophe (U+2019). ``can't get application``
#    and ``application can't be found`` were written with the ASCII one, so they
#    matched nothing. ``isn't running`` was given both forms in 2026-08-11; its
#    siblings were not.
# 2. This machine's macOS emits the BRITISH spelling, "auth**oris**ed". The
#    clause only knew the American one.
#
# The permission verdict survived on its ``-1743`` companion. **app_missing did
# not**: there is no numeric companion for -1728, so a genuinely absent Office
# app classified as ``other`` - not fatal - and a user without Office got three
# generic per-file errors followed by the systemic message telling them to
# "Quit Microsoft Word and run again", about an app they do not have.
#
# The remedy normalises the apostrophe ONCE instead of spelling every clause
# twice, because the next clause added would otherwise inherit the same bug.

_REAL_MISSING_APP = 'execution error: Can’t get application "NoSuchApp12345XYZ". (-1728)'
_REAL_DENIED = ('execution error: Not authorised to send Apple events to '
                'System Events. (-1743)')


@pytest.mark.parametrize("msg", [
    _REAL_MISSING_APP,
    'syntax error: Can’t get application id "com.nonexistent.app". (-1728)',
    # the same message with no error number at all - the case the wording
    # clause is the ONLY defence for
    'execution error: Can’t get application "Microsoft Word".',
])
def test_a_missing_app_is_app_missing_despite_the_typographic_apostrophe(msg):
    assert AB._classify_stderr(msg) == "app_missing", (
        "macOS writes a typographic apostrophe, so an ASCII-only clause never "
        "fires. There is no numeric companion for -1728, so this fell through "
        "to 'other' and the phase never aborted for an uninstalled Office.")


def test_app_missing_is_fatal_so_the_phase_stops_asking():
    assert AB._classify_stderr(_REAL_MISSING_APP) in AB.FATAL_CATEGORIES


@pytest.mark.parametrize("msg", [
    _REAL_DENIED,
    # British and American, each WITHOUT the error number, so the wording is
    # the only thing that can decide
    'execution error: Not authorised to send Apple events to Microsoft Word.',
    'execution error: Not authorized to send Apple events to Microsoft Word.',
])
def test_a_denial_is_permission_in_either_spelling(msg):
    assert AB._classify_stderr(msg) == "permission", (
        "this machine's macOS says 'authorised'; the clause knew only "
        "'authorized', leaving the verdict resting on the -1743 code")


@pytest.mark.parametrize("msg", [
    "execution error: Microsoft Word isn’t running.",
    "execution error: Microsoft Word isn't running.",
])
def test_both_apostrophes_still_reach_app_crashed(msg):
    """The clause that WAS fixed must survive the shared normalisation."""
    assert AB._classify_stderr(msg) == "app_crashed"


@pytest.mark.parametrize("msg,why", [
    ('execution error: Can’t get active document. (-1728)',
     "our own scripts raise -1728 for an absent DOCUMENT"),
    ('execution error: Can’t get window 1 of application "Microsoft Word". (-1728)',
     "-1728 about some other object of a perfectly present app"),
])
def test_minus_1728_alone_must_not_mean_the_app_is_missing(msg, why):
    """Why -1728 is deliberately NOT in the numeric list.

    Mapping the code wholesale would abort a phase with "Office is not
    installed" on a machine where it plainly is - a fatal, and the wrong one.
    The wording separates the two exactly, which is the whole reason the
    apostrophe had to be fixed rather than the number added.
    """
    assert AB._classify_stderr(msg) != "app_missing", why


def test_the_apostrophe_is_normalised_once_not_per_clause():
    """A new clause must not have to remember the typographic form.

    Spelling each clause twice is what produced this defect: ``isn't running``
    carried both forms while its neighbours carried one.
    """
    import inspect
    import re
    src = inspect.getsource(AB._classify_stderr)
    body = src.split('"""')[-1]
    # Blank COMMENTS before scanning - the same rule verify_architecture.py
    # applies, and for the same reason: documenting a trap must never trip the
    # check that polices it. The escape used by the normalisation itself is
    # written \u2019, so it survives this strip on purpose.
    body = re.sub(r"#.*", "", body)
    assert "’" not in body, (
        "a clause still spells the typographic apostrophe inline; normalise it "
        "in one place instead so the next clause added cannot miss it")


# ---------------------------------------------------------------------------
# ...and neither is a connection that died, nor our own frontmost guard.
#
# Found by the live macOS audit, 2026-08-21, matrix row m032 - the largest
# Office batch in the plan (~88 files across two courses). Three files failed,
# each surrounded by dozens of successes:
#
#   02:42:24  PowerPoint failed (other): ... the frontmost presentation is not
#             the one Canvas Downloader opened (-30001)
#   02:45:56  PowerPoint failed (other): ... Connection is invalid. (-609)
#
# Both are TRANSIENT and both fell to `other`, which gets no retry. They were
# recovered only by `retry_failed_conversions` sweeping the phase afterwards -
# and because that late sweep re-resolves the destination, each one also left a
# duplicate `<stem> (n).pdf` beside the real product.
#
# -609 is `connectionInvalid`: the app was there when we addressed it and is
# gone now, which is -600 one step earlier. This module's own docstring already
# cited it as the signature of PowerPoint being torn down mid-conversion.
#
# -30001 is OUR OWN guard, and retrying it is safe BY CONSTRUCTION: the guard
# exists to refuse a document we do not own, so a retry can never convert
# something it should not.
# ---------------------------------------------------------------------------

TRANSIENT_MESSAGES = [
    ("connection invalid, numeric",
     "1022:1028: execution error: Microsoft PowerPoint got an error: "
     "Connection is invalid. (-609)"),
    ("connection invalid, wording only",
     "execution error: Microsoft Word got an error: Connection is invalid."),
]


@pytest.mark.parametrize("why,msg", TRANSIENT_MESSAGES,
                         ids=[w for w, _ in TRANSIENT_MESSAGES])
def test_a_transient_office_failure_is_recoverable_not_other(why, msg):
    got = AB._classify_stderr(msg)
    assert got == "app_crashed", (
        f"{why}: classified {got!r}, so it gets no retry and the file fails "
        "outright for a condition that clears on the next attempt")


@pytest.mark.parametrize("why,msg", TRANSIENT_MESSAGES,
                         ids=[w for w, _ in TRANSIENT_MESSAGES])
def test_a_transient_office_failure_is_never_fatal(why, msg):
    assert AB._classify_stderr(msg) not in AB.FATAL_CATEGORIES, (
        f"{why}: a transient failure must not abort the phase - that is the "
        "exact mistake -600 made when it was classified app_missing")


def test_the_quiet_direction_genuine_absence_is_still_app_missing():
    """A check that only ever fires is not a check."""
    assert AB._classify_stderr(
        'execution error: Can’t get application "Microsoft Word". (-1728)'
    ) == "app_missing"
    assert AB._classify_stderr("execution error: (-10810)") == "app_missing"


def test_the_quiet_direction_permission_is_still_permission():
    assert AB._classify_stderr(
        "execution error: Not authorised to send Apple events to Microsoft "
        "Word. (-1743)") == "permission"


def test_an_ordinary_error_is_still_other():
    """Widening must not swallow everything into 'retry me'."""
    assert AB._classify_stderr(
        "execution error: Parameter error. (-50)") == "other"
    assert AB._classify_stderr("execution error: something odd") == "other"


def test_the_NUMBER_alone_carries_a_dead_connection_on_a_localised_mac():
    """On a Danish macOS every wording clause matches nothing.

    This repo already learned that once: three of four clauses in this function
    were locale-dead and only the numeric companions kept them working, which is
    why `app_missing` losing its number mattered more than it looked. So the
    number must classify -609 on its own, with no English in the message.

    The mutation pass is what forced this test: with only an English message in
    the suite, deleting `'-609' in err_msg` SURVIVED, because the wording clause
    beside it rescued the very case the number exists for.
    """
    assert AB._classify_stderr(
        "1022:1028: eksekveringsfejl: Microsoft PowerPoint fik en fejl. (-609)"
    ) == "app_crashed"


def test_our_own_frontmost_guard_deliberately_stays_other():
    """A DECISION, not an omission - do not "fix" this into app_crashed.

    -30001 is our own guard: the app is running perfectly, it simply has
    someone else's document in front, which is what happens when the user opens
    a document mid-run. Retrying it would be safe, but `app_crashed` tells the
    user the app "stopped running while converting", which is false - and a
    product whose reporting contract is that it tells the truth does not buy one
    retry with a message that misdescribes the machine.

    `tests/test_container_denied_attribution.py` also relies on -30001 being the
    one non-timeout `other` message, to exercise a clause nothing else reaches.
    If this is ever made retryable it needs its OWN category and wording.
    """
    for msg in (
        "1022:1028: execution error: the frontmost presentation is not the one "
        "Canvas Downloader opened (-30001)",
        "eksekveringsfejl: (-30001)",
    ):
        assert AB._classify_stderr(msg) == "other"
