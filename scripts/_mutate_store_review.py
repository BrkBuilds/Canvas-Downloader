"""Mutation pass for the Microsoft Store rating ask.

Flips one real behaviour at a time and asserts the tests go RED. A test that
survives its own mutant is testing the shape of the code rather than what it
does.

Every mutant here is a PLAUSIBLE refactor rather than a strawman - an off-by-one
on the cap, a "simplification" of the snooze, the tempting ``len(errors) == 0``
spelling of a clean run, charging the ask on a click instead of on show. Those
are the shapes this feature would actually regress into.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so (a) HEAD may not be what this pass
started from, and (b) a hard checkout would discard somebody else's uncommitted
edit to a file this pass never mutated. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it has changed underneath -
without restoring anything, because at that point the only thing on disk is
their edit, and writing the snapshot over it is exactly the loss being
prevented.

Each mutant runs under a TIMEOUT. A mutant that makes the code block hangs
pytest, the pass gets killed from outside, its ``finally`` never runs, and the
MUTANT IS LEFT ON DISK - indistinguishable from real code. A timeout counts as
CAUGHT: a mutant that hangs the suite is one the suite noticed.

    python scripts/_mutate_store_review.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

STORE = "core/store_review.py"
COMPONENTS = "shared/components.py"
APP = "app.py"
SYNC = "sync/completion.py"
HELPERS = "shared/helpers.py"

TESTS = [
    "tests/test_store_review.py",
    "tests/test_settings_coownership.py",
]

#: Seconds per mutant. Generous against a cold import of the app graph, tight
#: enough that a genuinely wedged mutant is reported rather than waited out.
TIMEOUT = 300

#: (label, file, old, new)
STORE_REVIEW_MUTANTS = [
    # ── The gate ────────────────────────────────────────────────────────────
    (
        "should_ask ignores the terminal 'rated' state",
        STORE,
        '    if st.get("rated"):\n        return False\n'
        '    if int(st.get("asks", 0)) >= MAX_ASKS:',
        '    if int(st.get("asks", 0)) >= MAX_ASKS:',
    ),
    (
        "the lifetime cap is off by one (a fourth ask)",
        STORE,
        '    if int(st.get("asks", 0)) >= MAX_ASKS:',
        '    if int(st.get("asks", 0)) > MAX_ASKS:',
    ),
    (
        "the lifetime cap is raised out of the way",
        STORE,
        "REQUIRED_RUN_DAYS = 3\nSNOOZE_DAYS = 7\nMAX_ASKS = 3",
        "REQUIRED_RUN_DAYS = 3\nSNOOZE_DAYS = 7\nMAX_ASKS = 99",
    ),
    (
        "one day of use is enough (asks a brand-new install)",
        STORE,
        "REQUIRED_RUN_DAYS = 3\nSNOOZE_DAYS = 7\nMAX_ASKS = 3",
        "REQUIRED_RUN_DAYS = 1\nSNOOZE_DAYS = 7\nMAX_ASKS = 3",
    ),
    (
        "the snooze is not honoured",
        STORE,
        "    if snoozed and snoozed > today:\n        return False",
        "    if False:\n        return False",
    ),
    (
        "the snooze never expires",
        STORE,
        "    if snoozed and snoozed > today:\n        return False",
        "    if snoozed:\n        return False",
    ),
    (
        "a garbled snooze date reads as 'ask now'",
        STORE,
        '    snoozed = st.get("snoozed_until") or ""',
        '    snoozed = ""',
    ),
    # ── The writes ──────────────────────────────────────────────────────────
    (
        "a clean run is recorded per RERUN, not per day",
        STORE,
        "    if len(days) >= REQUIRED_RUN_DAYS or today in days:\n        return False",
        "    if len(days) >= REQUIRED_RUN_DAYS:\n        return False",
    ),
    (
        "showing the card does not start the snooze",
        STORE,
        "    until = _dt.date.fromisoformat(today) + _dt.timedelta(days=SNOOZE_DAYS)\n"
        '    state["snoozed_until"] = until.isoformat()',
        "    pass",
    ),
    (
        "note_rated does not actually mark it rated",
        STORE,
        '    state = load_state()\n    state["rated"] = True',
        "    state = load_state()",
    ),
    (
        "an unreadable ask count is assumed FRESH (re-opens a settled ask)",
        STORE,
        '        state["asks"] = MAX_ASKS  # unreadable = assume spent, never = assume fresh',
        '        state["asks"] = 0',
    ),
    (
        "_save_state degrades an unreadable settings file to {} and writes",
        STORE,
        "    full, may_write = _read_full_config_for_update()\n"
        "    if not may_write:",
        "    full, may_write = _read_full_config_for_update()\n"
        "    if False:",
    ),
    # ── The surface ─────────────────────────────────────────────────────────
    (
        "the card renders outside MSIX too (macOS, the .exe build)",
        COMPONENTS,
        "    from shared.helpers import is_msix_package\n"
        "    if not is_msix_package():\n        return False",
        "    pass",
    ),
    (
        "package identity is inferred from the executable path again",
        HELPERS,
        "            rc = ctypes.windll.kernel32.GetCurrentPackageFullName(\n"
        "                ctypes.byref(length), None)\n"
        "            packaged = (rc != _APPMODEL_ERROR_NO_PACKAGE)",
        '            packaged = "WindowsApps" in (sys.executable or "")',
    ),
    (
        "the ask is charged on a CLICK, so ignoring the card never counts",
        COMPONENTS,
        "            store_review.note_ask()",
        "            pass",
    ),
    (
        "the Store is opened BEFORE the outcome is recorded",
        COMPONENTS,
        "    store_review.note_rated()\n"
        "    st.session_state['_sr_opened'] = store_review.open_store_review_page()",
        "    st.session_state['_sr_opened'] = store_review.open_store_review_page()\n"
        "    store_review.note_rated()",
    ),
    (
        "the two live states no longer emit the same child count",
        COMPONENTS,
        "            pad_slot_children(1, _STORE_REVIEW_SLOT_CHILDREN)",
        "            pass",
    ),
    # ── The call sites ──────────────────────────────────────────────────────
    (
        "the download screen asks after a run that reported errors",
        APP,
        "                clean_run=(_retriable == 0 and _app_errors == 0\n"
        "                           and success_count > 0),",
        "                clean_run=True,",
    ),
    (
        "the download screen gates on len(errors) instead of the retriable count",
        APP,
        "                clean_run=(_retriable == 0 and _app_errors == 0\n"
        "                           and success_count > 0),",
        "                clean_run=(len(download_errors) == 0),",
    ),
    (
        "the sync screen asks after a run that reported errors",
        SYNC,
        "        clean_run=(_sync_retriable == 0 and synced_count > 0),",
        "        clean_run=True,",
    ),
    (
        "the sync screen gates on len(errors) instead of the retriable count",
        SYNC,
        "        clean_run=(_sync_retriable == 0 and synced_count > 0),",
        "        clean_run=(len(sync_errors) == 0),",
    ),
    (
        "the sync completion screen stops asking at all",
        SYNC,
        "    render_store_review_card(\n"
        "        clean_run=(_sync_retriable == 0 and synced_count > 0),\n"
        "        key_prefix='sync_complete',\n"
        "    )",
        "    pass",
    ),
    (
        "the download completion screen stops asking at all",
        APP,
        "            render_store_review_card(\n"
        "                clean_run=(_retriable == 0 and _app_errors == 0\n"
        "                           and success_count > 0),\n"
        "                key_prefix='dl',\n"
        "            )",
        "            pass",
    ),
    # ── The listing it points at ────────────────────────────────────────────
    (
        "the rating click points at a different Store product",
        STORE,
        'STORE_PRODUCT_ID = "9n1dwwvrq5wc"',
        'STORE_PRODUCT_ID = "9nblggh4xxxx"',
    ),
]

TEST_TARGET = TESTS


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; these files are CRLF on this checkout.

    Matching raw bytes is what makes an anchor honest (a universal-newlines read
    would silently rewrite the file's line endings on restore), so the anchor is
    translated to the file's own newline instead. A multi-line anchor written
    with the wrong one reports a live guard as MISSING - the "brittle test
    anchor reads like a missing guard" trap, one level up.
    """
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in STORE_REVIEW_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale, ambiguous = [], []
    for label, rel, old, new in STORE_REVIEW_MUTANTS:
        nl = _nl_of(snapshot[rel])
        hits = snapshot[rel].count(old.replace("\n", nl))
        if hits == 0:
            stale.append(f"{label!r} in {rel}")
        elif hits > 1:
            # The twin-anchor trap: `.replace(..., 1)` takes whichever twin is
            # defined FIRST, so the pass reports a result under a label that is
            # a lie. It has bitten this repo five times.
            ambiguous.append(f"{label!r} in {rel} ({hits} matches)")
    if stale or ambiguous:
        if stale:
            print("STALE ANCHORS - these mutants could not run at all, so any "
                  "score recorded for them is UNMEASURED, not passing:")
            for s in stale:
                print("  " + s)
        if ambiguous:
            print("AMBIGUOUS ANCHORS - these would mutate whichever match comes "
                  "first, reporting a result under the wrong label:")
            for s in ambiguous:
                print("  " + s)
        return 4

    print(f"baseline: running {len(TESTS)} test file(s)")
    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in STORE_REVIEW_MUTANTS:
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
            try:
                rc = subprocess.run(
                    [sys.executable, "-m", "pytest", *TEST_TARGET, "-q", "-x",
                     "--no-header", "-p", "no:cacheprovider"],
                    cwd=REPO, capture_output=True, timeout=TIMEOUT).returncode
            except subprocess.TimeoutExpired:
                rc = 1  # a mutant that hangs the suite is one the suite noticed
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{label}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(STORE_REVIEW_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
