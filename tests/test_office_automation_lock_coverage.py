"""Every osascript that DRIVES an Office app takes that app's lock.

macOS gives a user session exactly ONE Microsoft Word / Excel / PowerPoint, so
two Canvas Downloader instances drive the same application. `_office_app_lock`
was added on 2026-08-11 for that reason - and it landed on ONE of the eight
osascript call sites in this module: the conversion. Priming and teardown were
left unlocked.

MEASURED 2026-08-21, five audit lanes (= five instances) on macOS 26.6.1: two
lanes that convert NOTHING (`free2`, `free3`) were both driving
`tell application "Microsoft Excel"` for their run-end teardown when Excel
crashed into Microsoft Error Reporting. Four concurrent Office teardown
osascripts were captured in flight, including two for Word.

That is WORSE than the case the original lock was written for - it needs
neither instance to be converting - and a crashed Excel takes the user's
unsaved workbook with it. `office_is_ours_to_quit` prevents us QUITTING their
document; nothing prevents us CRASHING it.

This test counts the SITES rather than checking that a fix exists, because
this repo's history is that such a fix lands on some of them and nobody
notices for months (`pdf_looks_real`: two of three delete sites, eight months;
the Office delete-gate: Windows but not macOS).
"""
import ast
import pathlib
import re

import pytest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "engine" / "applescript_bridge.py"
SRC = MODULE.read_text(encoding="utf-8")
TREE = ast.parse(SRC)

# Every function that issues an osascript, and the lock it MUST carry.
#
#   "always"      - takes `_office_app_lock`
#   "conditional" - takes `_office_app_lock_unless` (caller may already hold it)
#   "caller"      - runs INSIDE a lock its caller holds; taking it again would
#                   block, because flock is per open file description
#   "not-office"  - drives System Events only, never `tell application "Microsoft"`
# NOTE `run_applescript` is absent on purpose: it issues no osascript itself,
# it is the function that HOLDS the lock while `_run_applescript_locked` does.
# `test_conversion_still_holds_the_lock_at_its_wrapper` pins that separately.
EXPECTED = {
    "_run_applescript_locked":           "caller",
    "_try_close_document_after_timeout": "caller",
    "_force_close_canvas_docs_sync":     "conditional",
    "_probe_open_docs":                  "always",
    "_quit_pass":                        "always",
    "_terminate_gallery_stuck":          "always",
    "_warmup_apps":                      "always",
    "_wait_for_exit":                    "not-office",
    # the enclosing orchestrator; its osascript calls all live in the nested
    # helpers above, which are listed in their own right
    "quit_idle_office_apps":             "always",
}


def _functions():
    return [n for n in ast.walk(TREE)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _osascript_calls(fn):
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if name in ("run", "Popen", "check_output", "call"):
                seg = ast.get_source_segment(SRC, n) or ""
                if "osascript" in seg:
                    out.append(n)
    return out


def _lock_kinds(fn):
    kinds = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.With):
            for item in n.items:
                seg = ast.get_source_segment(SRC, item.context_expr) or ""
                if "_office_app_lock_unless" in seg:
                    kinds.add("conditional")
                elif "_office_app_lock" in seg:
                    kinds.add("always")
    return kinds


def _issuers():
    return {fn.name: fn for fn in _functions() if _osascript_calls(fn)}


def test_the_set_of_osascript_issuing_functions_is_known():
    """A NEW osascript call site must be classified, not silently unlocked.

    This is the half that actually holds the line: the fix itself is one `with`
    per site, and the way it rots is a tenth site added later.
    """
    assert set(_issuers()) == set(EXPECTED), (
        "osascript call sites changed - classify each new one in EXPECTED:\n"
        f"  added:   {sorted(set(_issuers()) - set(EXPECTED))}\n"
        f"  removed: {sorted(set(EXPECTED) - set(_issuers()))}"
    )


@pytest.mark.parametrize("name", sorted(n for n, k in EXPECTED.items() if k == "always"))
def test_office_driving_sites_take_the_lock(name):
    fn = _issuers()[name]
    assert "always" in _lock_kinds(fn), (
        f"{name} drives an Office app without taking `_office_app_lock`. Two "
        f"instances doing this at once crash the app into Microsoft Error "
        f"Reporting - measured 2026-08-21."
    )


