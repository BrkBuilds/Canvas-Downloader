"""Trading a browser session for a long-lived access token.

A Canvas session is a **day**, rolling. A token a student mints for themselves
is up to **120 days** (``TokensController::MAXIMUM_EXPIRATION_DURATION``), and
Canvas will mint one for a signed-in session through a documented API. Where an
institution allows it that is the whole answer to "why am I signing in again".

Read out of Canvas' own source on 2026-09-12, because every behaviour asserted
here is Canvas' and not ours:

* ``POST /api/v1/users/self/tokens`` -> ``TokensController#create``, with
  ``token[purpose]`` required and, for a student-only account, ``expires_at``
  required and capped at 120 days.
* ``before_action :require_password_session`` - a session established from a
  ``pseudonym_credentials`` remember-me cookie may NOT mint. Canvas answers
  that with a redirect to the login page, not an error.
* ``protect_from_forgery with: :exception`` - a cookie-authenticated request is
  in-app, so the CSRF check applies. Canvas' own client echoes the
  ``_csrf_token`` cookie in ``X-CSRF-Token`` after ``decodeURIComponent``.
* ``AccessToken``'s policy skips the account restrictions when
  ``session[:root_account]`` is absent, which is every Bearer request - so a
  token must never be used to mint a FIRST token.

Everything here drives the REAL functions against a REAL local HTTP server
answering the way Canvas does. No mocks, no network, no credentials.
"""
from __future__ import annotations

import ast
import datetime as dt
import http.server
import json
import threading
import types
from pathlib import Path
from urllib.parse import quote

import pytest

from core import token_mint
from core.canvas_auth import from_cookies, from_token

_ROOT = Path(__file__).resolve().parents[1]
_AUTH_SRC = (_ROOT / "ui" / "auth.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# A Canvas that behaves the way the source says it does
# ---------------------------------------------------------------------------

#: What Canvas actually puts in the cookie: base64, so it carries `+` and `=`,
#: and a cookie value is percent-encoded. The header must carry the DECODED
#: form or the forgery check fails - this value is what makes that testable.
CSRF_RAW = 'aB3+cD4/eF5=='
CSRF_COOKIE = quote(CSRF_RAW, safe='')


class _Canvas:
    """A Canvas whose answer to the mint is whatever the test asked for."""

    def __init__(self, mode='allow'):
        self.mode = mode
        self.requests = []          # (method, path, headers, body)
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a):
                pass

            def _send(self, code, body=b'', ctype='application/json',
                      extra=()):
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                for k, v in extra:
                    self.send_header(k, v)
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _record(self, body=b''):
                outer.requests.append((self.command, self.path,
                                       dict(self.headers), body))

            def do_GET(self):
                self._record()
                if self.path.startswith('/profile/settings'):
                    if outer.mode == 'remembered':
                        # require_password_session REDIRECTS, it does not error.
                        return self._send(302, extra=[('Location', '/login')])
                    return self._send(
                        200, b'<html>settings</html>', 'text/html',
                        [('Set-Cookie',
                          f'_csrf_token={CSRF_COOKIE}; path=/')])
                if self.path.startswith('/login'):
                    return self._send(200, b'<html>sign in</html>', 'text/html')
                return self._send(404, b'{}')

            def do_POST(self):
                n = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(n) if n else b''
                self._record(raw)
                if outer.mode == 'remembered_post':
                    # WHERE CANVAS ACTUALLY DOES THIS.
                    # `require_password_session` is a before_action on
                    # TokensController, so a remembered session is redirected
                    # on the POST - and following that redirect lands on the
                    # sign-in page answering 200.
                    return self._send(302, extra=[('Location', '/login')])
                if outer.mode == 'blocked':
                    # grants_right?(:create) said no: the account has turned
                    # self-service tokens off for this user.
                    return self._send(401, b'{"status":"unauthorized"}')
                if outer.mode == 'csrf':
                    return self._send(422, b'{"errors":"InvalidAuthenticityToken"}')
                if outer.mode == 'no_value':
                    # A 200 that creates nothing. Canvas returns the token
                    # value ONLY on creation.
                    return self._send(200, json.dumps(
                        {'id': 9, 'expires_at': '2027-01-01T00:00:00Z'}
                    ).encode())
                body = json.loads(raw or b'{}')
                return self._send(200, json.dumps({
                    'id': 4242,
                    'token': 'NEWLY-MINTED-TOKEN',
                    'purpose': body.get('token', {}).get('purpose'),
                    'expires_at': body.get('token', {}).get('expires_at'),
                }).encode())

            def do_PUT(self):
                n = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(n) if n else b''
                self._record(raw)
                if outer.mode == 'capped':
                    # Accepted, expiry not moved. An account policy.
                    return self._send(200, json.dumps(
                        {'id': 4242, 'expires_at': _iso(3)}).encode())
                if outer.mode == 'no_expiry':
                    return self._send(200, json.dumps({'id': 4242}).encode())
                body = json.loads(raw or b'{}')
                return self._send(200, json.dumps({
                    'id': 4242,
                    'expires_at': body.get('token', {}).get('expires_at'),
                }).encode())

        self.server = http.server.HTTPServer(('127.0.0.1', 0), H)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def sent(self, method):
        return [r for r in self.requests if r[0] == method]


