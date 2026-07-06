"""faster-whisper model registry + on-demand download manager.

Models are CTranslate2 conversions hosted on Hugging Face. They are downloaded
on demand into ``get_config_dir()/panopto_models/<model_id>/`` and loaded from
there by the transcription engine (Phase 2).

Download runs on a daemon thread; progress is tracked in a module-level registry
(threads must never touch ``st.session_state``). The Panopto page polls
``get_download_state()`` and auto-reruns to render a live progress bar.
"""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Model registry ──────────────────────────────────────────────────────────
# size_mb is the approximate on-disk size of the essential CT2 files, used for
# the progress denominator and the UI size hint.
# ``speed`` and ``accuracy`` are 1-5 display ratings for the model card's twin
# dash-bars (5 = fastest / most accurate). Roughly inverse along the size axis,
# except Turbo, which is engineered to be both fast and highly accurate.
MODEL_REGISTRY: list[dict] = [
    {
        "id": "tiny",
        "label": "Tiny",
        "repo": "Systran/faster-whisper-tiny",
        "size_mb": 75,
        "note": "Fastest, lowest accuracy. Good for quick tests.",
        "speed": 5, "accuracy": 1,
    },
    {
        "id": "base",
        "label": "Base",
        "repo": "Systran/faster-whisper-base",
        "size_mb": 145,
        "note": "Fast, modest accuracy.",
        "speed": 4, "accuracy": 2,
    },
    {
        "id": "small",
        "label": "Small",
        "repo": "Systran/faster-whisper-small",
        "size_mb": 484,
        "note": "Balanced speed/accuracy on CPU. Recommended default.",
        "recommended": True,
        "speed": 3, "accuracy": 3,
    },
    {
        "id": "medium",
        "label": "Medium",
        "repo": "Systran/faster-whisper-medium",
        "size_mb": 1530,
        "note": "Strong accuracy, slower on CPU.",
        "speed": 2, "accuracy": 4,
    },
    {
        "id": "large-v3",
        "label": "Large v3",
        "repo": "Systran/faster-whisper-large-v3",
        "size_mb": 3090,
        "note": "Best accuracy (notably better for Danish). Wants a GPU.",
        "speed": 1, "accuracy": 5,
    },
    {
        "id": "turbo",
        "label": "Large v3 Turbo",
        "repo": "deepdml/faster-whisper-large-v3-turbo-ct2",
        "size_mb": 1620,
        "note": "Near-large accuracy, much faster. Excellent on GPU.",
        "speed": 4, "accuracy": 4,
    },
]

_REGISTRY_BY_ID = {m["id"]: m for m in MODEL_REGISTRY}

# Essential filenames for a faster-whisper CT2 model (repos vary on vocabulary.*).
_ESSENTIAL_NAMES = {
    "config.json",
    "tokenizer.json",
    "vocabulary.txt",
    "vocabulary.json",
    "preprocessor_config.json",
}


def get_model(model_id: str) -> dict | None:
    return _REGISTRY_BY_ID.get(model_id)


def models_dir() -> Path:
    from shared.helpers import get_config_dir
    d = Path(get_config_dir()) / "panopto_models"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"Could not create panopto_models dir: {e}")
    return d


def model_dir(model_id: str) -> Path:
    return models_dir() / model_id


def hf_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("huggingface_hub") is not None


def whisper_available() -> bool:
    """True if faster-whisper (and its CT2 backend) can be imported.

    Needed for transcription (Phase 2); the model manager itself only needs
    huggingface_hub.

    NOTE: this is a cheap *presence* check (find_spec) - it does NOT prove the
    backend actually imports. A broken optional dependency (e.g. a corrupt
    PyTorch whose c10.dll fails with WinError 1114) lets the package resolve but
    crashes on real import. Use ``engine_diagnostics()`` / ``backend_import_ok()``
    for a definitive answer (and for the debug log).
    """
    import importlib.util
    return (
        importlib.util.find_spec("faster_whisper") is not None
        and importlib.util.find_spec("ctranslate2") is not None
    )


# Cached real-import probe result: (ok: bool, error: str|None).
_BACKEND_PROBE: tuple[bool, str | None] | None = None


def backend_import_ok(force: bool = False) -> tuple[bool, str | None]:
    """Actually import the transcription backend and report (ok, error).

    Unlike ``whisper_available()`` this performs the real ``import
    faster_whisper`` (which transitively imports ctranslate2 -> optional torch),
    so it catches the broken-DLL case the presence check misses. Result is cached
    for the process (the import outcome won't change mid-run); pass force=True to
    re-probe. Never raises.
    """
    global _BACKEND_PROBE
    if _BACKEND_PROBE is not None and not force:
        return _BACKEND_PROBE
    try:
        import faster_whisper  # noqa: F401  (import side effect is the probe)
        _BACKEND_PROBE = (True, None)
    except BaseException as e:  # noqa: BLE001 - a broken DLL can raise OSError/SystemError
        _BACKEND_PROBE = (False, f"{type(e).__name__}: {e}")
    return _BACKEND_PROBE


