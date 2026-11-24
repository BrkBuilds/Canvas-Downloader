"""Two follow-ups to v2.0.4, asked for by the product owner on 2026-11-24.

1. An expired EXTENSION sign-in is renewed through the extension, not through
   the app's own window. Both routes produce the same credential and only
   `auth_method` was recorded, so the renewal always opened the window - whose
   web view profile an extension user has never signed in to, so it asked for
   the full institutional password.

2. Logging out revokes, in Canvas, the token the APP minted for itself. It used
   to stay valid for up to 120 days after the student signed out. A token the
   student pasted is never touched.

The revoke is driven against a real local HTTP server, like the rest of the
token tests: no mocks of `requests`, no network, no credentials.
"""
from __future__ import annotations

import ast
import http.server
import json
import threading
from pathlib import Path

import pytest

import ui.auth as auth
from core import token_mint

_ROOT = Path(__file__).resolve().parent.parent
_SRC = (_ROOT / "ui" / "auth.py").read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)


def _fn(name):
    return next(n for n in ast.walk(_TREE)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(fn, name):
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == name]


class _St:
    def __init__(self, state=None):
        self.session_state = dict(state or {})


# ---------------------------------------------------------------------------
# 1. The route is recorded, and the renewal follows it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("adopter, route", [
    ("adopt_pending_handoff", "ROUTE_EXTENSION"),
    ("adopt_pending_browser_login", "ROUTE_WINDOW"),
])
def test_each_sign_in_records_its_OWN_route(adopter, route):
    calls = _calls(_fn(adopter), "_record_signin_route")
    assert len(calls) == 1, f"{adopter} records its route {len(calls)} times"
    assert ast.unparse(calls[0].args[0]) == route


def test_the_extension_route_is_recorded_BEFORE_the_token_upgrade():
    """An extension sign-in that was upgraded to a minted token must also be
    renewed through the extension when that token expires."""
    fn = _fn("adopt_pending_handoff")
    record = _calls(fn, "_record_signin_route")[0].lineno
    upgrade = _calls(fn, "_upgrade_to_access_token")[0].lineno
    assert record < upgrade


@pytest.mark.parametrize("stored, expected", [
    ({"browser_signin_route": "extension"}, "extension"),
    ({"browser_signin_route": "window"}, "window"),
    ({}, "window"),                                   # recorded before 2.0.4
    ({"browser_signin_route": "nonsense"}, "window"),
])
def test_an_unknown_route_renews_the_way_it_always_did(monkeypatch, stored,
                                                       expected):
    monkeypatch.setattr(auth, "read_config_for_update", lambda: (stored, True))
    assert auth._signin_route() == expected


def test_an_UNREADABLE_settings_file_answers_window(monkeypatch):
    def boom():
        raise OSError("locked")
    monkeypatch.setattr(auth, "read_config_for_update", boom)
    assert auth._signin_route() == auth.ROUTE_WINDOW


def test_recording_a_route_never_overwrites_an_unreadable_file(monkeypatch):
    written = []
    monkeypatch.setattr(auth, "read_config_for_update", lambda: ({}, False))
    monkeypatch.setattr(auth, "write_config_atomically",
                        lambda c: written.append(c) or True)
    auth._record_signin_route(auth.ROUTE_EXTENSION)
    assert written == []


def _restore_branch():
    """The `if st.session_state.pop('browser_restore_pending', False):` block."""
    fn = _fn("render_login_page")
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and "browser_restore_pending" in ast.unparse(n.test):
            return n
    raise AssertionError("the renewal branch is gone")


def test_an_expired_EXTENSION_sign_in_never_opens_the_apps_window():
    branch = _restore_branch()
    first = branch.body[0]
    assert isinstance(first, ast.If)
    assert "ROUTE_EXTENSION" in ast.unparse(first.test)
    ext_src = "\n".join(ast.unparse(s) for s in first.body)
    assert "handoff_renewal_offer" in ext_src
    assert "begin_browser_signin" not in ext_src, (
        "an extension user is sent to the app's own window, which asks for the "
        "full institutional password")
    # The window route is still there for everyone else.
    assert "begin_browser_signin" in ast.unparse(first.orelse[0])


def test_the_renewal_does_NOT_open_the_listener_by_itself():
    """The listener opens only when the student presses the button: that is
    the consent the handoff's whole threat model rests on."""
    first = _restore_branch().body[0]
    ext_src = "\n".join(ast.unparse(s) for s in first.body)
    assert "begin_browser_handoff" not in ext_src
    assert "handoff.start" not in ext_src


def test_the_card_offers_the_renewal_by_the_buttons_REAL_name(monkeypatch):
    monkeypatch.setattr(auth, "st", _St({"handoff_renewal_offer": True}))
    html = auth._handoff_card_html()
    assert f"<b>{auth.HANDOFF_START_LABEL}</b>" in html
    assert "run out" in html