def _iso(days):
    when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    return when.strftime('%Y-%m-%dT%H:%M:%SZ')


@pytest.fixture
def canvas(request):
    srv = _Canvas(getattr(request, 'param', 'allow'))
    yield srv
    srv.stop()


def _session_cred(base):
    return from_cookies({'canvas_session': 'LIVE'}, base, user_agent='UA')


# ---------------------------------------------------------------------------
# 1. A token must never mint another token
# ---------------------------------------------------------------------------

def test_a_token_credential_may_NOT_mint(canvas):
    """The single most important refusal in this module.

    ``AccessToken``'s policy reads the account restrictions out of
    ``session[:root_account]``, which a Bearer request does not have - Canvas'
    own comment is *"if the session wasn't set up correctly, just ignore the
    additional restrictions"*. So minting with a token would appear to work at
    an institution that has deliberately switched self-service tokens OFF, and
    would be walking round a setting an administrator chose.
    """
    result = token_mint.mint(from_token('SOME-TOKEN'), canvas.base)
    assert result.reason == token_mint.NO_SESSION
    assert not result
    assert not canvas.requests, (
        "a token credential reached Canvas, so the account restrictions an "
        "administrator set were bypassed")


def test_an_unusable_session_never_reaches_canvas(canvas):
    """No cookie is the signed-out state, not an error worth a round trip."""
    assert token_mint.mint(from_cookies({}, canvas.base), canvas.base).reason \
        == token_mint.NO_SESSION
    assert not canvas.requests


# ---------------------------------------------------------------------------
# 2. The happy path, and what Canvas is actually asked for
# ---------------------------------------------------------------------------

def test_a_session_mints_a_token(canvas):
    result = token_mint.mint(_session_cred(canvas.base), canvas.base)
    assert result, result.detail
    assert result.reason == token_mint.OK
    assert result.token == 'NEWLY-MINTED-TOKEN'
    assert result.token_id == '4242'
    assert not result.permanent


def test_the_request_carries_a_purpose_and_an_expiry_inside_canvas_cap(canvas):
    """Canvas REQUIRES both for a student-only account, and refuses an expiry
    more than 120 days out against its OWN clock - so asking for exactly 120
    fails on a machine a few minutes fast."""
    token_mint.mint(_session_cred(canvas.base), canvas.base)
    body = json.loads(canvas.sent('POST')[0][3])['token']
    assert body['purpose'] == token_mint.PURPOSE

    asked = dt.datetime.strptime(body['expires_at'], '%Y-%m-%dT%H:%M:%SZ')
    asked = asked.replace(tzinfo=dt.timezone.utc)
    days = (asked - dt.datetime.now(dt.timezone.utc)).total_seconds() / 86400
    # A HALF-DAY floor, not `< MAXIMUM_DAYS`. The first version of this
    # assertion was `118 < days < MAXIMUM_DAYS`, and asking for the full 120
    # satisfies it: the value computed is 119.9999-something, which really is
    # less than 120. The mutation pass caught that, and it is the whole point
    # of the constant - Canvas compares against ITS clock, so a laptop a few
    # minutes fast asks for more than the cap and is refused outright.
    assert days <= token_mint.MAXIMUM_DAYS - 0.5, (
        f"asked Canvas for {days:.4f} days against a {token_mint.MAXIMUM_DAYS}"
        " day cap. There is no margin for clock skew, so this fails on any "
        "machine whose clock leads Canvas'.")
    assert days > 118, f"asked for only {days:.1f} days"


