"""CUDA provisioning: cancellation latency, run isolation, staged install.

Every case here reproduces a defect that shipped:

* Cancel was only observed between wheel chunks, so a Cancel pressed while a
  700 MB cuDNN DLL was being unpacked did nothing for a minute or two - with a
  frozen progress bar, because unpacking moves no download bytes.
* The UI waited for the worker to acknowledge the cancel, so that latency was
  the user's latency.
* Extraction wrote straight into the live lib dir, so a run stopped after cuBLAS
  but before cuDNN left the sentinel DLL behind and ``is_provisioned()`` then
  claimed GPU-ready for an install that fails at inference.
"""

import json
import zipfile

import pytest

import panopto.cuda_provision as cp


@pytest.fixture(autouse=True)
def _clean_state():
    cp.clear_state()
    cp._RUN = None
    yield
    cp.clear_state()
    cp._RUN = None


def _run(gen: int = 1) -> "cp._Run":
    """A run registered as the current one, with state seeded like a live run."""
    r = cp._Run(gen)
    cp._RUN = r
    with cp._LOCK:
        cp._STATE.clear()
        cp._STATE.update(gen=gen, status="downloading", downloaded_bytes=0,
                         total_bytes=100, phase="Downloading…")
    return r


# ── Cancellation is immediate and terminal ──────────────────────────────────

def test_cancel_is_reported_without_waiting_for_the_worker():
    r = _run()
    assert cp.is_running() is True
    cp.request_cancel()
    assert r.cancel.is_set(), "the worker must still be told to stop"
    st = cp.get_state()
    assert st["status"] == "cancelled"
    assert cp.is_running() is False, "the UI must be free the instant Cancel is clicked"


def test_a_cancelled_worker_cannot_write_over_the_terminal_state():
    r = _run()
    cp.request_cancel()
    # The worker is mid-chunk and keeps publishing for a while afterwards.
    cp._set(r.gen, status="downloading", downloaded_bytes=999, phase="Downloading…")
    cp._finalize(r.gen, status="error", error="socket timeout")
    assert cp.get_state()["status"] == "cancelled"
    assert cp.get_state()["downloaded_bytes"] == 0


def test_a_superseded_worker_cannot_write_over_the_new_run():
    old = _run(gen=1)
    cp.request_cancel()
    _run(gen=2)                       # the user immediately tries again
    cp._set(old.gen, status="downloading", downloaded_bytes=777)
    cp._finalize(old.gen, status="cancelled")
    st = cp.get_state()
    assert st["gen"] == 2 and st["status"] == "downloading"
    assert st["downloaded_bytes"] == 0


def test_finalize_wins_only_once():
    r = _run()
    cp._finalize(r.gen, status="done", phase="GPU acceleration ready.")
    cp._finalize(r.gen, status="error", error="late failure")
    assert cp.get_state()["status"] == "done"


# ── Extraction notices a cancel inside a single huge member ─────────────────

def _wheel_with(path, name: str, size: int):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"nvidia/bin/{name}", b"\0" * size)
    return path


def test_extract_aborts_inside_a_single_large_dll(tmp_path):
    """A per-member check was not enough: cuDNN ships DLLs of several hundred
    MB, so one member IS the whole stall."""
    wheel = _wheel_with(tmp_path / "w.whl", "cudnn64_9.dll", 8 * 1024 * 1024)
    stage = tmp_path / "stage"
    stage.mkdir()
    r = cp._Run(1)
    r.cancel.set()
    with pytest.raises(cp._Cancelled):
        cp._extract_dlls(wheel, stage, r)


def test_extract_writes_only_dlls_and_flattens(tmp_path):
    wheel = tmp_path / "w.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("nvidia/bin/cublas64_12.dll", b"abc")
        z.writestr("nvidia/include/thing.h", b"no")
    stage = tmp_path / "stage"
    stage.mkdir()
    assert cp._extract_dlls(wheel, stage, cp._Run(1)) == 1
    assert (stage / "cublas64_12.dll").read_bytes() == b"abc"
    assert not (stage / "thing.h").exists()


# ── Staged install ──────────────────────────────────────────────────────────

