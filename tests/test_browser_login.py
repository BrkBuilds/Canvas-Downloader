"""Signing in to Canvas with a browser session instead of an access token.

Three things are being protected here, in descending order of what it costs to
get them wrong:

1. **The cookie never leaves the Canvas host.** A Canvas session cookie is a
   complete login for the user's account, and Canvas file URLs redirect onto a
   content CDN (`*.canvas-user-content.com`, inst-fs). A jar without a domain
   is sent to every host a session touches, so this is a real credential leak
   one missing argument away, and nothing else in the app would notice.

2. **Browser mode sends NO Authorization header.** Canvas runs
   `load_pseudonym_from_access_token` BEFORE it looks at the session, and a
   token it cannot accept - an empty one included - raises there and answers
   401. So a stray bearer alongside a perfectly good cookie does not merely
   look untidy, it breaks the login completely, and it breaks it in a way that
   reads as "your session expired".

3. **The two login kinds stay interchangeable.** The whole design is that
   nothing below the auth layer knows which one is in play, which is only true
   for as long as every site asks the credential rather than formatting a
   bearer itself. The censuses below fail on a NEW unclassified site rather
   than checking that today's sites are fixed.

The HTTP tests drive a real local server rather than a mock, following
`tests/test_canvas_metadata_retry.py`: no Canvas, no network, no credentials,
so they run everywhere.
"""

from __future__ import annotations

import ast
import asyncio
import types
import http.server
import json
import re
import sys
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

import pytest

from core.canvas_auth import (
    BROWSER, TOKEN, CanvasCredential, canvas_host, coerce, credential_of,
    from_cookies, from_token,
)

_ROOT = Path(__file__).resolve().parent.parent
_LOGIC_SRC = (_ROOT / "core" / "canvas_logic.py").read_text(encoding="utf-8")
_AUTH_SRC = (_ROOT / "ui" / "auth.py").read_text(encoding="utf-8")
_START_SRC = (_ROOT / "start.py").read_text(encoding="utf-8")
_SYNC_EXEC_SRC = (_ROOT / "sync" / "execution.py").read_text(encoding="utf-8")

CANVAS = "https://cbscanvas.instructure.com"
CDN = "https://abc123.canvas-user-content.com/files/1/x.pdf"


def _browser_cred(**kw) -> CanvasCredential:
    return from_cookies(
        kw.pop("cookies", {"canvas_session": "SESSION-SECRET",
                           "_csrf_token": "csrf", "log_session_id": "log"}),
        kw.pop("api_url", CANVAS),
        user_agent=kw.pop("user_agent", "Mozilla/5.0 (WebView2) Edg/141.0"),
    )


# ---------------------------------------------------------------------------
# 1. The cookie must not leave the Canvas host
# ---------------------------------------------------------------------------

def test_the_aiohttp_jar_sends_cookies_to_canvas():
    async def go():
        from yarl import URL
        jar = _browser_cred().aiohttp_cookie_jar()
        return dict(jar.filter_cookies(URL(f"{CANVAS}/api/v1/users/self")))

    sent = asyncio.run(go())
    assert "canvas_session" in sent, sent


def test_the_aiohttp_jar_sends_NOTHING_to_the_content_cdn():
    """The leak this design exists to prevent.

    Canvas answers a file request with a redirect onto a CDN it does not own.
    A cookie with no domain rides along, handing a third-party host a complete
    Canvas login - silently, on every file of every download.
    """
    async def go():
        from yarl import URL
        jar = _browser_cred().aiohttp_cookie_jar()
        return dict(jar.filter_cookies(URL(CDN)))

    assert asyncio.run(go()) == {}


def test_the_requests_jar_is_domain_scoped():
    jar = _browser_cred().requests_cookie_jar()
    assert {c.domain for c in jar} == {"cbscanvas.instructure.com"}


def test_a_requests_session_does_not_carry_the_cookie_off_host():
    """The `requests` half of the same boundary, measured through requests'
    own cookie policy rather than by reading the domain back."""
    import requests
    session = requests.Session()
    _browser_cred().apply_to_requests_session(session)

    on_host = requests.Request("GET", f"{CANVAS}/api/v1/users/self")
    off_host = requests.Request("GET", CDN)
    assert "canvas_session" in (session.prepare_request(on_host).headers
                                .get("Cookie") or "")
    # NOTHING, not merely "not the session cookie". The harvest keeps every
    # cookie the Canvas host set - a WAF clearance cookie among them - so the
    # boundary is about the whole jar, and naming one cookie here would pass
    # while three others leaked. `_browser_cred()` carries three by default.
    assert len(_browser_cred().cookies) > 1, "this test needs a multi-cookie jar"
    assert (session.prepare_request(off_host).headers.get("Cookie") or "") == ""


def test_a_credential_never_prints_its_secret():
    """Tracebacks reach the debug log and the health record."""
    text = repr(_browser_cred()) + repr(from_token("TOKEN-SECRET"))
    assert "SESSION-SECRET" not in text
    assert "TOKEN-SECRET" not in text


# ---------------------------------------------------------------------------
# 2. Browser mode sends no Authorization header
# ---------------------------------------------------------------------------

def test_browser_mode_sends_no_authorization_header():
    headers = _browser_cred().auth_headers()
    assert "Authorization" not in headers, (
        "Canvas rejects a request whose bearer it cannot accept BEFORE it "
        "looks at the session cookie, so any Authorization header here turns "
        "a working sign-in into a 401.")


def test_browser_mode_still_sends_the_web_view_user_agent():
    """The session keeps looking like the client that created it - a WAF reads
    a client that changes mid-session as suspicious."""
    assert _browser_cred().auth_headers()["User-Agent"].startswith("Mozilla/5.0")


def test_token_mode_is_unchanged():
    headers = from_token("abc123").auth_headers()
    assert headers["Authorization"] == "Bearer abc123"
    assert from_token("abc123").scoped_cookies() == {}
    assert from_token("abc123").aiohttp_cookie_jar() is None


# ---------------------------------------------------------------------------
# 3. What counts as a usable credential
# ---------------------------------------------------------------------------

def test_cookies_without_a_session_cookie_are_not_a_login():
    """A web view sitting on the identity provider holds plenty of cookies and
    none of them sign the user in to Canvas."""
    assert not from_cookies({"__cf_bm": "x", "AWSALB": "y"}, CANVAS).usable


@pytest.mark.parametrize("name", ["canvas_session", "_normandy_session"])
def test_both_session_cookie_names_are_accepted(name):
    """`canvas_session` is what Instructure's production estate sets;
    `_normandy_session` is the open-source default a self-hosted Canvas keeps."""
    assert from_cookies({name: "v"}, CANVAS).usable


def test_a_credential_with_no_host_is_not_usable():
    """Without a host there is nothing to scope the cookies to, so they would
    either go nowhere or - far worse - go everywhere."""
    assert not from_cookies({"canvas_session": "v"}, "").usable


def test_storable_round_trip():
    """A stored credential comes back usable, and comes back IDENTICAL once the
    storage trim has been applied - so restoring it twice cannot drift."""
    cred = _browser_cred(cookies={"canvas_session": "SESSION-SECRET"})
    assert CanvasCredential.from_storable(cred.to_storable()) == cred

    # With extras present the round trip is lossy BY DESIGN (see below), and
    # what survives is a working credential, not a broken one.
    restored = CanvasCredential.from_storable(_browser_cred().to_storable())
    assert restored.usable
    assert CanvasCredential.from_storable(restored.to_storable()) == restored


def test_what_is_stored_is_the_session_cookie_and_nothing_else():
    """The at-rest copy is trimmed; the LIVE credential is not.

    Windows Credential Manager refuses a secret over 2,560 bytes, and a full
    real CBS jar serialises to 3,260 - measured through the app's own writer,
    `CredWrite` -> error 1783, the whole credential falling through to the
    DPAPI file beside it. `canvas_session` alone authenticates, so that is what
    is kept. The trim belongs to STORAGE: applying it at harvest time also took
    the WAF clearance cookie away from the live session, which is the one place
    it can be load-bearing.
    """
    cred = _browser_cred(cookies={
        "canvas_session": "S" * 762, "cf_clearance": "x" * 426,
        "_csrf_token": "y" * 102, "log_session_id": "z" * 32,
    })
    stored = cred.to_storable()
    assert set(stored['cookies']) == {"canvas_session"}, stored['cookies'].keys()
    # The live value is untouched by asking it what to store.
    assert set(cred.cookies) == {"canvas_session", "cf_clearance",
                                 "_csrf_token", "log_session_id"}
    # CredWrite counts UTF-16 bytes, which is why this is doubled.
    assert len(json.dumps(stored)) * 2 < 2560, (
        "the stored credential no longer fits Windows Credential Manager")


@pytest.mark.parametrize("junk", ["garbage", None, 42, {"kind": "wat"},
                                  {"kind": "browser", "cookies": "nope"}])
def test_a_damaged_store_reads_as_signed_out_and_never_raises(junk):
    """This runs on the startup path, before anything has rendered. An
    exception here is a blank window, so a store that has been corrupted,
    hand-edited or written by a newer version must degrade, not explode."""
    assert CanvasCredential.from_storable(junk).usable is False


def test_coerce_accepts_the_three_shapes_the_app_carries():
    assert coerce("tok").kind == TOKEN
    assert coerce(None).usable is False
    assert coerce(_browser_cred()).kind == BROWSER


def test_coerce_refuses_anything_else_rather_than_guessing():
    """Stringifying an unexpected object would send a garbage bearer to Canvas
    and report it as a revoked token."""
    with pytest.raises(TypeError):
        coerce(12345)


def test_coerce_learns_a_host_when_the_credential_has_none():
    cred = CanvasCredential(kind=BROWSER, cookies={"canvas_session": "v"})
    assert coerce(cred, CANVAS).host == "cbscanvas.instructure.com"


@pytest.mark.parametrize("raw,expected", [
    ("https://cbscanvas.instructure.com", "cbscanvas.instructure.com"),
    ("cbscanvas.instructure.com/", "cbscanvas.instructure.com"),
    ("HTTPS://CBSCanvas.Instructure.COM/api", "cbscanvas.instructure.com"),
    ("", ""),
])
def test_canvas_host_reads_a_host_or_nothing(raw, expected):
    assert canvas_host(raw) == expected


def test_credential_of_prefers_auth_and_falls_back_to_the_token():
    class _Real:
        auth = _browser_cred()
        api_key = ""
        api_url = CANVAS

    class _Standin:
        api_key = "tok"
        api_url = CANVAS

    assert credential_of(_Real()).kind == BROWSER
    assert credential_of(_Standin()).token == "tok"


def test_credential_of_does_not_mask_an_empty_credential():
    """An empty credential is a real answer - "not signed in" - and falling
    back to a token string there would turn a logged-out state into a
    confusing authentication failure further down."""
    class _LoggedOut:
        auth = CanvasCredential()
        api_key = "leftover-token"
        api_url = CANVAS

    assert credential_of(_LoggedOut()).token == ""


# ---------------------------------------------------------------------------
# 4. The engine, driven against a real server
# ---------------------------------------------------------------------------

class _Canvasish(http.server.BaseHTTPRequestHandler):
    """Answers like Canvas: a bearer it does not know is 401 even when a
    perfectly good session cookie is present."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.server.seen.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "cookie": self.headers.get("Cookie"),
            "ua": self.headers.get("User-Agent"),
        })
        auth = self.headers.get("Authorization")
        cookie = self.headers.get("Cookie") or ""
        # An SSO portal answers a browser-shaped request with 200 and its own
        # page - here as JSON with no `id`, which is the shape that gets past a
        # status-code-only check.
        if "canvas_session=PORTAL" in cookie:
            body = json.dumps({"redirect": "/login"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        ok = (auth == "Bearer GOOD") or (
            auth is None and "canvas_session=GOOD" in cookie)
        body = json.dumps(
            {"id": 124390, "name": "Birk"} if ok
            else {"errors": [{"message": "user authorisation required"}]}
        ).encode("utf-8")
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def canvasish():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Canvasish)
    srv.seen = []
    srv.base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_api_client_signs_in_with_cookies_and_no_bearer(canvasish):
    from core.canvas_logic import CanvasManager

    cred = from_cookies({"canvas_session": "GOOD"}, canvasish.base,
                        user_agent="WebView2/1.0")
    ok, message = CanvasManager(cred, canvasish.base).validate_token()

    assert ok, message
    api_calls = [r for r in canvasish.seen if "/api/v1/users/self" in r["path"]]
    assert api_calls, canvasish.seen
    assert api_calls[-1]["auth"] is None
    assert "canvas_session=GOOD" in (api_calls[-1]["cookie"] or "")
    assert api_calls[-1]["ua"] == "WebView2/1.0"


def test_the_api_client_still_signs_in_with_a_token(canvasish):
    from core.canvas_logic import CanvasManager

    ok, message = CanvasManager("GOOD", canvasish.base).validate_token()
    assert ok, message
    api_calls = [r for r in canvasish.seen if "/api/v1/users/self" in r["path"]]
    assert api_calls[-1]["auth"] == "Bearer GOOD"
    assert not (api_calls[-1]["cookie"] or "")


def test_a_manager_built_without_init_still_has_a_credential():
    """`CanvasManager.__new__` is a legitimate idiom and several tests use it.
    An AttributeError on `.auth` surfaces inside a download worker as "could
    not fetch items for module", which names the wrong cause entirely."""
    from core.canvas_logic import CanvasManager

    cm = CanvasManager.__new__(CanvasManager)
    assert isinstance(cm.auth, CanvasCredential)
    assert cm.auth.usable is False


