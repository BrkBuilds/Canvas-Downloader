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


# A macOS version is one or two digits today (26 at the time of writing). A
# parsed "floor" in the hundreds or thousands is not a newer macOS - it is a
# PARSE FAILURE, and the whole point of this guard is that it must not fail
# confidently. Anything above this is reported as a broken parse naming the
# line, rather than silently blocking a release. See parse_minos.
_PLAUSIBLE_MAX_MAJOR = 99


def parse_minos(otool_output: str) -> str | None:
    """The minimum macOS recorded by ``otool -l`` output, or None if absent.

    Kept separate from the subprocess call so it can be tested without a Mach-O
    binary or an ``otool`` - which is the only reason this ever gets exercised
    off macOS, and this parser has already shipped one release-blocking bug
    because nothing ran it anywhere.

    THE TRAP THIS EXISTS TO AVOID. Only two load commands record a minimum OS:

        LC_BUILD_VERSION        ->  minos 11.0
        LC_VERSION_MIN_MACOSX   ->  version 10.9

    but the token ``version`` appears in several OTHER places in the same
    output, and one of them is *inside LC_BUILD_VERSION itself*::

            cmd LC_BUILD_VERSION
        platform 1
           minos 11.0            <- the floor
             sdk 26.5
          ntools 1
            tool 3               <- TOOL_LD
         version 1267.0          <- the LINKER's version, not an OS

    A line-wise regex for ``minos|version`` therefore reads ld64's version as a
    macOS floor. Measured 2026-08-22: every modern binary carries one, so the
    check failed on 214 of 215 binaries and reported "requires macOS 1267.0".
    LC_SOURCE_VERSION and LC_LOAD_DYLIB's ``current version`` are the same
    hazard in milder form.

    So this tracks which load command it is inside and reads ``minos`` ONLY
    under LC_BUILD_VERSION and ``version`` ONLY under LC_VERSION_MIN_MACOSX.
    A fat binary lists one command per slice - the max wins, since every slice
    has to load.
    """
    best = None
    cmd = None
    platform_is_macos = True  # absent platform line -> assume macOS (see below)

    for raw in otool_output.splitlines():
        line = raw.strip()
        # 'cmdsize 16' does not match: its fifth character is 's', not a space.
        if line.startswith("cmd "):
            cmd = line[4:].strip()
            platform_is_macos = True
            continue
        if cmd == "LC_BUILD_VERSION":
            if line.startswith("platform "):
                tok = line.split()[1]
                # PLATFORM_MACOS is 1; newer otool may spell it out. Anything
                # else (MACCATALYST, iOS, a simulator) is a different OS's
                # numbering and must never be read as a macOS floor.
                platform_is_macos = tok in ("1", "MACOS", "macos")
                continue
            # Every other field of this command - sdk, ntools, tool, and the
            # linker's own `version` - is not a floor. `continue` here rather
            # than falling through, or the platform line above reaches the
            # `cand` check with nothing bound (an UnboundLocalError this repo
            # has been bitten by before, and which the tests caught here).
            if not (line.startswith("minos ") and platform_is_macos):
                continue
            cand = line.split()[1]
        elif cmd == "LC_VERSION_MIN_MACOSX" and line.startswith("version "):
            cand = line.split()[1]
        else:
            continue

        if not re.fullmatch(r"[0-9][0-9.]*", cand):
            continue
        if best is None or _version_tuple(cand) > _version_tuple(best):
            best = cand

    return best


def _minos_of(path: Path) -> str | None:
    """The minimum macOS this binary was built for, or None if not recorded."""
    try:
        out = subprocess.run(
            ["otool", "-l", str(path)],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_minos(out)


def main(argv: list, minos_reader=_minos_of) -> int:
    """``minos_reader`` is injectable so the pass/fail decision itself can be
    tested without a Mach-O bundle or an ``otool``. The reason that matters:
    this script's own regression was a parse bug, and a test that only covers
    the parser would not have caught a comparison that never fires."""
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

    # One read per binary. The previous version called otool a second time to
    # rank the offenders, i.e. twice per binary on a 215-binary bundle.
    found = []           # [(minos, path)]
    unreadable = 0
    for b in binaries:
        mv = minos_reader(b)
        if mv is None:
            unreadable += 1
            continue
        if _version_tuple(mv)[0] > _PLAUSIBLE_MAX_MAJOR:
            print(f"::error::parsed a minimum of {mv!r} for {b.name}, which is "
                  f"not a macOS version. That is a bug in this checker's "
                  f"parsing, not a real floor - see parse_minos. Refusing to "
                  f"pass or fail the build on a number this script does not "
                  f"understand.")
            return 2
        found.append((mv, b))

    worst, worst_file = max(found, key=lambda r: _version_tuple(r[0]), default=(None, None))

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
        ranked = sorted(
            ((mv, b.name) for mv, b in found
             if _version_tuple(mv) > _version_tuple(declared)),
            key=lambda r: _version_tuple(r[0]), reverse=True,
        )
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