def test_a_caller_asking_for_MORE_than_the_cap_is_clamped(canvas):
    """Not a hypothetical: the one number a future caller would change."""
    token_mint.mint(_session_cred(canvas.base), canvas.base, days=3650)
    body = json.loads(canvas.sent('POST')[0][3])['token']
    asked = dt.datetime.strptime(body['expires_at'], '%Y-%m-%dT%H:%M:%SZ')
    asked = asked.replace(tzinfo=dt.timezone.utc)
    days = (asked - dt.datetime.now(dt.timezone.utc)).total_seconds() / 86400
    assert days <= token_mint.MAXIMUM_DAYS


def test_the_csrf_token_is_echoed_back_DECODED(canvas):
    """The cookie is percent-encoded because it is base64; Canvas' own client
    does `decodeURIComponent` before sending the header. Sending the raw cookie
    value fails the forgery check, and a 422 is not a failure mode anyone would
    guess at from the outside."""
    token_mint.mint(_session_cred(canvas.base), canvas.base)
    headers = canvas.sent('POST')[0][2]
    assert headers.get('X-CSRF-Token') == CSRF_RAW, (
        "the CSRF header was not the decoded cookie value")
    assert '%' not in headers.get('X-CSRF-Token', ''), "still percent-encoded"


def test_the_csrf_token_is_fetched_from_canvas_not_the_credential(canvas):
    """`to_storable` narrows the STORED credential to the session cookies, so a
    restored one has no CSRF token at all. Asking Canvas is one round trip and
    is correct on every launch rather than only the one the user signed in on.
    """
    token_mint.mint(_session_cred(canvas.base), canvas.base)
    assert any(r[1].startswith('/profile/settings')
               for r in canvas.sent('GET')), (
        "nothing asked Canvas for a CSRF token, so a renewal would fail for a "
        "reason that has nothing to do with the account")


def test_browser_mode_sends_NO_authorization_header(canvas):
    """Canvas' `load_pseudonym_from_access_token` runs BEFORE it looks at the
    session, so a Bearer it cannot accept raises there - a bogus or empty token
    alongside a perfectly good cookie produces 401."""
    token_mint.mint(_session_cred(canvas.base), canvas.base)
    for method, _path, headers, _body in canvas.requests:
        assert 'Authorization' not in headers, (
            f"{method} carried an Authorization header in browser mode")


def test_the_session_user_agent_is_kept(canvas):
    """An institution's WAF reads a client that changes mid-session as
    suspicious."""
    token_mint.mint(_session_cred(canvas.base), canvas.base)
    assert canvas.sent('POST')[0][2].get('User-Agent') == 'UA'


# ---------------------------------------------------------------------------
# 3. Every way it can decline, told apart
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("canvas,reason,permanent", [
    ('blocked', token_mint.BLOCKED, True),
    ('csrf', token_mint.CSRF_REJECTED, False),
    ('remembered', token_mint.NEEDS_FRESH_LOGIN, False),
    ('no_value', token_mint.UNEXPECTED, False),
], indirect=['canvas'])
def test_each_refusal_is_named(canvas, reason, permanent):
    """Distinguishing them is the whole point. "Your school does not allow
    this" must never be retried and must never be reported as a fault; the
    others are worth saying out loud."""
    result = token_mint.mint(_session_cred(canvas.base), canvas.base)
    assert not result
    assert result.reason == reason, result.detail
    assert result.permanent is permanent


@pytest.mark.parametrize("canvas", ['remembered'], indirect=True)
def test_a_login_redirect_is_not_read_as_permission(canvas):
    """`require_password_session` REDIRECTS to the login page rather than
    answering 401, so a status-only classifier would read a remembered session
    as an institution that forbids tokens - and record that permanently."""
    result = token_mint.mint(_session_cred(canvas.base), canvas.base)
    assert result.reason == token_mint.NEEDS_FRESH_LOGIN
    assert not result.permanent, (
        "a remembered session was recorded as a permanent institutional no, "
        "so this user can never be offered a token again")
    assert not canvas.sent('POST'), (
        "the mint was attempted after Canvas had already asked for a sign-in")


def test_an_unreachable_canvas_is_NOT_a_fact_about_the_account():
    """Offline, a captive portal, a university TLS intercept. Recording that as
    "your school does not allow tokens" would be permanent."""
    result = token_mint.mint(
        from_cookies({'canvas_session': 'X'}, 'http://127.0.0.1:9', ''),
        'http://127.0.0.1:9')
    assert result.reason == token_mint.NETWORK
    assert not result.permanent


# ---------------------------------------------------------------------------
# 4. Keeping it alive, without pulling the rug out from under the running app
# ---------------------------------------------------------------------------

