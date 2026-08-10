"""Fabricate every sync scenario a real course folder can be in.

``scripts/seed_today_test.py`` makes two of the seven categories. This makes all
seven, plus the messy-folder cases that decide whether the product works for a
real student rather than for a folder the app itself created and nobody touched.

The design rule is that every fixture carries its own PREDICTION - the category
the analyzer must place it in and what must be true on disk afterwards - written
next to the mutation that causes it. A fixture whose expectation lives somewhere
else drifts from the mutation the first time either is edited, and then the suite
asserts something nobody intended.

There are TWO md5s in this system and they are easy to confuse, so the rename
fixtures below are built around the difference:

* ``original_md5`` in the manifest is computed **locally by the app** from the
  bytes it wrote (``sync_manager`` says so at the ``record_file`` docstring:
  "Canvas's API does not expose a usable file hash, so the fresh-download path
  hashes bytes inline"). It is present on every row - including negative-id
  Quiz/Discussion rows whose ``original_size`` is 0, which Canvas could not
  possibly have hashed.
* ``c_file.md5`` from the Canvas API feeds exactly one place: adoption tier (b)
  inside ``analyze_course``. Measured on course 43660: **0 of 140 files carry
  one**, so that tier cannot fire against this instance.

The consequence is the opposite of what the second bullet suggests on its own.
A rename is normally recovered by ``heal_manifest``, which runs BEFORE the
analyzer and matches local-to-local, so it works with no Canvas hash at all:

    Tier 1  exact normalised filename        (edited but not renamed)
    Tier 2  original_md5 + exact size        (renamed but not edited)  <- the real one
    Tier 3  fuzzy stem containment >= 0.90   (renamed AND edited), with an
            ambiguity reject and a documented refusal to match single-character
            SUBSTITUTIONS ("Lecture1" -> "Lecture2")

Healing only runs while the manifest ROW still exists. So the fixtures separate:
a rename with the row intact (heal Tier 2 must catch it), a rename with the row
dropped (only the analyzer's weak size+extension fallback remains), and a
substitution rename (every tier must REFUSE - binding there would mark a missing
file present).

One more property of this instance: synthetic entities compare by content
signature rather than timestamp and are stored with size 0, which makes them
usable as New fixtures but not as update ones.

Everything here DELETES AND EDITS FILES with no backup. Point it at an audit run
directory, never at a folder anyone cares about.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import unquote_plus

from .oracles import db as odb
from .oracles import disk as odisk

OLD_TS = "2020-01-01T00:00:00Z"
GHOST_ID_BASE = 900_000_000        # far above any real Canvas file id

# A missing .url/.webloc or archive is treated by the engine as "converted
# away" rather than deleted, so neither makes an honest fixture.
BYPASS_EXTS = {".url", ".webloc", ".zip", ".tar", ".gz"}


@dataclass
class Fixture:
    label: str
    kind: str
    path: str                      # folder-relative, post-mutation
    expect_category: str = ""      # what the analyzer must say
    expect_after: str = ""         # restored | absent | new_version | unchanged
    expect_path: str = ""          # where it must be after a sync
    match_name: str = ""           # name the log/UI will show it under
    why: str = ""
    canvas_file_id: int | None = None
    original_path: str = ""
    edited_md5: str = ""
    synthetic: bool = True
    extra: dict = field(default_factory=dict)


class Seeder:
    def __init__(self, folder: str | Path, seed: int = 20260727):
        self.folder = Path(folder).resolve()
        self.db_path = self.folder / odb.DB_FILENAME
        if not self.db_path.is_file():
            raise SystemExit(f"No {odb.DB_FILENAME} in {self.folder} - "
                             "download this course first.")
        self.rng = random.Random(seed)
        self.info = odb.read(self.folder)
        self.disk = odisk.scan(self.folder, full_hash=True)
        self.by_rel = {self._k(f["rel"]): f for f in self.disk["files"]}
        self.fixtures: list[Fixture] = []
        self._used_ids: set[int] = set()
        self._used_paths: set[str] = set()

    # -- candidate selection ---------------------------------------------

    @staticmethod
    def _k(p: str) -> str:
        return os.path.normcase(str(p).replace("\\", "/").strip("/"))

    def _rows(self, *, real=True, clean=True) -> list[dict]:
        """Manifest rows usable as fixtures, cheapest-to-restore first."""
        out = []
        for r in self.info["rows"]:
            if r["is_ignored"] or r["canvas_file_id"] in self._used_ids:
                continue
            if real and r["canvas_file_id"] < 0:
                continue
            if not real and r["canvas_file_id"] > 0:
                continue
            f = self.by_rel.get(self._k(r["local_path"]))
            if not f:
                continue
            if Path(r["local_path"]).suffix.lower() in BYPASS_EXTS:
                continue
            if clean and r.get("original_md5") and f.get("md5") \
                    and r["original_md5"] != f["md5"]:
                continue
            out.append({**r, "_disk": f})
        out.sort(key=lambda r: r["_disk"]["size"])
        return out

    def _size_ext_counts(self) -> dict[tuple, int]:
        c: dict[tuple, int] = {}
        for f in self.disk["files"]:
            if f["app_generated"]:
                continue
            k = (f["size"], f["ext"])
            c[k] = c.get(k, 0) + 1
        return c

    def _take(self, rows: list[dict], n: int, *, unique_size_ext: bool | None = None,
              min_size: int = 1) -> list[dict]:
        counts = self._size_ext_counts()
        picked = []
        for r in rows:
            if len(picked) >= n:
                break
            f = r["_disk"]
            if f["size"] < min_size:
                continue
            if self._k(r["local_path"]) in self._used_paths:
                continue
            if unique_size_ext is not None:
                is_uniq = counts.get((f["size"], f["ext"]), 0) == 1
                if is_uniq != unique_size_ext:
                    continue
            picked.append(r)
            self._used_ids.add(r["canvas_file_id"])
            self._used_paths.add(self._k(r["local_path"]))
        return picked

    # -- mutation primitives ----------------------------------------------

    def _con(self):
        try:
            return sqlite3.connect(str(self.db_path), timeout=15.0)
        except sqlite3.OperationalError as e:
            raise SystemExit(f"Cannot write {self.db_path}: {e}\n"
                             "Is the app mid-run against this folder?")

    def _drop_row(self, con, fid: int) -> None:
        con.execute("DELETE FROM sync_manifest WHERE canvas_file_id=?", (fid,))

    def _direct_targets(self) -> list[dict]:
        """Rows whose local file is what Canvas sent, not a converted rewrite.

        A conversion product differs from its Canvas source in BOTH the things
        the app matches on: the extension ("x.js" -> "x_js.txt") and the size
        (the converter prepends a header). Any fixture whose expected outcome
        depends on the app recognising the local file FROM Canvas metadata must
        therefore start here, or it is asking for a match that cannot exist.

        Measured 2026-07-29: `renamed_row_dropped` did not, and on the two rows
        where it happened to pick a `convert_code` output it reported the
        analyzer for classifying the file as New. That verdict was correct -
        tier (c) keys on unique size+extension and neither matches - and the
        alternative (binding a .txt to a .sql on name evidence alone) is the
        unsafe direction the tier-(c) name floor exists to prevent.

        The extension test is the cheap, reliable signal: `canvas_filename` is
        URL-encoded in the manifest, hence the unquote.
        """
        return [r for r in self._rows()
                if Path(r["local_path"]).suffix.lower()
                == Path(unquote_plus(r.get("canvas_filename") or "")).suffix.lower()]

    def _backdate(self, con, fid: int, disk_size: int) -> None:
        """Make Canvas look newer than the local copy.

        Both halves are required. Back-dating the timestamp alone is vetoed by
        ``_is_canvas_newer`` as a metadata touch when the byte count is
        unchanged, so ``original_size`` is knocked off by one as well.
        """
        fake = disk_size - 1 if disk_size > 1 else disk_size + 1
        con.execute("UPDATE sync_manifest SET canvas_updated_at=?, original_size=? "
                    "WHERE canvas_file_id=?", (OLD_TS, fake, fid))

    # ======================================================================
    # fixtures
    # ======================================================================

    def new_regular(self, n: int = 3) -> None:
        """Delete file AND row so the file resurfaces as New.

        Deleting only the row is not enough: the analyzer auto-discovers
        untracked on-disk files and silently re-adopts them as up to date, so
        the file would never appear. Candidates are restricted to a UNIQUE
        size+extension so no surviving orphan can be claimed in its place.
        """
        rows = self._take(self._rows(), n, unique_size_ext=True, min_size=1024)
        with self._con() as con:
            for r in rows:
                self._drop_row(con, r["canvas_file_id"])
                (self.folder / r["local_path"]).unlink(missing_ok=True)
                self.fixtures.append(Fixture(
                    label=f"new:{Path(r['local_path']).name}", kind="new_regular",
                    path=r["local_path"], expect_category="new",
                    expect_after="restored", expect_path=r["local_path"],
                    match_name=Path(r["local_path"]).name,
                    canvas_file_id=r["canvas_file_id"],
                    why="File and manifest row both removed, and no unclaimed file "
                        "on disk shares its size+extension, so no adoption tier can "
                        "reclaim it. It must be offered as New and re-downloaded to "
                        "its original path."))

    def new_secondary(self, n: int = 2) -> None:
        """Same, for a Canvas Content entity (negative id).

        These carry size 0 and match on NAME alone, so the uniqueness argument
        above does not apply - the guard is that the name is unique, which it is
        because the engine builds it from the entity's title.
        """
        rows = self._take(self._rows(real=False, clean=False), n, min_size=0)
        with self._con() as con:
            for r in rows:
                self._drop_row(con, r["canvas_file_id"])
                (self.folder / r["local_path"]).unlink(missing_ok=True)
                self.fixtures.append(Fixture(
                    label=f"new-secondary:{Path(r['local_path']).name}",
                    kind="new_secondary", path=r["local_path"],
                    expect_category="new", expect_after="restored",
                    expect_path=r["local_path"],
                    match_name=Path(r["local_path"]).name,
                    canvas_file_id=r["canvas_file_id"],
                    why=f"Canvas Content entity ({odb.entity_type(r['canvas_file_id'])}) "
                        "removed from disk and manifest. Secondary entities compare by "
                        "content signature, so it must reappear as New and regenerate."))

    def clean_update(self, n: int = 3) -> None:
        rows = self._take(self._rows(), n, min_size=1024)
        with self._con() as con:
            for r in rows:
                self._backdate(con, r["canvas_file_id"], r["_disk"]["size"])
                self.fixtures.append(Fixture(
                    label=f"clean-update:{Path(r['local_path']).name}",
                    kind="clean_update", path=r["local_path"],
                    expect_category="updated_clean", expect_after="restored",
                    expect_path=r["local_path"],
                    match_name=Path(r["local_path"]).name,
                    canvas_file_id=r["canvas_file_id"],
                    why="Canvas timestamp back-dated and recorded size perturbed, "
                        "while original_md5 still matches the file on disk - so the "
                        "modification classifier returns 'clean' and the file must be "
                        "overwritten in place, same name, same folder."))

    def edited_update(self, n: int = 2) -> None:
        """Canvas is newer AND the user has edited their copy.

        The most consequential category in the product: the promise is that the
        local file is never touched and the new version lands beside it as
        ``_NewVersion``. The fixture records the edited md5 so the check can
        prove the user's bytes survived, not merely that a sibling appeared.
        """
        rows = self._take(self._rows(), n, min_size=1024)
        with self._con() as con:
            for r in rows:
                p = self.folder / r["local_path"]
                with p.open("ab") as fh:
                    fh.write(b"\n<!-- canvas-downloader audit: local edit -->\n")
                new_md5 = odisk.full_md5(p)
                self._backdate(con, r["canvas_file_id"], p.stat().st_size)
                self.fixtures.append(Fixture(
                    label=f"edited-update:{Path(r['local_path']).name}",
                    kind="edited_update", path=r["local_path"],
                    expect_category="updated_modified", expect_after="new_version",
                    expect_path=r["local_path"],
                    match_name=Path(r["local_path"]).name,
                    canvas_file_id=r["canvas_file_id"], edited_md5=new_md5,
                    why="Bytes appended so the file no longer matches original_md5, "
                        "and Canvas back-dated so an update is due. Must be classified "
                        "'edited locally', UNCHECKED by default, and - if synced - "
                        "written as a _NewVersion sibling with the original untouched."))

    def deleted_locally(self, n: int = 2) -> None:
        rows = self._take(self._rows(), n, min_size=1)
        for r in rows:
            (self.folder / r["local_path"]).unlink(missing_ok=True)
            self.fixtures.append(Fixture(
                label=f"deleted-locally:{Path(r['local_path']).name}",
                kind="deleted_locally", path=r["local_path"],
                expect_category="deleted_locally", expect_after="absent",
                expect_path=r["local_path"],
                match_name=Path(r["local_path"]).name,
                canvas_file_id=r["canvas_file_id"],
                why="File removed but its manifest row kept, which is what a real "
                    "user deletion looks like. The deletion must be respected: "
                    "unchecked by default, and always skipped by Quick Sync."))

    def deleted_on_canvas(self, n: int = 2) -> None:
        """A file the teacher removed from Canvas that the student still has.

        Fabricated by registering a row against an id Canvas cannot return. The
        contract is INFORMATION ONLY - the app must never delete a local file -
        so the check afterwards is that the copy is still there.
        """
        donors = self._take(self._rows(), n, min_size=1024)
        with self._con() as con:
            for i, r in enumerate(donors):
                src = self.folder / r["local_path"]
                ghost_rel = str(Path(r["local_path"]).parent /
                                f"GhostFile_{i}_{Path(r['local_path']).name}"
                                ).replace("\\", "/").lstrip("./")
                dst = self.folder / ghost_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                gid = GHOST_ID_BASE + i
                con.execute(
                    "INSERT OR REPLACE INTO sync_manifest (canvas_file_id, "
                    "canvas_filename, local_path, canvas_updated_at, downloaded_at, "
                    "original_size, is_ignored, original_md5, content_sig) "
                    "VALUES (?,?,?,?,?,?,0,?,'')",
                    (gid, dst.name, ghost_rel, OLD_TS,
                     time.strftime("%Y-%m-%dT%H:%M:%S"), dst.stat().st_size,
                     odisk.full_md5(dst)))
                self.fixtures.append(Fixture(
                    label=f"deleted-on-canvas:{dst.name}", kind="deleted_on_canvas",
                    path=ghost_rel, expect_category="deleted_on_canvas",
                    expect_after="unchanged", expect_path=ghost_rel,
                    match_name=dst.name, canvas_file_id=gid,
                    why="A manifest row exists for a Canvas id that cannot be "
                        "returned, so the analyzer must report it as deleted on "
                        "Canvas. The local copy must be left exactly where it is - "
                        "the app never deletes local files."))

    def ignored(self, n: int = 2) -> None:
        rows = self._take(self._rows(), n, min_size=1)
        with self._con() as con:
            for r in rows:
                con.execute("UPDATE sync_manifest SET is_ignored=1 WHERE canvas_file_id=?",
                            (r["canvas_file_id"],))
                self.fixtures.append(Fixture(
                    label=f"ignored:{Path(r['local_path']).name}", kind="ignored",
                    path=r["local_path"], expect_category="ignored",
                    expect_after="unchanged", expect_path=r["local_path"],
                    match_name=Path(r["local_path"]).name,
                    canvas_file_id=r["canvas_file_id"],
                    why="Marked ignored in the manifest. It must appear only in the "
                        "Ignored Files category, never in New or Updates, and must "
                        "be restorable from there."))

    # -- the messy-folder tiers -------------------------------------------

    def renamed_row_intact(self, n: int = 2) -> None:
        """The ordinary user rename: file renamed, manifest row untouched.

        This is THE case the product's "recognises your messy folder" promise
        rests on, and it is handled by ``heal_manifest`` Tier 2 - exact
        ``original_md5`` plus exact size, both sides computed locally, so no
        Canvas hash is involved and the match is exact rather than heuristic.
        The new name deliberately shares no stem with the old one, so Tier 1
        (name) and Tier 3 (fuzzy containment) both fail and Tier 2 is proved in
        isolation.
        """
        rows = self._take(self._rows(), n, min_size=1024)
        for i, r in enumerate(rows):
            src = self.folder / r["local_path"]
            new_rel = str(Path(r["local_path"]).parent /
                          f"zz mine noter {i}{src.suffix}").replace("\\", "/").lstrip("./")
            src.rename(self.folder / new_rel)
            self.fixtures.append(Fixture(
                label=f"renamed-row-intact:{Path(new_rel).name}",
                kind="renamed_row_intact", path=new_rel,
                original_path=r["local_path"], expect_category="uptodate",
                expect_after="unchanged", expect_path=new_rel,
                match_name=Path(r["local_path"]).name,
                canvas_file_id=r["canvas_file_id"],
                why="Renamed on disk, bytes untouched, manifest row still present. "
                    "heal_manifest Tier 2 (original_md5 + exact size, both computed "
                    "locally) must relocate the row so the file reads UP TO DATE. "
                    "Offering it as New would put a second copy of the same content "
                    "in the folder under the Canvas name."))

    def renamed_row_dropped(self, n: int = 1) -> None:
        """Row gone, but the new name still RECOGNISABLY derives from the old.

        Healing cannot run without a row, so recovery falls to
        ``analyze_course`` tier (c): unique size + extension, plus (since
        2026-07-27) a stem-containment floor. Keeping the original stem and
        appending a suffix is what a student's rename usually looks like, and it
        must still be adopted - a floor that rejected this would trade a silent
        data loss for a folder full of duplicates.

        DIRECT targets only. Tier (c) keys on unique size + extension, and a
        conversion product matches its Canvas source on neither, so seeding one
        here asks the analyzer for a match that cannot exist and then reports it
        for saying New - which is both correct and the safe direction.
        """
        rows = self._take(self._direct_targets(), n,
                          unique_size_ext=True, min_size=1024)
        with self._con() as con:
            for i, r in enumerate(rows):
                src = self.folder / r["local_path"]
                new_rel = str(Path(r["local_path"]).parent /
                              f"{src.stem} - mine noter {i}{src.suffix}"
                              ).replace("\\", "/").lstrip("./")
                src.rename(self.folder / new_rel)
                self._drop_row(con, r["canvas_file_id"])
                self.fixtures.append(Fixture(
                    label=f"renamed-row-dropped:{Path(new_rel).name}",
                    kind="renamed_row_dropped", path=new_rel,
                    original_path=r["local_path"], expect_category="uptodate",
                    expect_after="unchanged", expect_path=new_rel,
                    match_name=Path(r["local_path"]).name,
                    canvas_file_id=r["canvas_file_id"],
                    why="Renamed with the original stem intact AND the manifest row "
                        "dropped, so healing cannot run. Tier (c) must adopt it: the "
                        "size+extension are unique and the stem still contains the "
                        "Canvas name, which is the evidence the name floor asks for."))

    def renamed_row_dropped_unrecognisable(self, n: int = 1) -> None:
        """Row gone AND the new name shares nothing with the Canvas name.

        Correct behaviour changed here on 2026-07-27 and the change is the
        point of the fixture. Tier (c) used to adopt on size+extension alone,
        which let a same-sized file of unrelated content take a real file's
        manifest row - the file was then never re-downloaded and never
        mentioned again. With no name evidence and no Canvas md5 to fall back
        on, the safe answer is to treat it as New: the student keeps their
        renamed copy AND gets the real file back. A duplicate, never a loss.

        DIRECT targets only, for the opposite reason to its sibling above: this
        one asserts a REFUSAL, and a conversion product would be refused on the
        extension before the name floor was ever consulted - so the fixture
        would pass without testing the thing it exists to test.
        """
        rows = self._take(self._direct_targets(), n,
                          unique_size_ext=True, min_size=1024)
        with self._con() as con:
            for i, r in enumerate(rows):
                src = self.folder / r["local_path"]
                new_rel = str(Path(r["local_path"]).parent /
                              f"zz omdøbt uden række {i}{src.suffix}"
                              ).replace("\\", "/").lstrip("./")
                src.rename(self.folder / new_rel)
                self._drop_row(con, r["canvas_file_id"])
                self.fixtures.append(Fixture(
                    label=f"renamed-unrecognisable:{Path(new_rel).name}",
                    kind="renamed_row_dropped_unrecognisable", path=new_rel,
                    original_path=r["local_path"], expect_category="new",
                    expect_after="restored", expect_path=r["local_path"],
                    match_name=Path(r["local_path"]).name,
                    canvas_file_id=r["canvas_file_id"],
                    extra={"untracked_expected": new_rel},
                    why="Renamed beyond recognition with the row dropped. The tier (c) "
                        "name floor must REFUSE, so the real file is re-downloaded "
                        "rather than silently replaced by whatever happened to share "
                        "its size. The renamed copy stays on disk, untouched."))

    def renamed_ambiguous(self, n: int = 1) -> None:
        """Row dropped AND size+extension shared with another file.

        The correct behaviour here is the OPPOSITE of the two above: every tier
        must REFUSE, because binding a coincidentally same-sized file would mark
        a genuinely-missing file as present. New is the right answer, and a
        suite that expected adoption in all rename cases would file correct
        behaviour as a bug.
        """
        rows = self._take(self._rows(), n, unique_size_ext=False, min_size=1024)
        with self._con() as con:
            for i, r in enumerate(rows):
                src = self.folder / r["local_path"]
                new_rel = str(Path(r["local_path"]).parent /
                              f"zz flertydig {i}{src.suffix}").replace("\\", "/").lstrip("./")
                src.rename(self.folder / new_rel)
                self._drop_row(con, r["canvas_file_id"])
                self.fixtures.append(Fixture(
                    label=f"renamed-ambiguous:{Path(new_rel).name}",
                    kind="renamed_ambiguous", path=new_rel,
                    original_path=r["local_path"], expect_category="new",
                    expect_after="restored", expect_path=r["local_path"],
                    match_name=Path(r["local_path"]).name,
                    canvas_file_id=r["canvas_file_id"],
                    why="Renamed, row dropped, and another file shares its size and "
                        "extension. The uniqueness guard must REFUSE to adopt, so New "
                        "is correct - binding here would silently mark a missing file "
                        "present and the user would never get it back."))

    def renamed_substitution(self, n: int = 1) -> None:
        """A rename that every healing tier must refuse.

        The file is renamed by SUBSTITUTING its last stem character and then
        edited, which defeats Tier 1 (name changed), Tier 2 (md5 and size both
        changed) and Tier 3 (stem containment fails on a substitution - the code
        calls this out as "the classic mis-heal trap", because "Lecture1" and
        "Lecture2" are different documents that differ by one character).

        Refusing leaves the row unhealed, which surfaces as deleted-locally -
        safe, honest, and recoverable by the user. Silently binding the two
        would be data loss dressed up as a successful sync.
        """
        rows = self._take(self._rows(), n, min_size=1024)
        for r in rows:
            src = self.folder / r["local_path"]
            stem = src.stem
            if len(stem) < 2:
                continue
            last = stem[-1]
            sub = "9" if last.lower() != "9" else "0"
            dst = src.parent / f"{stem[:-1]}{sub}{src.suffix}"
            src.rename(dst)
            with dst.open("ab") as fh:
                fh.write(b"\n<!-- audit: edited so Tier 2 cannot fire -->\n")
            rel = str(dst.relative_to(self.folder)).replace("\\", "/")
            self.fixtures.append(Fixture(
                label=f"renamed-substitution:{dst.name}", kind="renamed_substitution",
                path=rel, original_path=r["local_path"],
                expect_category="deleted_locally", expect_after="absent",
                expect_path=r["local_path"], match_name=Path(r["local_path"]).name,
                canvas_file_id=r["canvas_file_id"],
                extra={"untracked_expected": rel},
                why="Last stem character substituted and the file edited, so Tier 1, "
                    "Tier 2 and Tier 3 must all refuse. The row stays unhealed and "
                    "surfaces as deleted-locally, which is the safe outcome. A heal "
                    "here would bind two genuinely different documents."))

    def moved_deep(self, n: int = 2) -> None:
        """Moved into a nested folder with the manifest row left pointing at the
        old path. ``heal_manifest`` must relocate the row rather than report a
        deletion followed by a new file."""
        rows = self._take(self._rows(), n, min_size=1)
        for i, r in enumerate(rows):
            src = self.folder / r["local_path"]
            deep = self.folder / "My Notes" / f"semester {i}" / "week 3" / "reading"
            deep.mkdir(parents=True, exist_ok=True)
            dst = deep / src.name
            shutil.move(str(src), str(dst))
            rel = str(dst.relative_to(self.folder)).replace("\\", "/")
            self.fixtures.append(Fixture(
                label=f"moved-deep:{dst.name}", kind="moved_deep", path=rel,
                original_path=r["local_path"], expect_category="uptodate",
                expect_after="unchanged", expect_path=rel,
                match_name=dst.name, canvas_file_id=r["canvas_file_id"],
                why="Moved four levels down with the same name while the manifest "
                    "still points at the old path. heal_manifest Tier 1 (exact "
                    "normalised filename) must follow it. Reporting it as "
                    "deleted-locally or New would re-download a second copy at the "
                    "original location."))

    def moved_and_renamed(self, n: int = 1) -> None:
        """Reorganised AND renamed, row intact - the fully-restructured folder.

        Row kept because that is what actually happens when a student
        reorganises: nothing touches the database. Both Tier 1 and Tier 3 fail
        (different folder, unrelated stem), so this proves Tier 2 tracks a file
        across a move and a rename at once.
        """
        rows = self._take(self._rows(), n, min_size=1024)
        for i, r in enumerate(rows):
            src = self.folder / r["local_path"]
            deep = self.folder / "Exam prep" / "sorted by topic"
            deep.mkdir(parents=True, exist_ok=True)
            dst = deep / f"zz emne {i} handout{src.suffix}"
            shutil.move(str(src), str(dst))
            rel = str(dst.relative_to(self.folder)).replace("\\", "/")
            self.fixtures.append(Fixture(
                label=f"moved+renamed:{dst.name}", kind="moved_and_renamed",
                path=rel, original_path=r["local_path"],
                expect_category="uptodate", expect_after="unchanged",
                expect_path=rel, match_name=Path(r["local_path"]).name,
                canvas_file_id=r["canvas_file_id"],
                why="Moved into a new folder AND renamed, with the manifest row "
                    "untouched - what a student reorganising their folder actually "
                    "does. Only heal Tier 2 (local md5 + size) can follow both "
                    "changes at once. This is the case the product's value "
                    "proposition rests on."))

    def duplicate_copy(self, n: int = 1) -> None:
        """A second byte-identical copy the student made themselves.

        Exactly one of the two may be claimed by the manifest. If the analyzer
        claims both, one Canvas file is silently marked present twice.
        """
        rows = self._take(self._rows(), n, min_size=1024)
        for i, r in enumerate(rows):
            src = self.folder / r["local_path"]
            dst = src.parent / f"{src.stem} - copy for exam{src.suffix}"
            shutil.copy2(src, dst)
            rel = str(dst.relative_to(self.folder)).replace("\\", "/")
            self.fixtures.append(Fixture(
                label=f"duplicate:{dst.name}", kind="duplicate_copy", path=rel,
                original_path=r["local_path"], expect_category="",
                expect_after="unchanged", expect_path=rel,
                match_name=dst.name, canvas_file_id=r["canvas_file_id"],
                why="A byte-identical copy the student made. The original stays "
                    "claimed by its row; the copy must remain unclaimed and must "
                    "never be counted as Canvas content or offered for anything."))

    def decoy_same_size_ext(self, n: int = 1) -> None:
        """A file that only LOOKS like a deleted one. Must not be adopted."""
        rows = self._take(self._rows(), n, unique_size_ext=True, min_size=4096)
        with self._con() as con:
            for i, r in enumerate(rows):
                src = self.folder / r["local_path"]
                size, suffix = src.stat().st_size, src.suffix
                decoy = self.folder / f"decoy {i} unrelated{suffix}"
                decoy.write_bytes(b"\x00" * size)
                self._drop_row(con, r["canvas_file_id"])
                src.unlink()
                self.fixtures.append(Fixture(
                    label=f"decoy:{decoy.name}", kind="decoy_same_size_ext",
                    path=str(decoy.relative_to(self.folder)).replace("\\", "/"),
                    original_path=r["local_path"], expect_category="new",
                    expect_after="restored", expect_path=r["local_path"],
                    match_name=Path(r["local_path"]).name,
                    canvas_file_id=r["canvas_file_id"],
                    extra={"decoy_size": size},
                    why="The real file was removed and a same-size, same-extension "
                        "file of unrelated content put in the folder. Tier (c) WILL "
                        "bind these (Canvas exposes no md5 to disprove it), so the "
                        "expectation records what the product actually promises: if "
                        "the decoy is adopted, the user silently keeps junk in place "
                        "of their file. Investigate whichever way this lands."))

    def foreign_content(self) -> None:
        """The student's own unrelated files and folders. Must be invisible."""
        junk = self.folder / "Min egen mappe"
        (junk / "gamle noter").mkdir(parents=True, exist_ok=True)
        made = []
        for rel, data in (
            ("Min egen mappe/mine noter.docx", b"PK\x03\x04 not really a docx"),
            ("Min egen mappe/gamle noter/tanker.txt", b"personal notes"),
            ("eksamensplan 2026.pdf", b"%PDF-1.4 fake"),
        ):
            p = self.folder / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            made.append(rel)
            self.fixtures.append(Fixture(
                label=f"foreign:{Path(rel).name}", kind="foreign_content", path=rel,
                expect_category="", expect_after="unchanged", expect_path=rel,
                match_name=Path(rel).name,
                why="A file the student put in the folder themselves. It must never "
                    "be claimed by a manifest row, counted as Canvas content, or "
                    "shown in any sync category - and must still be there afterwards."))

    def partial_artifact(self) -> None:
        """Crashed-write leftovers in both shapes the engines produce."""
        for rel in ("interrupted download.pdf.part", "recording.part.mp4"):
            (self.folder / rel).write_bytes(b"\x00" * 2048)
            self.fixtures.append(Fixture(
                label=f"partial:{rel}", kind="partial_artifact", path=rel,
                expect_category="", expect_after="unchanged", expect_path=rel,
                match_name=rel,
                why="Both partial-artifact shapes the engines produce (x.ext.part "
                    "from the file engine, x.part.ext from the Panopto downloader). "
                    "Neither may be healed onto a missing entry, auto-discovered, "
                    "counted as study material, or picked up by post-processing."))

    def readonly_target(self, n: int = 1) -> None:
        """An update whose destination cannot be written.

        Stands in for the file the student has open in Word. The engine's
        documented fallback is a ``_NewVersion`` sibling rather than a failed
        sync, so the user never loses the run to one locked file.
        """
        # Must be a DIRECT download target, never a conversion product - the
        # engine writes the Canvas file first and the converter renames it
        # afterwards, so locking the .txt leaves the write path free: no
        # PermissionError, no _NewVersion, and the fixture silently tests the
        # CONVERTER's failure path instead of the locked-target fallback it was
        # written for.
        # THE _NewVersion FALLBACK IS WINDOWS-ONLY, and the expectation has to
        # say so or this fixture reports a critical on every POSIX run.
        # Measured on macOS 15, 2026-08-10: `open(target, 'wb')` on a mode-444
        # file raises PermissionError, but `os.replace(tmp, target)` onto that
        # same file SUCCEEDS - rename is governed by write permission on the
        # DIRECTORY, not by the target's mode. The engine commits every download
        # with `os.replace(part_path, final_path)` and its fallback is
        # `except PermissionError` (sync/execution.py ~1081), so on POSIX the
        # exception never fires, `_register_new_version(..., 'in_use')` is
        # unreachable, and the file is simply updated. Nothing the user authored
        # is lost - the EDITED-file fork is a separate md5-based path that works
        # on every platform - so expecting a sibling here is asserting Windows
        # semantics, not the product's contract. It produced 6 spurious
        # criticals in the first macOS matrix.
        _posix = os.name != "nt"
        rows = self._take(self._direct_targets(), n, min_size=1024)
        with self._con() as con:
            for r in rows:
                p = self.folder / r["local_path"]
                self._backdate(con, r["canvas_file_id"], p.stat().st_size)
                os.chmod(p, 0o444)
                self.fixtures.append(Fixture(
                    label=f"readonly:{p.name}", kind="readonly_target",
                    path=r["local_path"], expect_category="updated_clean",
                    # "" asserts nothing about the after-state; the
                    # expect_category check above still runs, so the row keeps
                    # its real value on POSIX - the analyzer must still classify
                    # a read-only file as a clean update, and the run must still
                    # finish without an error.
                    expect_after="" if _posix else "new_version",
                    expect_path=r["local_path"],
                    match_name=p.name, canvas_file_id=r["canvas_file_id"],
                    extra={"restore_mode": True, "posix_no_fork": _posix},
                    why=("A clean update whose destination is read-only. On POSIX "
                         "the rename succeeds regardless of the file's mode, so the "
                         "engine updates it in place; what is checked here is that "
                         "it is still classified as a clean update and that the run "
                         "reports neither a silent success nor a hard error."
                         if _posix else
                         "A clean update whose destination is read-only. The engine "
                         "must fall back to a _NewVersion sibling instead of failing "
                         "the file, and must report neither a silent success nor a "
                         "hard error for the run.")))

    def unicode_rename(self, n: int = 1) -> None:
        """A rename into the character classes that break naive path handling.

        Row kept, so the recovery path is heal Tier 2 - which hashes the file
        and therefore has to open it by that name. Danish letters, an en dash,
        an emoji and a combining accent together cover the encoding mistakes
        this codebase has hit before (CP1252 defaults on Windows, and NFC/NFD
        normalisation differences between macOS and Windows).
        """
        rows = self._take(self._rows(), n, min_size=1024)
        for r in rows:
            src = self.folder / r["local_path"]
            # The accent below is "e" + U+0301 COMBINING ACUTE - decomposed (NFD)
            # on purpose, so any path compared after NFC normalisation genuinely
            # fails to match and the bug is exposed rather than accidentally
            # avoided. Do not "tidy" it into a precomposed é.
            dst = src.parent / f"læsning – uge 42 ✅ resumé{src.suffix}"
            src.rename(dst)
            rel = str(dst.relative_to(self.folder)).replace("\\", "/")
            self.fixtures.append(Fixture(
                label=f"unicode:{dst.name}", kind="unicode_rename", path=rel,
                original_path=r["local_path"], expect_category="uptodate",
                expect_after="unchanged", expect_path=rel,
                match_name=Path(r["local_path"]).name,
                canvas_file_id=r["canvas_file_id"],
                why="Renamed to a name mixing Danish letters, an en dash, an emoji "
                    "and a COMBINING acute accent (NFD). heal Tier 2 must still hash "
                    "and match it, and nothing downstream may mangle the name in the "
                    "UI, the log or the manifest."))

    def long_path(self, n: int = 1) -> None:
        rows = self._take(self._rows(), n, min_size=1)
        for r in rows:
            src = self.folder / r["local_path"]
            deep = self.folder
            for part in ("a very long folder name for testing windows path limits",
                         "another equally long folder name to push past two sixty",
                         "and a third one so the total comfortably exceeds the cap"):
                deep = deep / part
            deep.mkdir(parents=True, exist_ok=True)
            dst = deep / src.name
            try:
                shutil.move(str(src), str(dst))
            except OSError:
                continue
            rel = str(dst.relative_to(self.folder)).replace("\\", "/")
            self.fixtures.append(Fixture(
                label=f"longpath:{dst.name}", kind="long_path", path=rel,
                original_path=r["local_path"], expect_category="uptodate",
                expect_after="unchanged", expect_path=rel,
                match_name=dst.name, canvas_file_id=r["canvas_file_id"],
                extra={"path_len": len(str(dst))},
                why="Moved to a path past the 260-character Windows limit. Healing, "
                    "hashing and any rewrite must all go through the long-path "
                    "prefix; a failure here usually surfaces as WinError 206."))

    # ======================================================================

    # Ordered so the categories that need the widest candidate pool are seeded
    # first: each fixture consumes rows, and a later one silently degrades to
    # "no eligible candidate" if an earlier one took everything it could use.
    ALL = ("new_regular", "new_secondary", "clean_update", "edited_update",
           "deleted_locally", "deleted_on_canvas", "ignored",
           "renamed_row_intact", "renamed_row_dropped",
           "renamed_row_dropped_unrecognisable", "renamed_ambiguous",
           "renamed_substitution", "moved_deep", "moved_and_renamed",
           "duplicate_copy", "decoy_same_size_ext", "readonly_target",
           "unicode_rename", "long_path", "foreign_content", "partial_artifact")

    def apply(self, kinds: list[str] | None = None, counts: dict | None = None) -> dict:
        # None means "every fixture"; an EMPTY LIST means "none of them", which
        # is a scenario in its own right - the sync matrix needs a folder where
        # genuinely nothing changed, to exercise the empty-analysis screen. The
        # old `kinds or list(self.ALL)` collapsed the two, so asking for nothing
        # silently seeded everything: the loudest possible folder, checked
        # against an expectation of complete quiet.
        if kinds is None:
            kinds = list(self.ALL)
        counts = counts or {}
        applied, skipped = [], {}
        for k in kinds:
            fn = getattr(self, k, None)
            if fn is None:
                skipped[k] = "unknown fixture kind"
                continue
            before = len(self.fixtures)
            try:
                if k in ("foreign_content", "partial_artifact"):
                    fn()
                else:
                    fn(counts.get(k, 2 if k != "new_regular" else 3))
            except Exception as e:
                skipped[k] = f"{type(e).__name__}: {e}"
                continue
            made = len(self.fixtures) - before
            if made:
                applied.append({"kind": k, "count": made})
            else:
                skipped[k] = "no eligible candidate in this folder"
        return {"applied": applied, "skipped": skipped}


