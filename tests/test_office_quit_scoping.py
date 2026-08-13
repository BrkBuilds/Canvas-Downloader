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

-----------------------------------------------------------------------------
THE SAME DEFECT, ONE LEVEL UP - found 2026-08-13, fixed here.

The observation above is only as good as the moment it is taken, and it was
taken in only one of the three places that can launch an Office app, once per
PROCESS rather than once per RUN. Three holes, all reproduced against the real
functions with `sys.platform` reporting darwin:

1. `first_run_permission_setup` launches all three and never observed. It runs
   at run start, BEFORE `prime_office_automation`, so on a new user's first run
   the later observation saw our own launch:

       first-run batch ran: True;  alive after: [Excel, PowerPoint, Word]
       ours to quit -> NONE

   All three left in the dock and (because all three were running) the Recents
   purge declined too - the D11 symptom, on the run that forms a first
   impression.

2. `reset_office_priming` cleared every other piece of per-run Office state and
   not this one, so run 2 of a session answered with run 1's facts:

       run 1  nothing open, we launch Word -> "ours"
              ...the user opens Word, starts an unsaved essay...
       run 2  Word is THEIRS, still reads "ours" -> quit `saving no`

   and run 2 has just had a conversion phase, which is the exact state the
   documents are undescribable in - so the document check cannot catch it
   either. `_office_quit_fired` IS reset per run, so the teardown does fire.

3. An app never observed at all counted as ours. Reachable by cancelling before
   priming ran, and the teardown fires on the cancelled screens too.

The fix is per-run state, an observation at every launcher (with the duty also
placed on `_warmup_apps`, the one function that actually launches, so a future
fourth caller is safe by construction), and a predicate with THREE answers
instead of a boolean with a default.
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
    assert AB._office_preexisting["Word"] is True
    assert AB.office_is_ours_to_quit("Word") is False


def test_an_app_we_launched_is_not(monkeypatch):
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(False))
    AB._note_office_preexisting("Word")
    assert AB._office_preexisting["Word"] is False
    assert AB.office_is_ours_to_quit("Word") is True


def test_the_observation_is_made_ONCE(monkeypatch):
    """It has to be the state BEFORE we drove the app. Re-observing later would
    see the app we just launched and call it the user's for ever, so nothing
    would ever be quit."""
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(False))
    AB._note_office_preexisting("Excel")
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(True))   # now it IS running
    AB._note_office_preexisting("Excel")
    assert AB.office_is_ours_to_quit("Excel") is True


def test_an_unobserved_app_is_LEFT_ALONE(monkeypatch):
    """Absence of a record means we never drove it, so there is nothing of ours
    to clean up in it - and it must not silently become a quit target either.

    THAT SENTENCE IS THE ORIGINAL TEST'S OWN DOCSTRING, and until 2026-08-13 the
    assertion under it pinned the opposite: `office_was_preexisting` answered
    False for an unrecorded app, and False is what makes the teardown send the
    quit script. So the stated intent and the asserted behaviour disagreed, and
    the behaviour won.

    It is reachable rather than theoretical: cancel a download before priming
    has run and NOTHING has been observed, yet the teardown fires on the
    cancelled screens too - so every Office app, including one the user is
    working in, was asked to quit with only the document check (the check D9
    proved cannot answer) standing in the way.
    """
    assert "PowerPoint" not in AB._office_preexisting
    assert AB.office_is_ours_to_quit("PowerPoint") is False


def test_the_three_states_are_all_distinguishable(monkeypatch):
    """A boolean with a default cannot express "we never looked", which is why
    the predicate is `... is False` and not `dict.get(app, False)`."""
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(True))
    AB._note_office_preexisting("Word")                       # the user's
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(False))
    AB._note_office_preexisting("Excel")                      # ours
    assert AB.office_is_ours_to_quit("Excel") is True          # observed, ours
    assert AB.office_is_ours_to_quit("Word") is False          # observed, theirs
    assert AB.office_is_ours_to_quit("PowerPoint") is False    # never observed
    # ...and the two "False" answers are NOT the same fact
    assert AB._office_preexisting.get("Word") is True
    assert AB._office_preexisting.get("PowerPoint") is None


