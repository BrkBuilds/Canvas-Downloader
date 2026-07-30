"""Tests for ``core.preset_manager`` - saved download settings.

Why this file exists
--------------------
A preset is a configuration the user built by hand across three cards of
settings, and it is stored in one JSON file. The module had no tests, and its
two most interesting behaviours are both recovery paths that only run when
something has already gone wrong:

* a **corrupt** presets file is backed up to ``.corrupt`` and treated as empty,
  so the app keeps working - but if that recovery is itself broken the user
  loses every preset AND cannot save a new one;
* an **IOError** must NOT trigger that recovery. A file that is momentarily
  locked (antivirus, a sync client) is not a corrupt file, and renaming it away
  would destroy good data over a transient error. The module says so in a
  comment; nothing enforced it.

The built-ins are the other half. They are documented as immutable, and
``get_builtin_presets`` returns deep copies to make that true - a shallow copy
would let one screen's edit leak into every later read within the session.
"""

from __future__ import annotations

import json
import os

import pytest

from core.preset_manager import PresetManager, PRESETS_FILENAME


@pytest.fixture()
def mgr(tmp_path):
    return PresetManager(str(tmp_path))


@pytest.fixture()
def presets_file(tmp_path):
    return tmp_path / PRESETS_FILENAME


def _settings(**over):
    base = {'download_mode': 'modules', 'file_filter': 'all'}
    base.update(over)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# Round trip
# ═══════════════════════════════════════════════════════════════════════════

def test_a_saved_preset_comes_back(mgr):
    made = mgr.save_preset("My Preset", "Everything I want", _settings(),
                           False, "")
    loaded = mgr.load_presets()
    assert [p['preset_id'] for p in loaded] == [made['preset_id']]
    assert loaded[0]['preset_name'] == "My Preset"
    assert loaded[0]['settings'] == _settings()


def test_loading_with_no_file_returns_empty(mgr, presets_file):
    assert not presets_file.exists()
    assert mgr.load_presets() == []


def test_several_presets_accumulate(mgr):
    for i in range(3):
        mgr.save_preset(f"P{i}", "", _settings(), False, "")
    assert len(mgr.load_presets()) == 3


def test_each_preset_gets_a_unique_id(mgr):
    ids = {mgr.save_preset(f"P{i}", "", _settings(), False, "")['preset_id']
           for i in range(5)}
    assert len(ids) == 5


def test_a_saved_preset_is_never_marked_builtin(mgr):
    """The UI keys "can this be deleted?" off this flag. A user preset that
    claims to be built-in can never be removed."""
    p = mgr.save_preset("P", "", _settings(), False, "")
    assert p['is_builtin'] is False
    assert mgr.load_presets()[0]['is_builtin'] is False


def test_the_name_and_description_are_stripped(mgr):
    p = mgr.save_preset("  Padded  ", "  desc  ", _settings(), False, "")
    assert p['preset_name'] == "Padded"
    assert p['description'] == "desc"


def test_a_missing_description_becomes_an_empty_string(mgr):
    """Not None - the UI interpolates it into markup."""
    p = mgr.save_preset("P", None, _settings(), False, "")
    assert p['description'] == ''


def test_non_ascii_names_survive_the_round_trip(mgr, presets_file):
    """Danish course/preset names are normal here, and Windows would write
    cp1252 without the explicit encoding."""
    name = "Økonomi & Ledelse – Ærø"
    mgr.save_preset(name, "", _settings(), False, "")
    assert mgr.load_presets()[0]['preset_name'] == name
    assert name in presets_file.read_bytes().decode("utf-8")


def test_the_download_path_is_dropped_unless_it_is_included(mgr):
    """A preset that silently carried a path would relocate somebody else's
    downloads when applied."""
    without = mgr.save_preset("A", "", _settings(), False, r"C:\Secret")
    assert without['download_path'] == ''
    with_path = mgr.save_preset("B", "", _settings(), True, r"C:\Courses")
    assert with_path['download_path'] == r"C:\Courses"


