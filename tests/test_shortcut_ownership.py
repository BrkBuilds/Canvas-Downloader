"""One link file, one owner - in BOTH directions.

`panopto.shortcut.resolve_shortcut_path` is careful: it adopts a shortcut this
app produced, and steps over anything foreign, precisely so the Panopto pass and
the Canvas file sync never take turns clobbering one path. Its docstring says
so at length. The rule was written once, on that side only.

`core.canvas_logic._create_link` had NO ownership check at all - it overwrote
whatever sat at its computed name. A Panopto lecture IS a Canvas ExternalTool
module item, so in the match layout the two compute the SAME path.

MEASURED 2026-08-22 against the real .canvas_sync.db of course 43660:

    sync_manifest .webloc rows : 41
      md5 mismatch, file present: 36     <- Panopto's file under Canvas's row
      file missing              :  5     <- real external links (bypass covers)
    panopto_manifest url rows  : 36
    SAME PATH IN BOTH TABLES   : 36

The chain: _create_link writes the Canvas link and records a row hashing it ->
post-processing's URL compiler deletes it (no marker) -> the Panopto pass finds
the name free and writes its own shortcut there. So on the next run _create_link
would overwrite the user's selected output, and it survived only because the
compiler deleted it again and Panopto rewrote it - correctness resting on an
unrelated converter toggle. Cancel the Panopto pass mid-run and it is lost.

The register recorded this as "a stale md5, in the safe direction", and gave a
mechanism that is not what happens: it said resolve_shortcut_path ADOPTED the
Canvas link because write_shortcut had marked it. `_create_link` writes a bare
plistlib dump and never calls write_shortcut, so is_produced_shortcut is False
for it - test_a_canvas_link_is_not_mistaken_for_ours below is that check.
"""
from __future__ import annotations

import plistlib
import sqlite3
from pathlib import Path

import pytest

from core.canvas_logic import CanvasManager
from core.sync_manager import (
    CanvasFileInfo, SyncManager, _is_replaced_by_produced_shortcut,
)
from shared.shortcuts import (
    SOURCE_PANOPTO, is_produced_shortcut, shortcut_extension, write_shortcut,
)

#: The suffix `_create_link` will COMPUTE on this host - `.webloc` on macOS,
#: `.url` everywhere else - resolved through the same `platform.system()` test
#: the method itself uses.
#:
#: Hard-coding `.webloc` here is what made four of these tests fail on Windows
#: for the whole life of the file: the fixture wrote `Lecture 8.webloc` while
#: the method under test returned `Lecture 8.url`, so the assertions compared
#: two different paths. Nothing noticed, because no CI job runs pytest on
#: Windows - the platform carrying the large majority of installs.
NATIVE_EXT = shortcut_extension()

#: Both formats, for the checks that are genuinely format-agnostic. The readers
#: MUST accept either suffix on either host (shared/shortcuts.py states this: a
#: folder synced on Windows and then opened on macOS holds `.url` files), so
#: exercising only the native one tests half the contract - and specifically
#: the half that does NOT cover cross-platform adoption.
BOTH_EXTS = (".url", ".webloc")


def _mgr() -> CanvasManager:
    """A CanvasManager without __init__, so no network and no credentials.

    _create_link only needs _sanitize_filename and _handle_conflict, both of
    which are ordinary methods.
    """
    return object.__new__(CanvasManager)


def _canvas_link(path: Path, url: str = "https://cbscanvas.instructure.com/x") -> Path:
    """Byte-for-byte what `_create_link` writes for a path with this suffix.

    An UNMARKED shortcut, i.e. the thing the URL compiler is meant to consume
    and the thing the ownership check must NOT protect. The format follows the
    suffix, exactly as `write_shortcut` does, so this helper is honest on both
    platforms rather than only on the one it was written on.
    """
    if path.suffix.lower() == ".webloc":
        path.write_bytes(plistlib.dumps({"URL": url}, fmt=plistlib.FMT_XML))
    else:
        path.write_text(f"[InternetShortcut]\nURL={url}", encoding="utf-8")
    return path


def _panopto_shortcut(path: Path) -> Path:
    write_shortcut(path, "https://cbs.cloud.panopto.eu/Panopto/Pages/Viewer.aspx?id=a",
                   source=SOURCE_PANOPTO)
    return path


# --------------------------------------------------------- the predicate

@pytest.mark.parametrize("ext", BOTH_EXTS)
def test_a_canvas_link_is_not_mistaken_for_ours(tmp_path, ext):
    """The register's stated mechanism, disproved. If this were True, Panopto
    would be OVERWRITING foreign files - including a user's own shortcut.

    Both suffixes, because the two formats are read by two different branches
    of `read_shortcut` (plist vs the hand-rolled INI parser) and a marker
    mis-read in either direction has the same consequence.
    """
    assert is_produced_shortcut(_canvas_link(tmp_path / f"a{ext}")) is False


