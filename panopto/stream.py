"""Panopto stream resolution + audio/video download via the bundled ffmpeg.

``DeliveryInfo.aspx`` returns the stream URL(s) for a video given an
authenticated Panopto session. The "podcast" stream is a single combined
MP4 (primary view + audio); we either transcode its audio to MP3, or remux the
whole stream to a kept MP4. Both use the ffmpeg binary that ships with the app
(imageio_ffmpeg) - never relying on a system PATH ffmpeg.
"""

from __future__ import annotations

import html as _html
import logging
import os
import re
import subprocess
import sys
import time

from shared.helpers import make_long_path, PANOPTO_UNAVAILABLE_REASON

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_error(msg) -> str:
    """Normalize a Panopto error message to plain text.

    ``DeliveryInfo`` returns its ``ErrorMessage`` as an HTML fragment (e.g.
    ``This session isn't available. It may have been deleted.<br><a
    href='/Panopto/Pages/Sessions/List.aspx'>See other videos</a>``) - raw
    markup that would otherwise surface verbatim in the live UI log and
    debug_log.txt. Strip the tags, unescape entities and collapse whitespace
    at the SOURCE so every consumer gets readable text.
    """
    text = _html.unescape(_TAG_RE.sub(" ", str(msg or "")))
    return re.sub(r"\s+", " ", text).strip()


# Panopto's DeliveryInfo returns operator-facing error copy - most commonly
# "This session isn't available. It may have been deleted." trailed by a
# "See other videos" link into Panopto's own web UI. Once _clean_error has
# stripped the tags, that anchor text survives as a dangling "See other videos"
# that points nowhere in this app, and "session" is Panopto's word, not a
# student's. This maps the well-known "the recording is gone" family to one
# plain sentence a student can act on, and drops a trailing "See other videos"
# from anything else. Everything unrecognised passes through unchanged.
_SEE_OTHER_VIDEOS_RE = re.compile(r"\s*See other videos\.?\s*$", re.IGNORECASE)


def friendly_stream_error(msg) -> str:
    """Turn a raw Panopto stream/delivery error into student-facing text.

    Idempotent: safe to call on a message that has already been cleaned or
    friendlied (its own output re-matches the "no longer available" branch).
    """
    text = _clean_error(msg)
    low = text.lower()
    if ("isn't available" in low or "is not available" in low
            or "may have been deleted" in low or "no longer available" in low):
        # The shared constant, so the classifier (split_delivery_errors) can
        # recognise this exact reason and treat the recording as a permanent
        # decline rather than a retriable failure.
        return PANOPTO_UNAVAILABLE_REASON
    return _SEE_OTHER_VIDEOS_RE.sub("", text).strip()


def ffmpeg_exe() -> str:
    """Return the path to the bundled ffmpeg binary (PyInstaller-aware).

    Mirrors video_converter.py's resolution so frozen builds use the binary in
    the bundle, falling back to imageio_ffmpeg's copy in dev, then PATH.
    """
    try:
        import imageio_ffmpeg
        if getattr(sys, "frozen", False):
            name = os.path.basename(imageio_ffmpeg.get_ffmpeg_exe())
            cand = os.path.join(sys._MEIPASS, "imageio_ffmpeg", "binaries", name)
            if os.path.exists(cand):
                return cand
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        logger.warning(f"Bundled ffmpeg not found ({e}); falling back to PATH 'ffmpeg'.")
        return "ffmpeg"


def get_delivery_info(session, panopto_base: str, video_id: str):
    """Return (delivery_dict, error_str). delivery_dict is the 'Delivery' node."""
    url = f"{panopto_base}/Panopto/Pages/Viewer/DeliveryInfo.aspx"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": panopto_base,
        "Referer": f"{panopto_base}/Panopto/Pages/Viewer.aspx?id={video_id}",
    }
    body = f"deliveryId={video_id}&isEmbed=true&responseType=json"
    try:
        r = session.post(url, data=body, headers=headers, timeout=30)
        status = r.status_code
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.info("Panopto DeliveryInfo failed for %s: %s", video_id, e)
        return None, str(e)

    if data.get("ErrorCode"):
        # Keep the raw (tag-stripped) message in the log for diagnostics, but
        # hand callers the student-facing rewrite - this is what reaches the
        # completion screen and Sync History as the failure reason.
        raw = _clean_error(
            data.get("ErrorMessage", f"ErrorCode {data.get('ErrorCode')}"))
        logger.info("Panopto DeliveryInfo error for %s: %s", video_id, raw)
        return None, friendly_stream_error(raw)
    delivery = data.get("Delivery", {}) or {}
    logger.debug(
        "Panopto DeliveryInfo %s: HTTP %s, duration=%.0fs, podcast=%d streams=%d",
        video_id, status, delivery_duration(delivery),
        len(delivery.get("PodcastStreams", []) or []),
        len(delivery.get("Streams", []) or []),
    )
    return delivery, None


