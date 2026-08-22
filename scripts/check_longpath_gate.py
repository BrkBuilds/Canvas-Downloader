"""Is this machine capable of DETECTING a forgotten make_long_path?

Run this BEFORE believing any audit row that touches a long path. It answers one
question and nothing else: would an unprefixed open at >260 characters actually
fail here?

WHY THIS EXISTS
---------------
Windows only enforces MAX_PATH when `LongPathsEnabled` is 0 *and* the process is
not long-path aware. When it is enforced, a code path that forgot make_long_path
raises and the defect is visible. When it is NOT enforced, that same code path
SUCCEEDS, and a whole audit - download, sync, Office, Panopto, archive - comes
back clean while proving nothing. That is a MASKED PASS, and it is worse than no
audit at all, because it gets written down as evidence.

CLAUDE.md records two long-path defects that survived precisely because a dev box
had the key enabled (`office_safe_path`'s own I/O, and the `panopto/transcribe.py`
`.part` delete, where an over-long path raises FileNotFoundError and the retry
loop reads it as "already gone" - no removal, no retry, no log). Both write-ups
end with "when a path-length fix cannot be reproduced, check that registry key
first". This script is that check, made mechanical.

WHY THE REGISTRY READ IS NOT THE ANSWER
---------------------------------------
It is reported, because it is the thing you fix. It is NOT what the verdict rests
on. Enforcement needs the registry value AND the executable's `longPathAware`
manifest (python.exe ships one), the value is read at process start so a reboot
is required, and a `subst` drive or an unusual mount can behave differently again.
Measured 2026-08-21 on this laptop: the registry said 1, and only an actual
321-character `open()` settled it. So the verdict is empirical and the registry
is context.

THE FIXTURE IS BUILT WITH THE PREFIX, DELIBERATELY
--------------------------------------------------
Every directory is created through make_long_path. If the fixture were built the
same unprefixed way it is probed, then on an enforcing machine the *creation*
would fail, the file would genuinely not exist, and the unprefixed open would
raise for the wrong reason - reporting a working gate on evidence that proves
only that mkdir failed. Building with the prefix removes that confound.

WHAT MAKES THE VERDICT SOUND
----------------------------
Two measurements, and BOTH are load-bearing:

  unprefixed open MUST raise    - this is the gate doing its job
  prefixed open MUST succeed    - this is the CONTROL

Without the control, "unprefixed raised" is equally explained by a fixture that
was never written, a permissions problem, or a full disk. The prefixed open is
what proves the file is really there and really reachable, so the unprefixed
failure can only be about path length.

EXIT CODES
----------
  0  gate is VALID (or not applicable off Windows) - audit results can be trusted
  1  gate is MASKED - long paths are enforced nowhere here; do not trust a clean run
  2  INCONCLUSIVE - the control failed, so nothing was measured

Usage:
    python scripts/check_longpath_gate.py
    python scripts/check_longpath_gate.py --root D:\\        # probe another volume
    python scripts/check_longpath_gate.py --self-test        # prove BOTH verdicts
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.helpers import make_long_path  # noqa: E402

#: Comfortably past MAX_PATH (260) with room for the filename, so a machine that
#: enforces the limit cannot be sitting near a boundary when it answers.
TARGET_PATH_CHARS = 300

VALID, MASKED, INCONCLUSIVE = 0, 1, 2


def read_registry_flag() -> str:
    """Context, never the verdict. See the module docstring."""
    if os.name != "nt":
        return "n/a (not Windows)"
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
        return str(value)
    except FileNotFoundError:
        return "0 (value absent, which means disabled)"
    except OSError as exc:
        return f"unreadable ({exc})"


def build_fixture(root: Path) -> Path:
    """A real file at >260 characters, every level created WITH the prefix."""
    deep = root
    os.makedirs(make_long_path(str(deep)), exist_ok=True)
    segment = "d" * 40
    while len(str(deep)) < TARGET_PATH_CHARS:
        deep = deep / segment
        os.makedirs(make_long_path(str(deep)), exist_ok=True)

    target = deep / "gate_probe.txt"
    with open(make_long_path(str(target)), "wb") as fh:
        fh.write(b"long path gate probe")
    return target


def probe(target: Path) -> dict:
    """Measure both opens. Returns facts; it does not decide anything."""
    result: dict = {"path": str(target), "length": len(str(target))}

    try:
        with open(str(target), "rb") as fh:
            fh.read()
        result["unprefixed_ok"] = True
        result["unprefixed_detail"] = "read successfully"
    except OSError as exc:
        result["unprefixed_ok"] = False
        result["unprefixed_detail"] = (
            f"{type(exc).__name__} errno={exc.errno} "
            f"winerror={getattr(exc, 'winerror', None)}"
        )

    try:
        with open(make_long_path(str(target)), "rb") as fh:
            fh.read()
        result["prefixed_ok"] = True
        result["prefixed_detail"] = "read successfully"
    except OSError as exc:
        result["prefixed_ok"] = False
        result["prefixed_detail"] = f"{type(exc).__name__}: {exc}"

    return result


def verdict(measurements: dict) -> tuple[int, str]:
    """Pure, so it can be driven to BOTH answers without touching a registry.

    Order matters: the control is checked FIRST. If the prefixed open failed we
    measured nothing at all, and reporting either "valid" or "masked" on that
    would be an invention.
    """
    if not measurements["prefixed_ok"]:
        return INCONCLUSIVE, (
            "INCONCLUSIVE - the prefixed open FAILED, so the control did not "
            "hold and nothing was measured. Fix the fixture before reading "
            "anything into the unprefixed result."
        )
    if measurements["unprefixed_ok"]:
        return MASKED, (
            "MASKED - an unprefixed open at "
            f"{measurements['length']} characters SUCCEEDED. Long paths are "
            "enforced nowhere on this machine, so a code path that forgot "
            "make_long_path CANNOT fail here. Any clean audit row that touches "
            "a long path is a masked pass and must not be recorded as evidence."
        )
    return VALID, (
        "VALID - an unprefixed open at "
        f"{measurements['length']} characters failed while the prefixed open "
        "succeeded. This machine enforces MAX_PATH, so a forgotten "
        "make_long_path will show up as a real failure."
    )


def self_test() -> int:
    """Prove the detector can return every verdict.

    A check that can only ever say PASS proves nothing, and this one cannot be
    driven to its MASKED branch by an enforcing machine - a short path reaches
    that branch by the same route (an unprefixed open that succeeds), so the
    decision logic is exercised in both directions without touching the registry.
    """
    cases = [
        ({"length": 300, "unprefixed_ok": False, "prefixed_ok": True}, VALID),
        ({"length": 300, "unprefixed_ok": True, "prefixed_ok": True}, MASKED),
        ({"length": 300, "unprefixed_ok": False, "prefixed_ok": False}, INCONCLUSIVE),
        ({"length": 300, "unprefixed_ok": True, "prefixed_ok": False}, INCONCLUSIVE),
    ]
    ok = True
    for facts, expected in cases:
        got, text = verdict(facts)
        mark = "ok " if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"  [{mark}] unprefixed_ok={facts['unprefixed_ok']!s:<5} "
              f"prefixed_ok={facts['prefixed_ok']!s:<5} -> {text.split(' - ')[0]}")

    # A short path really does let an unprefixed open through, which is the same
    # observation the MASKED branch keys on - so this is a live control on the
    # measurement, not only on the decision.
    with tempfile.TemporaryDirectory() as td:
        short = Path(td) / "short.txt"
        short.write_bytes(b"x")
        m = probe(short)
        print(f"  [{'ok ' if m['unprefixed_ok'] else 'FAIL'}] live control: a SHORT "
              f"path opens unprefixed ({m['length']} chars)")
        ok = ok and m["unprefixed_ok"]

    print("\nself-test:", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """*argv* defaults to ``sys.argv[1:]``; pass a list to call this in-process.

    It has to be a parameter. Without one, ``parse_args()`` reads ``sys.argv``,
    and a test that calls ``main()`` therefore parses PYTEST's arguments and
    dies on ``-q``. That is not hypothetical - it is how this was found.
    """
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="volume or directory to probe (default: temp)")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the detector can return every verdict, then exit")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    print(f"platform                  : {sys.platform}")
    print(f"registry LongPathsEnabled : {read_registry_flag()}")

    if os.name != "nt":
        print()
        print("NOT APPLICABLE - make_long_path is a documented no-op off Windows, "
              "and there is no MAX_PATH to mask. (macOS caps components at 255 "
              "UTF-16 units and the full path at PATH_MAX 1024, with no "
              "escape-hatch prefix, so a long path fails there regardless.)")
        return VALID

    base = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="lpgate_"))
    holder = base if args.root else base
    created_here = args.root is None
    workdir = holder / "lpgate" if args.root else holder

    try:
        target = build_fixture(workdir)
        measurements = probe(target)

        print(f"probe path length         : {measurements['length']} chars")
        print(f"open() WITHOUT the prefix : "
              f"{'SUCCEEDED' if measurements['unprefixed_ok'] else 'FAILED'} "
              f"({measurements['unprefixed_detail']})")
        print(f"open() WITH make_long_path: "
              f"{'SUCCEEDED' if measurements['prefixed_ok'] else 'FAILED'} "
              f"({measurements['prefixed_detail']})")

        code, text = verdict(measurements)
        print()
        print(text)
        return code
    finally:
        # rmtree must go through the prefix too: on the very machine this script
        # is FOR, an unprefixed delete of the fixture cannot reach it.
        try:
            shutil.rmtree(make_long_path(str(workdir)), ignore_errors=True)
            if created_here:
                shutil.rmtree(make_long_path(str(base)), ignore_errors=True)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
