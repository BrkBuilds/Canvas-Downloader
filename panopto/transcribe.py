"""Local transcription via faster-whisper (CTranslate2, no PyTorch).

Streams segments as they decode so we can report live progress and cancel
between segments. Writes ``.txt`` (plain transcript) and/or ``.srt`` (timestamped
subtitles). The loaded model is cached per (model_dir, device, compute_type) so
a multi-lecture run loads it once.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class PanoptoCancelled(Exception):
    """Raised to abort a Panopto operation when the user cancels."""


# (model_dir, device, compute_type) -> WhisperModel
_MODEL_CACHE: dict = {}


def _compute_type(device: str) -> str:
    return "float16" if device == "cuda" else "int8"


def load_model(model_dir: str, device: str = "cpu"):
    """Load (and cache) a faster-whisper model from a local directory."""
    ctype = _compute_type(device)
    key = (str(model_dir), device, ctype)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(str(model_dir), device=device, compute_type=ctype)
    except Exception as e:
        # GPU/compute-type mismatch -> fall back to CPU int8 so a run never dies
        # just because CUDA/float16 isn't available on this machine.
        if device != "cpu":
            logger.warning(f"faster-whisper {device}/{ctype} failed ({e}); falling back to CPU.")
            return load_model(model_dir, device="cpu")
        raise
    _MODEL_CACHE[key] = model
    return model


def clear_model_cache() -> None:
    _MODEL_CACHE.clear()


def _fmt_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe(
    mp3_path,
    model_dir: str,
    *,
    language: str | None = None,
    device: str = "cpu",
    want_txt: bool = True,
    want_srt: bool = True,
    progress=None,
    is_cancelled=None,
) -> dict:
    """Transcribe *mp3_path*; write .txt/.srt next to it.

    progress: optional callable(pct:int, detected_language:str|None).
    is_cancelled: optional callable() -> bool; checked between segments.

    Returns {'txt': path|None, 'srt': path|None, 'language': str}.
    Raises PanoptoCancelled if cancelled, ImportError if engine missing.
    """
    mp3_path = str(mp3_path)
    base, _ = os.path.splitext(mp3_path)
    txt_path = base + ".txt"
    srt_path = base + ".srt"

    model = load_model(model_dir, device=device)

    segments, info = model.transcribe(
        mp3_path,
        language=(None if (not language or language == "auto") else language),
        vad_filter=True,
        beam_size=5,
    )
    total = float(getattr(info, "duration", 0.0) or 0.0)
    detected = getattr(info, "language", None)

    # Stream to temp files so a cancel/crash never leaves a half-written sidecar
    # at the final path.
    txt_tmp = txt_path + ".part" if want_txt else None
    srt_tmp = srt_path + ".part" if want_srt else None
    txt_f = open(txt_tmp, "w", encoding="utf-8") if want_txt else None
    srt_f = open(srt_tmp, "w", encoding="utf-8") if want_srt else None

    try:
        idx = 0
        for seg in segments:
            if is_cancelled and is_cancelled():
                raise PanoptoCancelled()
            idx += 1
            text = (seg.text or "").strip()
            if txt_f:
                txt_f.write(text + " ")
            if srt_f:
                srt_f.write(
                    f"{idx}\n{_fmt_srt_time(seg.start)} --> {_fmt_srt_time(seg.end)}\n{text}\n\n"
                )
            if progress and total > 0:
                pct = min(99, int((seg.end / total) * 100))
                progress(pct, detected)
    finally:
        if txt_f:
            txt_f.close()
        if srt_f:
            srt_f.close()

    # Commit temp -> final
    out = {"txt": None, "srt": None, "language": detected or "?"}
    if txt_tmp:
        os.replace(txt_tmp, txt_path)
        out["txt"] = txt_path
    if srt_tmp:
        os.replace(srt_tmp, srt_path)
        out["srt"] = srt_path
    if progress:
        progress(100, detected)
    return out