SEED_MARKER = ".canvas_audit_seeded.json"

# Fixture kinds that deliberately remove or move a tracked file, so its manifest
# row is SUPPOSED to point at nothing afterwards.
_LEAVES_ROW_DANGLING = frozenset({
    "deleted_locally", "renamed_row_intact", "renamed_row_dropped",
    "renamed_row_dropped_unrecognisable", "renamed_ambiguous",
    "renamed_substitution", "moved_deep", "moved_and_renamed",
    "unicode_rename", "long_path",
})
# Every dangling-row kind EXCEPT the one that leaves no file behind.
_RELOCATES_A_TRACKED_FILE = _LEAVES_ROW_DANGLING - {"deleted_locally"}
# Fixtures whose file is MEANT to stay unclaimed - decoys, foreign files,
# and the two renames that exist to prove adoption refuses.
_LEAVES_UNCLAIMED = frozenset({
    "foreign_content", "partial_artifact", "duplicate_copy",
    "decoy_same_size_ext", "renamed_substitution", "renamed_ambiguous",
})
# TWO different facts, and collapsing them was wrong in both directions.
#
# `_backdate` falsifies the manifest's `original_size` by one byte - that is its
# mechanism, without which `_is_canvas_newer` vetoes the change as a metadata
# touch. So EVERY kind that calls it leaves the recorded size diverging from
# disk, by design. Only `edited_update` also rewrites the file, so only it
# leaves the recorded md5 diverging.
#
# Declared as one set, the size half went unsuppressed for `readonly_target`
# (6 medium findings per run, every one the seeder's own falsification) while
# the md5 half was over-suppressed for `clean_update` - whose whole point is
# that original_md5 STILL MATCHES, so a real mismatch there was invisible.
#
# `_PERTURBS_RECORDED_SIZE` must list every fixture method that calls
# `_backdate`; `tests/test_audit_seed_expectations.py` enforces that statically,
# because the coupling is otherwise something each new fixture has to remember.
_PERTURBS_RECORDED_SIZE = frozenset({"clean_update", "edited_update",
                                     "readonly_target"})
