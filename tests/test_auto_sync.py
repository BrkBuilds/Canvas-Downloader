"""Tests for core.auto_sync - the daily auto-sync trigger logic and the
Today success-notice snapshot.

``should_auto_sync`` decides whether a launch silently starts downloading;
a false positive re-syncs on every open, a false negative kills the feature.
``build_today_sync_notice`` feeds both the in-page notice and the native
daily-sync notification, and must be resilient to partial session state.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared import helpers
from core import auto_sync, today_store


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers, "get_config_dir", lambda: str(tmp_path))
    return tmp_path


@pytest.fixture()
def fake_session(monkeypatch):
    """Replace the streamlit module ref inside core.auto_sync with a stub whose
    session_state is a plain dict - deterministic, no Streamlit runtime."""
    stub = SimpleNamespace(session_state={})
    monkeypatch.setattr(auto_sync, "st", stub)
    return stub.session_state


# ── resolve_today_pairs ──────────────────────────────────────────────────────

def test_resolve_drops_missing_folders(config_dir, tmp_path):
    real = tmp_path / "algo_folder"
    real.mkdir()
    today_store.set_today_pairs([
        {"course_id": 1, "course_name": "Algo", "local_folder": str(real)},
        {"course_id": 2, "course_name": "Gone", "local_folder": str(tmp_path / "nope")},
    ])
    runnable = auto_sync.resolve_today_pairs()
    assert [p["course_id"] for p in runnable] == [1]


def test_resolve_empty_when_nothing_curated(config_dir):
    assert auto_sync.resolve_today_pairs() == []


# ── should_auto_sync ─────────────────────────────────────────────────────────

def _curate_one_real_pair(tmp_path):
    folder = tmp_path / "course"
    folder.mkdir(exist_ok=True)
    today_store.set_today_pairs(
        [{"course_id": 1, "course_name": "A", "local_folder": str(folder)}]
    )


def test_should_not_fire_when_disabled(config_dir, tmp_path):
    _curate_one_real_pair(tmp_path)
    today_store.set_auto_sync_enabled(False)
    assert auto_sync.should_auto_sync() is False


def test_should_not_fire_twice_same_logical_day(config_dir, tmp_path):
    _curate_one_real_pair(tmp_path)
    today_store.set_auto_sync_enabled(True)
    today_store.mark_auto_synced(today_store.logical_today())
    assert auto_sync.should_auto_sync() is False


def test_fires_on_new_day_with_runnable_pairs(config_dir, tmp_path):
    _curate_one_real_pair(tmp_path)
    today_store.set_auto_sync_enabled(True)
    today_store.mark_auto_synced("2020-01-01")
    assert auto_sync.should_auto_sync() is True


def test_does_not_fire_when_every_folder_is_missing(config_dir, tmp_path):
    today_store.set_today_pairs(
        [{"course_id": 1, "course_name": "A", "local_folder": str(tmp_path / "gone")}]
    )
    today_store.set_auto_sync_enabled(True)
    today_store.mark_auto_synced("2020-01-01")
    assert auto_sync.should_auto_sync() is False


# ── build_today_sync_notice ──────────────────────────────────────────────────

def test_notice_counts_files_per_course(fake_session):
    fake_session.update({
        "today_sync_is_auto": True,
        "synced_count": 5,
        "sync_errors": [],
        "synced_groups": [
            {"course_name": "Algorithms 101", "files": [{"name": "a"}, {"name": "b"}]},
            {"course_name": "Statistics", "files": [{"name": "c"}, {"name": "d"}, {"name": "e"}]},
            {"course_name": "Empty Course", "files": []},   # no files -> omitted
        ],
    })
    notice = auto_sync.build_today_sync_notice()
    assert notice["is_auto"] is True
    assert notice["total_files"] == 5
    assert notice["errors"] == 0
    assert [c["count"] for c in notice["courses"]] == [2, 3]
    assert all(c["name"] for c in notice["courses"])


def test_notice_trusts_larger_of_count_and_groups(fake_session):
    # group-building is best-effort; synced_count is the engine tally.
    fake_session.update({
        "synced_count": 2,
        "synced_groups": [{"course_name": "A", "files": [{}, {}, {}]}],  # 3 files
        "sync_errors": ["boom"],
    })
    notice = auto_sync.build_today_sync_notice()
    assert notice["total_files"] == 3
    assert notice["errors"] == 1
    assert notice["is_auto"] is False


def test_notice_survives_empty_session(fake_session):
    notice = auto_sync.build_today_sync_notice()
    assert notice["total_files"] == 0
    assert notice["courses"] == []
    assert notice["errors"] == 0
    assert notice["completed_at"]  # HH:MM stamp always present


def test_notice_tolerates_garbage_types(fake_session):
    fake_session.update({
        "synced_count": "not-an-int",
        "synced_groups": [{"course_name": "A", "files": [{}]}],
        "sync_errors": None,
    })
    notice = auto_sync.build_today_sync_notice()
    assert notice["total_files"] == 1   # falls back to the group tally
    assert notice["errors"] == 0


# ── Today's files: quick-sync-only filter (ui.today_dashboard._todays_groups) ─
# "Today's files" must reflect ONLY the page's own hands-off / one-click syncs
# (daily auto-sync + "Quick Sync now", both recorded sync_mode == 'quick'). A
# manual "Analyze, Review & Sync" is the ONLY run type that can restore a
# locally-deleted file, so filtering to quick-mode is also what keeps restored
# files off the Today page.

def _write_history_entry(config_dir, *, sync_mode, course_id, course_name, files):
    from datetime import datetime
    from core.sync_manager import SyncHistoryManager
    SyncHistoryManager(str(config_dir)).add_entry({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sync_mode": sync_mode,
        "synced_groups": [{
            "course_id": course_id, "course_name": course_name,
            "local_folder": f"/tmp/c{course_id}", "files": files,
        }],
    })


def test_todays_files_excludes_manual_review_sync(config_dir, monkeypatch):
    import ui.today_dashboard as td
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))

    # Manual review-sync today that RESTORED a locally-deleted file.
    _write_history_entry(
        config_dir, sync_mode="normal", course_id=1, course_name="Manual",
        files=[{"name": "restored.pdf", "rel": "restored.pdf", "category": "restored"}],
    )
    # Quick Sync today that pulled a genuinely new file.
    _write_history_entry(
        config_dir, sync_mode="quick", course_id=2, course_name="Quick",
        files=[{"name": "new.pdf", "rel": "new.pdf", "category": "new"}],
    )

    groups = td._todays_groups()
    assert {g["course_id"] for g in groups} == {2}          # manual run excluded
    all_files = [f for g in groups for f in g["files"]]
    assert all(f["category"] != "restored" for f in all_files)


def test_todays_files_excludes_legacy_boolean_sync_mode(config_dir, monkeypatch):
    # Pre-fix entries stored sync_mode as a boolean (True = "in sync mode"), which
    # can't prove the run was quick - so they're safely excluded, not shown.
    import ui.today_dashboard as td
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))
    _write_history_entry(
        config_dir, sync_mode=True, course_id=9, course_name="Legacy",
        files=[{"name": "x.pdf", "rel": "x.pdf", "category": "new"}],
    )
    assert td._todays_groups() == []
