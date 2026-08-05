"""core.library - the ONE source of truth for saved course/folder pairs.

WHAT THIS IS
------------
Sync mode used to spread "a Canvas course linked to a local folder" across three
disconnected files keyed on a fragile folder PATH:

  * ``saved_sync_groups.json`` - the hub, and the only place a NAME lived (as a
    "group with one member": the ``is_single_pair`` / ``group_name`` /
    ``auto_named`` warts);
  * ``canvas_sync_pairs.json``  - the working sync list (label-stripped copies);
  * ``today_dashboard.json``    - a self-contained daily-sync copy kept in step
    by ``reconcile_daily_list_with_hub()``.

Because identity was a path, moving a folder stranded the name and re-downloading
to the same path resurrected a deleted one. This module replaces all of that with
one store whose identity is a STABLE ID.

THE MODEL
---------
A **Library** of first-class SAVED pairs plus named GROUPS that reference pairs
by id:

    pair  = {id, course_id, course_name, local_folder, name, in_daily_sync,
             created_at, updated_at}
    group = {id, name, member_ids:[pair_id, ...]}

  * ``name`` on a stable id  -> renaming/moving a folder edits the SAME record,
    so the name follows; deleting a pair frees its id, so re-adding the same
    path is a NEW pair with no name (no resurrection). ``""`` name means
    "use the live Canvas name" (this subsumes the old ``auto_named`` flag).
  * ``in_daily_sync`` on the pair -> Today's daily set is a QUERY over the
    library, not a copy: no reconcile, no drift. Today is a child of the library.
  * a group names the SET; it can never touch a member pair's name.

The working sync list (``canvas_sync_pairs.json``) is NOT here - it is a thin
list of ``{saved_id}`` references (to library pairs) and raw ``{course_id,
local_folder, course_name}`` entries, resolved against this library at load.

CONVENTIONS
-----------
Streamlit-free on purpose (the sync engine formats names for its progress UI, so
this must not need a ScriptRunContext). Atomic writes (tmp + ``os.replace`` under
a module lock), mirroring ``core/today_store.py`` and ``sync/persistence.py``.
Every read degrades to an empty/default library rather than raising - a naming
store must never be able to break a sync screen.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from shared.helpers import norm_folder_key

_FILENAME = "sync_library.json"
_VERSION = 2
_lock = threading.Lock()

# name_index memo, keyed on the file's (mtime_ns, size) - correct by
# construction, because every write goes through _save's os.replace.
_memo_lock = threading.Lock()
_memo: tuple | None = None


# ── identity ─────────────────────────────────────────────────────────────────

def coerce_course_id(course_id):
    """``42`` and ``"42"`` are the same course. Coerce to int when it looks like
    one, else leave as-is (matches ``core.pair_labels.pair_key``)."""
    try:
        return int(course_id)
    except (TypeError, ValueError):
        return course_id


def link_key(course_id, local_folder) -> tuple:
    """The identity of a course/folder LINK: coerced id + normalised folder."""
    return (coerce_course_id(course_id), norm_folder_key(local_folder))


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── persistence ──────────────────────────────────────────────────────────────

def _path(config_dir=None) -> Path:
    if config_dir is not None:
        return Path(config_dir) / _FILENAME
    from shared.helpers import get_config_dir
    return Path(get_config_dir()) / _FILENAME


def _default() -> dict:
    return {"version": _VERSION, "pairs": [], "groups": []}


def _norm_pair_record(p: dict) -> dict | None:
    """Coerce a stored pair to the canonical shape, or None if unusable."""
    if not isinstance(p, dict):
        return None
    folder = p.get("local_folder")
    if not folder:
        return None
    return {
        "id": p.get("id") or _new_id("pair"),
        "course_id": p.get("course_id"),
        "course_name": p.get("course_name", "") or "",
        "local_folder": folder,
        "name": (p.get("name") or "").strip(),
        # standalone = the user saved this as an individual pair, so it shows as a
        # Pair card in the hub. A pair that exists ONLY because a group references
        # it is standalone=False (still a first-class pair - named, daily-able,
        # on the active list - just not listed on its own). Default True so any
        # hand-written/older record is treated as a normal saved pair.
        "standalone": bool(p.get("standalone", True)),
        "in_daily_sync": bool(p.get("in_daily_sync", False)),
        "created_at": p.get("created_at") or _now(),
        "updated_at": p.get("updated_at") or _now(),
    }


def _norm_group_record(g: dict, valid_ids: set) -> dict | None:
    """Coerce a stored group; drop member ids that no longer exist."""
    if not isinstance(g, dict):
        return None
    members = [m for m in (g.get("member_ids") or []) if m in valid_ids]
    return {
        "id": g.get("id") or _new_id("grp"),
        "name": (g.get("name") or "").strip(),
        "member_ids": members,
        "created_at": g.get("created_at") or _now(),
    }


def load_library() -> dict:
    """Load the library. Always returns a well-formed dict, never raises."""
    p = _path()
    if not p.exists():
        return _default()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default()
        raw_pairs = data.get("pairs")
        pairs = [np for np in (_norm_pair_record(x) for x in (raw_pairs or [])) if np] \
            if isinstance(raw_pairs, list) else []
        valid_ids = {p["id"] for p in pairs}
        raw_groups = data.get("groups")
        groups = [ng for ng in (_norm_group_record(x, valid_ids) for x in (raw_groups or [])) if ng] \
            if isinstance(raw_groups, list) else []
        return {"version": _VERSION, "pairs": pairs, "groups": groups}
    except (json.JSONDecodeError, OSError):
        return _default()


def _save(data: dict, config_dir=None) -> None:
    p = _path(config_dir)
    tmp = p.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(str(tmp), str(p))
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def replace_all(data: dict, config_dir=None) -> dict:
    """Atomically write a whole library (normalised first). Used by the one-time
    migration and by tests; ordinary code uses the CRUD helpers below.

    ``config_dir`` targets a specific directory instead of the live config dir,
    so the migration writes the library to the SAME dir it read the legacy files
    from (production passes None -> the live config dir, unchanged)."""
    with _lock:
        pairs_ = [np for np in (_norm_pair_record(x) for x in (data.get("pairs") or [])) if np]
        valid = {p["id"] for p in pairs_}
        groups_ = [ng for ng in (_norm_group_record(x, valid) for x in (data.get("groups") or [])) if ng]
        out = {"version": _VERSION, "pairs": pairs_, "groups": groups_}
        _save(out, config_dir)
        return out


def _update(mutator) -> dict:
    """Atomically load -> mutate -> save under the module lock.

    *mutator* receives the fresh library dict and mutates it in place (its return
    value is ignored). Solves cross-thread tearing the same way
    ``sync.persistence.atomic_update_sync_pairs`` does.
    """
    with _lock:
        data = load_library()
        mutator(data)
        data["version"] = _VERSION
        _save(data)
        return data


# ── reads ────────────────────────────────────────────────────────────────────

def pairs() -> list[dict]:
    return load_library()["pairs"]


def groups() -> list[dict]:
    return load_library()["groups"]


def get_pair(pair_id: str, data: dict | None = None) -> dict | None:
    for p in (data or load_library())["pairs"]:
        if p.get("id") == pair_id:
            return p
    return None


def pair_for(course_id, local_folder, data: dict | None = None) -> dict | None:
    """The saved pair for a course/folder LINK, or None if it isn't saved."""
    key = link_key(course_id, local_folder)
    for p in (data or load_library())["pairs"]:
        if link_key(p.get("course_id"), p.get("local_folder")) == key:
            return p
    return None


