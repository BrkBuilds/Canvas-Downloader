"""``canvas_sync_history.json`` is the record of every sync - one bad read must not erase it.

``SyncHistoryManager`` had the "unreadable is not empty" defect this repo has now
fixed in six other stores (``core.library``, ``core.library_migrate``,
``core.preset_manager``, ``core.today_store``, ``ui.auth`` and
``atomic_update_sync_pairs``). The sweep never reached this one.

``load_history()`` degraded EVERY failure to ``[]``, and both mutators did
``history = load_history()`` -> append/amend -> write. So one TRANSIENT read
failure - an antivirus lock, the config dir on a share that is briefly offline,
a permissions blip - replaced the whole record with the single entry being
added. Measured against the real class before the fix: **50 seeded runs became
1**.

``amend_last_entry`` was the same bug wearing a disguise: it returned ``False``
on an empty history, and its own docstring says the caller then "creates one" -
i.e. it funnelled a transient failure straight into the ``add_entry`` that does
the damage. It therefore has to know the CAUSE too, and answers ``True``
("consider it handled, change nothing") rather than ``False``.

The fix reuses ``shared.helpers.read_json_for_update`` - generalised with an
``expect`` type - instead of restating the decision here. That is the same
reasoning the primitive's own docstring gives for existing at all: a shared
decision with two implementations is a fix that lands on half the app.

These tests assert the INVARIANT ("a write never destroys the existing record")
and the CAUSE split, not any particular spelling of the guard.
"""

from __future__ import annotations

import ast
import builtins
import json
from pathlib import Path

import pytest

from core.sync_manager import SyncHistoryManager

REPO = Path(__file__).resolve().parents[1]
HISTORY_NAME = "canvas_sync_history.json"


def _seed(tmp_path: Path, n: int) -> tuple[SyncHistoryManager, Path]:
    """A manager over a history file holding *n* real-shaped past runs."""
    mgr = SyncHistoryManager(str(tmp_path))
    for i in range(n):
        mgr.add_entry({
            "timestamp": f"2026-08-{i % 28 + 1:02d}T10:00:00",
            "files_synced": i,
            "course_names": [f"Course {i}"],
        })
    path = tmp_path / HISTORY_NAME
    assert len(json.loads(path.read_text(encoding="utf-8"))) == n
    return mgr, path


