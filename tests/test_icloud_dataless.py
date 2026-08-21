"""What makes the engine safe on an iCloud "Optimize Mac Storage" folder.

A student on a small-SSD Mac has macOS EVICT their course files: the name and
size stay, the bytes do not (``st_blocks == 0``), and the first process to READ
one silently downloads it again. So on such a folder, hashing a file is not
cheap - it is a network fetch and a disk refill, and it undoes the very setting
the student turned on.

MEASURED on macOS 26.6.1 with a real iCloud account, 2026-08-20:

    analysis, nothing changed on Canvas   0 of 10 files materialised
    analysis, ONE genuine update          1 of 12   (only the changed one)
    heal_manifest after a RENAME          1 of 12   (only the renamed one)
    os.replace onto a dataless target     works, content correct
    read of a dataless file               correct md5, ~0.9-1.35 s, classify 'clean'

macOS 26 uses DATALESS FILES, not ``.icloud`` placeholder stubs, so an evicted
file does NOT read as missing-plus-untracked.

**The engine passes because of properties nothing was pinning.** Folder walks
take ``stat().st_size`` and never open the file; candidate md5s are explicitly
lazy; and the update path hashes only files ``_is_canvas_newer`` already
selected. None of that was a stated contract, so a reasonable refactor - "just
hash everything up front, it's simpler" - would silently turn every sync into a
full re-download for these users, and no existing test would fail.

These tests are that contract. They are PORTABLE on purpose: they count calls to
``compute_local_md5`` rather than needing iCloud, so they hold the line on
Windows and CI too, where the failure they prevent is invisible.
"""
from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import core.sync_manager as SM  # noqa: E402
from core.sync_manager import CanvasFileInfo, SyncManager  # noqa: E402


class _HashCounter:
    """Counts every byte-reading hash the engine performs.

    On an evicted folder each of these is a materialisation: a network fetch
    plus a disk refill. The count IS the cost.
    """

    def __init__(self, monkeypatch):
        self.paths: list[str] = []
        real = SM.compute_local_md5

        def spy(filepath):
            self.paths.append(Path(filepath).name)
            return real(filepath)

        monkeypatch.setattr(SM, "compute_local_md5", spy)
        # The staticmethod delegates to the module-level name, but bind it too
        # so a caller reaching it through the class is also counted.
        monkeypatch.setattr(SyncManager, "compute_local_md5", staticmethod(spy))

    @property
    def n(self) -> int:
        return len(self.paths)


@pytest.fixture
def course(tmp_path):
    """A folder of 10 tracked files, exactly as a completed sync leaves it."""
    folder = tmp_path / "Course"
    folder.mkdir()
    sm = SyncManager(str(folder), 4242, "iCloud contract")
    man = sm.load_manifest()
    files = []
    for i in range(1, 11):
        p = folder / f"Lecture {i:02d}.pdf"
        body = b"%PDF-1.4\n" + (f"lecture {i} ".encode() * (500 + i))
        p.write_bytes(body)
        cf = CanvasFileInfo(id=5000 + i, filename=p.name, display_name=p.name,
                            size=p.stat().st_size,
                            modified_at="2020-01-01T00:00:00Z",
                            url=f"https://example/{i}", content_sig=f"sig{i}")
        man = sm.add_file_to_manifest(man, cf, p.name,
                                      local_md5=hashlib.md5(body).hexdigest())
        files.append(p)
    return sm, folder, files


def _canvas(files, *, changed_index=None):
    """Canvas's view. A changed file must differ in SIZE, not just timestamp:
    `_is_canvas_newer` deliberately treats same-size-newer-timestamp as a
    metadata touch, so a timestamp-only 'change' produces no update at all -
    which is how an earlier version of this measurement fooled itself."""
    out = []
    for i, p in enumerate(files, start=1):
        ch = (changed_index == i)
        out.append(CanvasFileInfo(
            id=5000 + i, filename=p.name, display_name=p.name,
            size=p.stat().st_size + (777 if ch else 0),
            modified_at="2030-01-01T00:00:00Z" if ch else "2020-01-01T00:00:00Z",
            url=f"https://example/{i}", content_sig=f"sig{i}"))
    return out


# --------------------------------------------------------------------------
# the contract
# --------------------------------------------------------------------------