def _unlocked_osascript_calls(fn):
    """osascript calls in *fn* that are NOT lexically inside a lock.

    `_lock_kinds` answers "does this function contain a lock ANYWHERE", which
    is a question about the function. The thing that regresses is a CALL SITE,
    and the two differ the moment a function holds more than one lock block.

    MEASURED 2026-08-23: `_terminate_gallery_stuck` has TWO
    `with _office_app_lock(app):` blocks - one around `... to quit saving no`,
    one around the `pgrep`/`pkill` pair - so the mutant that unlocks the FIRST
    left the second in place, `_lock_kinds` still answered {"always"}, and the
    mutant SURVIVED. Same "count the sites, not the functions" discipline this
    repo applies to the delete-family gates, one level in.

    Nested `def`s are not descended into: they are separate entries in EXPECTED
    and are checked in their own right (this is what makes the orchestrator
    `quit_idle_office_apps` vacuous here rather than doubly-counted).
    """
    unlocked = []

    def walk(node, locked):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue                      # classified separately
            child_locked = locked
            if isinstance(child, (ast.With, ast.AsyncWith)):
                for item in child.items:
                    seg = ast.get_source_segment(SRC, item.context_expr) or ""
                    if "_office_app_lock" in seg:
                        child_locked = True
            if isinstance(child, ast.Call):
                nm = getattr(child.func, "attr", None) or getattr(child.func, "id", None)
                if nm in ("run", "Popen", "check_output", "call"):
                    seg = ast.get_source_segment(SRC, child) or ""
                    if "osascript" in seg and not locked:
                        unlocked.append(child)
            walk(child, child_locked)

    walk(fn, False)
    return unlocked


@pytest.mark.parametrize(
    "name", sorted(n for n, k in EXPECTED.items() if k in ("always", "conditional")))
def test_EVERY_osascript_call_site_is_inside_the_lock_not_merely_the_function(name):
    """The per-SITE form of the census above.

    A function that locks one of its two Office calls is exactly as dangerous
    as one that locks neither - the unlocked call still drives an application a
    second instance may be mid-conversion with, which is what crashes it into
    Microsoft Error Reporting.
    """
    fn = _issuers()[name]
    unlocked = _unlocked_osascript_calls(fn)
    assert not unlocked, (
        f"{name} issues {len(unlocked)} osascript call(s) OUTSIDE any "
        f"`_office_app_lock`, at line(s) "
        f"{sorted(n.lineno for n in unlocked)} - the function containing a "
        f"lock elsewhere does not protect them."
    )


def test_the_per_site_check_can_actually_fail():
    """A guard that cannot say no is not a guard.

    `_unlocked_osascript_calls` is the whole strength of the test above, and it
    is easy to write one that returns [] for everything (walk the wrong node,
    mis-name the call, treat every `with` as a lock). So hand it a function
    shaped exactly like the surviving mutant: two osascript calls, one locked
    and one not, and require it to find precisely the unlocked one.
    """
    src = (
        "def f(app):\n"
        "    with _office_app_lock(app):\n"
        "        subprocess.run(['osascript', '-e', 'tell application X'])\n"
        "    if True:\n"
        "        subprocess.run(['osascript', '-e', 'tell application Y'])\n"
    )
    global SRC
    saved = SRC
    try:
        SRC = src
        fn = ast.parse(src).body[0]
        found = _unlocked_osascript_calls(fn)
        assert len(found) == 1, f"expected exactly the unlocked call, got {found}"
        assert "tell application Y" in (ast.get_source_segment(src, found[0]) or "")
    finally:
        SRC = saved


def test_the_conditional_helper_still_has_both_arms_structurally():
    """The STRUCTURAL half of the exemption, so it is covered off macOS too.

    `test_the_conditional_helper_REALLY_LOCKS_when_the_caller_does_not` is the
    behavioural proof and it is necessarily macOS-only: `_office_app_lock` is
    built on flock, which degrades to a no-op elsewhere, so there is no lock to
    observe on Windows. That left a real gap - a mutant reducing this function's
    whole body to a bare `yield` (i.e. it NEVER locks, and every one of the
    eight call sites silently stops being protected) SURVIVED a Windows
    mutation pass, because the only test that could see it was skipped.

    macOS is the rare machine here - it is rented - so leaning entirely on it
    is the wrong way round. This asserts the shape on every platform: an
    `already_held` early-out, and a real `_office_app_lock` acquisition on the
    other arm. It cannot prove the lock BLOCKS; it can prove it is still there.
    """
    fn = next(f for f in _functions() if f.name == "_office_app_lock_unless")

    guards = [n for n in ast.walk(fn) if isinstance(n, ast.If)
              and "already_held" in (ast.get_source_segment(SRC, n.test) or "")]
    assert guards, (
        "_office_app_lock_unless no longer branches on already_held - the "
        "nested sweep would re-acquire its caller's lock and stall for the "
        "full 120s timeout")

    locks = [n for n in ast.walk(fn) if isinstance(n, (ast.With, ast.AsyncWith))
             and any("_office_app_lock" in (ast.get_source_segment(SRC, i.context_expr) or "")
                     for i in n.items)]
    assert locks, (
        "_office_app_lock_unless never acquires `_office_app_lock` on ANY path "
        "- the exemption has stopped being conditional and all eight call "
        "sites are now unlocked")

    yields_in_lock = [n for lock in locks for n in ast.walk(lock)
                      if isinstance(n, (ast.Yield, ast.YieldFrom))]
    assert yields_in_lock, (
        "the lock is acquired but the body does not yield inside it, so the "
        "caller's work happens outside the lock it thinks it holds")


