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
    if os.name == "nt":
        # Not merely untestable here - FALSE BY DESIGN. `normcase` folds case
        # unconditionally on Windows, and `_path_key`'s own gate is written
        # `os.name != 'nt' and _case_insensitive_volume(...)`, so the patched
        # verdict is short-circuited before it is ever read. Windows models no
        # case-sensitive volume, so the property this guards does not exist
        # here; asserting it fails against CORRECT code.
        pytest.skip("normcase folds unconditionally on Windows; the gate is "
                    "os.name-guarded, so there is no case-sensitive case to test")
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

    "/" WAS ASSERTED HERE AND IS NOT ANY MORE, deliberately (2026-08-11). It only
    answered False because the old whole-path flip had no letters to flip - an
    accident of the implementation, not a decision. The probe now flips a CHILD
    entry (see the mount-point test below), which compares two DIFFERENT strings,
    so the trivially-true hazard this test is named for cannot arise there at all
    - and "/" then answers True, which on macOS is simply the correct answer for
    the root volume. Nothing in the product asks it: `_case_insensitive_volume`
    refuses a root ancestor outright, because reaching "/" means nothing below it
    existed (an unplugged drive), and that is covered by its own test.

    "/12345" still exercises exactly the stated hazard: it cannot be listed, so
    the fallback runs, and the fallback flip is a no-op.
    """
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


# ---------------------------------------------------------------------------
# A directory's own NAME lives on its PARENT volume
# ---------------------------------------------------------------------------

def test_the_probe_flips_a_CHILD_not_the_directory_itself():
    """Measured on macOS 26.6, 2026-08-11, against a real case-sensitive APFS
    image made with hdiutil (A.txt and a.txt coexisting on it, so the volume is
    genuinely case-sensitive):

        _case_insensitive_volume('/Volumes/CSens2/Notes.pdf')  ->  True   WRONG

    The cause is that the probe flipped the whole directory path, and a mount
    point's own name lives in /Volumes - which is on the case-INSENSITIVE root
    volume - so `samefile('/Volumes/CSens2', '/volumes/csens2')` is itself True
    and the probe answered about the wrong filesystem.

    It fails in the DANGEROUS direction: a True makes _path_key lower-case the
    path, so on a case-sensitive volume two genuinely distinct files collapse to
    one key, merging manifest rows and mis-binding a heal - exactly what this
    gate exists to prevent. Reachable when the course folder IS the mount point,
    i.e. sitting at the root of a case-sensitive external drive.

    A CHILD entry genuinely lives on the mounted volume, so flipping one asks
    the right filesystem. This test pins the mechanism without needing a real
    volume: the directory NAME is one that would flip-resolve, while the child
    would not."""
    seen = {}

    def fake_listdir(d):
        seen["listed"] = d
        return ["Report.pdf"]

    def fake_samefile(a, b):
        # The volume is case-SENSITIVE: only an exact match is the same file.
        return a == b

    orig_listdir, orig_samefile = SM.os.listdir, SM.os.path.samefile
    SM._probe_case_insensitive.cache_clear()
    try:
        SM.os.listdir = fake_listdir
        SM.os.path.samefile = fake_samefile
        assert SM._probe_case_insensitive("/Volumes/Drive") is False, (
            "the probe must ask about a CHILD, which lives on the mounted "
            "volume, not about the directory's own name")
        assert seen.get("listed") == "/Volumes/Drive", (
            "it never listed the directory, so it cannot have probed a child")
    finally:
        SM.os.listdir, SM.os.path.samefile = orig_listdir, orig_samefile
        SM._probe_case_insensitive.cache_clear()


def test_the_probe_still_says_yes_on_a_case_insensitive_volume_via_a_child():
    """The other direction: the fold must keep working where it is correct, or
    a case-only rename starts reading as an orphan again."""
    orig_listdir, orig_samefile = SM.os.listdir, SM.os.path.samefile
    SM._probe_case_insensitive.cache_clear()
    try:
        SM.os.listdir = lambda d: ["Report.pdf"]
        SM.os.path.samefile = lambda a, b: a.lower() == b.lower()
        assert SM._probe_case_insensitive("/Volumes/Drive") is True
    finally:
        SM.os.listdir, SM.os.path.samefile = orig_listdir, orig_samefile
        SM._probe_case_insensitive.cache_clear()


def test_a_caseless_or_empty_directory_falls_back_and_stays_safe():
    """No child with letters means no evidence from a child. Falling back to the
    old whole-path flip is right (it is correct everywhere but a mount point),
    and an unreadable directory must answer False rather than raise."""
    orig_listdir, orig_samefile = SM.os.listdir, SM.os.path.samefile
    SM._probe_case_insensitive.cache_clear()
    try:
        SM.os.listdir = lambda d: ["12345", "67890"]     # nothing to flip
        SM.os.path.samefile = lambda a, b: a.lower() == b.lower()
        assert SM._probe_case_insensitive("/Volumes/Drive") is True  # via fallback
        SM._probe_case_insensitive.cache_clear()
        def boom(d):
            raise OSError("unreadable")
        SM.os.listdir = boom
        SM.os.path.samefile = lambda a, b: (_ for _ in ()).throw(OSError())
        assert SM._probe_case_insensitive("/Volumes/Drive") is False
    finally:
        SM.os.listdir, SM.os.path.samefile = orig_listdir, orig_samefile
        SM._probe_case_insensitive.cache_clear()


def test_a_root_or_relative_ancestor_is_refused():
    """Both answer about the WRONG volume, and both used to be refused only by
    accident (the old flip was a no-op on "/" and ".").

    The root case is the one with teeth: an unplugged external drive gives
    /Volumes/Drive/Course/file.pdf with nothing below / existing, and answering
    "case-insensitive" from the boot volume would fold keys for a volume that
    may be case-SENSITIVE when it comes back."""
    assert SM._case_insensitive_volume("/12345/not/here") is False
    assert SM._case_insensitive_volume("relative/thing") is False
    assert SM._case_insensitive_volume("") is False


def test_a_relative_path_is_refused_even_when_an_ancestor_EXISTS(tmp_path, monkeypatch):
    """The root-ancestor guard alone does NOT cover this, which a mutation run
    showed: a relative path's anchor is "" (== Path(".")), so "relative/thing"
    happens to be caught by the root check. Give it a real existing ancestor that
    is not "." and only the is_absolute() guard stops it.

    It must stop it: the cwd is not where the course folder lives, so probing it
    answers about the wrong volume."""
    (tmp_path / "subdir").mkdir()
    monkeypatch.chdir(tmp_path)
    assert SM._case_insensitive_volume("subdir/Notes.pdf") is False


def test_a_caseless_child_is_SKIPPED_not_a_reason_to_stop_looking():
    """Also from a mutation run: with `continue` swapped for `break`, a directory
    whose first entry happens to be caseless ("12345") would abandon the child
    probe entirely and fall back to flipping the directory name - i.e. straight
    back to the mount-point bug, but only for folders that happen to start with a
    numeric file. Course folders are full of those."""
    orig_listdir, orig_samefile = SM.os.listdir, SM.os.path.samefile
    SM._probe_case_insensitive.cache_clear()
    probed = []
    try:
        SM.os.listdir = lambda d: ["12345", "Report.pdf"]

        def fake_samefile(a, b):
            probed.append(os.path.basename(a))
            return a == b                     # a case-SENSITIVE volume
        SM.os.path.samefile = fake_samefile
        assert SM._probe_case_insensitive("/Volumes/Drive") is False
        assert probed == ["Report.pdf"], (
            f"expected the caseless entry to be skipped and Report.pdf probed, "
            f"got {probed!r}")
    finally:
        SM.os.listdir, SM.os.path.samefile = orig_listdir, orig_samefile
        SM._probe_case_insensitive.cache_clear()


def test_an_EMPTY_mount_point_answers_False_not_True():
    """The child-flip's one blind spot: a directory with nothing to flip.

    MEASURED on macOS 26.6 against a real case-sensitive APFS image
    (`hdiutil create -fs "Case-sensitive APFS"`), probed while the volume was
    still EMPTY: the no-child fallback flipped `/Volumes/CDCaseSens`, resolved
    it against `/Volumes` - which is on the case-INSENSITIVE root volume - and
    returned True for a case-SENSITIVE drive.

    That is the merging direction: `_path_key` would then lower-case the path,
    so `Notes.pdf` and `notes.pdf` - two genuinely distinct files on such a
    volume - collapse to one manifest row. And `_probe_case_insensitive` is
    lru_cached, so the wrong answer is frozen for the session even after the
    first files land.

    Reachable because `_case_insensitive_volume` climbs to the nearest EXISTING
    ancestor: a course folder that does not exist yet on a freshly-formatted
    external drive resolves to the drive's root. Verified after the fix on both
    image types - sensitive answers False at every stage and keeps the two
    names apart; insensitive answers True once the folder holds a file and
    folds them.
    """
    orig_listdir, orig_samefile = SM.os.listdir, SM.os.path.samefile
    orig_ismount = SM.os.path.ismount
    SM._probe_case_insensitive.cache_clear()
    try:
        SM.os.listdir = lambda d: []                  # the empty volume
        SM.os.path.ismount = lambda d: True           # ...which is a mount point
        # The parent volume WOULD resolve the flipped name - that is the trap.
        SM.os.path.samefile = lambda a, b: True
        assert SM._probe_case_insensitive("/Volumes/CDCaseSens") is False, (
            "an empty mount point answered case-INSENSITIVE from its parent "
            "volume - this merges two distinct files into one manifest row")
    finally:
        SM.os.listdir, SM.os.path.samefile = orig_listdir, orig_samefile
        SM.os.path.ismount = orig_ismount
        SM._probe_case_insensitive.cache_clear()


def test_an_empty_ORDINARY_directory_still_uses_the_name_fallback():
    """The guard must be about mount points, not about emptiness.

    One level below a mount point the directory's own name lives on the SAME
    volume, so flipping it is sound - and that is the common case (an empty
    course folder inside a normal download directory). Refusing there would
    stop recognising case-only renames on every ordinary empty folder.
    """
    orig_listdir, orig_samefile = SM.os.listdir, SM.os.path.samefile
    orig_ismount = SM.os.path.ismount
    SM._probe_case_insensitive.cache_clear()
    try:
        SM.os.listdir = lambda d: []
        SM.os.path.ismount = lambda d: False
        SM.os.path.samefile = lambda a, b: True       # a case-insensitive volume
        assert SM._probe_case_insensitive("/Users/me/Downloads/Course") is True
    finally:
        SM.os.listdir, SM.os.path.samefile = orig_listdir, orig_samefile
        SM.os.path.ismount = orig_ismount
        SM._probe_case_insensitive.cache_clear()


def test_a_failing_ismount_is_treated_as_doubt():
    """`os.path.ismount` stats the path and its parent; on an unplugged drive
    or a permission-denied mount that can raise. Doubt answers False, which is
    the recoverable direction - a case-only rename goes unrecognised rather
    than two distinct files being merged."""
    orig_listdir, orig_ismount = SM.os.listdir, SM.os.path.ismount
    orig_samefile = SM.os.path.samefile
    SM._probe_case_insensitive.cache_clear()
    try:
        SM.os.listdir = lambda d: []

        def boom(_d):
            raise OSError("device not configured")
        SM.os.path.ismount = boom
        # The parent volume WOULD resolve the flipped name. Without this the
        # fall-through reaches a `samefile` that raises and returns False by
        # another route - so swapping the handler's `return False` for `pass`
        # survived the mutation pass, and the test proved nothing.
        SM.os.path.samefile = lambda a, b: True
        assert SM._probe_case_insensitive("/Volumes/Gone") is False, (
            "a failing ismount fell through to the parent-volume flip instead "
            "of answering doubt")
    finally:
        SM.os.listdir, SM.os.path.ismount = orig_listdir, orig_ismount
        SM.os.path.samefile = orig_samefile
        SM._probe_case_insensitive.cache_clear()
