"""Per-course Panopto orchestration.

Ties discovery -> LTI auth -> audio download -> transcription together, with
output-path routing (match course structure vs separate folder), skip-if-exists,
and optional sync-manifest recording (Phase 3).

The caller (app.py download phase / sync execution) supplies a ``progress``
callback and an ``is_cancelled`` checker, and renders the dashboard. The runner
itself never touches Streamlit.

progress(kind, **kw) event kinds:
    'discovering'  course=...
    'found'        course=..., count=int
    'video_start'  title=...
    'skipped'      title=..., paths=[...]
    'downloaded'   title=..., path=..., size=int
    'transcribe'   title=..., pct=int
    'produced'     title=..., path=...        (a final file written: mp3/txt/srt)
    'video_done'   title=...
    'warn'         message=...                (one-off, e.g. model missing)
    'error'        error=DownloadError
"""

from __future__ import annotations

import logging
from pathlib import Path

from panopto import models as pmodels
from panopto.auth import lti_launch
from panopto.discovery import discover_course_videos
from panopto.stream import (
    download_audio_mp3, get_delivery_info, pick_audio_stream,
)
from panopto.transcribe import PanoptoCancelled, transcribe
from panopto.settings import wants_transcription

logger = logging.getLogger(__name__)


def _noop(*_a, **_k):
    pass


def make_recorder(sync_manager, course_root):
    """Return a record_fn(video, produced_paths) that logs artifacts to the
    folder's dedicated panopto_manifest table. Best-effort; never raises."""
    def _rec(video, produced_paths):
        for p in produced_paths:
            kind = Path(p).suffix.lower().lstrip(".") or "file"
            try:
                rel = str(Path(p).relative_to(course_root)).replace("\\", "/")
            except Exception:
                rel = str(p)
            sync_manager.record_panopto_file(video.video_id, kind, rel, video.title)
    return _rec


PANOPTO_SUBFOLDER = "Panopto Recordings"


def video_dir(course_root, module_name_sanitized, settings: dict, download_mode: str,
              *, lecture_title_sanitized: str) -> Path:
    """Resolve the output directory for a lecture, honoring the layout setting.

    Both layouts keep lectures INSIDE the course folder (``course_root``):
      - 'separate' -> ``<course_root>/Panopto Recordings/<lecture>/`` so a
        lecture's possibly-many artifacts (mp3/txt/srt) stay grouped together
        and don't clutter the course folder.
      - 'match'    -> alongside course files: the module subfolder in modules
        mode, or the course root in flat mode.
    """
    layout = settings.get("layout", "match")
    if layout == "separate":
        return Path(course_root) / PANOPTO_SUBFOLDER / lecture_title_sanitized
    if download_mode == "modules" and module_name_sanitized:
        return Path(course_root) / module_name_sanitized
    return Path(course_root)


def _unique_base(directory: Path, safe_title: str, seen: set) -> Path:
    """Return a collision-free <directory>/<safe_title> stem (no extension)."""
    base = directory / safe_title
    key = str(base).lower()
    if key not in seen:
        seen.add(key)
        return base
    n = 1
    while True:
        cand = directory / f"{safe_title} ({n})"
        if str(cand).lower() not in seen:
            seen.add(str(cand).lower())
            return cand
        n += 1


