"""The completion screen's stats are read by their LABEL, not by proximity.

On the real screen the number and its caption are separate lines::

    3
    COURSES DOWNLOADED
    335
    FILES DOWNLOADED
    242.1
    MB DOWNLOADED
    5
    CANNOT BE DOWNLOADED
    45 files skipped because they exceeded the 5 MB limit.

A pattern of "<number> files" therefore cannot match the stat at all - and the
first thing it DID match was the sentence at the bottom. The check was
comparing the SKIPPED count against the saved count and reporting the
difference as a miscount, on four rows of the matrix.

The second half is scope: the screen totals the whole BATCH, and a row's
evidence is one course. Comparing them across a multi-course row is a category
error in both directions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import crosscheck        # noqa: E402

REAL_SCREEN = (
    "1. Select Courses\n\n2. Configure Download\n\n5. Complete\n\n"
    "Download Complete!\nPartial Success\n"
    "{courses}\n{course_label}\n"
    "{files}\nFILES DOWNLOADED\n"
    "242.1\nMB DOWNLOADED\n"
    "5\nCANNOT BE DOWNLOADED\n"
    "45 files skipped because they exceeded the 5 MB limit.\n"
)


def _screen(files, courses=1):
    return REAL_SCREEN.format(
        files=files, courses=courses,
        course_label="COURSE DOWNLOADED" if courses == 1 else "COURSES DOWNLOADED")


def _ev(files_saved, screen):
    return crosscheck.Evidence(
        folder=Path("/x"),
        disk={"exists": True, "files": [], "content_count": files_saved},
        db={}, log={"files_saved": files_saved, "secondary_saved": 0,
                    "links_created": 0, "courses_finished": []},
        ui={"completion": {"text": screen}}, canvas={},
        expect={"convert_zip": False}, scenario="s")


def _titles(out):
    return [f.title for f in out]


# --------------------------------------------------------------------------

def test_the_skipped_sentence_is_not_mistaken_for_the_stat():
    """The regression: '45 files skipped' was read as the files-downloaded
    stat and compared against 95 saved."""
    out = crosscheck._count_coherence(_ev(95, _screen(files=335)))
    assert not any("Completion screen shows" in t for t in _titles(out)), _titles(out)


def test_a_genuine_under_count_is_still_caught():
    out = crosscheck._count_coherence(_ev(95, _screen(files=40)))
    assert any("shows 40 but 95 files were saved" in t for t in _titles(out))


def test_the_screen_may_legitimately_show_more_than_were_saved():
    """It counts items: files + Canvas Content + Panopto."""
    out = crosscheck._count_coherence(_ev(95, _screen(files=335)))
    assert not any("Completion screen" in t for t in _titles(out))


def test_a_multi_course_batch_is_not_compared_against_one_course():
    """The screen totals the batch; this evidence is a single course."""
    out = crosscheck._count_coherence(_ev(95, _screen(files=40, courses=3)))
    assert not any("Completion screen" in t for t in _titles(out)), _titles(out)


def test_the_singular_label_is_understood():
    out = crosscheck._count_coherence(_ev(95, _screen(files=40, courses=1)))
    assert any("Completion screen" in t for t in _titles(out))


def test_a_thousands_separator_is_read_correctly():
    out = crosscheck._count_coherence(_ev(95, _screen(files="1,200")))
    assert not any("Completion screen" in t for t in _titles(out))


def test_a_screen_without_the_stat_is_not_guessed_at():
    out = crosscheck._count_coherence(
        _ev(95, "Download Complete!\n45 files skipped because of the limit.\n"))
    assert not any("Completion screen" in t for t in _titles(out))


@pytest.mark.parametrize("label", ["FILES DOWNLOADED", "files downloaded",
                                   "File Downloaded"])
def test_the_label_match_is_case_insensitive(label):
    screen = f"Download Complete!\n40\n{label}\n1\nCOURSE DOWNLOADED\n"
    out = crosscheck._count_coherence(_ev(95, screen))
    assert any("Completion screen" in t for t in _titles(out))
