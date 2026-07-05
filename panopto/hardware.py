"""Compute-hardware detection for Panopto transcription.

The transcription engine is faster-whisper / CTranslate2, whose ONLY GPU backend
is NVIDIA CUDA. There is no AMD/ROCm, no Intel, and - importantly - no Apple
Metal/MPS backend. So:

  * Windows / Linux  -> GPU is available only with an NVIDIA card AND a loadable
                        CUDA runtime (the CTranslate2 cuda libs). We confirm this
                        with ``ctranslate2.get_cuda_device_count()`` (authoritative
                        for "can CT2 use the GPU") and enrich the display with the
                        card name / VRAM from ``nvidia-smi``.
  * macOS (Apple Silicon OR Intel) -> there is NO usable GPU backend; everything
                        runs on the CPU cores. The Apple-Silicon CPU is fast for
                        this, so that is fine - we just say so plainly and disable
                        the GPU toggle.

``detect_compute_hardware()`` returns a structured, cached snapshot the UI uses
to show what was found, enable/disable the GPU toggle, and warn about
slow/under-powered configurations. Detection never raises.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

# Cached snapshot (hardware doesn't change within a process run).
_CACHE: dict | None = None

# One-shot guard for the background warm-up thread (see warm_compute_hardware_async).
_WARM_LOCK = threading.Lock()
_WARM_STARTED = False

# Preference order for the CTranslate2 compute type per device. The first entry
# that CT2 reports as supported on this machine wins. float16 is the modern-GPU
# sweet spot; older cards (e.g. Pascal/GTX 10xx) don't list it, so we drop to an
# int8 path that is both faster AND lower-VRAM on those cards.
_CUDA_COMPUTE_PREFERENCE = ("float16", "int8_float16", "int8_float32", "int8", "float32")
_CPU_COMPUTE_PREFERENCE = ("int8", "int8_float32", "float32")


def _run(cmd: list[str], timeout: float = 4.0) -> str | None:
    """Run a command, return stdout on success (no console window on Windows)."""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=creationflags,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except Exception as e:
        logger.debug(f"hardware probe '{cmd[0]}' failed: {e}")
    return None


def _nvidia_gpus() -> list[dict]:
    """Return [{name, vram_mb}] from nvidia-smi, or [] if unavailable."""
    out = _run([
        "nvidia-smi", "--query-gpu=name,memory.total",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return []
    gpus = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
        vram = None
        if len(parts) > 1:
            try:
                vram = int(float(parts[1]))
            except ValueError:
                vram = None
        gpus.append({"name": parts[0], "vram_mb": vram})
    return gpus


def _ct2_supported_compute_types(device: str) -> set:
    try:
        import ctranslate2
        return set(ctranslate2.get_supported_compute_types(device))
    except Exception as e:
        logger.debug(f"ct2 supported_compute_types({device}) failed: {e}")
        return set()


def _ct2_cuda_device_count() -> int:
    """CT2's view of usable CUDA devices. -1 means "couldn't determine"."""
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception as e:
        logger.debug(f"ct2 get_cuda_device_count failed: {e}")
        return -1


def _cuda_compute_libs_loadable() -> bool:
    """Crash-safe check that BOTH compute libraries inference NEEDS - cuBLAS AND
    cuDNN - actually load on this machine.

    This is the critical distinction: ``get_cuda_device_count()`` only proves the
    CUDA *driver* is present (it counts devices). The math libraries cuBLAS and
    cuDNN are SEPARATE and are what the first transcription call uses - if either
    is missing (e.g. it was only ever provided by a since-removed PyTorch), the
    model loads on the GPU but inference dies with "Library cublas64_12.dll is
    not found" (or an uncatchable native crash from a missing/mismatched cuDNN).
    Both are gated here because a machine can easily have one but not the other
    (cuBLAS present, cuDNN missing -> falsely "gpu_ready" -> crash); the app's
    provision step installs both, so requiring both keeps the offered fix honest.
    Loading a DLL with ctypes just maps it (or raises a catchable OSError) - it
    never runs CUDA kernels, so it cannot trigger the native crash that real
    inference would.
    """
    if sys.platform != "win32":
        # On Linux/macOS the lib resolution differs (RPATH / bundled wheels);
        # don't over-gate - the runtime CPU fallback covers a missing lib there.
        return True
    import ctypes

    def _any_loadable(names: tuple[str, ...]) -> bool:
        for name in names:
            try:
                ctypes.WinDLL(name)
                return True
            except Exception:
                continue
        return False

    # CTranslate2 4.x is built against CUDA 12 (cublas64_12.dll) and cuDNN 9
    # (cudnn64_9.dll). Require one DLL from EACH family to load.
    cublas_ok = _any_loadable(("cublas64_12.dll", "cublasLt64_12.dll"))
    cudnn_ok = _any_loadable(("cudnn64_9.dll", "cudnn_ops64_9.dll", "cudnn_cnn64_9.dll"))
    return cublas_ok and cudnn_ok


