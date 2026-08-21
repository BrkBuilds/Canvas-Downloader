"""Mutation pass for the locale-fragile AppleScript error clauses.

Measured on macOS 26.6.1 (2026-08-20): a missing app really says
``Can’t get application "X". (-1728)`` - typographic apostrophe - and this
machine's macOS says ``Not authorised`` with an S. Three of the four wording
clauses in ``_classify_stderr`` therefore matched nothing. ``permission``
survived on its ``-1743`` companion; ``app_missing`` did not, because there is
no numeric companion for -1728, so an uninstalled Office classified as ``other``
and never aborted the phase.

Every mutant below is a REVERSION to a plausible earlier form, not a strawman:
dropping the normalisation, dropping one spelling, or "simplifying" by adding
-1728 to the numeric list - which looks like the obvious fix and is wrong,
because our own scripts raise -1728 for an absent DOCUMENT.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so a hard checkout could discard
somebody else's uncommitted edit. Before every mutant the target is compared
against its snapshot and the pass ABORTS if it changed underneath - restoring
nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_applescript_locale.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

BRIDGE = "engine/applescript_bridge.py"

TESTS = ["tests/test_office_crash_is_not_missing.py"]
TEST_TARGET = TESTS

_NORM = ("    low = err_msg.lower().replace('\\u2019', \"'\")"
         ".replace('\\u2018', \"'\")\n")

#: (label, file, old, new)
APPLESCRIPT_LOCALE_MUTANTS = [
    ("the apostrophe normalisation is dropped (the original defect)",
     BRIDGE, _NORM, "    low = err_msg.lower()\n"),

    ("only the curly apostrophe is normalised, not the single quote form",
     BRIDGE, _NORM,
     "    low = err_msg.lower().replace('\\u2018', \"'\")\n"),

    ("the British spelling is dropped again",
     BRIDGE,
     "            or 'not authorised to send apple events' in low):\n",
     "            ):\n"),

    ("the American spelling is dropped instead",
     BRIDGE,
     "            or 'not authorized to send apple events' in low\n",
     ""),

    ("-1728 is added to the numeric list - the obvious fix, and wrong",
     BRIDGE,
     "        '-10810' in err_msg or '-10814' in err_msg\n",
     "        '-10810' in err_msg or '-10814' in err_msg or '-1728' in err_msg\n"),

    ("the app_missing wording clause is dropped, leaving only the codes",
     BRIDGE,
     "        or \"can't get application\" in low\n",
     ""),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in APPLESCRIPT_LOCALE_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in APPLESCRIPT_LOCALE_MUTANTS:
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
    for label, rel, old, new in APPLESCRIPT_LOCALE_MUTANTS:
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

    print(f"\n{len(caught)}/{len(APPLESCRIPT_LOCALE_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
