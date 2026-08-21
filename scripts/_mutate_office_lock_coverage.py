"""Mutation pass for Office-automation lock coverage.

Flips one real behaviour at a time and asserts the tests go RED. A test that
survives its own mutant is testing the shape of the code rather than what it
does.

The defect these mutants encode: `_office_app_lock` was added on 2026-08-11 and
landed on ONE of this module's osascript call sites (the conversion), leaving
priming and teardown unlocked. Measured 2026-08-21 on macOS 26.6.1 with five
audit lanes: two lanes that convert NOTHING were both driving
`tell application "Microsoft Excel"` when Excel crashed into Microsoft Error
Reporting.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so (a) HEAD may not be what this pass
started from, and (b) a hard checkout would discard somebody else's uncommitted
edit to a file this pass never mutated. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it has changed underneath -
without restoring anything, because at that point the only thing on disk is
their edit, and writing the snapshot over it is exactly the loss being
prevented.

    python scripts/_mutate_office_lock_coverage.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

BRIDGE = "engine/applescript_bridge.py"

TESTS = [
    "tests/test_office_automation_lock_coverage.py",
]

#: (label, file, old, new)
OFFICE_LOCK_MUTANTS = [
    # -- the teardown paths, which is where the crash was measured ------------
    ("the teardown quit loses the lock",
     BRIDGE,
     "                with _office_app_lock(app):\n                    r = subprocess.run(",
     "                if True:\n                    r = subprocess.run("),
    ("the marker force-close loses the lock",
     BRIDGE,
     "            with _office_app_lock_unless(app, _locked_by_caller):",
     "            if True:"),
    ("the open-document probe loses the lock",
     BRIDGE,
     "        with _office_app_lock(app):\n            r = subprocess.run(['osascript', '-e', script],",
     "        if True:\n            r = subprocess.run(['osascript', '-e', script],"),
    ("the force-terminate quit loses the lock",
     BRIDGE,
     "            with _office_app_lock(app):\n                subprocess.run(\n"
     "                    ['osascript', '-e', f'tell application \"{app}\" to quit saving no'],",
     "            if True:\n                subprocess.run(\n"
     "                    ['osascript', '-e', f'tell application \"{app}\" to quit saving no'],"),

    # -- priming: the LAUNCHER, and the one an audit harness cannot see -------
    ("warmup launches the apps without the lock",
     BRIDGE,
     "        with _office_app_lock(app):\n            try:\n                # Launch hidden",
     "        if True:\n            try:\n                # Launch hidden"),

    # -- the exemption, which must stay narrow and explicit -------------------
    ("the nested sweep stops declaring that it already holds the lock",
     BRIDGE,
     "_force_close_canvas_docs_async(mapping[0], _locked_by_caller=True)",
     "_force_close_canvas_docs_async(mapping[0])"),
    ("the exemption gains a default, so a new caller inherits 'unlocked'",
     BRIDGE,
     "def _office_app_lock_unless(app_name: str, already_held: bool):",
     "def _office_app_lock_unless(app_name: str, already_held: bool = True):"),
    ("the exemption stops being conditional and never locks",
     BRIDGE,
     "    if already_held:\n        yield\n        return\n    with _office_app_lock(app_name):\n        yield",
     "    yield"),

    # -- and the original fix, which widening must not loosen ----------------
    # NOTE the anchor carries the docstring terminator ABOVE the `with`. The
    # bare `with _office_app_lock(app_name):` line appears TWICE in this module
    # - here and inside `_office_app_lock_unless` - and `replace(..., 1)` takes
    # the helper, which is defined first. That made this mutant silently test
    # the helper while its label said conversion, and report SURVIVED for a
    # reason unrelated to conversion. Anchor uniquely.
    ("conversion itself loses the lock",
     BRIDGE,
     '    """\n    with _office_app_lock(app_name):\n'
     "        # Under the lock, so the observation cannot race",
     '    """\n    if True:\n'
     "        # Under the lock, so the observation cannot race"),
]

TEST_TARGET = TESTS


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; these files may be CRLF on a checkout.

    Matching raw bytes is what makes an anchor honest (a universal-newlines read
    would silently rewrite the file's line endings on restore), so the anchor is
    translated to the file's own newline instead. A multi-line anchor written
    with the wrong one reports a live guard as MISSING - the "brittle test
    anchor reads like a missing guard" trap, one level up.
    """
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in OFFICE_LOCK_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, new in OFFICE_LOCK_MUTANTS:
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
    for label, rel, old, new in OFFICE_LOCK_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass "
                  f"(another session?). Nothing restored - the file on disk is "
                  f"THEIR edit, not a mutant.")
            return 3
        nl = _nl_of(current)
        old_nl, new_nl = old.replace("\n", nl), new.replace("\n", nl)
        if old_nl not in current:
            print(f"\nSTALE ANCHOR for {label!r} in {rel} - the pass cannot run it")
            return 4

        _write(rel, current.replace(old_nl, new_nl, 1))
        assert _read(rel) != snapshot[rel], f"{label}: mutation changed nothing"
        try:
            rc = subprocess.run([sys.executable, "-m", "pytest", *TEST_TARGET,
                                 "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True,
                                timeout=600).returncode
        except subprocess.TimeoutExpired:
            rc = 1      # a mutant that hangs the suite is one the suite noticed
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"RESTORE FAILED for {rel}"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(OFFICE_LOCK_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
