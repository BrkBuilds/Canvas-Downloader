"""One Canvas file, one fetch - the already-placed-copy claim.

The download engine reaches the same Canvas file once per phase that
references it (module walk, Files-tab Catch-All, Canvas Content attachment),
and each phase computes its own destination. Measured on course 46396: file
1784620 fetched twice, 21 seconds apart, landing as two copies under two
names - and in the flat layout the second write took over the single manifest
row, orphaning the first copy for good.

These tests pin the claim's contract:
  * identity - which ids may be compared with each other at all,
  * placement - move when the two requests share a manifest row, copy when
    they legitimately own separate rows,
  * and the failure modes, every one of which must fall through to an
    ordinary download rather than lose the file.
"""

import asyncio
import types
from pathlib import Path

import pytest

from core.canvas_logic import CanvasManager, real_canvas_file_id
from core.sync_manager import make_secondary_id, secondary_raw_id


# ── helpers ──────────────────────────────────────────────────────────────


def _file_obj(fid, name="doc.pdf", size=10):
    return types.SimpleNamespace(
        id=fid, url="https://canvas.example/files/1/download",
        filename=name, display_name=name, size=size,
        modified_at="2026-01-01T00:00:00Z", md5=None,
        content_type="application/pdf", folder_id=None,
    )


class _Manifest:
    """Minimal stand-in for SyncManager's one method the claim calls."""

    def __init__(self, root):
        self.local_path = Path(root)
        self.rows = {}

    def record_downloaded_file(self, canvas_file_id, canvas_filename,
                               local_path, canvas_updated_at, original_size,
                               local_md5="", content_sig="", clear_ignored=False):
        self.rows[canvas_file_id] = local_path
        return True


def _claim(cm, file_obj, dest, *, base, sm=None, events=None):
    def _cb(msg, progress_type=None, **kw):
        if events is not None:
            events.append((msg, progress_type, kw))

    return asyncio.run(cm._claim_placed_copy(
        file_obj, dest, sync_manager=sm, course_base_path=base,
        progress_callback=_cb if events is not None else None,
        debug_file=None, file_size_bytes=getattr(file_obj, 'size', 0)))


@pytest.fixture()
def cm():
    m = CanvasManager.__new__(CanvasManager)
    m._file_registry = {}
    return m


# ── identity: which ids describe the same FILE ───────────────────────────


def test_real_id_of_a_files_tab_file_is_itself():
    assert real_canvas_file_id(_file_obj(1784620)) == 1784620


def test_real_id_sees_through_an_attachment_synthetic():
    syn = make_secondary_id('attachment', 1784620)
    assert real_canvas_file_id(_file_obj(syn)) == 1784620


@pytest.mark.parametrize("kind", ['assignment', 'quiz', 'discussion',
                                  'announcement', 'submission', 'syllabus',
                                  'rubric', 'calendar', 'module_item'])
def test_non_attachment_synthetics_are_not_file_ids(kind):
    """An assignment id of 1784620 is not the FILE 1784620.

    Every other synthetic band re-keys an ENTITY id from a different Canvas
    namespace. Treating one as a file id would let a quiz claim an unrelated
    file's bytes - the registry must refuse to answer for them at all.
    """
    syn = make_secondary_id(kind, 1784620)
    assert real_canvas_file_id(_file_obj(syn)) is None


@pytest.mark.parametrize("bad", [None, 0, "", "abc", object()])
def test_unusable_ids_are_none_not_zero(bad):
    assert real_canvas_file_id(types.SimpleNamespace(id=bad)) is None


def test_secondary_raw_id_round_trips_every_band():
    for kind in ('attachment', 'assignment', 'quiz', 'module_item'):
        assert secondary_raw_id(make_secondary_id(kind, 4242)) == 4242


# ── placement ────────────────────────────────────────────────────────────


