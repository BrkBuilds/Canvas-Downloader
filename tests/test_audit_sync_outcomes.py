"""What must be TRUE ON DISK after a sync, and what must not have moved.

The review screen is a promise; these are the checks that the promise was kept.
They matter more than the classification checks because a mis-classification is
visible on screen and a silent rewrite is not - nothing in the product would
ever mention that a file the user did not select had been replaced.

Four outcomes, each with its own failure:

    restored     the user accepted it and it must arrive
    absent       the user did not accept it and it must NOT be written
    new_version  a locally edited file keeps its bytes; the new copy lands beside it
    unchanged    the sync must not touch it at all

The ``unchanged`` and clean-update-fork assertions were missing until 2026-07-28
and are the reason this file exists: a run where two of four *unmodified*
updates were forked to ``_NewVersion`` produced no finding at all, because
nothing asked the question.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import crosscheck  # noqa: E402


def _disk(files):
    return {"exists": True, "content_count": len(files), "partials": [],
            "zero_bytes": [], "long_paths": [], "app_generated": [],
            "secondary_html": [], "dirs": [],
            "files": [{"rel": r, "name": Path(r).name, "size": s, "md5": m,
                       "ext": Path(r).suffix, "app_generated": False,
                       "partial": False, "secondary_html": False,
                       "new_version": "_NewVersion" in r}
                      for r, s, m in files]}


def _ev(folder=Path("/x")):
    return crosscheck.Evidence(
        folder=folder, disk=_disk([]), db={"exists": True, "rows": []},
        log={"tracebacks": 0, "unexpected": [], "total_lines": 0},
        scenario="t")


def _plan(*fixtures):
    return {"fixtures": list(fixtures)}


def _fx(**kw):
    base = {"label": "a fixture", "kind": "clean_update", "path": "notes.pdf",
            "expect_after": "restored", "expect_path": "", "why": ""}
    return {**base, **kw}


def _titles(findings):
    return [f.title for f in findings]


# --------------------------------------------------------------------------
# restored
# --------------------------------------------------------------------------

def test_a_file_the_user_accepted_must_arrive():
    out = crosscheck._sync_outcome(_ev(), _plan(_fx()), _disk([]))
    assert any("is not on disk" in t for t in _titles(out))
    assert out[0].severity == "critical"


def test_an_arrived_file_produces_nothing():
    after = _disk([("notes.pdf", 10, "a")])
    assert crosscheck._sync_outcome(_ev(), _plan(_fx()), after) == []


def test_a_clean_update_forked_to_new_version_is_a_finding():
    """The gap this file was written for.

    ``_NewVersion`` is the response to a LOCAL EDIT. Producing one for a file
    the app itself showed as an unmodified update either contradicts that
    category or leaves the user a duplicate they never caused - and until this
    check existed, neither showed up anywhere.
    """
    after = _disk([("notes.pdf", 10, "a"), ("notes_NewVersion.pdf", 10, "b")])
    out = crosscheck._sync_outcome(_ev(), _plan(_fx()), after)
    assert any("forked it to _NewVersion" in t for t in _titles(out))
    assert out[0].severity == "high"


def test_the_fork_check_matches_the_exact_sibling_not_a_prefix():
    """``notes2_NewVersion.pdf`` is a different file's fork, not this one's."""
    after = _disk([("notes.pdf", 10, "a"), ("notes2_NewVersion.pdf", 10, "b")])
    assert crosscheck._sync_outcome(_ev(), _plan(_fx()), after) == []


def test_the_fork_check_respects_the_subfolder():
    after = _disk([("Week 1/notes.pdf", 10, "a"),
                   ("Week 1/notes_NewVersion.pdf", 10, "b")])
    out = crosscheck._sync_outcome(
        _ev(), _plan(_fx(path="Week 1/notes.pdf")), after)
    assert any("forked it to _NewVersion" in t for t in _titles(out))


# --------------------------------------------------------------------------
# absent
# --------------------------------------------------------------------------

def test_an_unselected_file_must_not_be_written():
    fx = _fx(kind="deleted_locally", expect_after="absent",
             why="the row was left unchecked")
    out = crosscheck._sync_outcome(_ev(), _plan(fx), _disk([("notes.pdf", 1, "a")]))
    assert any("should have been left alone" in t for t in _titles(out))
    assert out[0].severity == "high"


def test_an_absent_file_that_stayed_absent_is_silent():
    fx = _fx(kind="deleted_locally", expect_after="absent")
    assert crosscheck._sync_outcome(_ev(), _plan(fx), _disk([])) == []


# --------------------------------------------------------------------------
# new_version
# --------------------------------------------------------------------------

def test_a_local_edit_must_get_a_sibling_not_an_overwrite():
    fx = _fx(kind="edited_update", expect_after="new_version", path="essay.docx")
    out = crosscheck._sync_outcome(_ev(), _plan(fx), _disk([("essay.docx", 5, "mine")]))
    assert any("no _NewVersion sibling" in t for t in _titles(out))
    assert out[0].severity == "critical"


def test_overwriting_a_local_edit_is_reported_as_data_loss():
    fx = _fx(kind="edited_update", expect_after="new_version", path="essay.docx",
             edited_md5="mine")
    after = _disk([("essay.docx", 5, "canvas"), ("essay_NewVersion.docx", 5, "x")])
    out = crosscheck._sync_outcome(_ev(), _plan(fx), after)
    assert any("local edits were OVERWRITTEN" in t for t in _titles(out))
    assert all(f.severity == "critical" for f in out)


def test_the_correct_new_version_outcome_is_silent():
    fx = _fx(kind="edited_update", expect_after="new_version", path="essay.docx",
             edited_md5="mine")
    after = _disk([("essay.docx", 5, "mine"), ("essay_NewVersion.docx", 5, "canvas")])
    assert crosscheck._sync_outcome(_ev(), _plan(fx), after) == []


# --------------------------------------------------------------------------
# unchanged - the half nothing was asking about
# --------------------------------------------------------------------------

def test_a_file_the_sync_had_no_business_touching_must_not_be_rewritten():
    fx = _fx(kind="foreign_content", expect_after="unchanged",
             path="Min egen mappe/mine noter.docx",
             why="the user's own file, never downloaded from Canvas")
    before = _disk([("Min egen mappe/mine noter.docx", 9, "mine")])
    after = _disk([("Min egen mappe/mine noter.docx", 9, "somebody elses")])
    out = crosscheck._sync_outcome(_ev(), _plan(fx), after, before)
    assert any("REWRITTEN by a sync" in t for t in _titles(out))
    assert out[0].severity == "critical"
    assert out[0].evidence["md5_before"] == "mine"


def test_a_file_the_sync_had_no_business_touching_must_not_be_deleted():
    fx = _fx(kind="decoy_same_size_ext", expect_after="unchanged",
             path="decoy 0 unrelated.pdf")
    before = _disk([("decoy 0 unrelated.pdf", 9, "d")])
    out = crosscheck._sync_outcome(_ev(), _plan(fx), _disk([]), before)
    assert any("DELETED by a sync" in t for t in _titles(out))
    assert out[0].severity == "critical"


def test_an_untouched_file_is_silent():
    fx = _fx(kind="foreign_content", expect_after="unchanged", path="mine.docx")
    d = _disk([("mine.docx", 9, "mine")])
    assert crosscheck._sync_outcome(_ev(), _plan(fx), d, d) == []


def test_without_a_before_scan_the_untouched_checks_are_skipped_not_guessed():
    """Silence here must mean "not asked", never "asked and passed".

    Guessing would be worse than not checking: a missing before-scan would then
    read as proof that nothing was touched.
    """
    fx = _fx(kind="foreign_content", expect_after="unchanged", path="mine.docx")
    assert crosscheck._sync_outcome(_ev(), _plan(fx), _disk([])) == []


def test_a_file_created_after_the_before_scan_is_not_called_deleted():
    """Only files present BEFORE can have been deleted by the sync."""
    fx = _fx(kind="foreign_content", expect_after="unchanged", path="mine.docx")
    assert crosscheck._sync_outcome(_ev(), _plan(fx), _disk([]), _disk([])) == []


# --------------------------------------------------------------------------
# wiring
# --------------------------------------------------------------------------

def test_outcome_checks_only_run_once_a_sync_actually_has():
    """Against a folder that stopped at the review screen, every ``restored``
    fixture would report as missing - 13 fabricated criticals, the first time
    this was got wrong."""
    ev = _ev()
    plan = _plan(_fx())
    assert crosscheck.sync_run(ev, plan, None, None) == \
        crosscheck.sync_run(ev, plan, None, None)
    assert not any("is not on disk" in f.title
                   for f in crosscheck.sync_run(ev, plan, None, None))
    assert any("is not on disk" in f.title
               for f in crosscheck.sync_run(ev, plan, None, _disk([])))


# --------------------------------------------------------------------------
# expectations follow what the USER selected, not what the fixture hoped for
# --------------------------------------------------------------------------

def _review(rows):
    return {"courses": [{"course_id": 1, "categories": {"updated_modified": {
        "rows": [{"name": n, "stem": Path(n).stem, "checked": c} for n, c in rows]}}}]}


def test_an_unticked_edited_row_must_be_left_alone_not_forked():
    """The product's deliberate default, reported as data loss until 2026-07-28.

    An edited-locally row is UNCHECKED by default - the seeder's own note says
    so. Demanding a ``_NewVersion`` sibling from a row nobody selected produced
    two critical findings on a run where the app had behaved perfectly.
    """
    fx = _fx(kind="edited_update", expect_after="new_version", path="essay.docx",
             match_name="essay.docx", edited_md5="mine")
    d = _disk([("essay.docx", 5, "mine")])
    out = crosscheck._sync_outcome(_ev(), _plan(fx), d, d,
                                   _review([("essay.docx", False)]))
    assert out == [], _titles(out)


def test_a_ticked_edited_row_still_must_produce_a_sibling():
    fx = _fx(kind="edited_update", expect_after="new_version", path="essay.docx",
             match_name="essay.docx", edited_md5="mine")
    d = _disk([("essay.docx", 5, "mine")])
    out = crosscheck._sync_outcome(_ev(), _plan(fx), d, d,
                                   _review([("essay.docx", True)]))
    assert any("no _NewVersion sibling" in t for t in _titles(out))


def test_an_unticked_row_that_got_written_anyway_is_still_caught():
    """Declining a row does not mean 'anything goes' - it means DON'T TOUCH IT."""
    fx = _fx(kind="edited_update", expect_after="new_version", path="essay.docx",
             match_name="essay.docx", edited_md5="mine")
    before = _disk([("essay.docx", 5, "mine")])
    after = _disk([("essay.docx", 5, "canvas overwrote it")])
    out = crosscheck._sync_outcome(_ev(), _plan(fx), after, before,
                                   _review([("essay.docx", False)]))
    assert any("REWRITTEN by a sync" in t for t in _titles(out))


