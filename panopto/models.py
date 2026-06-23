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
MODEL_REGISTRY: list[dict] = [
    {
        "id": "tiny",
        "label": "Tiny",
        "repo": "Systran/faster-whisper-tiny",
        "size_mb": 75,
        "note": "Fastest, lowest accuracy. Good for quick tests.",
    },
    {
        "id": "base",
        "label": "Base",
        "repo": "Systran/faster-whisper-base",
        "size_mb": 145,
        "note": "Fast, modest accuracy.",
    },
    {
        "id": "small",
        "label": "Small",
        "repo": "Systran/faster-whisper-small",
        "size_mb": 484,
        "note": "Balanced speed/accuracy on CPU. Recommended default.",
        "recommended": True,
    },
    {
        "id": "medium",
        "label": "Medium",
        "repo": "Systran/faster-whisper-medium",
        "size_mb": 1530,
        "note": "Strong accuracy, slower on CPU.",
    },
    {
        "id": "large-v3",
        "label": "Large v3",
        "repo": "Systran/faster-whisper-large-v3",
        "size_mb": 3090,
        "note": "Best accuracy (notably better for Danish). Wants a GPU.",
    },
    {
        "id": "turbo",
        "label": "Large v3 Turbo",
        "repo": "deepdml/faster-whisper-large-v3-turbo-ct2",
        "size_mb": 1620,
        "note": "Near-large accuracy, much faster. Excellent on GPU.",
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
    from ui_helpers import get_config_dir
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
    """
    import importlib.util
    return (
        importlib.util.find_spec("faster_whisper") is not None
        and importlib.util.find_spec("ctranslate2") is not None
    )


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


def _download_worker(model_id: str, entry: dict) -> None:
    from huggingface_hub import HfApi, hf_hub_download

    repo = entry["repo"]
    target = model_dir(model_id)
    target.mkdir(parents=True, exist_ok=True)

    try:
        api = HfApi()
        all_files = api.list_repo_files(repo)
        wanted = [
            f for f in all_files
            if f in _ESSENTIAL_NAMES or f.endswith("model.bin")
        ]
        if not wanted:
            raise RuntimeError("No model files found in the Hugging Face repo.")
        # Download the big model.bin last so cancel-between-files is useful.
        wanted.sort(key=lambda f: (f.endswith("model.bin"), f))
        _set_state(model_id, total_files=len(wanted))

        # Background size poller so the bar moves *within* the large file too.
        stop_poll = threading.Event()

        def _poll():
            while not stop_poll.is_set():
                _set_state(model_id, downloaded_bytes=dir_size_bytes(target))
                stop_poll.wait(0.4)

        poller = threading.Thread(target=_poll, daemon=True)
        poller.start()

        try:
            for i, fname in enumerate(wanted):
                if _cancel_requested(model_id):
                    raise ModelDownloadCancelled()
                hf_hub_download(repo_id=repo, filename=fname, local_dir=str(target))
                _set_state(model_id, files_done=i + 1,
                           downloaded_bytes=dir_size_bytes(target))
        finally:
            stop_poll.set()

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
