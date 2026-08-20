"""A denied "access data from other apps" prompt must not read as a slow document.

MEASURED in the PACKAGED app on macOS 26.6.1 (2026-08-20) by clicking **Don't
Allow** on the powerbox prompt - a state nothing had ever driven, and an
entirely ordinary one, because the wording ("Canvas Downloader would like to
access data from other apps") gives a cautious student no reason to accept.

What the user got for ONE `.doc`::

    21:34:26  Word failed (other): ... AppleEvent timed out. (-1712)
    21:34:26  Klyngevejledning_1_Program_2023.doc  Conversion failed - ... (-1712)
    21:36:26  ... AppleEvent timed out. (-1712)            <- the retry
    21:36:26  Klyngevejledning_1_Program_2023.doc  Conversion failed twice

i.e. **~4 minutes and a message naming neither the cause nor a remedy**. On a
course with thirty Office files that is hours of apparent hang.

THE MECHANISM, confirmed rather than inferred: Word was left holding
``Klyngevejledning_1_Program_2023.doc @ Macintosh HD:private:tmp:...`` - the
ORIGINAL path, not a staged ``src_*`` one. So the denial made
``_office_container_tmp`` answer None, ``office_container_stage`` fell back to
``_direct_passthrough``, and Word was asked to open a file OUTSIDE its container
- which raises the per-folder file-access prompt **that staging exists to
avoid**. A blocked prompt holds the AppleEvent until it times out.

`office_container_stage`'s own docstring called that degrade "never worse than
before, only ever better", and the trap note further down the same function
already described this exact mechanism - as a hazard for anyone re-MEASURING
staging, without anyone noticing it is a live USER path.

Why the fix is at the failure and not at the staging: under a denial TCC makes
the container read as ABSENT, which is indistinguishable from "Office was never
launched". The deciding fact is only available later - did THIS run get staging
for THIS app, and did the conversion then time out.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import engine.applescript_bridge as AB  # noqa: E402

#: The exact stderr macOS produced in the packaged app at 21:34:26.
REAL_TIMEOUT = ("1197:1203: execution error: Microsoft Word got an error: "
                "AppleEvent timed out. (-1712)")


@pytest.fixture(autouse=True)
def _clean_run_state():
    AB._office_unstaged.clear()
    yield
    AB._office_unstaged.clear()


def _classify_as_run_applescript_would(err_msg: str, app_name: str) -> str:
    """The two-step verdict `run_applescript` reaches: stderr, then run state.

    Both steps are the REAL functions. The first version of this helper
    RE-IMPLEMENTED the second step inline, and the mutation pass duly reported
    4 of 7 mutants as survivors - because breaking the product's copy could not
    fail a test that carried its own. Extracting `attribute_office_failure` is
    what made this testable at all; never inline the rule here again.
    """
    return AB.attribute_office_failure(
        AB._classify_stderr(err_msg), app_name, err_msg)


def _message_branch() -> str:
    """The container_denied message branch, with COMMENTS BLANKED.

    Blanking is not tidiness: the explanatory comment above the message names
    both "Full Disk Access" and "Files and Folders", so a test that scans the
    raw source passes on the comment whatever the message says. That is exactly
    how the "remedy names the pane that has no toggle" mutant survived the first
    version. Same rule `scripts/verify_architecture.py` applies for the same
    reason - documenting a trap must never satisfy the check that polices it.
    """
    import re
    src = (REPO / "engine" / "applescript_bridge.py").read_text(encoding="utf-8")
    i = src.find("elif category == 'container_denied':")
    assert i > 0, "the container_denied message branch is gone"
    branch = src[i:i + 1600]
    return re.sub(r"#.*", "", branch)


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------

def test_a_timeout_while_unstaged_is_attributed_to_the_prompt():
    AB._office_unstaged.add("Word")
    assert _classify_as_run_applescript_would(REAL_TIMEOUT, "Word") == "container_denied"


def test_a_timeout_while_STAGED_stays_an_ordinary_per_file_failure():
    """The control. Staging worked, so a timeout is a slow document, not a prompt.

    Without this the fix could classify every Office timeout as a permission
    problem, which is the failure in the other direction: a genuinely huge deck
    would abort the phase and tell the user to change a setting that is fine.
    """
    assert _classify_as_run_applescript_would(REAL_TIMEOUT, "Word") == "other"


def test_only_the_app_that_lost_staging_is_affected():
    """Staging is per app - Word losing its container says nothing about Excel."""
    AB._office_unstaged.add("Word")
    assert _classify_as_run_applescript_would(REAL_TIMEOUT, "Excel") == "other"


@pytest.mark.parametrize("msg", [
    "execution error: Not authorised to send Apple events to Microsoft Word. (-1743)",
    'execution error: Can’t get application "Microsoft Word". (-1728)',
    "execution error: Microsoft Word isn't running. (-600)",
])
def test_a_non_timeout_failure_keeps_its_own_category_even_when_unstaged(msg):
    """Being unstaged must not swallow verdicts that are already correct."""
    AB._office_unstaged.add("Word")
    got = _classify_as_run_applescript_would(msg, "Word")
    assert got != "container_denied", (
        f"{msg[:40]!r} was reclassified; only a TIMEOUT is evidence of the prompt")


def test_the_category_is_FATAL_so_the_phase_aborts_once():
    """A denied app-data grant dooms every Office file in that folder alike.

    That is the definition of FATAL_CATEGORIES, and it is what turns ~4 minutes
    per file into one message.
    """
    assert 'container_denied' in AB.FATAL_CATEGORIES


# --------------------------------------------------------------------------
# the state it rests on
# --------------------------------------------------------------------------

def test_the_fallback_records_itself():
    """Taking the no-container path is what makes a later timeout explicable.

    Asserted on ``_direct_passthrough``, which is where BOTH routes into the
    fallback converge - see
    ``test_the_record_lives_at_the_shared_boundary_not_at_one_branch`` for why
    that distinction is not cosmetic. This test originally required the record
    inside ``office_container_stage`` and therefore passed while the packaged
    app was still misreporting, because a denied grant takes the branch that
    version did not instrument.
    """
    import ast
    src = (REPO / "engine" / "applescript_bridge.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_direct_passthrough")
    adds = [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "add"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "_office_unstaged"]
    assert adds, (
        "the staging fallback no longer records itself, so a timeout can no "
        "longer be told from a slow document and the user is back to a bare "
        "-1712 that names neither cause nor remedy")


def test_the_record_is_PER_RUN():
    """A run that got staging must not inherit the previous run's verdict.

    Same lesson as `_office_preexisting`, which was per-PROCESS until 2026-08-13
    and answered run 2 with run 1's facts.
    """
    AB._office_unstaged.add("Word")
    AB.reset_office_priming()
    assert AB._office_unstaged == set(), (
        "reset_office_priming does not clear _office_unstaged, so a later run "
        "with working staging would explain an ordinary timeout as a "
        "permission problem")


# --------------------------------------------------------------------------
# the message
# --------------------------------------------------------------------------

def test_the_message_names_a_pane_that_actually_has_a_toggle():
    """Full Disk Access, NOT "Files and Folders".

    Checked in System Settings on 26.6.1 with this exact denial recorded: the
    app appears under Files and Folders with **no toggle**, so naming that pane
    sends the user somewhere they can do nothing. FDA supersedes the grant and
    is the pane the app's own nudge and Settings card already open.
    """
    branch = _message_branch()
    assert "Full Disk Access" in branch, (
        "the remedy must name Full Disk Access - the only pane with a control "
        "the user can actually operate for this permission")
    assert "Files and Folders" not in branch, (
        "Files and Folders lists the app with no toggle; naming it in the "
        "remedy sends the user nowhere")


def test_the_message_does_not_blame_the_document():
    branch = _message_branch()
    assert "permission" in branch.lower() or "waiting on" in branch.lower(), (
        "the whole point is that the user learns this is a permission state, "
        "not a bad file")


@pytest.mark.parametrize("msg", [
    # classifies as 'other' AND is not a timeout - the case the first version of
    # these tests missed entirely, which let the "any failure while unstaged is
    # called a permission problem" mutant survive. Every non-timeout message it
    # DID try classified as permission/app_missing/app_crashed, so the guard's
    # first clause (`category == 'other'`) carried them and the timeout clause
    # was never under test.
    "1103:1109: execution error: the frontmost document is not the one "
    "Canvas Downloader opened (-30001)",
    "1103:1109: execution error: Microsoft Word got an error: Parameter error. (-50)",
    "1103:1109: execution error: missing value doesn't understand the "
    "\"save as\" message. (-1708)",
])
def test_an_OTHER_failure_that_is_not_a_timeout_stays_other_when_unstaged(msg):
    """Losing staging is not evidence about every subsequent failure.

    A wedged Word (-1708), a mis-bound document (-30001) and a parameter error
    (-50) are all per-file `other`s that happen to occur while unstaged. Calling
    them permission problems would abort the phase and send the user to a
    settings pane about a document that is simply bad.
    """
    AB._office_unstaged.add("Word")
    assert AB._classify_stderr(msg) == "other", "precondition: this must be an 'other'"
    assert _classify_as_run_applescript_would(msg, "Word") == "other"


def test_the_classifier_actually_CONSULTS_the_run_state():
    """The rule is worthless if the one caller stops asking.

    These tests exercise `attribute_office_failure` directly, which is right -
    but it means deleting its call site is invisible to them. Measured: that
    mutant survived until this test existed.
    """
    import ast
    src = (REPO / "engine" / "applescript_bridge.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_run_applescript_locked")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "attribute_office_failure"]
    assert calls, (
        "_run_applescript_locked no longer calls attribute_office_failure, so a "
        "denied "
        "powerbox is back to a bare -1712 that names neither cause nor remedy")


def test_the_refined_category_is_what_reaches_the_message():
    """The verdict must be ASSIGNED, not merely computed and dropped."""
    import ast
    src = (REPO / "engine" / "applescript_bridge.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_run_applescript_locked")
    assigned = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "category" for t in n.targets)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "attribute_office_failure"
    ]
    assert assigned, (
        "attribute_office_failure is called but its result is discarded - the "
        "message branch below would still see the unrefined category")


# --------------------------------------------------------------------------
# BOTH routes into the fallback must count
# --------------------------------------------------------------------------
#
# The first version of this fix recorded the fallback at ONE of its two entry
# points - `stage_root is None` - and the packaged app went on reporting a bare
# -1712, because a DENIED app-data grant takes the OTHER one. The container
# directory still exists and still lists; what fails is the `mkdir`/`copy2`
# INTO it. Only a live re-run in the bundle exposed that; every unit test passed.
#
# So the record belongs in `_direct_passthrough`, which is what both routes
# converge on, and a third route added later gets it for free.

def test_the_record_lives_at_the_shared_boundary_not_at_one_branch():
    import ast
    src = (REPO / "engine" / "applescript_bridge.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    def adds_in(fn_name):
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == fn_name), None)
        assert fn is not None, f"{fn_name} is gone"
        return [n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add" and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "_office_unstaged"]

    assert adds_in("_direct_passthrough"), (
        "_direct_passthrough no longer records the fallback. It is the ONE place "
        "both routes converge, and recording at a branch instead is what let a "
        "denied app-data grant keep reporting a bare -1712 in the packaged app")
    assert not adds_in("office_container_stage"), (
        "office_container_stage records it too - two places to keep in step, "
        "which is the shape that produced the original miss")


def test_every_route_into_the_fallback_goes_through_direct_passthrough():
    """Count the routes, so a new one cannot quietly skip the record."""
    import ast
    src = (REPO / "engine" / "applescript_bridge.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "office_container_stage")
    yields = [n for n in ast.walk(fn) if isinstance(n, ast.YieldFrom)]
    assert len(yields) >= 2, (
        "office_container_stage used to have TWO fallbacks - container missing, "
        "and the staging copy failing. If that changed, re-check that every one "
        "still reaches _direct_passthrough")
    for y in yields:
        assert (isinstance(y.value, ast.Call)
                and isinstance(y.value.func, ast.Name)
                and y.value.func.id == "_direct_passthrough"), (
            "a fallback bypasses _direct_passthrough, so it does not record "
            "itself and its timeouts will be misreported")


def test_the_staging_failure_is_logged_where_it_can_be_READ():
    """debug level is invisible: a real run with debug mode ON had 0 DEBUG lines.

    This is the only line that explains why conversions are about to fail, and
    at `logger.debug` neither a user nor this audit could ever see it.
    """
    import ast
    src = (REPO / "engine" / "applescript_bridge.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "office_container_stage")
    levels = {
        n.func.attr for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "logger"
        and any("staging unavailable" in getattr(a, "value", "")
                for a in ast.walk(n) if isinstance(a, ast.Constant)
                and isinstance(a.value, str))
    }
    assert levels and "debug" not in levels, (
        f"the staging-unavailable line is logged at {levels or 'nowhere'}; the "
        f"app's debug log captures INFO and above, so debug means invisible")
