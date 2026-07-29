"""Panopto sync planning: classify discovered recordings against local disk.

This is the single source of truth that lets the **sync analysis/review** phase
treat a Panopto recording exactly like any other file. Discovery (slow, done
once in analysis) yields a list of ``PanoptoVideo``; this module compares each
recording's *configured* outputs (mp4/mp3/txt/srt) against what is actually on
disk + the per-folder ``panopto_manifest`` and assigns a state:

    'new'      - never downloaded; nothing on disk            -> New bucket
    'partial'  - some configured outputs missing (e.g. a newly
                 enabled SRT, or one output deleted)           -> New bucket
    'restore'  - was fully produced before, but its outputs
                 were deleted from disk by the user           -> Deleted-Locally
    'uptodate' - every configured output is present            -> hidden

Path resolution mirrors ``panopto.runner`` (``video_dir`` + the recording's
sanitized title) and prefers the manifest's recorded relative path when the
recording was downloaded in a prior run, so a custom collision-suffixed name
(``Title (1).mp3``) still resolves correctly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import os

from shared.helpers import make_long_path, path_exists
from panopto.runner import (
    video_dir, recording_stem_name, recording_base_candidates,
)
from panopto.settings import active_outputs

logger = logging.getLogger(__name__)

# Output kinds we can actually produce, in badge display order (video first).
_SUPPORTED_KINDS = ("mp4", "mp3", "txt", "srt")
_TRANSCRIPT_KINDS = ("txt", "srt")


def wanted_kinds(settings: dict) -> list[str]:
    """Configured output kinds, ordered mp4, mp3, txt, srt.

    model_ready is IGNORED here — classification always considers every
    configured kind so that previously-produced txt/srt files that have been
    deleted locally still appear in the "Deleted Locally" review bucket, and
    new recordings with txt/srt configured still appear in "New Files".

    The runner is responsible for gating actual production on model readiness
    (via v_model_ready per recording). The sync review notice warns the user
    when the model is missing so they can install it before syncing.
    """
    active = set(active_outputs(settings))
    return [k for k in _SUPPORTED_KINDS if k in active]


@dataclass
class PanoptoChange:
    """One discovered recording classified against the local folder."""
    video: object                      # panopto.discovery.PanoptoVideo
    state: str                         # 'new'|'partial'|'restore'|'uptodate'|'ignored'
    wanted_kinds: list = field(default_factory=list)
    present_kinds: list = field(default_factory=list)
    missing_kinds: list = field(default_factory=list)
    deleted_kinds: list = field(default_factory=list)  # in manifest, now gone
    new_kinds: list = field(default_factory=list)      # never produced
    paths: dict = field(default_factory=dict)          # kind -> absolute path str
    sizes: dict = field(default_factory=dict)          # kind -> bytes (real or est.)
    estimated: set = field(default_factory=set)        # kinds whose size is an estimate
    # kind -> absolute path str for kinds whose MANIFEST path was stale but a
    # live copy was found at the current-layout path (see classify_videos);
    # the caller should re-point the manifest at these.
    healed_paths: dict = field(default_factory=dict)
    # The classification this recording WOULD have had if not ignored, so the UI
    # can put it back in the right bucket on restore.
    pre_ignore_state: str = ""

    @property
    def video_id(self) -> str:
        return getattr(self.video, "video_id", "")

    @property
    def title(self) -> str:
        return getattr(self.video, "title", "") or "Untitled recording"

    @property
    def bucket(self) -> str | None:
        """Which review category this belongs to.

        'new'     -> the default-checked "New / missing outputs" list
        'restore' -> the default-unchecked "Deleted Locally" list
        'ignored' -> the Ignored Files section (excluded from sync)
        None      -> up to date (hidden)
        """
        if self.state == "ignored":
            return "ignored"
        if self.state in ("new", "partial"):
            return "new"
        if self.state == "restore":
            return "restore"
        return None

    @property
    def is_actionable(self) -> bool:
        """True only for recordings that would actually sync (not ignored / uptodate)."""
        return self.bucket in ("new", "restore")

    @property
    def download_kinds(self) -> list:
        """The output kinds this recording will actually produce on the next sync.

        This is simply ``missing_kinds`` - every configured output not currently
        on disk. For a pure 'restore' (all missing kinds were previously produced)
        this equals ``deleted_kinds`` anyway; for a 'partial' recording it is the
        full set of gaps (a previously-deleted output AND a never-produced one).

        It must NOT collapse to only the deleted kinds: that would silently drop a
        configured-but-never-produced output (e.g. a txt/srt that couldn't be made
        at first download because the transcription engine was unavailable) when
        the recording also has a deleted output to restore. The runner gates actual
        transcription on live engine readiness (``v_model_ready``) independently, so
        returning every missing kind here is safe even while the engine is down -
        the audio is re-downloaded and txt/srt are simply skipped until the model
        is installed, after which they reappear here and get transcribed.
        """
        return list(self.missing_kinds)

    def size_for(self, kinds) -> int:
        """Sum of known byte sizes (real or estimated) for *kinds*."""
        return sum(int(self.sizes.get(k, 0) or 0) for k in kinds)

    def estimated_for(self, kinds) -> bool:
        """True if any of *kinds* contributes an ESTIMATED (not measured) size."""
        return any(k in self.estimated for k in kinds)

    def has_size_for(self, kinds) -> bool:
        """True if at least one of *kinds* has a known size."""
        return any(k in self.sizes for k in kinds)

    @property
    def download_size(self) -> int:
        """Total bytes this recording will add on the next sync (download_kinds)."""
        return self.size_for(self.download_kinds)


def _video_base_path(cm, video, course_root: Path, settings: dict,
                     download_mode: str) -> Path:
    """Deterministic ``<dir>/<safe_title>`` stem for a recording (no extension).

    Mirrors ``panopto.runner.run_panopto_batch`` planning, minus the cross-video
    collision suffix (a detection-time concern handled via the manifest path).
    """
    safe_title = cm._sanitize_filename(video.title) or (video.video_id or "")[:8]
    module_safe = cm._sanitize_filename(video.module_name) if getattr(video, "module_name", "") else ""
    out_dir = video_dir(course_root, module_safe, settings, download_mode,
                        lecture_title_sanitized=safe_title)
    # The SAME rule the runner writes by - see recording_stem_name. Computing it
    # separately here is how the writer and the analyzer drift, and the symptom
    # is silent: every recording reads as missing on every sync.
    return out_dir / recording_stem_name(safe_title, settings)


def classify_videos(cm, videos, course_root, download_mode: str, settings: dict,
                    manifest: dict, *, ignored_ids=None, durations=None) -> list[PanoptoChange]:
    """Classify each discovered recording against disk + the panopto manifest.

    Args:
        cm: CanvasManager (for ``_sanitize_filename``).
        videos: list of ``PanoptoVideo`` from ``discover_course_videos``.
        course_root: the synced course folder (recordings live inside it).
        download_mode: 'modules' | 'flat' (governs the 'match' layout subfolder).
        settings: Panopto settings dict (output_* / layout / model / device).
        manifest: ``{video_id: {kind: rel_path}}`` from
            ``SyncManager.get_panopto_manifest()``.
        ignored_ids: iterable of video_ids the user has permanently ignored; these
            are flagged ``state='ignored'`` (kept out of the actionable buckets)
            while still carrying their classification + sizes for the Ignored UI.
        durations: optional ``{video_id: seconds}`` map to estimate the size of
            not-yet-downloaded outputs (see ``apply_size_estimates``).

    Returns a ``PanoptoChange`` per video. Never raises - a per-video failure
    degrades that recording to a best-effort 'new' entry rather than aborting.
    """
    course_root = Path(course_root)
    wanted = wanted_kinds(settings)
    ignored = {str(i) for i in (ignored_ids or [])}
    changes: list[PanoptoChange] = []

    # No producible outputs configured -> nothing to plan (e.g. only transcription
    # outputs while the model isn't ready, or every output toggled off). Treat
    # every recording as up-to-date noise.
    if not wanted:
        return changes

    for v in videos:
        try:
            base = _video_base_path(cm, v, course_root, settings, download_mode)
            _safe_title = cm._sanitize_filename(v.title) or (v.video_id or "")[:8]
            mani = manifest.get(v.video_id) or manifest.get(str(v.video_id)) or {}

            present, missing, deleted, new = [], [], [], []
            paths: dict = {}
            sizes: dict = {}
            healed: dict = {}
            # Where this recording's artifacts could be, current naming first
            # then the pre-2026-07-29 one, so a folder downloaded by an older
            # version is ADOPTED rather than re-downloaded. `base` stays the
            # write target for anything genuinely new.
            _cands = recording_base_candidates(base.parent, _safe_title, settings)

            def _find(kind, _c=_cands, _b=base):
                for cand in _c:
                    q = Path(str(cand) + "." + kind)
                    if path_exists(q):
                        return q, True
                return Path(str(_b) + "." + kind), False

            for kind in wanted:
                rel = mani.get(kind)
                if rel:
                    p = course_root / rel
                else:
                    p, _ = _find(kind)
                # path_exists, not Path.exists(): over Windows' 260-char limit
                # the latter returns False rather than raising, so a recording
                # that is sitting right there reads as missing and is
                # re-downloaded on every single sync.
                exists = path_exists(p)
                if rel and not exists:
                    # The manifest path is stale (its file is gone), but the
                    # same kind may exist at the CURRENT layout path - e.g. a
                    # download-mode run of this folder plans purely by layout
                    # (it has no manifest to honour) and, when interrupted,
                    # records nothing. Trusting the manifest alone would
                    # misreport the kind as missing and the next sync would
                    # re-download it into the stale folder - a duplicate copy
                    # of a file the user already has. Adopt the on-disk copy
                    # and flag it for a manifest heal instead.
                    alt, alt_exists = _find(kind)
                    if alt_exists and alt != p:
                        p, exists = alt, True
                        healed[kind] = str(alt)
                paths[kind] = str(p)
                if exists:
                    present.append(kind)
                    # Real on-disk size is authoritative (never an estimate).
                    try:
                        # Matches the path_exists() above: a plain stat() on an
                        # over-long path raises, and the recording would then be
                        # counted as 0 bytes in the confirm screen's total.
                        sizes[kind] = os.path.getsize(make_long_path(p))
                    except OSError:
                        pass
                else:
                    missing.append(kind)
                    (deleted if kind in mani else new).append(kind)

            if not missing:
                state = "uptodate"
            elif new:
                # Brand-new recording (never recorded, nothing on disk) -> 'new';
                # otherwise it has some outputs/history -> 'partial'. Both land in
                # the default-checked New bucket.
                state = "new" if (not present and not mani) else "partial"
            else:
                # Only previously-produced outputs are gone -> user deleted them.
                state = "restore"

            # An ignored recording keeps its real classification under
            # pre_ignore_state so it can be restored to the correct bucket.
            pre_ignore = ""
            if str(v.video_id) in ignored:
                pre_ignore = state
                state = "ignored"

            changes.append(PanoptoChange(
                video=v, state=state, wanted_kinds=list(wanted),
                present_kinds=present, missing_kinds=missing,
                deleted_kinds=deleted, new_kinds=new, paths=paths,
                sizes=sizes, pre_ignore_state=pre_ignore,
                healed_paths=healed,
            ))
        except Exception as e:  # noqa: BLE001 - classification must never abort analysis
            logger.debug(f"Panopto classify failed for '{getattr(v, 'title', '?')}': {e}")
            changes.append(PanoptoChange(
                video=v, state="new", wanted_kinds=list(wanted),
                present_kinds=[], missing_kinds=list(wanted),
                deleted_kinds=[], new_kinds=list(wanted), paths={},
            ))

    if durations:
        apply_size_estimates(changes, durations)
    return changes


def videos_needing_duration(changes) -> list:
    """Return the ``PanoptoVideo`` objects whose size can't be known from disk.

    A recording needs a duration probe when any estimable output kind (mp4/mp3)
    it wants has no measured on-disk size yet. Used by the analysis phase to
    limit the (network) duration fetch to recordings that actually need it.
    """
    from panopto.stream import estimate_kind_size
    out = []
    for c in changes or []:
        needs = any(
            k not in c.sizes and estimate_kind_size(k, 1.0) is not None
            for k in c.wanted_kinds
        )
        if needs and getattr(c, "video", None) is not None:
            out.append(c.video)
    return out


def apply_size_estimates(changes, durations: dict) -> None:
    """Fill in estimated sizes for not-yet-downloaded outputs, in place.

    Only kinds without a measured on-disk size are touched, so real sizes always
    win. Kinds filled here are recorded in ``change.estimated`` so the UI can mark
    them with a "~" (approximate).
    """
    from panopto.stream import estimate_kind_size
    if not durations:
        return
    for c in changes or []:
        dur = durations.get(c.video_id) or durations.get(str(c.video_id))
        if not dur:
            continue
        for kind in c.wanted_kinds:
            if kind in c.sizes:
                continue
            est = estimate_kind_size(kind, dur)
            if est is not None:
                c.sizes[kind] = est
                c.estimated.add(kind)


def tally(changes) -> dict:
    """Summarize a list of ``PanoptoChange`` for routing / debug logging."""
    out = {"new": 0, "restore": 0, "ignored": 0, "uptodate": 0, "total": 0}
    for c in changes or []:
        out["total"] += 1
        if c.bucket == "new":
            out["new"] += 1
        elif c.bucket == "restore":
            out["restore"] += 1
        elif c.bucket == "ignored":
            out["ignored"] += 1
        else:
            out["uptodate"] += 1
    return out
