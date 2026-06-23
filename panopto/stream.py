"""Panopto stream resolution + audio download via the bundled ffmpeg.

``DeliveryInfo.aspx`` returns the stream URL(s) for a video given an
authenticated Panopto session. We pull the audio (podcast) stream and transcode
to MP3 with the ffmpeg binary that ships with the app (imageio_ffmpeg) - never
relying on a system PATH ffmpeg.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

logger = logging.getLogger(__name__)


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
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return None, str(e)

    if data.get("ErrorCode"):
        return None, data.get("ErrorMessage", f"ErrorCode {data.get('ErrorCode')}")
    return data.get("Delivery", {}) or {}, None


def pick_audio_stream(delivery: dict) -> str | None:
    """Pick the best audio stream URL from a Delivery node."""
    for key in ("PodcastStreams", "Streams"):
        streams = delivery.get(key, []) or []
        if streams:
            u = streams[0].get("StreamUrl")
            if u:
                return u
    return None


def delivery_duration(delivery: dict) -> float:
    try:
        return float(delivery.get("Duration") or 0.0)
    except Exception:
        return 0.0


def _cookie_header(session, panopto_base: str) -> str:
    return "; ".join(
        f"{c.name}={c.value}"
        for c in session.cookies
        if "panopto" in c.domain.lower()
    )


def download_audio_mp3(
    session,
    panopto_base: str,
    stream_url: str,
    out_path,
    *,
    is_cancelled=None,
    bitrate: str = "128k",
) -> tuple[bool, str | None]:
    """Transcode the stream to MP3 at *out_path*. Returns (ok, error).

    Cancellable: polls *is_cancelled* and terminates ffmpeg if requested.
    """
    out_path = str(out_path)
    cookie_str = _cookie_header(session, panopto_base)

    cmd = [ffmpeg_exe(), "-y", "-loglevel", "warning"]
    headers = ""
    if cookie_str:
        headers += f"Cookie: {cookie_str}\r\n"
    headers += f"Referer: {panopto_base}/\r\n"
    cmd += ["-headers", headers]
    cmd += ["-i", stream_url, "-vn", "-acodec", "libmp3lame", "-ab", bitrate, out_path]

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except Exception as e:
        return False, f"ffmpeg launch failed: {e}"

    try:
        while proc.poll() is None:
            if is_cancelled and is_cancelled():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                # Clean up the partial file.
                try:
                    if os.path.exists(out_path):
                        os.remove(out_path)
                except OSError:
                    pass
                return False, "cancelled"
            time.sleep(0.25)
        rc = proc.returncode
    finally:
        try:
            if proc.stderr:
                proc.stderr.read()
        except Exception:
            pass

    if rc != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        return False, f"ffmpeg exited with code {rc}"
    return True, None