def test_install_staged_moves_everything_into_the_lib_dir(tmp_path):
    stage, out = tmp_path / "stage", tmp_path / "libs"
    stage.mkdir()
    (stage / "cublas64_12.dll").write_bytes(b"a")
    (stage / "cudnn64_9.dll").write_bytes(b"b")
    cp._install_staged(stage, out)
    assert sorted(p.name for p in out.glob("*.dll")) == \
        ["cublas64_12.dll", "cudnn64_9.dll"]


def test_install_staged_keeps_a_locked_destination(tmp_path, monkeypatch):
    """Windows holds an open handle on a DLL this process has loaded, so
    re-provisioning over a live install cannot replace it - and must not fail:
    the loaded file IS the library we were about to write."""
    stage, out = tmp_path / "stage", tmp_path / "libs"
    stage.mkdir()
    out.mkdir()
    (stage / "cublas64_12.dll").write_bytes(b"new")
    (out / "cublas64_12.dll").write_bytes(b"loaded")
    monkeypatch.setattr(cp.os, "replace",
                        lambda *a: (_ for _ in ()).throw(PermissionError(32, "in use")))
    cp._install_staged(stage, out)          # must not raise
    assert (out / "cublas64_12.dll").read_bytes() == b"loaded"


def test_install_staged_raises_when_the_file_is_simply_missing(tmp_path, monkeypatch):
    stage, out = tmp_path / "stage", tmp_path / "libs"
    stage.mkdir()
    (stage / "cublas64_12.dll").write_bytes(b"new")
    monkeypatch.setattr(cp.os, "replace",
                        lambda *a: (_ for _ in ()).throw(OSError(13, "denied")))
    with pytest.raises(RuntimeError):
        cp._install_staged(stage, out)


# ── A partial run never reads as provisioned ────────────────────────────────

def test_partial_run_leaves_no_sentinel_in_the_lib_dir(tmp_path, monkeypatch):
    """The sentinel DLL is what is_provisioned() trusts, so it must only ever
    appear once the whole set is installed."""
    libs = tmp_path / "cuda_libs"
    monkeypatch.setattr(cp, "cuda_libs_dir", lambda: libs)
    stage = libs / "_tmp1" / "dll"
    stage.mkdir(parents=True)
    (stage / cp._SENTINEL_DLL).write_bytes(b"partial")   # cuBLAS done, cuDNN not
    assert cp.is_provisioned() is False


def test_provisioned_requires_a_complete_manifest(tmp_path, monkeypatch):
    libs = tmp_path / "cuda_libs"
    libs.mkdir()
    monkeypatch.setattr(cp, "cuda_libs_dir", lambda: libs)
    (libs / cp._SENTINEL_DLL).write_bytes(b"x")
    (libs / ".provision.json").write_text(json.dumps({"complete": False}),
                                          encoding="utf-8")
    assert cp.is_provisioned() is False
    (libs / ".provision.json").write_text(
        json.dumps({"complete": True, "versions": {}}), encoding="utf-8")
    assert cp.is_provisioned() is True


# ── Staging hygiene ─────────────────────────────────────────────────────────

def test_stale_staging_dirs_are_purged(tmp_path, monkeypatch):
    libs = tmp_path / "cuda_libs"
    (libs / "_tmp3" / "dll").mkdir(parents=True)
    (libs / "_tmp3" / "big.whl").write_bytes(b"x" * 1024)
    (libs / "cublas64_12.dll").write_bytes(b"keep")
    monkeypatch.setattr(cp, "cuda_libs_dir", lambda: libs)
    cp._purge_stale_staging()
    assert not (libs / "_tmp3").exists()
    assert (libs / "cublas64_12.dll").exists(), "must not touch the install"


def test_start_provision_refuses_while_a_run_is_live(monkeypatch):
    _run()
    monkeypatch.setattr(cp, "is_supported", lambda: True)
    assert cp.start_provision() is False