def pick_audio_stream(delivery: dict) -> str | None:
    """Pick the best audio stream URL from a Delivery node."""
    for key in ("PodcastStreams", "Streams"):
        streams = delivery.get(key, []) or []
        if streams:
            u = streams[0].get("StreamUrl")
            if u:
                return u
    return None


# ── Size estimation (for the sync review / confirm UI before a download) ──────
# Recordings that aren't downloaded yet have no file on disk to measure, so we
# estimate from the recording's duration. Audio is CBR so the estimate is exact;
# video bitrate varies, so the video figure is an approximation (shown as "~").
# How long a running ffmpeg may produce NO new bytes before it is treated as
# wedged. Generous on purpose: it must clear the initial connect + HLS manifest
# fetch on a slow link, and a lecture that is merely downloading slowly is still
# growing its .part file and so never trips it.
_STALL_TIMEOUT_SECONDS = 180

_AUDIO_BITS_PER_SEC = 128_000          # matches download_audio_mp3's -ab 128k
_VIDEO_BITS_PER_SEC = 1_500_000        # ~1.5 Mbps: typical mixed lecture


def estimate_kind_size(kind: str, duration_sec: float) -> int | None:
    """Estimate the on-disk byte size of a not-yet-downloaded output.

    Returns None for kinds we can't meaningfully estimate (txt/srt transcripts
    are tiny and length-dependent, so they're only sized once on disk).
    """
    try:
        d = float(duration_sec or 0.0)
    except (TypeError, ValueError):
        d = 0.0
    if d <= 0:
        return None
    if kind == "mp3":
        return int(d * _AUDIO_BITS_PER_SEC / 8)
    if kind == "mp4":
        return int(d * _VIDEO_BITS_PER_SEC / 8)
    return None


def _delivery_info_via_cookies(cookie_header: str, panopto_base: str, video_id: str):
    """Thread-safe DeliveryInfo lookup using a pre-snapshotted cookie string.

    Unlike :func:`get_delivery_info` this never touches a shared
    ``requests.Session`` (whose cookie jar is NOT thread-safe) - each call is a
    standalone ``requests.post`` carrying the auth cookies explicitly, so any
    number of worker threads can run it concurrently. Returns
    ``(delivery_dict, error_str)``.
    """
    import requests as _requests

    url = f"{panopto_base}/Panopto/Pages/Viewer/DeliveryInfo.aspx"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": panopto_base,
        "Referer": f"{panopto_base}/Panopto/Pages/Viewer.aspx?id={video_id}",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    body = f"deliveryId={video_id}&isEmbed=true&responseType=json"
    try:
        r = _requests.post(url, data=body, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.debug("Panopto DeliveryInfo (cookie mode) failed for %s: %s", video_id, e)
        return None, str(e)
    if data.get("ErrorCode"):
        return None, _clean_error(
            data.get("ErrorMessage", f"ErrorCode {data.get('ErrorCode')}"))
    return data.get("Delivery", {}) or {}, None


def fetch_durations(cm, videos, *, is_cancelled=None, max_workers: int = 10) -> dict:
    """Return {video_id: duration_seconds} for *videos*, fetched concurrently.

    Authenticates to Panopto ONCE (one LTI handshake), snapshots the session's
    auth cookies into a plain string ON THIS THREAD, then pulls each
    recording's DeliveryInfo in a small thread pool via standalone requests
    (H-5: ``requests.Session`` is not thread-safe - the pool must never share
    one; the runner's download path already follows this cookie-snapshot rule).
    Best-effort: a recording whose duration can't be resolved is simply absent
    from the result (its size is then shown as unknown rather than estimated).
    Never raises.
    """
    from panopto.auth import lti_launch

    out: dict = {}
    videos = list(videos or [])
    if not videos:
        return out

    # Discovery-verified beacons first, then per-video launch URLs (legacy
    # items can carry launch URLs whose LTI chain no longer completes).
    session = panopto_base = None
    _candidates: list = []
    for v in videos:
        _beacon = getattr(v, "auth_launch_url", "")
        if _beacon and "sessionless_launch" in _beacon and _beacon not in _candidates:
            _candidates.append(_beacon)
    for v in videos:
        _lurl = getattr(v, "launch_url", "")
        if _lurl and "sessionless_launch" in _lurl and _lurl not in _candidates:
            _candidates.append(_lurl)
    for _cand in _candidates:
        try:
            session, _final, _rid, panopto_base, _folder = lti_launch(_cand, cm.api_key)
        except Exception as e:
            logger.debug("fetch_durations LTI launch failed: %s", e)
            session = panopto_base = None
        if session and panopto_base:
            break
        session = panopto_base = None
    if session is None or panopto_base is None:
        logger.info("Panopto duration probe skipped: no authenticated session.")
        return out

    # Snapshot the auth cookies ONCE, on this thread, before any worker runs.
    cookie_header = _cookie_header(session, panopto_base)

    import concurrent.futures as _cf

    def _one(v):
        if is_cancelled and is_cancelled():
            return v.video_id, None
        try:
            delivery, _err = _delivery_info_via_cookies(cookie_header, panopto_base, v.video_id)
            if delivery:
                d = delivery_duration(delivery)
                if d > 0:
                    return v.video_id, d
        except Exception as e:
            logger.debug("fetch_durations failed for %s: %s", v.video_id, e)
        return v.video_id, None

    try:
        with _cf.ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(videos)))) as ex:
            for vid, dur in ex.map(_one, videos):
                if dur:
                    out[vid] = dur
    except Exception as e:
        logger.debug("fetch_durations pool failed: %s", e)
    logger.info("Panopto duration probe: resolved %d/%d recording(s).", len(out), len(videos))
    return out


