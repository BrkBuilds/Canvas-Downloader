"""Render-smoke tests: every high-risk UI surface is actually EXECUTED.

Why this file exists
--------------------
This is the app's documented blind spot. CLAUDE.md's "Verify in the REAL app"
section states it plainly: *1,431 passing unit tests cannot see an
``UnboundLocalError``, and one real download can.* The engine's flat-mode
dispatch referenced a name bound in a different function, the exception was
swallowed and reported as a generic "Processing Error", an entire course
downloaded nothing - and every structural test still passed, because they
assert source SHAPE and the shape was right.

The same family shows up repeatedly in this repo's history:

* ``sync/analysis.py:sync_progress_hook`` raised ``NameError`` on every tick
  for months because an import lived in the wrong branch, inside a bare
  ``except Exception``. The analysis panel silently never painted.
* a swallowed exception in any repaint hook hides the whole panel.

None of that is reachable by testing pure functions. ``streamlit.testing.v1``
runs the real script, so an import that is not there, a name that is not bound,
or a signature that has drifted surfaces as ``at.exception``.

What these tests are and are NOT
--------------------------------
They assert **"this renders, and produces the elements it claims to"**. They do
NOT assert layout, spacing or visual design - Streamlit's test runtime has no
browser, so none of the CSS rules CLAUDE.md documents are exercised here. That
is what the UI gallery and a real ``streamlit run`` are for. The value is
narrow and real: a render path that raises can no longer reach a release.
"""

from __future__ import annotations

import itertools
import textwrap
from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parents[1]

# ── why these scripts are written to a file we control ───────────────────────
# ``AppTest.from_string`` stages the script through a temp file written with the
# platform's DEFAULT encoding, and Streamlit's script cache reads it back as
# utf-8. On Windows that is cp1252, so a single non-ASCII character - the "Ø" in
# a realistic Danish course name - fails the run with
# ``UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd8``, reported as a
# script *compilation* error rather than anything to do with encodings.
#
# This is the same trap CLAUDE.md records under Platform Notes ("always specify
# encoding='utf-8' explicitly - Windows defaults to CP1252"). Writing the file
# here with an explicit encoding is the fix, and it keeps the non-ASCII course
# names in the fixtures where they belong: mojibake in course names is a bug
# this app has had before, so the smoke tests should be able to express it.
_SCRIPT_DIR: Path | None = None
_COUNTER = itertools.count()


@pytest.fixture(scope="session", autouse=True)
def _script_dir(tmp_path_factory):
    global _SCRIPT_DIR
    _SCRIPT_DIR = tmp_path_factory.mktemp("render_smoke")
    yield _SCRIPT_DIR

# A pair of realistic Canvas course stand-ins. `course_code` carries the
# "(Course Name)" suffix Canvas really appends, because stripping it is part of
# what the list under test does.
# Indented to 4 spaces so it concatenates with the equally-indented bodies below
# and ``textwrap.dedent`` still finds a common prefix across the whole script.
COURSES = """
    courses = [
        SimpleNamespace(id=101, name="Introduction to Information Systems",
                        course_code="BINTO1060U.LA_E25 (Introduction to Information Systems)",
                        friendly_name=None),
        SimpleNamespace(id=102, name="Regnskab og \u00d8konomistyring",
                        course_code="BREGN1020U.LA_E25", friendly_name=None),
    ]
"""


# Proof that the script body actually RAN to the end.
#
# This is not belt-and-braces, it is load-bearing. A script *compilation*
# failure - a stray indent, a bad encoding - does NOT appear in
# ``at.exception``; it is logged to stderr and the run simply produces nothing.
# So a smoke test whose only assertion is "no exception" passes when the body
# never executed at all, which is the strongest possible version of a test that
# cannot fail. Found the hard way: an unindented fixture string made
# ``textwrap.dedent`` a no-op, five dashboard tests silently stopped running,
# and they still reported green when the function they call had its signature
# renamed out from under them.
_SENTINEL = "_cd_smoke_completed"


def _script(body: str, *, state: dict | None = None) -> str:
    head = [
        "import sys",
        f"sys.path.insert(0, {str(REPO)!r})",
        "from types import SimpleNamespace",
        "from collections import deque",
        "import streamlit as st",
    ]
    for key, value in (state or {}).items():
        head.append(f"st.session_state[{key!r}] = {value!r}")
    # dedent() needs ONE common prefix across the whole body, so every fixture
    # chunk that gets concatenated here must share the callers' indentation.
    return ("\n".join(head) + "\n"
            + textwrap.dedent(body)
            + f"\nst.session_state[{_SENTINEL!r}] = True\n")


