"""Local transcription via faster-whisper (CTranslate2, no PyTorch).

Streams segments as they decode so we can report live progress and cancel
between segments. Writes ``.txt`` (plain transcript) and/or ``.srt`` (timestamped
subtitles). The loaded model is cached per (model_dir, device, compute_type) so
a multi-recording run loads it once.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class PanoptoCancelled(Exception):
    """Raised to abort a Panopto operation when the user cancels."""


class TranscriptionEngineCrash(Exception):
    """The transcription SUBPROCESS terminated abnormally without returning a
    result - i.e. a native crash (CUDA/cuDNN access violation, etc.) that cannot
    be caught in-process. The caller should retry on CPU, or treat the engine as
    unusable on this machine. Carries a tail of the child's stderr for the log."""

    def __init__(self, message: str, *, exit_code: int | None = None,
                 stderr_tail: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr_tail = stderr_tail


def _is_vad_engine_error(exc: BaseException) -> bool:
    """True if *exc* looks like the VAD's onnxruntime backend failing to load
    (e.g. ``DLL load failed while importing onnxruntime_pybind11_state``). VAD is
    a quality nicety, not essential - so we retry without it rather than fail."""
    msg = str(exc).lower()
    return any(n in msg for n in ("onnxruntime", "onnx", "silero", "vad"))


# (model_dir, device, compute_type) -> WhisperModel
_MODEL_CACHE: dict = {}


def _compute_type(device: str) -> str:
    """Best CTranslate2 precision actually supported on this machine.

    Hardware-aware (not a hardcoded float16-for-cuda): older NVIDIA cards
    (e.g. Pascal/GTX 10xx) don't support fast FP16, so CT2 reports float16 as
    unsupported and we must drop to an int8 path - otherwise the model load is
    slow or errors. Falls back to the historical default if detection fails.
    """
    try:
        from panopto.hardware import best_compute_type
        return best_compute_type(device)
    except Exception:
        return "float16" if device == "cuda" else "int8"


def load_model(model_dir: str, device: str = "cpu"):
    """Load (and cache) a faster-whisper model from a local directory."""
    # If the app downloaded the CUDA libraries (cuBLAS/cuDNN) for GPU use, put
    # them on the DLL search path before CTranslate2 tries to load them.
    if device == "cuda":
        try:
            from panopto.cuda_provision import register_dll_dir
            register_dll_dir()
        except Exception:
            pass
    ctype = _compute_type(device)
    key = (str(model_dir), device, ctype)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    import time as _time
    _t0 = _time.time()
    # Imported here (not at module top) so the heavy CTranslate2/torch import
    # chain only runs when transcription actually starts - and so an engine
    # failure (e.g. a broken torch DLL) surfaces here with a clear traceback.
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
    logger.info("Loaded transcription model (%s, %s) in %.1fs from %s",
                device, ctype, _time.time() - _t0, model_dir)
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

    import time as _time
    _t0 = _time.time()
    model = load_model(model_dir, device=device)

    _lang = (None if (not language or language == "auto") else language)
    try:
        segments, info = model.transcribe(
            mp3_path, language=_lang, vad_filter=True, beam_size=5,
        )
    except Exception as e:
        # VAD runs eagerly inside transcribe() and needs onnxruntime. On machines
        # where onnxruntime's DLL won't load, retry WITHOUT the voice-activity
        # filter so the transcript is still produced (slightly noisier timing).
        if not _is_vad_engine_error(e):
            raise
        logger.warning("VAD unavailable (%s); transcribing without it.", e)
        segments, info = model.transcribe(
            mp3_path, language=_lang, vad_filter=False, beam_size=5,
        )
    total = float(getattr(info, "duration", 0.0) or 0.0)
    detected = getattr(info, "language", None)
    logger.info("Transcribing %s: audio=%.0fs, language=%s (%s)",
                os.path.basename(mp3_path), total, detected or "?",
                "requested:" + language if language and language != "auto" else "auto-detected")

    # Stream to temp files so a cancel/crash never leaves a half-written sidecar
    # at the final path.
    txt_tmp = txt_path + ".part" if want_txt else None
    srt_tmp = srt_path + ".part" if want_srt else None
    txt_f = open(txt_tmp, "w", encoding="utf-8") if want_txt else None
    srt_f = open(srt_tmp, "w", encoding="utf-8") if want_srt else None

    try:
        idx = 0
        _txt_started = False  # have we written the first non-empty txt segment?
        for seg in segments:
            if is_cancelled and is_cancelled():
                raise PanoptoCancelled()
            idx += 1
            text = (seg.text or "").strip()
            if txt_f and text:
                # Space-separate segments WITHOUT a leading/trailing space: write a
                # separator only before the 2nd+ segment, and skip empty segments.
                txt_f.write((" " + text) if _txt_started else text)
                _txt_started = True
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
    logger.info("Transcribed %s: %d segments, lang=%s, %.1fs -> %s",
                os.path.basename(mp3_path), idx, detected or "?",
                _time.time() - _t0,
                ", ".join(k for k in ("txt", "srt") if out.get(k)) or "no output")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Crash-isolated subprocess runner
# ─────────────────────────────────────────────────────────────────────────────

_WORKER_FLAG = "--panopto-transcribe-worker"


def _worker_command() -> list[str]:
    """Command that launches one transcription worker (dev vs frozen .exe)."""
    import sys
    if getattr(sys, "frozen", False):
        # The frozen app re-execs itself; start.py routes this flag to the worker.
        return [sys.executable, _WORKER_FLAG]
    return [sys.executable, "-u", "-m", "panopto.transcribe_worker"]


def _clean_part_files(mp3_path: str, want_txt: bool, want_srt: bool) -> None:
    """Remove any half-written .part sidecars left by a killed/crashed worker."""
    base, _ = os.path.splitext(mp3_path)
    for ext, want in ((".txt", want_txt), (".srt", want_srt)):
        if want:
            try:
                os.remove(base + ext + ".part")
            except OSError:
                pass


def transcribe_in_subprocess(
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
    """Run :func:`transcribe` in an isolated child process.

    Same signature/return as :func:`transcribe`. The native engine runs in a
    child so a hard crash (CUDA access violation, etc.) cannot take down the
    host (Streamlit) process.

    Raises:
        PanoptoCancelled          - user cancelled (child is killed).
        TranscriptionEngineCrash  - child died abnormally with no result
                                    (native crash) -> caller should retry on CPU.
        Exception                 - a clean, catchable failure reported by the
                                    child (re-raised so the runner's existing
                                    cuda/engine/per-file classification applies).
    """
    import json
    import os as _os
    import queue
    import subprocess
    import sys
    import tempfile
    import threading

    mp3_path = str(mp3_path)
    job = {
        "mp3": mp3_path,
        "model_dir": str(model_dir),
        "device": device,
        "language": language,
        "want_txt": bool(want_txt),
        "want_srt": bool(want_srt),
    }

    # Controlled environment: prepend the app's known-good CUDA libs so the engine
    # binds THEM and not a conflicting system CUDA/cuDNN on the inherited PATH
    # (the in-process crash cause). UTF-8 I/O so non-ASCII paths survive the pipe.
    env = dict(_os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if device == "cuda":
        try:
            from panopto.cuda_provision import cuda_libs_dir
            libdir = str(cuda_libs_dir())
            if _os.path.isdir(libdir):
                env["PATH"] = libdir + _os.pathsep + env.get("PATH", "")
        except Exception:
            pass

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # dev: cwd must be the project root so `-m panopto.transcribe_worker` and its
    # `import ui_helpers` resolve. frozen: imports come from the bundle, not cwd.
    cwd = None if getattr(sys, "frozen", False) else \
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

    # Capture stderr to a temp file (not a pipe) so the child can never block on a
    # full stderr pipe while we're busy reading stdout.
    stderr_f = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            _worker_command(), cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_f,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=creationflags,
        )
    except Exception:
        stderr_f.close()
        raise

    try:
        proc.stdin.write(json.dumps(job) + "\n")
        proc.stdin.flush()
        proc.stdin.close()
    except Exception:
        pass

    # Drain stdout on a thread -> queue, so the main loop can poll is_cancelled
    # responsively even between the worker's progress lines.
    q: "queue.Queue" = queue.Queue()

    def _reader():
        try:
            for line in proc.stdout:
                q.put(line)
        finally:
            q.put(None)  # EOF sentinel

    threading.Thread(target=_reader, daemon=True).start()

    result = None
    error_msg = None
    while True:
        if is_cancelled and is_cancelled():
            try:
                proc.kill()
            except Exception:
                pass
            _clean_part_files(mp3_path, want_txt, want_srt)
            raise PanoptoCancelled()
        try:
            line = q.get(timeout=0.3)
        except queue.Empty:
            continue
        if line is None:
            break  # worker stdout closed (process ending)
        line = line.strip()
        if not line or not line.startswith("{"):
            continue  # ignore any stray (non-protocol) output
        try:
            evt = json.loads(line)
        except Exception:
            continue
        kind = evt.get("event")
        if kind == "progress":
            if progress:
                try:
                    progress(evt.get("pct", 0), evt.get("lang"))
                except Exception:
                    pass
        elif kind == "result":
            result = {"txt": evt.get("txt"), "srt": evt.get("srt"),
                      "language": evt.get("language") or "?"}
        elif kind == "error":
            error_msg = evt.get("error") or "Transcription failed."

    rc = proc.wait()
    try:
        stderr_f.seek(0)
        stderr_tail = (stderr_f.read() or "")[-2000:]
    except Exception:
        stderr_tail = ""
    finally:
        stderr_f.close()

    if result is not None:
        return result
    if error_msg is not None:
        # Clean failure the worker caught and reported - re-raise for the runner.
        raise RuntimeError(error_msg)
    # No result and no clean error: the worker died abnormally (native crash).
    raise TranscriptionEngineCrash(
        f"Transcription worker exited abnormally (exit code {rc}) with no result.",
        exit_code=rc, stderr_tail=stderr_tail,
    )
