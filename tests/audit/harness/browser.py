"""A browser that outlives the CLI call, driven by key rather than by guesswork.

Why a detached Chrome plus CDP instead of Playwright's normal launch: the audit
is a sequence of many short CLI invocations, and a Playwright-launched browser
dies with the Python process that launched it. Losing the browser between steps
would lose the Streamlit SESSION - and session state is most of what this app
is. So Chrome is started once, detached, with a remote-debugging port, and each
CLI call attaches to it, acts, and detaches.

Everything is addressed by the widget ``key`` the app already assigns, never by
text or position. Text is translated, positions move, and an accessibility
snapshot of a 200-row review screen is enormous; ``st-key-<key>`` is stable,
unique and cheap. Streamlit lowercases keys when generating the class, so every
lookup lowercases too - this is a documented trap in the project's own notes.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import probe
from .paths import RunPaths

CDP_PORT_BASE = 9333


class BrowserError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------

def _cdp_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def open_browser(rp: RunPaths, headed: bool = True, width: int = 1600,
                 height: int = 1200, port: int | None = None) -> dict:
    """Start (or reuse) the detached Chrome for this run.

    Headed by default and deliberately: the app is a desktop product rendered in
    a webview, several of its behaviours are layout- and paint-dependent, and a
    headless run cannot produce the screenshots the agent needs to judge a
    screen. Headless remains available for unattended regression runs.

    *port* pins the CDP port instead of scanning for a free one. Parallel lanes
    MUST pass it: the scan below tests liveness and then binds a moment later,
    so two workers starting together both see 9333 as free, both claim it, and
    one of them dies with a CDP timeout that reads like a Chrome problem.
    Disjoint bands make the race structurally impossible rather than unlikely.
    """
    meta = rp.load_meta().get("browser", {})
    if meta.get("cdp_port") and _cdp_alive(meta["cdp_port"]):
        return {"status": "already-running", **meta}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        exe = p.chromium.executable_path

    if port is None:
        # Skip ports other runs have claimed as well as ports currently serving:
        # a run whose Chrome died still owns the tabs a user may reopen, and
        # attaching to a FOREIGN browser is the failure mode that had one run's
        # Chrome quietly driving another run's app.
        taken = _cdp_ports_of_other_runs(rp)
        port = CDP_PORT_BASE
        while (port in taken or _cdp_alive(port)) and port < CDP_PORT_BASE + 60:
            port += 1

    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={rp.browser_profile}",
        f"--window-size={width},{height}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter,OptimizationHints",
        "--disable-backgrounding-occluded-windows",
        # The run dashboard repaints ~2.5x/second for minutes. Chrome throttles
        # timers and rAF in a background window, which would make every timing
        # observation in the audit a measurement of Chrome's throttling instead
        # of the app's behaviour.
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "about:blank",
    ]
    if not headed:
        args.insert(1, "--headless=new")

    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    proc = subprocess.Popen(args, creationflags=flags,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL,
                            start_new_session=(os.name != "nt"))

    deadline = time.time() + 30
    while time.time() < deadline:
        if _cdp_alive(port):
            info = {"cdp_port": port, "pid": proc.pid, "headed": headed}
            rp.update_meta(browser=info)
            return {"status": "started", **info}
        time.sleep(0.3)
    raise BrowserError(f"Chrome did not expose CDP on {port} within 30s")


def _cdp_ports_of_other_runs(rp: RunPaths) -> set[int]:
    from .paths import RUNS_ROOT
    out: set[int] = set()
    if not RUNS_ROOT.is_dir():
        return out
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
        p = (data.get("browser") or {}).get("cdp_port")
        if isinstance(p, int):
            out.add(p)
    return out


def close_browser(rp: RunPaths) -> dict:
    meta = rp.load_meta().get("browser", {})
    pid = meta.get("pid")
    if not pid:
        return {"status": "not-started"}
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=20)
        else:
            os.kill(pid, 15)
    except Exception:
        pass
    rp.update_meta(browser={})
    return {"status": "closed", "pid": pid}


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------

@contextlib.contextmanager
def session(rp: RunPaths):
    """Attach to the run's browser and yield a :class:`Session`."""
    meta = rp.load_meta().get("browser", {})
    port = meta.get("cdp_port")
    if not port or not _cdp_alive(port):
        raise BrowserError("Browser is not open. Run: python -m tests.audit browser open")

    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        yield Session(rp, page)
    finally:
        with contextlib.suppress(Exception):
            pw.stop()


