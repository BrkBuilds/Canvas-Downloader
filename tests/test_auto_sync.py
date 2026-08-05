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


# ── Today's files scoping (ui.today_dashboard._todays_groups) ────────────────
# Two independent filters define "today's files", and each one was a real bug:
#   1. COURSE  - only courses in the curated daily-sync set. Without this the
#      page listed every quick sync run from the Sync page, so a user with an
#      EMPTY daily list still saw 43 files under "Courses in your daily sync:
#      none". It is a display filter: adding the course reveals its files,
#      removing it hides them again.
#   2. CATEGORY - only files Canvas actually gave you (new/updated/protected),
#      never 'restored' (a file the user deleted locally and asked back). The
#      old code filtered on sync_mode == 'quick' as a PROXY for this, which
#      also discarded every genuine new file from a review sync.
#
# Membership comes from resolve_today_pairs(), the same call the "Courses in
# your daily sync" card renders - so the folders below MUST really exist, and a
# pair whose folder is gone is not in the set for either of them.

def _folder(tmp_path, course_id, *, create=True):
    p = tmp_path / f"course_{course_id}"
    if create:
        p.mkdir(exist_ok=True)
    return str(p)


def _write_history_entry(config_dir, *, sync_mode, course_id, course_name, files,
                         local_folder=None):
    from datetime import datetime
    from core.sync_manager import SyncHistoryManager
    SyncHistoryManager(str(config_dir)).add_entry({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sync_mode": sync_mode,
        "synced_groups": [{
            "course_id": course_id, "course_name": course_name,
            "local_folder": local_folder or _folder(config_dir, course_id),
            "files": files,
        }],
    })


def _daily(config_dir, course_id, *, create=True):
    today_store.set_today_pairs([
        {"course_id": course_id, "course_name": f"C{course_id}",
         "local_folder": _folder(config_dir, course_id, create=create)},
    ])


def test_todays_files_only_covers_daily_sync_courses(config_dir, monkeypatch):
    """THE BUG: a quick sync from the Sync page must not appear on Today unless
    its course is in the daily-sync set."""
    import ui.today_dashboard as td
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))

    _write_history_entry(
        config_dir, sync_mode="quick", course_id=7, course_name="Off-list",
        files=[{"name": "a.pdf", "rel": "a.pdf", "category": "new"}],
    )

    # Daily set empty -> nothing on the page, but the day is reported honestly.
    groups, off_list = td._todays_groups()
    assert groups == []
    assert off_list == {"files": 1, "courses": 1}

    # Add the course -> its files from earlier today appear, nothing is "off-list".
    _daily(config_dir, 7)

    groups, off_list = td._todays_groups()
    assert [g["course_id"] for g in groups] == [7]
    assert off_list == {"files": 0, "courses": 0}

    # Remove it again -> they disappear.
    today_store.set_today_pairs([])
    groups, off_list = td._todays_groups()
    assert groups == []
    assert off_list["files"] == 1


def test_todays_files_includes_review_sync_arrivals(config_dir, monkeypatch):
    """A file downloaded via "Analyze, Review & Sync" arrived today too - only
    the RESTORED ones are curation rather than an arrival."""
    import ui.today_dashboard as td
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))
    _daily(config_dir, 1)

    _write_history_entry(
        config_dir, sync_mode="normal", course_id=1, course_name="C1",
        files=[
            {"name": "new.pdf", "rel": "new.pdf", "category": "new"},
            {"name": "upd.pdf", "rel": "upd.pdf", "category": "updated"},
            {"name": "prot_NewVersion.pdf", "rel": "prot_NewVersion.pdf",
             "category": "protected"},
            {"name": "restored.pdf", "rel": "restored.pdf", "category": "restored"},
        ],
    )

    groups, off_list = td._todays_groups()
    assert [g["course_id"] for g in groups] == [1]
    names = {f["name"] for f in groups[0]["files"]}
    assert names == {"new.pdf", "upd.pdf", "prot_NewVersion.pdf"}
    # A restored file is never counted as an arrival - not on the page, and not
    # in the "you're missing these" tally either.
    assert off_list == {"files": 0, "courses": 0}


def test_todays_files_merges_both_modes_and_dedupes(config_dir, monkeypatch):
    import ui.today_dashboard as td
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))
    _daily(config_dir, 3)

    _write_history_entry(
        config_dir, sync_mode="quick", course_id=3, course_name="C3",
        files=[{"name": "a.pdf", "rel": "a.pdf", "category": "new"}],
    )
    _write_history_entry(
        config_dir, sync_mode="normal", course_id=3, course_name="C3",
        files=[
            {"name": "a.pdf", "rel": "a.pdf", "category": "new"},   # same file again
            {"name": "b.pdf", "rel": "b.pdf", "category": "new"},
        ],
    )

    groups, _ = td._todays_groups()
    assert len(groups) == 1
    assert {f["rel"] for f in groups[0]["files"]} == {"a.pdf", "b.pdf"}


