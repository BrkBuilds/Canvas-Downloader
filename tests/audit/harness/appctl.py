"""Start, stop and health-check the application under test.

The audit drives the DEV app (``streamlit run app.py``) rather than the
packaged exe: it is the same code, a failure maps straight to a line number,
and its state lands where the harness can read it. The packaged build has its
own risks (PyInstaller excludes, the patched faster-whisper decoder) but those
are a packaging audit, not a behaviour audit.

Two things here are less obvious than they look.

**health 200 does not mean the app is ready.** ``/_stcore/health`` answers as
soon as tornado binds - the frontend, the websocket session and the first
script run all come after it (measured in this project at ~2.9s to React mount
and ~6.9s to first content). So readiness is confirmed from the BROWSER side by
``browser.wait_ready``, and this module only proves the port is serving.

**The port must be genuinely free, and the probe must use the SAME ADDRESS the
server will.** Two independent ways to get this wrong, and this harness shipped
with the second:

* ``SO_REUSEADDR`` on Windows means "bind even if another process is
  LISTENING", so a probe that sets it hands out occupied ports - the app's own
  ``start.py`` documents being bitten by exactly this. The probe below does not
  set it.
* Streamlit binds the **wildcard** address ``0.0.0.0``. A probe that binds
  ``127.0.0.1`` is asking a different question, and Windows answers yes:
  measured on 2026-07-28 with Streamlit listening on ``0.0.0.0:8790``, binding
  ``127.0.0.1:8790`` **succeeded** while ``0.0.0.0:8790`` correctly failed. So
  the probe handed out an occupied port, the new app died with "Port 8790 is
  already in use", and the readiness loop below was answered 200 by the OTHER
  run's app - a whole audit phase then drove the wrong application, against the
  wrong config dir, and nothing anywhere said so.

**Which is why "health 200" is no longer accepted as proof.** ``/_stcore/health``
identifies nothing; any Streamlit on that port answers it. Readiness now
requires that the process LISTENING on the port is our own child, which is the
only unambiguous statement available.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .paths import REPO_ROOT, RunPaths, app_env

DEFAULT_PORT_BASE = 8790


def port_is_free(port: int) -> bool:
    """True only if the WILDCARD address is bindable - see the module docstring."""
    for addr in ("0.0.0.0", "127.0.0.1"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((addr, port))
            except OSError:
                return False
    return True


def find_free_port(base: int = DEFAULT_PORT_BASE, span: int = 200,
                   avoid: set[int] | None = None) -> int:
    """First genuinely free port in [base, base+span), skipping *avoid*.

    *avoid* carries the ports previous runs have used. A port is reused only
    after that whole band is exhausted, because a browser tab left open by an
    earlier run reconnects the instant a new server appears on its port - and
    then that tab is driving an audit run nobody knows about. Observed: a stale
    tab pointed at 8790 restored its own ``?mode=sync&step=4`` into a freshly
    started app and left it sitting on a review screen.
    """
    avoid = avoid or set()
    for port in range(base, base + span):
        if port not in avoid and port_is_free(port):
            return port
    for port in range(base, base + span):          # band exhausted; reuse is fine
        if port_is_free(port):
            return port
    raise SystemExit(f"No free port in {base}..{base + span}")


def listening_pids(port: int) -> set[int]:
    """PIDs with a LISTEN socket on *port*. Empty when it cannot be determined."""
    try:
        import psutil
    except ImportError:
        return set()
    out = set()
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN \
                    and c.pid:
                out.add(c.pid)
    except (psutil.AccessDenied, OSError):
        return set()
    return out


def _is_ours(port: int, pid: int) -> bool | None:
    """Is *pid* (or a descendant) the listener on *port*? None = cannot tell.

    Streamlit re-execs itself in some configurations, so a descendant counts.
    None is returned rather than False when psutil is unavailable or the query
    is denied - the caller then falls back to a weaker check instead of
    refusing to start at all.
    """
    pids = listening_pids(port)
    if not pids:
        return None
    if pid in pids:
        return True
    try:
        import psutil
        kids = {c.pid for c in psutil.Process(pid).children(recursive=True)}
    except Exception:
        return False
    return bool(pids & kids)


def health(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health",
                                    timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start(rp: RunPaths, port: int | None = None, timeout: float = 120.0) -> dict:
    """Launch the app against the run's isolated config dir.

    ``fileWatcherType=none`` is not an optimisation here, it is correctness: the
    watcher re-imports modules on change, and ``core.canvas_debug`` documents
    that a re-import leaves stale logging bridges attached to the root logger so
    every line lands in the debug log two or three times. Oracle O2 counts those
    lines, so a duplicated log entry would read as a duplicated download.
    """
    existing = rp.load_meta().get("app", {})
    if existing.get("port") and health(existing["port"]) \
            and _is_ours(existing["port"], existing.get("pid", -1)) is not False:
        return {"status": "already-running", **existing}

    port = port or find_free_port(avoid=ports_used_by_other_runs(rp))
    log_path = rp.root / "streamlit.log"
    env = app_env(rp)

    cmd = [sys.executable, "-m", "streamlit", "run", "app.py",
           "--server.port", str(port),
           "--server.headless", "true",
           "--server.fileWatcherType", "none",
           "--browser.gatherUsageStats", "false",
           "--server.runOnSave", "false",
           # A long analysis/download run holds the script thread for minutes;
           # the default websocket ping timeout is generous enough, but an
           # oversized message limit stops a 200-row review screen truncating.
           "--server.maxMessageSize", "500"]

    with open(log_path, "ab") as lf:
        lf.write(f"\n=== audit app start {time.strftime('%Y-%m-%d %H:%M:%S')} "
                 f"port={port} ===\n".encode())
        proc = subprocess.Popen(
            cmd, cwd=str(REPO_ROOT), env=env, stdout=lf, stderr=lf,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = _tail(log_path, 40)
            raise SystemExit(f"Streamlit exited with code {proc.returncode}.\n{tail}")
        if health(port):
            # A 200 proves only that SOMETHING serves this port. Require that it
            # is our own child before believing it, or a foreign Streamlit that
            # already owns the port makes a dead launch look successful and the
            # whole run then drives the wrong app against the wrong config dir.
            ours = _is_ours(port, proc.pid)
            if ours is False:
                _kill_tree(proc.pid)
                raise SystemExit(
                    f"Port {port} is served by another process "
                    f"(pids {sorted(listening_pids(port))}), not by this run's app. "
                    f"Stop the other run, or pass an explicit --port.\n"
                    f"{_tail(log_path, 20)}")
            if ours is None and time.time() < deadline - timeout + 3.0:
                # Cannot identify the listener; give the child a moment to fail
                # on its own ("Port N is already in use" and exit) rather than
                # accepting the first 200 that arrives.
                time.sleep(0.4)
                continue
            info = {"port": port, "pid": proc.pid, "url": f"http://127.0.0.1:{port}",
                    "log": str(log_path), "started": time.time(),
                    "verified_owner": bool(ours)}
            rp.update_meta(app=info)
            _remember_port(rp, port)
            return {"status": "started", **info}
        time.sleep(0.4)

    stop(rp)
    raise SystemExit(f"App did not become healthy on port {port} within {timeout}s.\n"
                     f"{_tail(log_path, 40)}")


def ports_used_by_other_runs(rp: RunPaths) -> set[int]:
    """Every app port any run has ever recorded, except this run's own.

    Read from the runs themselves rather than a separate ledger so it cannot
    drift out of sync with reality, and so deleting a run directory genuinely
    releases its port.
    """
    from .paths import RUNS_ROOT
    used: set[int] = set()
    if not RUNS_ROOT.is_dir():
        return used
    for d in RUNS_ROOT.iterdir():
        if not d.is_dir() or d.name in ("CURRENT", "_snapshots") or d.name == rp.run_id:
            continue
        meta = d / "run.json"
        if not meta.is_file():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        for p in (data.get("app", {}).get("port"), *data.get("ports_used", [])):
            if isinstance(p, int):
                used.add(p)
    return used


def _remember_port(rp: RunPaths, port: int) -> None:
    """Keep a run's port history even after its app is stopped.

    ``app`` is cleared on stop, but a browser tab left pointing at that port is
    not - so the port must stay claimed for as long as the run directory does.
    """
    meta = rp.load_meta()
    used = [p for p in meta.get("ports_used", []) if isinstance(p, int)]
    if port not in used:
        used.append(port)
    rp.update_meta(ports_used=used)


def status(rp: RunPaths) -> dict:
    info = rp.load_meta().get("app", {})
    if not info:
        return {"status": "not-started"}
    port = info.get("port", 0)
    if not health(port):
        return {"status": "unreachable", **info}
    ours = _is_ours(port, info.get("pid", -1))
    if ours is False:
        return {"status": "FOREIGN", "detail": f"port {port} is served by "
                f"{sorted(listening_pids(port))}, not by pid {info.get('pid')}",
                **info}
    return {"status": "healthy", "verified_owner": bool(ours), **info}


def stop(rp: RunPaths) -> dict:
    """Kill the app and its whole process tree.

    The tree matters: a download run spawns transcription workers, and a bare
    ``terminate()`` on the parent orphans them - they keep a GPU and a model
    file open, and the next run's model load fails in a way that looks like a
    product bug. This project has already been bitten by an orphaned child
    process surviving ``os._exit`` (see the Store-hang note in CLAUDE.md).
    """
    info = rp.load_meta().get("app", {})
    pid = info.get("pid")
    if not pid:
        return {"status": "not-started"}
    killed = _kill_tree(pid)
    rp.update_meta(app={})
    return {"status": "stopped", "pid": pid, "killed": killed}


def _kill_tree(pid: int) -> bool:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=30)
        else:
            subprocess.run(["pkill", "-TERM", "-P", str(pid)], capture_output=True)
            os.kill(pid, 15)
        return True
    except Exception:
        return False


def _tail(p: Path, n: int) -> str:
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "(no log)"
