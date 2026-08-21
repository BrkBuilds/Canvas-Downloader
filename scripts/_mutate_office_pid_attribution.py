"""Mutation pass for the Office PID attribution fix.

Flips one real behaviour at a time and asserts the tests go RED. A test that
survives its own mutant is testing the shape of the code rather than what it
does.

The mutants are the plausible ways this gets undone: reverting to "first new
process wins" (the original defect), dropping the settle re-check that catches a
racing sibling, resolving ambiguity by picking one, and failing OPEN on an
unreadable command line - which is the one that silently turns a leak back into
a force-kill aimed at a process we could not identify.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once - a Windows session is live on this
same repo right now - so (a) HEAD may not be what this pass started from, and
(b) a hard checkout would discard somebody else's uncommitted edit to a file
this pass never mutated. Before every mutant the target is compared against its
snapshot and the pass ABORTS if it has changed underneath, without restoring
anything, because at that point the only thing on disk is their edit.

    python scripts/_mutate_office_pid_attribution.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PID = "engine/office_pid.py"

TESTS = ["tests/test_office_pid_attribution.py"]

#: (label, file, old, new)
OFFICE_PID_MUTANTS = [
    # -- the original defect, restored ---------------------------------------
    ("attribution reverts to 'first new process of that name wins'",
     PID,
     "            if _is_com_launched(p):\n                found.add(p.pid)",
     "            found.add(p.pid)"),

    # -- ambiguity is resolved by guessing ------------------------------------
    ("ambiguity picks one instead of refusing",
     PID,
     "            if len(candidates) == 1:\n                return next(iter(candidates))",
     "            if candidates:\n                return next(iter(candidates))"),
    ("ambiguity refuses but says nothing, so it cannot be diagnosed",
     PID,
     "            logger.warning(\n"
     '                "Cannot attribute a %s process to this run: %d COM-launched "',
     "            logger.debug(\n"
     '                "Cannot attribute a %s process to this run: %d COM-launched "'),

    # -- the settle re-check ---------------------------------------------------
    ("the settle re-check is dropped, so a racing sibling is never seen",
     PID,
     "            _t.sleep(_ATTRIBUTION_SETTLE_SECONDS)\n"
     "            candidates = _new_com_pids(psutil, upper, pre_pids)\n",
     ""),

    # -- failing OPEN on an unreadable process (the dangerous direction) ------
    ("an unreadable command line is treated as OURS",
     PID,
     "    except Exception:\n        return False\n"
     "    return any(marker in cmdline for marker in _COM_ACTIVATION_MARKERS)",
     "    except Exception:\n        return True\n"
     "    return any(marker in cmdline for marker in _COM_ACTIVATION_MARKERS)"),

    # -- the discriminator itself ---------------------------------------------
    ("the marker match becomes case-SENSITIVE against a lower-cased line",
     PID,
     '        cmdline = " ".join(proc.cmdline() or ()).lower()',
     '        cmdline = " ".join(proc.cmdline() or ())'),
    ("only the dash spelling is recognised, so the slash form is missed",
     PID,
     '_COM_ACTIVATION_MARKERS = ("-embedding", "/embedding")',
     '_COM_ACTIVATION_MARKERS = ("-embedding",)'),

    # -- the exe-name filter still has to apply -------------------------------
    ("the process NAME filter is dropped, so any COM client is adopted",
     PID,
     "            if (p.info['name'] or '').upper() != upper or p.pid in pre_pids:\n"
     "                continue",
     "            if p.pid in pre_pids:\n                continue"),
    ("the pre_pids snapshot is ignored",
     PID,
     "            if (p.info['name'] or '').upper() != upper or p.pid in pre_pids:\n"
     "                continue",
     "            if (p.info['name'] or '').upper() != upper:\n                continue"),

    # -- it must not raise on the init path -----------------------------------
    ("a missing psutil raises instead of answering None",
     PID,
     "    try:\n        import psutil\n    except Exception:\n        return None",
     "    import psutil"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a file in this repo may be CRLF.

    Matching raw bytes is what makes an anchor honest (a universal-newlines read
    would silently rewrite the file's line endings on restore), so the anchor is
    translated to the file's own newline instead.
    """
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in OFFICE_PID_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, new in OFFICE_PID_MUTANTS:
        nl = _nl_of(snapshot[rel])
        if old.replace("\n", nl) not in snapshot[rel]:
            stale.append(f"{label!r} in {rel}")
        elif snapshot[rel].count(old.replace("\n", nl)) > 1:
            stale.append(f"{label!r} in {rel} - ANCHOR IS NOT UNIQUE "
                         "(replace(...,1) would mutate the first match, which "
                         "may not be the one the label names)")
    if stale:
        print("STALE OR AMBIGUOUS ANCHORS - these mutants could not run "
              "honestly, so any score recorded for them is UNMEASURED:")
        for s in stale:
            print("  " + s)
        return 4

    print(f"baseline: running {len(TESTS)} test file(s)")
    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in OFFICE_PID_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass "
                  f"(another session?). Nothing restored - the file on disk is "
                  f"THEIR edit, not a mutant.")
            return 3
        nl = _nl_of(current)
        old_nl, new_nl = old.replace("\n", nl), new.replace("\n", nl)

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

    print(f"\n{len(caught)}/{len(OFFICE_PID_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
