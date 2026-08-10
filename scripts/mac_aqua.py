#!/usr/bin/env python3
"""Run a command inside the Mac's **Aqua** (graphical login) session.

WHY THIS EXISTS, measured on a Scaleway Apple-silicon Mac 2026-08-10.

`scripts/mac_audit_doctor.py` deliberately tests window-server *capability*
rather than the launchd domain, and its docstring says `managername` "says
nothing about what the process can reach". That is correct **for the window
server** and wrong for the **Keychain**, which is the one macOS service that is
scoped to the security session rather than to the framebuffer. Measured, in one
session, from the same shell:

    screencapture                     -> a real 4.4 MB PNG
    osascript / System Events         -> answers
    keyring.set_password(new item)    -> errSecInteractionNotAllowed (-25308)

So a tmux server started over SSH gives you a `Background` session in which the
audit can drive the whole GUI and still cannot save or read a single Keychain
item. The app under test is a child of that shell, so **every** Keychain
observation in the audit is then false: token save "fails", auto-login "does not
restore", and the 90 s watchdog looks like it is being hit. None of that is the
product.

The root fix is to start tmux from a Terminal inside the graphical session, and
the doctor now BLOCKs when the Keychain is unusable so nobody spends an hour on
it again. This module is the fallback for when you are already mid-session and
do not want to lose it: it hands one command to **Terminal.app**, which Launch
Services starts inside Aqua, and every child of that command inherits the Aqua
session - including a long-lived Streamlit process.

    python3 scripts/mac_aqua.py check
    python3 scripts/mac_aqua.py run "python -m tests.audit app start"
    python3 scripts/mac_aqua.py run "pyinstaller ..." --detach --timeout 0

`run` is synchronous by default: it returns the command's real exit status and
its combined output, so it is a drop-in for a Bash call. `--detach` returns
immediately and prints the log path, for anything long enough to want watching.

TWO THINGS THAT ARE NOT NEGOTIABLE, both learned by breaking them:

* **The command goes to a FILE, never into the AppleScript.** An AppleScript
  string literal cannot span lines and cannot hold a bare quote, and the
  commands worth running here are full of both. Only a fixed, safe temp path is
  interpolated, so there is nothing to escape - the same reasoning as
  `engine.applescript_bridge.applescript_string`, applied by avoiding the
  problem instead of solving it.
* **Completion is a SENTINEL, not a timer.** `do script` returns as soon as
  Terminal accepts the text, so polling for output would race a command that
  has not started. The wrapper writes the exit status and then `__AQUA_DONE__`,
  and nothing is believed until that line exists.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path("/tmp/canvas_dl_aqua")
DONE = "__AQUA_DONE__"


def _osascript(script: str, timeout: int = 30) -> tuple[int, str]:
    p = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def session_name() -> str:
    """This process's own launchd domain - 'Aqua' or 'Background'."""
    try:
        p = subprocess.run(["launchctl", "managername"],
                           capture_output=True, text=True, timeout=10)
        return p.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def keychain_usable() -> tuple[bool, str]:
    """Round-trip the audit's OWN probe item: create, read, delete.

    A brand-new item of our own making needs no ACL authorisation and no
    password, so a failure here is the SESSION and nothing else. That is what
    makes this a capability probe rather than a proxy - the same standard the
    doctor already holds its window-server checks to.
    """
    service, account = "CanvasDownloaderAuditProbe", "session-capability"
    try:
        import keyring
    except Exception as e:                                  # pragma: no cover
        return False, f"keyring import failed: {type(e).__name__}: {e}"
    try:
        keyring.set_password(service, account, "probe")
        got = keyring.get_password(service, account)
        keyring.delete_password(service, account)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    if got != "probe":
        return False, "round trip returned a different value"
    return True, "set/get/delete round trip ok"