def test_remove_refuses_while_a_cancelled_worker_is_still_unwinding(monkeypatch,
                                                                    tmp_path):
    """Cancel releases the UI immediately, so `not is_running()` no longer means
    "no thread is touching this directory" - deleting the tree under a
    winding-down extractor is exactly the corruption the guard exists to stop."""
    libs = tmp_path / "cuda_libs"
    libs.mkdir()
    (libs / "cublas64_12.dll").write_bytes(b"x")
    monkeypatch.setattr(cp, "cuda_libs_dir", lambda: libs)
    r = _run()
    cp.request_cancel()
    assert cp.is_running() is False           # the user is free to click on
    r.thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()
    assert cp.remove_provision() is False
    assert (libs / "cublas64_12.dll").exists()


# ── The worker, end to end ──────────────────────────────────────────────────

def _fake_wheels(tmp_path, monkeypatch, dll_names=("cublas64_12.dll", "cudnn64_9.dll")):
    """Serve local wheels through _resolve_wheel + _download, so the worker runs
    for real without touching PyPI."""
    wheels = {}
    for i, dll in enumerate(dll_names):
        p = tmp_path / f"pkg{i}.whl"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr(f"nvidia/bin/{dll}", bytes([i]) * 4096)
        wheels[f"pkg{i}"] = p

    monkeypatch.setattr(cp, "_PACKAGES", [(k, 12) for k in wheels])
    monkeypatch.setattr(cp, "_resolve_wheel", lambda pkg, major: {
        "version": "1.2.3", "url": str(wheels[pkg]), "size": wheels[pkg].stat().st_size,
        "sha256": "", "filename": wheels[pkg].name})

    def _dl(url, dest, sha256, done_before, run):
        if run.cancel.is_set():
            raise cp._Cancelled()
        dest.write_bytes(open(url, "rb").read())
    monkeypatch.setattr(cp, "_download", _dl)
    return wheels


def test_worker_installs_and_marks_complete(tmp_path, monkeypatch):
    libs = tmp_path / "cuda_libs"
    monkeypatch.setattr(cp, "cuda_libs_dir", lambda: libs)
    monkeypatch.setattr(cp, "_manifest_path", lambda: libs / ".provision.json")
    monkeypatch.setattr(cp, "register_dll_dir", lambda: True)
    _fake_wheels(tmp_path, monkeypatch)

    run = cp._Run(1)
    cp._RUN = run
    with cp._LOCK:
        cp._STATE.clear()
        cp._STATE.update(gen=1, status="Finding")
    cp._worker(run)

    st = cp.get_state()
    assert st["status"] == "done", st
    assert sorted(p.name for p in libs.glob("*.dll")) == \
        ["cublas64_12.dll", "cudnn64_9.dll"]
    assert not list(libs.glob("_tmp*")), "staging must be cleaned up"
    assert cp.is_provisioned() is True


def test_worker_leaves_nothing_behind_when_cancelled(tmp_path, monkeypatch):
    """The whole point of staging: a cancel must not leave the sentinel DLL (or
    a half-written one) where is_provisioned() will find it."""
    libs = tmp_path / "cuda_libs"
    monkeypatch.setattr(cp, "cuda_libs_dir", lambda: libs)
    monkeypatch.setattr(cp, "_manifest_path", lambda: libs / ".provision.json")
    monkeypatch.setattr(cp, "register_dll_dir", lambda: True)
    wheels = _fake_wheels(tmp_path, monkeypatch)

    run = cp._Run(1)
    cp._RUN = run
    with cp._LOCK:
        cp._STATE.clear()
        cp._STATE.update(gen=1, status="Finding")

    # Cancel as soon as the first wheel has been unpacked.
    real_extract = cp._extract_dlls

    def _extract(whl, stage, r):
        n = real_extract(whl, stage, r)
        cp.request_cancel()
        return n
    monkeypatch.setattr(cp, "_extract_dlls", _extract)

    cp._worker(run)

    assert cp.get_state()["status"] == "cancelled"
    assert list(libs.glob("*.dll")) == [], "nothing may reach the live lib dir"
    assert not list(libs.glob("_tmp*")), "staging must be cleaned up"
    assert cp.is_provisioned() is False
    assert wheels  # (kept for readability of the fixture)
