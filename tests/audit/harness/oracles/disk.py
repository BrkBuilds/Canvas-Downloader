"""Oracle O3 - what actually exists on disk.

The end result. Everything else in this suite is a claim; this is the thing the
user opens on Monday morning. A run that logs 234 saves and shows a green
completion card has still failed if the folder holds 233 files and one of them
is zero bytes.

Hashing policy: every file gets a **quick signature** (size + md5 of the first
and last 256 KB), and files under ``FULL_HASH_LIMIT`` also get a full md5. The
split is not laziness - one of the target courses contains a 470 MB PowerPoint,
and hashing the whole folder fully on every check would make the audit too slow
to run often, which is the failure mode that kills test suites. The quick
signature is sufficient for the questions actually asked here (did this file
change between two observations, are these two files the same object), because
a truncated or partially-written download differs in size or in its tail, and
that is exactly the corruption class we are hunting.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

FULL_HASH_LIMIT = 64 * 1024 * 1024
CHUNK = 256 * 1024

# Files the app itself writes into a course folder. They are not study material
# and must never be counted as Canvas content - the sync engine excludes them
# from orphan healing for the same reason.
APP_GENERATED = {
    "debug_log.txt", "download_errors.txt", "☁️ Canvas Updates & Deletions.txt",
    ".canvas_sync.db", ".canvas_sync_manifest.json",
    "canvas_sync_pairs.json", "canvas_sync_history.json", "saved_sync_groups.json",
    # The audit's own bookkeeping. It lives in the folder so that restoring a
    # snapshot clears it, which means it must be excluded HERE or the harness
    # reports its own marker as an untracked Canvas file - a finding created
    # entirely by the tool looking for findings.
    ".canvas_audit_seeded.json", "_audit_seed_plan.json",
}

# Outputs the post-processing pipeline creates from a source file. Tracked
# separately because they are legitimately present without being Canvas files,
# and because "the converter ran" is asserted by their existence.
CONVERTED_EXTS = {".pdf", ".txt", ".md", ".mp3", ".csv", ".xlsx"}

SECONDARY_PREFIXES = ("Announcement ", "Assignment ", "Quiz ", "Discussion ",
                      "Page ", "Syllabus", "Submission ", "Rubric ")


def _is_partial(name: str) -> bool:
    """In-flight or crashed atomic-write artifacts.

    ``x.ext.part`` comes from the file engines and ``x.part.ext`` from the
    Panopto ffmpeg downloader. Their presence after a run has finished means a
    write was abandoned without cleanup, which is a real defect - so they are
    detected rather than ignored.
    """
    low = name.lower()
    return low.endswith(".part") or ".part." in low


def quick_sig(p: Path, size: int) -> str:
    h = hashlib.md5()
    h.update(str(size).encode())
    try:
        with p.open("rb") as f:
            h.update(f.read(CHUNK))
            if size > CHUNK * 2:
                f.seek(-CHUNK, os.SEEK_END)
                h.update(f.read(CHUNK))
    except OSError as e:
        return f"unreadable:{type(e).__name__}"
    return h.hexdigest()


def full_md5(p: Path) -> str:
    h = hashlib.md5()
    try:
        with p.open("rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
    except OSError as e:
        return f"unreadable:{type(e).__name__}"
    return h.hexdigest()


def scan(root: str | Path, full_hash: bool = True) -> dict:
    root = Path(root)
    if not root.is_dir():
        return {"root": str(root), "exists": False, "files": [], "count": 0}

    files, dirs = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        if d != root:
            dirs.append(str(d.relative_to(root)).replace("\\", "/"))
        for fn in filenames:
            p = d / fn
            try:
                st = p.stat()
            except OSError:
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            ext = p.suffix.lower()
            size = st.st_size
            rec = {
                "rel": rel,
                "name": fn,
                "dir": str(d.relative_to(root)).replace("\\", "/") if d != root else "",
                "depth": rel.count("/"),
                "ext": ext,
                "size": size,
                "mtime": round(st.st_mtime, 3),
                "sig": quick_sig(p, size),
                "app_generated": fn in APP_GENERATED or fn.startswith(".canvas_sync"),
                "partial": _is_partial(fn),
                "zero_byte": size == 0,
                "new_version": "_NewVersion" in fn,
                "secondary_html": ext == ".html" and any(
                    fn.startswith(pre) for pre in SECONDARY_PREFIXES),
                "path_len": len(str(p)),
            }
            if full_hash and size <= FULL_HASH_LIMIT and not rec["app_generated"]:
                rec["md5"] = full_md5(p)
            files.append(rec)

    content = [f for f in files if not f["app_generated"] and not f["partial"]]
    by_ext: dict[str, int] = {}
    for f in content:
        by_ext[f["ext"] or "(none)"] = by_ext.get(f["ext"] or "(none)", 0) + 1

    # Byte-identical duplicates. Legitimate on Canvas (the same handout uploaded
    # to two modules), so this is reported as an observation, not an error - but
    # it is exactly the population the sync analyzer's adoption tiers have to
    # disambiguate, so the audit needs to know it is there.
    by_md5: dict[str, list[str]] = {}
    for f in content:
        if f.get("md5"):
            by_md5.setdefault(f["md5"], []).append(f["rel"])
    dupes = {k: v for k, v in by_md5.items() if len(v) > 1}

    return {
        "root": str(root),
        "exists": True,
        "count": len(files),
        "content_count": len(content),
        "dirs": sorted(dirs),
        "dir_count": len(dirs),
        "max_depth": max((f["depth"] for f in files), default=0),
        "total_bytes": sum(f["size"] for f in content),
        "by_ext": dict(sorted(by_ext.items(), key=lambda kv: -kv[1])),
        "partials": [f["rel"] for f in files if f["partial"]],
        "zero_bytes": [f["rel"] for f in content if f["zero_byte"]],
        "new_versions": [f["rel"] for f in content if f["new_version"]],
        "secondary_html": [f["rel"] for f in content if f["secondary_html"]],
        "app_generated": [f["rel"] for f in files if f["app_generated"]],
        "long_paths": [f["rel"] for f in files if f["path_len"] > 255],
        "duplicate_groups": dupes,
        "files": files,
    }


def diff(before: dict, after: dict) -> dict:
    """What a run changed. The unit of proof for "did this sync do what it said".

    Compares on the quick signature, so a file re-downloaded with identical
    bytes reads as unchanged - which is correct, and is what makes an
    unnecessary re-download detectable as ``rewritten`` (mtime moved, content
    did not).
    """
    b = {f["rel"]: f for f in before.get("files", [])}
    a = {f["rel"]: f for f in after.get("files", [])}
    added = sorted(set(a) - set(b))
    removed = sorted(set(b) - set(a))
    changed, rewritten = [], []
    for rel in sorted(set(a) & set(b)):
        if a[rel]["sig"] != b[rel]["sig"]:
            changed.append({"rel": rel, "before": b[rel]["size"], "after": a[rel]["size"]})
        elif a[rel]["mtime"] != b[rel]["mtime"]:
            rewritten.append(rel)
    return {
        "added": added, "removed": removed, "changed": changed,
        "rewritten": rewritten,
        "added_count": len(added), "removed_count": len(removed),
        "changed_count": len(changed), "rewritten_count": len(rewritten),
        "added_bytes": sum(a[r]["size"] for r in added),
    }


def save(scan_result: dict, path: str | Path) -> str:
    Path(path).write_text(json.dumps(scan_result, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    return str(path)


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def brief(scan_result: dict) -> dict:
    """Everything except the per-file list - safe to print into a transcript."""
    return {k: v for k, v in scan_result.items() if k != "files"}
