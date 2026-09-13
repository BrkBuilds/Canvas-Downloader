"""Mutation pass for the access-token upgrade and its renewal.

`tests/test_token_mint.py` guards properties that fail in three different
silent ways, which is why the pass exists at all:

* **A bypassed administrator setting.** `AccessToken`'s policy skips the
  account restrictions for a Bearer request, so minting with a token would
  appear to work at an institution that deliberately switched self-service
  tokens off. Nothing would report it.
* **A user logged out of their own running app.** A renewal that regenerates
  replaces the token value the running session, every download thread, the
  sync executor and the Panopto runner are holding - mid-download.
* **A user who never gets the long-lived credential at all**, because a
  transient network failure was recorded as a permanent institutional no, or
  because the upgrade silently ate the sign-in it was supposed to improve.

Restore is from an in-memory SNAPSHOT, never `git checkout`: this repo is
routinely worked by two sessions at once. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath,
restoring nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_token_mint.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

MINT = "core/token_mint.py"
UI = "ui/auth.py"
APP = "app.py"

TESTS = ["tests/test_token_mint.py"]

#: (label, file, old, new)
TOKEN_MINT_MUTANTS = [
    # -- 1. the refusal that protects an administrator's setting ------------
    ("a TOKEN is allowed to mint another token, which walks round the account "
     "restrictions Canvas skips for Bearer requests",
     MINT,
     "        if getattr(credential, 'kind', None) != BROWSER or not credential.usable:",
     "        if False:"),

    ("an unusable (signed-out) credential still spends a round trip",
     MINT,
     "        if getattr(credential, 'kind', None) != BROWSER or not credential.usable:",
     "        if getattr(credential, 'kind', None) != BROWSER:"),

    # -- 2. CSRF -------------------------------------------------------------
    ("the CSRF cookie is echoed back still percent-encoded, so Canvas refuses "
     "every mint with a 422 nobody would guess at",
     MINT,
     "            return unquote(raw)",
     "            return raw"),

    ("the CSRF header is never sent at all",
     MINT,
     "        if csrf:\n            headers['X-CSRF-Token'] = csrf",
     "        if False:\n            headers['X-CSRF-Token'] = csrf"),

    ("nothing asks Canvas for a CSRF token, so the mint can only ever work on "
     "the launch the user signed in on",
     MINT,
     "        landing = session.get(urljoin(base + '/', 'profile/settings'),",
     "        landing = session.get(urljoin(base + '/', 'api/v1/users/self'),"),

    # -- 3. what Canvas is asked for ----------------------------------------
    ("the expiry asks for the full 120 days, which Canvas refuses outright on "
     "any machine whose clock is a few minutes ahead of its own",
     MINT,
     "REQUEST_DAYS = 119",
     "REQUEST_DAYS = 120"),

    ("a caller's day count is no longer clamped to Canvas' cap",
     MINT,
     "                            'expires_at': _expiry_iso(min(days, MAXIMUM_DAYS))}},\n"
     "            headers=headers, timeout=TIMEOUT, allow_redirects=True)",
     "                            'expires_at': _expiry_iso(days)}},\n"
     "            headers=headers, timeout=TIMEOUT, allow_redirects=True)"),

    ("the purpose is dropped, which Canvas requires - every mint 400s",
     MINT,
     "            json={'token': {'purpose': purpose,",
     "            json={'token': {'purpose_x': purpose,"),

    # -- 4. telling the refusals apart --------------------------------------
    ("a login redirect is classified by STATUS, so a remembered session that "
     "may not mint is recorded as an institution that forbids tokens - for good",
     MINT,
     "    if _looks_like_login(response):\n"
     "        return MintResult(reason=NEEDS_FRESH_LOGIN, detail=f'HTTP {status}')",
     "    if False:\n"
     "        return MintResult(reason=NEEDS_FRESH_LOGIN, detail=f'HTTP {status}')"),

    ("an unreachable Canvas is reported as a permanent institutional no, so a "
     "dropped wifi connection denies this user a long-lived token for ever",
     MINT,
     "        return MintResult(reason=NETWORK, detail=repr(e))\n"
     "    finally:",
     "        return MintResult(reason=BLOCKED, detail=repr(e))\n"
     "    finally:"),

    ("a CSRF rejection is called permanent",
     MINT,
     'PERMANENT = (BLOCKED, CAPPED)',
     'PERMANENT = (BLOCKED, CAPPED, CSRF_REJECTED, NETWORK)'),

    ("a 200 that created nothing is reported as a mint, so an empty token is "
     "stored and the user is signed out with no way back",
     MINT,
     "    if not token:\n"
     "        # Canvas returns the token value ONLY on creation. No value means it\n"
     "        # did not create one, whatever the status said.\n"
     "        return MintResult(reason=UNEXPECTED,\n"
     "                          detail='Canvas returned no token value')",
     "    if False:\n"
     "        return MintResult(reason=UNEXPECTED,\n"
     "                          detail='Canvas returned no token value')"),

    # -- 5. the renewal, and the running app --------------------------------
    ("the renewal REGENERATES, replacing the token value the running session, "
     "every download thread and the Panopto runner are already holding",
     MINT,
     "            json={'token': {'expires_at': _expiry_iso(min(days, MAXIMUM_DAYS))}},\n"
     "            headers=headers, timeout=TIMEOUT)",
     "            json={'token': {'regenerate': True,\n"
     "                            'expires_at': _expiry_iso(min(days, MAXIMUM_DAYS))}},\n"
     "            headers=headers, timeout=TIMEOUT)"),

    ("an extension Canvas accepted but did not APPLY is reported as renewed, "
     "so it is retried on every launch for the rest of the token's life",
     MINT,
     '    if not due_for_renewal(fresh, granted_days):\n        logger.info("Extended the Canvas access token (id=%s, now expires %s).",\n                    token_id, fresh)\n        return MintResult(token_id=token_id, expires_at=fresh, reason=OK)',
     '    if True:\n        logger.info("Extended the Canvas access token (id=%s, now expires %s).",\n                    token_id, fresh)\n        return MintResult(token_id=token_id, expires_at=fresh, reason=OK)'),

    ("a token with no expiry is reported as a failure, so a non-student's "
     "permanent token is re-extended on every single launch",
     MINT,
     "        logger.info(\"The Canvas access token now reports no expiry.\")\n"
     "        return MintResult(token_id=token_id, expires_at='', reason=OK)",
     "        logger.info(\"The Canvas access token now reports no expiry.\")\n"
     "        return MintResult(reason=UNEXPECTED, detail='no expiry')"),

    ("the renewal window shrinks to nothing, so a user who opens the app every "
     "few weeks reaches the expiry and has to sign in again",
     MINT,
     "RENEW_WITHIN_DAYS = 21",
     "RENEW_WITHIN_DAYS = 0"),

    ("an unreadable expiry is treated as due, so a token that works perfectly "
     "is rewritten on every launch",
     MINT,
     '    left = days_left(expires_at)\n    if left is None:\n        return False\n    return left < renewal_threshold_days(granted_days)',
     '    left = days_left(expires_at)\n    if left is None:\n        return True\n    return left < renewal_threshold_days(granted_days)'),

    # -- 6. the call site ---------------------------------------------------
    ("a minted token that this machine cannot STORE is adopted anyway, "
     "swapping a credential that survives a restart for one that does not",
     UI,
     "    if not store_token(api_url or 'default', result.token):",
     "    if False:"),

    ("the superseded browser session is left on disk beside the token, so an "
     "unrevocable credential outlives the revocable one that replaced it",
     UI,
     "        delete_browser_credential(api_url)",
     "        pass"),

    ("the token id is not recorded, so the token can never renew itself and "
     "the user signs in again in four months",
     UI,
     "            config_data['minted_token_id'] = result.token_id",
     "            pass"),

    ("a transient refusal is remembered as a permanent one",
     UI,
     "        if result.permanent:",
     "        if True:"),

    ("a declined upgrade eats the sign-in instead of falling through, so a "
     "student at a token-restricted school is never saved at all",
     UI,
     "    if _upgrade_to_access_token(credential):\n        return True\n\n"
     "    _persist_browser_login(credential)",
     "    _upgrade_to_access_token(credential)\n    return True\n\n"
     "    _persist_browser_login(credential)"),

    ("the renewal's once-per-process claim is never released when the thread "
     "cannot start, so renewal is dead for the life of the process",
     UI,
     "        with _token_extend_lock:\n            _token_extend_started = False\n"
     "        logger.warning(\"Could not start the access-token renewal thread.\")",
     "        logger.warning(\"Could not start the access-token renewal thread.\")"),

    ("the renewal runs on the SCRIPT thread, freezing the window during init "
     "for as long as Canvas takes",
     UI,
     "        threading.Thread(target=_work, name='canvas-token-extend',\n"
     "                         daemon=True).start()",
     "        _work()"),

    ("the disclosure toast is emitted from the TOP of the run again, which "
     "shifts every stylesheet after it onto its neighbour's host on the one "
     "run that signs the user in",
     UI,
     "    st.session_state['token_upgrade_notice'] = True",
     "    st.toast('made a token')"),

    ("the notice is not one-shot, so it reappears on every single rerun",
     UI,
     "    if not st.session_state.pop('token_upgrade_notice', False):",
     "    if not st.session_state.get('token_upgrade_notice', False):"),

    ("app.py stops emitting the disclosure, so a token is created in the "
     "user's Canvas account and nothing tells them",
     APP,
     "render_pending_token_notice()",
     "pass  # disclosure deliberately not emitted"),

    ("app.py stops calling the renewal, making the whole thing dead code - "
     "which is exactly what refresh_silently was for two passes",
     APP,
     "maybe_extend_minted_token()",
     "pass  # renewal deliberately not called"),
    # -- the granted lifetime differs by INSTITUTION ------------------------
    ("the renewal window stops scaling to the grant, so a school that grants "
     "7 days has the token due the moment it is minted - a request and a "
     "warning on every launch for ever",
     MINT,
     "    left = days_left(expires_at)\n"
     "    if left is None:\n"
     "        return False\n"
     "    return left < renewal_threshold_days(granted_days)",
     "    left = days_left(expires_at)\n"
     "    if left is None:\n"
     "        return False\n"
     "    return left < RENEW_WITHIN_DAYS"),

    ("the fraction becomes the whole lifetime, so every grant is due "
     "immediately whatever its length",
     MINT,
     "RENEW_FRACTION = 1.0 / 3.0",
     "RENEW_FRACTION = 1.0"),

    ("the ceiling stops applying, so a multi-year grant is only renewed in "
     "its last months and a user who opens the app rarely misses the window",
     MINT,
     "    return min(float(RENEW_WITHIN_DAYS), granted_days * RENEW_FRACTION)",
     "    return granted_days * RENEW_FRACTION"),

    ("a capped grant is treated as retriable, so every launch asks an "
     "institution a question it has already answered",
     MINT,
     "PERMANENT = (BLOCKED, CAPPED)",
     "PERMANENT = (BLOCKED,)"),

    ("a capped grant is reported as successfully renewed, so the expiry is "
     "believed to have moved when it has not",
     MINT,
     "    return MintResult(reason=CAPPED, expires_at=fresh,",
     "    return MintResult(reason=OK, expires_at=fresh,"),

    ("the granted lifetime is never recorded, so the renewal window has "
     "nothing to scale to and falls back to a ceiling that is wrong for every "
     "school granting less",
     UI,
     "            config_data['minted_token_days'] = token_mint.days_left(\n"
     "                result.expires_at)",
     "            pass"),

    ("nothing marks the token as one the app created, so the reconnect screen "
     "tells a user who never pasted a token to paste a new one",
     UI,
     "            config_data['token_source'] = 'minted'",
     "            pass"),

    ("the renewal stops passing the grant through, so `extend` judges the new "
     "expiry against the ceiling and calls a good capped grant a failure",
     UI,
     "            result = token_mint.extend(token, api_url, token_id,\n"
     "                                       granted_days=granted)",
     "            result = token_mint.extend(token, api_url, token_id)"),

    ("a capped institution is never remembered, so it is asked again on every "
     "launch for the life of the token",
     UI,
     "                if may_write:\n"
     "                    fresh['minted_token_capped'] = True\n"
     "                    write_config_atomically(fresh)",
     "                if False:\n"
     "                    fresh['minted_token_capped'] = True\n"
     "                    write_config_atomically(fresh)"),

    ("the remembered cap is ignored on the next launch",
     UI,
     "            if config.get('minted_token_capped'):",
     "            if False:"),

]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _write(rel: str, text: str) -> None:
    (REPO / rel).write_text(text, encoding="utf-8")


def _run_tests() -> bool:
    """True when the suite PASSES."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTS, "-q", "-x", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    return r.returncode == 0


def main(argv=None) -> int:
    targets = sorted({m[1] for m in TOKEN_MINT_MUTANTS})
    snapshot = {rel: _read(rel) for rel in targets}

    print("Baseline ...", end=" ", flush=True)
    if not _run_tests():
        print("RED - fix that first.")
        return 2
    print("green")

    caught = 0
    survivors = []
    for label, rel, old, new in TOKEN_MINT_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass "
                  f"(before mutant: {label!r}). Restoring nothing.")
            return 3
        if current.count(old) != 1:
            print(f"  [ANCHOR ] {label}")
            survivors.append(f"ANCHOR ({current.count(old)} hits): {label}")
            continue
        _write(rel, current.replace(old, new, 1))
        try:
            passed = _run_tests()
        finally:
            _write(rel, snapshot[rel])
        if passed:
            print(f"  [SURVIVED] {label}")
            survivors.append(label)
        else:
            print(f"  [CAUGHT ] {label}")
            caught += 1

    total = len(TOKEN_MINT_MUTANTS)
    print(f"\n{caught}/{total} caught")
    for s in survivors:
        print(f"  SURVIVED: {s}")
    return 0 if caught == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