def test_todays_files_legacy_boolean_sync_mode_now_included(config_dir, monkeypatch):
    """Pre-fix entries stored sync_mode as a boolean, which the old quick-only
    filter could never match. Mode no longer gates anything, so a legacy entry
    is scoped by course + category like every other run."""
    import ui.today_dashboard as td
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))
    _daily(config_dir, 9)
    _write_history_entry(
        config_dir, sync_mode=True, course_id=9, course_name="Legacy",
        files=[{"name": "x.pdf", "rel": "x.pdf", "category": "new"}],
    )
    groups, _ = td._todays_groups()
    assert [f["name"] for g in groups for f in g["files"]] == ["x.pdf"]


def test_todays_files_folder_match_survives_path_form(config_dir, monkeypatch):
    """The daily set stores the folder the user saved; history stores
    ``str(sync_manager.local_path)``. Same folder, different spelling."""
    import ui.today_dashboard as td
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))

    folder = _folder(config_dir, 5)
    today_store.set_today_pairs([
        {"course_id": 5, "course_name": "C5",
         "local_folder": folder.replace("\\", "/") + "/"},   # trailing slash, fwd slashes
    ])
    _write_history_entry(
        config_dir, sync_mode="quick", course_id=5, course_name="C5",
        files=[{"name": "a.pdf", "rel": "a.pdf", "category": "new"}],
        local_folder=folder,
    )
    groups, _ = td._todays_groups()
    assert [g["course_id"] for g in groups] == [5]


def test_todays_files_same_course_other_folder_is_not_daily(config_dir, monkeypatch):
    """Course 6 syncs into two folders; only the daily-set pair belongs here -
    the card's "Open Folder" button points at that folder, not the other one."""
    import ui.today_dashboard as td
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))
    _daily(config_dir, 6)

    _write_history_entry(
        config_dir, sync_mode="quick", course_id=6, course_name="C6",
        files=[{"name": "in.pdf", "rel": "in.pdf", "category": "new"}],
    )
    _write_history_entry(
        config_dir, sync_mode="quick", course_id=6, course_name="C6",
        files=[{"name": "out.pdf", "rel": "out.pdf", "category": "new"}],
        local_folder="/tmp/backup_c6",
    )

    groups, off_list = td._todays_groups()
    assert [f["name"] for g in groups for f in g["files"]] == ["in.pdf"]
    assert off_list == {"files": 1, "courses": 1}


def test_unreachable_daily_pair_is_listed_not_hidden(config_dir, monkeypatch):
    """A daily pair whose folder was deleted stays ON the list, in the amber
    state - it is never silently dropped.

    Two bugs met here. The card used to hide such a pair entirely, so three
    courses the user had deliberately added vanished from the page with no
    explanation anywhere and the daily sync quietly had nothing to do. And for
    one round the file list read the raw stored pairs while the card filtered on
    folder existence, which put a 40-file course card directly under a panel
    reading "No courses in your daily sync yet".
    """
    import ui.today_dashboard as td
    from core.auto_sync import resolve_today_pairs
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))

    gone = _folder(config_dir, 11, create=False)
    today_store.set_today_pairs([
        {"course_id": 11, "course_name": "Deleted folder", "local_folder": gone},
    ])
    _write_history_entry(
        config_dir, sync_mode="quick", course_id=11, course_name="Deleted folder",
        files=[{"name": "a.pdf", "rel": "a.pdf", "category": "new"}],
        local_folder=gone,
    )

    # It is not runnable...
    assert resolve_today_pairs() == []
    # ...but it IS on the list, and the card renders it in the amber state.
    runnable, unreachable = td._split_daily_pairs()
    assert runnable == []
    assert [p["course_id"] for p in unreachable] == [11]

    groups, off_list = td._todays_groups()
    # No files: the folder they lived in is gone, so there is nothing to open.
    assert groups == []
    # And NOT counted as "a course that isn't in your daily sync" - it is in the
    # daily sync, listed in amber right above. Saying otherwise would contradict
    # the card.
    assert off_list == {"files": 0, "courses": 0}


def _hub_group(config_dir, group_name, pairs):
    from core.sync_manager import SavedGroupsManager
    SavedGroupsManager(str(config_dir)).save_group(group_name, pairs)