def render(body: str, *, state: dict | None = None, timeout: int = 60) -> AppTest:
    """Write the script as utf-8 and run it. See the note above on encoding."""
    assert _SCRIPT_DIR is not None, "the session fixture did not run"
    path = _SCRIPT_DIR / f"smoke_{next(_COUNTER)}.py"
    path.write_text(_script(body, state=state), encoding="utf-8")
    at = AppTest.from_file(str(path), default_timeout=timeout)
    at.run()
    return at


def assert_clean(at: AppTest, what: str) -> None:
    """Assert the body ran to completion and raised nothing.

    Checks the sentinel too, because "no exception" alone is satisfied by a
    script that never compiled - see the note on ``_SENTINEL``.
    """
    if at.exception:
        detail = "\n".join(f"    {e.value}" for e in at.exception)
        raise AssertionError(f"{what} raised while rendering:\n{detail}")
    try:
        ran = at.session_state[_SENTINEL]
    except KeyError:
        ran = False
    assert ran is True, (
        f"{what}: the script never reached its end and raised no exception - "
        "that means it failed to COMPILE (indentation, encoding, syntax). "
        "Check the captured stderr for 'Script compilation error'.")


def style_bodies(at: AppTest) -> list[str]:
    """Every ``st.html`` payload emitted by the run."""
    return [el.proto.body for el in at.get("html")]


# ═══════════════════════════════════════════════════════════════════════════
# Guard on the guard
# ═══════════════════════════════════════════════════════════════════════════

def test_the_harness_actually_reports_a_failure():
    """If AppTest ever stopped surfacing exceptions, every test below would
    pass by rendering nothing at all. This is the canary."""
    at = render("raise RuntimeError('boom')")
    assert at.exception, "AppTest no longer reports script exceptions"
    assert "boom" in str(at.exception[0].value)


def test_the_harness_puts_the_repo_on_the_path():
    at = render("import core.cancellation as c\nst.write(len(c.IN_PROGRESS_STATUSES))")
    assert_clean(at, "importing an app module")


def test_a_script_that_fails_to_COMPILE_is_reported():
    """The hole that made five tests unfalsifiable.

    A compilation error is not a script exception: ``at.exception`` stays empty
    and the run produces nothing, so "assert no exception" passes for a body
    that never executed. ``assert_clean`` therefore also requires the sentinel.
    """
    at = render("if True:\nst.write('bad indent')")
    assert not at.exception, (
        "if AppTest starts reporting compile errors as exceptions, the sentinel "
        "check below is redundant - but leave it, it costs nothing")
    with pytest.raises(AssertionError, match="failed to COMPILE"):
        assert_clean(at, "a deliberately broken script")


def test_the_sentinel_is_absent_when_the_body_raises_partway():
    """A raise mid-body must not be mistaken for a compile failure - the
    exception branch has to win, with the real traceback in the message."""
    at = render("st.write('before')\nraise ValueError('mid-body')")
    with pytest.raises(AssertionError, match="mid-body"):
        assert_clean(at, "a script that raises")


# ═══════════════════════════════════════════════════════════════════════════
# The course list
# ═══════════════════════════════════════════════════════════════════════════

def test_the_multi_select_course_list_renders():
    at = render(COURSES + """
    from ui.course_selector import render_course_list
    st.session_state['selected_course_ids'] = [101]
    st.session_state['_out'] = render_course_list(courses, "dl", multi_select=True)
    """)
    assert_clean(at, "render_course_list(multi)")
    assert len(at.checkbox) == 2, "one checkbox per course"
    assert at.session_state['_out'] == [101]


def test_the_single_select_course_list_renders():
    at = render(COURSES + """
    from ui.course_selector import render_course_list
    render_course_list(courses, "hub", multi_select=False)
    """)
    assert_clean(at, "render_course_list(single)")


def test_an_empty_course_list_renders_its_notice():
    """The empty state is a real screen, and it routes through amber_notice -
    a module with no other coverage."""
    at = render("""
    from ui.course_selector import render_course_list
    st.session_state['_out'] = render_course_list([], "dl", multi_select=True)
    """)
    assert_clean(at, "render_course_list([])")
    assert at.session_state['_out'] == []
    assert not at.checkbox


def test_an_empty_single_select_list_renders():
    at = render("""
    from ui.course_selector import render_course_list
    render_course_list([], "hub", multi_select=False)
    """)
    assert_clean(at, "render_course_list([], single)")