def _cpu_name() -> str | None:
    sysname = platform.system()
    try:
        if sysname == "Darwin":
            return _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if sysname == "Windows":
            # Registry ProcessorNameString gives the friendly brand name
            # (e.g. "Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz") rather than
            # the raw family/model/stepping string in PROCESSOR_IDENTIFIER.
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                ) as key:
                    name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                    if name and name.strip():
                        # Collapse repeated spaces (common in AMD/Intel strings)
                        return " ".join(name.strip().split())
            except Exception:
                pass
            return platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER") or None
        if sysname == "Linux":
            try:
                with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                    for ln in f:
                        if ln.lower().startswith("model name"):
                            return ln.split(":", 1)[1].strip()
            except OSError:
                pass
    except Exception:
        pass
    return platform.processor() or None


def _best_compute_type(device: str, supported: set | None = None) -> str:
    """Pick the best CT2 compute type actually supported on this machine."""
    if supported is None:
        supported = _ct2_supported_compute_types(device)
    prefs = _CUDA_COMPUTE_PREFERENCE if device == "cuda" else _CPU_COMPUTE_PREFERENCE
    for t in prefs:
        if t in supported:
            return t
    # Sensible fallback if CT2 reported nothing (older binding / probe failure).
    return "float16" if device == "cuda" else "int8"


def best_compute_type(device: str) -> str:
    """Public helper for the transcription engine to pick a supported precision."""
    return _best_compute_type(device)


def warm_compute_hardware_async() -> None:
    """Populate the hardware cache in a daemon thread, once per process.

    ``detect_compute_hardware()`` performs the heavy first-time import of the
    transcription backend (faster-whisper -> ctranslate2) plus a CUDA probe,
    which otherwise blocks the FIRST open of the transcription-config dialog for
    a noticeable beat. Kicking it off in the background (e.g. when the Settings
    dialog opens) means the cache is usually already populated by the time the
    user reaches that dialog, so it opens promptly.

    Idempotent: no-op if already warmed or a warm-up is already in flight. Never
    raises into the caller (the worker swallows everything; a failed probe just
    leaves the cache empty for the normal on-demand path to fill).
    """
    global _WARM_STARTED
    with _WARM_LOCK:
        if _WARM_STARTED or _CACHE is not None:
            return
        _WARM_STARTED = True

    def _worker() -> None:
        try:
            detect_compute_hardware()
        except Exception:
            logger.debug("Background compute-hardware warm-up failed", exc_info=True)

    threading.Thread(target=_worker, name="warm-compute-hw", daemon=True).start()


