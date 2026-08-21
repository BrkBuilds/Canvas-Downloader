"""`result.new_files` must not be rebuilt from a dict keyed by FILENAME.

Registered as `fp:5c1dc682e36c` - "two orphaned Canvas files of identical size
are re-offered one per sync, not both" - and carried for ten days with its
mechanism explicitly unestablished ("I did not find the line that defers the
second one"). This is that line.

`analyze_course` built `new_name_map` so the teacher-re-upload check could find
a new file by name, and then rebuilt `result.new_files` **from that map's
values**. A dict keyed by name cannot hold two files that share a name, so the
loser of a `setdefault` was dropped from the offer entirely: not new, not up to
date, not deleted on Canvas, not deleted locally - absent from every category
the review screen can show.

It needs no exotic data, because `_match_key` unquotes. Canvas keeps ONE
`filename` when a file is uploaded twice and disambiguates only `display_name`
(`X.pptx`, `X-1.pptx`), so the copy whose display_name still EQUALS its filename
collapses to a single key - and if the other copy is listed first, that key is
already taken. Which copy loses is therefore decided by the order Canvas
happened to list them in.

MEASURED, twice, on real course 43660:

  * ids 1560011 / 1560205, both `2024_Lektion+uge+46_1+...+Upload.pptx`,
    both 2,223,911 bytes. Driven against the real folder and its real 262-row
    manifest: 1560011 landed in NO category. Reversing the input list offered
    both.
  * the `CBS_SolbjergPlads_ImageHeader.jpg` TRIPLE (1559837 / 1560082 /
    1560087, one filename, display names `X-1.jpg` / `X.jpg` / `X-1-1.jpg`):
    2 of 3 offered, the missing one being exactly the copy whose display_name
    equals its filename - which is what the register recorded from the live app.

It self-heals on the NEXT sync, because the offered copy gains a manifest row
and stops competing for the key. That is why it read as "one per sync" rather
than as a loss, and it is also why it is worth fixing rather than documenting:
until the user syncs a second time, a file Canvas is offering is one the app
never mentions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.sync_manager import (            # noqa: E402
    CanvasFileInfo,
    SyncManager,
    _match_key,
)

RAW = "2024_Lektion+uge+46_1+Organisationer+i+et+foranderligt+perspektiv+-+Omgivelser+-+1+_+Upload.pptx"
D_PLAIN = "2024_Lektion uge 46_1 Organisationer i et foranderligt perspektiv - Omgivelser - 1 _ Upload.pptx"
D_DEDUP = "2024_Lektion uge 46_1 Organisationer i et foranderligt perspektiv - Omgivelser - 1 _ Upload-1.pptx"
SIZE = 2223911


def _cf(fid, display, filename=RAW, size=SIZE, when="2025-10-20T04:33:17Z"):
    return CanvasFileInfo(id=fid, filename=filename, display_name=display,
                          size=size, modified_at=when, url="https://x/y")


def _folder(tmp_path, orphans=2, orphan_size=599225):
    for i in range(orphans):
        (tmp_path / f"zz flertydig {i}.pdf").write_bytes(b"x" * orphan_size)
    return SyncManager(str(tmp_path), 43660)


def _new_ids(res):
    return {f.id for f in res.new_files}


# ── the premise: two Canvas names really do collapse to one key ──────────

def test_the_raw_filename_and_the_plain_display_name_are_ONE_key():
    """Without this the defect is unreachable, so it is the first thing to pin.

    `_match_key` unquotes, so Canvas's `+`-encoded upload name and the
    teacher-facing display name of the SAME file are the same key - which is
    correct and deliberate. It means a file uploaded twice has one copy with a
    single key and one with two.
    """
    assert _match_key(RAW) == _match_key(D_PLAIN)
    assert _match_key(RAW) != _match_key(D_DEDUP)


# ── THE regression, in both input orders ────────────────────────────────

@pytest.mark.parametrize("order", ["plain-first", "dedup-first"])
def test_both_copies_are_offered_whatever_order_canvas_lists_them(tmp_path, order):
    """The defect was invisible in one order and total in the other."""
    sm = _folder(tmp_path)
    a, b = _cf(1560011, D_PLAIN), _cf(1560205, D_DEDUP, when="2026-05-15T06:09:54Z")
    files = [a, b] if order == "plain-first" else [b, a]
    got = _new_ids(sm.analyze_course(files, {"files": {}}, download_mode="modules"))
    assert got == {1560011, 1560205}, (
        f"{order}: Canvas offers two files and the analyzer offered {sorted(got)}")


@pytest.mark.parametrize("order", ["plain-first", "dedup-first"])
def test_the_dropped_file_was_in_NO_category_at_all(tmp_path, order):
    """Not merely mis-filed - absent. That is what made it invisible on screen
    and unreportable by any oracle that reads a category."""
    sm = _folder(tmp_path)
    a, b = _cf(1560011, D_PLAIN), _cf(1560205, D_DEDUP)
    res = sm.analyze_course([a, b] if order == "plain-first" else [b, a],
                            {"files": {}}, download_mode="modules")
    placed = _new_ids(res)
    placed |= {f.id for f, _ in res.uptodate_files}
    placed |= {getattr(s, "canvas_file_id", None) for s in res.locally_deleted_files}
    placed |= {getattr(s, "canvas_file_id", None) for s in res.deleted_on_canvas}
    for fid in (1560011, 1560205):
        assert fid in placed, f"{fid} appears in no category in {order}"


def test_the_registered_ImageHeader_triple(tmp_path):
    """The second, independent reproduction the register recorded from the app.

    Three ids, one filename, and the copy whose display_name equals the filename
    is the one that loses - which is exactly what the live run showed.
    """
    sm = _folder(tmp_path, orphans=2, orphan_size=2032529)
    triple = [_cf(1559837, "CBS_SolbjergPlads_ImageHeader-1.jpg",
                  filename="CBS_SolbjergPlads_ImageHeader.jpg", size=2032529),
              _cf(1560082, "CBS_SolbjergPlads_ImageHeader.jpg",
                  filename="CBS_SolbjergPlads_ImageHeader.jpg", size=2032529),
              _cf(1560087, "CBS_SolbjergPlads_ImageHeader-1-1.jpg",
                  filename="CBS_SolbjergPlads_ImageHeader.jpg", size=2032529)]
    got = _new_ids(sm.analyze_course(triple, {"files": {}}, download_mode="modules"))
    assert got == {1559837, 1560082, 1560087}, sorted(got)


def test_a_file_registered_under_two_keys_is_still_offered_once(tmp_path):
    """The dedup the old loop was FOR. Removing the map must not double-offer."""
    sm = _folder(tmp_path, orphans=0)
    res = sm.analyze_course([_cf(1560205, D_DEDUP)], {"files": {}},
                            download_mode="modules")
    assert [f.id for f in res.new_files] == [1560205]


def test_offer_order_follows_canvas(tmp_path):
    """A user-visible list should be in the order the source gave it, not in
    the order a hash map happened to yield."""
    sm = _folder(tmp_path, orphans=0)
    files = [_cf(1560205, D_DEDUP), _cf(1560011, D_PLAIN)]
    res = sm.analyze_course(files, {"files": {}}, download_mode="modules")
    assert [f.id for f in res.new_files] == [1560205, 1560011]


# ── the re-upload hand-over must still work ─────────────────────────────

def test_a_reupload_still_takes_its_new_file_off_the_new_list(tmp_path):
    """The one legitimate reason a new file leaves the offer.

    Teacher deletes a Canvas file and re-uploads it under a new id while the
    student had already deleted their local copy: M-6 says the deletion is
    RESPECTED, so the pair routes to "Deleted Locally" and the new file rides on
    it instead of being offered separately. Replacing the name-keyed rebuild
    must not lose that - it is now an explicit consumed-set instead of a side
    effect of deleting dict keys.
    """
    sm = _folder(tmp_path, orphans=0)
    manifest = {"files": {"999001": {
        "canvas_file_id": 999001,
        "canvas_filename": "Handout.pdf",
        "local_path": "Handout.pdf",          # deleted by the student
        "canvas_updated_at": "2025-01-01T00:00:00Z",
        "downloaded_at": "2025-01-02T00:00:00Z",
        "original_size": 1234, "is_ignored": False,
        "original_md5": "", "content_sig": "",
    }}}
    fresh = _cf(1560999, "Handout.pdf", filename="Handout.pdf", size=1234)
    res = sm.analyze_course([fresh], manifest, download_mode="modules")
    assert 1560999 not in _new_ids(res), (
        "a re-uploaded file must ride on the locally-deleted row, not be "
        "offered twice")
    ridden = [getattr(d, "_reupload_new_file", None)
              for d in res.locally_deleted_files]
    assert any(getattr(r, "id", None) == 1560999 for r in ridden), (
        "and it must actually be attached to that row")


def test_an_unrelated_new_file_survives_a_reupload_handover(tmp_path):
    """The consumed set must be per-FILE, not per-name.

    Consuming by name is how the original bug got in; a fix that removed
    everything sharing the re-uploaded name would reintroduce it from the other
    side.
    """
    sm = _folder(tmp_path, orphans=0)
    manifest = {"files": {"999001": {
        "canvas_file_id": 999001, "canvas_filename": "Handout.pdf",
        "local_path": "Handout.pdf", "canvas_updated_at": "2025-01-01T00:00:00Z",
        "downloaded_at": "2025-01-02T00:00:00Z", "original_size": 1234,
        "is_ignored": False, "original_md5": "", "content_sig": "",
    }}}
    files = [_cf(1560999, "Handout.pdf", filename="Handout.pdf", size=1234),
             _cf(1561000, "Handout-1.pdf", filename="Handout.pdf", size=1234)]
    res = sm.analyze_course(files, manifest, download_mode="modules")
    assert 1561000 in _new_ids(res), (
        "the second copy is a different Canvas file and must still be offered")


# ── the shape, so the rebuild cannot quietly return ─────────────────────

def test_new_files_is_not_rebuilt_from_the_name_map():
    """Anchored on the DATA FLOW, via the AST.

    The map is a lookup index. The moment it becomes the source of the offer
    again, two files that share a name collapse to one - silently, and only in
    one of the two possible input orders.
    """
    import ast
    src = (REPO / "core" / "sync_manager.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "analyze_course")
    assign = next(n for n in ast.walk(fn)
                  if isinstance(n, ast.Assign)
                  and any(getattr(t, "id", "") == "_unique_new" for t in n.targets))
    expr = ast.unparse(assign.value)
    assert "new_name_map" not in expr, (
        f"_unique_new is built from the name-keyed map again: {expr}")
    assert "regular_new_files" in expr, (
        f"it must be built from the new files themselves: {expr}")


# ── gaps the mutation pass found in the tests above ─────────────────────

def _del_row(fid, canvas_filename, local_path, size=1234):
    return {"files": {str(fid): {
        "canvas_file_id": fid, "canvas_filename": canvas_filename,
        "local_path": local_path, "canvas_updated_at": "2025-01-01T00:00:00Z",
        "downloaded_at": "2025-01-02T00:00:00Z", "original_size": size,
        "is_ignored": False, "original_md5": "", "content_sig": "",
    }}}


def test_a_reupload_matches_a_row_that_recorded_the_RAW_canvas_filename(tmp_path):
    """The map indexes BOTH names, and each half is load-bearing.

    A manifest row written by an older version records the raw Canvas
    `filename`; a row written today records the display-derived on-disk name.
    They are genuinely different strings whenever a teacher curated the display
    name, so dropping either half silently stops the re-upload hand-over for
    half the folders in the wild.
    """
    sm = _folder(tmp_path, orphans=0)
    manifest = _del_row(999001, "final_v3_REAL2.pdf", "Lecture 1.pdf")
    fresh = _cf(1560999, "Lecture 1.pdf", filename="final_v3_REAL2.pdf", size=1234)
    res = sm.analyze_course([fresh], manifest, download_mode="modules")
    assert 1560999 not in _new_ids(res), (
        "the row records the RAW filename - it must still match the re-upload")


def test_a_reupload_matches_a_row_that_recorded_the_DISPLAY_name(tmp_path):
    """The mirror half, so neither can be dropped unnoticed."""
    sm = _folder(tmp_path, orphans=0)
    manifest = _del_row(999002, "Lecture 1.pdf", "Lecture 1.pdf")
    fresh = _cf(1561001, "Lecture 1.pdf", filename="final_v3_REAL2.pdf", size=1234)
    res = sm.analyze_course([fresh], manifest, download_mode="modules")
    assert 1561001 not in _new_ids(res), (
        "the row records the DISPLAY name - it must still match the re-upload")


def test_secondary_content_is_still_offered(tmp_path):
    """`new_files` is `_unique_new + secondary_new_files`, and the second half
    is every Page, Assignment, Quiz, Announcement and Discussion in the course.

    They are split out because the name-based re-upload dedup must not apply to
    them (two assignments with the same sanitized name are distinct entities),
    so they never pass through the map at all - which means a change to how the
    regular half is assembled can drop them with nothing else failing.
    """
    sm = _folder(tmp_path, orphans=0)
    secondary = CanvasFileInfo(
        id=-40161008, filename="Discussion Upload af besvarelse.html",
        display_name="Discussion Upload af besvarelse.html", size=0,
        modified_at="2025-01-01T00:00:00Z", url="https://x/y")
    regular = _cf(1560205, D_DEDUP)
    res = sm.analyze_course([regular, secondary], {"files": {}},
                            download_mode="modules")
    assert -40161008 in _new_ids(res), "secondary content vanished from the offer"
    assert 1560205 in _new_ids(res)
