"""Measure the packaged app's FIRST SECONDS on screen, frame by frame.

The reported defect (`fp:66b3e213c23d`): a cold launch shows a full-screen WHITE
frame before the dark splash. `start.py` already passes
``background_color='#0d1117'`` and pywebview applies it - but to the **NSWindow**
(`cocoa.py: self.window.setBackgroundColor_(...)`), while the WKWebView draws its
own opaque white until its first document paints. So the window colour is never
what you see.

WHY A SCRIPT AND NOT AN EYEBALL: the flash is ONE frame of a launch. "Did it look
better?" cannot answer whether a compositing change fixed it or merely moved it,
and this change touches how every screen composites. A luminance trace can, and
it is the same instrument `scripts/measure_nav.py` uses for the navigation
overlay - a peak above the settled value IS the flash.

    python scripts/measure_launch_flash.py --label before
    python scripts/measure_launch_flash.py --label after --compare before

Frames land in ``_audit_runs/_screens/flash_<label>/`` and the trace in
``flash_<label>.json`` beside them, so a run can be re-read without re-launching.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "dist" / "Canvas Downloader.app"
OUT_ROOT = REPO / "_audit_runs" / "_screens"

#: RECORD, DO NOT SAMPLE. A one-frame flash cannot be caught by
#: `screencapture` polling: a full-screen PNG takes 100-200 ms to write, so the
#: effective rate is ~5-8 fps and the event is ~16-30 ms. The first version of
#: this script sampled at 0.12 s and "found" a peak at 0.52 s that was simply
#: the DESKTOP before the window appeared - measuring the wallpaper, not the app.
#: `screencapture -v` records at the display's real rate instead.
RECORD_S = 10
#: Analysis crops to the window INTERIOR so the desktop, menu bar and Dock
#: cannot be mistaken for the app. Fractions of the screen, inset generously.
CROP = (0.18, 0.22, 0.82, 0.80)   # l, t, r, b


def _luminance(img) -> float:
    """Rec.709 luma of the WINDOW INTERIOR, 0-255."""
    w, h = img.size
    img = img.crop((int(w * CROP[0]), int(h * CROP[1]),
                    int(w * CROP[2]), int(h * CROP[3])))
    px = img.convert("RGB").resize((160, 100))
    r, g, b = 0.0, 0.0, 0.0
    data = list(px.getdata())
    n = len(data)
    for pr, pg, pb in data:
        r += pr
        g += pg
        b += pb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / n


def _kill_app() -> None:
    for pat in ("MacOS/Canvas_Downloader", "start.py"):
        subprocess.run(["pkill", "-f", pat], capture_output=True, timeout=30)
    time.sleep(2)


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def capture(label: str, from_source: bool = False) -> dict:
    """Re-sign, launch, RECORD, then decode to frames.

    Re-signing is what makes the launch COLD - a fresh code signature forces
    macOS to re-validate instead of serving a cached decision, and the runbook
    records that as the condition the flash needs.
    """
    from PIL import Image

    out = OUT_ROOT / f"flash_{label}"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    mov = out / "screen.mov"
    if mov.exists():
        mov.unlink()

    _kill_app()
    if not from_source:
        subprocess.run(["codesign", "--force", "--deep", "-s", "-",
                        "--entitlements", str(REPO / "entitlements.mac.plist"),
                        str(APP)], capture_output=True, timeout=300)

    rec = subprocess.Popen(["screencapture", "-v", f"-V{RECORD_S}", "-x", str(mov)])
    time.sleep(1.2)                      # let the recorder actually start
    t_launch = time.time()
    if from_source:
        # ITERATE FROM SOURCE. `python start.py` builds the same pywebview
        # window with the same splash, so the flash reproduces identically -
        # and a rebuild+resign costs ~10 minutes per attempt, which is the
        # difference between measuring three candidate fixes and measuring one.
        # The winner is still confirmed against the packaged bundle.
        subprocess.Popen([sys.executable, str(REPO / "start.py")],
                         cwd=str(REPO),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["open", "-a", str(APP)])
    rec.wait(timeout=RECORD_S + 60)

    # Decode every frame. `-vsync 0` keeps the source timing rather than
    # resampling, so a frame index really is a frame.
    subprocess.run([_ffmpeg(), "-y", "-i", str(mov), "-vsync", "0",
                    str(out / "f%04d.png")], capture_output=True, timeout=600)

    pngs = sorted(out.glob("f*.png"))
    frames = []
    for i, png in enumerate(pngs):
        try:
            frames.append({"i": i, "t": round(i / 60.0, 3),
                           "png": str(png), "lum": round(_luminance(Image.open(png)), 2)})
        except Exception as e:
            frames.append({"i": i, "t": round(i / 60.0, 3), "png": str(png),
                           "lum": None, "error": str(e)})

    trace = {"label": label, "record_s": RECORD_S, "crop": CROP,
             "launch_offset_s": round(t_launch, 3), "frames": frames}
    (OUT_ROOT / f"flash_{label}.json").write_text(
        json.dumps(trace, indent=1), encoding="utf-8")
    return trace


def summarise(trace: dict) -> dict:
    """The three numbers that decide it.

    `settled` is the median of the LAST third - by then the app is showing real
    content. `peak` is the brightest frame before that. A flash is `peak` far
    above `settled`; the navigation-overlay work used the same ratio.
    """
    lums = [(f["t"], f["lum"]) for f in trace["frames"] if f.get("lum") is not None]
    if not lums:
        return {"error": "no frames"}

    # POSITIVE CONTROL, and it is not optional. A recording where the app never
    # appeared has NO flash either, so "peak_over_settled: 1.0" reads exactly
    # like a fix. That happened: an `after` run scored a perfect 1.00 because a
    # broken edit had made the launcher unreachable and the app exited 0 in
    # silence - the trace was 10 seconds of desktop wallpaper. A launch moves
    # the screen a lot; if it did not move, nothing was measured.
    span = max(l for _, l in lums) - min(l for _, l in lums)
    if span < 5.0:
        return {"error": "THE APP NEVER APPEARED - the screen never changed "
                         f"(luminance span {span:.2f} over {len(lums)} frames). "
                         "This trace measures the desktop, not the app.",
                "frames": len(lums), "span": round(span, 2)}
    tail = sorted(l for _, l in lums[len(lums) * 2 // 3:])
    settled = tail[len(tail) // 2]
    head = [(t, l) for t, l in lums if t < lums[-1][0] * 2 / 3]
    peak_t, peak = max(head, key=lambda x: x[1]) if head else (0, settled)
    return {
        "frames": len(lums),
        "settled": round(settled, 2),
        "peak": round(peak, 2),
        "peak_at_s": peak_t,
        "peak_over_settled": round(peak / settled, 2) if settled else None,
        "max_lum": round(max(l for _, l in lums), 2),
        "first_8_lums": [l for _, l in lums[:8]],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--compare", help="another label to diff against")
    ap.add_argument("--reread", action="store_true",
                    help="summarise a saved trace without relaunching")
    ap.add_argument("--source", action="store_true",
                    help="launch `python start.py` instead of the bundle - same "
                         "window and splash, no 10-minute rebuild per attempt")
    a = ap.parse_args()

    if a.reread:
        trace = json.loads((OUT_ROOT / f"flash_{a.label}.json").read_text(encoding="utf-8"))
    else:
        if not a.source and not APP.exists():
            print(f"no bundle at {APP}", file=sys.stderr)
            return 2
        trace = capture(a.label, from_source=a.source)

    s = summarise(trace)
    print(json.dumps({a.label: s}, indent=1))

    if a.compare:
        prev = json.loads(
            (OUT_ROOT / f"flash_{a.compare}.json").read_text(encoding="utf-8"))
        ps = summarise(prev)
        print(json.dumps({a.compare: ps}, indent=1))
        print(json.dumps({
            "peak_over_settled": {a.compare: ps["peak_over_settled"],
                                  a.label: s["peak_over_settled"]},
            "max_lum": {a.compare: ps["max_lum"], a.label: s["max_lum"]},
            "settled_delta": round(s["settled"] - ps["settled"], 2),
        }, indent=1))
    _kill_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
