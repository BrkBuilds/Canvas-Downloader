"""Measure what Canvas's own "Download as Zip" misses, from the audit census.

WHY THIS EXISTS
---------------
Every university help desk, forum answer and competitor page asserts that
Download as Zip "can miss files attached to modules". Nobody has ever put a
number on it. The live audit harness captures a per-course census against real
Canvas courses (`_audit_runs/*/evidence/canvas/course_<id>.json`), and those
files carry exactly the fields needed to answer it:

    files_tab            every file id visible in the course's Files tab
    module_file_ids      every file id attached to a module item
    only_in_modules      module-attached files ABSENT from the Files tab
    only_in_files_tab    Files-tab files no module links to
    files_tab_restricted the Files tab is hidden from students entirely
    expected_file_ids    the union - every file a student can reach
    quizzes / announcements / discussions / assignments / pages
                         the non-file content, none of which any zip contains

This script is the METHOD, published so the numbers can be checked. It is
deliberately dumb: it reads the censuses, dedupes to one per course (the most
recently fetched), and counts. No estimation, no extrapolation, no weighting.

HONESTY CONSTRAINTS, which are the point rather than a caveat
------------------------------------------------------------
* The sample is every real course this project has ever audited. It is small
  and it is not random: one student's enrolment at ONE institution (all 33
  courses are on cbscanvas.instructure.com), censused mid-2026.
* It therefore describes THESE courses. Publishing it as a survey of Canvas
  would be dishonest, and the site says so wherever it quotes a figure.
* A course where the number is ZERO counts. Reporting only the courses that
  make the point is how a real measurement becomes marketing.

THE RESULT, and it inverts the folklore
---------------------------------------
The thing every help desk warns about - Download as Zip missing files that a
module links to - happened in **1 of 8** courses where the Files tab worked,
and cost **3 files out of 358 (0.8%)**.

What happened far more often is that Download as Zip could not be used at all.
**3 of the 11** courses holding any material answered the Files endpoint with
403 "user not authorised to perform that action", and those courses held
**246 files** between them. Two of them held 121 and 124 files, every one of
which was reachable through the course's modules.

That the 403 is a per-course setting rather than an account problem is checked
rather than assumed: the same credential succeeded on 29 of the same 33
courses, in the same minutes.

Run:  python scripts/measure_export_gap.py [--json]
"""
from __future__ import annotations

import argparse

import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / "_audit_runs"


