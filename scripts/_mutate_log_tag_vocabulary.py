"""Mutation pass for the audit's log-tag vocabulary and blind-oracle guards.

Flips one real behaviour at a time and asserts the tests go RED. A test that
survives its own mutant is testing the shape of the code rather than what it
does.

The mutants here are not strawmen - each is the code as it ACTUALLY SHIPPED
before 2026-08-21, or a plausible next version of it:

  * three tag names the app has never emitted (the original defect, which cost
    the sync matrix 14 fabricated HIGH findings across the two categories that
    decide whether a student's edited file is protected),
  * `_LOG_DETAILED_CATS` back to the two-category constant that was derived FROM
    that defect and then written down as a fact about the product,
  * the blind guard back to `oracle == "O2"`, which protected half the branch,
  * the peer list back to the log, i.e. to an oracle the finding never consulted,
  * the re-check's completion-capture fallback, which made a re-check disagree
    with the live pass it exists to reproduce,
  * NFC folding removed, which is invisible on every ASCII filename and breaks
    Danish `a-ring` while leaving the slashed-o and ae ligature alone.

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

    python scripts/_mutate_log_tag_vocabulary.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

LOG = "tests/audit/harness/oracles/log.py"
CROSS = "tests/audit/harness/crosscheck.py"
PAR = "tests/audit/harness/parallel.py"

TESTS = [
    "tests/test_audit_log_tag_vocabulary.py",
    "tests/test_audit_harness.py",
    "tests/test_audit_recheck_parity.py",
]
TEST_TARGET = TESTS
PER_MUTANT_TIMEOUT = 600

#: (label, file, old, new)
VOCAB_MUTANTS = [
    # -- the original defect, one tag at a time ------------------------------
    ("UPDATE-EDIT reverts to the tag the app never emitted",
     LOG,
     '    "UPDATE-EDIT": "updated_modified",',
     '    "UPDATE-MODIFIED": "updated_modified",'),
    ("CANVAS-DEL reverts to the tag the app never emitted",
     LOG,
     '    "CANVAS-DEL": "deleted_on_canvas",',
     '    "DELETED-CANVAS": "deleted_on_canvas",'),
    ("LOCAL-DEL reverts to the tag the app never emitted",
     LOG,
     '    "LOCAL-DEL": "deleted_locally",',
     '    "DELETED-LOCAL": "deleted_locally",'),

    # -- the arrow suffix ----------------------------------------------------
    ("the row pattern swallows the arrow suffix into the filename again",
     LOG,
     r'    r"\s+(?P<name>.+?)(?:\s{2,}->\s*(?P<local>.+))?$")',
     r'    r"\s+(?P<name>.+)$")'),
    ("only the display name reaches the matcher, never the local path",
     LOG,
     '        for v in (e.data.get("name"), e.data.get("local")):\n'
     '            if v and v not in bucket:\n'
     '                bucket.append(v)\n'
     '    for e in pl.of("qs_select"):',
     '        v = e.data.get("name")\n'
     '        if v and v not in bucket:\n'
     '            bucket.append(v)\n'
     '    for e in pl.of("qs_select"):'),
    ("the counting view double-counts every row that carries a path",
     LOG,
     '        out.setdefault(e.data["cat"], []).append(\n'
     '            {"display": e.data.get("name") or "", "local": e.data.get("local") or ""})',
     '        for _v in (e.data.get("name"), e.data.get("local")):\n'
     '            if _v:\n'
     '                out.setdefault(e.data["cat"], []).append({"display": _v, "local": ""})'),

    # -- the false premise that was built on the defect ----------------------
    ("_LOG_DETAILED_CATS reverts to the two-category constant",
     CROSS,
     "_LOG_DETAILED_CATS = frozenset(_LOG_CAT.values())",
     '_LOG_DETAILED_CATS = frozenset({"new", "updated_clean"})'),
    ("the vocabulary is restated locally instead of imported",
     CROSS,
     "from .oracles.log import ANALYSIS_ROW_TAGS as _LOG_CAT      # noqa: E402",
     '_LOG_CAT = {"NEW": "new", "UPDATE-CLEAN": "updated_clean",\n'
     '            "UPDATE-MODIFIED": "updated_modified",\n'
     '            "DELETED-CANVAS": "deleted_on_canvas",\n'
     '            "DELETED-LOCAL": "deleted_locally", "IGNORED": "ignored"}'),

    # -- the blind guard -----------------------------------------------------
    ("the blind guard is scoped to O2 again, leaving O1 unprotected",
     CROSS,
     "            blind = (not _own_rows) and (_placed is None or _placed > 0)",
     '            blind = (oracle == "O2") and (not _own_rows)'),
    ("a category the app genuinely left EMPTY is excused as blindness",
     CROSS,
     "            blind = (not _own_rows) and (_placed is None or _placed > 0)",
     "            blind = not _own_rows"),
    ("the peer list is read from the log whichever oracle decided",
     CROSS,
     '                              "peers_in_category": _own_rows[:20]},',
     '                              "peers_in_category": (_log_rows or [])[:20]},'),

    # -- the oracle's self-check ---------------------------------------------
    ("the tally-vs-rows invariant stops running",
     CROSS,
     "    out.extend(_log_tally_matches_its_own_rows(ev))\n",
     "\n"),
    ("the tally check reads the MATCHING view instead of the row view",
     CROSS,
     '    detail = ev.log.get("analysis_row_detail") or {}',
     '    detail = ev.log.get("analysis_rows") or {}'),

    # -- Unicode -------------------------------------------------------------
    ("NFC folding is dropped from _norm",
     CROSS,
     '    return os.path.normcase(_nfc(Path(str(name).replace("\\\\", "/")).name.strip()))',
     '    return os.path.normcase(Path(str(name).replace("\\\\", "/")).name.strip())'),
    ("NFC folding is dropped from _stem",
     CROSS,
     '    return os.path.normcase(_nfc(Path(str(name).replace("\\\\", "/")).stem.strip()))',
     '    return os.path.normcase(Path(str(name).replace("\\\\", "/")).stem.strip())'),
    ("the fold normalises the wrong way (NFD)",
     CROSS,
     '    return unicodedata.normalize("NFC", s)',
     '    return unicodedata.normalize("NFD", s)'),

    # -- selection / re-check parity -----------------------------------------
    ("a completion capture passes as a review screen again",
     CROSS,
     '    if not ui_review.get("courses") \\\n'
     '            and not (ui_review.get("seen") or {}).get("categoryContainers"):\n'
     '        return None\n',
     ''),
    ("the re-check falls back to the completion capture for a sync row",
     PAR,
     '                ui = _ui_capture(lrp, f"{job.name}_review")\n            else:',
     '                ui = _ui_capture(lrp, f"{job.name}_review") or \\\n'
     '                    _ui_capture(lrp, f"{job.name}_complete")\n            else:'),
    ("a re-checked finding loses the course it happened in",
     PAR,
     "    return Path(root).name if root else fallback",
     "    return fallback"),
]

KNOWN_EQUIVALENT = 0
#: Nothing recorded here yet. Two mutants LOOKED equivalent on first reading and
#: are not, so they stay in the set above:
#:
#:   * "the fold normalises the wrong way (NFD)" - folding either way makes the
#:     two spellings compare equal INSIDE the audit, which is why it survived
#:     the first pass. It is still wrong: NFC is what `core.sync_manager.
#:     _path_key` uses and what the seed plan carries, so an audit folding the
#:     other way is one un-folded comparison away from being wrong again.
#:   * "a category the app genuinely left EMPTY is excused as blindness" - it
#:     reads as a widening of a safety guard and is really the removal of an
#:     assertion, i.e. it hides real defects rather than inventing them.


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in VOCAB_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in VOCAB_MUTANTS:
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
    for label, rel, old, new in VOCAB_MUTANTS:
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

    print(f"\n{len(caught)}/{len(VOCAB_MUTANTS)} caught "
          f"(+{KNOWN_EQUIVALENT} documented equivalent, not run)")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
