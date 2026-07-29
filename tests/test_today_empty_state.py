"""Today's files panel must never claim the day is settled when it is not.

Three distinct empty states, and the middle one did not exist:

    no courses in the daily set   "Nothing here yet"      + how to add some
    courses listed, one broken    "No new files today"    + N needs attention
    courses listed, all healthy   "No new files today"    + "You're all caught up."

An unreachable course (its folder renamed or moved) is deliberately SKIPPED by
the daily sync and gets no card or file list of its own - that is the documented
contract and it is right. But it must not let the page assert "You're all caught
up", which is the one state where the panel hides something and says the
opposite: measured on a renamed folder, 15 of that course's arrivals were
invisible with only an amber chip to hint at it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SRC = (REPO / "ui" / "today_dashboard.py").read_text(encoding="utf-8")


def empty_state(has_courses: bool, unreachable: int) -> tuple[str, str]:
    """The branch under test, mirrored from _render_today_files."""
    if has_courses and unreachable:
        n = unreachable
        return ("No new files today",
                f"{n} course{'s' if n != 1 else ''} above "
                f"need{'' if n != 1 else 's'} attention, so "
                f"{'they were' if n != 1 else 'it was'} skipped.")
    if has_courses:
        return ("No new files today", "You're all caught up.")
    return ("Nothing here yet",
            "Add courses to your daily sync above and today's "
            "downloads for them show up here.")


# --------------------------------------------------------------------------
# the three states
# --------------------------------------------------------------------------

def test_a_healthy_list_with_nothing_new_is_still_all_caught_up():
    assert empty_state(True, 0) == ("No new files today", "You're all caught up.")


def test_a_broken_course_replaces_the_caught_up_claim():
    """The regression."""
    title, sub = empty_state(True, 1)
    assert title == "No new files today"
    assert "caught up" not in sub
    assert "needs attention" in sub and "skipped" in sub


def test_an_empty_daily_set_explains_what_to_do_instead():
    title, sub = empty_state(False, 0)
    assert title == "Nothing here yet"
    assert "Add courses" in sub
    assert "caught up" not in sub, \
        "with nothing in scope the app has not checked anything"


# --------------------------------------------------------------------------
# it reads correctly at every count
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n,expect", [
    (1, "1 course above needs attention, so it was skipped."),
    (2, "2 courses above need attention, so they were skipped."),
    (7, "7 courses above need attention, so they were skipped."),
])
def test_singular_and_plural(n, expect):
    assert empty_state(True, n)[1] == expect


def test_it_points_at_where_the_courses_are():
    """The chips are directly above; "above" is what makes it actionable."""
    assert "above" in empty_state(True, 1)[1]


# --------------------------------------------------------------------------
# the implementation still carries the rule
# --------------------------------------------------------------------------

def test_the_unreachable_branch_comes_before_the_caught_up_branch():
    # Anchored on the empty-state block itself: "if not groups:" also appears
    # in the Add-courses dialog earlier in the file.
    i0 = SRC.find("_empty_icon, _empty_title, _empty_sub")
    assert i0 > 0, "the empty-state block moved"
    body = re.sub(r"^\s*#.*$", "", SRC[i0 - 1200:i0 + 1600], flags=re.M)
    i_unreach = body.find("unreachable_pairs")
    i_caught = body.find("You're all caught up.")
    assert 0 < i_unreach < i_caught, (
        "the caught-up branch is reached first again, so a broken course is "
        "reported as a settled day")


def test_the_guard_uses_the_same_list_the_chips_do():
    """A second source of truth for "which courses are broken" is how the chip
    and the message would drift apart."""
    i0 = SRC.find("_empty_icon, _empty_title, _empty_sub")
    body = SRC[i0 - 1200:i0 + 1600]
    assert "unreachable_pairs" in body
    assert "_split_daily_pairs" in SRC, "the split that produces it moved"
