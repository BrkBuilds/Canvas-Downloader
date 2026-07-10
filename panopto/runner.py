"""Panopto orchestration, grouped by activity.

Discovery -> audio download -> transcription, run as three distinct PHASES
across all selected courses (mirroring the app's Download -> Post-Processing
flow): every recording is discovered first, then every audio file is downloaded,
then every transcription runs one-by-one. This keeps the progress UI honest
(one phase, one colour, one moving bar) instead of flip-flopping per video.

The caller (app.py download phase / sync execution) supplies a ``progress``
callback and an ``is_cancelled`` checker, and renders the dashboard. The runner
itself never touches Streamlit.

progress(kind, **kw) event kinds:
    # ── Discovery ──
    'discovering'    course=..., index=int, total=int   (about to scan a course)
    'scan_stage'     name=...                            (section: Modules/Pages/…)
    'scan_item'      detail=...                          (item currently examined)
    'scan_found'     title=..., source=...               (a recording was found)
    'found'          course=..., count=int               (finished scanning a course)
    'skipped'        title=..., paths=[...]              (already fully on disk)
    'discovery_done' found=int, courses=int, scanned=int
    # ── Download ──
    'download_phase' total=int
    'video_start'    title=...
    'downloaded'     title=..., path=..., size=int
    'download_done'  total=int, ok=int
    # ── Transcription ──
    'transcribe_phase' total=int
    'transcribe_start' title=..., index=int, total=int
    'transcribe'       title=..., pct=int
    'transcribed'      title=..., paths=[...]
    'transcribe_done'  total=int, ok=int
    # ── Shared ──
    'produced'       title=..., path=...   (a final artifact written: mp3/txt/srt)
    'warn'           message=...           (one-off, e.g. model missing)
    'error'          error=DownloadError
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from panopto import models as pmodels
from panopto.auth import lti_launch
from panopto.discovery import discover_course_videos
from panopto.stream import (
    delivery_duration, download_audio_mp3, download_video_mp4,
    estimate_kind_size, get_delivery_info, pick_audio_stream, pick_video_stream,
)
from panopto.transcribe import (
    PanoptoCancelled, TranscriptionEngineCrash, transcribe_in_subprocess,
)
from panopto.settings import wants_transcription

logger = logging.getLogger(__name__)


def _log_engine_diagnostics() -> None:
    """Dump the transcription-stack status to the debug log (once per batch).

    This is the single highest-value diagnostic for "transcription doesn't
    work" reports: it reveals a missing engine OR an installed-but-broken
    PyTorch (the WinError 1114 / c10.dll case that silently crashes the
    ctranslate2 import that faster-whisper relies on).
    """
    try:
        from core.canvas_debug import get_active_debug_file, log_debug
        diag = pmodels.engine_diagnostics()
        lines = ["=== Panopto transcription engine diagnostics ==="]
        for k, v in diag.items():
            lines.append(f"  {k}: {v}")
        lines.append("================================================")
        block = "\n".join(lines)
        # Mirror to the debug file AND the app logger (so it shows in dev consoles
        # too). get_active_debug_file() returns None when debug mode is off -
        # log_debug then no-ops, but the logger.info still fires.
        log_debug(block, get_active_debug_file())
        logger.info("Transcription engine: backend_usable=%s | torch=%s",
                    diag.get("backend_usable"), diag.get("torch"))
    except Exception as e:
        logger.debug(f"engine diagnostics dump failed: {e}")


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


def make_ignorer(sync_manager):
    """Return an ignore_fn(video) that marks a recording as ignored in the
    folder's panopto_ignored table. Used by the size-limit gate so an oversized
    recording lands in the Ignored bucket (like a manually-ignored recording or
    an over-limit Canvas file) instead of being re-offered on every future sync.
    Best-effort; never raises."""
    def _ign(video):
        try:
            sync_manager.ignore_panopto(video.video_id, getattr(video, "title", ""))
        except Exception:
            pass
    return _ign


PANOPTO_SUBFOLDER = "Panopto Recordings"


def video_dir(course_root, module_name_sanitized, settings: dict, download_mode: str,
              *, lecture_title_sanitized: str) -> Path:
    """Resolve the output directory for a recording, honoring the layout setting.

    Both layouts keep recordings INSIDE the course folder (``course_root``):
      - 'separate' -> ``<course_root>/Panopto Recordings/<recording>/`` so a
        recording's possibly-many artifacts (mp3/txt/srt) stay grouped together
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


def _recording_base(course_root: Path, out_dir: Path, safe_title: str,
                    video_id: str, manifest: dict | None, seen: set) -> Path:
    """Resolve the output stem (no extension) for a recording - manifest-first.

    If this recording was downloaded in a prior run, the per-folder manifest
    records the EXACT relative path of each artifact (including any collision
    suffix like ``Title (1).mp3``). Reusing that stem guarantees a restore /
    new-output sync writes alongside the existing files instead of diverging to a
    fresh ``Title (2)`` - the runner thus resolves paths the same way the sync
    analysis (``panopto.sync_plan.classify_videos``) did, so what executed matches
    what Review showed. Only a never-before-downloaded recording falls back to a
    freshly de-duplicated stem under *out_dir*. The chosen stem is reserved in
    *seen* so a later same-titled recording can't collide with it.
    """
    if manifest:
        mani = manifest.get(video_id) or manifest.get(str(video_id)) or {}
        for kind in ("mp4", "mp3", "txt", "srt"):
            rel = mani.get(kind)
            if not rel:
                continue
            try:
                base = (Path(course_root) / rel).with_suffix("")
                seen.add(str(base).lower())
                return base
            except Exception:
                pass
    return _unique_base(out_dir, safe_title, seen)