# Relocating a tracked file has TWO consequences and the seeder must declare
# both: its manifest row now points at nothing (`_LEAVES_ROW_DANGLING`) AND its
# new path has no row (here). Only the first was declared, so the always-on
# "content file on disk with no manifest row" invariant reported the seeder's
# own renames - 14 findings across the 43-row plan.
#
# Whether the analyzer then ADOPTS the new path is a real question, and it has
# a real check: `sync_run`'s "classified as new, expected uptodate". Reporting
# it twice, once as an orphan, is what buried it. `deleted_locally` is excluded
# because it creates no new file - it only leaves the row dangling.
# Kinds that deliberately make a file's bytes diverge from the recorded baseline.
_DRIFTS_FROM_BASELINE = frozenset({"edited_update"})


def declarations(fixtures: list[dict]) -> dict:
    """What the seeder deliberately broke, so the invariants can stop policing it.

    The always-on invariants look for dangling manifest rows, md5 drift and
    ``.part`` leftovers - and the seeder creates all three ON PURPOSE, because
    they are the conditions the app is being asked to handle. Without these
    declarations the fixtures that PROVE the app behaved correctly are counted
    as evidence that it did not: a run where every category matched and every
    on-disk outcome was right still reported 4 broken manifest rows (the
    deleted-locally fixtures the user left unchecked), 2 md5 mismatches (the
    edited files whose bytes the app correctly preserved) and 2 stray partials
    (the fixtures testing that partials are ignored).

    Derived here rather than written only at seed time so an existing plan gets
    the same treatment, and so there is exactly ONE definition of "expected".
    """
    untracked = []
    for f in fixtures:
        kind = f.get("kind")
        # Refusal fixtures: the point is that the analyzer REFUSES to adopt the
        # renamed file, so it staying untracked IS the pass condition. Listing
        # only one of the two reported the other one's success as an orphan.
        if kind in _LEAVES_UNCLAIMED:
            untracked.append(f.get("path", ""))
        # A read-only destination makes the engine write a _NewVersion sibling
        # and repoint the row to it, leaving the original - the user's locked
        # copy - deliberately untracked. Verified on disk: both files present,
        # original still read-only, row on the sibling, and a second sync does
        # NOT re-offer the original.
        if kind == "readonly_target":
            untracked.append(f.get("path", ""))
        # A relocated file has no row at its NEW path until the analyzer adopts
        # it - and whether it did is `sync_run`'s question, with its own check.
        if kind in _RELOCATES_A_TRACKED_FILE:
            untracked.append(f.get("path", ""))
        if (f.get("extra") or {}).get("untracked_expected"):
            untracked.append(f["extra"]["untracked_expected"])

    return {
        "expected_untracked": sorted(set(untracked) - {""}),
        # The path the ROW still points at - which for a relocation is where
        # the file WAS, not where it now is. Declaring the new path instead
        # suppressed nothing and left the seeder's own moves reported as broken
        # manifest rows (6 on the busiest row of the 43). `deleted_locally`
        # records no `original_path` because it moved nothing, so it correctly
        # falls through to its own path.
        #
        # Deliberately NOT the new path as well: a row pointing at the new path
        # with no file there is a genuine adoption failure, and suppressing it
        # would hide the one thing this check is for.
        "expected_missing_rows": sorted({
            f.get("original_path") or f.get("expect_path") or f.get("path", "")
            for f in fixtures
            if f.get("kind") in _LEAVES_ROW_DANGLING} - {""}),
        "expected_md5_drift": sorted({
            f.get("path", "") for f in fixtures
            if f.get("kind") in _DRIFTS_FROM_BASELINE} - {""}),
        "expected_size_drift": sorted({
            f.get("path", "") for f in fixtures
            if f.get("kind") in _PERTURBS_RECORDED_SIZE} - {""}),
        "expected_partials": sorted({
            f.get("path", "") for f in fixtures
            if f.get("kind") == "partial_artifact"} - {""}),
    }