def test_extend_does_NOT_regenerate(canvas):
    """THE safety property of the renewal.

    `token[regenerate]` replaces the token VALUE, and the value is what this
    session, every download thread, the sync executor and the Panopto runner
    are already holding. A renewal meant to save a login in three months would
    log the user out of their own running app - and it would do it silently,
    mid-download.
    """
    result = token_mint.extend('LIVE-TOKEN', canvas.base, '4242')
    assert result.reason == token_mint.OK, result.detail
    body = json.loads(canvas.sent('PUT')[0][3])['token']
    assert 'regenerate' not in body, (
        "the renewal regenerates the token, invalidating the value the "
        "running app is using")
    assert 'expires_at' in body


def test_extend_returns_no_token_value_so_nothing_writes_an_empty_one(canvas):
    """Nothing was replaced, so there is nothing to store. A caller that read
    a truthy result as "here is a new token to save" would save ''."""
    result = token_mint.extend('LIVE-TOKEN', canvas.base, '4242')
    assert result.reason == token_mint.OK
    assert result.token == ''
    assert not result, "a truthy extend result invites the caller to store ''"


def test_extend_authenticates_with_a_bearer_token(canvas):
    token_mint.extend('LIVE-TOKEN', canvas.base, '4242')
    assert canvas.sent('PUT')[0][2].get('Authorization') == 'Bearer LIVE-TOKEN'


@pytest.mark.parametrize("canvas", ['capped'], indirect=True)
def test_an_expiry_the_institution_CAPS_is_its_own_answer(canvas):
    """Canvas took the request and left the expiry short - an institution
    capping the grant, which `set_permanent_expiration` reads off the
    developer key. It is NOT a failure (the token still works) and it is NOT a
    success (nothing moved), so it gets its own reason: the caller records it
    and stops asking, instead of spending a request and a warning on every
    launch for the rest of the token's life.
    """
    result = token_mint.extend('LIVE-TOKEN', canvas.base, '4242')
    assert result.reason == token_mint.CAPPED
    assert result.permanent, (
        "a capped grant is a settled fact about the institution; retrying it "
        "means a wasted request every launch")
    assert result.expires_at, "the caller still needs to know the real expiry"


# ---------------------------------------------------------------------------
# 5b. The granted lifetime differs by INSTITUTION
# ---------------------------------------------------------------------------

def test_the_renewal_window_scales_to_what_the_institution_GRANTED():
    """120 days is only the ceiling a student may ASK for.

    `AccessToken#set_permanent_expiration` takes the real lifetime from
    `developer_key.tokens_expire_in`, so the grant differs per institution. A
    FIXED 21-day window is wrong for every school that grants less than 21
    days: the token is "due for renewal" from the moment it is minted, so
    every launch spends a request, is capped straight back, and logs about it.
    """
    assert token_mint.renewal_threshold_days(119) == token_mint.RENEW_WITHIN_DAYS
    assert token_mint.renewal_threshold_days(30) == 10
    assert round(token_mint.renewal_threshold_days(7), 2) == 2.33
    # Unknown grant - an older stored token - keeps the previous behaviour.
    assert token_mint.renewal_threshold_days(None) == token_mint.RENEW_WITHIN_DAYS
    assert token_mint.renewal_threshold_days(0) == token_mint.RENEW_WITHIN_DAYS


@pytest.mark.parametrize("granted,left,due", [
    # The case the fixed window got wrong: a short grant, freshly minted.
    (7, 7, False),
    (7, 6, False),
    (7, 2, True),
    # A long grant behaves exactly as before.
    (119, 100, False),
    (119, 15, True),
    # Unknown grant falls back to the ceiling.
    (None, 100, False),
    (None, 15, True),
])
def test_a_short_grant_is_not_due_the_moment_it_is_minted(granted, left, due):
    assert token_mint.due_for_renewal(_iso(left), granted) is due


def test_a_fresh_grant_of_ANY_length_is_never_immediately_due():
    """The property that matters, over the whole plausible range rather than
    the handful of points above. A grant that is due on the day it is issued
    is a request on every launch, for ever."""
    for granted in (1, 2, 3, 7, 14, 30, 60, 90, 119, 120, 365):
        assert token_mint.due_for_renewal(_iso(granted), granted) is False, (
            f"a {granted}-day grant is due for renewal the moment it is "
            f"minted")


@pytest.mark.parametrize("canvas", ['no_expiry'], indirect=True)
def test_a_token_with_no_expiry_at_all_is_a_success(canvas):
    """A legitimate answer for a user who is not student-only, and one that
    needs no further renewal ever."""
    result = token_mint.extend('LIVE-TOKEN', canvas.base, '4242')
    assert result.reason == token_mint.OK
    assert result.expires_at == ''


