"""Mutation pass for the iCloud dataless-file contract.

The properties in `tests/test_icloud_dataless.py` currently hold by ACCIDENT of
good design - nothing in the code says "do not hash this folder". That makes the
tests unusually easy to write in a way that cannot fail, so this pass matters
more than most: it breaks each property deliberately and asserts the suite goes
RED.

Each mutant is a plausible refactor, not a strawman. "Just hash it while we're
walking" and "cache the md5 up front" are exactly the changes a reasonable
developer makes for speed on a local disk, without knowing that on an evicted
iCloud folder every hash is a network fetch and a disk refill.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so a hard checkout could discard
somebody else's uncommitted edit. Before every mutant the target is compared
against its snapshot and the pass ABORTS if it changed underneath - restoring
nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_icloud_dataless.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SYNC = "core/sync_manager.py"

TESTS = ["tests/test_icloud_dataless.py"]
TEST_TARGET = TESTS

#: (label, file, old, new)
ICLOUD_DATALESS_MUTANTS = [
    # -- the walks must not touch bytes --------------------------------------
    ("the orphan walk reads each file while it is there",
     SYNC,
     "                try:\n"
     "                    sz = os.stat(make_long_path(filepath)).st_size\n",
     "                try:\n"
     "                    filepath.read_bytes()\n"
     "                    sz = os.stat(make_long_path(filepath)).st_size\n"),
    ("the analysis walk reads each file while it is there",
     SYNC,
     "            try:\n"
     "                size = os.stat(make_long_path(filepath)).st_size\n",
     "            try:\n"
     "                filepath.read_bytes()\n"
     "                size = os.stat(make_long_path(filepath)).st_size\n"),

    # -- candidate md5s must stay LAZY ---------------------------------------
    ("candidate md5s are computed eagerly instead of on demand",
     SYNC,
     "            candidate = {'path': filepath, 'size': size, 'md5': None}",
     "            candidate = {'path': filepath, 'size': size,\n"
     "                         'md5': SyncManager.compute_local_md5(filepath)}"),

    # -- a failed materialisation must never read as CLEAN -------------------
    ("an unreadable file is treated as clean instead of preserved",
     SYNC,
     "        current_md5 = compute_local_md5(local_path)\n"
     "        if not current_md5:\n"
     "            return 'modified'",
     "        current_md5 = compute_local_md5(local_path)\n"
     "        if not current_md5:\n"
     "            return 'clean'"),

    # -- the hash must survive an EIO, not only a PermissionError ------------
    ("compute_local_md5 narrows its handler to PermissionError",
     SYNC,
     "        return h.hexdigest()\n"
     "    except OSError:\n"
     "        return None",
     "        return h.hexdigest()\n"
     "    except PermissionError:\n"
     "        return None"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in ICLOUD_DATALESS_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in ICLOUD_DATALESS_MUTANTS:
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
    for label, rel, old, new in ICLOUD_DATALESS_MUTANTS:
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

    print(f"\n{len(caught)}/{len(ICLOUD_DATALESS_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
