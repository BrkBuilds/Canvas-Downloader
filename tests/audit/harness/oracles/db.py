"""Oracle O4 - the app's internal model of a course folder (``.canvas_sync.db``).

This is the oracle the other four cannot substitute for. The UI, the log and the
disk are all views of what happened during a run; the manifest is what the app
will BELIEVE on the next run, and a wrong belief is silent by construction:

* a manifest row whose ``local_path`` no longer exists makes the file read as
  "deleted locally" forever, so it is never re-downloaded and never mentioned;
* a file on disk with no row is re-offered as "New" on every single sync, which
  is the "wrongfully shows up as new" complaint in its purest form;
* a row whose ``original_size`` or ``original_md5`` does not describe the file
  actually on disk mis-classifies the next update as clean or modified, which
  decides whether the user's annotations survive.

The DB also carries the three CONTRACTS the folder was configured with, and
this project's own contract says the DB is the single source of truth for them.
So "did the settings the user chose in the UI actually reach the folder" is
answerable here and nowhere else.
"""

from __future__ import annotations

import json
import os
import sqlite3
# ── long-path awareness ──────────────────────────────────────────────────────
# The ORACLES must see what the app sees. On a machine with LongPathsEnabled=0
# a course folder past 260 characters answers False to Path.exists()/is_dir(),
# and an oracle that cannot see a folder does not under-report - it INVENTS:
# "the manifest is missing", "0 files on disk". Measured 2026-08-22: a real
# .canvas_sync.db at 266 chars, 65,536 bytes, read as absent.
from shared.helpers import make_long_path as _mlp  # noqa: E402

from pathlib import Path

DB_FILENAME = ".canvas_sync.db"

# Mirrors core.sync_manager.SECONDARY_ID_OFFSETS. Duplicated deliberately: the
# audit must be able to say "the app classified this id as an attachment" from
# outside the app, and importing the app's own table would make the check agree
# with the code it is auditing by construction.
SECONDARY_OFFSETS = {
    "module_item": 0, "assignment": 10_000_000, "syllabus": 20_000_000,
    "announcement": 30_000_000, "discussion": 40_000_000, "quiz": 50_000_000,
    "rubric": 60_000_000, "calendar": 70_000_000, "submission": 80_000_000,
    "attachment": 90_000_000,
}


def entity_type(canvas_file_id: int) -> str:
    if canvas_file_id >= 0:
        return "file"
    a = abs(canvas_file_id)
    for name, off in sorted(SECONDARY_OFFSETS.items(), key=lambda kv: kv[1], reverse=True):
        if a >= off:
            return name
    return "module_item"