@pytest.mark.parametrize("bad", [
    'SimpleNamespace(id=1, name=None, course_code=None, friendly_name=None)',
    'SimpleNamespace(id=2, name="", course_code="", friendly_name=None)',
    'SimpleNamespace(id=3, name="Only a name")',          # no course_code at all
    'SimpleNamespace(id=4, name="X", course_code="()", friendly_name=None)',
    'SimpleNamespace(id=5, name="X", course_code="(Name)", friendly_name="Nick")',
])
def test_an_incomplete_course_object_still_renders(bad):
    """Canvas returns partial objects, and the module's own docstrings promise
    ``getattr`` guards throughout. A raise here blanks the whole selector."""
    at = render(f"""
    from ui.course_selector import render_course_list
    render_course_list([{bad}], "dl", multi_select=True)
    """)
    assert_clean(at, f"render_course_list([{bad}])")


def test_the_list_sorts_alphabetically_by_default():
    at = render("""
    from ui.course_selector import render_course_list
    courses = [SimpleNamespace(id=1, name="Zebra", course_code="Z", friendly_name=None),
               SimpleNamespace(id=2, name="Alpha", course_code="A", friendly_name=None)]
    render_course_list(courses, "dl", multi_select=True)
    """)
    assert_clean(at, "sorted course list")
    assert [c.label for c in at.checkbox] == ["Alpha", "Zebra"]


def test_sort_false_preserves_the_relevance_order():
    """Search results arrive pre-ranked; re-sorting them alphabetically would
    throw the ranking away."""
    at = render("""
    from ui.course_selector import render_course_list
    courses = [SimpleNamespace(id=1, name="Zebra", course_code="Z", friendly_name=None),
               SimpleNamespace(id=2, name="Alpha", course_code="A", friendly_name=None)]
    render_course_list(courses, "dl", multi_select=True, sort=False)
    """)
    assert_clean(at, "unsorted course list")
    assert [c.label for c in at.checkbox] == ["Zebra", "Alpha"]


# ═══════════════════════════════════════════════════════════════════════════
# The style-breakout defect, end to end
# ═══════════════════════════════════════════════════════════════════════════

def test_a_course_code_cannot_terminate_the_injected_style_element():
    """The real defect, asserted against the bytes actually emitted.

    The course list interpolates the Canvas course code into
    ``st.html(f'<style>…</style>')``. A code containing ``</style>`` used to
    close the element early - the HTML parser scans a style element's raw text
    for that literal - which silently kills every rule after it AND drops the
    remainder into the document as markup.

    The unit test for the escape lives in test_course_selector.py; this one
    proves the escape is actually WIRED UP on the path that renders.
    """
    at = render("""
    from ui.course_selector import render_course_list
    evil = SimpleNamespace(id=1, name="Nasty",
                           course_code="AB</style><script>alert(1)</script>",
                           friendly_name=None)
    render_course_list([evil], "dl", multi_select=True)
    """)
    assert_clean(at, "render_course_list with a hostile course code")

    for body in style_bodies(at):
        if not body.startswith("<style>"):
            continue
        inner = body[len("<style>"):]
        assert "</style" not in inner[:-len("</style>")].lower(), (
            "a course code closed the style element early:\n" + body[:400])
        assert "<script" not in inner.lower(), (
            "markup from a course code reached the document:\n" + body[:400])


def test_a_hostile_course_code_is_still_displayed():
    """The escape must neutralise, not delete - the user still needs to see
    their course code, whatever is in it."""
    at = render("""
    from ui.course_selector import render_course_list
    evil = SimpleNamespace(id=1, name="Nasty", course_code="AB</style>CD",
                           friendly_name=None)
    render_course_list([evil], "dl", multi_select=True)
    """)
    assert_clean(at, "hostile course code")
    joined = "".join(style_bodies(at))
    assert "00003c" in joined, "the '<' should be unicode-escaped, not stripped"


# ═══════════════════════════════════════════════════════════════════════════
# The rest of the selector chrome
# ═══════════════════════════════════════════════════════════════════════════

def test_the_search_field_renders_and_returns_a_string():
    at = render("""
    from ui.course_selector import render_course_search
    st.session_state['_q'] = render_course_search("course_search")
    """)
    assert_clean(at, "render_course_search")
    assert isinstance(at.session_state['_q'], str)


def test_the_search_field_renders_inside_a_dialog_too():
    at = render("""
    from ui.course_selector import render_course_search
    render_course_search("hub_search", in_dialog=True)
    """)
    assert_clean(at, "render_course_search(in_dialog=True)")


def test_the_favorites_pill_renders():
    at = render("""
    from ui.course_selector import render_favorites_pill
    st.session_state['_fav'] = render_favorites_pill("dl")
    """)
    assert_clean(at, "render_favorites_pill")
    assert isinstance(at.session_state['_fav'], bool)


