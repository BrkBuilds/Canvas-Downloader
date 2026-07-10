"""Prime synced course folders so a manual Quick Sync produces a known,
predictable set of changes to eyeball on the Today page.

Per folder, this deletes N files from disk (plus their manifest rows) so they
resurface as **New**, and back-dates M intact rows so they resurface as
**Clean Update**. Quick Sync then downloads exactly N New + M Clean Updates,
giving the Today page's "Today's files" section and its sync-history sibling a
mixed, non-trivial payload to render.

    python scripts/seed_today_test.py "C:\\path\\to\\Course A" "C:\\path\\to\\Course B"
    python scripts/seed_today_test.py --dry-run "C:\\path\\to\\Course A"
    python scripts/seed_today_test.py --new 3 --updates 8 "C:\\path\\to\\Course A"

This DELETES FILES and edits .canvas_sync.db in place. No backup is taken - the
folder is disposable test fixture, re-downloadable from Canvas in a couple of
minutes. Point it at a scratch course folder, never at anything you care about.

--- Why the mutations look the way they do -------------------------------

New: the manifest row is deleted AND the file is removed from disk. Deleting
only the row is not enough - ``analyze_course`` auto-discovers untracked
on-disk files by name / md5 / unique size+ext and silently re-adopts them as
*up-to-date*, so the file never appears on the Today page at all. Candidates
whose bytes could be claimed by some OTHER unclaimed file still on disk are
rejected by ``_would_be_adopted`` below.

Clean Update: back-dating ``canvas_updated_at`` alone is NOT enough either.
``_is_canvas_newer`` vetoes a newer Canvas timestamp as a "metadata touch" when
the byte count is unchanged, so ``original_size`` is also knocked off by one.
``original_md5`` is deliberately left matching the on-disk file, which is what
makes ``_classify_local_modification`` return 'clean' (-> updated_clean_files)
rather than 'modified' (-> updated_modified_files, which Quick Sync skips).
Canvas's file API exposes no md5, so the md5 short-circuit at the top of
``_is_canvas_newer`` never fires and the timestamp path is reached.

Only positive (real Canvas file) ids are used. Synthetic secondary entities
(negative ids: announcements, pages, assignments) compare by content signature
rather than timestamp, and depend on the folder's secondary-content contract
being enabled - both make them unreliable as update fixtures.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.sync_manager import (  # noqa: E402
    DB_FILENAME,
    MANIFEST_FILENAME,
    SYNC_HISTORY_FILENAME,
    SYNC_PAIRS_FILENAME,
    SAVED_GROUPS_FILENAME,
    _APP_GENERATED_FILES,
    _CONTENT_MATCH_MAX_BYTES,
    _is_archive_path,
    _is_partial_artifact,
    _match_key,
    compute_local_md5,
)

# Back-dated far enough that no real Canvas timestamp can be older.
OLD_TS = "2020-01-01T00:00:00Z"

# Post-processing bypasses: a missing .url/.webloc or archive is treated as
# "converted away", never as new/deleted. Useless as fixtures.
BYPASS_EXTS = {".url", ".webloc"}

COLS = ("canvas_file_id", "canvas_filename", "local_path", "canvas_updated_at",
        "downloaded_at", "original_size", "is_ignored", "original_md5")


# --------------------------------------------------------------------------
# disk / manifest inspection
# --------------------------------------------------------------------------

def _walk_content_files(root: Path) -> list[Path]:
    """Every on-disk file the analyzer would consider Canvas content.

    Mirrors the exclusion list in ``SyncManager.heal_manifest``'s orphan walk.
    """
    skip_names = {MANIFEST_FILENAME, DB_FILENAME, SYNC_PAIRS_FILENAME,
                  SYNC_HISTORY_FILENAME, SAVED_GROUPS_FILENAME} | _APP_GENERATED_FILES
    out: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn in skip_names or fn.startswith(".canvas_sync") or _is_partial_artifact(fn):
                continue
            out.append(Path(dirpath) / fn)
    return out


def _read_rows(db: Path) -> list[dict]:
    with sqlite3.connect(str(db)) as con:
        cur = con.execute(f"SELECT {', '.join(COLS)} FROM sync_manifest")
        return [dict(zip(COLS, r)) for r in cur.fetchall()]


def _row_is_clean(root: Path, row: dict) -> bool:
    """File exists on disk and is byte-identical to what we downloaded."""
    p = root / row["local_path"]
    if not p.is_file() or not row["original_md5"]:
        return False
    return compute_local_md5(p) == row["original_md5"]


def _eligible(root: Path, row: dict) -> bool:
    """Usable as either fixture kind."""
    if row["is_ignored"]:
        return False
    if int(row["canvas_file_id"]) <= 0:          # synthetic secondary entity
        return False
    lp = row["local_path"]
    if Path(lp).suffix.lower() in BYPASS_EXTS or _is_archive_path(lp):
        return False
    return _row_is_clean(root, row)


# --------------------------------------------------------------------------
# the orphan-adoption guard
# --------------------------------------------------------------------------

def _would_be_adopted(row: dict, unclaimed: list[dict]) -> str:
    """Reason this row would be re-adopted as up-to-date instead of New, or ''.

    Reproduces the three auto-discovery tiers of ``analyze_course``:
      (a) name match  - normalized name equal AND size equal (real files)
      (b) md5 match   - same size and same content hash
      (c) size+ext    - exactly one same-size, same-extension candidate
    """
    size = row["original_size"]
    ext = Path(row["local_path"]).suffix.lower()
    name_keys = {_match_key(Path(row["local_path"]).name), _match_key(row["canvas_filename"] or "")}
    name_keys.discard("")

    same_size = [u for u in unclaimed if u["size"] == size]

    for u in same_size:
        if _match_key(u["path"].name) in name_keys:
            return f"name+size match: {u['rel']}"

    if row["original_md5"] and size <= _CONTENT_MATCH_MAX_BYTES:
        for u in same_size:
            if u["md5"] is None:
                u["md5"] = compute_local_md5(u["path"])
            if u["md5"] == row["original_md5"]:
                return f"md5 match: {u['rel']}"

    if ext:
        ext_pool = [u for u in same_size if u["path"].suffix.lower() == ext]
        if len(ext_pool) == 1:
            return f"unique size+ext match: {ext_pool[0]['rel']}"
    return ""


# --------------------------------------------------------------------------
# candidate selection
# --------------------------------------------------------------------------

def _spread(rows: list[dict], n: int) -> list[dict]:
    """Pick n rows spread across distinct parent folders, smallest first.

    The spread makes the sync-history sibling group by module folder - the
    interesting case for the Today card - and preferring small files keeps the
    Quick Sync download short.
    """
    by_parent: dict[str, list[dict]] = {}
    for r in sorted(rows, key=lambda r: r["original_size"]):
        by_parent.setdefault(str(Path(r["local_path"]).parent), []).append(r)

    picked: list[dict] = []
    while len(picked) < n and any(by_parent.values()):
        for parent in sorted(by_parent):
            if len(picked) >= n:
                break
            if by_parent[parent]:
                picked.append(by_parent[parent].pop(0))
    return picked


def plan_folder(root: Path, n_new: int, n_upd: int) -> dict:
    db = root / DB_FILENAME
    if not db.is_file():
        raise SystemExit(f"No {DB_FILENAME} in {root} - is this a synced course folder?")

    rows = _read_rows(db)
    claimed = {os.path.normcase(os.path.normpath(str(root / r["local_path"]))) for r in rows}
    unclaimed = []
    for p in _walk_content_files(root):
        if os.path.normcase(os.path.normpath(str(p))) not in claimed:
            unclaimed.append({"path": p, "rel": p.relative_to(root).as_posix(),
                              "size": p.stat().st_size, "md5": None})

    eligible = [r for r in rows if _eligible(root, r)]

    # New: must be safe from orphan re-adoption.
    safe, rejected = [], []
    for r in eligible:
        why = _would_be_adopted(r, unclaimed)
        (rejected if why else safe).append((r, why))
    new_rows = _spread([r for r, _ in safe], n_new)

    # Updates: disjoint from the delete set; adoption is irrelevant (row stays).
    new_ids = {r["canvas_file_id"] for r in new_rows}
    upd_rows = _spread([r for r in eligible if r["canvas_file_id"] not in new_ids], n_upd)

    return {
        "root": root, "db": db, "rows": rows,
        "new": new_rows, "updates": upd_rows,
        "rejected": [(r, why) for r, why in rejected if why],
        "unclaimed": unclaimed,
    }


# --------------------------------------------------------------------------
# apply / verify
# --------------------------------------------------------------------------

def apply_plan(plan: dict) -> None:
    root, db = plan["root"], plan["db"]
    try:
        con = sqlite3.connect(str(db), timeout=10.0)
    except sqlite3.OperationalError as e:
        raise SystemExit(f"Cannot open {db}: {e}\nIs Canvas Downloader still running? Close it first.")

    with con:
        for r in plan["new"]:
            con.execute("DELETE FROM sync_manifest WHERE canvas_file_id=?", (r["canvas_file_id"],))
            (root / r["local_path"]).unlink()
            print(f"  NEW       deleted row + file          {r['local_path']}")

        for r in plan["updates"]:
            disk = (root / r["local_path"]).stat().st_size
            fake = disk - 1 if disk > 1 else disk + 1
            con.execute(
                "UPDATE sync_manifest SET canvas_updated_at=?, original_size=? WHERE canvas_file_id=?",
                (OLD_TS, fake, r["canvas_file_id"]),
            )
            print(f"  UPDATE    backdated, size {disk}->{fake}   {r['local_path']}")
    con.close()

    # Prune folders emptied by the deletions, so the module folder itself
    # reappears when Quick Sync re-downloads (matches a real user deletion).
    for r in plan["new"]:
        parent = (root / r["local_path"]).parent
        while parent != root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            print(f"  pruned empty dir              {parent.relative_to(root).as_posix()}/")
            parent = parent.parent


def verify(plan: dict) -> bool:
    """Re-read the mutated DB and assert every fixture landed in its bucket."""
    root = plan["root"]
    rows = {r["canvas_file_id"]: r for r in _read_rows(plan["db"])}
    ok = True

    for r in plan["new"]:
        if r["canvas_file_id"] in rows:
            print(f"  FAIL row {r['canvas_file_id']} still in manifest"); ok = False
        if (root / r["local_path"]).exists():
            print(f"  FAIL file still on disk: {r['local_path']}"); ok = False

    for r in plan["updates"]:
        cur = rows.get(r["canvas_file_id"])
        if not cur:
            print(f"  FAIL update row {r['canvas_file_id']} vanished"); ok = False
            continue
        p = root / cur["local_path"]
        disk = p.stat().st_size
        backdated = cur["canvas_updated_at"] == OLD_TS
        size_differs = cur["original_size"] != disk              # beats the metadata-touch veto
        md5_clean = cur["original_md5"] == compute_local_md5(p)  # -> 'clean', not 'modified'
        if not (backdated and size_differs and md5_clean):
            print(f"  FAIL {cur['local_path']}: backdated={backdated} "
                  f"size_differs={size_differs} md5_clean={md5_clean}"); ok = False
    return ok


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prime course folders for a manual Quick Sync on the Today page. Deletes files.")
    ap.add_argument("folders", nargs="+", help="Synced course folder(s) containing .canvas_sync.db")
    ap.add_argument("--new", type=int, default=5, help="files to delete per folder (default 5)")
    ap.add_argument("--updates", type=int, default=5, help="rows to back-date per folder (default 5)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    args = ap.parse_args()

    roots = [Path(f).resolve() for f in args.folders]
    for r in roots:
        if not r.is_dir():
            raise SystemExit(f"Not a directory: {r}")

    plans = [plan_folder(root, args.new, args.updates) for root in roots]

    exit_code = 0
    for plan in plans:
        root = plan["root"]
        print(f"\n{'=' * 78}\n{root.name}\n{'=' * 78}")
        print(f"  manifest rows: {len(plan['rows'])}   unclaimed files on disk: {len(plan['unclaimed'])}")

        if plan["rejected"]:
            print(f"  skipped {len(plan['rejected'])} row(s) that an unclaimed file would re-adopt:")
            for r, why in plan["rejected"][:5]:
                print(f"    - {r['local_path']}  ({why})")

        short = []
        if len(plan["new"]) < args.new:
            short.append(f"{len(plan['new'])}/{args.new} New")
        if len(plan["updates"]) < args.updates:
            short.append(f"{len(plan['updates'])}/{args.updates} Updates")
        if short:
            print(f"  WARNING: only found {', '.join(short)} - not enough clean, eligible files.")
            exit_code = 1

        if args.dry_run:
            for r in plan["new"]:
                print(f"  [dry] NEW     {r['local_path']}")
            for r in plan["updates"]:
                print(f"  [dry] UPDATE  {r['local_path']}")
            continue

        apply_plan(plan)
        passed = verify(plan)
        print("  verify:", "PASS" if passed else "FAIL")
        if not passed:
            exit_code = 1

    if not args.dry_run:
        print(f"\nPrimed {len(plans)} folder(s). Now: open the app -> Today page -> Quick Sync now.\n"
              f"Only Quick Sync writes sync_mode='quick', which is what Today's files filters on.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