def detect_compute_hardware(force: bool = False) -> dict:
    """Return a cached snapshot of the transcription compute hardware.

    Keys:
        platform        : 'windows' | 'macos' | 'linux'
        is_mac, is_arm_mac : bool
        cpu_name, cpu_cores
        engine_ok       : bool | None  (faster-whisper/ctranslate2 importable)
        gpu_available   : bool         (CT2 can actually use a CUDA GPU)
        gpu_name, gpu_vram_mb
        gpu_present_but_unusable : bool (NVIDIA card seen, but CT2 can't use it)
        gpu_reason      : str | None   (why GPU is off, for the UI)
        cuda_compute_types, cpu_compute_types : set
        cuda_has_fp16   : bool         (modern card with fast FP16?)
        recommended_device : 'cpu' | 'cuda'
        status          : 'gpu_ready' | 'gpu_unusable' | 'cpu_only_mac'
                          | 'cpu_only' | 'engine_missing'
    """
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE

    sysname = platform.system()
    machine = (platform.machine() or "").lower()
    is_mac = sysname == "Darwin"
    is_arm_mac = is_mac and machine in ("arm64", "aarch64")

    res: dict = {
        "platform": "macos" if is_mac else ("windows" if sysname == "Windows" else "linux"),
        "is_mac": is_mac,
        "is_arm_mac": is_arm_mac,
        "cpu_name": _cpu_name(),
        "cpu_cores": os.cpu_count() or 0,
        "engine_ok": None,
        "gpu_available": False,
        "gpu_name": None,
        "gpu_vram_mb": None,
        "gpu_present_but_unusable": False,
        "gpu_reason": None,
        "cuda_compute_types": set(),
        "cpu_compute_types": set(),
        "cuda_has_fp16": False,
        "recommended_device": "cpu",
        "status": "cpu_only",
        # Recommended remedy for the UI: None | 'provision' (app can download the
        # CUDA libs) | 'driver' (user must update the NVIDIA driver) | 'engine'.
        "gpu_fix": None,
        "provisioned": False,
    }

    # Make any previously app-provisioned CUDA libs visible to the cuBLAS probe
    # below (and to CTranslate2 later).
    try:
        from panopto import cuda_provision
        cuda_provision.register_dll_dir()
        res["provisioned"] = cuda_provision.is_provisioned()
    except Exception:
        pass

    # Is the engine itself importable? (A broken torch breaks ctranslate2 - see
    # panopto.models.engine_diagnostics.) If not, GPU detection is moot.
    try:
        from panopto import models as pmodels
        engine_ok, _ = pmodels.backend_import_ok()
    except Exception:
        engine_ok = False
    res["engine_ok"] = engine_ok

    # ── macOS: no CUDA backend exists; CPU only. ──
    if is_mac:
        chip = "Apple Silicon" if is_arm_mac else "this Mac"
        res["gpu_reason"] = (
            f"The transcription engine has no GPU backend on macOS - it runs on "
            f"{chip}'s CPU cores"
            + (" (fast for transcription)." if is_arm_mac else ".")
        )
        res["status"] = "cpu_only_mac"
        res["recommended_device"] = "cpu"
        if engine_ok:
            res["cpu_compute_types"] = _ct2_supported_compute_types("cpu")
        _CACHE = res
        return res

    # ── Windows / Linux ──
    if not engine_ok:
        res["gpu_reason"] = "Transcription engine unavailable - install/repair it to use the GPU."
        res["status"] = "engine_missing"
        res["gpu_fix"] = "engine"
        _CACHE = res
        return res

    res["cpu_compute_types"] = _ct2_supported_compute_types("cpu")
    cuda_count = _ct2_cuda_device_count()
    nv = _nvidia_gpus()
    if nv:
        res["gpu_name"] = nv[0]["name"]
        res["gpu_vram_mb"] = nv[0]["vram_mb"]
    gpu_label = (nv[0]["name"] if nv else "An NVIDIA GPU")

    if cuda_count > 0 and _cuda_compute_libs_loadable():
        # Device visible AND the math library inference needs (cuBLAS) loads.
        res["gpu_available"] = True
        res["recommended_device"] = "cuda"
        res["status"] = "gpu_ready"
        res["cuda_compute_types"] = _ct2_supported_compute_types("cuda")
        res["cuda_has_fp16"] = "float16" in res["cuda_compute_types"]
    elif cuda_count > 0:
        # Driver/device present, but cuBLAS/cuDNN are missing - the model would
        # LOAD on the GPU then die at the first transcription. Keep GPU OFF. This
        # is the case the app CAN fix by downloading the CUDA libraries.
        res["recommended_device"] = "cpu"
        res["gpu_present_but_unusable"] = True
        res["status"] = "gpu_unusable"
        try:
            from panopto import cuda_provision
            res["gpu_fix"] = "provision" if cuda_provision.is_supported() else "libs"
        except Exception:
            res["gpu_fix"] = "libs"
        res["gpu_reason"] = (
            f"{gpu_label} detected, but the CUDA libraries (cuBLAS/cuDNN) needed "
            "for GPU transcription aren't installed - using CPU."
        )
    else:
        res["recommended_device"] = "cpu"
        if nv:
            # NVIDIA card present but CT2 can't see a CUDA device at all - the
            # CUDA driver/runtime isn't available (driver missing/too old). We
            # can't auto-install a driver (needs admin + reboot) -> guide instead.
            res["gpu_present_but_unusable"] = True
            res["status"] = "gpu_unusable"
            res["gpu_fix"] = "driver"
            res["gpu_reason"] = (
                f"{gpu_label} detected, but the CUDA driver/runtime needed for GPU "
                "transcription isn't available - using CPU."
            )
        else:
            res["status"] = "cpu_only"
            res["gpu_reason"] = "No NVIDIA GPU detected - using CPU."

    _CACHE = res
    return res


def device_advisory(device: str, model_id: str, hw: dict | None = None) -> tuple[str, str] | None:
    """Return (level, message) advising on the chosen device+model, or None.

    level is 'warn' (likely a problem) or 'info' (heads-up). Covers: a big model
    on CPU (slow), a low-core CPU, a model that may not fit in GPU VRAM, and an
    older GPU without fast FP16.
    """
    hw = hw or detect_compute_hardware()
    big_models = {"medium", "large-v3", "large-v2", "large"}

    if device == "cuda" and hw.get("gpu_available"):
        vram = hw.get("gpu_vram_mb")
        try:
            from panopto.models import get_model
            size_mb = (get_model(model_id) or {}).get("size_mb", 0)
        except Exception:
            size_mb = 0
        # CT2 needs roughly the model size plus working memory; ~1.3x + 1 GB.
        if vram and size_mb and vram < (size_mb * 1.3 + 1024):
            return ("warn",
                    f"This model (~{size_mb} MB) may not fit in your GPU's "
                    f"{vram} MB of VRAM. It will fall back to CPU if it runs out.")
        if not hw.get("cuda_has_fp16"):
            return ("info",
                    "Your GPU is an older model, but it's fully supported and "
                    "transcription will still be much faster than using the CPU.")
        return None

    if device == "cpu":
        cores = hw.get("cpu_cores", 0)
        if model_id in big_models:
            return ("warn",
                    "Large models are slow on the CPU - expect long transcription "
                    "times. The 'Small' model is recommended for CPU"
                    + (", or switch to GPU." if hw.get("gpu_available") else "."))
        if cores and cores < 4 and model_id != "tiny":
            return ("info",
                    f"Only {cores} CPU cores detected - transcription may be slow. "
                    "Consider the 'Tiny' or 'Base' model.")
    return None
