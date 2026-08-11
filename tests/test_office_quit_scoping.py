"""Quit only what we launched. Asking the documents cannot answer it.

THE DEFECT (data loss), found 2026-08-12 by driving all three Office apps in
the ordinary "the user is editing while a sync converts" state:

    Word        docs 1 -> 0   THE USER'S DOCUMENT WAS CLOSED, app quit
    Excel       docs 1 -> 1   survived
    PowerPoint  docs 1 -> 1   survived

`_idle_quit_script` decided a document is the user's if it has a path on disk
or unsaved changes, with every property read wrapped in its own `try`. The
defaults on a failed read were `hasPath=false` / `isSaved=true` - which is
exactly the definition of PRISTINE - so an undescribable document did not block
the quit, and the quit goes out `saving no`.

And they ARE undescribable. Measured on the same run:

    before a conversion phase   path=[Macintosh HD:...:MY WORD WORK.doc] saved=false
    after a conversion phase    name / path / full name / saved ALL FAIL

not stale references either - the reads fail inside a single `tell` block.
Every app is left holding one such document, and
`_force_close_canvas_docs_sync` cannot close it because it identifies documents
by those same properties.

So NEITHER default works: undescribable-as-pristine destroys a student's
unsaved essay, undescribable-as-blocker leaves all three apps in the dock after
every run (measured: exactly that).

The question that IS answerable is "was it already running before we touched
it?" - which is also the rule the product owner chose. If the user had Word
open, it is theirs; if we launched it, every document in it is ours.

Verified end to end afterwards, all three apps
(`scripts/verify_office_end_to_end.py`):

    cold   12/12 converted, all three quit,      Recents 37 -> 0
    busy   12/12 converted, 3/3 user documents survived, all three left running
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import engine.applescript_bridge as AB  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    AB._office_preexisting.clear()
    yield
    AB._office_preexisting.clear()


# --------------------------------------------------------------------------
# recording who was already running
# --------------------------------------------------------------------------

def _pgrep(found: bool):
    class _R:
        returncode = 0 if found else 1
    return lambda *_a, **_k: _R()


def test_an_app_the_user_already_had_open_is_remembered(monkeypatch):
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(True))
    AB._note_office_preexisting("Word")
    assert AB.office_was_preexisting("Word") is True


def test_an_app_we_launched_is_not(monkeypatch):
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(False))
    AB._note_office_preexisting("Word")
    assert AB.office_was_preexisting("Word") is False


def test_the_observation_is_made_ONCE(monkeypatch):
    """It has to be the state BEFORE we drove the app. Re-observing later would
    see the app we just launched and call it the user's for ever, so nothing
    would ever be quit."""
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(False))
    AB._note_office_preexisting("Excel")
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(True))   # now it IS running
    AB._note_office_preexisting("Excel")
    assert AB.office_was_preexisting("Excel") is False


def test_an_unobserved_app_is_not_treated_as_the_users(monkeypatch):
    """Absence of a record means we never drove it, so there is nothing of ours
    to clean up in it - but it must not silently become a quit target either."""
    assert AB.office_was_preexisting("PowerPoint") is False


def test_a_failing_probe_treats_the_app_as_the_USERS(monkeypatch):
    """Doubt costs an app left in the dock; the other direction costs a
    student's unsaved essay."""
    def boom(*_a, **_k):
        raise OSError("pgrep unavailable")
    monkeypatch.setattr(AB.subprocess, "run", boom)
    AB._note_office_preexisting("Word")
    assert AB.office_was_preexisting("Word") is True


def test_the_observation_happens_under_the_lock_before_the_script():
    """Two instances race to launch the same app, so 'was it running?' is only
    meaningful inside the serialisation - and it must be recorded before we run
    the script that would launch it."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(AB.run_applescript)).body[0]
    withs = [n for n in ast.walk(fn) if isinstance(n, ast.With)]
    assert withs, "run_applescript no longer takes the Office lock"
    body = ast.unparse(withs[0])
    assert "_note_office_preexisting" in body, (
        "the observation must be INSIDE the lock, or it races the other "
        "instance's launch")
    assert body.index("_note_office_preexisting") < body.index("_run_applescript_locked")


# --------------------------------------------------------------------------
# the quit gate
# --------------------------------------------------------------------------

def test_a_preexisting_app_is_never_even_asked_to_quit(monkeypatch):
    """The gate must come BEFORE the document script - the script cannot tell
    whose documents these are, which is the whole point."""
    import ast
    import inspect
    # CODE, not prose: the docstring names `_idle_quit_script` several hundred
    # characters before the gate appears, so a raw string scan compares the
    # explanation with the implementation and fails against correct code.
    fn = ast.parse(inspect.getsource(AB.quit_idle_office_apps)).body[0]
    stripped = [n for n in ast.walk(fn)
                if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                        and isinstance(n.value.value, str))]
    src = "\n".join(ast.unparse(n) for n in stripped
                    if isinstance(n, (ast.If, ast.Call, ast.Assign, ast.For)))
    i_gate = src.find("office_was_preexisting")
    i_script = src.find("_idle_quit_script")
    assert i_gate != -1, "the quit loop does not check who launched the app"
    assert i_script != -1, "the document script is gone - re-derive this test"
    assert i_gate < i_script, (
        "the document script runs before the launched-by-us gate - it would "
        "quit an app the user is working in")


@pytest.mark.parametrize("app,term", [("Word", "documents"),
                                      ("Excel", "workbooks"),
                                      ("PowerPoint", "presentations")])
def test_every_app_is_covered_by_the_gate(app, term):
    """Word behaved differently from Excel and PowerPoint, which is exactly why
    the defect needed all three to surface. The gate must not be per-app."""
    assert app in AB._APP_DOC_MAP


def test_an_undescribable_document_is_OURS_only_when_we_launched_the_app():
    """The policy is explicit rather than an accident of the property defaults,
    because both possible defaults are wrong in one direction."""
    ours = AB._idle_quit_script("Microsoft Word", "documents",
                                undescribable_is_ours=True)
    strict = AB._idle_quit_script("Microsoft Word", "documents",
                                  undescribable_is_ours=False)
    assert "set pristine to true" in ours.split("else")[-1]
    assert "set pristine to false" in strict
    for script in (ours, strict):
        assert "pathKnown" in script and "savedKnown" in script, (
            "the script cannot express 'we could not tell' - which is the "
            "state a real document is in after a conversion phase")


def test_the_full_name_fallback_accepts_an_HFS_path():
    """Word reports `Macintosh HD:Users:...`, with no forward slash in it, so
    the old `contains "/"` test could never fire for Word - a second default
    leaning the same way, toward calling a real document pristine."""
    script = AB._idle_quit_script("Microsoft Word", "documents")
    assert 'fn contains "/"' not in script
    assert 'fn is not ""' in script
