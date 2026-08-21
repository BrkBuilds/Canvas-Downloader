"""The tracked Office PID decides what gets FORCE-KILLED, so it must never be a guess.

``find_new_office_pid`` used to return the first process of its name that was
not in the pre-dispatch snapshot, with nothing checking it was ours. Measured on
Windows 2026-08-21 against ``Application.Hwnd`` -> ``GetWindowThreadProcessId``
as ground truth, with two concurrent instances::

    lane A   guessed = 2448   TRUE = 9816
    lane B   guessed = 2448   TRUE = 2448

Lane A held lane B's PID, and 9816 was tracked by nobody - which is the 5h54m
orphaned ``EXCEL.EXE`` the register has carried since 2026-08-08. Both loose
ends in those two register entries fall out of this: "the app killed every
instance it tracked" is true because it tracked 2448 twice, and the leak
appearing "inside a row whose convert_excel was never applied" is because
attribution was cross-lane.

**IT WAS NOT ONLY A HARNESS PROBLEM, and that is why this is fixed rather than
noted.** One process, no harness: the user opens their own workbook, the app
dispatches, and ``find_new_office_pid`` returns the user's PID. The 180 s
watchdog then runs ``taskkill /F`` on it and their unsaved document is gone -
the precise outcome ``engine/office_pid.py``'s module docstring says it exists
to prevent. The window is small but reopens on every conversion batch: measured
0.506 s Excel, 2.344 s Word, 2.357 s PowerPoint.

THE DISCRIMINATOR WAS ALREADY MEASURED, twice, on real Windows, and is recorded
in ``tests/audit/AUDIT_FINDINGS.md``: a COM-activated Office is
``EXCEL.EXE /automation -Embedding`` with ParentProcessId = RPCSS - *"COM-
launched and headless, NOT a user's own Excel window"*. A document the user
double-clicked never carries that flag. So this fix applies an established fact
rather than introducing a new heuristic.

WHY THE FIX IS PURE psutil AND TOUCHES NO COM. The obvious exact answer is to
ask the COM object for its own window handle, and the Windows session proved
that works. It cannot go here: ``tests/test_crash_vector_hardening.py`` pins the
ordering that everything between ``DispatchEx`` and the PID capture is a window
where a raise strands a real process, and a property read on an Office build
that refuses it is exactly such a raise. The command line is readable from
outside the process and adds nothing to that window.

WHY THIS SHIPS WITHOUT THE SECOND HALF. The Windows session's write-up says the
two halves must land together, because "stop guessing when ambiguous" makes
``kill_office_pid``'s broad ``/IM`` fallback more reachable. That is true of an
ambiguity rule ALONE. It is not true of this one: for an ordinary single
instance the candidate set is exactly one whether or not the user has Office
open - the user's own process is filtered out by rule 1 rather than making the
answer ambiguous - so ``None`` does not become more common for them and the
fallback is no more reachable than before. The two halves are decoupled by the
``-Embedding`` filter, which is the point of choosing it.

The broad-``/IM``-kill fallback is a **separate, pre-existing** data-loss path
and is deliberately NOT changed here; see the note at the end of this file.
"""

from __future__ import annotations

import types

import pytest

import engine.office_pid as office_pid


# ── a fake process table ─────────────────────────────────────────────────────

class FakeProc:
    """Enough of ``psutil.Process`` for the attribution logic."""

    def __init__(self, pid, name, cmdline, raises=None):
        self.pid = pid
        self.info = {"pid": pid, "name": name}
        self._cmdline = cmdline
        self._raises = raises

    def cmdline(self):
        if self._raises:
            raise self._raises
        return self._cmdline


def fake_psutil(procs):
    return types.SimpleNamespace(
        process_iter=lambda attrs=None: list(procs),
        NoSuchProcess=RuntimeError,
        AccessDenied=PermissionError,
    )


def install(monkeypatch, procs, settle=0.0):
    """Point the real function at a fake table, with the settle wait removed."""
    monkeypatch.setattr(office_pid, "_ATTRIBUTION_SETTLE_SECONDS", settle)
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil(procs))


COM = ["C:\\Office\\EXCEL.EXE", "/automation", "-Embedding"]
USER = ["C:\\Office\\EXCEL.EXE", "C:\\Users\\me\\Budget.xlsx"]


# ── the scenario that loses a student's work ─────────────────────────────────

