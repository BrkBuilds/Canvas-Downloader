"""Tests for ``ui.course_selector`` - search ranking, selection reconciliation
and the CSS-content escape.

Why this file exists
--------------------
At ~2,250 lines this is the largest module in the app and it had no test at
all, while carrying more hard-won fixes than anything else in CLAUDE.md (the
``st.empty()`` unmount, the shift-select bridge, ``blur()``-when-unfocused, the
fragment-scoped ``disabled=`` trap, the stale-fade override). It also decides
**which courses get downloaded**, so a reconciliation bug does not crash - it
quietly downloads the wrong set.

What is covered here is the part that is pure: scoring, ranking, and the three
functions that own selection state. The rendering itself is covered by the
render-smoke tests.

The reconciliation rule is ONE function on purpose
--------------------------------------------------
``resolve_multi_selection`` is called twice per run - once by the toolbar,
which has to print the post-click count while sitting ABOVE the list, and once
by the list as it renders. CLAUDE.md is explicit that duplicating the rule
instead of sharing it is how the label and the list drift apart, so there is a
test below asserting the list still calls it rather than reimplementing it.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.helpers import css_content_safe
from ui import course_selector as cs

REPO = Path(__file__).resolve().parents[1]


# ── helpers ──────────────────────────────────────────────────────────────────

def course(cid, name, code="", friendly=None):
    return SimpleNamespace(id=cid, name=name, course_code=code,
                           friendly_name=friendly)


@pytest.fixture()
def state(monkeypatch):
    """Stub ``st`` inside the module; session_state is a plain dict."""
    stub = SimpleNamespace(session_state={})
    monkeypatch.setattr(cs, "st", stub)
    return stub.session_state


# ═══════════════════════════════════════════════════════════════════════════
# Fuzzy subsequence
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("needle,haystack,expected", [
    ("infosys", "introduction to information systems", True),
    ("abc", "aXbXc", True),
    ("abc", "cba", False),          # order matters
    ("", "anything", True),         # vacuously true
    ("aa", "a", False),             # each char consumes one position
    ("aa", "aa", True),
    ("xyz", "", False),
])
def test_subsequence_matching(needle, haystack, expected):
    assert cs._is_subsequence(needle, haystack) is expected


def test_subsequence_consumes_the_iterator_so_matches_cannot_overlap():
    """``all(ch in it for ch in needle)`` advances a single iterator. If it were
    rewritten as ``all(ch in haystack ...)`` this would wrongly pass, and the
    fuzzy fallback would match nearly everything."""
    assert cs._is_subsequence("aab", "ab") is False


# ═══════════════════════════════════════════════════════════════════════════
# Token scoring - the ranking ladder
# ═══════════════════════════════════════════════════════════════════════════

def test_the_score_ladder_is_strictly_ordered():
    """The ladder IS the ranking. Two rungs scoring the same makes the order
    fall through to the alphabetical tie-break, which reads as random."""
    name_prefix = cs._token_score("intro", "introduction to x", "")
    word_prefix = cs._token_score("sys", "information systems", "")
    name_sub = cs._token_score("form", "information systems", "")
    code_prefix = cs._token_score("binto", "unrelated", "binto1060u")
    code_sub = cs._token_score("1060", "unrelated", "binto1060u")
    fuzzy = cs._token_score("ifs", "information systems", "")

    ladder = [name_prefix, word_prefix, name_sub, code_prefix, code_sub, fuzzy]
    assert ladder == sorted(ladder, reverse=True), \
        f"ranking rungs are out of order: {ladder}"
    assert len(set(ladder)) == len(ladder), "two rungs score the same"


def test_a_non_match_scores_zero():
    assert cs._token_score("zzz", "information systems", "binto") == 0


def test_the_fuzzy_rung_fires_for_a_two_character_token():
    """``ifs`` -> "information systems" is the abbreviation case the fuzzy
    fallback exists for: not a prefix, not a word start, not a substring."""
    assert cs._token_score("ifs", "information systems", "") == 12
    assert cs._token_score("is", "information systems", "") == 12


def test_a_single_character_is_decided_before_the_fuzzy_rung():
    """Pins the real behaviour, which is not what the ``len(tok) >= 2`` guard
    appears to promise.

    For a one-character token, subsequence matching and substring matching are
    the same question - so if the character is present, the substring rung at
    50 has already returned, and if it is absent the subsequence is false too.
    The guard therefore cannot change any outcome for length 1; it is
    belt-and-braces, not the thing keeping a single keystroke from listing
    every course. That job is done by the substring rung returning a real
    score rather than the fuzzy one.
    """
    # present -> substring rung, well above the fuzzy score
    assert cs._token_score("q", "quantitative methods", "") == 100  # also a prefix
    assert cs._token_score("v", "quantitative methods", "") == 50   # substring
    # absent -> no rung matches
    assert cs._token_score("z", "quantitative methods", "") == 0


def test_word_start_matching_uses_the_separator_set():
    """Course names use hyphens, slashes, dots and ampersands as word breaks,
    so a token must be able to match the start of any segment."""
    for name in ["data-science methods", "data/science", "data.science",
                 "data (science)", "data & science", "data_science"]:
        assert cs._token_score("science", name, "") >= 80, \
            f"'science' should match a word start in {name!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Whole-query scoring
# ═══════════════════════════════════════════════════════════════════════════

def test_an_empty_query_matches_everything():
    assert cs._course_match_score("", "anything", "x") == 1
    assert cs._course_match_score("   ", "anything", "x") == 1


def test_every_token_must_match_something():
    """AND semantics. With OR, adding a word would ever-widen the result set,
    which is the opposite of what typing more means."""
    assert cs._course_match_score("intro info", "Introduction to Information Systems", "") > 0
    assert cs._course_match_score("intro zzzz", "Introduction to Information Systems", "") == 0


def test_a_contiguous_whole_query_hit_outranks_scattered_tokens():
    scattered = cs._course_match_score(
        "intro systems", "Introduction to Information Systems", "")
    contiguous = cs._course_match_score(
        "introduction to information", "Introduction to Information Systems", "")
    assert contiguous > scattered


def test_matching_is_case_insensitive():
    assert cs._course_match_score("INTRO", "introduction", "") == \
           cs._course_match_score("intro", "INTRODUCTION", "")


def test_a_course_can_be_found_by_its_code_alone():
    assert cs._course_match_score("binto1060", "Regnskab", "BINTO1060U.LA_E25") > 0


# ═══════════════════════════════════════════════════════════════════════════
# Filtering and ranking
# ═══════════════════════════════════════════════════════════════════════════

def test_an_empty_query_returns_everything_unchanged():
    """The caller applies its own alphabetical sort, so reordering here would
    fight it."""
    courses = [course(1, "Zebra"), course(2, "Alpha")]
    assert cs._filter_and_rank_courses(courses, "") == courses
    assert cs._filter_and_rank_courses(courses, "   ") == courses


def test_non_matching_courses_are_dropped():
    courses = [course(1, "Regnskab"), course(2, "Statistics")]
    out = cs._filter_and_rank_courses(courses, "stat")
    assert [c.id for c in out] == [2]


def test_the_best_match_comes_first():
    courses = [
        course(1, "Advanced Information Retrieval"),   # word-start
        course(2, "Information Systems"),              # full-name prefix
        course(3, "Misinformation Studies"),           # substring only
    ]
    out = cs._filter_and_rank_courses(courses, "information")
    assert out[0].id == 2, "the full-name prefix must rank first"
    assert [c.id for c in out] == [2, 1, 3]


def test_equal_scores_break_alphabetically_not_by_input_order():
    """Otherwise the list reshuffles between reruns for no visible reason."""
    courses = [course(1, "Statistics B"), course(2, "Statistics A")]
    out = cs._filter_and_rank_courses(courses, "statistics")
    assert [c.name for c in out] == ["Statistics A", "Statistics B"]


def test_ranking_survives_a_course_with_no_name_or_code():
    """Canvas returns incomplete course objects; ranking must not raise."""
    courses = [course(1, ""), course(2, None), SimpleNamespace(id=3)]
    assert cs._filter_and_rank_courses(courses, "x") == []
    assert len(cs._filter_and_rank_courses(courses, "")) == 3


def test_query_matches_any_agrees_with_the_filter():
    """The empty-state notice is driven by this; disagreeing with the filter
    means showing 'no results' above a populated list, or the reverse."""
    courses = [course(1, "Regnskab"), course(2, "Statistics")]
    for q in ["stat", "zzz", "", "regn", "statistics extra"]:
        assert cs._query_matches_any(q, courses) == \
               bool(cs._filter_and_rank_courses(courses, q))


def test_query_matches_any_on_an_empty_course_list():
    assert cs._query_matches_any("", []) is False
    assert cs._query_matches_any("x", []) is False


# ═══════════════════════════════════════════════════════════════════════════
# resolve_multi_selection - the reconciliation rule
# ═══════════════════════════════════════════════════════════════════════════

def test_a_ticked_checkbox_is_selected(state):
    state['selected_course_ids'] = []
    state['dl_chk_1'] = True
    assert cs.resolve_multi_selection([course(1, "A")], "dl") == [1]


def test_an_unticked_checkbox_is_not_selected(state):
    state['selected_course_ids'] = [1]
    state['dl_chk_1'] = False
    assert cs.resolve_multi_selection([course(1, "A")], "dl") == []


def test_a_course_with_no_checkbox_yet_falls_back_to_the_saved_selection(state):
    """First render: the widget key does not exist, so the stored selection is
    what the checkbox's ``value=`` will use. Reading it any other way makes the
    toolbar count disagree with the list on the very first paint."""
    state['selected_course_ids'] = [1]
    assert cs.resolve_multi_selection([course(1, "A")], "dl") == [1]
    state['selected_course_ids'] = []
    assert cs.resolve_multi_selection([course(1, "A")], "dl") == []


def test_off_screen_selections_are_preserved(state):
    """THE property. A course hidden by the search box or the CBS filters is
    still selected - otherwise typing in the search field silently deselects
    everything you had picked."""
    state['selected_course_ids'] = [1, 2, 3]
    visible = [course(2, "B")]
    state['dl_chk_2'] = True
    assert sorted(cs.resolve_multi_selection(visible, "dl")) == [1, 2, 3]


def test_deselecting_a_visible_course_keeps_the_hidden_ones(state):
    state['selected_course_ids'] = [1, 2]
    state['dl_chk_2'] = False
    assert cs.resolve_multi_selection([course(2, "B")], "dl") == [1]


def test_the_namespace_scopes_the_checkbox_keys(state):
    """Download and the sync dialogs render lists side by side in one session.
    Ignoring the namespace would let one list's ticks drive the other."""
    state['selected_course_ids'] = []
    state['dl_chk_1'] = True
    state['hub_chk_1'] = False
    assert cs.resolve_multi_selection([course(1, "A")], "hub") == []
    assert cs.resolve_multi_selection([course(1, "A")], "dl") == [1]