# ─────────────────────────────────────────────────────────────────────────────
# Planning data
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _Task:
    """One planned recording: everything needed to download + transcribe it."""
    video: object
    course: object
    course_name: str
    mp4_path: Path
    mp3_path: Path
    txt_path: Path
    srt_path: Path
    record_fn: object
    # Marks an oversized recording as ignored when the size-limit gate trips
    # (parallel to record_fn; resolved per target during planning). None when no
    # sync_manager is available (best-effort).
    ignore_fn: object = None
    # Max-file-size gate (bytes). 0/None = disabled. A recording whose estimated
    # download size exceeds this is skipped + ignored instead of downloaded.
    max_bytes: int = 0
    # auth context (resolved once per course during planning)
    session: object = None
    panopto_base: object = None
    canvas_token: str = ""
    # Serializes access to the shared per-course ``session`` across the concurrent
    # download workers (requests.Session is not thread-safe). All tasks of one
    # course share the SAME lock instance. Defaults to a private lock so a task
    # built without one (e.g. the single-course helper) is still safe.
    auth_lock: object = field(default_factory=threading.Lock)
    # transcription input: the local media file we feed to whisper. When a video
    # is kept we transcribe straight from the MP4 (no second download of the same
    # lecture); otherwise the MP3 audio intermediate is the source.
    tx_source: object = None
    # work flags
    need_video: bool = False     # download the kept MP4
    need_audio: bool = False     # download the MP3 (kept, and/or transcription source)
    want_tx: bool = False        # this recording wants a transcript/subtitle written
    want_mp3: bool = False
    want_mp4: bool = False
    # Per-recording transcript outputs (resolved from this target's contract, so a
    # sync run can produce txt for one folder and srt for another in one pass).
    want_txt: bool = False
    want_srt: bool = False
    # runtime state
    downloaded: bool = False
    failed: bool = False
    produced: list = field(default_factory=list)


def _is_fatal_engine_error(exc: Exception) -> bool:
    """True if *exc* signals the transcription ENGINE is broken on this machine
    (missing DLL / runtime), so retrying every remaining recording would only
    reproduce the identical error. Distinguishes from a per-file decode error."""
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return True
    msg = str(exc).lower()
    needles = (
        ".dll", "winerror 1114", "winerror 126", "winerror 127",
        "failed to load", "error loading", "cudnn", "cublas", "libomp",
        "cannot load library", "shared object", "image not found",
        "dll initialization", "dll load failed",
    )
    return any(n in msg for n in needles)


def _is_cuda_runtime_error(exc: Exception) -> bool:
    """True if *exc* is a GPU/CUDA failure that a CPU retry would avoid (e.g.
    cuBLAS/cuDNN missing, out-of-memory). Used to downgrade GPU -> CPU rather
    than killing the whole transcription phase."""
    msg = str(exc).lower()
    needles = ("cublas", "cudnn", "cuda", "gpu", "nvrtc", "curand",
               "out of memory", "cublaslt")
    return any(n in msg for n in needles)


# ─────────────────────────────────────────────────────────────────────────────
# Phased batch runner
# ─────────────────────────────────────────────────────────────────────────────

def run_panopto_batch(
    cm,
    targets: list,
    *,
    settings: dict,
    progress=None,
    is_cancelled=None,
    debug_file=None,
    max_file_size_bytes: int | None = None,
) -> dict:
    """Run :func:`_run_panopto_batch` inside the macOS Dock-recents guard.

    Transcription re-execs this app's binary per recording; a worker's
    termination (normal exit, or the SIGKILL a cancel sends) can be filed by
    the Dock as a phantom "Canvas Downloader" recents tile. Snapshot OUR
    recents rows before the batch and strip exactly what the batch added -
    on EVERY exit path (return, cancel, raise) via finally, off-thread so
    completion rendering never waits on Dock polling. No-op off macOS.
    See engine.applescript_bridge for the mechanism write-up.
    """
    _dock = None
    if sys.platform == 'darwin':
        try:
            from engine import applescript_bridge as _dock
            _dock.snapshot_own_dock_recents()
        except Exception:
            _dock = None
    try:
        return _run_panopto_batch(
            cm, targets, settings=settings, progress=progress,
            is_cancelled=is_cancelled, debug_file=debug_file,
            max_file_size_bytes=max_file_size_bytes,
        )
    finally:
        if _dock is not None:
            threading.Thread(
                target=_dock.cleanup_own_dock_recents, daemon=True).start()


