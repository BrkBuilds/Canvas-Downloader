"""Mutation pass for expired-session detection and the rolling refresh.

`tests/test_session_expiry.py` guards two properties, and BOTH fail silently:

* an expired browser session must be caught the way a revoked token is - if it
  is not, the user's file becomes a 45 KB HTML login page, or every remaining
  file reports a "Content-Type mismatch" that names Canvas as the culprit and
  offers the user nothing to do;
* a rolled session cookie must be carried back to the credential store - if it
  is not, the stored sign-in expires one day after the user signed in however
  much they use the app, and nothing anywhere says why.

Restore is from an in-memory SNAPSHOT, never `git checkout`: this repo is
routinely worked by two sessions at once. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath,
restoring nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_session_expiry.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

AUTHMOD = "core/canvas_auth.py"
LOGIC = "core/canvas_logic.py"
PANAUTH = "panopto/auth.py"
UI = "ui/auth.py"

TESTS = ["tests/test_session_expiry.py"]

#: (label, file, old, new)
SESSION_EXPIRY_MUTANTS = [
    # -- 1. the predicate ----------------------------------------------------
    ("the login-redirect check only looks at the FINAL url, so the chain that "
     "ends on the identity provider's 200 page reads as a successful download",
     AUTHMOD,
     "    for raw in visited_urls or ():",
     "    for raw in list(visited_urls or ())[-1:]:"),

    ("the login path match loses its boundary, so a file called "
     "login_form.docx reads as a sign-in page and a real download is thrown away",
     AUTHMOD,
     "        if path == _LOGIN_PATH_PREFIX or path.startswith(_LOGIN_PATH_PREFIX + '/'):",
     "        if _LOGIN_PATH_PREFIX in path:"),

    ("only the bare /login route counts, so an institution whose chain lands on "
     "/login/saml/3 is never detected",
     AUTHMOD,
     "        if path == _LOGIN_PATH_PREFIX or path.startswith(_LOGIN_PATH_PREFIX + '/'):",
     "        if path == _LOGIN_PATH_PREFIX:"),

    ("visited_urls forgets the redirect history, so only the last hop is ever "
     "examined",
     AUTHMOD,
     "        out.extend(str(h.url) for h in (getattr(response, 'history', None) or ()))",
     "        pass"),

    # -- 2. the download engine ---------------------------------------------
    ("the download stops noticing that Canvas asked for a sign-in, so an "
     "expired session writes the identity provider's login page to disk",
     LOGIC,
     "                                if is_login_redirect(visited_urls(response)):",
     "                                if False:"),

    ("the Content-Type guard is gated on a reported size again, so a file "
     "Canvas gives no size for is written as an HTML error page",
     LOGIC,
     "                                if is_html_response and not expects_html:",
     "                                if is_html_response and not expects_html and file_size_bytes > 0:"),

    ("an expired session is retried on a credential that cannot have changed, "
     "spending the whole backoff schedule to fail three more times",
     LOGIC,
     "                except CanvasSessionExpired as e:",
     "                except CanvasSessionExpired as _unused_e:\n"
     "                    raise ValueError('RATE_LIMIT:1')\n"
     "                except CanvasSessionExpired as e:"),

    ("CanvasSessionExpired stops carrying a 401, so is_auth_error no longer "
     "recognises it and the user is never routed to reconnect",
     LOGIC,
     "    status_code = 401",
     "    status_code = 599"),

    # -- 3. Panopto ----------------------------------------------------------
    ("the Panopto launch stops checking, so a signed-out user is told the "
     "course has no recordings",
     PANAUTH,
     "    if _is_login_redirect(_visited_urls(r)):",
     "    if False:"),

    # -- 4. the rolling refresh ---------------------------------------------
    ("the refreshed session cookie is never noticed, so the stored sign-in "
     "expires one day after login however much the app is used",
     LOGIC,
     "            if value and value != fresh.get(name):",
     "            if False:"),

    ("a refresh is reported even when nothing changed, so every launch rewrites "
     "the credential store for no reason",
     LOGIC,
     "        return cred.with_cookies(fresh) if changed else None",
     "        return cred.with_cookies(fresh)"),

    ("the refresh leaks into token mode, where there is no session to roll",
     LOGIC,
     "        if not isinstance(cred, CanvasCredential) or not cred.is_browser:",
     "        if not isinstance(cred, CanvasCredential):"),

    ("with_cookies mutates the credential other threads are reading instead of "
     "replacing it",
     AUTHMOD,
     "        return CanvasCredential(\n"
     "            kind=self.kind, token=self.token,\n"
     "            cookies={str(k): str(v) for k, v in (cookies or {}).items()},\n"
     "            user_agent=self.user_agent, host=self.host,\n"
     "        )",
     "        object.__setattr__(self, 'cookies',\n"
     "                           {str(k): str(v) for k, v in (cookies or {}).items()})\n"
     "        return self"),

    ("the restore path stops writing the refreshed session down, so it is "
     "re-learned and thrown away on every launch",
     UI,
     "                store_browser_credential(st.session_state.get('api_url', ''), _renewed)",
     "                pass"),
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
        cwd=REPO, capture_output=True, text=True,
    )
    return r.returncode == 0


def main(argv=None) -> int:
    targets = sorted({m[1] for m in SESSION_EXPIRY_MUTANTS})
    snapshot = {rel: _read(rel) for rel in targets}

    print("Baseline ...", end=" ", flush=True)
    if not _run_tests():
        print("RED - fix that first.")
        return 2
    print("green")

    caught = 0
    survivors = []
    for label, rel, old, new in SESSION_EXPIRY_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass "
                  f"(before mutant: {label!r}). Restoring nothing.")
            return 3
        if current.count(old) != 1:
            print(f"  [ANCHOR ] {label}")
            survivors.append(f"ANCHOR: {label}")
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

    total = len(SESSION_EXPIRY_MUTANTS)
    print(f"\n{caught}/{total} caught")
    for s in survivors:
        print(f"  SURVIVED: {s}")
    return 0 if caught == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
