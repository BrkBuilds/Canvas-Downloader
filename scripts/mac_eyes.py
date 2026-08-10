#!/usr/bin/env python3
"""Let the agent SEE the Mac's real screen, over SSH, with no remote desktop.

`screencapture` writes the actual desktop to a PNG from a plain shell - so an
agent on the Mac can look at the window server's output and read it directly.
That is what turns "the user must watch and describe what happened" into
something the agent settles for itself, which was the entire time sink of the
previous macOS audit.

    python3 scripts/mac_eyes.py eyesight             # RUN THIS FIRST - can we see?
    python3 scripts/mac_eyes.py shot                 # whole desktop
    python3 scripts/mac_eyes.py shot --window "Canvas Downloader"
    python3 scripts/mac_eyes.py watch --seconds 20   # a burst, for transients
    python3 scripts/mac_eyes.py dialogs              # what is asking for input
    python3 scripts/mac_eyes.py dock                 # Dock tiles (stale-tile bug)
    python3 scripts/mac_eyes.py windows              # every on-screen window

Shots land in `_audit_runs/_screens/` with a timestamped name and the path is
printed, so an agent can Read it immediately.

**CHECK `eyesight` BEFORE BELIEVING ANY SCREENSHOT.** The premise above holds
only when the framebuffer `screencapture` reads is the one being displayed, and
a remote-desktop display driver can break that: measured on a Scaleway Mac over
NoMachine, the window server listed 12 windows and every capture came back as
the bare desktop, with `screencapture -l <winid>` refusing outright. The user
was looking straight at those windows. A blank capture is then indistinguishable
from a blank app - which is exactly the WKWebView failure phase M3 hunts, so it
manufactures a CRITICAL out of a healthy build. On a BLIND machine, hand every
visual question to the human instead; that is not a failure of the audit, it is
the one honest reading of the evidence.

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


# ─────────────────────────────────────────────────── can we see at all?

def eyesight() -> dict:
    """Does `screencapture` actually render WINDOW CONTENT on this machine?

    THE ASSUMPTION THIS FILE IS BUILT ON CAN BE FALSE, and it fails silently in
    the worst possible direction. Measured on a Scaleway Mac driven over
    NoMachine, 2026-08-10:

        mac_eyes windows          -> 12 windows, incl. `Canvas Downloader` 1920x970
        screencapture -x full     -> 4.4 MB PNG of the bare DESKTOP, no windows
        screencapture -l <winid>  -> "could not create image from window"

    One display, the window server agreeing the windows are on screen, the user
    looking straight at them in their remote viewer - and every capture blank.
    A remote-desktop display driver can intercept window composition, so the
    framebuffer `screencapture` reads holds only the wallpaper and the menu bar.

    Why this is dangerous rather than merely annoying: `MAC_AUDIT_PROMPT.md` and
    `MAC_RUNBOOK.md` both tell the agent it HAS eyes and must not ask the user
    to describe the screen. Following that on such a machine, the packaged app's
    WKWebView check - the highest-value item in phase M3, whose whole failure
    mode is "the UI is blank" - reads as a confirmed CRITICAL when the app is in
    fact rendering perfectly. A blank screenshot is indistinguishable from a
    blank app unless something asks this question first.

    So: ask it explicitly, and treat a blind capture as a reason to ask a human
    rather than as evidence about the product.
    """
    require_darwin()
    ws = [w for w in _windows()
          if w["w"] > 200 and w["h"] > 150 and w["owner"] not in ("Dock", "")]
    if not ws:
        return {"ok": True, "verdict": "no windows to test with",
                "windows": 0, "window_capture": None}
    target = max(ws, key=lambda w: w["w"] * w["h"])
    out = _stamp("eyesight")
    rc, err = sh(["screencapture", "-x", "-o", "-l", str(target["id"]), str(out)])
    got = out.exists() and out.stat().st_size > 10_000
    try:
        out.unlink()
    except OSError:
        pass
    return {"ok": bool(got), "windows": len(ws),
            "target": f"{target['owner']} {target['w']}x{target['h']}",
            "window_capture": "ok" if got else (err[:120] or "empty file"),
            "verdict": ("window content is capturable" if got else
                        "BLIND - the window server reports windows that "
                        "screencapture cannot render (remote-desktop display "
                        "driver). Screenshots show only the desktop; ask the "
                        "user for anything visual.")}


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


# A window macOS keeps alive from login that is registered on-screen and never
# drawn. Measured 2026-08-10: `universalAccessAuthWarn` (pid 812, started at the
# 14:12:39 LOGIN, i.e. before the audit began) held a window at (729,224)
# 461x177 with kCGWindowIsOnscreen True and alpha 1.0, unchanged in every sample
# across 40+ minutes - including while the operator was looking at a completely
# different screen and had already answered every real prompt.
#
# NOTE ON THE EVIDENCE, because the obvious argument is not available here: the
# first version of this comment said "and every screenshot showed an empty
# desktop", which proves nothing on a machine where `eyesight()` reports BLIND -
# no window renders in a capture there, real or phantom. What carries the
# conclusion is the DURATION and the process's login start time: a consent
# prompt is transient and is created when something asks for consent, not at
# login, and no prompt survives 40 minutes of being ignored.
#
# It made `dialogs` claim a human was needed when nothing was, twice - which is
# the one failure this command must not have, because its whole job is deciding
# when to interrupt somebody. Crying wolf here trains the reader to ignore it,
# and then the real TCC prompt goes unanswered.
#
# Scoped as narrowly as the evidence allows: this owner, and only with an EMPTY
# title. A real accessibility prompt carries text, and no other owner in the
# `interesting` list is affected - so this cannot mask a genuine consent prompt.
_PHANTOM_ALERTS = ("universalaccessauthwarn",)


def _is_phantom_alert(w: dict) -> bool:
    return (not (w.get("title") or "").strip()
            and w.get("owner", "").lower() in _PHANTOM_ALERTS)


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
             if any(k.lower() in w["owner"].lower() for k in interesting)
             and not _is_phantom_alert(w)]
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
    sub.add_parser("eyesight", help="can screencapture render window content at all?")
    sub.add_parser("dialogs", help="is anything waiting for a human?")
    sub.add_parser("dock", help="Dock tiles, flagging any whose target is gone")

    a = ap.parse_args()
    if a.cmd == "shot":
        return 0 if shot(a.tag, a.window, a.delay) else 1
    if a.cmd == "watch":
        watch(a.seconds, a.every, a.tag)
    elif a.cmd == "windows":
        windows()
    elif a.cmd == "eyesight":
        r = eyesight()
        for k in ("windows", "target", "window_capture", "verdict"):
            if r.get(k) is not None:
                print(f"  {k:<15} {r[k]}")
        return 0 if r["ok"] else 1
    elif a.cmd == "dialogs":
        dialogs()
    elif a.cmd == "dock":
        dock()
    return 0


if __name__ == "__main__":
    sys.exit(main())
