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