def test_the_users_own_workbook_is_never_adopted(monkeypatch):
    """THE defect. One app instance, no harness.

    The user opens Budget.xlsx during the 0.5 s window between the snapshot and
    the poll. Before the fix this returned 5001 - their PID - and the watchdog
    force-killed it.
    """
    install(monkeypatch, [
        FakeProc(5001, "EXCEL.EXE", USER),   # the user's, opened just now
        FakeProc(5002, "EXCEL.EXE", COM),    # ours
    ])
    assert office_pid.find_new_office_pid("EXCEL.EXE", pre_pids=set()) == 5002


def test_the_users_workbook_alone_yields_no_pid_at_all(monkeypatch):
    """If OUR dispatch has not appeared yet, the honest answer is "I don't know".

    Returning the user's PID here is what made the watchdog lethal.
    """
    install(monkeypatch, [FakeProc(5001, "EXCEL.EXE", USER)])
    assert office_pid.find_new_office_pid("EXCEL.EXE", pre_pids=set()) is None


def test_a_user_process_that_predates_us_is_excluded_twice_over(monkeypatch):
    """Belt and braces: it is in pre_pids AND it is not COM-launched."""
    install(monkeypatch, [
        FakeProc(4000, "EXCEL.EXE", USER),
        FakeProc(5002, "EXCEL.EXE", COM),
    ])
    assert office_pid.find_new_office_pid("EXCEL.EXE", {4000}) == 5002


def test_a_LEAKED_ORPHAN_from_an_earlier_batch_is_excluded_by_pre_pids(monkeypatch):
    """The case that makes the snapshot load-bearing, and the one my first pass
    missed - the mutation survived because every other fixture let the
    ``-Embedding`` filter do the snapshot's job.

    The register carries a COM-launched EXCEL.EXE that outlived its owner by
    5h54m. It is ``-Embedding``, so rule 1 cannot exclude it; only ``pre_pids``
    can. Without the snapshot the next ``_init_app`` sees the orphan alongside
    our fresh process, calls it ambiguous, and tracks NOTHING - so that batch
    leaks too, and the leak compounds with every conversion for the life of the
    session.
    """
    install(monkeypatch, [
        FakeProc(20872, "EXCEL.EXE", COM),   # yesterday's orphan, still alive
        FakeProc(5002, "EXCEL.EXE", COM),    # ours, dispatched just now
    ])
    assert office_pid.find_new_office_pid("EXCEL.EXE", pre_pids={20872}) == 5002


def test_two_orphans_plus_ours_still_resolves_to_ours(monkeypatch):
    """Leaks accumulate, so the snapshot has to hold at more than one."""
    install(monkeypatch, [
        FakeProc(20872, "EXCEL.EXE", COM),
        FakeProc(20999, "EXCEL.EXE", COM),
        FakeProc(5002, "EXCEL.EXE", COM),
    ])
    assert office_pid.find_new_office_pid(
        "EXCEL.EXE", pre_pids={20872, 20999}) == 5002


# ── ambiguity: two automation clients ────────────────────────────────────────

def test_two_concurrent_com_instances_are_AMBIGUOUS_not_a_guess(monkeypatch):
    """The measured cross-lane case: lane A must not claim lane B's process."""
    install(monkeypatch, [
        FakeProc(2448, "EXCEL.EXE", COM),
        FakeProc(9816, "EXCEL.EXE", COM),
    ])
    assert office_pid.find_new_office_pid("EXCEL.EXE", pre_pids=set()) is None


def test_ambiguity_is_LOGGED_because_a_silent_none_is_undiagnosable(monkeypatch, caplog):
    """This repo has already paid an hour for a destructive path that logged
    nothing. A refusal to attribute must say so."""
    install(monkeypatch, [
        FakeProc(2448, "EXCEL.EXE", COM),
        FakeProc(9816, "EXCEL.EXE", COM),
    ])
    with caplog.at_level("WARNING"):
        office_pid.find_new_office_pid("EXCEL.EXE", pre_pids=set())
    # getMessage() applies the args once; r.message is ALREADY formatted, so
    # `r.message % r.args` double-formats and raises.
    rendered = " ".join(r.getMessage() for r in caplog.records)
    assert "2448" in rendered and "9816" in rendered, rendered
    assert "Cannot attribute" in rendered, rendered


def test_the_settle_pass_is_what_catches_a_racing_sibling(monkeypatch):
    """Deciding on the first sighting would call a two-instance race unambiguous.

    The table grows between the first look and the second, exactly as a second
    COM activation would. Without the settle re-check this returns 2448.
    """
    first = [FakeProc(2448, "EXCEL.EXE", COM)]
    later = first + [FakeProc(9816, "EXCEL.EXE", COM)]
    state = {"n": 0}

    def process_iter(attrs=None):
        state["n"] += 1
        return list(first if state["n"] == 1 else later)

    monkeypatch.setattr(office_pid, "_ATTRIBUTION_SETTLE_SECONDS", 0.0)
    monkeypatch.setitem(
        __import__("sys").modules, "psutil",
        types.SimpleNamespace(process_iter=process_iter,
                              NoSuchProcess=RuntimeError,
                              AccessDenied=PermissionError))
    assert office_pid.find_new_office_pid("EXCEL.EXE", pre_pids=set()) is None
    assert state["n"] >= 2, "the settle re-check never ran"


