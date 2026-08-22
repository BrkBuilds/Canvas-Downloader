"""Mutation pass for the download md5-baseline preservation fix.

``original_md5`` is the whole basis of "never overwrite your edits", and the
bug this guards against was ONE bookkeeping line that rewrote it from whatever
happened to be on disk. Each mutant below is a way of half-doing the fix - the
shapes a later refactor would plausibly land on.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath,
restoring nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_download_baseline.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SYNC = "core/sync_manager.py"

TESTS = [
    "tests/test_download_baseline_preservation.py",
    "tests/test_icloud_dataless.py",
]
TEST_TARGET = TESTS

#: (label, file, old, new)
DOWNLOAD_BASELINE_MUTANTS = [
    ("the fix is reverted - the on-disk bytes always win",
     SYNC,
     "        if not local_md5 and not clear_ignored:\n"
     "            _prev = self.get_manifest_baseline(canvas_file_id)\n"
     "            if _prev and _prev[0]:\n"
     "                local_md5 = _prev[0]\n",
     ""),
    ("the fresh/skip discriminator is dropped, so a re-render keeps a stale baseline",
     SYNC,
     "        if not local_md5 and not clear_ignored:",
     "        if not local_md5:"),
    ("the hashing fallback is removed, so a row with no baseline never gets one",
     SYNC,
     "        if not local_md5:\n"
     "            full_path = self.local_path / local_path\n"
     "            if path_exists(full_path):\n"
     "                local_md5 = SyncManager.compute_local_md5(full_path) or \"\"",
     "        if False:\n"
     "            full_path = self.local_path / local_path\n"
     "            if path_exists(full_path):\n"
     "                local_md5 = SyncManager.compute_local_md5(full_path) or \"\""),
    ("an explicitly supplied md5 is overridden by the stored row",
     SYNC,
     "        if not local_md5 and not clear_ignored:",
     "        if not clear_ignored:"),
]

#: Tried, and EQUIVALENT - kept here so nobody spends the time twice.
#:
#: ("an EMPTY stored baseline is trusted",
#:      "if _prev and _prev[0]:"  ->  "if _prev is not None:")
#:
#: `get_manifest_baseline` returns ``('', path)`` for a row that exists with no
#: md5, so the mutant assigns ``local_md5 = ''`` - and the very next block
#: hashes whenever the md5 is falsy, so the outcome is identical. The
#: ``and _prev[0]`` guard is belt-and-braces rather than load-bearing.
#: `test_a_row_that_EXISTS_with_an_empty_baseline_is_still_hashed` pins the
#: BEHAVIOUR (such a row does acquire a baseline) and passes either way, which
#: is the correct outcome for an equivalent mutant.
KNOWN_EQUIVALENT = 1


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in DOWNLOAD_BASELINE_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in DOWNLOAD_BASELINE_MUTANTS:
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
    for label, rel, old, new in DOWNLOAD_BASELINE_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass (another "
                  f"session?). Nothing restored - the file on disk is THEIR edit.")
            return 3
        nl = _nl_of(current)
        old_nl, new_nl = old.replace("\n", nl), new.replace("\n", nl)
        if old_nl not in current:
            print(f"\nSTALE ANCHOR for {label!r} in {rel}")
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

    print(f"\n{len(caught)}/{len(DOWNLOAD_BASELINE_MUTANTS)} caught "
          f"(+{KNOWN_EQUIVALENT} documented equivalent, not run)")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