def test_no_duplicates_when_a_course_is_both_saved_and_ticked(state):
    """``selected_course_ids`` feeds a count and a download loop; a duplicate
    would download the course twice and inflate the total."""
    state['selected_course_ids'] = [1]
    state['dl_chk_1'] = True
    assert cs.resolve_multi_selection([course(1, "A")], "dl") == [1]


def test_resolution_is_stable_when_called_twice(state):
    """The toolbar calls it, then the list calls it again in the same run. The
    second call must return exactly what the first did."""
    state['selected_course_ids'] = [5]
    courses = [course(1, "A"), course(2, "B")]
    state['dl_chk_1'] = True
    first = cs.resolve_multi_selection(courses, "dl")
    second = cs.resolve_multi_selection(courses, "dl")
    assert first == second


def test_resolution_with_nothing_in_state_at_all(state):
    assert cs.resolve_multi_selection([course(1, "A")], "dl") == []
    assert cs.resolve_multi_selection([], "dl") == []


def _calls_named(func, name: str) -> int:
    """How many times ``func``'s body really CALLS ``name``.

    Walks the AST rather than searching the text. A substring search passes on
    a mere mention: ``_render_multi_select_list`` carries a comment that names
    ``resolve_multi_selection()``, so deleting the actual call left a text
    search still matching - the brittle-anchor failure CLAUDE.md describes.
    """
    import ast
    import inspect
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name)
               and n.func.id == name)


