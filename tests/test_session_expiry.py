"""An expired BROWSER SESSION must be caught exactly like a revoked token.

Measured against real Canvas on 2026-09-12, with no credential at all - this is
the whole reason this file exists:

====================================  =================  =====================
request                               revoked TOKEN      expired SESSION
====================================  =================  =====================
``/api/v1/users/self``                401 JSON           401 JSON
``/courses/<id>/files/<id>/download`` **401**            **302 -> /login**
``/courses/<id>/modules/items/<id>``  302 -> /login      302 -> /login
====================================  =================  =====================

The API is at parity and needs nothing: canvasapi raises ``Unauthorized`` for
both and ``is_auth_error`` already routes it to the reconnect flow. Everything
OUTSIDE the API is not. Follow that 302 - which every HTTP client does by
default - and the chain ends at the institution's identity provider answering
**HTTP 200** with 45,524 bytes of HTML login page. A downloader that trusts a
200 writes that into ``lecture.pdf``; one that notices only the Content-Type
calls it "Canvas returned an error page", which names the wrong culprit and
gives the user nothing to do.

Everything here drives the REAL functions against a REAL local HTTP server that
redirects the way Canvas does. No mocks, no network, no credentials, so it runs
anywhere.
"""
from __future__ import annotations

import asyncio
import http.server
import json
import threading
from pathlib import Path

import pytest

from core.canvas_auth import (CanvasCredential, from_cookies, is_login_redirect,
                              visited_urls)
from core.canvas_logic import CanvasSessionExpired, is_auth_error


# ---------------------------------------------------------------------------
# 1. The predicate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chain,expected", [
    # The measured expired-session chain, in full.
    (["https://cbscanvas.instructure.com/courses/1/files/2/download?download_frd=1",
      "https://cbscanvas.instructure.com/login",
      "https://login.microsoftonline.com/875c414e/saml2"], True),
    # A LEGITIMATE download also redirects, and also ends 200 - onto the content
    # CDN. This is the case a naive "did we get redirected?" check would break.
    (["https://cbscanvas.instructure.com/files/1/download",
      "https://a1736.canvas-user-content.com/x",
      "https://cdn.inst-fs-dub-prod.inscloudgate.net/y"], False),
    # Canvas' other sign-in routes, one per auth provider.
    (["https://x.instructure.com/login/canvas"], True),
    (["https://x.instructure.com/login/saml/3"], True),
    (["https://x.instructure.com/login/cas"], True),
    (["https://x.instructure.com/login/"], True),
    # A file whose NAME starts with login must not read as a sign-in.
    (["https://x.instructure.com/courses/1/files/loginnotes.pdf"], False),
    (["https://x.instructure.com/courses/1/files/2/login_form.docx"], False),
    ([], False),
    ([None], False),
])
def test_a_login_redirect_is_told_apart_from_an_ordinary_one(chain, expected):
    assert is_login_redirect(chain) is expected


def test_the_predicate_ignores_the_HOST_on_purpose():
    """A vanity address (`canvas.cbs.dk`) lands the chain on the canonical host
    (`cbscanvas.instructure.com`), so requiring the host to match the one we
    hold would answer False in exactly the configuration this exists for."""
    assert is_login_redirect(["https://some.other.host.example/login"]) is True


class _Resp:
    def __init__(self, url, history=()):
        self.url = url
        self.history = [_Resp(u) for u in history]


def test_visited_urls_reads_both_clients_the_same_way():
    """`aiohttp` and `requests` both expose .history and .url, so one reader
    serves both and the two can never disagree about what the chain was."""
    r = _Resp("https://end/", ["https://a/", "https://b/"])
    assert visited_urls(r) == ["https://a/", "https://b/", "https://end/"]
    assert visited_urls(object()) == []


def test_an_expired_session_is_an_auth_error_like_any_other():
    """A distinct type rather than a crafted message: the alternative is every
    raiser remembering to spell a word `is_auth_error` happens to match."""
    assert is_auth_error(CanvasSessionExpired("nope")) is True
    assert CanvasSessionExpired.status_code == 401


# ---------------------------------------------------------------------------
# 2. The download engine, against a server that expires like Canvas
# ---------------------------------------------------------------------------

class _ExpiringCanvas(http.server.BaseHTTPRequestHandler):
    """Canvas, gated on the session cookie exactly as the real thing is.

    A LIVE session gets the page. Anything else - a dead cookie or none at all -
    302s to /login, which goes on to the identity provider, which answers 200
    with a login page. That is the measured production chain, and gating on the
    cookie rather than on the path is what lets the same server serve both the
    failing case and its control.
    """

    def log_message(self, *a):
        pass

    def _live(self) -> bool:
        return "canvas_session=LIVE" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path.startswith("/login"):
            self._send(302, "text/html", b"", location="/idp/saml2")
        elif self.path.startswith("/idp"):
            # The identity provider. 200, HTML, and big - exactly what the real
            # chain ends on.
            self._send(200, "text/html; charset=utf-8", b"<html>Sign in</html>" * 200)
        elif self.path.startswith("/good"):
            self._send(200, "application/pdf", b"%PDF-1.4 real bytes")
        elif self._live():
            # An ordinary signed-in Canvas page with no Panopto form on it.
            self._send(200, "text/html; charset=utf-8", b"<html><body>Course</body></html>")
        else:
            self._send(302, "text/html", b"", location="/login")

    def _send(self, code, ctype, body, location=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


@pytest.fixture
def expiring():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _ExpiringCanvas)
    srv.base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _fetch(url):
    """What the engine sees: a followed redirect chain, like aiohttp's default."""
    async def go():
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                return r.status, r.headers.get("Content-Type", ""), visited_urls(r), await r.read()
    return asyncio.run(go())


