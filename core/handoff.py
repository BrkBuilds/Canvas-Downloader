"""Take a Canvas session from the browser the student already uses.

Why this exists
---------------
A student uses Canvas every day and is already signed in to it in Chrome, with
their institution password in Chrome's own password manager. The app cannot see
any of that: its web view is a separate profile, so it asks them to sign in
again. That is the friction the product owner keeps naming, and the only route
that removes it entirely is to ask the browser - from inside the browser.

A small extension does that. The student clicks it while a Canvas tab is open,
it reads the Canvas session cookie for that tab, and it posts it here. The app
verifies it against Canvas exactly as it verifies a sign-in of its own, and
shows whose account it is. **Nothing is typed, no institution is picked, no
password is entered**, because the browser already did all of it.

This is SUPPLEMENTARY, by the product owner's ruling (2026-09-12): the straight
path stays the in-app sign-in. Nobody has to install anything.

Why this is not the thing the module docstring of `browser_login` rules out
---------------------------------------------------------------------------
That entry closes reading cookies out of an installed browser's **files** -
Chrome's App-Bound Encryption killed it, and it is the technique credential
stealers use. This is the opposite: the browser hands the cookie over itself,
through its own extension API, because the person who owns it clicked a button.
No database is read, nothing is decrypted, and App-Bound Encryption is
irrelevant because the request comes from inside the browser.

The threat model, stated because a localhost listener deserves one
------------------------------------------------------------------
Five things bound it, and the shape of the extension follows from them:

1. **Loopback only.** Bound to 127.0.0.1, so nothing off the machine can
   reach it.
2. **Time-boxed and user-initiated.** It listens only while the user is
   looking at the sign-in screen having asked for it, for
   :data:`WINDOW_SECONDS`, and closes on the first accepted handoff.
3. **Extension origins only.** A web page cannot set its own ``Origin``
   header - the browser sets it - so a page on the internet cannot pretend to
   be ``chrome-extension://``. That single check is what stops any open tab
   from talking to this.
4. **Nothing is readable by a page even if it did POST.** The CORS headers
   name extension origins, so a page gets no response body. Data flows ONE
   way: this endpoint never hands anything back but an acknowledgement.
5. **The credential is proven, and the user is named.** The app verifies it
   against Canvas before adopting it and then shows whose account it is - so a
   session pushed by something other than the student is visible rather than
   silent. That is the residual risk and it is bounded to "somebody could sign
   you into an account that is not yours", which the screen then shows.

No secret ever travels TOWARDS the browser, so there is nothing here for a
page to steal even in principle.
"""

from __future__ import annotations

import http.server
import json
import logging
import socketserver
import sys
import threading
import time
import types

logger = logging.getLogger(__name__)

#: Ports the extension tries, in order. A fixed short list rather than an
#: ephemeral port, because the extension has to FIND the app without being
#: told - and a handful of ports it can probe is the only way to do that
#: without inventing a discovery protocol. Three, so a machine where one is
#: taken still works.
PORTS = (53127, 53128, 53129)

#: How long the app listens after the user asks. Long enough to click the
#: extension and grant it a host permission the first time, short enough that
#: the listener is not a standing fixture. It also closes on the first
#: accepted handoff, so the usual life of it is a few seconds.
WINDOW_SECONDS = 180.0

#: Schemes a browser extension's `Origin` can have. A page cannot forge these:
#: `Origin` is a forbidden header name, so the browser, not the script, sets
#: it. This is the check that makes a loopback listener safe to open at all.
_EXTENSION_SCHEMES = ('chrome-extension://', 'moz-extension://',
                      'safari-web-extension://', 'ms-browser-extension://')

#: Cookie names worth accepting. The session cookie is the credential.
#:
#: `_csrf_token` is still ACCEPTED and is no longer SENT. The extension stopped
#: reading it on 2026-09-15: the stated reason (that it saves the access-token
#: upgrade a round trip) was measured false on real Canvas - the one
#: `GET /profile/settings` that `core.token_mint.mint` makes always answers
#: with `set-cookie: _csrf_token=...`, even when the request already carried
#: one. Kept in this list only so an extension installed before that date still
#: works; `to_storable` drops it either way, so nothing of it reaches disk.
ACCEPTED_COOKIES = ('canvas_session', '_normandy_session', '_csrf_token')

