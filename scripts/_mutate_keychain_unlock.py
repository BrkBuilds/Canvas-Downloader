"""Mutation pass for the macOS Keychain unlock.

Flips one real behaviour at a time and asserts the tests go RED. A test that
survives its own mutant is testing the shape of the code rather than what it
does - and three of the mutants here exist because the first draft of the tests
did exactly that.

Restore is from an in-memory SNAPSHOT, never ``git checkout``: this repo is
routinely worked by two sessions at once, so (a) HEAD may not be what this pass
started from, and (b) a hard checkout would discard somebody else's uncommitted
edit to a file this pass never mutated. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it has changed underneath -
without restoring anything, because at that point the only thing on disk is
their edit, and writing the snapshot over it is exactly the loss being
prevented.

    python scripts/_mutate_keychain_unlock.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

AUTH = "ui/auth.py"
APP = "app.py"

TESTS = ["tests/test_keychain_unlock.py", "tests/test_startup.py"]
TEST_TARGET = TESTS

#: (label, file, old, new)
KEYCHAIN_UNLOCK_MUTANTS = [
    # -- the block itself, which is the whole point ---------------------------
    ("init goes back to the read that can PROMPT (the original defect)",
     AUTH,
     "                        loaded_token, _needs_prompt = keyring_get_without_prompting(\n"
     "                            KEYRING_SERVICE, keyring_user)",
     "                        loaded_token, _needs_prompt = (\n"
     "                            _safe_keyring_get(KEYRING_SERVICE, keyring_user), False)"),
    ("the probe stops suppressing keychain UI, so it can prompt again",
     AUTH,
     "        if not _set_keychain_ui_allowed(False):",
     "        if False:"),
    ("keychain UI is left switched OFF for the rest of the process",
     AUTH,
     "        finally:\n            _set_keychain_ui_allowed(True)\n",
     "        finally:\n            pass\n"),

    # -- classification -------------------------------------------------------
    ("a 'would prompt' status is misread as an ordinary failure",
     AUTH,
     "            if any(code in text for code in _KEYCHAIN_PROMPT_STATUSES):\n"
     "                logger.info(\"Saved sign-in needs a Keychain prompt \"\n"
     "                            \"(the app signature changed since it was saved).\")\n"
     "                return (None, True)",
     "            if False:\n"
     "                return (None, True)"),
    ("errSecInteractionNotAllowed drops out of the prompt statuses",
     AUTH,
     "_KEYCHAIN_PROMPT_STATUSES = ('-25293', '-25308')",
     "_KEYCHAIN_PROMPT_STATUSES = ('-25293',)"),
    ("a missing item is reported as needing a prompt",
     AUTH,
     "            return (_run_keyring_op(keyring.get_password, service, username,\n"
     "                                    timeout=_KEYRING_PROBE_TIMEOUT), False)",
     "            return (_run_keyring_op(keyring.get_password, service, username,\n"
     "                                    timeout=_KEYRING_PROBE_TIMEOUT), True)"),
    ("an unsuppressable keychain is gambled on instead of deferred",
     AUTH,
     "            # perform the real read off the script thread.\n            return (None, True)",
     "            # perform the real read off the script thread.\n            return (None, False)"),
    ("the probe WAITS on an unlock already in flight (re-blocking init)",
     AUTH,
     "    if not _keychain_ui_lock.acquire(blocking=False):\n        return (None, True)",
     "    _keychain_ui_lock.acquire()\n    if False:\n        return (None, True)"),

    # -- Windows must not change ---------------------------------------------
    ("the non-darwin path stops being the plain watchdogged read",
     AUTH,
     "    if sys.platform != 'darwin':\n        return (_safe_keyring_get(service, username), False)",
     "    if sys.platform != 'darwin':\n        return (None, True)"),

    # -- single flight --------------------------------------------------------
    ("the poll can stack up a new prompt every second",
     AUTH,
     "        if _kc_unlock['state'] == 'running' and _kc_unlock['key'] == key:\n            return",
     "        if False:\n            return"),
    ("the unlocked token is CONSUMED, so a second session gets a bare login page",
     AUTH,
     "        return _kc_unlock['token'] if _kc_unlock['state'] == 'ok' else ''",
     "        t = _kc_unlock['token'] if _kc_unlock['state'] == 'ok' else ''; "
     "_kc_unlock['token'] = ''; return t"),
    ("a denied prompt is recorded as a generic error",
     AUTH,
     "                if any(code in text for code in _KEYCHAIN_DENIED_STATUSES):\n"
     "                    state, token, err = 'denied', '', ''",
     "                if False:\n"
     "                    state, token, err = 'denied', '', ''"),

    # -- adoption -------------------------------------------------------------
    ("adoption gives up while the prompt is still on screen",
     AUTH,
     "    if status == 'running' or status == 'idle':\n        return False",
     "    if False:\n        return False"),
    ("a denial never stops the wait, so the notice spins for ever",
     AUTH,
     "        st.session_state['keychain_unlock_pending'] = False\n"
     "        st.session_state['keychain_unlock_failed'] = status\n"
     "        return False",
     "        return False"),
    ("the unlock path skips validation and signs in blind",
     AUTH,
     "    try:\n        _adopt_restored_token(token)",
     "    try:\n        st.session_state['api_token'] = token"),
    ("app.py stops adopting a resolved unlock at all",
     APP,
     "from ui.auth import adopt_pending_keychain_unlock\nadopt_pending_keychain_unlock()",
     "from ui.auth import adopt_pending_keychain_unlock"),

    # -- the copy, which is a MEASURED instruction, not decoration -------------
    ("the copy stops naming Always Allow",
     AUTH,
     "\"<li>Click <b>Always Allow</b> - one click and macOS stops asking. Plain \"\n"
     "        \"<i>Allow</i> puts up a second dialog straight away, and asks again \"\n"
     "        \"every time you open the app.</li>\"",
     "\"<li>Click <b>Allow</b> to continue.</li>\""),
    ("the reassurance is dropped, leaving a bare instruction",
     AUTH,
     "\"saved. <b>You have not been logged out and nothing is lost.</b></div>\"",
     "\"saved.</div>\""),
    ("the way out (Deny + paste a token) is no longer stated",
     AUTH,
     "\"<li>Would rather not? Click <b>Deny</b> and paste a Canvas token below \"\n"
     "        \"instead - everything still works.</li>\"",
     "\"\""),

    # -- rendering contract ---------------------------------------------------
    ("the notice renders even when there is nothing to say",
     AUTH,
     "    if not pending and not failed:\n        return",
     "    if False:\n        return"),
    ("the prompt is raised BEFORE the page is emitted",
     AUTH,
     "    if st.session_state.get('keychain_unlock_pending'):\n"
     "        begin_keychain_unlock(KEYRING_SERVICE,\n"
     "                              st.session_state.get('api_url') or 'default')",
     "    pass"),
    ("the slot stops zeroing its gap",
     AUTH,
     'div[class*="st-key-kc_unlock_slot"] { gap: 0 !important; }',
     'div[class*="st-key-kc_unlock_slot"] { }'),
    ("logout stops resetting a stale unlock verdict",
     AUTH,
     "                reset_keychain_unlock()\n"
     "                st.session_state.pop('keychain_unlock_pending', None)",
     "                st.session_state.pop('keychain_unlock_pending', None)"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; translate to the file's own newline.

    Matching raw bytes is what makes an anchor honest (a universal-newlines read
    would silently rewrite the file's line endings on restore). A multi-line
    anchor written with the wrong one reports a live guard as MISSING - the
    "brittle test anchor reads like a missing guard" trap, one level up.
    """
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in KEYCHAIN_UNLOCK_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, new in KEYCHAIN_UNLOCK_MUTANTS:
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
    for label, rel, old, new in KEYCHAIN_UNLOCK_MUTANTS:
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
            # TIMEOUT IS LOAD-BEARING, not tidiness. Some mutants here make the
            # code BLOCK (the probe taking the lock blocking deadlocks against a
            # test that holds it). Without a bound, pytest never returns, the
            # pass is eventually killed from outside, and the `finally` below
            # never runs - which leaves the MUTANT on disk, indistinguishable
            # from real code. That happened on this very set while it was being
            # written. A timeout counts as CAUGHT: a mutant that hangs the suite
            # is a mutant the suite noticed.
            rc = subprocess.run([sys.executable, "-m", "pytest", *TEST_TARGET,
                                 "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True, timeout=180).returncode
        except subprocess.TimeoutExpired:
            rc = -1
            print(f"  (timed out - counted as caught: {label})")
        finally:
            _write(rel, snapshot[rel])
        assert _read(rel) == snapshot[rel], f"{label}: RESTORE FAILED - fix by hand"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(KEYCHAIN_UNLOCK_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
