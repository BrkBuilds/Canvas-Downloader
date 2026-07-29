"""The local health record - what the Store never gave us.

5 of this app's 6 Store failures came back as "Uncategorized" with no stack
("detailed diagnostic data is not currently available"), which is a known
Partner Center limitation rather than anything fixable on our side. So the app
keeps its own post-mortem. These tests guard the two properties that make it
worth having:

  * an unclean exit is DETECTABLE next launch (the marker's absence is the
    signal, so nothing may write it on a crash path), and
  * the orphan sweep can only ever touch processes this app recorded as its own
    - several unrelated WebView2 hosts (Teams, WhatsApp, Widgets, Phone Link)
    are normally running and killing one of those would be far worse than the
    leak being cleaned up.
"""

import json
import subprocess
import sys

import pytest

from core import health_log


@pytest.fixture
def diag(tmp_path, monkeypatch):
    """Point the module at a throwaway diagnostics dir and reset its state."""
    d = tmp_path / "diagnostics"
    d.mkdir()
    monkeypatch.setattr(health_log, "_diag_dir", lambda: str(d))
    health_log._closed.clear()
    health_log._state.update({
        "phase": "startup", "peak_self_mb": 0.0, "peak_tree_mb": 0.0,
        "children": [], "webview_runtime": "", "sampler": None, "stop": None,
    })
    return d


def _log(diag):
    p = diag / "health.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _write_prev(diag, **fields):
    snap = {"pid": 4242, "clean_exit": False, "phase": "downloading",
            "uptime_s": 90, "peak_self_mb": 210.5, "peak_tree_mb": 660.0,
            "children": [], "env": {}}
    snap.update(fields)
    (diag / "session_state.json").write_text(json.dumps(snap), encoding="utf-8")


def _spawn():
    """A live child, recorded exactly as the sampler would record it."""
    import psutil
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    proc = psutil.Process(p.pid)
    return p, {"pid": p.pid, "name": proc.name(),
               "created": round(proc.create_time(), 3), "mb": 5.0}


# ── The unclean-exit signal ──────────────────────────────────────────────────

def test_clean_exit_is_marked_and_not_reported_next_launch(diag):
    health_log.session_start()
    health_log.session_end("clean")
    assert json.loads((diag / "session_state.json").read_text())["clean_exit"] is True

    (diag / "health.log").unlink()
    health_log.session_start()
    assert "DID NOT EXIT CLEANLY" not in _log(diag)


def test_a_crash_is_never_recorded_as_a_tidy_shutdown(diag):
    """start.py calls session_end from a `finally`, so it runs on the crash path
    too. Only reason='clean' may write the marker - otherwise a crash inside
    webview.start() would erase the one signal we have."""
    health_log.session_start()
    health_log.session_end("crashed")
    state = json.loads((diag / "session_state.json").read_text())
    assert state["clean_exit"] is False
    assert state["end_reason"] == "crashed"


def test_a_late_sampler_tick_cannot_undo_the_clean_marker(diag):
    """The race that would poison the whole signal: session_end sets the
    sampler's stop event, but a sampler already PAST its wait() and inside
    _scan_children() still calls _save_state() afterwards. Unguarded that
    rewrites clean_exit back to False and a perfectly normal shutdown gets
    reported as a crash on the next launch."""
    health_log.session_start()
    health_log.session_end("clean")

    health_log._save_state()          # the late tick, arriving after the marker

    assert json.loads((diag / "session_state.json").read_text())["clean_exit"] is True
    (diag / "health.log").unlink()
    health_log.session_start()
    assert "DID NOT EXIT CLEANLY" not in _log(diag)


def test_unclean_previous_session_is_reported_with_its_phase_and_memory(diag):
    _write_prev(diag)
    health_log.session_start()
    out = _log(diag)
    assert "DID NOT EXIT CLEANLY" in out
    assert "'downloading'" in out        # what it was doing
    assert "210.5" in out and "660.0" in out   # and how much memory it held


