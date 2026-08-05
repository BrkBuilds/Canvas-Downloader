"""Tests for sync-pair persistence: ``sync.persistence`` + the atomic write
primitive it rests on (``shared.helpers.atomic_update_sync_pairs``).

Why this file exists
--------------------
``canvas_sync_pairs.json`` is the user's configuration - which Canvas course
maps to which folder on their disk. Losing it means every pair has to be set up
again by hand, and the failure is silent: the app simply opens with no pairs.

Neither layer had a single test. ``atomic_update_sync_pairs`` in particular is
the one function standing between a cross-thread Streamlit rerun and a
half-written config file, and its entire contract - lock, re-read from DISK,
modify, ``os.replace`` - is invisible unless something exercises it
concurrently.

The read-modify-write is the point
----------------------------------
Every mutation re-reads the file inside the lock rather than trusting the list
in ``st.session_state``. That is what makes two updates racing from different
threads compose instead of clobbering. A "simplification" that passes
``st.session_state['sync_pairs']`` into the modifier would pass every test that
only ever calls one function at a time - hence the concurrency tests below.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from types import SimpleNamespace

import pytest

from shared import helpers
from sync import persistence


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """Point every read/write at a throwaway directory.

    Without this the suite would rewrite the developer's real sync pairs.
    """
    monkeypatch.setattr(helpers, "get_config_dir", lambda: str(tmp_path))
    return tmp_path


@pytest.fixture()
def pairs_file(config_dir):
    return config_dir / helpers.SYNC_PAIRS_FILENAME


@pytest.fixture()
def session(monkeypatch):
    """Stub ``st`` inside sync.persistence; record toasts instead of showing them."""
    toasts: list = []
    stub = SimpleNamespace(
        session_state={},
        toast=lambda msg, icon=None: toasts.append((msg, icon)),
    )
    monkeypatch.setattr(persistence, "st", stub)
    stub.toasts = toasts
    return stub


def _pair(cid, folder, name="Course", last=None):
    p = {"course_id": cid, "local_folder": folder, "course_name": name}
    if last is not None:
        p["last_synced"] = last
    return p


def _on_disk(pairs_file) -> list:
    return json.loads(pairs_file.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════
# The atomic primitive
# ═══════════════════════════════════════════════════════════════════════════

def test_the_modifier_receives_what_is_on_DISK_not_what_was_passed_in(config_dir, pairs_file):
    """The core contract. Another thread (or another window) may have written
    since this caller last read, and the modifier must see that."""
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")

    seen = {}

    def modifier(fresh):
        seen['value'] = list(fresh)
        return fresh + [_pair(2, "/b")]

    helpers.atomic_update_sync_pairs(modifier)
    assert seen['value'] == [_pair(1, "/a")], \
        "the modifier was not given the current on-disk state"
    assert len(_on_disk(pairs_file)) == 2


def test_a_concurrent_write_is_not_clobbered(config_dir, pairs_file):
    """Simulates the real race: this caller read the file, something else wrote
    to it, and only then does the modifier run. The other write must survive."""
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")

    def modifier(fresh):
        return fresh + [_pair(3, "/c")]

    # A different actor commits between the caller's mental read and the call.
    pairs_file.write_text(json.dumps([_pair(1, "/a"), _pair(2, "/b")]),
                          encoding="utf-8")
    helpers.atomic_update_sync_pairs(modifier)

    ids = sorted(p["course_id"] for p in _on_disk(pairs_file))
    assert ids == [1, 2, 3], "a concurrent write was lost"


def test_parallel_appends_all_survive(config_dir, pairs_file):
    """20 threads each append one pair. Every one must land.

    This is the test that fails if the lock or the re-read is removed - the
    classic lost-update, where two threads read the same list and the second
    write erases the first.
    """
    n = 20
    barrier = threading.Barrier(n)
    errors: list = []

    def worker(i):
        try:
            barrier.wait(timeout=10)
            helpers.atomic_update_sync_pairs(
                lambda fresh, i=i: fresh + [_pair(i, f"/f{i}")])
        except Exception as e:                      # pragma: no cover - diagnostic
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"worker(s) raised: {errors}"
    ids = sorted(p["course_id"] for p in _on_disk(pairs_file))
    assert ids == list(range(n)), f"lost updates: missing {set(range(n)) - set(ids)}"


def test_corrupt_json_is_treated_as_empty_and_still_writes(config_dir, pairs_file):
    """A truncated file (power loss mid-write on an older build) must not brick
    the feature - and must not stop the user creating a new pair."""
    pairs_file.write_text('[{"course_id": 1, "local_fo', encoding="utf-8")
    out = helpers.atomic_update_sync_pairs(lambda fresh: fresh + [_pair(9, "/z")])
    assert out == [_pair(9, "/z")]
    assert _on_disk(pairs_file) == [_pair(9, "/z")]


def test_a_json_object_instead_of_a_list_is_treated_as_empty(config_dir, pairs_file):
    """Defends the ``isinstance(data, list)`` check: a dict would make the
    modifier iterate keys and silently produce nonsense."""
    pairs_file.write_text('{"course_id": 1}', encoding="utf-8")
    out = helpers.atomic_update_sync_pairs(lambda fresh: fresh + [_pair(9, "/z")])
    assert out == [_pair(9, "/z")]


def test_a_missing_file_starts_from_empty(config_dir, pairs_file):
    assert not pairs_file.exists()
    out = helpers.atomic_update_sync_pairs(lambda fresh: fresh + [_pair(1, "/a")])
    assert out == [_pair(1, "/a")]
    assert pairs_file.exists()


def test_no_tmp_file_is_left_behind(config_dir, pairs_file):
    """``.tmp`` is the staging file for ``os.replace``. One left on disk means
    a write died halfway, and it would shadow nothing but confuse the next
    reader looking at the config directory."""
    helpers.atomic_update_sync_pairs(lambda fresh: fresh + [_pair(1, "/a")])
    leftovers = list(config_dir.glob("*.tmp"))
    assert not leftovers, f"staging files left behind: {leftovers}"


def test_the_written_file_is_valid_utf8_json_with_non_ascii(config_dir, pairs_file):
    """Course names carry Danish characters. ``ensure_ascii=False`` plus an
    explicit utf-8 encoding is what keeps them readable; Windows would
    otherwise write cp1252 and mojibake them."""
    helpers.atomic_update_sync_pairs(
        lambda fresh: [_pair(1, "/a", name="Økonomi og Ledelse - Ærø")])
    raw = pairs_file.read_bytes().decode("utf-8")
    assert "Økonomi og Ledelse - Ærø" in raw
    assert json.loads(raw)[0]["course_name"] == "Økonomi og Ledelse - Ærø"


def test_a_failed_write_returns_what_is_on_disk_not_the_new_list(config_dir, pairs_file, monkeypatch):
    """The M-22 contract. If the commit fails, callers must not be handed the
    list that did NOT get saved - they would put it in session_state and show
    the user a pair that vanishes on restart.
    """
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    out = helpers.atomic_update_sync_pairs(lambda fresh: fresh + [_pair(2, "/b")])
    assert out == [_pair(1, "/a")], "a failed write must report the committed state"
    assert _on_disk(pairs_file) == [_pair(1, "/a")]


def test_load_sync_pairs_survives_corruption(config_dir, pairs_file):
    pairs_file.write_text("not json at all", encoding="utf-8")
    assert helpers.load_sync_pairs() == []


def test_load_sync_pairs_rejects_a_non_list(config_dir, pairs_file):
    pairs_file.write_text('{"a": 1}', encoding="utf-8")
    assert helpers.load_sync_pairs() == []


def test_load_sync_pairs_on_a_missing_file(config_dir):
    assert helpers.load_sync_pairs() == []


# ═══════════════════════════════════════════════════════════════════════════
# The dangerous-folder guard
# ═══════════════════════════════════════════════════════════════════════════

_WIN_ROOTS = [r"C:\Windows", r"c:\windows\system32", r"C:\Program Files\App",
              r"C:\Program Files (x86)\App", r"C:\ProgramData\Sub"]
_NIX_ROOTS = ["/etc", "/etc/nested", "/usr/lib", "/bin", "/var/log", "/sys"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows system roots")
@pytest.mark.parametrize("folder", _WIN_ROOTS)
def test_windows_system_roots_are_rejected(folder):
    """Syncing into these would write course files into the OS install and, on
    a later 'restore deleted', hand the delete logic a system directory."""
    assert persistence._validate_pair_folder(folder) is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX system roots")
@pytest.mark.parametrize("folder", _NIX_ROOTS)
def test_posix_system_roots_are_rejected(folder):
    assert persistence._validate_pair_folder(folder) is False


def test_a_nested_path_under_a_bad_root_is_rejected_not_just_the_root(tmp_path):
    """The guard matches prefixes, so ``C:\\Windows\\Fonts\\Courses`` is caught
    too. Matching only the exact root would leave the whole tree open."""
    if sys.platform == "win32":
        assert persistence._validate_pair_folder(r"C:\Windows\Fonts\Courses") is False
    else:
        assert persistence._validate_pair_folder("/usr/lib/courses") is False


def test_an_ordinary_user_folder_is_accepted(tmp_path):
    assert persistence._validate_pair_folder(str(tmp_path)) is True


def test_a_folder_that_cannot_be_resolved_is_rejected(tmp_path):
    """Fails CLOSED. ``resolve()`` raising means we cannot prove the path is
    safe, and the cost of a false reject is one re-pick."""
    assert persistence._validate_pair_folder(None) is False
    assert persistence._validate_pair_folder(b"\xff") is False


def test_the_empty_string_is_currently_ACCEPTED(tmp_path, monkeypatch):
    """Documents a real weakness rather than pretending it is not there.

    ``Path('').resolve()`` is the process's working directory, so an empty
    folder validates as safe and would pair a course to wherever the app was
    launched from. Both call sites (``ui/hub_dialog.py``,
    ``ui/sync_dialogs.py``) pick the folder from a picker first, so it is not
    reachable today - but nothing in THIS layer says so, and the guard's whole
    job is to be the last line.

    If the guard is ever hardened to reject blank input, delete this test and
    assert ``False``; do not weaken it silently.
    """
    assert persistence._validate_pair_folder("") is True


# ═══════════════════════════════════════════════════════════════════════════
# Library references (saved pairs on the working list follow hub edits)
# ═══════════════════════════════════════════════════════════════════════════

def test_active_entry_follows_a_hub_relink_by_stable_id(config_dir):
    """A saved pair on the working list is stored as a reference (saved_id), so a
    hub re-link (folder move) shows up on load without touching the sync list."""
    import core.library as library
    pid = library.save_pair(1, "C:/old", "Course A", name="Macro")
    (config_dir / helpers.SYNC_PAIRS_FILENAME).write_text(
        json.dumps([{"course_id": 1, "local_folder": "C:/old",
                     "course_name": "Course A", "saved_id": pid}]),
        encoding="utf-8")

    library.relink_pair(pid, 1, "C:/new", "Course A")
    got = helpers.load_sync_pairs()
    assert got[0]["local_folder"] == "C:/new"      # followed the move
    assert got[0]["saved_id"] == pid


def test_active_entry_binds_a_bare_link_opportunistically(config_dir):
    """A pre-existing entry with no saved_id but a link that IS a saved pair gets
    bound to it on load (so old lists pick up references)."""
    import core.library as library
    pid = library.save_pair(2, "C:/b", "Course B", name="Beta")
    (config_dir / helpers.SYNC_PAIRS_FILENAME).write_text(
        json.dumps([{"course_id": 2, "local_folder": "C:/b", "course_name": "Course B"}]),
        encoding="utf-8")
    assert helpers.load_sync_pairs()[0]["saved_id"] == pid


def test_active_entry_degrades_to_raw_when_saved_pair_deleted(config_dir):
    """Deleting the saved pair must not drop it from the working list - it stays
    as a raw entry (keeps its cached fields, loses the dangling reference)."""
    import core.library as library
    pid = library.save_pair(3, "C:/c", "Course C", name="Gamma")
    (config_dir / helpers.SYNC_PAIRS_FILENAME).write_text(
        json.dumps([{"course_id": 3, "local_folder": "C:/c",
                     "course_name": "Course C", "saved_id": pid}]),
        encoding="utf-8")
    library.delete_pair(pid)
    got = helpers.load_sync_pairs()
    assert len(got) == 1
    assert got[0]["local_folder"] == "C:/c"        # kept
    assert "saved_id" not in got[0]                # dangling ref dropped


# ═══════════════════════════════════════════════════════════════════════════
# Create
# ═══════════════════════════════════════════════════════════════════════════

def test_add_pair_writes_through_to_disk(config_dir, pairs_file, session, tmp_path):
    persistence.add_pair(_pair(1, str(tmp_path)))
    assert _on_disk(pairs_file) == [_pair(1, str(tmp_path))]
    assert session.session_state['sync_pairs'] == [_pair(1, str(tmp_path))]


def test_add_pair_deduplicates_on_course_AND_folder(config_dir, pairs_file, session, tmp_path):
    """Double-click safety. ``on_click`` handlers can fire twice, and the
    project rule is that every mutation must be idempotent."""
    persistence.add_pair(_pair(1, str(tmp_path)))
    persistence.add_pair(_pair(1, str(tmp_path)))
    assert len(_on_disk(pairs_file)) == 1


def test_the_same_course_in_a_DIFFERENT_folder_is_a_different_pair(config_dir, pairs_file, session, tmp_path):
    """Identity is (course, folder) - the same course legitimately syncs into
    two places, and Today's off-list tally depends on that being distinct."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    persistence.add_pair(_pair(1, str(a)))
    persistence.add_pair(_pair(1, str(b)))
    assert len(_on_disk(pairs_file)) == 2