def test_the_cbs_filters_render():
    at = render(COURSES + """
    from ui.course_selector import render_cbs_filters
    st.session_state['_f'] = render_cbs_filters(courses, "dl")
    """)
    assert_clean(at, "render_cbs_filters")
    assert isinstance(at.session_state['_f'], list)


def test_the_cbs_filters_survive_an_empty_course_list():
    at = render("""
    from ui.course_selector import render_cbs_filters
    st.session_state['_f'] = render_cbs_filters([], "dl")
    """)
    assert_clean(at, "render_cbs_filters([])")


def test_the_selector_css_injection_renders():
    at = render("""
    from ui.course_selector import inject_course_selector_css
    inject_course_selector_css()
    """)
    assert_clean(at, "inject_course_selector_css")


# ═══════════════════════════════════════════════════════════════════════════
# The step tracker - the FIRST element on six screens
# ═══════════════════════════════════════════════════════════════════════════

def _steps(name):
    from shared import helpers
    return [s[0] for s in getattr(helpers, name)]


@pytest.mark.parametrize("step", _steps("DOWNLOAD_WIZARD_STEPS"))
def test_the_download_tracker_renders_at_every_step(step):
    at = render(f"""
    from shared.helpers import render_download_wizard
    render_download_wizard(st.container(), {step!r})
    """)
    assert_clean(at, f"render_download_wizard({step!r})")
    assert at.button, "the tracker renders as native buttons"


@pytest.mark.parametrize("step", _steps("SYNC_WIZARD_STEPS"))
@pytest.mark.parametrize("quick", [None, True, False], ids=["unset", "quick", "review"])
def test_the_sync_tracker_renders_at_every_step_in_both_modes(step, quick):
    """Quick Sync SKIPS the review step rather than removing it, so both modes
    must render the same skeleton - CLAUDE.md notes the equal child count is
    load-bearing for Streamlit's index-based reconciliation."""
    at = render(f"""
    from shared.helpers import render_sync_wizard
    render_sync_wizard(st.container(), {step!r}, quick={quick!r})
    """)
    assert_clean(at, f"render_sync_wizard({step!r}, quick={quick!r})")


def test_both_trackers_render_the_same_number_of_steps_in_either_mode():
    at = render("""
    from shared.helpers import render_sync_wizard
    render_sync_wizard(st.container(), 'sync', quick=True)
    st.session_state['_quick'] = 1
    """)
    assert_clean(at, "quick sync tracker")
    quick_buttons = len(at.button)

    at2 = render("""
    from shared.helpers import render_sync_wizard
    render_sync_wizard(st.container(), 'sync', quick=False)
    """)
    assert_clean(at2, "review sync tracker")
    assert len(at2.button) == quick_buttons, (
        "Quick Sync and review mode render a different number of tracker "
        "steps - the skeleton must match or Streamlit reconciles them wrongly")


def test_an_unknown_step_id_does_not_crash_the_tracker():
    """It is the first element on the page; a raise here means a blank screen
    rather than a slightly wrong highlight."""
    at = render("""
    from shared.helpers import render_download_wizard
    render_download_wizard(st.container(), 'not_a_real_step')
    """)
    assert_clean(at, "render_download_wizard('not_a_real_step')")


# ═══════════════════════════════════════════════════════════════════════════
# The run dashboard
# ═══════════════════════════════════════════════════════════════════════════

# Indented to match the bodies it is concatenated with - see _script().
_PLACEHOLDERS = """
    from engine.progress_dashboard import DashboardPlaceholders
    ph = DashboardPlaceholders(header=st.empty(), progress=st.empty(),
                               metrics=st.empty(), active_file=st.empty(),
                               log=st.empty())
"""


def test_the_full_run_dashboard_renders():
    at = render(_PLACEHOLDERS + """
    from engine.progress_dashboard import render_full_dashboard
    from engine.estimation import transfer_estimator
    render_full_dashboard(
        ph, deque(["line one", "line two"]),
        header_label="Downloading", course_name="Regnskab",
        current_files=3, total_files=10,
        downloaded_bytes=1024.0, total_bytes=4096.0,
        estimator=transfer_estimator())
    """)
    assert_clean(at, "render_full_dashboard")


def test_the_analysis_dashboard_renders():
    """It renders from three call sites and previously drew its own chrome
    with no metrics at all."""
    at = render(_PLACEHOLDERS + """
    from engine.progress_dashboard import render_analysis_dashboard
    render_analysis_dashboard(ph, course_label="Analyzing",
                              course_name="Regnskab",
                              status_text="Scanning modules", percent=42)
    """)
    assert_clean(at, "render_analysis_dashboard")


