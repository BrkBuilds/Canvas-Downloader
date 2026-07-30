"""Tests for sync_manager - the SQLite manifest engine that is the single
source of truth for what has been synced.

Covers: DB creation + course-identity binding, manifest record/load
round-trips, ignore-flag preservation across re-records (a user's "never
download this" must survive), the static peek helpers, sync-history
persistence/retention/amendment, and the connection-closing regression
(a lingering handle transiently locks .canvas_sync.db on Windows).
"""

from __future__ import annotations

import os

import pytest

from core.sync_manager import SyncHistoryManager, SyncManager


@pytest.fixture()
def course_dir(tmp_path):
    d = tmp_path / "Algorithms 101"
    d.mkdir()
    return d


@pytest.fixture()
def sm(course_dir):
    return SyncManager(course_dir, course_id=4242, course_name="Algorithms 101")


def _write_local(course_dir, rel, content=b"hello world"):
    p = course_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


# ── Init & identity binding ──────────────────────────────────────────────────

def test_init_creates_db(sm, course_dir):
    assert sm.db_path.exists()
    assert sm.db_was_reset is False
    assert sm._db_init_failed is False


def test_course_identity_binds_once(sm, course_dir):
    assert SyncManager.peek_bound_course_id(str(course_dir)) == 4242
    # A second manager with a DIFFERENT id must NOT rebind the folder -
    # manifest file-ids are course-specific.
    SyncManager(course_dir, course_id=9999, course_name="Imposter")
    assert SyncManager.peek_bound_course_id(str(course_dir)) == 4242


def test_course_name_refreshes(sm, course_dir):
    SyncManager(course_dir, course_id=4242, course_name="Algorithms 101 (renamed)")
    assert SyncManager.peek_bound_course_name(str(course_dir)) == "Algorithms 101 (renamed)"


def test_peeks_on_folder_without_db(tmp_path):
    empty = tmp_path / "no-db-here"
    empty.mkdir()
    assert SyncManager.peek_bound_course_id(str(empty)) is None
    assert SyncManager.peek_last_synced(str(empty)) is None


# ── Manifest record / load round-trip ────────────────────────────────────────

def test_record_and_load_roundtrip(sm, course_dir):
    _write_local(course_dir, "Week 1/slides.pdf", b"pdf-bytes")
    ok = sm.record_downloaded_file(
        canvas_file_id=101,
        canvas_filename="slides.pdf",
        local_path="Week 1/slides.pdf",
        canvas_updated_at="2026-07-01T10:00:00Z",
        original_size=9,
    )
    assert ok is True

    manifest = sm.load_manifest()
    assert manifest["course_id"] == 4242
    entry = manifest["files"]["101"]
    assert entry["canvas_filename"] == "slides.pdf"
    assert entry["local_path"] == "Week 1/slides.pdf"
    assert entry["original_size"] == 9
    assert entry["is_ignored"] is False
    # md5 baseline computed from the on-disk file when caller passes none
    assert entry["original_md5"] != ""


def test_rerecord_same_id_is_idempotent(sm, course_dir):
    _write_local(course_dir, "a.pdf")
    for _ in range(3):
        sm.record_downloaded_file(101, "a.pdf", "a.pdf", "2026-01-01T00:00:00Z", 11)
    assert len(sm.load_manifest()["files"]) == 1


def test_ignore_survives_redownload_record(sm, course_dir):
    """A user's ignore decision must not be wiped by a later re-record."""
    _write_local(course_dir, "big-video.mp4", b"x" * 64)
    sm.record_downloaded_file(7, "big-video.mp4", "big-video.mp4", "", 64)
    assert sm.ignore_file(7, "big-video.mp4", 64) is True
    assert any(f.canvas_file_id == 7 for f in sm.get_ignored_files())

    # Re-record (e.g. a partial re-download pass touches the same id)
    sm.record_downloaded_file(7, "big-video.mp4", "big-video.mp4", "", 64)
    assert sm.load_manifest()["files"]["7"]["is_ignored"] is True


