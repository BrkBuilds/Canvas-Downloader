"""Fail the macOS build when the bundle needs a newer macOS than it promises.

WHY THIS EXISTS
---------------
``LSMinimumSystemVersion`` is a *claim*. The real floor is whatever the bundled
native wheels were compiled against, and that is decided by pip at build time
against the CI runner - so it moves on its own. Measured 2026-08-14:

    onnxruntime  arm64 wheels tagged  macosx_14_0  (only)
    av           arm64 wheels tagged  macosx_14_0
    numpy        arm64 wheels tagged  macosx_11_0 AND macosx_14_0

and neither is pinned - both arrive as transitives of ``faster-whisper``. The
workflow runs on ``macos-14``, so pip takes the highest compatible tag. The spec
meanwhile declared 11.0, and the website promised "macOS 11 Big Sur or later,
Monterey / Ventura / Sonoma all work" - a claim nothing in the build could
honour, and which no test could catch because the app was only ever run on
macOS 15 and 26.

The failure mode is the worst kind for a free app: a student on an older Mac
downloads 151 MB, drags it to Applications, and gets a dyld error instead of an
honest "this app requires macOS 14" refusal from the OS.

WHAT IT CHECKS
--------------
Every Mach-O in the .app carries ``LC_BUILD_VERSION`` (or the older
``LC_VERSION_MIN_MACOSX``) recording the minimum OS it was built for. This reads
that out of all of them, takes the maximum, and compares it with the
``LSMinimumSystemVersion`` in the bundle's own Info.plist. If a binary demands
more than the plist promises, the build fails and names the offender.

So the number in the spec stops being a hope and becomes a measured fact. Bump a
dependency that raises the floor and CI tells you at build time, which is the
only moment it is cheap to know.

Usage:
    python scripts/check_macos_floor.py "dist/Canvas Downloader.app"

Exit codes: 0 = floor honoured, 1 = a binary needs more than we promise,
2 = could not inspect (tooling missing / bad path).
"""
from __future__ import annotations

import plistlib
import re
import subprocess
import sys
from pathlib import Path

# Mach-O magic numbers, little- and big-endian, 32- and 64-bit, plus fat.
_MACHO_MAGIC = (
    b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
)


def _is_macho(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) in _MACHO_MAGIC
    except OSError:
        return False


def _version_tuple(text: str) -> tuple:
    """'14.0' -> (14, 0). Tolerates '14', '14.0.1' and stray whitespace."""
    parts = [int(p) for p in re.findall(r"\d+", text)][:3]
    while len(parts) < 2:
        parts.append(0)
    return tuple(parts)


def _minos_of(path: Path) -> str | None:
    """The minimum macOS this binary was built for, or None if not recorded."""
    try:
        out = subprocess.run(
            ["otool", "-l", str(path)],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    # LC_BUILD_VERSION records `minos 14.0`; the older LC_VERSION_MIN_MACOSX
    # records `version 11.0`. A fat binary lists one per slice - take the max,
    # since every slice has to load.
    found = re.findall(r"^\s+(?:minos|version)\s+([0-9][0-9.]*)", out, re.M)
    if not found:
        return None
    return max(found, key=_version_tuple)


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    app = Path(argv[1])
    plist_path = app / "Contents" / "Info.plist"
    if not plist_path.is_file():
        print(f"::error::no Info.plist at {plist_path} - is that a .app bundle?")
        return 2

    with open(plist_path, "rb") as fh:
        declared = plistlib.load(fh).get("LSMinimumSystemVersion")
    if not declared:
        print("::error::the bundle declares no LSMinimumSystemVersion at all")
        return 1

    binaries = [p for p in app.rglob("*") if p.is_file() and _is_macho(p)]
    if not binaries:
        print(f"::error::found no Mach-O binaries inside {app}")
        return 2

    worst, worst_file, unreadable = None, None, 0
    for b in binaries:
        mv = _minos_of(b)
        if mv is None:
            unreadable += 1
            continue
        if worst is None or _version_tuple(mv) > _version_tuple(worst):
            worst, worst_file = mv, b

    print(f"Info.plist LSMinimumSystemVersion : {declared}")
    print(f"binaries inspected                : {len(binaries)}"
          f" ({unreadable} with no recorded minimum)")
    print(f"highest minimum found             : {worst}  ({worst_file})")

    if worst is None:
        print("::warning::no binary recorded a minimum OS - nothing to verify")
        return 0

    if _version_tuple(worst) > _version_tuple(declared):
        print()
        print(f"::error::the bundle promises macOS {declared} but "
              f"{worst_file.name} requires macOS {worst}. Either raise "
              f"LSMinimumSystemVersion in Canvas_Downloader_macOS.spec to "
              f"{worst} (and update the website's stated requirement to match), "
              f"or pin the offending dependency to a wheel built for "
              f"macOS {declared}.")
        # Name the worst few so the offender is obvious without a rebuild.
        ranked = []
        for b in binaries:
            mv = _minos_of(b)
            if mv and _version_tuple(mv) > _version_tuple(declared):
                ranked.append((mv, b.name))
        ranked.sort(key=lambda r: _version_tuple(r[0]), reverse=True)
        print(f"\n{len(ranked)} binaries exceed the declared floor:")
        for mv, name in ranked[:15]:
            print(f"    macOS {mv:6s}  {name}")
        if len(ranked) > 15:
            print(f"    ... and {len(ranked) - 15} more")
        return 1

    print(f"\nOK - every binary runs on macOS {declared} or newer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