def test_without_an_offer_the_idle_card_says_nothing(monkeypatch):
    monkeypatch.setattr(auth, "st", _St())
    assert auth._handoff_card_html() == "<div class='login-handoff'></div>"


def test_taking_up_the_offer_or_resetting_clears_it():
    assert "handoff_renewal_offer" in ast.unparse(_fn("begin_browser_handoff"))
    assert "handoff_renewal_offer" in ast.unparse(_fn("_reset_browser_login_state"))


def test_the_extension_card_OPENS_when_it_has_something_to_say():
    for n in ast.walk(_fn("render_login_page")):
        if (isinstance(n, ast.Call) and ast.unparse(n.func) == "st.expander"
                and n.args and getattr(n.args[0], "value", "") ==
                "Use the browser extension instead"):
            expanded = next(k for k in n.keywords if k.arg == "expanded")
            src = ast.unparse(expanded.value)
            assert "handoff_renewal_offer" in src and "handoff_waiting" in src
            return
    raise AssertionError("the extension disclosure is gone")


# ---------------------------------------------------------------------------
# 2. Logout revokes the token the app minted
# ---------------------------------------------------------------------------

class _Canvas:
    """Answers DELETE /api/v1/users/self/tokens/:id the way Canvas does."""

    def __init__(self, status=200):
        self.status = status
        self.requests = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_DELETE(self):
                outer.requests.append((self.path,
                                       self.headers.get("Authorization")))
                body = json.dumps({"id": 4242}).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def canvas():
    servers = []

    def make(status=200):
        c = _Canvas(status)
        servers.append(c)
        return c
    yield make
    for c in servers:
        c.close()


def test_revoke_DELETEs_that_exact_token_with_itself(canvas):
    c = canvas(200)
    assert token_mint.revoke("tok-123", c.base, "4242") is True
    assert c.requests == [("/api/v1/users/self/tokens/4242", "Bearer tok-123")]


@pytest.mark.parametrize("status", [401, 404])
def test_a_token_that_is_ALREADY_gone_counts_as_revoked(canvas, status):
    """Reporting a failure there would be a warning about a logout that
    worked."""
    assert token_mint.revoke("tok", canvas(status).base, "4242") is True


def test_a_refusal_is_reported_as_not_revoked(canvas):
    assert token_mint.revoke("tok", canvas(500).base, "4242") is False


def test_revoke_without_a_token_or_id_sends_nothing(canvas):
    c = canvas(200)
    assert token_mint.revoke("", c.base, "4242") is False
    assert token_mint.revoke("tok", c.base, "") is False
    assert c.requests == []


def test_an_unreachable_canvas_never_raises():
    assert token_mint.revoke("tok", "http://127.0.0.1:9", "4242") is False


def _logout_with(monkeypatch, config, token="tok-123"):
    calls = []
    monkeypatch.setattr(auth, "st", _St({"api_token": token,
                                         "api_url": "https://x.instructure.com"}))
    monkeypatch.setattr(auth, "read_config_for_update", lambda: (config, True))
    monkeypatch.setattr(token_mint, "revoke",
                        lambda *a: calls.append(a) or True)
    auth._revoke_minted_token_on_logout()
    return calls


def test_logout_revokes_a_MINTED_token(monkeypatch):
    calls = _logout_with(monkeypatch, {"token_source": "minted",
                                       "minted_token_id": "4242"})
    assert calls == [("tok-123", "https://x.instructure.com", "4242")]


def test_logout_NEVER_revokes_a_token_the_student_pasted(monkeypatch):
    """It is theirs, and may be used by other tools too."""
    assert _logout_with(monkeypatch, {"minted_token_id": "4242"}) == []
    assert _logout_with(monkeypatch, {"token_source": "pasted",
                                      "minted_token_id": "4242"}) == []


def test_a_browser_SESSION_is_never_sent_as_a_token(monkeypatch):
    """`api_token` holds a credential OBJECT in browser mode; only a string is
    a token."""
    calls = _logout_with(monkeypatch, {"token_source": "minted",
                                       "minted_token_id": "4242"},
                         token=object())
    assert calls == []


def test_logout_revokes_BEFORE_it_deletes_the_token():
    """The token is the credential that authorises its own deletion."""
    fn = _fn("_render_authenticated_nav_bottom")
    revoke = _calls(fn, "_revoke_minted_token_on_logout")
    assert len(revoke) == 1
    deletes = [n.lineno for n in _calls(fn, "_safe_keyring_delete")
               if n.lineno > revoke[0].lineno - 10]
    assert deletes and revoke[0].lineno < min(deletes)


def test_logout_forgets_the_minted_bookkeeping():
    fn = _fn("_render_authenticated_nav_bottom")
    src = ast.unparse(fn)
    assert "for _minted_key in _MINTED_KEYS" in src