def test_an_expired_session_really_does_serve_a_200_html_login_page(expiring):
    """The premise, driven rather than asserted. If this ever stops being true
    the guard below is measuring nothing."""
    status, ctype, chain, body = _fetch(f"{expiring.base}/courses/1/files/2/download")
    assert status == 200, "the chain no longer ends 200 - re-check the guard"
    assert "text/html" in ctype
    assert b"Sign in" in body
    assert is_login_redirect(chain), chain


def test_a_real_file_is_not_mistaken_for_a_sign_in(expiring):
    """The control. A guard that cannot say no is not a guard."""
    status, ctype, chain, body = _fetch(f"{expiring.base}/good/file.pdf")
    assert status == 200 and body.startswith(b"%PDF")
    assert is_login_redirect(chain) is False


# ---------------------------------------------------------------------------
# 3. The engine's own guard, by source - the holes that were there
# ---------------------------------------------------------------------------

_ENGINE = Path(__file__).resolve().parents[1] / "core" / "canvas_logic.py"


def _download_body() -> str:
    import ast
    tree = ast.parse(_ENGINE.read_text(encoding="utf-8"))
    src = _ENGINE.read_text(encoding="utf-8").splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "_download_file_async":
            return "\n".join(src[node.lineno - 1:node.end_lineno])
    raise AssertionError("_download_file_async is gone - re-anchor this test")


def test_the_download_checks_for_a_sign_in_redirect():
    body = _download_body()
    assert "is_login_redirect(visited_urls(response))" in body, (
        "the download no longer notices that Canvas asked for a sign-in, so an "
        "expired session reports as a Content-Type problem or writes a login "
        "page to disk")
    assert "CanvasSessionExpired" in body


def test_the_content_type_guard_no_longer_depends_on_a_reported_SIZE():
    """Canvas reports no size for some files, and `file_size_bytes > 0` meant
    the guard was SKIPPED for exactly those - so the error page was written to
    disk under the real filename."""
    body = _download_body()
    assert "is_html_response and not expects_html and file_size_bytes > 0" not in body, (
        "the Content-Type guard is gated on a reported size again, so a file "
        "Canvas gives no size for is unprotected")
    assert "if is_html_response and not expects_html:" in body


def test_an_expired_session_is_not_retried():
    """The credential cannot change between attempts, so retrying spends the
    whole backoff schedule to fail three more times. Same reasoning as the TLS
    handler beside it, which says so in its own comment.

    Asserted through the AST rather than over a slice of source: a character
    window is exactly the brittle anchor this repo has been bitten by - a
    comment explaining the fix pushes the code out of the window and the guard
    then passes against a regression.
    """
    import ast
    tree = ast.parse(_ENGINE.read_text(encoding="utf-8"))
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
              and f.name == "_download_file_async")

    # Handlers of the SAME try, not every handler in the function: the download
    # nests try blocks (the .part write, the manifest record) whose own
    # `except Exception` clauses are not siblings of this one and cannot shadow
    # it. Comparing across all of them reported a false ordering failure.
    tries = [t for t in ast.walk(fn) if isinstance(t, ast.Try)
             and any(h.type is not None
                     and ast.unparse(h.type) == "CanvasSessionExpired"
                     for h in t.handlers)]
    assert len(tries) == 1, (
        "the download no longer has exactly one handler for an expired session")
    handlers = tries[0].handlers
    names = [ast.unparse(h.type) if h.type else "" for h in handlers]

    mine = handlers[names.index("CanvasSessionExpired")]
    # It must END the attempt, not fall through to the retry loop.
    assert isinstance(mine.body[-1], ast.Return), (
        "the session-expiry handler does not return, so an expired session is "
        "retried on a credential that cannot have changed")
    assert not [n for n in ast.walk(mine) if isinstance(n, ast.Continue)]

    # And it must precede the broader clauses, or they catch it first.
    cert = "aiohttp.ClientConnectorCertificateError"
    if cert in names:
        assert names.index("CanvasSessionExpired") < names.index(cert)
    for broad in ("Exception", "ValueError"):
        if broad in names:
            assert names.index("CanvasSessionExpired") < names.index(broad)


