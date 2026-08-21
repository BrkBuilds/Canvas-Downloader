"""Mutation pass for the PDF trailer gate.

`pdf_looks_real` guards the one irreversible step in the pipeline - deleting the
user's only copy of a legacy Office document. Before this fix it asked only
"does it start with %PDF and clear a size floor", and the audit measured a
65,536-byte partial that satisfied both. Each mutant below is a way of
half-doing the trailer check.

A per-mutant TIMEOUT is mandatory (see CLAUDE.md): a mutant that blocks hangs
pytest, the pass is killed from outside, its `finally` never runs, and the
MUTANT IS LEFT ON DISK. A timeout counts as CAUGHT.

Restore is from an in-memory SNAPSHOT, never `git checkout` - this repo is
routinely worked by two sessions at once - and the pass ABORTS, restoring
nothing, if a target changed underneath it.

    python scripts/_mutate_pdf_trailer.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V = "converters/verify.py"
TESTS = ["tests/test_pdf_trailer_gate.py",
         "tests/test_crash_vector_hardening.py",
         "tests/test_office_product_gate.py"]
PER_MUTANT_TIMEOUT = 300.0

PDF_TRAILER_MUTANTS = [
    ("the trailer check is removed - the fix is reverted", V,
     '        if b"%%EOF" not in tail:\n'
     '            return False, ("the PDF written is incomplete - it has no %%EOF "\n'
     '                           "trailer, so the converter stopped part-way")',
     '        if False:\n'
     '            return False, ("the PDF written is incomplete - it has no %%EOF "\n'
     '                           "trailer, so the converter stopped part-way")'),

    ("the window is read from the FRONT, so every large PDF is rejected", V,
     "            fh.seek(max(0, size - _PDF_TRAILER_WINDOW))",
     "            fh.seek(0)"),

    ("the trailer test is inverted", V,
     '        if b"%%EOF" not in tail:',
     '        if b"%%EOF" in tail:'),

    ("a bare EOF substring is accepted, which any content can contain", V,
     '        if b"%%EOF" not in tail:',
     '        if b"EOF" not in tail:'),

    ("the window shrinks below what real producers use", V,
     "_PDF_TRAILER_WINDOW = 4096",
     "_PDF_TRAILER_WINDOW = 4"),

    ("the size floor is dropped, leaving only the trailer", V,
     "        if size < _MIN_PDF_BYTES:",
     "        if False:"),
]

KNOWN_EQUIVALENT = 0


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in PDF_TRAILER_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = [f"{label!r}" for label, rel, old, _n in PDF_TRAILER_MUTANTS
             if old.replace("\n", _nl_of(snapshot[rel])) not in snapshot[rel]]
    if stale:
        print("STALE ANCHORS - unmeasured, not passing:")
        for s in stale:
            print("  " + s)
        return 4

    print(f"baseline: {len(TESTS)} test file(s)")
    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in PDF_TRAILER_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass. Nothing restored.")
            return 3
        nl = _nl_of(current)
        old_nl, new_nl = old.replace("\n", nl), new.replace("\n", nl)
        if old_nl not in current:
            print(f"\nSTALE ANCHOR for {label!r}")
            return 4
        _write(rel, current.replace(old_nl, new_nl, 1))
        assert _read(rel) != snapshot[rel], f"{label}: mutation changed nothing"
        try:
            rc = subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q", "-x",
                                 "--no-header", "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True,
                                timeout=PER_MUTANT_TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            rc = 1
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{rel}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(PDF_TRAILER_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
