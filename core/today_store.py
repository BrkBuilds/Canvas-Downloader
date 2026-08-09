"""core.today_store - persistence for the Today dashboard & daily auto-sync.

Stores the daily-sync SETTINGS in ``today_dashboard.json`` (config dir):
  - ``auto_sync_enabled``     master toggle for the daily auto-sync
  - ``last_auto_sync_date``   the logical date the daily run last fired
  - ``fda_nudge_dismissed``   macOS: the Full Disk Access nudge card was closed
                              (it then only reopens via its subtle link)

The daily-sync COURSE SELECTION is NOT stored here any more. Today is a child of
the library (``core.library``): the daily set is simply the saved pairs whose
``in_daily_sync`` flag is set. ``load_today_config()["pairs"]`` reads that flag
live, and ``set_today_pairs`` / ``remove_today_pair`` write it - so there is one
source of truth, no self-contained copy, and nothing to reconcile.

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
    from shared.helpers import get_config_dir
    return Path(get_config_dir()) / _FILENAME


def _default() -> dict:
    return {
        "auto_sync_enabled": False,
        "pairs": [],
        "last_auto_sync_date": "",
        # macOS: the "make it fully hands-off" (Full Disk Access) nudge card was
        # closed - it then never auto-shows again, only via its subtle link.
        "fda_nudge_dismissed": False,
    }


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


def _daily_pairs_from_library() -> list[dict]:
    """The daily selection, read from the library's ``in_daily_sync`` flag and
    projected to Today's ``{course_id, course_name, local_folder}`` shape.

    Each pair also carries its library ``saved_id`` (the STABLE id) so a Today /
    daily run records it in sync history and the user's name resolves via
    ``core.pair_labels.label_for_id`` even after the folder is later moved - the
    same parity a Sync-page run gets. ``saved_id`` is an identity reference, not
    a label, so it is safe to carry here; ``set_today_pairs``'s ``_norm_pair``
    strips it again on write, so it never round-trips back into the store.
    """
    try:
        import core.library as library
        out = []
        for p in library.daily_pairs():
            np = _norm_pair(p)
            if np:
                np["saved_id"] = p.get("id")
                out.append(np)
        return out
    except Exception:
        return []


def _read_settings() -> tuple[dict, bool]:
    """``(settings, may_write)`` - the stored settings and the write verdict.

    ONE coercion of the stored shape, shared by the read path
    (:func:`load_today_config`) and the write path (:func:`_update`), so the two
    can never disagree about what the file said.

    The verdict is what stops a read-modify-write from destroying the file it
    could not read - the same class ``core.library``, ``atomic_update_sync_pairs``
    and the settings file were each hardened against. It matters here because
    ``_update`` writes only the keys it is given and re-persists the rest from
    whatever the read produced: degrading to defaults and saving turns an
    unreadable file into ``auto_sync_enabled: False`` and an empty
    ``last_auto_sync_date``. That silently switches the daily auto-sync OFF -
    and the daily sync is the run nobody watches, so nothing would say so.
    """
    from shared.helpers import read_json_for_update
    data, may_write = read_json_for_update(_path())
    d = _default()
    d["auto_sync_enabled"] = bool(data.get("auto_sync_enabled", False))
    d["last_auto_sync_date"] = str(data.get("last_auto_sync_date", "") or "")
    d["fda_nudge_dismissed"] = bool(data.get("fda_nudge_dismissed", False))
    return d, may_write


def load_today_config() -> dict:
    """Load the Today config. Always returns a well-formed dict, never raises.

    Settings come from ``today_dashboard.json``; the ``pairs`` come LIVE from the
    library's ``in_daily_sync`` flag (Today is a child of the library).

    Degrading to defaults is correct HERE - a reader wants a usable answer - and
    wrong in ``_update``, which persists what it was handed. See
    :func:`_read_settings`."""
    d, _ = _read_settings()
    d["pairs"] = _daily_pairs_from_library()
    return d


_SETTING_KEYS = ("auto_sync_enabled", "last_auto_sync_date", "fda_nudge_dismissed")


def _save(data: dict) -> None:
    # SETTINGS ONLY - the daily course selection lives on the library's
    # in_daily_sync flag, never in this file (load_today_config injects it live,
    # so writing it back would create the stale copy this refactor removed).
    out = {k: data.get(k, _default()[k]) for k in _SETTING_KEYS}
    p = _path()
    tmp = p.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
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
    """Apply *changes* to the stored settings, persisting only when it is safe.

    On a transient read failure the change is applied in memory and returned -
    so the caller and the current screen behave as the user asked - but nothing
    is written, because the write would replace the settings that could not be
    read with this call's defaults.
    """
    with _lock:
        data, may_write = _read_settings()
        data.update(changes)
        if may_write:
            _save(data)
        else:
            import logging
            logging.getLogger(__name__).warning(
                "Not writing %s: it could not be read, so a write would reset "
                "auto_sync_enabled and last_auto_sync_date to their defaults.",
                _FILENAME)
        data["pairs"] = _daily_pairs_from_library()
        return data


def set_auto_sync_enabled(enabled: bool) -> None:
    _update(auto_sync_enabled=bool(enabled))


def set_fda_nudge_dismissed(dismissed: bool = True) -> None:
    _update(fda_nudge_dismissed=bool(dismissed))


def set_today_pairs(pairs: list[dict]) -> None:
    """Replace the daily-sync set with *pairs* by flipping ``in_daily_sync`` on
    the library. Only SAVED pairs can be in the daily set (Today is a child of
    the library); a selection for a link that somehow isn't saved yet is claimed
    into the library first, so the user's choice is never silently dropped."""
    import core.library as library
    want = set()
    for p in pairs:
        np = _norm_pair(p)
        if np:
            want.add(library.link_key(np["course_id"], np["local_folder"]))
    with _lock:
        data = library.load_library()
        have = {library.link_key(p["course_id"], p["local_folder"]): p for p in data["pairs"]}
        # turn OFF pairs no longer selected
        for key, rec in have.items():
            if rec.get("in_daily_sync") and key not in want:
                library.set_daily(rec["id"], False)
        # turn ON selected pairs, claiming any that aren't saved yet
        for p in pairs:
            np = _norm_pair(p)
            if not np:
                continue
            rec = library.pair_for(np["course_id"], np["local_folder"])
            pid = rec["id"] if rec else library.save_pair(
                np["course_id"], np["local_folder"], np["course_name"], standalone=True)
            library.set_daily(pid, True)


def remove_today_pair(course_id, local_folder) -> None:
    """Drop one pair from the daily set (clears its ``in_daily_sync`` flag)."""
    import core.library as library
    rec = library.pair_for(course_id, local_folder)
    if rec is not None:
        library.set_daily(rec["id"], False)


def mark_auto_synced(date_str: str) -> None:
    _update(last_auto_sync_date=date_str)