def test_extend_refuses_without_an_id(canvas):
    assert token_mint.extend('T', canvas.base, '').reason == token_mint.NO_SESSION
    assert not canvas.requests


# ---------------------------------------------------------------------------
# 5. When to renew
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("days,due", [
    (0.5, True), (5, True), (20, True), (22, False), (100, False),
    # Already expired. Still "due" - trying and failing costs one request and
    # tells the log why; not trying guarantees a sign-in.
    (-3, True),
])
def test_due_for_renewal(days, due):
    assert token_mint.due_for_renewal(_iso(days)) is due


@pytest.mark.parametrize("value", ['', 'not-a-date', 'tomorrow', None])
def test_an_unreadable_expiry_is_never_renewed(value):
    """`None` means "do not renew on this", never "renew now". An unreadable
    expiry on a token that still works is not a reason to touch it."""
    assert token_mint.days_left(value) is None
    assert token_mint.due_for_renewal(value) is False


def test_an_expiry_without_a_zone_is_read_as_utc():
    """Canvas stamps a trailing Z, but a naive value must not raise: comparing
    a naive and an aware datetime is a TypeError, which is the trap this repo
    already records for `_is_canvas_newer`."""
    naive = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=60)
             ).strftime('%Y-%m-%dT%H:%M:%S')
    assert token_mint.days_left(naive) is not None
    assert token_mint.due_for_renewal(naive) is False


# ---------------------------------------------------------------------------
# 6. A credential must never be readable from a log line
# ---------------------------------------------------------------------------

def test_a_mint_result_redacts_its_token():
    """This object reaches log lines and the health record through ordinary
    %r formatting, and a minted token is a complete login."""
    r = token_mint.MintResult(token='SECRET-abc123', token_id='7',
                              expires_at='2027-01-01', reason=token_mint.OK)
    assert 'SECRET' not in repr(r)
    assert '****' in repr(r)
    # ...and the id and expiry ARE shown, because that is what a log line is
    # for and neither authenticates anything.
    assert '7' in repr(r) and '2027-01-01' in repr(r)


# ---------------------------------------------------------------------------
# 7. The call site: an upgrade must never leave the user worse off
# ---------------------------------------------------------------------------

def _fn(name):
    tree = ast.parse(_AUTH_SRC)
    return next(f for f in ast.walk(tree)
                if isinstance(f, ast.FunctionDef) and f.name == name)


def _upgrade_with(monkeypatch, result, *, store_ok=True):
    """Drive `_upgrade_to_access_token` with a fixed mint outcome."""
    import ui.auth as auth

    class _SS(dict):
        pass

    ss = _SS({'api_url': 'https://x.instructure.com'})
    written = {}
    deleted = []
    monkeypatch.setattr(auth, 'st', types.SimpleNamespace(
        session_state=ss, toast=lambda *a, **k: None))
    monkeypatch.setattr(auth, '_token_upgrade_enabled', lambda: True)
    monkeypatch.setattr(auth, 'read_config_for_update', lambda: ({}, True))
    monkeypatch.setattr(auth, 'write_config_atomically',
                        lambda cfg: written.update(cfg) or True)
    monkeypatch.setattr(auth, 'store_token', lambda _u, _t: store_ok)
    monkeypatch.setattr(auth, 'delete_browser_credential', deleted.append)
    monkeypatch.setattr(token_mint, 'mint', lambda *a, **k: result)
    ok = auth._upgrade_to_access_token(
        from_cookies({'canvas_session': 'LIVE'}, 'https://x.instructure.com'))
    return ok, ss, written, deleted


def test_a_successful_upgrade_switches_the_app_to_the_token(monkeypatch):
    ok, ss, written, deleted = _upgrade_with(monkeypatch, token_mint.MintResult(
        token='T-123', token_id='9', expires_at=_iso(119), reason=token_mint.OK))
    assert ok is True
    assert ss['api_token'] == 'T-123'
    assert written['auth_method'] == 'token'
    assert written['minted_token_id'] == '9', (
        "without the id the token can never renew itself")
    assert written['minted_token_expires_at'], (
        "Canvas never tells you the expiry again - a renewal needs it stored")
    assert deleted == ['https://x.instructure.com'], (
        "the superseded session cookie was left on disk, which is a "
        "credential the user can neither see nor revoke")


