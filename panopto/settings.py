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
    # Master toggle: include Panopto lectures in download / sync runs.
    "enabled": False,
    # Output formats the user wants written per lecture.
    "output_mp3": True,        # audio
    "output_txt": True,        # plain-text transcript
    "output_srt": True,        # timestamped subtitles
    "output_mp4": False,       # reserved - video download deferred (Phase 2+)
    # Transcription.
    "model": "small",          # faster-whisper model id (see panopto.models)
    "language": "auto",        # 'auto' | ISO code ('da', 'en', ...)
    "device": "cpu",           # 'cpu' | 'cuda'
    # Output organization. Both layouts keep lectures INSIDE the course folder.
    #   'match'    -> save alongside course files (module subfolder in modules
    #                 mode, course root in flat mode).
    #   'separate' -> a "Panopto Recordings" subfolder inside the course folder,
    #                 with one subfolder per lecture.
    "layout": "match",
}


def _config_path() -> Path:
    """Resolve the shared settings JSON path (lazy import of get_config_dir)."""
    from ui_helpers import get_config_dir
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
