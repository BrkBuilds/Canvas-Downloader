"""Mutation pass for "a phase that ABORTED on a fatal condition is not retried".

Measured in the PACKAGED app on macOS 26.6.1 with Automation for Microsoft Word
genuinely DENIED: one `.doc` produced 3 per-file errors and **2 aborts**, ending
in "Conversion failed twice" - which blames the document for a machine-wide
permission state. Corroborated from a second oracle by the health record's
`failures={'osascript_permission': 2}`.

The mutants are the plausible ways this lapses, not strawmen: dropping the
record, dropping the skip, making the skip GLOBAL (which would stop retrying
unrelated converters - the failure in the other direction), and renaming a
runner out from under the map, which is silent because the map keys on
``__name__``.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so a hard checkout could discard
somebody else's uncommitted edit. Before every mutant the target is compared
against its snapshot and the pass ABORTS if it changed underneath - restoring
nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_retry_fatal_skip.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PP = "converters/post_processing.py"

TESTS = ["tests/test_conversion_retry.py"]
TEST_TARGET = TESTS

#: (label, file, old, new)
RETRY_FATAL_SKIP_MUTANTS = [
    ("the abort stops recording which phase died",
     PP,
     "        ui.aborted_phases.add(phase_label)\n",
     "        pass\n"),

    ("the retry stops skipping the aborted phase (the original defect)",
     PP,
     "    attempts = [(r, items) for r, items in attempts if not _phase_aborted(r)]\n",
     "    attempts = list(attempts)\n"),

    ("the skip goes GLOBAL - unrelated converters stop being retried",
     PP,
     "        return _RUNNER_PHASE.get(getattr(runner, \"__name__\", \"\")) in _aborted\n",
     "        return bool(_aborted)\n"),

    ("a Word denial is taken as evidence about Excel too",
     PP,
     '    "run_excel_conversion": "Excel",\n',
     '    "run_excel_conversion": "Word",\n'),

    ("the phase map loses an entry, so that phase is retried after aborting",
     PP,
     '    "run_word_conversion": "Word",\n',
     ""),

    ("the map keys on a runner that no longer exists",
     PP,
     '    "run_pptx_conversion": "PowerPoint",\n',
     '    "run_powerpoint_conversion": "PowerPoint",\n'),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in RETRY_FATAL_SKIP_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in RETRY_FATAL_SKIP_MUTANTS:
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
    for label, rel, old, new in RETRY_FATAL_SKIP_MUTANTS:
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

    print(f"\n{len(caught)}/{len(RETRY_FATAL_SKIP_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