def test_add_pair_refuses_a_system_folder_and_writes_nothing(config_dir, pairs_file, session):
    bad = r"C:\Windows" if sys.platform == "win32" else "/etc"
    persistence.add_pair(_pair(1, bad))
    assert not pairs_file.exists(), "a rejected pair must not create the file"
    assert session.toasts, "the user must be told why nothing happened"
    assert 'sync_pairs' not in session.session_state


def test_add_pairs_batch_adds_all_of_them(config_dir, pairs_file, session, tmp_path):
    folders = []
    for i in range(3):
        d = tmp_path / f"c{i}"
        d.mkdir()
        folders.append(str(d))
    persistence.add_pairs_batch([_pair(i, f) for i, f in enumerate(folders)])
    assert len(_on_disk(pairs_file)) == 3


@pytest.mark.parametrize("bad_first", [False, True], ids=["good-first", "bad-first"])
def test_a_batch_keeps_the_good_pairs_and_drops_only_the_bad(
        config_dir, pairs_file, session, tmp_path, bad_first):
    """Partial acceptance, and it must not depend on ORDER.

    Rejecting the whole batch because one folder is bad would lose the user's
    other selections with no way to tell which failed. The bad-first case is
    the one that matters: with the good pair first, an implementation that
    aborts on the first rejection still leaves it appended and looks correct.
    """
    bad = r"C:\Windows" if sys.platform == "win32" else "/etc"
    good = tmp_path / "ok"
    good.mkdir()
    batch = [_pair(2, bad), _pair(1, str(good))] if bad_first \
        else [_pair(1, str(good)), _pair(2, bad)]
    persistence.add_pairs_batch(batch)
    disk = _on_disk(pairs_file)
    assert [p["course_id"] for p in disk] == [1], \
        "the valid pair must be saved regardless of where the bad one sits"
    assert session.toasts and "1" in session.toasts[0][0]