#: The largest request body worth reading. A session cookie is a few hundred
#: bytes, so anything near this is not one - and an unbounded read on a socket
#: is its own bug. ONE definition, because it bounds two different things: what
#: is accepted, and how much of a REFUSED request is drained to keep the
#: connection in sync (see `_Handler._dispose_of_body`).
MAX_BODY_BYTES = 64 * 1024

#: Where the listener's live state lives, and it is NOT this module.
#:
#: THE BUG THIS EXISTS FOR, reproduced 2026-09-13. Streamlit's file watcher
#: does `del sys.modules[name]` for EVERY watched module on ANY file change
#: (`streamlit/watcher/local_sources_watcher.py`, "as a workaround we simply
#: unload all watched modules"). So `core.handoff` is re-imported FRESH: the
#: new module's `_server` is None, while the socket the old one opened is
#: still LISTENING in a `serve_forever` thread that nothing holds a reference
#: to any more. Nothing can ever call `stop()` on it.
#:
#: Measured, on three throwaway ports: one edit leaks one listener, three edits
#: leak three, and the fourth `start()` answers 0 - which the card reports as
#: "Could not open a connection for the browser extension", permanently.
#:
#: THE SECOND CONSEQUENCE IS THE WORSE ONE. The extension walks the port list
#: and finds the FIRST answering port, which is the oldest ORPHAN. That orphan
#: answers `/ping`, reports itself armed, accepts the handoff and logs
#: "Accepted a Canvas session handoff" - into state the live module cannot
#: read. So the extension shows success, the terminal shows success, and
#: `result()` stays None for ever: "Canvas sign-in did not finish".
#: `scripts/check_handoff.py` passed all ten checks against an orphan.
#:
#: A synthetic module has no `__file__`, so the watcher never watches it and
#: never deletes it. Holding the socket, the lock and the state here means a
#: re-imported module ADOPTS the running listener instead of orphaning it -
#: and an orphaned HANDLER from a previous incarnation still writes into the
#: same state dict, because its globals were bound to these same objects.
_RUNTIME_KEY = 'canvas_downloader._handoff_runtime'


def _runtime() -> types.ModuleType:
    """The process-wide listener state, created once and never reloaded."""
    rt = sys.modules.get(_RUNTIME_KEY)
    if rt is None:
        rt = types.ModuleType(_RUNTIME_KEY)
        rt.server = None
        rt.lock = threading.Lock()
        rt.state = {}
        sys.modules[_RUNTIME_KEY] = rt
    return rt


_rt = _runtime()
#: The SAME objects across every re-import, because they are mutated in place.
_lock = _rt.lock
_state: dict = _rt.state