# ═══════════════════════════════════════════════════════════════════════════
# Delete
# ═══════════════════════════════════════════════════════════════════════════

def test_deleting_a_preset_removes_only_it(mgr):
    a = mgr.save_preset("A", "", _settings(), False, "")
    b = mgr.save_preset("B", "", _settings(), False, "")
    assert mgr.delete_preset(a['preset_id']) is True
    assert [p['preset_id'] for p in mgr.load_presets()] == [b['preset_id']]


def test_deleting_an_unknown_id_reports_false(mgr):
    mgr.save_preset("A", "", _settings(), False, "")
    assert mgr.delete_preset("preset_nope") is False
    assert len(mgr.load_presets()) == 1


def test_a_failed_delete_does_not_rewrite_the_file(mgr, presets_file):
    """``delete_preset`` returns before saving when nothing matched. Rewriting
    anyway would reformat the file on every miss and mask a real problem."""
    mgr.save_preset("A", "", _settings(), False, "")
    before = presets_file.read_bytes()
    mtime = presets_file.stat().st_mtime_ns
    assert mgr.delete_preset("preset_nope") is False
    assert presets_file.read_bytes() == before
    assert presets_file.stat().st_mtime_ns == mtime


def test_a_builtin_id_cannot_be_deleted(mgr):
    """Built-ins live in code, not in the file, so a delete must simply miss."""
    builtins = mgr.get_builtin_presets()
    assert builtins, "there should be built-in presets"
    for b in builtins:
        assert mgr.delete_preset(b['preset_id']) is False


def test_deleting_the_last_preset_leaves_a_valid_empty_file(mgr):
    a = mgr.save_preset("A", "", _settings(), False, "")
    mgr.delete_preset(a['preset_id'])
    assert mgr.load_presets() == []
    # and the next save still works
    mgr.save_preset("B", "", _settings(), False, "")
    assert len(mgr.load_presets()) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Built-ins are immutable
# ═══════════════════════════════════════════════════════════════════════════

def test_builtins_are_deep_copies(mgr):
    """A shallow copy would let a caller mutating ``settings`` change what
    every later caller sees, for the rest of the session."""
    first = mgr.get_builtin_presets()
    first[0]['preset_name'] = "VANDALISED"
    first[0]['settings']['download_mode'] = "vandalised"
    second = mgr.get_builtin_presets()
    assert second[0]['preset_name'] != "VANDALISED"
    assert second[0]['settings']['download_mode'] != "vandalised"


def test_builtins_are_all_flagged_builtin(mgr):
    for b in mgr.get_builtin_presets():
        assert b['is_builtin'] is True, f"{b.get('preset_name')} is not flagged"


def test_builtins_never_appear_in_the_user_list(mgr):
    """They are not persisted, so saving a user preset must not pull them in
    and delete must not be able to reach them."""
    mgr.save_preset("Mine", "", _settings(), False, "")
    loaded = mgr.load_presets()
    assert len(loaded) == 1
    assert all(not p.get('is_builtin') for p in loaded)


def test_every_builtin_has_the_fields_the_ui_reads(mgr):
    for b in mgr.get_builtin_presets():
        for field in ('preset_id', 'preset_name', 'settings', 'is_builtin'):
            assert field in b, f"built-in {b.get('preset_name')!r} lacks {field}"


def test_builtin_ids_are_unique(mgr):
    ids = [b['preset_id'] for b in mgr.get_builtin_presets()]
    assert len(ids) == len(set(ids))


# ═══════════════════════════════════════════════════════════════════════════
# Corruption recovery
# ═══════════════════════════════════════════════════════════════════════════

def test_a_corrupt_file_is_backed_up_and_treated_as_empty(mgr, presets_file, tmp_path):
    presets_file.write_text('{"presets": [{"preset_id": "a"', encoding="utf-8")
    assert mgr.load_presets() == []
    backup = presets_file.with_suffix('.corrupt')
    assert backup.exists(), "the corrupt file must be preserved, not just dropped"
    assert not presets_file.exists(), "the corrupt file must be moved out of the way"