def is_saved(course_id, local_folder) -> bool:
    return pair_for(course_id, local_folder) is not None


def standalone_pairs() -> list[dict]:
    """Pairs the user saved on their own - the hub's "Pair" cards."""
    return [p for p in pairs() if p.get("standalone", True)]


def daily_pairs() -> list[dict]:
    """Saved pairs the user selected for daily sync, in file order. Folder
    existence is deliberately NOT checked here - callers that RUN the sync
    filter missing folders (see core.auto_sync); callers that MANAGE the daily
    set need the full selection."""
    return [p for p in pairs() if p.get("in_daily_sync")]


# ── pair writes ──────────────────────────────────────────────────────────────

def save_pair(course_id, local_folder, course_name="", name="", standalone=True) -> str:
    """Claim a course/folder link into the library (idempotent by link).

    Returns the pair id. If the link is already saved, its course_name cache is
    refreshed and a non-empty *name* overwrites the stored one; the id is stable.
    ``standalone`` is only ever raised, never lowered - once the user has saved a
    pair on its own, adding it to a group must not hide its Pair card.
    """
    result = {"id": None}

    def mut(data):
        existing = pair_for(course_id, local_folder, data)
        if existing is not None:
            if course_name:
                existing["course_name"] = course_name
            if name:
                existing["name"] = name.strip()
            if standalone:
                existing["standalone"] = True
            existing["updated_at"] = _now()
            result["id"] = existing["id"]
            return
        pid = _new_id("pair")
        data["pairs"].append({
            "id": pid,
            "course_id": coerce_course_id(course_id),
            "course_name": course_name or "",
            "local_folder": local_folder,
            "name": (name or "").strip(),
            "standalone": bool(standalone),
            "in_daily_sync": False,
            "created_at": _now(),
            "updated_at": _now(),
        })
        result["id"] = pid

    _update(mut)
    return result["id"]


def rename_pair(pair_id: str, name: str) -> bool:
    """Set a saved pair's user name (``""`` reverts to the live Canvas name)."""
    changed = {"v": False}

    def mut(data):
        p = get_pair(pair_id, data)
        if p is not None:
            p["name"] = (name or "").strip()
            p["updated_at"] = _now()
            changed["v"] = True

    _update(mut)
    return changed["v"]


def relink_pair(pair_id: str, course_id, local_folder, course_name="") -> bool:
    """Re-point a saved pair at a new course/folder, KEEPING its name and daily
    membership. This is how a moved folder follows its name - the record is the
    same, only its link changes."""
    changed = {"v": False}

    def mut(data):
        p = get_pair(pair_id, data)
        if p is not None:
            p["course_id"] = coerce_course_id(course_id)
            p["local_folder"] = local_folder
            if course_name:
                p["course_name"] = course_name
            p["updated_at"] = _now()
            changed["v"] = True

    _update(mut)
    return changed["v"]