def test_a_failing_probe_treats_the_app_as_the_USERS(monkeypatch):
    """Doubt costs an app left in the dock; the other direction costs a
    student's unsaved essay."""
    def boom(*_a, **_k):
        raise OSError("pgrep unavailable")
    monkeypatch.setattr(AB.subprocess, "run", boom)
    AB._note_office_preexisting("Word")
    assert AB.office_is_ours_to_quit("Word") is False


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
    i_gate = src.find("office_is_ours_to_quit")
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
    # The parameter must actually DECIDE something. Asserting on the strings
    # `set pristine to true/false` is not enough - `set pristine to false` is
    # also the loop's initialiser, so a version that ignores the parameter
    # entirely satisfied it, and that mutant survived the first pass.
    assert ours != strict, (
        "undescribable_is_ours changes nothing - the policy has gone back to "
        "being an accident of the property defaults")
    assert "undescribable_is_ours" in __import__("inspect").getsource(
        AB._idle_quit_script).split('"""')[-1], (
        "the parameter is documented but never used in the script body")
    for script in (ours, strict):
        assert "pathKnown" in script and "savedKnown" in script, (
            "the script cannot express 'we could not tell' - which is the "
            "state a real document is in after a conversion phase")


def test_the_full_name_fallback_accepts_an_HFS_path():
    """Word reports `Macintosh HD:Users:...`, with no forward slash in it, so a
    slash-ONLY test could never fire for Word - a default leaning toward
    calling a real document pristine. Both separators must be accepted; see
    `test_a_full_name_needs_a_SEPARATOR_to_count_as_a_path` for why it must not
    be loosened all the way to "any non-empty name"."""
    script = AB._idle_quit_script("Microsoft Word", "documents")
    assert 'fn contains ":"' in script


def _module_ast():
    import ast
    import inspect
    return ast.parse(inspect.getsource(AB))


def _functions_that_reach(name: str) -> dict:
    """Every top-level function whose body mentions *name*, as {func: node}."""
    import ast
    out = {}
    for node in _module_ast().body:
        if isinstance(node, ast.FunctionDef) and any(
                isinstance(n, ast.Name) and n.id == name for n in ast.walk(node)):
            out[node.name] = node
    return out