def engine_diagnostics() -> dict:
    """Probe the transcription stack and return a structured status dict.

    Never raises. Designed for the debug log: a single dump here pinpoints the
    common "transcription silently fails" causes (missing engine, or - the
    nastier one - an installed-but-broken PyTorch that crashes ctranslate2's
    import because ctranslate2 guards its optional ``import torch`` with
    ``except ImportError`` only, which does NOT catch an OSError/DLL failure).
    """
    import importlib
    import importlib.util

    diag: dict = {}

    def _probe(mod: str, attr: str = "__version__") -> str:
        if importlib.util.find_spec(mod) is None:
            return "not installed"
        try:
            m = importlib.import_module(mod)
            return f"{getattr(m, attr, 'unknown')} (import OK)"
        except BaseException as e:  # noqa: BLE001
            return f"PRESENT BUT IMPORT FAILED -> {type(e).__name__}: {e}"

    diag["faster_whisper"] = _probe("faster_whisper")
    diag["ctranslate2"] = _probe("ctranslate2")
    diag["onnxruntime"] = _probe("onnxruntime")

    # torch is OPTIONAL for inference, but a BROKEN torch breaks ctranslate2's
    # import (see docstring). Call it out explicitly.
    if importlib.util.find_spec("torch") is None:
        diag["torch"] = "not installed (fine - optional for inference)"
    else:
        try:
            import torch
            diag["torch"] = f"{torch.__version__} (loads OK; optional)"
        except BaseException as e:  # noqa: BLE001
            diag["torch"] = (
                f"INSTALLED BUT BROKEN -> {type(e).__name__}: {e} "
                "** this also breaks ctranslate2/faster-whisper. Fix: reinstall a "
                "working CPU build (pip install torch --index-url "
                "https://download.pytorch.org/whl/cpu) or uninstall torch entirely "
                "(it is not required)."
            )

    ok, err = backend_import_ok()
    diag["backend_usable"] = "YES" if ok else f"NO -> {err}"
    return diag


def dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return total


def is_installed(model_id: str) -> bool:
    """Installed = the target dir has a CTranslate2 model.bin and a config.json."""
    d = model_dir(model_id)
    return (d / "model.bin").exists() and (d / "config.json").exists()


def transcription_status() -> dict:
    """Readiness of the local transcription stack for the ACTIVE model, with a
    user-facing reason. Single source of truth for the Section 4 banner and the
    sync-review "transcription not set up" notice. Never raises.

    Returns a dict:
      ``ready``            engine importable AND the active model is installed
      ``engine_available`` faster-whisper / ctranslate2 importable
      ``model_id``         the configured active model id
      ``any_installed``    at least one model exists on disk (any id)
      ``reason``           "" when ready, else a short lowercase clause saying
                           why (engine missing / installed-but-not-activated /
                           none downloaded) - safe to interpolate after a dash.
    """
    from panopto.settings import load_settings
    try:
        model_id = load_settings().get("model", "small")
        engine = whisper_available()
        installed = is_installed(model_id)
        any_inst = any(is_installed(m["id"]) for m in MODEL_REGISTRY)
    except Exception:
        return {
            "ready": False, "engine_available": False, "model_id": "small",
            "any_installed": False,
            "reason": "the local transcription engine isn't available yet",
        }
    ready = engine and installed
    if ready:
        reason = ""
    elif not engine:
        reason = "the local transcription engine isn't available yet"
    elif any_inst:
        reason = "a transcription model is installed but not activated yet"
    else:
        reason = "no transcription model is downloaded yet"
    return {
        "ready": ready, "engine_available": engine, "model_id": model_id,
        "any_installed": any_inst, "reason": reason,
    }


def installed_size_mb(model_id: str) -> float:
    return dir_size_bytes(model_dir(model_id)) / (1024 * 1024)


def delete_model(model_id: str) -> bool:
    d = model_dir(model_id)
    try:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        return True
    except Exception as e:
        logger.warning(f"Could not delete model '{model_id}': {e}")
        return False


# ── Download state (module-level; thread-safe) ──────────────────────────────
# model_id -> {status, downloaded_bytes, total_bytes, files_done, total_files,
#              error, cancel}
_DL_STATE: dict[str, dict] = {}
_DL_LOCK = threading.Lock()


