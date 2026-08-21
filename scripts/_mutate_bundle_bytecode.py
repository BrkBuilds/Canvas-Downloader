"""Mutation pass for the bundle's ``__pycache__`` exclusion.

Flips one real behaviour at a time and asserts the tests go RED. A test that
survives its own mutant is testing the shape of the code rather than what it
does.

The mutants worth having here are the plausible-refactor ones, not strawmen:
dropping the filter from ONE spec (this repo's documented failure mode), turning
the directory-component match into a substring, forgetting Windows separators,
and letting the filter take the sources with the bytecode.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so (a) HEAD may not be what this pass
started from, and (b) a hard checkout would discard somebody else's uncommitted
edit to a file this pass never mutated. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it has changed underneath -
without restoring anything, because at that point the only thing on disk is
their edit, and writing the snapshot over it is exactly the loss being
prevented.

    python scripts/_mutate_bundle_bytecode.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

EXCL = "scripts/build_excludes.py"
SPEC_WIN = "Canvas_Downloader.spec"
SPEC_MAC = "Canvas_Downloader_macOS.spec"

TESTS = ["tests/test_bundle_bytecode_exclusion.py"]

#: (label, file, old, new)
BUNDLE_BYTECODE_MUTANTS = [
    # -- the call sites: one of two is the whole failure mode -----------------
    ("the WINDOWS spec stops stripping bytecode",
     SPEC_WIN,
     "a.datas = _excl.strip_bytecode_datas(a.datas)",
     "pass  # a.datas = _excl.strip_bytecode_datas(a.datas)"),
    ("the macOS spec stops stripping bytecode",
     SPEC_MAC,
     "a.datas = _excl.strip_bytecode_datas(a.datas)",
     "pass  # a.datas = _excl.strip_bytecode_datas(a.datas)"),
    ("the macOS spec hand-rolls its own filter instead of using the shared one",
     SPEC_MAC,
     "a.datas = _excl.strip_bytecode_datas(a.datas)",
     'a.datas = [d for d in a.datas if "__pycache__" not in d[0]]'),

    # -- the filter itself ----------------------------------------------------
    ("the .pyc suffix test is dropped, so a bare .pyc ships",
     EXCL,
     '        if parts[-1].endswith((".pyc", ".pyo")):\n            continue\n',
     ""),
    ("the __pycache__ component test is dropped",
     EXCL,
     '        if "__pycache__" in parts[:-1]:\n            continue\n',
     ""),
    ("the directory-component match becomes a substring match",
     EXCL,
     '        if "__pycache__" in parts[:-1]:',
     '        if "__pycache__" in dest:'),
    # TWIN ANCHOR, same trap as the one below: this exact line also opens
    # strip_test_datas, which is defined FIRST. The unique prefix is the
    # `kept = []` that precedes it inside THIS function only because the
    # preceding line differs (strip_test_datas declares junk_dirs first).
    ("the Windows separator is no longer normalised, so the filter is a no-op there",
     EXCL,
     '    kept = []\n    for entry in datas:\n'
     '        dest = str(entry[0]).replace("\\\\", "/")\n'
     '        parts = dest.split("/")\n'
     '        if "__pycache__" in parts[:-1]:',
     '    kept = []\n    for entry in datas:\n'
     "        dest = str(entry[0])\n"
     '        parts = dest.split("/")\n'
     '        if "__pycache__" in parts[:-1]:'),
    ("the filter takes the .py sources with the bytecode",
     EXCL,
     '        if parts[-1].endswith((".pyc", ".pyo")):',
     '        if parts[-1].endswith((".pyc", ".pyo", ".py")):'),
    # ANCHORED UNIQUELY, and it has to be. `kept = []\n    for entry in datas:`
    # is BYTE-IDENTICAL in strip_test_datas, which is defined FIRST - so
    # `.replace(..., 1)` mutated that one instead and the pass reported
    # SURVIVED under a label that was a lie. Third instance of this trap in
    # this repo; the fix is always to include a preceding, unique line.
    ("the filter mutates its argument instead of returning a new list",
     EXCL,
     '        if parts[-1].endswith((".pyc", ".pyo")):\n            continue\n'
     "        kept.append(entry)",
     '        if parts[-1].endswith((".pyc", ".pyo")):\n            continue\n'
     "        datas.remove(entry) if entry in datas else None\n"
     "        kept.append(entry)"),
]


#: DOCUMENTED EQUIVALENT MUTANT - deliberately not in the set above.
#:
#: ``parts[:-1]`` -> ``parts`` widens the directory test to include the
#: basename. A PyInstaller TOC destination is always a FILE path, so the two
#: differ only for a file literally named ``__pycache__`` - which cannot occur
#: alongside a directory of that name, and which it would be right to drop
#: anyway. Carrying it in the set would mean a permanent false SURVIVED, and a
#: score with a known-unkillable mutant in it stops meaning anything.


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a file in this repo may be CRLF.

    Matching raw bytes is what makes an anchor honest (a universal-newlines read
    would silently rewrite the file's line endings on restore), so the anchor is
    translated to the file's own newline instead. A multi-line anchor written
    with the wrong one reports a live guard as MISSING - the "brittle test
    anchor reads like a missing guard" trap, one level up.
    """
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in BUNDLE_BYTECODE_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, new in BUNDLE_BYTECODE_MUTANTS:
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
    for label, rel, old, new in BUNDLE_BYTECODE_MUTANTS:
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
            rc = subprocess.run([sys.executable, "-m", "pytest", *TESTS,
                                 "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True, timeout=900).returncode
        except subprocess.TimeoutExpired:
            rc = 1  # a mutant that hangs the suite is one the suite noticed
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{rel}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(BUNDLE_BYTECODE_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