def _run_panopto_batch(
    cm,
    targets: list,
    *,
    settings: dict,
    progress=None,
    is_cancelled=None,
    debug_file=None,
    max_file_size_bytes: int | None = None,
) -> dict:
    """Download + transcribe Panopto recordings for many courses, grouped by phase.

    ``targets`` is a list of dicts, one per course/folder:
        {
            'course':        obj with .id and .name,
            'course_root':   Path to the course folder (recordings saved inside),
            'download_mode': 'modules' | 'flat',
            'record_fn':     callable(video, produced_paths) | None,
            'ignore_fn':     callable(video) | None,   # mark recording ignored
            # Optional (sync mode): reuse the recordings discovered during the
            # analysis phase instead of re-running the slow discovery, and limit
            # work to the recordings the user selected in Review.
            'videos':        list[PanoptoVideo] | None,   # skip discovery if set
            'selected_ids':  iterable[str] | None,        # allowlist of video_id
            # Optional per-target output/layout contract. When present, THIS
            # target's output formats (output_mp4/mp3/txt/srt) and folder
            # 'layout' are read from here instead of the batch ``settings`` - so a
            # sync run can honour each folder's own stored contract. Engine config
            # (model/device/language) always comes from the batch ``settings``.
            'settings':      dict | None,
        }

    Returns a summary dict:
        {found, downloaded, transcribed, skipped, failed, courses}.
    """
    from core.canvas_logic import DownloadError

    progress = progress or _noop
    is_cancelled = is_cancelled or (lambda: False)
    summary = {"found": 0, "downloaded": 0, "transcribed": 0,
               "skipped": 0, "size_skipped": 0, "failed": 0, "courses": 0}

    # Max-file-size gate (skip-large-files Setting): a recording whose estimated
    # download size exceeds this is skipped + ignored mid-download, exactly like
    # an over-limit Canvas file. 0/None disables it.
    try:
        _gate_bytes = int(max_file_size_bytes or 0)
    except (TypeError, ValueError):
        _gate_bytes = 0

    # Per-target settings: the OUTPUT formats (mp4/mp3/txt/srt) and the folder
    # LAYOUT are resolved from each target's own ``settings`` contract (download
    # mode passes one global contract for every course; sync mode passes each
    # folder's stored contract). Engine config (model/device/language) is global
    # - the model lives on disk and is shared by every target.
    def _ts(target):
        return target.get("settings") or settings

    model_id = settings.get("model", "small")
    engine_ready = pmodels.whisper_available() and pmodels.is_installed(model_id)
    any_want_tx = any(wants_transcription(_ts(t)) for t in targets)
    # Record whether ANY target's contract asked for a transcript this run. The
    # completion card uses this to decide whether to surface the "Transcribed"
    # stat at all: a course with transcription switched off shouldn't display a
    # "0 Transcribed" box (reads as a bug). See render_panopto_summary.
    summary["want_transcription"] = bool(any_want_tx)
    model_path = str(pmodels.model_dir(model_id)) if engine_ready else None
    device = settings.get("device", "cpu")
    language = settings.get("language", "auto")

    # pid tags EVERY line of this batch run. If the log shows overlapping batches
    # with DIFFERENT pids, multiple app instances are running (e.g. the macOS
    # rogue-GUI bug); the SAME pid restarting a batch means the phase re-entered
    # (a rerun that wasn't routed to cancelled - the _active_dl_statuses class).
    logger.info(
        "Panopto batch start (pid=%s): %d target(s) | model=%s device=%s lang=%s | "
        "engine_ready=%s (outputs + layout resolved per target)",
        os.getpid(), len(targets), model_id, device, language, engine_ready,
    )
    # When transcription is configured, dump the engine + hardware diagnostics
    # up front so a broken backend / missing GPU is diagnosable from the log.
    if any_want_tx:
        _log_engine_diagnostics()
        try:
            from panopto.hardware import detect_compute_hardware
            hw = detect_compute_hardware()
            logger.info(
                "Transcription hardware: requested device=%s | gpu_available=%s "
                "gpu=%s vram=%sMB | cpu=%s cores | status=%s",
                device, hw.get("gpu_available"), hw.get("gpu_name"),
                hw.get("gpu_vram_mb"), hw.get("cpu_cores"), hw.get("status"),
            )
            if device == "cuda" and not hw.get("gpu_available"):
                logger.warning("Requested GPU but none usable (%s) - will run on CPU.",
                               hw.get("gpu_reason"))
        except Exception as e:
            logger.debug(f"hardware diagnostics failed: {e}")

    # ═══ Phase 1: Discover every recording across every course ═══
    tasks: list[_Task] = []
    seen_bases: set = set()
    n_targets = len(targets)
    _did_discover = False  # True if any target actually ran discovery (vs reused)

    for ti, target in enumerate(targets):
        if is_cancelled():
            break
        course = target["course"]
        course_root = Path(target["course_root"])
        download_mode = target.get("download_mode", "modules")
        record_fn = target.get("record_fn")

        # This target's output/layout contract (per-folder in sync mode).
        t_settings = _ts(target)
        t_want_mp4 = bool(t_settings.get("output_mp4"))
        t_want_mp3 = bool(t_settings.get("output_mp3"))
        t_want_txt = bool(t_settings.get("output_txt"))
        t_want_srt = bool(t_settings.get("output_srt"))

        prediscovered = target.get("videos")

        def _on_scan(kind, **kw):
            if kind == "stage":
                progress("scan_stage", name=kw.get("name", ""))
            elif kind == "scan":
                progress("scan_item", detail=kw.get("detail", ""))
            elif kind == "video":
                progress("scan_found", title=kw.get("title", ""),
                         source=kw.get("source", ""))

        if prediscovered is not None:
            # Sync mode: discovery already ran during the analysis phase. Reuse it
            # verbatim so what executes is exactly what the user reviewed (no
            # drift) and we skip the second, slow per-video LTI handshake pass.
            # No 'discovering'/'found' events here - there is NO search to show;
            # the UI goes straight to the download phase like any other file.
            videos = list(prediscovered)
            logger.info("Reusing %d pre-discovered Panopto recording(s) for '%s'.",
                        len(videos), course.name)
        else:
            _did_discover = True
            progress("discovering", course=course.name, index=ti + 1, total=n_targets)
            logger.info("Discovering Panopto recordings in '%s' (course id=%s)...",
                        course.name, course.id)
            try:
                videos = discover_course_videos(
                    cm.api_url, cm.api_key, course.id,
                    include_folder_sessions=True,
                    is_cancelled=is_cancelled,
                    on_event=_on_scan,
                )
            except Exception as e:
                logger.error(f"Panopto discovery failed for '{course.name}': {e}", exc_info=True)
                progress("error", error=DownloadError(
                    course.name, "Panopto", "Discovery Error", str(e),
                    raw_error=e, is_app_error=True,
                ))
                progress("found", course=course.name, count=0)
                continue

        # Optional allowlist: only act on the recordings the user selected in
        # Review. Non-selected (including up-to-date) recordings are never
        # planned, so they can't be re-touched or inflate any "skipped" count.
        selected_ids = target.get("selected_ids")
        if selected_ids is not None:
            _sel = {str(s).lower() for s in selected_ids}
            videos = [v for v in videos if str(v.video_id).lower() in _sel]

        # Sync mode: per-recording allowed output kinds from the analysis phase.
        # A restore-from-deleted recording only has 'mp4' (or 'mp3') in its
        # download_kinds; it should NOT produce txt/srt for the first time just
        # because settings have those enabled. When absent (download mode or
        # unknown), fall back to settings for all recordings.
        per_video_kinds: dict | None = target.get("per_video_kinds")

        # Per-folder Panopto manifest ({video_id: {kind: rel_path}}), passed by
        # sync mode so a re-download/restore reuses the exact recorded path. None
        # in download mode (a fresh run has no prior manifest to honour).
        target_manifest: dict | None = target.get("manifest")

        summary["found"] += len(videos)
        if videos:
            summary["courses"] += 1
        # Breakdown by source helps explain unexpected counts (folder expansion,
        # page/assignment links, etc.).
        _by_source: dict[str, int] = {}
        for v in videos:
            _by_source[v.source] = _by_source.get(v.source, 0) + 1
        logger.info("Discovered %d recording(s) in '%s'%s",
                    len(videos), course.name,
                    (" by source " + str(_by_source)) if videos else "")
        if prediscovered is None:
            progress("found", course=course.name, count=len(videos))
        if not videos:
            continue

        # Authenticate once per course (reused for every DeliveryInfo call).
        # Candidate launches, best first: the discovery-VERIFIED beacon(s)
        # (auth_launch_url - a launch that just reached a Panopto host), then
        # each video's own raw launch URL. Legacy items can carry launch URLs
        # whose chain dies on the Canvas tool page (observed post-LTI-1.3
        # migration), so trying only the per-video URLs used to leave the
        # whole course without a session even though 30 working launches had
        # just run during discovery.
        session = panopto_base = None
        _auth_candidates: list[str] = []
        for v in videos:
            _beacon = getattr(v, "auth_launch_url", "")
            if _beacon and "sessionless_launch" in _beacon and _beacon not in _auth_candidates:
                _auth_candidates.append(_beacon)
        for v in videos:
            if (v.launch_url and "sessionless_launch" in v.launch_url
                    and v.launch_url not in _auth_candidates):
                _auth_candidates.append(v.launch_url)
        for _try_no, _cand in enumerate(_auth_candidates, 1):
            session, _final, _rid, panopto_base, _folder = lti_launch(_cand, cm.api_key)
            _ok = bool(session and panopto_base)
            logger.info(
                "Panopto auth bootstrap attempt %d/%d via %s -> %s",
                _try_no, len(_auth_candidates), _cand.split("?")[0],
                "OK" if _ok else "no Panopto session",
            )
            if _ok:
                break
            session = panopto_base = None
        if session is None or panopto_base is None:
            logger.warning(
                "Panopto auth could NOT be established for '%s' - downloads for "
                "this course will fail (no Panopto session/host).", course.name)

        # One lock per course-session, shared by every task of this course, so the
        # concurrent download workers never touch the shared requests.Session at
        # the same time (it is not thread-safe).
        auth_lock = threading.Lock()

        for v in videos:
            if is_cancelled():
                break
            safe_title = cm._sanitize_filename(v.title) or v.video_id[:8]
            module_safe = cm._sanitize_filename(v.module_name) if v.module_name else ""
            out_dir = video_dir(course_root, module_safe, t_settings, download_mode,
                                lecture_title_sanitized=safe_title)
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                progress("error", error=DownloadError(
                    course.name, v.title, "Folder Error", str(e), raw_error=e))
                summary["failed"] += 1
                continue

            base = _recording_base(course_root, out_dir, safe_title, v.video_id,
                                   target_manifest, seen_bases)
            # Defensive: a manifest-derived stem could live in a different subfolder
            # than out_dir (e.g. layout history); make sure its parent exists.
            try:
                base.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            mp4_path = Path(str(base) + ".mp4")
            mp3_path = Path(str(base) + ".mp3")
            txt_path = Path(str(base) + ".txt")
            srt_path = Path(str(base) + ".srt")

            # Narrow to the kinds this specific recording is allowed to produce.
            # In sync mode this comes from PanoptoChange.download_kinds (what the
            # analysis determined needs action); e.g. a restore-from-deleted mp4
            # only has 'mp4' in its allowed set even if settings have txt=True.
            v_kinds = (per_video_kinds or {}).get(str(v.video_id).lower()) if per_video_kinds else None
            v_want_mp4 = t_want_mp4 and (v_kinds is None or 'mp4' in v_kinds)
            v_want_mp3 = t_want_mp3 and (v_kinds is None or 'mp3' in v_kinds)
            v_want_txt = t_want_txt and (v_kinds is None or 'txt' in v_kinds)
            v_want_srt = t_want_srt and (v_kinds is None or 'srt' in v_kinds)
            v_model_ready = engine_ready and (v_want_txt or v_want_srt)

            mp4_missing = v_want_mp4 and not mp4_path.exists()
            mp3_missing = v_want_mp3 and not mp3_path.exists()
            txt_missing = v_want_txt and v_model_ready and not txt_path.exists()
            srt_missing = v_want_srt and v_model_ready and not srt_path.exists()
            tx_missing = txt_missing or srt_missing

            # Nothing to do -> already fully present on disk.
            if not (mp4_missing or mp3_missing or txt_missing or srt_missing):
                existing = [str(p) for p in (mp4_path, mp3_path, txt_path, srt_path) if p.exists()]
                progress("skipped", title=v.title, paths=existing, course=course.name)
                summary["skipped"] += 1
                continue

            # Transcription reads its audio from the kept MP4 when we have one
            # (avoids downloading the same lecture twice); otherwise from the MP3.
            # So a standalone audio download is only needed for a kept MP3, or to
            # feed transcription when no video is kept.
            tx_source = mp4_path if v_want_mp4 else mp3_path
            need_video = mp4_missing
            need_audio = mp3_missing or (tx_missing and not v_want_mp4 and not mp3_path.exists())
            tasks.append(_Task(
                video=v, course=course, course_name=course.name,
                mp4_path=mp4_path, mp3_path=mp3_path, txt_path=txt_path, srt_path=srt_path,
                record_fn=record_fn, ignore_fn=target.get("ignore_fn"),
                max_bytes=_gate_bytes,
                session=session, panopto_base=panopto_base,
                canvas_token=cm.api_key, auth_lock=auth_lock,
                tx_source=tx_source,
                need_video=need_video,
                need_audio=need_audio,
                want_tx=(v_model_ready and tx_missing),
                want_mp3=v_want_mp3,
                want_mp4=v_want_mp4,
                want_txt=v_want_txt,
                want_srt=v_want_srt,
            ))

    # Only announce a discovery phase if one actually ran. In sync mode the
    # recordings were discovered during analysis, so there is nothing to "search".
    if _did_discover:
        progress("discovery_done", found=summary["found"],
                 courses=summary["courses"], scanned=n_targets)

    # Warn if transcription outputs were genuinely wanted (files missing, per-video
    # kinds allow it) but can't run because the engine/model isn't installed.
    # Checked post-task-build so restore-only recordings (where per_video_kinds
    # excluded txt/srt) don't trigger a false "skipped transcription" notice.
    if not engine_ready and any(t.want_txt or t.want_srt for t in tasks):
        if not pmodels.whisper_available():
            progress("warn", message="Transcription engine not installed — Transcript & Subtitle outputs will be skipped.")
        else:
            progress("warn", message="Transcription model not set up — Transcript & Subtitle outputs will be skipped.")

    _n_dl = sum(1 for t in tasks if t.need_video or t.need_audio)
    _n_tx = sum(1 for t in tasks if t.want_tx)
    logger.info(
        "Discovery complete: %d found across %d course(s); planned %d download(s) "
        "(%d video), %d transcription(s), %d skipped (already on disk).",
        summary["found"], summary["courses"], _n_dl,
        sum(1 for t in tasks if t.need_video), _n_tx, summary["skipped"],
    )

    if is_cancelled() or not tasks:
        logger.info("Panopto batch ending after discovery (cancelled=%s, tasks=%d).",
                    is_cancelled(), len(tasks))
        return summary

    # ═══ Phase 2: Download every recording's media (video and/or audio) ═══
    # Downloads run CONCURRENTLY. Each recording is an independent ffmpeg
    # subprocess (dominated by the network transfer of the combined stream, plus
    # a light MP3 transcode), so overlapping a handful of them collapses N
    # sequential downloads toward N/workers wall-clock time. The heavy work
    # (delivery resolve + ffmpeg) runs on worker threads; every progress(...) call
    # is funnelled back to THIS thread because Streamlit rendering is not
    # thread-safe. Workers only push a live 'video_start' onto a queue and return
    # a structured result the orchestrator turns into produced/downloaded events
    # and summary mutations (all task/summary state stays single-threaded here).
    dl_tasks = [t for t in tasks if t.need_video or t.need_audio]
    if dl_tasks:
        import concurrent.futures as _cf
        import queue as _queue
        import time as _time

        max_workers = _download_concurrency(settings, len(dl_tasks))
        logger.info(
            "Download phase: %d recording(s) (%d video, %d audio); %d concurrent worker(s).",
            len(dl_tasks),
            sum(1 for t in dl_tasks if t.need_video),
            sum(1 for t in dl_tasks if t.need_audio),
            max_workers)
        progress("download_phase", total=len(dl_tasks))
        _ok = 0
        ev_q: _queue.Queue = _queue.Queue()

        def _drain_events():
            """Emit any live worker events (video_start) on the main thread."""
            try:
                while True:
                    kind, kw = ev_q.get_nowait()
                    progress(kind, **kw)
            except _queue.Empty:
                pass

        # Best-effort: hand the worker threads the active Streamlit script-run
        # context so the cancel checker's session_state fallback doesn't spam
        # "missing ScriptRunContext!" warnings. The threading.Event is the real
        # cancel signal; this only silences the benign off-thread fallback read.
        # Guarded so the runner still works when driven outside Streamlit.
        _worker_init = None
        try:
            from streamlit.runtime.scriptrunner import (
                get_script_run_ctx as _gsrc, add_script_run_ctx as _asrc)
            _srctx = _gsrc()
            if _srctx is not None:
                import threading as _threading

                def _worker_init():
                    try:
                        _asrc(_threading.current_thread(), _srctx)
                    except Exception:
                        pass
        except Exception:
            _worker_init = None

        with _cf.ThreadPoolExecutor(max_workers=max_workers,
                                    thread_name_prefix="pan-dl",
                                    initializer=_worker_init) as ex:
            futures = [ex.submit(_run_download_task, t, is_cancelled, ev_q)
                       for t in dl_tasks]
            remaining = set(futures)
            _last_tick = 0.0
            while remaining:
                _drain_events()
                done, remaining = _cf.wait(
                    remaining, timeout=0.15, return_when=_cf.FIRST_COMPLETED)
                for fut in done:
                    try:
                        res = fut.result()
                    except Exception as e:
                        logger.error("Panopto download worker crashed: %s", e, exc_info=True)
                        continue
                    t = res.task
                    v = t.video
                    for err in res.errors:
                        progress("error", error=err)
                    if res.cancelled:
                        continue
                    if res.size_skipped:
                        # Over the size limit: nothing downloaded. Register it as
                        # ignored (so future syncs don't re-offer it) and surface
                        # it as a size-skip, like an over-limit Canvas file. The
                        # recording has no media on disk, so Phase 3 skips its
                        # transcription automatically.
                        summary["size_skipped"] += 1
                        if t.ignore_fn:
                            t.ignore_fn(v)
                        progress("size_skipped", title=v.title,
                                 size=res.est_bytes, course=t.course_name)
                        continue
                    # Apply kept artifacts here (task mutation on the main thread).
                    for p in res.produced_kept:
                        t.produced.append(p)
                        progress("produced", title=v.title, path=p, course=t.course_name)
                    if res.total_bytes == 0:
                        # Nothing came down (every media failed) -> a failure; don't
                        # advance the "downloaded" tally.
                        if res.rec_failed:
                            summary["failed"] += 1
                            t.failed = True
                        continue
                    t.downloaded = True
                    _ok += 1
                    if res.kept_any:
                        # "Downloaded" counts recordings with a kept media file
                        # (mp4/mp3), mirroring the per-recording dashboard counter.
                        summary["downloaded"] += 1
                    # One 'downloaded' event per recording (aggregated bytes) keeps
                    # the dashboard's recording counter aligned with the phase
                    # total. It's 'intermediate' only when nothing was kept (audio
                    # pulled purely to feed transcription).
                    progress("downloaded", title=v.title,
                             path=res.primary_path or str(t.mp3_path),
                             size=res.total_bytes, course=t.course_name,
                             intermediate=(not res.kept_any))
                # Keep the dashboard alive (elapsed/speed) during the gaps between
                # completions: with concurrency several seconds can pass with no
                # 'downloaded' event - notably the initial delivery-resolve
                # handshake before any bytes flow - which would otherwise look
                # frozen. Throttled to ~2 Hz so it's cheap.
                _now = _time.time()
                if _now - _last_tick >= 0.5:
                    _last_tick = _now
                    progress("download_tick")
                if is_cancelled():
                    # Stop promptly: drop not-yet-started downloads; in-flight
                    # ffmpeg workers see is_cancelled() and bail on their own.
                    for f in remaining:
                        f.cancel()
                    logger.info("Panopto download cancelled (%d not started).",
                                len(remaining))
                    break
            _drain_events()
        progress("download_done", total=len(dl_tasks), ok=_ok)

    if is_cancelled():
        return summary

    # ═══ Phase 3: Transcribe every downloaded recording, one-by-one ═══
    # Source is the MP4 when a video was kept, else the MP3 intermediate; either
    # way it must exist on disk (a failed download drops the recording here).
    tx_tasks = [t for t in tasks
                if t.want_tx and t.tx_source and Path(t.tx_source).exists()]
    engine_failed = False
    if engine_ready and tx_tasks:
        logger.info("Transcription phase: %d file(s) (model=%s, device=%s).",
                    len(tx_tasks), model_id, device)
        progress("transcribe_phase", total=len(tx_tasks))
        # active_device may be downgraded cuda -> cpu mid-phase if the GPU fails
        # at runtime (e.g. cuBLAS/cuDNN missing); the recording is then retried on
        # CPU so the user still gets transcripts instead of a dead/crashed phase.
        active_device = device
        _ok = 0
        i = 0
        while i < len(tx_tasks):
            if is_cancelled() or engine_failed:
                break
            t = tx_tasks[i]
            v = t.video
            progress("transcribe_start", title=v.title, index=i + 1, total=len(tx_tasks))
            logger.info("Transcribing [%d/%d] '%s' (device=%s, source=%s)...",
                        i + 1, len(tx_tasks), v.title, active_device,
                        Path(t.tx_source).name)
            try:
                # Runs in an isolated child process: a native CUDA crash can no
                # longer take down the host (the "server closed itself" bug).
                result = transcribe_in_subprocess(
                    t.tx_source, model_path,
                    language=language, device=active_device,
                    want_txt=t.want_txt, want_srt=t.want_srt,
                    progress=lambda pct, _lang, _t=v.title: progress(
                        "transcribe", title=_t, pct=pct),
                    is_cancelled=is_cancelled,
                )
                summary["transcribed"] += 1
                _ok += 1
                made = []
                for key in ("txt", "srt"):
                    p = result.get(key)
                    if p:
                        made.append(p)
                        t.produced.append(p)
                        progress("produced", title=v.title, path=p, course=t.course_name)
                progress("transcribed", title=v.title, paths=made)
                # Transcription succeeded: drop the intermediate audio unless kept.
                if not t.want_mp3 and t.mp3_path.exists():
                    try:
                        t.mp3_path.unlink()
                    except OSError:
                        pass
                i += 1
            except PanoptoCancelled:
                logger.info("Transcription cancelled by user at [%d/%d] '%s'.",
                            i + 1, len(tx_tasks), v.title)
                break
            except TranscriptionEngineCrash as e:
                # The child process died NATIVELY (e.g. a CUDA/cuDNN access
                # violation) - uncatchable in-process, which is exactly why it now
                # runs in a subprocess. The host server is unharmed.
                logger.error("Transcription worker crashed for '%s' (exit=%s): %s\n%s",
                             v.title, getattr(e, "exit_code", "?"), e,
                             getattr(e, "stderr_tail", "") or "(no stderr)")
                if active_device != "cpu":
                    # GPU path crashes on this machine -> CPU for the rest, retry.
                    progress("warn", message=(
                        "GPU transcription crashed on this PC - switching to CPU "
                        "for the remaining recordings (transcripts still produced)."))
                    logger.warning("Downgrading transcription to CPU after GPU worker crash.")
                    active_device = "cpu"
                    continue  # retry this same recording on CPU
                # CPU worker also crashed -> the engine is unusable here. Stop
                # trying (every remaining recording would crash identically).
                engine_failed = True
                progress("error", error=DownloadError(
                    t.course_name, "Transcription", "Transcription Engine Error",
                    "The transcription engine crashed on this computer. Audio was "
                    "downloaded but transcripts were skipped.",
                    raw_error=e, is_app_error=True))
                progress("warn", message=(
                    "Transcription skipped for the remaining recordings - engine "
                    "crashed. Downloaded audio has been kept."))
                if t.mp3_path.exists() and str(t.mp3_path) not in t.produced:
                    t.produced.append(str(t.mp3_path))
                    progress("produced", title=v.title, path=str(t.mp3_path),
                             course=t.course_name)
                i += 1
            except Exception as e:
                # GPU runtime failure (cuBLAS/cuDNN missing, OOM, ...): downgrade
                # the whole remaining phase to CPU and RETRY this same recording.
                if active_device != "cpu" and _is_cuda_runtime_error(e):
                    logger.warning("GPU transcription failed (%s); falling back to CPU "
                                   "for the rest of the run.", e)
                    progress("warn", message=(
                        "GPU transcription failed (CUDA libraries unavailable) - "
                        "switching to CPU for the remaining recordings."))
                    active_device = "cpu"
                    continue  # retry the same recording on CPU
                if _is_fatal_engine_error(e):
                    engine_failed = True
                    logger.error(f"Panopto transcription engine unavailable: {e}")
                    progress("error", error=DownloadError(
                        t.course_name, "Transcription", "Transcription Engine Error",
                        "The local transcription engine could not start on this "
                        "computer (a required component failed to load). Audio was "
                        "downloaded but transcripts were skipped.",
                        raw_error=e, is_app_error=True))
                    progress("warn", message=(
                        "Transcription skipped for the remaining recordings - engine "
                        "unavailable. Downloaded audio has been kept."))
                else:
                    logger.error(f"Transcription failed for '{v.title}': {e}", exc_info=True)
                    summary["failed"] += 1
                    progress("error", error=DownloadError(
                        t.course_name, v.title, "Transcription Error", str(e), raw_error=e))
                # Failure of any kind: keep the audio so the user has SOMETHING,
                # even if they only asked for a transcript.
                if t.mp3_path.exists() and str(t.mp3_path) not in t.produced:
                    t.produced.append(str(t.mp3_path))
                    progress("produced", title=v.title, path=str(t.mp3_path),
                             course=t.course_name)
                i += 1
        progress("transcribe_done", total=len(tx_tasks), ok=_ok)

    # If the engine died mid-phase, retain audio for every not-yet-processed
    # recording too (so nothing is silently deleted as a stale intermediate).
    if engine_failed:
        for t in tx_tasks:
            if t.mp3_path.exists() and str(t.mp3_path) not in t.produced:
                t.produced.append(str(t.mp3_path))
                progress("produced", title=t.video.title, path=str(t.mp3_path),
                         course=t.course_name)

    # ═══ Record produced artifacts to the per-folder manifest ═══
    for t in tasks:
        if t.record_fn and t.produced:
            try:
                t.record_fn(t.video, t.produced)
            except Exception as e:
                logger.debug(f"Panopto record_fn failed for '{t.video.title}': {e}")

    logger.info(
        "Panopto batch done: found=%(found)d downloaded=%(downloaded)d "
        "transcribed=%(transcribed)d skipped=%(skipped)d failed=%(failed)d "
        "courses=%(courses)d", summary,
    )
    return summary


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
    """Backward-compatible single-course entry point (delegates to the batch).

    Provide EITHER ``save_dir`` (download mode: course folder is
    ``save_dir/<course>``) OR ``course_root`` (sync mode: the synced folder IS
    the course folder).
    """
    if course_root is None:
        course_root = Path(save_dir) / cm._sanitize_filename(course.name)
    target = {
        "course": course,
        "course_root": Path(course_root),
        "download_mode": download_mode,
        "record_fn": record_fn,
    }
    return run_panopto_batch(
        cm, [target], settings=settings, progress=progress,
        is_cancelled=is_cancelled, debug_file=debug_file,
    )


