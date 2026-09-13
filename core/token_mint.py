"""Turn a Canvas browser session into a long-lived access token.

Why this exists
---------------
A Canvas browser session lasts a **day**, rolling (``expire_after: 1.day``).
An access token a student mints for themselves lasts up to **120 days** -
Canvas' own cap, ``TokensController::MAXIMUM_EXPIRATION_DURATION`` - and Canvas
will mint one for a signed-in session through a documented API:

    POST /api/v1/users/self/tokens   token[purpose], token[expires_at]

So the one interactive sign-in a user performs can be upgraded, on the spot,
into a credential that outlives it by four months. That is the difference
between a login screen every day or two and a login screen once a term.

It is strictly better than the session it replaces, in three ways at once:

* **It lasts.** 120 days against one day.
* **It is revocable.** A harvested session cookie is not: the user cannot see
  it and cannot withdraw it. A minted token appears in Canvas under
  Account -> Settings -> Approved Integrations, named, with a delete button.
  That closes the one security gap the 2026-09-12 review could only state.
* **It has full parity.** Panopto needs a token to mint an LTI launch and a
  session cannot do it at all (see ``.claude/rules/browser-login.md``), and
  session auth drops the ``verifier=`` from file URLs embedded in exported
  pages. Both of those stop being true the moment this succeeds.

What it CANNOT do, and why that is the normal case
--------------------------------------------------
Three account settings switch self-service tokens off, and a growing number of
institutions have done it - which is precisely why the browser-session login
exists at all. From ``AccessToken``'s policy:

* ``limit_personal_access_tokens`` - nobody may mint their own.
* ``restrict_personal_access_tokens_from_students`` - a user whose roles are
  only student and/or observer may not. This one is aimed exactly at our users.
* ``can_manage_own_access_tokens?`` - the outer gate.

**CBS, the institution this whole feature was built for, has it switched off.**
So minting is an UPGRADE and never a requirement: every failure path here
leaves the caller holding exactly the session it came in with, and the reason
is reported precisely enough to tell "your school does not allow this" apart
from "something went wrong".

Two things about Canvas that are easy to get wrong here
-------------------------------------------------------
**CSRF.** ``ApplicationController`` has ``protect_from_forgery with:
:exception`` and Canvas authenticates this request by COOKIE, so it is an
in-app request and the forgery check applies - unlike a Bearer-token request,
which skips it. Canvas' own JavaScript answers it by echoing the
``_csrf_token`` cookie back in the ``X-CSRF-Token`` header, and the cookie is
**percent-encoded** (it is base64, so it contains ``+`` and ``=``), so it has
to be unquoted first. Canvas' client does ``decodeURIComponent``; this does
``urllib.parse.unquote``. Sending the raw cookie value fails the check.

**A remember-me session may not mint.** ``require_password_session`` rejects
any session that was established from a ``pseudonym_credentials`` cookie -
Canvas will not let a "remembered" login change security settings. A session
harvested from a login the user just performed is fine; one that was silently
renewed from a remember-me token is not, and Canvas answers that with a
redirect to the login page rather than an error. Hence ``'needs_fresh_login'``.
"""

from __future__ import annotations

import datetime as _dt
import logging
from urllib.parse import unquote, urljoin

logger = logging.getLogger(__name__)

#: Canvas' own hard cap for a student-only account, from
#: ``TokensController::MAXIMUM_EXPIRATION_DURATION = 120.days``. Asking for
#: more is refused with "Expiration date cannot be more than 120 days in the
#: future", so this is a ceiling and not a preference.
MAXIMUM_DAYS = 120

#: What we actually ask for. One day under the cap, because the comparison
#: Canvas makes is ``expiration_date > 120.days.from_now`` against **its**
#: clock: a machine a few minutes fast would ask for 120 days and be refused
#: for it. A day of margin costs nothing and removes a whole class of
#: "it works on my laptop".
REQUEST_DAYS = 119

