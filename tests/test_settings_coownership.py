"""``canvas_downloader_settings.json`` is CO-OWNED - no writer may erase the rest.

Four modules read-modify-write this one file, each changing only its own keys:

* ``ui.auth``          - the Settings dialog and the login path
* ``panopto.settings`` - the ``"panopto"`` engine block AND ``panopto_globally_enabled``
* ``shared.legal``     - ``panopto_notice_ack_version``, an accepted legal notice
* ``core.store_review`` - the ``"store_review"`` block (Microsoft Store rating ask)

Every one of them read the whole file, degraded an unreadable read to ``{}``, and
wrote anyway. ``ui.auth`` was hardened for this on 2026-08-08 via
``read_config_for_update``; the sweep stopped there, so on 2026-08-09 the other
three writers still reduced a full settings file to a single key - and each
returned ``True``, reporting success.

Reproduced against the real functions before the fix. One unreadable read cost
``panopto_notice_ack_version`` (the user is asked to accept the notice again),
the whole ``"panopto"`` engine block, ``canvas_url``, ``default_download_path``,
``show_help_text`` and ``use_12h_format``.

The tests assert the INVARIANT - "a write never loses another module's key" -
rather than any particular spelling of the guard, so a future refactor that keeps
the property keeps passing.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: A realistic, fully populated settings file. Every key belongs to a DIFFERENT
#: owner, which is the entire point of the file and of these tests.
FULL = {
    "canvas_url": "https://cbs.instructure.com",
    "default_download_path": "C:/Users/student/Canvas",
    "show_help_text": True,
    "use_12h_format": False,
    "panopto_notice_ack_version": 2,
    "panopto_globally_enabled": True,
    "panopto": {"model": "medium", "language": "da", "device": "cuda"},
}


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """An isolated config dir the real modules resolve through.

    ``get_config_dir`` honours ``CANVAS_DL_CONFIG_DIR`` first and unconditionally,
    and both modules under test resolve the path per call, so this reaches the
    REAL functions with no patching of their internals.
    """
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    return tmp_path / "canvas_downloader_settings.json"


def _writers():
    """Every writer of the co-owned settings file, as ``(label, callable)``.

    Imported inside the test so the isolated config dir is already in place.
    """
    import panopto.settings as ps
    import shared.legal as legal
    import core.store_review as sr
    return [
        ("panopto.settings.set_globally_enabled", lambda: ps.set_globally_enabled(False)),
        ("panopto.settings.save_settings", lambda: ps.save_settings({"model": "small"})),
        ("panopto.settings.set_tx_setup_notice_dismissed",
         lambda: ps.set_tx_setup_notice_dismissed(True)),
        ("shared.legal.record_panopto_acknowledgement", legal.record_panopto_acknowledgement),
        # All three of core.store_review's writers, not one representative: they
        # funnel through _save_state, so listing only one would leave the other
        # two free to grow their own read and this census would not notice.
        ("core.store_review.note_clean_run", sr.note_clean_run),
        ("core.store_review.note_ask", sr.note_ask),
        ("core.store_review.note_rated", sr.note_rated),
    ]


def _assert_isolated(cfg):
    """Refuse to run a writer unless it will land in the test's own directory.

    These tests drive the REAL persistence functions, and ``get_config_dir()``
    falls back to the REPO ROOT for a script run - which is where a developer's
    live ``canvas_downloader_settings.json`` actually sits. If the isolation ever
    breaks, the writers quietly rewrite that file instead of failing, and the
    damage looks like nothing at all. (It happened once while this file was being
    written: a ``monkeypatch.undo()`` reverted the fixture's env var and reset a
    live ``"panopto"`` block to its defaults.) One assertion turns the whole class
    of accident into a red test.
    """
    from shared.helpers import get_config_dir
    resolved = os.path.normcase(os.path.realpath(get_config_dir()))
    expected = os.path.normcase(os.path.realpath(str(cfg.parent)))
    assert resolved == expected, (
        f"config-dir isolation is BROKEN: the real settings writers would "
        f"target {resolved!r}, not the test's {expected!r}")


def _write_full(path):
    path.write_text(json.dumps(FULL, indent=2), encoding="utf-8")


def _damage_utf8(path):
    """A file re-saved by an editor in a local ANSI codepage.

    Not hypothetical for THIS app: these configs carry Danish course names and
    paths, so they are full of ``æøå``. ``UnicodeDecodeError`` is a sibling of
    ``JSONDecodeError``, not a subclass, which is what made it slip past
    handlers that meant to catch "the file is broken".
    """
    raw = json.dumps(FULL, indent=2).encode("utf-8").replace(b"Canvas", b"Canv\xe6s")
    path.write_bytes(raw)


def _damage_json(path):
    path.write_text('{"canvas_url": "https://cbs.instructure.com",', encoding="utf-8")


# ── The invariant, on a healthy file ────────────────────────────────────────

def test_a_healthy_write_keeps_every_other_owners_key(cfg):
    """The base case. If this breaks, the file is not co-ownable at all."""
    for name, fn in _writers():
        _write_full(cfg)
        _assert_isolated(cfg)
        assert fn() is True, f"{name} failed on a perfectly good file"
        after = json.loads(cfg.read_text(encoding="utf-8"))
        missing = [k for k in FULL if k not in after]
        assert not missing, f"{name} lost another owner's keys: {missing}"


# ── Damaged content: quarantine, then recover ───────────────────────────────

@pytest.mark.parametrize("damage,why", [
    (_damage_utf8, "bytes that are not valid UTF-8"),
    (_damage_json, "malformed JSON"),
])
def test_damaged_content_is_preserved_on_disk_not_silently_overwritten(cfg, damage, why):
    """The file cannot be kept in place, so its CONTENT must survive beside it.

    Writing is allowed to proceed here - the user needs a working settings file
    back - but the bytes they had must still exist, because a settings file is
    the only record of an accepted legal notice and a configured download path.
    """
    for name, fn in _writers():
        for f in cfg.parent.iterdir():
            f.unlink() if f.is_file() else shutil.rmtree(f)
        damage(cfg)
        original = cfg.read_bytes()

        _assert_isolated(cfg)
        fn()

        quarantined = [p for p in cfg.parent.iterdir() if "corrupt" in p.name]
        assert quarantined, (
            f"{name}: {why} was overwritten with no copy kept - the user's "
            f"accepted notice and settings are gone with nothing to recover from")
        assert quarantined[0].read_bytes() == original, (
            f"{name}: the quarantined copy is not the bytes that were there")


def test_quarantine_never_overwrites_an_earlier_one(cfg):
    """The FIRST quarantine is the copy closest to the last good state."""
    import panopto.settings as ps
    first, second = b'{"first": 1', b'{"second": 2'
    _assert_isolated(cfg)
    cfg.write_bytes(first)
    ps.set_globally_enabled(False)
    cfg.write_bytes(second)
    ps.set_globally_enabled(True)

    kept = sorted(p.name for p in cfg.parent.iterdir() if "corrupt" in p.name)
    assert len(kept) == 2, f"expected both damaged copies to survive, got {kept}"
    bodies = {p.read_bytes() for p in cfg.parent.iterdir() if "corrupt" in p.name}
    assert first in bodies and second in bodies


# ── Transient failure: refuse to write at all ───────────────────────────────

def test_a_transient_read_failure_writes_nothing(cfg, monkeypatch):
    """Nothing is wrong with the FILE, so nothing may be replaced.

    **The READ must fail while the WRITE would still succeed** - that is the
    whole condition, and getting it wrong makes this test pass against broken
    code. The first version of it put a directory where the settings file
    belongs; that fails the read, but it also fails ``os.replace``, so removing
    the guard entirely still left the file intact and FOUR mutants survived.
    The test was passing for the wrong reason.

    A read-only failure is the realistic shape anyway: an antivirus scanner
    holding the file open, a share that drops reads, a permissions blip on the
    file but not the directory. Patching ``open`` for reads of this one path
    reproduces it exactly, and leaves the tmp-file write and ``os.replace`` fully
    functional - so if a writer ignores the verdict, it really does overwrite.
    """
    import builtins
    real_open = builtins.open
    target = os.path.normcase(str(cfg))

    def picky_open(file, mode="r", *a, **kw):
        same = os.path.normcase(str(file)) == target
        if same and ("r" in mode and "w" not in mode and "a" not in mode):
            raise PermissionError(13, "simulated antivirus read lock")
        return real_open(file, mode, *a, **kw)

    for name, fn in _writers():
        for f in cfg.parent.iterdir():
            f.unlink() if f.is_file() else shutil.rmtree(f)
        _write_full(cfg)
        before = cfg.read_bytes()

        # A NESTED context, never `monkeypatch.undo()`. `undo()` reverts every
        # patch the same monkeypatch instance holds - including the `cfg`
        # fixture's CANVAS_DL_CONFIG_DIR - so from the second iteration on these
        # writers resolved to the REAL config dir and wrote the developer's own
        # settings file. (That is not hypothetical: it happened while this test
        # was being written, and reset a live "panopto" block to its defaults.)
        with monkeypatch.context() as m:
            m.setattr(builtins, "open", picky_open)
            _assert_isolated(cfg)
            result = fn()

        assert result is False, (
            f"{name} reported SUCCESS after a transient read failure - the "
            f"caller believes the setting was persisted when it was not")
        assert cfg.read_bytes() == before, (
            f"{name} rewrote the settings file after a transient read failure; "
            f"it now holds only that writer's own key and every other owner's "
            f"settings - including the accepted notice - are gone")
        assert not [p for p in cfg.parent.iterdir() if "corrupt" in p.name], (
            f"{name} quarantined an intact file over a transient error - that "
            f"is the misclassification this whole guard exists to prevent")


# ── Structural: the decision has exactly ONE implementation ─────────────────

def _calls_in(fn_node):
    out = set()
    for n in ast.walk(fn_node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                out.add(f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


@pytest.mark.parametrize("module_path,writers", [
    ("panopto/settings.py", ["save_settings", "set_globally_enabled",
                             "set_tx_setup_notice_dismissed"]),
    ("shared/legal.py", ["record_panopto_acknowledgement"]),
    # core.store_review funnels its three public writers through ONE
    # read-modify-write, so _save_state is the function this census is about.
    # That every writer really does go through it is asserted separately, by
    # tests/test_store_review.py - splitting the two keeps both meaningful.
    ("core/store_review.py", ["_save_state"]),
])
def test_every_writer_reads_through_the_for_update_reader(module_path, writers):
    """A writer must never take its dict from the degrading reader.

    Matched on the CALL, not on the token: leaving ``_read_full_config`` present
    anywhere in the file (an import, a docstring, another function) satisfies a
    substring test while the writer has quietly gone back to the unsafe reader.
    That exact weakness let four mutants escape an earlier test in this repo.
    """
    tree = ast.parse((REPO / module_path).read_text(encoding="utf-8"))
    found = {n.name: n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name in writers}
    assert set(found) == set(writers), f"{module_path}: missing {set(writers) - set(found)}"

    for name, node in found.items():
        calls = _calls_in(node)
        assert "_read_full_config_for_update" in calls, (
            f"{module_path}:{name} does not read through the for-update reader")
        assert "_read_full_config" not in calls, (
            f"{module_path}:{name} still calls the DEGRADING reader, which "
            f"returns {{}} on an unreadable file and takes every other module's "
            f"settings with it")


def test_the_shared_reader_is_the_only_implementation_of_the_verdict():
    """``ui.auth`` must not keep a private copy of the read/quarantine logic.

    The whole reason three writers were unprotected is that this decision was
    implemented once, in one module, and the other co-owners never got it. Two
    implementations is a fix that lands on half the app, silently - the lesson
    ``make_long_path`` already taught this repo.
    """
    src = (REPO / "ui" / "auth.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "read_config_for_update")
    assert "read_json_for_update" in _calls_in(fn), (
        "ui.auth.read_config_for_update no longer delegates to the shared "
        "primitive - the four co-owners of the settings file can now drift")

    from shared.helpers import read_json_for_update
    assert callable(read_json_for_update)


def test_shared_reader_rejects_a_non_dict_payload(tmp_path):
    """A JSON list or scalar is damaged content: callers subscript the result."""
    from shared.helpers import read_json_for_update
    p = tmp_path / "cfg.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    data, may_write = read_json_for_update(p)
    assert data == {} and may_write is True
    assert [q for q in tmp_path.iterdir() if "corrupt" in q.name], (
        "a non-object payload was accepted, so the writer would raise on it")


def test_shared_reader_treats_a_missing_file_as_a_fresh_install(tmp_path):
    from shared.helpers import read_json_for_update
    data, may_write = read_json_for_update(tmp_path / "nope.json")
    assert data == {} and may_write is True
