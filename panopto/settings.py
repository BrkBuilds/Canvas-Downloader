"""Panopto settings persistence.

All Panopto configuration lives under a single ``"panopto"`` key inside the
app's main settings file (``canvas_downloader_settings.json`` in
``get_config_dir()``).  We use an atomic read-modify-write so other top-level
settings written by ui/auth.py's settings dialog are never clobbered, and vice
versa.

The settings dict shape (with defaults) is defined by ``PANOPTO_DEFAULTS``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SETTINGS_KEY = "panopto"

# Single source of truth for the Panopto config shape + defaults.
PANOPTO_DEFAULTS: dict = {
    # Master toggle: include Panopto recordings in download / sync runs.
    "enabled": False,
    # Output formats the user wants written per recording.
    "output_mp3": True,        # audio
    "output_txt": True,        # plain-text transcript
    "output_srt": True,        # timestamped subtitles
    "output_mp4": False,       # full video (combined MP4, stream-copied)
    # Transcription.
    # faster-whisper model id (see panopto.models). This static value is only a
    # schema placeholder / last-resort fallback: the effective default for a
    # machine with nothing persisted yet comes from
    # ``panopto.models.recommend_model()``, which reads the actual GPU VRAM or CPU
    # core count. A fixed default is wrong on most hardware - 'small' in
    # particular transcribes non-English lecture audio poorly.
    "model": "small",
    "language": "auto",        # 'auto' | ISO code ('da', 'en', ...)
    "device": "cpu",           # 'cpu' | 'cuda'
    # Output organization. Both layouts keep recordings INSIDE the course folder.
    #   'match'    -> save alongside course files (module subfolder in modules
    #                 mode, course root in flat mode).
    #   'separate' -> a "Panopto Recordings" subfolder inside the course folder,
    #                 with one subfolder per recording.
    "layout": "match",
}


def _config_path() -> Path:
    """Resolve the shared settings JSON path (lazy import of get_config_dir)."""
    from shared.helpers import get_config_dir
    return Path(get_config_dir()) / "canvas_downloader_settings.json"


def _read_full_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Could not read settings file for Panopto: {e}")
        return {}


def load_settings() -> dict:
    """Return the persisted Panopto settings merged over defaults.

    Unknown/legacy keys in the stored dict are dropped; missing keys fall back
    to ``PANOPTO_DEFAULTS`` so the shape is always complete and predictable.
    """
    stored = _read_full_config().get(SETTINGS_KEY, {})
    if not isinstance(stored, dict):
        stored = {}
    merged = dict(PANOPTO_DEFAULTS)
    for k in PANOPTO_DEFAULTS:
        if k in stored:
            merged[k] = stored[k]
    return merged


def save_settings(settings: dict) -> bool:
    """Atomically persist the Panopto settings under the ``"panopto"`` key.

    Reads the whole config first so all other top-level keys are preserved,
    then writes via a temp file + os.replace. Returns True on success.
    """
    # Sanitize to the known shape so we never store stray keys.
    clean = dict(PANOPTO_DEFAULTS)
    for k in PANOPTO_DEFAULTS:
        if k in settings:
            clean[k] = settings[k]

    full = _read_full_config()
    full[SETTINGS_KEY] = clean

    path = _config_path()
    tmp = str(path) + ".tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(full, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.warning(f"Could not save Panopto settings: {e}")
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return False


def active_outputs(settings: dict) -> list[str]:
    """Return the list of enabled output kinds, e.g. ['mp3', 'txt', 'srt']."""
    out = []
    if settings.get("output_mp4"):
        out.append("mp4")
    if settings.get("output_mp3"):
        out.append("mp3")
    if settings.get("output_txt"):
        out.append("txt")
    if settings.get("output_srt"):
        out.append("srt")
    return out


def wants_transcription(settings: dict) -> bool:
    """True if any transcription output (txt/srt) is requested."""
    return bool(settings.get("output_txt") or settings.get("output_srt"))


# ── Per-run contract <-> runtime settings ───────────────────────────────────
# As of the "integrate Panopto like every other download" pivot, the OUTPUT
# choices (mp4/mp3/txt/srt) and the folder LAYOUT are per-run, configured in the
# download settings page (Section 4) and stored - exactly like the Canvas
# Content "secondary_content_contract" - in each synced folder's manifest. They
# are NOT persisted to the global Panopto JSON.
#
# The ENGINE config (model/language/device) is the one genuine one-time setup
# (you download a model once; it lives on disk). That alone still lives in the
# persisted JSON and is edited by the transcription-config dialog.
#
# A "contract" is the per-run portion: {output_mp4, output_mp3, output_txt,
# output_srt, layout}. ``compose_settings`` rehydrates a full settings dict by
# layering the contract over the persisted engine config, deriving ``enabled``.

_OUTPUT_KEYS = ("output_mp4", "output_mp3", "output_txt", "output_srt")
_CONTRACT_KEYS = (*_OUTPUT_KEYS, "layout")
_ENGINE_KEYS = ("model", "language", "device")


def engine_settings() -> dict:
    """Return only the persisted engine config (model/language/device)."""
    s = load_settings()
    return {k: s.get(k, PANOPTO_DEFAULTS[k]) for k in _ENGINE_KEYS}


def make_contract(*, mp4: bool, mp3: bool, txt: bool, srt: bool,
                  layout: str) -> dict:
    """Build the per-run contract dict from individual output toggles + layout."""
    return {
        "output_mp4": bool(mp4),
        "output_mp3": bool(mp3),
        "output_txt": bool(txt),
        "output_srt": bool(srt),
        "layout": layout if layout in ("match", "separate") else "match",
    }


def infer_contract_from_manifest(manifest: dict | None) -> dict | None:
    """Reconstruct a contract from Panopto artifacts already on disk.

    Recovery path for a folder whose stored ``panopto_contract`` is missing. That
    happens when the download-mode seed write fails (it is a best-effort
    ``_save_metadata``), and the consequence used to be severe and silent: sync
    fell back to the ``persistent_pan_out_*`` session toggles, which are
    session-only and reset to False on every app launch, so ``is_enabled()``
    returned False and the entire Panopto pass was skipped on every future sync.
    The user's Panopto setup appeared to have vanished, with no message.

    A folder that already contains produced artifacts is proof that Panopto WAS
    configured for it, which makes the all-False fallback provably wrong. The
    kinds present tell us which outputs were wanted, and a recorded path under
    "Panopto Recordings/" tells us the layout.

    Args:
        manifest: ``{video_id: {kind: rel_path}}`` from
            ``SyncManager.get_panopto_manifest()``.

    Returns:
        A contract dict, or ``None`` when the manifest is empty (nothing to infer
        from - a folder that never had Panopto must stay disabled).
    """
    if not manifest:
        return None

    kinds: set[str] = set()
    separate = False
    for per_video in manifest.values():
        if not isinstance(per_video, dict):
            continue
        for kind, rel in per_video.items():
            if kind in ("mp4", "mp3", "txt", "srt"):
                kinds.add(kind)
            if isinstance(rel, str) and "panopto recordings/" in rel.replace("\\", "/").lower():
                separate = True

    if not kinds:
        return None

    # A transcript on disk implies the audio step ran, but the user may have since
    # had mp3 output turned off - only assert what the artifacts actually show.
    return make_contract(
        mp4="mp4" in kinds,
        mp3="mp3" in kinds,
        txt="txt" in kinds,
        srt="srt" in kinds,
        layout="separate" if separate else "match",
    )


def extract_contract(settings: dict) -> dict:
    """Return the per-run (contract) portion of a full settings dict, for storage."""
    return {k: settings.get(k, PANOPTO_DEFAULTS[k]) for k in _CONTRACT_KEYS}


def compose_settings(contract: dict | None) -> dict:
    """Rehydrate a complete settings dict from a per-run *contract*.

    Engine config (model/language/device) is pulled from the persisted JSON;
    the output/layout come from the contract; ``enabled`` is derived from
    whether any output ends up selected.

    **A None/empty contract does NOT yield a disabled config** - it yields the
    defaults, and ``PANOPTO_DEFAULTS`` has mp3/txt/srt ON, so ``enabled`` comes
    back True. (This docstring claimed the opposite until 2026-07-30; the
    behaviour has always been this.) Keys absent from a partial contract are
    likewise filled from the defaults, not from False.

    That matters because ``panopto/runner.py`` resolves a target's outputs as
    ``target.get("settings") or settings``, so a target with a falsy contract
    inherits whatever this returned for the batch. Nothing reaches that state
    today - ``sync_ui`` skips any pair with no user-selected recordings, and the
    only path that yields an empty contract (a Panopto analysis that raised)
    also yields nothing to select - but it is one guard away, and the failure
    would be transcription nobody asked for. Every contract this module builds
    (``make_contract``, ``extract_contract``, ``infer_contract_from_manifest``)
    carries all five keys, so hardening the gaps to False would change only the
    None/empty/partial cases. Covered both ways in tests/test_panopto_settings.py.
    """
    s = dict(PANOPTO_DEFAULTS)
    s.update(engine_settings())
    for k in _CONTRACT_KEYS:
        if contract and k in contract:
            s[k] = contract[k]
    s["enabled"] = any(s.get(k) for k in _OUTPUT_KEYS)
    return s


def is_enabled(contract: dict | None) -> bool:
    """True if a contract selects at least one output kind."""
    return bool(contract) and any(contract.get(k) for k in _OUTPUT_KEYS)


def contract_to_ui_keys(contract: dict | None) -> dict:
    """Map a per-run contract ({output_mp4..., layout}) to the badge/UI key
    names ({pan_out_mp4..., pan_layout}) consumed by the shared configuration
    summary renderer (``ui_shared.render_config_summary_badges``).

    Single source of truth so every config viewer (sync hub, dialogs) can show
    Panopto pills from a stored contract without re-deriving the mapping.
    """
    c = contract or {}
    layout = c.get("layout", "match")
    return {
        "pan_out_mp4": bool(c.get("output_mp4")),
        "pan_out_mp3": bool(c.get("output_mp3")),
        "pan_out_txt": bool(c.get("output_txt")),
        "pan_out_srt": bool(c.get("output_srt")),
        "pan_layout": layout if layout in ("match", "separate") else "match",
    }
