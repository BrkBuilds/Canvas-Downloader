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

def test_the_phase_sweeps_partials_however_it_ends():
    """The loop has several exits; sweeping per-exit is how one got missed."""
    i = RUNNER.find('progress("transcribe_done"')
    assert i > 0, "the transcription phase moved; re-verify against a real cancel"
    tail = RUNNER[i:i + 1800]
    assert "_clean_part_files(" in tail, (
        "the phase no longer sweeps .part sidecars on the way out - a cancel "
        "caught at the loop head leaves them in the user's course folder")
    assert "tx_tasks" in tail, "the sweep must cover every target, not just one"


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
    i = RUNNER.find('progress("transcribe_done"')
    assert marker in RUNNER[i:i + 1800]