def test_conversion_still_holds_the_lock_at_its_wrapper():
    """The original 2026-08-11 fix, pinned so widening never loosens it."""
    fn = next(f for f in _functions() if f.name == "run_applescript")
    assert "always" in _lock_kinds(fn)
    inner = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "_run_applescript_locked"]
    assert len(inner) == 1, "conversion must go through exactly one locked call"


def test_the_timeout_sweep_is_exempt_because_its_caller_holds_the_lock():
    fn = _issuers()["_force_close_canvas_docs_sync"]
    assert "conditional" in _lock_kinds(fn)
    assert re.search(r"_locked_by_caller\s*:\s*bool\s*=\s*False", SRC), (
        "the exemption must DEFAULT to False so a new caller cannot inherit "
        "the unlocked answer by saying nothing")


def test_the_one_nested_call_site_declares_that_it_already_holds_the_lock():
    """Passing nothing there would stall the sweep for the whole lock timeout."""
    fn = next(f for f in _functions() if f.name == "_run_applescript_locked")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and (getattr(n.func, "id", None) == "_force_close_canvas_docs_async")]
    assert len(calls) == 1, "expected exactly one timeout-recovery sweep call"
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert "_locked_by_caller" in kw, (
        "_run_applescript_locked holds this app's lock; the sweep it fires must "
        "say so or it blocks for _OFFICE_LOCK_TIMEOUT_S")
    assert isinstance(kw["_locked_by_caller"], ast.Constant)
    assert kw["_locked_by_caller"].value is True


def test_wait_for_exit_must_not_hold_the_lock_across_its_poll():
    """It queries System Events, never `tell application "Microsoft ..."`.

    Holding a per-app lock across a 12s exit poll is the phase-wide lock the
    module docstring rules out - it would block a second instance for the whole
    teardown rather than for one indivisible operation.
    """
    fn = _issuers()["_wait_for_exit"]
    assert _lock_kinds(fn) == set()
    body = ast.get_source_segment(SRC, fn) or ""
    assert 'tell application "System Events"' in body
    assert not re.search(r'tell application "\{app\}"', body)


def test_a_second_acquire_from_one_process_really_does_block():
    """The measurement the exemption rests on.

    flock is per open file description, so acquiring the same app's lock twice
    in one process blocks against itself. Without the exemption the timeout
    sweep - whose async wrapper exists precisely so a hung app cannot block the
    next file - would stall for the full lock timeout.
    """
    import sys
    if sys.platform != "darwin":
        pytest.skip("the lock degrades to a no-op off macOS")
    import threading
    import time
    import engine.applescript_bridge as B

    prev = B._OFFICE_LOCK_TIMEOUT_S
    B._OFFICE_LOCK_TIMEOUT_S = 2.0
    waited = []
    try:
        def worker():
            t = time.time()
            with B._office_app_lock("CanvasDownloaderTest"):
                waited.append(time.time() - t)

        with B._office_app_lock("CanvasDownloaderTest"):
            th = threading.Thread(target=worker)
            th.start()
            th.join(timeout=15)
        assert not th.is_alive(), "lock never released - it must time out, not hang"
    finally:
        B._OFFICE_LOCK_TIMEOUT_S = prev

    assert waited and waited[0] >= 1.5, (
        "a second acquire returned immediately - flock is not serialising, so "
        "the whole basis for the exemption is gone")


def test_the_exemption_is_a_real_no_op_when_the_caller_holds_the_lock():
    import sys
    if sys.platform != "darwin":
        pytest.skip("the lock degrades to a no-op off macOS")
    import time
    import engine.applescript_bridge as B

    t = time.time()
    with B._office_app_lock("CanvasDownloaderTest2"):
        with B._office_app_lock_unless("CanvasDownloaderTest2", True):
            pass
    assert time.time() - t < 1.0