def load_censuses() -> dict[int, dict]:
    """One census per course id: the most recently fetched wins."""
    best: dict[int, dict] = {}
    for p in sorted(RUNS.glob("*/evidence/canvas/course_*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        cid = d.get("course_id")
        if not isinstance(cid, int):
            continue
        prev = best.get(cid)
        if prev is None or str(d.get("fetched_at", "")) > str(prev.get("fetched_at", "")):
            d["_source"] = str(p.relative_to(ROOT))
            best[cid] = d
    return best


def _n(d: dict, key: str) -> int:
    v = d.get(key)
    if isinstance(v, (list, dict)):
        return len(v)
    return 0


def analyse(courses: dict[int, dict]) -> dict:
    rows = []
    for cid, d in sorted(courses.items()):
        files_tab = _n(d, "files_tab")
        expected = _n(d, "expected_file_ids")
        only_mod = _n(d, "only_in_modules")
        rows.append(dict(
            course_id=cid,
            files_tab=files_tab,
            module_files=_n(d, "module_file_ids"),
            only_in_modules=only_mod,
            only_in_files_tab=_n(d, "only_in_files_tab"),
            expected=expected,
            files_tab_restricted=bool(d.get("files_tab_restricted")),
            pages_restricted=bool(d.get("pages_restricted")),
            pages=_n(d, "pages"),
            assignments=_n(d, "assignments"),
            quizzes=_n(d, "quizzes"),
            announcements=_n(d, "announcements"),
            discussions=_n(d, "discussions"),
            syllabus=bool(d.get("syllabus_present")),
            source=d.get("_source", ""),
        ))

    # A course with no files at all tells us nothing about a file-download gap.
    # 22 of the 33 are empty shells - programme containers and unused course
    # sites. Their censuses fetched fine (elapsed 2-3s, no errors); they simply
    # hold no material. They are reported, and excluded from every denominator
    # about files, because including them would flatter every ratio.
    withfiles = [r for r in rows if r["expected"] > 0]

    # TWO DISTINCT FAILURES, and conflating them was the first draft's mistake.
    #   unavailable: Canvas answers the Files endpoint with 403 "user not
    #                authorised to perform that action". Download as Zip cannot
    #                be used at all. Verified per-course rather than per-token:
    #                the same credential succeeds on 29 of these 33 courses.
    #   incomplete:  the Files tab works and is missing files that a module
    #                links to. This is the failure the folklore names, and in
    #                this sample it is the RARER of the two.
    unavailable = [r for r in withfiles if r["files_tab_restricted"]]
    working = [r for r in withfiles if not r["files_tab_restricted"]]
    incomplete = [r for r in working if r["only_in_modules"] > 0]

    total_expected = sum(r["expected"] for r in withfiles)
    total_only_mod = sum(r["only_in_modules"] for r in withfiles)
    affected = [r for r in withfiles if r["only_in_modules"] > 0]
    restricted = [r for r in rows if r["files_tab_restricted"]]

    # Per-course share of files that a Files-tab zip would not contain.
    shares = [100.0 * r["only_in_modules"] / r["expected"] for r in withfiles]

    non_file = [r["pages"] + r["assignments"] + r["quizzes"]
                + r["announcements"] + r["discussions"] + (1 if r["syllabus"] else 0)
                for r in rows]

    return dict(
        courses=len(rows),
        courses_empty=len(rows) - len(withfiles),
        courses_with_files=len(withfiles),
        zip_unavailable=len(unavailable),
        zip_unavailable_files=sum(r["expected"] for r in unavailable),
        zip_working=len(working),
        zip_incomplete=len(incomplete),
        zip_incomplete_files=sum(r["only_in_modules"] for r in incomplete),
        zip_working_files=sum(r["expected"] for r in working),
        total_expected=total_expected,
        total_only_in_modules=total_only_mod,
        pct_files_missed=(100.0 * total_only_mod / total_expected) if total_expected else 0.0,
        courses_affected=len(affected),
        pct_courses_affected=(100.0 * len(affected) / len(withfiles)) if withfiles else 0.0,
        worst_course=max(withfiles, key=lambda r: r["only_in_modules"])["course_id"] if withfiles else None,
        worst_count=max((r["only_in_modules"] for r in withfiles), default=0),
        worst_share=round(max(shares), 1) if shares else 0.0,
        median_share=round(statistics.median(shares), 1) if shares else 0.0,
        files_tab_restricted=len(restricted),
        pages_restricted=sum(1 for r in rows if r["pages_restricted"]),
        total_non_file=sum(non_file),
        median_non_file=round(statistics.median(non_file), 1) if non_file else 0,
        totals={k: sum(r[k] for r in rows)
                for k in ("pages", "assignments", "quizzes", "announcements", "discussions")},
        courses_with_any_non_file=sum(1 for x in non_file if x > 0),
        rows=rows,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit the full result as JSON")
    args = ap.parse_args(argv)

    courses = load_censuses()
    if not courses:
        print("No course censuses found under _audit_runs/*/evidence/canvas/", file=sys.stderr)
        return 2
    a = analyse(courses)

    if args.json:
        print(json.dumps(a, indent=2))
        return 0

    print("Canvas course census - %d distinct real courses\n" % a["courses"])
    hdr = ("course", "files tab", "in modules", "MODULE-ONLY", "total files",
           "quiz", "ann", "disc", "asg", "pages")
    print("%-8s %9s %10s %12s %11s %5s %4s %5s %4s %6s" % hdr)
    for r in a["rows"]:
        flag = "  (files tab hidden)" if r["files_tab_restricted"] else ""
        print("%-8d %9d %10d %12d %11d %5d %4d %5d %4d %6s%s" % (
            r["course_id"], r["files_tab"], r["module_files"], r["only_in_modules"],
            r["expected"], r["quizzes"], r["announcements"], r["discussions"],
            r["assignments"],
            "hidden" if r["pages_restricted"] else r["pages"], flag))

    print("\n--- the sample ---")
    print("  %d courses censused, of which %d hold no material at all"
          % (a["courses"], a["courses_empty"]))
    print("  %d courses actually have files. Everything below is about those."
          % a["courses_with_files"])

    print("\n--- failure 1: Download as Zip is not available ---")
    print("  Canvas answers the Files endpoint 403 'user not authorised':"
          " %d of %d courses with files" % (a["zip_unavailable"], a["courses_with_files"]))
    print("  files in those courses, none of them reachable that way: %d"
          % a["zip_unavailable_files"])

    print("\n--- failure 2: the Files tab works but is incomplete ---")
    print("  courses where a module links a file the Files tab does not list:"
          " %d of %d working" % (a["zip_incomplete"], a["zip_working"]))
    print("  those files: %d of %d (%.1f%% of the files in working courses)"
          % (a["zip_incomplete_files"], a["zip_working_files"],
             100.0 * a["zip_incomplete_files"] / a["zip_working_files"]
             if a["zip_working_files"] else 0.0))

    print("\n--- content no zip contains at all ---")
    t = a["totals"]
    print("  quizzes %d | announcements %d | discussions %d | assignments %d | pages %d"
          % (t["quizzes"], t["announcements"], t["discussions"], t["assignments"], t["pages"]))
    print("  total non-file items: %d across %d courses" % (a["total_non_file"], a["courses"]))

    print("\n--- what this sample is NOT ---")
    print("  one student's enrolment at ONE institution. Not a survey of Canvas.")
    print("  quote it as 'in 33 real courses at one university', or not at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
