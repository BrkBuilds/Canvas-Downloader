"""Mutation pass for the browser-extension handoff.

`tests/test_handoff.py` guards a LOOPBACK LISTENER, so the failures it
prevents are not "the feature stopped working" but:

* **any open tab can sign the app in.** The origin check is one `if`, and
  without it every page on the internet can POST a Canvas session to the
  user's machine.
* **a web page can read the reply.** Echoing a page's origin in the CORS
  header turns a one-way endpoint into a two-way one.
* **the whole network can reach it.** One string - `127.0.0.1` - separates
  loopback from every device on the campus wifi.
* **the listener becomes a standing fixture**, open long after the user asked
  for it, or surviving a logout entirely.

Every mutant is a plausible edit rather than a strawman: dropping a guard that
looks redundant, widening a CORS header to "make it work", binding to all
interfaces because that is what most examples do.

Restore is from an in-memory SNAPSHOT, never `git checkout`: this repo is
routinely worked by two sessions at once. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath,
restoring nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_handoff.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

HANDOFF = "core/handoff.py"
UI = "ui/auth.py"
APP = "app.py"

POPUP = "extension/popup.js"
HTML = "extension/popup.html"
BG = "extension/background.js"
CHECKER = "scripts/check_handoff.py"
DEV = "dev.py"
DEBUG = "core/canvas_debug.py"

#: `tests/test_keychain_unlock.py` owns `_safe_keyring_delete` and
#: `tests/test_dev_tooling.py` owns `scripts/check_handoff.py`. Both were
#: missing here, and a mutant whose only guard lives in a file the harness does
#: not run is reported SURVIVED under a label that reads like a product gap.
TESTS = ["tests/test_handoff.py",
         "tests/test_keychain_unlock.py",
         "tests/test_dev_tooling.py",
         "tests/test_debug_log_noise.py"]

#: (label, file, old, new)
HANDOFF_MUTANTS = [
    # -- 1. only an extension may talk to it --------------------------------
    ("the origin check is dropped from the POST, so ANY OPEN TAB on the "
     "internet can hand the app a Canvas session",
     HANDOFF,
     "        origin = self.headers.get('Origin') or ''\n"
     "        if not _is_extension_origin(origin):",
     "        origin = self.headers.get('Origin') or ''\n"
     "        if False:"),

    ("a web page's origin counts as an extension, which is the same hole "
     "wearing a different shape",
     HANDOFF,
     "    return bool(origin) and origin.startswith(_EXTENSION_SCHEMES)",
     "    return True"),

    ("a caller with NO Origin counts as an extension again - the code as it "
     "was until 2026-09-14, when a urllib POST was measured being accepted "
     "and the app would have adopted evil.example as the student's Canvas",
     HANDOFF,
     "    return bool(origin) and origin.startswith(_EXTENSION_SCHEMES)",
     "    return (not origin) or origin.startswith(_EXTENSION_SCHEMES)"),

    ("the probe is tightened along with the POST, so a caller with no origin "
     "(the diagnostic checker among them) is refused a harmless question",
     HANDOFF,
     "        if origin and not _is_extension_origin(origin):\n"
     "            return self._reply(403, {'error': 'forbidden'})",
     "        if not _is_extension_origin(origin):\n"
     "            return self._reply(403, {'error': 'forbidden'})"),

    ("the probe endpoint answers a web page, telling any site that the app is "
     "listening and on which port",
     HANDOFF,
     "        if origin and not _is_extension_origin(origin):\n"
     "            return self._reply(403, {'error': 'forbidden'})\n"
     "        with _lock:\n"
     "            waiting = bool(_state.get('open')) and not _state.get('payload')",
     "        with _lock:\n"
     "            waiting = bool(_state.get('open')) and not _state.get('payload')"),

    # -- 2. nothing readable by a page --------------------------------------
    ("the CORS header echoes WHATEVER origin asked, so a web page can read "
     "the reply and the endpoint stops being one-way",
     HANDOFF,
     "        if origin and origin.startswith(_EXTENSION_SCHEMES):\n"
     "            self.send_header('Access-Control-Allow-Origin', origin)",
     "        if origin:\n"
     "            self.send_header('Access-Control-Allow-Origin', origin)"),

    ("the CORS header becomes a wildcard",
     HANDOFF,
     "        if origin and origin.startswith(_EXTENSION_SCHEMES):\n"
     "            self.send_header('Access-Control-Allow-Origin', origin)",
     "        if True:\n"
     "            self.send_header('Access-Control-Allow-Origin', '*')"),

    ("the preflight stops refusing a page, so a page's POST is no longer "
     "blocked before it is sent",
     HANDOFF,
     "        self._reply(204 if _is_extension_origin(\n"
     "            self.headers.get('Origin') or '') else 403, {})",
     "        self._reply(204, {})"),

    # -- 3. loopback only ---------------------------------------------------
    ("the listener binds to every interface, so anything on the campus wifi "
     "can hand this machine a Canvas session",
     HANDOFF,
     "            server = _Server(('127.0.0.1', port), _Handler)",
     "            server = _Server(('0.0.0.0', port), _Handler)"),

    # -- 4. time-boxed and one-shot -----------------------------------------
    ("the window stays open after a handoff, so the listener is a standing "
     "fixture and a second session can replace the first",
     HANDOFF,
     "            _state['payload'] = {'host': host, 'cookies': cookies}\n"
     "            _state['open'] = False                     # first one wins",
     "            _state['payload'] = {'host': host, 'cookies': cookies}"),

    ("the deadline is ignored, so the listener never times out",
     HANDOFF,
     "        if time.monotonic() > float(_state.get('deadline') or 0):\n"
     "            _state['open'] = False\n"
     "            return False",
     "        if False:\n"
     "            return False"),

    ("the handoff is not consumed, so a later rerun re-adopts a session that "
     "has already been used - the shape `unlocked_token()` had",
     HANDOFF,
     "        return _state.pop('payload', None)",
     "        return _state.get('payload')"),

    ("stop() leaves the socket open, so a logout leaves a listener accepting "
     "Canvas sessions",
     HANDOFF,
     "    try:\n"
     "        server.shutdown()",
     "    if True:\n"
     "        return\n"
     "    try:\n"
     "        server.shutdown()"),

    # -- 5. what it accepts -------------------------------------------------
    ("every cookie the extension sends is kept, so a future version of it - "
     "or a bug in it - widens what the app stores",
     HANDOFF,
     "        cookies = {str(k): str(v) for k, v in raw.items()\n"
     "                   if k in ACCEPTED_COOKIES and v}",
     "        cookies = {str(k): str(v) for k, v in raw.items() if v}"),

    ("a CSRF token counts as a session, so a handoff with no credential in it "
     "is adopted and then fails against Canvas for no stated reason",
     HANDOFF,
     "        if not any(k in cookies for k in ('canvas_session', '_normandy_session')):\n"
     "            return self._reply(400, {'error': 'no session cookie'})",
     "        if False:\n"
     "            return self._reply(400, {'error': 'no session cookie'})"),

    ("the body size is unbounded, so an unbounded read happens on a socket",
     HANDOFF,
     "        if length <= 0 or length > MAX_BODY_BYTES:",
     "        if length <= 0:"),

    # -- 5b. HTTP framing: the connection has to survive being refused ------
    # All four were found on 2026-09-12 by building the dev-testing harness
    # and reading what the listener put on the wire. Two of them were REAL
    # BUGS on the extension's live path, invisible to sections 1-5 because
    # `urllib` opens a connection per request - so an unread body is followed
    # by EOF and the server never trips over it. A browser keeps the
    # connection, which is the whole point of these.
    ("a refused request stops draining its body, so the next request on the "
     "same connection reads a JSON body as its request line - measured: "
     "HTTP/1.1 501 Unsupported method ('{\"host\":\"x\"...}GET')",
     HANDOFF,
     "        self._dispose_of_body()\n"
     "\n"
     "        # A 204 CARRIES NO BODY.",
     "        pass\n"
     "\n"
     "        # A 204 CARRIES NO BODY."),

    ("a 204 preflight announces a body again, which Chrome sends before "
     "EVERY handoff POST - measured: Content-Length: 2, the client reads 0 "
     "bytes, and the server raises ConnectionResetError",
     HANDOFF,
     "        no_body = code == 204 or code == 304",
     "        no_body = False"),

    ("an oversized refused body is DRAINED rather than disowned, so the "
     "unbounded read the size guard exists to prevent happens anyway, one "
     "layer down",
     HANDOFF,
     "        if length > MAX_BODY_BYTES:\n"
     "            self.close_connection = True\n"
     "            return",
     "        if length > MAX_BODY_BYTES:\n"
     "            length = MAX_BODY_BYTES"),

    ("the body is not claimed after being read, so `_reply` tries to drain a "
     "body that is already gone and blocks until the read timeout",
     HANDOFF,
     "            self._body_consumed = True\n"
     "            data = json.loads(raw.decode('utf-8'))",
     "            data = json.loads(raw.decode('utf-8'))"),

    ("a handler failure is swallowed, so the listener stops being "
     "diagnosable - the `except Exception: pass` this repo keeps paying for, "
     "wearing an error handler's clothes",
     HANDOFF,
     "        exc = _sys.exc_info()[1]\n"
     "        if isinstance(exc, (ConnectionError, TimeoutError)):",
     "        exc = _sys.exc_info()[1]\n"
     "        if True:"),

    ("a missing host is accepted, so the app builds a credential for nowhere",
     HANDOFF,
     "        if not host or not isinstance(raw, dict):",
     "        if not isinstance(raw, dict):"),

    # -- 6. the app side ----------------------------------------------------
    ("app.py stops collecting the handoff, so it arrives on the listener's "
     "thread and nothing ever adopts it",
     APP,
     "adopt_pending_handoff()",
     "pass  # handoff deliberately not collected"),

    ("logging out leaves the listener running",
     UI,
     "    # accepting Canvas sessions is a logout in name only.\n"
     "    cancel_browser_handoff()",
     "    # accepting Canvas sessions is a logout in name only.\n"
     "    pass"),

    ("the handoff forms its own opinion of the credential instead of going "
     "through the one adoption, so the three routes drift apart about what a "
     "network blip means",
     UI,
     "        _verdict = _adopt_restored_credential(credential, optimistic=False)",
     "        cm = CanvasManager(credential, api_url)\n"
     "        valid, _msg = cm.validate_token()\n"
     "        st.session_state['is_authenticated'] = valid\n"
     "        _verdict = 'ok' if valid else 'refused'"),

    # -- 7. opening the student's Canvas, and the gate on it ---------------
    # -- 7. opening the student's Canvas, and the gate on it ---------------
    ("the host plausibility check is dropped, so a typo in the address "
     "field opens a junk tab - measured: `not a url` normalises to "
     "`https://not a url` and `file:///C:/Windows` to `https://file:`",
     UI,
     "    if not host or '.' not in host or any(c.isspace() for c in host):",
     "    if False:"),

    ("the scheme check is dropped, so whatever normalize_canvas_url "
     "produced goes straight to the operating system's URL handler",
     UI,
     "    if not url.startswith(('https://', 'http://')):\n"
     "        return False",
     "    if False:\n"
     "        return False"),

    ("the Canvas tab is opened BEFORE the listener is armed, so the "
     "extension asks whether the app is waiting and is correctly told no",
     UI,
     "    port = handoff.start()\n"
     "    st.session_state['handoff_waiting'] = bool(port)",
     "    st.session_state['handoff_opened_tab'] = open_canvas_tab(api_url)\n"
     "    port = handoff.start()\n"
     "    st.session_state['handoff_waiting'] = bool(port)"),

    ("cancelling forgets to clear the opened-tab flag, so the NEXT handoff "
     "tells the student their Canvas was opened when it was not",
     UI,
     "    st.session_state.pop('handoff_opened_tab', None)",
     "    pass"),

    ("the waiting notice stops reading whether a tab was opened, so it "
     "tells a student to go and open the page it just opened for them",
     UI,
     "        opened = bool(st.session_state.get('handoff_opened_tab'))",
     "        opened = False"),

    ("an ABSENT keyring entry is reported as a failed delete again, so "
     "every normal logout logs a warning and a real failure becomes "
     "indistinguishable from an empty store",
     UI,
     "    except PasswordDeleteError as e:",
     "    except _NeverRaisedHere as e:"),

    ("a handoff is never upgraded to a long-lived token, so the extension "
     "stays in the loop for ever",
     UI,
     "    if _upgrade_to_access_token(credential):\n"
     "        return True\n"
     "    _persist_browser_login(credential)\n"
     "    return True\n"
     "\n"
     "\n"
     "def adopt_pending_browser_login() -> bool:",
     "    _persist_browser_login(credential)\n"
     "    return True\n"
     "\n"
     "\n"
     "def adopt_pending_browser_login() -> bool:"),

    # -- 8. the screen for when there is nothing to do ------------------
    ("the popup goes back to closing itself after a sign-in, throwing "
     "away the only confirmation a student ever gets - the app has no "
     "way to send one",
     POPUP,
     "    await showDone();\n"
     "    return;",
     "    await showDone();\n"
     "    setTimeout(() => window.close(), 2200);\n"
     "    return;"),

    ("the worker stops recording that a sign-in succeeded, so the popup "
     "is back to reading the silence of an app that has already stopped "
     "listening as 'not running'",
     BG,
     "  if (result && result.ok) await rememberSignedIn(result.host);\n",
     ""),

    ("the countdown never lands, so the finished screen sits there for "
     "ever and the student never reaches the resting one",
     POPUP,
     "      showRest(running);",
     "      /* leave it on the finished screen */"),

    ("the countdown is treated as decoration and hidden under reduced "
     "motion, which is exactly the machine that reported the first "
     "spinner as broken",
     HTML,
     "      .spin { display: none; }",
     "      .spin, .countdown { display: none; }"),

    ("the finished screen keeps a big disabled button, which is then the "
     "heaviest thing on a screen with nothing to press",
     POPUP,
     "    button: null, enabled: false,",
     "    button: \"Signed in\", enabled: false,"),

    ("one part of the guide is forgotten in the resting rule, so the "
     "step tracker leaks onto the clean screen - the exact defect class "
     "this repo calls a fix that landed on some sites and not others",
     HTML,
     "    body.resting .steps,\n",
     ""),

    ("a remembered sign-in is consulted even while the app is asking "
     "for a NEW one, so the student is shown a resting screen instead of "
     "the sign-in they are waiting on",
     POPUP,
     "  if (!(app && app.waiting)) {",
     "  {"),

    ("going back to the guide no longer forgets the remembered sign-in, "
     "so the resting screen returns on the next open and the student is "
     "stuck in it",
     POPUP,
     "    await chrome.storage.session.remove(\"signedIn\");",
     "    /* keep it */"),

    # -- 9. surviving a module re-import --------------------------------
    ("the runtime is rebuilt on every lookup instead of being found in "
     "sys.modules, so each re-import opens ANOTHER listener and the "
     "fourth one answers 0 - the leak the product owner hit",
     HANDOFF,
     "    rt = sys.modules.get(_RUNTIME_KEY)\n"
     "    if rt is None:",
     "    rt = None\n"
     "    if rt is None:"),

    ("the runtime is given a __file__, so a file watcher can watch it, "
     "unload it, and the leak is straight back",
     HANDOFF,
     "        rt = types.ModuleType(_RUNTIME_KEY)\n",
     "        rt = types.ModuleType(_RUNTIME_KEY)\n"
     "        rt.__file__ = __file__\n"),

    ("a re-imported module stops adopting the listener already running, "
     "so it binds the next port and orphans the one the extension will "
     "reach first",
     HANDOFF,
     "        if rt.server is not None:",
     "        if False:"),

    ("the state dict is local to each incarnation again, so a handoff "
     "accepted by an older one is written where the live module will "
     "never look - accepted and logged, and the app says the sign-in did "
     "not finish",
     HANDOFF,
     "_state: dict = _rt.state",
     "_state: dict = {}"),

    ("each incarnation gets its own lock, so two of them guard the same "
     "state with different locks and the mutual exclusion is a fiction",
     HANDOFF,
     "_lock = _rt.lock",
     "_lock = threading.Lock()"),

    ("stop() closes the socket but leaves the runtime pointing at it, so "
     "the next start() re-arms a dead server and reports a port nothing "
     "is listening on",
     HANDOFF,
     "        server, rt.server = rt.server, None",
     "        server = rt.server"),

    ("the checker stops at the FIRST port that answers, so an orphaned "
     "listener passes every check while the app never receives the "
     "sign-in - measured: ten of ten checks green against an orphan",
     CHECKER,
     "    if len(answering) > 1:",
     "    if False:"),

    # -- 10. the sign-in card state machine -----------------------------
    ("the notice decides a handoff is over the moment it ARRIVES, so the "
     "polling fragment stops being rendered - and it is the only thing "
     "that asks for the run which COLLECTS the credential. The extension "
     "shows success and the app never signs in",
     UI,
     "                    and (handoff.waiting() or handoff.has_payload()))",
     "                    and handoff.waiting())"),

    ("a new attempt stops clearing the OTHER route's stale failure, so a "
     "previous error card is drawn over a sign-in that is working",
     UI,
     "    st.session_state.pop('browser_login_failed', None)\n"
     "    st.session_state.pop('handoff_arrived_shown', None)\n"
     "    port = handoff.start()",
     "    st.session_state.pop('handoff_arrived_shown', None)\n"
     "    port = handoff.start()"),

    ("a failure the app can set loses its card and silently falls back "
     "to the generic one - the defect this section exists for, in a hat",
     UI,
     "    'no_port': (",
     "    '_retired_no_port': ("),

    ("two causes collapse back to one sentence, so the student is told "
     "the same thing whatever actually happened",
     UI,
     "        \"That tab was not signed in to Canvas\",",
     "        \"Canvas did not accept that sign-in\","),

    ("\"Listening\" comes back under the spinner - developer wording, on "
     "the one feature where telling a student something is listening is "
     "the wrong thing to say about it",
     UI,
     "            \"<span>Waiting for your browser</span></div>\"",
     "            \"<span>Listening</span></div>\""),

    ("the app's OWN Canvas-window failure starts advertising the browser "
     "extension, which has nothing to do with why that route failed",
     UI,
     "Nothing has changed, and you can try again. ",
     "Install the Canvas Downloader extension in Chrome and try again. "),

    ("the puzzle-piece hint is dropped, so a student who has just added "
     "the extension is hunting for a button Chrome has hidden",
     UI,
     "<b>puzzle-piece</b> icon in Chrome's toolbar first",
     "button in Chrome's toolbar first"),

    ("the waiting card stops reading whether a tab was opened, so it "
     "tells a student to go and open the page it just opened for them",
     UI,
     "        where = (\"Your Canvas is now open in another tab.\"\n"
     "                 if opened else \"Open your Canvas in Chrome.\")",
     "        where = \"Your Canvas is now open in another tab.\""),

    ("an uncollected handoff is DISCARDED when the student presses the "
     "button again - which is exactly the student who could not see that "
     "it had worked, so their credential is destroyed at that moment",
     HANDOFF,
     "            _state['deadline'] = time.monotonic() + WINDOW_SECONDS\n",
     "            _state['deadline'] = time.monotonic() + WINDOW_SECONDS\n"
     "            _state.pop('payload', None)\n"),

    # -- 11. the icon, the session record, the readable log -------------
    ("the icon lights wherever you are, so it is on during ordinary "
     "Canvas browsing - which is how an extension gets uninstalled",
     BG,
     "  if (!(await onGrantedCanvasTab())) return paintBadge(false);",
     "  if (false) return paintBadge(false);"),

    ("the icon stops asking whether the app wants anything, so being on "
     "Canvas alone lights it and the badge stops meaning click me now",
     BG,
     "  const app = await findApp();\n"
     "  await paintBadge(!!(app && app.waiting));",
     "  await paintBadge(true);"),

    ("the popup's status reply paints the icon from its own answer, so "
     "that path drifts away from the one function that knows the rule",
     BG,
     "      refreshBadge();\n"
     "    });",
     "      paintBadge(!!(app && app.waiting));\n"
     "    });"),

    ("dev.py stops keeping the session record, so health.log is never "
     "written under the tool built to exercise production faithfully",
     DEV,
     "        from core.health_log import session_start\n"
     "        session_start()",
     "        pass"),

    ("dev.py kills its children before closing the session record, so "
     "the record describes a session already taken apart",
     DEV,
     "            from core.health_log import session_end\n"
     "            session_end('clean' if exit_code == 0 else 'error')",
     "            pass"),

    ("the debug log stops filtering closed-browser-socket notices, so a "
     "download with a backgrounded tab drowns the one file a user sends "
     "when something goes wrong - measured: 37,360 of 49,250 lines",
     DEBUG,
     "        if not is_app_logger and _is_browser_disconnect(record):",
     "        if False:"),

    ("the suppression goes SILENT - no first one kept, no count - so the "
     "log hides that it is happening at all",
     DEBUG,
     "            if count > 1:",
     "            if count > 0:"),

    ("the filter stops walking the exception chain, so the pair tornado "
     "actually raises is missed in one of its two orders",
     DEBUG,
     "        exc = exc.__cause__ or exc.__context__",
     "        exc = None"),

    # -- 12. the 2026-09-14 extension pass --------------------------------
    ("nothing closes the socket when the window ends, so the listener stays "
     "bound for the life of the app - the state measured on 2026-09-13",
     HANDOFF,
     "        threading.Thread(target=_close_when_window_ends, args=(server,),\n"
     "                         name='canvas-handoff-window', daemon=True).start()\n",
     ""),

    ("the window closing throws away a sign-in that arrived just before it",
     HANDOFF,
     "    if _stop_server(only=server, keep_payload=True):",
     "    if _stop_server(only=server, keep_payload=False):"),

    ("a deliberate stop - logout, cancel - keeps an uncollected credential, "
     "so the next press of the button signs in with it",
     HANDOFF,
     "    if _stop_server(only=None, keep_payload=False):",
     "    if _stop_server(only=None, keep_payload=True):"),

    ("a fresh bind after the window closed discards the student's own "
     "uncollected sign-in",
     HANDOFF,
     "            if kept is not None:\n"
     "                _state['payload'] = kept",
     "            if False:\n"
     "                _state['payload'] = kept"),

    ("the watcher stops noticing its listener was stopped, so every press of "
     "the button leaves a thread behind for the life of the app",
     HANDOFF,
     "            if _runtime().server is not server:\n"
     "                return                       # stopped, or superseded",
     "            if False:\n"
     "                return"),

    ("the handover is adopted OPTIMISTICALLY again, so a sign-in Canvas never "
     "confirmed is signed in and saved - measured before the fix",
     UI,
     "        _verdict = _adopt_restored_credential(credential, optimistic=False)",
     "        _verdict = _adopt_restored_credential(credential, optimistic=True)"),

    ("the adoption ignores the optimistic switch, so the one rule answers "
     "'trust it' for a credential that has never been confirmed",
     UI,
     "    if not optimistic:\n"
     "        # Nothing has ever confirmed this credential",
     "    if False:\n"
     "        # Nothing has ever confirmed this credential"),

    ("could-not-reach-Canvas collapses into Canvas-refused, so a student with "
     "a perfectly good Canvas tab is told to go and sign in again",
     UI,
     "        if _verdict == 'unconfirmed':",
     "        if False:"),

    ("the unconfirmed credential is left in the session in place of whatever "
     "a reconnect was holding",
     UI,
     "        if _had_token:\n"
     "            st.session_state['api_token'] = _prev_token\n"
     "        else:\n"
     "            st.session_state.pop('api_token', None)\n",
     ""),

    ("the arrival tick reruns at once, so the waiting card stays on screen "
     "through the blocking check and 'Got it' is never seen - finding 8",
     UI,
     "            st.session_state['handoff_arrived_shown'] = True\n"
     "            _state = 'handoff_arrived'",
     "            st.rerun(scope=\"app\")"),

    ("the arrival tick never hands over, so the student sits on 'Got it' "
     "while the credential waits uncollected",
     UI,
     "        elif (handoff.has_payload()\n"
     "              and not st.session_state.get('handoff_arrived_shown')):",
     "        elif handoff.has_payload():"),

    ("a new attempt inherits the previous attempt's arrived flag, so its own "
     "arrival skips the card",
     UI,
     "    st.session_state.pop('handoff_arrived_shown', None)\n"
     "    port = handoff.start()",
     "    port = handoff.start()"),

    ("the popup's [hidden] rule is dropped, so 'Finishing up in 5' is back "
     "on every screen - measured 2026-09-14 in Chromium 149",
     HTML,
     "    [hidden] { display: none !important; }\n",
     ""),
]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _write(rel: str, text: str) -> None:
    (REPO / rel).write_text(text, encoding="utf-8")


_SUMMARY = re.compile(r'(\d+) (passed|failed|skipped|error)')


def _run_tests() -> tuple[bool, dict]:
    """``(passed, counts)``. The counts are what makes a clean score honest."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTS, "-q", "-x", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    counts = {kind: int(n) for n, kind in _SUMMARY.findall(r.stdout or '')}
    return r.returncode == 0, counts


