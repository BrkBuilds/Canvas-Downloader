"""Mutation pass for the Office document guard. Throwaway - not shipped.

Hazards this respects, all recorded in AUDIT_PLAYBOOK.md after they cost real
code or real time:

* **refuses a dirty tree.** `restore()` is a hard `git checkout`, so any
  uncommitted edit would be silently discarded (it ate two finished fixes on
  2026-08-11).
* **bytecode.** A same-size mutation restored inside the same second leaves a
  stale `.pyc` that Python trusts, so the next run tests the mutant. Runs with
  PYTHONDONTWRITEBYTECODE and clears __pycache__ between mutants.
* **targeted run**, ~80x cheaper than the whole file; the FULL suite is run
  once at the end, by hand, because that is what catches a capture.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGETS = ["converters/pdf.py", "converters/word.py", "converters/excel.py",
           "engine/applescript_bridge.py"]
TEST = "tests/test_office_document_guard.py"

# (label, file, old, new)
MUTANTS = [
    # the two guard sites, per converter
    ("ppt: unguard the error-handler close", "converters/pdf.py",
     "if {ours} then close active presentation saving no",
     "close active presentation saving no"),
    ("word: unguard the error-handler close", "converters/word.py",
     "if {ours} then close active document saving no",
     "close active document saving no"),
    ("excel: unguard the error-handler close", "converters/excel.py",
     "if {ours} then close active workbook saving no",
     "close active workbook saving no"),
    ("ppt: drop the success-path check", "converters/pdf.py",
     'if not {ours} then\n                            error "the frontmost presentation is not the one Canvas Downloader opened" number {OFFICE_WRONG_DOC_ERRNO}\n                        end if\n                        ',
     ""),
    ("word: drop the success-path check", "converters/word.py",
     'if not {ours} then\n                            error "the frontmost document is not the one Canvas Downloader opened" number {OFFICE_WRONG_DOC_ERRNO}\n                        end if\n                        ',
     ""),
    ("excel: drop the success-path check", "converters/excel.py",
     'if not {ours} then\n                            error "the frontmost workbook is not the one Canvas Downloader opened" number {OFFICE_WRONG_DOC_ERRNO}\n                        end if\n                        ',
     ""),
    # bind the wrong name
    ("ppt: guard built from the ORIGINAL name", "converters/pdf.py",
     'our_document_test("PowerPoint", s_src.name)',
     'our_document_test("PowerPoint", src.name)'),
    ("word: guard built from the ORIGINAL name", "converters/word.py",
     'our_document_test("Word", s_src.name)',
     'our_document_test("Word", src.name)'),
    ("excel: guard built from the ORIGINAL name", "converters/excel.py",
     'our_document_test("Excel", s_src.name)',
     'our_document_test("Excel", src.name)'),
    # the helper itself
    ("helper: always true", "engine/applescript_bridge.py",
     'return f\'((name of {doc_term}) is "{applescript_string(staged_name)}")\'',
     "return 'true'"),
    ("helper: skip the escaper", "engine/applescript_bridge.py",
     'return f\'((name of {doc_term}) is "{applescript_string(staged_name)}")\'',
     'return f\'((name of {doc_term}) is "{staged_name}")\''),
    ("helper: unknown app returns a dud instead of raising",
     "engine/applescript_bridge.py",
     '        raise KeyError(f"unknown Office app_name {app_name!r}")',
     '        return "true"'),
    ("helper: wrong document term", "engine/applescript_bridge.py",
     "    _ms_name, doc_term = mapping",
     '    _ms_name, doc_term = mapping\n    doc_term = "active document"'),
    ("errno: collides with a real AppleScript error",
     "engine/applescript_bridge.py",
     "OFFICE_WRONG_DOC_ERRNO = -30001", "OFFICE_WRONG_DOC_ERRNO = -1708"),
    # the Excel page-setup binding
    ("excel: page setup back on the application's active sheet",
     "converters/excel.py",
     "tell page setup of active sheet of theBook",
     "tell page setup of active sheet"),
]


# --- D6: a crashed app is not a missing one -------------------------------
AB = "engine/applescript_bridge.py"
CRASH_TEST = "tests/test_office_crash_is_not_missing.py"
CRASH_MUTANTS = [
    ("-600 back in app_missing", AB,
     "'-10810' in err_msg or '-10814' in err_msg",
     "'-10810' in err_msg or '-10814' in err_msg or '-600' in err_msg"),
    ("app_crashed made fatal", AB,
     "FATAL_CATEGORIES = ('permission', 'app_missing')",
     "FATAL_CATEGORIES = ('permission', 'app_missing', 'app_crashed')"),
    ("no retry at all", AB,
     "if category == 'app_crashed':\n                logger.warning(",
     "if False:\n                logger.warning("),
    ("successful retry does not reset the wedge counter", AB,
     "                    global _repeat_key, _repeat_count\n                    _repeat_key, _repeat_count = None, 0\n                    logger.info(",
     "                    logger.info("),
    ("curly apostrophe dropped", AB,
     ' or "isn\u2019t running" in low', ""),
    ("straight apostrophe dropped", AB,
     '"isn\'t running" in low or ', ""),
    ("crash detail claims not installed", AB,
     'f"Microsoft {app_name} stopped running while converting "',
     'f"Microsoft {app_name} is not installed or could not be launched. "'),
    ("missing app is retried too", AB,
     "if category == 'app_crashed':\n                logger.warning(",
     "if category in ('app_crashed', 'app_missing'):\n                logger.warning("),
    ("retry does not re-classify the second failure", AB,
     "                err_msg = result.stderr.strip() or err_msg\n                category = _classify_stderr(err_msg)",
     "                err_msg = result.stderr.strip() or err_msg"),
    ("relaunch pause removed", AB,
     "_CRASH_RELAUNCH_PAUSE_S = 3.0", "_CRASH_RELAUNCH_PAUSE_S = 0.0"),
]


def _clean() -> bool:
    r = subprocess.run(["git", "status", "--porcelain"] + TARGETS + [TEST],
                       cwd=REPO, capture_output=True, text=True)
    return not r.stdout.strip()


def _restore() -> None:
    subprocess.run(["git", "checkout", "--"] + TARGETS, cwd=REPO,
                   capture_output=True)
    for d in REPO.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def main(mutants=None, test=None) -> int:
    mutants = mutants or MUTANTS
    test = test or TEST
    if not _clean():
        print("REFUSING: tree is dirty for the targeted files. Commit first - "
              "restore() is a hard git checkout and would discard your work.")
        return 2
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    survivors = []
    for label, rel, old, new in mutants:
        p = REPO / rel
        src = p.read_text(encoding="utf-8")
        if old not in src:
            print(f"  !! ANCHOR MISSING  {label}  ({rel})")
            survivors.append(f"{label} [anchor missing - the test proves nothing]")
            continue
        p.write_text(src.replace(old, new, 1), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "pytest", test, "-x", "-q"],
                           cwd=REPO, capture_output=True, text=True, env=env)
        _restore()
        caught = r.returncode != 0
        print(f"  {'caught ' if caught else 'SURVIVED'}  {label}")
        if not caught:
            survivors.append(label)
    print(f"\n{len(mutants) - len(survivors)}/{len(mutants)} caught")
    for s in survivors:
        print("  SURVIVOR:", s)
    return 1 if survivors else 0


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "guard"
    raise SystemExit(main(CRASH_MUTANTS, CRASH_TEST) if which == "crash" else main())