def test_shared_row_moves_so_no_orphan_is_left(tmp_path, cm):
    """Flat layout: the attachment keeps the file's true id.

    The analyzer resolves that one id to the attachment's prefixed name, so
    only the moved file can be described by the manifest. A second copy left
    at the old name is exactly the orphan this finding was about.
    """
    src = tmp_path / "Grupper til Klyngevejledning 1-1.pdf"
    src.write_bytes(b"x" * 10)
    dest = tmp_path / "Announcement 2026-03-01 - Grupper til Klyngevejledning 1.pdf"
    cm._file_registry[1784620] = (1784620, src)
    sm = _Manifest(tmp_path)

    got = _claim(cm, _file_obj(1784620), dest, base=tmp_path, sm=sm)

    assert got is not None
    assert dest.exists() and not src.exists(), "the old copy must not survive"
    assert sm.rows == {1784620: dest.name}, "the single row follows the file"
    assert cm._file_registry[1784620] == (1784620, dest)


def test_distinct_rows_copy_so_neither_row_dangles(tmp_path, cm):
    """Isolate layout: the attachment is re-keyed to a synthetic id.

    Here the analyzer expects BOTH a Files-tab entry and an attachment entry,
    each with its own manifest row. Moving would leave the Files-tab row
    pointing at nothing and the next sync would re-download it to the root for
    ever - so the second placement is a copy. Two files as designed, one fetch.
    """
    src = tmp_path / "notes.pdf"
    src.write_bytes(b"x" * 10)
    dest = tmp_path / "Announcements" / "Week 1" / "notes.pdf"
    cm._file_registry[1784620] = (1784620, src)
    syn = make_secondary_id('attachment', 1784620)
    sm = _Manifest(tmp_path)

    got = _claim(cm, _file_obj(syn), dest, base=tmp_path, sm=sm)

    assert got is not None
    assert src.exists(), "the Files-tab copy still has a row pointing at it"
    assert dest.read_bytes() == b"x" * 10
    assert sm.rows == {syn: "Announcements/Week 1/notes.pdf"}
    assert cm._file_registry[1784620] == (1784620, src), "the original stays the source"


def test_claim_creates_the_entity_folder(tmp_path, cm):
    src = tmp_path / "notes.pdf"
    src.write_bytes(b"x" * 10)
    dest = tmp_path / "Announcements" / "Week 1" / "notes.pdf"
    cm._file_registry[1784620] = (1784620, src)
    assert _claim(cm, _file_obj(make_secondary_id('attachment', 1784620)),
                  dest, base=tmp_path) is not None
    assert dest.parent.is_dir()


# ── progress accounting ──────────────────────────────────────────────────


def test_claim_counts_the_item_but_returns_its_bytes(tmp_path, cm):
    """'skipped', not 'download'.

    The item IS delivered, so it must be counted and must reach the run
    ledger (which is what scopes post-processing). But no bytes crossed the
    network, so its size has to leave the MB denominator - otherwise the
    counter can never reach its own total.
    """
    src = tmp_path / "notes.pdf"
    src.write_bytes(b"x" * 10)
    dest = tmp_path / "sub" / "notes.pdf"
    cm._file_registry[1784620] = (1784620, src)
    events = []

    _claim(cm, _file_obj(make_secondary_id('attachment', 1784620), size=4096),
           dest, base=tmp_path, events=events)

    assert len(events) == 1
    msg, kind, kw = events[0]
    assert kind == 'skipped'
    assert kw['file_size'] == 4096, "the denominator must shrink by the real size"
    assert Path(kw['explicit_filepath']) == dest, "post-processing scope needs the NEW path"
    assert msg == dest.name, "a nameless event writes no log line"


# ── every failure falls through to a real download ───────────────────────


def test_no_registry_entry_is_a_miss(tmp_path, cm):
    assert _claim(cm, _file_obj(1784620), tmp_path / "a.pdf", base=tmp_path) is None


def test_a_vanished_source_is_forgotten_not_claimed(tmp_path, cm):
    cm._file_registry[1784620] = (1784620, tmp_path / "gone.pdf")
    assert _claim(cm, _file_obj(1784620), tmp_path / "a.pdf", base=tmp_path) is None
    assert 1784620 not in cm._file_registry, "a stale entry must not be retried"


def test_same_path_is_left_to_the_exists_check(tmp_path, cm):
    same = tmp_path / "notes.pdf"
    same.write_bytes(b"x" * 10)
    cm._file_registry[1784620] = (1784620, same)
    assert _claim(cm, _file_obj(1784620), same, base=tmp_path) is None
    assert same.exists()


