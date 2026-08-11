"""One unreadable read at LAUNCH destroyed the user's whole library (2026-08-11).

`core/library.py` was hardened for the "unreadable is not empty" class in
2026-08-06, and `core/preset_manager.py`, `ui/auth.py`, `core.today_store` and
`shared.helpers.atomic_update_sync_pairs` followed. **`core/library_migrate.py`
was never swept** - and it sits UPSTREAM of the hardened one, so it can destroy the
library before `load_library`'s guards ever run. It is also the only member of the
family that runs on **every launch** (`app.py`, once per session).

THE MECHANISM. The legacy stores are never deleted - the migration only copies
them to `*.bak` - so a re-run always has something to import, and importing
REBUILDS the library from the state it had at first migration. `needs_migration`
answered "yes, migrate" for any library file it could not read, and `_read_json`
swallowed `OSError` alongside `JSONDecodeError`. So one transient failure - an
antivirus lock, a config dir on an offline share, a permissions blip - was enough.

Reproduced against the real functions: a pair the user had renamed reverted to its
original 2026 name, and a second pair they had saved **disappeared entirely**.
Every saved pair, every user-given name, every group and every daily-sync
membership created since the first migration, gone at launch, with a debug-level
log as the only trace.

Two more, found in the same read:

  * `UnicodeDecodeError` is a SIBLING of `json.JSONDecodeError` (both
    `ValueError`), not a subclass, so it escaped `_read_json` entirely - and it
    escaped from `needs_migration`, which `migrate_if_needed` calls OUTSIDE its own
    try. One config file re-saved by an editor in a Danish ANSI codepage broke the
    "never raises" contract its own docstring states.
  * A LEGACY file that exists and cannot be read this time was treated as empty,
    so the migration would write a library missing every pair that file held - and
    `needs_migration` then answers False for ever, making the loss permanent and
    silent. It now aborts and retries on the next launch.
"""
from __future__ import annotations

import builtins
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """A config dir holding the two legacy stores, as a real upgrade would."""
    monkeypatch.setenv('CANVAS_DL_CONFIG_DIR', str(tmp_path))
    (tmp_path / "saved_sync_groups.json").write_text(json.dumps({"groups": [
        {"is_single_pair": True, "group_name": "Legacy pair",
         "pairs": [{"course_id": 111, "course_name": "Macro",
                    "local_folder": "/tmp/Macro"}]},
    ]}), encoding="utf-8")
    (tmp_path / "today_dashboard.json").write_text(
        json.dumps({"pairs": []}), encoding="utf-8")
    return tmp_path


def _lib_path(cfg):
    import core.library as library
    return cfg / library._FILENAME


def _pairs(cfg):
    import core.library as library
    return [(p["name"], p["local_folder"]) for p in library.load_library()["pairs"]]


class _unreadable:
    """Context manager: reads of exactly ONE path fail transiently.

    Patching `open` for that one path is what makes this a TRANSIENT-read test.
    Putting a directory where the file goes (the obvious shortcut) also breaks the
    WRITE, so the guard could be deleted with the test still green - the trap that
    let four mutants survive in tests/test_settings_coownership.py.

    A CONTEXT MANAGER rather than `monkeypatch` + `undo()`, and that is not style:
    `undo()` reverts the fixture's `CANVAS_DL_CONFIG_DIR` too, so every assertion
    after it would read **the developer's real library in the repo root**. Exactly
    the hazard `test_settings_coownership._assert_isolated` exists for; here the
    tests caught it themselves, by failing with an empty pair list.
    """

    def __init__(self, target: pathlib.Path):
        self.target = str(target)
        self.real = builtins.open

    def __enter__(self):
        real = self.real
        target = self.target

        def flaky(path, *a, **k):
            if str(path) == target:
                raise OSError(11, "Resource temporarily unavailable")
            return real(path, *a, **k)

        builtins.open = flaky
        return self

    def __exit__(self, *exc):
        builtins.open = self.real
        return False


def _assert_isolated(cfg):
    """Refuse to assert against a config dir that is not the test's own.

    Same guard, same reason, as tests/test_settings_coownership.py: without it a
    reverted env var silently points these functions at the real store.
    """
    from shared.helpers import get_config_dir
    assert pathlib.Path(get_config_dir()).resolve() == pathlib.Path(cfg).resolve(), \
        "config dir escaped the fixture - refusing to touch the real library"


# ── the headline ────────────────────────────────────────────────────────────

def test_a_transient_read_does_not_reimport_the_legacy_stores(cfg, monkeypatch):
    """THE regression. One blip at launch used to revert the whole library."""
    from core.library_migrate import migrate_if_needed
    import core.library as library

    assert migrate_if_needed(str(cfg))["migrated"] is True     # first boot
    pid = library.load_library()["pairs"][0]["id"]
    library.rename_pair(pid, "My current name")
    library.save_pair(222, "/tmp/Stats", course_name="Stats", name="Second pair")
    before = _pairs(cfg)
    assert ("Second pair", "/tmp/Stats") in before

    with _unreadable(_lib_path(cfg)):
        res = migrate_if_needed(str(cfg))

    assert res["migrated"] is False
    _assert_isolated(cfg)
    assert _pairs(cfg) == before, "the library must be left exactly as it was"