def test_the_list_renderer_calls_the_shared_resolver(state):
    """Structural, and deliberately so: two copies of the rule would agree on
    the day they were written and drift later. CLAUDE.md names duplicating this
    rule as the failure to prevent.
    """
    assert _calls_named(cs._render_multi_select_list, "resolve_multi_selection") >= 1, (
        "_render_multi_select_list no longer calls resolve_multi_selection - "
        "the toolbar count and the list can now disagree")


def test_the_toolbar_count_uses_the_same_resolver(state):
    """The other caller. If the toolbar stops asking, it is back to either a
    stale count or the ``st.empty()`` placeholder that unmounted the label for
    ~76ms on every keystroke."""
    assert _calls_named(cs._course_list_section, "resolve_multi_selection") >= 1, (
        "the toolbar no longer resolves the selection up front")


# ═══════════════════════════════════════════════════════════════════════════
# Select All / Clear - the resurrection bug
# ═══════════════════════════════════════════════════════════════════════════

def test_select_all_adds_the_visible_courses(state):
    state['selected_course_ids'] = []
    cs._cs_select_all({1, 2})
    assert sorted(state['selected_course_ids']) == [1, 2]
    assert state['dl_chk_1'] is True and state['dl_chk_2'] is True


def test_select_all_keeps_selections_that_are_off_screen(state):
    """It is 'select everything I can see', not 'replace my selection'."""
    state['selected_course_ids'] = [9]
    cs._cs_select_all({1})
    assert sorted(state['selected_course_ids']) == [1, 9]