def test_another_courses_file_is_never_claimed(tmp_path, cm):
    """The registry lives on the manager, which outlives one course.

    The retry entry point does not build a fresh one, so containment is
    checked as a property rather than left to every caller to remember.
    """
    other = tmp_path / "other_course" / "notes.pdf"
    other.parent.mkdir()
    other.write_bytes(b"x" * 10)
    mine = tmp_path / "my_course"
    mine.mkdir()
    cm._file_registry[1784620] = (1784620, other)

    assert _claim(cm, _file_obj(1784620), mine / "notes.pdf", base=mine) is None
    assert other.exists() and not (mine / "notes.pdf").exists()


def test_an_unplaceable_destination_falls_back_to_downloading(tmp_path, cm, monkeypatch):
    src = tmp_path / "notes.pdf"
    src.write_bytes(b"x" * 10)
    cm._file_registry[1784620] = (1784620, src)

    def _boom(*a, **kw):
        raise PermissionError("file is open in another program")

    monkeypatch.setattr("os.replace", _boom)
    assert _claim(cm, _file_obj(1784620), tmp_path / "sub" / "notes.pdf",
                  base=tmp_path) is None
    assert src.exists(), "a failed claim must not consume the copy we have"


def test_manager_without_a_registry_never_claims(tmp_path):
    """Entry points outside a course download must be inert, not crash."""
    bare = CanvasManager.__new__(CanvasManager)
    assert _claim(bare, _file_obj(1784620), tmp_path / "a.pdf", base=tmp_path) is None


# ── the registry is only written for real file ids ───────────────────────


def test_remember_records_by_real_file_id(tmp_path, cm):
    cm._remember_placed_file(_file_obj(1784620), tmp_path / "a.pdf")
    cm._remember_placed_file(_file_obj(make_secondary_id('attachment', 99)),
                             tmp_path / "b.pdf")
    assert cm._file_registry == {1784620: (1784620, tmp_path / "a.pdf"),
                                 99: (make_secondary_id('attachment', 99), tmp_path / "b.pdf")}


def test_remember_ignores_entity_synthetics(tmp_path, cm):
    cm._remember_placed_file(_file_obj(make_secondary_id('assignment', 7)),
                             tmp_path / "a.html")
    assert cm._file_registry == {}


def test_remember_is_inert_without_a_registry(tmp_path):
    bare = CanvasManager.__new__(CanvasManager)
    bare._remember_placed_file(_file_obj(1), tmp_path / "a.pdf")  # must not raise


# ── the Catch-All's question, and the order that lets it be asked ────────


def test_catch_all_defers_when_canvas_content_owns_the_row(tmp_path, cm):
    """Flat layout: the attachment kept the file's true id.

    That id has exactly one manifest row and Canvas Content has it, so a
    second copy at the course root could never be tracked - which is exactly
    how the root copy came to be orphaned.
    """
    cm._file_registry[1784620] = (1784620, tmp_path / "Announcement X - a.pdf")
    assert cm._row_already_placed(1784620) == tmp_path / "Announcement X - a.pdf"


def test_catch_all_proceeds_when_the_attachment_holds_a_synthetic_row(tmp_path, cm):
    """Isolate layout: the Files-tab entry is its own tracked entity.

    Deferring here would leave its row pointing at nothing and the next sync
    would offer the file as new for ever.
    """
    syn = make_secondary_id('attachment', 1784620)
    cm._file_registry[1784620] = (syn, tmp_path / "Announcements" / "W1" / "a.pdf")
    assert cm._row_already_placed(1784620) is None


def test_catch_all_proceeds_for_an_unseen_file(cm):
    assert cm._row_already_placed(1784620) is None


def test_row_check_is_inert_without_a_registry():
    assert CanvasManager.__new__(CanvasManager)._row_already_placed(1) is None


def _download_course_source():
    import inspect
    from core import canvas_logic
    return inspect.getsource(canvas_logic.CanvasManager.download_course_async)