def test_api_key_stays_a_plain_string_in_browser_mode():
    """Thirteen construction sites and a keyring write read `.api_key` as a
    str. Browser mode has no token, and saying so honestly beats handing them
    an object they would mis-handle."""
    from core.canvas_logic import CanvasManager

    cm = CanvasManager(_browser_cred(), CANVAS)
    assert isinstance(cm.api_key, str) and cm.api_key == ""


# ---------------------------------------------------------------------------
# 5. Censuses - these fail on a NEW site, not on today's
# ---------------------------------------------------------------------------

def test_no_engine_module_formats_its_own_bearer_header():
    """One rule, one place. A second site that formats `Bearer {...}` is a
    login the browser path silently does not reach - the shape this repo has
    hit with `make_long_path`, `pdf_looks_real` and three AppleScript escapers.
    """
    offenders = []
    for path in sorted(_ROOT.glob("**/*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith(("dist/", "tests/", "scripts/", "build/")):
            continue
        if rel in ("core/canvas_auth.py",):
            continue          # the one definition
        src = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(src.splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"['\"]Bearer \{", code) or re.search(
                    r"Authorization['\"]\s*:\s*f?['\"]Bearer", code):
                offenders.append(f"{rel}:{i} {line.strip()}")
    assert not offenders, (
        "these sites format an Authorization header themselves instead of "
        "asking the credential:\n  " + "\n  ".join(offenders))


def test_every_aiohttp_session_in_the_engine_takes_its_auth_from_the_credential():
    """A ClientSession built without the credential downloads unauthenticated,
    which presents as "every file failed" with no cause named."""
    missing = []
    for label, src in (("core/canvas_logic.py", _LOGIC_SRC),
                       ("sync/execution.py", _SYNC_EXEC_SRC)):
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", ""))
            if name != "ClientSession":
                continue
            spread = [k for k in node.keywords if k.arg is None]
            got = any(
                "aiohttp_session_kwargs" in ast.dump(k.value) for k in spread)
            if not got:
                missing.append(f"{label}:{node.lineno}")
    assert not missing, (
        "these aiohttp sessions do not take their auth from the credential: "
        + ", ".join(missing))


#: Functions that authenticate to Canvas on the caller's behalf. Handing any of
#: them `.api_key` is a silent browser-mode outage: it is `''` there, so the
#: request goes out with an empty bearer and comes back 401.
_CREDENTIAL_CONSUMERS = {
    "lti_launch", "discover_course_videos", "_CanvasREST", "_new_canvas_client",
    "course_level_launch_url",
}


def _api_key_arguments(tree):
    """Every `<anything>.api_key` passed INTO a credential consumer."""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if name not in _CREDENTIAL_CONSUMERS:
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Attribute) and sub.attr == "api_key":
                    hits.append(f"{name}(... {ast.unparse(sub)} ...) line {node.lineno}")
    return hits


def test_no_site_authenticates_with_api_key_instead_of_the_credential():
    """A census, because this is the class the design rests on.

    `.api_key` is a plain `str` and is EMPTY in browser mode, so a site that
    passes it instead of asking for the credential authenticates as nobody -
    silently, and only for the users who signed in with the browser. Eight such
    reverts were written as mutants during the 2026-09-11 audit and SEVEN of
    them survived the entire related test set; only the aiohttp one was pinned
    (by the ClientSession census above). This is the guard that answers for the
    other seven, and it fails on a NEW site rather than on today's.
    """
    offenders = []
    for path in sorted(_ROOT.glob("**/*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith(("dist/", "tests/", "scripts/", "build/", "_audit_runs/")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        offenders += [f"{rel}: {hit}" for hit in _api_key_arguments(tree)]
    assert not offenders, (
        "these sites authenticate with .api_key (empty in browser mode) instead "
        "of the credential:\n  " + "\n  ".join(offenders))


def test_the_census_can_still_say_yes():
    """A census that cannot fail is not a census. Drives the real matcher over
    the exact shape the seven surviving mutants had."""
    bad = ast.parse("lti_launch(_cand, cm.api_key)\n"
                    "discover_course_videos(cm.api_url, cm.api_key, cid)\n")
    assert len(_api_key_arguments(bad)) == 2
    good = ast.parse("lti_launch(_cand, credential_of(cm))\n"
                     "discover_course_videos(cm.api_url, credential_of(cm), cid)\n")
    assert _api_key_arguments(good) == []


def _auth_method_writes():
    """Every `config_data['auth_method'] = X` in ui/auth.py, by function."""
    out = {}
    tree = ast.parse(_AUTH_SRC)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and getattr(target.slice, "value", None) == "auth_method"):
                    out.setdefault(fn.name, set()).add(
                        getattr(node.value, "id", None))
    return out


def test_EVERY_login_route_records_how_the_user_signed_in():
    """`auth_method` is what the next launch reads to decide which credential
    to restore. Written on one route only, a user who switches is restored
    against a credential they have stopped using.

    A PER-FUNCTION census, and the previous version of this test is the reason
    why. It was a substring check - `"config_data['auth_method'] = TOKEN" in
    _AUTH_SRC` - and when `_upgrade_to_access_token` was added it became the
    SECOND site writing that exact line. So deleting the write on the
    token-paste route still satisfied the assertion, the mutant for it
    SURVIVED, and the census had gone vacuous in the commit that added a
    legitimate third site. Same shape as `pdf_looks_real` sitting on two of
    three delete sites: a check that asks "does this exist anywhere" cannot
    notice its own reduction.
    """
    writes = _auth_method_writes()
    expected = {
        # the browser sign-in, and the upgrade that supersedes it with a token
        "_persist_browser_login": {"BROWSER"},
        "_upgrade_to_access_token": {"TOKEN"},
        # the token the user pastes in themselves
        "render_login_page": {"TOKEN"},
    }
    for fn, values in expected.items():
        assert fn in writes, (
            f"{fn}() no longer records auth_method, so the next launch "
            f"restores whatever the PREVIOUS sign-in method was")
        assert writes[fn] == values, (
            f"{fn}() records auth_method={writes[fn]}, expected {values}")
    # And nothing else writes it, so this census stays a complete statement
    # rather than a list of the sites that happened to exist when it was typed.
    assert set(writes) == set(expected), (
        f"a new auth_method write appeared in {set(writes) - set(expected)} - "
        "classify it here, because a route that does not record it restores "
        "the wrong credential on the next launch")


# ---------------------------------------------------------------------------
# 6. Verification - the one definition of "this credential works"
# ---------------------------------------------------------------------------

def test_verify_accepts_a_real_user_payload(canvasish):
    from core import browser_login

    ok, name, why = browser_login.verify(
        from_cookies({"canvas_session": "GOOD"}, canvasish.base),
        canvasish.base)
    assert ok and name == "Birk", why


def test_verify_rejects_an_expired_session(canvasish):
    from core import browser_login

    ok, _name, why = browser_login.verify(
        from_cookies({"canvas_session": "STALE"}, canvasish.base),
        canvasish.base)
    assert not ok and "expired" in why.lower()


def test_verify_rejects_a_200_whose_body_is_not_a_user(canvasish):
    """The signed-out case an SSO portal actually produces: 200, a perfectly
    valid JSON body, and no user in it. A status-code-only check reads that as
    a successful sign-in and stores a credential that can never work."""
    from core import browser_login

    ok, _name, why = browser_login.verify(
        from_cookies({"canvas_session": "PORTAL"}, canvasish.base),
        canvasish.base)
    assert not ok and why


def test_verify_refuses_an_unusable_credential_without_a_round_trip(canvasish):
    """Counted, not asserted from the return value: with the guard removed the
    call still fails, just after spending a request - so only the request count
    can tell the two apart."""
    from core import browser_login

    before = len(canvasish.seen)
    ok, _n, why = browser_login.verify(CanvasCredential(), canvasish.base)
    assert not ok and why
    assert len(canvasish.seen) == before, canvasish.seen[before:]


# ---------------------------------------------------------------------------
# 7. Harvesting from the web view
# ---------------------------------------------------------------------------

class _FakeWindow:
    """A pywebview Window as far as this module is concerned.

    `get_cookies()` returns a list of `http.cookies.SimpleCookie`, one morsel
    each - the shape BOTH backends normalise to (WebView2's CookieManager and
    WKWebView's WKHTTPCookieStore), including HttpOnly cookies, which is the
    whole reason this works at all.
    """

    def __init__(self, cookies: dict, user_agent="UA/1.0", raise_on_js=False):
        # A value may be a bare string (no domain attribute, which is what a
        # backend that already scoped its query returns) or a
        # ``(value, domain)`` pair, which is what BOTH backends actually emit -
        # pywebview's ``create_cookie`` always fills ``domain`` in from the
        # platform cookie object.
        self._cookies = cookies
        self._ua = user_agent
        self._raise = raise_on_js

    def get_cookies(self):
        out = []
        for name, value in self._cookies.items():
            domain = ''
            if isinstance(value, tuple):
                value, domain = value
            c = SimpleCookie()
            c[name] = value
            if domain:
                c[name]['domain'] = domain
            out.append(c)
        return out

    def evaluate_js(self, _script):
        if self._raise:
            raise RuntimeError("no JS bridge on this page")
        return self._ua


def test_harvest_reads_the_session_out_of_the_web_view():
    from core.browser_login import _harvest

    cred = _harvest(_FakeWindow({"canvas_session": "S", "_csrf_token": "c"}),
                    CANVAS)
    assert cred is not None
    assert cred.cookies["canvas_session"] == "S"
    assert cred.host == "cbscanvas.instructure.com"
    assert cred.user_agent == "UA/1.0"


def test_harvest_answers_none_while_the_user_is_still_on_their_idp():
    """The normal state for most of a sign-in: cookies exist, none of them are
    a Canvas session. Treating that as success would store a credential that
    can never work."""
    from core.browser_login import _harvest

    assert _harvest(_FakeWindow({"ESTSAUTH": "x"}), CANVAS) is None


def test_harvest_survives_a_page_with_no_js_bridge():
    """Canvas sets a Content Security Policy, and the User-Agent is a nicety.
    Losing it must not lose the login."""
    from core.browser_login import _harvest

    cred = _harvest(_FakeWindow({"canvas_session": "S"}, raise_on_js=True),
                    CANVAS)
    assert cred is not None and cred.usable


def test_clear_session_is_a_no_op_without_a_gui():
    """Logout must complete whatever the web view does."""
    from core import browser_login
    assert browser_login.clear_session() is False


def test_is_available_says_why_it_is_not():
    from core import browser_login
    ok, reason = browser_login.is_available()
    assert ok is False and "token" in reason.lower()


# ---------------------------------------------------------------------------
# 8. The wiring that makes any of it persist
# ---------------------------------------------------------------------------

def test_the_web_view_profile_is_persistent():
    """pywebview defaults to `private_mode=True`, which runs WebView2 InPrivate
    against a temp directory thrown away on exit. Without both settings the
    sign-in works and is forgotten on every launch - a silent, total
    regression of the feature, with nothing failing."""
    call = _START_SRC[_START_SRC.index("webview.start(_boot"):]
    assert "_webview_kwargs" in call[:120]
    assert "'private_mode': False" in _START_SRC
    assert "'storage_path': _profile_dir" in _START_SRC


def test_a_profile_that_cannot_be_created_still_launches_the_app():
    """Degrading to a forgotten session beats refusing to start."""
    # Checked through the AST, on the HANDLER BODY. The first version of this
    # grepped the block for "except Exception", which a mutant satisfied by
    # adding `raise` as the handler's first statement - the handler was still
    # there, and it now aborted the launch.
    tree = ast.parse(_START_SRC)
    handlers = [h for node in ast.walk(tree) if isinstance(node, ast.Try)
                for h in node.handlers if h.name == "_profile_err"]
    assert handlers, "the profile setup no longer has its own handler"
    for h in handlers:
        assert not [n for n in ast.walk(h) if isinstance(n, ast.Raise)], (
            "the launcher re-raises a profile failure instead of degrading to "
            "a session that is simply not remembered")
    assert "_webview_kwargs: dict = {}" in _START_SRC


def test_the_signin_button_is_a_form_submit_above_the_token_field():
    """Inside `st.form` a plain button cannot rerun - this file records that at
    three other call sites - and the whole point of the placement is that a
    user whose institution has disabled tokens meets the route that works
    BEFORE the field that cannot."""
    form_start = _AUTH_SRC.index('with st.form("auth_form"')
    button = _AUTH_SRC.index('key="login_browser_btn"', form_start)
    token_field = _AUTH_SRC.index('key="token_input"', form_start)
    submit = _AUTH_SRC.index('key="login_submit_btn"', form_start)
    assert form_start < button < token_field < submit

    # WHICH CALL this key belongs to is an AST question, not a text-window one.
    # This was `"st.form_submit_button(" in _AUTH_SRC[button - 200:button]`,
    # and it broke on 2026-09-14 when the label became a multi-line expression
    # (`_signin_button_label(...)` resolving the school name) and pushed the
    # call name past 200 characters. The guard then failed against code that
    # satisfies it perfectly, which reads exactly like the property being gone.
    # Widening the window only moves the next break; asking the tree cannot
    # break at all. Same rule this repo already records as "assert the
    # expression, not the token".
    calls = [
        node for node in ast.walk(ast.parse(_AUTH_SRC))
        if isinstance(node, ast.Call)
        and any(kw.arg == "key"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "login_browser_btn"
                for kw in node.keywords)
    ]
    assert len(calls) == 1, (
        f"expected exactly one widget keyed login_browser_btn, found {len(calls)}")
    assert ast.unparse(calls[0].func) == "st.form_submit_button", (
        "the sign-in control is no longer a form submit button; inside st.form "
        "a plain st.button cannot rerun, so it would do nothing at all"
    )
    # It is the screen's one primary now. Before 2026-09-14 the only solid
    # button on the page was `Log In` under the token field, so the brightest
    # thing on a first-run login screen belonged to the one route a growing
    # share of students are not permitted to take.
    assert any(kw.arg == "type" and getattr(kw.value, "value", None) == "primary"
               for kw in calls[0].keywords), (
        "the sign-in button is not the primary any more - check that the "
        "weight inversion has not come back"
    )


def test_the_signin_notice_emits_exactly_one_element_in_every_state():
    """A fragment rerun rewinds the event container's write index, and the slot
    below it reconciles by position - two elements in one state and one in
    another hands the next block a stranger's children."""
    tree = ast.parse(_AUTH_SRC)
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, ast.FunctionDef) and f.name == "_browser_login_poll")
    # An ALLOW-list of element names was the first version of this, and a
    # mutant adding `st.caption('')` walked straight past it. Count every call
    # on `st` instead, minus the ones that are provably not element writes -
    # so a new Streamlit element cannot be added without this noticing.
    NOT_A_WRITE = {"rerun", "fragment", "session_state", "stop"}
    writes = [n for n in ast.walk(fn)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and getattr(n.func.value, "id", "") == "st"
              and n.func.attr not in NOT_A_WRITE]
    assert len(writes) == 1, [n.func.attr for n in writes]