def test_saving_works_again_after_corruption(mgr, presets_file):
    """The point of the recovery. If it left the bad file in place, every
    subsequent save would read it, fail, and the user could never recover."""
    presets_file.write_text("garbage", encoding="utf-8")
    mgr.save_preset("Fresh", "", _settings(), False, "")
    assert [p['preset_name'] for p in mgr.load_presets()] == ["Fresh"]


def test_a_stale_corrupt_backup_does_not_block_the_next_one(mgr, presets_file):
    """Windows-specific: ``Path.rename`` raises ``FileExistsError`` when the
    destination exists, so the recovery unlinks the old backup first. Without
    that, a second corruption falls through to the delete branch and the file
    is lost instead of preserved.
    """
    stale = presets_file.with_suffix('.corrupt')
    stale.write_text("an older corruption", encoding="utf-8")
    presets_file.write_text("newly corrupt", encoding="utf-8")

    assert mgr.load_presets() == []
    assert stale.exists()
    assert stale.read_text(encoding="utf-8") == "newly corrupt", \
        "the newest corrupt file should be the one preserved"


@pytest.mark.parametrize("content,why", [
    ('[]', "a list root, not the {'presets': [...]} envelope"),
    ('"a string"', "a bare string root"),
    ('42', "a number root"),
    ('null', "a null root"),
    ('{"presets": {"a": 1}}', "presets is an object, not a list"),
    ('{"presets": "nope"}', "presets is a string"),
    ('{}', "no presets key at all"),
])
def test_a_structurally_wrong_file_is_treated_as_empty(mgr, presets_file, content, why):
    """These are all VALID json, so the corruption branch never fires - the
    type checks are the only thing standing between them and a crash on the
    next iteration."""
    presets_file.write_text(content, encoding="utf-8")
    assert mgr.load_presets() == [], f"failed for {why}"


def test_a_structurally_wrong_file_is_NOT_backed_up(mgr, presets_file):
    """Only a JSONDecodeError triggers the backup. A well-formed file with the
    wrong shape is left alone so the next save simply overwrites it."""
    presets_file.write_text('{"presets": "nope"}', encoding="utf-8")
    mgr.load_presets()
    assert presets_file.exists()
    assert not presets_file.with_suffix('.corrupt').exists()


def test_an_io_error_does_not_destroy_the_file(mgr, presets_file, monkeypatch):
    """THE contract the module states in a comment: a temporary access error is
    not corruption. Recovering from it would rename away a perfectly good file
    because an antivirus scanner held it open for a moment.
    """
    presets_file.write_text(json.dumps({'presets': [{'preset_id': 'keep'}]}),
                            encoding="utf-8")
    real_open = open

    def flaky(path, *a, **k):
        if str(path) == str(presets_file):
            raise IOError("temporarily locked")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", flaky)
    assert mgr.load_presets() == []
    monkeypatch.undo()

    assert presets_file.exists(), "an IOError must never delete the presets"
    assert not presets_file.with_suffix('.corrupt').exists()
    assert mgr.load_presets()[0]['preset_id'] == 'keep', "the data must survive"


# ═══════════════════════════════════════════════════════════════════════════
# Atomic write
# ═══════════════════════════════════════════════════════════════════════════

def test_no_tmp_file_is_left_after_a_save(mgr, tmp_path):
    mgr.save_preset("A", "", _settings(), False, "")
    assert not list(tmp_path.glob("*.tmp"))


def test_a_failed_save_leaves_the_previous_file_intact(mgr, presets_file, monkeypatch):
    """``os.replace`` is what makes the write atomic. If it fails, the old file
    must still be the complete previous state - never a truncated new one."""
    mgr.save_preset("Original", "", _settings(), False, "")
    before = presets_file.read_bytes()

    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    mgr.save_preset("Doomed", "", _settings(), False, "")
    monkeypatch.undo()

    assert presets_file.read_bytes() == before
    assert [p['preset_name'] for p in mgr.load_presets()] == ["Original"]