def _resolve_delivery(session, panopto_base, video, canvas_token):
    """Resolve the Delivery node for a recording, with a per-video LTI fallback.

    Returns ``(session, panopto_base, delivery, error)``. Some Canvas links need
    the embed's *real* id resolved via a per-video LTI launch (the Canvas-side id
    differs from the delivery id); when the first lookup yields no usable stream
    we retry through that launch and adopt its session/host. The discovery-
    verified beacon (auth_launch_url) is tried too, in case the item's own
    launch chain is dead but a fresh course session unlocks the delivery.
    """
    delivery, err = get_delivery_info(session, panopto_base, video.video_id)
    has_stream = bool(delivery and pick_audio_stream(delivery))
    if not has_stream:
        _launches = [video.launch_url, getattr(video, "auth_launch_url", "")]
        for _lurl in _launches:
            if not (_lurl and "sessionless_launch" in _lurl):
                continue
            v_session, _final, real_id, v_base, _folder = lti_launch(_lurl, canvas_token)
            if v_session and v_base:
                _vid = real_id or video.video_id
                _delivery, _err = get_delivery_info(v_session, v_base, _vid)
                if _delivery and pick_audio_stream(_delivery):
                    return v_session, v_base, _delivery, _err
                delivery, err = _delivery or delivery, _err or err
    return session, panopto_base, delivery, err


