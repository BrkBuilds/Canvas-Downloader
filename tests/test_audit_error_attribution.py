"""A course's errors are counted from its OWN log, not from the engine's tally.

The engine's ``Errors: N`` on the ``Course Finished`` line is cumulative across
a batch: the second course of a two-course run reports the first course's
failures as its own. An audit that reads that number and compares it against
the current course's locked files concludes that something unexplained failed -
and on the 2026-07-28 download matrix it concluded that 32 times, against
courses whose own logs recorded not one failure. That was the single largest
finding class in the run, and all of it was the checker.

So the oracle counts ``ERROR [kind] ...`` lines straight off the text, and the
check compares the two numbers instead of trusting either. The tests below pin
both halves, and both directions of each: the counter defect must FIRE where the
counts disagree and stay SILENT where they agree, and a genuine delivery failure
must survive both.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness.oracles import log as olog  # noqa: E402


HEAD = "[2026-07-28 20:37:00.000] "


def _write(tmp_path, *lines) -> str:
    p = tmp_path / "course.txt"
    p.write_text("\n".join(HEAD + l for l in lines) + "\n", encoding="utf-8")
    return str(p)


def _finished(course="Course A", items=10, errors=0):
    return (f"=== Course Finished: {course} | Downloaded: {items} items | "
            f"Errors: {errors} ===")


LOCKED = ("ERROR [Locked File] Course A :: Slides 1.pptx :: The teacher has "
          "locked this file on Canvas, so it cannot be downloaded.")
DISPATCH = ("ERROR [Discussion Dispatch Error] Course A :: Spørgsmål til "
            "pensum :: Not Found")


# --------------------------------------------------------------------------
# the oracle
# --------------------------------------------------------------------------

def test_error_lines_are_counted_off_the_text_not_the_grammar(tmp_path):
    """The whole point of the independence. ``ERROR [Discussion Dispatch
    Error]`` reaches the event list only as `suspicious` and ``ERROR [Locked
    File]`` only as a locked-name match, so ``pl.of("error")`` returned [] on
    all 73 rows of a real matrix. Counting raw lines cannot miss an error kind
    the PATTERNS table has never heard of."""
    s = olog.parse_and_summarize(_write(tmp_path, LOCKED, DISPATCH,
                                        _finished(errors=2)))
    assert s["error_line_count"] == 2
    assert s["error_kinds"] == ["Discussion Dispatch Error", "Locked File"]
    assert s["errors"] == [], "the narrow grammar channel is still empty - " \
                              "which is exactly why error_lines exists"


def test_an_unknown_error_kind_still_counts(tmp_path):
    """A kind nobody has written a pattern for is the case this must survive."""
    s = olog.parse_and_summarize(_write(
        tmp_path, "ERROR [Some Future Failure] Course A :: thing :: broke",
        _finished(errors=1)))
    assert s["error_line_count"] == 1
    assert s["error_kinds"] == ["Some Future Failure"]


def test_a_clean_log_reports_no_errors(tmp_path):
    s = olog.parse_and_summarize(_write(tmp_path, "File Saved: C:\\x\\y.pdf (12 bytes)",
                                        _finished(errors=0)))
    assert s["error_line_count"] == 0 and s["error_kinds"] == []


def test_a_course_name_containing_error_is_not_an_error(tmp_path):
    """Real course material is called things like "Forelæsning 7.
    Error-handling, Moduler". Only the ``ERROR [kind]`` shape counts."""
    s = olog.parse_and_summarize(_write(
        tmp_path,
        "Processing Module: Uge 43: Forelæsning 7. Error-handling, Moduler",
        "File Saved: C:\\x\\Error-handling\\notes.pdf (12 bytes)",
        _finished(errors=0)))
    assert s["error_line_count"] == 0


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------

