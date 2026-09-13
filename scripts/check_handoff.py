"""Prove the browser-extension handoff end to end, without Chrome.

Why this is worth its own script
--------------------------------
"The extension does not work" has four possible causes and only one of them is
in the extension: the app is not running, the listener is not armed, the
listener refuses what it is sent, or Chrome is not sending it. This script
settles the first three from the command line, so whatever is left is the
extension, in Chrome, and can be looked at there.

It speaks the same protocol the extension does, against the same ports, using
``core.handoff``'s own constants - so it cannot drift from the app by probing
somewhere the app is not listening.

Nothing here consumes the handoff by default. Every check either reads
(``/ping``, ``OPTIONS``) or is refused on purpose (a page origin, a body with no
session cookie), and a refused POST never sets the payload - so after a clean
run the listener is still armed and the real extension can be tested on the
same arming. ``--accept`` is the exception and says so.

Usage
-----
    python scripts/check_handoff.py          # non-destructive; keeps the arming
    python scripts/check_handoff.py --accept # also send a synthetic session
    python scripts/check_handoff.py --host canvas.cbs.dk --accept

Run it while the app (``python dev.py`` or the real launcher) is on the sign-in
screen. For everything past discovery, press the browser-extension card first
so the listener is armed.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.handoff import ACCEPTED_COOKIES, PORTS       # noqa: E402

#: A plausible extension origin. The real id differs per install; the listener
#: checks the SCHEME, which is the part a web page cannot forge.
EXT_ORIGIN = 'chrome-extension://abcdefghijklmnopabcdefghijklmnop'

#: What a hostile page would have. The browser sets `Origin` itself, so a page
#: cannot send the value above - this is the request the listener must refuse.
PAGE_ORIGIN = 'https://not-your-school.example'

_PASS, _FAIL, _SKIP = 'PASS', 'FAIL', 'skip'
_results: list[tuple[str, str, str]] = []


def _record(name: str, verdict: str, detail: str = '') -> bool:
    _results.append((verdict, name, detail))
    mark = {'PASS': '  ok  ', 'FAIL': ' FAIL ', 'skip': ' --   '}[verdict]
    print(f'{mark} {name}' + (f'  ({detail})' if detail else ''),
          flush=True)
    return verdict == _PASS


def _request(port: int, method: str, path: str, *, origin: str | None,
             body: bytes | None = None,
             content_length: int | None = None) -> tuple[int, dict, str]:
    """One request. Answers ``(status, json_body, error)``.

    ``content_length`` overrides the header independently of what is actually
    sent, which is how the size guard gets tested without pushing 64 KB down a
    socket: the listener rejects on the header and never reads the body.
    """
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=4)
    try:
        conn.putrequest(method, path, skip_host=False, skip_accept_encoding=True)
        if origin is not None:
            conn.putheader('Origin', origin)
        if body is not None:
            conn.putheader('Content-Type', 'application/json')
            conn.putheader('Content-Length',
                           str(content_length if content_length is not None
                               else len(body)))
        conn.endheaders()
        if body is not None:
            conn.send(body)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            parsed = json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:                                       # noqa: BLE001
            parsed = {}
        return resp.status, parsed, ''
    except Exception as e:                                      # noqa: BLE001
        return 0, {}, f'{type(e).__name__}: {e}'
    finally:
        try:
            conn.close()
        except Exception:                                       # noqa: BLE001
            pass


def _answering() -> list[tuple[int, bool]]:
    """EVERY port that answers, not just the first. ``[(port, armed), ...]``

    Probing all of them is the whole point. On 2026-09-13 this checker reported
    all ten checks passing while the app could not sign in at all, because it
    was talking to an ORPHANED listener: a module re-import had left a previous
    incarnation's socket running, and the extension - which also takes the
    first port that answers - was reaching the same orphan. It answered `/ping`,
    called itself armed and accepted a handoff, into state the live app cannot
    read. A checker that stops at the first answer cannot tell that apart from
    a healthy app, which made it worse than no checker at all.
    """
    found = []
    for port in PORTS:
        status, body, err = _request(port, 'GET', '/ping', origin=EXT_ORIGIN)
        if status == 200 and body.get('app') == 'canvas-downloader':
            found.append((port, bool(body.get('waiting'))))
    return found


def _discover() -> tuple[int, bool]:
    """The port the extension would use: the first that answers."""
    found = _answering()
    return found[0] if found else (0, False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='python scripts/check_handoff.py',
                                 description=__doc__.splitlines()[0])
    ap.add_argument('--accept', action='store_true',
                    help='also POST a synthetic session. CONSUMES the arming: '
                         'the app will try it, fail to verify it against '
                         'Canvas, and show that on screen.')
    ap.add_argument('--host', default='example.instructure.com',
                    help='the Canvas host to claim in the synthetic handoff')
    args = ap.parse_args(argv)

    print(f'\n  Probing 127.0.0.1 on {", ".join(str(p) for p in PORTS)}\n',
          flush=True)

    answering = _answering()
    if not answering:
        _record('the app is listening', _FAIL,
                'nothing answered /ping on any port')
        print('\n  Start the app first: python dev.py\n', flush=True)
        return 1
    port, armed = answering[0]
    _record('the app is listening', _PASS, f'port {port}')

    # ONE listener, or the one being talked to may not be the live one.
    if len(answering) > 1:
        ports = ', '.join(str(p) for p, _ in answering)
        _record('exactly one listener is running', _FAIL,
                f'{len(answering)} answered: {ports}')
        print('\n  More than one handoff listener is running in that app.\n'
              '  Every check below is against the FIRST one, which is the one\n'
              '  the extension reaches, and it is probably an orphan left by a\n'
              '  module re-import - so it can pass every check here while the\n'
              '  app itself never receives the sign-in.\n'
              '\n  Restart the app, then run this again.\n', flush=True)
        return 1
    _record('exactly one listener is running', _PASS, f'only {port} answers')

    # -- the security properties, which hold armed or not -------------------
    status, body, err = _request(port, 'POST', '/canvas-session',
                                 origin=PAGE_ORIGIN,
                                 body=b'{"host":"x","cookies":{}}')
    _record('a web page origin is refused', _PASS if status == 403 else _FAIL,
            err or f'HTTP {status} {body.get("error", "")}'.strip())

    status, _b, err = _request(port, 'OPTIONS', '/canvas-session',
                               origin=PAGE_ORIGIN)
    _record('a web page preflight is refused', _PASS if status == 403 else _FAIL,
            err or f'HTTP {status}')

    status, _b, err = _request(port, 'OPTIONS', '/canvas-session',
                               origin=EXT_ORIGIN)
    _record('an extension preflight is allowed', _PASS if status == 204 else _FAIL,
            err or f'HTTP {status}')

    status, _b, err = _request(port, 'GET', '/nope', origin=EXT_ORIGIN)
    _record('an unknown path is 404', _PASS if status == 404 else _FAIL,
            err or f'HTTP {status}')

    if not armed:
        _record('the listener is armed', _SKIP,
                'press the browser-extension card on the sign-in screen, '
                'then run this again')
        print('\n  The app is running and refusing the right things. The '
              'checks that need\n  an armed listener were skipped.\n', flush=True)
        return 0 if not any(v == _FAIL for v, _n, _d in _results) else 1

    _record('the listener is armed', _PASS)

    # -- body validation: accepted origin, rejected content -----------------
    status, body, err = _request(port, 'POST', '/canvas-session',
                                 origin=EXT_ORIGIN,
                                 body=b'{"host":"x.instructure.com","cookies":{}}')
    _record('a payload with no session cookie is refused',
            _PASS if status == 400 and body.get('error') == 'no session cookie'
            else _FAIL,
            err or f'HTTP {status} {body.get("error", "")}'.strip())

    status, body, err = _request(port, 'POST', '/canvas-session',
                                 origin=EXT_ORIGIN, body=b'{}',
                                 content_length=64 * 1024 + 1)
    _record('an oversized body is refused',
            _PASS if status == 400 and body.get('error') == 'bad size' else _FAIL,
            err or f'HTTP {status} {body.get("error", "")}'.strip())

    status, body, err = _request(port, 'POST', '/canvas-session',
                                 origin=EXT_ORIGIN, body=b'not json at all')
    _record('an unparseable body is refused',
            _PASS if status == 400 and body.get('error') == 'bad json' else _FAIL,
            err or f'HTTP {status} {body.get("error", "")}'.strip())

    # -- the real thing, which consumes the arming --------------------------
    if args.accept:
        payload = json.dumps({
            'host': args.host,
            # Named from the app's own list, so this cannot test a cookie the
            # app has stopped accepting.
            'cookies': {ACCEPTED_COOKIES[0]: 'synthetic-not-a-real-session'},
        }).encode('utf-8')
        status, body, err = _request(port, 'POST', '/canvas-session',
                                     origin=EXT_ORIGIN, body=payload)
        _record('a well-formed handoff is accepted',
                _PASS if status == 200 and body.get('ok') else _FAIL,
                err or f'HTTP {status} {body.get("error", "")}'.strip())
        print('\n  Look at the app now. It should try that session, fail to '
              'verify it\n  against Canvas, and say so. The listener is closed '
              'again either way.', flush=True)
    else:
        _record('a well-formed handoff is accepted', _SKIP,
                'pass --accept (consumes the arming)')

    failed = [n for v, n, _d in _results if v == _FAIL]
    print(flush=True)
    if failed:
        print(f'  {len(failed)} check(s) FAILED: ' + '; '.join(failed) + '\n', flush=True)
        return 1
    print('  The app side of the handoff is working. Anything still wrong is '
          'in\n  the extension or in Chrome.\n', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
