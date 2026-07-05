"""Tests for panopto.stream - cookie selection, size estimation, and the
ffmpeg download runner.

Two regressions guarded here:

1. Cookie selection previously kept only cookies whose domain contained the
   literal substring "panopto", silently dropping auth cookies on
   institutions that front Panopto with a vanity CNAME -> every download
   403'd while discovery worked.

2. ``_run_ffmpeg_download`` previously read the child's stderr only AFTER
   exit; a chatty remux could fill the OS pipe buffer, block ffmpeg on its
   own stderr write, and hang the download forever. The runner must drain
   stderr concurrently. The chatty-child test below writes ~1MB of stderr
   BEFORE producing its output file: old code deadlocks, fixed code passes.

The runner takes an arbitrary argv list, so the subprocess tests drive it
with small ``python -c`` children instead of a real ffmpeg binary.
"""

from __future__ import annotations

import concurrent.futures
import sys
import time
from types import SimpleNamespace

import pytest

from panopto.stream import (
    _cookie_domain_matches,
    _cookie_header,
    _input_headers,
    _run_ffmpeg_download,
    estimate_kind_size,
)

# Generous wall-clock cap: a deadlocked runner never returns, so every
# subprocess test runs under a watchdog that fails (not hangs) the suite.
WATCHDOG_SECS = 90


def run_with_watchdog(fn, *args, **kwargs):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn, *args, **kwargs)
        return fut.result(timeout=WATCHDOG_SECS)


# ── Cookie domain matching ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "cookie_domain, host, expected",
    [
        # Standard Panopto cloud tenancy
        (".cloud.panopto.eu", "uni.cloud.panopto.eu", True),
        ("uni.cloud.panopto.eu", "uni.cloud.panopto.eu", True),
        # Vanity CNAME (the regression): no "panopto" anywhere in the domain
        ("video.university.edu", "video.university.edu", True),
        (".university.edu", "video.university.edu", True),
        # Unrelated hosts must be excluded (Canvas / LTI intermediaries)
        ("canvas.university.edu", "video.university.edu", False),
        (".instructure.com", "uni.cloud.panopto.eu", False),
        # Suffix matching must be label-aligned, not substring
        ("opanopto.eu", "uni.cloud.panopto.eu", False),
        ("niversity.edu", "video.university.edu", False),
        # Degenerate cookie domains
        ("", "video.university.edu", False),
        # Host unavailable -> historical fallback keeps panopto-ish cookies
        (".cloud.panopto.eu", "", True),
        ("video.university.edu", "", False),
    ],
)
def test_cookie_domain_matches(cookie_domain, host, expected):
    assert _cookie_domain_matches(cookie_domain, host) is expected


def _fake_session(cookies):
    return SimpleNamespace(
        cookies=[SimpleNamespace(name=n, value=v, domain=d) for n, v, d in cookies]
    )


def test_cookie_header_vanity_cname_kept():
    session = _fake_session([
        ("ASPXAUTH", "secret1", "video.university.edu"),
        ("csrf", "secret2", ".university.edu"),
        ("canvas_session", "leakme", "canvas.instructure.com"),
    ])
    header = _cookie_header(session, "https://video.university.edu")
    assert "ASPXAUTH=secret1" in header
    assert "csrf=secret2" in header
    assert "canvas_session" not in header


def test_cookie_header_standard_cloud_tenancy():
    session = _fake_session([
        ("auth", "x", ".cloud.panopto.eu"),
        ("other", "y", "example.com"),
    ])
    header = _cookie_header(session, "https://cbs.cloud.panopto.eu")
    assert header == "auth=x"


def test_cookie_header_unparseable_base_falls_back_to_substring():
    session = _fake_session([
        ("auth", "x", ".cloud.panopto.eu"),
        ("other", "y", "video.university.edu"),
    ])
    # No hostname extractable -> keep the historical panopto-substring filter
    header = _cookie_header(session, "not a url")
    assert "auth=x" in header
    assert "other" not in header