#: Renew once the token has less than this left. Generous on purpose: the app
#: only gets to renew on a launch, and a user who opens it every few weeks
#: must still never reach the expiry.
#:
#: A CEILING, never the whole rule - see :func:`due_for_renewal`. **The granted
#: lifetime differs from institution to institution**, because
#: `AccessToken#set_permanent_expiration` takes it from
#: `developer_key.tokens_expire_in` (and a site-admin cap can shorten it
#: further); 120 days is only the maximum Canvas will let a student ASK for.
#: A fixed 21-day window is wrong for every institution that grants less than
#: 21 days: the token is "due for renewal" from the moment it is minted, so
#: every launch spends a request, is capped straight back, and logs a warning
#: about an expiry that did not move. Measured against no institution yet -
#: this is read out of Canvas' source, which is why the rule is written to be
#: correct for any grant rather than tuned for one.
RENEW_WITHIN_DAYS = 21

#: The other half of the rule: renew once this fraction of the granted lifetime
#: is left. A third leaves two chances to succeed before expiry for any grant
#: length, which matters because the app only gets to try when it is launched.
RENEW_FRACTION = 1.0 / 3.0

#: What the user will see in Canvas under Approved Integrations. It has to say
#: what it is without them having to remember granting it.
PURPOSE = 'Canvas Downloader'

#: Total budget for the mint. Two requests, one of which Canvas answers from a
#: cold cache, and a login that is already finished is waiting on it.
TIMEOUT = 20

#: Reasons a mint did not happen. Distinguishing them is the whole point: the
#: first two are permanent facts about the institution and must never be
#: retried or reported as a fault, and the rest are worth saying out loud.
BLOCKED = 'blocked_by_institution'
NEEDS_FRESH_LOGIN = 'needs_fresh_login'
CSRF_REJECTED = 'csrf_rejected'
NO_SESSION = 'no_session'
NETWORK = 'network'
#: Canvas accepted an extension and capped it: this institution will not grant
#: more. A settled fact about the account, so the caller stops asking - but NOT
#: a failure, and the token it describes still works.
CAPPED = 'capped_by_institution'
UNEXPECTED = 'unexpected'
OK = 'ok'

#: Reasons that are a settled property of the account, not a transient
#: failure. Recording one means "do not ask this institution again".
PERMANENT = (BLOCKED, CAPPED)


class MintResult:
    """What came back. Falsy unless a token was actually minted.

    A class rather than a tuple because four of the five call sites care about
    exactly one field and unpacking a 4-tuple at each of them is how the third
    one gets the order wrong.
    """

    __slots__ = ('token', 'token_id', 'expires_at', 'reason', 'detail')

    def __init__(self, token: str = '', token_id: str = '',
                 expires_at: str = '', reason: str = UNEXPECTED,
                 detail: str = '') -> None:
        self.token = token
        self.token_id = token_id
        self.expires_at = expires_at
        self.reason = reason
        self.detail = detail

    def __bool__(self) -> bool:
        return bool(self.token)

    @property
    def permanent(self) -> bool:
        """Whether re-trying could ever answer differently."""
        return self.reason in PERMANENT

    def __repr__(self) -> str:
        """Redacted, by the same rule as ``CanvasCredential.__repr__``.

        A minted token is a complete login and this object reaches log lines
        and the health record through ordinary ``%r`` formatting.
        """
        return (f"MintResult(reason={self.reason!r}, "
                f"token={'****' if self.token else ''!r}, "
                f"token_id={self.token_id!r}, expires_at={self.expires_at!r})")


def _expiry_iso(days: int) -> str:
    """An ISO-8601 UTC instant *days* from now, the way Canvas parses it."""
    when = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=days)
    return when.strftime('%Y-%m-%dT%H:%M:%SZ')


def _csrf_from_jar(jar) -> str:
    """The ``_csrf_token`` cookie, percent-decoded ready for the header.

    Empty when Canvas has not set one, which is not an error here: the caller
    sends the header only if there is something to send, and Canvas' own
    failure message for a missing one is clearer than anything invented here.
    """
    for name in ('_csrf_token',):
        try:
            raw = jar.get(name)
        except Exception:                                       # noqa: BLE001
            raw = None
        if raw:
            return unquote(raw)
    return ''


