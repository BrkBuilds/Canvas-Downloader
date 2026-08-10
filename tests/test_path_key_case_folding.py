"""``_path_key`` must fold case on a case-INSENSITIVE volume, and only there.

``os.path.normcase`` is the IDENTITY off Windows, so the "case" half of
``_path_key``'s contract was a no-op on exactly the platform where it matters
most: macOS's default volume is case-INSENSITIVE. Probed on the audit hardware
2026-08-10 - both the home APFS volume and /tmp - so ``Notes.pdf`` and
``notes.pdf`` really are one file there, while the two spellings compared unequal.

The consequence is not a crash, which is why it sat open: the SAME physical file
reads as an untracked orphan (its walked name is not in the manifest key set) AND
as a missing row (its manifest name is not in the walked set), so a case-only
rename inflates the untracked count that the review screen exists to reconcile
against what the user sees in the folder.

Folding unconditionally is the trap, and it is why this was not a one-line
`.lower()`: a case-SENSITIVE volume - an ordinary external drive - genuinely holds
both names as two files, and folding there would merge two manifest rows and
mis-bind a heal. So the fold is gated on a cheap read-only probe that answers
False on any doubt, which is the previous behaviour exactly.

Both directions were verified on REAL volumes, not simulations: the home volume
(insensitive), and a case-sensitive APFS image created with hdiutil, where
`Notes.pdf` and `notes.pdf` coexist as two files and the keys correctly stay
distinct.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import sync_manager as SM  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """The probe is lru_cached per directory, so a monkeypatched verdict from one
    test would leak into the next."""
    SM._probe_case_insensitive.cache_clear()
    yield
    SM._probe_case_insensitive.cache_clear()


def test_case_only_spellings_collapse_on_a_case_insensitive_volume(
        tmp_path, monkeypatch):
    monkeypatch.setattr(SM, "_case_insensitive_volume", lambda p: True)
    if os.name == "nt":
        pytest.skip("normcase already folds on Windows - nothing added to test")
    assert SM._path_key(tmp_path / "Notes.pdf") == SM._path_key(tmp_path / "notes.pdf")
    assert SM._path_key(tmp_path / "A/B/Notes.pdf") == SM._path_key(tmp_path / "a/b/notes.pdf")


def test_case_only_spellings_stay_DISTINCT_on_a_case_sensitive_volume(
        tmp_path, monkeypatch):
    """THE guard. Merging these would mis-bind a heal on an external drive."""
    monkeypatch.setattr(SM, "_case_insensitive_volume", lambda p: False)
    assert SM._path_key(tmp_path / "Notes.pdf") != SM._path_key(tmp_path / "notes.pdf")


def test_genuinely_different_names_never_collapse(tmp_path, monkeypatch):
    monkeypatch.setattr(SM, "_case_insensitive_volume", lambda p: True)
    assert SM._path_key(tmp_path / "Notes.pdf") != SM._path_key(tmp_path / "Other.pdf")


def test_the_probe_answers_FALSE_when_the_flip_is_a_NO_OP():
    """A path with no letters ANYWHERE makes the swapcase trick trivially true -
    samefile(x, x) - so it has to be refused rather than read as 'insensitive'.

    Note the letters can come from any component, not just the last: a numeric
    directory under /private/var/... still flips, and there the probe genuinely
    IS answering about the volume, correctly. This is the narrow case where it
    cannot answer at all.
    """
    assert SM._probe_case_insensitive("/") is False
    assert SM._probe_case_insensitive("/12345") is False


def test_the_probe_never_raises_on_a_missing_or_odd_path():
    """It runs inside the sync's comparison loops; an exception there would take
    out the analysis for the whole course."""
    for bad in ("/no/such/directory/at/all", "", "\x00broken", "relative/thing"):
        assert SM._case_insensitive_volume(bad) is False


def test_path_key_still_normalises_the_other_two_things(tmp_path, monkeypatch):
    """The fold must not have displaced NFC or normpath."""
    monkeypatch.setattr(SM, "_case_insensitive_volume", lambda p: False)
    import unicodedata
    nfc = unicodedata.normalize("NFC", "Måned.pdf")
    nfd = unicodedata.normalize("NFD", "Måned.pdf")
    assert nfc != nfd, "fixture is not actually testing normalisation"
    assert SM._path_key(tmp_path / nfc) == SM._path_key(tmp_path / nfd)
    assert SM._path_key(f"{tmp_path}/a/../b.pdf") == SM._path_key(tmp_path / "b.pdf")


@pytest.mark.skipif(sys.platform != "darwin", reason="probes the real volume")
def test_the_real_default_macos_volume_is_detected_as_insensitive(tmp_path):
    """Not a tautology: it is what makes the fix reach anyone. If a future macOS
    ships a case-sensitive default this fails, which is the right signal."""
    assert SM._probe_case_insensitive(str(tmp_path)) is True
