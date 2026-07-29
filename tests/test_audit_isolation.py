"""The audit's isolation guarantees, pinned by the failures that broke them.

An audit run claims to be a sealed application: its own config dir, its own
port, its own browser. Every check the suite makes is worthless if that is not
true, because a finding would then describe a different app than the one it
names. All three of these shipped broken and none of them raised anything:

1. **The port probe asked the wrong question.** Streamlit binds ``0.0.0.0``;
   the probe bound ``127.0.0.1``. On Windows the second succeeds while the
   first is held, so the probe handed out a port another run was serving. The
   new app died with "Port N is already in use" and the readiness loop was
   answered 200 by the *other* app - so a whole phase ran against the wrong
   application and the wrong config dir, reporting success throughout.

2. **"health 200" was accepted as proof of ownership.** ``/_stcore/health``
   identifies nothing. Any Streamlit on that port answers it.

3. **``--run X`` moved the CURRENT pointer.** A read-only ``register show
   --run <other>`` silently re-pointed every later command in the session.

The common shape: a check that is *almost* the right check, failing silently in
the direction of "everything is fine".
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import appctl, paths  # noqa: E402


@pytest.fixture()
def runs_root(tmp_path, monkeypatch):
    root = tmp_path / "_audit_runs"
    root.mkdir()
    monkeypatch.setattr(paths, "RUNS_ROOT", root)
    return root


def _make_run(root: Path, run_id: str, **meta) -> paths.RunPaths:
    rp = paths.RunPaths(run_id)
    rp.root.mkdir(parents=True, exist_ok=True)
    rp.save_meta({"run_id": run_id, **meta})
    return rp


# --------------------------------------------------------------------------
# the port probe
# --------------------------------------------------------------------------

def test_a_wildcard_listener_makes_the_port_unfree():
    """The exact bug: a loopback bind is not the question Streamlit asks."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("0.0.0.0", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert appctl.port_is_free(port) is False, \
            "a port with a wildcard listener was reported free"
    finally:
        srv.close()


