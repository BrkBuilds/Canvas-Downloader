"""A transcript-only run must not show a "0 Downloaded" box.

FOUND BY THE OPERATOR on the real completion screen, macOS 26.6.1, 2026-08-20:
course 43660 synced with a folder contract asking for **txt + srt only** and no
transcription model installed rendered

    Panopto Recordings - 36 processed
    [ 0 DOWNLOADED ]   [ 0 TRANSCRIBED ]

`summary["downloaded"]` is only ever advanced `if res.kept_any`, and the
runner's own comment says it "counts recordings with a kept media file
(mp4/mp3)". txt/srt are produced by TRANSCRIPTION - the audio that feeds it is
discarded - so a transcript-only run can never advance it. The box was therefore
a structurally impossible zero, which is the exact misreading `want_media` was
added to prevent for link-only runs.

THE CAUSE IS A SHARED CONSTANT ANSWERING TWO QUESTIONS. `want_media` asked
`MEDIA_KINDS`, whose own docstring scopes it to "which kinds cost bandwidth" -
true for txt/srt, because the audio must be fetched. That is the right answer
for the auth bootstrap and the size estimator and the wrong one for a display
flag. Same shape as this repo's other divergent-primitive bugs (the LTI-stream
set vs the size-mismatch set; `.pdf` in `file_in_scope`): two same-looking lists
that must not be merged.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from panopto.shortcut import DOWNLOADED_KINDS, MEDIA_KINDS  # noqa: E402


def _want_media(contract: dict) -> bool:
    """The runner's expression, evaluated against one target's settings."""
    return any(contract.get("output_" + k) for k in DOWNLOADED_KINDS)


TRANSCRIPT_ONLY = {"output_mp4": False, "output_mp3": False, "output_url": False,
                   "output_txt": True, "output_srt": True}


def test_a_transcript_only_contract_does_not_want_the_downloaded_box():
    assert _want_media(TRANSCRIPT_ONLY) is False, (
        "a txt/srt-only run can never advance summary['downloaded'], so the "
        "Downloaded box would show a structurally impossible zero")


@pytest.mark.parametrize("kind", ["mp4", "mp3"])
def test_a_media_contract_still_wants_the_downloaded_box(kind):
    c = dict(TRANSCRIPT_ONLY, **{"output_" + kind: True})
    assert _want_media(c) is True


def test_a_shortcut_only_contract_does_not_want_it_either():
    """The case `want_media` was originally added for - kept working."""
    c = {"output_mp4": False, "output_mp3": False, "output_txt": False,
         "output_srt": False, "output_url": True}
    assert _want_media(c) is False


def test_the_two_kind_sets_are_NOT_the_same_and_differ_by_exactly_txt_and_srt():
    """Merging them re-opens this bug in one direction or the auth bootstrap in
    the other, and both failures are silent."""
    assert DOWNLOADED_KINDS != MEDIA_KINDS
    assert set(MEDIA_KINDS) - set(DOWNLOADED_KINDS) == {"txt", "srt"}
    assert set(DOWNLOADED_KINDS) <= set(MEDIA_KINDS)


def test_want_media_is_computed_from_DOWNLOADED_KINDS_in_the_real_runner():
    """Anchored on the CALL, via AST - a leftover `MEDIA_KINDS` import keeps the
    name in the file, so a substring test passes against the reverted code."""
    tree = ast.parse((REPO / "panopto" / "runner.py").read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        t = node.targets[0]
        if not (isinstance(t, ast.Subscript)
                and isinstance(t.slice, ast.Constant)
                and t.slice.value == "want_media"):
            continue
        found.append({n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)})
    assert found, "no `summary['want_media'] = ...` assignment in runner.py"
    for names in found:
        assert "DOWNLOADED_KINDS" in names, (
            "want_media must be computed from DOWNLOADED_KINDS")
        assert "MEDIA_KINDS" not in names, (
            "want_media must NOT read MEDIA_KINDS - it includes txt/srt")


# ---------------------------------------------------------------------------
# ...and the CARD ITSELF must not render when the run produced nothing.
#
# Same operator report, same screen. The guard's sync clause was `selected`, so
# merely SELECTING recordings counted as having done work - which is how a
# success card made entirely of zeros reached the completion screen. Product
# owner's call 2026-08-20: hide it.
#
# `selected` was failing its own case in the opposite direction too:
# sync/execution.py writes the all-up-to-date summary with 'selected': 0
# specifically so the card can "surface the up-to-date count", and 0 is falsy,
# so the guard hid the one card that summary exists to produce. Keying on
# `uptodate` fixes both directions.
from shared.components import panopto_summary_has_outcome as _renders  # noqa: E402


PRODUCED_NOTHING = {"found": 36, "selected": 36, "uptodate": 0, "downloaded": 0,
                    "transcribed": 0, "shortcuts": 0, "failed": 0, "courses": 1,
                    "want_transcription": True}


def test_a_sync_that_produced_nothing_hides_the_card():
    assert _renders(PRODUCED_NOTHING) is False, (
        "36 selected, nothing produced - the card would be a success panel made "
        "entirely of zeros")


def test_an_all_up_to_date_sync_ALSO_hides_the_card():
    """Same rule, not an exception to it.

    An intermediate version of this fix keyed the sync clause on `uptodate`
    instead of `selected`, which would have SHOWN this card - and that is the
    very shape being suppressed, because it renders a zero stat plus an "N
    already up to date" subtitle. `tests/test_panopto_summary_card.py` already
    asserted it must hide, and it was right.

    Consequence worth knowing: the fallback summary `sync/execution.py` writes
    when every recording is current now has nothing to render. That is by
    design, not by accident.
    """
    assert _renders({"found": 0, "downloaded": 0, "transcribed": 0, "skipped": 0,
                     "failed": 0, "courses": 0, "selected": 0,
                     "uptodate": 12}) is False


@pytest.mark.parametrize("field", ["downloaded", "transcribed", "shortcuts", "failed"])
def test_any_real_outcome_still_shows_the_card(field):
    assert _renders(dict(PRODUCED_NOTHING, **{field: 1})) is True


def test_download_mode_is_unchanged_by_the_sync_clause():
    """No 'uptodate' key at all -> not sync; the found<=0 rule still governs.

    The middle case is the DISCRIMINATING one and the first version of this test
    lacked it: `found=0, downloaded=0` is already rejected by the produced-
    nothing guard, so deleting the `found <= 0` rule left every assertion here
    passing. The mutation pass is what exposed that - it needs a summary that
    PRODUCED something while reporting nothing found.
    """
    assert _renders({"found": 0, "downloaded": 0, "transcribed": 0,
                     "failed": 0}) is False
    assert _renders({"found": 0, "downloaded": 3}) is False
    assert _renders({"found": 5, "downloaded": 2}) is True


def test_the_guard_in_the_real_module_keys_on_uptodate_not_selected():
    """AST-anchored as well as behavioural: `selected` is still computed for the
    subtitle, so a substring test would pass against the reverted code."""
    src = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef)
              and n.name == "panopto_summary_has_outcome")
    consts = {c.value for c in ast.walk(fn)
              if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    assert "uptodate" in consts, "the guard must key on uptodate"
    assert "selected" not in consts, (
        "the guard must NOT key on selected - selecting produces nothing")


def test_the_renderer_delegates_to_that_ONE_function():
    """The extraction is the point: a copy of this rule in the renderer would
    drift, and a copy in THIS FILE would pass while the shipped guard is wrong -
    which is exactly what the first version of these tests did."""
    src = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "render_panopto_summary")
    calls = {getattr(c.func, "id", getattr(c.func, "attr", None))
             for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "panopto_summary_has_outcome" in calls
