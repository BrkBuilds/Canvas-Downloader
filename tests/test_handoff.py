"""Taking a Canvas session from the browser the student already uses.

The zero-typing route: the extension reports the host of the tab it read, so
nothing is picked, typed or entered. Supplementary by the product owner's
ruling - the in-app sign-in stays the straight path.

This is a LOOPBACK LISTENER, so most of this file is its threat model rather
than its happy path. Five properties, each driven against the real server:

1. loopback only;
2. time-boxed and user-initiated, closing on the first accepted handoff;
3. **extension origins only** - a web page cannot set its own `Origin`, so it
   cannot pretend to be one, and that single check is what makes opening the
   port acceptable;
4. nothing readable by a page even if it did POST (CORS names extension
   origins only);
5. the credential is verified and the user named, so a session that is not
   theirs is visible rather than silent.

Everything here drives the REAL module over real HTTP. No mocks, no network
beyond loopback, no credentials.
"""
from __future__ import annotations

import ast
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core import handoff

_ROOT = Path(__file__).resolve().parents[1]
EXT = 'chrome-extension://abcdefghijklmnopabcdefghijklmnop'
PAGE = 'https://evil.example'


#: Whether this session has ever successfully opened a handoff port.
#:
#: It is what separates the two reasons `start()` can answer 0, and they need
#: OPPOSITE verdicts. Both were met on 2026-09-13:
#:
#: * something ELSE on the machine holds the ports (a `python dev.py` left
#:   running). Not a product failure - 26 tests reported as errors with a
#:   message that explained nothing. SKIP.
#: * the code under test LEAKED a listener, so the ports it had a moment ago
#:   are gone. That is the defect section 9 exists for, and skipping it hides
#:   exactly the bug the suite is here to catch. FAIL.
#:
#: Collapsing them into a skip was measured doing real harm: the mutation pass
#: turned the mutant *"stop() leaves the socket open"* from CAUGHT into 27
#: skips, i.e. a leak the suite used to notice became invisible.
_EVER_BOUND = False


@pytest.fixture
def listening():
    global _EVER_BOUND
    handoff.stop()
    port = handoff.start()
    if not port:
        ports = ', '.join(str(p) for p in handoff.PORTS)
        if _EVER_BOUND:
            pytest.fail(
                f"ports {ports} were available earlier in this very session "
                f"and are not now, so a listener was LEAKED by the code under "
                f"test rather than held by another program. That is the "
                f"re-import orphan defect (section 9) or a stop() that no "
                f"longer closes its socket.")
        pytest.skip(
            f"ports {ports} are all in use by another process on this machine "
            f"(a running `python dev.py` or Canvas Downloader will do it). "
            f"Close it and re-run; this test needs to own the listener.")
    _EVER_BOUND = True
    yield port
    handoff.stop()


def _call(port, path, payload=None, origin=None, method=None):
    url = f'http://127.0.0.1:{port}{path}'
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=body, method=method or ('POST' if body else 'GET'))
    if origin:
        req.add_header('Origin', origin)
    if body:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read() or b'{}'
            return resp.status, json.loads(raw or b'{}'), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, {}, dict(e.headers or {})


# ---------------------------------------------------------------------------
# 1. Only a browser extension may talk to it
# ---------------------------------------------------------------------------

def test_a_WEB_PAGE_cannot_hand_over_a_session(listening):
    """The check the whole design rests on.

    `Origin` is a forbidden header name, so a page's script cannot set it -
    the browser does. A page on the internet therefore cannot pretend to be
    `chrome-extension://`, which is what stops any open tab from talking to a
    listener on the user's own machine.
    """
    status, _body, _h = _call(listening, '/canvas-session',
                              {'host': 'x.instructure.com',
                               'cookies': {'canvas_session': 'STOLEN'}},
                              origin=PAGE)
    assert status == 403
    assert handoff.result() is None, (
        "a web page's POST was accepted, so any open tab can sign the app in")


def test_a_web_page_cannot_even_PROBE_for_the_app(listening):
    """`/ping` exists so the extension can find the port. A page learning that
    the app is listening is harmless, but there is no reason to tell it."""
    status, _b, _h = _call(listening, '/ping', origin=PAGE)
    assert status == 403


def test_an_extension_gets_no_CORS_grant_for_a_PAGES_origin(listening):
    """Even if a page could POST, it must not be able to READ the answer.
    Echoing a page's origin here is exactly how that would leak."""
    _s, _b, headers = _call(listening, '/canvas-session',
                            {'host': 'x', 'cookies': {'canvas_session': 'A'}},
                            origin=PAGE)
    allowed = headers.get('Access-Control-Allow-Origin')
    assert allowed != PAGE, "a web page was granted read access to the reply"
    assert not allowed or allowed.startswith('chrome-extension://')


def test_an_extension_IS_allowed(listening):
    """The positive control. A check that can only say no is not a check."""
    status, body, headers = _call(listening, '/ping', origin=EXT)
    assert status == 200
    assert body.get('app') == 'canvas-downloader'
    assert body.get('waiting') is True
    assert headers.get('Access-Control-Allow-Origin') == EXT


def test_the_preflight_answers_for_an_extension_and_refuses_a_page(listening):
    assert _call(listening, '/canvas-session', origin=EXT,
                 method='OPTIONS')[0] == 204
    assert _call(listening, '/canvas-session', origin=PAGE,
                 method='OPTIONS')[0] == 403


# ---------------------------------------------------------------------------
# 2. Loopback only
# ---------------------------------------------------------------------------

