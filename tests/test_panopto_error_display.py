"""A failed Panopto recording must name the LECTURE, in words a student reads.

Reported 2026-08-04: a Today quick-sync hit two recordings whose Panopto
sessions had been deleted. Sync History showed them as two files literally
called "Panopto" (so the user could not tell which lecture, nor find it in
Canvas), under the reason "This session isn't available. It may have been
deleted. See other videos" - Panopto's own operator copy, whose "See other
videos" is a dead link into Panopto's web UI that means nothing here.

Three faults, three guards:

1. The reason text is Panopto jargon plus a dangling dead-link phrase.
   ``friendly_stream_error`` rewrites the "recording is gone" family and drops
   the trailing "See other videos" from everything else.
2. The recording title was thrown away: the sync flow stored
   ``f"Panopto: {message}"``, hard-coding the name. It now stores the shared
   ``"Error syncing {name}: {reason}"`` protocol built from the error's own
   ``item_name`` - see the guard on sync_ui.py below.
3. Panopto titles routinely contain ": " ("Forelæsningsvideo (1):
   organisationsprojekt"), which that protocol's first-``": "`` split would
   mangle. The name is sanitized the way its saved folder is named (colon
   removed), so both parsers still recover the whole title.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from panopto.stream import friendly_stream_error  # noqa: E402


# The exact fragment Panopto returned for the deleted sessions in the report.
_RAW_DELETED = ("This session isn't available. It may have been deleted.<br>"
                "<a href='/Panopto/Pages/Sessions/List.aspx'>See other videos</a>")


# ── 1. the reason text ───────────────────────────────────────────────────────

def test_deleted_session_becomes_plain_student_facing_text():
    out = friendly_stream_error(_RAW_DELETED)
    assert "See other videos" not in out          # the dead link is gone
    assert "session" not in out.lower()            # Panopto's word, not a student's
    assert "no longer available" in out.lower()
    assert "deleted" in out.lower()                # the part the user found clear, kept
    assert "<" not in out and ">" not in out       # never any markup


def test_a_dangling_see_other_videos_is_dropped_from_other_errors():
    """Any Panopto error can carry the navigation link; strip its text even when
    the message itself is not one we rewrite."""
    raw = ("Access is denied. <a href='/Panopto/Pages/Sessions/List.aspx'>"
           "See other videos</a>")
    out = friendly_stream_error(raw)
    assert out == "Access is denied."


def test_ordinary_errors_pass_through_unchanged():
    assert friendly_stream_error("Connection timed out") == "Connection timed out"
    assert friendly_stream_error("") == ""


def test_friendly_stream_error_is_idempotent():
    once = friendly_stream_error(_RAW_DELETED)
    assert friendly_stream_error(once) == once


def test_deleted_session_returns_the_shared_classifier_constant():
    """The rewrite must be the exact constant split_delivery_errors matches on,
    or a deleted recording would render friendly but still count as a retriable
    failure (see tests/test_delivery_outcome_split.py)."""
    from shared.helpers import PANOPTO_UNAVAILABLE_REASON
    assert friendly_stream_error(_RAW_DELETED) == PANOPTO_UNAVAILABLE_REASON


# ── 2. the producer no longer hard-codes "Panopto" ───────────────────────────

def test_sync_flow_names_the_recording_not_the_word_panopto():
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    # The exact old bug: the message stored with a hard-coded "Panopto:" prefix
    # that discarded item_name.
    assert 'f"Panopto: {getattr(err' not in src
    # The fix: the shared protocol, built from the error's own item_name,
    # sanitized so the title is named the way its folder is.
    assert 'f"Error syncing {_name}: {_msg}"' in src
    assert "_sanitize_filename(_raw_name)" in src


# ── 3. the "Error syncing NAME: reason" protocol survives a colon ────────────

class _Dummy:
    """`CanvasManager._sanitize_filename` reads no instance state, so an unbound
    call with a throwaway self avoids a network-touching constructor."""


def test_error_protocol_recovers_a_title_that_contains_a_colon():
    from core.canvas_logic import CanvasManager

    title = "Forelæsningsvideo (1): organisationsprojekt - vidensproduktion"
    name = CanvasManager._sanitize_filename(_Dummy(), title)
    assert ":" not in name, "a colon in the name would mis-split the protocol"

    reason = friendly_stream_error(_RAW_DELETED)
    line = f"Error syncing {name}: {reason}"

    # completion screen (shared/components.py) - regex extract of the file name
    m = re.match(r"^\s*Error syncing (.+?):\s", line)
    assert m and m.group(1) == name

    # Sync History (sync_ui.py) - first ": " split, "Error syncing " stripped
    prefix, got_reason = line.split(": ", 1)
    assert prefix.replace("Error syncing ", "") == name
    assert got_reason == reason
    # the whole lecture title is recovered, not a fragment cut at the colon
    assert "vidensproduktion" in m.group(1)