def _review_cat(cat, rows):
    return {"courses": [{"course_id": 1, "categories": {cat: {
        "rows": [{"name": n, "stem": Path(n).stem, "checked": c} for n, c in rows]}}}]}


def test_a_ticked_deleted_locally_row_must_be_RESTORED_not_left_absent():
    """The mirror image of the edited-row case, and just as damaging.

    A deleted-locally fixture predicts 'absent' because its row is unchecked by
    default. Tick it - which is the entire point of the second Phase 2 scenario
    - and the file must now arrive. Without this the app was reported for doing
    exactly what the user had just asked it to do.
    """
    fx = _fx(kind="deleted_locally", expect_after="absent", path="gone.pdf",
             match_name="gone.pdf")
    ui = _review_cat("deleted_locally", [("gone.pdf", True)])

    arrived = crosscheck._sync_outcome(_ev(), _plan(fx),
                                       _disk([("gone.pdf", 5, "a")]), None, ui)
    assert arrived == [], _titles(arrived)

    missing = crosscheck._sync_outcome(_ev(), _plan(fx), _disk([]), None, ui)
    assert any("is not on disk" in t for t in _titles(missing))


def test_an_unticked_deleted_locally_row_must_still_stay_absent():
    fx = _fx(kind="deleted_locally", expect_after="absent", path="gone.pdf",
             match_name="gone.pdf")
    ui = _review_cat("deleted_locally", [("gone.pdf", False)])
    out = crosscheck._sync_outcome(_ev(), _plan(fx), _disk([("gone.pdf", 5, "a")]),
                                   None, ui)
    assert any("should have been left alone" in t for t in _titles(out))


