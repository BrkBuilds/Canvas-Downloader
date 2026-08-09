"""The presets store must survive a read it could not perform.

``core.preset_manager`` was the last JSON store in the app that had not been
swept with the rule the others were hardened against on 2026-08-06 and
2026-08-08:

    "Unreadable" is not "empty", and load -> mutate -> save turns the second
    into permanent loss.

Two defects, both reproduced against the real ``PresetManager`` before the fix:

1. ``UnicodeDecodeError`` escaped ``load_presets`` entirely. It is a *sibling* of
   ``json.JSONDecodeError``, not a subclass (both are ``ValueError``), so neither
   the ``JSONDecodeError`` handler nor the ``IOError`` one caught it. The caller
   is the Presets hub inside an ``@st.dialog``, where a raise blanks the modal.
   One presets file re-saved by an editor in a Danish ANSI codepage does it, and
   preset names are typed by the user - ``æøå`` is ordinary here.

2. A transient ``IOError`` degraded to ``[]`` and ``save_preset`` /
   ``delete_preset`` then WROTE, replacing the user's whole preset library with
   the single preset they were adding - while reporting success.
"""

from __future__ import annotations

import builtins
import json
import os

import pytest

from core.preset_manager import PresetManager


@pytest.fixture()
def mgr(tmp_path):
    return PresetManager(str(tmp_path))


def _seed(m, names):
    json.dump({"presets": [{"preset_id": f"p{i}", "preset_name": n}
                           for i, n in enumerate(names)]},
              open(m.presets_path, "w", encoding="utf-8"))


@pytest.fixture()
def block_reads(monkeypatch):
    """Make reads of one path fail while writes still succeed.

    The read must fail and the write must NOT - otherwise a writer that ignores
    the verdict still fails to damage the file, and the test passes against
    broken code. (That exact mistake left four mutants alive in the sibling
    settings-file suite.)
    """
    def _install(path):
        real_open = builtins.open
        target = os.path.normcase(str(path))

        def picky(file, mode="r", *a, **kw):
            if (os.path.normcase(str(file)) == target
                    and "r" in mode and "w" not in mode and "a" not in mode):
                raise PermissionError(13, "simulated antivirus read lock")
            return real_open(file, mode, *a, **kw)

        monkeypatch.setattr(builtins, "open", picky)
    return _install


# ── 1. Damaged content must not raise into the dialog ───────────────────────

#: A presets file re-saved by an editor in a Danish ANSI codepage.
#:
#: ``ensure_ascii=False`` is load-bearing: with the default the ``Ø`` is written
#: as the ASCII escape ``\\u00d8``, the bytes are then valid UTF-8, and the
#: "damaged" fixture is a perfectly readable file - so the test passes without
#: exercising anything. The whole point is to produce the raw 0xD8 byte.
_ANSI_PRESETS = json.dumps(
    {"presets": [{"preset_id": "a", "preset_name": "Økonomi"}]},
    indent=2, ensure_ascii=False).encode("cp1252")


def test_the_ansi_fixture_really_is_undecodable():
    """Guard the guard: if this ever decodes, every test using it is vacuous."""
    with pytest.raises(UnicodeDecodeError):
        _ANSI_PRESETS.decode("utf-8")


@pytest.mark.parametrize("body,label", [
    (_ANSI_PRESETS, "a local ANSI codepage"),
    (b'{"presets": [', "truncated JSON"),
    (b'\xff\xfe\x00rubbish', "binary rubbish"),
])
def test_damaged_presets_file_never_raises_into_the_ui(mgr, body, label):
    """``load_presets`` is called unguarded inside an ``@st.dialog``."""
    mgr.presets_path.write_bytes(body)
    try:
        got = mgr.load_presets()
    except Exception as e:  # noqa: BLE001 - that is the defect
        pytest.fail(f"load_presets raised {type(e).__name__} on {label}; the "
                    f"Presets hub dialog blanks when this happens")
    assert got == []


def test_damaged_presets_content_survives_on_disk(mgr):
    """The file cannot be kept in place, so its bytes must survive beside it."""
    raw = _ANSI_PRESETS
    mgr.presets_path.write_bytes(raw)

    mgr.load_presets()

    kept = [p for p in mgr.presets_path.parent.iterdir() if "corrupt" in p.name]
    assert kept, "a damaged presets file was discarded with no copy kept"
    assert kept[0].read_bytes() == raw


