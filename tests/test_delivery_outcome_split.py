"""What Canvas declines to serve is not a failure of the download.

Two outcomes are permanent facts about a course rather than problems with a
run: a file the teacher locked, and a video Canvas streams through a plugin
instead of storing as a file. No retry, no setting and no amount of waiting
changes either.

Counting them as errors made every download of course 43660 - which carries two
permanently-locked files - render amber "Partial Success", for ever. A colour
that appears on a healthy run is a colour users learn to ignore, which costs
exactly the runs where it means something.

The rule has to be identical in both flows, and they carry different shapes:
the download flow has ``DownloadError`` objects, the sync flow has plain
strings. One classifier handles both, off constants the producers share.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from shared.helpers import (  # noqa: E402
    LOCKED_FILE_ERROR_TYPE, LOCKED_FILE_REASON,
    LTI_STREAM_ERROR_TYPE, LTI_STREAM_REASON,
    split_delivery_errors,
)


class _Err:
    """Enough of DownloadError for the classifier."""

    def __init__(self, error_type="HTTP 500", *, is_app_error=False,
                 filepath="C:/x/y.pdf", retry_exhausted=False):
        self.error_type = error_type
        self.is_app_error = is_app_error
        self.retry_exhausted = retry_exhausted
        self.context = {"filepath": filepath} if filepath else {}


# --------------------------------------------------------------------------
# the download flow's objects
# --------------------------------------------------------------------------

def test_a_locked_file_is_not_a_failure():
    s = split_delivery_errors([_Err(LOCKED_FILE_ERROR_TYPE, retry_exhausted=True)])
    assert s["retriable"] == 0 and s["app"] == 0
    assert s["unresolvable"] == 1 and s["reasons"]["locked"] == 1


def test_an_lti_stream_is_not_a_failure():
    s = split_delivery_errors([_Err(LTI_STREAM_ERROR_TYPE)])
    assert s["retriable"] == 0
    assert s["unresolvable"] == 1 and s["reasons"]["stream"] == 1


def test_a_real_file_error_is_still_retriable():
    """The direction that must NOT change: a genuine failure still colours the
    card, or this whole change would trade a false alarm for a silent one."""
    s = split_delivery_errors([_Err("HTTP 500")])
    assert s["retriable"] == 1 and s["unresolvable"] == 0


def test_an_app_error_is_counted_separately():
    s = split_delivery_errors([_Err("Processing Error", is_app_error=True)])
    assert s["app"] == 1 and s["retriable"] == 0 and s["unresolvable"] == 0


def test_a_permanently_stuck_file_with_no_named_cause_is_unresolvable_but_generic():
    """`retry_exhausted` with no recognised type: a retry cannot help, so it is
    not retriable - but we have not established WHY, and claiming a cause we
    did not measure is worse than admitting we do not know."""
    s = split_delivery_errors([_Err("No URL", retry_exhausted=True)])
    assert s["unresolvable"] == 1
    assert s["reasons"]["other"] == 1
    assert s["reasons"]["locked"] == 0 and s["reasons"]["stream"] == 0


def test_an_error_with_nowhere_to_retry_to_is_not_retriable():
    s = split_delivery_errors([_Err("Missing Page URL", filepath=None)])
    assert s["retriable"] == 0 and s["unresolvable"] == 1


# --------------------------------------------------------------------------
# the sync flow's strings
# --------------------------------------------------------------------------

def test_the_sync_flow_classifies_its_own_sentences():
    """Sync errors are list[str]. Before this they were counted as retriable
    wholesale, so a locked file turned a clean sync amber there too."""
    s = split_delivery_errors([
        f"Error syncing notes.pdf: {LOCKED_FILE_REASON}",
        f"Error syncing lecture.mp4: {LTI_STREAM_REASON}",
        "Error syncing slides.pptx: Connection reset",
    ])
    assert s["unresolvable"] == 2
    assert s["reasons"] == {"locked": 1, "stream": 1, "other": 0}
    assert s["retriable"] == 1


def test_the_constants_are_what_the_sync_engine_actually_writes():
    """The classifier matches on text, so the producer must use the SAME
    constants - inlining the sentence at the producer would let a reword
    silently reclassify every locked file as a hard failure."""
    src = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    assert "err_msg = LOCKED_FILE_REASON" in src
    assert "err_msg = LTI_STREAM_REASON" in src


# --------------------------------------------------------------------------
# the headline
# --------------------------------------------------------------------------

def _variant(synced, *, retriable=0, unresolvable=0, app=0, error_count=None):
    """Re-derive the card variant the way render_completion_card does."""
    ec = error_count if error_count is not None else (retriable + unresolvable + app)
    has_split = (retriable or unresolvable or app)
    blocking = (retriable + app) if has_split else ec
    if synced == 0 and blocking > 0:
        return "failure"
    if blocking > 0:
        return "partial"
    if synced > 0:
        return "success"
    if unresolvable > 0:
        return "nothing-downloadable"
    return "up-to-date"


def test_a_run_whose_only_problem_is_locked_files_is_a_success():
    assert _variant(143, unresolvable=2) == "success"


def test_a_run_with_a_real_failure_is_still_partial():
    assert _variant(143, retriable=1, unresolvable=2) == "partial"


def test_an_app_error_still_colours_the_card():
    assert _variant(143, app=1) == "partial"


def test_nothing_downloaded_and_everything_declined_is_not_up_to_date():
    """The edge this change opens: without its own branch, a course where every
    file was locked fell through to "All Up to Date - nothing to download",
    which is the one reading that is definitely false."""
    assert _variant(0, unresolvable=3) == "nothing-downloadable"


def test_a_genuinely_empty_run_is_still_up_to_date():
    assert _variant(0) == "up-to-date"


def test_a_caller_with_no_split_still_reports_its_errors():
    """Backwards safety: an unmigrated call site must not go silently green."""
    assert _variant(5, error_count=3) == "partial"


def test_size_skips_never_reach_the_error_count():
    """They travel on their own progress channel (`progress_type='size_skipped'`)
    and are rendered from `size_skipped_files`, so they were never part of the
    headline - asserted so a future refactor cannot quietly fold them in."""
    src = (REPO / "app.py").read_text(encoding="utf-8")
    assert "elif progress_type == 'size_skipped':" in src
    assert "size_skipped_files" in src


# --------------------------------------------------------------------------
# shapes this function cannot read
# --------------------------------------------------------------------------

def test_an_unreadable_error_shape_counts_as_a_FAILURE():
    """app.py already guards for `isinstance(err, dict)` in the retry pass, so
    a non-DownloadError entry is not hypothetical.

    The two mistakes are not symmetric. Calling a harmless outcome a failure
    shows an amber card the user investigates and dismisses; calling a failure
    harmless hides it behind a green one. When the shape cannot be read, the
    safe guess is the loud one.
    """
    s = split_delivery_errors([{"message": "something went wrong"}])
    assert s["retriable"] == 1
    assert s["unresolvable"] == 0, "an unreadable entry must not read as 'declined'"


def test_a_None_entry_does_not_crash_or_go_silent():
    s = split_delivery_errors([None])
    assert s["retriable"] == 1 and s["unresolvable"] == 0


def test_an_empty_list_is_all_zeros():
    s = split_delivery_errors([])
    assert s == {"retriable": 0, "unresolvable": 0, "app": 0,
                 "reasons": {"locked": 0, "stream": 0, "other": 0}}


def test_None_instead_of_a_list_is_tolerated():
    """Called straight off session state, which can be unset on the first run."""
    assert split_delivery_errors(None)["retriable"] == 0