def test_panopto_reports_an_expired_session_instead_of_no_recordings(expiring):
    """The launch chain starts at a Canvas module-item page, which 302s to
    /login for an expired session. The form-chain walker would then try to
    submit the IdP's sign-in form, exhaust its steps and report no delivery id -
    i.e. "this course has no recordings", which is the wrong answer to "you are
    signed out" and the only one a user would ever see.

    DRIVEN, not grepped. The first version of this asserted that the source
    contained `is_login_redirect` and `CanvasSessionExpired`, which a mutant
    replacing the condition with `if False:` satisfies perfectly - and the
    mutation pass duly reported it SURVIVED.
    """
    from panopto.auth import lti_launch

    cred = from_cookies({"canvas_session": "DEAD"}, expiring.base, user_agent="UA")
    launch = (f"{expiring.base}/api/v1/courses/43660/external_tools/"
              f"sessionless_launch?launch_type=module_item&module_item_id=1087340&id=9")

    with pytest.raises(CanvasSessionExpired):
        lti_launch(launch, cred, timeout=10)


def test_a_panopto_launch_that_is_NOT_a_sign_in_still_runs(expiring):
    """The control. This chain does not pass through /login, so the guard must
    stay out of the way and let the ordinary handshake report its own failure."""
    from panopto.auth import lti_launch

    cred = from_cookies({"canvas_session": "LIVE"}, expiring.base, user_agent="UA")
    launch = (f"{expiring.base}/api/v1/courses/43660/external_tools/"
              f"sessionless_launch?id=9&url={expiring.base}/good/tool")

    # The property under test is that the guard STAYS OUT OF THE WAY: the
    # handshake runs and reports its own outcome. What that outcome is on a page
    # with no Panopto form is the handshake's business, not this test's.
    result = lti_launch(launch, cred, timeout=10)
    assert len(result) == 5
    assert result[2] is None, "there is no delivery id behind an ordinary page"


# ---------------------------------------------------------------------------
# 4. How long a sign-in lasts: the rolling refresh
# ---------------------------------------------------------------------------

class _RollingCanvas(http.server.BaseHTTPRequestHandler):
    """Canvas as configured: `expire_after` is set, so a non-empty session is
    re-issued on every response with a fresh day on it."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"id": 1, "name": "Birk"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", "canvas_session=ROLLED; path=/; httponly")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def rolling():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _RollingCanvas)
    srv.base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_rolled_session_cookie_is_picked_up(rolling):
    """Canvas' session is ONE DAY (`expire_after: 86400`), rolled forward on
    every response. The live jar absorbs that and is then thrown away, so
    without this the stored copy stays frozen at whatever the user signed in
    with and expires a day later however much they use the app."""
    from core.canvas_logic import CanvasManager

    cred = from_cookies({"canvas_session": "OLD"}, rolling.base, user_agent="UA")
    cm = CanvasManager(cred, rolling.base)
    ok, _msg = cm.validate_token()
    assert ok

    renewed = cm.refreshed_credential()
    assert renewed is not None, "the rolled session cookie was not noticed"
    assert renewed.session_cookie() == "ROLLED"
    # Everything else is carried over untouched.
    assert renewed.host == cred.host and renewed.user_agent == cred.user_agent
    assert renewed.is_browser


def test_an_unchanged_cookie_answers_None_so_nothing_is_written(rolling):
    """Costs nothing if a Canvas ever stops rolling: no change, no write."""
    from core.canvas_logic import CanvasManager

    cred = from_cookies({"canvas_session": "ROLLED"}, rolling.base)
    cm = CanvasManager(cred, rolling.base)
    cm.validate_token()
    assert cm.refreshed_credential() is None


def test_token_mode_never_refreshes_anything(rolling):
    from core.canvas_logic import CanvasManager
    cm = CanvasManager("a-token", rolling.base)
    cm.validate_token()
    assert cm.refreshed_credential() is None


def test_a_manager_with_no_live_jar_does_not_raise():
    """Several tests build a manager with __new__, and the Panopto helpers are
    handed stand-ins carrying only api_key/api_url."""
    from core.canvas_logic import CanvasManager
    cm = CanvasManager.__new__(CanvasManager)
    assert cm.refreshed_credential() is None


def test_with_cookies_does_not_mutate_the_original():
    """A credential is read from download workers, the sync executor and the
    Panopto runner at once; a value that cannot change under them needs no
    lock."""
    cred = from_cookies({"canvas_session": "A"}, "https://x.instructure.com")
    other = cred.with_cookies({"canvas_session": "B"})
    assert cred.session_cookie() == "A"
    assert other.session_cookie() == "B"
    assert isinstance(other, CanvasCredential) and other.is_browser


def test_the_restore_path_persists_a_refreshed_session():
    """One function every restored credential passes through, so the token path
    and all three browser paths get this from one place."""
    import ast
    src = (Path(__file__).resolve().parents[1] / "ui" / "auth.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, ast.FunctionDef) and f.name == "_adopt_restored_credential")
    body = "\n".join(src.splitlines()[fn.lineno - 1:fn.end_lineno])
    assert "refreshed_credential()" in body
    assert "store_browser_credential" in body