def test_deleting_a_saved_pair_removes_it_from_daily(config_dir):
    """Deleting a saved pair from the hub clears its daily membership too - the
    daily flag lives ON the pair (core.library), so it cannot outlive it."""
    folder = _folder(config_dir, 21)
    from core.sync_manager import SavedGroupsManager
    mgr = SavedGroupsManager(str(config_dir))
    rec = mgr.save_group("P21", [
        {"course_id": 21, "course_name": "C21", "local_folder": folder}],
        is_single_pair=True)
    today_store.set_today_pairs([
        {"course_id": 21, "course_name": "C21", "local_folder": folder}])
    assert [p["course_id"] for p in today_store.load_today_config()["pairs"]] == [21]

    mgr.delete_group(rec["group_id"])   # delete the saved pair
    assert today_store.load_today_config()["pairs"] == []


def test_relinking_a_saved_pair_moves_its_daily_membership(config_dir):
    """"Edit Pair" to re-link a moved folder fixes it on the Today page too, with
    no reconcile - it is the SAME record, so its daily flag follows the move."""
    old = _folder(config_dir, 22, create=False)      # where it used to live
    new = _folder(config_dir, 23)                    # where the user re-linked it
    from core.sync_manager import SavedGroupsManager
    mgr = SavedGroupsManager(str(config_dir))
    rec = mgr.save_group("P22", [
        {"course_id": 22, "course_name": "C22", "local_folder": old}],
        is_single_pair=True)
    today_store.set_today_pairs([
        {"course_id": 22, "course_name": "C22", "local_folder": old}])

    mgr.update_group(rec["group_id"], {"pairs": [
        {"course_id": 22, "course_name": "C22", "local_folder": new}]})   # hub Edit Pair

    cfg = today_store.load_today_config()
    assert cfg["pairs"][0]["local_folder"] == new    # daily followed the re-link
    assert [p["course_id"] for p in auto_sync.resolve_today_pairs()] == [22]


def test_reconcile_is_a_noop_now(config_dir):
    """The daily set is the library's own flag, so there are no copies to
    reconcile: the function stays (its call sites are harmless) but does nothing."""
    folder = _folder(config_dir, 24)
    today_store.set_today_pairs([
        {"course_id": 24, "course_name": "C24", "local_folder": folder}])
    before = today_store.load_today_config()["pairs"]
    assert auto_sync.reconcile_daily_list_with_hub() == 0
    assert today_store.load_today_config()["pairs"] == before


def test_unreachable_pairs_are_reported_as_skipped(config_dir, fake_session):
    """A skipped course is otherwise invisible - the run just quietly covers
    fewer courses than the list says."""
    gone = _folder(config_dir, 26, create=False)
    live = _folder(config_dir, 27)
    today_store.set_today_pairs([
        {"course_id": 26, "course_name": "Gone (LA)", "local_folder": gone},
        {"course_id": 27, "course_name": "Fine (LA)", "local_folder": live},
    ])

    # The run itself is NOT blocked by the missing folder - it syncs the rest.
    assert [p["course_id"] for p in auto_sync.resolve_today_pairs()] == [27]
    assert [p["course_id"] for p in auto_sync.unreachable_today_pairs()] == [26]

    notice = auto_sync.build_today_sync_notice()
    assert notice["skipped"] == ["Gone (LA)"]


def test_unreachable_pair_does_not_suppress_a_healthy_one(config_dir, monkeypatch):
    """One broken pair must not affect the rest of the daily set."""
    import ui.today_dashboard as td
    monkeypatch.setattr(td, "get_config_dir", lambda: str(config_dir))

    gone = _folder(config_dir, 12, create=False)
    live = _folder(config_dir, 13)
    today_store.set_today_pairs([
        {"course_id": 12, "course_name": "Gone", "local_folder": gone},
        {"course_id": 13, "course_name": "Fine", "local_folder": live},
    ])
    _write_history_entry(
        config_dir, sync_mode="quick", course_id=12, course_name="Gone",
        files=[{"name": "x.pdf", "rel": "x.pdf", "category": "new"}],
        local_folder=gone,
    )
    _write_history_entry(
        config_dir, sync_mode="normal", course_id=13, course_name="Fine",
        files=[{"name": "y.pdf", "rel": "y.pdf", "category": "new"}],
        local_folder=live,
    )

    runnable, unreachable = td._split_daily_pairs()
    assert [p["course_id"] for p in runnable] == [13]
    assert [p["course_id"] for p in unreachable] == [12]

    groups, off_list = td._todays_groups()
    assert [f["name"] for g in groups for f in g["files"]] == ["y.pdf"]
    assert off_list == {"files": 0, "courses": 0}
