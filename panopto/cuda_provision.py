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
    from shared.helpers import get_config_dir
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

    Also the point where a removal deferred from a previous session is carried
    out - see ``process_pending_removal``. It runs here because this is the
    earliest, most reliable moment in a fresh process: it is called before
    anything can load a DLL out of that directory, so the delete can succeed.
    """
    global _registered
    process_pending_removal()
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
    """Delete the provisioned libraries (frees ~1.3 GB).

    Returns True only when the directory is actually gone. This used to
    ``rmtree(ignore_errors=True)`` and then ``return True`` unconditionally, which
    made the honest failure path unreachable: on Windows the CUDA DLLs are loaded
    into this process once GPU transcription has run, so rmtree silently skips
    them and ~1.3 GB stays on disk while the UI reports success. The caller shows
    a "they may be in use" notice on False - it could never fire.

    Refuses while a provisioning download/extract is in flight; deleting the tree
    underneath the extractor would corrupt a half-written install.
    """
    if is_running() or _worker_alive():
        # _worker_alive() covers the window a cancel opens: the UI is released
        # the moment Cancel is clicked, so "not running" no longer means "no
        # thread touching this directory". Deleting the tree out from under a
        # winding-down extractor is the corruption this guard exists to stop.
        logger.warning("Refusing to remove CUDA libs while provisioning is running.")
        return False
    try:
        d = cuda_libs_dir()
        if not d.exists():
            return True                      # already absent - nothing to do
        # ignore_errors so a single locked DLL does not abort the rest of the
        # tree; the post-check below is what decides success.
        shutil.rmtree(d, ignore_errors=True)
        if not d.exists():
            return True
        # Partial delete: report the leftovers so the caller can tell the user
        # something is holding them rather than claiming the space was freed.
        try:
            leftover = sum(1 for _ in d.rglob('*') if _.is_file())
        except Exception:
            leftover = -1
        logger.warning("CUDA libs only partially removed - %s file(s) remain in %s "
                       "(most likely loaded by this process).", leftover, d)
        return False
    except Exception as e:
        logger.warning("Could not remove CUDA libs: %s", e)
        return False


# ── Deferred removal ─────────────────────────────────────────────────────────
# `remove_provision` genuinely CANNOT succeed once this process has loaded the
# DLLs - Windows holds an open handle on every loaded module, and nothing the
# app does short of exiting will release it. Telling the user to "close the app
# and try again" is correct but puts the work on them, and they have to
# remember to do it before anything touches the GPU. So the request is written
# down instead and executed at the top of the next launch, when the directory
# is provably not in use yet.

def _pending_removal_marker() -> Path:
    from shared.helpers import get_config_dir
    return Path(get_config_dir()) / "cuda_libs.pending_delete"


def request_removal_on_restart() -> bool:
    """Mark the CUDA libraries for deletion at the next app start.

    Returns True if the request was recorded (or there is nothing to delete).
    """
    try:
        if not cuda_libs_dir().exists():
            return True
        _pending_removal_marker().write_text(str(time.time()), encoding="utf-8")
        logger.info("CUDA library removal deferred to next launch.")
        return True
    except Exception as e:
        logger.warning("Could not record deferred CUDA removal: %s", e)
        return False


def removal_pending() -> bool:
    """True if a removal has been requested but not carried out yet."""
    try:
        return _pending_removal_marker().exists() and cuda_libs_dir().exists()
    except Exception:
        return False


def cancel_pending_removal() -> None:
    """Drop a deferred removal request (the user changed their mind)."""
    try:
        _pending_removal_marker().unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("Could not clear deferred CUDA removal: %s", e)


def process_pending_removal() -> bool:
    """Carry out a removal requested in a previous session. Idempotent.

    Called from ``register_dll_dir`` - the earliest point in a fresh process,
    before any DLL can be loaded out of the directory. Returns True if a
    pending removal was found and completed.
    """
    try:
        marker = _pending_removal_marker()
        if not marker.exists():
            return False
        ok = remove_provision()
        if ok:
            marker.unlink(missing_ok=True)
            logger.info("Deferred CUDA library removal completed.")
        else:
            # Keep the marker so the next launch tries again rather than
            # silently leaving 1.3 GB behind.
            logger.warning("Deferred CUDA library removal did not complete; "
                           "will retry on the next launch.")
        return ok
    except Exception as e:
        logger.warning("Deferred CUDA removal failed: %s", e)
        return False


# ── Progress state (module-level, thread-safe) ───────────────────────────────
# {gen, status: Finding|downloading|extracting|installing|done|error|cancelled,
#  phase: str, downloaded_bytes, total_bytes, current, error, final}
#
# Every run carries a generation number and every state write is gated on it, so
# a worker that is still unwinding after a cancel can never write over the run
# that replaced it (or over the terminal state the UI is already showing).
_STATE: dict = {}
_LOCK = threading.Lock()
_GEN = 0
_RUN: "_Run | None" = None


class _Run:
    """One provisioning attempt: its generation, its cancel flag and its thread.

    The cancel flag lives here rather than in ``_STATE`` because ``_STATE`` is
    reset by the next run, and a worker that has not noticed the cancel yet must
    keep seeing its OWN flag.
    """

    __slots__ = ("gen", "cancel", "thread")

    def __init__(self, gen: int) -> None:
        self.gen = gen
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None


def get_state() -> dict | None:
    with _LOCK:
        return dict(_STATE) if _STATE else None


def is_running() -> bool:
    st = get_state()
    return bool(st and st.get("status") in
                ("Finding", "downloading", "extracting", "installing"))


def _worker_alive() -> bool:
    """True while a provisioning thread is still executing - INCLUDING one that
    has been cancelled and is unwinding. Distinct from ``is_running``, which
    answers the UI's question ("is a provision in progress for the user?")."""
    run = _RUN
    return bool(run and run.thread and run.thread.is_alive())