def _is_extension_origin(origin: str) -> bool:
    """Whether *origin* is a browser extension. An ABSENT origin is not one.

    **It used to answer True for no Origin at all**, on the reasoning that the
    extension's service worker "may omit it" and that something with no Origin
    is not a web page. The second half is true and is exactly the problem: it
    is any OTHER PROGRAM on the machine, and `adopt_pending_handoff` takes the
    Canvas address from the payload. Measured 2026-09-14 against the real
    listener: a `urllib` POST with no Origin was answered 200 and the app would
    have adopted `evil.example` as the student's Canvas.

    **The first half was never measured, and it is false.** The real extension
    in Chromium 149, driven through its own `connect()`, sent
    `Origin: chrome-extension://<id>` on `GET /ping`, on the CORS preflight AND
    on `POST /canvas-session`. So requiring an origin costs the extension
    nothing. `/ping` still answers a request with no Origin on purpose - see
    `do_GET` - because all it discloses is whether a sign-in is being asked for.
    """
    return bool(origin) and origin.startswith(_EXTENSION_SCHEMES)


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'CanvasDownloader'

    #: Idle keep-alive connections close instead of holding a thread each.
    #: `ThreadingMixIn` gives every connection its own thread and HTTP/1.1
    #: keeps them open, so without this a local process could pile threads up
    #: by connecting and saying nothing. `handle_one_request` turns the read
    #: timeout into `close_connection`, and the log line it writes goes
    #: through `log_message`, which is silenced.
    timeout = 10

    #: Whether this request's body has been consumed. `_reply` reads it to
    #: decide whether the body still has to be drained, which is what keeps a
    #: keep-alive connection in sync on every REFUSAL path - see
    #: `_dispose_of_body`.
    _body_consumed = False

    def log_message(self, *args):                      # noqa: D102
        pass                                           # never to stderr

    def handle_error(self, request, client_address):
        """A dropped connection is not a crash, and never goes to stderr.

        `socketserver`'s default prints a traceback to stderr. That is wrong
        here twice over: `log_message` is silenced precisely so this listener
        never writes there, and in the packaged app stderr is a handle nobody
        reads (on Windows, a windowed build has none at all), so the default
        is noise at best and a write to a closed handle at worst.

        MEASURED, 2026-09-12: before the framing fixes below, an OPTIONS
        preflight and a refused POST each dumped a `ConnectionResetError`
        traceback here - which is how those two bugs were found. Logged rather
        than swallowed, because a listener that reports nothing is a listener
        nobody can diagnose.
        """
        import sys as _sys
        exc = _sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            # The client hung up. Ordinary, and the only thing worth saying is
            # that it happened.
            logger.debug("Handoff client disconnected: %r", exc)
            return
        logger.warning("Handoff request from %s failed.", client_address,
                       exc_info=True)

    # -- helpers ---------------------------------------------------------

    def _dispose_of_body(self) -> None:
        """Leave the connection in a state the next request can be read from.

        **The bug this exists for.** Every refusal here answers without reading
        the request body - a 403 for a page origin, a 404, a 409 when nothing
        is waiting. With `protocol_version = 'HTTP/1.1'` the connection is
        keep-alive, so those unread bytes are still in the socket when the
        server goes looking for the NEXT request line, and it reads the tail of
        a JSON body as a request. Measured 2026-09-12: a refused POST raised
        `ConnectionResetError` out of `handle_one_request`.

        That is not cosmetic, because the extension makes exactly the pair of
        requests that trips it - `GET /ping` to find the port, then
        `POST /canvas-session` - and a browser is free to send both down one
        connection.

        A body larger than `MAX_BODY_BYTES` is never read: the connection is
        closed instead. Draining is a courtesy to a well-behaved client, not an
        obligation to read whatever a refused caller decided to send.
        """
        if self._body_consumed:
            return
        self._body_consumed = True
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            return
        try:
            self.rfile.read(length)
        except Exception as e:                         # noqa: BLE001
            logger.debug("Could not drain a refused request body: %r", e)
            self.close_connection = True

    def _cors(self, origin: str) -> None:
        # Echo only an EXTENSION origin. Naming a page's origin here would let
        # it read the response.
        if origin and origin.startswith(_EXTENSION_SCHEMES):
            self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Vary', 'Origin')

    def _reply(self, code: int, payload: dict) -> None:
        # BEFORE the response, and on every path: a refusal that answers
        # without reading the body leaves the bytes in the socket for the next
        # request to trip over. Doing it here rather than in each verb is what
        # makes it true for the ones not yet written.
        self._dispose_of_body()

        # A 204 CARRIES NO BODY. RFC 9110: "A 204 response is terminated by the
        # end of the header section" - it cannot have Content-Length, and a
        # client that knows that does not read the two bytes `{}` we used to
        # send, so they sat in the socket and the connection desynchronised.
        # Measured 2026-09-12: every CORS preflight - which Chrome sends before
        # every handoff POST, because `Content-Type: application/json` is not
        # safelisted - ended in a `ConnectionResetError` traceback.
        no_body = code == 204 or code == 304
        body = b'' if no_body else json.dumps(payload).encode('utf-8')

        self.send_response(code)
        if not no_body:
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
        self._cors(self.headers.get('Origin') or '')
        self.end_headers()
        if not body:
            return
        try:
            self.wfile.write(body)
        except Exception:                              # noqa: BLE001
            pass                                       # client hung up

    # -- verbs -----------------------------------------------------------

    def do_OPTIONS(self):                              # noqa: N802
        self._reply(204 if _is_extension_origin(
            self.headers.get('Origin') or '') else 403, {})

    def do_GET(self):                                  # noqa: N802
        """Let the extension find which port the app is on."""
        if self.path.rstrip('/') != '/ping':
            return self._reply(404, {'error': 'not found'})
        origin = self.headers.get('Origin') or ''
        # A PRESENT non-extension origin is a web page, and a page learns
        # nothing here. An ABSENT one is a local program or a diagnostic such
        # as `scripts/check_handoff.py`, and the only thing this answers is
        # whether a sign-in is being asked for - no identity, no address, and
        # the handover itself (`do_POST`) still demands an extension origin.
        if origin and not _is_extension_origin(origin):
            return self._reply(403, {'error': 'forbidden'})
        with _lock:
            waiting = bool(_state.get('open')) and not _state.get('payload')
        # Says only whether a sign-in screen is waiting. No identity, no
        # address, nothing a page could learn something from.
        self._reply(200, {'app': 'canvas-downloader', 'waiting': waiting})

    def do_POST(self):                                 # noqa: N802
        origin = self.headers.get('Origin') or ''
        if not _is_extension_origin(origin):
            logger.warning("Refused a Canvas session handoff from a "
                           "non-extension origin.")
            return self._reply(403, {'error': 'forbidden'})
        if self.path.rstrip('/') != '/canvas-session':
            return self._reply(404, {'error': 'not found'})
        with _lock:
            if not _state.get('open'):
                return self._reply(409, {'error': 'not waiting'})

        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            # A session cookie is a few hundred bytes. Anything else is not
            # one, and an unbounded read on a loopback socket is its own bug.
            return self._reply(400, {'error': 'bad size'})
        try:
            raw = self.rfile.read(length)
            # Claimed HERE, next to the read, so `_reply` does not try to drain
            # a body that is already gone - which on a keep-alive connection
            # would block until the read timeout rather than return empty.
            self._body_consumed = True
            data = json.loads(raw.decode('utf-8'))
        except Exception:                              # noqa: BLE001
            return self._reply(400, {'error': 'bad json'})

        host = str((data or {}).get('host') or '').strip().lower()
        raw = (data or {}).get('cookies') or {}
        if not host or not isinstance(raw, dict):
            return self._reply(400, {'error': 'missing host or cookies'})
        cookies = {str(k): str(v) for k, v in raw.items()
                   if k in ACCEPTED_COOKIES and v}
        if not any(k in cookies for k in ('canvas_session', '_normandy_session')):
            return self._reply(400, {'error': 'no session cookie'})

        with _lock:
            _state['payload'] = {'host': host, 'cookies': cookies}
            _state['open'] = False                     # first one wins
        logger.info("Accepted a Canvas session handoff for %s (%d cookies).",
                    host, len(cookies))
        self._reply(200, {'ok': True})


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False        # never inherit somebody else's socket