def already_seeded(folder: str | Path) -> dict | None:
    p = Path(folder) / SEED_MARKER
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"seeded_at": "unknown"}


def seed(folder: str | Path, kinds: list[str] | None = None,
         counts: dict | None = None, out_path: str | Path | None = None,
         again: bool = False) -> dict:
    """Fabricate sync scenarios in *folder*, ONCE.

    Seeding twice is not additive in any useful sense - the second pass reads a
    folder the first pass already rearranged, so fixtures land on fixtures and
    the plan it writes describes only its own half. Every category count then
    disagrees with the screen and the disagreement looks like an application
    bug. That cost a whole Phase 2 run: a ``seed apply`` that appeared to time
    out had in fact completed in its own process, the retry seeded on top of it,
    and the review screen came back with New at 20 against a plan predicting 10.

    The marker makes the second call refuse instead of silently corrupting the
    scenario. Restore a fresh snapshot rather than passing ``again`` - it takes
    about as long and yields a folder whose history is known.
    """
    prev = already_seeded(folder)
    if prev and not again:
        raise SystemExit(
            f"{Path(folder).name} was already seeded at {prev.get('seeded_at')} "
            f"({prev.get('fixture_count', '?')} fixtures). Seeding again layers "
            f"fixtures on fixtures and invalidates BOTH plans.\n"
            f"Restore a clean snapshot instead:\n"
            f"    python -m tests.audit snapshot restore <name> --pair\n"
            f"or pass --again if you genuinely want to stack them.")
    s = Seeder(folder)
    result = s.apply(kinds, counts)
    after_disk = odisk.scan(s.folder, full_hash=False)
    after_db = odb.read(s.folder)
    plan = {
        "folder": str(s.folder),
        "seeded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "applied": result["applied"],
        "skipped": result["skipped"],
        "fixture_count": len(s.fixtures),
        "expected_categories": _tally([f.expect_category for f in s.fixtures if f.expect_category]),
        **declarations([asdict(f) for f in s.fixtures]),
        "before": {"rows": s.info["row_count"], "files": s.disk["content_count"]},
        "after": {"rows": after_db["row_count"], "files": after_disk["content_count"]},
        "fixtures": [asdict(f) for f in s.fixtures],
    }
    p = Path(out_path) if out_path else (s.folder / "_audit_seed_plan.json")
    p.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    plan["plan_path"] = str(p)

    # The marker lives IN the folder, not beside the plan in the run's evidence
    # dir, because it is a property of the folder: a snapshot restore replaces
    # the folder and therefore clears it, which is exactly the semantics wanted.
    (s.folder / SEED_MARKER).write_text(json.dumps(
        {"seeded_at": plan["seeded_at"], "fixture_count": plan["fixture_count"],
         "plan_path": str(p)}, indent=2), encoding="utf-8")
    return plan


def restore_permissions(folder: str | Path, plan: dict) -> int:
    """Undo read-only fixtures so the folder can be cleaned up or re-seeded."""
    n = 0
    for fx in plan.get("fixtures", []):
        if fx.get("extra", {}).get("restore_mode"):
            p = Path(folder) / fx["path"]
            if p.exists():
                try:
                    os.chmod(p, 0o666)
                    n += 1
                except OSError:
                    pass
    return n


def _tally(items) -> dict:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