def test_a_batch_is_one_atomic_write(config_dir, session, tmp_path, monkeypatch):
    """N pairs must cost ONE read-modify-write, not N. The hub adds a whole
    saved group at once, and N writes is N chances to be interrupted."""
    calls = []
    real = helpers.atomic_update_sync_pairs
    monkeypatch.setattr(persistence, "atomic_update_sync_pairs",
                        lambda m: (calls.append(1), real(m))[1])
    folders = []
    for i in range(4):
        d = tmp_path / f"d{i}"
        d.mkdir()
        folders.append(str(d))
    persistence.add_pairs_batch([_pair(i, f) for i, f in enumerate(folders)])
    assert len(calls) == 1


def test_a_batch_deduplicates_against_what_is_already_saved(config_dir, pairs_file, session, tmp_path):
    persistence.add_pair(_pair(1, str(tmp_path)))
    persistence.add_pairs_batch([_pair(1, str(tmp_path)), _pair(2, str(tmp_path))])
    assert sorted(p["course_id"] for p in _on_disk(pairs_file)) == [1, 2]


# ═══════════════════════════════════════════════════════════════════════════
# Update
# ═══════════════════════════════════════════════════════════════════════════

def test_update_by_signature_replaces_only_the_match(config_dir, pairs_file, session, tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    pairs_file.write_text(json.dumps([_pair(1, a), _pair(2, b)]), encoding="utf-8")
    persistence.update_pair_by_signature(
        {"course_id": 1, "local_folder": a}, _pair(1, a, name="Renamed"))
    disk = _on_disk(pairs_file)
    assert disk[0]["course_name"] == "Renamed"
    assert disk[1] == _pair(2, b), "the untouched pair must be byte-identical"


def test_update_with_no_match_changes_nothing(config_dir, pairs_file, session):
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")
    persistence.update_pair_by_signature(
        {"course_id": 99, "local_folder": "/nope"}, _pair(99, "/nope"))
    assert _on_disk(pairs_file) == [_pair(1, "/a")], \
        "a non-matching update must not append"


def test_update_by_signature_can_repoint_a_pair_to_a_new_folder(config_dir, pairs_file, session):
    """This is Edit Pair. Today's daily list reconciles against the result, so
    the pair must be REPLACED, never duplicated."""
    pairs_file.write_text(json.dumps([_pair(1, "/old")]), encoding="utf-8")
    persistence.update_pair_by_signature(
        {"course_id": 1, "local_folder": "/old"}, _pair(1, "/new"))
    assert _on_disk(pairs_file) == [_pair(1, "/new")]


def test_last_synced_batch_updates_the_right_rows(config_dir, pairs_file, session):
    pairs_file.write_text(
        json.dumps([_pair(1, "/a"), _pair(2, "/b"), _pair(3, "/c")]),
        encoding="utf-8")
    persistence.update_last_synced_batch([(1, "/a", "T1"), (3, "/c", "T3")])
    disk = {p["course_id"]: p.get("last_synced") for p in _on_disk(pairs_file)}
    assert disk == {1: "T1", 2: None, 3: "T3"}


def test_last_synced_ignores_a_pair_that_no_longer_exists(config_dir, pairs_file, session):
    """A sync can finish after the user deleted the pair. Recreating it here
    would resurrect a pair they removed on purpose."""
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")
    persistence.update_last_synced_batch([(2, "/gone", "T")])
    assert _on_disk(pairs_file) == [_pair(1, "/a")]


def test_last_synced_matches_on_folder_too_not_just_course(config_dir, pairs_file, session):
    """The same course in two folders must not have both stamped by one run."""
    pairs_file.write_text(json.dumps([_pair(1, "/a"), _pair(1, "/b")]),
                          encoding="utf-8")
    persistence.update_last_synced_batch([(1, "/b", "T")])
    disk = {p["local_folder"]: p.get("last_synced") for p in _on_disk(pairs_file)}
    assert disk == {"/a": None, "/b": "T"}


# ── the session list is stamped, never REPLACED ──────────────────────────────
#
# update_last_synced_batch is the one mutator called by the sync ENGINE rather
# than by the Sync page's CRUD, so it is the only one that can run while
# st.session_state['sync_pairs'] is something other than the contents of
# canvas_sync_pairs.json. The Today dashboard is exactly that case: its pair
# list is a curated subset published from today_dashboard.json and never written
# to the pairs file at all.

def test_last_synced_does_not_replace_the_session_list_with_the_file(
        config_dir, pairs_file, session):
    """The 2026-07-31 frozen-build hang, at its source.

    A Today Quick Sync runs with a curated ``sync_pairs`` that is NOT in
    canvas_sync_pairs.json. Assigning the persisted list over it wiped the
    running sync's own pair list the moment it finished - and for a user who
    only ever used Saved Groups & Pairs the file is ``[]``, so ``sync_pairs``
    became empty and render_sync_step4 stranded a completed 203-file sync on
    "No course folders found".
    """
    pairs_file.write_text("[]", encoding="utf-8")
    today_pairs = [_pair(48018, "C:/dl/Makro"), _pair(43660, "C:/dl/Org")]
    session.session_state['sync_pairs'] = today_pairs

    persistence.update_last_synced_batch([(48018, "C:/dl/Makro", "T1")])

    assert session.session_state['sync_pairs'], \
        "the running sync's pair list was wiped by its own completion"
    assert [p["course_id"] for p in session.session_state['sync_pairs']] \
        == [48018, 43660]


def test_last_synced_stamps_the_session_list_in_place(config_dir, pairs_file, session):
    """Not replacing it is only half the contract - the timestamps the Sync page
    renders come from the SESSION list, so they must land there too."""
    pairs_file.write_text(json.dumps([_pair(1, "/a"), _pair(2, "/b")]),
                          encoding="utf-8")
    session.session_state['sync_pairs'] = [_pair(1, "/a"), _pair(2, "/b")]

    persistence.update_last_synced_batch([(1, "/a", "T1")])

    in_session = {p["course_id"]: p.get("last_synced")
                  for p in session.session_state['sync_pairs']}
    on_disk = {p["course_id"]: p.get("last_synced") for p in _on_disk(pairs_file)}
    assert in_session == {1: "T1", 2: None}
    assert in_session == on_disk, "the two stamps drifted apart"


def test_last_synced_survives_an_absent_or_odd_session_list(config_dir, pairs_file, session):
    """It runs at the very end of a sync, where raising would lose the run's
    history write. No sync_pairs key at all is a real state (the engine can
    outlive a cleanup), and so is a non-list left by something else."""
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")

    persistence.update_last_synced_batch([(1, "/a", "T1")])          # key absent
    session.session_state['sync_pairs'] = None
    persistence.update_last_synced_batch([(1, "/a", "T2")])          # not a list

    assert _on_disk(pairs_file)[0]["last_synced"] == "T2"


# ═══════════════════════════════════════════════════════════════════════════
# Delete
# ═══════════════════════════════════════════════════════════════════════════

def test_remove_takes_out_only_the_named_pair(config_dir, pairs_file, session):
    pairs_file.write_text(json.dumps([_pair(1, "/a"), _pair(2, "/b")]),
                          encoding="utf-8")
    persistence.remove_pairs_by_signature([{"course_id": 1, "local_folder": "/a"}])
    assert _on_disk(pairs_file) == [_pair(2, "/b")]


def test_remove_handles_several_signatures_at_once(config_dir, pairs_file, session):
    pairs_file.write_text(
        json.dumps([_pair(1, "/a"), _pair(2, "/b"), _pair(3, "/c")]),
        encoding="utf-8")
    persistence.remove_pairs_by_signature([
        {"course_id": 1, "local_folder": "/a"},
        {"course_id": 3, "local_folder": "/c"},
    ])
    assert [p["course_id"] for p in _on_disk(pairs_file)] == [2]


def test_remove_needs_BOTH_course_and_folder_to_match(config_dir, pairs_file, session):
    """Matching on course alone would delete the same course's other pair -
    silent data loss for anyone syncing one course to two places."""
    pairs_file.write_text(json.dumps([_pair(1, "/a"), _pair(1, "/b")]),
                          encoding="utf-8")
    persistence.remove_pairs_by_signature([{"course_id": 1, "local_folder": "/a"}])
    assert [p["local_folder"] for p in _on_disk(pairs_file)] == ["/b"]


def test_removing_something_absent_is_a_no_op(config_dir, pairs_file, session):
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")
    persistence.remove_pairs_by_signature([{"course_id": 9, "local_folder": "/x"}])
    assert _on_disk(pairs_file) == [_pair(1, "/a")]


def test_removing_everything_leaves_an_empty_list_not_a_broken_file(config_dir, pairs_file, session):
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")
    persistence.remove_pairs_by_signature([{"course_id": 1, "local_folder": "/a"}])
    assert _on_disk(pairs_file) == []
    assert helpers.load_sync_pairs() == []


# ═══════════════════════════════════════════════════════════════════════════
# Session load
# ═══════════════════════════════════════════════════════════════════════════

def test_load_persistent_pairs_populates_session_state(config_dir, pairs_file, session):
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")
    persistence.load_persistent_pairs()
    assert session.session_state['sync_pairs'] == [_pair(1, "/a")]
    assert session.session_state['sync_pairs_loaded'] is True


def test_a_cleared_selection_is_not_resurrected_on_the_next_rerun(config_dir, pairs_file, session):
    """The ``sync_pairs_loaded`` sentinel is load-bearing, and this is the ONLY
    case that proves it.

    ``load_persistent_pairs`` also refuses to overwrite a non-empty
    ``sync_pairs``, which masks the sentinel in every ordinary scenario - the
    obvious "load twice, second one must not win" test passes with the sentinel
    deleted. The gap is an EMPTY in-session list: it is falsy, so without the
    sentinel the next rerun reloads from disk and every pair the user just
    removed comes back.
    """
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")
    persistence.load_persistent_pairs()
    assert session.session_state['sync_pairs'] == [_pair(1, "/a")]

    # The user clears the list in-session (disk write still pending / failed).
    session.session_state['sync_pairs'] = []
    persistence.load_persistent_pairs()          # the next rerun
    assert session.session_state['sync_pairs'] == [], \
        "an emptied selection was resurrected from disk on the next rerun"


def test_a_second_load_never_replaces_live_session_pairs(config_dir, pairs_file, session):
    """The other half: pairs edited in-session outrank whatever is on disk."""
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")
    persistence.load_persistent_pairs()
    pairs_file.write_text(json.dumps([_pair(2, "/b")]), encoding="utf-8")
    persistence.load_persistent_pairs()
    assert session.session_state['sync_pairs'] == [_pair(1, "/a")]


def test_load_does_not_overwrite_pairs_already_in_session(config_dir, pairs_file, session):
    session.session_state['sync_pairs'] = [_pair(7, "/live")]
    pairs_file.write_text(json.dumps([_pair(1, "/a")]), encoding="utf-8")
    persistence.load_persistent_pairs()
    assert session.session_state['sync_pairs'] == [_pair(7, "/live")]


def test_load_with_no_file_still_marks_itself_done(config_dir, session):
    """Otherwise every rerun re-hits the disk looking for a file that is not
    there, on a first-run install."""
    persistence.load_persistent_pairs()
    assert session.session_state['sync_pairs_loaded'] is True
