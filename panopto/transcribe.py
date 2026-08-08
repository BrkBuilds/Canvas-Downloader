"""Local transcription via faster-whisper (CTranslate2, no PyTorch).

Streams segments as they decode so we can report live progress and cancel
between segments. Writes ``.txt`` (plain transcript) and/or ``.srt`` (timestamped
subtitles). The loaded model is cached per (model_dir, device, compute_type) so
a multi-recording run loads it once.
"""

from __future__ import annotations

import logging
import os

from shared.helpers import make_long_path

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


#: Seconds to wait for the worker PROCESS to exit after its stdout has closed.
#: Only ever spent on the pathological path - a clean finish exits immediately.
#: See the note at the wait() call for why this is not the stall watchdog that
#: was deliberately declined for transcription.
_EXIT_GRACE_SECONDS = 10.0

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
    # Long-path form on the OS CALL only. Unlike the media download, this
    # function RETURNS its paths (they become `produced`, which the manifest
    # recorder turns into a relative path), so prefixing the variables would put
    # a "\?\" absolute into the manifest the moment relative_to() failed - and
    # every later comparison against a clean path would then miss.
    # Both opens live INSIDE the try. Opened above it, a failure on the SECOND
    # one (disk full, permissions, an antivirus hold) left the first handle open
    # with the try not yet entered, so the finally never ran. That is not
    # academic on Windows: the traceback keeps the frame - and therefore the
    # handle - alive for as long as Streamlit displays it, so the partial
    # `<name>.txt.part` stays locked and cannot be cleaned up or rewritten.
    txt_f = srt_f = None
    try:
        txt_f = open(make_long_path(txt_tmp), "w", encoding="utf-8") if want_txt else None
        srt_f = open(make_long_path(srt_tmp), "w", encoding="utf-8") if want_srt else None

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
        os.replace(make_long_path(txt_tmp), make_long_path(txt_path))
        out["txt"] = txt_path          # clean: this is what gets recorded
    if srt_tmp:
        os.replace(make_long_path(srt_tmp), make_long_path(srt_path))
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
    """Command that launches one transcription worker (dev vs frozen .exe/.app).

    Frozen: re-exec the app binary. start.py routes the child into worker mode
    PRIMARILY via the ``CANVAS_DL_TRANSCRIBE_WORKER`` env var (set in
    transcribe_in_subprocess), because a macOS windowed ``.app`` bundle does not
    reliably forward custom argv to ``sys.argv`` - its bootloader rebuilds argv
    from Apple events, silently dropping the flag, which made the child boot the
    FULL GUI instead of the worker. The flag is still passed as a secondary
    signal (and for parity with the dev command).

    Frozen macOS: prefer the bundled CONSOLE-bootloader binary
    (Canvas_Downloader_Worker - same code, built by the .spec) over the
    windowed one. The windowed bootloader registers each child with
    LaunchServices for Apple-event handling, and macOS 15's Dock files that
    child's termination as a phantom "Canvas Downloader" recents tile held in
    Dock MEMORY - invisible to `defaults export`, so the prefs-based recents
    strip can't remove it until a Dock restart flushes it. The console binary
    never registers, so workers run with zero Dock footprint. Falls back to
    the app binary when the worker binary is absent (older bundles).

    Dev: run the worker module directly - argv works normally there.
    """
    import os
    import sys
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            _worker_bin = os.path.join(
                os.path.dirname(sys.executable), "Canvas_Downloader_Worker")
            if os.path.isfile(_worker_bin):
                return [_worker_bin, _WORKER_FLAG]
        return [sys.executable, _WORKER_FLAG]
    return [sys.executable, "-u", "-m", "panopto.transcribe_worker"]