def test_last_synced_metadata_roundtrip(sm, course_dir):
    assert SyncManager.peek_last_synced(str(course_dir)) is None
    assert sm._save_metadata("last_synced", "2026-07-05 09:30") is True
    assert SyncManager.peek_last_synced(str(course_dir)) == "2026-07-05 09:30"


# ── Connection lifecycle (the closing() regression) ──────────────────────────

def test_db_file_deletable_immediately_after_operations(sm, course_dir):
    """Every operation must CLOSE its connection, not leave it to GC.

    On Windows an open handle makes os.remove raise PermissionError, so this
    is a direct, platform-relevant probe for a leaked connection. Deliberately
    no gc.collect() first - the point is that none is needed.
    """
    _write_local(course_dir, "f.pdf")
    sm.record_downloaded_file(1, "f.pdf", "f.pdf", "", 11)
    sm.load_manifest()
    sm.ignore_file(1)
    sm.get_ignored_files()
    sm._save_metadata("last_synced", "2026-07-05 09:30")
    SyncManager.peek_last_synced(str(course_dir))

    for suffix in ("", "-wal", "-shm"):
        p = course_dir / (sm.db_path.name + suffix)
        if p.exists():
            os.remove(p)  # PermissionError here = a connection leaked


# ── Panopto manifest / ignore tables ─────────────────────────────────────────

def test_panopto_record_and_ignore_roundtrip(sm):
    assert sm.record_panopto_file("vid-guid-1", "mp3", "lec.mp3", "Lecture 1") is True
    assert sm.get_ignored_panopto() == {}

    assert sm.ignore_panopto("vid-guid-2", "Lecture 2") is True
    assert sm.ignore_panopto("vid-guid-2", "Lecture 2 (renamed)") is True  # idempotent upsert
    ignored = sm.get_ignored_panopto()
    assert ignored == {"vid-guid-2": "Lecture 2 (renamed)"}

    assert sm.restore_panopto("vid-guid-2") is True
    assert sm.get_ignored_panopto() == {}


# ── Sync history ─────────────────────────────────────────────────────────────

def test_history_roundtrip_and_corruption_safety(tmp_path):
    mgr = SyncHistoryManager(str(tmp_path))
    assert mgr.load_history() == []

    mgr.add_entry({"timestamp": "2026-07-05 09:00", "files_synced": 3})
    assert mgr.load_history()[0]["files_synced"] == 3

    # Corrupt file degrades to empty, never raises
    mgr.history_path.write_text("{corrupt", encoding="utf-8")
    assert mgr.load_history() == []


def test_history_retention_default_50(tmp_path):
    mgr = SyncHistoryManager(str(tmp_path))
    for i in range(55):
        mgr.add_entry({"timestamp": f"t{i}", "files_synced": i})
    hist = mgr.load_history()
    assert len(hist) == 50
    assert hist[0]["timestamp"] == "t5"     # oldest 5 trimmed
    assert hist[-1]["timestamp"] == "t54"


def test_amend_last_entry_merges_panopto_results(tmp_path):
    mgr = SyncHistoryManager(str(tmp_path))
    mgr.add_entry({
        "timestamp": "2026-07-05 09:00",
        "files_synced": 2,
        "synced_files": ["a.pdf"],
        "categorized_files": {"new": ["a.pdf"], "updated": [], "restored": [], "protected": []},
    })
    ok = mgr.amend_last_entry(
        timestamp="2026-07-05 09:00",
        add_files_synced=1,
        add_categorized={"new": ["lec.mp3"]},
        add_synced_files=["lec.mp3"],
        synced_groups=[{"course_name": "A", "files": [{"name": "lec.mp3"}]}],
    )
    assert ok is True
    entry = mgr.load_history()[-1]
    assert entry["files_synced"] == 3
    assert "lec.mp3" in entry["synced_files"]
    assert entry["synced_groups"][0]["files"][0]["name"] == "lec.mp3"