def test_a_transient_read_answers_do_not_migrate(cfg, monkeypatch):
    from core.library_migrate import migrate_if_needed, needs_migration
    migrate_if_needed(str(cfg))
    with _unreadable(_lib_path(cfg)):
        assert needs_migration(str(cfg)) is False


def test_a_transient_read_writes_nothing_at_all(cfg, monkeypatch):
    """Not merely "the pairs survive" - the file's bytes must be untouched."""
    from core.library_migrate import migrate_if_needed
    migrate_if_needed(str(cfg))
    p = _lib_path(cfg)
    before = p.read_bytes()
    with _unreadable(p):
        migrate_if_needed(str(cfg))
    assert p.read_bytes() == before


# ── damaged content: rebuild is right, but keep the bytes ───────────────────

@pytest.mark.parametrize("payload,label", [
    ('{"version": 2, "pairs": [{"name": "Makroøkonomi"}]}'.encode('cp1252'),
     "a Danish ANSI codepage"),
    (b"{not json", "malformed JSON"),
    (b'["a", "list"]', "a non-object root"),
])
def test_damaged_content_is_quarantined_then_rebuilt(cfg, payload, label):
    """The docstring's reasoning ("rebuilding beats an empty library") is right for
    CORRUPTION - it was only wrong for a blip. The bytes are kept either way:
    a corrupt library can still be salvaged by hand, a deleted one cannot."""
    from core.library_migrate import migrate_if_needed
    _lib_path(cfg).write_bytes(payload)
    res = migrate_if_needed(str(cfg))
    assert res["migrated"] is True, label
    assert list(cfg.glob("sync_library.corrupt*")), f"{label}: bytes were not kept"
    assert ("Legacy pair", "/tmp/Macro") in _pairs(cfg)


def test_a_mis_encoded_library_does_not_raise_out_of_either_entry_point(cfg):
    """`migrate_if_needed` promises never to raise, and its `needs_migration`
    call sits outside its own try - so the promise depended on `_read_json`
    being total, and it was not."""
    from core.library_migrate import migrate_if_needed, needs_migration
    _lib_path(cfg).write_bytes(
        '{"version": 2, "pairs": [{"name": "Makroøkonomi"}]}'.encode('cp1252'))
    assert needs_migration(str(cfg)) is True        # must not raise
    assert migrate_if_needed(str(cfg))["migrated"] is True


# ── a legacy store that cannot be read must abort, not import a partial ────

def test_an_unreadable_legacy_store_aborts_and_retries(cfg, monkeypatch):
    """Treating it as empty writes a library missing every pair it held - and
    `needs_migration` then answers False for ever, so the loss is permanent."""
    from core.library_migrate import migrate_if_needed
    with _unreadable(cfg / "saved_sync_groups.json"):
        res = migrate_if_needed(str(cfg))

    assert res["migrated"] is False
    assert "legacy read failed" in res["reason"]
    assert not _lib_path(cfg).exists(), "nothing may be written on this path"

    # the next launch, with the file readable again, migrates properly
    res2 = migrate_if_needed(str(cfg))
    assert res2["migrated"] is True
    _assert_isolated(cfg)
    assert ("Legacy pair", "/tmp/Macro") in _pairs(cfg)


# ── nothing above may have broken the ordinary paths ───────────────────────

def test_a_normal_first_run_still_migrates(cfg):
    from core.library_migrate import migrate_if_needed
    assert migrate_if_needed(str(cfg))["migrated"] is True
    assert ("Legacy pair", "/tmp/Macro") in _pairs(cfg)


def test_it_stays_idempotent(cfg):
    from core.library_migrate import migrate_if_needed
    assert migrate_if_needed(str(cfg))["migrated"] is True
    second = migrate_if_needed(str(cfg))
    assert second == {"migrated": False, "reason": "already"}


def test_an_absent_library_with_no_legacy_files_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv('CANVAS_DL_CONFIG_DIR', str(tmp_path))
    from core.library_migrate import migrate_if_needed
    res = migrate_if_needed(str(tmp_path))
    assert res["migrated"] is True and res["pairs"] == 0


# ── the primitive itself ───────────────────────────────────────────────────

def test_read_json_reports_the_CAUSE(tmp_path):
    from core.library_migrate import _read_json, _READ_FAILED, _DAMAGED
    assert _read_json(tmp_path / "nope.json") is None
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert _read_json(tmp_path / "bad.json") is _DAMAGED
    (tmp_path / "enc.json").write_bytes("{\"a\": \"ø\"}".encode('cp1252'))
    assert _read_json(tmp_path / "enc.json") is _DAMAGED
    (tmp_path / "ok.json").write_text('{"a": 1}', encoding="utf-8")
    assert _read_json(tmp_path / "ok.json") == {"a": 1}


def test_the_three_outcomes_are_distinct_objects():
    """`None` (absent), `_DAMAGED` and `_READ_FAILED` drive three different
    decisions; any two of them being the same value reintroduces the bug."""
    from core.library_migrate import _READ_FAILED, _DAMAGED
    assert _READ_FAILED is not _DAMAGED
    assert _READ_FAILED is not None and _DAMAGED is not None