def _clean_part_files(mp3_path: str, want_txt: bool, want_srt: bool) -> None:
    """Remove any half-written .part sidecars left by a killed/crashed worker.

    Retries briefly because the caller has just killed the worker and a kill is
    ASYNCHRONOUS: on Windows the dying process still holds its output handles
    for a short while, so the first ``os.remove`` raises ``PermissionError``
    (an ``OSError``) and used to be swallowed silently. The files then stayed in
    the user's course folder for good - and because the engine deliberately
    ignores ``.part`` artifacts everywhere else, nothing would ever clean or
    even mention them. Measured after a real cancel: two leftovers,
    ``<name>.txt.part`` and ``<name>.srt.part``.

    Still never raises - a leftover is untidy, not dangerous - but a persistent
    failure is now logged so it is diagnosable rather than invisible.
    """
    import time as _time
    base, _ = os.path.splitext(mp3_path)
    for ext, want in ((".txt", want_txt), (".srt", want_srt)):
        if not want:
            continue
        target = base + ext + ".part"
        last_err = None
        for attempt in range(6):
            try:
                os.remove(target)
                last_err = None
                break
            except FileNotFoundError:
                last_err = None
                break
            except OSError as e:
                last_err = e
                _time.sleep(0.25)
        if last_err is not None:
            logger.warning("Could not remove partial transcript %s: %s",
                           target, last_err)


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
    # Route the child into worker mode via the ENVIRONMENT, not just the argv
    # flag: a macOS windowed .app bundle can silently drop custom argv (its
    # bootloader rebuilds sys.argv from Apple events), which made the child boot
    # the full GUI instead of the worker - a second app window opened for every
    # transcription and the parent blocked until the user closed it. An env var
    # is inherited verbatim by the execve'd child and is immune to that; start.py
    # checks it before any webview/streamlit import. Harmless on Windows/dev,
    # where argv already routes correctly.
    env["CANVAS_DL_TRANSCRIBE_WORKER"] = "1"
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
    # package imports (e.g. `from shared.helpers import ...`) resolve. frozen:
    # imports come from the bundle, not cwd.
    cwd = None if getattr(sys, "frozen", False) else \
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

    # Capture stderr to a temp file (not a pipe) so the child can never block on a
    # full stderr pipe while we're busy reading stdout.
    import time as _time
    _t0 = _time.time()
    _basename = _os.path.basename(mp3_path)
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

    # Spawn breadcrumb: pid ties the parent's view to the worker's own stderr log
    # (mirrored below on exit). On the macOS argv-drop bug the child booted a GUI
    # instead of the worker - which shows up here as a spawn with NO matching
    # "worker start" line in the mirrored stderr, then an abnormal exit.
    logger.info("Transcribe worker spawned: pid=%s device=%s frozen=%s file=%s",
                proc.pid, device, bool(getattr(sys, "frozen", False)), _basename)

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
    rc = None
    _gone_since = None
    try:
        while True:
            if is_cancelled and is_cancelled():
                try:
                    proc.kill()
                except Exception:
                    pass
                # WAIT for it to actually die before cleaning up. kill() only
                # requests termination; the worker keeps its output handles open
                # until the OS finishes reaping it, so cleaning immediately hit
                # a locked file every time and left the .part sidecars behind.
                try:
                    proc.wait(timeout=10)
                except Exception:
                    pass
                _clean_part_files(mp3_path, want_txt, want_srt)
                raise PanoptoCancelled()
            try:
                line = q.get(timeout=0.3)
            except queue.Empty:
                # Don't rely on stdout EOF alone to detect the worker's end: EOF
                # only arrives when the LAST write-end of the pipe closes, and any
                # process that inherited the worker's std handles (a stray
                # grandchild - e.g. the macOS rogue-GUI relaunch) keeps the pipe
                # open indefinitely AFTER the worker itself has exited. That
                # stalled this loop until the user closed the phantom window,
                # blocking the next file. If the worker PROCESS is gone, give the
                # reader a short grace to flush buffered lines, then move on.
                if proc.poll() is not None:
                    if _gone_since is None:
                        _gone_since = _time.time()
                    elif _time.time() - _gone_since > 3.0:
                        logger.warning(
                            "Transcribe worker (pid=%s) exited but its stdout pipe "
                            "is still open (inherited by another process?) - "
                            "proceeding without waiting for EOF.", proc.pid)
                        break
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
        # Bounded, because this line is reached on a `break` out of the loop
        # above and one of those breaks is stdout EOF - which means the reader
        # thread saw the pipe close, NOT necessarily that the worker exited. A
        # worker that closes stdout and then wedges (or one whose exit is being
        # held up by a stuck native library) parked this on an unbounded wait
        # with nothing left to rescue it: the `finally` below only kills the
        # child AFTER wait() returns. The daily auto-sync runs unattended, so
        # there is no user to cancel it.
        #
        # This is NOT the stall watchdog that was deliberately declined for
        # transcription (see CLAUDE.md): that would have to bound the whole
        # transcribe, where slow and wedged are genuinely hard to tell apart.
        # By this line the worker has finished producing output and all that is
        # left is process teardown, so a few seconds is generous.
        try:
            rc = proc.wait(timeout=_EXIT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Transcribe worker (pid=%s) closed stdout but had not exited "
                "after %.0fs - killing it.", proc.pid, _EXIT_GRACE_SECONDS)
            try:
                proc.kill()
            except Exception:
                pass
            try:
                rc = proc.wait(timeout=_EXIT_GRACE_SECONDS)
            except Exception:
                rc = None
    finally:
        # Never leave the worker transcribing in the background when we unwind for
        # a reason OTHER than a clean finish. The important case is a user Cancel:
        # the progress callback renders, which is exactly where Streamlit raises a
        # RerunException to interrupt this (BaseException - it slips past the inner
        # `except Exception`), tearing down this function with the child still
        # running. On the normal path the worker has already exited, so poll() is
        # not None and we skip the kill. (PanoptoCancelled already killed it.)
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
    stderr_full = ""
    try:
        stderr_f.seek(0)
        stderr_full = stderr_f.read() or ""
    except Exception:
        pass
    finally:
        stderr_f.close()
    stderr_tail = stderr_full[-2000:]

    # Mirror the worker's OWN log (routed to its stderr) into debug_log.txt: the
    # worker is a separate process with no debug-file bridge, so this is the only
    # way its internals - "worker start" (confirms routing), model load, audio
    # duration, segment count, actual device, VAD fallback, "worker done" - reach
    # the shared log. Capped so a runaway child can't flood the file.
    if stderr_full.strip():
        logger.info("Transcribe worker (pid=%s, %s) log:\n%s",
                    proc.pid, _basename, stderr_full.strip()[-4000:])

    _dur = _time.time() - _t0
    if result is not None:
        logger.info("Transcribe worker (pid=%s) OK in %.1fs: %s", proc.pid, _dur,
                    ", ".join(k for k in ("txt", "srt") if result.get(k)) or "no output")
        return result
    if error_msg is not None:
        # Clean failure the worker caught and reported - re-raise for the runner.
        logger.warning("Transcribe worker (pid=%s) reported error in %.1fs: %s",
                       proc.pid, _dur, error_msg)
        raise RuntimeError(error_msg)
    # No result and no clean error: the worker died abnormally (native crash).
    logger.error("Transcribe worker (pid=%s) exited abnormally (exit=%s) in %.1fs "
                 "with no result - native crash or dropped-flag GUI boot.",
                 proc.pid, rc, _dur)
    raise TranscriptionEngineCrash(
        f"Transcription worker exited abnormally (exit code {rc}) with no result.",
        exit_code=rc, stderr_tail=stderr_tail,
    )