def test_input_headers_carry_cookie_and_referer():
    args = _input_headers("a=1; b=2", "https://video.university.edu")
    assert args[0] == "-headers"
    assert "Cookie: a=1; b=2\r\n" in args[1]
    assert "Referer: https://video.university.edu/\r\n" in args[1]


def test_input_headers_without_cookies_still_send_referer():
    args = _input_headers("", "https://x.y")
    assert "Cookie:" not in args[1]
    assert "Referer: https://x.y/" in args[1]


# ── Size estimation ──────────────────────────────────────────────────────────

def test_estimate_audio_exact_cbr():
    # 128 kbit/s * 60 s / 8 = 960,000 bytes
    assert estimate_kind_size("mp3", 60) == 960_000


def test_estimate_video_approximation():
    assert estimate_kind_size("mp4", 60) == int(60 * 1_500_000 / 8)


@pytest.mark.parametrize("kind", ["txt", "srt", "unknown"])
def test_unestimatable_kinds_return_none(kind, ):
    assert estimate_kind_size(kind, 600) is None


@pytest.mark.parametrize("duration", [0, -5, None, "garbage"])
def test_bad_durations_return_none(duration):
    assert estimate_kind_size("mp3", duration) is None


# ── ffmpeg runner (driven with python -c stand-ins) ──────────────────────────

def test_chatty_stderr_does_not_deadlock(tmp_path):
    """THE deadlock regression: >1MB of stderr before the output appears."""
    out = tmp_path / "lecture.mp3"
    child = (
        "import sys\n"
        "chunk = b'warning: Non-monotonous DTS in output stream 0:0\\n' * 20000\n"
        "sys.stderr.buffer.write(chunk)\n"       # ~0.9MB >> 64KB pipe buffer
        "sys.stderr.buffer.flush()\n"
        "open(sys.argv[1], 'wb').write(b'x' * 2048)\n"
    )
    ok, err = run_with_watchdog(
        _run_ffmpeg_download,
        [sys.executable, "-c", child, str(out)],
        str(out),
    )
    assert ok is True and err is None
    assert out.stat().st_size == 2048


def test_failure_surfaces_stderr_tail(tmp_path):
    out = tmp_path / "lecture.mp3"
    child = (
        "import sys\n"
        "sys.stderr.write('boom: HTTP error 403 Forbidden\\n')\n"
        "sys.exit(1)\n"
    )
    ok, err = run_with_watchdog(
        _run_ffmpeg_download,
        [sys.executable, "-c", child, str(out)],
        str(out),
    )
    assert ok is False
    assert "403 Forbidden" in err          # the actionable reason, not just a code
    assert "code 1" in err


def test_empty_output_is_failure_and_removed(tmp_path):
    out = tmp_path / "lecture.mp3"
    child = "import sys\nopen(sys.argv[1], 'wb').close()\n"   # exit 0, 0 bytes
    ok, err = run_with_watchdog(
        _run_ffmpeg_download,
        [sys.executable, "-c", child, str(out)],
        str(out),
    )
    assert ok is False
    assert "empty" in err.lower()
    assert not out.exists()                 # partial artifact cleaned up


def test_cancel_terminates_child_and_cleans_partial(tmp_path):
    out = tmp_path / "lecture.mp3"
    child = (
        "import sys, time\n"
        "open(sys.argv[1], 'wb').write(b'partial')\n"
        "time.sleep(60)\n"
    )
    t0 = time.time()
    ok, err = run_with_watchdog(
        _run_ffmpeg_download,
        [sys.executable, "-c", child, str(out)],
        str(out),
        is_cancelled=lambda: True,
    )
    assert ok is False and err == "cancelled"
    assert time.time() - t0 < 30            # terminated, not waited out
    assert not out.exists()                 # partial file removed


def test_unlaunchable_command_returns_clean_error(tmp_path):
    out = tmp_path / "x.mp3"
    ok, err = run_with_watchdog(
        _run_ffmpeg_download,
        ["definitely-not-a-real-binary-xyz"],
        str(out),
    )
    assert ok is False
    assert "launch failed" in err