def test_session_start_records_the_dimensions_the_store_slices_by(diag):
    """The Store pinned every crash to OS build 10.0.26100 and the one hang to
    10.0.26220 - useless unless the local record carries the same fields."""
    health_log.session_start()
    out = _log(diag)
    assert "SESSION START" in out
    for field in ("app=", "build=", "arch=", "ram_gb=", "frozen="):
        assert field in out


# ── The orphan sweep must be surgical ───────────────────────────────────────

def test_sweep_reaps_a_child_it_genuinely_recorded(diag):
    """The macOS-shaped case too: there is no msedgewebview2.exe there, so the
    sweep must work on any recorded child (transcription worker, ffmpeg) and not
    just on WebView2."""
    victim, entry = _spawn()
    try:
        count, names = health_log._reap_recorded_orphans({"children": [entry]})
        assert count == 1 and names
        victim.wait(timeout=5)
    finally:
        if victim.poll() is None:
            victim.kill()
            victim.wait(timeout=5)


def test_sweep_spares_a_recycled_pid(diag):
    """The one outcome worse than the leak: killing an innocent process that
    inherited the pid. The recorded creation time cannot match, because a
    recycled pid was by definition created later."""
    victim, entry = _spawn()
    try:
        entry = dict(entry, created=entry["created"] - 60.0)   # "an older process"
        count, _ = health_log._reap_recorded_orphans({"children": [entry]})
        assert count == 0
        assert victim.poll() is None, "an unrelated process was killed"
    finally:
        victim.kill()
        victim.wait(timeout=5)


def test_sweep_spares_a_pid_whose_image_name_changed(diag):
    victim, entry = _spawn()
    try:
        entry = dict(entry, name="msedgewebview2.exe")
        count, _ = health_log._reap_recorded_orphans({"children": [entry]})
        assert count == 0
        assert victim.poll() is None
    finally:
        victim.kill()
        victim.wait(timeout=5)


def test_sweep_spares_a_webview2_whose_user_data_dir_does_not_match(diag):
    """Teams/WhatsApp/Widgets all run WebView2. The per-launch user-data-dir is
    the fourth, independent proof that a browser process is OURS."""
    victim, entry = _spawn()
    try:
        entry = dict(entry, udd=r"C:\Temp\tmp_not_this_one")
        count, _ = health_log._reap_recorded_orphans({"children": [entry]})
        assert count == 0
        assert victim.poll() is None
    finally:
        victim.kill()
        victim.wait(timeout=5)


def test_sweep_is_a_noop_on_an_empty_record(diag):
    assert health_log._reap_recorded_orphans({}) == (0, [])
    assert health_log._reap_recorded_orphans({"children": []}) == (0, [])


# ── Diagnostics may never break the app ─────────────────────────────────────

@pytest.mark.parametrize("fn,args", [
    ("session_start", ()), ("session_end", ("clean",)), ("note_phase", ("x",)),
])
def test_nothing_raises_when_the_diagnostics_dir_is_unusable(monkeypatch, fn, args):
    monkeypatch.setattr(health_log, "_diag_dir",
                        lambda: (_ for _ in ()).throw(OSError("read-only")))
    getattr(health_log, fn)(*args)      # must simply return


def test_nothing_raises_without_psutil(diag, monkeypatch):
    import builtins
    real = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "psutil":
            raise ImportError("blocked")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    health_log.session_start()
    health_log.session_end("clean")
    assert health_log._scan_children() == (0.0, 0.0, [], "")


def test_log_rotates_instead_of_growing_without_bound(diag, monkeypatch):
    monkeypatch.setattr(health_log, "_MAX_LOG_BYTES", 2048)
    for _ in range(400):
        health_log._write("x" * 100)
    assert (diag / "health.log").stat().st_size < 2048 * 2


def test_phase_is_persisted_so_a_crash_names_what_it_was_doing(diag):
    health_log.session_start()
    health_log.note_phase("converting")
    assert json.loads((diag / "session_state.json").read_text())["phase"] == "converting"


# ── macOS parity ────────────────────────────────────────────────────────────

