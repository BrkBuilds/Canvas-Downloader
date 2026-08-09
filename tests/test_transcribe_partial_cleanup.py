"""Cancelling a transcription must not leave `.part` sidecars behind.

The write path is correctly atomic - the worker streams into `<name>.txt.part`
and `<name>.srt.part` and only `os.replace`s them onto the final names when a
recording finishes. The cleanup was the broken half, in two independent ways,
both found by cancelling a real run twice:

1. **The kill is asynchronous.** ``transcribe_in_subprocess`` called
   ``proc.kill()`` and cleaned up immediately. On Windows the dying worker still
   holds its output handles, so ``os.remove`` raised ``PermissionError`` - an
   ``OSError``, swallowed by a bare ``except``. Every cancel left both files.

2. **Only one exit from the phase cleaned up at all.** The transcription loop
   leaves through ``except PanoptoCancelled`` (which cleans, via the call
   above), through ``if is_cancelled() or engine_failed: break`` at the loop
   head (which does not), and through an engine failure (which does not). The
   two cancel routes are distinguishable in the log - one writes "Transcription
   cancelled by user", the other writes nothing - and only the logged one ever
   cleaned.

Why it matters more than it looks: the engine deliberately IGNORES `.part`
artifacts everywhere else - never healed onto a manifest row, never
auto-discovered, never counted as study material, never post-processed. So a
leftover is invisible to the app for ever, and nothing would remove or even
mention it again.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from panopto.transcribe import _clean_part_files  # noqa: E402

RUNNER = (REPO / "panopto" / "runner.py").read_text(encoding="utf-8")
TRANSCRIBE = (REPO / "panopto" / "transcribe.py").read_text(encoding="utf-8")


def _make_parts(tmp_path: Path, stem="Lecture"):
    mp3 = tmp_path / f"{stem}.mp3"
    mp3.write_bytes(b"audio")
    txt = tmp_path / f"{stem}.txt.part"
    srt = tmp_path / f"{stem}.srt.part"
    txt.write_text("half", encoding="utf-8")
    srt.write_text("half", encoding="utf-8")
    return mp3, txt, srt


# --------------------------------------------------------------------------
# the cleanup itself
# --------------------------------------------------------------------------

def test_both_sidecars_are_removed(tmp_path):
    mp3, txt, srt = _make_parts(tmp_path)
    _clean_part_files(str(mp3), True, True)
    assert not txt.exists() and not srt.exists()


def test_only_the_requested_outputs_are_touched(tmp_path):
    mp3, txt, srt = _make_parts(tmp_path)
    _clean_part_files(str(mp3), True, False)
    assert not txt.exists()
    assert srt.exists(), "an output that was not requested is none of its business"


def test_the_finished_file_is_never_touched(tmp_path):
    """Committed output has already been renamed off the .part path."""
    mp3, txt, _srt = _make_parts(tmp_path)
    final = tmp_path / "Lecture.txt"
    final.write_text("the real transcript", encoding="utf-8")
    _clean_part_files(str(mp3), True, True)
    assert final.read_text(encoding="utf-8") == "the real transcript"


def test_absent_files_are_not_an_error(tmp_path):
    mp3 = tmp_path / "Lecture.mp3"
    mp3.write_bytes(b"audio")
    _clean_part_files(str(mp3), True, True)   # must not raise


def test_it_retries_rather_than_giving_up_on_the_first_lock(tmp_path, monkeypatch):
    """The bug: a kill is asynchronous, so the first remove hits a locked file.

    Without the retry the very first PermissionError ended it, silently, and the
    leftovers stayed for good.
    """
    mp3, txt, srt = _make_parts(tmp_path)
    real_remove = os.remove
    calls = {"n": 0}

    def flaky(path, *a, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(32, "being used by another process")
        return real_remove(path, *a, **kw)

    monkeypatch.setattr(os, "remove", flaky)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    _clean_part_files(str(mp3), True, True)
    assert not txt.exists() and not srt.exists()
    assert calls["n"] > 2, "it gave up before retrying"


def test_a_persistent_failure_is_logged_not_silent(tmp_path, monkeypatch, caplog):
    """Untidy is survivable; invisible is not."""
    mp3, _txt, _srt = _make_parts(tmp_path)
    monkeypatch.setattr(os, "remove", lambda *a, **k: (_ for _ in ()).throw(
        PermissionError(32, "locked for ever")))
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    with caplog.at_level("WARNING"):
        _clean_part_files(str(mp3), True, True)   # must still not raise
    assert any("partial transcript" in r.message.lower() or
               "partial transcript" in r.getMessage().lower()
               for r in caplog.records), caplog.text


# --------------------------------------------------------------------------
# it is actually wired to every exit
# --------------------------------------------------------------------------

def _transcription_phase_sweep():
    """The ``_clean_part_files`` call that sweeps the phase, as an AST node.

    Found by STRUCTURE rather than by character distance from
    ``progress("transcribe_done")``. The distance form was brittle in the way
    this repo has already been bitten by once ("a brittle test anchor reads like
    a missing guard"): it used an 1800-character window, so documenting the fix
    pushed the call out of range and three tests started reporting the sweep as
    missing when it was right there. It was also too weak to catch the defect it
    was written for - see ``test_the_sweep_is_in_a_finally_not_merely_after_the_loop``.
    """
    import ast
    tree = ast.parse(RUNNER)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_clean_part_files"):
            continue
        # the phase sweep is the one driven by the tx_tasks loop variable
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        if "_t" in names or {"want_txt", "want_srt"} & attrs:
            return node, names, attrs
    return None, set(), set()


def test_the_phase_sweeps_partials_however_it_ends():
    """The loop has several exits; sweeping per-exit is how one got missed."""
    node, _names, _attrs = _transcription_phase_sweep()
    assert node is not None, (
        "the phase no longer sweeps .part sidecars on the way out - a cancel "
        "caught at the loop head leaves them in the user's course folder")
    import ast
    tree = ast.parse(RUNNER)
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and isinstance(n.iter, ast.Name) and n.iter.id == "tx_tasks"
             and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                     and c.func.id == "_clean_part_files" for c in ast.walk(n))]
    assert loops, "the sweep must cover every target in tx_tasks, not just one"


def test_the_cancel_path_waits_for_the_worker_before_cleaning():
    # Anchor on proc.kill(), not on the cancel test: `if is_cancelled and
    # is_cancelled():` also appears in the IN-WORKER segment loop, which has no
    # subprocess to wait for.
    i = TRANSCRIBE.find("proc.kill()")
    assert i > 0, "the cancel branch moved"
    block = TRANSCRIBE[i:i + 700]
    assert "proc.kill()" in block
    assert "proc.wait(" in block, (
        "cleanup runs while the killed worker still holds its handles, so every "
        "remove fails and the sidecars survive")
    assert block.index("proc.wait(") < block.index("_clean_part_files("), \
        "the wait has to come BEFORE the cleanup to be worth anything"


@pytest.mark.parametrize("marker", ["want_txt", "want_srt", "tx_source"])
def test_the_sweep_uses_the_tasks_own_output_flags(marker):
    """The sweep must ask each task what IT produced, not assume both kinds.

    Read off the call's own arguments rather than a text window, so the assertion
    survives a comment or a reflow (see ``_transcription_phase_sweep``).
    """
    node, names, attrs = _transcription_phase_sweep()
    assert node is not None, "the phase sweep is gone"
    assert marker in attrs, (
        f"the sweep no longer passes {marker}; it would then delete sidecars for "
        f"outputs the user never asked for, or miss the ones they did")


# --------------------------------------------------------------------------
# ROUND 2 (2026-08-09): the live audit cancelled a REAL run and both sidecars
# were still there. Two more defects, and the tests above passed against both.
# --------------------------------------------------------------------------

def test_the_sweep_is_in_a_finally_not_merely_after_the_loop():
    """A cancel from the UI is a ``BaseException``, and it skipped the sweep.

    The sweep used to be ordinary statements after the loop, with a comment
    claiming it covered "every route out of the phase". It did not cover the
    route users actually take: clicking Cancel makes Streamlit stop the script
    run by raising ``RerunException`` / ``StopException`` from the next ``st.*``
    call - which happens inside the ``progress()`` callback, i.e. INSIDE the
    loop. Both derive from ``BaseException``, not ``Exception``, so nothing
    caught them and they propagated straight past the sweep.

    Measured on course 43660: the log simply ENDS at the cancellation - no
    "Transcription cancelled by user", no ``transcribe_done`` - and
    ``<name>.txt.part`` (8416 B) and ``<name>.srt.part`` (16536 B) were left in
    the student's folder. Calling ``_clean_part_files`` by hand afterwards
    removed both instantly, which is what proved the sweep was never reached.

    Asserted on the AST, not on proximity: the previous guard only checked that
    ``_clean_part_files(`` appeared within 1800 characters of
    ``progress("transcribe_done")``, which stayed true the whole time the bug
    existed. Being in a ``finally`` is the property that actually matters.
    """
    import ast
    tree = ast.parse(RUNNER)

    def _line_span(nodes):
        lines = [ln for n in nodes for ln in
                 (getattr(x, "lineno", None) for x in ast.walk(n)) if ln]
        return (min(lines), max(lines)) if lines else None

    finally_spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.finalbody:
            span = _line_span(node.finalbody)
            if span:
                finally_spans.append(span)

    sweep_calls = [n.lineno for n in ast.walk(tree)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Name)
                   and n.func.id == "_clean_part_files"]
    assert sweep_calls, "the phase no longer sweeps .part sidecars at all"

    protected = [ln for ln in sweep_calls
                 if any(lo <= ln <= hi for lo, hi in finally_spans)]
    assert protected, (
        "no _clean_part_files() call in panopto/runner.py is inside a `finally`. "
        "A UI cancel raises BaseException through the transcription loop, so a "
        "sweep placed merely after the loop is skipped and the user is left with "
        "orphaned .txt.part/.srt.part files that nothing will ever remove.")


def test_the_delete_is_long_path_safe():
    """The one direction in this module that was not.

    Every WRITE already goes through ``make_long_path`` (the sidecars are opened
    with it and committed with it). ``os.remove`` did not - and that fails in the
    most misleading way available: on a default Windows install
    (``LongPathsEnabled = 0``, i.e. most users) a path over 260 characters raises
    ERROR_PATH_NOT_FOUND, which Python surfaces as ``FileNotFoundError``, which
    the handler reads as "already gone". Result: no removal, no retry, no log.

    The audit measured 259 paths over 255 characters in one course, and the two
    files actually left behind were 341. It did not bite on that machine only
    because it has ``LongPathsEnabled = 1``.

    Asserted by spying on what ``os.remove`` is HANDED, which is portable and is
    the property that makes it work on a stock install.
    """
    seen = []
    real_remove = os.remove

    def spy(path, *a, **kw):
        seen.append(str(path))
        return real_remove(path, *a, **kw)

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        mp3 = Path(d) / "Lecture.mp3"
        mp3.write_bytes(b"audio")
        (Path(d) / "Lecture.txt.part").write_text("half", encoding="utf-8")
        (Path(d) / "Lecture.srt.part").write_text("half", encoding="utf-8")
        os.remove = spy
        try:
            _clean_part_files(str(mp3), True, True)
        finally:
            os.remove = real_remove

    assert seen, "nothing was removed"
    if sys.platform == "win32":
        assert all(p.startswith("\\\\?\\") for p in seen), (
            f"os.remove was handed a bare path {seen!r}; on a default Windows "
            f"install a >260 char sidecar then reports FileNotFoundError, which "
            f"this function treats as success - so it is silently never removed")


def test_a_long_path_is_still_removed_when_the_bare_call_would_fail():
    """Emulates ``LongPathsEnabled = 0`` and proves the leftover still goes.

    The bare call is made to fail exactly as Windows fails it - with
    ``FileNotFoundError`` - which is precisely the error the retry loop treats as
    "already gone". So a fix that merely widened the except would still leave the
    file; only actually passing a usable path removes it.
    """
    real_remove = os.remove

    def strict(path, *a, **kw):
        p = str(path)
        if not p.startswith("\\\\?\\"):
            raise FileNotFoundError(3, "The system cannot find the path specified")
        return real_remove(p[4:] if p.startswith("\\\\?\\") else p, *a, **kw)

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        mp3 = Path(d) / "Lecture.mp3"
        mp3.write_bytes(b"audio")
        txt = Path(d) / "Lecture.txt.part"
        txt.write_text("half", encoding="utf-8")
        os.remove = strict
        try:
            _clean_part_files(str(mp3), True, False)
        finally:
            os.remove = real_remove
        assert not txt.exists(), (
            "the sidecar survived a remove that only accepts long-path form - "
            "which is what a stock Windows install does to a 341-char path")
