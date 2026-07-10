"""Tests for core.today_store - persistence behind the Today dashboard and
the daily auto-sync trigger.

Covers the 4am logical-day roll (the contract that decides whether auto-sync
fires), corrupt-file degradation, pair normalisation/dedupe, and the atomic
write pattern (no stray .tmp files).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from shared import helpers
from core import today_store


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """Point the store at an isolated temp config dir.

    today_store resolves the path via ``shared.helpers.get_config_dir()`` at
    call time (function-local import), so patching the attribute on
    shared.helpers is sufficient and leaks nothing across tests.
    """
    monkeypatch.setattr(helpers, "get_config_dir", lambda: str(tmp_path))
    return tmp_path


# ── Logical day (rolls at 04:00 local) ───────────────────────────────────────

@pytest.mark.parametrize(
    "dt, expected",
    [
        (datetime(2026, 7, 5, 3, 59), "2026-07-04"),   # late night = previous day
        (datetime(2026, 7, 5, 4, 0), "2026-07-05"),    # 4am sharp = new day
        (datetime(2026, 7, 5, 23, 59), "2026-07-05"),
        (datetime(2026, 7, 5, 0, 0), "2026-07-04"),    # midnight = previous day
        (datetime(2026, 1, 1, 2, 0), "2025-12-31"),    # year boundary
    ],
)
def test_logical_date_rolls_at_4am(dt, expected):
    assert today_store.logical_date_of(dt) == expected


# ── Defaults & corruption ────────────────────────────────────────────────────

def test_missing_file_returns_defaults(config_dir):
    cfg = today_store.load_today_config()
    assert cfg == {
        "auto_sync_enabled": False,
        "pairs": [],
        "last_auto_sync_date": "",
        "fda_nudge_dismissed": False,
    }


@pytest.mark.parametrize("garbage", ["{not json", '"a string"', "[1,2,3]", ""])
def test_corrupt_file_degrades_to_defaults(config_dir, garbage):
    (config_dir / "today_dashboard.json").write_text(garbage, encoding="utf-8")
    cfg = today_store.load_today_config()
    assert cfg["auto_sync_enabled"] is False
    assert cfg["pairs"] == []


def test_malformed_pairs_are_dropped_on_load(config_dir):
    import json
    (config_dir / "today_dashboard.json").write_text(
        json.dumps({
            "auto_sync_enabled": True,
            "pairs": [
                {"course_id": 1, "course_name": "Good", "local_folder": "C:/x"},
                {"course_id": 2, "course_name": "No folder"},          # unusable
                "not-a-dict",                                          # junk
                {"course_id": 3, "local_folder": ""},                  # empty folder
            ],
            "last_auto_sync_date": "2026-07-01",
        }),
        encoding="utf-8",
    )
    cfg = today_store.load_today_config()
    assert [p["course_id"] for p in cfg["pairs"]] == [1]
    assert cfg["auto_sync_enabled"] is True
    assert cfg["last_auto_sync_date"] == "2026-07-01"


# ── Round-trips, dedupe, add/remove ──────────────────────────────────────────

def test_set_and_reload_pairs(config_dir):
    pairs = [
        {"course_id": 10, "course_name": "Algo", "local_folder": "C:/algo"},
        {"course_id": 11, "course_name": "Stats", "local_folder": "C:/stats"},
    ]
    today_store.set_today_pairs(pairs)
    cfg = today_store.load_today_config()
    assert len(cfg["pairs"]) == 2
    assert cfg["pairs"][0]["course_name"] == "Algo"


def test_set_pairs_dedupes_by_course_and_folder(config_dir):
    p = {"course_id": 10, "course_name": "Algo", "local_folder": "C:/algo"}
    today_store.set_today_pairs([p, dict(p), dict(p, course_name="Renamed")])
    cfg = today_store.load_today_config()
    assert len(cfg["pairs"]) == 1  # same (course_id, folder) = one entry


def test_same_course_two_folders_is_two_entries(config_dir):
    today_store.set_today_pairs([
        {"course_id": 10, "course_name": "Algo", "local_folder": "C:/a"},
        {"course_id": 10, "course_name": "Algo", "local_folder": "C:/b"},
    ])
    assert len(today_store.load_today_config()["pairs"]) == 2


def test_add_pairs_returns_actually_added_count(config_dir):
    base = {"course_id": 1, "course_name": "A", "local_folder": "C:/a"}
    today_store.set_today_pairs([base])
    added = today_store.add_today_pairs([
        dict(base),                                                    # dup -> 0
        {"course_id": 2, "course_name": "B", "local_folder": "C:/b"},  # new -> 1
    ])
    assert added == 1
    assert len(today_store.load_today_config()["pairs"]) == 2


def test_remove_pair_by_signature(config_dir):
    today_store.set_today_pairs([
        {"course_id": 1, "course_name": "A", "local_folder": "C:/a"},
        {"course_id": 2, "course_name": "B", "local_folder": "C:/b"},
    ])
    today_store.remove_today_pair(1, "C:/a")
    cfg = today_store.load_today_config()
    assert [p["course_id"] for p in cfg["pairs"]] == [2]


def test_mark_auto_synced_and_toggle(config_dir):
    today_store.mark_auto_synced("2026-07-05")
    today_store.set_auto_sync_enabled(True)
    cfg = today_store.load_today_config()
    assert cfg["last_auto_sync_date"] == "2026-07-05"
    assert cfg["auto_sync_enabled"] is True


def test_fda_nudge_dismissed_round_trip(config_dir):
    assert today_store.load_today_config()["fda_nudge_dismissed"] is False
    today_store.set_fda_nudge_dismissed(True)
    assert today_store.load_today_config()["fda_nudge_dismissed"] is True
    # Dismissing must not clobber neighbouring keys.
    today_store.set_auto_sync_enabled(True)
    cfg = today_store.load_today_config()
    assert cfg["fda_nudge_dismissed"] is True
    assert cfg["auto_sync_enabled"] is True


def test_fda_nudge_flag_coerced_and_absent_defaults_false(config_dir):
    import json
    # Legacy file written before the key existed + a junk value both load safely.
    (config_dir / "today_dashboard.json").write_text(
        json.dumps({"auto_sync_enabled": True, "pairs": [],
                    "last_auto_sync_date": ""}),
        encoding="utf-8",
    )
    assert today_store.load_today_config()["fda_nudge_dismissed"] is False
    (config_dir / "today_dashboard.json").write_text(
        json.dumps({"fda_nudge_dismissed": "yes-ish"}), encoding="utf-8",
    )
    assert today_store.load_today_config()["fda_nudge_dismissed"] is True


# ── Atomic write hygiene ─────────────────────────────────────────────────────

def test_no_tmp_file_left_behind(config_dir):
    today_store.set_today_pairs(
        [{"course_id": 1, "course_name": "A", "local_folder": "C:/a"}]
    )
    leftovers = list(config_dir.glob("*.tmp"))
    assert leftovers == []


def test_unicode_course_names_survive_round_trip(config_dir):
    name = "Indføring i økonomi (ÆØÅ) 📚"
    today_store.set_today_pairs(
        [{"course_id": 1, "course_name": name, "local_folder": "C:/kurser/øko"}]
    )
    assert today_store.load_today_config()["pairs"][0]["course_name"] == name