def start() -> int:
    """Open the handoff window. Answers the port, or 0 if none could be had.

    Idempotent: calling it while a window is already open re-arms the clock
    and keeps the same port, so a user pressing the button twice does not lose
    the listener.
    """
    rt = _runtime()
    with _lock:
        if rt.server is not None:
            # Also the RE-IMPORT path: a listener opened by a previous
            # incarnation of this module is adopted here rather than orphaned.
            _state['open'] = True
            _state['deadline'] = time.monotonic() + WINDOW_SECONDS
            # An ARRIVED-but-uncollected handoff is deliberately KEPT. It was
            # dropped here until 2026-09-13, on the reasoning that a re-arm
            # starts a fresh attempt - but the only thing that can be sitting
            # here is a session this same student sent seconds ago, and the
            # student pressing the button again is usually somebody who could
            # not see that it had worked. Discarding their credential at that
            # exact moment is the worst possible answer. `result()` is called
            # near the top of every Streamlit run, so nothing here can be old.
            return int(_state.get('port') or 0)

    for port in PORTS:
        try:
            server = _Server(('127.0.0.1', port), _Handler)
        except OSError:
            continue                                   # in use; try the next
        with _lock:
            rt.server = server
            # A handoff that arrived and was not collected survives a fresh
            # bind for the same reason it survives a re-arm (above). Since the
            # socket now closes itself when the window ends, "the window ran
            # out a moment after the credential landed, and the student pressed
            # the button again" reaches THIS branch rather than that one.
            kept = _state.get('payload')
            _state.clear()
            if kept is not None:
                _state['payload'] = kept
            _state.update(open=True, port=port,
                          deadline=time.monotonic() + WINDOW_SECONDS)
        threading.Thread(target=server.serve_forever, name='canvas-handoff',
                         daemon=True).start()
        threading.Thread(target=_close_when_window_ends, args=(server,),
                         name='canvas-handoff-window', daemon=True).start()
        logger.info("Listening for a Canvas session handoff on 127.0.0.1:%d.",
                    port)
        return port

    logger.warning("Could not open a handoff port (%s all in use).",
                   ', '.join(str(p) for p in PORTS))
    return 0


