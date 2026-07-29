"""Two checks that reported the product's correct behaviour as data loss.

Both were measured on course 43660 with the "Slides & PDFs" filter and Panopto
audio enabled - one ordinary matrix row - and both came out **high**.

**Ignored rows.** The engine records files it deliberately skipped (study
filter, size cap) so a later sync does not re-offer them; the Settings copy
promises exactly that. Nothing is written, so the row carries no local path.
Keying 23 such rows on ``""`` made them collide with each other and produced
"1 local path claimed by more than one manifest row" - which reads as two
Canvas files overwriting each other.

**Panopto outputs.** "Slides & PDFs" filters the Canvas FILES a course exposes.
Recordings are a separate pass the user enabled by name, so all 36 mp3s were
reported as "36 other file type(s) were downloaded".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import crosscheck                     # noqa: E402
from tests.audit.harness.oracles import db as odb              # noqa: E402


# --------------------------------------------------------------------------
# an ignored row is not a path collision
# --------------------------------------------------------------------------

def _row(fid, path, ignored=False, size=10, md5="m"):
    return {"canvas_file_id": fid, "canvas_filename": f"f{fid}", "local_path": path,
            "original_size": size, "original_md5": md5, "is_ignored": ignored,
            "content_sig": "", "canvas_updated_at": "", "downloaded_at": ""}


def _disk(*rels):
    return {"exists": True, "files": [
        {"rel": r, "name": Path(r).name, "ext": Path(r).suffix, "size": 10,
         "md5": "m", "app_generated": False, "partial": False}
        for r in rels]}


def test_skipped_files_do_not_collide_with_each_other():
    """The regression: 23 skipped files, all with no path, one HIGH finding."""
    rows = [_row(1000 + i, "", ignored=True) for i in range(23)]
    rows.append(_row(1, "slides.pdf"))
    rec = odb.reconcile_with_disk({"exists": True, "rows": rows}, _disk("slides.pdf"))
    assert rec["duplicate_local_paths"] == {}


def test_a_real_collision_is_still_reported():
    rows = [_row(1, "slides.pdf"), _row(2, "slides.pdf")]
    rec = odb.reconcile_with_disk({"exists": True, "rows": rows}, _disk("slides.pdf"))
    assert list(rec["duplicate_local_paths"].values()) == [[1, 2]]


def test_an_ignored_row_with_a_path_still_does_not_claim_it():
    """A restored-then-ignored file must not block the live row for that path."""
    rows = [_row(1, "slides.pdf"), _row(2, "slides.pdf", ignored=True)]
    rec = odb.reconcile_with_disk({"exists": True, "rows": rows}, _disk("slides.pdf"))
    assert rec["duplicate_local_paths"] == {}


def test_an_empty_path_row_is_not_counted_as_missing_on_disk():
    """It was never written, so "the manifest says it is there" is not true."""
    rec = odb.reconcile_with_disk({"exists": True, "rows": [_row(1, "", ignored=True)]}, _disk())
    assert rec["missing_on_disk"] == []


# --------------------------------------------------------------------------
# the study filter does not govern Panopto
# --------------------------------------------------------------------------

def _ev(expect, *rels):
    return crosscheck.Evidence(folder=Path("/x"), disk=_disk(*rels),
                               db={"exists": False}, log={}, canvas={},
                               expect=expect, scenario="s")


def test_recordings_are_not_offenders_under_the_study_filter():
    """The regression, with the real layout from course 43660."""
    out = crosscheck._file_filter(_ev(
        {"file_filter": "study", "pan_out_mp3": True},
        "Panopto Recordings/Lecture 1/Lecture 1.mp3", "slides.pdf"))
    assert out == [], [f.title for f in out]


def test_an_output_that_was_NOT_requested_is_still_an_offender():
    """Excusing every Panopto extension would hide a genuine layout defect."""
    out = crosscheck._file_filter(_ev(
        {"file_filter": "study", "pan_out_mp3": True},
        "Panopto Recordings/Lecture 1/Lecture 1.mp4"))
    assert any("other file type" in f.title for f in out)


@pytest.mark.parametrize("key,ext", list(crosscheck.PANOPTO_OUTPUTS.items()))
def test_each_requested_output_is_excused(key, ext):
    out = crosscheck._file_filter(_ev(
        {"file_filter": "study", key: True}, f"Panopto Recordings/L/L{ext}"))
    assert out == [], [f.title for f in out]


def test_an_ordinary_stray_file_type_is_still_reported():
    out = crosscheck._file_filter(_ev(
        {"file_filter": "study", "pan_out_mp3": True}, "data/notes.zip"))
    assert any("other file type" in f.title for f in out)


def test_nothing_is_checked_without_the_study_filter():
    assert crosscheck._file_filter(_ev({"file_filter": "all"}, "x.zip")) == []
