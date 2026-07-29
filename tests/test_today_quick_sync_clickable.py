"""Today's Quick Sync shortcut is INERT while Today mode is off. On purpose.

Quick Sync's real home is the Sync page. The copy on the Today page is a
SHORTCUT, for someone who has turned Today mode on and lives on that page day to
day, so they can pull the newest files without switching pages. With Today mode
off - the default - the whole page reads "NOT ACTIVATED", every section is dimmed,
and the shortcut is inert along with them. The action is still one click away
where it actually lives.

This file exists because a 2026-07-28 audit pass "fixed" that. The reasoning
looked sound in isolation: the button is enabled server-side while the dimming's
inherited ``pointer-events: none`` makes it unclickable, so the app appears to
offer an action it will not perform. Measured, both true. But it was the wrong
conclusion - what the dimming expresses is the state of the PAGE, not the state
of that one button, and a shortcut to a page you have not activated is correctly
unavailable.

So the guard runs the other way: the Quick Sync section must STAY in the dimming
list. If someone (or some future audit) removes it again, this fails and points
at the reason.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SRC = (REPO / "ui" / "today_dashboard.py").read_text(encoding="utf-8")

QS = "today_qs_section"
DIMMED_SECTIONS = ("today_courses_card", "today_files_hero", QS)


def _dimming_css() -> str:
    """The CSS literal applied when auto-sync is off or a sync is running."""
    body = SRC.split("def _inject_dynamic_css", 1)[1].split("toggle_active_css", 1)[0]
    cond = "if not auto_sync_enabled or sync_running:"
    i = body.find(cond)
    assert i > 0, "the dimming condition moved; update this guard"
    parts = body[i:].split('"""')
    assert len(parts) >= 3, "no CSS literal under the dimming condition"
    return parts[1]


def test_the_quick_sync_shortcut_is_dimmed_with_the_rest_of_the_page():
    """Do not "fix" this. See the module docstring."""
    css = _dimming_css()
    assert QS in css, (
        "the Today Quick Sync shortcut was excluded from the dimming. It is "
        "meant to be inert while Today mode is off - the page is not activated, "
        "and Quick Sync's real home is the Sync page.")


def test_every_dimmed_section_is_dimmed_the_same_way():
    """One rule, one appearance - a section dimmed differently reads as a bug."""
    css = _dimming_css()
    for key in DIMMED_SECTIONS:
        assert key in css, f"{key} lost its dimming"
    assert "pointer-events: none" in css
    assert "opacity: 0.45" in css


def test_the_running_sync_card_is_never_dimmed():
    """It is the active thing on the page while a sync runs."""
    assert "today_running_card" not in _dimming_css()


def test_the_button_is_also_gated_server_side():
    """The CSS expresses the page state; ``disabled=`` is the real gate.

    Deliberately does NOT include ``auto_sync_enabled``: with Today mode off the
    page is inert as a whole, which the dimming already says, and duplicating
    that into the widget would make the "no courses yet" tooltip unreachable.
    """
    i = SRC.find('key="today_sync_now_btn"')
    assert i > 0, "the Quick Sync button moved"
    decl = SRC[max(0, i - 400):i + 200]
    assert "disabled=not runnable or sync_running" in decl
