"""The Panopto results card shows work that happened, never a zero.

A "0 DOWNLOADED" stat is read as a failure report, and on a download where every
recording was skipped by the skip-large-files limit it sat directly beside the
line that already explains the situation:

    61 files skipped because they exceeded the 5 MB limit.
    Panopto Recordings · 36 found across 1 course
    0 DOWNLOADED

Those 36 recordings are IN the 61 - measured on course 43660 with a 5 MB limit,
25 over-limit Canvas files plus 36 over-limit recordings. So the card was a
second panel describing the same event, phrased as a success metric reading
zero. The guard that prevents this existed for sync mode only; download mode
tested `found <= 0`, which is true of neither.

The card must still appear whenever something DID happen - including a failure,
which must never be hidden.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SRC = (REPO / "shared" / "components.py").read_text(encoding="utf-8")


def would_render(summary: dict) -> bool:
    """The guard under test, mirrored from render_panopto_summary."""
    if not summary:
        return False
    found = int(summary.get("found", 0) or 0)
    is_sync = "uptodate" in summary
    selected = int(summary.get("selected", found) or 0)
    did_work = (int(summary.get("downloaded", 0) or 0)
                or int(summary.get("transcribed", 0) or 0)
                or int(summary.get("failed", 0) or 0)
                or (selected if is_sync else 0))
    if not did_work:
        return False
    if not is_sync and found <= 0:
        return False
    return True


# --------------------------------------------------------------------------
# download mode
# --------------------------------------------------------------------------

def test_a_run_where_every_recording_was_size_skipped_shows_no_card():
    """The regression. The size-skip notice already accounts for them."""
    assert not would_render(
        {"found": 36, "downloaded": 0, "transcribed": 0, "failed": 0,
         "size_skipped": 36, "courses": 1})


def test_a_real_download_still_shows_the_card():
    assert would_render({"found": 36, "downloaded": 36, "courses": 1})


def test_transcripts_alone_still_show_the_card():
    """Nothing new downloaded, but three transcripts is real work."""
    assert would_render({"found": 3, "downloaded": 0, "transcribed": 3})


def test_a_failure_is_NEVER_hidden():
    """Suppressing a zero must not suppress an error."""
    assert would_render({"found": 36, "downloaded": 0, "transcribed": 0, "failed": 2})


def test_nothing_found_shows_nothing():
    assert not would_render({"found": 0})


def test_no_summary_at_all_shows_nothing():
    assert not would_render(None) and not would_render({})


# --------------------------------------------------------------------------
# sync mode is unchanged
# --------------------------------------------------------------------------

def test_sync_all_up_to_date_still_hides_the_card():
    assert not would_render(
        {"found": 36, "uptodate": 36, "downloaded": 0, "selected": 0})


def test_sync_with_selected_work_still_shows_the_card():
    assert would_render(
        {"found": 36, "uptodate": 33, "downloaded": 3, "selected": 3})


def test_sync_selection_alone_counts_as_work():
    """Preserved from the original sync guard: a selection means the user asked
    for something, even if the counters have not caught up yet."""
    assert would_render({"found": 36, "uptodate": 30, "selected": 6, "downloaded": 0})


# --------------------------------------------------------------------------
# the implementation still carries the rule
# --------------------------------------------------------------------------

def test_the_guard_is_shared_by_both_modes():
    body = SRC.split("def render_panopto_summary", 1)[1][:2600]
    body = re.sub(r"^\s*#.*$", "", body, flags=re.M)   # comments quote the old text
    assert "_did_work" in body
    assert "if not _did_work:" in body, "the zero-suppression guard is gone"
    assert body.count("_did_work =") == 1, \
        "the two modes have diverged again - that is how download mode kept its zero"


def test_the_download_branch_no_longer_renders_on_found_alone():
    body = SRC.split("def render_panopto_summary", 1)[1][:2600]
    body = re.sub(r"^\s*#.*$", "", body, flags=re.M)
    assert "elif found <= 0:" not in body, \
        "`found` alone decides rendering again, so a size-skipped run shows 0"


@pytest.mark.parametrize("stat", ["downloaded", "transcribed", "failed"])
def test_every_work_signal_is_part_of_the_guard(stat):
    body = SRC.split("def render_panopto_summary", 1)[1][:2600]
    i = body.find("_did_work =")
    assert stat in body[i:i + 400], f"{stat} no longer counts as work"