def request_cancel() -> None:
    """Cancel the run and report it as cancelled IMMEDIATELY.

    The worker can be parked in a blocking socket read, or half-way through
    unzipping a single 700 MB cuDNN DLL, so waiting for it to notice left the UI
    frozen on a motionless progress bar for a minute or more - the user clicks
    Cancel, nothing happens, they click again, and eventually the card returns on
    its own. Nothing the worker does after this point is user-visible: it writes
    only inside its own staging directory (never into the installed lib dir) and
    its state updates are dropped by ``_set``. So the honest answer is available
    now, and the thread is left to wind down on its own time.
    """
    run = _RUN
    if run is not None:
        run.cancel.set()
    with _LOCK:
        if _STATE and not _STATE.get("final"):
            _STATE.update(status="cancelled", phase="Cancelled.", final=True)


def clear_state() -> None:
    with _LOCK:
        _STATE.clear()


def _set(gen: int, **kw) -> None:
    """Publish progress for run *gen* - dropped if that run is superseded or
    already finished (cancelled/errored/done)."""
    with _LOCK:
        if _STATE.get("gen") != gen or _STATE.get("final"):
            return
        _STATE.update(kw)


def _finalize(gen: int, **kw) -> None:
    """Publish the terminal state for run *gen*; later writes are ignored."""
    with _LOCK:
        if _STATE.get("gen") != gen or _STATE.get("final"):
            return
        _STATE.update(final=True, **kw)


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


def _free_disk_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(str(path)).free
    except Exception:
        return 1 << 62  # unknown -> don't block


