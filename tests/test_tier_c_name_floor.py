"""Auto-discovery tier (c) must not bind a file on size and extension alone.

Found by the live audit on 2026-07-27. Tier (c) adopts an untracked on-disk file
when exactly one orphan shares the Canvas file's size AND extension. It compared
no names and no content, so a planted file of identical byte-length but entirely
unrelated content was silently bound to a deleted Canvas file: the real file was
never re-offered as New and the student kept junk under its manifest row.

Tier (b) - the md5 content match - was supposed to catch that first, but Canvas
publishes md5 for **0 of 140 files** on the reference course, so tier (b) never
fires and tier (c) was running with no corroboration at all.

The fix is a stem-CONTAINMENT floor, and the choice of containment over a
similarity ratio is measured, not inherited. ``heal_manifest`` Tier 3 pairs
containment with ``ratio >= 0.90``; on real rename shapes that ratio is the
wrong instrument, and these tests pin the evidence so nobody "simplifies" the
floor back into a ratio:

    Intro          -> Intro_v2               contained,     ratio 0.857
    Lecture 1      -> Lecture 1 (annotated)  contained,     ratio 0.684
    Lecture1       -> Lecture2               NOT contained, ratio 0.917

A 0.90 floor rejects the genuine renames and passes the substitution.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.sync_manager import (  # noqa: E402
    _TIER_C_MIN_RATIO, _TIER_C_MIN_STEM, _match_key, _name_floor_reject,
)


class _CanvasFile:
    """Minimal stand-in - the floor only reads names and the id."""

    def __init__(self, filename, display_name=None, fid=1):
        self.id = fid
        self.filename = filename
        self.display_name = display_name or filename
        self.name_locked = False


def _cand(name):
    return {"path": Path("/course/Module 1") / name, "size": 1000, "md5": None}


def _allows(canvas_name, disk_name, display=None):
    return _name_floor_reject(_CanvasFile(canvas_name, display), _cand(disk_name)) == ""


# ------------------------------------------------------- genuine renames

@pytest.mark.parametrize("canvas,disk", [
    ("Lecture 1.pdf", "Lecture 1 (annotated).pdf"),
    ("Intro.pdf", "Intro_v2.pdf"),
    ("Forelaesning13.pptx", "Uge 7 Forelaesning13.pptx"),
    ("hints.html", "hints backup.html"),
    ("Kotter kap 1.pdf", "Kotter kap 1 - MINE NOTER.pdf"),
    # Case and separator differences are normalised away by _match_key.
    ("SQL Opgave Vejl.pdf", "sql_opgave_vejl.pdf"),
])
def test_adopts_recognisable_renames(canvas, disk):
    assert _allows(canvas, disk), f"{canvas!r} -> {disk!r} should still be adopted"


def test_matches_against_the_raw_filename_too():
    """Folders built by older versions carry the raw Canvas filename while a
    fresh download carries the display name; tier (a) checks both and so must
    this, or an old folder stops being recognised."""
    cf = _CanvasFile("Kotter+kap+1.pdf", display_name="Something Else Entirely.pdf")
    assert _name_floor_reject(cf, _cand("Kotter kap 1.pdf")) == ""


# ------------------------------------------------------- must be refused

@pytest.mark.parametrize("canvas,disk,why", [
    ("Gavelisten - Opgave.pdf", "decoy 0 unrelated.pdf", "the audit's decoy"),
    ("Lecture1.pdf", "Lecture2.pdf", "single-character substitution"),
    ("Kotter kap 1.pdf", "Kotter kap 2.pdf", "substitution inside a shared prefix"),
    ("SQL Opgave Vejl.pdf", "my own notes 3 - renamed.pdf", "unrecognisable"),
    ("Manual for eksamensprojekt 2025-2026.pdf", "Manual eksamen.pdf", "abbreviated"),
])
def test_refuses_unrelated_or_substituted_names(canvas, disk, why):
    reason = _name_floor_reject(_CanvasFile(canvas), _cand(disk))
    assert reason, f"{why}: {canvas!r} -> {disk!r} must NOT be adopted"


def test_refusal_explains_itself():
    """Every refusal is logged, so the reason has to be human-readable - a bare
    False would make 'why was this re-downloaded?' undiagnosable."""
    reason = _name_floor_reject(_CanvasFile("Gavelisten.pdf"),
                                _cand("decoy 0 unrelated.pdf"))
    assert "contains" in reason or "rename" in reason
    assert len(reason) > 20


# ------------------------------------------------------- the substance floor

def test_short_stems_are_not_evidence():
    """A two-character stem is contained in almost anything; containment there
    means nothing and would re-open the hole this floor closes."""
    assert not _allows("G4.pdf", "Assignment G4 solutions final.pdf")


def test_a_fragment_is_not_a_rename():
    """Containment with almost nothing in common is coincidence, not a rename."""
    long_name = "SEMESTER 3 ORGANISATION UGE 42 FORBEREDELSE OG NOTER notes.pdf"
    assert not _allows("notes.pdf", long_name)


def test_floor_constants_are_sane():
    assert _TIER_C_MIN_STEM >= 3
    assert 0.0 < _TIER_C_MIN_RATIO < 1.0


# ------------------------------------------------------- the calibration itself

@pytest.mark.parametrize("a,b,contained,ratio_above_90", [
    ("Intro.pdf", "Intro_v2.pdf", True, False),
    ("Lecture 1.pdf", "Lecture 1 (annotated).pdf", True, False),
    ("Forelaesning13.pptx", "Uge 7 Forelaesning13.pptx", True, False),
    ("Lecture1.pdf", "Lecture2.pdf", False, True),
    ("Kotter kap 1.pdf", "Kotter kap 2.pdf", False, True),
])
def test_containment_and_ratio_disagree_as_measured(a, b, contained, ratio_above_90):
    """Pins WHY the floor is containment-based.

    If this ever fails, the normalisation changed and the choice of instrument
    needs re-deriving - do not just update the expectations.
    """
    sa, sb = _match_key(Path(a).stem), _match_key(Path(b).stem)
    short, long = sorted((sa, sb), key=len)
    assert (short in long) is contained
    ratio = difflib.SequenceMatcher(None, _match_key(a), _match_key(b)).ratio()
    assert (ratio >= 0.90) is ratio_above_90, (
        f"{a} vs {b}: ratio {ratio:.3f}")


def test_a_ratio_only_floor_would_be_wrong():
    """The summary judgement: a 0.90 similarity floor gets the decisive cases
    exactly backwards, passing substitutions and rejecting real renames."""
    def ratio(a, b):
        return difflib.SequenceMatcher(None, _match_key(a), _match_key(b)).ratio()

    assert ratio("Lecture1.pdf", "Lecture2.pdf") >= 0.90            # would PASS
    assert not _allows("Lecture1.pdf", "Lecture2.pdf")              # we refuse

    assert ratio("Lecture 1.pdf", "Lecture 1 (annotated).pdf") < 0.90   # would FAIL
    assert _allows("Lecture 1.pdf", "Lecture 1 (annotated).pdf")        # we allow


def test_tier_c_call_site_is_gated():
    """The floor has to be wired into analyze_course, not merely exist."""
    import inspect
    from core.sync_manager import SyncManager
    src = inspect.getsource(SyncManager.analyze_course)
    assert "_name_floor_reject" in src
    i = src.index("_matched_tier = 'size_ext'")
    assert "_name_floor_reject" in src[:i], "floor must be checked BEFORE adopting"