def set_daily(pair_id: str, enabled: bool) -> bool:
    changed = {"v": False}

    def mut(data):
        p = get_pair(pair_id, data)
        if p is not None:
            p["in_daily_sync"] = bool(enabled)
            p["updated_at"] = _now()
            changed["v"] = True

    _update(mut)
    return changed["v"]


def delete_pair(pair_id: str) -> bool:
    """Remove a pair from the library and from every group's membership.

    "Delete" is the user saying they are done with that course: its name is
    forgotten everywhere and it leaves Today. Callers that keep a working sync
    list are responsible for demoting any reference to it to a raw entry.
    """
    changed = {"v": False}

    def mut(data):
        before = len(data["pairs"])
        data["pairs"] = [p for p in data["pairs"] if p.get("id") != pair_id]
        for g in data["groups"]:
            g["member_ids"] = [m for m in g.get("member_ids", []) if m != pair_id]
        changed["v"] = len(data["pairs"]) != before

    _update(mut)
    return changed["v"]


# ── group writes ─────────────────────────────────────────────────────────────

def save_group(name: str, pair_ids: list[str]) -> str:
    """Create a named group referencing existing library pairs (deduped, order
    preserved). Unknown ids are dropped."""
    result = {"id": None}

    def mut(data):
        valid = {p["id"] for p in data["pairs"]}
        seen, members = set(), []
        for pid in pair_ids:
            if pid in valid and pid not in seen:
                seen.add(pid)
                members.append(pid)
        gid = _new_id("grp")
        data["groups"].append({
            "id": gid, "name": (name or "").strip(), "member_ids": members,
            "created_at": _now(),
        })
        result["id"] = gid

    _update(mut)
    return result["id"]


def rename_group(group_id: str, name: str) -> bool:
    changed = {"v": False}

    def mut(data):
        for g in data["groups"]:
            if g.get("id") == group_id:
                g["name"] = (name or "").strip()
                changed["v"] = True
                break

    _update(mut)
    return changed["v"]


def set_group_members(group_id: str, pair_ids: list[str]) -> bool:
    changed = {"v": False}

    def mut(data):
        valid = {p["id"] for p in data["pairs"]}
        seen, members = set(), []
        for pid in pair_ids:
            if pid in valid and pid not in seen:
                seen.add(pid)
                members.append(pid)
        for g in data["groups"]:
            if g.get("id") == group_id:
                g["member_ids"] = members
                changed["v"] = True
                break

    _update(mut)
    return changed["v"]


def delete_group(group_id: str) -> bool:
    """Delete a group. STANDALONE member pairs stay in the library (they were
    saved on their own, so they keep their name and any daily membership);
    members that existed ONLY to back this group - not standalone, referenced by
    no other group - are removed entirely, INCLUDING from the daily set. Deleting
    a group you'd added to daily therefore takes its exclusive courses out of the
    daily sync too, and leaves no invisible orphans behind."""
    changed = {"v": False}

    def mut(data):
        gone = [g for g in data["groups"] if g.get("id") == group_id]
        data["groups"] = [g for g in data["groups"] if g.get("id") != group_id]
        if not gone:
            return
        changed["v"] = True
        still_referenced = {m for g in data["groups"] for m in g.get("member_ids", [])}
        data["pairs"] = [
            p for p in data["pairs"]
            if p.get("standalone", True) or p["id"] in still_referenced
        ]

    _update(mut)
    return changed["v"]


def group_pairs(group_id: str, data: dict | None = None) -> list[dict]:
    """The pair records a group references, in membership order (missing ids
    skipped)."""
    data = data or load_library()
    by_id = {p["id"]: p for p in data["pairs"]}
    for g in data["groups"]:
        if g.get("id") == group_id:
            return [by_id[m] for m in g.get("member_ids", []) if m in by_id]
    return []


# ── name resolution ──────────────────────────────────────────────────────────

def _groups_stat(path) -> tuple:
    try:
        st_ = os.stat(path)
        return (st_.st_mtime_ns, st_.st_size)
    except OSError:
        return ()


def name_index() -> dict:
    """``{link_key: name}`` for every saved pair with a user-chosen name,
    memoised on the file's ``(mtime_ns, size)``. Consumed by
    ``core.pair_labels``. Any read failure degrades to ``{}``.
    """
    global _memo
    try:
        path = _path()
        sig = (str(path),) + _groups_stat(path)
        with _memo_lock:
            if _memo is not None and _memo[0] == sig and sig[1:]:
                return _memo[1]
        idx: dict = {}
        for p in load_library()["pairs"]:
            nm = (p.get("name") or "").strip()
            if nm:
                idx[link_key(p.get("course_id"), p.get("local_folder"))] = nm
        with _memo_lock:
            _memo = (sig, idx)
        return idx
    except Exception:
        return {}