def test_EVERY_function_that_launches_an_office_app_observes_first():
    """THE COUNTING RULE, and the reason this test is whole-module.

    The 2026-08-12 fix hoisted the observation into `prime_office_automation`
    and the test written for it checked `prime_office_automation`. There were
    TWO launchers. `first_run_permission_setup` - the EARLIER of the two, called
    at run start by both `app.py` and `sync/execution.py`, while priming happens
    per course - spawned the same `_warmup_apps` with no observation at all, so
    on a machine whose Automation grants were not yet recorded (a new user's
    first run) every app read as the user's and nothing was ever quit.

    Same shape as `pdf_looks_real`, which was written for two delete sites and
    landed on one of them for eight months. So the assertion is not "priming
    observes" but "everything that can launch observes, and does it first".
    """
    import ast
    launchers = _functions_that_reach("_warmup_apps")
    assert launchers, (
        "nothing reaches _warmup_apps any more - re-derive this test against "
        "whatever launches an Office app now")
    for fname, node in sorted(launchers.items()):
        if fname == "_warmup_apps":
            continue
        body = [n for n in node.body
                if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        src = "\n".join(ast.unparse(n) for n in body)
        i_obs = src.find("observe_office_before_launch")
        i_launch = src.find("_warmup_apps")
        assert i_obs != -1, (
            f"{fname} starts _warmup_apps without recording who was already "
            f"open - every app it launches will read as the user's and never "
            f"be quit")
        assert i_obs < i_launch, (
            f"{fname} launches before it observes, so the observation sees our "
            f"own launch")


def test_the_launcher_itself_observes_before_its_first_open():
    """The duty also sits on `_warmup_apps`, which is the ONE function in the
    app that actually runs `open -g -j`.

    Both callers observe on their own (calling) thread, which is what orders it
    correctly - `_warmup_apps` runs on a worker. This call is the backstop that
    makes a FUTURE third caller safe by construction rather than by remembering,
    and it costs a dict lookup when the callers have already done it.
    """
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(AB._warmup_apps)).body[0]
    body = [n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    src = "\n".join(ast.unparse(n) for n in body)
    assert "observe_office_before_launch" in src
    assert src.find("observe_office_before_launch") < src.find("'open'"), (
        "the observation must precede the launch it is describing")


def test_the_observation_covers_ALL_apps_not_only_the_ones_being_launched():
    """A run's contract WIDENS between courses - `office_contract_from_folder`
    scopes priming to the file types in each folder - so the app nobody was
    going to open is exactly the one that gets launched later, by which time
    our own launch has happened."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(AB.observe_office_before_launch)).body[0]
    src = ast.unparse(fn)
    assert "_APP_TRIPLES" in src, (
        "the observation is scoped to something narrower than every app")


def test_the_two_app_name_tables_agree():
    """`_APP_TRIPLES` (priming) and `_APP_DOC_MAP` (the quit gate) name the
    same apps in the same words. If they drift, priming records a key the gate
    never reads and the gate silently stops protecting that app."""
    assert {t[2] for t in AB._APP_TRIPLES} == set(AB._APP_DOC_MAP)


# --------------------------------------------------------------------------
# what counts as "has a path" - the test that decides whether an app is quit
# --------------------------------------------------------------------------

def test_a_full_name_needs_a_SEPARATOR_to_count_as_a_path():
    """An UNSAVED document's `full name` is just its NAME.

    Measured on the real app: `Book1 || path=[] || full name=[Book1] ||
    saved=true`. Excel auto-creates that blank on a hidden launch, so if any
    non-empty full name counts as "has a path", the blank looks user-owned and
    keeps Excel in the dock FOR EVER - which is the exact failure this function
    was originally written to fix, and which left all three apps running after
    the operator's cancelled run on 2026-08-12.

    The test must therefore be for a path SEPARATOR. Both are needed: `/` for
    Excel and PowerPoint, which report POSIX, and `:` for Word, which reports
    an HFS path (`Macintosh HD:Users:...`) and so could never satisfy a
    slash-only test.
    """
    script = AB._idle_quit_script("Microsoft Excel", "workbooks")
    assert 'fn is not ""' not in script, (
        "any non-empty full name counts as a path - an unsaved document's full "
        "name is its NAME, so a pristine blank would block the quit for ever")
    assert 'fn contains "/"' in script, "POSIX paths (Excel, PowerPoint) unmatched"
    assert 'fn contains ":"' in script, "HFS paths (Word) unmatched"


def test_a_document_staged_in_OUR_temp_dir_never_blocks():
    """Our own staged conversion file HAS a real path on disk, so without this
    it reads as user-owned and blocks the quit - which is what left PowerPoint
    and Word running after the cancelled run. A path carrying the
    CanvasDownloaderTmp marker is ours by construction, whoever launched the
    app."""
    for app, coll in (("Microsoft Word", "documents"),
                      ("Microsoft Excel", "workbooks"),
                      ("Microsoft PowerPoint", "presentations")):
        script = AB._idle_quit_script(app, coll)
        assert AB._CANVAS_TMP_MARKER in script, f"{app}: no marker test"
        assert "set isOurs to true" in script
        assert "if isOurs then" in script, (
            f"{app}: the marker result does not short-circuit the blocker test")


# --------------------------------------------------------------------------
# the observation is PER RUN, not per process
# --------------------------------------------------------------------------

def test_reset_office_priming_clears_the_observation():
    """It cleared every OTHER piece of per-run Office state and not this one.

    That omission is the whole of hole 2 in this module's docstring: run 2 of a
    session answered "whose app is this?" with run 1's facts.
    """
    AB._office_preexisting["Word"] = False
    AB.reset_office_priming()
    assert "Word" not in AB._office_preexisting, (
        "the observation survived a run boundary - the next run will decide "
        "whose Word this is using the previous run's answer")


def test_a_second_run_re_observes_and_protects_a_newly_opened_app(monkeypatch):
    """The scenario, end to end, at the level the bug actually bit.

        run 1  nothing open, we launch Word -> ours, correctly quit
               ...the user opens Word and starts an unsaved essay...
        run 2  Word is THEIRS

    Before the fix run 2 still answered "ours", and run 2 has just had a
    conversion phase - the state D9 measured Word's documents as undescribable
    in - so the document check could not catch it either and the quit went out
    `saving no`.
    """
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(False))
    AB.reset_office_priming()
    AB._note_office_preexisting("Word")
    assert AB.office_is_ours_to_quit("Word") is True             # run 1

    monkeypatch.setattr(AB.subprocess, "run", _pgrep(True))      # the user opens it
    AB.reset_office_priming()
    AB._note_office_preexisting("Word")
    assert AB.office_is_ours_to_quit("Word") is False, (         # run 2
        "the second run in a session inherited the first run's answer and "
        "would quit the user's Word saving no")


def test_a_second_run_re_observes_an_app_the_user_CLOSED(monkeypatch):
    """The mirror direction, so the fix cannot be a one-way clamp: an app the
    user had open in run 1 and closed before run 2 becomes ours again, rather
    than being left in the dock for the rest of the session."""
    monkeypatch.setattr(AB.subprocess, "run", _pgrep(True))
    AB.reset_office_priming()
    AB._note_office_preexisting("Excel")
    assert AB.office_is_ours_to_quit("Excel") is False

    monkeypatch.setattr(AB.subprocess, "run", _pgrep(False))
    AB.reset_office_priming()
    AB._note_office_preexisting("Excel")
    assert AB.office_is_ours_to_quit("Excel") is True


def test_the_first_run_batch_still_observes_on_a_LATER_run(monkeypatch):
    """`_first_run_batch_started` is once per PROCESS and the observation is now
    once per RUN, so the platform check and the batch check had to be split.
    Folding them back together makes run 2 skip the run-start observation."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(AB.first_run_permission_setup)).body[0]

    # By POSITION, not by substring: `global _first_run_batch_started` is the
    # function's first statement, so a substring search finds the DECLARATION
    # and reports correct code as broken. The thing that must come second is the
    # early-return GUARD.
    obs = [n.lineno for n in ast.walk(fn)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
           and n.func.id == "observe_office_before_launch"]
    guards = [n.lineno for n in ast.walk(fn)
              if isinstance(n, ast.If)
              and any(isinstance(x, ast.Name) and x.id == "_first_run_batch_started"
                      for x in ast.walk(n.test))
              and any(isinstance(x, ast.Return) for x in ast.walk(n))]
    assert obs, "the run-start launcher does not observe"
    assert guards, (
        "the once-per-process batch guard is gone - re-derive this test; if it "
        "merged back into the platform check, run 2 stops observing at run start")
    assert min(obs) < min(guards), (
        "the once-per-process batch guard short-circuits the once-per-run "
        "observation, so only the first run of a session observes at run start")

    # ...and the platform check must still come FIRST, or this runs pgrep on
    # Windows three times per run.
    plat = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.If) and "platform" in ast.unparse(n.test)]
    assert plat and min(plat) < min(obs), (
        "the observation runs before the platform gate - pgrep does not exist "
        "off macOS")