def get_download_state(model_id: str) -> dict | None:
    with _DL_LOCK:
        st = _DL_STATE.get(model_id)
        return dict(st) if st else None


def is_downloading(model_id: str) -> bool:
    st = get_download_state(model_id)
    return bool(st and st.get("status") == "downloading")


def request_cancel(model_id: str) -> None:
    with _DL_LOCK:
        if model_id in _DL_STATE:
            _DL_STATE[model_id]["cancel"] = True


def clear_download_state(model_id: str) -> None:
    with _DL_LOCK:
        _DL_STATE.pop(model_id, None)


def _set_state(model_id: str, **kw) -> None:
    with _DL_LOCK:
        _DL_STATE.setdefault(model_id, {}).update(kw)


def _cancel_requested(model_id: str) -> bool:
    with _DL_LOCK:
        return bool(_DL_STATE.get(model_id, {}).get("cancel"))


class ModelDownloadCancelled(Exception):
    pass


def start_download(model_id: str) -> bool:
    """Kick off a background download for *model_id*. Returns False if it can't
    start (already running, unknown model, or huggingface_hub missing)."""
    entry = get_model(model_id)
    if entry is None:
        return False
    if not hf_available():
        _set_state(model_id, status="error",
                   error="huggingface_hub is not installed.")
        return False
    if is_downloading(model_id):
        return True

    _set_state(
        model_id,
        status="downloading",
        downloaded_bytes=0,
        total_bytes=int(entry["size_mb"] * 1024 * 1024),
        files_done=0,
        total_files=0,
        error=None,
        cancel=False,
    )
    t = threading.Thread(
        target=_download_worker, args=(model_id, entry), daemon=True,
        name=f"panopto-model-dl-{model_id}",
    )
    t.start()
    return True


def _stream_file(url: str, dest: Path, model_id: str, done_before: int) -> int:
    """Stream *url* into *dest* in chunks, honouring the cancel flag between every
    chunk and advancing the global byte counter. Returns the bytes written.

    Unlike a single blocking ``hf_hub_download`` (which can't be interrupted while
    the large ``model.bin`` transfers - the root cause of the dead Cancel button),
    this checks ``_cancel_requested`` ~every 256 KB, so Cancel takes effect almost
    immediately even mid-file.
    """
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    got = 0
    headers = {"User-Agent": "CanvasDownloader"}
    with requests.get(url, stream=True, timeout=60, headers=headers) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if _cancel_requested(model_id):
                    raise ModelDownloadCancelled()
                if not chunk:
                    continue
                f.write(chunk)
                got += len(chunk)
                _set_state(model_id, downloaded_bytes=done_before + got)
    return got


def _download_worker(model_id: str, entry: dict) -> None:
    from huggingface_hub import HfApi, hf_hub_url

    repo = entry["repo"]
    target = model_dir(model_id)
    target.mkdir(parents=True, exist_ok=True)

    try:
        api = HfApi(token=False)
        all_files = api.list_repo_files(repo)
        wanted = [
            f for f in all_files
            if f in _ESSENTIAL_NAMES or f.endswith("model.bin")
        ]
        if not wanted:
            raise RuntimeError("No model files found in the Hugging Face repo.")
        # Download the big model.bin last so a cancel between files is fast.
        wanted.sort(key=lambda f: (f.endswith("model.bin"), f))
        _set_state(model_id, total_files=len(wanted))

        # Stream each file ourselves so cancel is honoured mid-transfer (the big
        # model.bin would otherwise block uninterruptibly inside hf_hub_download).
        done_before = 0
        for i, fname in enumerate(wanted):
            if _cancel_requested(model_id):
                raise ModelDownloadCancelled()
            url = hf_hub_url(repo_id=repo, filename=fname)
            done_before += _stream_file(url, target / fname, model_id, done_before)
            _set_state(model_id, files_done=i + 1, downloaded_bytes=done_before)

        if _cancel_requested(model_id):
            raise ModelDownloadCancelled()

        if not is_installed(model_id):
            raise RuntimeError("Download finished but model files are incomplete.")
        _set_state(model_id, status="done",
                   downloaded_bytes=dir_size_bytes(target))

    except ModelDownloadCancelled:
        delete_model(model_id)
        _set_state(model_id, status="cancelled")
    except Exception as e:
        logger.warning(f"Model download failed for '{model_id}': {e}")
        # Leave partial files for inspection only if they look complete; else clean.
        if not is_installed(model_id):
            delete_model(model_id)
        _set_state(model_id, status="error", error=str(e))
