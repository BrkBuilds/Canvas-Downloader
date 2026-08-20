"""Mutation pass for "every caller of transcribe_in_subprocess sweeps .part".

Why this pass matters more than most: the property it protects is currently true
by a COUNT of one. ``transcribe_in_subprocess`` cleans up on its CANCEL branch
and NOT on its crash branch - measured on macOS 26.6.1 (2026-08-20) by sending a
real SIGSEGV to a live worker, which is what an uncatchable native crash looks
like and is the whole reason the subprocess design exists. Containment therefore
comes entirely from the single caller, ``panopto/runner.py:_run_panopto_batch``,
whose phase-level ``finally`` sweeps every task on the way out.

So the interesting mutant is not "break the sweep" - two older tests already
catch that - it is **adding a second caller that does not sweep**. Nothing in the
suite noticed that before ``test_every_caller_of_the_subprocess_runner_sweeps_in_a_finally``,
which is the same shape as ``pdf_looks_real`` landing on two of three delete
sites and surviving eight months.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so a hard checkout could discard
somebody else's uncommitted edit. Before every mutant the target is compared
against its snapshot and the pass ABORTS if it changed underneath - restoring
nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_transcribe_caller_sweep.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

RUNNER = "panopto/runner.py"

TESTS = ["tests/test_transcribe_partial_cleanup.py"]
TEST_TARGET = TESTS

_SWEEP = (
    "            for _t in tx_tasks:\n"
    "                try:\n"
    "                    if _t.tx_source:\n"
    "                        _clean_part_files(str(_t.tx_source), _t.want_txt, _t.want_srt)\n"
    "                except Exception:\n"
    "                    pass\n"
)

#: (label, file, old, new)
TRANSCRIBE_CALLER_SWEEP_MUTANTS = [
    # -- the mutant only the new rule catches --------------------------------
    ("a SECOND caller is added that never sweeps its partials",
     RUNNER,
     "def _noop(*_a, **_k):\n"
     "    pass\n",
     "def _noop(*_a, **_k):\n"
     "    pass\n"
     "\n"
     "\n"
     "def _retranscribe_one(task, model_path, device):\n"
     "    # a plausible helper: retry a single recording outside the phase loop\n"
     "    return transcribe_in_subprocess(task.tx_source, model_path, device=device)\n"),

    # -- the older rules, re-run here so this pass stands alone ---------------
    ("the phase sweep moves out of the finally to after the loop",
     RUNNER,
     "        finally:\n"
     "            # The sweep below MUST stay in a `finally`.\n",
     "        finally:\n"
     "            pass\n"
     "        if True:\n"
     "            # The sweep below MUST stay in a `finally`.\n"),
    ("the phase stops sweeping partials at all",
     RUNNER,
     _SWEEP,
     "            for _t in []:\n"
     "                pass\n"),
    ("the sweep covers only the first task instead of every task",
     RUNNER,
     "            for _t in tx_tasks:\n",
     "            for _t in tx_tasks[:1]:\n"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in TRANSCRIBE_CALLER_SWEEP_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in TRANSCRIBE_CALLER_SWEEP_MUTANTS:
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
    for label, rel, old, new in TRANSCRIBE_CALLER_SWEEP_MUTANTS:
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

    print(f"\n{len(caught)}/{len(TRANSCRIBE_CALLER_SWEEP_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