def test_the_signin_notice_slot_kills_its_own_gap():
    assert re.search(r'st-key-browser_login_slot"\]\s*\{\s*gap:\s*0', _AUTH_SRC)


def test_the_notice_markup_and_stylesheet_agree():
    """Every class the notice emits must have a rule, and the rules must live
    in the login page's UNCONDITIONAL stylesheet."""
    from ui import auth as auth_mod

    classes = set()
    for state in ("waiting", "checking", "cancelled", "error"):
        classes.update(re.findall(r"class='([^']+)'",
                                  auth_mod._browser_notice_html(state)))
    emitted = {c for group in classes for c in group.split()}
    for name in emitted:
        assert f".{name}" in _AUTH_SRC, f"no rule for .{name}"


def test_the_notice_interpolates_nothing():
    """Rendered with `unsafe_allow_html=True`, so every character has to be a
    literal from this file - never a message that came back from a server."""
    from ui import auth as auth_mod

    for state in ("waiting", "checking", "cancelled", "error", "anything"):
        html = auth_mod._browser_notice_html(state)
        assert "{" not in html and "}" not in html, html


def test_a_signed_in_browser_session_is_not_overwritten_by_an_empty_token_read():
    """The token read runs after the browser restore and answers '' when there
    is no token. Unguarded, it replaces a working session and drops the user on
    the login page holding a valid credential."""
    tree = ast.parse(_AUTH_SRC)
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, ast.FunctionDef) and f.name == "restore_saved_session")
    assigns = [n for n in ast.walk(fn)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Subscript)
                       and getattr(t.slice, "value", None) == "api_token"
                       for t in n.targets)]
    assert assigns, "restore_saved_session no longer assigns api_token"

    guarded = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        test_src = ast.dump(node.test)
        if "is_authenticated" not in test_src or "UnaryOp" not in test_src:
            continue
        guarded.extend(n for n in ast.walk(node) if n in assigns)
    assert len(guarded) == len(assigns), (
        "an api_token assignment in restore_saved_session is not guarded by "
        "`not is_authenticated`, so it can overwrite a live browser session")


# ---------------------------------------------------------------------------
# 9. The silent phase, driven end to end with no GUI
# ---------------------------------------------------------------------------

class _Ev:
    """pywebview's Event, as far as the worker uses it."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self


class _StuckOnIdP:
    """A window that never leaves the identity provider.

    The realistic silent-phase failure: the institution's SSO session has
    lapsed, so the redirect chain parks on the IdP and no Canvas cookie is ever
    issued. The worker must notice and hand over to a human.
    """

    def __init__(self, log):
        self.events = types.SimpleNamespace(closed=_Ev())
        self.log = log
        # The worker builds its own window and `_drive` resets the job on
        # the way out, so this is the only handle a test has on it. The
        # membership checks the other tests make against `log` are
        # unaffected.
        log.append(self)

    def get_current_url(self):
        return "https://login.microsoftonline.com/875c414e/saml2"

    def get_cookies(self):
        return []

    def evaluate_js(self, _s):
        return "UA/1.0"

    def show(self):
        self.log.append("show")

    def destroy(self):
        self.log.append("destroy")


class _ChurningIdP(_StuckOnIdP):
    """A chain that never settles: every poll sees a different URL.

    The case the settle rule cannot answer - an IdP that keeps redirecting, or a
    URL we cannot read steadily - so SILENT_TIMEOUT is what has to show the
    window. Without this the clock could be given the ten-minute value again and
    every settling login would hide the regression.
    """

    def __init__(self, log):
        super().__init__(log)
        self._n = 0

    def get_current_url(self):
        self._n += 1
        return f"https://login.microsoftonline.com/875c414e/step{self._n}"


class _TitledIdP(_StuckOnIdP):
    """A window whose title can be read back, sitting on the IdP.

    `events.loaded` is SET, which is the state a real window is in once its
    first page is in - and the state `_set_title` requires, because pywebview's
    title setter opens with `events.loaded.wait(15)` and this runs inside the
    0.5s poll loop.
    """

    def __init__(self, log):
        super().__init__(log)
        loaded = _Ev()
        loaded.is_set = lambda: True
        self.events = types.SimpleNamespace(closed=_Ev(), loaded=loaded)
        self.titles = []

    @property
    def title(self):
        return self.titles[-1] if self.titles else ''

    @title.setter
    def title(self, value):
        self.titles.append(value)


class _UnloadedIdP(_TitledIdP):
    """The same window BEFORE its first page has loaded.

    pywebview's title setter begins `self.events.loaded.wait(15)`, so retitling
    one of these from the poll loop would stall the whole login for fifteen
    seconds - taking the harvest, the settle counter and the cancel check with
    it.
    """

    def __init__(self, log):
        super().__init__(log)
        loaded = _Ev()
        loaded.is_set = lambda: False
        loaded.wait = lambda _t=None: time.sleep(5) or False
        self.events = types.SimpleNamespace(closed=_Ev(), loaded=loaded)
        #: How many times the worker has polled the URL. A stalled loop stops
        #: counting, which is the only way a block is observable from outside.
        self.polls = 0

    def get_current_url(self):
        self.polls += 1
        return super().get_current_url()

    @property
    def title(self):
        return self.titles[-1] if self.titles else ''

    @title.setter
    def title(self, value):                                    # pragma: no cover
        self.events.loaded.wait(15)
        self.titles.append(value)


def _drive(monkeypatch, interactive, log, window_cls=_StuckOnIdP):
    """Run a real login attempt against a fake web view. No GUI, no network."""
    from core import browser_login as bl
    import core.canvas_logic as cl

    monkeypatch.setattr(bl, "SILENT_TIMEOUT", 0.4)
    monkeypatch.setattr(bl, "INTERACTIVE_TIMEOUT", 1.6)
    monkeypatch.setattr(bl, "POLL_INTERVAL", 0.05)

    fake_webview = types.SimpleNamespace(
        guilib=object(),
        windows=[],
        create_window=lambda *a, **k: window_cls(log),
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    class _CM:
        def __init__(self, _cred, url):
            self.api_url = "https://cbscanvas.instructure.com"

    monkeypatch.setattr(cl, "CanvasManager", _CM)

    bl.reset()
    started = time.monotonic()
    bl.begin_login("canvas.cbs.dk", interactive=interactive)
    deadline = started + 8
    while time.monotonic() < deadline:
        if bl.status() in ("needs_user", "ok", "error", "cancelled"):
            break
        time.sleep(0.02)
    elapsed = time.monotonic() - started
    state = bl.status()
    # Sample again in the window BETWEEN the two clocks: comfortably past the
    # point a mis-set deadline would expire, and comfortably before the
    # interactive timeout legitimately does. Asserting the state the instant it
    # first changes is what let two mutants through; sleeping past
    # INTERACTIVE_TIMEOUT instead catches the honest timeout and fails against
    # correct code.
    time.sleep(bl.SILENT_TIMEOUT * 1.5)
    settled = bl.status()
    bl.reset()
    return state, settled, elapsed


def test_an_interactive_sign_in_shows_the_window_when_the_silent_attempt_expires(monkeypatch):
    """The whole feature, in one assertion.

    The first version of this worker gave an interactive login the LONG clock
    up front, so the window stayed hidden for ten minutes: the user clicked
    "Sign in with Canvas" and nothing ever appeared. 51 unit tests and a 22/23
    mutation pass did not see it; one real run did. This is that run, without
    a GUI.
    """
    from core import browser_login as bl
    log = []
    state, settled, elapsed = _drive(monkeypatch, True, log)
    assert state == "needs_user", state
    assert "show" in log, log
    # WHEN, not just whether. The shipped bug still reached `needs_user` - it
    # just took the ten-minute clock to get there - so only the timing tells a
    # working silent phase from a broken one.
    assert elapsed < bl.SILENT_TIMEOUT * 3, (
        f"the window took {elapsed:.2f}s to appear against a "
        f"{bl.SILENT_TIMEOUT}s silent phase - it is waiting on the long clock")
    # And it must STAY up: showing the window has to extend the deadline, or it
    # appears and is torn down on the very next poll.
    assert settled == "needs_user", (
        f"the window was shown and the attempt then ended as {settled!r} - "
        f"showing it did not extend the clock")


def test_a_silent_renewal_never_shows_a_window(monkeypatch):
    """The startup path. Putting a login window in front of someone who did not
    ask for one is worse than simply showing the login screen."""
    log = []
    state, settled, _elapsed = _drive(monkeypatch, False, log)
    assert state == "error", state
    assert settled == "error", settled
    assert "show" not in log, log


def test_the_silent_clock_is_much_shorter_than_the_interactive_one():
    """They are two different waits: one is a redirect chain, the other is a
    person finding their phone for an MFA prompt."""
    from core import browser_login as bl
    assert bl.SILENT_TIMEOUT < bl.INTERACTIVE_TIMEOUT / 10


def test_the_window_appears_as_soon_as_the_page_stops_moving(monkeypatch):
    """The whole clock is paid by the one user who cannot avoid it.

    Measured in the real app against real CBS SSO: the hidden window was on the
    Entra login page at 3.3s and was not shown until 17.0s. A settled URL is the
    honest signal that the chain has stopped and a human is needed, and
    SILENT_TIMEOUT is a constant - so on a FASTER machine the old rule wasted
    MORE time, not less.
    """
    from core import browser_login as bl
    log = []
    state, _settled, elapsed = _drive(monkeypatch, True, log)
    assert state == "needs_user", state
    assert "show" in log, log
    # The settle path, not the clock: SETTLE_POLLS * POLL_INTERVAL is well under
    # SILENT_TIMEOUT in the harness, so only the new rule can get here this fast.
    assert elapsed < bl.SILENT_TIMEOUT, (
        f"window took {elapsed:.2f}s against a {bl.SILENT_TIMEOUT}s silent "
        f"clock - it waited out the clock instead of noticing the settled page")


def test_a_chain_that_never_settles_still_shows_on_the_SHORT_clock(monkeypatch):
    """The backstop, and the reason it needs its own test.

    The settle rule shows the window as soon as the page stops moving - which
    means it also MASKS the original shipped bug (an interactive login given the
    ten-minute clock up front) on every login that settles. Only a chain that
    never settles can tell the two clocks apart, and the mutation pass proved it:
    with the settle rule in place and this test missing, that mutant survived.
    """
    from core import browser_login as bl
    log = []
    state, _settled, elapsed = _drive(monkeypatch, True, log,
                                      window_cls=_ChurningIdP)
    assert state == "needs_user", state
    assert "show" in log, log
    assert elapsed < bl.SILENT_TIMEOUT * 2, (
        f"a never-settling chain took {elapsed:.2f}s to show its window against "
        f"a {bl.SILENT_TIMEOUT}s silent clock - it is waiting out the "
        f"INTERACTIVE clock instead")


class _AnonymousCanvasLogin:
    """A window parked on Canvas' OWN login form.

    The realistic non-SSO case: Canvas hands an ANONYMOUS visitor a session
    cookie (measured - `GET /login/canvas` answers `Set-Cookie: canvas_session`),
    so the harvest succeeds on every poll while the user is still typing.
    """

    def __init__(self, log):
        self.events = types.SimpleNamespace(closed=_Ev())
        self.log = log

    def get_current_url(self):
        return "https://cbscanvas.instructure.com/login/canvas"

    def get_cookies(self):
        c = SimpleCookie()
        c["canvas_session"] = "ANONYMOUS-SAME-EVERY-POLL"
        return [c]

    def evaluate_js(self, _s):
        return "UA/1.0"

    def show(self):
        self.log.append("show")

    def destroy(self):
        self.log.append("destroy")


def test_an_unchanged_session_cookie_is_not_verified_again(monkeypatch):
    """One API call per session, not one per poll.

    Without this the app calls /api/v1/users/self every ~0.5s for as long as the
    login form is on screen - up to ~1,200 requests inside the ten-minute
    interactive window, all of them answering the same 401.
    """
    from core import browser_login as bl
    import core.canvas_logic as cl

    verifies = []
    monkeypatch.setattr(bl, "SILENT_TIMEOUT", 0.6)
    monkeypatch.setattr(bl, "INTERACTIVE_TIMEOUT", 1.2)
    monkeypatch.setattr(bl, "POLL_INTERVAL", 0.05)
    monkeypatch.setattr(bl, "verify", lambda cred, url: (
        verifies.append(cred.cookies.get("canvas_session")), (False, "", "no"))[1])

    log = []
    fake_webview = types.SimpleNamespace(
        guilib=object(), windows=[],
        create_window=lambda *a, **k: _AnonymousCanvasLogin(log))
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    class _CM:
        def __init__(self, _cred, url):
            self.api_url = "https://cbscanvas.instructure.com"

    monkeypatch.setattr(cl, "CanvasManager", _CM)

    bl.reset()
    bl.begin_login("cbscanvas.instructure.com", interactive=True)
    time.sleep(1.4)                      # many polls, one unchanged cookie
    bl.reset()
    assert len(verifies) == 1, (
        f"verify() ran {len(verifies)} times for one unchanged session cookie")


def test_a_second_click_re_shows_the_window_instead_of_destroying_it():
    """Measured in the real app: the old behaviour threw the open window away,
    made the user wait the silent phase again, and lost whatever they had typed
    into their institution's login form."""
    from core import browser_login as bl

    shown = []

    class _Win:
        def show(self):
            shown.append(1)

    bl.reset()
    job = bl._Job("https://cbscanvas.instructure.com", True)
    job.state = "needs_user"
    job.window = _Win()
    bl._job = job
    try:
        assert bl.bring_to_front("https://cbscanvas.instructure.com") is True
        assert shown == [1]
        # A different address is a different sign-in and must NOT be adopted.
        assert bl.bring_to_front("https://other.instructure.com") is False
        # A hidden attempt still in its silent phase is left alone: the user has
        # not been told it failed yet.
        job.state = "running"
        assert bl.bring_to_front("https://cbscanvas.instructure.com") is False
    finally:
        bl._job = None


