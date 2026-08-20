"""Mutation pass for the transcription-notice dismissal.

Flips one real behaviour at a time and asserts the tests go RED. A test that
survives its own mutant is testing the shape of the code rather than what it
does.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so (a) HEAD may not be what this pass
started from, and (b) a hard checkout would discard somebody else's uncommitted
edit to a file this pass never mutated. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it has changed underneath -
without restoring anything, because at that point the only thing on disk is
their edit, and writing the snapshot over it is exactly the loss being
prevented.

    python scripts/_mutate_tx_notice.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

COMPONENTS = "shared/components.py"
SYNC_UI = "sync_ui.py"
REVIEW = "ui/sync_review.py"
CSS = "styles/global.css"
SETTINGS = "panopto/settings.py"

TESTS = [
    "tests/test_transcription_notice_dismissal.py",
    "tests/test_settings_coownership.py",
]

#: (label, file, old, new)
TX_NOTICE_MUTANTS = [
    # -- who may collapse -----------------------------------------------------
    ("the review notice becomes collapsible too",
     COMPONENTS,
     'if dismissible and not st.session_state.get("tx_setup_card_open", False):',
     'if not st.session_state.get("tx_setup_card_open", False):'),
    ("an unreadable settings file nags instead of collapsing",
     COMPONENTS,
     "            _collapsed = True\n",
     "            _collapsed = False\n"),
    ("the session re-spawn flag stops beating the stored dismissal",
     COMPONENTS,
     'if dismissible and not st.session_state.get("tx_setup_card_open", False):',
     'if dismissible:'),

    # -- slot shape -----------------------------------------------------------
    ("the collapsed slot stops padding to the card's child count",
     COMPONENTS,
     "            pad_slot_children(1, _TX_NOTICE_SLOT_CHILDREN)\n",
     "            pass\n"),
    ("the slot-children constant drifts from what the card emits",
     COMPONENTS,
     "_TX_NOTICE_SLOT_CHILDREN = 2",
     "_TX_NOTICE_SLOT_CHILDREN = 3"),

    # -- the stylesheet stays static -----------------------------------------
    ("the stylesheet goes back to being emitted inline, per branch",
     COMPONENTS,
     '    _card_key = f"tx_setup_card_{key}"',
     '    st.html("<style>/* per-branch */</style>")\n    _card_key = f"tx_setup_card_{key}"'),

    # -- the toggles stay callbacks ------------------------------------------
    ("the close button stops using on_click",
     COMPONENTS,
     '                    st.button("\\u200b", key=f"tx_setup_close_{key}",\n'
     '                              on_click=_dismiss_tx_setup_notice)',
     '                    if st.button("\\u200b", key=f"tx_setup_close_{key}"):\n'
     '                        _dismiss_tx_setup_notice()\n'
     '                        st.rerun(scope="app")'),
    ("the re-spawn link stops using on_click",
     COMPONENTS,
     ",\n                      on_click=_spawn_tx_setup_card)",
     ")"),
    ("the collapsed link gains a help= tooltip that nags on every pass",
     COMPONENTS,
     "                      on_click=_spawn_tx_setup_card)",
     '                      on_click=_spawn_tx_setup_card, help="Show it again.")'),
    ("the close button gains a help= tooltip that breaks its 32px sizing",
     COMPONENTS,
     '                    st.button("\\u200b", key=f"tx_setup_close_{key}",',
     '                    st.button("\\u200b", key=f"tx_setup_close_{key}", help="Dismiss",'),

    # -- dismissing takes effect immediately ---------------------------------
    ("dismissing leaves the session re-spawn flag set",
     COMPONENTS,
     '    st.session_state.pop("tx_setup_card_open", None)\n',
     "\n"),

    # -- the collapsed state still states the fact ---------------------------
    ("the collapsed link stops naming what is not set up",
     COMPONENTS,
     '            st.button("Transcripts & Subtitles are not set up yet",',
     '            st.button("Details",'),
    ("collapsing reports itself as having rendered nothing",
     COMPONENTS,
     "    st.markdown(\"<div style='margin-bottom:14px;'></div>\", unsafe_allow_html=True)\n"
     "    return True",
     "    st.markdown(\"<div style='margin-bottom:14px;'></div>\", unsafe_allow_html=True)\n"
     "    return not _collapsed"),

    # -- the call sites -------------------------------------------------------
    ("the sync list stops opting in",
     SYNC_UI,
     "            dismissible=True,\n",
     ""),
    ("the sync review opts in",
     REVIEW,
     '        key="sync_review_setup_tx",\n',
     '        key="sync_review_setup_tx",\n        dismissible=True,\n'),

    # -- the CSS --------------------------------------------------------------
    ("the padded slot loses gap: 0 and gains a phantom gap",
     CSS,
     'div[class*="st-key-tx_setup_link_"] {\n    gap: 0 !important;',
     'div[class*="st-key-tx_setup_link_"] {'),
    ("the collapsed link's rules are renamed out from under the markup",
     CSS,
     'div[class*="st-key-tx_setup_relink_"] button {',
     'div[class*="st-key-tx_respawn_"] button {'),

    # -- the persisted flag ---------------------------------------------------
    ("the dismissal defaults to already-dismissed",
     SETTINGS,
     "    return bool(_read_full_config().get(TX_NOTICE_DISMISSED_KEY, False))",
     "    return bool(_read_full_config().get(TX_NOTICE_DISMISSED_KEY, True))"),
    ("the dismissal writer takes its dict from the DEGRADING reader",
     SETTINGS,
     "    full, may_write = _read_full_config_for_update()\n"
     "    if not may_write:\n"
     '        logger.warning("Not saving the transcription-notice dismissal: the "',
     "    full, may_write = _read_full_config(), True\n"
     "    if not may_write:\n"
     '        logger.warning("Not saving the transcription-notice dismissal: the "'),
    ("the atomic writer claims success without writing",
     SETTINGS,
     "    path = _config_path()\n"
     '    tmp = str(path) + ".tmp"\n'
     "    try:\n"
     "        path.parent.mkdir(parents=True, exist_ok=True)\n"
     '        with open(tmp, "w", encoding="utf-8") as f:\n'
     "            json.dump(full, f, indent=2, ensure_ascii=False)",
     "    return True\n"
     "    path = _config_path()\n"
     '    tmp = str(path) + ".tmp"\n'
     "    try:\n"
     "        path.parent.mkdir(parents=True, exist_ok=True)\n"
     '        with open(tmp, "w", encoding="utf-8") as f:\n'
     "            json.dump(full, f, indent=2, ensure_ascii=False)"),
    ("the dismissal is copied into the per-run contract schema",
     SETTINGS,
     '    "layout": "match",\n}',
     '    "layout": "match",\n    "transcription_setup_notice_dismissed": False,\n}'),
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
    files = sorted({m[1] for m in TX_NOTICE_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, new in TX_NOTICE_MUTANTS:
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
    for label, rel, old, new in TX_NOTICE_MUTANTS:
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
            rc = subprocess.run([sys.executable, "-m", "pytest", *TEST_TARGET,
                                 "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True).returncode
        finally:
            _write(rel, snapshot[rel])
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(TX_NOTICE_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