def _download_media(cookie_header, panopto_base, delivery, kind, out_path, is_cancelled):
    """Download one media *kind* ('video' | 'audio') from a resolved Delivery node.

    *cookie_header* is the pre-snapshotted auth cookie string (the session is not
    touched here, so this runs safely on a worker thread). Returns (ok, error);
    error == 'cancelled' signals user abort.
    """
    if kind == "video":
        url = pick_video_stream(delivery)
        if not url:
            return False, "No video stream available for this recording."
        return download_video_mp4(cookie_header, panopto_base, url, out_path,
                                  is_cancelled=is_cancelled)
    url = pick_audio_stream(delivery)
    if not url:
        return False, "No audio stream available for this recording."
    return download_audio_mp3(cookie_header, panopto_base, url, out_path,
                              is_cancelled=is_cancelled)


# ─────────────────────────────────────────────────────────────────────────────
# Concurrent download worker (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _DLResult:
    """Outcome of one recording's concurrent download.

    Produced on a worker thread, consumed on the main thread - which owns ALL
    progress(...) calls and summary/task-flag mutations (Streamlit rendering and
    shared counters must stay single-threaded)."""
    task: object
    cancelled: bool = False
    rec_failed: bool = False
    # Set when the size-limit gate skips this recording before any download.
    # ``est_bytes`` is the estimated size that tripped the gate (for the UI).
    size_skipped: bool = False
    est_bytes: int = 0
    total_bytes: int = 0
    kept_any: bool = False
    primary_path: object = None       # first KEPT file (drives the log icon)
    produced_kept: list = field(default_factory=list)  # paths of kept artifacts
    errors: list = field(default_factory=list)         # DownloadError(s) to emit