def test_the_ui_asks_for_the_open_window_before_starting_a_new_one():
    """`begin_browser_signin` used to `reset()` unconditionally, which destroys
    the window the user is looking at. The order is the fix, so the order is
    what is pinned."""
    fn = _fn("begin_browser_signin")
    calls = [(n.lineno, getattr(n.func, "attr", getattr(n.func, "id", "")))
             for n in ast.walk(fn) if isinstance(n, ast.Call)]
    front = [ln for ln, name in calls if name == "bring_to_front"]
    reset = [ln for ln, name in calls if name == "reset"]
    assert front, "begin_browser_signin never looks for an open window"
    assert reset, "begin_browser_signin no longer resets a stale job"
    assert min(front) < min(reset), (
        "begin_browser_signin resets before asking whether a window is already "
        "open, so a second click still throws it away")


def test_the_window_says_which_host_the_user_is_typing_a_password_into(monkeypatch):
    """The address bar is the one thing an embedded web view takes away.

    A student signing in here types their university password into a window
    with no URL anywhere on it, and the chain really does leave Canvas - CBS
    goes to `login.microsoftonline.com` and back. Without this the window
    cannot answer "am I on my own institution's login page?", which is the
    standing objection to embedded-webview SSO and the reason Google blocks it
    outright.
    """
    from core import browser_login as bl
    log = []
    state, _settled, _elapsed = _drive(monkeypatch, True, log,
                                       window_cls=_TitledIdP)
    assert state == "needs_user", state
    window = next(w for w in log if isinstance(w, _TitledIdP))
    titles = window.titles
    assert titles, "the window was never retitled, so it shows no host at all"
    assert titles[-1] == "Sign in to Canvas - login.microsoftonline.com", titles


def test_retitling_never_waits_on_a_page_that_has_not_loaded(monkeypatch):
    """pywebview's title setter opens with `events.loaded.wait(15)`.

    The poll loop runs every 0.5s and owns the cancel check, the harvest and
    the settle counter, so a fifteen-second block inside it is not a cosmetic
    problem - it is the login stopping. `_set_title` therefore asks whether the
    page is loaded before it assigns, and this drives a window that would sleep
    if it did not.

    **What is asserted is that the LOOP KEEPS RUNNING**, not that the title was
    skipped, and the difference is what makes this test work at all. The first
    version checked `not window.titles` after the attempt had reported
    `needs_user` - which it does *before* the retitle, so the assertion ran
    while the mutated worker was still asleep inside `wait()`, found an empty
    list, and passed. The mutation pass caught that: the mutant SURVIVED. A
    stall can only be seen by watching for progress that does not arrive.
    """
    from core import browser_login as bl
    import core.canvas_logic as cl

    log = []
    monkeypatch.setattr(bl, "SILENT_TIMEOUT", 0.3)
    monkeypatch.setattr(bl, "INTERACTIVE_TIMEOUT", 30.0)
    monkeypatch.setattr(bl, "POLL_INTERVAL", 0.05)
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(
        guilib=object(), windows=[],
        create_window=lambda *a, **k: _UnloadedIdP(log)))

    class _CM:
        def __init__(self, _cred, url):
            self.api_url = "https://cbscanvas.instructure.com"

    monkeypatch.setattr(cl, "CanvasManager", _CM)

    bl.reset()
    try:
        bl.begin_login("canvas.cbs.dk", interactive=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and bl.status() != "needs_user":
            time.sleep(0.02)
        assert bl.status() == "needs_user"

        window = next(w for w in log if isinstance(w, _UnloadedIdP))
        # The window is up. Now watch the loop: with the guard it polls every
        # 50ms, so a full second is ~20 polls. A worker parked in wait(15)
        # manages none.
        before = window.polls
        time.sleep(1.0)
        progressed = window.polls - before
        assert progressed >= 5, (
            f"the poll loop made {progressed} polls in a second after the "
            f"window was shown - it is blocked in the title setter, and the "
            f"cancel check, the harvest and the settle counter are blocked "
            f"with it")
    finally:
        bl.reset()


@pytest.mark.parametrize("url,expected", [
    ("https://cbscanvas.instructure.com/login",
     "Sign in to Canvas - cbscanvas.instructure.com"),
    ("https://login.microsoftonline.com/875c414e/saml2",
     "Sign in to Canvas - login.microsoftonline.com"),
    # A URL we could not read must not leave the window advertising the host it
    # was on a moment ago.
    ("", "Sign in to Canvas"),
    # Homoglyphs are the whole reason an indicator can lie. Cyrillic "a".
    ("https://аpple.com/", "Sign in to Canvas - xn--pple-43d.com"),
])
def test_the_host_indicator_is_punycoded(url, expected):
    """`urlparse().hostname` hands back whatever the URL contained, so an
    internationalised host arrives in its Unicode form - and the Unicode form
    is the one that can be built out of homoglyphs to read as somebody else's
    domain. `xn--` is ugly exactly where ugly is the correct answer."""
    from core.browser_login import _title_for
    assert _title_for(url) == expected


def test_the_live_session_keeps_everything_the_canvas_host_set():
    """The harvest is WIDE and the store is narrow, and that split is the point.

    Trimming at the harvest - which is what this used to do, for the Credential
    Manager size limit - also threw away whatever the institution's WAF had
    issued. A Cloudflare `cf_clearance` is the measured example: without it the
    first API call meets a challenge page, which is a 200 that is not JSON, and
    `verify` reports that as "your Canvas session has expired" with nothing the
    user can do. The size limit is a fact about the KEYRING and is enforced in
    `to_storable`, which this asserts stays true at the same time.
    """
    from core.browser_login import _harvest

    cred = _harvest(_FakeWindow({
        "canvas_session": "S" * 762, "cf_clearance": "x" * 426,
        "_csrf_token": "y" * 102, "log_session_id": "z" * 32,
    }), CANVAS)
    assert cred is not None
    assert set(cred.cookies) == {"canvas_session", "cf_clearance",
                                 "_csrf_token", "log_session_id"}
    assert len(json.dumps(cred.to_storable())) * 2 < 2560, (
        "the stored credential no longer fits Windows Credential Manager")


def test_a_cookie_belonging_to_another_host_is_never_harvested():
    """pywebview's macOS backend filters the cookie store by SUBSTRING of the
    URL the window was loaded with (`if domain not in self.url`), so for a
    window opened on `https://cbscanvas.instructure.com/login` a cookie for the
    unrelated tenant `canvas.instructure.com` passes its filter - that string
    does occur inside it. Everything harvested goes into a jar scoped to OUR
    Canvas host, i.e. it becomes something the app SENDS to Canvas, so a
    foreign cookie must not reach it."""
    from core.browser_login import _harvest

    cred = _harvest(_FakeWindow({
        "canvas_session": ("MINE", "cbscanvas.instructure.com"),
        # The macOS substring hole, exactly.
        "other_tenant": ("THEIRS", "canvas.instructure.com"),
        # A parent-domain cookie IS ours: that is ordinary browser scoping.
        "shared": ("OK", ".instructure.com"),
    }), "https://cbscanvas.instructure.com")
    assert cred is not None
    assert set(cred.cookies) == {"canvas_session", "shared"}, cred.cookies.keys()


def test_a_session_cookie_from_a_foreign_host_is_not_a_login():
    """The same hole, at the one cookie that decides the sign-in is finished.
    Harvesting somebody else's `canvas_session` and scoping it to ours would
    hand Canvas a credential for a different tenant and report it as success."""
    from core.browser_login import _harvest

    assert _harvest(_FakeWindow({
        "canvas_session": ("THEIRS", "canvas.instructure.com"),
    }), "https://cbscanvas.instructure.com") is None


@pytest.mark.parametrize("host,domain,expected", [
    ("cbscanvas.instructure.com", "cbscanvas.instructure.com", True),
    ("cbscanvas.instructure.com", ".instructure.com", True),
    ("cbscanvas.instructure.com", "instructure.com", True),
    ("cbscanvas.instructure.com", "canvas.instructure.com", False),
    # The suffix trap: endswith() without the dot says yes to this.
    ("cbscanvas.instructure.com", "scanvas.instructure.com", False),
    ("cbscanvas.instructure.com", "", False),
    ("", "instructure.com", False),
])
def test_cookie_domain_matching_is_the_browser_rule(host, domain, expected):
    from core.canvas_auth import cookie_domain_matches
    assert cookie_domain_matches(host, domain) is expected


# ---------------------------------------------------------------------------
# 10. Contracts the old `str` credential satisfied silently
# ---------------------------------------------------------------------------

def test_a_credential_can_key_a_dict():
    """`core/course_cache.py` keys its cache on `(token, url)`.

    A `str` is hashable and a frozen dataclass holding a `dict` is not, so the
    moment a browser credential reached that key the lookup raised TypeError -
    deep inside the fetch, reported to the user as "We couldn't reach Canvas".
    Measured in the real app, signed in, with the sidebar already showing the
    user's name, against real Canvas.
    """
    cache = {}
    cache[(_browser_cred(), "u")] = "browser"
    cache[(from_token("tok"), "u")] = "token"
    assert cache[(_browser_cred(), "u")] == "browser"
    assert len(cache) == 2


def test_two_sessions_for_one_host_are_different_cache_keys():
    """Excluding the cookies from the HASH must not merge two credentials.

    They collide in the hash bucket and `__eq__` separates them, so a renewed
    session gets its own entry instead of silently serving the old session's
    courses.
    """
    a = _browser_cred(cookies={"canvas_session": "OLD"})
    b = _browser_cred(cookies={"canvas_session": "NEW"})
    assert a != b
    assert len({a, b}) == 2


def test_the_course_cache_really_accepts_a_browser_credential(monkeypatch):
    """Against the REAL module, not a re-implementation of its key.

    The first version of this test built a local dict and asserted on that,
    while its docstring claimed the opposite - so it passed whatever
    `core.course_cache` did, including raising TypeError on an unhashable
    credential, which is the failure it was written for and which SHIPPED
    (reported to the user as "We couldn't reach Canvas").
    """
    import core.course_cache as cc

    cc.clear()
    calls = []
    monkeypatch.setattr(cc, "_loader", lambda token, url: calls.append(token) or [])

    cred = _browser_cred()
    cc.fetch_courses(cred, CANVAS)          # cold: must not raise on the key
    cc.fetch_courses(cred, CANVAS)          # warm: served from the cache
    assert len(calls) == 1, "a browser credential did not survive as a cache key"

    # A RENEWED session must not be served the expired one's courses.
    cc.fetch_courses(_browser_cred(cookies={"canvas_session": "NEW"}), CANVAS)
    assert len(calls) == 2
    cc.clear()


def test_a_pending_flag_with_no_job_is_cleared_instead_of_looping(monkeypatch):
    """`pending` set and the job `idle` is a LOOP, not a wait.

    `_browser_login_poll` treats `idle` as terminal and calls
    `st.rerun(scope="app")`; this function used to return on the same `idle`
    with the pending flag STILL SET, so the next run polled again - a rerun a
    second for as long as the page stayed open. The pair is reachable whenever
    the job is reset by someone other than this session, which is exactly what
    a second window or a logout in another tab does: the job is process-global
    and the flag is per session.

    Driven, not read: the old shape passes every structural assertion in this
    file.
    """
    import ui.auth as auth
    from core import browser_login as bl

    class _SS(dict):
        pass

    ss = _SS({'browser_login_pending': True})
    monkeypatch.setattr(auth, 'st', types.SimpleNamespace(session_state=ss))
    bl.reset()
    assert bl.status() == 'idle'

    assert auth.adopt_pending_browser_login() is False
    assert ss.get('browser_login_pending') is False, (
        "the pending flag survived an idle job, so the poll fragment reruns "
        "the app forever")
    # And it says nothing: `idle` is the ABSENCE of an attempt, not a failure
    # that happened to this user, so there is nothing honest to announce.
    assert not ss.get('browser_login_failed')


def test_starting_a_login_closes_the_window_of_the_one_it_replaces(monkeypatch):
    """A superseded job never reaches the branch that closes its window.

    `_finish` declines to record a state for a job that is no longer current,
    so an already-visible window sits there until its own ten-minute clock runs
    out - two sign-in windows, one of them for an address the user has moved
    on from. `ui/auth.begin_browser_signin` calls `reset()` first and so covers
    the app's own route; this closes it for every caller.
    """
    from core import browser_login as bl
    import core.canvas_logic as cl

    log = []
    monkeypatch.setattr(bl, "SILENT_TIMEOUT", 0.3)
    monkeypatch.setattr(bl, "INTERACTIVE_TIMEOUT", 30.0)
    monkeypatch.setattr(bl, "POLL_INTERVAL", 0.05)
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(
        guilib=object(), windows=[],
        create_window=lambda *a, **k: _StuckOnIdP(log)))

    class _CM:
        def __init__(self, _cred, url):
            self.api_url = url if url.startswith("http") else f"https://{url}"

    monkeypatch.setattr(cl, "CanvasManager", _CM)

    bl.reset()
    bl.begin_login("cbscanvas.instructure.com", interactive=True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and bl.status() != "needs_user":
        time.sleep(0.02)
    assert bl.status() == "needs_user"
    assert log.count("destroy") == 0

    # The user corrects the address and signs in again.
    bl.begin_login("other.instructure.com", interactive=True)
    assert log.count("destroy") >= 1, (
        "the first sign-in window was left on screen for its own full clock")
    bl.reset()


def test_the_sign_in_window_validates_tls(monkeypatch):
    """Nothing may switch certificate checking off, and the reason it needs a
    test is that the switch is PROCESS-GLOBAL.

    pywebview registers `ServerCertificateErrorDetected -> AlwaysAllow` when
    `webview.start(ssl=True)` or `webview.settings['IGNORE_SSL_ERRORS']` is on.
    Either flag would silently disable certificate validation in the CANVAS
    SIGN-IN window as well as in the local Streamlit one - and that window is
    where a student types their university password, on whatever campus or cafe
    network they are on. `private_mode` is already documented in this codebase
    as process-global for exactly the same reason; this is the same hazard with
    a worse consequence.
    """
    import webview
    assert webview.settings.get('IGNORE_SSL_ERRORS') is False, (
        "something switched IGNORE_SSL_ERRORS on at import time")

    tree = ast.parse(Path("start.py").read_text(encoding="utf-8"))
    starts = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "start"
              and getattr(getattr(n.func, "value", None), "id", "") == "webview"]
    assert starts, "webview.start() is not called in start.py any more"
    for call in starts:
        assert not any(k.arg == "ssl" for k in call.keywords), (
            f"start.py:{call.lineno} passes ssl= to webview.start, which turns "
            f"OFF certificate validation in the Canvas sign-in window too")

    src = Path("start.py").read_text(encoding="utf-8")
    assert "IGNORE_SSL_ERRORS" not in src, (
        "start.py touches IGNORE_SSL_ERRORS")