def test_the_analysis_dashboard_renders_indeterminate():
    at = render(_PLACEHOLDERS + """
    from engine.progress_dashboard import render_analysis_dashboard
    render_analysis_dashboard(ph, course_label="Analyzing", course_name="X",
                              status_text="Connecting", indeterminate=True)
    """)
    assert_clean(at, "render_analysis_dashboard(indeterminate)")


def test_the_dashboard_survives_a_course_name_containing_markup():
    at = render(_PLACEHOLDERS + """
    from engine.progress_dashboard import render_progress_header
    render_progress_header(ph, "Downloading", "<script>alert(1)</script>")
    """)
    assert_clean(at, "render_progress_header with markup")


def test_an_empty_terminal_log_renders():
    at = render(_PLACEHOLDERS + """
    from engine.progress_dashboard import render_terminal_log
    render_terminal_log(ph, deque())
    """)
    assert_clean(at, "render_terminal_log(empty)")


# ═══════════════════════════════════════════════════════════════════════════
# Notices and shared components
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("fn", ["render_amber_notice", "render_info_notice",
                                "render_success_notice", "render_error_notice"])
def test_every_notice_kind_renders(fn):
    at = render(f"""
    from ui.amber_notice import {fn}
    {fn}("Something the user needs to know.")
    """)
    assert_clean(at, fn)


@pytest.mark.parametrize("fn", ["render_amber_notice", "render_info_notice",
                                "render_success_notice", "render_error_notice"])
def test_a_notice_escapes_markup_in_its_message(fn):
    """Notices carry Canvas error text, which is not app copy."""
    at = render(f"""
    from ui.amber_notice import {fn}
    {fn}("<img src=x onerror=alert(1)>")
    """)
    assert_clean(at, f"{fn} with markup")


def test_the_help_card_renders():
    at = render("""
    from shared.components import render_help_card
    render_help_card("smoke", "What this does", "<p>Some explanation.</p>")
    """)
    assert_clean(at, "render_help_card")


@pytest.mark.parametrize("mode,errors", [
    ("download", 0), ("download", 2), ("sync", 0), ("sync", 3)])
def test_the_completion_card_renders(mode, errors):
    """The completion screens are the most reconciliation-fragile surface in
    the app (a card inheriting the run dashboard's children). This only proves
    it executes - but it executes on four different shapes."""
    at = render(f"""
    from shared.components import render_completion_card
    render_completion_card(synced_count=7, error_count={errors},
                           total_bytes=12345678, mode={mode!r}, courses_count=2)
    """)
    assert_clean(at, f"render_completion_card({mode}, {errors} errors)")


def test_the_completion_card_renders_with_nothing_downloaded():
    """A run where every file was already up to date - the zero case that the
    metric builders explicitly refuse to render as '0 / 0'."""
    at = render("""
    from shared.components import render_completion_card
    render_completion_card(synced_count=0, error_count=0, total_bytes=0,
                           mode="sync", courses_count=1)
    """)
    assert_clean(at, "render_completion_card(empty run)")


def test_the_cancelled_card_renders():
    at = render("""
    from shared.components import render_cancelled_card
    render_cancelled_card("Download", 4, 10)
    """)
    assert_clean(at, "render_cancelled_card")


def test_the_panopto_summary_renders_and_tolerates_none():
    at = render("""
    from shared.components import render_panopto_summary
    render_panopto_summary(None)
    render_panopto_summary({'downloaded': 2, 'transcribed': 1, 'failed': 0})
    """)
    assert_clean(at, "render_panopto_summary")


def test_the_error_section_renders():
    at = render("""
    from shared.components import render_error_section
    render_error_section([
        {'course': 'Regnskab', 'file': 'notes.pdf', 'error': 'Locked File'},
        {'course': 'IS', 'file': 'x.docx', 'error': '<b>markup</b> in an error'},
    ])
    """)
    assert_clean(at, "render_error_section")


def test_an_empty_error_section_renders():
    at = render("""
    from shared.components import render_error_section
    render_error_section([])
    """)
    assert_clean(at, "render_error_section([])")


def test_the_config_summary_badges_build():
    at = render("""
    from shared.components import render_config_summary_badges
    st.session_state['_html'] = render_config_summary_badges(
        {'download_path': r'C:\\Courses', 'organize_by_module': True}, show_path=True)
    """)
    assert_clean(at, "render_config_summary_badges")
    assert isinstance(at.session_state['_html'], str)