@pytest.mark.parametrize("ext", BOTH_EXTS)
def test_a_produced_shortcut_is_recognised(tmp_path, ext):
    assert is_produced_shortcut(_panopto_shortcut(tmp_path / f"b{ext}")) is True


@pytest.mark.parametrize("name,make,expected", [
    *[(f"ours{e}", _panopto_shortcut, True) for e in BOTH_EXTS],
    *[(f"theirs{e}", _canvas_link, False) for e in BOTH_EXTS],
    ("plain.pdf", lambda p: (p.write_bytes(b"%PDF-1.4"), p)[1], False),
])
def test_is_replaced_by_produced_shortcut(tmp_path, name, make, expected):
    assert _is_replaced_by_produced_shortcut(make(tmp_path / name)) is expected


def test_the_predicate_is_total(tmp_path):
    """It runs inside analyze_course, which has no try around it. A missing or
    unreadable file must answer False - the pre-existing behaviour - not raise."""
    assert _is_replaced_by_produced_shortcut(tmp_path / "gone.webloc") is False
    d = tmp_path / "dir.webloc"
    d.mkdir()
    assert _is_replaced_by_produced_shortcut(d) is False


# ------------------------------------------------- _create_link's own half

def test_create_link_does_not_overwrite_a_produced_shortcut(tmp_path):
    """The headline fix: Canvas must step over Panopto's artifact, exactly as
    Panopto steps over Canvas's link.

    NATIVE_EXT, not a literal: `_create_link` derives its own suffix from
    `platform.system()`, so a hard-coded one makes the fixture and the method
    disagree about which file they are talking about on every other platform.
    """
    target = _panopto_shortcut(tmp_path / f"Lecture 8{NATIVE_EXT}")
    before = target.read_bytes()

    out = _mgr()._create_link("Lecture 8", "https://canvas/modules/items/9",
                              tmp_path, None)

    assert out == target, "it must still report the path that satisfies the item"
    assert target.read_bytes() == before, "the produced shortcut was overwritten"


def test_create_link_still_overwrites_its_own_previous_canvas_link(tmp_path):
    """The documented behaviour that must SURVIVE the fix: links are fully
    regenerated from Canvas, so a stale one is replaced rather than piling up
    numbered siblings. Only OUR artifacts are protected."""
    target = _canvas_link(tmp_path / f"Lecture 8{NATIVE_EXT}", "https://canvas/OLD")
    _mgr()._create_link("Lecture 8", "https://canvas/NEW", tmp_path, None)
    assert b"NEW" in target.read_bytes()


def test_create_link_writes_normally_when_the_name_is_free(tmp_path):
    out = _mgr()._create_link("Lecture 9", "https://canvas/x", tmp_path, None)
    assert out.is_file() and is_produced_shortcut(out) is False


def test_the_skip_path_still_records_a_manifest_row(tmp_path):
    """Without a row the Canvas item has none, reads as NEW on every later sync
    and is re-offered for ever - the failure this codebase calls out by name.
    Recording it also re-hashes what is on disk, which is what heals the 36
    stale rows measured on 43660."""
    import hashlib

    course = tmp_path / "course"
    course.mkdir()
    target = _panopto_shortcut(course / f"Lecture 8{NATIVE_EXT}")
    sm = SyncManager(str(course), 43660)

    _mgr()._create_link("Lecture 8", "https://canvas/modules/items/9", course, None,
                        sync_manager=sm, course_base_path=course, canvas_item_id=-77)

    con = sqlite3.connect(str(course / ".canvas_sync.db"))
    con.row_factory = sqlite3.Row
    row = con.execute("select local_path, original_md5 from sync_manifest "
                      "where canvas_file_id = -77").fetchone()
    con.close()
    assert row is not None, "no row was recorded - the item would be re-offered for ever"
    assert row["local_path"] == f"Lecture 8{NATIVE_EXT}"
    assert row["original_md5"] == hashlib.md5(target.read_bytes()).hexdigest(), (
        "the recorded baseline must describe the file that is actually there, "
        "or the row keeps reading as locally modified")


def test_an_unreadable_shortcut_falls_through_to_an_ordinary_write(tmp_path, monkeypatch):
    """A read failure is not proof of ownership.

    If the handler treated an error as "ours", a transient unreadable file
    would make the app silently NOT create a Canvas link - a missing file with
    no error anywhere, which is the worse direction. Found by the mutation
    pass: nothing had ever driven that branch.
    """
    import shared.shortcuts as sc

    def _boom(_p):
        raise OSError("disk hiccup")

    monkeypatch.setattr(sc, "is_produced_shortcut", _boom)
    target = tmp_path / f"Lecture 8{NATIVE_EXT}"
    target.write_bytes(b"whatever")

    out = _mgr()._create_link("Lecture 8", "https://canvas/NEW", tmp_path, None)

    assert out == target
    assert b"NEW" in target.read_bytes(), (
        "an unreadable shortcut was treated as ours, so no link was written")