def test_a_finished_sign_in_is_adopted_by_whichever_session_sees_it():
    """The sign-in state is process-global; "am I waiting?" is per session.

    Reload the app window mid-sign-in, or have a second session open, and the
    login completes into a flag nobody is holding - so the user finishes
    signing in at their institution, comes back, and the app is still on the
    login screen holding a perfectly good session. Observed in the real app.

    Asserted structurally: the status has to be read BEFORE the pending flag
    is allowed to end the function, or there is no way to notice a finished
    login this session did not start.
    """
    tree = ast.parse(_AUTH_SRC)
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, ast.FunctionDef)
              and f.name == "adopt_pending_browser_login")

    status_calls = [n.lineno for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "attr", "") == "status"]
    assert status_calls, "adopt_pending_browser_login never reads the status"

    pending_returns = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        if "browser_login_pending" not in ast.dump(node.test):
            continue
        pending_returns.extend(n.lineno for n in ast.walk(node)
                               if isinstance(n, ast.Return))
    assert pending_returns, "the pending flag no longer gates anything"
    assert min(status_calls) < min(pending_returns), (
        "adopt_pending_browser_login gives up on the pending flag before it "
        "has looked at the sign-in status, so a login finished by another "
        "session is stranded")


# ---------------------------------------------------------------------------
# 10b. Panopto: Canvas will not mint a sessionless launch for a session
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sessionless,expected", [
    ("https://x.instructure.com/api/v1/courses/43660/external_tools/"
     "sessionless_launch?launch_type=module_item&module_item_id=1087340&id=863",
     "https://x.instructure.com/courses/43660/modules/items/1087340"),
    ("https://x.instructure.com/api/v1/courses/43660/external_tools/"
     "sessionless_launch?id=863&url=https%3A%2F%2Fcbs.cloud.panopto.eu%2FPanopto%2FLTI%2FLTI.aspx",
     "https://x.instructure.com/courses/43660/external_tools/retrieve"
     "?url=https%3A%2F%2Fcbs.cloud.panopto.eu%2FPanopto%2FLTI%2FLTI.aspx"),
    ("https://x.instructure.com/api/v1/courses/43660/external_tools/"
     "sessionless_launch?id=863",
     "https://x.instructure.com/courses/43660/external_tools/863"),
    ("https://x.instructure.com/api/v1/users/self", ""),
    ("", ""),
])
def test_the_in_app_launch_url_is_derived_for_all_three_shapes(sessionless, expected):
    """Canvas refuses `sessionless_launch` to anything but an access token
    (`raise UnauthorizedClient unless @access_token`), measured as 403 on every
    Panopto item of a real course. All three in-app equivalents were driven end
    to end on a real session and landed on the Panopto host."""
    from panopto.auth import in_app_launch_url
    assert in_app_launch_url(sessionless) == expected


def test_a_browser_session_never_calls_the_token_only_launch_endpoint(monkeypatch):
    """The API call cannot succeed on cookies, and spending it would just log a
    403 per recording. Browser mode must go straight to the in-app route, with
    the Canvas cookies on the session that walks it."""
    import panopto.auth as pa
    import requests as _requests

    api_calls, session_gets = [], []

    monkeypatch.setattr(pa.requests, "get",
                        lambda url, **kw: api_calls.append(url))

    class _Resp:
        status_code, text = 200, ""

        def __init__(self, url):
            self.url = url

    monkeypatch.setattr(_requests.Session, "get",
                        lambda self, url, **kw: (session_gets.append((url, self)),
                                                 _Resp(url))[1])

    launch = ("https://cbscanvas.instructure.com/api/v1/courses/43660/"
              "external_tools/sessionless_launch?launch_type=module_item"
              "&module_item_id=1087340&id=863")
    pa.lti_launch(launch, _browser_cred(api_url="https://cbscanvas.instructure.com"))

    assert not api_calls, "browser mode still called the token-only endpoint"
    assert session_gets, "nothing was fetched at all"
    url, session = session_gets[0]
    assert url == ("https://cbscanvas.instructure.com/courses/43660/"
                   "modules/items/1087340")
    # The Canvas cookies must be ON the session (or the launch is anonymous)...
    assert "canvas_session" in (session.prepare_request(
        _requests.Request("GET", "https://cbscanvas.instructure.com/courses/1")
    ).headers.get("Cookie") or "")
    # ...and must never reach the Panopto host. Verified on a real launch too:
    # Panopto received .ASPXAUTH/csrfToken/sandboxCookie and nothing of ours.
    assert "canvas_session" not in (session.prepare_request(
        _requests.Request("GET", "https://cbs.cloud.panopto.eu/Panopto/Pages/Viewer.aspx")
    ).headers.get("Cookie") or "")


def test_token_mode_still_uses_the_sessionless_api(monkeypatch):
    """The proven path stays byte-for-byte: a token CAN mint a launch, and the
    in-app route is not better for it."""
    import panopto.auth as pa
    import requests as _requests

    api_calls = []

    class _ApiResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"url": "https://cbscanvas.instructure.com/courses/1/launch"}

    monkeypatch.setattr(pa.requests, "get",
                        lambda url, **kw: (api_calls.append(url), _ApiResp())[1])

    class _Resp:
        status_code, text, url = 200, "", "https://cbscanvas.instructure.com/x"

    monkeypatch.setattr(_requests.Session, "get", lambda self, url, **kw: _Resp())

    launch = ("https://cbscanvas.instructure.com/api/v1/courses/43660/"
              "external_tools/sessionless_launch?launch_type=module_item"
              "&module_item_id=1087340&id=863")
    pa.lti_launch(launch, from_token("TOKEN"))
    assert api_calls == [launch]


# ---------------------------------------------------------------------------
# 11. Logging out means logging out
# ---------------------------------------------------------------------------

def _fn(name):
    tree = ast.parse(_AUTH_SRC)
    return next(f for f in ast.walk(tree)
                if isinstance(f, ast.FunctionDef) and f.name == name)


def _restore_with(monkeypatch, stored, *, authenticates):
    """Drive `_restore_browser_session` with a fake store. Returns the state."""
    import ui.auth as auth

    class _SS(dict):
        pass

    ss = _SS()
    monkeypatch.setattr(auth, 'st', types.SimpleNamespace(session_state=ss))
    monkeypatch.setattr(auth, 'load_browser_credential',
                        lambda _url: (stored, False))

    def _adopt(_cred):
        if authenticates:
            ss['is_authenticated'] = True

    monkeypatch.setattr(auth, '_adopt_restored_credential', _adopt)
    found = auth._restore_browser_session(CANVAS)
    return found, ss