def read(folder: str | Path) -> dict:
    folder = Path(folder)
    db = folder / DB_FILENAME
    if not os.path.isfile(_mlp(db)):
        return {"folder": str(folder), "exists": False}

    # Read-only URI so an audit read can never take a write lock on a DB the
    # running app is using, and never modifies the file it is auditing.
    # Read-only URI so an audit read can never take a write lock on a DB the
    # running app is using, and never modifies the file it is auditing.
    #
    # SQLITE'S URI PARSER CANNOT EXPRESS AN EXTENDED-LENGTH PATH. Measured
    # 2026-08-22 against a real manifest at 266 characters: every spelling of
    # `file:` + `\?\...` fails - backslashes and forward slashes give "unable
    # to open database file", and percent-encoding gives "invalid uri
    # authority: %3F". Only a PLAIN prefixed filename opens it, and that form
    # takes no `mode=ro`.
    #
    # So rather than trade the read-only guarantee for reach, a deep manifest is
    # COPIED through the prefix to a short temp path and the COPY is opened
    # read-only. The audited file is never opened read-write at all, which is a
    # stronger guarantee than the URI gave - and the manifest is small (64 KB on
    # the course this was measured against).
    _tmp_copy = None
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=15.0)
    except sqlite3.Error:
        try:
            import shutil as _shutil
            import tempfile as _tempfile
            _fd, _tmp_copy = _tempfile.mkstemp(suffix=".canvas_sync_audit.db")
            os.close(_fd)
            _shutil.copyfile(_mlp(db), _tmp_copy)
            con = sqlite3.connect(f"file:{Path(_tmp_copy).as_posix()}?mode=ro",
                                  uri=True, timeout=15.0)
        except (sqlite3.Error, OSError) as e:
            if _tmp_copy:
                try:
                    os.unlink(_tmp_copy)
                except OSError:
                    pass
            return {"folder": str(folder), "exists": True, "error": str(e)}

    out: dict = {"folder": str(folder), "exists": True, "db": str(db)}
    try:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        out["tables"] = sorted(tables)

        meta = {}
        if "sync_metadata" in tables:
            for r in con.execute("SELECT key, value FROM sync_metadata"):
                meta[r["key"]] = r["value"]
        out["metadata"] = {k: v for k, v in meta.items()
                           if k != "panopto_discovery_cache"}
        out["contracts"] = {
            "sync": _json(meta.get("sync_contract")),
            "secondary": _json(meta.get("secondary_content_contract")),
            "panopto": _json(meta.get("panopto_contract")),
        }
        out["course_id"] = _int(meta.get("course_id"))
        out["download_mode"] = meta.get("download_mode")
        cache = _json(meta.get("panopto_discovery_cache")) or {}
        out["panopto_discovery_cached"] = len(cache.get("videos", []))

        rows = []
        if "sync_manifest" in tables:
            for r in con.execute(
                    "SELECT canvas_file_id, canvas_filename, local_path, "
                    "canvas_updated_at, downloaded_at, original_size, is_ignored, "
                    "original_md5, content_sig FROM sync_manifest"):
                d = dict(r)
                d["entity"] = entity_type(int(d["canvas_file_id"]))
                d["is_ignored"] = bool(d["is_ignored"])
                rows.append(d)
        out["rows"] = rows
        out["row_count"] = len(rows)

        pan = []
        if "panopto_manifest" in tables:
            pan = [dict(r) for r in con.execute(
                "SELECT video_id, kind, local_path, title, downloaded_at "
                "FROM panopto_manifest")]
        out["panopto_rows"] = pan
        out["panopto_kinds"] = _tally(pan, "kind")

        ign = []
        if "panopto_ignored" in tables:
            ign = [dict(r) for r in con.execute(
                "SELECT video_id, title, ignored_at FROM panopto_ignored")]
        out["panopto_ignored"] = ign
    finally:
        con.close()
        if _tmp_copy:
            try:
                os.unlink(_tmp_copy)
            except OSError:
                pass

    out["by_entity"] = _tally(out.get("rows", []), "entity")
    out["ignored_count"] = sum(1 for r in out.get("rows", []) if r["is_ignored"])
    out["no_md5"] = sum(1 for r in out.get("rows", [])
                        if not r.get("original_md5") and r["canvas_file_id"] > 0)
    return out


