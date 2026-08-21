"""Mutation pass for the conversion manifest-repoint spelling fix.

The defect this guards against was invisible from every direction at once: the
conversion succeeded, the PDF was correct, the source was correctly deleted, and
the ONLY symptom was a manifest row still naming the deleted source - with not a
single line logged. It shipped because ``Path.relative_to`` is a string
operation and two of the three Office converters ``resolve()`` the path they
return. Each mutant below is a way of half-doing the fix.

A per-mutant TIMEOUT is mandatory here, per ``CLAUDE.md``: a mutant that makes
the code block hangs pytest, the pass is killed from outside, its ``finally``
never runs, and the MUTANT IS LEFT ON DISK indistinguishable from real code.
A timeout counts as CAUGHT - a mutant that hangs the suite is one the suite
noticed.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath,
restoring nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_conversion_repoint.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PP = "converters/post_processing.py"

TESTS = ["tests/test_conversion_repoint_spelling.py"]
TEST_TARGET = TESTS

PER_MUTANT_TIMEOUT = 300.0

#: (label, file, old, new)
CONVERSION_REPOINT_MUTANTS = [
    ("the fix is reverted - naive relative_to, silent on mismatch",
     PP,
     "    original_rel = _course_relative(sm, original_file)\n"
     "    new_rel = _course_relative(sm, converted_path)\n",
     "    try:\n"
     "        original_rel = str(original_file.relative_to(sm.local_path)).replace('\\\\', '/')\n"
     "        new_rel = str(converted_path.relative_to(sm.local_path)).replace('\\\\', '/')\n"
     "    except ValueError:\n"
     "        return\n"),

    ("the realpath fallback is dropped, so only the exact spelling matches",
     PP,
     "    candidates = ((p, Path(root)),\n"
     "                  (Path(os.path.realpath(p)), Path(os.path.realpath(root))))",
     "    candidates = ((p, Path(root)),)"),

    ("only ONE side is realpath'd, which is the same mismatch in mirror image",
     PP,
     "                  (Path(os.path.realpath(p)), Path(os.path.realpath(root))))",
     "                  (Path(os.path.realpath(p)), Path(root)))"),

    ("robustness becomes 'relativise anything' - a path outside the course is accepted",
     PP,
     "        except (ValueError, AttributeError, OSError):\n"
     "            continue\n"
     "    return None",
     "        except (ValueError, AttributeError, OSError):\n"
     "            continue\n"
     "    return str(p.name)"),

    ("the outside-the-course case goes silent again, which is how it shipped",
     PP,
     "        logger.warning(\n"
     "            \"Could not place %s / %s inside the course folder %s, so the \"",
     "        logger.debug(\n"
     "            \"Could not place %s / %s inside the course folder %s, so the \""),

    ("a manager with no root is treated as a root of '.'",
     PP,
     "    root = getattr(sm, \"local_path\", None)\n"
     "    if root is None:\n"
     "        return None",
     "    root = getattr(sm, \"local_path\", None) or \".\""),

    ("the 'beside the source' test reverts to comparing ABSOLUTE parents",
     PP,
     "                                and PurePosixPath(prod_rel).parent\n"
     "                                == PurePosixPath(src_rel).parent):",
     "                                and prod_path.parent == src.parent):"),

    ("_resolve_conversion_target reverts to its own naive relativisation",
     PP,
     "        src_rel = _course_relative(sm, src)\n"
     "        if src_rel is not None:",
     "        try:\n"
     "            src_rel = str(src.relative_to(sm.local_path)).replace('\\\\', '/')\n"
     "        except (ValueError, AttributeError):\n"
     "            src_rel = None\n"
     "        if src_rel is not None:"),
]

KNOWN_EQUIVALENT = 1
#: Tried, and EQUIVALENT - recorded so nobody spends the time twice.
#:
#:   ("the candidate order is reversed - realpath tried FIRST")
#:
#: Both candidates describe the same location, and ``relative_to`` returns the
#: same relative string from either, so the order changes only which one
#: succeeds first. There is no input in this suite - or, as far as the fix is
#: concerned, in the product - that can tell the two orders apart.


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in CONVERSION_REPOINT_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in CONVERSION_REPOINT_MUTANTS:
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
    for label, rel, old, new in CONVERSION_REPOINT_MUTANTS:
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
                                cwd=REPO, capture_output=True,
                                timeout=PER_MUTANT_TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            rc = 1          # a mutant that hangs the suite is one it noticed
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{rel}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(CONVERSION_REPOINT_MUTANTS)} caught "
          f"(+{KNOWN_EQUIVALENT} documented equivalent, not run)")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