def pick_video_stream(delivery: dict) -> str | None:
    """Pick the combined video+audio stream URL from a Delivery node.

    Panopto's podcast stream is a single MP4 that combines the primary view and
    the audio - exactly what we keep as the recording's video. It's the same
    stream the audio path uses (we just keep the video track instead of dropping
    it), so the selection mirrors :func:`pick_audio_stream`.
    """
    return pick_audio_stream(delivery)


def delivery_duration(delivery: dict) -> float:
    try:
        return float(delivery.get("Duration") or 0.0)
    except Exception:
        return 0.0


def _cookie_domain_matches(cookie_domain: str, host: str) -> bool:
    """True when a cookie with *cookie_domain* would be sent to *host*.

    Implements the RFC 6265 domain-match: the host equals the cookie domain, or
    the host is a subdomain of it (a leading dot on the stored domain is
    normalisation noise). Falls back to the historical "panopto" substring test
    when *host* is unavailable, so a failed URL parse can never end up sending
    ZERO cookies (which would 403 every download).
    """
    d = (cookie_domain or "").lstrip(".").lower()
    if not d:
        return False
    if not host:
        return "panopto" in d
    return host == d or host.endswith("." + d)


def _cookie_header(session, panopto_base: str) -> str:
    """Snapshot the Panopto auth cookies into a single ``Cookie:`` header value.

    Returns a plain string so callers can capture it ONCE (under a lock, on the
    main/owning thread) and hand it to ffmpeg, instead of having concurrent
    download workers iterate the shared (non-thread-safe) session cookie jar.

    Cookies are selected by domain-matching against the host of *panopto_base*
    (not by looking for a literal "panopto" in the domain): institutions can
    front Panopto with a vanity CNAME like ``video.university.edu``, whose
    session cookies a substring test would silently drop - every ffmpeg
    download would then 403 while discovery still worked.
    """
    from urllib.parse import urlparse

    try:
        host = (urlparse(panopto_base).hostname or "").lower()
    except (ValueError, AttributeError):
        host = ""
    return "; ".join(
        f"{c.name}={c.value}"
        for c in session.cookies
        if _cookie_domain_matches(c.domain, host)
    )


def _input_headers(cookie_header: str, panopto_base: str) -> list[str]:
    """ffmpeg ``-headers`` args carrying the authenticated cookies + referer.

    The stream URLs are gated by the Panopto session cookies; ffmpeg has no
    access to the requests session, so we hand it a pre-snapshotted cookie string
    (and a referer the CDN expects) explicitly. Taking the cookie value as a
    plain string (not the session) keeps the concurrent download path off the
    shared session entirely.
    """
    headers = ""
    if cookie_header:
        headers += f"Cookie: {cookie_header}\r\n"
    headers += f"Referer: {panopto_base}/\r\n"
    return ["-headers", headers]


