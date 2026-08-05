"""Unit tests for core.library_migrate - legacy stores -> unified library."""

import importlib
import json

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    import core.library as library
    import core.library_migrate as migrate
    importlib.reload(library)
    importlib.reload(migrate)
    library._memo = None
    return tmp_path, library, migrate


def _write(tmp_path, name, obj):
    (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")


def test_standalone_pair_name_and_auto_named(env):
    tmp, library, migrate = env
    _write(tmp, "saved_sync_groups.json", {"groups": [
        {"group_id": "g1", "group_name": "Macro", "is_single_pair": True,
         "pairs": [{"course_id": 1, "local_folder": "C:/a", "course_name": "Canvas A"}]},
        {"group_id": "g2", "group_name": "Canvas B", "is_single_pair": True, "auto_named": True,
         "pairs": [{"course_id": 2, "local_folder": "C:/b", "course_name": "Canvas B"}]},
    ]})
    out = migrate.migrate_if_needed(str(tmp))
    assert out["migrated"] and out["pairs"] == 2
    names = {p["course_id"]: p["name"] for p in library.pairs()}
    assert names == {1: "Macro", 2: ""}          # auto_named -> unnamed


def test_group_members_become_pairs_with_labels(env):
    tmp, library, migrate = env
    _write(tmp, "saved_sync_groups.json", {"groups": [
        {"group_id": "grp1", "group_name": "Semester 1", "pairs": [
            {"course_id": 1, "local_folder": "C:/a", "course_name": "A", "label": "Alpha"},
            {"course_id": 2, "local_folder": "C:/b", "course_name": "B"},
        ]},
    ]})
    migrate.migrate_if_needed(str(tmp))
    data = library.load_library()
    assert len(data["pairs"]) == 2 and len(data["groups"]) == 1
    grp = data["groups"][0]
    assert grp["name"] == "Semester 1"
    members = library.group_pairs(grp["id"])
    assert [m["course_id"] for m in members] == [1, 2]
    assert {m["course_id"]: m["name"] for m in members} == {1: "Alpha", 2: ""}


def test_standalone_wins_over_group_label(env):
    tmp, library, migrate = env
    # Same link is a standalone pair "Macro" AND a group member labelled "Nope".
    _write(tmp, "saved_sync_groups.json", {"groups": [
        {"group_id": "g1", "group_name": "Macro", "is_single_pair": True,
         "pairs": [{"course_id": 1, "local_folder": "C:/a"}]},
        {"group_id": "grp1", "group_name": "Set", "pairs": [
            {"course_id": 1, "local_folder": "C:/a", "label": "Nope"},
        ]},
    ]})
    migrate.migrate_if_needed(str(tmp))
    assert len(library.pairs()) == 1             # one link, one pair
    assert library.pairs()[0]["name"] == "Macro"  # Pass 1 wins
    # the group still references that same pair
    assert library.groups()[0]["member_ids"] == [library.pairs()[0]["id"]]


def test_today_pairs_become_daily_flags(env):
    tmp, library, migrate = env
    _write(tmp, "saved_sync_groups.json", {"groups": [
        {"group_id": "g1", "group_name": "Macro", "is_single_pair": True,
         "pairs": [{"course_id": 1, "local_folder": "C:/a"}]},
    ]})
    _write(tmp, "today_dashboard.json", {"auto_sync_enabled": True, "pairs": [
        {"course_id": 1, "local_folder": "C:/a", "course_name": "A"},
        {"course_id": 9, "local_folder": "C:/z", "course_name": "Z"},   # daily but not in hub
    ]})
    out = migrate.migrate_if_needed(str(tmp))
    assert out["daily"] == 2
    daily = {p["course_id"] for p in library.daily_pairs()}
    assert daily == {1, 9}                        # daily selection preserved
    assert library.pair_for(9, "C:/z") is not None  # created so it can be daily


def test_idempotent_and_backups(env):
    tmp, library, migrate = env
    _write(tmp, "saved_sync_groups.json", {"groups": [
        {"group_id": "g1", "group_name": "Macro", "is_single_pair": True,
         "pairs": [{"course_id": 1, "local_folder": "C:/a"}]},
    ]})
    first = migrate.migrate_if_needed(str(tmp))
    assert first["migrated"]
    assert (tmp / "saved_sync_groups.json.bak").exists()   # reversible backup
    ids_before = [p["id"] for p in library.pairs()]
    second = migrate.migrate_if_needed(str(tmp))
    assert second == {"migrated": False, "reason": "already"}
    assert [p["id"] for p in library.pairs()] == ids_before  # no churn on re-run


def test_missing_and_corrupt_legacy_degrade(env):
    tmp, library, migrate = env
    (tmp / "saved_sync_groups.json").write_text("{bad json", encoding="utf-8")
    out = migrate.migrate_if_needed(str(tmp))
    assert out["migrated"] and out["pairs"] == 0     # nothing to migrate, still builds empty library
    assert library.load_library()["pairs"] == []