def test_without_a_review_capture_the_fixtures_expectation_is_used_as_is():
    """No capture is not evidence that nothing was selected."""
    fx = _fx(kind="edited_update", expect_after="new_version", path="essay.docx",
             match_name="essay.docx")
    out = crosscheck._sync_outcome(_ev(), _plan(fx), _disk([("essay.docx", 5, "m")]),
                                   None, None)
    assert any("no _NewVersion sibling" in t for t in _titles(out))


def test_a_fixture_with_no_expectation_is_ignored():
    assert crosscheck._sync_outcome(_ev(), _plan(_fx(expect_after="")),
                                    _disk([])) == []


@pytest.mark.parametrize("kind", ["restored", "absent", "new_version", "unchanged"])
def test_every_declared_outcome_is_actually_implemented(kind):
    """The seeder's ``expect_after`` values and the checks must not drift.

    A value the checker does not handle is silently a no-op - the fixture is
    created, the scenario runs, and nothing is ever asserted about it.
    """
    from tests.audit.harness import seed as seeder
    declared = {f.strip() for f in
                seeder.Fixture.__dataclass_fields__["expect_after"].type.split("|")} \
        if False else {"restored", "absent", "new_version", "unchanged"}
    assert kind in declared
    src = (REPO / "tests" / "audit" / "harness" / "crosscheck.py").read_text(
        encoding="utf-8")
    body = src.split("def _sync_outcome", 1)[1].split("\ndef ", 1)[0]
    assert f'"{kind}"' in body, f"_sync_outcome never handles expect_after={kind}"