def _run_ffmpeg_download(cmd: list[str], out_path: str, *, is_cancelled=None) -> tuple[bool, str | None]:
    """Run an ffmpeg download *cmd* writing *out_path*. Returns (ok, error).

    Shared by the audio (MP3) and video (MP4) downloaders: launches ffmpeg
    headless, polls *is_cancelled* (terminating + cleaning up on abort), drains
    stderr so a failure carries the real reason, and validates a non-empty file.

    H-4 Atomic ``.part`` pattern: ffmpeg writes to ``<out>.part`` and the file
    is os.replace'd into place ONLY on a clean exit with bytes on disk. The
    planning/classification layers treat "file exists" as "recording complete",
    so writing to the final path directly meant a failed run / crash / power
    loss left a TRUNCATED recording that every future sync considered done -
    permanently. Any non-success path now deletes the .part; the final path is
    either absent or a verified complete file, never a partial.

    stderr is drained CONCURRENTLY on a daemon thread, never after-the-fact: a
    chatty remux (HLS `-c copy` sources emit per-packet warnings like
    "Non-monotonous DTS" at exactly our `-loglevel warning`) can otherwise fill
    the ~64KB pipe buffer, ffmpeg blocks on its own stderr write, and the
    download stalls forever while the poll loop sleeps. Only the last few lines
    are kept (bounded memory) - that tail is the actionable part of any failure.
    """
    import collections
    import threading

    # The caller's cmd ends with the intended FINAL path; swap in the .part
    # target for the actual ffmpeg run. The marker goes BEFORE the media
    # extension ("Lecture.part.mp3") because ffmpeg infers the output muxer
    # from the final extension - a trailing ".part" would abort with "unable
    # to find a suitable output format".
    # Long-path form ONCE, here, and everything below inherits it: the .part
    # target, the ffmpeg argument, and every os.path call on either. A Panopto
    # recording is the deepest file this app writes (course / "Panopto
    # Recordings" / lecture title / lecture title.mp4), so on a default Windows
    # install - where LongPathsEnabled is 0 - the write fails outright. Verified
    # that the bundled ffmpeg accepts the prefixed target and produces a
    # byte-identical file.
    #
    # Contained on purpose: this function never returns or records a path, and
    # the log line below takes a basename, so the prefix cannot reach the
    # manifest (where it would break every later comparison) or the screen.
    out_path = make_long_path(out_path)
    _op = os.path.splitext(out_path)
    part_path = f"{_op[0]}.part{_op[1]}"
    cmd = list(cmd[:-1]) + [part_path]
    # A stale .part from a previous crashed run would trip ffmpeg's overwrite
    # prompt suppression into appending oddly on some muxers - clear it.
    try:
        if os.path.exists(part_path):
            os.remove(part_path)
    except OSError:
        pass

    def _cleanup_part() -> None:
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    _t0 = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except Exception as e:
        logger.warning("Panopto ffmpeg launch failed for %s: %s", os.path.basename(out_path), e)
        _cleanup_part()
        return False, f"ffmpeg launch failed: {e}"

    # Rolling tail of stderr lines. The reader thread is the ONLY writer while
    # ffmpeg runs; the main thread reads it only after join(), so no lock needed.
    stderr_tail: collections.deque = collections.deque(maxlen=40)

    def _drain_stderr() -> None:
        try:
            # Binary iteration (no TextIOWrapper): readline() returns b"" only
            # at EOF, i.e. when ffmpeg exits or closes its stderr.
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    stderr_tail.append(line)
        except Exception:
            pass  # a broken pipe on teardown is fine - the tail keeps what it has

    _stderr_thread = threading.Thread(
        target=_drain_stderr, name="panopto-ffmpeg-stderr", daemon=True,
    )
    _stderr_thread.start()

    def _stop_ffmpeg() -> None:
        """terminate, then kill, then REAP. Without the final wait() the child
        is left unreaped on POSIX, and on Windows its handle on the .part file
        may outlive the cleanup below, turning the removal into a silent no-op
        that strands a partial recording."""
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass

    stderr_text = ""
    try:
        # Stall watchdog. ffmpeg is given no timeout of its own (adding CLI
        # flags risks breaking every download on a version that does not accept
        # them), and the poll loop had no wall-clock bound - so a Panopto stream
        # that simply stops sending left ffmpeg waiting on a socket for ever and
        # this loop spinning behind it. Interactively the user can cancel; the
        # DAILY AUTO-SYNC runs unattended, so there is nobody to click it.
        #
        # Progress is measured as growth of the .part file rather than elapsed
        # time, so a genuinely slow download is never killed - only one that has
        # stopped producing bytes.
        _last_size = -1
        _last_progress_at = time.time()
        while proc.poll() is None:
            if is_cancelled and is_cancelled():
                _stop_ffmpeg()
                # Clean up the partial file.
                _cleanup_part()
                return False, "cancelled"
            try:
                _sz = os.path.getsize(part_path) if os.path.exists(part_path) else 0
            except OSError:
                _sz = _last_size
            _now = time.time()
            if _sz > _last_size:
                _last_size = _sz
                _last_progress_at = _now
            elif _now - _last_progress_at > _STALL_TIMEOUT_SECONDS:
                _stop_ffmpeg()
                _cleanup_part()
                logger.warning(
                    "Panopto download stalled (%s): no bytes for %ds; giving up.",
                    os.path.basename(out_path), _STALL_TIMEOUT_SECONDS)
                return False, (f"the download stalled - no data for "
                               f"{_STALL_TIMEOUT_SECONDS}s")
            time.sleep(0.25)
        rc = proc.returncode
    finally:
        # Let the reader finish consuming whatever ffmpeg wrote on the way out.
        # Short join: the process has exited (or been killed), so EOF is
        # imminent; never block teardown on a wedged pipe.
        _stderr_thread.join(timeout=5)
        stderr_text = "\n".join(stderr_tail).strip()

    try:
        size = os.path.getsize(part_path) if os.path.exists(part_path) else 0
    except OSError:
        size = 0

    if rc != 0 or size == 0:
        # Keep the last few stderr lines (the actionable part).
        tail = " | ".join(stderr_text.splitlines()[-4:]) if stderr_text else ""
        detail = f"ffmpeg exited with code {rc}"
        if size == 0 and rc == 0:
            detail = "ffmpeg produced an empty file"
        if tail:
            detail += f" - {tail}"
        logger.warning("Panopto download failed (%s): %s", os.path.basename(out_path), detail)
        # Remove the partial artifact so it can never be mistaken for a
        # complete recording by planning/classification (H-4).
        _cleanup_part()
        return False, detail

    # Verified complete → atomic promote to the final path.
    try:
        os.replace(part_path, out_path)
    except OSError as e:
        logger.warning("Panopto download rename failed (%s): %s", os.path.basename(out_path), e)
        _cleanup_part()
        return False, f"could not finalize file: {e}"

    logger.info(
        "Panopto downloaded %s (%.1f MB in %.1fs)",
        os.path.basename(out_path), size / (1024 * 1024), time.time() - _t0,
    )
    return True, None