def test_the_observation_is_thread_safe_and_the_FIRST_answer_wins(monkeypatch):
    """`_warmup_apps` observes from a worker thread while the callers observe on
    the main one. Two callers straddling a launch could both pass an unlocked
    "not recorded yet" check and let the LATER, post-launch answer win - which
    is the single direction that costs a user's document.
    """
    import threading
    import time
    alive = set()

    def slow_pgrep(cmd, *_a, **_k):
        class _R:
            # a real pgrep SAMPLES the process table when it runs, then takes
            # time to answer; sampling after the delay would model a probe that
            # sees the future, which is not the race under test
            returncode = 0 if cmd[2] in alive else 1
        time.sleep(0.05)
        return _R()

    monkeypatch.setattr(AB.subprocess, "run", slow_pgrep)

    def observer():
        AB._note_office_preexisting("Word")

    def launcher():
        time.sleep(0.01)
        alive.add("Microsoft Word")          # our own `open -g -j`
        AB._note_office_preexisting("Word")

    a, b = threading.Thread(target=observer), threading.Thread(target=launcher)
    a.start(); b.start(); a.join(); b.join()
    assert AB._office_preexisting["Word"] is False, (
        "a post-launch observation overwrote the pre-launch one")


def test_the_reset_takes_the_same_lock_as_the_write():
    """A worker thread from the PREVIOUS run may still be inside its probe when
    the next run clears, and a write landing after the clear seeds the new run
    with the old run's answer - the very thing being fixed."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(AB.reset_office_priming)).body[0]
    withs = [n for n in ast.walk(fn) if isinstance(n, ast.With)]
    assert any("_office_observe_lock" in ast.unparse(item.context_expr)
               for w in withs for item in w.items), (
        "the per-run clear is not serialised against the observation write")


# --------------------------------------------------------------------------
# the teardown states the undescribable-document policy, it does not inherit it
# --------------------------------------------------------------------------

def test_the_undescribable_default_is_the_SAFE_one():
    """Saying nothing must mean "not ours".

    It defaulted to True while the single call site said nothing, so the
    docstring's "the caller passes True only for an app IT LAUNCHED" described a
    contract nothing enforced - a second call site would have inherited the
    answer that discards a document.
    """
    import inspect
    default = inspect.signature(AB._idle_quit_script).parameters[
        "undescribable_is_ours"].default
    assert default is False, (
        "an undescribable document is treated as ours unless the caller says "
        "otherwise - that is the direction that quits a user's app saving no")


def test_the_teardown_passes_the_policy_EXPLICITLY():
    """One line under the gate that earns it, so the two can be read together."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(AB.quit_idle_office_apps)).body[0]
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_idle_quit_script"]
    assert calls, "the teardown no longer builds the quit script"
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "undescribable_is_ours" in kw, (
            "the teardown relies on the signature default for a decision that "
            "can discard a user's unsaved document")
        assert isinstance(kw["undescribable_is_ours"], ast.Constant)
        assert kw["undescribable_is_ours"].value is True