def test_the_conditional_helper_REALLY_LOCKS_when_the_caller_does_not():
    """The half the AST cannot see, and the gap my own first tests had.

    Every call site was asserted to go through `_office_app_lock_unless`, and
    the helper could still have been gutted to a bare `yield` with all of them
    still reading as locked. A mutation pass found it: two mutants that emptied
    the helper both SURVIVED. This is the behavioural check that closes it.
    """
    import sys
    if sys.platform != "darwin":
        pytest.skip("the lock degrades to a no-op off macOS")
    import threading
    import time
    import engine.applescript_bridge as B

    prev = B._OFFICE_LOCK_TIMEOUT_S
    B._OFFICE_LOCK_TIMEOUT_S = 2.0
    waited = []
    try:
        def worker():
            t = time.time()
            # already_held=False -> this MUST serialise against the holder
            with B._office_app_lock_unless("CanvasDownloaderTest3", False):
                waited.append(time.time() - t)

        with B._office_app_lock("CanvasDownloaderTest3"):
            th = threading.Thread(target=worker)
            th.start()
            th.join(timeout=15)
        assert not th.is_alive(), "must time out, never hang"
    finally:
        B._OFFICE_LOCK_TIMEOUT_S = prev

    assert waited and waited[0] >= 1.5, (
        "_office_app_lock_unless(app, False) did not take the lock - the "
        "helper is a no-op and every call site that trusts it is unprotected")


def test_the_conditional_helper_requires_an_explicit_answer():
    """No default: a new call site must state which case it is."""
    fn = next(f for f in _functions() if f.name == "_office_app_lock_unless")
    assert fn.args.defaults == [], (
        "`already_held` must have no default - inheriting the wrong answer "
        "silently is the failure this whole module keeps repeating")


# ---------------------------------------------------------------------------
# The marker force-close must SAY what it did.
#
# It logged nothing at all, and it is the one teardown step that can end another
# instance's in-flight conversion. During the 2026-08-21 live audit that silence
# meant an Office failure could not be correlated to any cause: the correlation
# table recorded it as "UNEXPLAINED - candidate genuine" and it was settled only
# by re-running the row alone, where it did not reproduce. A single log line
# would have answered it.
# ---------------------------------------------------------------------------

def test_the_marker_close_script_reports_a_result_instead_of_returning_nothing():
    import engine.applescript_bridge as B
    src = B._close_marker_docs_script("Microsoft Excel", "workbooks")
    assert '"not running"' in src, "must distinguish 'app absent' from 'closed nothing'"
    assert 'return "closed " & closedCount' in src, "must report HOW MANY it closed"
    assert "set closedCount to closedCount + 1" in src, "the count must actually increment"


def _run_close(monkeypatch, stdout, rc=0, boom=None):
    """Drive the real function with osascript stubbed to a known answer."""
    import engine.applescript_bridge as B

    class _R:
        def __init__(self): self.stdout, self.returncode = stdout, rc

    def fake_run(*a, **k):
        if boom:
            raise boom
        return _R()

    monkeypatch.setattr(B.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(B.subprocess, "run", fake_run)
    B._force_close_canvas_docs_sync(only_app="Microsoft Excel")


def test_a_closure_is_logged_at_info_with_the_count(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    _run_close(monkeypatch, "closed 2")
    hits = [r for r in caplog.records if "force-closed" in r.getMessage()]
    assert hits, "closing a document must not be silent"
    assert hits[0].levelno == logging.INFO
    assert "2" in hits[0].getMessage()
    assert "Microsoft Excel" in hits[0].getMessage()


def test_the_boring_cases_stay_at_debug(monkeypatch, caplog):
    """A closure is rare and always worth a line; 'nothing to do' is not."""
    import logging
    for answer in ("closed 0", "not running"):
        caplog.clear()
        caplog.set_level(logging.DEBUG)
        _run_close(monkeypatch, answer)
        assert not [r for r in caplog.records if r.levelno >= logging.INFO], \
            f"{answer!r} should not be louder than debug"
        assert [r for r in caplog.records if r.levelno == logging.DEBUG]


def test_an_unexpected_answer_is_a_warning(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    _run_close(monkeypatch, "execution error: something went wrong", rc=1)
    assert [r for r in caplog.records if r.levelno == logging.WARNING]


def test_an_exception_is_logged_not_swallowed(monkeypatch, caplog):
    """The handler was a bare `except Exception: pass`."""
    import logging
    caplog.set_level(logging.DEBUG)
    _run_close(monkeypatch, "", boom=OSError("osascript exploded"))
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warns, "a failed marker close must never be silent"
    assert "osascript exploded" in warns[0].getMessage()
