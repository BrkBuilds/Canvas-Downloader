"""Opt-in CUDA library provisioning for GPU transcription (Windows + NVIDIA).

CTranslate2's CUDA backend needs cuBLAS + cuDNN (+ the CUDA runtime, cudart) at
*inference* time. These are SEPARATE from the CUDA driver, are NOT bundled by the
app (they'd add ~1.3 GB for the minority with NVIDIA GPUs), and on many machines
were only ever present because some other package (e.g. PyTorch) happened to ship
them. When they're missing the model loads on the GPU but the first transcription
dies with ``Library cublas64_12.dll is not found``.

This module downloads the official NVIDIA pip wheels straight from PyPI (zip
archives), extracts just the ``.dll`` files into the app config dir, and registers
that dir on the Windows DLL search path so CTranslate2 finds them - with no system
CUDA install, no admin rights, and no pip (so it works inside the frozen .exe).

Threading + state mirror ``panopto.models`` so the UI can poll a single progress
state and auto-rerun. All public functions are best-effort and never raise.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# (pypi package, required major version). The newest release whose major matches
# is fetched - so a future cuDNN 10 / CUDA 13 can't silently break CT2 4.x, which
# needs cuBLAS 12.x and cuDNN 9.x.
_PACKAGES = [
    ("nvidia-cuda-runtime-cu12", 12),   # cudart64_12.dll (cuBLAS depends on it); tiny
    ("nvidia-cublas-cu12", 12),         # cublas64_12.dll, cublasLt64_12.dll
    ("nvidia-cudnn-cu12", 9),           # cudnn*64_9.dll
]
_WHEEL_TAG = "win_amd64"   # GPU auto-provisioning is Windows-only (see is_supported)
_PYPI_JSON = "https://pypi.org/pypi/{pkg}/json"

# A DLL whose presence means provisioning completed (cuBLAS is the one inference
# fails on first when missing).
_SENTINEL_DLL = "cublas64_12.dll"


# ── Paths ────────────────────────────────────────────────────────────────────

def cuda_libs_dir() -> Path:
    from ui_helpers import get_config_dir
    return Path(get_config_dir()) / "cuda_libs"


def _manifest_path() -> Path:
    return cuda_libs_dir() / ".provision.json"


def is_supported() -> bool:
    """Auto-provisioning is implemented for Windows x64 only. (macOS has no CUDA
    backend; Linux resolves libs via RPATH/LD_LIBRARY_PATH which can't be injected
    at runtime, so those users install system CUDA instead.)"""
    return sys.platform == "win32"


def is_provisioned() -> bool:
    """True if a completed provision is present on disk."""
    try:
        if not (cuda_libs_dir() / _SENTINEL_DLL).exists():
            return False
        mf = _manifest_path()
        if mf.exists():
            with open(mf, "r", encoding="utf-8") as f:
                return bool(json.load(f).get("complete"))
        return True  # sentinel DLL present, legacy/no-manifest -> treat as done
    except Exception:
        return False


def provisioned_version() -> str | None:
    try:
        with open(_manifest_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        vers = data.get("versions", {})
        return ", ".join(f"{k.split('-')[1]} {v}" for k, v in vers.items()) or None
    except Exception:
        return None


# ── DLL search-path registration ─────────────────────────────────────────────

_registered = False


def register_dll_dir() -> bool:
    """Add the provisioned lib dir to the process DLL search path (idempotent).

    Safe to call repeatedly and before/after ctranslate2 is imported: CT2 loads
    cuBLAS/cuDNN lazily at the first GPU op, so adding the directory any time
    before that works. No-op on non-Windows or when nothing is provisioned.
    """
    global _registered
    if _registered or not is_supported():
        return _registered
    d = cuda_libs_dir()
    if not d.exists():
        return False
    try:
        os.add_dll_directory(str(d))
        # Belt-and-suspenders: some loaders consult PATH rather than the secure
        # add_dll_directory list.
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        _registered = True
        logger.info("Registered provisioned CUDA lib dir on DLL path: %s", d)
        return True
    except Exception as e:
        logger.warning("Could not register CUDA lib dir %s: %s", d, e)
        return False


def remove_provision() -> bool:
    """Delete the provisioned libraries (frees ~1.3 GB)."""
    try:
        d = cuda_libs_dir()
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        return True
    except Exception as e:
        logger.warning("Could not remove CUDA libs: %s", e)
        return False


# ── Progress state (module-level, thread-safe) ───────────────────────────────
# {status: idle|resolving|downloading|extracting|done|error|cancelled,
#  phase: str, downloaded_bytes, total_bytes, current, error, cancel}
_STATE: dict = {}
_LOCK = threading.Lock()


def get_state() -> dict | None:
    with _LOCK:
        return dict(_STATE) if _STATE else None


def is_running() -> bool:
    st = get_state()
    return bool(st and st.get("status") in ("resolving", "downloading", "extracting"))


def request_cancel() -> None:
    with _LOCK:
        if _STATE:
            _STATE["cancel"] = True


def clear_state() -> None:
    with _LOCK:
        _STATE.clear()


def _set(**kw) -> None:
    with _LOCK:
        _STATE.update(kw)


def _cancelled() -> bool:
    with _LOCK:
        return bool(_STATE.get("cancel"))


class _Cancelled(Exception):
    pass


# ── Wheel resolution + download ──────────────────────────────────────────────

def _resolve_wheel(pkg: str, major: int) -> dict:
    """Return {version, url, size, sha256, filename} for the newest win_amd64
    wheel of *pkg* whose version major == *major*."""
    with urllib.request.urlopen(_PYPI_JSON.format(pkg=pkg), timeout=30) as r:
        data = json.load(r)
    best_ver = None
    best_key = None
    for ver, files in data.get("releases", {}).items():
        try:
            ver_major = int(ver.split(".")[0])
        except (ValueError, IndexError):
            continue
        if ver_major != major:
            continue
        if not any(_WHEEL_TAG in f["filename"] for f in files):
            continue
        # crude but correct version ordering on the numeric release tuple
        key = tuple(int(x) for x in ver.replace("-", ".").split(".") if x.isdigit())
        if best_key is None or key > best_key:
            best_key, best_ver = key, ver
    if best_ver is None:
        raise RuntimeError(f"No {_WHEEL_TAG} wheel for {pkg} (major {major}) on PyPI.")
    wheel = next(f for f in data["releases"][best_ver] if _WHEEL_TAG in f["filename"])
    return {
        "version": best_ver,
        "url": wheel["url"],
        "size": int(wheel.get("size") or 0),
        "sha256": wheel.get("digests", {}).get("sha256", ""),
        "filename": wheel["filename"],
    }


def estimate_total_mb() -> float:
    """Best-effort total download size (MB), resolved from PyPI; 0 on failure."""
    try:
        return sum(_resolve_wheel(p, m)["size"] for p, m in _PACKAGES) / (1024 * 1024)
    except Exception:
        return 0.0


def _free_disk_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(str(path)).free
    except Exception:
        return 1 << 62  # unknown -> don't block


def _download(url: str, dest: Path, sha256: str, done_before: int, total: int) -> None:
    """Stream *url* to *dest*, updating global byte progress; verify sha256."""
    h = hashlib.sha256()
    got = 0
    req = urllib.request.Request(url, headers={"User-Agent": "CanvasDownloader"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        while True:
            if _cancelled():
                raise _Cancelled()
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            _set(downloaded_bytes=done_before + got)
    if sha256 and h.hexdigest() != sha256:
        raise RuntimeError(f"Checksum mismatch for {dest.name} (download corrupted).")


def _extract_dlls(wheel_path: Path, out_dir: Path) -> int:
    """Extract every *.dll inside the wheel (flat) into out_dir. Returns count."""
    n = 0
    with zipfile.ZipFile(wheel_path) as z:
        for info in z.infolist():
            name = info.filename
            if name.lower().endswith(".dll"):
                target = out_dir / Path(name).name
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                n += 1
    return n


def _worker() -> None:
    out_dir = cuda_libs_dir()
    tmp_dir = out_dir / "_tmp"
    try:
        _set(status="resolving", phase="Resolving NVIDIA packages…",
             downloaded_bytes=0, total_bytes=0, current="")
        wheels = []
        for pkg, major in _PACKAGES:
            if _cancelled():
                raise _Cancelled()
            w = _resolve_wheel(pkg, major)
            w["pkg"] = pkg
            wheels.append(w)
        total = sum(w["size"] for w in wheels)
        _set(total_bytes=total)

        out_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # Disk-space guard: need room for the wheels + their extracted DLLs.
        need = int(total * 2.2)
        if _free_disk_bytes(out_dir) < need:
            raise RuntimeError(
                f"Not enough free disk space (need ~{need / 1e9:.1f} GB free).")

        done_before = 0
        versions = {}
        for w in wheels:
            if _cancelled():
                raise _Cancelled()
            _set(status="downloading", current=w["pkg"],
                 phase=f"Downloading {w['pkg']} {w['version']}…")
            whl = tmp_dir / w["filename"]
            _download(w["url"], whl, w["sha256"], done_before, total)
            done_before += w["size"]
            _set(status="extracting", phase=f"Installing {w['pkg']}…")
            _extract_dlls(whl, out_dir)
            try:
                whl.unlink()
            except OSError:
                pass
            versions[w["pkg"]] = w["version"]

        # Manifest (marks completion).
        with open(_manifest_path(), "w", encoding="utf-8") as f:
            json.dump({"complete": True, "versions": versions,
                       "completed_at": time.time()}, f, indent=2)

        shutil.rmtree(tmp_dir, ignore_errors=True)
        register_dll_dir()
        # Refresh the cached hardware snapshot so the UI flips to gpu_ready.
        try:
            from panopto.hardware import detect_compute_hardware
            detect_compute_hardware(force=True)
        except Exception:
            pass
        _set(status="done", phase="GPU acceleration ready.")
        logger.info("CUDA libs provisioned: %s", versions)
    except _Cancelled:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _set(status="cancelled", phase="Cancelled.")
        logger.info("CUDA provisioning cancelled by user.")
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _set(status="error", error=str(e), phase="Download failed.")
        logger.warning("CUDA provisioning failed: %s", e)


def start_provision() -> bool:
    """Kick off provisioning on a daemon thread. Returns False if not startable."""
    if not is_supported():
        _set(status="error", error="GPU auto-setup is only available on Windows.")
        return False
    if is_running():
        return False
    with _LOCK:
        _STATE.clear()
        _STATE.update(status="resolving", cancel=False, downloaded_bytes=0,
                      total_bytes=0, phase="Starting…", current="")
    threading.Thread(target=_worker, daemon=True).start()
    return True