def _download(url: str, dest: Path, sha256: str, done_before: int,
              run: "_Run") -> None:
    """Stream *url* to *dest*, updating byte progress; verify sha256."""
    h = hashlib.sha256()
    got = 0
    req = urllib.request.Request(url, headers={"User-Agent": "CanvasDownloader"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        while True:
            if run.cancel.is_set():
                raise _Cancelled()
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            _set(run.gen, downloaded_bytes=done_before + got)
    if sha256 and h.hexdigest() != sha256:
        raise RuntimeError(f"Checksum mismatch for {dest.name} (download corrupted).")


def _extract_dlls(wheel_path: Path, stage_dir: Path, run: "_Run") -> int:
    """Extract every *.dll inside the wheel (flat) into *stage_dir*.

    Copies in 1 MB blocks with a cancel check per block rather than one
    ``copyfileobj`` per member: cuDNN ships single DLLs of several hundred MB, so
    a per-member check meant a Cancel pressed during extraction was not seen for
    a minute or more - with the progress bar frozen the whole time, because
    extraction moves no bytes of its own.
    """
    n = 0
    with zipfile.ZipFile(wheel_path) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".dll"):
                continue
            if run.cancel.is_set():
                raise _Cancelled()
            target = stage_dir / Path(info.filename).name
            with z.open(info) as src, open(target, "wb") as dst:
                while True:
                    if run.cancel.is_set():
                        raise _Cancelled()
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    dst.write(block)
            n += 1
    return n


def _install_staged(stage_dir: Path, out_dir: Path) -> None:
    """Move the staged DLLs into the live lib dir.

    Extraction happens in a staging dir and only lands here once every wheel has
    been fetched and unpacked, so an interrupted provision cannot leave a
    half-installed set behind. That mattered: ``is_provisioned()`` treats the
    presence of cublas64_12.dll as "installed", so a run cancelled after cuBLAS
    but before cuDNN used to report GPU-ready and then fail at inference.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(stage_dir.glob("*.dll")):
        dst = out_dir / src.name
        try:
            os.replace(src, dst)
        except OSError as e:
            # Windows holds an open handle on a DLL this process has already
            # loaded, so re-provisioning over a live install fails here. The
            # loaded file IS the library we were about to write, so keeping it
            # is correct; only a missing destination is a real failure.
            if not dst.exists():
                raise RuntimeError(
                    f"Could not install {src.name}: {e}") from e
            logger.info("Kept the in-use copy of %s (already loaded).", src.name)


def _worker(run: "_Run") -> None:
    out_dir = cuda_libs_dir()
    # Per-run staging dir. A worker that is still unwinding after a cancel must
    # not be able to touch the files of the run that replaced it, and nothing
    # reaches the live lib dir until every wheel is unpacked (see
    # _install_staged).
    tmp_dir = out_dir / f"_tmp{run.gen}"
    stage_dir = tmp_dir / "dll"
    try:
        _set(run.gen, status="Finding", phase="Finding NVIDIA packages…",
             downloaded_bytes=0, total_bytes=0, current="")
        wheels = []
        for pkg, major in _PACKAGES:
            if run.cancel.is_set():
                raise _Cancelled()
            w = _resolve_wheel(pkg, major)
            w["pkg"] = pkg
            wheels.append(w)
        total = sum(w["size"] for w in wheels)
        _set(run.gen, total_bytes=total)

        stage_dir.mkdir(parents=True, exist_ok=True)

        # Disk-space guard: need room for the wheels + their extracted DLLs.
        need = int(total * 2.2)
        if _free_disk_bytes(out_dir) < need:
            raise RuntimeError(
                f"Not enough free disk space (need ~{need / 1e9:.1f} GB free).")

        done_before = 0
        versions = {}
        for w in wheels:
            if run.cancel.is_set():
                raise _Cancelled()
            _set(run.gen, status="downloading", current=w["pkg"],
                 phase=f"Downloading {w['pkg']} {w['version']}…")
            whl = tmp_dir / w["filename"]
            _download(w["url"], whl, w["sha256"], done_before, run)
            done_before += w["size"]
            _set(run.gen, status="extracting", current=w["pkg"],
                 phase=f"Unpacking {w['pkg']}…")
            _extract_dlls(whl, stage_dir, run)
            try:
                whl.unlink()
            except OSError:
                pass
            versions[w["pkg"]] = w["version"]

        if run.cancel.is_set():
            raise _Cancelled()
        _set(run.gen, status="installing", phase="Installing CUDA libraries…")
        _install_staged(stage_dir, out_dir)

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
        _finalize(run.gen, status="done", phase="GPU acceleration ready.")
        logger.info("CUDA libs provisioned: %s", versions)
    except _Cancelled:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # Usually a no-op: request_cancel() already published this. It still
        # matters when the run stops for an internal reason (e.g. the app is
        # shutting down) with no UI click behind it.
        _finalize(run.gen, status="cancelled", phase="Cancelled.")
        logger.info("CUDA provisioning cancelled (run %s).", run.gen)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _finalize(run.gen, status="error", error=str(e), phase="Download failed.")
        logger.warning("CUDA provisioning failed: %s", e)


def _purge_stale_staging() -> None:
    """Delete staging dirs left behind by a crash/kill (they can hold ~1.3 GB)."""
    try:
        base = cuda_libs_dir()
        if not base.exists():
            return
        for d in base.glob("_tmp*"):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
    except Exception as e:
        logger.debug("Could not purge CUDA staging dirs: %s", e)


def start_provision() -> bool:
    """Kick off provisioning on a daemon thread. Returns False if not startable."""
    global _GEN, _RUN
    if not is_supported():
        with _LOCK:
            _STATE.clear()
            _STATE.update(gen=0, status="error", final=True,
                          error="GPU auto-setup is only available on Windows.",
                          phase="Unavailable.")
        return False
    if is_running():
        return False

    prev = _RUN
    if _worker_alive():
        # A cancelled worker can still be unwinding - a blocking socket read
        # returns only when the peer sends or the timeout expires. It owns a
        # private staging dir and its state writes are dropped, so it cannot
        # interfere; joining it here would just make this click look dead.
        logger.info("Starting CUDA provisioning while run %s is still "
                    "winding down.", prev.gen)
    else:
        _purge_stale_staging()

    _GEN += 1
    run = _Run(_GEN)
    with _LOCK:
        _STATE.clear()
        _STATE.update(gen=run.gen, status="Finding", downloaded_bytes=0,
                      total_bytes=0, phase="Starting…", current="")
    run.thread = threading.Thread(target=_worker, args=(run,), daemon=True,
                                  name=f"cuda-provision-{run.gen}")
    _RUN = run
    run.thread.start()
    return True