def test_the_predicate_swallows_a_raising_ownership_check(tmp_path, monkeypatch):
    """It runs inside analyze_course, which has NO try around it - a raise here
    aborts the whole course's analysis. Also found by the mutation pass: the
    total-ness test used inputs that read_shortcut handles internally, so the
    handler was never actually exercised.
    """
    import shared.shortcuts as sc

    def _boom(_p):
        raise RuntimeError("nope")

    monkeypatch.setattr(sc, "is_produced_shortcut", _boom)
    f = tmp_path / "x.webloc"
    f.write_bytes(b"x")
    assert _is_replaced_by_produced_shortcut(f) is False


# --------------------------------------------------- the analyzer's half

def _analyze(course: Path, *, local: str):
    """One tracked ExternalTool link whose Canvas-side content HAS changed.

    A negative-id non-attachment entity is compared by CONTENT SIGNATURE, never
    by timestamp - Canvas bumps updated_at on events that change nothing, and a
    link's whole identity is its title+url. So the two sigs must DIFFER here or
    _is_canvas_newer returns False and everything lands in uptodate_files for a
    reason that has nothing to do with the branch under test. A first version of
    this fixture moved the timestamp instead and proved nothing.
    """
    sm = SyncManager(str(course), 43660)
    cf = CanvasFileInfo(id=-77, filename=local, display_name=local, size=0,
                        modified_at="2026-06-01T00:00:00Z", url="https://canvas/x",
                        content_sig="NEW-SIGNATURE")
    rows = {"-77": {
        "canvas_file_id": -77, "canvas_filename": local, "local_path": local,
        "canvas_updated_at": "2025-01-01T00:00:00Z",
        "downloaded_at": "2025-01-02T00:00:00Z", "original_size": 0,
        "is_ignored": False, "original_md5": "deadbeef",
        "content_sig": "OLD-SIGNATURE"}}
    return sm.analyze_course([cf], {"files": rows}, download_mode="flat")


@pytest.mark.parametrize("ext", BOTH_EXTS)
def test_a_row_whose_file_became_a_produced_shortcut_is_up_to_date(tmp_path, ext):
    """The 36. Before this branch they classified as 'modified' on the md5
    check, so the first Canvas-side edit to any of those module items would
    fork a _NewVersion sibling for a file the user never touched.

    Both suffixes: a folder first synced on Windows and later opened on macOS
    (or the reverse) carries the OTHER platform's shortcut, and the analyzer
    has to reach the same verdict about it either way.
    """
    course = tmp_path / "c"
    course.mkdir()
    _panopto_shortcut(course / f"Lecture 8{ext}")

    res = _analyze(course, local=f"Lecture 8{ext}")

    assert len(res.uptodate_files) == 1
    assert not res.updated_modified_files
    assert not res.updated_clean_files


@pytest.mark.parametrize("ext", BOTH_EXTS)
def test_a_row_whose_file_is_still_a_canvas_link_is_classified_normally(tmp_path, ext):
    """The bypass must not swallow a genuine update. A foreign/ours distinction
    that answers 'up to date' for everything is not a fix."""
    course = tmp_path / "c"
    course.mkdir()
    _canvas_link(course / f"Lecture 8{ext}")

    res = _analyze(course, local=f"Lecture 8{ext}")

    assert not res.uptodate_files
    assert (res.updated_modified_files or res.updated_clean_files), (
        "a Canvas link that Canvas has updated must still be offered")


# ------------------------------------------------------------- symmetry

def test_the_ownership_rule_exists_on_BOTH_sides():
    """A census, not a spot check. This defect was one direction of a two-sided
    rule being written once - the shape CLAUDE.md records repeatedly (a fix
    landing on two of three delete sites, one of two twins, five of six call
    sites). If a third producer of shortcut files is ever added, it needs the
    same check, and this is what will notice the asymmetry returning."""
    import ast

    def _calls_it(rel: str, func: str) -> bool:
        """Resolve the CALL through the AST, never a substring.

        `from shared.shortcuts import is_produced_shortcut` keeps the name in
        the file after the guard using it has been deleted, so a text search
        passes against code with no check left in it. CLAUDE.md records that
        exact trap letting four mutants escape a previous set.
        """
        tree = ast.parse(Path(rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = (f.id if isinstance(f, ast.Name)
                    else f.attr if isinstance(f, ast.Attribute) else None)
            if name == func and _in_function(tree, node, rel):
                return True
        return False

    def _in_function(tree, call, rel) -> bool:
        """The call must live inside a function, not merely in the module."""
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for n in ast.walk(fn):
                    if n is call:
                        return True
        return False

    assert _calls_it("panopto/shortcut.py", "is_produced_shortcut"), (
        "resolve_shortcut_path no longer CALLS the ownership check - Panopto "
        "would overwrite Canvas links and a user's own .webloc files")
    assert _calls_it("core/canvas_logic.py", "is_produced_shortcut"), (
        "_create_link no longer CALLS the ownership check - Canvas would "
        "overwrite the user's selected Panopto Shortcut output")
