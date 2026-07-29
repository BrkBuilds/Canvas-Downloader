"""Download once, exercise many - a golden copy of a synced course folder.

Almost every sync-side scenario needs the same expensive precondition: a course
folder that has genuinely been downloaded by the app, with a real
``.canvas_sync.db`` written by the real engine. Producing that costs a full
download - minutes of network for a small course, the better part of an hour for
a large one - and the audit needs dozens of them, each starting from the same
pristine state. Re-downloading per scenario is not thoroughness, it is the same
work repeated until the suite is too slow to run.

So the folder is downloaded ONCE per course, captured here, and restored per
scenario. The restore is a plain copy on the same volume - seconds instead of
minutes - and it is a genuine copy rather than a link because the scenarios
*mutate* what they restore (that is what seeding is).

Three things make this correct rather than merely convenient:

**The manifest is location-independent.** ``sync_manifest.local_path`` is stored
relative to the sync root, and ``sync_metadata`` holds only course identity, the
contract and conversion products - all relative. Verified against a real 206-row
manifest before this module was written. So a folder captured at path A and
restored at path B needs no rewriting, and a scenario cannot be poisoned by a
stale absolute path. The absolute paths all live in the config dir
(``canvas_sync_pairs.json`` and friends), which every lane owns privately.

**The database is captured through SQLite's backup API, not by copying bytes.**
The app may hold the DB open with a populated WAL; copying the file alone would
capture a torn state, and copying the ``-wal`` alongside it would depend on
replay working across a copy. ``Connection.backup()`` produces a fully
checkpointed, internally consistent database from a live one, which is precisely
the problem it exists to solve. A torn manifest would not crash - it would
silently mis-classify files in every scenario derived from it, which is the
worst failure this suite could have.

**The golden copy is made read-only.** A snapshot that is silently written to
invalidates every future run derived from it, with no error and no way to notice
after the fact. The read-only bit is cheap insurance against exactly that, and
is cleared on the restored copy so the app can work normally.

Long paths are handled throughout: extracted archive trees in this project
routinely exceed MAX_PATH, and the plain Windows APIs fail on them in ways that
look like missing files.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from .paths import RUNS_ROOT

SNAPSHOT_ROOT = RUNS_ROOT / "_snapshots"

DB_NAME = ".canvas_sync.db"
# Never copied: the backup API below produces a checkpointed database, so the
# write-ahead log and shared-memory index are not only redundant but actively
# misleading - they would describe a transaction history the copy no longer has.
DB_SIDECARS = (".canvas_sync.db-wal", ".canvas_sync.db-shm", ".canvas_sync.db-journal")

FILE_ATTRIBUTE_READONLY = 0x01
FILE_ATTRIBUTE_HIDDEN = 0x02
FILE_ATTRIBUTE_NORMAL = 0x80


# --------------------------------------------------------------------------
# windows path / attribute plumbing
# --------------------------------------------------------------------------

def _lp(p: Path | str) -> str:
    r"""Extended-length form of an absolute path.

    Archive extraction in this project produces trees deeper than MAX_PATH, and
    the ANSI/short-path APIs do not fail loudly on those - they report the file
    as absent. Everything here goes through ``\\?\`` so a deep tree is copied
    and inventoried in full rather than quietly truncated.
    """
    s = os.fspath(p)
    if os.name != "nt":
        return s
    s = os.path.abspath(s)
    if s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def _unlp(p: Path | str) -> Path:
    r"""Plain form of a path that may carry the extended-length prefix.

    ``os.walk`` yields roots in whatever form it was given, so every path
    derived from a ``\\?\`` walk carries the prefix. That is correct for the
    filesystem APIs and WRONG for anything that parses a path as a URI: SQLite
    reads ``file://?/G:/...`` as having the authority ``?`` and refuses to open
    it. The failure is reported rather than raised, so without this the manifest
    would quietly fall back to a byte copy on every capture.
    """
    s = os.fspath(p)
    if s.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + s[8:])
    if s.startswith("\\\\?\\"):
        return Path(s[4:])
    return Path(s)


def _set_attr(path: Path, flag: int, on: bool) -> bool:
    if os.name != "nt":
        return False
    try:
        k32 = ctypes.windll.kernel32
        cur = k32.GetFileAttributesW(_lp(path))
        if cur == -1:
            return False
        new = (cur | flag) if on else (cur & ~flag)
        if new == 0:
            new = FILE_ATTRIBUTE_NORMAL
        return bool(k32.SetFileAttributesW(_lp(path), new))
    except Exception:
        return False


def _make_writable(path: Path) -> None:
    """Clear read-only on a whole tree so it can be replaced or written to."""
    for root, dirs, files in os.walk(_lp(path)):
        for name in files:
            p = Path(root) / name
            _set_attr(p, FILE_ATTRIBUTE_READONLY, False)
            try:
                os.chmod(p, 0o666)
            except OSError:
                pass
        for name in dirs:
            _set_attr(Path(root) / name, FILE_ATTRIBUTE_READONLY, False)


def _rmtree(path: Path, attempts: int = 8, pause: float = 0.4) -> None:
    r"""Delete a tree, tolerating a handle another process is still closing.

    ``WinError 32`` is not a permission problem - ``_make_writable`` above
    already handles the read-only bit - it is "the file is in use". A lane
    keeps ONE app alive across all its rows, and that app holds
    ``.canvas_sync.db`` open; when the next row clears the destination folder
    a moment later, the handle is often still on its way out. Measured on sync
    row s041: the restore failed instantly on
    ``...\downloads\<course>\.canvas_sync.db`` and the very same row succeeded
    on retry 24 seconds later, having changed nothing.

    So a single attempt is a coin flip on a busy machine. Retrying briefly is
    the same remedy this project already applies to ``.part`` cleanup after a
    cancelled transcription, and for the same reason: the loser of that race
    is a whole row, and the failure looks like a defect in whatever ran next.
    """
    if not path.exists():
        return
    last = None
    for i in range(attempts):
        _make_writable(path)
        try:
            shutil.rmtree(_lp(path), ignore_errors=False)
            return
        except PermissionError as e:          # WinError 32 / 5
            last = e
            time.sleep(pause * (i + 1))
        except OSError as e:
            if getattr(e, "winerror", None) != 32:
                raise
            last = e
            time.sleep(pause * (i + 1))
    if path.exists():
        raise last if last else OSError(f"could not remove {path}")


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------

# Filenames only the audit's own seeder produces. A folder containing them has
# been through a scenario already, so it is not a baseline - see `_audit_traces`.
_FIXTURE_MARKERS = ("GhostFile_", "zz omdøbt uden række", "zz flertydig",
                    "decoy 0 unrelated", "decoy 1 unrelated", " - copy for exam")
SEED_MARKER = ".canvas_audit_seeded.json"


def _audit_traces(src: Path) -> list[str]:
    """Evidence that *src* has already been used as a scenario, not a baseline."""
    found = []
    if (src / SEED_MARKER).is_file():
        found.append(SEED_MARKER)
    for root, _dirs, files in os.walk(_lp(src)):
        for f in files:
            if any(m in f for m in _FIXTURE_MARKERS):
                found.append(os.path.relpath(os.path.join(root, f), _lp(src)))
                if len(found) >= 8:
                    return found
    return found


def capture(src: Path | str, name: str, *, course_id: int | None = None,
            course_name: str = "", config: dict | None = None, note: str = "",
            deep: bool = False, overwrite: bool = False,
            allow_seeded: bool = False) -> dict:
    """Freeze *src* (a downloaded course folder) as the snapshot *name*.

    Refuses a folder that has already been seeded, because a snapshot is only
    useful as a KNOWN starting point. Capturing a mid-audit folder produces a
    baseline that silently carries the previous scenario's fixtures: every later
    run then seeds on top of them and the review screen reports categories no
    plan predicts - New at 20 against a plan expecting 10, with nothing to say
    why. That happened, and the numbers were reproducible enough to look like a
    product defect rather than a poisoned baseline.
    """
    src = Path(src).resolve()
    if not src.is_dir():
        raise SystemExit(f"Not a folder: {src}")

    traces = _audit_traces(src)
    if traces and not allow_seeded:
        raise SystemExit(
            f"{src.name} carries audit fixtures, so it is not a clean baseline:\n"
            + "".join(f"    {t}\n" for t in traces[:6])
            + "A snapshot is only useful as a KNOWN starting point; seeding on "
              "top of an unknown one makes every category count unexplainable.\n"
              "Download the course fresh and capture that, or pass "
              "--allow-seeded if you deliberately want a mid-scenario baseline.")

    store = SNAPSHOT_ROOT / name
    if store.exists():
        if not overwrite:
            raise SystemExit(f"Snapshot {name!r} already exists. Pass --overwrite "
                             f"to replace it, or pick another name.")
        _rmtree(store)

    payload = store / "payload" / src.name
    payload.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    inv, db_info = _copy_tree(src, payload, deep=deep)
    _protect(store / "payload")

    meta = {
        "name": name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "source": str(src),
        "folder_name": src.name,
        "course_id": course_id,
        "course_name": course_name,
        "config": config or {},
        "note": note,
        "files": len(inv),
        "bytes": sum(v["size"] for v in inv.values()),
        "deep": deep,
        "seconds": round(time.time() - t0, 2),
        "manifest": db_info,
        "inventory": inv,
    }
    (store / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return _summary(meta)


def _copy_tree(src: Path, dst: Path, *, deep: bool) -> tuple[dict, dict]:
    """Copy *src* into *dst*, inventorying as it goes.

    The manifest is not copied as a file - see the module docstring. Everything
    else is a straight ``copy2`` so timestamps survive, because the app's own
    change detection is content-based but a scenario that wants to assert
    "untouched" is easier to trust when mtimes are preserved too.
    """
    inv: dict[str, dict] = {}
    db_info: dict = {"present": False}

    for root, dirs, files in os.walk(_lp(src)):
        rel_root = os.path.relpath(root, _lp(src))
        rel_root = "" if rel_root == "." else rel_root
        target_root = dst / rel_root if rel_root else dst
        target_root.mkdir(parents=True, exist_ok=True)

        for fname in files:
            if fname in DB_SIDECARS:
                continue
            s = Path(root) / fname
            d = target_root / fname
            rel = (Path(rel_root) / fname).as_posix() if rel_root else fname

            if fname == DB_NAME:
                db_info = _backup_db(s, d)
                st = os.stat(_lp(d))
                inv[rel] = {"size": st.st_size, "db": True}
                continue

            try:
                shutil.copy2(_lp(s), _lp(d))
                st = os.stat(_lp(d))
            except OSError as e:
                inv[rel] = {"size": -1, "error": str(e)}
                continue
            entry = {"size": st.st_size, "mtime": round(st.st_mtime, 3)}
            if deep:
                entry["md5"] = _md5(d)
            inv[rel] = entry

    return inv, db_info


def _backup_db(src: Path, dst: Path) -> dict:
    """Checkpointed copy of a live SQLite database.

    Opened read-only via a URI so capturing can never mutate the folder being
    captured, and ``backup()`` rather than a byte copy so a populated WAL is
    folded in instead of being lost or half-applied.
    """
    info: dict = {"present": True}
    try:
        uri = _unlp(src).resolve().as_uri() + "?mode=ro"
        srcdb = sqlite3.connect(uri, uri=True, timeout=30)
        try:
            out = sqlite3.connect(str(dst))
            try:
                srcdb.backup(out)
                out.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                info["rows"] = out.execute(
                    "SELECT COUNT(*) FROM sync_manifest").fetchone()[0]
                info["metadata"] = {
                    k: (v[:200] if isinstance(v, str) else v) for k, v in
                    out.execute("SELECT key, value FROM sync_metadata")
                    if k in ("course_id", "course_name", "download_mode")
                }
                try:
                    info["panopto_rows"] = out.execute(
                        "SELECT COUNT(*) FROM panopto_manifest").fetchone()[0]
                except sqlite3.Error:
                    info["panopto_rows"] = 0
                ok = out.execute("PRAGMA integrity_check").fetchone()
                info["integrity"] = ok[0] if ok else "?"
            finally:
                out.close()
        finally:
            srcdb.close()
    except Exception as e:
        # Fall back to a byte copy rather than losing the manifest entirely, but
        # SAY SO - a scenario built on a torn manifest must not look healthy.
        info.update({"backup_failed": str(e), "fallback": "bytes"})
        try:
            shutil.copy2(_lp(src), _lp(dst))
        except OSError as e2:
            info["copy_failed"] = str(e2)
    return info


def _protect(payload: Path) -> None:
    for root, _dirs, files in os.walk(_lp(payload)):
        for name in files:
            _set_attr(Path(root) / name, FILE_ATTRIBUTE_READONLY, True)


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(_lp(p), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# restore
# --------------------------------------------------------------------------

def restore(name: str, dest_parent: Path | str, *, folder_name: str = "",
            overwrite: bool = True, verify: bool = True) -> dict:
    """Materialise snapshot *name* inside *dest_parent* and hand back its path."""
    meta = read_meta(name)
    store = SNAPSHOT_ROOT / name
    payload = store / "payload" / meta["folder_name"]
    if not payload.is_dir():
        raise SystemExit(f"Snapshot {name!r} has no payload at {payload}")

    dest_parent = Path(dest_parent)
    dest = dest_parent / (folder_name or meta["folder_name"])
    if dest.exists():
        if not overwrite:
            raise SystemExit(f"{dest} already exists")
        _rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    copied, missing = 0, []
    for root, _dirs, files in os.walk(_lp(payload)):
        rel_root = os.path.relpath(root, _lp(payload))
        rel_root = "" if rel_root == "." else rel_root
        target_root = dest / rel_root if rel_root else dest
        target_root.mkdir(parents=True, exist_ok=True)
        for fname in files:
            s, d = Path(root) / fname, target_root / fname
            try:
                shutil.copy2(_lp(s), _lp(d))
            except OSError as e:
                missing.append({"path": fname, "error": str(e)})
                continue
            # The golden copy is read-only; the working copy must not be, or the
            # app fails to write with a permission error that reads like a bug.
            _set_attr(d, FILE_ATTRIBUTE_READONLY, False)
            try:
                os.chmod(d, 0o666)
            except OSError:
                pass
            if fname == DB_NAME:
                # Restore the hidden bit so the working folder is indistinguishable
                # from one the app produced itself.
                _set_attr(d, FILE_ATTRIBUTE_HIDDEN, True)
            copied += 1

    out = {"snapshot": name, "path": str(dest), "files": copied,
           "seconds": round(time.time() - t0, 2), "errors": missing}
    if verify:
        out["verify"] = verify_restore(name, dest)
    return out


def verify_restore(name: str, dest: Path | str) -> dict:
    """Compare a restored folder against the snapshot's recorded inventory.

    Size and presence only, deliberately: this is a same-volume copy, so the
    realistic failure is an OMITTED file (locked, too deep, permission), not a
    corrupted one. Checking every byte would cost minutes per restore and buy
    almost nothing; ``--deep`` at capture time is there when it is wanted.
    """
    meta = read_meta(name)
    inv = meta.get("inventory", {})
    dest = Path(dest)
    missing, wrong = [], []
    for rel, want in inv.items():
        p = dest / rel
        try:
            size = os.stat(_lp(p)).st_size
        except OSError:
            missing.append(rel)
            continue
        if want.get("size", -1) >= 0 and size != want["size"]:
            wrong.append({"path": rel, "expected": want["size"], "actual": size})
    extra = []
    for root, _dirs, files in os.walk(_lp(dest)):
        rel_root = os.path.relpath(root, _lp(dest))
        rel_root = "" if rel_root == "." else rel_root
        for fname in files:
            if fname in DB_SIDECARS:
                continue
            rel = (Path(rel_root) / fname).as_posix() if rel_root else fname
            if rel not in inv:
                extra.append(rel)
    return {"expected": len(inv), "missing": missing[:20], "missing_count": len(missing),
            "size_mismatch": wrong[:20], "extra": extra[:20], "extra_count": len(extra),
            "ok": not missing and not wrong and not extra}


# --------------------------------------------------------------------------
# inspection
# --------------------------------------------------------------------------

def read_meta(name: str) -> dict:
    p = SNAPSHOT_ROOT / name / "meta.json"
    if not p.is_file():
        raise SystemExit(f"No snapshot named {name!r} (looked in {SNAPSHOT_ROOT})")
    return json.loads(p.read_text(encoding="utf-8"))


def list_snapshots() -> list[dict]:
    if not SNAPSHOT_ROOT.is_dir():
        return []
    out = []
    for d in sorted(SNAPSHOT_ROOT.iterdir()):
        if not d.is_dir():
            continue
        try:
            out.append(_summary(read_meta(d.name)))
        except SystemExit:
            out.append({"name": d.name, "broken": "no meta.json"})
    return out


def drop(name: str) -> dict:
    store = SNAPSHOT_ROOT / name
    if not store.is_dir():
        return {"name": name, "status": "absent"}
    _rmtree(store)
    return {"name": name, "status": "dropped"}


def _summary(meta: dict) -> dict:
    man = meta.get("manifest") or {}
    out = {
        "name": meta.get("name"),
        "created": meta.get("created"),
        "folder_name": meta.get("folder_name"),
        "course_id": meta.get("course_id"),
        "files": meta.get("files"),
        "mb": round(meta.get("bytes", 0) / (1024 * 1024), 1),
        "manifest_rows": man.get("rows"),
        "manifest_integrity": man.get("integrity"),
        "note": meta.get("note", ""),
        "seconds": meta.get("seconds"),
    }
    # A byte-copied manifest may be torn if the app held the DB open, and every
    # scenario restored from it would mis-classify files while looking healthy.
    # Say so in the summary rather than leaving a null field to be read as "no
    # manifest" - that ambiguity is what hid the URI bug on the first capture.
    if man.get("backup_failed"):
        out["MANIFEST_WARNING"] = (
            f"checkpointed copy failed ({man['backup_failed']}); fell back to a "
            f"byte copy - trustworthy only if the app was not running")
    elif not man.get("present"):
        out["MANIFEST_WARNING"] = "no .canvas_sync.db in the source folder"
    return out


def auto_name(course_id: int, label: str = "base") -> str:
    return f"c{course_id}_{label}"