def _looks_like_login(response) -> bool:
    """Did Canvas answer with a sign-in page instead of doing the thing?

    ``require_password_session`` does not render an error - it redirects to
    ``login_url``. Reuses the engine's own predicate so this cannot come to
    disagree with the download path about what a login redirect looks like.
    """
    try:
        from core.canvas_auth import is_login_redirect, visited_urls
        return is_login_redirect(visited_urls(response))
    except Exception:                                           # noqa: BLE001
        return False


def _classify(response) -> 'MintResult':
    """Turn a non-200 into a reason. Never raises."""
    status = getattr(response, 'status_code', 0)
    body = ''
    try:
        body = (response.text or '')[:400]
    except Exception:                                           # noqa: BLE001
        pass

    if _looks_like_login(response):
        return MintResult(reason=NEEDS_FRESH_LOGIN, detail=f'HTTP {status}')
    if status in (401, 403):
        # `grants_right?(:create)` said no, which at this endpoint means the
        # account has turned self-service tokens off for this user. Permanent.
        return MintResult(reason=BLOCKED, detail=f'HTTP {status}')
    if status == 422:
        return MintResult(reason=CSRF_REJECTED, detail=f'HTTP {status}: {body}')
    return MintResult(reason=UNEXPECTED, detail=f'HTTP {status}: {body}')


def _session_for(credential, api_url: str):
    """A ``requests.Session`` carrying the browser session and nothing else.

    Deliberately goes through the credential's own installer rather than
    setting cookies here: that method is where the domain scoping lives, and a
    second copy of it is how a login gets forwarded to a content CDN.
    """
    import requests
    session = requests.Session()
    credential.apply_to_requests_session(session)
    session.headers.update(credential.auth_headers())
    return session


