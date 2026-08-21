"""Guards for the audit's snapshot store and its parallel lane scheduler.

Both exist to make the suite fast, and both fail SILENTLY when they are wrong:
a snapshot with a torn manifest still restores and still syncs - it just
mis-classifies files, and every scenario derived from it looks healthy while
proving nothing. A lane scheduler that lets two Office rows run together does
not raise; Word and Excel are driven through a machine-wide COM object, so the
two runs steer one application and hang.

So the things pinned here are the ones with no natural error:

* the manifest is CHECKPOINTED, not byte-copied (a live WAL would be lost)
* the extended-length path prefix never reaches the SQLite URI - it did, and
  turned every capture into a silent byte-copy fallback
* no job is dropped, duplicated, or given a port another lane already has
* office and gpu rows never end up in two lanes at once
* a failed row is retried on resume; a successful one is not repeated
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import parallel, snapshot  # noqa: E402
from tests.audit.harness.parallel import Job, classify, partition  # noqa: E402


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path, monkeypatch):
    root = tmp_path / "_snapshots"
    monkeypatch.setattr(snapshot, "SNAPSHOT_ROOT", root)
    return root


@pytest.fixture()
def course(tmp_path):
    """A folder shaped like one the app produced, manifest and all."""
    folder = tmp_path / "Some Course (LA E25 X)"
    (folder / "Week 1" / "deep" / "deeper").mkdir(parents=True)
    (folder / "Week 1" / "slides.pdf").write_bytes(b"pdf" * 100)
    (folder / "Week 1" / "deep" / "deeper" / "extracted.txt").write_text(
        "from an archive", encoding="utf-8")
    (folder / "notes.md").write_text("# notes\nunicode: æøå", encoding="utf-8")

    db = folder / ".canvas_sync.db"
    con = sqlite3.connect(str(db))
    con.executescript("""
        CREATE TABLE sync_manifest (canvas_file_id INTEGER PRIMARY KEY,
            canvas_filename TEXT, local_path TEXT, canvas_updated_at TEXT,
            downloaded_at TEXT, original_size INTEGER, is_ignored INTEGER DEFAULT 0,
            original_md5 TEXT DEFAULT "", content_sig TEXT DEFAULT "");
        CREATE TABLE sync_metadata (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE panopto_manifest (video_id TEXT, kind TEXT, local_path TEXT,
            title TEXT, downloaded_at TEXT, PRIMARY KEY (video_id, kind));
    """)
    con.executemany(
        "INSERT INTO sync_manifest (canvas_file_id, canvas_filename, local_path) "
        "VALUES (?, ?, ?)",
        [(1, "slides.pdf", "Week 1/slides.pdf"), (2, "notes.md", "notes.md")])
    con.executemany("INSERT INTO sync_metadata VALUES (?, ?)",
                    [("course_id", "45899"), ("course_name", "Some Course")])
    con.commit()
    con.close()
    return folder


# --------------------------------------------------------------------------
# snapshot: round trip
# --------------------------------------------------------------------------

def test_capture_then_restore_reproduces_the_tree(store, course, tmp_path):
    snapshot.capture(course, "s1", course_id=45899)
    out = snapshot.restore("s1", tmp_path / "dest")
    dest = Path(out["path"])

    assert out["verify"]["ok"], out["verify"]
    assert (dest / "Week 1" / "slides.pdf").read_bytes() == b"pdf" * 100
    assert (dest / "notes.md").read_text(encoding="utf-8").endswith("æøå")
    assert (dest / "Week 1" / "deep" / "deeper" / "extracted.txt").is_file()


def test_restore_can_rename_the_folder(store, course, tmp_path):
    snapshot.capture(course, "s1")
    out = snapshot.restore("s1", tmp_path / "dest", folder_name="Renamed Course")
    assert Path(out["path"]).name == "Renamed Course"
    assert (Path(out["path"]) / "notes.md").is_file()


def test_restored_manifest_is_readable_and_intact(store, course, tmp_path):
    snapshot.capture(course, "s1")
    dest = Path(snapshot.restore("s1", tmp_path / "dest")["path"])
    con = sqlite3.connect(str(dest / ".canvas_sync.db"))
    try:
        assert con.execute("SELECT COUNT(*) FROM sync_manifest").fetchone()[0] == 2
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def test_manifest_paths_are_relative_so_a_snapshot_is_portable(store, course, tmp_path):
    """The premise the whole store rests on.

    ``sync_manifest.local_path`` is relative to the sync root, so a folder
    captured at one path and restored at another needs no rewriting. If this
    ever stops being true, every restored scenario silently reasons about files
    that are not where the manifest says.
    """
    snapshot.capture(course, "s1")
    dest = Path(snapshot.restore("s1", tmp_path / "somewhere" / "else")["path"])
    con = sqlite3.connect(str(dest / ".canvas_sync.db"))
    try:
        rows = [r[0] for r in con.execute("SELECT local_path FROM sync_manifest")]
    finally:
        con.close()
    for lp in rows:
        assert not os.path.isabs(lp), f"manifest holds an absolute path: {lp}"
        assert (dest / lp).is_file(), f"{lp} does not resolve under the restore"


# --------------------------------------------------------------------------
# snapshot: the manifest is checkpointed, not copied
# --------------------------------------------------------------------------

def test_manifest_is_captured_through_the_backup_api(store, course):
    """A byte copy would be reported; a real capture reports rows + integrity."""
    res = snapshot.capture(course, "s1")
    assert res["manifest_rows"] == 2
    assert res["manifest_integrity"] == "ok"
    assert "MANIFEST_WARNING" not in res, res.get("MANIFEST_WARNING")


def test_uncommitted_wal_data_survives_capture(store, course, tmp_path):
    """The reason ``backup()`` is used instead of copying the file.

    With WAL journalling the newest rows can live entirely in the ``-wal``
    sidecar. Copying only the ``.db`` would drop them, and the snapshot would
    describe a folder state that never existed.
    """
    con = sqlite3.connect(str(course / ".canvas_sync.db"))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("INSERT INTO sync_manifest (canvas_file_id, canvas_filename, "
                "local_path) VALUES (99, 'late.pdf', 'late.pdf')")
    con.commit()
    try:
        res = snapshot.capture(course, "s1")
        assert res["manifest_rows"] == 3, "a WAL-resident row was lost"
    finally:
        con.close()


def test_wal_sidecars_are_not_copied(store, course, tmp_path):
    con = sqlite3.connect(str(course / ".canvas_sync.db"))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("INSERT INTO sync_manifest (canvas_file_id) VALUES (7)")
    con.commit()
    try:
        snapshot.capture(course, "s1")
    finally:
        con.close()
    payload = store / "s1" / "payload" / course.name
    assert not list(payload.glob(".canvas_sync.db-*")), \
        "a -wal/-shm sidecar was copied; it describes history the copy lacks"
    meta = snapshot.read_meta("s1")
    assert not [k for k in meta["inventory"] if k.startswith(".canvas_sync.db-")]


def test_missing_manifest_is_reported_not_silently_ignored(store, tmp_path):
    folder = tmp_path / "No Manifest"
    folder.mkdir()
    (folder / "a.txt").write_text("x", encoding="utf-8")
    res = snapshot.capture(folder, "s1")
    assert "MANIFEST_WARNING" in res


@pytest.mark.skipif(os.name != "nt", reason="extended-length paths are Windows-only")
def test_extended_length_prefix_is_stripped_before_uri_use():
    """The bug that made every capture fall back to a byte copy.

    ``os.walk`` yields roots in the form it was given, so a ``\\\\?\\`` walk
    produces ``\\\\?\\G:\\...`` paths. Turned into a URI that reads as
    ``file://?/G:/...`` and SQLite rejects the ``?`` authority - reported, not
    raised, so the fallback engaged silently.
    """
    plain = snapshot._unlp("\\\\?\\G:\\some\\path\\.canvas_sync.db")
    assert str(plain) == "G:\\some\\path\\.canvas_sync.db"
    assert "?" not in plain.as_posix()
    assert snapshot._unlp("\\\\?\\UNC\\server\\share\\f") == Path("\\\\server\\share\\f")
    assert snapshot._unlp("G:\\already\\plain") == Path("G:\\already\\plain")


# --------------------------------------------------------------------------
# snapshot: protection and verification
# --------------------------------------------------------------------------

@pytest.mark.skipif(os.name != "nt", reason="read-only attribute check is Windows-specific")
def test_golden_copy_is_read_only_and_the_restore_is_not(store, course, tmp_path):
    """A silently-overwritten snapshot poisons every run derived from it."""
    snapshot.capture(course, "s1")
    golden = store / "s1" / "payload" / course.name / "notes.md"
    with pytest.raises(PermissionError):
        golden.write_text("tampered", encoding="utf-8")

    dest = Path(snapshot.restore("s1", tmp_path / "dest")["path"])
    (dest / "notes.md").write_text("the app must be able to write here",
                                   encoding="utf-8")


def test_capture_refuses_to_clobber_without_overwrite(store, course):
    snapshot.capture(course, "s1")
    with pytest.raises(SystemExit):
        snapshot.capture(course, "s1")
    assert snapshot.capture(course, "s1", overwrite=True)["name"] == "s1"


def test_verify_catches_a_missing_file(store, course, tmp_path):
    snapshot.capture(course, "s1")
    dest = Path(snapshot.restore("s1", tmp_path / "dest", verify=False)["path"])
    (dest / "notes.md").unlink()
    v = snapshot.verify_restore("s1", dest)
    assert not v["ok"] and "notes.md" in v["missing"]


def test_verify_catches_a_size_change_and_an_extra_file(store, course, tmp_path):
    snapshot.capture(course, "s1")
    dest = Path(snapshot.restore("s1", tmp_path / "dest", verify=False)["path"])
    (dest / "notes.md").write_text("much longer content than before" * 20,
                                   encoding="utf-8")
    (dest / "stray.txt").write_text("not in the snapshot", encoding="utf-8")
    v = snapshot.verify_restore("s1", dest)
    assert not v["ok"]
    assert [w["path"] for w in v["size_mismatch"]] == ["notes.md"]
    assert "stray.txt" in v["extra"]


def test_deep_capture_records_hashes(store, course):
    snapshot.capture(course, "s1", deep=True)
    inv = snapshot.read_meta("s1")["inventory"]
    assert all("md5" in v for k, v in inv.items() if not v.get("db"))


def test_list_and_drop(store, course):
    snapshot.capture(course, "s1", course_id=45899)
    snapshot.capture(course, "s2", course_id=43667)
    names = {s["name"] for s in snapshot.list_snapshots()}
    assert names == {"s1", "s2"}
    snapshot.drop("s1")
    assert {s["name"] for s in snapshot.list_snapshots()} == {"s2"}


def test_restoring_an_unknown_snapshot_fails_loudly(store, tmp_path):
    with pytest.raises(SystemExit):
        snapshot.restore("nope", tmp_path)


# --------------------------------------------------------------------------
# parallel: lane classes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("factor", parallel.OFFICE_FACTORS)
def test_office_converters_claim_the_office_lane(factor):
    assert classify({factor: True}) == "office"


@pytest.mark.parametrize("factor", parallel.GPU_FACTORS)
def test_transcription_claims_the_gpu_lane(factor):
    assert classify({factor: True}) == "gpu"


def test_gpu_outranks_office_when_a_row_needs_both():
    """One lane can only serialise one resource, so the scarcer one wins.

    The GPU row is also an Office row here; putting it in the office lane would
    let a second lane's transcription run alongside it, which is the failure
    that segfaults rather than erroring.
    """
    assert classify({"convert_excel": True, "pan_out_txt": True}) == "gpu"


def test_a_row_with_nothing_exclusive_is_free():
    assert classify({"convert_zip": True, "dl_quizzes": True}) == "free"
    assert classify({}) == "free"


# --------------------------------------------------------------------------
# parallel: partitioning
# --------------------------------------------------------------------------

def _jobs(specs):
    return [Job(id=f"m{i:03d}", kind="download", course_id=1, config=c)
            for i, c in enumerate(specs)]


def _all_ids(parts):
    return [j.id for d in parts for j in d["jobs"]]


@pytest.mark.parametrize("lanes", [1, 2, 3, 4, 8])
def test_every_job_is_placed_exactly_once(lanes):
    jobs = _jobs([{}, {"convert_excel": True}, {"pan_out_txt": True},
                  {"convert_zip": True}, {"convert_word": True},
                  {"pan_out_srt": True}, {}, {"convert_code": True}])
    ids = _all_ids(partition(jobs, lanes))
    assert sorted(ids) == sorted(j.id for j in jobs)
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("lanes", [1, 2, 3, 4, 8])
def test_ports_never_collide(lanes):
    parts = partition(_jobs([{}, {"convert_excel": True}, {"pan_out_txt": True},
                             {}, {}]), lanes)
    ports = [d["app_port"] for d in parts] + [d["cdp_port"] for d in parts]
    assert len(set(ports)) == len(ports)
    # App and CDP bands must not overlap either - a Chrome on Streamlit's port
    # would health-check green and serve nothing.
    assert not ({d["app_port"] for d in parts} & {d["cdp_port"] for d in parts})


@pytest.mark.parametrize("cls,factor", [("office", "convert_excel"),
                                        ("gpu", "pan_out_txt")])
def test_a_serial_class_is_never_split_across_lanes(cls, factor):
    """The whole point of the lane classes.

    Two Office rows in two lanes are two threads driving one COM Application.
    Two transcriptions are two processes on one GPU.
    """
    jobs = _jobs([{factor: True}] * 5 + [{}] * 6)
    for lanes in (1, 2, 3, 4, 6):
        parts = partition(jobs, lanes)
        holders = [d["lane"] for d in parts
                   if any(j.lane_class == cls for j in d["jobs"])]
        assert len(holders) == 1, f"{cls} rows spread over {holders}"


def test_office_and_gpu_share_a_lane_when_there_are_not_enough():
    """Sharing is safe; splitting is not. With two lanes, one must hold both."""
    jobs = _jobs([{"convert_excel": True}, {"pan_out_txt": True}] + [{}] * 4)
    parts = partition(jobs, 2)
    assert len(parts) == 2
    serial = [d for d in parts if d["serial"]]
    assert len(serial) == 1
    classes = {j.lane_class for j in serial[0]["jobs"]}
    assert classes == {"office", "gpu"}


def test_free_work_always_gets_a_lane():
    """Reserving every lane for the serial classes would stall the bulk."""
    jobs = _jobs([{"convert_excel": True}, {"pan_out_txt": True}] + [{}] * 4)
    for lanes in (2, 3, 4):
        parts = partition(jobs, lanes)
        assert any(not d["serial"] for d in parts) or len(parts) == 1


def test_a_run_list_with_only_office_rows_collapses_to_one_lane():
    parts = partition(_jobs([{"convert_word": True}] * 6), 4)
    assert len(parts) == 1 and parts[0]["serial"]


def test_a_single_lane_is_reported_as_serial():
    parts = partition(_jobs([{}, {}, {}]), 1)
    assert len(parts) == 1 and parts[0]["serial"] is True


def test_free_rows_are_spread_evenly():
    parts = partition(_jobs([{}] * 8), 4)
    assert sorted(d["count"] for d in parts) == [2, 2, 2, 2]


def test_partition_is_deterministic():
    """A run list that reshuffles cannot be compared against its own history."""
    jobs = _jobs([{}, {"convert_excel": True}, {"pan_out_srt": True}] * 4)
    a = [(d["lane"], [j.id for j in d["jobs"]]) for d in partition(jobs, 4)]
    b = [(d["lane"], [j.id for j in d["jobs"]]) for d in partition(jobs, 4)]
    assert a == b


def test_lanes_must_be_positive():
    with pytest.raises(ValueError):
        partition(_jobs([{}]), 0)


# --------------------------------------------------------------------------
# parallel: plan -> jobs
# --------------------------------------------------------------------------

def test_jobs_from_plan_drops_underscore_keys():
    plan = {"runs": [
        {"convert_zip": True, "_isolates": "convert_zip=True", "_course_id": 45899},
        {"pan_out_txt": True, "_course_id": 43660, "_isolates": "triple"},
    ]}
    jobs = parallel.jobs_from_plan(plan)
    assert [j.id for j in jobs] == ["m000", "m001"]
    assert jobs[0].config == {"convert_zip": True}
    assert jobs[0].note == "convert_zip=True"
    assert jobs[0].course_id == 45899
    assert jobs[1].lane_class == "gpu"


def test_an_unassigned_row_is_an_error_not_a_silent_drop():
    """This test used to assert the OPPOSITE, and that is how the defect
    survived: ``jobs_from_plan`` skipped a row with ``_course_id = None``, so a
    plan reporting "73 runs, 100% coverage" produced 72 jobs with nothing
    anywhere recording the difference. ``assign_courses`` now always assigns
    (see tests/test_audit_matrix_assignment.py); this is the backstop."""
    with pytest.raises(SystemExit):
        parallel.jobs_from_plan({"runs": [{"convert_zip": False,
                                           "_course_id": None}]})


def test_a_job_defaults_its_name_to_its_id():
    assert Job(id="m007", kind="download", course_id=1).name == "m007"


# --------------------------------------------------------------------------
# parallel: resumability
# --------------------------------------------------------------------------

class _RP:
    def __init__(self, root):
        self.root = Path(root)


def test_only_successful_rows_are_skipped_on_resume(tmp_path):
    """A failed row is exactly the one worth retrying."""
    rp = _RP(tmp_path)
    (tmp_path / "progress.json").write_text(json.dumps({"rows": [
        {"id": "m000", "ok": True}, {"id": "m001", "ok": False},
        {"id": "m002", "ok": True}]}), encoding="utf-8")
    assert parallel._completed(rp) == {"m000", "m002"}


def test_a_row_abandoned_mid_flight_is_not_treated_as_done(tmp_path):
    """Killed workers never write a record, so the row simply reruns."""
    rp = _RP(tmp_path)
    parallel._mark_current(rp, "m005")
    assert parallel._completed(rp) == set()
    assert parallel.progress(rp)["current"] == "m005"


def test_progress_survives_a_corrupt_file(tmp_path):
    rp = _RP(tmp_path)
    (tmp_path / "progress.json").write_text("{not json", encoding="utf-8")
    assert parallel._completed(rp) == set()
    assert parallel.progress(rp)["done"] == 0


def test_recording_a_row_clears_the_current_marker(tmp_path):
    rp = _RP(tmp_path)
    parallel._mark_current(rp, "m001")
    parallel._record(rp, {"id": "m001", "ok": True})
    p = parallel.progress(rp)
    assert p["done"] == 1 and p["failed"] == 0 and not p["current"]


def test_lane_run_ids_are_derived_from_the_parent():
    assert parallel.lane_run_id("20260728_x", "office") == "20260728_x__office"


# --------------------------------------------------------------------------
# seeding happens once, and a snapshot restore is what resets it
# --------------------------------------------------------------------------

def test_a_seeded_folder_refuses_to_be_seeded_again(store, course, tmp_path):
    """Seeding twice invalidates BOTH plans.

    The second pass reads a folder the first already rearranged, so fixtures
    land on fixtures and the plan it writes describes only its own half. Every
    category then disagrees with the screen and the disagreement reads as an
    application bug - it cost a full Phase 2 run before this guard existed.
    """
    from tests.audit.harness import seed as seeder
    (course / seeder.SEED_MARKER).write_text(
        '{"seeded_at": "2026-07-28T00:00:00", "fixture_count": 43}',
        encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        seeder.seed(course, ["new_regular"], out_path=tmp_path / "plan.json")
    assert "already seeded" in str(e.value)
    assert "snapshot restore" in str(e.value), \
        "the error must name the remedy, not just the problem"


def test_restoring_a_snapshot_clears_the_seed_marker(store, course, tmp_path):
    """Why the marker lives in the folder rather than in the run's evidence dir."""
    from tests.audit.harness import seed as seeder
    snapshot.capture(course, "s1")
    (course / seeder.SEED_MARKER).write_text("{}", encoding="utf-8")
    dest = Path(snapshot.restore("s1", tmp_path / "dest")["path"])
    assert seeder.already_seeded(dest) is None


def test_the_seed_marker_is_never_counted_as_canvas_content():
    """A finding invented by the tool looking for findings."""
    from tests.audit.harness.oracles import disk as odisk
    from tests.audit.harness import seed as seeder
    assert seeder.SEED_MARKER in odisk.APP_GENERATED
    assert "_audit_seed_plan.json" in odisk.APP_GENERATED


# --------------------------------------------------------------------------
# a snapshot must be a KNOWN starting point
# --------------------------------------------------------------------------

def test_capturing_a_folder_that_carries_the_seed_marker_is_refused(store, course):
    from tests.audit.harness import seed as seeder
    (course / seeder.SEED_MARKER).write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        snapshot.capture(course, "s1")
    assert "not a clean baseline" in str(e.value)


@pytest.mark.parametrize("fixture_name", [
    "GhostFile_0_notes.pdf",
    "zz flertydig 0.pdf",
    "zz omdøbt uden række 1.pdf",
    "decoy 0 unrelated.pdf",
    "slides - copy for exam.pdf",
])
def test_leftover_fixtures_are_detected_even_without_a_marker(store, course,
                                                              fixture_name):
    """The folder that actually poisoned a run predated the marker entirely.

    Its only evidence was the fixture filenames, so those are checked too -
    otherwise the guard would not have caught the case it exists for.
    """
    (course / "Week 1" / fixture_name).write_bytes(b"x")
    with pytest.raises(SystemExit) as e:
        snapshot.capture(course, "s1")
    assert fixture_name in str(e.value)


def test_a_mid_scenario_baseline_can_still_be_captured_deliberately(store, course):
    from tests.audit.harness import seed as seeder
    (course / seeder.SEED_MARKER).write_text("{}", encoding="utf-8")
    assert snapshot.capture(course, "s1", allow_seeded=True)["name"] == "s1"


def test_a_clean_folder_captures_without_complaint(store, course):
    assert snapshot.capture(course, "s1")["manifest_rows"] == 2


# --------------------------------------------------------------------------
# a retried row is reported by its LATEST attempt
# --------------------------------------------------------------------------
#
# `_record` appends, and a resumed run re-runs exactly the rows that failed -
# so after a successful retry the file holds both records. Counting them all
# reported the row as still failed for the rest of the run, and pushed `done`
# past the number of rows in the lane.

def test_a_recovered_row_is_no_longer_counted_as_failed(tmp_path):
    rp = _RP(tmp_path)
    (tmp_path / "progress.json").write_text(json.dumps({"rows": [
        {"id": "s018", "ok": False, "error": "FlowError"},
        {"id": "s019", "ok": True},
        {"id": "s018", "ok": True},          # the retry
    ]}), encoding="utf-8")
    got = parallel.progress(rp)
    assert got["failed"] == 0, got
    assert got["done"] == 2, "each row counts once, by its latest attempt"
    assert got["retried"] == 1


def test_a_row_that_failed_again_is_still_failed(tmp_path):
    rp = _RP(tmp_path)
    (tmp_path / "progress.json").write_text(json.dumps({"rows": [
        {"id": "s018", "ok": False}, {"id": "s018", "ok": False},
    ]}), encoding="utf-8")
    got = parallel.progress(rp)
    assert got["failed"] == 1 and got["done"] == 1


def test_the_append_only_history_is_left_intact(tmp_path):
    """It is the record of what was retried; only the REPORT collapses it."""
    rp = _RP(tmp_path)
    body = {"rows": [{"id": "a", "ok": False}, {"id": "a", "ok": True}]}
    (tmp_path / "progress.json").write_text(json.dumps(body), encoding="utf-8")
    parallel.progress(rp)
    assert json.loads((tmp_path / "progress.json").read_text(encoding="utf-8")) == body


# --------------------------------------------------------------------------
# deleting a tree a live process is still letting go of
# --------------------------------------------------------------------------
#
# WinError 32 is "the file is in use", not a permission bit - `_make_writable`
# already handles read-only. A lane keeps ONE app alive across all its rows and
# that app holds `.canvas_sync.db` open, so when the next row clears the
# destination the handle is often still on its way out. Measured on sync row
# s041: the restore failed instantly on `.canvas_sync.db`, and the same row
# succeeded 24 seconds later having changed nothing. A single attempt is a coin
# flip, and the loser is a whole row.

def test_a_tree_that_frees_up_is_deleted_rather_than_failing(tmp_path, monkeypatch):
    folder = tmp_path / "course"
    folder.mkdir()
    (folder / ".canvas_sync.db").write_bytes(b"x")

    calls = {"n": 0}
    real = snapshot.shutil.rmtree

    def flaky(path, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(32, "in use")
        return real(path, **kw)

    monkeypatch.setattr(snapshot.shutil, "rmtree", flaky)
    monkeypatch.setattr(snapshot.time, "sleep", lambda *_: None)
    snapshot._rmtree(folder)
    assert not folder.exists()
    assert calls["n"] == 3, "it gave up before the handle was released"


def test_a_tree_that_never_frees_up_still_raises(tmp_path, monkeypatch):
    """Retrying must not turn a real, permanent lock into silence."""
    folder = tmp_path / "course"
    folder.mkdir()
    (folder / "f.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(snapshot.shutil, "rmtree",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError(32, "in use")))
    monkeypatch.setattr(snapshot.time, "sleep", lambda *_: None)
    with pytest.raises(PermissionError):
        snapshot._rmtree(folder, attempts=3)


def test_an_unrelated_oserror_is_not_retried(tmp_path, monkeypatch):
    """Only the in-use case is a race; anything else is a real failure and
    retrying it just delays the report."""
    folder = tmp_path / "course"
    folder.mkdir()
    boom = OSError("disk on fire")
    boom.winerror = 1234
    monkeypatch.setattr(snapshot.shutil, "rmtree",
                        lambda *a, **k: (_ for _ in ()).throw(boom))
    with pytest.raises(OSError):
        snapshot._rmtree(folder)


def test_an_absent_tree_is_a_no_op(tmp_path):
    snapshot._rmtree(tmp_path / "never-existed")


# --------------------------------------------------------------------------
# parallel: a row needing BOTH resources must not let the two lanes overlap
#
# Found by the live macOS audit, 2026-08-21. `classify` answers with ONE lane
# name, which is the right answer to "where does this row live" and the wrong
# answer to "what does it touch": a row with transcription AND Office
# conversion reports "gpu", lands in the gpu lane, and then drives Office while
# the office lane is driving Office - the exact arrangement this module's
# docstring says must never happen.
#
# Measured on that run's 56-row plan: 7 of the 9 gpu rows also converted
# Office. It only escaped the clash because the gpu lane was started by hand
# after the office lane had finished; a plain `matrix launch` would have run
# them together, and the resulting -609 / -30001 PowerPoint failures read
# exactly like product defects. One such row cost a full investigation.
# --------------------------------------------------------------------------

def _lane_of(parts, job_id):
    for d in parts:
        if any(j.id == job_id for j in d["jobs"]):
            return d["lane"]
    raise AssertionError(f"{job_id} was not placed")


def test_resources_reports_every_resource_not_just_the_first():
    assert parallel.resources({"pan_out_txt": True}) == {"gpu"}
    assert parallel.resources({"convert_excel": True}) == {"office"}
    assert parallel.resources({"convert_excel": True, "pan_out_txt": True}) \
        == {"gpu", "office"}
    assert parallel.resources({}) == set()


@pytest.mark.parametrize("lanes", [2, 3, 4, 8])
def test_a_dual_need_row_forces_office_and_gpu_into_ONE_lane(lanes):
    """The office rows must not run while the dual row drives Office."""
    jobs = _jobs([
        {"convert_excel": True},                        # m000 office
        {"pan_out_txt": True},                          # m001 gpu
        {"convert_word": True, "pan_out_srt": True},    # m002 BOTH
        {},                                             # m003 free
    ])
    parts = partition(jobs, lanes)
    assert _lane_of(parts, "m000") == _lane_of(parts, "m001") == _lane_of(parts, "m002"), (
        "a dual-need row is present, so office work and gpu work can no longer "
        "be given a lane each - whichever lane holds it drives Office while the "
        "other lane is also driving Office")
    assert all(d["serial"] for d in parts
               if _lane_of(parts, "m002") == d["lane"]), \
        "the merged lane must still be serial"


@pytest.mark.parametrize("lanes", [3, 4, 8])
def test_the_quiet_direction_no_dual_row_keeps_the_lanes_separate(lanes):
    """A check that always fires is not a check.

    With no dual-need row the two resources really are independent, and merging
    them would halve the throughput of every ordinary plan for nothing.

    Three lanes minimum: at two, `test_office_and_gpu_share_a_lane_when_there_
    are_not_enough` already applies, and the pre-existing "never spend every
    lane on the serial classes" rule merges them for a different reason.
    """
    jobs = _jobs([
        {"convert_excel": True},
        {"pan_out_txt": True},
        {},
    ])
    parts = partition(jobs, lanes)
    assert _lane_of(parts, "m000") != _lane_of(parts, "m001"), (
        "office and gpu are independent here and must still get a lane each")


def test_a_dual_need_row_is_still_placed_exactly_once():
    jobs = _jobs([
        {"convert_excel": True},
        {"pan_out_txt": True},
        {"convert_word": True, "pan_out_srt": True},
        {},
    ])
    ids = _all_ids(partition(jobs, 4))
    assert sorted(ids) == sorted(j.id for j in jobs)
    assert len(ids) == len(set(ids))