def test_a_token_that_cannot_be_STORED_is_not_adopted(monkeypatch):
    """Swapping a credential that survives a restart for one that does not is
    worse than not upgrading. The session is still live in memory either way.
    """
    ok, ss, written, deleted = _upgrade_with(
        monkeypatch,
        token_mint.MintResult(token='T-123', token_id='9', reason=token_mint.OK),
        store_ok=False)
    assert ok is False
    assert not deleted, "the browser session was deleted with nothing to replace it"
    assert written.get('auth_method') != 'token'


def test_a_permanent_refusal_is_remembered(monkeypatch):
    """The answer is a setting on the Canvas account and cannot change between
    two sign-ins on the same afternoon. Asking again every time would put a
    pointless request, and a scary 401, in front of exactly the users this app
    was built for."""
    ok, _ss, written, _deleted = _upgrade_with(monkeypatch, token_mint.MintResult(
        reason=token_mint.BLOCKED, detail='HTTP 401'))
    assert ok is False
    assert written.get('token_upgrade_blocked') is True


@pytest.mark.parametrize("reason", [
    token_mint.NETWORK, token_mint.CSRF_REJECTED, token_mint.NEEDS_FRESH_LOGIN,
    token_mint.UNEXPECTED,
])
def test_a_TRANSIENT_refusal_is_NOT_remembered(monkeypatch, reason):
    """Recording one of these would permanently deny a long-lived credential to
    a user whose wifi dropped at the wrong moment."""
    ok, _ss, written, _deleted = _upgrade_with(
        monkeypatch, token_mint.MintResult(reason=reason))
    assert ok is False
    assert 'token_upgrade_blocked' not in written


def test_a_failed_upgrade_leaves_the_browser_session_to_be_persisted():
    """`adopt_pending_browser_login` must fall through to
    `_persist_browser_login` on a declined upgrade, or a sign-in at a
    token-restricted school is not saved at all - which is every CBS student.
    """
    fn = _fn("adopt_pending_browser_login")
    src = ast.unparse(fn)
    assert "_upgrade_to_access_token" in src
    assert "_persist_browser_login" in src
    upgrade_at = src.index("_upgrade_to_access_token")
    persist_at = src.index("_persist_browser_login")
    assert upgrade_at < persist_at, (
        "the session is persisted before the upgrade is attempted, so a "
        "successful upgrade leaves an unrevocable cookie on disk too")
    # The upgrade's return must be the thing that skips the persist.
    ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If)
           and "_upgrade_to_access_token" in ast.dump(n.test)]
    assert ifs, ("the upgrade's answer is ignored, so either the session is "
                 "never saved or it is saved alongside the token")


# ---------------------------------------------------------------------------
# 8. The renewal runs once, off the script thread, and releases its claim
# ---------------------------------------------------------------------------

def test_the_renewal_never_runs_on_the_script_thread():
    """One or two Canvas round trips during init is the blocking-init failure
    `.claude/rules/macos.md` documents: the window stays empty for as long as
    it takes."""
    fn = _fn("maybe_extend_minted_token")
    threads = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
               and getattr(getattr(n.func, 'value', None), 'id', '') == 'threading'
               and getattr(n.func, 'attr', '') == 'Thread']
    assert threads, "the token renewal blocks the Streamlit script thread"
    assert any(kw.arg == 'daemon' and kw.value.value is True
               for t in threads for kw in t.keywords), (
        "a non-daemon renewal thread can hold the app open on exit")


def test_a_renewal_thread_that_cannot_START_releases_its_claim():
    """The trap `.claude/rules/data-safety.md` records for the Panopto model
    download and the CUDA provisioner: a "running" flag set before the only
    thing that would ever clear it. Here it would kill renewal for the whole
    process, so the token eventually expires and the user signs in again."""
    fn = _fn("maybe_extend_minted_token")
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    resets = [n for h in handlers for n in ast.walk(h)
              if isinstance(n, ast.Assign)
              and any(getattr(t, 'id', '') == '_token_extend_started'
                      for t in n.targets)
              and n.value.value is False]
    assert resets, (
        "a thread that fails to start leaves the once-per-process claim set, "
        "so the token can never renew for the life of the process")


def test_the_renewal_runs_at_most_once_per_process(monkeypatch):
    """`app.py` calls it on every rerun."""
    import ui.auth as auth
    monkeypatch.setattr(auth, '_token_extend_started', False)
    started = []
    monkeypatch.setattr(auth.threading, 'Thread',
                        lambda **kw: types.SimpleNamespace(
                            start=lambda: started.append(kw.get('name'))))
    for _ in range(5):
        auth.maybe_extend_minted_token()
    assert len(started) == 1, f"started {len(started)} renewal threads"


