"""Isolated subprocess entrypoint: transcribe ONE file, then exit.

Why a separate process? The CTranslate2/CUDA + onnxruntime native stack can
**hard-crash** the host process (an access-violation, e.g. a cuDNN/cuBLAS version
clash with a conflicting system CUDA on the inherited PATH). A native crash is
NOT a Python exception - no ``try/except`` can catch it - so in-process it takes
down the whole Streamlit server (the symptom this module fixes: "the server
closed itself the moment transcription started"). Running each transcription in
a child process contains any such crash: the parent sees the abnormal exit code,
keeps the server alive, and falls back to CPU. It also hands the engine the
clean, controlled DLL environment that the in-process server does not have.

Invocation (see ``panopto.transcribe.transcribe_in_subprocess``):
    python -m panopto.transcribe_worker        (dev)
    <app.exe> --panopto-transcribe-worker      (frozen; routed by start.py)
The job is a single JSON object read from **stdin**.

Wire protocol - one JSON object per line on **stdout**:
    {"event": "progress", "pct": int, "lang": str|null}
    {"event": "result",   "txt": str|null, "srt": str|null, "language": str}
    {"event": "error",    "error": str}        # clean, catchable failure
A native crash produces NO ``result``/``error`` line and a non-zero/abnormal
exit code, plus a faulthandler dump on **stderr** (captured by the parent).
"""

from __future__ import annotations

import json
import sys


def _emit(stream, **obj) -> None:
    stream.write(json.dumps(obj) + "\n")
    stream.flush()


def main() -> int:
    # A native crash here dumps a C/Python traceback to stderr (which the parent
    # reads back for the debug log) instead of vanishing silently.
    try:
        import faulthandler
        faulthandler.enable(file=sys.stderr)
    except Exception:
        pass

    out = sys.stdout
    try:
        job = json.loads(sys.stdin.read() or "{}")
    except Exception as e:
        _emit(out, event="error", error=f"Bad job payload: {e}")
        return 0

    device = job.get("device", "cpu")
    # Put the app's provisioned CUDA libs on the DLL search path early (also done
    # inside load_model, but belt-and-suspenders for the GPU path).
    if device == "cuda":
        try:
            from panopto.cuda_provision import register_dll_dir
            register_dll_dir()
        except Exception:
            pass

    try:
        from panopto.transcribe import transcribe

        def _progress(pct, lang):
            _emit(out, event="progress", pct=int(pct), lang=lang)

        res = transcribe(
            job["mp3"], job["model_dir"],
            language=job.get("language"),
            device=device,
            want_txt=bool(job.get("want_txt", True)),
            want_srt=bool(job.get("want_srt", True)),
            progress=_progress,
            is_cancelled=None,  # cancellation = the parent kills this process
        )
        _emit(out, event="result", txt=res.get("txt"), srt=res.get("srt"),
              language=res.get("language") or "?")
        return 0
    except BaseException as e:  # noqa: BLE001 - report ANY clean failure to the parent
        # A catchable error (missing DLL, decode failure, OOM surfaced as an
        # exception, ...). Reported as a clean 'error' event; the parent re-raises
        # it so the runner's existing CPU/engine classification handles it. The
        # non-zero exit path is reserved for an UNCATCHABLE native crash.
        _emit(out, event="error", error=f"{type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