def reconcile_with_disk(dbinfo: dict, diskinfo: dict) -> dict:
    """The O3 <-> O4 crosscheck, computed once and reused by every check.

    Path comparison is case- and separator-insensitive because the manifest
    stores the string the engine wrote while the disk scan produces the form
    ``os.walk`` yields; on Windows those differ in ways that mean nothing.
    """
    if not dbinfo.get("exists") or not diskinfo.get("exists"):
        return {"applicable": False}

    def key(p: str) -> str:
        return os.path.normcase(str(p).replace("\\", "/").strip("/"))

    on_disk = {key(f["rel"]): f for f in diskinfo["files"]
               if not f["app_generated"] and not f["partial"]}
    tracked: dict[str, dict] = {}
    ignored_paths: set[str] = set()
    dup_paths: dict[str, list[int]] = {}
    for r in dbinfo["rows"]:
        k = key(r["local_path"])
        # AN IGNORED ROW COMES IN TWO SHAPES AND THEY ARE NOT INTERCHANGEABLE.
        # `SyncManager.ignore_file` is an UPSERT:
        #
        #   * brand-new file  -> INSERT with local_path='' - nothing was ever
        #     written, and this is also how the engine records what it skipped
        #     (study filter, size cap) so a later sync does not re-offer it.
        #   * already downloaded -> ON CONFLICT ... SET is_ignored = 1, which
        #     leaves local_path AND downloaded_at intact, with the file still
        #     sitting on disk.
        #
        # Excluding BOTH from `tracked` made the second shape read as an orphan:
        # measured on course 43660, the two ignored fixtures were reported as
        # "2 content file(s) on disk with no manifest row" at HIGH, whose detail
        # says they "will be re-offered as New forever". They will not - the
        # analyzer has a row for them and files them under Ignored, which is
        # exactly where the review screen showed them. Not a seeding artefact
        # either: any user who ignores a file they already have produces it.
        #
        # The first shape still has to go, and `if not k` is what removes it -
        # keying them all on "" made them collide with each other (23 skipped
        # files under the study filter reported as "1 local path claimed by more
        # than one manifest row", which reads as data loss and is the opposite
        # of what happened).
        if not k:
            continue
        if r.get("is_ignored"):
            # Accounted for, but NOT tracked: the app maintains no expectation
            # about an ignored file's bytes, so it must stay out of the size and
            # md5 comparisons below, and out of `missing_on_disk` - a user is
            # free to delete a file they told the app to leave alone.
            ignored_paths.add(k)
            continue
        dup_paths.setdefault(k, []).append(r["canvas_file_id"])
        tracked[k] = r

    missing = []          # manifest says it is there; it is not
    for k, r in tracked.items():
        if k not in on_disk:
            missing.append({"canvas_file_id": r["canvas_file_id"],
                            "entity": r["entity"],
                            "local_path": r["local_path"],
                            "canvas_filename": r["canvas_filename"]})

    untracked = []        # on disk, no row - will be re-offered as New forever
    for k, f in on_disk.items():
        if k not in tracked and k not in ignored_paths:
            untracked.append({"rel": f["rel"], "size": f["size"], "ext": f["ext"],
                              "secondary_html": f["secondary_html"],
                              "new_version": f["new_version"]})

    size_mismatch = []    # row describes a different object than the file
    for k, r in tracked.items():
        f = on_disk.get(k)
        if not f or r["canvas_file_id"] < 0:
            continue      # secondary entities are stored with size 0 by design
        if r["original_size"] and f["size"] != r["original_size"]:
            size_mismatch.append({"local_path": r["local_path"],
                                  "manifest_size": r["original_size"],
                                  "disk_size": f["size"]})

    md5_mismatch = []
    for k, r in tracked.items():
        f = on_disk.get(k)
        if not f or not r.get("original_md5") or not f.get("md5"):
            continue
        if f["md5"] != r["original_md5"]:
            md5_mismatch.append({"local_path": r["local_path"]})

    return {
        "applicable": True,
        "tracked": len(tracked),
        # Reported separately so "why is this file not in either list?" has an
        # answer in the evidence rather than only in this function.
        "ignored_on_disk": sorted(k for k in ignored_paths if k in on_disk),
        "on_disk": len(on_disk),
        "missing_on_disk": missing,
        "untracked_on_disk": untracked,
        "size_mismatch": size_mismatch,
        "md5_mismatch": md5_mismatch,
        "duplicate_local_paths": {k: v for k, v in dup_paths.items() if len(v) > 1},
        "counts": {
            "missing_on_disk": len(missing),
            "untracked_on_disk": len(untracked),
            "size_mismatch": len(size_mismatch),
            "md5_mismatch": len(md5_mismatch),
        },
    }


def brief(dbinfo: dict) -> dict:
    return {k: v for k, v in dbinfo.items()
            if k not in ("rows", "panopto_rows", "metadata")}


def _json(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return {"_unparseable": str(s)[:200]}


def _int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _tally(rows: list[dict], field: str) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        out[str(r.get(field))] = out.get(str(r.get(field)), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