def test_analysing_an_unchanged_course_hashes_NOTHING(course, monkeypatch):
    """THE headline property. Every hash here would be a re-download for a
    student whose folder macOS has evicted to free space."""
    sm, _folder, files = course
    spy = _HashCounter(monkeypatch)
    res = sm.analyze_course(_canvas(files), sm.load_manifest())
    assert len(res.uptodate_files) == len(files)
    assert spy.n == 0, (
        f"analysis hashed {spy.n} file(s) with nothing to do ({spy.paths}) - on "
        f"an evicted iCloud folder that is {spy.n} silent re-downloads")


def test_a_genuine_update_hashes_ONLY_the_changed_file(course, monkeypatch):
    """Hashing the updated file is REQUIRED - it is how an edited local copy is
    told from a clean one, which is what `_NewVersion` protection rests on. What
    must not happen is hashing its neighbours."""
    sm, _folder, files = course
    spy = _HashCounter(monkeypatch)
    res = sm.analyze_course(_canvas(files, changed_index=5), sm.load_manifest())
    assert len(res.updated_files) == 1, "the fixture stopped producing an update"
    assert spy.n <= 1, f"hashed {spy.n} files for ONE update: {spy.paths}"
    if spy.n:
        assert spy.paths == ["Lecture 05.pdf"]


def test_healing_a_renamed_file_does_not_hash_the_whole_folder(course, monkeypatch):
    """The orphan matcher falls back to size/md5 when the NAME no longer
    matches. If it hashed every candidate, one broken row would cost an evicted
    student their entire folder."""
    sm, _folder, files = course
    files[4].rename(files[4].with_name("Week 05 - renamed.pdf"))
    man = sm.load_manifest()
    man["files"].pop(str(5000 + 5), None)
    spy = _HashCounter(monkeypatch)
    sm.heal_manifest(man)
    assert spy.n <= 2, (
        f"heal hashed {spy.n} of {len(files)} files ({spy.paths}) - the size "
        f"prefilter must keep this proportional to the DAMAGE, not the folder")


def test_the_folder_walks_stat_and_never_read(course):
    """A `stat` leaves a dataless file dataless; opening it materialises it.

    AST-checked because it is a property of the LOOP, and the cheapest possible
    regression ("just read it while we're here") is invisible in review.
    """
    src = (REPO / "core" / "sync_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    walks = [n for n in ast.walk(tree)
             if isinstance(n, ast.For) and isinstance(n.iter, ast.Call)
             and getattr(n.iter.func, "attr", None) == "walk"]
    assert walks, "no os.walk loops found - has the scan been rewritten?"
    banned = {"read_bytes", "read_text", "open"}
    for w in walks:
        called = {getattr(c.func, "attr", getattr(c.func, "id", None))
                  for c in ast.walk(w) if isinstance(c, ast.Call)}
        leaked = banned & called
        assert not leaked, (
            f"a folder walk calls {sorted(leaked)} - that materialises every "
            f"evicted file it touches")
        assert "stat" in called, "the walk no longer sizes files with stat()"


def test_an_unreadable_file_is_preserved_not_overwritten(tmp_path):
    """A materialisation that FAILS (offline, quota, a stalled daemon) must
    never read as 'clean'. `compute_local_md5` returns None on any OSError and
    the classifier biases to 'modified', which forks to `_NewVersion` - the
    local copy is preserved. Losing it would be silent data loss."""
    p = tmp_path / "Lecture.pdf"
    p.write_bytes(b"%PDF-1.4\nlocal\n")
    good = hashlib.md5(p.read_bytes()).hexdigest()
    assert SyncManager._classify_local_modification(p, good) == "clean"

    import unittest.mock as mock
    with mock.patch.object(SM, "compute_local_md5", return_value=None):
        assert SyncManager._classify_local_modification(p, good) == "modified"


def test_compute_local_md5_swallows_every_OSError_not_just_permission():
    """A failed materialisation surfaces as EIO/ETIMEDOUT, not PermissionError.
    Narrowing this handler would let it escape into `analyze_course`, which has
    no try around the call and would abort the whole course."""
    fn = next(n for n in ast.walk(ast.parse(
        (REPO / "core" / "sync_manager.py").read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef) and n.name == "compute_local_md5")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    caught = {getattr(h.type, "id", None) for h in handlers}
    assert "OSError" in caught, (
        f"compute_local_md5 catches {caught or '{}'} - a failed iCloud "
        f"materialisation raises OSError subclasses other than PermissionError")