def test_no_stored_session_never_triggers_a_hidden_renewal(monkeypatch):
    """That state is what LOGGING OUT looks like.

    Trying to sign the user back in there is both wrong and alarming: they
    asked to be signed out, and the attempt they never made then fails and
    announces "Canvas sign-in did not finish" on a screen they reached on
    purpose. Reported from the real app.

    Driven rather than read. The previous version of this test asserted that
    the flag write sat inside an `if _saved_cred is not None:` branch **of
    `restore_saved_session`**, and that anchor went stale the moment the
    decision was extracted into one function with two call sites: it failed
    with "no longer arms a renewal at all" against code that arms it correctly.
    A brittle anchor reads exactly like a missing guard, which is a trap this
    repo has now hit four times.
    """
    found, ss = _restore_with(monkeypatch, None, authenticates=False)
    assert found is False
    assert not ss.get('browser_restore_pending'), (
        "signing out starts a sign-in the user never asked for")


def test_a_stored_session_canvas_refuses_DOES_arm_a_renewal(monkeypatch):
    """The positive control, without which the test above proves nothing.

    A check that can only ever say no is not a check. This is also the case
    the whole feature turns on: the stored cookie has aged out, and the
    institution's SSO session can replace it with no interaction at all.
    """
    found, ss = _restore_with(monkeypatch, _browser_cred(), authenticates=False)
    assert found is True
    assert ss.get('browser_restore_pending') is True, (
        "an expired stored session no longer arms the hidden renewal, so "
        "every launch after Canvas' own day is a manual sign-in")


def test_a_stored_session_that_WORKS_arms_nothing(monkeypatch):
    """The third state, and the common one. Nothing to renew."""
    found, ss = _restore_with(monkeypatch, _browser_cred(), authenticates=True)
    assert found is True
    assert not ss.get('browser_restore_pending')


def test_the_browser_restore_decision_has_exactly_ONE_implementation():
    """Two copies of "restore a session, arm a renewal if it is stale" is how
    the marker-driven path and the no-token-found fallback would come to
    disagree about what a stale session means - the `make_long_path` shape.

    So `restore_saved_session` must DELEGATE and never arm the flag itself.
    """
    fn = _fn("restore_saved_session")
    own_writes = [n for n in ast.walk(fn)
                  if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Subscript)
                          and getattr(t.slice, "value", None) == "browser_restore_pending"
                          for t in n.targets)]
    assert not own_writes, (
        "restore_saved_session arms the renewal itself instead of going "
        "through _restore_browser_session, so there are two implementations")

    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_restore_browser_session"]
    assert len(calls) == 2, (
        "expected exactly two restore sites - the auth_method marker and the "
        "no-token-found fallback - found "
        f"{len(calls)}. The marker is a HINT; the credential store is the "
        "fact, and a sign-in whose settings write was skipped is stored with "
        "nothing naming it.")


def test_a_hidden_renewal_that_fails_is_not_announced():
    """The ordinary way of arriving at the login screen - an expired session,
    or being offline - must not be reported as a failure to somebody who has
    done nothing but open the app."""
    fn = _fn("adopt_pending_browser_login")
    failure_writes = [n for n in ast.walk(fn)
                      if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Subscript)
                              and getattr(t.slice, "value", None) == "browser_login_failed"
                              for t in n.targets)]
    assert failure_writes, "nothing records a failed sign-in any more"

    interactive_guarded = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and "was_interactive" in ast.dump(node.test):
            interactive_guarded.extend(n for n in ast.walk(node) if n in failure_writes)
    assert interactive_guarded, (
        "a failed HIDDEN renewal is announced as 'Canvas sign-in did not "
        "finish', on a login screen the user reached deliberately")


def test_an_expired_browser_session_is_renewed_not_destroyed():
    """A dead TOKEN can only be replaced by the user; a dead browser session is
    the ordinary end of Canvas' day-long session, and the institution's SSO
    session can mint a new one with no interaction. Deleting the stored
    credential threw away the input to that renewal - and then told the user to
    paste an access token, which at a school that has turned token creation off
    is not something they can do."""
    fn = _fn("force_reauth")
    assert "_browser = browser_session_active()" in _AUTH_SRC, (
        "force_reauth no longer asks how the user actually signed in")
    branches = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                and "_browser" in ast.dump(n.test)]
    assert branches, "force_reauth no longer asks how the user signed in"

    # Every credential delete must sit inside the `if not _browser:` arm, or the
    # renewal below has nothing left to renew.
    token_arms = [b for b in branches if isinstance(b.test, ast.UnaryOp)
                  and isinstance(b.test.op, ast.Not)]
    assert token_arms, "force_reauth no longer has a token-only arm"
    guarded = {id(n) for arm in token_arms for stmt in arm.body
               for n in ast.walk(stmt)}
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(
                node.func, "id", getattr(node.func, "attr", "")) in (
                    "delete_browser_credential", "_delete_fallback_token",
                    "_safe_keyring_delete"):
            assert id(node) in guarded, (
                f"force_reauth calls {ast.unparse(node.func)} outside the "
                f"token-only arm, so an expired browser session is destroyed "
                f"instead of renewed")

    arms = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Subscript)
                    and getattr(t.slice, "value", None) == "browser_restore_pending"
                    for t in n.targets)]
    assert arms, "an expired browser session no longer arms a renewal"


def test_the_reconnect_screen_speaks_the_users_own_credential():
    """"Generate a fresh access token" is not merely the wrong route for a
    browser-session user - at a token-restricted school it is one they cannot
    take."""
    assert "_browser_mode = browser_session_active()" in _AUTH_SRC
    i = _AUTH_SRC.index("Your Canvas address is saved:")
    block = _AUTH_SRC[i:i + 1200]
    # By SIGHT, not by label: the button says "Sign in to <the student's own
    # university>" now, so no literal can name it. See the census below.
    assert "<b>Sign in</b> button below" in block, (
        "the reconnect screen has no browser-session instruction")
    assert "Generate a fresh access token" in block, (
        "the token instruction disappeared - it is still right for token users")
    assert "_browser_mode" in block, "the two instructions are not selected by mode"


def test_no_copy_names_the_primary_button_by_a_LITERAL_LABEL():
    """The button's label is the student's own university now.

    `_signin_button_label()` returns "Sign in to " + the institution the picker
    resolved, and "Sign in to Canvas" when it resolved nothing. So "Sign in
    with Canvas" - the label this screen shipped with - is a button that exists
    on NOBODY's screen, including the fallback's, which says "to", not "with".

    A CENSUS, not a check that five known strings were fixed: the five were
    written months apart in three different structures (a failure table, a
    notice builder, an inline reconnect header), and the next one will be too.
    Bolding a label is the tell - it presents that text as the button's name -
    so the rule is that no user-facing string in this module may bold anything
    but the sight-description the copy actually uses.
    """
    bolded = set(re.findall(r"<b>Sign in[^<]*</b>", _AUTH_SRC))
    assert bolded <= {"<b>Sign in</b>"}, (
        "copy names the primary button by a hardcoded label, which no longer "
        "matches what the button says: %s" % sorted(bolded - {"<b>Sign in</b>"})
    )


# ---------------------------------------------------------------------------
# 12. The persistent profile must not lock the NEXT launch out
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, pid, name, cmdline, parent=None, kids=()):
        self.pid, self._name, self._cmd = pid, name, cmdline
        self._parent, self._kids = parent, list(kids)
        self.info = {"name": name, "pid": pid}
        self.killed = False

    def name(self):
        return self._name

    def cmdline(self):
        return self._cmd

    def parent(self):
        return self._parent

    def is_running(self):
        return not self.killed

    def children(self, recursive=False):
        return list(self._kids)

    def kill(self):
        self.killed = True


def _fake_psutil(procs):
    return types.SimpleNamespace(
        process_iter=lambda attrs=None: list(procs),
        Process=lambda pid: next(p for p in procs if p.pid == pid),
        wait_procs=lambda procs_, timeout=None: ([], []),
    )


def test_a_wedged_web_view_holding_our_profile_is_reaped(monkeypatch):
    """Before the persistent profile a leftover could not touch the next launch.
    Now it can: measured twice, the next launch waits ~45s and then
    CoreWebView2 creation fails with E_ABORT, so the window never loads."""
    import core.health_log as hl

    profile = r"C:\cfg\webview"
    udd = f'--user-data-dir="{profile}\\EBWebView"'   # what WebView2 really passes
    # Measured shape: the browser process's parent is the app, and the
    # renderer/gpu children hang off the BROWSER process, not off the app.
    browser = _FakeProc(1, "msedgewebview2.exe", ["msedgewebview2.exe", udd],
                        parent=None)
    child = _FakeProc(2, "msedgewebview2.exe", ["msedgewebview2.exe", udd],
                      parent=browser)
    browser._kids = [child]
    monkeypatch.setattr(hl.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil([browser, child]))

    n, pids = hl.reap_webview_orphans(profile)
    assert browser.killed and child.killed, "the wedged orphan survived"
    assert n == 2 and set(pids) == {1, 2}


def test_a_LIVE_instance_keeps_its_web_view(monkeypatch):
    """The app's single-instance guard fails open in three documented ways, so a
    second live instance legitimately shares this profile. Killing its WebView2
    would take down a running window or a sync in flight - the exact failure
    `_reap_recorded_orphans` already exists to prevent."""
    import core.health_log as hl

    profile = r"C:\cfg\webview"
    udd = f'--user-data-dir="{profile}\\EBWebView"'
    owner = _FakeProc(10, "Canvas Downloader.exe", ["app"])
    browser = _FakeProc(11, "msedgewebview2.exe", ["msedgewebview2.exe", udd],
                        parent=owner)
    monkeypatch.setattr(hl.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil([owner, browser]))

    n, _pids = hl.reap_webview_orphans(profile)
    assert n == 0 and not browser.killed, "a live instance's web view was killed"


def test_another_apps_web_view_is_not_ours_to_kill(monkeypatch):
    """Teams, WhatsApp, Widgets and Phone Link all run WebView2."""
    import core.health_log as hl

    stranger = _FakeProc(20, "msedgewebview2.exe",
                         ["msedgewebview2.exe",
                          '--user-data-dir="C:\\Users\\x\\Teams\\EBWebView"'],
                         parent=None)
    monkeypatch.setattr(hl.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil([stranger]))

    n, _ = hl.reap_webview_orphans(r"C:\cfg\webview")
    assert n == 0 and not stranger.killed


def test_the_reap_runs_before_the_window_is_created():
    """It races WebView2's own initialisation otherwise: the health record's
    sweep runs on a background thread from `_boot`, which starts at the same
    moment `webview.start()` begins creating the window."""
    i_reap = _START_SRC.index("reap_webview_orphans(")
    i_start = _START_SRC.index("webview.start(_boot")
    assert i_reap < i_start


def test_logging_out_keeps_the_school_on_screen():
    """`force_reauth` has prefilled the address since it was written and logout
    never did, so signing out dropped the user on a login screen that had
    forgotten which Canvas they use. The address is in the config either way -
    this only decides whether the app SHOWS what it already knows."""
    logout = _AUTH_SRC[_AUTH_SRC.index('key="nav_btn_logout"'):]
    logout = logout[:logout.index("# Version and support badge")]
    assert "st.session_state['url_input'] = st.session_state['api_url']" in logout, (
        "logout does not prefill the Canvas address, so the login screen it "
        "lands on has forgotten the school")


# ---------------------------------------------------------------------------
# 13. The sign-in window must let a password manager work
# ---------------------------------------------------------------------------

class _FakeSettings:
    """A CoreWebView2.Settings that can REFUSE a write, silently."""

    def __init__(self, accept=True):
        object.__setattr__(self, '_accept', accept)
        object.__setattr__(self, 'IsPasswordAutosaveEnabled', False)
        object.__setattr__(self, 'AreDefaultContextMenusEnabled', False)
        object.__setattr__(self, 'IsGeneralAutofillEnabled', True)

    def __setattr__(self, name, value):
        if not object.__getattribute__(self, '_accept'):
            return                      # written, not kept: the real hazard
        object.__setattr__(self, name, value)


class _FakeControl:
    def __init__(self, settings=None, ready=True):
        self.Settings = settings if settings is not None else _FakeSettings()
        self._ready = ready
        self.cleared = None

    @property
    def CoreWebView2(self):
        return self if self._ready else None

    @property
    def Profile(self):
        return self

    def ClearBrowsingDataAsync(self, kinds):
        self.cleared = kinds
        return object()


