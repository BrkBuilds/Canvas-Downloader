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
        # No static "recommended" flag on any model - see recommend_model().
        # Previously this said "Recommended default." while the UI separately
        # computed its own recommendation, so on a GPU machine BOTH Small and
        # Large v3 Turbo appeared recommended at the same time.
        "note": "Balanced speed/accuracy, but noticeably weaker on non-English audio.",
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

# Preference order, best first: accuracy leads, speed breaks ties. Turbo outranks
# Large v3 deliberately - it is nearly as accurate and several times faster, so
# there is no machine on which plain Large v3 is the better *recommendation*
# (it stays selectable for anyone who wants the last sliver of accuracy).
_PREFERENCE_ORDER = ("turbo", "large-v3", "medium", "small", "base", "tiny")

# What a model needs to be a sensible recommendation, per device.
#   gpu_vram_mb: free-ish VRAM needed for float16 inference, with headroom.
#   cpu_cores:   cores below which the model is too slow to recommend. CPU
#                inference is int8 and memory-light, so wall-clock time - not
#                memory - is the real constraint here.
_MODEL_REQUIREMENTS = {
    "turbo":    {"gpu_vram_mb": 4000, "cpu_cores": 8},
    "large-v3": {"gpu_vram_mb": 6000, "cpu_cores": 999},  # never recommended on CPU
    "medium":   {"gpu_vram_mb": 3000, "cpu_cores": 6},
    "small":    {"gpu_vram_mb": 2000, "cpu_cores": 2},
    "base":     {"gpu_vram_mb": 1500, "cpu_cores": 1},
    "tiny":     {"gpu_vram_mb": 1000, "cpu_cores": 1},
}


def recommend_model(hw: dict | None = None) -> str:
    """Return the model id that best fits *this* machine. Single source of truth.

    There is no static "recommended" flag in the registry: a fixed recommendation
    is wrong on most hardware. Small used to be flagged in the registry AND the
    UI computed its own answer, so a GPU machine showed two "Recommended" badges
    at once - and Small's transcription quality on Danish lecture audio is poor
    enough that recommending it is bad advice regardless.

    Picks the highest-preference model the machine can actually run well:
    VRAM decides on a GPU, core count on a CPU (int8 CPU inference is
    memory-light, so time is the binding constraint). Falls back to the smallest
    model rather than raising, so a failed probe can never leave the UI without
    a recommendation.

    Args:
        hw: a ``detect_compute_hardware()`` dict. Probed on demand when omitted.
    """
    if hw is None:
        try:
            from panopto.hardware import detect_compute_hardware
            hw = detect_compute_hardware()
        except Exception:
            hw = {}
    hw = hw or {}

    on_gpu = bool(hw.get("gpu_available"))
    if on_gpu:
        # An unknown VRAM figure (nvidia-smi did not report it) should not veto
        # the GPU path - assume enough for Turbo, the intended GPU default.
        vram = hw.get("gpu_vram_mb")
        budget = int(vram) if isinstance(vram, (int, float)) and vram else 10**9
        for mid in _PREFERENCE_ORDER:
            need = _MODEL_REQUIREMENTS.get(mid, {}).get("gpu_vram_mb", 0)
            if budget >= need:
                return mid
    else:
        cores = int(hw.get("cpu_cores") or 0) or 4  # unknown -> assume a modest quad-core
        for mid in _PREFERENCE_ORDER:
            need = _MODEL_REQUIREMENTS.get(mid, {}).get("cpu_cores", 10**9)
            if cores >= need:
                return mid
    return "tiny"


def recommendation_reason(hw: dict | None = None) -> str:
    """One short sentence explaining why recommend_model() picked what it did."""
    if hw is None:
        try:
            from panopto.hardware import detect_compute_hardware
            hw = detect_compute_hardware()
        except Exception:
            hw = {}
    hw = hw or {}
    mid = recommend_model(hw)
    label = (get_model(mid) or {}).get("label", mid)
    if hw.get("gpu_available"):
        vram = hw.get("gpu_vram_mb")
        gpu = hw.get("gpu_name") or "your GPU"
        if vram:
            return f"{label} is recommended for {gpu} ({int(vram) // 1024} GB VRAM)."
        return f"{label} is recommended for {gpu}."
    cores = int(hw.get("cpu_cores") or 0)
    if cores:
        return (f"{label} is recommended for CPU transcription on "
                f"{cores} cores. A GPU would allow a larger model.")
    return f"{label} is recommended for CPU transcription."

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
        # Fall back to the hardware-appropriate model, not a fixed 'small'.
        model_id = load_settings().get("model") or recommend_model()
        engine = whisper_available()
        installed = is_installed(model_id)
        any_inst = any(is_installed(m["id"]) for m in MODEL_REGISTRY)
    except Exception:
        return {
            "ready": False, "engine_available": False, "model_id": "",
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
    try:
        t.start()
    except RuntimeError:
        # Thread creation can fail (resource exhaustion). The "downloading"
        # claim above was made on the promise that _download_worker would run
        # and reach a terminal status. If it never starts, nothing else ever
        # writes that state: is_downloading() stays True for the life of the
        # process, the card shows a progress bar that cannot move, and the
        # early-return at the top of this function refuses every retry - so the
        # user can never install the model again without restarting the app.
        # Same guard, same reasoning as core.course_cache.fetch_courses.
        logger.warning("Could not start the model download thread for '%s'.",
                       model_id, exc_info=True)
        _set_state(model_id, status="error",
                   error="Could not start the download. Please try again.")
        return False
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
    try:
        # Inside the try, not above it. Every one of these can raise on a real
        # machine - the import (a broken/partial huggingface_hub), the key
        # lookup, and above all mkdir (read-only volume, full disk, a config
        # dir on an offline share) - and an exception here killed the thread
        # with the state still reading "downloading". Nothing else writes that
        # state, so the card showed a progress bar that could never move and
        # start_download refused to retry for the rest of the session.
        from huggingface_hub import HfApi, hf_hub_url

        repo = entry["repo"]
        target = model_dir(model_id)
        target.mkdir(parents=True, exist_ok=True)

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