def test_it_is_bound_to_LOOPBACK_and_nothing_else(listening):
    """Bound to 0.0.0.0 this would accept a session from anyone on the campus
    wifi."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2)
        assert probe.connect_ex(('127.0.0.1', listening)) == 0

    # The machine's own routable address must NOT answer.
    try:
        outward = socket.gethostbyname(socket.gethostname())
    except OSError:
        pytest.skip("no routable address to test against")
    if outward.startswith('127.'):
        pytest.skip("this machine resolves only to loopback")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2)
        assert probe.connect_ex((outward, listening)) != 0, (
            f"the handoff port answers on {outward}, so anything on this "
            f"network can hand the app a Canvas session")


# ---------------------------------------------------------------------------
# 3. Time-boxed, one-shot, and closable
# ---------------------------------------------------------------------------

def test_the_FIRST_handoff_wins_and_closes_the_window(listening):
    """A listener that stays open after it has what it came for is a standing
    fixture, which is what the time box exists to avoid."""
    assert _call(listening, '/canvas-session',
                 {'host': 'a.instructure.com',
                  'cookies': {'canvas_session': 'FIRST'}}, origin=EXT)[0] == 200
    assert handoff.waiting() is False
    second = _call(listening, '/canvas-session',
                   {'host': 'b.instructure.com',
                    'cookies': {'canvas_session': 'SECOND'}}, origin=EXT)
    assert second[0] == 409
    got = handoff.result()
    assert got['cookies']['canvas_session'] == 'FIRST'


def test_a_handoff_is_consumed_exactly_once(listening):
    """Process-global state read by a Streamlit run. Left in place it would be
    re-adopted on a later rerun - the shape `unlocked_token()` had."""
    _call(listening, '/canvas-session',
          {'host': 'a.instructure.com', 'cookies': {'canvas_session': 'A'}},
          origin=EXT)
    assert handoff.result() is not None
    assert handoff.result() is None


def test_an_expired_window_stops_accepting(listening, monkeypatch):
    monkeypatch.setattr(handoff, 'WINDOW_SECONDS', -1.0)
    handoff.start()                       # re-arms with the negative clock
    assert handoff.waiting() is False
    assert _call(listening, '/canvas-session',
                 {'host': 'x', 'cookies': {'canvas_session': 'A'}},
                 origin=EXT)[0] == 409


def test_stopping_closes_the_socket(listening):
    handoff.stop()
    assert handoff.port() == 0
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2)
        assert probe.connect_ex(('127.0.0.1', listening)) != 0, (
            "the port is still open after stop(), so a logout leaves a "
            "listener accepting Canvas sessions")


def test_starting_twice_re_arms_rather_than_losing_the_listener(listening):
    """A user pressing the button again must not end up with no listener."""
    again = handoff.start()
    assert again == listening
    assert handoff.waiting() is True


def test_re_arming_KEEPS_a_handoff_that_has_arrived_but_not_been_collected():
    """Pressing the button again must not destroy the credential.

    The re-arm used to `_state.pop('payload', None)` on the reasoning that a
    new attempt starts clean. But the only thing that can be sitting there is a
    session THIS student sent seconds ago, and the student pressing the button
    a second time is precisely the one who could not see that it had worked -
    which is exactly the case reported on 2026-09-13. Discarding their sign-in
    at that moment is the worst available answer.

    A mutation pass caught that nothing tested it: re-adding the pop SURVIVED.
    """
    handoff.stop()
    port = handoff.start()
    if not port:
        pytest.skip("the handoff ports are in use by another process")
    try:
        assert _call(port, '/canvas-session',
                     {'host': 'cbscanvas.instructure.com',
                      'cookies': {'canvas_session': 'THEIRS'}},
                     origin=EXT)[0] == 200
        assert handoff.has_payload() is True

        again = handoff.start()                 # the second button press
        assert again == port, "the re-arm moved the listener"
        assert handoff.has_payload() is True, (
            "pressing the button again threw away a sign-in that had already "
            "arrived and had not been collected yet")

        got = handoff.result()
        assert got and got['cookies']['canvas_session'] == 'THEIRS'
    finally:
        handoff.stop()


def test_has_payload_does_NOT_consume_it(listening):
    """It is the question `waiting()` cannot answer, and asking it must not be
    the thing that loses the answer - `result()` is the only consumer."""
    _call(listening, '/canvas-session',
          {'host': 'x.instructure.com', 'cookies': {'canvas_session': 'A'}},
          origin=EXT)
    assert handoff.has_payload() is True
    assert handoff.has_payload() is True, "asking twice consumed it"
    assert handoff.result() is not None
    assert handoff.has_payload() is False


# ---------------------------------------------------------------------------
# 4. What it will and will not accept
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload,why", [
    ({'cookies': {'canvas_session': 'A'}}, 'no host'),
    ({'host': 'x.instructure.com'}, 'no cookies'),
    ({'host': 'x.instructure.com', 'cookies': {}}, 'empty cookies'),
    ({'host': 'x.instructure.com', 'cookies': {'_csrf_token': 'A'}},
     'a CSRF token is not a session'),
    ({'host': '', 'cookies': {'canvas_session': 'A'}}, 'blank host'),
])
def test_an_incomplete_handoff_is_refused(listening, payload, why):
    status, _b, _h = _call(listening, '/canvas-session', payload, origin=EXT)
    assert status == 400, why
    assert handoff.result() is None


def test_only_the_named_cookies_are_kept(listening):
    """An extension bug, or a future version of it, must not be able to widen
    what the app stores just by sending more."""
    _call(listening, '/canvas-session',
          {'host': 'a.instructure.com',
           'cookies': {'canvas_session': 'A', '_csrf_token': 'B',
                       'ESTSAUTH': 'SSO', 'whatever': 'C'}}, origin=EXT)
    got = handoff.result()
    assert set(got['cookies']) == {'canvas_session', '_csrf_token'}, (
        f"kept {sorted(got['cookies'])}; only the session and CSRF token are "
        "accepted")


def test_an_oversized_body_is_refused_without_being_read(listening):
    """An unbounded read on a socket is its own bug. A session cookie is a few
    hundred bytes."""
    status, _b, _h = _call(listening, '/canvas-session',
                           {'host': 'x', 'cookies': {'canvas_session': 'A' * 70000}},
                           origin=EXT)
    assert status == 400
    assert handoff.result() is None


def test_an_unknown_path_is_not_a_handoff(listening):
    assert _call(listening, '/', origin=EXT)[0] == 404
    assert _call(listening, '/anything',
                 {'host': 'x', 'cookies': {'canvas_session': 'A'}},
                 origin=EXT)[0] == 404


# ---------------------------------------------------------------------------
# 5. The extension is consistent with the app
# ---------------------------------------------------------------------------

def _extension_js() -> str:
    """Every script the extension ships, as one blob.

    Reads the DIRECTORY rather than naming `popup.js`, because on 2026-09-12
    the ports and the cookie names moved into `background.js` - the work had to
    leave the popup, which Chrome destroys when it shows a permission prompt.
    A test that names one file passes vacuously the day the code moves.
    """
    ext = _ROOT / 'extension'
    return '\n'.join(p.read_text(encoding='utf-8')
                     for p in sorted(ext.glob('*.js')))


def test_the_extension_and_the_app_agree_on_the_PORTS():
    """Two lists, two files, one contract - and the extension cannot probe a
    port the app never opens."""
    js = _extension_js()
    for port in handoff.PORTS:
        assert str(port) in js, (
            f"the app listens on {port} and the extension never tries it")


def test_the_extension_and_the_app_agree_on_the_COOKIES():
    js = _extension_js()
    for name in handoff.ACCEPTED_COOKIES:
        assert name in js, (
            f"the app accepts {name} and the extension never sends it")


def test_the_extension_asks_for_NO_site_access_at_install_time():
    """The difference between "may read the cookies of the site you are on,
    when you click" and "may read every site's cookies, for ever"."""
    manifest = json.loads(
        (_ROOT / 'extension' / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['manifest_version'] == 3
    assert 'host_permissions' not in manifest, (
        "the extension holds site access from the moment it is installed; it "
        "should request the one site at click time instead")
    assert manifest['optional_host_permissions'], "no way to ask at all"

    # `storage` and `alarms` were added on 2026-09-12 and neither can see a
    # page: `storage` carries the one pending sign-in across the popup being
    # destroyed by Chrome's permission prompt, and `alarms` drives the
    # once-a-minute question to the app ON THIS MACHINE that lets the icon say
    # "now". This set is a ceiling, not the property - the property is below.
    assert set(manifest['permissions']) <= {
        'cookies', 'activeTab', 'storage', 'alarms'}, (
        f"the extension asks for more than it needs: {manifest['permissions']}")

    # THE PROPERTY, stated separately so it survives the ceiling being raised.
    # Any of these would let the extension watch browsing, which the product
    # owner named as the thing that would make a student uninstall it.
    for browsing in ('tabs', 'webNavigation', 'history', 'browsingData',
                     'bookmarks'):
        assert browsing not in manifest['permissions'], (
            f"`{browsing}` lets the extension see where the user goes. The "
            f"whole design rests on it never being able to.")
    assert not manifest.get('content_scripts'), (
        "a content script runs on pages; this extension never should")

    js = _extension_js()
    assert 'permissions.request' in js, (
        "nothing ever asks for the site permission, so the cookie read fails")


def test_the_extension_posts_only_to_loopback():
    js = (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')
    import re
    for url in re.findall(r'fetch\(`([^`]+)`', js):
        assert url.startswith('http://127.0.0.1:'), (
            f"the extension talks to {url}, which is not this machine")


# ---------------------------------------------------------------------------
# 6. The app side of the flow
# ---------------------------------------------------------------------------

def test_the_collector_is_called_from_app_py():
    """Otherwise the handoff arrives on the listener's thread and nothing ever
    collects it - the `refresh_silently` shape."""
    src = (_ROOT / 'app.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', '') == 'adopt_pending_handoff']
    assert calls, "app.py never collects a handoff"


def test_logging_out_stops_the_listener():
    """A logout that leaves a loopback socket accepting Canvas sessions is a
    logout in name only. Asserted at the ONE place both logout and
    force_reauth go through."""
    src = (_ROOT / 'ui' / 'auth.py').read_text(encoding='utf-8')
    fn = next(f for f in ast.walk(ast.parse(src))
              if isinstance(f, ast.FunctionDef)
              and f.name == '_reset_browser_login_state')
    assert 'cancel_browser_handoff' in ast.unparse(fn), (
        "the handoff listener survives a logout")


def test_a_handoff_adopts_through_the_SAME_door_as_every_other_credential():
    """The verdict about what a network blip means, the optimistic restore and
    the rolled-cookie write-back all live in `_adopt_restored_credential`. A
    second opinion here is how the routes come to disagree."""
    src = (_ROOT / 'ui' / 'auth.py').read_text(encoding='utf-8')
    fn = next(f for f in ast.walk(ast.parse(src))
              if isinstance(f, ast.FunctionDef)
              and f.name == 'adopt_pending_handoff')
    body = ast.unparse(fn)
    assert '_adopt_restored_credential' in body
    assert 'validate_token' not in body, (
        "adopt_pending_handoff validates the credential itself instead of "
        "going through the one adoption")


def test_a_handoff_is_also_upgraded_to_a_long_lived_token():
    """A session is a day; a token the institution allows is months. It also
    takes the extension out of the loop once it has worked once."""
    src = (_ROOT / 'ui' / 'auth.py').read_text(encoding='utf-8')
    fn = next(f for f in ast.walk(ast.parse(src))
              if isinstance(f, ast.FunctionDef)
              and f.name == 'adopt_pending_handoff')
    body = ast.unparse(fn)
    assert '_upgrade_to_access_token' in body
    assert '_persist_browser_login' in body, (
        "a handoff at a token-restricted school is never saved at all")

def test_every_file_the_manifest_NAMES_actually_exists():
    """Chrome refuses the WHOLE extension for one missing file.

    Shipped exactly that: the manifest declared `icon128.png` and nothing
    created it, so Chrome answered *"Could not load icon 'icon128.png'
    specified in 'icons'. Manifest could not be loaded"* and the extension did
    not install at all. Not a degraded icon - a dead feature, and the
    product owner hit it before any test did.

    Cheap, and it covers every future reference rather than that one icon.
    """
    ext = _ROOT / 'extension'
    manifest = json.loads((ext / 'manifest.json').read_text(encoding='utf-8'))

    referenced = set()
    referenced.update((manifest.get('icons') or {}).values())
    action = manifest.get('action') or {}
    referenced.update((action.get('default_icon') or {}).values())
    if action.get('default_popup'):
        referenced.add(action['default_popup'])
    for key in ('content_scripts', 'web_accessible_resources'):
        for entry in manifest.get(key) or ():
            for field in ('js', 'css', 'resources'):
                referenced.update(entry.get(field) or ())
    worker = (manifest.get('background') or {}).get('service_worker')
    if worker:
        referenced.add(worker)

    assert referenced, "the manifest references nothing at all"
    missing = sorted(r for r in referenced if not (ext / r).is_file())
    assert not missing, (
        f"the manifest names files that do not exist: {missing}. Chrome "
        f"refuses the entire extension, so this is a dead feature rather "
        f"than a missing icon.")


def test_the_toolbar_button_HAS_an_icon():
    """The button the student has to find and click. Without `default_icon`
    Chrome draws a grey placeholder, which is not something anyone would look
    for in a toolbar."""
    manifest = json.loads(
        (_ROOT / 'extension' / 'manifest.json').read_text(encoding='utf-8'))
    assert (manifest.get('action') or {}).get('default_icon'), (
        "the toolbar button has no icon of its own")


# ---------------------------------------------------------------------------
# 5b. The extension's COPY, which is the product for a student
#
# Ruled on by the product owner, 2026-09-12, after using it:
#   "'Send my session' is scary and developer wording - developer wording IS
#    BANNED FROM THE CHROME EXTENSION COPY. The copy needs to be as USER
#    FRIENDLY AS POSSIBLE (non-technical bad-at-using-computer students should
#    be able to understand it)."
# So it is a test, not a preference.
# ---------------------------------------------------------------------------

#: Words a student does not have and does not need. Each one is a thing the
#: EXTENSION knows and the READER should never have to.
_BANNED_WORDS = (
    'session', 'cookie', 'token', 'origin', 'localhost', '127.0.0.1',
    'handoff', 'payload', 'endpoint', 'port', 'json', 'http', 'api',
    'csrf', 'httponly', 'credential', 'auth', 'header', 'request body',
)


def _js_strings(src: str) -> list[str]:
    """Every string literal in *src*, by one scan that also knows comments.

    Neither a regex for strings nor a regex for comments can be run first,
    because each construct can contain the other. Both failures were measured
    here on 2026-09-12, by running the positive control:

    * a `"..."` regex paired the wrong quotes around
      `\'<span class="spin"></span>\'` - a single-quoted string containing two
      double quotes - and captured code as copy;
    * stripping `/* ... */` first ATE the `/*` inside the template literal
      `` `${url.origin}/*` ``, unbalancing the backtick and swallowing forty
      lines, so the guard reported `chrome.storage.session` as copy.

    Both are false POSITIVES, which is the direction that gets a guard
    disabled. One pass, with the opening token deciding the closing one.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ''

        if ch == '/' and nxt == '/':                    # line comment
            while i < n and src[i] != '\n':
                i += 1
            continue
        if ch == '/' and nxt == '*':                    # block comment
            end = src.find('*/', i + 2)
            i = n if end == -1 else end + 2
            continue
        if ch in '"\'`':                                # string literal
            quote, i, buf = ch, i + 1, []
            while i < n:
                c = src[i]
                if c == '\\':
                    i += 2
                    continue
                if c == quote:
                    break
                buf.append(c)
                i += 1
            text = ''.join(buf)
            # An INTERPOLATED template literal is code, never copy. In this
            # file every student-facing sentence is double-quoted and backticks
            # build URLs and permission match patterns - `${url.origin}/*`, which
            # is what made this guard fire on the word "origin" the first time
            # it worked. A backtick string with no `${` could still be prose, so
            # only the interpolated ones are excluded.
            if not (quote == '`' and '${' in text):
                out.append(text)
            i += 1
            continue
        i += 1
    return out


def _visible_copy() -> dict[str, str]:
    """Every string a student can actually read, per file.

    HTML text and attributes, and the quoted strings in `popup.js` that reach
    `show()`. Comments and code identifiers are excluded on purpose: the files
    have to be able to EXPLAIN the rule without breaking it, which is the
    comment-matching trap this repo has hit four times.
    """
    import re
    ext = _ROOT / 'extension'

    html = (ext / 'popup.html').read_text(encoding='utf-8')
    html_body = html.split('</style>', 1)[-1]
    text = re.sub(r'<[^>]+>', ' ', html_body)
    text += ' ' + ' '.join(re.findall(r'(?:title|alt|placeholder)="([^"]*)"',
                                      html_body))

    js = (ext / 'popup.js').read_text(encoding='utf-8')
    strings = _js_strings(js)          # comments handled inside the scanner

    manifest = json.loads((ext / 'manifest.json').read_text(encoding='utf-8'))
    meta = ' '.join([
        manifest.get('name', ''), manifest.get('description', ''),
        (manifest.get('action') or {}).get('default_title', ''),
    ])

    return {
        'popup.html': text,
        'popup.js': ' '.join(strings),
        'manifest.json': meta,
    }


@pytest.mark.parametrize("word", _BANNED_WORDS)
def test_no_DEVELOPER_WORDING_reaches_the_student(word):
    """The copy is the product here. A student who reads "send my session" does
    not know whether they are about to give something away."""
    import re
    # WORD boundaries, not substrings: "port" is inside "important" and
    # "auth" is inside "author". A guard that fires on those teaches people
    # to ignore it.
    pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.I)
    offenders = []
    for name, copy in _visible_copy().items():
        m = pattern.search(copy)
        if m:
            lo = max(0, m.start() - 55)
            offenders.append(f"{name}: ...{copy[lo:m.end() + 20]}...")
    assert not offenders, (
        f"the word {word!r} reaches the student:\n  " + "\n  ".join(offenders)
        + "\n\nDeveloper wording is banned from the extension copy (product "
          "owner, 2026-09-12). Say what happens, in the words a student "
          "already has.")


def test_the_popup_GUIDES_rather_than_presenting_one_button():
    """A student who does not already know the flow has to be able to learn it
    from the screen. Three steps, and the popup marks which one they are on."""
    html = (_ROOT / 'extension' / 'popup.html').read_text(encoding='utf-8')
    for n in (1, 2, 3):
        assert f'id="step{n}"' in html, f"step {n} is not on the screen"
    js = (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')
    assert 'setSteps' in js, "the steps are decoration, not a live guide"
    assert "classList.toggle(\"now\"" in js, (
        "nothing marks the step the student is actually on")


def test_the_popup_TELLS_THEM_when_they_are_on_the_wrong_page():
    """The product owner asked for exactly this: "notice if the user is on
    canvas and let them know they're on the right page"."""
    js = (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')
    assert 'isCanvasHost' in js, (
        "the popup never checks whether this tab is Canvas at all")
    assert 'does not look like Canvas' in js, (
        "there is no wrong-page state, so a student on the wrong tab is told "
        "nothing useful")


def test_the_extension_recognises_canvas_from_the_APPS_OWN_list():
    """A second hand-written list of Canvas hosts is the duplicate-primitive
    failure this repo pays for most. The generator derives it, and this fails
    when the two drift."""
    import subprocess
    out = subprocess.run(
        [sys.executable, str(_ROOT / 'scripts' / 'build_extension_hosts.py'),
         '--check'],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, (
        f"extension/canvas-hosts.js is stale or missing:\n{out.stdout}\n"
        f"{out.stderr}")


def test_the_popups_own_references_exist_too():
    """One level down from the manifest, and the same failure: a popup whose
    script 404s is a card with a dead button."""
    import re
    ext = _ROOT / 'extension'
    html = (ext / 'popup.html').read_text(encoding='utf-8')
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
        assert (ext / src).is_file(), f"popup.html loads {src}, which is absent"


# ---------------------------------------------------------------------------
# 6. HTTP framing: the connection has to survive being refused
#
# All of this was found by building the dev-testing harness on 2026-09-12 and
# reading what the listener actually put on the wire. Both bugs sat on the
# extension's live path and no test in sections 1-5 could see either, because
# `urllib` opens a connection per request - so an unread body is followed by
# EOF and the server never trips over it. A BROWSER does the opposite: it keeps
# the connection and sends the next request down it, which is exactly the pair
# the extension makes (`GET /ping` to find the port, then
# `POST /canvas-session`).
# ---------------------------------------------------------------------------

def _raw(method, path, origin, body=None):
    lines = [f'{method} {path} HTTP/1.1', 'Host: 127.0.0.1', f'Origin: {origin}']
    if body is not None:
        lines += ['Content-Type: application/json',
                  f'Content-Length: {len(body)}']
    return ('\r\n'.join(lines) + '\r\n\r\n').encode('ascii') + (body or b'')


#: What this helper reports for a connection the server has given up on. One
#: marker for every way that shows: a read that returns nothing, and a SEND
#: that is aborted because the close raced the write - which is what an
#: oversized refusal actually does, since the server closes while the client is
#: still pushing 64 KB.
GONE = '<connection gone>'


def _one_socket(port, requests, *, settle=0.3):
    """Send *requests* down ONE connection; answer the status lines.

    Tolerant of the connection dying, because that is a RESULT here rather
    than an error: stops at the first sign of it and reports :data:`GONE`.
    """
    import time
    out = []
    sock = socket.create_connection(('127.0.0.1', port), timeout=5)
    sock.settimeout(3)
    try:
        for method, path, origin, body in requests:
            try:
                sock.sendall(_raw(method, path, origin, body))
            except (OSError, TimeoutError):
                out.append(GONE)
                break
            time.sleep(settle)
            try:
                chunk = sock.recv(65536)
            except (OSError, TimeoutError):
                out.append(GONE)
                break
            if not chunk:
                out.append(GONE)
                break
            out.append(chunk.split(b'\r\n', 1)[0].decode('latin-1', 'replace'))
    finally:
        try:
            sock.close()
        except OSError:
            pass
    return out


@pytest.mark.parametrize("first,why", [
    (('POST', '/canvas-session', PAGE, b'{"host":"x","cookies":{}}'),
     'a refused page origin'),
    (('POST', '/nope', EXT, b'{"host":"x","cookies":{}}'),
     'an unknown path'),
])
def test_a_REFUSED_request_does_not_poison_the_NEXT_one(listening, first, why):
    """Every refusal answers WITHOUT reading the request body, and the
    connection is keep-alive, so those bytes are still in the socket when the
    server goes looking for the next request line - and it reads the tail of a
    JSON body as a request.

    MEASURED 2026-09-12, with the drain removed::

        1st: HTTP/1.1 403 Forbidden
        2nd: HTTP/1.1 501 Unsupported method ('{"host":"x","cookies":{}}GET')

    The second request is the extension's own `POST /canvas-session`, so this
    is a handoff that cannot arrive - on a connection the browser is entitled
    to reuse.
    """
    statuses = _one_socket(listening, [first, ('GET', '/ping', EXT, None)])
    assert len(statuses) == 2, statuses
    assert statuses[1].startswith('HTTP/1.1 200'), (
        f"after {why} the next request on the same connection answered "
        f"{statuses[1]!r} instead of 200 - the refused body was left in the "
        f"socket and read as a request line")


def test_a_204_PREFLIGHT_CARRIES_NO_BODY(listening):
    """RFC 9110: "A 204 response is terminated by the end of the header
    section" - it cannot have a Content-Length, and a client that knows that
    does not read a body. So two bytes of `{}` stay in the socket and the
    connection desynchronises.

    MEASURED 2026-09-12: with the body restored, `Content-Length: 2`, the
    client read 0 bytes, and the server raised `ConnectionResetError` into
    `handle_error`. Chrome sends this preflight before EVERY handoff POST,
    because `Content-Type: application/json` is not CORS-safelisted.
    """
    status, _b, headers = _call(listening, '/canvas-session', origin=EXT,
                                method='OPTIONS')
    assert status == 204
    assert 'Content-Length' not in headers, (
        f"a 204 announced a body ({headers.get('Content-Length')} bytes)")
    assert 'Content-Type' not in headers, "a 204 announced a content type"


def test_an_OVERSIZED_refused_body_is_never_read(listening):
    """Draining is a courtesy to a well-behaved client, not an obligation to
    read whatever a refused caller decided to send. Past the cap the
    connection is closed instead, so the refusal costs one header parse."""
    body = b'{"host":"x","cookies":{"canvas_session":"' \
           + b'A' * (handoff.MAX_BODY_BYTES + 50) + b'"}}'
    statuses = _one_socket(listening,
                           [('POST', '/canvas-session', EXT, body),
                            ('GET', '/ping', EXT, None)])
    # The 400 itself is asserted by `test_an_oversized_body_is_refused...`
    # through urllib. What is asserted HERE is the disposal: the connection
    # does not survive, so nothing on it can have read 64 KB. Measured: the
    # close races the client's own send, so the `GONE` marker can land on
    # either the first entry or the second.
    assert GONE in statuses, (
        f"the connection survived an oversized refusal, so the body was "
        f"drained rather than disowned: {statuses}")
    assert not any(s.startswith('HTTP/1.1 200') for s in statuses), statuses
    assert handoff.result() is None


def test_a_dropped_connection_is_LOGGED_not_dumped_to_stderr(listening, caplog):
    """`socketserver`'s default prints a traceback to stderr, and this listener
    silences `log_message` precisely so it never writes there - in a windowed
    Windows build there is no stderr at all. Logged rather than swallowed,
    because a listener that reports nothing cannot be diagnosed."""
    import io
    import logging
    import sys as _sys

    handler = object.__new__(handoff._Handler)
    buf = io.StringIO()
    real_stderr, _sys.stderr = _sys.stderr, buf
    try:
        with caplog.at_level(logging.DEBUG, logger='core.handoff'):
            try:
                raise ConnectionResetError(10054, 'client went away')
            except ConnectionResetError:
                handler.handle_error(None, ('127.0.0.1', 1234))
    finally:
        _sys.stderr = real_stderr

    assert 'Traceback' not in buf.getvalue(), (
        f"a dropped connection printed a traceback to stderr: "
        f"{buf.getvalue()[:200]!r}")
    assert any('disconnect' in r.message.lower() for r in caplog.records), (
        "a dropped connection was swallowed without a word")


def test_an_UNEXPECTED_handler_failure_is_still_reported(listening, caplog):
    """The positive control for the test above. Quietening a hang-up must not
    quieten a real bug: `except Exception: pass` shaped as an error handler is
    how a listener stops being diagnosable."""
    import logging

    handler = object.__new__(handoff._Handler)
    with caplog.at_level(logging.DEBUG, logger='core.handoff'):
        try:
            raise ValueError('something genuinely broken')
        except ValueError:
            handler.handle_error(None, ('127.0.0.1', 1234))
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "a real handler failure was logged below warning, or not at all")


def test_every_extension_script_PARSES():
    """A JavaScript syntax error makes the extension silently do nothing.

    That is the same failure shape as the missing icon the product owner hit on
    2026-09-12 - Chrome refuses the file and reports it nowhere the student will
    look - and it is the one class of extension defect a Python test suite can
    catch outright. `node --check` is the whole check.

    Skips where node is absent rather than passing vacuously, because a guard
    that quietly stops running is worse than no guard.
    """
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip("node is not installed, so the extension scripts cannot be "
                    "syntax-checked here")

    ext = _ROOT / 'extension'
    scripts = sorted(ext.glob('*.js'))
    assert scripts, "the extension ships no scripts at all"

    broken = []
    for path in scripts:
        out = subprocess.run([node, '--check', str(path)],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            broken.append(f"{path.name}: {out.stderr.strip().splitlines()[:3]}")
    assert not broken, (
        "extension script(s) do not parse, so the extension is inert:\n  "
        + "\n  ".join(broken))


def test_the_popup_CANNOT_HANG_waiting_for_an_answer():
    """Reported stuck on "Checking / One moment" (2026-09-12).

    Two unbounded waits could do it: the worker's `fetch` to a port that
    accepts and never answers, and the popup's own `sendMessage` when the
    worker failed to start. A popup that hangs tells the student nothing, so
    both ends carry a deadline now.
    """
    popup = (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')
    worker = (_ROOT / 'extension' / 'background.js').read_text(encoding='utf-8')

    assert 'ASK_TIMEOUT_MS' in popup and 'setTimeout' in popup, (
        "the popup waits on the worker with no deadline, so a worker that "
        "never answers leaves it on 'Checking' for ever")
    assert worker.count('AbortSignal.timeout') >= 2, (
        "the worker's requests to the app are unbounded; a socket that accepts "
        "and says nothing would hang the popup behind it")


def test_the_popup_ALWAYS_SAYS_whether_the_app_is_running():
    """The product owner's instruction after using it: "we should let the user
    know visually and with text whether or not canvas downloader is ON or OFF".

    It is reported FIRST in `read()`, before the tab checks, so it is right even
    on the wrong-page screen - which is the screen they were looking at.
    """
    popup = (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')
    html = (_ROOT / 'extension' / 'popup.html').read_text(encoding='utf-8')

    assert 'id="appstate"' in html and 'id="appText"' in html
    assert 'showAppState' in popup
    assert 'is not running' in popup, "nothing says the app is off"
    assert 'ready to log in' in popup, "nothing says the app is ready"

    # It must be answered before the tab is even looked at, or the wrong-page
    # screen goes back to saying nothing about the app.
    first_call = popup.index('showAppState(app)')
    tab_query = popup.index('chrome.tabs.query')
    assert first_call < tab_query, (
        "the app's on/off state is decided after the tab checks, so a student "
        "on the wrong tab is told nothing about whether the app is even open")


# ---------------------------------------------------------------------------
# 7. Opening the student's Canvas for them
#
# Product owner, 2026-09-12: "we literally create friction by having the user
# manually find their URL when their URL is already typed in - we could do a
# simple check and say if the user already has their canvas URL typed in, and
# it has a proper URL format, then we open that tab for them."
# ---------------------------------------------------------------------------

def test_a_VALID_address_opens_the_students_canvas(monkeypatch):
    import ui.auth as auth
    opened = []
    monkeypatch.setattr(auth, 'webbrowser', None, raising=False)
    import webbrowser as _wb
    monkeypatch.setattr(_wb, 'open', lambda url, new=0: opened.append(url))

    assert auth.open_canvas_tab('https://cbscanvas.instructure.com') is True
    assert opened and 'cbscanvas.instructure.com' in opened[0]


@pytest.mark.parametrize("bad", ['', '   ', 'not a url', 'javascript:alert(1)',
                                 'file:///C:/Windows'])
def test_an_UNVALIDATED_address_is_never_navigated_to(monkeypatch, bad):
    """The security property, and the reason this goes through
    `normalize_canvas_url` rather than straight to the browser: whatever is in
    that field is user input, and handing it to the OS handler unchecked turns
    a typo - or a paste - into a navigation to somewhere arbitrary."""
    import ui.auth as auth
    opened = []
    import webbrowser as _wb
    monkeypatch.setattr(_wb, 'open', lambda url, new=0: opened.append(url))

    assert auth.open_canvas_tab(bad) is False
    assert not opened, f"{bad!r} was opened in the browser"


def test_the_SCHEME_gate_refuses_even_when_normalisation_lets_it_through(
        monkeypatch):
    """The gate that `normalize_canvas_url` currently makes unreachable.

    Every value the parametrised test above feeds in comes back from
    normalisation with `https://` already on the front, so the HOST check does
    all the refusing and the scheme check is never the one that fires. A
    mutation pass measured exactly that: dropping it changed nothing and the
    mutant SURVIVED.

    That does not make the gate dead code - it makes it the guard for the day
    normalisation changes, or a second caller skips it. So drive it directly:
    hand `open_canvas_tab` a normaliser that returns something the OS handler
    would act on, and require a refusal.
    """
    import ui.auth as auth
    from core.canvas_auth import canvas_host
    opened = []
    import webbrowser as _wb
    monkeypatch.setattr(_wb, 'open', lambda url, new=0: opened.append(url))

    # EVERY VALUE HERE MUST SURVIVE THE HOST GATE, and that is asserted rather
    # than hoped. The first version of this test used `file:///C:/Windows`,
    # `javascript:alert(1)`, `ms-settings:` and a `data:` URL - and measured,
    # every one of those yields a host of '' or a bare scheme word with no dot,
    # so the HOST check refused them and the scheme check was never reached.
    # The test passed, the mutation pass reported the scheme gate SURVIVED, and
    # the test was in fact exercising the line above it. A test for gate N must
    # prove its input gets past gate N-1.
    hostile = (
        'javascript://evil.example.com/%0aalert(1)',   # //... is a comment;
                                                       # %0a ends it, so this
                                                       # really does execute
        'vbscript://a.b.c/x',
        'smb://evil.example.com/share',                # leaks NTLM creds on
                                                       # Windows
        'ftp://evil.example.com/x',
    )
    for bad in hostile:
        host = canvas_host(bad)
        assert host and '.' in host and not any(c.isspace() for c in host), (
            f"{bad!r} is stopped by the HOST check, so it cannot exercise the "
            f"scheme check at all (host={host!r})")
        monkeypatch.setattr(auth, 'normalize_canvas_url',
                            lambda _v, _h=bad: _h)
        assert auth.open_canvas_tab('anything') is False, (
            f"{bad!r} passed the scheme gate")
        assert not opened, f"{bad!r} was handed to the operating system"


def test_a_browser_that_will_not_open_does_NOT_fail_the_signin(monkeypatch):
    """The listener is already armed by then and the student can reach Canvas
    themselves, so this is a convenience that must degrade rather than throw."""
    import ui.auth as auth
    import webbrowser as _wb

    def _boom(*_a, **_k):
        raise OSError('no browser configured')

    monkeypatch.setattr(_wb, 'open', _boom)
    assert auth.open_canvas_tab('https://x.instructure.com') is False


def test_the_tab_is_opened_only_AFTER_the_listener_is_armed():
    """The extension asks whether the app is waiting the moment it is clicked.
    Opening the tab first leaves a window in which the honest answer is 'not
    waiting', which is exactly the state the student was told to avoid."""
    import inspect
    import ui.auth as auth
    src = inspect.getsource(auth.begin_browser_handoff)
    assert src.index('handoff.start()') < src.index('open_canvas_tab'), (
        "the Canvas tab is opened before the listener is armed")


def test_the_notice_says_what_ACTUALLY_happened(notice):
    """Having opened their Canvas for them, telling them to go and open it is
    both wrong and confusing.

    DRIVEN, not grepped. This was a source test anchored on one sentence, and
    it failed the moment the copy was improved while the behaviour it names was
    perfectly intact - the brittle-anchor trap this repo documents. Rendering
    both branches tests the thing the test is named after.
    """
    opened = notice('handoff', handoff_opened_tab=True)
    not_opened = notice('handoff', handoff_opened_tab=False)
    assert opened != not_opened, (
        "the waiting notice reads the same whether or not it opened their "
        "Canvas, so one of the two is wrong")
    assert 'another tab' in opened, (
        f"having opened their Canvas, the notice does not say so: {opened}")
    assert 'Open your Canvas' in not_opened, (
        f"no tab was opened and the notice does not ask for one: {not_opened}")
    assert 'Open your Canvas' not in opened, (
        "it tells the student to go and open the page it just opened for them")


def test_cancelling_forgets_that_a_tab_was_opened():
    """Left behind, the NEXT handoff would claim a tab had been opened when
    none had - the stale-flag shape this repo keeps paying for."""
    import inspect
    import ui.auth as auth
    src = inspect.getsource(auth.cancel_browser_handoff)
    assert "pop('handoff_opened_tab'" in src


def test_NO_step_is_actionable_while_the_app_is_off():
    """Reported 2026-09-13: with Canvas Downloader closed the popup still lit
    step 1, "which would amount to nothing or have no purpose if canvas
    downloader isn't running".

    `current === 0` marks nothing as current. The three steps stay visible, so
    the student can still read what the flow is; none of them is presented as
    the thing to go and do.
    """
    js = (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')
    assert 'step: 0' in js, (
        "no state uses step 0, so some step is always highlighted even with "
        "the app closed")
    # The not-open state specifically.
    idx = js.index('Canvas Downloader is not open')
    window = js[max(0, idx - 200):idx]
    assert 'step: 0' in window, (
        "the app-is-not-open state still highlights a step")


def test_SUCCESS_marks_every_step_done():
    """Reported 2026-09-13: after signing in, step 3 was still blue rather than
    ticked. A guide that never completes reads as a flow that did not."""
    js = (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')
    # The two success paths - clicking the button, and reopening after Chrome's
    # approval prompt destroyed the popup mid-sign-in - used to render the
    # finished screen SEPARATELY, so this once counted the copies. They now
    # share `showDone()`, which is the repo's own rule: a primitive with two
    # implementations is a fix that lands on half the app. So count the CALLS.
    assert js.count('showDone()') >= 2, (
        "only one of the two success paths shows the finished screen; the "
        "other leaves the student on a guide that never completed")
    idx = js.index('async function showDone')
    assert 'step: 4' in js[idx:idx + 900], (
        "the finished screen does not mark the guide complete")
    assert 'current > 3' in js, (
        "setSteps has no way to express 'all done', so step 3 stays current "
        "even after the sign-in finished")


def test_the_student_can_ASK_AGAIN_without_reopening_the_popup():
    """The app can start after the popup opened. Reported: "when it opened the
    extension didnt have enough time to find it... there should be a refresh
    icon button to the far right"."""
    html = (_ROOT / 'extension' / 'popup.html').read_text(encoding='utf-8')
    js = (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')
    assert 'id="recheck"' in html
    assert 'margin-left: auto' in html, (
        "the re-check control is not pushed to the far right of the row")
    assert 'els.recheck.addEventListener' in js, (
        "the re-check control is decoration; nothing re-runs the check")


def test_the_state_dot_carries_NO_glyph():
    """It is a 9px circle. A tick inside it landed on top of the dot rather
    than beside it - "the bar there has a checkmark and the dot on top of each
    other? keep just the green dot"."""
    js = (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')
    idx = js.index('function showAppState')
    body = js[idx:idx + 900]
    assert 'appDot' not in body, (
        "showAppState writes into the indicator dot again")

# ---------------------------------------------------------------------------
# 8. The screen for when there is nothing to do
#
# THE CONSTRAINT THIS SECTION EXISTS FOR, and it is a real one: the extension
# CANNOT ASK whether the app is signed in. `core/handoff.py` sets `open = False`
# the moment a sign-in is accepted and `ui/auth.py` then calls `handoff.stop()`,
# which closes the socket - so within seconds of SUCCEEDING, `/ping` answers
# nothing and the only honest reading of that silence is "not running". That is
# what a student was shown immediately after the thing worked.
#
# The answer is not to keep a socket open. It is that the extension never
# needed to ask: it performed the sign-in, so it already knows. Product owner,
# 2026-09-13: "if we cant properly tell if the app is actually running after
# the sign-in, then the extension should be designed around that... a success
# message that the app has been signed in and then mb a countdown from 5 or
# something to make the transition to the step 0 state smooth".
# ---------------------------------------------------------------------------

def _popup_js() -> str:
    return (_ROOT / 'extension' / 'popup.js').read_text(encoding='utf-8')


def _popup_html() -> str:
    return (_ROOT / 'extension' / 'popup.html').read_text(encoding='utf-8')


def test_a_SUCCESSFUL_signin_is_REMEMBERED_because_it_cannot_be_asked_about():
    """The worker has to write the fact down, because nothing else can answer
    it later. Without this the popup is back to reading the app's silence."""
    bg = (_ROOT / 'extension' / 'background.js').read_text(encoding='utf-8')
    assert 'signedIn' in bg, (
        "the worker never records that a sign-in succeeded, so the popup has "
        "no way to know and falls back to pinging an app that has already "
        "stopped listening")
    idx = bg.index('async function setResult')
    assert 'rememberSignedIn' in bg[idx:idx + 400], (
        "a successful result does not write the memory")


def test_the_LISTENER_REALLY_DOES_STOP_after_a_handoff(listening):
    """The premise, measured rather than assumed.

    If this ever stops being true the whole resting screen is solving a problem
    that no longer exists, and this test is where that gets noticed."""
    assert handoff.waiting() is True

    code = _call(listening, '/canvas-session',
                 {'host': 'x.instructure.com',
                  'cookies': {'canvas_session': 'v'}}, origin=EXT)[0]
    assert code == 200

    # Still listening, but no longer asking. This is the window in which the
    # extension can still see the app at all.
    assert handoff.waiting() is False
    assert _call(listening, '/ping', origin=EXT)[1]['waiting'] is False

    # And then the app consumes it and shuts the socket, which is the state a
    # student's extension actually meets a second later.
    assert handoff.result() is not None
    handoff.stop()
    assert handoff.port() == 0


def test_the_popup_NEVER_CLOSES_ITSELF_after_a_signin():
    """It used to shut after 2.2 seconds. That threw away the only
    confirmation a student ever gets, since the app cannot send one."""
    js = _popup_js()
    assert 'window.close()' not in js, (
        "the popup still closes itself, discarding the only place the "
        "successful sign-in is ever reported")


def test_the_FINISHED_screen_counts_down_to_the_resting_one():
    """Asked for directly: a success message "and then mb a countdown from 5
    or something to make the transition to the step 0 state smooth"."""
    js = _popup_js()
    assert 'DONE_SECONDS = 5' in js, "the countdown is not five seconds"
    idx = js.index('async function showDone')
    body = js[idx:idx + 1400]
    assert 'setInterval' in body, "nothing counts"
    assert 'showRest(' in body, (
        "the countdown does not land anywhere; the finished screen just sits "
        "there")
    assert 'id="countdown"' in _popup_html(), "there is nowhere to count"


def test_the_countdown_is_a_NUMBER_not_an_animation():
    """This laptop has Windows animation effects off, which is what made the
    first spinner look broken. A counting number is content, so it survives
    `prefers-reduced-motion` - a draining bar would not."""
    html = _popup_html()
    assert 'id="countNum"' in html, "the countdown has no number to read"
    reduced = html.split('prefers-reduced-motion', 1)[-1].split('}', 2)[0]
    assert 'countdown' not in reduced and 'countNum' not in reduced, (
        "the countdown is hidden under reduced motion, so the student who "
        "most needs a non-animated signal gets none")


def test_the_RESTING_screen_shows_no_guide_and_no_button():
    """"a clean (no steps/walkthrough) ... with the logo and a green dot"."""
    js, html = _popup_js(), _popup_html()
    assert 'function showRest' in js
    assert 'id="rest"' in html and 'id="restTitle"' in html
    assert "classList.add(\"resting\")" in js, (
        "nothing switches the popup into the resting screen")
    # The finished screen must not present a control that does nothing.
    idx = js.index('async function showDone')
    assert 'button: null' in js[idx:idx + 900], (
        "the finished screen still renders a button, which on a screen with "
        "nothing to press is the heaviest thing on it")


def test_EVERY_part_of_the_guide_is_hidden_on_the_resting_screen():
    """A census, not a spot check.

    This repo's most expensive recurring defect is a rule that lands on some
    sites and not others. The resting screen is exactly that shape: one more
    element added to the guide leaks onto it unless somebody remembers. So the
    test enumerates what the guide IS - the top-level children of the body -
    and fails on any that `body.resting` does not account for.
    """
    import re
    html = _popup_html()
    body = html.split('<body>', 1)[1].split('</body>', 1)[0]

    # Top-level blocks of the popup, by id or class, in source order.
    blocks = re.findall(r'^  <(?:div|p|button)\s+([^>]*)>', body, re.M)
    named = []
    for attrs in blocks:
        m = re.search(r'id="([^"]+)"', attrs)
        c = re.search(r'class="([^" ]+)', attrs)
        named.append((m.group(1) if m else None, c.group(1) if c else None))
    assert len(named) >= 5, (
        f"the block scanner found only {named}; it has stopped matching the "
        "document and would pass no matter what leaked")

    hides = html.split('body.resting', 1)[-1].split('body:not(.resting)', 1)[0]
    rest_owned = {'rest'}                      # the resting screen itself
    brand = {'brand'}                          # the logo stays, deliberately
    missing = []
    for ident, cls in named:
        if (ident in rest_owned) or (cls in rest_owned) or (cls in brand):
            continue
        if not (('#' + (ident or '~')) in hides or ('.' + (cls or '~')) in hides):
            missing.append(ident or cls)
    assert not missing, (
        "these parts of the guide are still on screen when there is nothing "
        f"to do: {missing}. Add them to the `body.resting` rule in popup.html.")


def test_a_LIVE_request_for_a_signin_BEATS_the_remembered_one():
    """The memory must never stand between a student and the screen they need.

    If the app is asking for a sign-in right now - it was reopened, the session
    expired, they logged out - that is live and actionable, and a remembered
    sign-in from earlier in this browsing is not."""
    import re
    js = _popup_js()
    idx = js.index('async function read')
    # COMMENTS STRIPPED FIRST. The window below sits directly under a comment
    # explaining this very rule, so an unstripped search passes on the prose
    # that describes the guard rather than on the guard. That trap has cost
    # this repo four separate findings.
    body = re.sub(r'//[^\n]*', '', js[idx:idx + 1800])
    assert 'signedIn' in body, (
        "read() does not consult the remembered sign-in at all")
    assert 'if (!(app && app.waiting)) {' in body, (
        "the remembered sign-in is consulted WITHOUT first checking whether "
        "the app is asking for one now, so a stale memory hides a live "
        "request and the student has no way back to the guide")
    guard = body[:body.index('signedIn')]
    assert 'waiting' in guard, (
        "the waiting check does not come BEFORE the remembered sign-in")


def test_the_student_can_always_get_BACK_to_the_guide():
    """"there should be a little link text allowing the user to go to the step
    tracker screen thing that shows the steps"."""
    js, html = _popup_js(), _popup_html()
    assert 'id="again"' in html, "there is no way off the resting screen"
    assert 'els.again.addEventListener' in js, (
        "the way back is decoration; nothing listens to it")
    idx = js.index('els.again.addEventListener')
    body = js[idx:idx + 500]
    assert 'remove("signedIn")' in body, (
        "going back to the guide does not forget the remembered sign-in, so "
        "the resting screen returns the moment the popup is reopened and the "
        "student is stuck in it")



# ---------------------------------------------------------------------------
# 9. Surviving a module re-import
#
# THE DEFECT, reproduced 2026-09-13 from the product owner's own terminal plus
# netstat: one `python dev.py` held 53127, 53128 AND 53129 LISTENING at once.
#
#     01:09:38  Listening ... on 127.0.0.1:53128.
#     01:10:21  Accepted a Canvas session handoff for cbscanvas... (2 cookies).
#     01:10:28  Listening ... on 127.0.0.1:53129.
#     01:11:30  Listening ... on 127.0.0.1:53127.
#
# Streamlit's watcher does `del sys.modules[name]` for EVERY watched module on
# ANY file change - its own comment says "as a workaround we simply unload all
# watched modules". So `core.handoff` is re-imported FRESH, its `_server` is
# None, and the socket the previous incarnation opened is still listening in a
# thread nothing holds a reference to. It can never be stopped.
#
# THE SECOND CONSEQUENCE IS THE ONE THAT COST A SIGN-IN. The extension walks
# the port list and reaches the OLDEST ORPHAN first. That orphan answers
# `/ping`, reports itself armed, accepts the handoff and logs "Accepted a
# Canvas session handoff" - into state the live module cannot read. The
# extension showed success, the terminal showed success, and the app said
# "Canvas sign-in did not finish". `scripts/check_handoff.py` passed all ten
# of its checks against an orphan.
#
# SOURCE RUNS ONLY: `start.py` passes `--server.fileWatcherType=none` when
# frozen, so the shipped app has no watcher. `python dev.py` and
# `python start.py` do.
# ---------------------------------------------------------------------------

_PROBE_PORTS = [53520, 53521, 53522]


@pytest.fixture
def reimportable():
    """Drive re-imports on throwaway ports, and put `sys.modules` back.

    NOT `monkeypatch`, and that is measured rather than stylistic. A
    `monkeypatch.setattr(original, 'PORTS', ...)` restores the attribute on the
    object it was given - but this fixture deliberately replaces
    `sys.modules['core.handoff']` several times, so the module the next test
    imports need not be the one monkeypatch is holding. It leaked:
    `tests/test_dev_tooling.py` then found `PORTS == [53520, 53521, 53522]`,
    `handoff.start()` answered 53520, and the checker - probing the REAL ports -
    reported the app as not running. Two passing tests failed only when run
    after this one. Restoring by hand, on every incarnation, has no such gap.
    """
    import core.handoff as original
    saved = sys.modules.get('core.handoff')
    real_ports = list(original.PORTS)
    original.stop()
    original.PORTS = _PROBE_PORTS

    made = [original]

    def again():
        """Exactly what the watcher does: drop it and let import rebuild it."""
        sys.modules.pop('core.handoff', None)
        import core.handoff as fresh
        fresh.PORTS = _PROBE_PORTS
        made.append(fresh)
        return fresh

    try:
        yield again
    finally:
        for m in made:
            try:
                m.stop()
            except Exception:                              # noqa: BLE001
                pass
            m.PORTS = real_ports          # EVERY incarnation, not just one
        if saved is not None:
            sys.modules['core.handoff'] = saved
            saved.PORTS = real_ports
            saved.stop()
        # The shared runtime outlives all of them, so leaving a probe port in
        # its state would hand the next test a port nothing is listening on.
        _rt = sys.modules.get('canvas_downloader._handoff_runtime')
        if _rt is not None:
            _rt.state.clear()


def _live_probe_ports() -> list[int]:
    out = []
    for p in _PROBE_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', p)) == 0:
                out.append(p)
    return out


def test_a_RE_IMPORT_does_not_leak_a_listener(reimportable):
    """The measurement: before the fix, three edits left three ports
    listening and the fourth start() answered 0."""
    import core.handoff as h
    first = h.start()
    if not first:
        pytest.skip("the probe ports are in use on this machine")
    assert _live_probe_ports() == [first]

    for n in range(1, 6):
        fresh = reimportable()
        assert fresh.start() == first, (
            f"re-import {n} opened a SECOND listener instead of adopting the "
            f"one already running")
        assert _live_probe_ports() == [first], (
            f"re-import {n} leaked a listener: {_live_probe_ports()}")


def test_a_re_imported_module_ADOPTS_the_running_listener(reimportable):
    """Not merely "does not leak": it has to still know the port and still
    consider the window armed, or the card reports no connection."""
    import core.handoff as h
    first = h.start()
    if not first:
        pytest.skip("the probe ports are in use on this machine")
    fresh = reimportable()
    fresh.start()
    assert fresh.port() == first, "the re-imported module lost the port"
    assert fresh.waiting() is True, (
        "the re-imported module thinks nothing is armed, so the extension is "
        "correctly told the app is not asking for a sign-in")


def test_a_handoff_accepted_by_an_OLD_incarnation_is_still_READABLE(
        reimportable):
    """THE BUG THE PRODUCT OWNER HIT. The socket, and therefore the handler
    that serves it, belongs to the incarnation that opened it. Its `_state`
    must be the same object the live module reads, or the handoff is accepted
    and logged into a dictionary nothing will ever look at."""
    import core.handoff as h
    first = h.start()
    if not first:
        pytest.skip("the probe ports are in use on this machine")

    fresh = reimportable()
    fresh.start()

    # Served by the ORIGINAL incarnation's handler class.
    status, _b, _hdr = _call(first, '/canvas-session',
                             {'host': 'cbscanvas.instructure.com',
                              'cookies': {'canvas_session': 'V'}}, origin=EXT)
    assert status == 200

    got = fresh.result()
    assert got is not None, (
        "the handoff was accepted and logged, and the live module cannot see "
        "it - which is exactly 'Canvas sign-in did not finish' while the "
        "terminal says Accepted")
    assert got['host'] == 'cbscanvas.instructure.com'


def test_stop_from_a_NEW_incarnation_closes_the_OLD_socket(reimportable):
    """Otherwise logging out leaves a listener accepting Canvas sessions - the
    property section 3 already pins, which a re-import quietly broke."""
    import core.handoff as h
    first = h.start()
    if not first:
        pytest.skip("the probe ports are in use on this machine")
    fresh = reimportable()
    fresh.start()
    fresh.stop()
    assert _live_probe_ports() == [], (
        "stop() from the current module left a previous incarnation's socket "
        "listening")


def test_the_runtime_is_held_where_a_watcher_CANNOT_reach_it():
    """A synthetic module has no `__file__`, so Streamlit's watcher never
    watches it and never deletes it. That property is the whole fix, so it is
    asserted rather than assumed."""
    import core.handoff as h
    rt = h._runtime()
    assert rt is sys.modules.get(h._RUNTIME_KEY)
    assert not hasattr(rt, '__file__'), (
        "the handoff runtime has a __file__, so a file watcher can watch it, "
        "unload it, and the leak is back")
    assert h._RUNTIME_KEY not in {'core.handoff', __name__}
    # It must be the SAME lock and state a fresh import would bind to.
    assert h._lock is rt.lock and h._state is rt.state



# ---------------------------------------------------------------------------
# 10. The card state machine
#
# Reported 2026-09-13, and it is worth stating as a sequence rather than a bug:
# the extension showed a green success screen with a countdown, and the app
# showed "Canvas sign-in did not finish" - while holding a perfectly good
# credential that it signed in with on the very next click.
#
# Three separate faults, stacked:
#
#   1. `waiting_handoff` was `handoff.waiting()`, which goes False the INSTANT
#      the handoff lands. The polling fragment is rendered only while that is
#      true, and it is the only thing that asks for the full run which collects
#      the credential. So arrival switched off the collector.
#   2. `begin_browser_handoff` cleared neither failure flag, so a previous
#      attempt's error card was drawn over an attempt that was working.
#   3. Five specific failure causes were computed and thrown away -
#      `render_browser_login_notice` used the failure only as a truthiness
#      test, so every cause rendered one generic sentence.
#
# THE TWO ROUTES ARE NOT ONE ROUTE. "Sign in with Canvas" opens the app's own
# Canvas window and needs NO extension; "Use the Canvas tab in my browser"
# requires the Chrome extension. They share one notice slot, and the copy must
# never give one route's advice for the other's failure.
# ---------------------------------------------------------------------------

@pytest.fixture
def notice(monkeypatch):
    """Render a notice state with a stubbed `st.session_state`."""
    import ui.auth as auth

    class _FakeSt:
        def __init__(self):
            self.session_state = {}

    def render(state, **session):
        fake = _FakeSt()
        fake.session_state.update(session)
        monkeypatch.setattr(auth, 'st', fake)
        return auth._browser_notice_html(state)

    return render


def _one_root(html: str) -> bool:
    """Exactly one top-level element, which the slot contract requires."""
    import re
    return len(re.findall(r"<div class='kc-notice", html)) == 1


def test_EVERY_notice_state_emits_exactly_one_element(notice):
    import ui.auth as auth
    states = ['waiting', 'handoff', 'handoff_arrived', 'checking', 'cancelled',
              'error'] + ['fail:' + k for k in auth._HANDOFF_FAILURES]
    for state in states:
        html = notice(state)
        assert _one_root(html), f"{state} does not emit exactly one element"
        assert html.rstrip().endswith('</div>'), f"{state} is not closed"


def test_ARRIVAL_keeps_the_collector_on_screen():
    """THE DEFECT. `has_payload()` is what tells "the window stopped accepting"
    from "the credential is here and nobody has picked it up"."""
    import inspect
    import ui.auth as auth
    src = inspect.getsource(auth.render_browser_login_notice)
    assert 'has_payload()' in src, (
        "the notice decides a handoff is over the moment it ARRIVES, so the "
        "polling fragment - the only thing that asks for the run which "
        "collects the credential - stops being rendered and the sign-in sits "
        "there uncollected")
    assert 'handoff.waiting() or handoff.has_payload()' in src


def test_an_ARRIVED_handoff_has_a_state_of_its_own(notice):
    """Without it the two halves of one flow contradict each other."""
    html = notice('handoff_arrived')
    assert _one_root(html)
    assert 'Got it' in html
    assert 'kc-spin' in html, "the arrived state shows no sign of progress"


def test_a_NEW_attempt_clears_BOTH_previous_failures():
    """The two routes share one slot, so leaving either flag behind draws the
    previous attempt's error over a sign-in that is in flight."""
    import inspect
    import ui.auth as auth
    src = inspect.getsource(auth.begin_browser_handoff)
    for key in ('handoff_failed', 'browser_login_failed'):
        assert f"pop('{key}'" in src, (
            f"starting a handoff does not clear {key}, so a previous "
            f"attempt's failure card outlives it")


def test_IN_FLIGHT_outranks_a_failure_in_the_shared_slot():
    import inspect
    import ui.auth as auth
    src = inspect.getsource(auth.render_browser_login_notice)
    poll = src.index('_browser_login_poll()')
    fail = src.index("_browser_notice_html('fail:")
    assert poll < fail, (
        "a failure card is chosen before an in-flight sign-in, so a stale "
        "error hides a working attempt")


def test_EVERY_failure_CAUSE_has_its_own_card(notice):
    """Five causes were computed and thrown away. A student met the same
    sentence whatever had actually happened."""
    import ui.auth as auth
    import re
    # BOTH HALVES, and that is not belt-and-braces. A mutation pass measured it
    # on 2026-09-13: a mutant that gave two causes the same HEADLINE while
    # leaving their bodies distinct SURVIVED, because this test compared only
    # bodies. The headline is the line a student actually reads first, so two
    # causes sharing one is the defect this test is named after.
    for part, label in ((r"<div class='kc-head'>.*?<span>(.*?)</span>",
                         'headline'),
                        (r"<div class='kc-body'>(.*?)</div>", 'body')):
        seen = {}
        for key in auth._HANDOFF_FAILURES:
            html = notice('fail:' + key)
            assert _one_root(html), f"{key} does not emit one element"
            found = re.search(part, html, re.S)
            assert found, f"{key} renders no {label}"
            text = found.group(1)
            assert text not in seen, (
                f"{key} has exactly the same {label} as {seen[text]}, so the "
                f"cause is still being thrown away: {text!r}")
            seen[text] = key


def test_every_failure_the_APP_can_set_HAS_a_card():
    """A census. A key with no card falls back to a generic one, silently -
    which is the defect this section exists for, wearing a new hat."""
    import ast
    import inspect
    import ui.auth as auth

    tree = ast.parse(inspect.getsource(auth.adopt_pending_handoff)
                     + '\n' + inspect.getsource(auth.begin_browser_handoff))
    keys = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for t in node.targets:
                if (isinstance(t, ast.Subscript)
                        and isinstance(t.slice, ast.Constant)
                        and t.slice.value == 'handoff_failed'):
                    keys.add(node.value.value)
    assert keys, "no failure keys found; the scanner has stopped matching"
    missing = keys - set(auth._HANDOFF_FAILURES)
    assert not missing, (
        f"these causes are set by the app and have no card, so they render "
        f"the fallback: {sorted(missing)}")


def test_the_PATH_B_card_names_the_extension_and_PATH_A_never_does(notice):
    """The routes are different and the advice must not cross over.

    Path B (the Chrome handoff) REQUIRES the extension, so "you may not have
    it" is its most useful sentence. Path A opens the app's own Canvas window
    and needs no extension at all - telling somebody to go and install one
    there sends them to fix something unrelated to what went wrong.
    """
    b = notice('fail:no_arrival')
    assert 'Canvas Downloader' in b and 'extension' in b.lower(), (
        "the extension route's main failure does not mention the extension, "
        "which is its most likely cause")

    a = notice('error')
    assert 'extension' not in a.lower(), (
        "the app's own Canvas-window failure tells the student about the "
        "browser extension, which has nothing to do with it")
    assert 'Canvas Access' in a, (
        "path A's failure does not offer the token field, its real fallback")


def test_the_WAITING_card_says_where_to_look_when_the_button_is_hidden(notice):
    """Chrome hides a new extension behind the puzzle-piece, so a student who
    has just installed it is hunting for a button that is not on screen. Every
    other sentence in that card assumes they can see it."""
    html = notice('handoff', handoff_opened_tab=True)
    assert 'puzzle' in html.lower(), (
        "the waiting card does not say where Chrome hides a new button")


def test_NO_developer_wording_reaches_the_APP_cards_either(notice):
    """The extension's copy rules were a product-owner ruling, and the app is
    the other half of the same flow. "Listening" under a spinner is the one
    that was there: on a feature that reads a browser session, a student who
    reads that it is listening has been told the wrong thing about it.
    """
    import re
    import ui.auth as auth
    banned = ('listening', 'handoff', 'localhost', 'port', 'payload',
              'endpoint', 'cookie', 'session token', 'origin')
    states = ['waiting', 'handoff', 'handoff_arrived', 'checking', 'cancelled',
              'error'] + ['fail:' + k for k in auth._HANDOFF_FAILURES]
    offenders = []
    for state in states:
        text = re.sub(r'<[^>]+>', ' ', notice(state, handoff_opened_tab=True))
        for word in banned:
            if re.search(r'\b' + re.escape(word) + r'\b', text, re.I):
                offenders.append(f"{state}: {word}")
    assert not offenders, (
        "developer wording reaches the sign-in cards: " + ", ".join(offenders))

# ---------------------------------------------------------------------------
# 11. The toolbar icon
#
# Asked for by the product owner on 2026-09-13 after a successful sign-in:
# "extension ikonet burde jo recognize at det var en canvas URL og saa vise det
# med et lille maerkat?" - and chosen by him, from three options, as the
# NARROWEST one: the icon lights only when the app is asking for a sign-in AND
# the student is on a Canvas they granted.
#
# That is his own earlier reasoning applied: an icon lit during ordinary Canvas
# use reads as "this thing is on and watching me", which is how an extension
# gets uninstalled. Blank the rest of the time is honest, because the rest of
# the time there is nothing to do.
#
# The privacy property is CHROME'S, not a promise of ours: with no `tabs`
# permission, Chrome redacts `tab.url` for every origin the extension holds no
# host permission for. The one site it can see is the one granted for the
# sign-in.
# ---------------------------------------------------------------------------

def _background_js() -> str:
    return (_ROOT / 'extension' / 'background.js').read_text(encoding='utf-8')


def test_the_icon_lights_only_on_a_GRANTED_canvas_tab():
    bg = _background_js()
    assert 'permissions.contains' in bg, (
        "the badge does not check that we were granted this origin, so it "
        "rests on Chrome's redaction alone instead of stating the rule")
    idx = bg.index('async function refreshBadge')
    body = bg[idx:idx + 400]
    assert 'onGrantedCanvasTab' in body, (
        "refreshBadge no longer asks whether this is a granted Canvas tab")
    assert 'paintBadge(false)' in body, (
        "there is no path that blanks the badge off a Canvas tab")


def test_the_icon_still_needs_the_APP_to_be_asking():
    """Being on Canvas is not the signal. "The app wants a sign-in AND you are
    on Canvas" is, because that is the only moment clicking does anything."""
    bg = _background_js()
    idx = bg.index('async function refreshBadge')
    body = bg[idx:idx + 400]
    assert 'findApp()' in body and 'app.waiting' in body, (
        "the badge lights without asking whether the app wants anything, so "
        "it is on during ordinary Canvas use")


def test_the_badge_rule_lives_in_ONE_place():
    """The popup's status reply repaints the icon too. If it painted from its
    own answer it would light on any tab, and the two paths would disagree
    about what the icon means - the divergent-primitive shape this repo keeps
    paying for."""
    bg = _background_js()
    idx = bg.index('msg.type === "status"')
    body = bg[idx:idx + 700]
    assert 'refreshBadge()' in body, (
        "the status path repaints the badge without going through the one "
        "function that knows the rule")
    assert 'paintBadge(' not in body, (
        "the status path paints the badge directly, bypassing the granted-tab "
        "rule")


def test_recognising_canvas_costs_NO_new_permission():
    """The whole design depends on this: no `tabs`, no content script. A test
    already bans those; this one pins the REASON they are still absent after
    the icon learned to react to Canvas."""
    manifest = json.loads(
        (_ROOT / 'extension' / 'manifest.json').read_text(encoding='utf-8'))
    perms = set(manifest.get('permissions') or [])
    assert 'tabs' not in perms, (
        "the icon feature added the `tabs` permission, which is exactly the "
        "browsing history the design exists to avoid")
    assert not manifest.get('host_permissions'), (
        "host permissions are held at install time again")


def test_the_header_does_not_claim_MORE_than_is_true():
    """The file used to say it "cannot see what sites you visit", full stop.
    That is no longer exactly true - it can see the ONE origin the student
    granted - and a comment that overstates a privacy property is worse than
    none, because it is what anybody auditing this reads first."""
    bg = _background_js()
    header = bg[:bg.index('const PORTS')]
    assert 'granted' in header, (
        "the header does not mention the one origin the extension can see")