def _inline_ui_thread(_window, work):
    """Run the UI-thread work here. The real hop needs a real window."""
    try:
        return True, work()
    except Exception as e:                                       # noqa: BLE001
        return False, None


def test_the_password_manager_is_switched_on_for_the_signin_window(monkeypatch):
    """WebView2 ships with `IsPasswordAutosaveEnabled = False`, so without
    this the student types a full institutional password by hand on EVERY
    sign-in - which is the friction a longer session does nothing about."""
    from core import browser_login as bl
    settings = _FakeSettings()
    monkeypatch.setattr(bl.sys, 'platform', 'win32')
    monkeypatch.setattr(bl, '_webview2_control',
                        lambda _w: _FakeControl(settings))
    monkeypatch.setattr(bl, '_on_ui_thread', _inline_ui_thread)

    assert bl.enable_password_manager(object()) is True
    assert settings.IsPasswordAutosaveEnabled is True
    assert settings.AreDefaultContextMenusEnabled is True, (
        "right-click Paste is still off, so a user who reaches for the "
        "context menu - which is what a password-manager extension's users "
        "do - gets nothing")


def test_a_REFUSED_write_answers_False_instead_of_claiming_success(monkeypatch):
    """THE point of the read-back, and the lesson of the backed-out popup fix.

    That fix reported `handler_installed: true` while plainly not working,
    because it measured that OUR subscription took and never that pywebview's
    had gone - a guard that could not say no. A settings property CAN be read
    back, so this one must only answer True when the live object agrees.
    """
    from core import browser_login as bl
    settings = _FakeSettings(accept=False)      # writes land nowhere
    monkeypatch.setattr(bl.sys, 'platform', 'win32')
    monkeypatch.setattr(bl, '_webview2_control',
                        lambda _w: _FakeControl(settings))
    monkeypatch.setattr(bl, '_on_ui_thread', _inline_ui_thread)

    assert bl.enable_password_manager(object()) is False
    assert settings.IsPasswordAutosaveEnabled is False


def test_an_uninitialised_webview_is_retried_not_failed(monkeypatch):
    """`CoreWebView2` is None until its async init completes - measured ~2.3s,
    which is many polls. Treating that as a failure would mean the feature
    never switches on."""
    from core import browser_login as bl
    monkeypatch.setattr(bl.sys, 'platform', 'win32')
    monkeypatch.setattr(bl, '_webview2_control',
                        lambda _w: _FakeControl(ready=False))
    monkeypatch.setattr(bl, '_on_ui_thread', _inline_ui_thread)
    assert bl.enable_password_manager(object()) is False


def test_it_is_a_silent_no_op_off_windows(monkeypatch):
    """WKWebView has no equivalent for a non-browser app. Driven from Windows
    by answering the platform guard, the technique this repo uses for every
    macOS branch - a `skipif` would only ever run on the rare machine."""
    from core import browser_login as bl
    touched = []
    monkeypatch.setattr(bl.sys, 'platform', 'darwin')
    monkeypatch.setattr(bl, '_webview2_control',
                        lambda _w: touched.append(1))
    assert bl.enable_password_manager(object()) is False
    assert bl._clear_profile_identity_data(object()) is False
    assert not touched, "reached for a WinForms control off Windows"


def _reachable(fn, target_ids):
    """Of *target_ids* in *fn*, those NOT sitting under a constant-false test.

    `if False:` keeps a call in the source while removing it from the program,
    which is how a "does this function call X" census passes against code that
    never runs it. This repo has now paid for that twice in one session - the
    Panopto login-redirect mutant, and the worker's password-manager call.
    """
    parent = {}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node
    dead = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Constant) and not test.value:
                for stmt in node.body:
                    dead.update(id(n) for n in ast.walk(stmt))
    return {i for i in target_ids if i not in dead}


def _coreview_accesses(fn):
    """Every way *fn* reaches `.CoreWebView2`, and whether each is nested.

    BOTH forms, and the second is the one that matters: the original defect
    was written `getattr(webview2, 'CoreWebView2', None)`, and a census that
    only walks `ast.Attribute` cannot see a `getattr` with a string literal -
    so the mutant restoring that exact bug SURVIVED the first version of this
    test. A census blind to the shape the defect actually took is not a
    census.
    """
    out = []
    nested = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.FunctionDef) and node is not fn:
            nested.update(id(n) for n in ast.walk(node))
    for node in ast.walk(fn):
        hit = isinstance(node, ast.Attribute) and node.attr == 'CoreWebView2'
        if not hit and isinstance(node, ast.Call) and getattr(
                node.func, 'id', '') == 'getattr' and len(node.args) >= 2:
            arg = node.args[1]
            hit = isinstance(arg, ast.Constant) and arg.value == 'CoreWebView2'
        if hit:
            out.append(id(node) in nested)
    return out


def test_CoreWebView2_is_only_ever_touched_on_the_UI_THREAD():
    """`.CoreWebView2` is a WinForms control property and the sign-in worker
    is a daemon thread. Reading it from there is a cross-thread access.

    Found by a probe HANGING rather than by reading: an earlier version of
    `_webview2_control` reached `.CoreWebView2` itself, and the two probes
    that appeared to prove the API works had both happened to touch it inside
    the UI-thread hop. Caught and turned into "not ready yet", that access
    would make the retry answer False for ever and the feature silently never
    activate.
    """
    src = (_ROOT / "core" / "browser_login.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = {f.name: f for f in ast.walk(tree)
           if isinstance(f, ast.FunctionDef)}

    for name in ('enable_password_manager', '_clear_profile_identity_data'):
        accesses = _coreview_accesses(fns[name])
        assert accesses, f"{name} no longer reaches CoreWebView2 at all"
        assert all(accesses), (
            f"{name} touches .CoreWebView2 outside the UI-thread closure, "
            f"which is a cross-thread access from the sign-in worker")

    assert not _coreview_accesses(fns['_webview2_control']), (
        "_webview2_control reaches .CoreWebView2, so every caller performs a "
        "cross-thread access before it can hop to the UI thread")


def test_the_worker_actually_switches_it_on():
    """Otherwise it is dead code - which is exactly what `refresh_silently`
    was for three passes."""
    src = (_ROOT / "core" / "browser_login.py").read_text(encoding="utf-8")
    worker = next(f for f in ast.walk(ast.parse(src))
                  if isinstance(f, ast.FunctionDef) and f.name == '_worker')
    calls = [n for n in ast.walk(worker) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', '') == 'enable_password_manager']
    assert calls, "_worker never enables the password manager"
    # REACHABLE, not merely present. `if False:` around the call left it in the
    # source and out of the program, and the first version of this assertion
    # passed against exactly that - the same trap as the Panopto
    # login-redirect mutant earlier the same day.
    assert _reachable(worker, {id(c) for c in calls}), (
        "_worker's call to enable_password_manager is unreachable, so the "
        "password manager is never switched on for any sign-in")


def test_logging_out_clears_SAVED_PASSWORDS_not_just_cookies(monkeypatch):
    """A requirement created by enabling the password manager.

    `clear_session`'s own docstring reasons about a shared machine - "leaving
    it intact at logout would mean the next launch signs straight back in, as
    the PREVIOUS user". Once the profile can hold an institution password,
    `clear_cookies()` alone stops making that true: the next user finds the
    previous one's password filled in for them.
    """
    import sys as _sys
    import types as _t
    from core import browser_login as bl
    assert 'PasswordAutosave' in bl._LOGOUT_DATA_KINDS, (
        "logout does not reach saved passwords")
    assert 'Cookies' in bl._LOGOUT_DATA_KINDS

    control = _FakeControl()
    monkeypatch.setattr(bl.sys, 'platform', 'win32')
    monkeypatch.setattr(bl, '_webview2_control', lambda _w: control)
    monkeypatch.setattr(bl, '_on_ui_thread', _inline_ui_thread)
    # The real enum is a CLR type; stand in for it so the OR loop runs.
    mod = _t.ModuleType('Microsoft.Web.WebView2.Core')
    mod.CoreWebView2BrowsingDataKinds = _t.SimpleNamespace(
        Cookies=1, PasswordAutosave=2, GeneralAutofill=4)
    monkeypatch.setitem(_sys.modules, 'Microsoft.Web.WebView2.Core', mod)

    assert bl._clear_profile_identity_data(object()) is True
    assert control.cleared == 1 | 2 | 4, (
        f"cleared {control.cleared!r}; every identity-bearing kind must go")


def test_a_logout_that_can_only_clear_cookies_SAYS_SO(monkeypatch, caplog):
    """A destructive action that reports nothing is a bug waiting to be
    un-diagnosable - this repo's own rule, learned from the marker
    force-close. On such a machine a logout is weaker than it looks."""
    import logging
    import sys as _sys
    from core import browser_login as bl
    cleared = []
    monkeypatch.setattr(bl, '_clear_profile_identity_data', lambda _w: False)
    fake_window = types.SimpleNamespace(
        clear_cookies=lambda: cleared.append(1))
    monkeypatch.setitem(_sys.modules, 'webview',
                        types.SimpleNamespace(windows=[fake_window]))

    with caplog.at_level(logging.WARNING):
        assert bl.clear_session() is True
    assert cleared, "the cookies were not cleared either"
    assert any('saved passwords' in r.message.lower()
               for r in caplog.records), (
        "a logout that left saved passwords behind said nothing about it")


# ---------------------------------------------------------------------------
# 14. The app's own "stay signed in"
# ---------------------------------------------------------------------------

class _FakeCookie:
    def __init__(self, name, session=True):
        self.Name = name
        self.IsSession = session
        self.Expires = None


class _FakeTask:
    def __init__(self, cookies, completes=True):
        self.Result = cookies
        self.IsCompleted = completes


class _CookieControl:
    """A CoreWebView2 whose CookieManager records what was written back."""

    def __init__(self, cookies, completes=True):
        self._task = _FakeTask(cookies, completes)
        self.updated = []
        self.CookieManager = self
        self.Settings = _FakeSettings()

    @property
    def CoreWebView2(self):
        return self

    def GetCookiesAsync(self, _filter):
        return self._task

    def AddOrUpdateCookie(self, cookie):
        self.updated.append(cookie)


class _FakeDateTime:
    """Stands in for `System.DateTime`, so the assertion can tell a real
    DateTime-shaped value from the float that raises."""

    def __init__(self, days=0):
        self.days = days

    def AddDays(self, n):
        return _FakeDateTime(n)


class _UtcNow:
    UtcNow = _FakeDateTime()


def _persist_with(monkeypatch, cookies, *, completes=True, platform='win32'):
    """Drive `persist_session_cookies` with a fake profile.

    `System` is injected because pythonnet's import hook only exists once
    `clr` has been imported, which a test process that never opens a window
    has not done. The real app always has it (pywebview imports clr), and the
    first version of this helper left it out - so the closure raised
    ModuleNotFoundError, the count came back 0, and the test failed against
    correct code. Same shape as faking `Microsoft.Web.WebView2.Core` for the
    logout test.
    """
    import sys as _sys
    import types as _t
    from core import browser_login as bl
    control = _CookieControl(cookies, completes)
    monkeypatch.setattr(bl.sys, 'platform', platform)
    monkeypatch.setattr(bl, '_webview2_control', lambda _w: control)
    monkeypatch.setattr(bl, '_on_ui_thread', _inline_ui_thread)
    if 'System' not in _sys.modules:
        mod = _t.ModuleType('System')
        mod.DateTime = _UtcNow
        monkeypatch.setitem(_sys.modules, 'System', mod)
    count = bl.persist_session_cookies(object())
    return count, control


def test_a_session_cookie_is_given_an_expiry_so_it_SURVIVES_a_restart(monkeypatch):
    """The measured fact this rests on: the profile keeps cookies carrying an
    expiry and LOSES ones that do not. An identity provider the student did
    not tick "Stay signed in" at leaves a session cookie, so it is gone on the
    next launch and they sign in again. Re-dating it is what that tick box
    does, and this works at institutions whose IdP offers no tick box at all.
    """
    idp = _FakeCookie('ESTSAUTH')
    canvas = _FakeCookie('canvas_session')
    count, control = _persist_with(monkeypatch, [idp, canvas])
    assert count == 2
    assert {c.Name for c in control.updated} == {'ESTSAUTH', 'canvas_session'}
    assert idp.Expires is not None, "the cookie was written back undated"
    assert not isinstance(idp.Expires, float), (
        "a float was assigned to Expires, which the .NET wrapper refuses with "
        "'float value cannot be converted to System.DateTime' - inside the "
        "UI-thread closure, where nothing surfaces it")


def test_an_ALREADY_DATED_cookie_is_left_alone(monkeypatch):
    """Re-dating a cookie the identity provider deliberately gave a short life
    would be overriding its choice, not standing in for a missing tick box."""
    dated = _FakeCookie('ESTSAUTHPERSISTENT', session=False)
    count, control = _persist_with(monkeypatch, [dated])
    assert count == 0
    assert not control.updated


def test_it_covers_EVERY_host_not_just_canvas(monkeypatch):
    """The whole point is the IDENTITY PROVIDER's cookie. Canvas' own session
    is already carried across a restart by the credential store; the IdP's is
    what lets the next launch renew it without asking anybody anything, and it
    lives on a different host entirely.

    `GetCookiesAsync(None)` is what makes that reachable - pywebview's
    `get_cookies()` is scoped to the current URL, so a window sitting on
    Canvas can never see it.
    """
    from core import browser_login as bl
    src = (_ROOT / "core" / "browser_login.py").read_text(encoding="utf-8")
    fn = next(f for f in ast.walk(ast.parse(src))
              if isinstance(f, ast.FunctionDef)
              and f.name == 'persist_session_cookies')
    # THE CALL, not the source text. This read `'GetCookiesAsync(None)' in
    # ast.unparse(fn)` and could not fail: the function's own docstring
    # explains why the argument is None, so the prose satisfied the assertion
    # while the real call was filtered to 'canvas'. It survived a mutation
    # pass in exactly that state.
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, 'attr', '') == 'GetCookiesAsync']
    assert len(calls) == 1, f"expected one enumeration, found {len(calls)}"
    arg = calls[0].args[0] if calls[0].args else None
    assert isinstance(arg, ast.Constant) and arg.value is None, (
        "the enumeration is filtered to "
        f"{ast.unparse(arg) if arg is not None else 'nothing'}, so the "
        "identity provider's cookie - the only one that matters here - is "
        "invisible and the daily login stays")
    body = ast.unparse(fn)
    assert 'canvas_host' not in body and 'SESSION_COOKIE_NAMES' not in body, (
        "the conversion is restricted to Canvas, which leaves the IdP session "
        "to expire and the daily login in place")