def test_select_all_is_idempotent(state):
    """Project rule: every ``on_click`` mutation must survive a double click."""
    state['selected_course_ids'] = []
    cs._cs_select_all({1, 2})
    cs._cs_select_all({1, 2})
    assert sorted(state['selected_course_ids']) == [1, 2]


def test_clear_resets_the_whole_universe_not_just_the_visible_view(state):
    """The resurrection bug, stated as a test.

    ``selected_course_ids`` is global but the checkbox keys are per course. If
    Clear only reset the visible ones, a course selected in the *other* view
    (a non-favourite picked under All Courses) would keep ``dl_chk=True``, and
    the reconciliation above would resurrect it as selected the moment the user
    switched back.
    """
    state['selected_course_ids'] = [1, 2]
    state['dl_chk_1'] = True
    state['dl_chk_2'] = True                 # this one is currently off-screen

    cs._cs_clear_selection([1, 2])           # the ENTIRE universe

    assert state['selected_course_ids'] == []
    assert state['dl_chk_1'] is False and state['dl_chk_2'] is False
    # And the reconciliation agrees, from either view.
    assert cs.resolve_multi_selection([course(1, "A")], "dl") == []
    assert cs.resolve_multi_selection([course(2, "B")], "dl") == []


def test_clearing_only_the_visible_view_would_resurrect(state):
    """Demonstrates the failure the test above prevents, so the reason the
    universe is passed in cannot be optimised away as redundant."""
    state['selected_course_ids'] = []
    state['dl_chk_2'] = True                 # left over from the other view
    assert cs.resolve_multi_selection([course(2, "B")], "dl") == [2], \
        "a stale checkbox key really does resurrect a selection"