@pytest.fixture
def failing_reads(monkeypatch):
    """Make reads of ONE path raise, while writes to it still succeed.

    A test for a transient READ failure must not break the write as well -
    putting a directory where the file goes (the obvious shortcut) fails
    ``os.replace`` too, so the guard could be deleted with the test still green.
    That exact mistake let four mutants survive in
    ``tests/test_settings_coownership.py``; patch ``open`` for reads of the one
    path instead.
    """
    real_open = builtins.open

    def install(path, exc):
        def flaky(file, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if str(file) == str(path) and "r" in str(mode) and "+" not in str(mode):
                raise exc
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", flaky)

    return install


# --- The defect: a transient read must never destroy the record -------------

@pytest.mark.parametrize("exc", [
    OSError(35, "Resource temporarily unavailable"),
    OSError(13, "Permission denied"),
    OSError(5, "Input/output error"),
])
def test_a_transient_read_failure_does_not_wipe_the_history(tmp_path, failing_reads, exc):
    mgr, path = _seed(tmp_path, 50)
    before = path.read_text(encoding="utf-8")

    failing_reads(path, exc)
    mgr.add_entry({"timestamp": "2026-08-11T12:00:00", "files_synced": 999})

    assert path.read_text(encoding="utf-8") == before, (
        "a transient read failure must leave the file byte-identical - the run "
        "goes unrecorded, which is recoverable; a wiped record is not")


def test_the_run_being_added_is_dropped_rather_than_replacing_everything(tmp_path, failing_reads):
    """The explicit statement of the trade: lose one entry, never the other 50."""
    mgr, path = _seed(tmp_path, 50)
    failing_reads(path, OSError(35, "Resource temporarily unavailable"))
    mgr.add_entry({"timestamp": "new", "files_synced": 999})

    entries = json.loads(path.read_text(encoding="utf-8"))
    assert len(entries) == 50
    assert all(e["files_synced"] != 999 for e in entries)


def test_amend_does_not_wipe_the_history_either(tmp_path, failing_reads):
    mgr, path = _seed(tmp_path, 50)
    before = path.read_text(encoding="utf-8")

    failing_reads(path, OSError(13, "Permission denied"))
    mgr.amend_last_entry(add_files_synced=5)

    assert path.read_text(encoding="utf-8") == before


def test_amend_reports_handled_so_the_caller_does_not_fall_into_add_entry(tmp_path, failing_reads):
    """``False`` means "no entry to amend, go create one" - which is the very
    write that must not happen. On a transient failure it must answer True."""
    mgr, path = _seed(tmp_path, 50)
    failing_reads(path, OSError(35, "Resource temporarily unavailable"))

    assert mgr.amend_last_entry(add_files_synced=5) is True


def test_a_genuinely_empty_history_still_answers_false_to_amend(tmp_path):
    """The transient guard must not swallow the real "nothing to amend" case -
    that answer is what makes the caller create the entry."""
    mgr = SyncHistoryManager(str(tmp_path))
    assert mgr.amend_last_entry(add_files_synced=5) is False


# --- Damaged content is a DIFFERENT cause and must still recover ------------

@pytest.mark.parametrize("payload, why", [
    (b"\xff\xfe not utf-8 at all", "UnicodeDecodeError - a SIBLING of JSONDecodeError"),
    (b"{ this is not json", "malformed JSON"),
    (b'{"not": "a list"}', "wrong top-level shape - callers iterate it"),
    (b'"a bare string"', "wrong top-level shape"),
])
def test_damaged_content_is_quarantined_and_writing_proceeds(tmp_path, payload, why):
    mgr, path = _seed(tmp_path, 3)
    path.write_bytes(payload)

    mgr.add_entry({"timestamp": "fresh", "files_synced": 1})

    entries = json.loads(path.read_text(encoding="utf-8"))
    assert entries and entries[-1]["files_synced"] == 1, (
        f"{why}: the file cannot be preserved in place, so the user must get a "
        "working history back rather than a permanently unwritable one")
    assert list(path.parent.glob("*corrupt*")), (
        "the damaged bytes must survive on disk, not be silently discarded")


def test_the_first_quarantine_is_never_overwritten(tmp_path):
    mgr, path = _seed(tmp_path, 2)
    path.write_bytes(b"broken once")
    mgr.add_entry({"timestamp": "a", "files_synced": 1})
    path.write_bytes(b"broken twice")
    mgr.add_entry({"timestamp": "b", "files_synced": 2})

    assert len(list(path.parent.glob("*corrupt*"))) == 2


# --- Normal operation is unchanged ------------------------------------------

def test_normal_appends_still_work(tmp_path):
    mgr, path = _seed(tmp_path, 3)
    mgr.add_entry({"timestamp": "n", "files_synced": 7})
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 4


def test_a_fresh_install_can_record_its_first_run(tmp_path):
    mgr = SyncHistoryManager(str(tmp_path))
    mgr.add_entry({"timestamp": "first", "files_synced": 1})
    assert len(json.loads((tmp_path / HISTORY_NAME).read_text(encoding="utf-8"))) == 1


def test_normal_amend_still_merges(tmp_path):
    mgr, path = _seed(tmp_path, 2)
    assert mgr.amend_last_entry(add_files_synced=10) is True
    assert json.loads(path.read_text(encoding="utf-8"))[-1]["files_synced"] == 11


def test_retention_still_trims(tmp_path):
    mgr, path = _seed(tmp_path, 3)
    for i in range(60):
        mgr.add_entry({"timestamp": f"x{i}", "files_synced": i})
    assert len(json.loads(path.read_text(encoding="utf-8"))) <= 50


# --- The display readers stay total -----------------------------------------

def test_display_read_never_raises_and_reports_empty(tmp_path, failing_reads):
    """Two DISPLAY surfaces call load_history on every render. It must not
    raise - but it must also not be the read a mutator uses."""
    mgr, path = _seed(tmp_path, 5)
    failing_reads(path, OSError(35, "unavailable"))
    assert mgr.load_history() == []


def test_display_read_logs_rather_than_swallowing(tmp_path, failing_reads, caplog):
    """Rendering [] tells the user "you have no sync history" - the same
    confusion this repo already fixed once in _render_sync_history."""
    mgr, path = _seed(tmp_path, 5)
    failing_reads(path, OSError(35, "unavailable"))
    with caplog.at_level("WARNING"):
        mgr.load_history()
    assert any("sync history" in r.message.lower() for r in caplog.records)


# --- Structural: the decision is not restated -------------------------------

def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse((REPO / "core" / "sync_manager.py").read_text(encoding="utf-8"))
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "SyncHistoryManager":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == name:
                    return fn
    raise AssertionError(f"SyncHistoryManager.{name} not found")


@pytest.mark.parametrize("mutator", ["add_entry", "amend_last_entry"])
def test_no_mutator_reads_through_the_display_loader(mutator):
    """The whole defect in one property: a read-modify-write must not use the
    reader that cannot tell "empty" from "unreadable"."""
    calls = {
        n.func.attr for n in ast.walk(_method(mutator))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "load_history" not in calls, (
        f"{mutator} must read through _load_for_update, which reports the CAUSE")
    assert "_load_for_update" in calls


def test_the_update_read_delegates_to_the_one_shared_implementation():
    """Not a style rule: ``make_long_path`` had a second copy in this very file
    and the fix reached none of the 26 manifest call sites."""
    src = ast.unparse(_method("_load_for_update"))
    assert "read_json_for_update" in src, (
        "the cause split must reuse shared.helpers.read_json_for_update, not "
        "restate it - a shared decision with two implementations is a fix that "
        "lands on half the app")
    assert "expect=list" in src.replace(" ", ""), (
        "history is a LIST; asking for the dict default would quarantine every "
        "valid history file as 'wrong shape'")


def test_the_shared_primitive_still_defaults_to_dict():
    """Every pre-existing caller passes no ``expect`` and needs a dict."""
    from shared.helpers import read_json_for_update
    import inspect
    assert inspect.signature(read_json_for_update).parameters["expect"].default is dict


def test_the_shared_primitive_returns_the_asked_for_empty_shape(tmp_path):
    from shared.helpers import read_json_for_update
    missing = tmp_path / "nope.json"
    assert read_json_for_update(missing, expect=list) == ([], True)
    assert read_json_for_update(missing) == ({}, True)


def test_the_shared_primitive_rejects_the_wrong_shape_per_caller(tmp_path):
    """A list is damaged content for a dict caller and vice versa."""
    from shared.helpers import read_json_for_update
    p = tmp_path / "s.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    data, may_write = read_json_for_update(p, expect=list)
    assert data == [] and may_write is True
    assert list(tmp_path.glob("*corrupt*"))


# --- Same class, swept to the last store that held it -----------------------
# engine.applescript_bridge's macOS Office-permission record had the identical
# read -> mutate -> write shape. The stake is far smaller (it only decides
# whether the one-time permission batch re-runs), but "the fix is not done until
# the class has been swept across every module that could hold it".

def test_the_macos_permission_record_survives_a_transient_read(tmp_path, monkeypatch, failing_reads):
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    import engine.applescript_bridge as ab

    ab._record_permission_answered("Microsoft Word")
    ab._record_permission_answered("Microsoft Excel")
    path = Path(ab._permission_record_path())

    failing_reads(path, OSError(35, "Resource temporarily unavailable"))
    ab._record_permission_answered("Microsoft PowerPoint")

    kept = json.loads(path.read_text(encoding="utf-8"))
    assert kept == {"Microsoft Word": True, "Microsoft Excel": True}, (
        "a transient read must not drop the other apps' answered prompts and "
        "silently re-launch Word/Excel/PowerPoint on a later run")


def test_the_permission_record_writer_does_not_read_through_the_total_loader():
    tree = ast.parse((REPO / "engine" / "applescript_bridge.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_record_permission_answered")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_load_permission_record" not in called
    assert "_load_permission_record_for_update" in called
