"""Mutation pass for the name-keyed `new_files` rebuild (fp:5c1dc682e36c).

Flips one real behaviour at a time and asserts the tests go RED. Every mutant
here is either the code exactly as it shipped, or the plausible near-miss fix.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so (a) HEAD may not be what this pass
started from, and (b) a hard checkout would discard somebody else's uncommitted
edit to a file this pass never mutated. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath -
without restoring anything, because at that point the only thing on disk is
their edit, and writing the snapshot over it is exactly the loss being
prevented.

A timeout counts as CAUGHT - a mutant that hangs the suite is one the suite
noticed.

    python scripts/_mutate_new_files_name_key.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SM = "core/sync_manager.py"

TESTS = [
    "tests/test_new_files_are_not_name_keyed.py",
    "tests/test_sync_manager.py",
]
TEST_TARGET = TESTS
PER_MUTANT_TIMEOUT = 600

#: (label, file, old, new)
NAME_KEY_MUTANTS = [
    ("the offer is rebuilt from the name-keyed map again (the shipped defect)",
     SM,
     "        _unique_new = [nf for nf in regular_new_files\n"
     "                       if id(nf) not in _reupload_consumed]",
     "        _new_seen_ids: set = set()\n"
     "        _unique_new = []\n"
     "        for nf in new_name_map.values():\n"
     "            if id(nf) not in _new_seen_ids:\n"
     "                _new_seen_ids.add(id(nf))\n"
     "                _unique_new.append(nf)"),

    ("a re-uploaded file is offered as new AS WELL as riding the deleted row",
     SM,
     "                _reupload_consumed.add(id(matching_new_cfile))\n",
     "                pass\n"),

    ("the consumed set is keyed by NAME, so a same-named sibling dies with it",
     SM,
     "        _unique_new = [nf for nf in regular_new_files\n"
     "                       if id(nf) not in _reupload_consumed]",
     "        _consumed_names = {_match_key(getattr(nf, 'filename', ''))\n"
     "                           for nf in regular_new_files\n"
     "                           if id(nf) in _reupload_consumed}\n"
     "        _unique_new = [nf for nf in regular_new_files\n"
     "                       if _match_key(getattr(nf, 'filename', ''))\n"
     "                       not in _consumed_names]"),

    ("the map stops registering the raw filename, so a legacy row cannot match",
     SM,
     "            for _nm in (nf.filename, preferred_disk_name(nf)):",
     "            for _nm in (preferred_disk_name(nf),):"),

    ("the map stops registering the display name",
     SM,
     "            for _nm in (nf.filename, preferred_disk_name(nf)):",
     "            for _nm in (nf.filename,):"),

    ("setdefault becomes an overwrite, so the LAST file wins the key",
     SM,
     "                    new_name_map.setdefault(_k, nf)",
     "                    new_name_map[_k] = nf"),

    ("secondary content stops being appended to the offer",
     SM,
     "        result.new_files = _unique_new + secondary_new_files",
     "        result.new_files = _unique_new"),
]

KNOWN_EQUIVALENT = 0


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    with io.open(REPO / rel, "w", encoding="utf-8", newline="") as fh:
        fh.write(body)


def _nl_of(body: str) -> str:
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in NAME_KEY_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, new in NAME_KEY_MUTANTS:
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
    for label, rel, old, new in NAME_KEY_MUTANTS:
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
                                cwd=REPO, capture_output=True,
                                timeout=PER_MUTANT_TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            rc = 1          # a mutant that hangs the suite is one it noticed
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{rel}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(NAME_KEY_MUTANTS)} caught "
          f"(+{KNOWN_EQUIVALENT} documented equivalent, not run)")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
