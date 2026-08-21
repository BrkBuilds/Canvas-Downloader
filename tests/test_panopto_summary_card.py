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


# THE REAL DECISION, not a mirror of it. This used to be a hand-copied
# reimplementation ("mirrored from render_panopto_summary"), and a copy passes
# happily while the shipped guard is wrong - measured 2026-08-20, when reverting
# the real guard failed only the source-text checks and none of the behavioural
# ones. The rule now lives in ONE module-level function and both test files
# import it.
from shared.components import panopto_summary_has_outcome as would_render  # noqa: E402


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


def test_sync_selection_alone_is_NOT_work():
    """REVERSED 2026-08-20, deliberately - this used to assert the opposite.

    The old rule ("a selection means the user asked for something") is how a
    success card made entirely of zeros reached the completion screen: the
    operator synced course 43660 with a folder configured for txt/srt and no
    transcription model, so 36 recordings were selected, nothing was produced,
    and the card read "36 processed / 0 DOWNLOADED / 0 TRANSCRIBED". Selecting
    is not producing. Product owner's call the same day: hide it.
    """
    assert not would_render(
        {"found": 36, "uptodate": 30, "selected": 6, "downloaded": 0})


# --------------------------------------------------------------------------
# the implementation still carries the rule
# --------------------------------------------------------------------------

def _guard_src() -> str:
    """The extracted guard's source, comments stripped.

    Anchored on the FUNCTION, not on a byte offset inside the renderer: the rule
    was moved out of `render_panopto_summary` on 2026-08-20 and these checks all
    reported it as MISSING, which is the "brittle anchor reads like a missing
    guard" trap this repo has paid for before. The guard had in fact got
    stronger.
    """
    body = SRC.split("def panopto_summary_has_outcome", 1)[1]
    body = body.split("\ndef ", 1)[0]
    return re.sub(r"^\s*#.*$", "", body, flags=re.M)


def test_the_guard_is_shared_by_both_modes():
    # ONE rule, asked once. Two would be how download mode kept its zero.
    assert SRC.count("def panopto_summary_has_outcome") == 1
    renderer = SRC.split("def render_panopto_summary", 1)[1][:2600]
    assert "panopto_summary_has_outcome(" in renderer, \
        "the renderer no longer delegates to the shared guard"
    # Behavioural, because that is what "shared" has to mean: the SAME produced-
    # nothing summary is suppressed whichever mode it came from.
    assert not would_render({"found": 36, "downloaded": 0, "transcribed": 0,
                             "failed": 0})
    assert not would_render({"found": 36, "uptodate": 0, "selected": 36,
                             "downloaded": 0, "transcribed": 0, "failed": 0})


def test_the_download_branch_no_longer_renders_on_found_alone():
    body = _guard_src()
    assert "elif found <= 0:" not in body, \
        "`found` alone decides rendering again, so a size-skipped run shows 0"


@pytest.mark.parametrize("stat", ["downloaded", "transcribed", "failed"])
def test_every_work_signal_is_part_of_the_guard(stat):
    """Behavioural, against the REAL guard - a source scan cannot tell whether a
    signal that is merely MENTIONED actually counts."""
    assert would_render({"found": 5, "uptodate": 0, stat: 1}) is True, \
        f"{stat} no longer counts as work"
    assert would_render({"found": 5, "uptodate": 0, stat: 0}) is False