def test_the_loopback_only_probe_is_what_gave_the_wrong_answer():
    """Documents WHY the probe changed, so nobody simplifies it back.

    On Windows binding ``127.0.0.1:N`` succeeds against a ``0.0.0.0:N``
    listener. If that ever stops being true this test fails and the wildcard
    probe becomes belt-and-braces rather than load-bearing - which is worth
    knowing either way.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("0.0.0.0", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
            loopback_succeeded = True
        except OSError:
            loopback_succeeded = False
        finally:
            probe.close()
        if sys.platform == "win32":
            assert loopback_succeeded, \
                "the loopback bind no longer succeeds - the trap may be gone"
        assert appctl.port_is_free(port) is False
    finally:
        srv.close()


def test_a_free_port_is_reported_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("0.0.0.0", 0))
    port = s.getsockname()[1]
    s.close()
    assert appctl.port_is_free(port) is True


def test_find_free_port_skips_ports_other_runs_have_claimed():
    """A tab left open by an old run reconnects the moment a server appears."""
    base = appctl.find_free_port()
    got = appctl.find_free_port(base=base, avoid={base, base + 1})
    assert got >= base + 2


def test_find_free_port_reuses_only_after_the_band_is_exhausted():
    base = appctl.find_free_port()
    got = appctl.find_free_port(base=base, span=2, avoid={base, base + 1})
    assert got in (base, base + 1), "should fall back rather than fail"


def test_find_free_port_raises_when_nothing_is_available(monkeypatch):
    monkeypatch.setattr(appctl, "port_is_free", lambda p: False)
    with pytest.raises(SystemExit):
        appctl.find_free_port(base=9000, span=3)


# --------------------------------------------------------------------------
# port history across runs
# --------------------------------------------------------------------------

def test_other_runs_ports_are_collected_and_own_is_excluded(runs_root):
    _make_run(runs_root, "r1", app={"port": 8790})
    _make_run(runs_root, "r2", app={}, ports_used=[8791, 8792])
    mine = _make_run(runs_root, "r3", app={"port": 8799}, ports_used=[8799])
    assert appctl.ports_used_by_other_runs(mine) == {8790, 8791, 8792}


def test_a_stopped_runs_port_stays_claimed(runs_root):
    """``stop`` clears ``app``; the browser tab pointing at that port survives.

    Without ``ports_used`` the port looks free the moment the app stops, and
    the next run lands exactly where a stale tab is waiting.
    """
    _make_run(runs_root, "r1", app={}, ports_used=[8790])
    assert appctl.ports_used_by_other_runs(_make_run(runs_root, "r2")) == {8790}


def test_a_deleted_run_releases_its_port(runs_root):
    _make_run(runs_root, "r1", ports_used=[8790])
    mine = _make_run(runs_root, "r2")
    assert appctl.ports_used_by_other_runs(mine) == {8790}
    import shutil
    shutil.rmtree(runs_root / "r1")
    assert appctl.ports_used_by_other_runs(mine) == set()


def test_a_corrupt_run_json_does_not_break_allocation(runs_root):
    (runs_root / "bad").mkdir()
    (runs_root / "bad" / "run.json").write_text("{not json", encoding="utf-8")
    _make_run(runs_root, "r1", ports_used=[8790])
    assert appctl.ports_used_by_other_runs(_make_run(runs_root, "r2")) == {8790}


def test_the_snapshot_store_is_not_mistaken_for_a_run(runs_root):
    (runs_root / "_snapshots").mkdir()
    (runs_root / "CURRENT").write_text("r1", encoding="utf-8")
    _make_run(runs_root, "r1", ports_used=[8790])
    assert appctl.ports_used_by_other_runs(_make_run(runs_root, "r2")) == {8790}


def test_remember_port_is_idempotent(runs_root):
    rp = _make_run(runs_root, "r1")
    appctl._remember_port(rp, 8790)
    appctl._remember_port(rp, 8790)
    appctl._remember_port(rp, 8791)
    assert rp.load_meta()["ports_used"] == [8790, 8791]


# --------------------------------------------------------------------------
# ownership
# --------------------------------------------------------------------------

def test_ownership_is_unknown_rather_than_false_when_it_cannot_be_determined(
        monkeypatch):
    """None and False mean different things and must not be conflated.

    False means "another process owns this port" and is grounds for refusing to
    start. None means psutil is missing or the query was denied, where refusing
    would make the harness unusable on a locked-down machine.
    """
    monkeypatch.setattr(appctl, "listening_pids", lambda port: set())
    assert appctl._is_ours(1234, 999) is None


def test_our_own_pid_is_recognised(monkeypatch):
    monkeypatch.setattr(appctl, "listening_pids", lambda port: {4242})
    assert appctl._is_ours(1234, 4242) is True


def test_a_foreign_listener_is_rejected(monkeypatch):
    monkeypatch.setattr(appctl, "listening_pids", lambda port: {5555})
    assert appctl._is_ours(1234, 4242) is False


# --------------------------------------------------------------------------
# the CURRENT pointer
# --------------------------------------------------------------------------

def test_run_scoping_does_not_move_the_current_pointer(runs_root):
    _make_run(runs_root, "r1")
    _make_run(runs_root, "r2")
    paths.use_run("r1")
    assert (runs_root / "CURRENT").read_text(encoding="utf-8").strip() == "r1"

    paths.resolve("r2")          # --run r2, a one-off scope
    assert (runs_root / "CURRENT").read_text(encoding="utf-8").strip() == "r1", \
        "--run changed the working run for every later command"


def test_run_use_does_move_the_pointer(runs_root):
    _make_run(runs_root, "r1")
    _make_run(runs_root, "r2")
    paths.use_run("r1")
    paths.use_run("r2")
    assert (runs_root / "CURRENT").read_text(encoding="utf-8").strip() == "r2"


def test_resolve_without_an_id_follows_the_pointer(runs_root):
    _make_run(runs_root, "r1")
    _make_run(runs_root, "r2")
    paths.use_run("r2")
    assert paths.resolve(None).run_id == "r2"


def test_resolving_an_unknown_run_fails_loudly(runs_root):
    with pytest.raises(SystemExit):
        paths.resolve("nope")


# --------------------------------------------------------------------------
# the config-dir seam
# --------------------------------------------------------------------------

def test_every_state_file_lands_in_the_runs_own_config_dir(runs_root, tmp_path):
    rp = paths.RunPaths("r1").create()
    paths.provision_config_dir(rp)
    for name in ("canvas_sync_pairs.json", "canvas_sync_history.json",
                 "saved_sync_groups.json", "saved_download_presets.json",
                 "today_dashboard.json", "canvas_downloader_settings.json"):
        assert (rp.config / name).is_file(), f"{name} was not provisioned"


def test_provisioning_forces_the_settings_the_audit_depends_on(runs_root):
    rp = paths.RunPaths("r1").create()
    paths.provision_config_dir(rp)
    s = json.loads((rp.config / "canvas_downloader_settings.json")
                   .read_text(encoding="utf-8"))
    # debug_mode is oracle O2; without it the audit is blind.
    assert s["debug_mode"] is True
    assert s["error_log_enabled"] is True
    # Unattended runs must not fire OS toasts.
    assert s["notifications_enabled"] is False
    assert s["default_download_path"] == str(rp.downloads)


def test_a_fresh_run_starts_with_no_pairs_history_or_groups(runs_root):
    rp = paths.RunPaths("r1").create()
    paths.provision_config_dir(rp)
    for name in ("canvas_sync_pairs.json", "canvas_sync_history.json",
                 "saved_sync_groups.json"):
        assert json.loads((rp.config / name).read_text(encoding="utf-8")) == []
    today = json.loads((rp.config / "today_dashboard.json").read_text(encoding="utf-8"))
    assert today["pairs"] == [] and today["auto_sync_enabled"] is False


def test_pairs_are_written_in_the_apps_own_format(runs_root):
    rp = paths.RunPaths("r1").create()
    paths.provision_config_dir(rp)
    folder = rp.downloads / "Some Course"
    folder.mkdir(parents=True)
    paths.add_sync_pair(rp, folder, 45899, "Some Course (LA)")
    pairs = json.loads((rp.config / "canvas_sync_pairs.json").read_text(encoding="utf-8"))
    assert len(pairs) == 1
    assert pairs[0]["course_id"] == 45899
    assert pairs[0]["course_name"] == "Some Course (LA)"
    assert "\\" not in pairs[0]["local_folder"], "the app stores forward slashes"
    assert pairs[0]["last_synced"] == ""


def test_registering_the_same_pair_twice_does_not_duplicate_it(runs_root):
    rp = paths.RunPaths("r1").create()
    paths.provision_config_dir(rp)
    folder = rp.downloads / "Some Course"
    folder.mkdir(parents=True)
    paths.add_sync_pair(rp, folder, 45899)
    paths.add_sync_pair(rp, folder, 45899)
    pairs = json.loads((rp.config / "canvas_sync_pairs.json").read_text(encoding="utf-8"))
    assert len(pairs) == 1


def test_today_membership_can_be_added_and_removed(runs_root):
    rp = paths.RunPaths("r1").create()
    paths.provision_config_dir(rp)
    folder = rp.downloads / "Some Course"
    folder.mkdir(parents=True)
    paths.set_today_pair(rp, folder, 45899, auto_sync=True)
    today = json.loads((rp.config / "today_dashboard.json").read_text(encoding="utf-8"))
    assert len(today["pairs"]) == 1 and today["auto_sync_enabled"] is True

    paths.set_today_pair(rp, folder, 45899, remove=True)
    today = json.loads((rp.config / "today_dashboard.json").read_text(encoding="utf-8"))
    assert today["pairs"] == []
    assert today["auto_sync_enabled"] is True, "removing a pair must not flip the toggle"


def test_app_env_points_the_child_at_the_isolated_config_dir(runs_root):
    rp = paths.RunPaths("r1").create()
    env = paths.app_env(rp)
    assert env["CANVAS_DL_CONFIG_DIR"] == str(rp.config)
    assert env["PYTHONUTF8"] == "1"