def _download_concurrency(settings: dict, n_tasks: int) -> int:
    """How many recordings to download in parallel.

    Downloads are network-bound (the combined stream transfer) plus a light audio
    transcode, so a few in flight overlap the per-file connection/transfer latency
    without saturating the link. Tunable via ``settings['download_concurrency']``;
    defaults to 4, and never exceeds the number of pending downloads.
    """
    try:
        c = int((settings or {}).get("download_concurrency", 0) or 0)
    except (TypeError, ValueError):
        c = 0
    if c <= 0:
        c = 4
    return max(1, min(c, max(1, n_tasks)))


def _run_download_task(t, is_cancelled, ev_q) -> "_DLResult":
    """Download one recording's media on a worker thread.

    Pushes a live 'video_start' event so the dashboard's active-file panel moves
    as each download begins, but otherwise NEVER calls progress() - that stays on
    the main thread. Returns a :class:`_DLResult` the orchestrator turns into
    produced/downloaded events and summary updates.
    """
    from core.canvas_logic import DownloadError

    v = t.video
    res = _DLResult(task=t)
    # Early-out so a task that only STARTS after a cancel (e.g. a worker the pool
    # spins up during shutdown) bails before its delivery-resolve HTTP call,
    # keeping cancellation snappy no matter which thread observed it first.
    if is_cancelled():
        res.cancelled = True
        return res
    try:
        ev_q.put(("video_start", {"title": v.title}))
    except Exception:
        pass

    if t.session is None or t.panopto_base is None:
        res.errors.append(DownloadError(
            t.course_name, v.title, "Auth Error",
            "Could not authenticate to Panopto (LTI handshake failed)."))
        res.rec_failed = True
        return res

    # Resolve the Delivery node ONCE (with a per-video LTI fallback), then pull
    # whichever media this recording needs from that single response. The resolve
    # touches the shared per-course requests.Session (a POST, and possibly a new
    # login), which is NOT thread-safe - so it runs under the course's auth_lock,
    # and we snapshot the auth cookies into a plain string WHILE STILL HOLDING the
    # lock. ffmpeg is then handed that string and never reads the session, so the
    # long concurrent downloads stay fully parallel and race-free.
    from panopto.stream import _cookie_header
    with t.auth_lock:
        _session, panopto_base, delivery, derr = _resolve_delivery(
            t.session, t.panopto_base, v, t.canvas_token)
        cookie_header = _cookie_header(_session, panopto_base) if _session else ""
    if not delivery:
        logger.warning("Panopto delivery resolve failed for '%s' (id=%s): %s",
                       v.title, v.video_id, derr or "no delivery")
        res.errors.append(DownloadError(
            t.course_name, v.title, "Download Error",
            derr or "No stream found for this recording.",
            context={"video_id": v.video_id}))
        res.rec_failed = True
        return res

    # Video first (the big file), then audio. The 'keep' flag marks whether the
    # file is a kept artifact (vs an audio-only transcription source).
    plan = []
    if t.need_video:
        plan.append(("video", t.mp4_path, t.want_mp4))
    if t.need_audio:
        plan.append(("audio", t.mp3_path, t.want_mp3))

    # Max-file-size gate (skip-large-files Setting). Panopto recordings have no
    # known byte size before download, so we estimate from the now-resolved
    # exact duration (audio is CBR/exact; video is ~1.5 Mbps, the same estimate
    # the disk-check and sync Review use). Gate on the LARGEST artifact this
    # recording would pull: if it exceeds the limit, skip the WHOLE recording
    # (no media, no transcription) and flag it for the main thread to ignore -
    # mirroring how an over-limit Canvas file is treated as an intentional skip.
    if t.max_bytes and plan:
        _dur = delivery_duration(delivery)
        _est = 0
        for _kind, _out, _keep in plan:
            _pk = "mp4" if _kind == "video" else "mp3"
            _est = max(_est, estimate_kind_size(_pk, _dur) or 0)
        if _est > t.max_bytes:
            logger.info(
                "Panopto size gate: skipping '%s' (~%.0f MB est > %.0f MB limit).",
                v.title, _est / (1024 * 1024), t.max_bytes / (1024 * 1024))
            res.size_skipped = True
            res.est_bytes = _est
            return res

    for kind, out_path, keep in plan:
        if is_cancelled():
            res.cancelled = True
            break
        ok, err = _download_media(
            cookie_header, panopto_base, delivery, kind, out_path, is_cancelled)
        if not ok:
            if err == "cancelled":
                res.cancelled = True
                break
            logger.warning("Panopto %s download failed for '%s' (id=%s): %s",
                           kind, v.title, v.video_id, err or "Unknown error")
            res.errors.append(DownloadError(
                t.course_name, v.title, "Download Error", err or "Unknown error",
                context={"video_id": v.video_id}))
            res.rec_failed = True
            continue
        try:
            sz = out_path.stat().st_size
        except OSError:
            sz = 0
        res.total_bytes += sz
        if keep:
            res.kept_any = True
            res.primary_path = res.primary_path or str(out_path)
            res.produced_kept.append(str(out_path))
    return res
