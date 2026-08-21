"""Drive the PACKAGED ``Canvas Downloader.app`` with the live-audit harness.

Why this exists
---------------
The bundle serves Streamlit on a loopback port and Streamlit runs the script in
the SERVER process, so a Playwright session pointed at that port executes
**inside the packaged app**: its children are the app's children and its Apple
events carry the app's own TCC identity (``com.canvasdownloader.app``).  That is
the only way to exercise the code paths that depend on the bundle's signature -
Automation grants, the powerbox, the Keychain ACL - and it removes the whole
CoreGraphics-clicking problem the earlier macOS sessions fought.

The reusable part is that it **reuses the harness rather than restating it**.
``Flow``/``DownloadFlow`` already know that the settings are ``st.button``s whose
state lives only in CSS ("ON iff the border colour is CHROMATIC"), that toggles
are addressed by KEY and never by text, and that a card's contents do not exist
in the DOM until the card is expanded.  A driver written from scratch
rediscovers all of that badly - measured, twice.

The only thing this module adds is pointing that machinery at a port the harness
did not start.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .browser import Session
from .flows import DownloadFlow, SyncFlow
from .paths import RunPaths


def attach(run_id: str, port: int, playwright, *, headless: bool = True):
    """Return ``(rp, browser, session)`` bound to an ALREADY-RUNNING app.

    ``run_id`` only decides where evidence lands; the app's own state lives in
    whatever ``CANVAS_DL_CONFIG_DIR`` the bundle was launched with, which is
    deliberately not ours to choose here.  Recording the port in the run meta is
    what lets ``Session.app_url`` keep working for callers that use it.
    """
    rp = RunPaths(run_id).create()
    meta = rp.load_meta()
    meta.setdefault("app", {})["port"] = port
    meta["app"]["packaged"] = True
    rp.meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    browser = playwright.chromium.launch(headless=headless)
    page = browser.new_page(viewport={"width": 1600, "height": 1200})
    page.set_default_timeout(120000)
    session = Session(rp, page)
    return rp, browser, session


# Absolute, because ``open -a`` resolves a RELATIVE path against the app
# registry rather than the cwd and fails with a bare exit 1.
REPO = Path(__file__).resolve().parents[3]
BUNDLE = REPO / "dist" / "Canvas Downloader.app"


def env_of(pid: int) -> dict:
    """The environment a running process was started with.

    ``ps -Eww`` is the only view of this that does not need the process to
    cooperate, and it is what makes :func:`launch` able to VERIFY rather than
    assume.
    """
    import subprocess

    try:
        out = subprocess.run(["ps", "-Eww", "-p", str(pid)],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return {}
    env = {}
    for tok in out.split():
        if "=" in tok:
            k, _, v = tok.partition("=")
            if k.isupper() or k.startswith("CANVAS_"):
                env[k] = v
    return env


def launch(config_dir: str | Path, bundle: str | Path = BUNDLE,
           port: int = 8501, timeout: float = 180.0) -> int:
    """Launch the packaged app on ``config_dir`` and PROVE the override took.

    ``open --env`` is not sticky, and the failure is silent in the worst way:
    a second launch (a Dock click, a stray ``open``) starts an instance with no
    ``CANVAS_DL_CONFIG_DIR`` at all, and because the single-instance lock lives
    INSIDE the config dir the two instances cannot see each other - so both run,
    the audit attaches to whichever answers the port, and every oracle is then
    reading the developer's real state while believing it is isolated.  That is
    exactly the contamination ``README.md`` calls "total or worthless", and it
    cost this session a whole 152-file run before the empty download directory
    gave it away.

    So the launch is not complete until the override is read back off the
    RUNNING process.  Raises rather than returning a pid it cannot vouch for.
    """
    import subprocess

    config_dir = str(Path(config_dir).resolve())
    if not Path(config_dir).is_dir():
        raise RuntimeError(f"config dir does not exist: {config_dir}")

    existing = app_pid()
    if existing:
        raise RuntimeError(
            f"an instance is already running (pid {existing}); quit it first - "
            "attaching to it would silently audit whatever config IT was given"
        )

    bundle = Path(bundle).resolve()
    if not bundle.is_dir():
        raise RuntimeError(f"bundle not found: {bundle}")
    subprocess.run(["open", "--env", f"CANVAS_DL_CONFIG_DIR={config_dir}",
                    "-a", str(bundle)], check=True, timeout=60)
    if not wait_health(port, timeout):
        raise RuntimeError(f"packaged app did not answer on {port} within {timeout}s")

    pid = app_pid()
    if not pid:
        raise RuntimeError("app answered the port but no bundle process is visible")
    got = env_of(pid).get("CANVAS_DL_CONFIG_DIR")
    if got != config_dir:
        raise RuntimeError(
            f"CANVAS_DL_CONFIG_DIR did not take: pid {pid} has {got!r}, "
            f"wanted {config_dir!r} - refusing to audit unisolated state"
        )
    return pid


def wait_health(port: int, timeout: float = 120.0) -> bool:
    """Block until the packaged app's server answers, or give up.

    ``/_stcore/health`` answers as soon as tornado BINDS, which is well before
    the frontend exists - so this only proves the process is alive.  Readiness
    is ``Session.wait_ready``'s job.
    """
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/_stcore/health", timeout=3
            ) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1.0)
    return False


def app_pid() -> int | None:
    """PID of the packaged app, matched on its bundle path.

    Deliberately NOT ``pgrep -f Canvas_Downloader``: that matches the agent's own
    shell command line and manufactures fake orphans - a trap this runbook has
    already paid for twice.
    """
    import subprocess

    needle = "Canvas Downloader.app/Contents/MacOS/Canvas_Downloader"
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,command="],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return None
    for line in out.splitlines():
        line = line.strip()
        if needle in line and " -Ao " not in line:
            try:
                return int(line.split(None, 1)[0])
            except ValueError:
                continue
    return None


__all__ = ["attach", "wait_health", "app_pid", "DownloadFlow", "SyncFlow", "Path"]
