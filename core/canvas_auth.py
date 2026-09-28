"""One credential, two ways of proving it.

Canvas Downloader can authenticate in two ways, and **nothing below this module
is allowed to know which one is in play**:

* ``token``   - a Canvas Access Token the user generated, sent as
  ``Authorization: Bearer <token>``. The original mechanism.
* ``browser`` - the session cookies of a real Canvas login, harvested from the
  app's own embedded web view (WebView2 on Windows, WKWebView on macOS). This
  is what every Canvas browser extension does, and it is the only mechanism
  that still works at an institution which has turned off personal access
  token creation (``limit_personal_access_tokens`` /
  ``restrict_personal_access_tokens_from_students``, shipped by Instructure in
  September 2025 and widely switched on after the April 2026 breach).

Why a credential OBJECT and not two code paths
----------------------------------------------
Every authenticated call in this app already funnels through exactly one
channel: ``CanvasManager(api_key, api_url)``. There are 13 construction sites.
Had "am I on cookies?" been asked at each of them, the next auth fix would have
landed on some and not others - the single most expensive recurring defect in
this codebase. So the *value* carries the answer instead: ``coerce()`` turns
whatever those 13 sites pass into a ``CanvasCredential``, and the five places
that actually build an HTTP client ask the credential for headers and cookies
rather than formatting a Bearer string themselves.

That is also why this is not a ``str`` subclass. A ``str`` subclass would have
let every existing site keep working *silently* - right up until something
called ``.strip()`` on it, got a plain ``str`` back, and degraded to an
unauthenticated request that fails as "your token was revoked". A distinct type
fails loudly at the one place that misuses it.

Cookie scoping is a security boundary, not a detail
---------------------------------------------------
Canvas file URLs redirect off the Canvas host onto a CDN
(``*.canvas-user-content.com``, inst-fs signed URLs). Those hosts must never
receive the session cookie: it is a full login credential for the user's
account. Both client builders below therefore install cookies into a jar that
is **scoped to the Canvas host**, so the redirect drops them by construction
rather than by us remembering to. A bare ``cookies={...}`` dict on either
``requests`` or ``aiohttp`` has no domain and is sent to every host it is
redirected to, which is exactly the leak this avoids.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

#: Credential kinds. Stored in config, so treat the strings as a wire format.
TOKEN = 'token'
BROWSER = 'browser'

#: The cookie Canvas' session actually lives in.
#:
#: ``canvas_session`` is what Instructure's production estate sets - measured
#: 2026-09-11 against ``cbscanvas.instructure.com``:
#: ``Set-Cookie: canvas_session=...; path=/; secure; httponly; samesite=none``.
#: ``_normandy_session`` is the name in the open-source default
#: (``config/initializers/session_store.rb``), which a self-hosted Canvas keeps
#: because Instructure overrides the key from Consul config rather than in code.
#: Both are accepted so a self-hosted instance is not silently unsupported.
SESSION_COOKIE_NAMES = ('canvas_session', '_normandy_session')

#: Canvas' own sign-in routes. Everything under here means "who are you?".
#: ``/login``, ``/login/canvas``, ``/login/saml/3``, ``/login/cas`` ...
_LOGIN_PATH_PREFIX = '/login'


def is_login_redirect(visited_urls) -> bool:
    """True when a request was diverted to Canvas' sign-in page.

    **This is what an expired session looks like everywhere except the API**,
    and getting it wrong is silent data corruption rather than an error.
    Measured 2026-09-12 against real Canvas, with no credential at all:

    ==================================  =================  ====================
    request                             revoked TOKEN      expired SESSION
    ==================================  =================  ====================
    ``/api/v1/...``                     401 JSON           401 JSON
    ``/courses/<id>/files/<id>/down..`` **401**            **302 -> /login**
    ``/courses/<id>/modules/items/..``  302 -> /login      302 -> /login
    ==================================  =================  ====================

    So the API is at parity on STATUS. It was NOT at parity in this app until
    2026-09-28: Canvas sends ``WWW-Authenticate`` on every API 401, so
    canvasapi raises ``InvalidAccessToken`` (a sibling of ``Unauthorized``,
    not a subclass), and the session's body - "user authorisation required" -
    matched nothing :func:`core.canvas_logic.is_auth_error` looked for. An
    expired session was therefore read as a network failure. See that
    function's docstring for the measurement. The
    file download is NOT. Follow that 302 - which every HTTP client does by
    default - and the chain ends at the institution's identity provider serving
    **HTTP 200** and 45 KB of HTML login page. A downloader that trusts a 200
    writes that into ``lecture.pdf``.

    The signal is the CHAIN, not the final response: a legitimate Canvas file
    download also redirects, onto the content CDN, and ends 200. The difference
    is that an unauthenticated one passes through ``/login`` first, every time.

    *visited_urls* is every URL the request actually walked, first to last -
    ``[h.url for h in resp.history] + [resp.url]`` for both ``aiohttp`` and
    ``requests``, which is why this takes strings rather than a response and
    serves the two clients from one definition.

    Matched on PATH alone, deliberately. The host is not checked because a
    vanity address (``canvas.cbs.dk``) can land the chain on the canonical host
    (``cbscanvas.instructure.com``), and requiring the host to match the one we
    hold would make this answer False in exactly the configuration it exists
    for. No Canvas content URL is served under ``/login``.
    """
    for raw in visited_urls or ():
        try:
            path = urlparse(str(raw)).path or ''
        except Exception:                                       # noqa: BLE001
            continue
        path = path.rstrip('/').lower()
        if path == _LOGIN_PATH_PREFIX or path.startswith(_LOGIN_PATH_PREFIX + '/'):
            return True
    return False


def visited_urls(response) -> list:
    """Every URL *response* walked, first to last. Client-agnostic.

    ``aiohttp`` and ``requests`` both expose ``.history`` (the redirects) and
    ``.url`` (where it ended), so one reader serves both and the two can never
    disagree about what the chain was.
    """
    out = []
    try:
        out.extend(str(h.url) for h in (getattr(response, 'history', None) or ()))
    except Exception:                                           # noqa: BLE001
        pass
    try:
        if getattr(response, 'url', None) is not None:
            out.append(str(response.url))
    except Exception:                                           # noqa: BLE001
        pass
    return out


def cookie_domain_matches(host: str, domain: str) -> bool:
    """Whether a cookie whose ``Domain`` is *domain* belongs to *host*.

    The rule a browser uses: an exact host match, or *host* is a subdomain of
    *domain*. A leading dot is the old wire spelling of the same thing and
    carries no extra meaning.

    This exists because the web view's own scoping cannot be trusted to be a
    host match on both platforms. pywebview's **macOS** backend filters the
    cookie store with ``if domain not in self.url`` - a plain SUBSTRING test
    against the URL the window was loaded with - so for a window opened on
    ``https://cbscanvas.instructure.com/login`` a cookie belonging to the
    unrelated tenant ``canvas.instructure.com`` passes, because that string
    does occur inside it. The Windows backend asks WebView2 for the current
    URL's cookies and is already correct. Filtering here makes both platforms
    agree, and makes the harvest below safe to widen: a cookie that is not
    Canvas' own must never end up in a jar scoped to the Canvas host, because
    that jar is what decides where it gets sent.
    """
    host = (host or '').strip().lower().rstrip('.')
    domain = (domain or '').strip().lower().lstrip('.').rstrip('.')
    if not host or not domain:
        return False
    return host == domain or host.endswith('.' + domain)


def canvas_host(api_url: str) -> str:
    """Hostname of *api_url*, or ``''`` if it has none.

    Never raises: a malformed URL yields an empty host, and an empty host makes
    :meth:`CanvasCredential.usable` false, so a bad address is reported as "not
    logged in" instead of crashing a download thread.
    """
    if not api_url:
        return ''
    try:
        raw = api_url if '://' in api_url else f'https://{api_url}'
        return (urlparse(raw).hostname or '').strip().lower()
    except Exception as e:                                      # noqa: BLE001
        logger.warning("Could not read a host out of %r: %s", api_url, e)
        return ''


@dataclass(frozen=True)
class CanvasCredential:
    """How to prove who the user is, to one Canvas instance.

    Immutable on purpose. A credential is read from background download
    threads, the sync executor and the Panopto runner concurrently; a value
    that cannot change under them needs no lock. Renewal replaces the object
    rather than mutating it.
    """

    kind: str = TOKEN
    token: str = ''
    #: name -> value, exactly as the web view's cookie store reported them.
    #:
    #: ``hash=False`` is load-bearing, not tidiness. A frozen dataclass derives
    #: ``__hash__`` from its comparable fields, and a ``dict`` is unhashable -
    #: so including it makes the whole credential unhashable, and the app puts
    #: this value in places that hash it. ``core/course_cache.py`` keys its
    #: cache on ``(token, url)``; with an unhashable credential that raises
    #: ``TypeError`` deep inside the fetch, which the UI reports as "We
    #: couldn't reach Canvas" - measured in the real app against real Canvas,
    #: signed in, with the sidebar already showing the user's name.
    #:
    #: Excluding it from the HASH and not from ``__eq__`` is the correct trade:
    #: two credentials for one host hash alike and still compare unequal, which
    #: is an ordinary collision, so a renewed session is still a distinct cache
    #: key rather than silently reusing the old one's courses.
    cookies: Mapping[str, str] = field(default_factory=dict, hash=False)
    #: The User-Agent the session was created under. Sent on every request so
    #: the session keeps looking like the client that logged in - an
    #: institution's WAF reads a client that changes mid-session as suspicious.
    user_agent: str = ''
    #: Host the cookies belong to. Set from the Canvas URL at harvest time.
    host: str = ''

    # ---- state -------------------------------------------------------

    @property
    def is_browser(self) -> bool:
        return self.kind == BROWSER

    @property
    def usable(self) -> bool:
        """Whether this credential carries enough to attempt a request.

        Not a claim that Canvas will accept it - only that sending it is worth
        a round trip. An unusable credential is the "logged out" state.
        """
        if self.kind == BROWSER:
            return bool(self.host) and any(
                self.cookies.get(name) for name in SESSION_COOKIE_NAMES
            )
        return bool(self.token)

    def __bool__(self) -> bool:
        return self.usable

    def __repr__(self) -> str:
        """Redacted. A credential must never be readable from a traceback.

        Tracebacks reach the debug log and the health record, and a session
        cookie is a complete login. ``core/canvas_debug.py`` strips Bearer
        tokens from log lines; this closes the same hole for the object itself.
        """
        if self.kind == BROWSER:
            return (f"CanvasCredential(kind='browser', host={self.host!r}, "
                    f"cookies={len(self.cookies)} redacted)")
        return f"CanvasCredential(kind='token', token='****')"

    # ---- what an HTTP client needs ------------------------------------

    def auth_headers(self) -> dict:
        """Headers that authenticate a request.

        Browser mode deliberately sends **no** ``Authorization`` header, and
        that is load-bearing rather than merely tidy. Canvas'
        ``load_pseudonym_from_access_token`` runs *before* it looks at the
        session, and a token string it cannot accept raises there - so a bogus
        or empty Bearer alongside a perfectly good cookie produces 401. The
        cookie only gets its turn when no token is presented at all.
        """
        headers: dict = {}
        if self.user_agent:
            headers['User-Agent'] = self.user_agent
        if self.kind == TOKEN and self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    def scoped_cookies(self) -> dict:
        """Cookies to install, ``{}`` in token mode."""
        return dict(self.cookies) if self.kind == BROWSER else {}

    def apply_to_requests_session(self, session) -> None:
        """Install this credential on a ``requests.Session``.

        Cookies are set with an explicit ``domain``, so ``requests`` drops them
        on a redirect to the content CDN instead of forwarding a login.
        """
        if self.user_agent:
            session.headers['User-Agent'] = self.user_agent
        if self.kind != BROWSER:
            return
        for name, value in self.cookies.items():
            try:
                session.cookies.set(name, value, domain=self.host, path='/')
            except Exception as e:                              # noqa: BLE001
                # One malformed cookie must not cost the whole session: the
                # others may well be all Canvas needs.
                logger.warning("Could not install cookie %r for %s: %s",
                               name, self.host, e, exc_info=True)

    def requests_cookie_jar(self):
        """A domain-scoped ``RequestsCookieJar``, or ``None`` in token mode.

        For the call sites that use ``requests.get(...)`` directly rather than
        holding a ``Session``. Passing this as ``cookies=`` keeps the domain
        matching that a plain dict would throw away.
        """
        if self.kind != BROWSER or not self.cookies or not self.host:
            return None
        try:
            from requests.cookies import RequestsCookieJar
            jar = RequestsCookieJar()
            for name, value in self.cookies.items():
                jar.set(name, value, domain=self.host, path='/')
            return jar
        except Exception as e:                                  # noqa: BLE001
            logger.error("Could not build a requests cookie jar for %s: %s",
                         self.host, e, exc_info=True)
            raise

    def aiohttp_cookie_jar(self):
        """A domain-scoped ``aiohttp.CookieJar``, or ``None`` in token mode.

        ``aiohttp.ClientSession(cookies={...})`` stores cookies with no domain
        and sends them to every host the session touches, including the file
        CDN. Feeding the jar through ``update_cookies(..., response_url=...)``
        is what attaches the domain, and the domain is what stops the leak.

        MUST be called with a running event loop: ``aiohttp.CookieJar()`` binds
        to one at construction and raises ``RuntimeError`` otherwise. Both call
        sites build their ``ClientSession`` inside an ``async def``, so this is
        satisfied by construction - but a future caller that prepares session
        kwargs synchronously would trip it, which is why it is stated here
        rather than left to be rediscovered.
        """
        if self.kind != BROWSER or not self.cookies or not self.host:
            return None
        try:
            import aiohttp
            from yarl import URL
            jar = aiohttp.CookieJar()
            jar.update_cookies(dict(self.cookies),
                               response_url=URL(f'https://{self.host}/'))
            return jar
        except Exception as e:                                  # noqa: BLE001
            # Returning None here would silently downgrade the download to an
            # unauthenticated one, which presents as "every file failed" with
            # no cause. Say so loudly; the caller raises it to the user.
            logger.error("Could not build a cookie jar for %s: %s",
                         self.host, e, exc_info=True)
            raise

    def aiohttp_session_kwargs(self) -> dict:
        """``headers`` / ``cookie_jar`` for ``aiohttp.ClientSession``."""
        kwargs: dict = {'headers': self.auth_headers()}
        jar = self.aiohttp_cookie_jar()
        if jar is not None:
            kwargs['cookie_jar'] = jar
        return kwargs

    def with_cookies(self, cookies: Mapping[str, str]) -> 'CanvasCredential':
        """A copy carrying *cookies*. The credential itself is immutable.

        Renewal replaces the object rather than mutating it, because this value
        is read from download workers, the sync executor and the Panopto runner
        at the same time and a value that cannot change under them needs no
        lock.
        """
        return CanvasCredential(
            kind=self.kind, token=self.token,
            cookies={str(k): str(v) for k, v in (cookies or {}).items()},
            user_agent=self.user_agent, host=self.host,
        )

    def session_cookie(self) -> str:
        """The value of whichever session cookie this credential carries."""
        for name in SESSION_COOKIE_NAMES:
            value = self.cookies.get(name)
            if value:
                return value
        return ''

    # ---- persistence --------------------------------------------------

    def to_storable(self) -> dict:
        """A JSON-safe dict for the OS keyring. Includes the secret.

        **Only the SESSION cookie is persisted**, and the constraint that
        decides this is the Windows credential store, not privacy. Measured
        2026-09-11 through the app's own writer with a real CBS session: the
        full jar serialises to 1,630 characters = **3,260 bytes**, and
        ``CredWrite`` refuses a secret over 2,560 with error 1783 ("The stub
        received bad data"), so the whole credential silently fell out of the
        OS store and into the DPAPI file beside it. ``canvas_session`` alone
        authenticates - measured 200 with the user's name and every other
        cookie dropped - and puts the payload back inside the limit.

        The narrowing belongs HERE and not at the harvest, which is where it
        used to live. A storage limit is a fact about the keyring; it is not a
        fact about what the live session needs, and applying it at harvest time
        also threw away whatever an institution's WAF had issued (a Cloudflare
        ``cf_clearance``, say), so the first API call met a challenge page and
        the app read that as "your Canvas session has expired" with no way
        forward. Now the in-memory credential keeps everything the Canvas host
        set and only the at-rest copy is trimmed - which is also the smaller
        secret at rest, so nothing is given up.

        A restored credential therefore carries the session cookie alone. If
        that is not enough at some institution, the request fails the way any
        expired session does and the silent renewal harvests a fresh, complete
        jar - so the degradation is self-healing rather than terminal.
        """
        cookies = {name: value for name, value in self.cookies.items()
                   if name in SESSION_COOKIE_NAMES}
        return {
            'kind': self.kind,
            'token': self.token,
            'cookies': cookies,
            'user_agent': self.user_agent,
            'host': self.host,
        }

    @classmethod
    def from_storable(cls, data) -> 'CanvasCredential':
        """Rebuild from :meth:`to_storable`. Never raises on bad input.

        A store that has been corrupted, hand-edited or written by a newer
        version must read as "logged out", never as a crash on the startup
        path - the app has no UI yet at that point, so an exception here is a
        blank window.
        """
        if not isinstance(data, dict):
            return cls(kind=TOKEN)
        kind = data.get('kind') or TOKEN
        if kind not in (TOKEN, BROWSER):
            logger.warning("Unknown stored credential kind %r; ignoring it.", kind)
            return cls(kind=TOKEN)
        raw_cookies = data.get('cookies') or {}
        cookies = {
            str(k): str(v) for k, v in raw_cookies.items()
            if isinstance(raw_cookies, dict) and v is not None
        } if isinstance(raw_cookies, dict) else {}
        return cls(
            kind=kind,
            token=str(data.get('token') or ''),
            cookies=cookies,
            user_agent=str(data.get('user_agent') or ''),
            host=str(data.get('host') or ''),
        )


def from_token(token: str) -> CanvasCredential:
    """The classic credential: a Canvas Access Token."""
    return CanvasCredential(kind=TOKEN, token=(token or '').strip())


def from_cookies(cookies: Mapping[str, str], api_url: str,
                 user_agent: str = '') -> CanvasCredential:
    """A browser-session credential harvested from the embedded web view."""
    return CanvasCredential(
        kind=BROWSER,
        cookies={str(k): str(v) for k, v in (cookies or {}).items()},
        user_agent=user_agent or '',
        host=canvas_host(api_url),
    )


def credential_of(manager) -> CanvasCredential:
    """The credential a ``CanvasManager``-shaped object carries.

    One accessor, because the alternative is four call sites each reaching for
    ``.auth`` and each needing its own opinion about an object that does not
    have one. Modules outside ``core`` (Panopto discovery, the Panopto runner,
    sync analysis) are handed a manager by their callers and cannot assume it
    is the real class: the test suite passes lightweight stand-ins carrying
    only ``api_key`` and ``api_url``, and so did several helpers before
    ``CanvasManager`` grew an ``auth`` attribute.

    Falling back to the token string is what keeps those working. The fallback
    is deliberately narrow - it applies only when there is no credential object
    at all, never when there is one that happens to be empty, because an empty
    credential is a real answer ("not signed in") and masking it would turn a
    logged-out state into a confusing authentication failure further down.
    """
    cred = getattr(manager, 'auth', None)
    if isinstance(cred, CanvasCredential):
        return cred
    return coerce(getattr(manager, 'api_key', '') or '',
                  getattr(manager, 'api_url', '') or '')


def _looks_like_credential(value) -> bool:
    """Whether *value* carries this class's whole shape.

    Used only to recognise a credential built by a RELOADED copy of this
    module (see `coerce`). Every field is required, so a lookalike missing one
    is still rejected and still fails loudly - the point is to survive a
    module reload, not to accept anything that resembles a credential.
    """
    return all(hasattr(value, name) for name in
               ('kind', 'token', 'cookies', 'user_agent', 'host', 'usable'))


def coerce(value, api_url: str = '') -> CanvasCredential:
    """Turn whatever the app is carrying into a credential.

    This is the seam that let browser login reach all 13 ``CanvasManager``
    construction sites without editing any of them. ``value`` may be:

    * a :class:`CanvasCredential` - returned as-is, except that a browser
      credential with no host learns one from *api_url* (the URL is resolved
      through vanity-domain redirects after the credential was built, so the
      caller's host can be the more accurate of the two);
    * a ``str`` - the historical access token;
    * ``None`` / ``''`` - the logged-out credential.
    """
    if isinstance(value, CanvasCredential):
        if value.is_browser and not value.host and api_url:
            return CanvasCredential(
                kind=value.kind, token=value.token, cookies=dict(value.cookies),
                user_agent=value.user_agent, host=canvas_host(api_url),
            )
        return value
    if isinstance(value, str):
        return from_token(value)
    if value is None:
        return CanvasCredential(kind=TOKEN)

    # A credential from a PREVIOUS INCARNATION of this module.
    #
    # Measured 2026-09-13, in the product owner's own session: repeated
    # `TypeError: Canvas credential must be a CanvasCredential, str or None,
    # got CanvasCredential` - a message that reads like nonsense and is exactly
    # right. Streamlit's file watcher re-imports a changed module, which builds
    # a NEW class object, while `st.session_state['api_token']` still holds an
    # instance of the OLD one. `isinstance` compares identity, so it answers
    # False for two classes that are the same code.
    #
    # The symptom is not a crash: `core/course_cache.py` catches it and logs
    # "Course refresh failed; keeping the cached list", so the user gets an
    # amber network error and eventually "Canvas sign-in did not finish" - with
    # a perfectly good credential in hand, and signing in again cannot fix it
    # because the NEW credential lands in the same stale-typed slot.
    #
    # SOURCE RUNS ONLY: the watcher is disabled for a frozen build
    # (`start.py` passes `--server.fileWatcherType=none` when frozen), so a
    # shipped app cannot reach this. `python start.py` and `python dev.py` can.
    #
    # Rebuilt rather than accepted, so what comes out is always an instance of
    # the CURRENT class and nothing downstream can meet the same mismatch
    # again. Narrow on purpose - it recognises this exact shape, so a genuinely
    # wrong type still fails loudly, which is the whole reason this is a
    # distinct type rather than a `str` subclass.
    if type(value).__name__ == 'CanvasCredential' and _looks_like_credential(value):
        logger.warning(
            "Adopting a Canvas credential from a reloaded module (%s). This "
            "happens when Streamlit hot-reloads while a session is signed in; "
            "the credential is rebuilt rather than lost.",
            getattr(type(value), '__module__', '?'))
        return coerce(
            CanvasCredential(
                kind=getattr(value, 'kind', TOKEN),
                token=getattr(value, 'token', '') or '',
                cookies=dict(getattr(value, 'cookies', None) or {}),
                user_agent=getattr(value, 'user_agent', '') or '',
                host=getattr(value, 'host', '') or '',
            ),
            api_url,
        )

    # Anything else is a programming error upstream. Name it rather than
    # coercing it to a string and sending a garbage Bearer to Canvas.
    raise TypeError(
        f"Canvas credential must be a CanvasCredential, str or None, "
        f"got {type(value).__name__}"
    )
