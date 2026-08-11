"""Quick Sync's "here is what I left alone" panel: INFO, and only what is actionable.

Reported by the product owner on the real completion screen, macOS 26.6,
2026-08-11, against a live seeded Quick Sync. The panel read:

    ⚠️ Quick Sync skipped 2 files you edited locally and 4 files deleted
       locally and 2 files deleted on Canvas.
       To download them, run a normal 'Analyze, Review & Sync' and select
       them manually.

Two things wrong with it, and neither is a bug in the sync:

1. **It was AMBER.** Declining a locally-edited or locally-deleted file is the
   documented difference between Quick Sync and Analyze/Review/Sync - it is
   stated up front, and it is why anyone chooses Quick Sync. So the run did
   exactly what was asked, and "⚠️" said something had gone wrong. The
   ignored-files panel sits directly BELOW this one and had already been moved
   to info for word-for-word the same reason ("files are only in this state
   because the user deliberately put them there"). Two panels, one rule.

2. **It listed files deleted on Canvas**, which the user cannot act on from
   this screen. The detail line offers to fetch the skipped files; a file
   deleted on Canvas is not there to fetch. The review screen already reports
   it, where it is information about the course rather than an item on a
   to-do list. So it is counted and never listed - and a run whose ONLY skip
   was `canvas_del` must render no panel at all rather than an empty one.

The sentence is a pure function because the app and
`scripts/completion_gallery.py` - the review instrument for these screens -
both render this panel and had two copies of it. That is exactly how the
`filtered` clause came to survive in the gallery after the app dropped it,
leaving the gallery describing a screen that no longer existed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from sync.completion import (  # noqa: E402
    QUICK_SYNC_SKIP_DETAIL,
    build_quick_sync_skip_notice,
)

COMPLETION_SRC = (REPO / "sync" / "completion.py").read_text(encoding="utf-8")
GALLERY_SRC = (REPO / "scripts" / "completion_gallery.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# what the sentence says
# --------------------------------------------------------------------------

def test_the_reported_screen_loses_only_its_canvas_clause():
    """The exact tallies from the reported run."""
    msg = build_quick_sync_skip_notice(
        {"edited": 2, "local_del": 4, "canvas_del": 2})
    assert msg == ("Quick Sync skipped 2 files you edited locally and "
                   "4 files deleted locally.")
    assert "Canvas" not in msg


def test_a_canvas_only_skip_renders_NOTHING():
    """The branch this change makes reachable. An empty panel is worse than
    no panel, and there is nothing here the user can do."""
    assert build_quick_sync_skip_notice({"canvas_del": 3}) is None


@pytest.mark.parametrize("skipped", [None, {}, {"canvas_del": 0}])
def test_nothing_to_report_renders_nothing(skipped):
    assert build_quick_sync_skip_notice(skipped) is None


def test_every_clause_that_IS_actionable_still_appears():
    msg = build_quick_sync_skip_notice(
        {"edited": 2, "local_del": 1, "panopto_local_del": 1})
    assert "2 files you edited locally" in msg
    assert "1 file deleted locally" in msg
    assert "1 Panopto recording deleted locally" in msg


@pytest.mark.parametrize("n,expect", [(1, "1 file you edited locally"),
                                      (2, "2 files you edited locally")])
def test_the_count_agrees_with_its_noun(n, expect):
    assert expect in build_quick_sync_skip_notice({"edited": n})


@pytest.mark.parametrize("n,expect", [(1, "1 Panopto recording deleted"),
                                      (3, "3 Panopto recordings deleted")])
def test_recordings_pluralise_too(n, expect):
    assert expect in build_quick_sync_skip_notice({"panopto_local_del": n})


def test_the_filtered_tally_is_gone_and_must_stay_gone():
    """It told the user to widen a folder past the shape they configured, and
    `analyze_course` now declines to make that possible. It is a standing
    property of the folder, not something that happened on this run."""
    msg = build_quick_sync_skip_notice({"edited": 1, "filtered": 5})
    assert "filter" not in msg
    assert msg == "Quick Sync skipped 1 file you edited locally."


# --------------------------------------------------------------------------
# it renders inside a terminal screen, so it may not raise
# --------------------------------------------------------------------------

@pytest.mark.parametrize("skipped", [
    {"edited": "two"},                       # a string
    {"edited": None, "local_del": None},     # present-and-null
    {"edited": float("nan")},                # a counter that went wrong
    {"edited": -3},                          # a negative count
    {"local_del": [1, 2]},                   # not a number at all
])
def test_a_bad_counter_costs_the_sentence_never_the_screen(skipped):
    """These tallies are summed from several subsystems (`sync/analysis.py`
    walks per-pair results), and this panel renders inside the completion
    card. A cell that raises takes the terminal screen with it - the rule
    `engine/progress_dashboard.py` already states for its own cells."""
    assert build_quick_sync_skip_notice(skipped) is None


def test_a_negative_count_is_not_reported_as_text():
    """`-3 files` is not a thing that can be skipped."""
    msg = build_quick_sync_skip_notice({"edited": -3, "local_del": 2})
    assert msg == "Quick Sync skipped 2 files deleted locally."


# --------------------------------------------------------------------------
# how it is rendered
# --------------------------------------------------------------------------

def _call_names_near(src: str, anchor: str, window: int = 900) -> str:
    i = src.index(anchor)
    return src[i:i + window]


def test_the_panel_is_INFO_not_amber():
    """The whole point of the report. `render_amber_notice` must not be what
    draws this one."""
    region = _call_names_near(COMPLETION_SRC, "_qs_message = build_quick_sync_skip_notice")
    assert "render_info_notice" in region
    assert "render_amber_notice" not in region.split("render_pp_warning")[0]


def test_the_detail_line_lives_beside_the_sentence_it_belongs_to():
    assert "Analyze, Review & Sync" in QUICK_SYNC_SKIP_DETAIL
    assert "QUICK_SYNC_SKIP_DETAIL" in COMPLETION_SRC


def test_the_tally_is_cleared_even_when_no_panel_is_drawn():
    """A run whose only skip was `canvas_del` renders nothing. If the cleanup
    sat inside the render branch - where it used to - that tally would be
    carried into the NEXT run's completion screen.

    Asserted through the AST: the pop must not be nested inside an `if`.
    """
    tree = ast.parse(COMPLETION_SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "show_sync_complete")

    def _pops_under_an_if(node, guarded: bool) -> list[bool]:
        out = []
        for child in ast.iter_child_nodes(node):
            inner = guarded or isinstance(node, ast.If)
            seg = ast.get_source_segment(COMPLETION_SRC, child) or ""
            if isinstance(child, ast.Expr) and "'qs_skipped'" in seg and ".pop(" in seg:
                out.append(guarded)
            out += _pops_under_an_if(child, inner)
        return out

    found = _pops_under_an_if(fn, False)
    assert found, "show_sync_complete must still clear qs_skipped"
    assert not any(found), (
        "the qs_skipped cleanup must not be nested inside a conditional - a "
        "canvas_del-only run draws no panel and would leak its tally")


# --------------------------------------------------------------------------
# ONE definition, two callers
# --------------------------------------------------------------------------

def test_the_gallery_renders_the_APPS_sentence_not_a_copy():
    """`scripts/completion_gallery.py` is the review instrument for these
    screens. It kept its own copy of this sentence, which is how it went on
    advertising a `filtered` clause the app had already removed."""
    assert "build_quick_sync_skip_notice" in GALLERY_SRC
    assert "QUICK_SYNC_SKIP_DETAIL" in GALLERY_SRC
    assert "Quick Sync skipped {" not in GALLERY_SRC, (
        "the gallery must not rebuild the sentence itself")


def test_the_gallery_covers_the_case_that_renders_nothing():
    """A branch with no gallery variant is a branch nobody ever looks at."""
    assert "s-qs-canvas-del-only" in GALLERY_SRC


def test_the_gallery_checklist_no_longer_calls_it_a_warning():
    cap = (REPO / "scripts" / "capture_completion_gallery.py").read_text(encoding="utf-8")
    assert "qs-warn" not in cap, "the id outlived the amber panel it named"
    assert "qs-info" in cap