def test_a_failed_save_cleans_up_its_staging_file(mgr, tmp_path, monkeypatch):
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    mgr.save_preset("Doomed", "", _settings(), False, "")
    monkeypatch.undo()
    assert not list(tmp_path.glob("*.tmp")), "a staging file was orphaned"


def test_a_save_failure_does_not_raise(mgr, monkeypatch):
    """It runs from a Streamlit callback; raising would replace the whole page
    with a traceback over a failed preference write."""
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    mgr.save_preset("Doomed", "", _settings(), False, "")   # must not raise


def test_the_file_is_a_presets_envelope_not_a_bare_list(mgr, presets_file):
    """The envelope is what lets a future version add sibling keys without
    another migration. ``load_presets`` rejects a bare list, so writing one
    would make the app forget every preset."""
    mgr.save_preset("A", "", _settings(), False, "")
    data = json.loads(presets_file.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data['presets'], list)


# ═══════════════════════════════════════════════════════════════════════════
# Capture and apply
# ═══════════════════════════════════════════════════════════════════════════

def test_capture_covers_every_declared_settings_key(mgr):
    captured = mgr.capture_current_settings({})
    assert set(captured) == set(PresetManager.SETTINGS_KEYS), \
        "capture must produce exactly the declared key set"


def test_capture_uses_the_documented_defaults_for_an_empty_session(mgr):
    captured = mgr.capture_current_settings({})
    assert captured['download_mode'] == 'modules'
    assert captured['file_filter'] == 'all'
    assert captured['pan_layout'] == 'match'
    others = [k for k in PresetManager.SETTINGS_KEYS
              if k not in ('download_mode', 'file_filter', 'pan_layout')]
    assert all(captured[k] is False for k in others), \
        "every other setting defaults to off"


def test_capture_reads_what_is_actually_in_session(mgr):
    state = {'download_mode': 'flat', 'file_filter': 'pdf', 'pan_layout': 'separate'}
    captured = mgr.capture_current_settings(state)
    assert captured['download_mode'] == 'flat'
    assert captured['file_filter'] == 'pdf'
    assert captured['pan_layout'] == 'separate'


def test_apply_writes_every_key_into_session(mgr):
    state: dict = {}
    mgr.apply_preset(state, {'settings': mgr.capture_current_settings({})})
    for key in PresetManager.SETTINGS_KEYS:
        assert key in state, f"{key} was not applied"


@pytest.mark.parametrize("stored,expected", [
    ('modules', 'modules'),
    ('flat', 'flat'),
    ('files', 'modules'),        # the legacy value named in the code comment
    ('nonsense', 'modules'),
    (None, 'modules'),
])
def test_an_unsupported_download_mode_is_coerced(mgr, stored, expected):
    """Only two modes are reachable in the UI and the engine's hybrid logic
    assumes it. A legacy 'files' surviving into session state means neither
    branch of the dispatch matches."""
    state: dict = {}
    mgr.apply_preset(state, {'settings': {'download_mode': stored}})
    assert state['download_mode'] == expected


@pytest.mark.parametrize("stored,expected", [
    ('match', 'match'), ('separate', 'separate'),
    ('legacy', 'match'), (None, 'match'),
])
def test_an_unsupported_panopto_layout_is_coerced(mgr, stored, expected):
    state: dict = {}
    mgr.apply_preset(state, {'settings': {'pan_layout': stored}})
    assert state['pan_layout'] == expected