def mint(credential, api_url: str, *, purpose: str = PURPOSE,
         days: int = REQUEST_DAYS) -> MintResult:
    """Ask Canvas for a long-lived access token for this signed-in session.

    *credential* must be a usable BROWSER credential; a token cannot mint
    another token on an account whose institution restricts them (the policy
    skips the account gates for token requests, so it would appear to work and
    then bypass a setting an administrator deliberately set).

    Never raises. Every failure is a ``MintResult`` whose ``reason`` says what
    happened, because the caller's job in all of them is identical: keep the
    session and carry on.
    """
    try:
        from core.canvas_auth import BROWSER
        if getattr(credential, 'kind', None) != BROWSER or not credential.usable:
            return MintResult(reason=NO_SESSION,
                              detail='not a usable browser session')
    except Exception as e:                                      # noqa: BLE001
        return MintResult(reason=NO_SESSION, detail=repr(e))

    base = (api_url or '').rstrip('/')
    if not base:
        return MintResult(reason=NO_SESSION, detail='no Canvas address')
    if '://' not in base:
        base = f'https://{base}'

    try:
        session = _session_for(credential, base)
    except Exception as e:                                      # noqa: BLE001
        logger.warning("Could not build a session to mint a token: %s", e,
                       exc_info=True)
        return MintResult(reason=UNEXPECTED, detail=repr(e))

    try:
        # One HTML request first, purely to be handed a `_csrf_token`. Reading
        # it from the harvested cookies instead would work only on the launch
        # the user signed in on: `to_storable` narrows the STORED copy to the
        # session cookies, so a restored credential has no CSRF token and a
        # renewal would fail for a reason that has nothing to do with the
        # account. Asking Canvas is one round trip and always correct.
        landing = session.get(urljoin(base + '/', 'profile/settings'),
                              timeout=TIMEOUT, allow_redirects=True)
        if _looks_like_login(landing):
            return MintResult(reason=NEEDS_FRESH_LOGIN,
                              detail='Canvas asked for a sign-in')
        csrf = _csrf_from_jar(session.cookies)

        headers = {'Accept': 'application/json',
                   'X-Requested-With': 'XMLHttpRequest'}
        if csrf:
            headers['X-CSRF-Token'] = csrf

        response = session.post(
            urljoin(base + '/', 'api/v1/users/self/tokens'),
            json={'token': {'purpose': purpose,
                            'expires_at': _expiry_iso(min(days, MAXIMUM_DAYS))}},
            headers=headers, timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:                                      # noqa: BLE001
        # Offline, a captive portal, a TLS intercept. Not a fact about the
        # account, so it must not be recorded as one.
        logger.info("Could not reach Canvas to mint an access token: %s", e)
        return MintResult(reason=NETWORK, detail=repr(e))
    finally:
        try:
            session.close()
        except Exception:                                       # noqa: BLE001
            pass

    # `or _looks_like_login(...)` is load-bearing and was missing.
    # `require_password_session` is a `before_action` on TokensController, so a
    # session established from a remember-me cookie is REDIRECTED on the POST
    # itself - and following that redirect (which every HTTP client does)
    # lands on the sign-in page answering **200**. Gating on the status alone
    # therefore never reached `_classify`, fell through to the JSON parse, and
    # reported "Canvas returned no token value" about a perfectly ordinary
    # remembered session. Harmless to the user (both reasons are transient) and
    # wrong in the log, which is where this would be diagnosed from.
    # Found by the mutation pass, not by reading.
    if getattr(response, 'status_code', 0) != 200 or _looks_like_login(response):
        result = _classify(response)
        if result.reason == BLOCKED:
            logger.info("This Canvas account may not create its own access "
                        "tokens (%s); keeping the browser session.",
                        result.detail)
        else:
            logger.warning("Could not mint a Canvas access token (%s): %s",
                           result.reason, result.detail)
        return result

    try:
        data = response.json() or {}
    except Exception as e:                                      # noqa: BLE001
        return MintResult(reason=UNEXPECTED, detail=f'unreadable JSON: {e!r}')

    token = str(data.get('token') or '')
    if not token:
        # Canvas returns the token value ONLY on creation. No value means it
        # did not create one, whatever the status said.
        return MintResult(reason=UNEXPECTED,
                          detail='Canvas returned no token value')
    result = MintResult(token=token,
                        token_id=str(data.get('id') or ''),
                        expires_at=str(data.get('expires_at') or ''),
                        reason=OK)
    logger.info("Minted a Canvas access token (id=%s, expires %s).",
                result.token_id or '?', result.expires_at or 'never')
    return result


def days_left(expires_at: str) -> float | None:
    """Days until *expires_at*, or ``None`` if it cannot be read.

    ``None`` means "do not renew on this", never "renew now": an unreadable
    expiry on a token that still works is not a reason to touch it.
    """
    if not expires_at:
        return None
    text = str(expires_at).strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        when = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    return (when - _dt.datetime.now(_dt.timezone.utc)).total_seconds() / 86400.0


def renewal_threshold_days(granted_days: float | None) -> float:
    """How little must be left before a token of this grant is renewed.

    ``granted_days`` is what the institution actually gave, not what was asked
    for. Unknown (an older stored token, or a grant with no expiry) falls back
    to the ceiling, which is the previous behaviour exactly.
    """
    if not granted_days or granted_days <= 0:
        return float(RENEW_WITHIN_DAYS)
    return min(float(RENEW_WITHIN_DAYS), granted_days * RENEW_FRACTION)


def due_for_renewal(expires_at: str,
                    granted_days: float | None = None) -> bool:
    """Whether a minted token is close enough to expiry to be rolled forward.

    Scaled to the GRANTED lifetime, because it differs by institution. With a
    fixed window a 7-day grant is due the moment it is minted, so every launch
    spends a request and logs a warning for the life of the token.
    """
    left = days_left(expires_at)
    if left is None:
        return False
    return left < renewal_threshold_days(granted_days)


def extend(token: str, api_url: str, token_id: str, *,
           days: int = REQUEST_DAYS,
           granted_days: float | None = None) -> MintResult:
    """Push a minted token's expiry out, WITHOUT changing its value.

    This is the piece that turns "120 days" into "as long as you keep using
    the app": no session, no window, no sign-in. ``PUT
    /api/v1/users/self/tokens/:id`` with only ``token[expires_at]`` runs
    Canvas' ``update`` action, which assigns the new expiry and saves.

    **Deliberately not ``regenerate``.** Passing it replaces the token VALUE,
    and the value is the one the running app, every download thread, the sync
    executor and the Panopto runner are already holding - so a renewal that
    rotated would log the user out of their own running session to save them a
    login in three months. Extending keeps every live copy valid, which is
    also what lets this run on a background thread at all.

    It works with Bearer auth, and that is not an accident of ours:
    ``AccessToken``'s policy reads the account restrictions out of
    ``session[:root_account]``, which a Bearer request does not have - Canvas'
    own comment is *"if the session wasn't set up correctly, just ignore the
    additional restrictions"*. Extending something an administrator already
    allowed is fair use of that. Minting a FIRST token that way would be
    walking round a setting they chose, which is why :func:`mint` refuses a
    token credential.

    Answers a ``MintResult`` whose ``expires_at`` is what Canvas now reports.
    ``token`` is left empty on purpose: nothing was replaced, so there is
    nothing to store, and a caller that treated a truthy result as "here is a
    new token to save" would write an empty one. Check ``reason == OK``.
    """
    if not token or not token_id:
        return MintResult(reason=NO_SESSION, detail='no token to extend')
    base = (api_url or '').rstrip('/')
    if not base:
        return MintResult(reason=NO_SESSION, detail='no Canvas address')
    if '://' not in base:
        base = f'https://{base}'

    # ASK THE CREDENTIAL for the header, never format one here. `canvas_auth`
    # is the only place in the app that writes `Bearer`, and a census test
    # enforces it - which is how this line was caught being a second copy.
    # The rule is not cosmetic: that method is also where "browser mode sends
    # NO Authorization header" lives, and a hand-rolled header is a site that
    # cannot inherit a later correction to either rule.
    from core.canvas_auth import from_token
    headers = dict(from_token(token).auth_headers())
    headers['Accept'] = 'application/json'

    try:
        import requests
        response = requests.put(
            urljoin(base + '/', f'api/v1/users/self/tokens/{token_id}'),
            json={'token': {'expires_at': _expiry_iso(min(days, MAXIMUM_DAYS))}},
            headers=headers, timeout=TIMEOUT)
    except Exception as e:                                      # noqa: BLE001
        logger.info("Could not reach Canvas to extend the access token: %s", e)
        return MintResult(reason=NETWORK, detail=repr(e))

    if getattr(response, 'status_code', 0) != 200:
        result = _classify(response)
        logger.warning("Could not extend the Canvas access token (%s): %s",
                       result.reason, result.detail)
        return result
    try:
        data = response.json() or {}
    except Exception as e:                                      # noqa: BLE001
        return MintResult(reason=UNEXPECTED, detail=f'unreadable JSON: {e!r}')

    fresh = str(data.get('expires_at') or '')
    if not fresh:
        # A token with no expiry at all is a legitimate answer for a user who
        # is not student-only, and it needs no further renewal ever. Say so
        # rather than reporting a failure that would be retried every launch.
        logger.info("The Canvas access token now reports no expiry.")
        return MintResult(token_id=token_id, expires_at='', reason=OK)
    if not due_for_renewal(fresh, granted_days):
        logger.info("Extended the Canvas access token (id=%s, now expires %s).",
                    token_id, fresh)
        return MintResult(token_id=token_id, expires_at=fresh, reason=OK)
    # Canvas took the request and did NOT move the expiry far enough out - an
    # institution capping the grant. Reporting OK would re-try on every single
    # launch for the rest of the token's life, so this reason is one the caller
    # RECORDS rather than retries.
    logger.info("Canvas accepted the extension but this institution caps the "
                "expiry at %s; not asking again.", fresh)
    return MintResult(reason=CAPPED, expires_at=fresh,
                      detail='the institution caps this token'"'"'s lifetime')