def test_app_py_actually_calls_the_renewal():
    """Nothing else in the app does, so without this line the whole renewal is
    dead code - which is exactly what `refresh_silently` was for two passes.
    """
    src = (_ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', '') == 'maybe_extend_minted_token']
    assert calls, "app.py never calls maybe_extend_minted_token"
    assert "from ui.auth import maybe_extend_minted_token" in src


@pytest.mark.parametrize("canvas", ['remembered_post'], indirect=True)
def test_a_POST_redirected_to_the_login_page_is_a_FRESH_LOGIN_not_a_refusal(canvas):
    """The shape real Canvas produces, and the one that needs the extra check.

    ``require_password_session`` is a ``before_action`` on
    ``TokensController``, so the redirect happens on the POST rather than on
    the page fetch before it - and following that redirect, which every HTTP
    client does by default, ends on the sign-in page answering **200**. A
    classifier gated on the status alone therefore never runs at all: the code
    falls through to the JSON parse and reports "Canvas returned no token
    value" about an entirely ordinary remembered session.

    Found by the mutation pass rather than by reading, and it was a real defect
    in `mint` and not only a gap in this file.
    """
    result = token_mint.mint(_session_cred(canvas.base), canvas.base)
    assert not result
    assert result.reason == token_mint.NEEDS_FRESH_LOGIN, (
        f"a remembered session was reported as {result.reason!r} "
        f"({result.detail!r}), which names the wrong cause in the one place "
        "this would ever be diagnosed from")
    assert not result.permanent, (
        "recorded as a permanent institutional no, so this user can never be "
        "offered a long-lived token again")
    assert canvas.sent('POST'), "the mint was never actually attempted"


# ---------------------------------------------------------------------------
# 9. The disclosure must not displace the page's stylesheets
# ---------------------------------------------------------------------------

def test_the_upgrade_ARMS_the_notice_instead_of_emitting_it(monkeypatch):
    """`st.toast` writes to the event root container, which Streamlit
    reconciles by INDEX and which every style-only `st.html()` also writes to.
    `_upgrade_to_access_token` runs from near the TOP of app.py, so a
    conditional toast there shifts every later stylesheet onto its neighbour's
    host - on exactly one run, the one that signs the user in.
    """
    import ui.auth as auth

    toasts = []

    class _SS(dict):
        pass

    ss = _SS({'api_url': 'https://x.instructure.com'})
    monkeypatch.setattr(auth, 'st', types.SimpleNamespace(
        session_state=ss, toast=lambda *a, **k: toasts.append(a)))
    monkeypatch.setattr(auth, '_token_upgrade_enabled', lambda: True)
    monkeypatch.setattr(auth, 'read_config_for_update', lambda: ({}, True))
    monkeypatch.setattr(auth, 'write_config_atomically', lambda cfg: True)
    monkeypatch.setattr(auth, 'store_token', lambda _u, _t: True)
    monkeypatch.setattr(auth, 'delete_browser_credential', lambda _u: None)
    monkeypatch.setattr(token_mint, 'mint', lambda *a, **k: token_mint.MintResult(
        token='T', token_id='9', expires_at=_iso(119), reason=token_mint.OK))

    assert auth._upgrade_to_access_token(
        from_cookies({'canvas_session': 'L'}, 'https://x.instructure.com')) is True
    assert not toasts, (
        "the upgrade emitted a toast from the top of the run, displacing every "
        "stylesheet after it")
    assert ss.get('token_upgrade_notice') is True, "nothing will tell the user"


def test_the_notice_is_emitted_once_and_says_where_to_revoke(monkeypatch):
    """It wrote something to the user's Canvas account, so it must name the
    token and where to delete it. One shot, or it reappears on every rerun."""
    import ui.auth as auth

    toasts = []

    class _SS(dict):
        pass

    ss = _SS({'token_upgrade_notice': True})
    monkeypatch.setattr(auth, 'st', types.SimpleNamespace(
        session_state=ss, toast=lambda msg, **k: toasts.append(msg)))

    auth.render_pending_token_notice()
    assert len(toasts) == 1
    assert token_mint.PURPOSE in toasts[0], "the token is not named"
    assert 'Approved Integrations' in toasts[0], (
        "the user is not told where to revoke a token this app created in "
        "their Canvas account")

    auth.render_pending_token_notice()
    assert len(toasts) == 1, "the notice repeats on every rerun"


def test_the_notice_is_emitted_LAST_in_app_py():
    """After every stylesheet on the page. Appending to the end of the event
    container's list cannot displace anything; writing into the middle can.

    The app already uses this ordering for its dialogs, for the same reason -
    `.claude/rules/streamlit-ui.md`: "Invoke a dialog after every
    event-container write on the page".
    """
    src = (_ROOT / "app.py").read_text(encoding="utf-8")
    assert "render_pending_token_notice()" in src, (
        "app.py never emits the notice, so the disclosure never appears")
    notice_at = src.index("render_pending_token_notice()")
    # The shell bridge is documented as "Emitted LAST"; the notice goes after.
    bridge_at = src.index("inject_app_shell_bridge()")
    assert notice_at > bridge_at, (
        "the notice is emitted before the end of the page, so it can still "
        "shift a later style-only st.html onto its neighbour's host")
    # Nothing may follow it that writes to the event container.
    tail = src[notice_at:]
    assert "st.html(" not in tail and "st.toast(" not in tail.replace(
        "render_pending_token_notice()", ""), (
        "something writes to the event container after the notice")


def test_the_caller_records_what_the_institution_GRANTED(monkeypatch):
    """Without it the renewal window has nothing to scale to, and falls back
    to a ceiling that is wrong for every school granting less."""
    ok, _ss, written, _deleted = _upgrade_with(monkeypatch, token_mint.MintResult(
        token='T', token_id='9', expires_at=_iso(7), reason=token_mint.OK))
    assert ok is True
    granted = written.get('minted_token_days')
    assert granted is not None, (
        "the granted lifetime was not recorded, so a 7-day token renews on "
        "every launch for ever")
    assert 6 < granted <= 7.1, granted
    assert written.get('token_source') == 'minted', (
        "nothing marks this token as one the app created, so the reconnect "
        "screen tells a user who never pasted a token to paste a new one")


def _extend_run(monkeypatch, config, result):
    """Drive `maybe_extend_minted_token` synchronously. Returns (calls, saved)."""
    import ui.auth as auth
    calls = []
    saved = {}

    monkeypatch.setattr(auth, '_token_extend_started', False)
    monkeypatch.setattr(auth.threading, 'Thread',
                        lambda target=None, **kw: types.SimpleNamespace(
                            start=lambda: target()))
    monkeypatch.setattr(auth, 'read_config_for_update',
                        lambda: (dict(config), True))
    monkeypatch.setattr(auth, 'write_config_atomically',
                        lambda cfg: saved.update(cfg) or True)
    monkeypatch.setattr(auth, 'keyring_get_without_prompting',
                        lambda *a: ('LIVE-TOKEN', False))

    def _extend(token, api_url, token_id, **kw):
        calls.append(kw)
        return result

    monkeypatch.setattr(token_mint, 'extend', _extend)
    auth.maybe_extend_minted_token()
    return calls, saved


_MINTED = {'minted_token_id': '9', 'api_url': 'https://x.instructure.com'}


def test_the_renewal_passes_the_granted_lifetime_through(monkeypatch):
    """Otherwise `extend` judges "did the expiry move" against the ceiling and
    reports a perfectly good capped grant as a failure."""
    cfg = dict(_MINTED, minted_token_expires_at=_iso(1), minted_token_days=7)
    calls, _saved = _extend_run(monkeypatch, cfg, token_mint.MintResult(
        expires_at=_iso(7), reason=token_mint.OK))
    assert calls, "the renewal never ran"
    assert calls[0].get('granted_days') == 7


def test_a_CAPPED_institution_is_asked_only_ONCE(monkeypatch):
    """The answer cannot change between two launches, and asking again spends
    a request and a log line every single time for the life of the token."""
    cfg = dict(_MINTED, minted_token_expires_at=_iso(1), minted_token_days=7)
    calls, saved = _extend_run(monkeypatch, cfg, token_mint.MintResult(
        expires_at=_iso(7), reason=token_mint.CAPPED))
    assert len(calls) == 1
    assert saved.get('minted_token_capped') is True, (
        "a capped grant was not remembered, so every launch retries it")

    # ...and the next launch does not ask at all.
    calls2, _ = _extend_run(monkeypatch, dict(cfg, minted_token_capped=True),
                            token_mint.MintResult(reason=token_mint.OK))
    assert not calls2, "a capped institution was asked again"


def test_a_token_the_user_pasted_is_never_touched(monkeypatch):
    """The renewal has no business regenerating or re-dating a credential the
    user created themselves in their own Canvas settings."""
    calls, saved = _extend_run(
        monkeypatch, {'api_url': 'https://x.instructure.com'},
        token_mint.MintResult(reason=token_mint.OK))
    assert not calls
    assert not saved
