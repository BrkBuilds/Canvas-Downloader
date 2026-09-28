"""An expired Canvas SESSION must read as a sign-in problem, not a network blip.

Owner report 2026-09-28: the app opened straight onto the course selector with
no name in the sidebar and an amber "We couldn't reach Canvas" where the
courses should be. The stored browser session had expired, and nothing noticed.

The mechanism, measured against `cbscanvas.instructure.com/api/v1/users/self`
the same day - every case is 401 with `WWW-Authenticate: Bearer
realm="canvas-lms"`:

    expired/invalid session   {"status":"unauthenticated","errors":[{"message":"user authorisation required"}]}
    revoked token             {"errors":[{"message":"Invalid access token."}]}

canvasapi raises `InvalidAccessToken` for a 401 that carries that header, and
`InvalidAccessToken` is a SIBLING of `Unauthorized`, not a subclass. So
`validate_token`'s `except Unauthorized` never fired against real Canvas, and
`is_auth_error` matched a token only because "invalid access token" happened
to be in its wording list. The session's "user authorisation required" matched
nothing: the restore trusted it optimistically, the course fetch showed the
network card, and the 30-second re-check got the same answer for ever.

**Why the suite never saw it**: the fake Canvas in `test_browser_login.py`
answers 401 WITHOUT the header, so canvasapi raised `Unauthorized` there and
every test took the one branch real Canvas never reaches. The server below
sends the header, and `test_the_fixture_really_raises_what_Canvas_raises` is
the control that proves it does.
"""
from __future__ import annotations

import http.server
import json
import threading
import types

import pytest
from canvasapi.exceptions import InvalidAccessToken, Unauthorized

import ui.auth as auth
from core.canvas_auth import from_cookies, from_token
from core.canvas_logic import CanvasManager, is_auth_error

#: Canvas' own bodies, as measured. Do not paraphrase: the spelling is the bug.
SESSION_BODY = {"status": "unauthenticated",
                "errors": [{"message": "user authorisation required"}]}
TOKEN_BODY = {"errors": [{"message": "Invalid access token."}]}


class _RealShapedCanvas(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_GET(self):
        auth_header = self.headers.get("Authorization")
        body = json.dumps(TOKEN_BODY if auth_header else SESSION_BODY).encode()
        self.send_response(401)
        if self.server.www_authenticate:
            self.send_header("WWW-Authenticate", 'Bearer realm="canvas-lms"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(www_authenticate: bool):
    srv = http.server.HTTPServer(("127.0.0.1", 0), _RealShapedCanvas)
    srv.www_authenticate = www_authenticate
    srv.base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def canvas():
    srv = _serve(www_authenticate=True)
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _session(base):
    return from_cookies({"canvas_session": "EXPIRED"}, base)


# ── The control: the fixture must reproduce what real Canvas makes canvasapi do

def test_the_fixture_really_raises_what_Canvas_raises(canvas):
    """Without this, every test below could pass against a server that makes
    canvasapi raise `Unauthorized` - which is exactly how the old fixture hid
    the defect."""
    cm = CanvasManager(_session(canvas.base), canvas.base)
    with pytest.raises(InvalidAccessToken):
        cm.canvas.get_current_user()


def test_without_the_header_canvasapi_raises_the_OTHER_type():
    """The other half of the control: the header is what decides the type, so
    a fake that omits it tests a different program."""
    srv = _serve(www_authenticate=False)
    try:
        cm = CanvasManager(_session(srv.base), srv.base)
        with pytest.raises(Unauthorized):
            cm.canvas.get_current_user()
    finally:
        srv.shutdown()
        srv.server_close()


# ── The classification ──────────────────────────────────────────────────────

def test_the_EXCEPTION_is_an_auth_error(canvas):
    """The course selector hands `is_auth_error` the exception object itself.
    This is the path that painted "We couldn't reach Canvas"."""
    cm = CanvasManager(_session(canvas.base), canvas.base)
    try:
        cm.canvas.get_current_user()
    except Exception as exc:                                    # noqa: BLE001
        assert is_auth_error(exc), f"{type(exc).__name__}: {exc}"
    else:
        pytest.fail("the fake Canvas accepted an expired session")


def test_the_TYPE_decides_whatever_Canvas_writes():
    """The wording is Canvas', and a self-hosted or localised Canvas can say
    anything. What canvasapi's type records is the STATUS and the header, which
    is the fact - so it must not depend on the keyword list below it."""
    assert is_auth_error(InvalidAccessToken([{"message": "Bitte anmelden"}]))


@pytest.mark.parametrize("text", [
    "user authorisation required",       # what Canvas actually says
    "user authorization required",       # the other spelling, same meaning
])
def test_Canvas_own_wording_is_an_auth_error(text):
    assert is_auth_error(text)


def test_a_403_is_still_NOT_an_auth_error():
    """The widening must not swallow a permission problem on a valid sign-in."""
    assert not is_auth_error("403 Forbidden: user not permitted")


@pytest.mark.parametrize("make", [_session, lambda b: from_token("1234~REVOKED")],
                         ids=["session", "token"])
def test_validate_token_reports_the_refusal_as_one(canvas, make):
    ok, msg = CanvasManager(make(canvas.base), canvas.base).validate_token()
    assert not ok
    assert is_auth_error(msg), msg
    # The normalised branch, not the generic one: the login screen routes on
    # "Unauthorized", and the old generic branch returned Canvas' bare text.
    assert msg.startswith("Unauthorized - "), msg


def test_validate_token_names_the_route_the_user_signed_in_with(canvas):
    _ok, msg = CanvasManager(_session(canvas.base), canvas.base).validate_token()
    assert "Canvas sign-in" in msg and "Access Token" not in msg, msg


# ── The launch: an expired stored session is REFUSED, never optimistic ─────

class _SS(dict):
    __getattr__ = dict.get


def test_an_expired_stored_session_is_refused_not_trusted(monkeypatch, canvas):
    ss = _SS(api_url=canvas.base)
    monkeypatch.setattr(auth, "st", types.SimpleNamespace(session_state=ss))
    # Nothing may be written to the real credential store from a test.
    monkeypatch.setattr(auth, "store_browser_credential", lambda *a, **k: True)

    verdict = auth._adopt_restored_credential(_session(canvas.base))

    assert verdict == "refused", verdict
    assert not ss.get("is_authenticated"), (
        "an expired session was signed in optimistically - the owner's report")
    assert not ss.get(auth.SESSION_CONFIRMED_KEY)
