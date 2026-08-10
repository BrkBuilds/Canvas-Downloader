"""A wedged Office app must abort its phase ONCE, not fail every remaining file.

Measured on real macOS 2026-08-10 (audit run macos-15-v2.0.2): feeding the Word
converter a corrupt or 0-byte `.doc` makes Word raise a MODAL "file could not be
opened" alert - the operator watched it bouncing in the Dock. AppleScript's
`open` then never yields an active document, so EVERY later file answers

    Microsoft Word got an error: missing value doesn't understand
    the "save as" message. (-1708)

including a genuine 153 KB .doc that had converted seconds earlier (4 of 4 good
files failed across two fresh processes). Nothing recovered it -
`_force_close_canvas_docs_sync` left the phantom document in place - and only
killing the process did. The delete gates held throughout, so no data was lost;
the user simply got no PDFs and one generic error per file.

`_classify_stderr` maps -1708 to 'other' = per-file, so `FATAL_CATEGORIES`
('permission', 'app_missing') never fired and `_abort_applescript_phase` - which
exists precisely for "failures that will identically doom every remaining file in
the phase" - had no way to be told.

The signal is REPETITION, not the category. These tests pin both directions,
because a threshold that fires on scattered failures would abort runs that are
converting everything else perfectly well.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_counter():
    """Each test starts from a fresh repeat run."""
    import engine.applescript_bridge as ab
    ab._repeat_key, ab._repeat_count = None, 0
    ab._last_error = None
    yield
    ab._repeat_key, ab._repeat_count = None, 0
    ab._last_error = None


def _fail(app: str, category: str, detail: str = "boom") -> None:
    """Simulate one recorded failure exactly as run_applescript's funnel does."""
    import engine.applescript_bridge as ab
    ab._last_error = (category, detail)
    key = f"{app}|{category}"
    if key == ab._repeat_key:
        ab._repeat_count += 1
    else:
        ab._repeat_key, ab._repeat_count = key, 1


def _succeed() -> None:
    import engine.applescript_bridge as ab
    ab._repeat_key, ab._repeat_count = None, 0


# ---------------------------------------------------------------- the counter

def test_a_single_failure_is_not_systemic():
    from engine.applescript_bridge import systemic_failure
    _fail("Word", "other")
    assert systemic_failure() is None


def test_the_same_failure_repeated_becomes_systemic():
    from engine.applescript_bridge import SYSTEMIC_REPEAT_THRESHOLD, systemic_failure
    for _ in range(SYSTEMIC_REPEAT_THRESHOLD):
        _fail("Word", "other")
    got = systemic_failure()
    assert got is not None, "a wedged app must be recognised"
    app, count = got
    assert app == "Word"
    assert count == SYSTEMIC_REPEAT_THRESHOLD


def test_a_success_resets_the_run():
    """THE OTHER DIRECTION, and the reason the threshold is safe.

    A course with a few genuinely odd documents must not abort the phase. Only
    an unbroken run of identical failures counts.
    """
    from engine.applescript_bridge import SYSTEMIC_REPEAT_THRESHOLD, systemic_failure
    for _ in range(SYSTEMIC_REPEAT_THRESHOLD * 3):
        _fail("Word", "other")
        _succeed()
    assert systemic_failure() is None


def test_a_different_app_or_category_restarts_the_count():
    from engine.applescript_bridge import SYSTEMIC_REPEAT_THRESHOLD, systemic_failure
    for i in range(SYSTEMIC_REPEAT_THRESHOLD * 2):
        _fail("Word" if i % 2 else "Excel", "other")
    assert systemic_failure() is None


def test_the_threshold_is_small_enough_to_matter_and_big_enough_to_be_safe():
    """A threshold of 1 is just "every failure is fatal"; a large one never fires
    on the short Office phases these courses produce."""
    from engine.applescript_bridge import SYSTEMIC_REPEAT_THRESHOLD
    assert 2 <= SYSTEMIC_REPEAT_THRESHOLD <= 5


# ------------------------------------------------------- the post-processing wiring

