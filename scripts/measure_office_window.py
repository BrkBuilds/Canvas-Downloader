"""Does an Office conversion put a window on screen?

Operator-reported, macOS 26.6, 2026-08-11: after PowerPoint crashed and
"Microsoft Error Reporting" restarted it (its "Recover work and restart" box is
ticked by default), EVERY subsequent .pptx conversion opened a full-screen
PowerPoint window for the rest of the batch.

THE MEASUREMENT THAT ALREADY EXISTS IS NOT ENOUGH, and that is the point of this
script. `engine/applescript_bridge.py` records "with NEITHER -> visible 0/7,
twice, repeatable" and concludes that doing nothing is quietest. That was taken
on a COLD app - its own trace is described as `absent -> false`, i.e. the app was
not running and an Apple event launched it without activating it. The reported
state is the opposite: already running, already visible. A cold-app control
PASSES with this bug fully present.

So this script reproduces the REPORTED state on purpose:

    python scripts/measure_office_window.py --app PowerPoint --file X.pptx --state visible
    python scripts/measure_office_window.py --app PowerPoint --file X.pptx --state hidden
    python scripts/measure_office_window.py --app PowerPoint --file X.pptx --state absent

`visible` is the one that matters; `hidden` mimics `prime_office_automation`'s
`open -g -j`; `absent` is the original cold control, kept so a regression there
is visible too.

It samples the app's own `visible of window` through its scripting dictionary -
NOT System Events, which would need Accessibility and is the thing this codebase
deliberately removed - and independently checks whether the app ever became
`frontmost`, because a window that steals focus is the actual complaint.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

BUNDLE = {"PowerPoint": "Microsoft PowerPoint",
          "Word": "Microsoft Word",
          "Excel": "Microsoft Excel"}
SAMPLE_S = 0.2


def _osa(script: str, timeout: float = 20) -> str:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=timeout)
    return (r.stdout or r.stderr or "").strip()


def _running(app: str) -> bool:
    out = _osa(f'tell application "System Events" to return '
               f'(exists application process "{BUNDLE[app]}")')
    return out.lower().startswith("true")


def _quit(app: str) -> None:
    if _running(app):
        _osa(f'tell application "{BUNDLE[app]}" to quit saving no', timeout=30)
    for _ in range(20):
        if not _running(app):
            return
        time.sleep(0.5)
    subprocess.run(["pkill", "-f", f"/{BUNDLE[app]}.app/"], capture_output=True)
    time.sleep(2)


def _put_in_state(app: str, state: str) -> None:
    """absent | hidden (open -g -j, what prime_office_automation does) | visible."""
    _quit(app)
    if state == "absent":
        return
    path = f"/Applications/{BUNDLE[app]}.app"
    if state == "hidden":
        subprocess.run(["open", "-g", "-j", "-a", path], capture_output=True)
    else:                                    # the post-crash state
        subprocess.run(["open", "-a", path], capture_output=True)
    for _ in range(40):
        if _running(app):
            break
        time.sleep(0.5)
    time.sleep(3)                            # let it settle / show its start screen


def _sampler(app: str, stop: threading.Event, out: list) -> None:
    """Sample WINDOW visibility through the app's own dictionary.

    Deliberately not System Events: that needs Accessibility, which this
    codebase removed on purpose (see applescript_bridge.py). `frontmost` is
    read from System Events only as a secondary signal and is allowed to fail.
    """
    while not stop.is_set():
        vis = _osa(f'''tell application "{BUNDLE[app]}"
                         try
                           return (count of (windows whose visible is true))
                         on error
                           return -1
                         end try
                       end tell''', timeout=8)
        front = _osa('tell application "System Events" to return '
                     '(name of first process whose frontmost is true)', timeout=8)
        out.append({"t": round(time.time(), 3), "visible_windows": vis,
                    "frontmost": front})
        stop.wait(SAMPLE_S)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", choices=sorted(BUNDLE), default="PowerPoint")
    ap.add_argument("--file", required=True, help="a real document to convert")
    ap.add_argument("--state", choices=("absent", "hidden", "visible"),
                    default="visible")
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    src = Path(a.file).resolve()
    if not src.exists():
        print(f"no such file: {src}", file=sys.stderr)
        return 2

    print(f"putting {a.app} into state: {a.state}")
    _put_in_state(a.app, a.state)
    base = {"absent": 0, "hidden": 0, "visible": 0}
    base_vis = _osa(f'tell application "{BUNDLE[a.app]}"\n try\n return '
                    f'(count of (windows whose visible is true))\n on error\n '
                    f'return -1\n end try\nend tell') if a.state != "absent" else "0"
    print(f"  baseline visible windows: {base_vis}")

    stop = threading.Event()
    samples: list = []
    t = threading.Thread(target=_sampler, args=(a.app, stop, samples), daemon=True)
    t.start()

    # THE REAL CONVERTER, not a hand-written script - the whole lesson of
    # `office_safe_path` is that driving AppleScript directly takes a different
    # code path (no container staging) and measures something else.
    from converters.pdf import PowerPointToPDF, WordToPDF, ExcelToPDF
    conv = {"PowerPoint": PowerPointToPDF, "Word": WordToPDF,
            "Excel": ExcelToPDF}[a.app]()
    t0 = time.time()
    try:
        out = conv.convert(str(src))
        ok = bool(out) and Path(out).exists()
    except Exception as e:
        out, ok = f"EXCEPTION {e}", False
    dur = time.time() - t0
    stop.set()
    t.join(timeout=10)

    def _n(v):
        try:
            return int(v)
        except Exception:
            return -1

    vis = [_n(s["visible_windows"]) for s in samples]
    shown = [v for v in vis if v > _n(base_vis)]
    stole = [s for s in samples if a.app.lower() in (s["frontmost"] or "").lower()]
    result = {
        "app": a.app, "state": a.state, "converted": ok, "seconds": round(dur, 1),
        "samples": len(samples),
        "baseline_visible_windows": _n(base_vis),
        "max_visible_windows": max(vis) if vis else None,
        "samples_with_EXTRA_window": len(shown),
        "samples_where_app_was_FRONTMOST": len(stole),
        "verdict": ("A WINDOW APPEARED" if shown else "no window appeared"),
        "output": str(out),
    }
    print(json.dumps(result, indent=1))
    if a.label:
        p = REPO / "_audit_runs" / "_screens" / f"office_window_{a.label}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"result": result, "samples": samples}, indent=1),
                     encoding="utf-8")
        print("saved", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