def _run(tmp_path, *lines, expect=None):
    """The course-errors check, on a log built from `lines`.

    `disk["exists"]` is required, not decoration: `_count_coherence` returns
    immediately without it, so an Evidence missing it makes every assertion here
    pass against an empty list. That is a test that cannot fail - which is how
    the first version of this file "passed" five checks it never ran.
    """
    from tests.audit.harness import crosscheck
    ev = crosscheck.Evidence(
        folder=tmp_path, scenario="t1",
        disk={"exists": True, "files": [], "content_count": 0}, db={},
        log=olog.parse_and_summarize(_write(tmp_path, *lines)),
        batch_log={}, ui={}, canvas={}, expect=expect or {})
    return crosscheck._count_coherence(ev)


def _titles(findings):
    return [f.title if hasattr(f, "title") else f["title"] for f in findings]


def _sev(findings, needle):
    for f in findings:
        t = f.title if hasattr(f, "title") else f["title"]
        if needle in t:
            return f.severity if hasattr(f, "severity") else f["severity"]
    return None


def test_batch_counter_leak_fires_and_is_NOT_a_delivery_defect(tmp_path):
    """The 32-false-HIGH case: a course that logged nothing, reporting the
    batch's total. It is a truth defect about the tally, not a delivery defect
    about the files - the files are all there."""
    out = _run(tmp_path, "File Saved: C:\\x\\y.pdf (12 bytes)",
               _finished(course="Course B", errors=2))
    joined = " | ".join(_titles(out))
    assert "reports 2 error(s) but this course's log records 0" in joined
    assert _sev(out, "reports 2 error") == "medium"
    assert not any("unexplained" in t for t in _titles(out)), (
        "an inherited count must never be reported as a delivery failure")


def test_an_honest_counter_says_nothing_about_itself(tmp_path):
    """The silent direction. First course of a batch: counter == own errors."""
    out = _run(tmp_path, LOCKED, _finished(errors=1))
    assert not any("Course Finished' reports" in t for t in _titles(out))


def test_all_teacher_locked_stays_info(tmp_path):
    """A standing Canvas-side condition with no action available. Recorded, but
    never in the blocking pile - it would sit there on every run for ever."""
    out = _run(tmp_path, LOCKED, _finished(errors=1))
    assert _sev(out, "all teacher-locked files") == "info"


def test_a_genuine_non_locked_error_is_high_AND_names_it(tmp_path):
    """The finding that must survive all of this. A bare count is not a
    delivery finding - every one of the 32 false HIGHs carried an empty error
    list, which was the tell."""
    out = _run(tmp_path, LOCKED, DISPATCH, _finished(errors=2))
    assert _sev(out, "unexplained") == "high"
    ev = [f.evidence if hasattr(f, "evidence") else f["evidence"]
          for f in out if "unexplained" in (f.title if hasattr(f, "title")
                                            else f["title"])][0]
    assert ev["kinds"] == ["Discussion Dispatch Error"]
    assert ev["unexplained"] and "Not Found" in ev["unexplained"][0]["msg"]


def test_a_genuine_error_is_reported_even_when_the_counter_also_lies(tmp_path):
    """Two independent facts, two findings. Collapsing them would let a real
    delivery failure hide behind a counter defect."""
    out = _run(tmp_path, DISPATCH, _finished(course="Course B", errors=5))
    joined = " | ".join(_titles(out))
    assert "reports 5 error(s) but this course's log records 1" in joined
    assert "unexplained" in joined
    assert _sev(out, "unexplained") == "high"


def test_a_clean_course_produces_nothing(tmp_path):
    out = _run(tmp_path, "File Saved: C:\\x\\y.pdf (12 bytes)", _finished(errors=0))
    assert _titles(out) == [] or not any(
        "error" in t.lower() for t in _titles(out))


def test_under_reporting_is_flagged_in_the_other_direction(tmp_path):
    """Not observed in the wild, but the mirror image of a known defect: errors
    reaching the log without reaching the tally the user is shown."""
    out = _run(tmp_path, LOCKED, DISPATCH, _finished(errors=1))
    joined = " | ".join(_titles(out))
    assert "reports 1 error(s) but this course's log records 2" in joined