def run_course_panopto(
    cm,
    course,
    *,
    save_dir=None,
    course_root=None,
    settings: dict,
    download_mode: str,
    progress=None,
    is_cancelled=None,
    debug_file=None,
    record_fn=None,
) -> dict:
    """Download + transcribe Panopto lectures for a single course.

    Provide EITHER ``save_dir`` (download mode: course folder is
    ``save_dir/<course>``) OR ``course_root`` (sync mode: the synced folder IS
    the course folder).

    record_fn(video, produced_paths) -> optional hook for manifest recording;
    called once per fully-processed video.

    Returns a summary dict: {found, downloaded, transcribed, skipped, failed}.
    """
    from canvas_logic import DownloadError

    progress = progress or _noop
    is_cancelled = is_cancelled or (lambda: False)
    summary = {"found": 0, "downloaded": 0, "transcribed": 0, "skipped": 0, "failed": 0}

    course_safe = cm._sanitize_filename(course.name)
    if course_root is None:
        course_root = Path(save_dir) / course_safe
    want_mp3 = bool(settings.get("output_mp3"))
    want_tx = wants_transcription(settings)
    want_txt = bool(settings.get("output_txt"))
    want_srt = bool(settings.get("output_srt"))

    # Transcription readiness (checked once).
    model_id = settings.get("model", "small")
    model_ready = want_tx and pmodels.whisper_available() and pmodels.is_installed(model_id)
    if want_tx and not model_ready:
        if not pmodels.whisper_available():
            progress("warn", message="Transcription engine not installed - audio only.")
        elif not pmodels.is_installed(model_id):
            progress("warn", message=f"Model '{model_id}' not installed - transcription skipped.")
    model_path = str(pmodels.model_dir(model_id)) if model_ready else None
    device = settings.get("device", "cpu")
    language = settings.get("language", "auto")

    # ── Discover ──
    progress("discovering", course=course.name)
    try:
        # Always fetch every video available in the course: directly-linked
        # videos PLUS every session in any linked Panopto folder.
        videos = discover_course_videos(
            cm.api_url, cm.api_key, course.id,
            include_folder_sessions=True,
            is_cancelled=is_cancelled,
        )
    except Exception as e:
        logger.warning(f"Panopto discovery failed for '{course.name}': {e}")
        progress("error", error=DownloadError(
            course.name, "Panopto", "Discovery Error", str(e),
            raw_error=e, is_app_error=True,
        ))
        return summary
    summary["found"] = len(videos)
    progress("found", course=course.name, count=len(videos))
    if not videos:
        return summary
    if is_cancelled():
        return summary

    # ── Authenticate once (reused for every DeliveryInfo call) ──
    session = None
    panopto_base = None
    for v in videos:
        if v.launch_url and "sessionless_launch" in v.launch_url:
            session, _final, _rid, panopto_base = lti_launch(v.launch_url, cm.api_key)
            if session and panopto_base:
                break
    seen_bases: set = set()

    for v in videos:
        if is_cancelled():
            break
        progress("video_start", title=v.title)

        safe_title = cm._sanitize_filename(v.title) or v.video_id[:8]
        module_safe = cm._sanitize_filename(v.module_name) if v.module_name else ""
        out_dir = video_dir(course_root, module_safe, settings, download_mode,
                            lecture_title_sanitized=safe_title)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            progress("error", error=DownloadError(
                course.name, v.title, "Folder Error", str(e), raw_error=e))
            summary["failed"] += 1
            continue

        base = _unique_base(out_dir, safe_title, seen_bases)
        mp3_path = Path(str(base) + ".mp3")
        txt_path = Path(str(base) + ".txt")
        srt_path = Path(str(base) + ".srt")

        mp3_missing = want_mp3 and not mp3_path.exists()
        txt_missing = want_txt and model_ready and not txt_path.exists()
        srt_missing = want_srt and model_ready and not srt_path.exists()

        if not (mp3_missing or txt_missing or srt_missing):
            existing = [str(p) for p in (mp3_path, txt_path, srt_path) if p.exists()]
            progress("skipped", title=v.title, paths=existing)
            summary["skipped"] += 1
            continue

        # Need audio on disk for either the mp3 output or transcription.
        need_audio = mp3_missing or ((txt_missing or srt_missing) and not mp3_path.exists())
        downloaded_mp3 = False
        if need_audio:
            if session is None or panopto_base is None:
                progress("error", error=DownloadError(
                    course.name, v.title, "Auth Error",
                    "Could not authenticate to Panopto (LTI handshake failed)."))
                summary["failed"] += 1
                continue
            ok, err = _download_one(
                session, panopto_base, v, cm.api_key, mp3_path, is_cancelled)
            if not ok:
                if err == "cancelled":
                    break
                progress("error", error=DownloadError(
                    course.name, v.title, "Download Error", err or "Unknown error",
                    context={"video_id": v.video_id}))
                summary["failed"] += 1
                continue
            downloaded_mp3 = True

        # Report the mp3 as produced (kept) only if the user wants it.
        if want_mp3 and mp3_path.exists():
            if downloaded_mp3:
                summary["downloaded"] += 1
                try:
                    sz = mp3_path.stat().st_size
                except OSError:
                    sz = 0
                progress("downloaded", title=v.title, path=str(mp3_path), size=sz)
            progress("produced", title=v.title, path=str(mp3_path))

        produced = [str(mp3_path)] if (want_mp3 and mp3_path.exists()) else []

        # ── Transcribe ──
        if model_ready and (txt_missing or srt_missing) and mp3_path.exists():
            try:
                result = transcribe(
                    mp3_path, model_path,
                    language=language, device=device,
                    want_txt=want_txt, want_srt=want_srt,
                    progress=lambda pct, _lang, _t=v.title: progress(
                        "transcribe", title=_t, pct=pct),
                    is_cancelled=is_cancelled,
                )
                summary["transcribed"] += 1
                for key in ("txt", "srt"):
                    p = result.get(key)
                    if p:
                        produced.append(p)
                        progress("produced", title=v.title, path=p)
            except PanoptoCancelled:
                break
            except Exception as e:
                logger.warning(f"Transcription failed for '{v.title}': {e}")
                progress("error", error=DownloadError(
                    course.name, v.title, "Transcription Error", str(e), raw_error=e))

        # If audio was only a transcription intermediate, remove it.
        if not want_mp3 and mp3_path.exists():
            try:
                mp3_path.unlink()
            except OSError:
                pass

        if record_fn and produced:
            try:
                record_fn(v, produced)
            except Exception as e:
                logger.debug(f"Panopto record_fn failed for '{v.title}': {e}")

        progress("video_done", title=v.title)

    return summary


def _download_one(session, panopto_base, video, canvas_token, mp3_path, is_cancelled):
    """Resolve the stream and download MP3, with a per-video LTI fallback.

    Returns (ok, error). error == 'cancelled' signals user abort.
    """
    delivery, err = get_delivery_info(session, panopto_base, video.video_id)
    stream_url = pick_audio_stream(delivery) if delivery else None

    # Fallback: some links need the embed's *real* id resolved via a per-video
    # LTI launch (the Canvas-side id differs from the delivery id).
    if not stream_url and video.launch_url and "sessionless_launch" in video.launch_url:
        v_session, _final, real_id, v_base = lti_launch(video.launch_url, canvas_token)
        if v_session and v_base and real_id:
            session, panopto_base = v_session, v_base
            delivery, err = get_delivery_info(session, panopto_base, real_id)
            stream_url = pick_audio_stream(delivery) if delivery else None

    if not stream_url:
        return False, err or "No stream found for this video."

    return download_audio_mp3(session, panopto_base, stream_url, mp3_path,
                              is_cancelled=is_cancelled)
