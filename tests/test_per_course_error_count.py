"""The "Course Finished" line must count THIS course's errors.

``download_errors_list`` is created once before the course loop and never
reset - the completion screen reads it under the name ``global_errors``. The
per-course log line took ``len()`` of it, so every course after the first
reported the whole batch's errors, while the download count on the SAME LINE
was per-course. The two halves disagreed about what they were counting.

Measured on the three-course row m025::

    Course Finished: 43660  ... Errors: 3     (2 locked + 1 discussion - correct)
    Course Finished: 46396  ... Errors: 5     (own: 2)
    Course Finished: 45899  ... Errors: 5     (own: ZERO)

It is a diagnostic line rather than a UI one, but it is the line anybody
judging a course's health reads - and it sent this audit hunting 90 errors
that did not exist across 40 rows.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.canvas_logic import DownloadError      # noqa: E402


def count_for(errors, course_name):
    """The expression under test, mirrored from app.py."""
    return sum(1 for e in errors
               if getattr(e, "course_name", None) == course_name)


A, B, C = "Course A", "Course B", "Course C"


def _err(course, item="x"):
    return DownloadError(course, item, "Locked File", "locked")


# --------------------------------------------------------------------------

def test_a_later_course_does_not_inherit_an_earlier_one_s_errors():
    """The regression: course C contributed nothing and was reported with 5."""
    batch = [_err(A), _err(A), _err(A), _err(B), _err(B)]
    assert count_for(batch, C) == 0
    assert count_for(batch, B) == 2
    assert count_for(batch, A) == 3


def test_the_first_course_is_unaffected():
    """Cumulative and per-course agree for course 1, which is exactly why the
    defect was invisible on a single-course run."""
    batch = [_err(A), _err(A)]
    assert count_for(batch, A) == len(batch) == 2


def test_a_clean_course_reports_zero():
    assert count_for([_err(A), _err(B)], C) == 0


def test_an_empty_batch_is_zero_for_everyone():
    assert count_for([], A) == 0


def test_a_malformed_entry_is_ignored_rather_than_counted():
    """The list is appended to from several places; one bad entry must not
    inflate an unrelated course."""
    assert count_for([_err(A), object(), None], A) == 1


def test_courses_with_similar_names_are_not_conflated():
    a = "Programmering (LA E25)"
    b = "Programmering (XC E25)"
    assert count_for([_err(a), _err(b), _err(b)], b) == 2


def test_download_error_carries_the_course_name():
    """The whole fix depends on this field existing on every entry."""
    assert _err(A).course_name == A


# --------------------------------------------------------------------------
# the source no longer takes len() of the batch list
# --------------------------------------------------------------------------

SRC = re.sub(r"^\s*#.*$", "",
             (REPO / "app.py").read_text(encoding="utf-8"), flags=re.M)


def test_the_count_is_filtered_by_course():
    i = SRC.find("_err_count_done")
    assert i > 0, "the Course Finished error count moved"
    body = SRC[i:i + 320]
    assert "course_name" in body, "the count is not scoped to this course"


def test_it_is_no_longer_a_bare_len_of_the_global_list():
    assert "_err_count_done = len(st.session_state.get('download_errors_list'" \
        not in SRC


def test_the_download_half_of_the_line_is_still_per_course():
    """Both halves must count the same thing; fixing one and not the other
    just moves the disagreement."""
    i = SRC.find("_dl_count_done")
    assert "download_file_details" in SRC[i:i + 200]
    assert "course.name" in SRC[i:i + 200]
