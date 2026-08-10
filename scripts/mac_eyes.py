#!/usr/bin/env python3
"""Let the agent SEE the Mac's real screen, over SSH, with no remote desktop.

`screencapture` writes the actual desktop to a PNG from a plain shell - so an
agent on the Mac can look at the window server's output and read it directly.
That is what turns "the user must watch and describe what happened" into
something the agent settles for itself, which was the entire time sink of the
previous macOS audit.

    python3 scripts/mac_eyes.py shot                 # whole desktop
    python3 scripts/mac_eyes.py shot --window "Canvas Downloader"
    python3 scripts/mac_eyes.py watch --seconds 20   # a burst, for transients
    python3 scripts/mac_eyes.py dialogs              # what is asking for input
    python3 scripts/mac_eyes.py dock                 # Dock tiles (stale-tile bug)
    python3 scripts/mac_eyes.py windows              # every on-screen window

Shots land in `_audit_runs/_screens/` with a timestamped name and the path is
printed, so an agent can Read it immediately.

WHAT IT CANNOT DO, and why that is not a gap you can engineer away: macOS
refuses synthetic clicks on TCC consent prompts by design (that is the whole
point of them). So the agent can SEE an Automation prompt and tell you exactly
which button to press, but a human has to press it. Everything else - reading
the UI, confirming a banner appeared, checking a Dock tile, comparing a
WKWebView render against Chrome - it can do alone.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHOTS = REPO / "_audit_runs" / "_screens"


def sh(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as e:                                    # noqa: BLE001
        return 127, f"{type(e).__name__}: {e}"


def _stamp(tag: str) -> Path:
    SHOTS.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)[:48]
    return SHOTS / f"{datetime.now():%H%M%S}_{safe}.png"


def require_darwin():
    if sys.platform != "darwin":
        print("mac_eyes.py only works on macOS.", file=sys.stderr)
        raise SystemExit(2)


# ───────────────────────────────────────────────────────────── capture

def shot(tag="desktop", window=None, delay=0.0):
    """Capture the desktop, or one window by title.

    -x suppresses the shutter sound; without it an unattended run clicks its
    way through a long audit audibly and, worse, the sound is a UI event on a
    machine we are also measuring.
    """
    require_darwin()
    if delay:
        time.sleep(delay)
    out = _stamp(tag)
    if window:
        wid = _window_id(window)
        if wid is None:
            print(f"no on-screen window matching {window!r}", file=sys.stderr)
            return None
        rc, err = sh(["screencapture", "-x", "-o", "-l", str(wid), str(out)])
    else:
        rc, err = sh(["screencapture", "-x", str(out)])
    if rc != 0 or not out.exists():
        print(f"capture failed: {err}", file=sys.stderr)
        return None
    print(out)
    return out


def _window_id(title_substr: str):
    """CGWindowID of the first on-screen window whose title/owner matches."""
    for w in _windows():
        hay = f"{w['owner']} {w['title']}".lower()
        if title_substr.lower() in hay:
            return w["id"]
    return None


def _windows() -> list[dict]:
    """Every on-screen window, via Quartz - no Accessibility grant needed."""
    require_darwin()
    try:
        from Quartz import (CGWindowListCopyWindowInfo, kCGNullWindowID,
                            kCGWindowListOptionOnScreenOnly)
    except ImportError:
        return []
    out = []
    for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly,
                                        kCGNullWindowID) or []:
        b = w.get("kCGWindowBounds") or {}
        out.append({"id": w.get("kCGWindowNumber"),
                    "owner": w.get("kCGWindowOwnerName") or "",
                    "title": w.get("kCGWindowName") or "",
                    "w": int(b.get("Width", 0)), "h": int(b.get("Height", 0))})
    return out


def windows():
    ws = [w for w in _windows() if w["w"] > 80 and w["h"] > 60]
    if not ws:
        print("no windows (or pyobjc-framework-Quartz missing)")
        return
    for w in ws:
        print(f"  {w['w']:>5}x{w['h']:<5}  {w['owner']:<28} {w['title'][:60]}")


def dialogs():
    """What, if anything, is waiting for a human.

    A TCC prompt is owned by a system process and cannot be clicked
    programmatically - but knowing it is there, and what it says, is what lets
    an agent stop and ask for one specific button instead of hanging.
    """
    require_darwin()
    interesting = ("UserNotificationCenter", "SecurityAgent", "coreautha",
                   "universalaccessAuthWarn", "tccd", "loginwindow")
    found = [w for w in _windows()
             if any(k.lower() in w["owner"].lower() for k in interesting)]
    if found:
        print("SOMETHING IS WAITING FOR A HUMAN:")
        for w in found:
            print(f"  {w['owner']}: {w['title']}")
        p = shot("dialog")
        print(f"\n  screenshot: {p}\n"
              f"  macOS refuses synthetic clicks on consent prompts by design -\n"
              f"  a person has to press the button. Say which one.")
    else:
        print("no consent/auth dialog on screen")


def watch(seconds=20, every=2.0, tag="watch"):
    """A burst of shots - for anything transient (a banner, a splash, a flash)."""
    require_darwin()
    made = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        p = shot(f"{tag}_{len(made):02d}")
        if p:
            made.append(p)
        time.sleep(every)
    print(f"\n{len(made)} shot(s) in {SHOTS}")


def dock():
    """The Dock's persistent + recent tiles.

    `purge_stale_self_dock_tiles` exists because a conversion left a Dock tile
    pointing at a file the app had already deleted. This reads the same plist
    the Dock does, so it needs no screenshot to answer.
    """
    require_darwin()
    import plistlib
    p = Path.home() / "Library/Preferences/com.apple.dock.plist"
    rc, out = sh(["defaults", "export", "com.apple.dock", "-"], timeout=60)
    try:
        data = plistlib.loads(out.encode()) if rc == 0 else plistlib.loads(p.read_bytes())
    except Exception as e:                                     # noqa: BLE001
        print(f"could not read the Dock: {e}")
        return
    for key in ("persistent-apps", "recent-apps", "persistent-others"):
        items = data.get(key) or []
        if not items:
            continue
        print(f"\n{key} ({len(items)}):")
        for it in items:
            tile = (it.get("tile-data") or {})
            label = tile.get("file-label") or tile.get("label") or "?"
            url = ((tile.get("file-data") or {}).get("_CFURLString") or "")
            missing = ""
            if url.startswith("file://"):
                from urllib.parse import unquote
                path = unquote(url[7:])
                missing = "" if Path(path).exists() else "   <-- TARGET MISSING"
            print(f"   {label:<38}{missing}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shot", help="capture the desktop or one window")
    s.add_argument("--tag", default="desktop")
    s.add_argument("--window", default=None, help="match on window title or app name")
    s.add_argument("--delay", type=float, default=0.0)

    w = sub.add_parser("watch", help="a burst of shots, for transients")
    w.add_argument("--seconds", type=int, default=20)
    w.add_argument("--every", type=float, default=2.0)
    w.add_argument("--tag", default="watch")

    sub.add_parser("windows", help="list on-screen windows")
    sub.add_parser("dialogs", help="is anything waiting for a human?")
    sub.add_parser("dock", help="Dock tiles, flagging any whose target is gone")

    a = ap.parse_args()
    if a.cmd == "shot":
        return 0 if shot(a.tag, a.window, a.delay) else 1
    if a.cmd == "watch":
        watch(a.seconds, a.every, a.tag)
    elif a.cmd == "windows":
        windows()
    elif a.cmd == "dialogs":
        dialogs()
    elif a.cmd == "dock":
        dock()
    return 0


if __name__ == "__main__":
    sys.exit(main())