def test_a_second_corruption_still_preserves_a_copy(mgr):
    """A repeat corruption must not fall through to "no backup at all".

    This module keeps the NEWEST corrupt copy (see ``_quarantine_presets``), which
    is its own long-standing decision and differs from the sync manifest's
    keep-the-first rule. What matters for THIS audit is only that a second
    corruption still leaves something on disk rather than nothing.
    """
    mgr.presets_path.write_bytes(b'{"presets": [1')
    mgr.load_presets()
    mgr.presets_path.write_bytes(b'{"presets": [2')
    mgr.load_presets()

    kept = [p for p in mgr.presets_path.parent.iterdir() if "corrupt" in p.name]
    assert kept, "a second corruption left no backup at all"
    assert kept[0].read_bytes() == b'{"presets": [2'


def test_a_damaged_file_does_not_block_saving_afterwards(mgr):
    """Quarantine, then let the user carry on - they need a working store back."""
    mgr.presets_path.write_bytes(b"not json at all")
    assert mgr.save_preset("Fresh", "", {}, False, "") is not None
    assert [p["preset_name"] for p in mgr.load_presets()] == ["Fresh"]


# ── 2. A transient failure must not rewrite the library ─────────────────────

def test_save_preset_declines_rather_than_replacing_the_library(mgr, block_reads):
    _seed(mgr, ["Keep me", "Me too"])
    before = mgr.presets_path.read_bytes()

    block_reads(mgr.presets_path)
    result = mgr.save_preset("New one", "", {}, False, "")

    assert result is None, (
        "save_preset reported SUCCESS after a transient read failure - the user "
        "is toasted 'saved' for a preset that is not on disk")
    assert mgr.presets_path.read_bytes() == before, (
        "save_preset rewrote the presets file after failing to read it; the "
        "user's whole preset library was replaced by this one preset")


def test_delete_preset_declines_rather_than_emptying_the_library(mgr, block_reads):
    # NOTE on mutation coverage: removing delete_preset's `may_write` guard is an
    # EQUIVALENT mutant today, and deliberately left that way. The degraded list
    # is empty, so the pre-existing "nothing actually matched" check
    # (`len(presets) == original_len`) returns False before any write is reached.
    # The guard is kept as defence in depth and because it is what makes the log
    # line honest - "could not read the file" is a different fact from "no such
    # preset" - not because a test can currently tell them apart. Per the audit
    # playbook: do not delete a redundant gate just to make a mutation die.
    _seed(mgr, ["Keep me", "Me too"])
    before = mgr.presets_path.read_bytes()

    block_reads(mgr.presets_path)
    assert mgr.delete_preset("p0") is False

    assert mgr.presets_path.read_bytes() == before, (
        "delete_preset rewrote the presets file after failing to read it - an "
        "empty list here means 'could not read', not 'you have no presets'")


def test_a_transient_failure_is_not_mistaken_for_corruption(mgr, block_reads):
    """Nothing is wrong with the FILE, so it must not be quarantined."""
    _seed(mgr, ["Keep me"])
    block_reads(mgr.presets_path)
    mgr.load_presets()
    assert not [p for p in mgr.presets_path.parent.iterdir() if "corrupt" in p.name]


# ── 3. The healthy path is unchanged ────────────────────────────────────────

def test_healthy_save_and_delete_still_work(mgr):
    a = mgr.save_preset("One", "", {}, False, "")
    b = mgr.save_preset("Two", "", {}, False, "")
    assert [p["preset_name"] for p in mgr.load_presets()] == ["One", "Two"]
    assert mgr.delete_preset(b["preset_id"]) is True
    assert [p["preset_name"] for p in mgr.load_presets()] == ["One"]
    assert mgr.delete_preset("nope") is False


def test_missing_file_reads_as_no_presets_not_as_a_failure(mgr):
    assert mgr.load_presets() == []
    assert mgr.save_preset("First", "", {}, False, "") is not None


# ── 4. Structural: the writers must consult the verdict ─────────────────────

def test_both_writers_read_through_the_for_update_reader():
    """Matched on the CALL, not the token - a leftover name satisfies a
    substring test while the writer has gone back to the unsafe reader."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "core" / "preset_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for name in ("save_preset", "delete_preset"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        calls = {n.func.attr for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "_load_presets_for_update" in calls, (
            f"{name} does not consult the write verdict")
        assert "load_presets" not in calls, (
            f"{name} still uses the display reader, which degrades an unreadable "
            f"file to [] - and then {name} writes it")