def test_canvas_content_runs_before_every_files_tab_sweep():
    """An ORDERING contract, and nothing else in the file states it.

    Whichever phase runs first computes its own destination for a file both
    want, and the second cannot know - so with a sweep first the same file was
    fetched twice and landed as two copies. Running Canvas Content ahead is
    what lets a sweep ask `_defer_to_canvas_content` at all; move the calls and
    every other guard in this file still passes while the bug returns.

    Both sweeps are checked because they are different code paths for the same
    rule: in modules mode the sweep is the Catch-All (so Canvas Content sits
    between the module walk and it), and in flat / folder-structure mode the
    sweep is the primary loop itself (so it has to go first).
    """
    src = _download_course_source()

    # Anchored on the two statements, never on them being ADJACENT: this used
    # to match the dispatch as one exact `if mode == 'flat':\n <call>` string,
    # so adding a comment line between them failed the test with
    # "substring not found" - which reads like the guard is gone rather than
    # like the source was reformatted.
    flat_call = src.index("if mode in ('flat', 'files'):")
    dispatch = src.index("if mode == 'flat':")
    assert flat_call < dispatch, (
        "in flat/files mode the primary loop IS the Files-tab sweep, so Canvas "
        "Content must claim its attachments before it runs"
    )

    modules_call = src.index("await _canvas_content_phase()", dispatch)
    catch_all = src.index("# ---- HYBRID MODE CATCH-ALL STARTED ----")
    assert modules_call < catch_all, (
        "the Catch-All must run AFTER Canvas Content, or it cannot see which "
        "files Canvas Content has already claimed"
    )


def test_canvas_content_phase_is_defined_once_and_called_three_times():
    """One body, three call sites: one per mode branch, plus the 401 fallback.

    It used to be an inline block, which is why the flat path kept the bug
    after the modules path was fixed: there was nothing to move.

    The count went 2 -> 3 on 2026-07-29 when the 401 fallback started calling
    it. That call is only safe because the phase is idempotent - see the
    run-once test below - so the number alone is no longer the invariant worth
    guarding, and this asserts both halves.
    """
    src = _download_course_source()
    assert src.count("async def _canvas_content_phase()") == 1
    assert src.count("await _canvas_content_phase()") == 3, (
        "one call per mode branch plus the 401 fallback; a fourth needs a "
        "reason, and one fewer means some path skips Canvas Content entirely"
    )


def test_canvas_content_phase_runs_at_most_once_per_course():
    """The guard that makes the 401 fallback safe.

    When the module walk raises 401 the handler retries the course as a flat
    scan. Whether Canvas Content already ran depends on WHERE the 401 surfaced:
    raised by ``get_modules()`` it has not, raised later it has. Neither caller
    can tell, so without a run-once guard both choices are wrong - skipping
    loses every announcement and assignment on a course with a hidden Modules
    tab, calling unconditionally downloads all of them twice.
    """
    src = _download_course_source()
    body_at = src.index("async def _canvas_content_phase()")
    guard_at = src.index("if _canvas_content_done:", body_at)
    set_at = src.index("_canvas_content_done.append(True)", body_at)
    settings_check = src.index("secondary_content_settings and any(", body_at)

    assert guard_at < set_at < settings_check, (
        "the run-once guard must be the FIRST thing the phase does. Behind the "
        "settings check it would never latch on a run with no Canvas Content "
        "enabled, which is harmless - but behind the download itself it would "
        "latch only on success and a failed phase would be retried by the "
        "fallback, which is the double-download this prevents"
    )


def test_the_401_fallback_runs_canvas_content_before_the_flat_sweep():
    """Same ordering rule as every other Files-tab sweep.

    The fallback calls ``_download_flat_async``, whose primary loop IS the
    sweep - so Canvas Content has to claim its attachments before it, exactly
    as the ordinary flat path does.
    """
    src = _download_course_source()
    fallback = src.index("Modules tab is hidden/unauthorized")
    phase = src.index("await _canvas_content_phase()", fallback)
    flat = src.index("await self._download_flat_async(", fallback)
    assert phase < flat, (
        "a course whose Modules tab is hidden must still get its Canvas "
        "Content, and must get it before the flat sweep reserves filenames"
    )
