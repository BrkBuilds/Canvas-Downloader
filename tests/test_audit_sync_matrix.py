"""The sync plan measures a different space from the download plan.

A download run is configuration x configuration: 24 switches the user picks,
which the run either honours or does not. A sync run's configuration is already
FIXED - the folder's contract, baked in at download time and read back from
`.canvas_sync.db`, with no on-the-fly overrides by design. What varies at sync
time is the WORLD: what changed since the last run, and which of it the user
accepts through which screen.

That asymmetry drives every choice here, and two of them were mistakes first:

  * ``sync_mode=quick`` with ``confirm=False`` is not a reachable state - Quick
    Sync has no review screen to cancel from - and a row that lands there is
    checked against an "untouched folder" expectation a Quick Sync legitimately
    violates.
  * A snapshot has to hold enough files for the seeder to find candidates. It
    reports "no eligible candidate in this folder" and moves on, so a thin
    folder produces a row that seeds nothing, analyses nothing and PASSES.
    Measured: with cost as the only tie-break, 34 of 43 rows were assigned to a
    2-file, 1-row snapshot that could not exercise a single one of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import matrix as M            # noqa: E402
from tests.audit.harness import parallel as P          # noqa: E402

PLAN = M.sync_plan()
RICH = {"course_id": 45899, "files": 21822, "manifest": {"rows": 215},
        "config": {"mode": "modules", "dl_assignments": True,
                   "convert_zip": True, "convert_code": True},
        "inventory": {"nested/" * 30 + "deep.js": {}}}   # 217 chars
THIN = {"course_id": 43667, "files": 2, "manifest": {"rows": 1},
        "config": {"mode": "modules"}, "inventory": {"x.pdf": {}}}


# --------------------------------------------------------------------------
# the space
# --------------------------------------------------------------------------

def test_every_pair_is_covered():
    assert PLAN["coverage_2way"]["percent"] == 100.0


def test_every_triple_of_the_interacting_factors_is_covered():
    assert PLAN["coverage_3way_interacting"]["percent"] == 100.0


def test_quick_sync_can_never_be_asked_to_cancel():
    """Quick Sync has no review screen, so there is nothing to cancel from."""
    assert not [r for r in PLAN["runs"]
                if r["sync_mode"] == "quick" and not r["confirm"]]


def test_both_screens_and_both_outcomes_appear():
    modes = {r["sync_mode"] for r in PLAN["runs"]}
    assert modes == {"quick", "review"}
    assert {r["confirm"] for r in PLAN["runs"]} == {True, False}


def test_a_folder_where_nothing_changed_is_a_scenario():
    """The empty-analysis screen needs a run of its own."""
    quiet = [r for r in PLAN["runs"] if r.get("_isolates") == "nothing-changed"]
    assert len(quiet) == 1
    assert not any(quiet[0].get(k) for k in M.SEED_KINDS)


@pytest.mark.parametrize("kind", M.SEED_KINDS)
def test_every_fixture_gets_a_run_of_its_own(kind):
    """With eight fixtures live, any of them could have produced the row under
    suspicion; isolation is what makes a defect attributable."""
    solo = [r for r in PLAN["runs"] if r.get("_isolates") == kind]
    assert len(solo) == 1
    assert not [k for k in M.SEED_KINDS if k != kind and solo[0].get(k)]


def test_the_plan_is_deterministic():
    assert [r.get("_isolates") for r in M.sync_plan()["runs"]] == \
           [r.get("_isolates") for r in PLAN["runs"]]


def test_coverage_is_measured_against_the_SYNC_constraint():
    """It used to hardcode the download one, which would count unreachable
    tuples as holes and report a complete plan as incomplete."""
    import inspect
    assert "constraint" in inspect.signature(M.coverage).parameters


# --------------------------------------------------------------------------
# assignment
# --------------------------------------------------------------------------

def _jobs(snaps):
    return P.sync_jobs_from_plan(PLAN, snaps)


def test_a_thin_snapshot_never_gets_a_row_that_needs_material():
    """The regression."""
    jobs = _jobs({"rich": RICH, "thin": THIN})
    needs = {"new_regular", "clean_update", "edited_update", "deleted_locally",
             "deleted_on_canvas", "renamed_row_intact", "renamed_row_dropped",
             "renamed_ambiguous", "moved_deep", "duplicate_copy",
             "readonly_target"}
    for j in jobs:
        if set(j.seed_kinds or []) & needs:
            assert j.snapshot == "rich", f"{j.id} {j.seed_kinds} -> {j.snapshot}"


def test_fixtures_that_create_their_own_files_may_use_a_thin_snapshot():
    """foreign_content and partial_artifact need no candidate, so spending the
    big folder on them is pure cost."""
    jobs = {j.note: j for j in _jobs({"rich": RICH, "thin": THIN})}
    assert jobs["foreign_content"].snapshot == "thin"
    assert jobs["partial_artifact"].snapshot == "thin"


def test_secondary_fixtures_need_a_folder_that_has_secondary_content():
    jobs = {j.note: j for j in _jobs({"rich": RICH, "thin": THIN})}
    assert jobs["new_secondary"].snapshot == "rich"


def test_seed_kinds_are_the_factors_the_row_switched_on():
    jobs = {j.note: j for j in _jobs({"rich": RICH})}
    assert jobs["edited_update"].seed_kinds == ["edited_update"]


def test_nothing_changed_asks_for_an_EMPTY_list_not_none():
    """None means "seed everything"; the difference is the whole scenario."""
    jobs = {j.note: j for j in _jobs({"rich": RICH})}
    assert jobs["nothing-changed"].seed_kinds == []


def test_the_mode_and_outcome_reach_the_job():
    for j in _jobs({"rich": RICH}):
        row = PLAN["runs"][int(j.id[1:])]
        assert j.quick == (row["sync_mode"] == "quick")
        assert j.confirm == row["confirm"]


def test_no_snapshots_is_an_error_not_an_empty_run():
    with pytest.raises(SystemExit):
        P.sync_jobs_from_plan(PLAN, {})


def test_every_row_becomes_a_job():
    assert len(_jobs({"rich": RICH})) == PLAN["count"]


# --------------------------------------------------------------------------
# snapshot capabilities
# --------------------------------------------------------------------------

def test_material_is_measured_from_the_manifest_not_the_file_count():
    """An archive-heavy folder has 21,822 files and 215 tracked rows; a folder
    of loose junk could have the reverse. Only tracked rows can be seeded."""
    assert "material" in P.snapshot_capabilities(RICH)
    assert "material" not in P.snapshot_capabilities(THIN)
    assert "material" not in P.snapshot_capabilities(
        {"files": 99999, "manifest": {"rows": 3}})


def test_capabilities_come_from_the_contract_the_folder_carries():
    caps = P.snapshot_capabilities(RICH)
    assert {"secondary", "converted", "archives", "long_path"} <= caps
    assert P.snapshot_capabilities(THIN) == set()


def test_a_snapshot_with_no_metadata_claims_nothing():
    assert P.snapshot_capabilities({}) == set()


# --------------------------------------------------------------------------
# the CONTRACT a folder carries is a sync input, so the shapes get spread
# --------------------------------------------------------------------------
#
# flat vs modules, isolated secondary, the study filter - each decides
# something sync has to get right: where a new file belongs, and whether a
# filtered-out file may come back as "new". Nothing in the plan names a shape,
# so with cost as the only tie-break every row went to ONE snapshot and the
# other shapes - a full download each to capture - were never synced at all.

SHAPES = {
    "flat":     {"course_id": 43657, "files": 51, "manifest": {"rows": 50},
                 "config": {"mode": "flat", "dl_announcements": True}},
    "isolated": {"course_id": 43657, "files": 51, "manifest": {"rows": 50},
                 "config": {"mode": "modules", "secondary_isolated": True,
                            "dl_announcements": True}},
    "study":    {"course_id": 43657, "files": 44, "manifest": {"rows": 43},
                 "config": {"mode": "modules", "file_filter": "study",
                            "dl_announcements": True}},
}


def test_every_captured_contract_shape_actually_gets_used():
    """The regression: three snapshots captured, one ever synced."""
    used = {j.snapshot for j in P.sync_jobs_from_plan(PLAN, SHAPES)}
    assert used == set(SHAPES), f"unused shapes: {set(SHAPES) - used}"


def test_the_spread_is_roughly_even():
    jobs = P.sync_jobs_from_plan(PLAN, SHAPES)
    counts = [sum(1 for j in jobs if j.snapshot == n) for n in SHAPES]
    assert max(counts) - min(counts) <= 1, counts


def test_the_spread_is_deterministic():
    a = [j.snapshot for j in P.sync_jobs_from_plan(PLAN, SHAPES)]
    b = [j.snapshot for j in P.sync_jobs_from_plan(PLAN, SHAPES)]
    assert a == b


def test_a_cheap_row_is_not_spread_onto_an_expensive_snapshot():
    """Interchangeable means the SAME capability set, not the same number of
    matches. A row needing nothing matches a 1-row folder and a 21,822-file one
    equally, and spreading across those is 26 seconds of restore for nothing."""
    jobs = {j.note: j for j in P.sync_jobs_from_plan(PLAN, {"rich": RICH,
                                                           "thin": THIN})}
    assert jobs["foreign_content"].snapshot == "thin"
    assert jobs["partial_artifact"].snapshot == "thin"


def test_capability_still_outranks_the_spread():
    """A shape rotation must never displace the only snapshot that can do the
    job."""
    jobs = {j.note: j for j in P.sync_jobs_from_plan(
        PLAN, dict(SHAPES, rich=RICH))}
    assert jobs["new_secondary"].snapshot in set(SHAPES) | {"rich"}
    # long_path is exclusive to the rich snapshot
    longp = [j for j in P.sync_jobs_from_plan(PLAN, dict(SHAPES, rich=RICH))
             if "long_path" in (j.seed_kinds or [])]
    assert longp and all(j.snapshot == "rich" for j in longp)