def download_audio_mp3(
    cookie_header: str,
    panopto_base: str,
    stream_url: str,
    out_path,
    *,
    is_cancelled=None,
    bitrate: str = "128k",
) -> tuple[bool, str | None]:
    """Transcode the stream to MP3 at *out_path*. Returns (ok, error).

    *cookie_header* is the pre-snapshotted Panopto cookie string (see
    ``_cookie_header``); this function never touches the requests session, so it
    is safe to run concurrently. Cancellable: polls *is_cancelled* and terminates
    ffmpeg if requested.
    """
    out_path = str(out_path)
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "warning"]
    cmd += _input_headers(cookie_header, panopto_base)
    cmd += ["-i", stream_url, "-vn", "-acodec", "libmp3lame", "-ab", bitrate, out_path]
    return _run_ffmpeg_download(cmd, out_path, is_cancelled=is_cancelled)


def download_video_mp4(
    cookie_header: str,
    panopto_base: str,
    stream_url: str,
    out_path,
    *,
    is_cancelled=None,
) -> tuple[bool, str | None]:
    """Remux the combined stream to a kept MP4 at *out_path*. Returns (ok, error).

    *cookie_header* is the pre-snapshotted Panopto cookie string (see
    ``_cookie_header``) - the session is never touched here, so concurrent
    downloads are safe. Uses stream copy (``-c copy``) so the original audio/video
    are kept verbatim (fast, no quality loss). HLS sources (.m3u8) carry
    ADTS-framed AAC that must be converted to the MP4 ASC framing on remux, hence
    the conditional bitstream filter. ``+faststart`` moves the moov atom to the
    front so the file plays while still on disk. Cancellable like the audio path.
    """
    out_path = str(out_path)
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "warning"]
    cmd += _input_headers(cookie_header, panopto_base)
    cmd += ["-i", stream_url, "-c", "copy"]
    if ".m3u8" in stream_url.lower():
        cmd += ["-bsf:a", "aac_adtstoasc"]
    cmd += ["-movflags", "+faststart", out_path]
    return _run_ffmpeg_download(cmd, out_path, is_cancelled=is_cancelled)
