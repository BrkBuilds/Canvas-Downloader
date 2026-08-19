"""Downscale and optimise README screenshots in place.

Screenshots are checked into the repository, so every clone pays for them
forever. A raw 1920x1080 PNG off a Windows capture runs 400 KB to 1.5 MB; the
README renders them at 820px at most, so the extra pixels are pure weight.

    python scripts/optimize_screenshots.py            # dry run, reports what it would do
    python scripts/optimize_screenshots.py --apply    # rewrite the files

Downscales anything wider than MAX_WIDTH with Lanczos resampling, drops metadata,
and re-encodes with PNG optimisation. Anything already small enough is left
alone rather than re-encoded, because a needless re-encode is a diff with no
benefit.

MAX_WIDTH is 1600, not 820. The README displays at 820 CSS pixels, and a 2x
source is what keeps it sharp on the high-DPI screens most people read GitHub
on. Going below that looks soft exactly where the detail matters, which in these
shots is small UI text.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow is required:  pip install Pillow")
    sys.exit(1)

MAX_WIDTH = 1600
SOFT_BUDGET_KB = 500          # per file, warn above this
SHOTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "assets" / "screenshots"

# The filenames the README's screenshot block expects.
EXPECTED = [
    "course-selection.png",
    "quick-download.png",
    "sync-review.png",
    "progress.png",
    "panopto-card.png",
    "institution-picker.png",
]


def human(n: int) -> str:
    return f"{n/1024:.0f} KB" if n < 1024 * 1024 else f"{n/1024/1024:.2f} MB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="rewrite the files (default is a dry run)")
    ap.add_argument("--max-width", type=int, default=MAX_WIDTH)
    args = ap.parse_args()

    if not SHOTS_DIR.is_dir():
        print(f"No screenshots directory at {SHOTS_DIR}")
        return 1

    shots = sorted(p for p in SHOTS_DIR.glob("*.png") if p.name.lower() != "readme.md")
    if not shots:
        print(f"No .png files in {SHOTS_DIR} yet.")
        print("Expected: " + ", ".join(EXPECTED))
        return 0

    total_before = total_after = 0

    for p in shots:
        before = p.stat().st_size
        total_before += before
        try:
            with Image.open(p) as im:
                im = im.convert("RGB") if im.mode not in ("RGB", "RGBA") else im.copy()
                w, h = im.size
                if w > args.max_width:
                    nh = round(h * args.max_width / w)
                    im = im.resize((args.max_width, nh), Image.LANCZOS)
                    action = f"{w}x{h} -> {args.max_width}x{nh}"
                else:
                    action = f"{w}x{h} (kept)"

                if args.apply:
                    im.save(p, "PNG", optimize=True)
        except Exception as e:
            print(f"  SKIP {p.name}: {type(e).__name__}: {e}")
            continue

        after = p.stat().st_size if args.apply else before
        total_after += after
        flag = "  <-- over budget" if after > SOFT_BUDGET_KB * 1024 else ""
        delta = f"{human(before)} -> {human(after)}" if args.apply else human(before)
        print(f"  {p.name:26} {action:22} {delta}{flag}")

    print()
    if args.apply:
        saved = total_before - total_after
        pct = (saved / total_before * 100) if total_before else 0
        print(f"Total {human(total_before)} -> {human(total_after)}  (saved {human(saved)}, {pct:.0f}%)")
    else:
        print(f"Total now: {human(total_before)}. Dry run - re-run with --apply to rewrite.")

    missing = [n for n in EXPECTED if not (SHOTS_DIR / n).exists()]
    if missing:
        print()
        print("Still missing: " + ", ".join(missing))

    return 0


if __name__ == "__main__":
    sys.exit(main())