def _ports_held() -> list[int]:
    """Handoff ports something ELSE on this machine is already listening on.

    THIS PREFLIGHT IS NOT TIDINESS. On 2026-09-13 a `python dev.py` was left
    running while this harness ran. It held all three ports, so the `listening`
    fixture could not bind, and 26 tests ERRORED on every single run - which
    means every mutant was reported CAUGHT by a broken fixture rather than by a
    test. The pass printed **38/38**. Re-measured with the ports free, three of
    those mutants SURVIVE.

    A mutation harness exists to say whether the tests are real. One that
    reports a perfect score because its fixture is broken is worse than no
    harness, because the number gets written down.
    """
    import socket
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))      # this file lives in scripts/
    from core.handoff import PORTS
    held = []
    for p in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', p)) == 0:
                held.append(p)
    return held


def main(argv=None) -> int:
    targets = sorted({m[1] for m in HANDOFF_MUTANTS})
    snapshot = {rel: _read(rel) for rel in targets}

    held = _ports_held()
    if held:
        print("REFUSING TO RUN: something is already listening on "
              + ", ".join(str(p) for p in held) + ".")
        print("The handoff tests need to OWN the listener. With the ports "
              "held they skip or error,")
        print("and a mutant that nothing exercised is then reported CAUGHT. "
              "That is how this")
        print("harness printed 38/38 on 2026-09-13 while three mutants were "
              "in fact surviving.")
        print("\nClose your `python dev.py` or Canvas Downloader and run "
              "this again.")
        return 2

    print("Baseline ...", end=" ", flush=True)
    ok, base = _run_tests()
    if not ok:
        print("RED - fix that first.")
        return 2
    print(f"green ({base.get('passed', 0)} passed, "
          f"{base.get('skipped', 0)} skipped)")

    caught = 0
    survivors = []
    for label, rel, old, new in HANDOFF_MUTANTS:
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
            passed, counts = _run_tests()
        finally:
            _write(rel, snapshot[rel])
        # NEW SKIPS mean the run did not exercise what it claims to, so the
        # verdict is worthless whichever way it fell.
        #
        # ERRORS are deliberately NOT treated that way, and the distinction was
        # measured. An error here is usually a fixture refusing to proceed, and
        # `tests/test_handoff.py`'s `listening` fixture now refuses in exactly
        # one circumstance - the code under test LEAKED a listener - which is a
        # genuine catch. The case that started all this, another program
        # holding the ports, SKIPS instead, and the preflight above stops the
        # pass before it can arise at all. So errors are legitimate and skips
        # are not.
        #
        # ...but ONLY when the mutant was not caught. A skip cannot manufacture
        # a FAILURE, so a run that failed caught the mutant whatever else it
        # skipped; it is the SURVIVED verdict that a skip makes worthless,
        # because the test that would have objected may be the one that did not
        # run. Measured: the checker mutant below both failed a test (caught)
        # and skipped one, and aborting on that lost a real result.
        if passed and counts.get('skipped', 0) > base.get('skipped', 0):
            print(f"\nABORT: this mutant SURVIVED a run that skipped tests, so "
                  f"the verdict is worthless - the test that would have "
                  f"objected may be one that never ran.\n"
                  f"  mutant: {label}\n"
                  f"  baseline: {base}\n"
                  f"  this run: {counts}")
            return 4
        if passed:
            print(f"  [SURVIVED] {label}")
            survivors.append(label)
        else:
            print(f"  [CAUGHT ] {label}")
            caught += 1

    total = len(HANDOFF_MUTANTS)
    print(f"\n{caught}/{total} caught")
    for s in survivors:
        print(f"  SURVIVED: {s}")
    return 0 if caught == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
