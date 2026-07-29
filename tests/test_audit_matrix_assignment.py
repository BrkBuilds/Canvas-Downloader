"""The matrix scheduler must not spend a run on something it cannot test.

Every case here is a defect that was live in the harness on 2026-07-28, found
while preparing the 73-row run and each one silently producing GREEN results:

  * ``capabilities`` called every ``ExternalTool`` item Panopto. Course 45899's
    twelve are Alma library citations, and because 45899 is a quarter the size
    of the one real Panopto course the assignment sent it 25 of the 29 Panopto
    rows and 17 of the 18 transcription rows - hours of GPU time against a
    course with zero recordings.
  * ``assign_courses`` seeded its best score with -1, so a row no course could
    satisfy kept ``_course_id = None`` - and ``jobs_from_plan`` skipped it
    without a word. 73 planned runs, 72 executed, nothing anywhere saying so.
  * Single-course assignment left 42 factor-instances switched ON against a
    course that could not exercise them, so their covering-array tuples were
    scheduled but never tested.
  * A lane reuses ONE app across all its rows, so a course folder left behind
    made the next row a no-op (the engine skips a file whose size matches) and
    the batch debug log accumulated every earlier row's output into oracle O2.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import matrix as M          # noqa: E402
from tests.audit.harness import parallel as P        # noqa: E402


def _snap(items=(), files=(), secondary=None):
    return {
        "modules": [{"items": list(items)}],
        "files_tab": {i: {"display_name": n, "has_url": True, "size": 1024}
                      for i, n in enumerate(files)},
        "expected_file_ids": list(range(len(files))),
        "module_item_types": {},
        "secondary_counts": secondary or {},
    }


PANOPTO_ITEM = {"type": "ExternalTool", "title": "Forelæsningsvideo (1)",
                "external_url": "https://cbs.cloud.panopto.eu/Panopto/LTI/LTI.aspx"}
ALMA_ITEM = {"type": "ExternalTool", "title": "UML @ Classroom : kap. 1",
             "external_url": "https://kbdk-cbs.alma.exlibrisgroup.com/lti/v3/"
                             "launch/45KBDK_CBS/LMS_CANVAS_1.3?citation_id=4026745000005765"}


# --------------------------------------------------------------------------
# a Panopto item is one that launches Panopto
# --------------------------------------------------------------------------

def test_a_panopto_launch_counts():
    assert len(M.panopto_items(_snap([PANOPTO_ITEM] * 3))) == 3


def test_a_library_citation_is_not_a_recording():
    """The regression: real data from course 45899."""
    assert M.panopto_items(_snap([ALMA_ITEM] * 12)) == []


def test_a_course_of_library_citations_is_not_panopto_capable():
    assert "panopto" not in M.capabilities(_snap([ALMA_ITEM] * 12))


def test_a_mixed_course_counts_only_the_panopto_ones():
    snap = _snap([ALMA_ITEM, PANOPTO_ITEM, ALMA_ITEM])
    assert len(M.panopto_items(snap)) == 1
    assert "panopto" in M.capabilities(snap)


@pytest.mark.parametrize("url", ["", None, "not a url", "https://"])
def test_a_tool_with_no_usable_url_is_not_panopto(url):
    assert M.panopto_items(_snap([{"type": "ExternalTool", "external_url": url}])) == []


def test_a_non_tool_item_is_never_a_recording():
    """A Page whose title happens to mention panopto is not a launch."""
    assert M.panopto_items(_snap([
        {"type": "Page", "title": "panopto", "external_url":
         "https://cbs.cloud.panopto.eu/x"}])) == []


# --------------------------------------------------------------------------
# cost
# --------------------------------------------------------------------------

STATS_PANOPTO = {"mb": 848.6, "files": 143, "recordings": 36}
STATS_PLAIN = {"mb": 235.6, "files": 124, "recordings": 0}


def test_panopto_flags_cost_nothing_on_a_course_with_no_recordings():
    a = M.estimate_cost({}, STATS_PLAIN)
    b = M.estimate_cost({"pan_out_mp4": True, "pan_out_srt": True}, STATS_PLAIN)
    assert a == b


def test_transcription_costs_more_than_audio_alone():
    mp3 = M.estimate_cost({"pan_out_mp3": True}, STATS_PANOPTO)
    txt = M.estimate_cost({"pan_out_mp3": True, "pan_out_txt": True}, STATS_PANOPTO)
    assert txt > mp3


def test_video_costs_more_on_disk_than_audio():
    mp3 = M.estimate_cost({"pan_out_mp3": True}, STATS_PANOPTO)
    mp4 = M.estimate_cost({"pan_out_mp4": True}, STATS_PANOPTO)
    assert mp4 > mp3


def test_a_restricted_files_tab_still_produces_a_cost():
    """45899 has no Files tab at all; a zero cost would make it look free."""
    st = M.course_stats({"files_tab": {}, "expected_file_ids": list(range(124)),
                         "modules": []})
    assert st["mb"] > 100


# --------------------------------------------------------------------------
# set cover
# --------------------------------------------------------------------------

CAPS = {
    1: {"pptx", "urls"},                    # cheap generalist
    2: {"panopto"},                         # the only Panopto course
    3: {"zip", "code"},
    4: {"video", "excel"},
}
STATS = {1: {"mb": 18.2}, 2: {"mb": 848.6, "recordings": 36},
         3: {"mb": 235.6}, 4: {"mb": 487.5}}


def test_one_course_is_enough_when_one_course_has_it_all():
    ids, left = M.cover_courses({"zip", "code"}, {}, CAPS, STATS)
    assert ids == [3] and left == []


def test_wants_spread_over_courses_get_every_course_they_need():
    """The regression: this used to pick ONE and silently drop the rest."""
    ids, left = M.cover_courses({"panopto", "zip", "video"}, {}, CAPS, STATS)
    assert set(ids) == {2, 3, 4}
    assert left == []


def test_an_unsatisfiable_want_is_reported_not_swallowed():
    ids, left = M.cover_courses({"syllabus"}, {}, CAPS, STATS)
    assert ids, "a row must still run"
    assert left == ["syllabus"]


def test_a_row_that_wants_nothing_gets_the_cheapest_course():
    ids, _ = M.cover_courses(set(), {}, CAPS, STATS)
    assert ids == [1]


def test_the_cover_is_deterministic():
    a = M.cover_courses({"panopto", "zip", "video"}, {}, CAPS, STATS)
    b = M.cover_courses({"panopto", "zip", "video"}, {}, CAPS, STATS)
    assert a == b


def test_cost_breaks_ties_but_never_beats_capability():
    """A cheap course must not displace the only one that can do the job."""
    caps = {1: {"pptx"}, 2: {"panopto"}}
    stats = {1: {"mb": 1.0}, 2: {"mb": 9999.0, "recordings": 36}}
    ids, left = M.cover_courses({"panopto"}, {"pan_out_srt": True}, caps, stats)
    assert ids == [2] and left == []


# --------------------------------------------------------------------------
# assignment over a whole plan
# --------------------------------------------------------------------------

def _plan(rows):
    return {"runs": [dict(r) for r in rows]}


def test_every_row_gets_a_course_even_when_nothing_satisfies_it():
    """The regression: dl_syllabus scored -1 everywhere and got None."""
    plan = M.assign_courses(_plan([{"dl_syllabus": True}]), CAPS, stats=STATS)
    run = plan["runs"][0]
    assert run["_course_id"] is not None
    assert run["_course_ids"]
    assert run["_unexercised"] == ["syllabus"]


def test_an_unreachable_requirement_is_stated_by_name():
    plan = M.assign_courses(_plan([{"dl_syllabus": True}]), CAPS, stats=STATS)
    assert "syllabus" in plan["unreachable_requirements"]
    assert plan["unexercised_factors"]["syllabus"] == 1


def test_a_reachable_requirement_is_not_reported_as_unreachable():
    plan = M.assign_courses(_plan([{"convert_zip": True}]), CAPS, stats=STATS)
    assert "zip" not in plan["unreachable_requirements"]
    assert plan["runs"][0]["_unexercised"] == []


def test_no_courses_at_all_is_an_error_not_a_silent_none():
    with pytest.raises(ValueError):
        M.assign_courses(_plan([{}]), {}, stats={})


def test_the_real_plan_exercises_every_reachable_factor():
    """End to end over the generated covering array, with the real pool."""
    caps = {44428: {"pptx", "quizzes", "secondary", "urls"},
            43657: {"announcements", "assignments", "discussions", "pptx",
                    "quizzes", "secondary", "urls"},
            45899: {"announcements", "assignments", "code", "discussions",
                    "pptx", "quizzes", "secondary", "urls", "zip"},
            43660: {"announcements", "assignments", "discussions", "excel",
                    "legacy_word", "panopto", "pptx", "quizzes", "secondary",
                    "urls"},
            46396: {"announcements", "assignments", "discussions", "excel",
                    "pptx", "secondary", "urls", "video"}}
    stats = {44428: {"mb": 18.2}, 43657: {"mb": 64.8}, 45899: {"mb": 235.6},
             43660: {"mb": 848.6, "recordings": 36}, 46396: {"mb": 487.5}}
    plan = M.assign_courses(M.build_plan(), caps, stats=stats)
    # The PROPERTY, not the count: how many rows happen to switch on the
    # unreachable factor is an artifact of how densely IPOG packs, and it moves
    # whenever the factor order changes (10 with Panopto last, 9 with it
    # first). What must hold is that nothing REACHABLE is left unexercised.
    assert set(plan["unexercised_factors"]) == {"syllabus"}, \
        "a reachable factor is switched on against a course that cannot " \
        "exercise it"
    assert plan["unreachable_requirements"] == ["syllabus"]
    assert plan["unexercised_factors"]["syllabus"] >= 1
    assert all(r["_course_ids"] for r in plan["runs"])


# --------------------------------------------------------------------------
# a planned row must never vanish on the way to a job
# --------------------------------------------------------------------------

def test_an_unassigned_row_stops_the_run_instead_of_disappearing():
    with pytest.raises(SystemExit):
        P.jobs_from_plan({"runs": [{"mode": "flat", "_course_id": None}]})


def test_jobs_carry_every_course_the_row_needs():
    jobs = P.jobs_from_plan({"runs": [{"mode": "flat", "_course_id": 2,
                                       "_course_ids": [2, 3, 4]}]})
    assert jobs[0].course_ids == [2, 3, 4]
    assert jobs[0].course_id == 2


def test_a_job_written_by_hand_still_works_with_one_course():
    j = P.Job(id="x", kind="download", course_id=7)
    assert j.course_ids == [7] and j.course_id == 7


def test_the_private_plan_keys_never_reach_the_app_config():
    jobs = P.jobs_from_plan({"runs": [{"mode": "flat", "_course_id": 2,
                                       "_course_ids": [2], "_isolates": "x",
                                       "_cost_mb": 1.0}]})
    assert set(jobs[0].config) == {"mode"}


# --------------------------------------------------------------------------
# factor ORDER is the cost lever, and it must not be shuffled casually
# --------------------------------------------------------------------------
#
# IPOG seeds an exhaustive product of the first `strength` factors and smears
# each later factor across every row that already exists. A factor declared
# EARLY is packed densely into few rows; one declared LATE turns up in row
# after row. With Panopto last, 36 recordings of video and transcription were
# sprayed across the plan. Measured on the same space, same 100% coverage:
#
#     Panopto last     36 pairwise rows · 15 GPU rows · 93.8 GB of Panopto work
#     Panopto FIRST    20 pairwise rows ·  5 GPU rows · 29.1 GB      (-69%)
#
# A cost-weighted tie-break inside horizontal growth was built and measured
# first and is WORSE - refusing an expensive level there pushes its tuples into
# vertical growth, which appends new rows that carry it anyway (36 -> 50-61
# rows, mp4 14 -> 18-23, across weights 0.5 to 4.0).

_PAN = ("pan_master", "pan_out_mp4", "pan_out_txt", "pan_out_srt",
        "pan_out_mp3", "pan_layout")


def test_the_panopto_factors_lead_the_declaration():
    names = [f.name for f in M.DOWNLOAD_FACTORS]
    assert tuple(names[:len(_PAN)]) == _PAN, (
        "the expensive factors moved out of the front of the list; that "
        "roughly doubles what the plan costs to run")


def test_reordering_does_not_weaken_coverage():
    """The reduction is only legitimate because coverage is re-derived."""
    plan = M.build_plan()
    assert plan["coverage_2way"]["percent"] == 100.0
    assert plan["coverage_3way_interacting"]["percent"] == 100.0


def test_putting_the_expensive_factors_last_is_measurably_worse():
    """Guards the reason, not just the result."""
    front = M.covering_array(M.DOWNLOAD_FACTORS, 2)
    back = M.covering_array(
        [f for f in M.DOWNLOAD_FACTORS if f.name not in _PAN]
        + [f for f in M.DOWNLOAD_FACTORS if f.name in _PAN], 2)

    def mp4_rows(rows):
        return sum(1 for r in rows if r.get("pan_out_mp4"))

    assert len(front) < len(back)
    assert mp4_rows(front) < mp4_rows(back)


def test_the_plan_stays_deterministic():
    a, b = M.build_plan(), M.build_plan()
    assert [r.get("_isolates") for r in a["runs"]] == \
           [r.get("_isolates") for r in b["runs"]]
    assert a["count"] == b["count"]