def test_build_is_the_platforms_own_version_not_the_darwin_banner(monkeypatch):
    """`build` is one key with a per-platform meaning: "10.0.26100" on Windows
    (what the Store groups by) and "14.6" on macOS. platform.version() is NOT a
    substitute - on macOS it returns the Darwin kernel banner, which nothing
    groups by and which would make the macOS record useless for correlation."""
    import platform as _p
    monkeypatch.setattr(health_log.sys, "platform", "darwin")
    monkeypatch.setattr(_p, "mac_ver", lambda: ("14.6", ("", "", ""), "arm64"))
    monkeypatch.setattr(_p, "version", lambda: "Darwin Kernel Version 23.6.0: ...")
    env = health_log.environment()
    assert env["build"] == "14.6"
    assert env["os"] == "macOS 14.6"
    assert "Darwin" not in env["build"]


def test_rosetta_is_reported_and_is_absent_off_darwin(monkeypatch):
    """platform.machine() cannot reveal translation - under Rosetta it reports
    the emulated x86_64. This app ships arch-pinned native wheels, so a bundle
    running translated has to be visible rather than deduced."""
    assert "rosetta" not in health_log.environment()      # this box is Windows
    monkeypatch.setattr(health_log, "_is_rosetta", lambda: True)
    assert health_log.environment()["rosetta"] is True


def test_is_rosetta_is_false_and_silent_off_darwin():
    assert health_log._is_rosetta() is False


def test_children_are_recorded_with_identity_not_just_a_pid(diag):
    """Every child, on both platforms - macOS has no separate browser process,
    so a WebView2-only scan would leave its record silent about the transcription
    worker and ffmpeg, which are exactly what can be stranded there."""
    victim, _ = _spawn()
    try:
        _self_mb, tree_mb, children, _rt = health_log._scan_children()
        mine = [c for c in children if c["pid"] == victim.pid]
        assert mine, "a live child was not recorded"
        assert set(mine[0]) >= {"pid", "name", "created", "mb"}
        assert tree_mb > 0
    finally:
        victim.kill()
        victim.wait(timeout=5)


def test_download_button_shares_the_app_button_sizing_baseline():
    """stDownloadButton is a SEPARATE Streamlit component from stButton, so it
    inherited none of global.css's button defaults: the Settings > Diagnostics
    card rendered a 40px "Download record" beside a 48px "Show in Explorer" in
    the same st.columns row (measured 2026-07-27). Registering it in the shared
    rule - rather than scoping a fix to that one key - is what stops the next
    st.download_button reintroducing the mismatch."""
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    css = open(_os.path.join(root, "styles", "global.css"), encoding="utf-8").read()
    i_rule = css.index(".stButton>button,")
    block = css[i_rule:css.index("}", i_rule)]
    assert ".stDownloadButton>button" in block


def test_health_record_is_not_offered_on_the_completion_screens():
    """It lived briefly in error_log_dialog, which was wrong twice over: that
    dialog answers "which files failed in the run I just did", and the failure
    this record exists to catch (the app dying) means nobody ever reaches a
    completion screen. Settings is its only home."""
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    comp = open(_os.path.join(root, "shared", "components.py"), encoding="utf-8").read()
    start = comp.index("def error_log_dialog(")
    body = comp[start:comp.index("\ndef ", start + 10)]
    assert "health_log_path" not in body
    auth = open(_os.path.join(root, "ui", "auth.py"), encoding="utf-8").read()
    assert "stg_btn_diag_dl" in auth and "health_log_path" in auth


def test_webview_runtime_version_is_parsed_from_the_exe_path():
    """The WER report named runtime 151.0.4129.21; the local record should be
    able to say the same thing without a WER bundle."""
    m = health_log._WV_VERSION_RE.search(
        r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application"
        r"\151.0.4129.21\msedgewebview2.exe")
    assert m and m.group(1) == "151.0.4129.21"


def test_user_data_dir_is_parsed_from_a_quoted_command_line():
    m = health_log._UDD_RE.search(
        r'msedgewebview2.exe --user-data-dir="C:\Users\x\AppData\Local\Temp\tmp1a2b" --type=gpu')
    assert m and m.group(1).strip('"').endswith("tmp1a2b")
