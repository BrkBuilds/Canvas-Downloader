"""CONSERVATION: every Canvas file the analyzer is given must reach a category.

This is the generalisation of two defects found on 2026-08-21, and the reason it
is written as an invariant rather than as two more regression tests: both were
instances of one class, neither was visible in review, and the class has more
members than anyone can enumerate by reading.

  1. `result.new_files` was rebuilt from `new_name_map`, a dict keyed by
     FILENAME. Of two Canvas files sharing a `filename` the loser of a
     `setdefault` was dropped from every category. Which one lost depended on
     the order Canvas listed them in.
  2. The phantom-row prune deleted a locally-deleted row that had CONSUMED a new
     Canvas file (the teacher-re-upload hand-over), and the file went with it -
     a file the user had never had, in no category at all.

Neither is a wrong CLASSIFICATION, which is what every other check in this suite
looks for. Both are a file that is simply *absent*: not new, not up to date, not
updated, not deleted anywhere. Nothing on the review screen can show a row that
was never produced, so the only way to see it is to count.

**The property.** Every `CanvasFileInfo` handed to `analyze_course` must appear
exactly once across:

    new_files · uptodate_files · updated_clean_files · updated_modified_files
    ignored_files · locally_deleted_files · deleted_on_canvas
    · riding on a locally-deleted row (`_reupload_new_file`)

...or be counted in `out_of_scope_files`, which is the one place the analyzer
legitimately declines to produce a row and says so with a number.

Both defects are caught by this property, measured: mutating the fix out again
makes the randomised sweep below report 49 and 15 losing seeds out of 600
respectively. A property test that passes on broken code is worth nothing, so
that control is part of the definition of this file working.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.sync_manager import CanvasFileInfo, SyncManager      # noqa: E402


# ---------------------------------------------------------------------------
# the accounting
# ---------------------------------------------------------------------------

def landed(res) -> dict[int, list[str]]:
    """``canvas id -> [categories it reached]``.

    `locally_deleted` and `deleted_on_canvas` ARE landing places for an input
    file - a row whose local file is gone is a legitimate answer about a file
    Canvas still has. Leaving them out is how the first version of this
    accounting reported a false loss, so they are listed explicitly rather than
    left to a reader's memory.
    """
    where: dict[int, list[str]] = {}

    def put(fid, cat):
        if fid is not None:
            where.setdefault(fid, []).append(cat)

    for f in res.new_files:
        put(f.id, "new")
    for f, _ in res.uptodate_files:
        put(f.id, "uptodate")
    for f, _ in res.updated_clean_files:
        put(f.id, "updated_clean")
    for f, _ in res.updated_modified_files:
        put(f.id, "updated_modified")
    for s in res.ignored_files:
        put(getattr(s, "canvas_file_id", None), "ignored")
    for s in res.locally_deleted_files:
        put(getattr(s, "canvas_file_id", None), "locally_deleted")
        rider = getattr(s, "_reupload_new_file", None)
        if rider is not None:
            put(rider.id, "rides_on_locally_deleted")
    for s in res.deleted_on_canvas:
        put(getattr(s, "canvas_file_id", None), "deleted_on_canvas")
    return where


def assert_conserved(res, canvas, label=""):
    where = landed(res)
    lost = [c.id for c in canvas if c.id not in where]
    assert len(lost) <= res.out_of_scope_files, (
        f"{label}: {lost} reached NO category "
        f"(out_of_scope={res.out_of_scope_files}). A file Canvas is offering "
        f"that the app mentions nowhere is invisible to the user and to every "
        f"oracle that reads a category.")
    inputs = {c.id for c in canvas}
    twice = {k: v for k, v in where.items() if len(v) > 1 and k in inputs}
    assert not twice, f"{label}: placed in two categories at once: {twice}"


def _cf(fid, filename, display=None, size=1000, when="2025-01-01T00:00:00Z"):
    return CanvasFileInfo(id=fid, filename=filename, display_name=display or filename,
                          size=size, modified_at=when, url="https://x/y")


def _row(fid, local, canvas_filename, size=1000, ignored=False, downloaded=True):
    return (str(fid), {
        "canvas_file_id": fid, "canvas_filename": canvas_filename,
        "local_path": local, "canvas_updated_at": "2025-01-01T00:00:00Z",
        "downloaded_at": "2025-01-02T00:00:00Z" if downloaded else "",
        "original_size": size, "is_ignored": ignored,
        "original_md5": "", "content_sig": ""})


def _run(tmp_path, canvas, rows=(), disk=(), mode="flat"):
    for rel, size in disk:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    sm = SyncManager(str(tmp_path), 43660)
    return sm.analyze_course(list(canvas), {"files": dict(rows)}, download_mode=mode)


# ---------------------------------------------------------------------------
# the two measured defects, as named shapes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("order", ["plain-first", "dedup-first"])
def test_two_canvas_files_sharing_one_filename(tmp_path, order):
    a = _cf(1, "X.pptx", "X.pptx")
    b = _cf(2, "X.pptx", "X-1.pptx")
    canvas = [a, b] if order == "plain-first" else [b, a]
    assert_conserved(_run(tmp_path, canvas), canvas, order)


def test_three_canvas_files_sharing_one_filename(tmp_path):
    canvas = [_cf(1, "X.jpg", "X-1.jpg"), _cf(2, "X.jpg", "X.jpg"),
              _cf(3, "X.jpg", "X-1-1.jpg")]
    assert_conserved(_run(tmp_path, canvas), canvas)


def test_a_reupload_consumed_by_a_row_that_is_then_pruned(tmp_path):
    """The second defect: two correct mechanisms, jointly wrong.

    Row 100 is gone from Canvas with its local file deleted, so it takes over
    new Canvas file 200 by name (M-6: respect the user's deletion). Row 101
    shares the basename in another folder and its file exists, so row 100 is
    pruned as superseded - and file 200, which the user has never had, went with
    it.
    """
    canvas = [_cf(101, "notes.pdf"), _cf(200, "notes.pdf", size=4321)]
    rows = dict([_row(100, "A/notes.pdf", "notes.pdf"),
                 _row(101, "B/notes.pdf", "notes.pdf")])
    res = _run(tmp_path, canvas, rows, [("B/notes.pdf", 1234)])
    assert_conserved(res, canvas)
    assert 200 in {f.id for f in res.new_files}, (
        "a file the user has never had must be OFFERED once the row that had "
        "taken it over is deleted")


# ---------------------------------------------------------------------------
# ordinary shapes - the property must not only hold for the bugs
# ---------------------------------------------------------------------------

def test_plain_new_files(tmp_path):
    canvas = [_cf(i, f"f{i}.pdf") for i in range(1, 6)]
    assert_conserved(_run(tmp_path, canvas), canvas)


def test_everything_tracked_and_present(tmp_path):
    canvas = [_cf(1, "a.pdf"), _cf(2, "b.pdf")]
    rows = dict([_row(1, "a.pdf", "a.pdf"), _row(2, "b.pdf", "b.pdf")])
    assert_conserved(_run(tmp_path, canvas, rows,
                          [("a.pdf", 1000), ("b.pdf", 1000)]), canvas)


def test_an_ignored_row(tmp_path):
    canvas = [_cf(1, "a.pdf"), _cf(2, "b.pdf")]
    rows = dict([_row(1, "a.pdf", "a.pdf", ignored=True), _row(2, "b.pdf", "b.pdf")])
    assert_conserved(_run(tmp_path, canvas, rows,
                          [("a.pdf", 1000), ("b.pdf", 1000)]), canvas)


def test_a_genuine_reupload_that_is_NOT_pruned(tmp_path):
    """The hand-over is legitimate and must keep working - the file is
    accounted for as a rider, not as a `new` row."""
    canvas = [_cf(200, "h.pdf")]
    res = _run(tmp_path, canvas, dict([_row(100, "h.pdf", "h.pdf")]))
    assert_conserved(res, canvas)
    assert 200 not in {f.id for f in res.new_files}
    assert any(getattr(d, "_reupload_new_file", None) is not None
               for d in res.locally_deleted_files)


def test_secondary_content_mixed_in(tmp_path):
    canvas = [_cf(1, "a.pdf"), _cf(-500, "Quiz X.html", size=0)]
    assert_conserved(_run(tmp_path, canvas), canvas)


def test_same_display_name_different_filenames(tmp_path):
    canvas = [_cf(1, "raw1.pdf", "same.pdf"), _cf(2, "raw2.pdf", "same.pdf")]
    assert_conserved(_run(tmp_path, canvas), canvas)


def test_a_tracked_file_the_user_deleted(tmp_path):
    canvas = [_cf(1, "a.pdf")]
    assert_conserved(_run(tmp_path, canvas, dict([_row(1, "a.pdf", "a.pdf")])), canvas)


def test_a_file_with_no_usable_name_at_all(tmp_path):
    """`_match_key('')` is empty, so this file registered NO key in the name map
    and the old rebuild dropped it for that reason too - a different route to
    the same disappearance."""
    canvas = [_cf(1, "", ""), _cf(2, "b.pdf")]
    assert_conserved(_run(tmp_path, canvas), canvas)


# ---------------------------------------------------------------------------
# the randomised sweep - what hand-written shapes cannot cover
# ---------------------------------------------------------------------------

_NAMES = ["notes.pdf", "notes.pptx", "X.pptx", "lecture.docx", "a.pdf"]
_DEDUP = ["", "-1", "-1-1", "-2"]
_FOLDERS = ["", "A/", "B/", "A/deep/"]
_MODES = ["flat", "modules", "folders"]


def _generate(rng):
    canvas, used = [], set()
    for _ in range(rng.randint(1, 6)):
        fid = rng.randint(1, 12) * 10
        while fid in used:
            fid += 1
        used.add(fid)
        fn = rng.choice(_NAMES)
        stem, _, ext = fn.rpartition(".")
        canvas.append(_cf(fid, fn, f"{stem}{rng.choice(_DEDUP)}.{ext}",
                          size=rng.choice([1000, 2000, 4321])))
    rows, disk = {}, []
    pool = [c.id for c in canvas] + [rng.randint(900, 999)
                                     for _ in range(rng.randint(0, 2))]
    for fid in pool:
        if rng.random() < 0.35:
            continue
        local = rng.choice(_FOLDERS) + rng.choice(_NAMES)
        k, v = _row(fid, local, rng.choice(_NAMES),
                    size=rng.choice([1000, 2000]),
                    ignored=rng.random() < 0.15,
                    downloaded=rng.random() >= 0.15)
        rows[k] = v
        if rng.random() < 0.6:
            disk.append((local, rng.choice([1000, 2000])))
    for _ in range(rng.randint(0, 2)):
        disk.append((rng.choice(_FOLDERS) + rng.choice(_NAMES),
                     rng.choice([1000, 2000])))
    return canvas, rows, disk, rng.choice(_MODES)


def test_conservation_holds_across_500_generated_states(tmp_path_factory):
    """Deterministic seeds, so a failure is reproducible by number.

    The generator deliberately draws names from a SMALL vocabulary and ids from
    a small pool: collisions are the whole point, and a generator that produced
    unique names everywhere would exercise none of this.
    """
    failures = []
    for seed in range(500):
        rng = random.Random(seed)
        canvas, rows, disk, mode = _generate(rng)
        folder = tmp_path_factory.mktemp(f"s{seed}")
        try:
            res = _run(folder, canvas, rows, disk, mode)
        except Exception as e:                              # noqa: BLE001
            failures.append(f"seed {seed} ({mode}) raised {type(e).__name__}: {e}")
            continue
        where = landed(res)
        lost = [c.id for c in canvas if c.id not in where]
        if len(lost) > res.out_of_scope_files:
            failures.append(f"seed {seed} ({mode}) lost {lost}")
        twice = {k: v for k, v in where.items()
                 if len(v) > 1 and k in {c.id for c in canvas}}
        if twice:
            failures.append(f"seed {seed} ({mode}) double-placed {twice}")
    assert not failures, "\n".join(failures[:12])