def test_amend_on_empty_history_returns_false(tmp_path):
    mgr = SyncHistoryManager(str(tmp_path))
    assert mgr.amend_last_entry(add_files_synced=1) is False


# ---------------------------------------------------------------------------
# analyze_course: the locally-deleted / re-upload branch
# ---------------------------------------------------------------------------
#
# This branch guards its own dict lookup, and the guard was briefly flipped
# from `and` to `or` (2026-07-30). The whole 1,542-test suite passed with that
# in place, because nothing covered the most ordinary shape of all: a file the
# user deleted locally that is ALSO gone from Canvas, with no same-named
# replacement. It raised KeyError in the middle of sync analysis.

def _cf(file_id: int, name: str):
    from core.sync_manager import CanvasFileInfo
    return CanvasFileInfo(id=file_id, filename=name, display_name=name, size=9,
                          modified_at="2026-07-01T00:00:00Z", url="http://x/f")


def _tracked_then_deleted_locally(sm, course_dir):
    """One manifest row whose local file does not exist."""
    sm.record_downloaded_file(555001, "Old Lecture Notes.pdf",
                              str(course_dir / "Old Lecture Notes.pdf"),
                              "2026-01-01T00:00:00Z", 1234)
    return sm.load_manifest()


def test_locally_deleted_and_gone_from_canvas_does_not_raise(sm, course_dir):
    """THE regression. Canvas no longer serves the file and offers nothing with
    the same name, so the re-upload lookup has no entry to find.

    Reachable constantly: the phantom-row pruning later in analyze_course exists
    specifically to handle canvas-gone + locally-gone rows, so they arrive here
    as a matter of course.
    """
    manifest = _tracked_then_deleted_locally(sm, course_dir)
    res = sm.analyze_course([_cf(555999, "Unrelated.pdf")], manifest)
    names = [d.canvas_filename for d in res.locally_deleted_files]
    assert "Old Lecture Notes.pdf" in names, "the deletion must still be reported"
    row = res.locally_deleted_files[names.index("Old Lecture Notes.pdf")]
    assert getattr(row, "_reupload_new_file", None) is None, \
        "there is no replacement, so nothing may be linked as one"


def test_a_genuine_reupload_is_still_linked(sm, course_dir):
    """The direction that must NOT regress while fixing the above: same name,
    NEW Canvas id, old id gone. The new file is claimed by the deleted row and
    withheld from new_files so it is not offered twice."""
    manifest = _tracked_then_deleted_locally(sm, course_dir)
    res = sm.analyze_course([_cf(555002, "Old Lecture Notes.pdf")], manifest)
    assert len(res.locally_deleted_files) == 1
    linked = getattr(res.locally_deleted_files[0], "_reupload_new_file", None)
    assert linked is not None and linked.id == 555002
    assert not res.new_files, "the re-upload must not also appear as a new file"


def test_a_file_still_on_canvas_is_a_plain_local_deletion(sm, course_dir):
    """Same id still served by Canvas: a normal restore candidate, and
    explicitly NOT a re-upload - `_is_true_reupload` is false here."""
    manifest = _tracked_then_deleted_locally(sm, course_dir)
    res = sm.analyze_course([_cf(555001, "Old Lecture Notes.pdf")], manifest)
    assert len(res.locally_deleted_files) == 1
    assert getattr(res.locally_deleted_files[0], "_reupload_new_file", None) is None


def test_the_reupload_guard_is_a_conjunction():
    """Structural, because the failure is a one-character edit that no existing
    test caught. The body immediately indexes `new_name_map[missing_norm]`, so
    the membership test is that lookup's only guard - and `or` also buys
    nothing, since the `else` performs the same append the branch ends with."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "core" / "sync_manager.py"
    text = src.read_text(encoding="utf-8")
    text = re.sub(r"^\s*#.*$", "", text, flags=re.M)      # ignore commentary
    assert "_is_true_reupload and missing_norm in new_name_map" in text
    assert "_is_true_reupload or missing_norm in new_name_map" not in text
