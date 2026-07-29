"""What the seeder deliberately broke, the checker must not report as a defect.

The seed plan publishes `expected_*` lists describing the state it created on
purpose, and `crosscheck.invariants` suppresses each one. The lists are a
CONTRACT between two files, and it fails silently in both directions: a fixture
whose damage is undeclared is reported as a product defect, and a declaration
nothing reads suppresses nothing.

The specific trap these pin: `_backdate` falsifies the manifest's recorded
SIZE by one byte - that is its mechanism, not a side effect - so every fixture
calling it leaves the size diverging, while only `edited_update` also rewrites
the file's bytes. One combined list got both halves wrong at once.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import seed as seeder      # noqa: E402
from tests.audit.harness import parallel            # noqa: E402

SEED_SRC = (REPO / "tests" / "audit" / "harness" / "seed.py").read_text(encoding="utf-8")


def _fixture_methods_calling(name: str) -> set[str]:
    """Every Seeder method whose body calls *name*, read from the source."""
    tree = ast.parse(SEED_SRC)
    out = set()
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    f = node.func
                    if isinstance(f, ast.Attribute) and f.attr == name:
                        out.add(fn.name)
    return out


def test_every_fixture_that_backdates_declares_its_size_drift():
    """The coupling, enforced instead of remembered.

    `readonly_target` called `_backdate` and was in neither list, so the size
    it falsified was reported as a manifest defect - 6 per run, on a product
    that had done nothing wrong. Adding a fixture is exactly when this is easy
    to forget, so it is checked from the source rather than by convention.
    """
    backdaters = _fixture_methods_calling("_backdate") - {"_backdate"}
    assert backdaters, "no fixture calls _backdate - has it been renamed?"
    missing = backdaters - set(seeder._PERTURBS_RECORDED_SIZE)
    assert not missing, (
        f"these fixtures falsify the recorded size but do not declare it: "
        f"{sorted(missing)}")


def test_only_a_fixture_that_rewrites_bytes_declares_md5_drift():
    """The other half, and it must stay NARROW.

    `clean_update`'s whole premise is that original_md5 STILL MATCHES - the
    file is untouched and only the recorded size is perturbed. Declaring md5
    drift for it suppressed the one check that could have caught a real
    mismatch there.
    """
    assert set(seeder._DRIFTS_FROM_BASELINE) == {"edited_update"}, (
        "only edited_update writes to the file; anything else here blinds the "
        "md5 check for a fixture whose bytes are supposed to be intact")


def test_size_drift_is_a_superset_of_md5_drift():
    """Rewriting the bytes changes the size too, so md5 drift implies size."""
    assert set(seeder._DRIFTS_FROM_BASELINE) <= set(seeder._PERTURBS_RECORDED_SIZE)


def test_expectations_emits_both_lists():
    fixtures = [
        {"kind": "clean_update", "path": "a.pdf"},
        {"kind": "edited_update", "path": "b.pdf"},
        {"kind": "readonly_target", "path": "c.pdf"},
        {"kind": "duplicate_copy", "path": "d.pdf"},
    ]
    got = seeder.declarations(fixtures)
    assert got["expected_size_drift"] == ["a.pdf", "b.pdf", "c.pdf"]
    assert got["expected_md5_drift"] == ["b.pdf"]


def test_every_declared_key_is_forwarded_to_the_checker():
    """A list the plan publishes and nothing forwards suppresses nothing."""
    published = set(seeder.declarations([{"kind": "edited_update", "path": "x"}]))
    forwarded = set(parallel._SEED_EXPECTATION_KEYS)
    assert published <= forwarded, f"never reaches the checker: {sorted(published - forwarded)}"


def test_a_plan_without_the_new_key_is_re_derived_from_its_fixtures():
    """Plans written before this key existed must not keep reporting it.

    `seed.declarations` is deliberately derived rather than only stored, so an
    old plan gets the same treatment as a new one.
    """
    old_plan = {  # what a pre-2026-07-29 plan looks like
        "fixtures": [{"kind": "readonly_target", "path": "locked.pdf"}],
        "expected_md5_drift": [],
        "expected_untracked": [],
        "expected_missing_rows": [],
        "expected_partials": [],
    }
    got = parallel.seed_expectations(old_plan)
    assert got["expected_size_drift"] == ["locked.pdf"]


def test_stored_and_derived_are_UNIONED_not_chosen_between():
    """The failure being fixed was an INCOMPLETE stored list, not a missing one.

    `expected_untracked` was present on every plan and simply did not name the
    renames, so preferring the stored value would leave every plan written
    before the fix reporting the seeder's own renames as orphans for ever.
    """
    plan = {"fixtures": [{"kind": "readonly_target", "path": "derived.pdf"}],
            "expected_size_drift": ["stored.pdf"]}
    assert parallel.seed_expectations(plan)["expected_size_drift"] == [
        "derived.pdf", "stored.pdf"]


def test_a_plan_with_no_fixtures_yields_empty_lists_not_a_crash():
    got = parallel.seed_expectations({})
    assert all(v == [] for v in got.values())


# ── a fixture must be able to reach the outcome it asserts ───────────────


def test_fixtures_that_need_canvas_metadata_use_direct_targets_only():
    """A conversion product cannot be matched from Canvas metadata.

    It differs from its source in BOTH things the app keys on - the extension
    ("x.js" -> "x_js.txt") and the size (the converter prepends a header). A
    fixture whose expectation depends on that match must start from
    `_direct_targets()`, or it asks for a match that cannot exist.

    Measured: `renamed_row_dropped` did not, and on the two rows where it
    happened to pick a `convert_code` output it reported the analyzer for
    saying New - a verdict that was correct, and the safe direction. Its
    `unrecognisable` sibling needs it for the opposite reason: it asserts a
    REFUSAL, and a conversion product is refused on the extension before the
    name floor is ever consulted, so it would pass without testing anything.
    """
    tree = ast.parse(SEED_SRC)
    needs = {"readonly_target", "renamed_row_dropped",
             "renamed_row_dropped_unrecognisable"}
    seen = set()
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
            if fn.name not in needs:
                continue
            calls = {n.func.attr for n in ast.walk(fn)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
            assert "_direct_targets" in calls, (
                f"{fn.name} picks candidates without excluding conversion "
                f"products, so its expectation may be unreachable")
            assert "_rows" not in calls, (
                f"{fn.name} still reaches for the unfiltered row list")
            seen.add(fn.name)
    assert seen == needs, f"fixture(s) missing from seed.py: {sorted(needs - seen)}"


def test_relocating_a_file_declares_BOTH_of_its_consequences():
    """A rename leaves a dangling row AND an untracked new path.

    Only the row was declared, so the always-on "content file on disk with no
    manifest row" invariant reported the seeder's own renames - 14 findings
    across the 43-row plan. Whether the analyzer then ADOPTS the new path is a
    real question with its own check (`sync_run`'s "classified as new, expected
    uptodate"); claiming it twice, once as an orphan, is what buried it.
    """
    assert seeder._RELOCATES_A_TRACKED_FILE == (
        seeder._LEAVES_ROW_DANGLING - {"deleted_locally"}), (
        "every dangling-row kind relocates its file except deleted_locally, "
        "which leaves none behind")


def test_the_relocation_set_is_actually_consulted():
    """A set that is defined and never read declares nothing."""
    got = seeder.declarations([
        {"kind": "moved_deep", "path": "My Notes/wk3/reading/a.pdf"},
        {"kind": "renamed_row_dropped", "path": "b - mine noter 0.pdf"},
        {"kind": "deleted_locally", "path": "gone.pdf"},
    ])
    assert got["expected_untracked"] == ["My Notes/wk3/reading/a.pdf",
                                         "b - mine noter 0.pdf"], (
        "a relocated file must be declared untracked; a deleted one leaves no "
        "file behind and must not be")


def test_expected_untracked_is_derivable_not_only_stored():
    """It used to be built inline in seed(), so an old plan could never gain it."""
    assert "expected_untracked" in seeder.declarations(
        [{"kind": "foreign_content", "path": "mine.docx"}])


def test_a_dangling_row_is_declared_at_the_path_it_POINTS_at():
    """For a relocation that is where the file WAS, not where it now is.

    Declaring the new path suppressed nothing - the row still names the old one
    - so the seeder's own moves were reported as broken manifest rows. And the
    new path is deliberately NOT declared: a row pointing there with no file is
    a genuine adoption failure, which is the one thing this check is for.
    """
    got = seeder.declarations([
        {"kind": "moved_deep", "path": "My Notes/wk3/a.pdf",
         "original_path": "a.pdf", "expect_path": "My Notes/wk3/a.pdf"},
        {"kind": "deleted_locally", "path": "gone.pdf", "expect_path": "gone.pdf"},
    ])
    assert got["expected_missing_rows"] == ["a.pdf", "gone.pdf"]


def test_every_relocation_fixture_records_where_the_file_was():
    """The declaration above is only correct if the fixtures supply it."""
    import ast
    tree = ast.parse(SEED_SRC)
    kinds_with_original = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kw = {k.arg for k in node.keywords if k.arg}
        if "original_path" not in kw:
            continue
        for k in node.keywords:
            if k.arg == "kind" and isinstance(k.value, ast.Constant):
                kinds_with_original.add(k.value.value)
    missing = seeder._RELOCATES_A_TRACKED_FILE - kinds_with_original
    assert not missing, (
        f"these relocate a file but never record where it was, so their "
        f"dangling row cannot be declared: {sorted(missing)}")