def test_clear_is_idempotent(state):
    cs._cs_clear_selection([1, 2])
    cs._cs_clear_selection([1, 2])
    assert state['selected_course_ids'] == []


def test_refresh_only_raises_a_flag(state):
    """It must not fetch. The fetch happens in step 2 so the click stays cheap
    and the fragment can rerun without blocking on the network."""
    cs._cs_start_refresh()
    assert state['_dl_courses_refreshing'] is True
    assert len(state) == 1, f"the refresh click touched more than its flag: {state}"


# ═══════════════════════════════════════════════════════════════════════════
# CSS content escaping
# ═══════════════════════════════════════════════════════════════════════════

def test_a_style_breakout_in_a_course_code_is_neutralised():
    """The live defect this consolidation fixed.

    The course list interpolates a Canvas-supplied course code into
    ``st.html(f'<style>…</style>')``. The HTML parser scans a style element's
    raw text for the literal ``</style``, so a code containing one closed the
    element early and silently killed every rule after it - the failure mode
    CLAUDE.md documents. The Today page had already hardened its copy; the
    course list had not.
    """
    out = cs._css_escape_content('x</style><script>alert(1)</script>')
    assert '<' not in out, "a literal '<' can still terminate the style element"
    assert '</style' not in out.lower()
    assert '\\00003c ' in out


def test_the_escape_still_handles_quotes_and_backslashes():
    assert css_content_safe('a"b') == 'a\\"b'
    assert css_content_safe('a\\b') == 'a\\\\b'


def test_backslashes_are_escaped_before_anything_else():
    """Order matters: escaping the quote first would leave the backslash the
    second pass then doubles, turning ``\\"`` into a literal backslash plus an
    unescaped quote and closing the string."""
    assert css_content_safe('\\"') == '\\\\\\"'


def test_ordinary_course_codes_pass_through_untouched():
    """The escape must be invisible for the 99.99% case, or every course code
    in the list renders with stray escapes in it."""
    for code in ["BINTO1060U.LA_E25", "Regnskab (LA)", "MAT-101", "Økonomi & Ledelse"]:
        assert css_content_safe(code) == code


def test_the_escape_accepts_non_strings():
    assert css_content_safe(None) == "None"
    assert css_content_safe(42) == "42"


def test_there_is_only_one_definition_of_this_escape():
    """It existed as three copies - two weak, one hardened - and which one you
    got depended on the call site. Consolidated onto
    ``shared.helpers.css_content_safe``; the aliases must still point at it.
    """
    from ui import today_dashboard as td
    assert cs._css_escape_content is css_content_safe or \
        cs._css_escape_content("<") == css_content_safe("<")
    assert td._css_escape_content is css_content_safe
    assert td._css_content_safe is css_content_safe


def test_no_ui_module_hand_rolls_a_weaker_css_escape():
    """Catches the copy coming back. A local
    ``.replace('\\\\','\\\\\\\\').replace('"','\\\\"')`` that stops before ``<`` is
    exactly the shape that was wrong in two places.
    """
    offenders = []
    pattern = re.compile(r"""replace\(\s*['"]\\\\['"]""")
    for path in sorted((REPO / "ui").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        for m in pattern.finditer(src):
            line_no = src[:m.start()].count("\n") + 1
            line = src.splitlines()[line_no - 1]
            if "00003c" in src[m.start():m.start() + 400]:
                continue                      # part of the hardened chain
            offenders.append(f"{path.name}:{line_no}: {line.strip()}")
    assert not offenders, (
        "a hand-rolled CSS escape reappeared - use "
        "shared.helpers.css_content_safe:\n  " + "\n  ".join(offenders))
