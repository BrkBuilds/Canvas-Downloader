"""Mutation pass for "a denied powerbox is not a slow document".

Measured in the PACKAGED app on macOS 26.6.1 by clicking Don't Allow on
"Canvas Downloader would like to access data from other apps": one `.doc` cost
~4 minutes and reported only `AppleEvent timed out (-1712)` twice, then
"Conversion failed twice". Word was confirmed holding the ORIGINAL path, not a
staged one, so the container fallback had been taken.

The mutants are the ways this lapses in BOTH directions - losing the
attribution, and over-claiming it onto ordinary timeouts, which would abort a
phase and tell the user to change a setting that is fine.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so a hard checkout could discard
somebody else's uncommitted edit. Before every mutant the target is compared
against its snapshot and the pass ABORTS if it changed underneath - restoring
nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_container_denied.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

AB = "engine/applescript_bridge.py"

TESTS = ["tests/test_container_denied_attribution.py"]
TEST_TARGET = TESTS

#: (label, file, old, new)
CONTAINER_DENIED_MUTANTS = [
    ("the fallback stops recording itself (back to a bare -1712)",
     AB,
     "            _office_unstaged.add(app_name)\n",
     "            pass\n"),

    ("the category stops being fatal - back to ~4 minutes PER FILE",
     AB,
     "FATAL_CATEGORIES = ('permission', 'app_missing', 'container_denied')\n",
     "FATAL_CATEGORIES = ('permission', 'app_missing')\n"),

    ("the record survives the run, so a later staged run misreports a timeout",
     AB,
     "    _office_unstaged.clear()\n",
     "    pass\n"),

    ("EVERY timeout is blamed on permissions, staged or not",
     AB,
     "    if (category == 'other' and app_name in _office_unstaged\n",
     "    if (category == 'other'\n"),

    ("the app scoping is dropped - Word losing staging speaks for Excel",
     AB,
     "    if (category == 'other' and app_name in _office_unstaged\n",
     "    if (category == 'other' and _office_unstaged\n"),

    ("any failure while unstaged is called a permission problem",
     AB,
     "            and ('-1712' in err_msg or 'timed out' in err_msg.lower())):\n",
     "            ):\n"),

    ("run_applescript stops consulting the run state at all",
     AB,
     "            category = attribute_office_failure(category, app_name, err_msg)\n",
     "            pass\n"),

    ("the remedy names the pane that has no toggle",
     AB,
     "                    f\"Turn on Canvas Downloader under System Settings → Privacy & \"\n"
     "                    f\"Security → Full Disk Access (or in the app's Settings → macOS \"\n",
     "                    f\"Turn on Canvas Downloader under System Settings → Privacy & \"\n"
     "                    f\"Security → Files and Folders (or in the app's Settings → macOS \"\n"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in CONTAINER_DENIED_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in CONTAINER_DENIED_MUTANTS:
        nl = _nl_of(snapshot[rel])
        if old.replace("\n", nl) not in snapshot[rel]:
            stale.append(f"{label!r} in {rel}")
    if stale:
        print("STALE ANCHORS - these mutants could not run at all, so any score "
              "recorded for them is UNMEASURED, not passing:")
        for s in stale:
            print("  " + s)
        return 4

    print(f"baseline: running {len(TESTS)} test file(s)")
    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in CONTAINER_DENIED_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass (another "
                  f"session?). Nothing restored - the file on disk is THEIR "
                  f"edit, not a mutant.")
            return 3
        nl = _nl_of(current)
        old_nl, new_nl = old.replace("\n", nl), new.replace("\n", nl)
        if old_nl not in current:
            print(f"\nSTALE ANCHOR for {label!r} in {rel} - cannot run it")
            return 4

        _write(rel, current.replace(old_nl, new_nl, 1))
        assert _read(rel) != snapshot[rel], f"{label}: mutation changed nothing"
        try:
            rc = subprocess.run([sys.executable, "-m", "pytest", *TEST_TARGET,
                                 "-q", "-x", "--no-header",
                                 "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True).returncode
        finally:
            _write(rel, snapshot[rel])
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(CONTAINER_DENIED_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
