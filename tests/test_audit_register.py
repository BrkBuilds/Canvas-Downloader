"""The findings register must survive being read and written repeatedly.

``parse`` and ``render`` are a LOOP - the register is re-read and re-written on
every audit run, and whatever parse returns is what render writes back. So any
text the parser wrongly claims as "the human's notes" is re-emitted, reclaimed
next run, and grows without bound. That is not a hypothetical: the renderer's
own "Not observed in the latest run" marker and the ``---`` entry separator were
both being swallowed into the preceding entry's Notes, and one entry had
accumulated four copies of each before it was noticed.

The other property pinned here is that a human's decision is never overwritten.
The register is the audit's work queue; if a run could silently flip a `wontfix`
back to `open`, triaging it would be pointless.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import register as reg  # noqa: E402


def _finding(title="Something broke", **kw):
    return {"title": title, "severity": "high", "category": "persistence",
            "oracles": ["O3", "O4"], "detail": "the detail", **kw}


@pytest.fixture()
def regpath(tmp_path):
    return tmp_path / "AUDIT_FINDINGS.md"


# --------------------------------------------------------------------------
# the round trip
# --------------------------------------------------------------------------

def test_render_parse_render_is_idempotent(regpath):
    reg.update([_finding()], "run1", regpath)
    first = regpath.read_text(encoding="utf-8")
    reg.update([_finding()], "run1", regpath)
    reg.update([_finding()], "run1", regpath)
    third = regpath.read_text(encoding="utf-8")
    # Only the occurrence count and dates may move; the structure must not grow.
    assert third.count("### ") == first.count("### ")
    assert third.count("**Notes**:") == first.count("**Notes**:")


def test_notes_never_absorb_the_separator_or_the_stale_marker(regpath):
    """The bug this file exists for.

    A finding that stops being observed gets a stale marker appended after its
    Notes. On the next parse that marker, and the entry separator below it, were
    read back AS notes and written out again - once per run, for ever.
    """
    reg.update([_finding("A"), _finding("B")], "run1", regpath)
    for run in ("run2", "run3", "run4"):
        reg.update([_finding("A")], run, regpath)   # B is never seen again

    entries = reg.parse(regpath)
    b = next(e for e in entries.values() if e["title"] == "B")
    assert b["notes"] == "", f"stale marker leaked into notes: {b['notes']!r}"
    text = regpath.read_text(encoding="latin-1" if False else "utf-8")
    assert text.count(reg._STALE_MARK) == 1, \
        "the stale marker multiplied across renders"


def test_a_humans_notes_survive_every_later_run(regpath):
    reg.update([_finding()], "run1", regpath)
    text = regpath.read_text(encoding="utf-8")
    text = text.replace("**Notes**: ", "**Notes**: Root cause is in heal_manifest.\n"
                                       "Deliberately deferred until after Phase 3.")
    regpath.write_text(text, encoding="utf-8")

    for run in ("run2", "run3"):
        reg.update([_finding()], run, regpath)

    notes = next(iter(reg.parse(regpath).values()))["notes"]
    assert "Root cause is in heal_manifest." in notes
    assert "Deliberately deferred until after Phase 3." in notes
    assert reg._STALE_MARK not in notes


def test_multi_line_notes_are_preserved_verbatim(regpath):
    reg.update([_finding()], "run1", regpath)
    body = "line one\nline two\n\nline four after a blank"
    text = regpath.read_text(encoding="utf-8").replace("**Notes**: ",
                                                       f"**Notes**: {body}")
    regpath.write_text(text, encoding="utf-8")
    reg.update([_finding()], "run2", regpath)
    assert reg.parse(regpath)[next(iter(reg.parse(regpath)))]["notes"] == body


# --------------------------------------------------------------------------
# the human owns the status
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["fixed", "accepted", "wontfix", "invalid"])
def test_a_status_is_never_overwritten_by_a_later_run(regpath, status):
    reg.update([_finding()], "run1", regpath)
    text = regpath.read_text(encoding="utf-8").replace("**Status**: open",
                                                       f"**Status**: {status}")
    regpath.write_text(text, encoding="utf-8")
    reg.update([_finding()], "run2", regpath)
    assert next(iter(reg.parse(regpath).values()))["status"] == status


def test_reappearing_after_fixed_is_a_regression(regpath):
    reg.update([_finding()], "run1", regpath)
    regpath.write_text(regpath.read_text(encoding="utf-8")
                       .replace("**Status**: open", "**Status**: fixed"),
                       encoding="utf-8")
    res = reg.update([_finding()], "run2", regpath)
    assert res["regressions"] == ["Something broke"]


def test_re_merging_an_OLDER_run_after_a_fix_is_not_a_regression(regpath):
    """Re-checking a folder after a fix re-reads the pre-fix pass.

    The run's findings file is append-only and cumulative, so the old finding is
    still in it. Flagging that as "it came back" is the same false signal as the
    same-run case, one step removed.
    """
    reg.update([_finding()], "20260728_010000_a", regpath)
    regpath.write_text(regpath.read_text(encoding="utf-8")
                       .replace("**Status**: open", "**Status**: invalid"),
                       encoding="utf-8")
    res = reg.update([_finding()], "20260727_090000_earlier", regpath)
    assert res["closed_but_seen_again"] == []
    assert res["regressions"] == []


def test_a_genuinely_later_run_still_reports_the_regression(regpath):
    reg.update([_finding()], "20260727_090000_a", regpath)
    regpath.write_text(regpath.read_text(encoding="utf-8")
                       .replace("**Status**: open", "**Status**: fixed"),
                       encoding="utf-8")
    res = reg.update([_finding()], "20260728_010000_later", regpath)
    assert res["regressions"] == ["Something broke"]


def test_closing_a_finding_mid_run_is_not_a_regression(regpath):
    """A run's findings file is cumulative.

    Fix something during an audit, mark it fixed, then re-run ``register
    update`` against the same unchanged ledger: the entry is still in it. Report
    that as a regression and the signal the register exists for becomes noise.
    """
    reg.update([_finding()], "run1", regpath)
    regpath.write_text(regpath.read_text(encoding="utf-8")
                       .replace("**Status**: open", "**Status**: fixed"),
                       encoding="utf-8")
    res = reg.update([_finding()], "run1", regpath)      # SAME run
    assert res["regressions"] == []


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def test_the_same_defect_with_a_different_count_is_one_entry(regpath):
    reg.update([_finding("7 source files survived conversion")], "run1", regpath)
    reg.update([_finding("9 source files survived conversion")], "run2", regpath)
    assert len(reg.parse(regpath)) == 1


def test_different_categories_are_different_entries(regpath):
    reg.update([_finding("X", category="persistence"),
                _finding("X", category="ui-truth")], "run1", regpath)
    assert len(reg.parse(regpath)) == 2


def test_observations_are_context_not_work_items(regpath):
    reg.update([_finding("just context", category="observation")], "run1", regpath)
    assert reg.parse(regpath) == {}


def test_fields_round_trip(regpath):
    reg.update([_finding(scenario="p2_sync_45899")], "run1", regpath)
    e = next(iter(reg.parse(regpath).values()))
    assert e["severity"] == "high"
    assert e["category"] == "persistence"
    assert e["oracles"] == "O3,O4"
    assert e["scenario"] == "p2_sync_45899"
    assert e["detail"] == "the detail"


def test_an_empty_oracles_dash_does_not_become_literal_text(regpath):
    """The renderer writes an em dash for "none"; parsing it back as the value
    would make the next render say the oracles are literally "—"."""
    reg.update([_finding(oracles=[])], "run1", regpath)
    reg.update([_finding(oracles=[])], "run2", regpath)
    assert reg.parse(regpath)[next(iter(reg.parse(regpath)))]["oracles"] == ""
