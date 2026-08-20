"""A conversion failure gets one retry, then a reason - in BOTH flows.

Most conversion failures are transient: a destination locked for a few seconds
by an editor, an antivirus handle, a COM hiccup. The pipeline used to record all
of them as permanent, so the completion screen said "N files failed during
post-processing" and the user had to open download_errors.txt to find a generic
"Conversion failed" with no cause.

Measured on course 43660: a converted `.txt` left read-only made the converter
raise ``[Errno 13] Permission denied`` and the run reported two failures with no
indication that closing one file would fix both.

The retry needs nothing from the nine individual runners, because every
source-consuming converter DELETES its source on success - so a source still on
disk after a pass IS the failure set. That single signal is what lets one pass
at the end cover every converter, in the download flow and the sync flow alike.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from converters.post_processing import (  # noqa: E402
    _is_locked, _locked_sibling, _still_present, retry_failed_conversions,
)

DOWNLOAD = (REPO / "converters" / "post_processing.py").read_text(encoding="utf-8")
SYNC = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")


class _UI:
    """The parts of UIBridge the retry touches."""
    def __init__(self, fail_count=0):
        self.pp_failure_count = fail_count
        self.pp_success_count = 0
        self.log_lines = []
        self.error_log_path = None
        self.emitted = []
        self.is_cancelled = lambda: False
        self.active_file_placeholder = type("P", (), {"empty": lambda s: None})()
        self.log_placeholder = type("P", (), {"markdown": lambda s, *a, **k: None})()


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """The retry emits UI rows; capture them instead of rendering."""
    import converters.post_processing as pp
    monkeypatch.setattr(pp, "_emit", lambda ui, kind, msg="", **kw:
                        ui.emitted.append((kind, msg, kw)))
    monkeypatch.setattr(pp, "_log_error_to_file", lambda *a, **k: None)


# --------------------------------------------------------------------------
# the lock probe
# --------------------------------------------------------------------------

def test_a_missing_file_is_not_locked(tmp_path):
    assert _is_locked(tmp_path / "nope.txt") is False


def test_an_ordinary_file_is_not_locked(tmp_path):
    p = tmp_path / "fine.txt"
    p.write_text("x", encoding="utf-8")
    assert _is_locked(p) is False


def test_the_probe_does_not_truncate_what_it_opens(tmp_path):
    p = tmp_path / "precious.txt"
    p.write_text("keep me", encoding="utf-8")
    _is_locked(p)
    assert p.read_text(encoding="utf-8") == "keep me"


def test_the_probe_handles_bytes_that_are_not_utf8(tmp_path):
    p = tmp_path / "binary.pdf"
    p.write_bytes(b"\xff\xfe\x00\x01not utf-8 at all")
    assert _is_locked(p) is False


def test_the_locked_sibling_is_found_by_stem(tmp_path, monkeypatch):
    src = tmp_path / "code.py"
    src.write_text("print(1)", encoding="utf-8")
    out = tmp_path / "code_py.txt"
    out.write_text("converted", encoding="utf-8")
    import converters.post_processing as pp
    monkeypatch.setattr(pp, "_is_locked", lambda p: p.name == "code_py.txt")
    assert pp._locked_sibling(src) == out


def test_the_source_itself_is_never_reported_as_the_locked_sibling(tmp_path,
                                                                  monkeypatch):
    src = tmp_path / "code.py"
    src.write_text("print(1)", encoding="utf-8")
    import converters.post_processing as pp
    monkeypatch.setattr(pp, "_is_locked", lambda p: True)
    assert pp._locked_sibling(src) is None


def test_a_stem_with_glob_characters_does_not_break_the_search(tmp_path):
    """Course material is full of brackets: "Lecture [2] (final).pptx"."""
    src = tmp_path / "Lecture [2] (final).pptx"
    src.write_text("x", encoding="utf-8")
    assert _locked_sibling(src) is None      # must not raise


# --------------------------------------------------------------------------
# the retry
# --------------------------------------------------------------------------

def _item(p):
    return (p, None, "Course")


def test_nothing_left_on_disk_means_nothing_to_retry(tmp_path):
    gone = tmp_path / "converted-away.py"
    ui = _UI()
    calls = []
    assert retry_failed_conversions([(lambda i, u: calls.append(i), [_item(gone)])],
                                    ui) == []
    assert calls == [], "a converter was re-run for a file that had succeeded"


def test_a_file_that_converts_on_the_second_attempt_is_not_reported(tmp_path):
    src = tmp_path / "code.py"
    src.write_text("x", encoding="utf-8")
    ui = _UI(fail_count=1)

    def runner(items, _ui):
        for it in items:
            Path(it[0]).unlink()          # succeeds this time

    assert retry_failed_conversions([(runner, [_item(src)])], ui) == []
    assert ui.pp_failure_count == 0, "a recovered file is still counted as failed"


def test_a_file_that_fails_twice_is_reported_once(tmp_path):
    src = tmp_path / "code.py"
    src.write_text("x", encoding="utf-8")
    ui = _UI(fail_count=1)

    def runner(items, _ui):
        _ui.pp_failure_count += len(items)   # what a real runner does

    still = retry_failed_conversions([(runner, [_item(src)])], ui)
    assert [Path(i[0]).name for i in still] == ["code.py"]
    assert ui.pp_failure_count == 1, \
        "the retry double-counted the same file as two failures"


def test_the_second_failure_names_the_locked_file(tmp_path, monkeypatch):
    src = tmp_path / "code.py"
    src.write_text("x", encoding="utf-8")
    out = tmp_path / "code_py.txt"
    out.write_text("half", encoding="utf-8")
    import converters.post_processing as pp
    monkeypatch.setattr(pp, "_is_locked", lambda p: p.name == "code_py.txt")

    ui = _UI(fail_count=1)
    pp.retry_failed_conversions([(lambda i, u: None, [_item(src)])], ui)
    errors = [e for e in ui.emitted if e[0] == "error"]
    assert errors, "nothing was reported for a file that failed twice"
    assert "code_py.txt" in errors[0][2].get("detail", ""), \
        "the reason must name the file the user has to close"


def test_an_unexplained_second_failure_still_says_it_was_retried(tmp_path):
    src = tmp_path / "code.py"
    src.write_text("x", encoding="utf-8")
    ui = _UI(fail_count=1)
    retry_failed_conversions([(lambda i, u: None, [_item(src)])], ui)
    errors = [e for e in ui.emitted if e[0] == "error"]
    assert "twice" in errors[0][2].get("detail", "").lower()


def test_a_crashing_runner_never_takes_down_the_run(tmp_path):
    src = tmp_path / "code.py"
    src.write_text("x", encoding="utf-8")

    def boom(_items, _ui):
        raise RuntimeError("COM went away")

    still = retry_failed_conversions([(boom, [_item(src)])], _UI(fail_count=1))
    assert [Path(i[0]).name for i in still] == ["code.py"]


def test_still_present_survives_a_malformed_item():
    assert _still_present(("", None, "")) is False
    assert _still_present(None) is False


# --------------------------------------------------------------------------
# both flows, one mechanism
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["download", "sync"])
def test_both_flows_run_the_retry_pass(name):
    src = DOWNLOAD if name == "download" else SYNC
    assert "retry_failed_conversions(_attempts" in src, \
        f"the {name} flow does not retry failed conversions"


@pytest.mark.parametrize("runner", [
    "run_pptx_conversion", "run_html_conversion", "run_code_conversion",
    "run_word_conversion", "run_excel_conversion", "run_video_conversion",
])
@pytest.mark.parametrize("name", ["download", "sync"])
def test_every_source_consuming_converter_is_registered(runner, name):
    src = DOWNLOAD if name == "download" else SYNC
    assert f"_attempts.append(({runner}" in src, \
        f"{runner} is missing from the {name} flow's retry set"


# ---------------------------------------------------------------------------
# A phase that ABORTED on a FATAL condition must not be retried
# ---------------------------------------------------------------------------
#
# Measured in the PACKAGED app on macOS 26.6.1 (2026-08-20) with Automation for
# Microsoft Word genuinely DENIED - the first time that state has ever been
# driven on a Mac. One `.doc` produced:
#
#     [AppleScript] Word failed (permission): ... Not authorised to send Apple
#                   events to Microsoft Word. (-1743)
#     Klyngevejledning_1_Program_2023.doc  Conversion failed - macOS blocked ...
#     macOS blocked Canvas Downloader ...  skipping remaining 0 Word file(s)
#     [AppleScript] Word failed (permission): ...            <- the RETRY
#     Klyngevejledning_1_Program_2023.doc  Conversion failed - macOS blocked ...
#     macOS blocked Canvas Downloader ...  skipping remaining 0 Word file(s)
#     Klyngevejledning_1_Program_2023.doc  Conversion failed twice
#
# i.e. 3 per-file errors and **2 aborts for ONE file**, corroborated from a
# different oracle by the health record's `failures={'osascript_permission': 2}`.
#
# The retry is right for a locked destination and wrong here. `permission` and
# `app_missing` are in FATAL_CATEGORIES precisely because they "will identically
# doom every remaining file in the phase", so a second attempt cannot succeed -
# it only emits the one actionable message twice, defeating the purpose of
# `_abort_applescript_phase`, and then labels the file "Conversion failed twice",
# which blames the document for a machine-wide permission state.

import converters.post_processing as pp  # noqa: E402


class _UIAborted(_UI):
    def __init__(self, phases=(), fail_count=0):
        super().__init__(fail_count=fail_count)
        self.aborted_phases = set(phases)


def _named(name, sink):
    """A stand-in runner carrying the __name__ the phase map keys on."""
    def _runner(items, ui):
        sink.append(name)
    _runner.__name__ = name
    return _runner


def test_the_aborted_phase_is_not_retried(tmp_path):
    src = tmp_path / "Lecture.doc"
    src.write_bytes(b"legacy")           # still present == it failed
    calls = []
    ui = _UIAborted(phases={"Word"})
    retry_failed_conversions([(_named("run_word_conversion", calls), [_item(src)])], ui)
    assert calls == [], (
        "the Word phase aborted on a fatal condition and was retried anyway - "
        "the user gets the actionable permission message twice and the file is "
        "labelled 'Conversion failed twice'")


def test_an_unaffected_phase_is_STILL_retried(tmp_path):
    """The skip is per phase. A Word denial says nothing about other runners.

    This is the half that makes the fix safe: `permission` is granted per
    (client, target app), and most runners use no AppleScript at all.
    """
    src = tmp_path / "page.html"
    src.write_bytes(b"<p>x</p>")
    calls = []
    ui = _UIAborted(phases={"Word"})
    retry_failed_conversions([(_named("run_html_conversion", calls), [_item(src)])], ui)
    assert calls == ["run_html_conversion"], (
        "an unrelated phase stopped being retried because a DIFFERENT phase "
        "aborted - the skip must be per phase, not global")


def test_excel_is_not_skipped_when_only_word_was_denied(tmp_path):
    src = tmp_path / "Book.xls"
    src.write_bytes(b"xls")
    calls = []
    ui = _UIAborted(phases={"Word"})
    retry_failed_conversions([(_named("run_excel_conversion", calls), [_item(src)])], ui)
    assert calls == ["run_excel_conversion"], (
        "Automation is granted per (client, target app), so a Word denial is "
        "not evidence about Excel")


def test_the_phase_still_retries_when_nothing_aborted(tmp_path):
    src = tmp_path / "Lecture.doc"
    src.write_bytes(b"legacy")
    calls = []
    retry_failed_conversions([(_named("run_word_conversion", calls), [_item(src)])],
                             _UIAborted(phases=()))
    assert calls == ["run_word_conversion"], (
        "the ordinary transient-failure retry was lost")


def test_a_bridge_without_the_field_still_retries(tmp_path):
    """Never let bookkeeping break a caller that predates the field."""
    src = tmp_path / "Lecture.doc"
    src.write_bytes(b"legacy")
    calls = []
    retry_failed_conversions([(_named("run_word_conversion", calls), [_item(src)])],
                             _UI())          # no aborted_phases attribute at all
    assert calls == ["run_word_conversion"]


def test_the_abort_records_its_phase_on_the_bridge():
    ui = _UIAborted()
    pp._abort_applescript_phase(ui, "macOS blocked ...", 0, "Word")
    assert "Word" in ui.aborted_phases, (
        "the abort is the one place that knows WHICH phase died and why; if it "
        "does not record that, the retry cannot decline")


def test_the_abort_survives_a_bridge_that_cannot_record():
    """A stand-in bridge must not be broken by the bookkeeping."""
    ui = _UI()                                # no aborted_phases
    pp._abort_applescript_phase(ui, "macOS blocked ...", 2, "Excel")
    assert ui.pp_failure_count == 2, "the abort's real work stopped happening"


def test_every_abort_label_is_in_the_phase_map():
    """A new Office phase must appear in both places or the skip silently lapses."""
    import ast, re
    labels = set(re.findall(r'_abort_applescript_phase\([^)]*?"([A-Za-z]+)"\)', DOWNLOAD))
    assert labels, "no _abort_applescript_phase call sites found - anchor moved"
    assert labels <= set(pp._RUNNER_PHASE.values()), (
        f"these phases abort but are not in _RUNNER_PHASE, so their retry is "
        f"never skipped: {labels - set(pp._RUNNER_PHASE.values())}")


def test_the_phase_map_names_real_runners():
    for fn_name in pp._RUNNER_PHASE:
        assert hasattr(pp, fn_name), (
            f"_RUNNER_PHASE names {fn_name!r}, which does not exist - the map "
            f"keys on __name__, so a rename makes the skip silently stop working")
