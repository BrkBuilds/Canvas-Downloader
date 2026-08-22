"""Mutation pass for the one-link-one-owner rule.

`tests/test_shortcut_ownership.py` guards a rule that has to hold in BOTH
directions - Panopto steps over Canvas's links, Canvas steps over Panopto's
artifacts - plus the analyzer branch that stops the resulting rows reading as
locally modified. Every mutant here is a plausible edit, not a strawman:
"the file is there, just overwrite it", "the check is redundant, the compiler
deletes it anyway", "make the predicate simpler".

The symmetry mutant is the one that justifies the set. Deleting the ownership
check while leaving the `from shared.shortcuts import is_produced_shortcut`
line above it is exactly what a hurried edit looks like, and a census that
greps for the NAME passes against it - the trap CLAUDE.md records letting four
mutants escape a previous set.

Restore is from an in-memory SNAPSHOT, never `git checkout`: this repo is
routinely worked by two sessions at once. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath,
restoring nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_shortcut_ownership.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CANVAS = "core/canvas_logic.py"
SYNC = "core/sync_manager.py"
PANOPTO = "panopto/shortcut.py"

TESTS = ["tests/test_shortcut_ownership.py"]
TEST_TARGET = TESTS

#: (label, file, old, new)
SHORTCUT_OWNERSHIP_MUTANTS = [
    # -- Canvas must step over OUR artifact ----------------------------------
    ("_create_link stops checking ownership and overwrites the Panopto output",
     CANVAS,
     "            _keep_produced = path_exists(filepath) and is_produced_shortcut(filepath)",
     "            _keep_produced = False"),

    ("_create_link protects EVERY existing shortcut, so a stale Canvas link "
     "is never regenerated",
     CANVAS,
     "            _keep_produced = path_exists(filepath) and is_produced_shortcut(filepath)",
     "            _keep_produced = path_exists(filepath)"),

    ("the skip path returns early and records no manifest row, so the Canvas "
     "item reads as NEW on every later sync for ever",
     CANVAS,
     "            if _keep_produced:\n"
     "                log_debug(",
     "            if _keep_produced:\n"
     "                return filepath\n"
     "                log_debug("),

    ("an unreadable shortcut is treated as OURS instead of falling through to "
     "an ordinary write",
     CANVAS,
     "        except Exception:\n"
     "            # An unreadable shortcut is not proof of ownership; fall through to\n"
     "            # the ordinary write rather than silently declining to create a link.\n"
     "            _keep_produced = False",
     "        except Exception:\n"
     "            _keep_produced = True"),

    # -- the analyzer must not report the replacement as a local edit --------
    ("the replaced-by-produced-shortcut branch is removed, so all 36 rows "
     "classify as locally modified again",
     SYNC,
     "                elif _is_replaced_by_produced_shortcut(local_path):",
     "                elif False:"),

    ("the predicate answers True for everything, swallowing genuine updates",
     SYNC,
     "        if _P(local_path).suffix.lower() not in SHORTCUT_SUFFIXES:\n"
     "            return False\n"
     "        return bool(is_produced_shortcut(local_path))",
     "        return True"),

    ("the predicate answers False for everything, i.e. the pre-fix behaviour",
     SYNC,
     "        if _P(local_path).suffix.lower() not in SHORTCUT_SUFFIXES:\n"
     "            return False\n"
     "        return bool(is_produced_shortcut(local_path))",
     "        return False"),

    ("the predicate stops being total and raises out of analyze_course, which "
     "has no try around it",
     SYNC,
     "    except Exception:                                           # noqa: BLE001\n"
     "        return False\n"
     "\n"
     "\ndef _is_archive_path(",
     "    except Exception:                                           # noqa: BLE001\n"
     "        raise\n"
     "\n"
     "\ndef _is_archive_path("),

    # -- the OTHER direction, with the import left in place ------------------
    ("Panopto stops checking ownership and adopts foreign files, with the "
     "import left behind so a name-grep census still passes",
     PANOPTO,
     "            if is_produced_shortcut(cand):\n"
     "                return cand          # ours already - adopt, never rewrite",
     "            if True:\n"
     "                return cand          # ours already - adopt, never rewrite"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in SHORTCUT_OWNERSHIP_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in SHORTCUT_OWNERSHIP_MUTANTS:
        nl = _nl_of(snapshot[rel])
        body = snapshot[rel]
        anchored = old.replace("\n", nl)
        if anchored not in body:
            stale.append(f"{label!r} in {rel}")
        elif body.count(anchored) > 1:
            # The twin-anchor trap: str.replace(..., 1) takes whichever copy is
            # defined FIRST, so the pass would report a result under a label
            # that is a lie. CLAUDE.md records five instances of this.
            stale.append(f"{label!r} in {rel} matches {body.count(anchored)} times "
                         f"- anchor it uniquely")
    if stale:
        print("STALE OR AMBIGUOUS ANCHORS - these mutants could not run "
              "correctly, so any score recorded for them is UNMEASURED:")
        for s in stale:
            print("  " + s)
        return 4

    print(f"baseline: running {len(TESTS)} test file(s)")
    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in SHORTCUT_OWNERSHIP_MUTANTS:
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
                                timeout=900).returncode
        except subprocess.TimeoutExpired:
            rc = 1          # a mutant that hangs the suite is one it noticed
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{rel}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(SHORTCUT_OWNERSHIP_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
