"""Mutation pass for the filename length cap vs the filesystem's UTF-16 limit.

The cap in ``CanvasManager._sanitize_filename`` counts **characters**; every
filesystem this app targets counts **UTF-16 code units** (measured on APFS,
macOS 26.6.1, 2026-08-20 - NTFS is the same). An astral character is a surrogate
pair, so the worst-case ratio is 2:1 and the safe cap is 127, not 255.

That makes this a boundary nobody would notice crossing. "Preserve longer
Canvas filenames" is an ordinary request, and raising ``max_length`` to 200
looks entirely harmless - it breaks only all-astral names, only past 127
characters, and it fails as ENAMETOOLONG at download time, i.e. as a MISSING
FILE rather than a visible error.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so a hard checkout could discard
somebody else's uncommitted edit. Before every mutant the target is compared
against its snapshot and the pass ABORTS if it changed underneath - restoring
nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_filename_utf16_cap.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

LOGIC = "core/canvas_logic.py"

TESTS = ["tests/test_sanitize_filename.py"]
TEST_TARGET = TESTS

_SIG = ("    def _sanitize_filename(self, filename, replace_spaces=False, "
        "max_length=120):\n")

#: (label, file, old, new)
FILENAME_UTF16_CAP_MUTANTS = [
    ("the cap is raised to 200 chars to preserve longer Canvas names",
     LOGIC, _SIG,
     _SIG.replace("max_length=120", "max_length=200")),
    ("the cap is nudged just past the 127-char safe boundary",
     LOGIC, _SIG,
     _SIG.replace("max_length=120", "max_length=128")),
    ("the cap is set to the filesystem number, read as characters",
     LOGIC, _SIG,
     _SIG.replace("max_length=120", "max_length=255")),
    ("truncation stops applying to names with a short extension",
     LOGIC,
     "            else: sanitized = name[:(max_length - len(ext))] + ext",
     "            else: sanitized = name + ext"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in FILENAME_UTF16_CAP_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in FILENAME_UTF16_CAP_MUTANTS:
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
    for label, rel, old, new in FILENAME_UTF16_CAP_MUTANTS:
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

    print(f"\n{len(caught)}/{len(FILENAME_UTF16_CAP_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
