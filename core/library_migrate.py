"""core.library_migrate - one-time migration of the three legacy pair stores
into the unified ``core.library``.

Legacy layout (see core.library's docstring):
  * ``saved_sync_groups.json`` - hub: standalone saved pairs (``is_single_pair``
    with the name in ``group_name``, ``auto_named`` meaning "unnamed") and
    multi-course groups (per-course ``label``).
  * ``today_dashboard.json``    - ``pairs`` selected for daily sync.
  * ``canvas_sync_pairs.json``  - the working sync list (NOT migrated here: it is
    re-expressed as ``{saved_id}`` / raw references at the sync-page cutover).

Runs once, idempotently: guarded by ``sync_library.json`` already existing at
``version >= 2``. Reads are tolerant (a missing/corrupt legacy file contributes
nothing). Legacy files are copied to ``*.bak`` before the library is written -
nothing is deleted, so the migration is reversible.

Precedence for a link's NAME mirrors the old ``core.pair_labels`` index exactly:
a standalone saved pair (Pass 1) wins over a group member's label (Pass 2);
first-in-file-order within each pass.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import core.library as library

_LEGACY_HUB = "saved_sync_groups.json"
_LEGACY_TODAY = "today_dashboard.json"


def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _config_dir(config_dir: str | None) -> Path:
    if config_dir is not None:
        return Path(config_dir)
    from shared.helpers import get_config_dir
    return Path(get_config_dir())


def needs_migration(config_dir: str | None = None) -> bool:
    """True ONLY when no library has been built yet.

    The gate is the EXISTENCE of a well-formed library file, NOT its version
    number. Re-importing the legacy stores is only ever correct when there is no
    library at all: the legacy files are kept as ``*.bak`` (never deleted), so
    gating on ``version < _VERSION`` would make a future ``_VERSION`` bump
    re-read them and OVERWRITE every change the user made since the first
    migration. A future schema change must be a library-to-library migration,
    never a re-run of this legacy import.

    A file that exists but is not a well-formed library (missing/corrupt) still
    counts as "needs migration": rebuilding from the still-present legacy
    originals is strictly better than the empty library ``load_library`` would
    otherwise degrade to.
    """
    lib_path = _config_dir(config_dir) / library._FILENAME
    data = _read_json(lib_path)
    return not (isinstance(data, dict)
                and isinstance(data.get("version"), int)
                and data.get("version", 0) >= 1
                and isinstance(data.get("pairs"), list))


def migrate_if_needed(config_dir: str | None = None) -> dict:
    """Build ``sync_library.json`` from the legacy stores if it doesn't exist yet.

    Returns a summary dict: ``{"migrated": bool, "pairs": int, "groups": int,
    "daily": int, "reason": str}``. Never raises - a migration failure must not
    stop the app from launching (the app falls back to an empty library, which
    degrades to Canvas names everywhere).
    """
    cfg = _config_dir(config_dir)
    if not needs_migration(str(cfg)):
        return {"migrated": False, "reason": "already"}

    try:
        return _do_migrate(cfg)
    except Exception as e:  # never block launch
        import logging
        logging.getLogger(__name__).warning(
            "Library migration failed; starting with an empty library", exc_info=True)
        return {"migrated": False, "reason": f"error: {e}"}


def _do_migrate(cfg: Path) -> dict:
    hub = _read_json(cfg / _LEGACY_HUB) or {}
    today = _read_json(cfg / _LEGACY_TODAY) or {}
    legacy_groups = hub.get("groups") if isinstance(hub, dict) else None
    legacy_groups = legacy_groups if isinstance(legacy_groups, list) else []
    today_pairs = today.get("pairs") if isinstance(today, dict) else None
    today_pairs = today_pairs if isinstance(today_pairs, list) else []

    pairs: list[dict] = []
    groups: list[dict] = []
    by_link: dict = {}          # link_key -> pair record (dedup)

    def ensure_pair(course_id, folder, course_name, name="", standalone=True) -> dict | None:
        if not folder:
            return None
        key = library.link_key(course_id, folder)
        rec = by_link.get(key)
        if rec is None:
            rec = {
                "id": library._new_id("pair"),
                "course_id": library.coerce_course_id(course_id),
                "course_name": course_name or "",
                "local_folder": folder,
                "name": (name or "").strip(),
                "standalone": bool(standalone),
                "in_daily_sync": False,
                "created_at": library._now(),
                "updated_at": library._now(),
            }
            by_link[key] = rec
            pairs.append(rec)
        else:
            # First-wins for the NAME; refresh the Canvas-name cache if we have
            # one; standalone is only ever raised (a pair saved on its own stays
            # a Pair card even if a group also references it).
            if not rec["name"] and name:
                rec["name"] = name.strip()
            if course_name and not rec["course_name"]:
                rec["course_name"] = course_name
            if standalone:
                rec["standalone"] = True
        return rec

    # Pass 1 - standalone saved pairs (their group_name is the pair's name).
    for g in legacy_groups:
        if not isinstance(g, dict) or not g.get("is_single_pair"):
            continue
        gp = (g.get("pairs") or [])
        if not gp or not isinstance(gp[0], dict):
            continue
        p = gp[0]
        name = "" if g.get("auto_named") else (g.get("group_name") or "")
        ensure_pair(p.get("course_id"), p.get("local_folder"), p.get("course_name", ""), name)

    # Pass 2 - multi-course groups: members become pairs (label = their name),
    # and the group references them by id.
    for g in legacy_groups:
        if not isinstance(g, dict) or g.get("is_single_pair"):
            continue
        member_ids: list[str] = []
        for p in (g.get("pairs") or []):
            if not isinstance(p, dict):
                continue
            rec = ensure_pair(p.get("course_id"), p.get("local_folder"),
                              p.get("course_name", ""), (p.get("label") or ""),
                              standalone=False)   # a group member is not a Pair card on its own
            if rec is not None and rec["id"] not in member_ids:
                member_ids.append(rec["id"])
        groups.append({
            "id": g.get("group_id") or library._new_id("grp"),
            "name": (g.get("group_name") or "").strip(),
            "member_ids": member_ids,
        })

    # Daily selection - flag matching pairs (creating one if a daily course was
    # never in the hub, so the user's daily set survives the move).
    #
    # standalone is decided per case: a daily course with NO hub entry becomes a
    # standalone pair so it is visible/manageable as a hub Pair card; but a
    # course that already exists ONLY as a group member must NOT be promoted to
    # standalone just because it is in the daily set - that would spawn a
    # duplicate Pair card the user never created. So only NEW pairs are
    # standalone; existing ones keep whatever pass 1/2 set (ensure_pair leaves
    # standalone untouched when passed standalone=False).
    daily = 0
    for p in today_pairs:
        if not isinstance(p, dict):
            continue
        folder = p.get("local_folder")
        if not folder:
            continue
        is_new = library.link_key(p.get("course_id"), folder) not in by_link
        rec = ensure_pair(p.get("course_id"), folder, p.get("course_name", ""),
                          standalone=is_new)
        if rec is not None and not rec["in_daily_sync"]:
            rec["in_daily_sync"] = True
            daily += 1

    # Back up the legacy files we consumed (reversible), then write the library.
    for fname in (_LEGACY_HUB, _LEGACY_TODAY):
        src = cfg / fname
        if src.exists():
            try:
                shutil.copy2(src, src.with_suffix(src.suffix + ".bak"))
            except OSError:
                pass

    # Write the library to the SAME dir the legacy files were read from, so a
    # migration targeting a custom config dir (tests) is self-consistent
    # instead of reading from one place and writing to the live config dir.
    library.replace_all({"version": library._VERSION, "pairs": pairs, "groups": groups},
                        config_dir=str(cfg))
    library._memo = None
    return {"migrated": True, "reason": "ok",
            "pairs": len(pairs), "groups": len(groups), "daily": daily}