# ── unreadable processes fail toward leaking, never toward killing ───────────

@pytest.mark.parametrize("boom", [PermissionError("AccessDenied"),
                                  RuntimeError("NoSuchProcess"),
                                  OSError("gone")])
def test_an_unreadable_command_line_is_not_adopted(monkeypatch, boom):
    """A process we cannot identify is not ours to kill.

    The asymmetry is the whole design: a leaked headless Office costs ~175 MB
    and is reclaimed on the next clean launch; a force-kill aimed at a process
    we could not identify costs the user their unsaved work.
    """
    install(monkeypatch, [FakeProc(5002, "EXCEL.EXE", None, raises=boom)])
    assert office_pid.find_new_office_pid("EXCEL.EXE", pre_pids=set()) is None


def test_a_missing_psutil_yields_no_pid_rather_than_raising(monkeypatch):
    """It runs on the init path; raising here strands the process it was
    dispatched to track."""
    import builtins
    real = builtins.__import__

    def no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("no psutil")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_psutil)
    assert office_pid.find_new_office_pid("EXCEL.EXE", pre_pids=set()) is None


# ── the discriminator itself ─────────────────────────────────────────────────

@pytest.mark.parametrize("cmdline,expected", [
    (["EXCEL.EXE", "/automation", "-Embedding"], True),    # measured on Windows
    (["WINWORD.EXE", "-Embedding"], True),                 # Word's COM form
    (["POWERPNT.EXE", "/automation", "-embedding"], True),  # case-insensitive
    (["EXCEL.EXE", "/Embedding"], True),                   # slash form
    (["EXCEL.EXE", "C:\\Users\\me\\Budget.xlsx"], False),  # the user's own
    (["EXCEL.EXE"], False),                                # bare launch
    ([], False),
    (None, False),
])
def test_the_com_activation_marker(cmdline, expected):
    assert office_pid._is_com_launched(FakeProc(1, "X", cmdline)) is expected


def test_the_markers_are_matched_case_insensitively_on_the_whole_line():
    """Windows reports the flag with inconsistent casing and either separator;
    matching only one spelling would silently stop adopting our own process,
    which degrades to a permanent leak rather than an error."""
    assert all(m == m.lower() for m in office_pid._COM_ACTIVATION_MARKERS), \
        "markers must be lower-case - the command line is lower-cased before matching"


# ── the name filter still applies ────────────────────────────────────────────

def test_another_apps_com_process_is_not_adopted(monkeypatch):
    """`-Embedding` is a COM flag, not an Office one - any automation client
    carries it. The exe name is still what says which app this is."""
    install(monkeypatch, [
        FakeProc(7001, "OUTLOOK.EXE", COM),
        FakeProc(7002, "EXCEL.EXE", COM),
    ])
    assert office_pid.find_new_office_pid("EXCEL.EXE", pre_pids=set()) == 7002


def test_the_exe_name_match_is_case_insensitive(monkeypatch):
    install(monkeypatch, [FakeProc(7002, "excel.exe", COM)])
    assert office_pid.find_new_office_pid("EXCEL.EXE", pre_pids=set()) == 7002


# ── what is deliberately NOT changed ─────────────────────────────────────────

def test_the_broad_IM_kill_fallback_still_exists_and_is_still_flagged():
    """SEPARATE, PRE-EXISTING, and deliberately untouched here.

    ``kill_office_pid(0, name)`` still runs ``taskkill /F /IM`` and closes every
    instance of that app, the user's documents included. It is a real data-loss
    path, but it is not this defect and it carries a genuine trade the fix above
    does not: the kill is what unblocks the stalled COM call in the main thread,
    so simply refusing to kill turns a 180 s hang into an unbounded one - and
    the daily auto-sync runs unattended.

    This test exists so the fallback cannot be quietly deleted as "obviously
    wrong" without that trade being decided: it must either keep warning the
    user or be replaced by something that also unblocks the thread.
    """
    import inspect
    src = inspect.getsource(office_pid.kill_office_pid)
    assert "/IM" in src, "the broad fallback vanished - was the hang trade decided?"
    assert "pp_force_kill_warning" in src, (
        "the broad kill no longer tells the completion screen it fired, so a "
        "user whose other documents were closed is never told")