class Session:
    """Actions and extractions against the live app page."""

    # A Streamlit rerun after a click is usually sub-second, but a click that
    # kicks off analysis holds the script thread. Callers that expect that pass
    # their own timeout; this is only the "ordinary interaction" budget.
    SETTLE_QUIET_MS = 450
    SETTLE_TIMEOUT = 90.0

    def __init__(self, rp: RunPaths, page):
        self.rp = rp
        self.page = page

    # -- navigation ----------------------------------------------------

    def goto(self, url: str, ready: bool = True) -> dict:
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.install_collector()
        return self.wait_ready() if ready else {"ready": None}

    def app_url(self, mode: str = "", step: str = "", quick: bool = False) -> str:
        port = self.rp.load_meta().get("app", {}).get("port")
        if not port:
            raise BrowserError("App is not started for this run.")
        base = f"http://127.0.0.1:{port}"
        if not mode:
            return base
        q = f"?mode={mode}&step={step or 1}" + ("&quick=1" if quick else "")
        return base + q

    def install_collector(self) -> dict:
        return self.page.evaluate(probe.INSTALL_COLLECTOR)

    def drain_console(self) -> dict:
        try:
            return self.page.evaluate(probe.DRAIN_COLLECTOR)
        except Exception as e:
            return {"console": [], "errors": [], "missing": True, "note": str(e)}

    # -- waiting -------------------------------------------------------

    def wait_ready(self, timeout: float = 120.0) -> dict:
        """Wait for the app to have painted real content, not just stylesheets."""
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            try:
                last = self.page.evaluate(probe.IS_READY)
            except Exception:
                last = {"ready": False, "why": "evaluate failed (navigating?)"}
            if last.get("ready"):
                self.install_collector()
                return last
            time.sleep(0.35)
        raise BrowserError(f"App not ready within {timeout}s: {last}")

    def settle(self, quiet_ms: int | None = None, timeout: float | None = None) -> dict:
        """Block until the DOM stops changing and no script run is in flight."""
        quiet_ms = self.SETTLE_QUIET_MS if quiet_ms is None else quiet_ms
        timeout = self.SETTLE_TIMEOUT if timeout is None else timeout
        self.page.set_default_timeout(max(timeout, 5.0) * 1000)
        try:
            return self.page.evaluate(probe.SETTLE, quiet_ms)
        except Exception as e:
            return {"settled": False, "why": f"{type(e).__name__}: {e}"}

    def wait_for(self, js_predicate: str, timeout: float = 3600.0,
                 poll: float = 2.0, label: str = "") -> dict:
        """Poll a JS predicate. Used for long phases (download, sync, transcribe).

        Returns the last evaluation rather than raising on timeout, because a
        phase that never finishes IS the finding - the caller records it with
        context instead of the harness dying and losing the run.
        """
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                last = self.page.evaluate(js_predicate)
            except Exception as e:
                last = {"error": f"{type(e).__name__}: {e}"}
            if isinstance(last, dict) and last.get("done"):
                last["waited_s"] = round(timeout - (deadline - time.time()), 1)
                return last
            if last is True:
                return {"done": True}
            time.sleep(poll)
        return {"done": False, "timeout": True, "label": label, "last": last,
                "waited_s": timeout}

    # -- actions -------------------------------------------------------

    def _host(self, key: str):
        return self.page.locator(f'[class*="st-key-{key.lower()}"]').first

    def probe_key(self, key: str, role: str = "button") -> dict:
        return self.page.evaluate(probe.FIND_BY_KEY, {"key": key, "role": role})

    def click(self, key: str, settle: bool = True, timeout: float = 20.0,
              force_gated: bool = False) -> dict:
        """Click the control carrying ``st-key-<key>``.

        ``force_gated`` exists for the two JS gates in this app that leave a
        button genuinely enabled and merely paint it unavailable
        (``pointer-events: none``). Clicking one anyway is how the audit proves
        the server-side guard behind it actually holds - a gate that is only
        cosmetic would let the action through.
        """
        info = self.probe_key(key, "button")
        if not info.get("found"):
            return {"clicked": False, "key": key, **info}
        if info.get("gated") and not force_gated:
            return {"clicked": False, "key": key, "reason": "gated", **info}
        loc = self._host(key).locator("button").first
        if loc.count() == 0:
            loc = self._host(key)
        try:
            loc.click(timeout=timeout * 1000, force=force_gated)
        except Exception as e:
            return {"clicked": False, "key": key, "error": f"{type(e).__name__}: {e}"}
        out = {"clicked": True, "key": key, "was": info}
        if settle:
            out["settle"] = self.settle()
        return out

    def set_checkbox(self, key: str, value: bool, settle: bool = True) -> dict:
        """Idempotent checkbox/toggle set - clicks only when the state differs.

        Idempotence matters more than it looks: several of this app's on_click
        handlers mutate arrays, and a double click that toggles twice can leave
        a list in a state no user could reach.
        """
        info = self.probe_key(key, "checkbox")
        if not info.get("found"):
            return {"set": False, "key": key, **info}
        if bool(info.get("checked")) == bool(value):
            return {"set": True, "key": key, "changed": False, "checked": value}
        # Click the label, not the input: Streamlit's real checkbox is hidden at
        # 0x0 / opacity 0, so Playwright refuses to click it as not visible. The
        # DIRECT-child form avoids the second label a help= tooltip nests inside
        # stWidgetLabel.
        host = self._host(key)
        loc = host.locator('[data-testid="stCheckbox"] > label').first
        if loc.count() == 0:
            loc = host.locator("label").first
        try:
            loc.click(timeout=20000)
        except Exception:
            host.locator('[data-testid="stCheckbox"]').first.click(timeout=20000)
        out = {"set": True, "key": key, "changed": True, "checked": value}
        if settle:
            out["settle"] = self.settle()
        after = self.probe_key(key, "checkbox")
        out["verified"] = bool(after.get("checked")) == bool(value)
        return out

    def fill(self, key: str, text: str, commit: bool = True, settle: bool = True) -> dict:
        """Type into a text input and commit it.

        Streamlit only sends a text input's value to Python on blur or Enter, and
        a synthetic key event is ignored because React only trusts real ones -
        so the commit is a real Enter press followed by a real blur.
        """
        loc = self._host(key).locator("input, textarea").first
        try:
            loc.click(timeout=15000)
            loc.fill("")
            loc.type(text, delay=12)
            if commit:
                loc.press("Enter")
                self.page.locator('[data-testid="stMain"]').first.click(
                    position={"x": 3, "y": 3}, timeout=5000)
        except Exception as e:
            return {"filled": False, "key": key, "error": f"{type(e).__name__}: {e}"}
        out = {"filled": True, "key": key, "value": text}
        if settle:
            out["settle"] = self.settle()
        return out

    def expand(self, key: str, open_: bool = True, settle: bool = True) -> dict:
        """Open/close an ``st.expander`` addressed by its container key."""
        det = self._host(key).locator("details").first
        try:
            is_open = det.evaluate("d => d.hasAttribute('open')")
        except Exception as e:
            return {"expanded": False, "key": key, "error": str(e)}
        if bool(is_open) == bool(open_):
            return {"expanded": True, "key": key, "changed": False}
        det.locator("summary").first.click(timeout=15000)
        out = {"expanded": True, "key": key, "changed": True}
        if settle:
            out["settle"] = self.settle(quiet_ms=250, timeout=30)
        return out

    def scroll_main(self, to: str = "bottom") -> None:
        self.page.evaluate(
            """(to) => { const m = document.querySelector('[data-testid="stMain"]');
                 if (m) m.scrollTop = to === 'top' ? 0 : m.scrollHeight; }""", to)

    def press(self, key: str) -> dict:
        """Send one key to the page, then settle.

        Exists for Escape: a Streamlit dialog hides its native close button by
        CSS, and while one is open its scrim intercepts every click - so a
        forgotten dialog makes the NEXT `ui click` fail with a pointer-events
        timeout naming an unrelated element (measured: the Settings dialog's
        `st-key-stg_card_path` swallowing a click meant for a course checkbox).
        """
        self.page.keyboard.press(key)
        return {"pressed": key, "settle": self.settle()}

    # -- extraction ----------------------------------------------------

    def extract(self, which: str = "screen") -> dict:
        js = {"screen": probe.SCREEN, "wizard": probe.WIZARD,
              "dashboard": probe.DASHBOARD, "review": probe.SYNC_REVIEW,
              "completion": probe.COMPLETION, "today": probe.TODAY}.get(which)
        if js is None:
            raise BrowserError(f"Unknown extraction '{which}'")
        return self.page.evaluate(js)

    def capture(self, name: str, which: tuple[str, ...] = ("screen",),
                full_page: bool = True) -> dict:
        """One screenshot + the named extractions, written to the run's evidence.

        Always paired: a screenshot with no structured extract cannot be
        asserted on, and an extract with no screenshot cannot be judged.
        """
        shot = self.rp.screenshots / f"{name}.png"
        try:
            self.page.screenshot(path=str(shot), full_page=full_page)
        except Exception:
            self.page.screenshot(path=str(shot), full_page=False)
        data = {"name": name, "screenshot": str(shot),
                "captured": time.strftime("%Y-%m-%d %H:%M:%S")}
        for w in which:
            data[w] = self.extract(w)
        data["console"] = self.drain_console()
        out = self.rp.ui / f"{name}.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"name": name, "screenshot": str(shot), "extract": str(out),
                "textLen": data.get("screen", {}).get("textLen"),
                "consoleErrors": len(data["console"].get("errors", [])),
                "exceptions": len(data.get("screen", {}).get("exceptions", []))}
