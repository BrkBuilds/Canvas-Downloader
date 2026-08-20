"""Mutation pass for predicates that match FOREIGN text.

Two live instances in one day, both on macOS 26.6.1: `_classify_stderr` betting
on American spelling and the ASCII apostrophe, and the folder picker matching
"User canceled" while macOS says "User cancelled". In both, a numeric companion
kept the verdict right and the wording clause was simply dead - which reads as
coverage and is not.

The mutants are the ways each lapses: losing a spelling, losing the numeric
companion, and re-splitting the SQLite lock rule into the two spellings it had.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so a hard checkout could discard
somebody else's uncommitted edit. Before every mutant the target is compared
against its snapshot and the pass ABORTS if it changed underneath - restoring
nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_foreign_text.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

H = "shared/helpers.py"
SM = "core/sync_manager.py"

TESTS = ["tests/test_foreign_text_predicates.py"]
TEST_TARGET = TESTS

_CANCEL = ("        if 'user cancelled' in _low or 'user canceled' in _low "
           "or '-128' in err:\n")

#: (label, file, old, new)
FOREIGN_TEXT_MUTANTS = [
    ("the picker drops the BRITISH spelling macOS actually emits",
     H, _CANCEL,
     "        if 'user canceled' in _low or '-128' in err:\n"),

    ("the picker drops the American spelling",
     H, _CANCEL,
     "        if 'user cancelled' in _low or '-128' in err:\n"),

    ("the picker keeps ONLY the error number, so the wording is decoration",
     H, _CANCEL,
     "        if '-128' in err:\n"),

    ("a genuine failure is swallowed as a cancel",
     H, _CANCEL,
     "        if True:\n"),

    ("the lock rule goes back to the NARROW spelling",
     SM,
     "    return 'locked' in str(exc).lower()\n",
     "    return 'database is locked' in str(exc)\n"),

    ("the lock rule stops being case-insensitive",
     SM,
     "    return 'locked' in str(exc).lower()\n",
     "    return 'locked' in str(exc)\n"),

    ("the lock rule retries EVERY sqlite error, corruption included",
     SM,
     "    return 'locked' in str(exc).lower()\n",
     "    return True\n"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in FOREIGN_TEXT_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in FOREIGN_TEXT_MUTANTS:
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
    for label, rel, old, new in FOREIGN_TEXT_MUTANTS:
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

    print(f"\n{len(caught)}/{len(FOREIGN_TEXT_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