def test_the_runner_is_told_to_abort_once_the_failure_repeats():
    from converters.post_processing import _applescript_last_error
    from engine.applescript_bridge import SYSTEMIC_REPEAT_THRESHOLD
    import sys
    if sys.platform != "darwin":
        pytest.skip("_applescript_last_error is a no-op off darwin by design")
    for _ in range(SYSTEMIC_REPEAT_THRESHOLD):
        _fail("Word", "other", "missing value doesn't understand the save as message")
    reason, fatal = _applescript_last_error()
    assert fatal, "the phase must be aborted once the failure is systemic"
    assert "Word" in fatal
    # It must tell the user what to DO. A disabled control that does not say why
    # is a dead end, and so is an error message that names no remedy.
    assert "Quit" in fatal and "run again" in fatal


def test_one_failure_does_not_abort_the_phase():
    from converters.post_processing import _applescript_last_error
    import sys
    if sys.platform != "darwin":
        pytest.skip("_applescript_last_error is a no-op off darwin by design")
    _fail("Word", "other", "one odd document")
    reason, fatal = _applescript_last_error()
    assert fatal is None, "a single per-file failure must stay per-file"
    assert "one odd document" in reason


# --------------------------------------------------------------- structure

def test_every_applescript_runner_consults_the_shared_classifier():
    """The three runners must not re-implement the decision.

    CLAUDE.md's recurring lesson: a rule written more than once is a rule some
    caller is following an old version of. `_applescript_last_error` is the one
    place the abort verdict is computed, so each runner has to ask it.
    """
    src = (REPO / "converters" / "post_processing.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    runners = {"run_pptx_conversion", "run_word_conversion", "run_excel_conversion"}
    seen = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in runners:
            calls = {
                n.func.id for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            seen[node.name] = calls
    missing = [name for name in runners
               if name in seen and "_applescript_last_error" not in seen[name]]
    assert not missing, f"{missing} do not ask the shared classifier"
    aborts = [name for name in runners
              if name in seen and "_abort_applescript_phase" not in seen[name]]
    assert not aborts, f"{aborts} never abort the phase"


def test_a_real_successful_run_applescript_resets_the_counter(tmp_path, monkeypatch):
    """Drive the REAL run_applescript, not a stand-in for it.

    This test exists because the first version of the suite tested a COPY: its
    "a success resets the run" case called a local helper that zeroed the module
    globals itself, so it passed even with the product's reset deleted. A
    mutation run caught it - remove the two reset lines from run_applescript and
    all nine tests still went green. Exactly the trap CLAUDE.md records as
    "verify the REAL thing, not a copy", and the reason the playbook insists on
    mutating rather than only running the suite.

    An AST check was tried too and was ALSO fooled: `_fail` is nested inside
    run_applescript and assigns the same pair (`_repeat_key, _repeat_count = key,
    1`), so "an assignment to that tuple exists in this function" matched the
    counter-INCREMENT and proved nothing about the reset.

    So: stub only the OS boundary (osascript) and let the real function decide.
    """
    import engine.applescript_bridge as ab

    src = tmp_path / "in.doc"
    src.write_bytes(b"x" * 32)
    dst = tmp_path / "out.pdf"

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, *a, **kw):
        # The success path is "osascript exited 0 AND dst exists".
        if cmd and "osascript" in str(cmd[0]):
            dst.write_bytes(b"%PDF-1.4\n" + b"0" * 512)
        return _R()

    monkeypatch.setattr(ab.subprocess, "run", _fake_run)

    # Wedge the counter first, the way three failed files would.
    for _ in range(ab.SYSTEMIC_REPEAT_THRESHOLD):
        _fail("Word", "other")
    assert ab.systemic_failure() is not None, "precondition: counter is wedged"

    ok = ab.run_applescript(src, dst, "Word", 'tell application "Word" to return 1')
    assert ok, "the stubbed osascript success must be reported as success"
    assert ab.systemic_failure() is None, (
        "a converted file proves the app is not wedged - the repeat run must reset")