def port() -> int:
    """The port currently listening, or 0."""
    with _lock:
        return int(_state.get('port') or 0) if _runtime().server is not None else 0


def waiting() -> bool:
    """Whether a handoff is still being accepted."""
    with _lock:
        if _runtime().server is None or not _state.get('open'):
            return False
        if time.monotonic() > float(_state.get('deadline') or 0):
            _state['open'] = False
            return False
        return True


def has_payload() -> bool:
    """Whether a handoff has ARRIVED and is not yet collected. Non-consuming.

    `waiting()` cannot answer this and must not be made to: it means "the
    window is still ACCEPTING", and accepting stops the instant a handoff
    lands. The two are opposites at exactly the moment that matters, which is
    what made the UI need this.

    Reported 2026-09-13: the extension showed success, the terminal logged
    `Accepted a Canvas session handoff`, and the app showed a failure card.
    `ui/auth.py` kept its polling fragment alive on `waiting()`, and that
    fragment is the only thing that triggers the full Streamlit run which
    collects the payload - so the arrival of the handoff switched off the very
    thing that would have picked it up. The credential sat here, uncollected,
    until the student pressed the button again. A one-second tick normally wins
    that race; a backgrounded tab on a slow laptop does not, and the app had
    just opened a Canvas tab in front of itself.
    """
    with _lock:
        return _state.get('payload') is not None


def result() -> dict | None:
    """The handoff that arrived, once. Consumes it."""
    with _lock:
        return _state.pop('payload', None)


#: How often the window watcher re-reads the deadline. It sleeps no longer than
#: this, so a re-arm that pushes the deadline out is honoured and a watcher
#: whose listener was already stopped exits within a second.
_WATCH_TICK_SECONDS = 1.0


def _close_when_window_ends(server) -> None:
    """Close the SOCKET when the window ends, not just the window.

    **The bug this exists for**, measured 2026-09-13 against the real module:
    when the three minutes ran out `waiting()` flipped the acceptance flag and
    nothing called `stop()`, so the socket stayed bound and answering `/ping`
    for the life of the process. The module docstring, `extension/README.md`
    and the published privacy policy all said it times out.

    One watcher per BIND, and it only ever closes the server it was started
    for. A re-arm extends the shared deadline, which this re-reads; a `stop()`
    followed by a new `start()` replaces the server, and the old watcher then
    exits instead of closing a listener that is not its own.

    Uses `_stop_server(..., keep_payload=True)`: a credential that arrived just
    before the deadline is the student's own, and closing the socket is no
    reason to throw it away before the app has collected it.
    """
    while True:
        with _lock:
            if _runtime().server is not server:
                return                       # stopped, or superseded
            left = float(_state.get('deadline') or 0) - time.monotonic()
        if left <= 0:
            break
        time.sleep(min(left, _WATCH_TICK_SECONDS))
    if _stop_server(only=server, keep_payload=True):
        logger.info("The Canvas session handoff window ended; stopped "
                    "listening.")


def stop() -> None:
    """Close the window and the socket, and forget anything uncollected.

    A deliberate stop is logout, a finished sign-in, or a cancelled attempt,
    and in every one of those a credential still sitting here belongs to an
    attempt the student has left behind. Keeping it would let the next press
    of the button sign in with it. Never raises.
    """
    if _stop_server(only=None, keep_payload=False):
        logger.info("Stopped listening for a Canvas session handoff.")


def _stop_server(*, only, keep_payload: bool) -> bool:
    """Shut the listener down. Answers whether there was one to shut.

    With *only*, it shuts that server and nothing else - the window watcher's
    guard against closing a listener opened after its own was stopped.
    """
    rt = _runtime()
    with _lock:
        if only is not None and rt.server is not only:
            return False
        server, rt.server = rt.server, None
        _state['open'] = False
        if not keep_payload:
            _state.pop('payload', None)
    if server is None:
        return False
    try:
        server.shutdown()
    except Exception as e:                             # noqa: BLE001
        logger.debug("Handoff server shutdown: %s", e)
    try:
        server.server_close()
    except Exception as e:                             # noqa: BLE001
        logger.debug("Handoff server close: %s", e)
    return True
