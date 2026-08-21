"""Mutation pass for the Office document guard. Throwaway - not shipped.

Hazards this respects, all recorded in AUDIT_PLAYBOOK.md after they cost real
code or real time:

* **refuses a dirty tree.** The pass rewrites its targets, so any uncommitted
  edit would be silently discarded (it ate two finished fixes on 2026-08-11).
* **aborts if a target changes MID-PASS.** The clean check runs once, at the
  start, so an edit made while the pass is running was restored away with no
  message - measured 2026-08-13, a docstring lost to a background pass. The
  same window that can CAPTURE a mutant can DESTROY work, and only that
  direction is silent. Restore is from a snapshot taken at the start rather
  than from `git checkout`, which also means a commit landing mid-pass cannot
  change what "restore" means.
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
           "engine/applescript_bridge.py", "core/sync_manager.py"]
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
     "FATAL_CATEGORIES = ('permission', 'app_missing', 'container_denied')",
     "FATAL_CATEGORIES = ('permission', 'app_missing', 'container_denied', 'app_crashed')"),
    ("no retry at all", AB,
     "if category == 'app_crashed':\n                logger.warning(",
     "if False:\n                logger.warning("),
    ("successful retry does not reset the wedge counter", AB,
     "                    global _repeat_key, _repeat_count\n                    _repeat_key, _repeat_count = None, 0\n                    logger.info(",
     "                    logger.info("),
    # RETIRED 2026-08-20. These two broke the two apostrophe CLAUSES, which no
    # longer exist: `_classify_stderr` now normalises U+2019 once, up front, so
    # a clause added later cannot inherit the bug that produced them. The same
    # property - and the wider locale problem they were the first sighting of -
    # is covered by scripts/_mutate_applescript_locale.py ("the apostrophe
    # normalisation is dropped", "only the curly apostrophe is normalised").
    # Deleted rather than re-anchored: pointing them at the normalisation line
    # would just duplicate that set, and a duplicated mutant inflates a score
    # without adding a property.
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
    # Added 2026-08-21 with the -609 / -30001 widening. Each is a way of
    # half-doing it, and the last two are the ones that matter: widening the
    # recoverable set must not swallow an ordinary error into "retry me", and
    # must not make a transient failure fatal.
    ("-609 falls back to 'other', so a dead connection is never retried", AB,
     "    if ('-600' in err_msg or '-609' in err_msg",
     "    if ('-600' in err_msg"),
    ("-30001 is made retryable, which misdescribes a running app", AB,
     "    if ('-600' in err_msg or '-609' in err_msg",
     "    if ('-600' in err_msg or '-609' in err_msg or '-30001' in err_msg"),
    ("the wording clause for a dead connection is dropped", AB,
     "            or 'connection is invalid' in low):",
     "            or 'connection is invalid xx' in low):"),
    ("the widening swallows EVERYTHING into app_crashed", AB,
     "            or 'connection is invalid' in low):",
     "            or True):"),
]


# --- D5: a declined product must leave nothing behind ---------------------
GATE_TEST = "tests/test_office_product_gate.py tests/test_office_staging_short_names.py"
GATE_MUTANTS = [
    ("promote anything that exists (the original bug)", AB,
     "if staged_dst.exists() and _product_is_real(staged_dst):",
     "if staged_dst.exists():"),
    ("gate always says yes", AB,
     "    if staged_dst.suffix.lower() == '.pdf':",
     "    return True\n    if staged_dst.suffix.lower() == '.pdf':"),
    ("pdf gate downgraded to mere existence", AB,
     "        ok, why = pdf_looks_real(staged_dst)",
     "        ok, why = file_has_content(staged_dst)"),
    ("non-pdf products no longer checked", AB,
     "        ok, why = file_has_content(staged_dst, what=f\"{staged_dst.suffix} file\")",
     "        ok, why = True, ''"),
    ("import failure now rejects instead of promoting", AB,
     "    except Exception:\n        return True\n    if staged_dst.suffix",
     "    except Exception:\n        return False\n    if staged_dst.suffix"),
    ("direct path: reject left behind", AB,
     "                dst.unlink()\n                logger.warning(\n                    f\"[AppleScript] {app_name} left an unusable {dst.suffix} for \"",
     "                logger.warning(\n                    f\"[AppleScript] {app_name} left an unusable {dst.suffix} for \""),
    ("direct path: deletes a file it overwrote", AB,
     "            if existed:\n                logger.warning(", "            if False:\n                logger.warning("),
    ("direct path: no gate at all", AB,
     "        if dst.exists() and not _product_is_real(dst):",
     "        if False:"),
    ("staging litter kept on decline", AB,
     "the same rule `converters/archive.py:_decline` states for extraction.\n        shutil.rmtree(work, ignore_errors=True)",
     "the same rule `converters/archive.py:_decline` states for extraction.\n        pass"),
]


# --- concurrency: unique staged names + the cross-process lock -------------
CONC_TEST = "tests/test_office_concurrency.py"
CONC_MUTANTS = [
    ("staged basename back to a constant", AB,
     '_tok = work.name[-6:]\n    staged_src = work / (f"src_{_tok}" + src.suffix)\n    staged_dst = work / (f"out_{_tok}" + dst.suffix)',
     '_tok = work.name[-6:]\n    staged_src = work / ("src" + src.suffix)\n    staged_dst = work / ("out" + dst.suffix)'),
    ("only the SOURCE gets a token", AB,
     'staged_dst = work / (f"out_{_tok}" + dst.suffix)',
     'staged_dst = work / ("out" + dst.suffix)'),
    ("token appended AFTER the suffix", AB,
     'staged_src = work / (f"src_{_tok}" + src.suffix)',
     'staged_src = work / ("src" + src.suffix + _tok)'),
    # RE-ANCHORED 2026-08-13. `70ce78c` inserted `_note_office_preexisting`
    # between the `with` and the `return`, which invalidated the original
    # anchor - so from that commit onward this mutant could not run on any
    # platform and the recorded "8/9 caught" stopped being reproducible. The
    # quit set was re-anchored at the time (`7a2a674`); this one was not.
    # `tests/test_mutation_anchors.py` now fails the SUITE when an anchor goes
    # stale, so it cannot rot silently again.
    ("run_applescript stops taking the lock", AB,
     "    with _office_app_lock(app_name):\n        # Under the lock",
     "    if True:\n        # Under the lock"),
    ("lock made global instead of per app", AB,
     'f"canvas_dl_office_{app_name.lower()}.lock"', '"canvas_dl_office.lock"'),
    ("lock never actually acquired", AB,
     "fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)",
     "pass"),
    ("lock never released", AB,
     "            if held:\n                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)",
     "            if False:\n                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)"),
    ("unbounded wait", AB, "_OFFICE_LOCK_TIMEOUT_S = 120.0",
     "_OFFICE_LOCK_TIMEOUT_S = 100000.0"),
    ("lock active on Windows too", AB,
     "    if sys.platform != 'darwin':\n        yield\n        return\n    try:\n        import fcntl",
     "    if False:\n        yield\n        return\n    try:\n        import fcntl"),
]


# --- macOS volumes: the empty-mount-point case probe ----------------------
SM = "core/sync_manager.py"
VOL_TEST = "tests/test_path_key_case_folding.py"
VOL_MUTANTS = [
    ("mount-point guard removed", SM,
     "    try:\n        if os.path.ismount(directory):\n            return False\n    except Exception:       # noqa: BLE001\n        return False\n    flipped = directory.swapcase()",
     "    flipped = directory.swapcase()"),
    ("mount point answers True instead", SM,
     "        if os.path.ismount(directory):\n            return False",
     "        if os.path.ismount(directory):\n            return True"),
    ("guard inverted - refuses ordinary dirs", SM,
     "        if os.path.ismount(directory):\n            return False",
     "        if not os.path.ismount(directory):\n            return False"),
    ("a failing ismount is treated as certainty", SM,
     "    except Exception:       # noqa: BLE001\n        return False\n    flipped = directory.swapcase()",
     "    except Exception:       # noqa: BLE001\n        pass\n    flipped = directory.swapcase()"),
]


# --- the Office Recents purge ---------------------------------------------
PURGE_TEST = "tests/test_office_recents_purge.py"
PURGE_MUTANTS = [
    ('back to deleting only value rows', AB,
     '                cur.executemany(\n                    "DELETE FROM HKEY_CURRENT_USER WHERE node_id=?", ids)',
     ''),
    ('marker gate removed', AB,
     '                    if not (_marker_in_value(name) and nid not in has_child):',
     '                    if not (True and nid not in has_child):'),
    ('leaf gate removed', AB,
     '                    if not (_marker_in_value(name) and nid not in has_child):',
     '                    if not (_marker_in_value(name)):'),
    ('MruUserData gate removed', AB,
     '                    if not under:\n                        continue',
     '                    if False:\n                        continue'),
    ("purges a RUNNING app's entries", AB,
     '                    if app in running:\n                        continue',
     '                    if False:\n                        continue'),
    ('takes unattributable entries while an app runs', AB,
     '                    if app is None and running:\n                        continue',
     '                    if False:\n                        continue'),
    ('runs even when every app is running', AB,
     '    if len(running) == len(_OFFICE_PROCESSES):',
     '    if False:'),
    ('running check launches Office instead', AB,
     'if subprocess.run(["pgrep", "-x", bundle],',
     'if subprocess.run(["osascript", "-e", "x"],'),
    ('running check reports NOTHING on doubt', AB,
     '        except Exception:       # noqa: BLE001\n            return set(_OFFICE_PROCESSES)',
     '        except Exception:       # noqa: BLE001\n            return set()'),
    ('cycle guard removed from the ancestor walk', AB,
     '        while cur_id in by_id and cur_id not in seen:',
     '        while cur_id in by_id:'),
]


# --- quit scoping: only what we launched ----------------------------------
QUIT_TEST = "tests/test_office_quit_scoping.py"
QUIT_MUTANTS = [
    ('our staged document counts as the user\'s', AB,
     '                    if isOurs then\n                        set pristine to true',
     '                    if False then\n                        set pristine to true'),
    ('preexisting gate removed from the quit loop', AB,
     '            if not (short and office_is_ours_to_quit(short)):',
     '            if False:'),
    ("preexisting probe defaults to NOT the user's on failure", AB,
     "        except Exception:       # noqa: BLE001\n            running = True      # on doubt, treat it as the user's and never quit it",
     '        except Exception:       # noqa: BLE001\n            running = False'),
    # BOTH guards, not just the outer one. Since 2026-08-13 the function is
    # double-checked (fast path, then the same test inside the lock), so
    # removing the FAST PATH ALONE is an EQUIVALENT MUTANT - the inner check
    # still makes it idempotent and only lock contention changes. Verified
    # surviving for exactly that reason; the mutant that must be caught is the
    # one that removes idempotence altogether.
    ('observation re-taken on every conversion (BOTH guards)', AB,
     '    if app_name in _office_preexisting:     # fast path: no lock once answered\n'
     '        return\n'
     '    bundle = _APP_DOC_MAP.get(app_name, (None,))[0]\n'
     '    if not bundle:\n'
     '        return\n'
     '    with _office_observe_lock:\n'
     '        if app_name in _office_preexisting:  # another thread got there first\n'
     '            return\n',
     '    bundle = _APP_DOC_MAP.get(app_name, (None,))[0]\n'
     '    if not bundle:\n'
     '        return\n'
     '    with _office_observe_lock:\n'),
    ('observation moved outside the lock', AB,
     '        _note_office_preexisting(app_name)\n        return _run_applescript_locked(',
     '        return _run_applescript_locked('),
    ('undescribable document back to pristine unconditionally', AB,
     '                    else\n                        set pristine to {str(undescribable_is_ours).lower()}\n                    end if',
     '                    end if'),
    ('HFS path fallback back to slash-only', AB,
     'if fn contains "/" or fn contains ":" then set hasPath to true',
     'if fn contains "/" then set hasPath to true'),

    # --- per-RUN scoping, 2026-08-13 -------------------------------------
    ('the observation survives a run boundary (back to per-process)', AB,
     '    with _office_observe_lock:\n        _office_preexisting.clear()',
     '    pass'),
    ('the per-run clear is not serialised against the write', AB,
     '    with _office_observe_lock:\n        _office_preexisting.clear()',
     '    _office_preexisting.clear()'),
    ('an UNOBSERVED app is ours again (the boolean-with-a-default)', AB,
     '    return _office_preexisting.get(app_name) is False',
     '    return not bool(_office_preexisting.get(app_name, False))'),
    ('the run-start launcher stops observing', AB,
     '    observe_office_before_launch()\n\n    if _first_run_batch_started:',
     '    if _first_run_batch_started:'),
    ('the run-start observation moves BELOW the once-per-process guard', AB,
     '    observe_office_before_launch()\n\n    if _first_run_batch_started:\n        return False',
     '    if _first_run_batch_started:\n        return False\n    observe_office_before_launch()'),
    ('priming stops observing', AB,
     '    observe_office_before_launch()\n\n    to_launch = []',
     '    to_launch = []'),
    ('priming observes only the apps it is about to launch', AB,
     '    for _key, _ms, short in _APP_TRIPLES:\n        _note_office_preexisting(short)',
     '    return'),
    ('the launcher itself stops observing', AB,
     '    observe_office_before_launch()\n\n    if write_macro_pref:',
     '    if write_macro_pref:'),
    ('the teardown inherits the undescribable policy again', AB,
     '                     _idle_quit_script(app, collection, undescribable_is_ours=True)],',
     '                     _idle_quit_script(app, collection)],'),
    ('the undescribable DEFAULT goes back to the unsafe answer', AB,
     '                      undescribable_is_ours: bool = False) -> str:',
     '                      undescribable_is_ours: bool = True) -> str:'),
]


def _clean() -> bool:
    r = subprocess.run(["git", "status", "--porcelain"] + TARGETS + [TEST],
                       cwd=REPO, capture_output=True, text=True)
    return not r.stdout.strip()


def _snapshot() -> dict:
    """The exact bytes of every target, read once, after the clean check."""
    return {rel: (REPO / rel).read_text(encoding="utf-8") for rel in TARGETS}


def _restore(snapshot: dict) -> None:
    """Put the targets back from the SNAPSHOT, not from git.

    `git checkout --` was the original and has two problems this does not: it
    depends on HEAD still being the version the pass started from (a commit
    landing mid-pass silently changes what "restore" means - the recorded
    2026-08-10 incident), and it rewrites every target whether or not this pass
    touched it. Writing back the bytes we read is exact and needs no git at all.
    """
    for rel, text in snapshot.items():
        p = REPO / rel
        if p.read_text(encoding="utf-8") != text:
            p.write_text(text, encoding="utf-8")
    for d in REPO.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def main(mutants=None, test=None) -> int:
    mutants = mutants or MUTANTS
    test = test or TEST
    if not _clean():
        print("REFUSING: tree is dirty for the targeted files. Commit first - "
              "the pass rewrites them and would discard your work.")
        return 2
    snapshot = _snapshot()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    survivors = []
    for label, rel, old, new in mutants:
        p = REPO / rel
        src = p.read_text(encoding="utf-8")
        # THE SOURCE MUST STILL BE WHAT WE STARTED FROM.
        #
        # `_clean()` runs ONCE, at the start, so an edit made to a target WHILE
        # the pass runs was restored away with no message at all. Measured
        # 2026-08-13: a docstring written into engine/applescript_bridge.py
        # during a background pass, gone, noticed only because the editor
        # warned the file had changed underneath it.
        #
        # It is the mirror of the recorded hazard - the same window that can
        # CAPTURE a mutant can DESTROY work - and only this direction is
        # silent, because the pass goes on reporting truthfully afterwards.
        if src != snapshot[rel]:
            print(f"  !! {rel} CHANGED UNDER THE PASS - aborting at {label!r}")
            print(f"     Something else is editing it: another session, an "
                  f"editor, or you. Every result after this point would "
                  f"describe a tree nobody wrote.")
            print(f"     NOTHING HAS BEEN RESTORED, deliberately: the change is "
                  f"on disk and it is not ours, so writing the snapshot over it "
                  f"is the exact data loss this guard exists to stop. No mutant "
                  f"is on disk either - the check runs BEFORE the write, and the "
                  f"previous mutant was already restored.")
            # Only the bytecode, which may be a mutant's.
            for d in REPO.rglob("__pycache__"):
                shutil.rmtree(d, ignore_errors=True)
            return 3
        if old not in src:
            print(f"  !! ANCHOR MISSING  {label}  ({rel})")
            survivors.append(f"{label} [anchor missing - the test proves nothing]")
            continue
        p.write_text(src.replace(old, new, 1), encoding="utf-8")
        # BOUNDED: a mutant can make the code loop forever, and an unbounded
        # run turns "caught" into a hung pass. A timeout counts as caught -
        # the mutant demonstrably broke termination.
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", *test.split(), "-x", "-q"],
                               cwd=REPO, capture_output=True, text=True, env=env,
                               timeout=180)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = -9
        _restore(snapshot)
        caught = rc != 0
        print(f"  {'caught ' if caught else 'SURVIVED'}  {label}")
        if not caught:
            survivors.append(label)
    print(f"\n{len(mutants) - len(survivors)}/{len(mutants)} caught")
    for s in survivors:
        print("  SURVIVOR:", s)
    return 1 if survivors else 0


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "guard"
    raise SystemExit(main(CRASH_MUTANTS, CRASH_TEST) if which == "crash"
                     else main(GATE_MUTANTS, GATE_TEST) if which == "gate"
                     else main(CONC_MUTANTS, CONC_TEST) if which == "conc"
                     else main(VOL_MUTANTS, VOL_TEST) if which == "vol"
                     else main(PURGE_MUTANTS, PURGE_TEST) if which == "purge"
                     else main(QUIT_MUTANTS, QUIT_TEST) if which == "quit"
                     else main())