def run(command: str, cwd: str | None = None, timeout: float = 900.0,
        detach: bool = False, keep_window: bool = False) -> dict:
    """Run ``command`` in the Aqua session. Returns rc, output and paths."""
    WORK.mkdir(parents=True, exist_ok=True)
    tag = f"{time.strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}"
    script = WORK / f"aqua_{tag}.command"
    log = WORK / f"aqua_{tag}.log"
    rcf = WORK / f"aqua_{tag}.rc"

    # `exec > log` on the wrapper, not on the command, so anything the command
    # spawns in the background is captured too.
    script.write_text(
        "#!/bin/bash\n"
        f"exec > {log} 2>&1\n"
        f"cd {cwd or REPO}\n"
        "[ -f .venv/bin/activate ] && source .venv/bin/activate\n"
        f"{command}\n"
        "__rc=$?\n"
        f"echo $__rc > {rcf}\n"
        f'echo "{DONE} rc=$__rc"\n',
        encoding="utf-8")
    script.chmod(0o755)

    # Only this fixed, quote-free path reaches the AppleScript literal.
    #
    # Return the WINDOW ID, not the tab. `do script` answers a tab reference, and
    # the first version tried to find its window with
    # `close (every window whose id is (id of window 1 whose selected tab is <tab>))`
    # - which never matched, so EVERY bridge call leaked a Terminal window. After
    # ~40 calls the desktop held ~20 of them (measured, and pointed out by the
    # operator). Harmless here; on Windows a per-call console would be a real
    # memory cost, and either way a tool that litters is a tool people stop
    # using. A window id is a plain integer we can close directly.
    rc, out = _osascript(
        'tell application "Terminal"\n'
        f'  do script "{script}"\n'
        '  return id of front window as text\n'
        'end tell')
    if rc != 0:
        return {"ok": False, "error": f"could not reach Terminal.app: {out}",
                "log": str(log)}
    tab = out.strip()

    if detach:
        return {"ok": True, "detached": True, "log": str(log),
                "script": str(script), "tab": tab}

    deadline = time.time() + timeout
    while time.time() < deadline:
        if log.exists() and DONE in log.read_text(encoding="utf-8", errors="replace"):
            break
        time.sleep(0.4)
    else:
        return {"ok": False, "error": f"timed out after {timeout:.0f}s",
                "log": str(log), "timed_out": True,
                "output": log.read_text(encoding="utf-8", errors="replace")
                          if log.exists() else ""}

    body = log.read_text(encoding="utf-8", errors="replace")
    try:
        code = int(rcf.read_text().strip())
    except Exception:
        code = -1
    if not keep_window and tab.isdigit():
        # Close only OUR window, by id, and `saving no` so a window whose shell
        # is still settling cannot raise a "close anyway?" sheet and leave the
        # window behind - which is the state that accumulated before.
        _osascript(f'tell application "Terminal" to close '
                   f'(every window whose id is {tab}) saving no')
    return {"ok": code == 0, "rc": code, "log": str(log),
            "output": body.replace(f"{DONE} rc={code}", "").rstrip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="report this session and whether the Keychain works")
    c.add_argument("--json", action="store_true")

    r = sub.add_parser("run", help="run a command in the Aqua session")
    r.add_argument("command")
    r.add_argument("--cwd")
    r.add_argument("--timeout", type=float, default=900.0)
    r.add_argument("--detach", action="store_true")
    r.add_argument("--keep-window", action="store_true")

    a = ap.parse_args()

    if a.cmd == "check":
        here = session_name()
        ok, note = keychain_usable()
        if a.json:
            import json
            print(json.dumps({"session": here, "keychain_ok": ok, "note": note}))
        else:
            print(f"this session   : {here}")
            print(f"keychain usable: {ok}  ({note})")
            if not ok:
                print("\nThe Keychain is scoped to the security session, unlike the window")
                print("server. Start tmux from a Terminal inside the graphical session, or")
                print("route the app through:  python3 scripts/mac_aqua.py run '<cmd>'")
        return 0 if ok else 1

    res = run(a.command, cwd=a.cwd, timeout=(a.timeout or 1e9),
              detach=a.detach, keep_window=a.keep_window)
    if res.get("output"):
        print(res["output"])
    if not res.get("ok"):
        print(f"[mac_aqua] {res.get('error', 'command failed')} (log: {res.get('log')})",
              file=sys.stderr)
    return 0 if res.get("ok") else (res.get("rc") or 1)


if __name__ == "__main__":
    sys.exit(main())
