"""A video with no audio track becomes a PDF of screenshots, not a failure.

Reported 2026-10-09 by the product owner on a "100% AI & NotebookLM Ready"
download: four macOS ReplayKit screen recordings (3440x1440 h264, NO audio
stream) were each reported as "Audio extraction failed" - twice, because the
retry pass re-ran a conversion that could not change - stayed as .mov, and then
NotebookLM REJECTED the drag of the whole folder because it takes no .mov.

What such a recording carries is on screen, so it becomes one PDF of its
distinct screens. Measured on the four real files: 6 / 12 / 13 / 16 pages,
2.0-5.5 MB against 54-124 MB, ~15-30 s each, full-resolution frames.

The test videos are generated with the bundled ffmpeg's lavfi sources, so this
needs no fixture files and runs anywhere the app's ffmpeg does.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import converters.video as video  # noqa: E402
import converters.post_processing as pp  # noqa: E402


def _ff(*args):
    subprocess.run([video._ffmpeg(), "-loglevel", "error", "-y", *args],
                   check=True, timeout=120)


def _silent_three_screens(path: Path) -> Path:
    """Three solid colours, 2 s each, no audio: three distinct screens."""
    _ff("-f", "lavfi", "-i", "color=c=red:s=320x180:d=2:r=10",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2:r=10",
        "-f", "lavfi", "-i", "color=c=white:s=320x180:d=2:r=10",
        "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))
    return path


def _with_audio(path: Path) -> Path:
    _ff("-f", "lavfi", "-i", "color=c=red:s=320x180:d=2:r=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(path))
    return path


def _pdf_pages(path: Path) -> int:
    # No PDF library is a runtime dependency, so read the page tree directly.
    # NOT a count of `/Type /Page` objects: each `append` is an incremental
    # update that writes the tree again, so earlier pages appear more than
    # once. The LAST `/Count` is the page tree a reader actually uses.
    import re
    return int(re.findall(rb"/Count\s+(\d+)", path.read_bytes())[-1])


# ── the probe ────────────────────────────────────────────────────────────────

def test_the_probe_sees_a_silent_video_as_silent(tmp_path):
    assert video.has_audio_track(_silent_three_screens(tmp_path / "s.mov")) is False


def test_the_probe_sees_audio_where_there_is_some(tmp_path):
    """The positive control - without it `False` could be a probe that always says no."""
    assert video.has_audio_track(_with_audio(tmp_path / "a.mp4")) is True


def test_an_unreadable_file_is_unknown_not_silent(tmp_path):
    """None, never False: an unreadable 'video' must not become a PDF of nothing."""
    junk = tmp_path / "junk.mov"
    junk.write_bytes(b"this is not a video")
    assert video.has_audio_track(junk) is None


# ── the converter ────────────────────────────────────────────────────────────

def test_a_silent_video_becomes_one_pdf_page_per_screen(tmp_path):
    src = _silent_three_screens(tmp_path / "rec.mov")
    out = video.convert_silent_video_to_pdf(src)
    assert out is not None
    pdf = Path(out)
    assert pdf.name == "rec.pdf"
    from converters.verify import pdf_looks_real
    assert pdf_looks_real(pdf) == (True, "")
    assert _pdf_pages(pdf) == 3, "one page per distinct screen"
    assert not src.exists(), "the proven PDF replaces the video, like the MP3 does"
    assert not list(tmp_path.glob("*.part")), "no partial file left behind"


def test_an_explicit_destination_is_honoured(tmp_path):
    """The caller passes `_resolve_conversion_target`'s answer - e.g. `rec (1).pdf`
    when a teacher's own `rec.pdf` sits beside the video. Writing to the default
    name instead would overwrite their slides."""
    src = _silent_three_screens(tmp_path / "rec.mov")
    slides = tmp_path / "rec.pdf"
    slides.write_bytes(b"%PDF-teacher slides")
    out = video.convert_silent_video_to_pdf(src, dst=tmp_path / "rec (1).pdf")
    assert Path(out).name == "rec (1).pdf"
    assert slides.read_bytes() == b"%PDF-teacher slides"


def test_an_unproven_pdf_keeps_the_video(tmp_path, monkeypatch):
    """The video is the larger, less replaceable file: it goes only on proof."""
    import converters.verify as verify
    monkeypatch.setattr(verify, "pdf_looks_real", lambda p: (False, "stub"))
    src = _silent_three_screens(tmp_path / "rec.mov")
    assert video.convert_silent_video_to_pdf(src) is None
    assert src.exists()
    assert not (tmp_path / "rec.pdf").exists()
    assert not list(tmp_path.glob("*.part"))


def test_cancel_keeps_the_video_and_writes_nothing(tmp_path):
    src = _silent_three_screens(tmp_path / "rec.mov")
    assert video.convert_silent_video_to_pdf(src, is_cancelled=lambda: True) is None
    assert src.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rec.mov"]


def test_cancel_stops_the_ANALYSIS(tmp_path):
    """The analysis decodes the whole video - minutes on a long lecture - so a
    cancel must stop the decode itself, not wait for it to finish."""
    src = _silent_three_screens(tmp_path / "rec.mov")
    assert video._keyframe_indices(str(src), is_cancelled=lambda: True) is None


def test_cancel_stops_the_PDF_WRITE(tmp_path, monkeypatch):
    """A cancel that lands after the analysis (it is the fast half) must still
    stop the page writes and leave no partial PDF."""
    src = _silent_three_screens(tmp_path / "rec.mov")
    monkeypatch.setattr(video, "_keyframe_indices", lambda p, c=None: [0, 9])
    assert video.convert_silent_video_to_pdf(src, is_cancelled=lambda: True) is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rec.mov"]


def test_a_screen_in_MOTION_is_not_captured_only_the_settled_one(tmp_path):
    """A scroll or a fade is not a page; the screen it settles on is.

    Hard cuts cannot tell this apart - every sample is either one screen or the
    other - so the transition here is a one-second fade. Without the settle
    check the first samples of the fade cross the change threshold and a
    half-faded frame becomes a page, then the rest of the fade makes another.
    """
    src = tmp_path / "fade.mov"
    _ff("-f", "lavfi", "-i", "color=c=red:s=320x180:d=3:r=10",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=3:r=10",
        "-filter_complex", "[0][1]xfade=transition=fade:duration=1:offset=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src))
    idx = video._keyframe_indices(str(src))
    assert len(idx) == 2, f"expected red + blue, got samples {idx}"
    assert idx[1] / video._FRAME_SAMPLE_FPS >= 3.0, "the blue page was taken mid-fade"


def test_a_long_recording_is_thinned_evenly_not_cut_off(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "_MAX_PAGES", 2)
    src = _silent_three_screens(tmp_path / "rec.mov")
    idx = video._keyframe_indices(str(src))
    assert len(idx) == 2
    assert idx[0] == 0, "the opening screen survives thinning"
    assert idx[-1] >= 8, "the LAST screen survives thinning (white, from 4 s on)"


# ── the runner: which path a video takes ─────────────────────────────────────

class _UI:
    def __init__(self):
        self.pp_failure_count = 0
        self.pp_success_count = 0
        self.error_log_path = None
        self.emitted = []
        self.on_detail_update = None
        self.is_cancelled = lambda: False
        self.active_file_placeholder = type("P", (), {"empty": lambda s: None})()


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(pp, "_emit", lambda ui, kind, msg="", **kw:
                        ui.emitted.append((kind, msg, kw)))
    monkeypatch.setattr(pp, "_log_error_to_file", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_render_dashboard", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_show_active_file", lambda *a, **k: None)
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)


def _route(monkeypatch, tmp_path, audio):
    calls = []
    monkeypatch.setattr(video, "has_audio_track", lambda p: audio)
    monkeypatch.setattr(video, "convert_video_to_mp3",
                        lambda p, dst=None: calls.append("mp3") or None)
    monkeypatch.setattr(video, "convert_silent_video_to_pdf",
                        lambda p, dst=None, is_cancelled=None: calls.append("pdf") or None)
    src = tmp_path / "rec.mov"
    src.write_bytes(b"x")
    ui = _UI()
    pp.run_video_conversion([(src, None, None)], ui)
    return calls, ui


def test_the_runner_sends_a_silent_video_to_screenshots(quiet, monkeypatch, tmp_path):
    calls, ui = _route(monkeypatch, tmp_path, False)
    assert calls == ["pdf"]
    assert ui.pp_failure_count == 1   # the stub fails; it must be COUNTED, not hidden


def test_the_runner_still_extracts_audio_where_there_is_some(quiet, monkeypatch, tmp_path):
    assert _route(monkeypatch, tmp_path, True)[0] == ["mp3"]


def test_an_unknown_probe_takes_the_mp3_path(quiet, monkeypatch, tmp_path):
    """`is False`, not falsy: None must fail honestly as an MP3, never become a PDF."""
    assert _route(monkeypatch, tmp_path, None)[0] == ["mp3"]


def test_the_runner_converts_a_real_silent_video_end_to_end(quiet, tmp_path):
    src = _silent_three_screens(tmp_path / "rec.mov")
    ui = _UI()
    pp.run_video_conversion([(src, None, None)], ui)
    assert (tmp_path / "rec.pdf").exists() and not src.exists()
    assert (ui.pp_success_count, ui.pp_failure_count) == (1, 0)
    assert ui.emitted[-2][0] == "success"


# ── the NotebookLM preset: one flat folder, everything in it ─────────────────

def _notebooklm_presets():
    from core.preset_manager import PresetManager
    from ui.quick_download import _QUICK_PRESETS
    builtin = next(p for p in PresetManager._BUILTIN_PRESETS
                   if p["preset_id"] == "builtin_notebooklm")["settings"]
    quick = next(p for p in _QUICK_PRESETS if p["id"] == "quick_notebooklm")["settings"]
    return {"builtin": builtin, "quick": quick}


@pytest.mark.parametrize("which", ["builtin", "quick"])
def test_the_notebooklm_preset_puts_canvas_content_in_the_course_folder(which):
    s = _notebooklm_presets()[which]
    assert s["download_mode"] == "flat"
    assert s["dl_isolate_secondary"] is False, (
        "isolate puts Assignments/, Announcements/... in subfolders, which a "
        "NotebookLM drag of the course folder leaves out")


@pytest.mark.parametrize("which", ["builtin", "quick"])
def test_the_notebooklm_preset_puts_panopto_audio_in_the_course_folder(which, tmp_path):
    """Asserted through the runner's own resolver, not by the setting's name."""
    from panopto.runner import video_dir
    s = _notebooklm_presets()[which]
    out = video_dir(tmp_path, "Week 1", {"layout": s["pan_layout"]}, s["download_mode"],
                    lecture_title_sanitized="Lecture 1")
    assert out == tmp_path