def test_the_expiry_is_a_DATETIME_not_a_float():
    """The trap that cost a run, and it fails SILENTLY.

    `CoreWebView2Cookie.Expires` is a `System.DateTime` in the .NET wrapper
    even though the underlying C++ API takes a double. Assigning a float
    raises *'float' value cannot be converted to System.DateTime* - inside the
    UI-thread closure, where nothing surfaces it, so the sign-in looks fine
    and is simply forgotten on the next launch.
    """
    src = (_ROOT / "core" / "browser_login.py").read_text(encoding="utf-8")
    fn = next(f for f in ast.walk(ast.parse(src))
              if isinstance(f, ast.FunctionDef)
              and f.name == 'persist_session_cookies')
    body = ast.unparse(fn)
    assert 'DateTime' in body, "no System.DateTime anywhere"
    assert 'time.time()' not in body, (
        "a float is being assigned to Expires, which raises inside the "
        "UI-thread closure and silently forgets the sign-in")


def test_a_cookie_list_that_never_ARRIVES_is_reported(monkeypatch, caplog):
    """The Task completes on the UI thread's own message loop, so it is polled
    from the worker. Giving up silently would mean a sign-in that is quietly
    forgotten."""
    import logging
    from core import browser_login as bl
    monkeypatch.setattr(bl, 'COOKIE_ENUMERATION_TIMEOUT', 0.2)
    with caplog.at_level(logging.WARNING):
        count, control = _persist_with(monkeypatch, [_FakeCookie('x')],
                                       completes=False)
    assert count == 0
    assert not control.updated
    assert any('cookies' in r.message.lower() for r in caplog.records)


def test_no_GUI_is_NOT_A_FAILURE_and_says_nothing(monkeypatch, caplog):
    """Development runs in a browser with no pywebview window, so there is no
    profile holding a session either. Nothing to clear is not a failed clear.

    This guards the LOG, not the return value. Removing the explicit no-GUI
    branch still returns False - `windows[0]` raises IndexError and both arms
    below catch it - which is why this mutant was carried as EQUIVALENT for a
    whole pass. It is not: it warns "Could not clear saved passwords on
    logout: list index out of range" at a user whose logout worked perfectly,
    and a warning about a failure that did not happen is the same problem as a
    failure that reports nothing, pointing the other way.
    """
    import logging
    from core import browser_login as bl

    class _NoWindows:
        windows = []

    monkeypatch.setitem(__import__('sys').modules, 'webview', _NoWindows())
    with caplog.at_level(logging.WARNING, logger=bl.logger.name):
        assert bl.clear_session() is False
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "a logout with no web view to clear warns about a failure that did "
        "not happen: %s" % [r.message for r in caplog.records]
    )


def test_persisting_is_a_no_op_off_windows(monkeypatch):
    count, control = _persist_with(monkeypatch, [_FakeCookie('x')],
                                   platform='darwin')
    assert count == 0
    assert not control.updated


def test_the_sign_in_keeps_itself_BEFORE_the_window_is_destroyed():
    """It needs the live window, and this is the ONE moment the profile holds
    both Canvas' session and the identity provider's."""
    src = (_ROOT / "core" / "browser_login.py").read_text(encoding="utf-8")
    worker = next(f for f in ast.walk(ast.parse(src))
                  if isinstance(f, ast.FunctionDef) and f.name == '_worker')
    body = ast.unparse(worker)
    assert 'persist_session_cookies' in body, (
        "a finished sign-in is never kept, so every launch after Canvas' own "
        "day is a fresh login")
    persist = body.index('persist_session_cookies')
    # The success branch's destroy, i.e. the first one after the persist.
    destroy = body.index('_destroy(job)', persist)
    finish_ok = body.index("_finish(job, 'ok'", persist)
    assert persist < destroy < finish_ok, (
        "the window is destroyed before its cookies are kept, so there is "
        "nothing left to read them from")

    # REACHABLE, and reachable behind the user's own flag. Presence alone said
    # nothing: `if False:` above the call leaves it exactly where it is, and
    # this test passed against a worker that could never keep a sign-in.
    guards = [n for n in ast.walk(worker) if isinstance(n, ast.If)
              and any(isinstance(c, ast.Call)
                      and getattr(c.func, 'id', '') == 'persist_session_cookies'
                      for c in ast.walk(n))]
    assert guards, "the keep is not conditional on anything at all"
    innermost = guards[-1]
    assert (isinstance(innermost.test, ast.Attribute)
            and innermost.test.attr == 'keep_signed_in'), (
        "the keep is guarded by "
        f"`{ast.unparse(innermost.test)}` rather than by the user's choice - "
        "a constant here makes the whole retention feature dead code that "
        "every presence check still passes")


def test_a_job_KEEPS_the_answer_it_was_given(monkeypatch):
    """Driven, not grepped.

    The source checks below cannot see a `keep_signed_in = True` pasted into
    `_Job.__init__`: every string they look for is still there, and the flag
    is simply overwritten a line later. A mutant doing exactly that survived
    the 2026-09-14 pass, which means nothing in the suite could tell the
    setting from a constant.
    """
    from core import browser_login as bl

    assert bl._Job("https://cbscanvas.instructure.com", True,
                   keep_signed_in=False).keep_signed_in is False, (
        "the job overrides the answer it was constructed with, so turning the "
        "setting off does nothing")
    assert bl._Job("https://cbscanvas.instructure.com", True).keep_signed_in \
        is True, "the default stopped being on"

    # And the whole way through `begin_login`, which is what the UI calls.
    monkeypatch.setattr(bl, 'is_available', lambda: (True, ''))
    started = []
    monkeypatch.setattr(bl.threading, 'Thread',
                        lambda **kw: type('T', (), {
                            'start': lambda self: started.append(kw)})())
    monkeypatch.setattr(bl, '_job', None, raising=False)
    bl.begin_login("https://cbscanvas.instructure.com", interactive=False,
                   keep_signed_in=False)
    assert started, "no worker was started"
    assert bl._job.keep_signed_in is False, (
        "begin_login dropped the choice on its way into the job")
    bl.reset()


def test_the_choice_is_made_by_the_UI_LAYER_and_threaded_through():
    """`core` must not grow a second reader of the settings file - the
    co-ownership defect `.claude/rules/data-safety.md` records was four
    modules reading and writing one config."""
    login_src = (_ROOT / "core" / "browser_login.py").read_text(encoding="utf-8")
    assert 'keep_signed_in' in login_src
    assert 'canvas_downloader_settings' not in login_src, (
        "core/browser_login.py reads the settings file itself, so there are "
        "now two readers of one store")

    auth_src = (_ROOT / "ui" / "auth.py").read_text(encoding="utf-8")
    assert 'keep_signed_in=_keep_signed_in_enabled()' in auth_src, (
        "the UI never passes the user's choice, so it cannot be turned off")


def test_keeping_the_sign_in_can_be_turned_OFF(monkeypatch):
    import ui.auth as auth
    monkeypatch.setattr(auth, 'read_config_for_update',
                        lambda: ({'keep_signed_in': False}, True))
    assert auth._keep_signed_in_enabled() is False
    monkeypatch.setattr(auth, 'read_config_for_update', lambda: ({}, True))
    assert auth._keep_signed_in_enabled() is True, (
        "the default must be ON - the whole point of the feature is not to "
        "ask again")


def test_an_unreadable_settings_file_still_keeps_the_sign_in(monkeypatch):
    """Defaulting OFF there would reinstate the daily login because of a file
    permission problem somewhere else entirely."""
    import ui.auth as auth

    def _boom():
        raise OSError("locked")

    monkeypatch.setattr(auth, 'read_config_for_update', _boom)
    assert auth._keep_signed_in_enabled() is True


# ---------------------------------------------------------------------------
# A credential from a RELOADED module (2026-09-13)
# ---------------------------------------------------------------------------

def test_a_credential_from_a_RELOADED_module_is_adopted(caplog):
    """Reported by the product owner, repeatedly, in one session:

        TypeError: Canvas credential must be a CanvasCredential, str or None,
        got CanvasCredential

    which reads like nonsense and is exactly right. Streamlit's file watcher
    re-imports a changed module and builds a NEW class object, while
    `st.session_state['api_token']` still holds an instance of the OLD one.
    `isinstance` compares identity, so it answers False for two classes that
    are the same code.

    The consequence was not a crash: `core/course_cache.py` catches it and
    logs "Course refresh failed; keeping the cached list", so the app showed an
    amber network error and then "Canvas sign-in did not finish" - with a
    working credential in hand, and signing in again could not fix it because
    the new credential landed in the same stale-typed slot.
    """
    import importlib
    import logging
    import sys

    import core.canvas_auth as ca

    # A genuine second incarnation of the module, which is what the watcher
    # produces. Not a hand-made lookalike: the whole point is that this is the
    # SAME code with a different class identity.
    spec = importlib.util.find_spec('core.canvas_auth')
    reloaded = importlib.util.module_from_spec(spec)
    sys.modules['core.canvas_auth__reloaded_for_test'] = reloaded
    try:
        spec.loader.exec_module(reloaded)
    finally:
        sys.modules.pop('core.canvas_auth__reloaded_for_test', None)

    assert reloaded.CanvasCredential is not ca.CanvasCredential, (
        "the reload produced the same class object, so this test cannot "
        "reproduce the failure it exists for")

    stale = reloaded.from_cookies({'canvas_session': 'abc'},
                                  'https://x.instructure.com')
    assert not isinstance(stale, ca.CanvasCredential)      # the whole problem

    with caplog.at_level(logging.WARNING, logger='core.canvas_auth'):
        adopted = ca.coerce(stale, 'https://x.instructure.com')

    assert isinstance(adopted, ca.CanvasCredential), (
        "a credential from a reloaded module was not adopted, so a hot reload "
        "signs the user out with no way back")
    assert adopted.usable
    assert adopted.is_browser
    assert adopted.cookies.get('canvas_session') == 'abc'
    assert any('reloaded module' in r.message for r in caplog.records), (
        "the adoption is silent, so nobody can tell a hot reload happened")


def test_a_GENUINELY_wrong_type_still_fails_loudly():
    """The positive control, and the reason the recogniser is narrow.

    `.claude/rules/browser-login.md` records why this is a distinct type and
    not a `str` subclass: a wrong value must fail at the site that misuses it
    rather than degrade into an unauthenticated request reported as "your
    token was revoked". Widening the reload escape into "anything shaped a bit
    like a credential" would give that away.
    """
    import core.canvas_auth as ca

    class CanvasCredential:                 # right name, nothing else
        pass

    with pytest.raises(TypeError):
        ca.coerce(CanvasCredential(), 'https://x.instructure.com')
    with pytest.raises(TypeError):
        ca.coerce(12345, 'https://x.instructure.com')
    with pytest.raises(TypeError):
        ca.coerce({'cookies': {}}, 'https://x.instructure.com')
