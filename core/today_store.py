"""core.today_store - persistence for the Today dashboard & daily auto-sync.

Stores three things in ``today_dashboard.json`` (config dir):
  - ``auto_sync_enabled``     master toggle for the daily auto-sync
  - ``pairs``                 the full course/folder pairs (course_id +
                              course_name + local_folder) the user imported from
                              the Saved Groups & Pairs hub into the daily set.
                              Stored as standalone copies so the daily sync is
                              self-contained and survives edits/deletes in the hub.
  - ``last_auto_sync_date``   the logical date the daily run last fired

Atomic writes (tmp + ``os.replace``) under a module ``threading.Lock``, mirroring
``sync/persistence.py``. All reads degrade to defaults on a corrupt/missing file.

The "logical day" rolls at 04:00 local time so that "the first time the user
opens the app today" means *after 4am* - a late-night session (e.g. 01:00) still
counts as the previous day and won't trigger a fresh daily sync.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

_FILENAME = "today_dashboard.json"
_lock = threading.Lock()

# Day boundary: "first open of the day after 4am".
_DAY_ROLL_HOUR = 4


def logical_date_of(dt: datetime) -> str:
    """Return the YYYY-MM-DD logical date for *dt* (day rolls at 04:00)."""
    return (dt - timedelta(hours=_DAY_ROLL_HOUR)).date().isoformat()


def logical_today() -> str:
    """Return today's logical date string (day rolls at 04:00 local)."""
    return logical_date_of(datetime.now())


def _path() -> Path:
    from ui_helpers import get_config_dir
    return Path(get_config_dir()) / _FILENAME


def _default() -> dict:
    return {"auto_sync_enabled": False, "pairs": [], "last_auto_sync_date": ""}


def _norm_pair(p: dict) -> dict | None:
    """Normalise a stored pair to ``{course_id, course_name, local_folder}``.

    Returns ``None`` for entries without a local folder (unusable).
    """
    if not isinstance(p, dict):
        return None
    folder = p.get("local_folder")
    if not folder:
        return None
    return {
        "course_id": p.get("course_id"),
        "course_name": p.get("course_name", ""),
        "local_folder": folder,
    }


def load_today_config() -> dict:
    """Load the Today config. Always returns a well-formed dict, never raises."""
    p = _path()
    if not p.exists():
        return _default()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default()
        d = _default()
        for k in d:
            d[k] = data.get(k, d[k])
        if not isinstance(d["pairs"], list):
            d["pairs"] = []
        else:
            d["pairs"] = [np for np in (_norm_pair(p) for p in d["pairs"]) if np]
        d["auto_sync_enabled"] = bool(d["auto_sync_enabled"])
        d["last_auto_sync_date"] = str(d["last_auto_sync_date"] or "")
        return d
    except Exception:
        return _default()


def _save(data: dict) -> None:
    p = _path()
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


def _update(**changes) -> dict:
    with _lock:
        data = load_today_config()
        data.update(changes)
        _save(data)
        return data


def set_auto_sync_enabled(enabled: bool) -> None:
    _update(auto_sync_enabled=bool(enabled))


def _dedupe(pairs: list[dict]) -> list[dict]:
    """Drop duplicates by (course_id, local_folder), preserving first-seen order."""
    seen: set = set()
    out: list[dict] = []
    for p in pairs:
        np = _norm_pair(p)
        if not np:
            continue
        sig = (np["course_id"], np["local_folder"])
        if sig in seen:
            continue
        seen.add(sig)
        out.append(np)
    return out


def set_today_pairs(pairs: list[dict]) -> None:
    """Replace the curated daily-sync set with *pairs* (deduped, normalised)."""
    _update(pairs=_dedupe(pairs))


def add_today_pairs(pairs: list[dict]) -> int:
    """Merge *pairs* into the curated set. Returns the count actually added.

    De-duplicates against the existing set by (course_id, local_folder) so the
    same course/folder is never queued twice.
    """
    with _lock:
        data = load_today_config()
        existing = data.get("pairs", [])
        before = {(p["course_id"], p["local_folder"]) for p in existing}
        merged = _dedupe(existing + list(pairs))
        added = len(merged) - len(existing)
        if added:
            data["pairs"] = merged
            _save(data)
        # Recompute against the post-merge signatures for an accurate count.
        return len({(p["course_id"], p["local_folder"]) for p in merged} - before)


def remove_today_pair(course_id, local_folder) -> None:
    """Remove a single pair from the curated set by its signature."""
    with _lock:
        data = load_today_config()
        data["pairs"] = [
            p for p in data.get("pairs", [])
            if not (p.get("course_id") == course_id
                    and p.get("local_folder") == local_folder)
        ]
        _save(data)


def mark_auto_synced(date_str: str) -> None:
    _update(last_auto_sync_date=date_str)