def test_apply_rederives_the_secondary_master_toggle(mgr):
    """The master is a VIEW of its sub-toggles. Trusting a stored value lets a
    preset show a master 'off' above three enabled children."""
    sub = PresetManager.SECONDARY_CONTENT_KEYS[0]
    state: dict = {}
    mgr.apply_preset(state, {'settings': {sub: True, 'dl_secondary_master': False}})
    assert state['dl_secondary_master'] is True

    state = {}
    mgr.apply_preset(state, {'settings': {'dl_secondary_master': True}})
    assert state['dl_secondary_master'] is False, \
        "with no sub-toggle on, the master must be off whatever was stored"


def test_apply_rederives_the_notebook_master_toggle(mgr):
    sub = PresetManager.NOTEBOOK_SUB_KEYS[0]
    state: dict = {}
    mgr.apply_preset(state, {'settings': {sub: True, 'notebooklm_master': False}})
    assert state['notebooklm_master'] is True


def test_apply_only_touches_the_download_path_when_told_to(mgr):
    state = {'download_path': r"C:\Existing"}
    mgr.apply_preset(state, {'settings': {}, 'include_path': False,
                             'download_path': r"C:\Other"})
    assert state['download_path'] == r"C:\Existing"


def test_apply_ignores_an_included_but_empty_path(mgr):
    """``include_path`` true with a blank path is a preset saved before the
    folder was chosen. Applying '' would point the download at nowhere."""
    state = {'download_path': r"C:\Existing"}
    mgr.apply_preset(state, {'settings': {}, 'include_path': True,
                             'download_path': ''})
    assert state['download_path'] == r"C:\Existing"


def test_apply_sets_the_path_when_the_preset_carries_one(mgr):
    state = {'download_path': r"C:\Existing"}
    mgr.apply_preset(state, {'settings': {}, 'include_path': True,
                             'download_path': r"C:\FromPreset"})
    assert state['download_path'] == r"C:\FromPreset"


def test_apply_survives_a_preset_with_no_settings_at_all(mgr):
    """A hand-edited or truncated preset must not take the page down."""
    state: dict = {}
    mgr.apply_preset(state, {})
    assert state['download_mode'] == 'modules'


def test_capture_apply_capture_is_stable(mgr):
    """Round-trip fidelity: applying a saved preset must reproduce exactly the
    configuration it was captured from, or presets drift each time they are used.

    The starting state has to be SELF-CONSISTENT - a sub-toggle on with its
    master off is not a state the UI can produce, and ``apply_preset``
    deliberately corrects it (see the re-derivation tests above). Feeding an
    inconsistent state in here would be testing the derivation, not the round
    trip, and would fail for the right reason at the wrong assertion.
    """
    original = dict.fromkeys(PresetManager.SETTINGS_KEYS, False)
    original['download_mode'] = 'flat'
    original['file_filter'] = 'pdf'
    original['pan_layout'] = 'separate'
    original[PresetManager.SECONDARY_CONTENT_KEYS[0]] = True
    original['dl_secondary_master'] = True        # derived from the line above

    state: dict = {}
    mgr.apply_preset(state, {'settings': original})
    recaptured = mgr.capture_current_settings(state)
    assert recaptured == original


def test_a_round_trip_through_DISK_is_also_stable(mgr):
    """The in-memory round trip above would still pass if json mangled a value
    on the way through (a tuple becoming a list, a bool becoming a string)."""
    captured = mgr.capture_current_settings(
        {'download_mode': 'flat', 'file_filter': 'pdf', 'pan_layout': 'separate'})
    mgr.save_preset("Round trip", "", captured, False, "")

    state: dict = {}
    mgr.apply_preset(state, mgr.load_presets()[0])
    assert mgr.capture_current_settings(state) == captured


def test_every_builtin_applies_cleanly(mgr):
    """The built-ins are the presets most users actually press."""
    for b in mgr.get_builtin_presets():
        state: dict = {}
        mgr.apply_preset(state, b)
        assert state['download_mode'] in ('modules', 'flat'), \
            f"built-in {b['preset_name']!r} applies an unreachable download mode"
        assert state['pan_layout'] in ('match', 'separate')
