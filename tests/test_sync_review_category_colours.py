"""Every sync-review category must be colour-coded to match its own icon.

The review screen is the source of truth a user acts on, and the colour is how
they tell the six categories apart at a glance. "Updates Available - You've
Edited These" shipped with an amber icon on an untinted card because its rule
was assumed to be covered by the one next to it:

    div[class*="st-key-cat_update"]   does NOT match   cat_updmod_45899

Those are substring selectors and the keys diverge at ``upd-M-od`` vs
``upd-A-te``. Nothing errors, nothing logs - the category simply renders
uncoloured, which is invisible in code review and easy to miss on screen among
five siblings that look right.

These tests pin the mapping so a new category, or a renamed key, fails loudly.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CSS = (REPO / "styles" / "sync_review.css").read_text(encoding="utf-8")
REVIEW_PY = (REPO / "ui" / "sync_review.py").read_text(encoding="utf-8")

# Container key prefix -> the accent it must be tinted with. The RGB triples are
# the ones the legend card in ui/sync_review.py already assigns to each category
# (_cc_new/_cc_clean/_cc_edited/_cc_loc_del/_cc_can_del), so the expander and
# the legend explaining it cannot drift apart.
CATEGORY_ACCENTS = {
    "cat_new": "59, 130, 246",
    "cat_update": "16, 185, 129",
    "cat_updmod": "245, 158, 11",
    "cat_deleted_local": "139, 92, 246",
    "cat_deleted_canvas": "239, 68, 68",
}

# Rendered by ui/sync_review.py; ignored is deliberately neutral ("the guy in
# the corner") and is asserted separately.
ALL_CATEGORY_KEYS = tuple(CATEGORY_ACCENTS) + ("cat_ignored",)


def _summary_rule(prefix: str) -> str | None:
    m = re.search(
        r'div\[class\*="st-key-' + re.escape(prefix) +
        r'"\]\s+div\[data-testid="stExpander"\]\s+details\s+summary\s*\{([^}]*)\}',
        CSS)
    return m.group(1) if m else None


def _details_rule(prefix: str) -> str | None:
    m = re.search(
        r'div\[class\*="st-key-' + re.escape(prefix) +
        r'"\]\s+div\[data-testid="stExpander"\]\s+details\s*\{([^}]*)\}',
        CSS)
    return m.group(1) if m else None


@pytest.mark.parametrize("prefix,rgb", CATEGORY_ACCENTS.items())
def test_every_category_has_a_tinted_summary(prefix, rgb):
    body = _summary_rule(prefix)
    assert body, f"no background rule for {prefix} - the category renders untinted"
    assert rgb in body, (
        f"{prefix} summary is tinted with something other than rgb({rgb}); it must "
        f"match the icon and the legend card")


@pytest.mark.parametrize("prefix,rgb", CATEGORY_ACCENTS.items())
def test_every_category_has_a_matching_border(prefix, rgb):
    body = _details_rule(prefix)
    assert body, f"no border rule for {prefix}"
    # deleted_local deliberately uses the lighter violet (167,139,250) on the
    # border than in its fill - both are the same ramp.
    assert "border" in body


def test_substring_selectors_do_not_silently_cover_each_other():
    """The exact trap that caused the bug.

    ``cat_update`` reads as though it covers ``cat_updmod`` and does not. If a
    future key makes that true by accident, one of the two rules starts winning
    on both categories and the colours quietly merge.
    """
    assert "cat_update" not in "cat_updmod_45899"
    for a in CATEGORY_ACCENTS:
        for b in CATEGORY_ACCENTS:
            if a != b:
                assert a not in f"{b}_45899", (
                    f"selector '{a}' also matches '{b}' containers, so their "
                    f"colours collide")


def test_all_rendered_categories_are_covered():
    """Any category the screen renders must appear in the map above.

    Catches the real-world case: someone adds a seventh category, styles the
    icon, and never notices the card is untinted.
    """
    rendered = set(re.findall(r'st\.container\(key=f"(cat_[a-z_]+)_\{', REVIEW_PY))
    assert rendered, "category containers moved; update this guard"
    missing = rendered - set(ALL_CATEGORY_KEYS)
    assert not missing, (
        f"category rendered but not colour-checked: {sorted(missing)}")


def test_ignored_is_deliberately_neutral():
    body = _summary_rule("cat_ignored")
    assert body, "the Ignored bucket lost its styling"
    for rgb in CATEGORY_ACCENTS.values():
        assert rgb not in body, (
            "Ignored must stay visually quiet - it is not an action category")
