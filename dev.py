"""Development host: the app in YOUR browser, with the sign-in window working.

Why this file exists
--------------------
``streamlit run app.py`` cannot open the Canvas sign-in window, and it never
could. The window is a second pywebview window, and pywebview can only create
one once ``webview.start()`` has run and set ``webview.guilib`` - which happens
on the process's MAIN thread and nowhere else (``webview/__init__.py``: ``start``
raises ``WebViewException('pywebview must be run on a main thread.')``, and
``create_window`` only really builds a window when ``guilib`` is already set).
Under ``streamlit run``, Streamlit owns the main thread and no GUI loop is ever
started, so ``core.browser_login.is_available()`` correctly answers False and
the button refuses with a message instead of hanging.

So this is ``start.py``'s threading model with the app window swapped for a
small control window:

    main thread     webview.start()   <- gives us `guilib`, so the sign-in
                                         window can be created later
    daemon thread   the Streamlit server, in THIS process
    your browser    http://127.0.0.1:8501

Being in the same process is the whole point, and it is not cosmetic: the
sign-in window, the loopback listener the browser extension posts to, and the
credential store are all process-global state. A dev loop that ran Streamlit in
a separate process would have the app talking to one set of globals and the web
view to another.

WHAT IS THE REAL THING HERE, AND WHAT IS NOT
--------------------------------------------
Asked directly by the product owner on 2026-09-12: *"did you make a python file
that mimicks the auth screen of the app without being it?"* No. The answer
matters enough to write down, because a harness that quietly differs from
production makes every test run against it worthless.

**Nothing about the app is reimplemented.** The only HTML this file contains is
:func:`_control_html`, a three-row status panel. The app is the real ``app.py``,
served by the real Streamlit server, started through ``start.py``'s own
``_launch_streamlit`` - production's function, not a copy of it. Every module
under test is the shipped one, in one process: ``ui/auth.py``,
``core/browser_login.py``, ``core/handoff.py``, ``core/canvas_auth.py``,
``core/token_mint.py``.

Identical to production, by construction rather than by care:

* the sign-in window, created by the real ``begin_login`` through the real
  ``webview.create_window``;
* the web view profile - same ``private_mode=False``, same ``storage_path``, so
  the cookie store is literally the same folder;
* the loopback listener the extension posts to, on the same ports;
* the stranded-WebView2 reap that runs before the loop starts;
* ``debug=False``, so the context-menu policy that decides whether right-click
  paste works in the sign-in window is production's.

**One thing differs, and it is the rendering surface.** By default the app is
drawn by YOUR browser, and the shipped app draws it in WebView2 (WKWebView on
macOS). Both are Chromium on Windows and the app page contains no
``window.pywebview`` bridge at all - verified, there is no such call anywhere in
the app - so nothing functional changes. But layout is not a functional
question, so **``--window`` renders the app in the pywebview window instead**,
in the same engine the shipped build uses. Use it for any UI verification;
``python start.py`` is production-faithful too and always was.

**And one pre-existing difference from the INSTALLED build, which is not this
file's doing:** run from source, ``get_config_dir()`` is the repo root, so the
profile is ``<repo>/webview`` rather than ``%APPDATA%/CanvasDownloader/webview``.
``python start.py`` has always behaved the same way. Two consequences worth
knowing: signing in here does not sign you in inside the installed .exe, and
the two cannot fight over the same WebView2 profile lock.

What this gets right on purpose
-------------------------------
**The real web view profile.** Same ``private_mode=False`` and ``storage_path``
as production, so "stay signed in" and the silent renewal on the next launch
are the same mechanism here as in the shipped app. ``--isolated`` gives a
separate profile when you want to test a first-ever sign-in without throwing
away the one you use.

**debug OFF by default**, even though this is a dev tool and DevTools would be
handy. pywebview sets ``AreDefaultContextMenusEnabled`` itself from its debug
flag, and the sign-in window's right-click paste depends on that setting - so a
dev host running with debug on would report that pasting a password works
whether or not the app's own code enables it. A harness that cannot reproduce a
production failure is worse than no harness. ``--debug`` opts in and says so.

**Hot reload stays on**, because ``_start_streamlit_server`` only disables the
file watcher for a frozen build. Editing a Streamlit-level module still needs a
restart of this process - Python has already imported it - which is why this
host is cheap to stop and start.

Usage
-----
    python dev.py                 # app in your default browser, sign-in works
    python dev.py --isolated      # a throwaway web view profile
    python dev.py --debug         # DevTools in the web views (NOT production-faithful)
    python dev.py --port 8600     # somewhere other than 8501
    python dev.py --window        # render the app in the pywebview window
                                  #   (same engine as the shipped app)
    python dev.py --no-browser    # do not open a browser; print the URL

Closing the control window stops everything.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import webbrowser

#: Loggers turned up so the end-to-end story shows in the terminal as it
#: happens: the listener arming, the extension's handoff arriving, the sign-in
#: window's state changes, the token mint's verdict. These all log at INFO
#: already, so this needs no instrumentation in the app itself.
_WATCHED = (
    'core.handoff',
    'core.browser_login',
    'core.token_mint',
    'core.canvas_auth',
    'ui.auth',
)

_BANNER = """
  Canvas Downloader - development host
  ------------------------------------
  App              {url}
  Rendered in      {surface}
  Web view profile {profile}
  Sign-in window   {signin}
  Extension ports  {ports}  (armed only while the sign-in screen asks)
{debug_note}
  Watch this terminal: the listener arming, a handoff arriving and the
  sign-in window's verdict all print here as they happen.

  Closing the "development host" window stops everything.

  In another terminal, to check the extension path without Chrome:
      python scripts/check_handoff.py
"""


def _signin_state() -> tuple[bool, str]:
    """ASK the app whether a sign-in window can be opened, never assert it.

    The whole reason this host exists is that `is_available()` answers False
    under `streamlit run app.py`. Printing "available" as a fixed string would
    make this banner a claim rather than a measurement - and the one thing a
    developer needs from it is the real answer, since a False here means the
    GUI loop did not come up and every sign-in test that follows is void.
    """
    try:
        from core.browser_login import is_available
        ok, reason = is_available()
    except Exception as e:                                      # noqa: BLE001
        return False, f'could not be checked ({e})'
    return ok, 'available' if ok else f'NOT available - {reason}'


def _console_logging(verbose: bool) -> logging.Handler:
    """Put the app's own INFO lines on stderr and answer the handler.

    Returned so it can be re-applied after Streamlit boots: ``stcli.main()``
    runs Streamlit's own logging setup, which reconfigures handlers and would
    otherwise silence everything this host exists to show.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        '  %(asctime)s  %(name)s  %(message)s', datefmt='%H:%M:%S'))
    _apply_logging(handler, verbose)
    return handler


def _apply_logging(handler: logging.Handler, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    for name in _WATCHED:
        log = logging.getLogger(name)
        log.setLevel(level)
        if handler not in log.handlers:
            log.addHandler(handler)
        # Streamlit's setup adds a root handler with its own format; keeping
        # propagation off means each line appears once, in our format.
        log.propagate = False


def _profile_dir(isolated: bool) -> str:
    """The web view profile to use, created if need be.

    The production one by default, so what is measured here is what ships. A
    sibling folder under ``--isolated``, which is the honest way to test a
    first-ever sign-in: clearing the real profile would sign the developer out
    of their own institution.
    """
    from core.browser_login import webview_profile_dir
    path = webview_profile_dir()
    if isolated:
        path = path + '-dev'
    os.makedirs(path, exist_ok=True)
    if not os.access(path, os.W_OK):
        raise OSError(f'{path} is not writable')
    return path


def _control_html(state: str, url: str = '', ports: str = '',
                  signin: str = '', signin_ok: bool = False) -> str:
    """The control window's page. Deliberately not the app.

    Two clients on one Streamlit server would each get their own
    ``session_state`` while sharing this process's globals - one sign-in job,
    one loopback listener - so a click in one window could move the other's
    state. Keeping this window out of the app removes that confusion entirely.
    """
    if state == 'starting':
        body = ("<h1>Starting</h1>"
                "<p class='m'>Bringing up the Streamlit server.</p>")
    elif state == 'failed':
        body = ("<h1 class='bad'>The server did not start</h1>"
                "<p class='m'>The terminal has the reason.</p>")
    else:
        body = (
            "<h1>Development host</h1>"
            f"<p class='m'>The app is running at <b>{url}</b> in your browser.</p>"
            "<div class='row'><span class='k'>Sign-in window</span>"
            f"<span class='v {'ok' if signin_ok else 'bad'}'>{signin}</span></div>"
            f"<div class='row'><span class='k'>Extension ports</span>"
            f"<span class='v'>{ports}</span></div>"
            "<p class='m sm'>Closing this window stops the server.</p>")
    # The app's own tokens rather than neighbouring hexes. Rule 8 flagged two
    # literals here at 0.80 CIEDE2000 from `TEXT_SLATE_200` - below the
    # threshold anyone can see, which is exactly the drift that file exists to
    # stop. A dev window is still a window in this app.
    from shared import theme
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Development host</title><style>
 body {{ margin:0; padding:22px; background:{theme.BG_TERMINAL};
        color:{theme.TEXT_SLATE_200};
        font:14px/1.55 system-ui,"Segoe UI",sans-serif; }}
 h1 {{ margin:0 0 6px; font-size:16px; font-weight:600; }}
 h1.bad {{ color:{theme.ERROR_LIGHT}; }}
 .m {{ margin:0 0 14px; color:{theme.TEXT_STATUS}; font-size:13px; }}
 .m.sm {{ margin-top:16px; font-size:12px; }}
 b {{ color:{theme.TEXT_SLATE_200}; font-weight:600; }}
 .row {{ display:flex; justify-content:space-between; gap:12px;
         padding:7px 0; border-top:1px solid {theme.BORDER_DEFAULT};
         font-size:13px; }}
 .k {{ color:{theme.TEXT_STATUS}; }}
 .v {{ font-family:ui-monospace,Consolas,monospace; font-size:12px; }}
 .ok {{ color:{theme.PHASE_SECONDARY}; }}
 .bad {{ color:{theme.ERROR_LIGHT}; }}
</style></head><body>{body}</body></html>"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog='python dev.py', description=__doc__.splitlines()[0])
    ap.add_argument('--port', type=int, default=8501,
                    help='Streamlit port (default 8501; a free one is found '
                         'if it is taken)')
    ap.add_argument('--isolated', action='store_true',
                    help='use a throwaway web view profile instead of the '
                         'real one')
    ap.add_argument('--debug', action='store_true',
                    help='DevTools in the web views. Changes context-menu '
                         'behaviour, so right-click paste in the sign-in '
                         'window stops being a production-faithful test.')
    ap.add_argument('--window', action='store_true',
                    help="render the app in the pywebview window instead of "
                         "your browser - the SAME engine the shipped app uses, "
                         "for verifying layout. Implies --no-browser.")
    ap.add_argument('--no-browser', action='store_true',
                    help='do not open a browser')
    ap.add_argument('--verbose', action='store_true', help='DEBUG logging')
    args = ap.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    handler = _console_logging(args.verbose)

    import webview
    import start as launcher
    from core import handoff

    try:
        profile = _profile_dir(args.isolated)
    except Exception as e:                                      # noqa: BLE001
        print(f'  Could not prepare a web view profile: {e}', file=sys.stderr, flush=True)
        return 1

    # A wedged WebView2 from a previous run still holds this folder, and a
    # shared profile makes that fatal rather than untidy - production documents
    # ~45s and then E_ABORT. Reaped before the loop starts, same as start.py.
    try:
        from core.health_log import reap_webview_orphans
        n, pids = reap_webview_orphans(profile)
        if n:
            print(f'  Reaped {n} stranded web view process(es): {pids}', flush=True)
    except Exception as e:                                      # noqa: BLE001
        logging.getLogger(__name__).debug('Orphan sweep skipped: %s', e)

    # `--window` makes this window the APP, at production's own size, so what
    # is on screen is rendered by the same WebView2/WKWebView the shipped build
    # uses rather than by Chrome. Nothing else about the run changes.
    window = webview.create_window(
        'Canvas Downloader' if args.window
        else 'Canvas Downloader - development host',
        html=_control_html('starting'),
        width=1400 if args.window else 460,
        height=900 if args.window else 300,
    )

    stop = threading.Event()
    window.events.closed += stop.set

    def _boot() -> None:
        """Runs on a pywebview background thread once the GUI is up."""
        port = launcher._find_free_port(args.port)
        ok, url, failed = launcher._launch_streamlit(port)
        # Streamlit's own logging setup has run by now and taken the handlers
        # with it, so re-assert ours.
        _apply_logging(handler, args.verbose)

        if not ok:
            window.load_html(_control_html('failed'))
            print('  Streamlit did not come up. '
                  f'failed={failed.is_set()}', file=sys.stderr, flush=True)
            return

        ports = ', '.join(str(p) for p in handoff.PORTS)
        signin_ok, signin = _signin_state()
        if args.window:
            # The REAL app, in the real engine. `load_url`, exactly as
            # `start.py`'s `_boot` does it.
            window.load_url(url)
        else:
            window.load_html(_control_html('running', url=url, ports=ports,
                                           signin=signin, signin_ok=signin_ok))
        print(_BANNER.format(
            url=url, profile=profile, ports=ports, signin=signin,
            surface=('the pywebview window (same engine as the shipped app)'
                     if args.window else 'your browser (Chrome/Edge)'),
            debug_note=('  DEBUG ON        context menus differ from production\n'
                        if args.debug else '')))
        if not args.no_browser and not args.window:
            # After the health check, so the first paint is not a connection
            # error the developer has to reload past.
            webbrowser.open(url)

    # THE SAME SESSION RECORD PRODUCTION KEEPS, and it was missing.
    #
    # `start.py` calls `session_start()` / `session_end()`; this file called
    # neither, so `diagnostics/health.log` was never written under `python
    # dev.py` - zero bytes - and `session_state.json` carried the sampler's
    # unmeasured defaults. The whole session-lifecycle path (phase recording,
    # the failure tally, the clean-exit signal, the recorded children the next
    # launch reaps) was therefore UNEXERCISED in the tool built to exercise
    # production faithfully. Found 2026-09-13 by reading the logs of a real
    # run. The omission was never a decision: the orphan reap above already
    # says "same as start.py".
    #
    # Safe to write from here: run from source the config dir is the repo root,
    # so these records land in `<repo>/diagnostics` and cannot mix with an
    # installed app's.
    try:
        from core.health_log import session_start
        session_start()
    except Exception:                                           # noqa: BLE001
        logging.getLogger(__name__).debug('Health session not started',
                                          exc_info=True)

    exit_code = 0
    try:
        webview.start(_boot, debug=args.debug,
                      private_mode=False, storage_path=profile)
    except KeyboardInterrupt:
        pass
    except Exception as e:                                      # noqa: BLE001
        logging.getLogger(__name__).error('Development host failed: %s', e,
                                          exc_info=True)
        exit_code = 1
    finally:
        # Closed BEFORE the children are killed, exactly as `start.py` orders
        # it: the record is what the next launch reads to decide whether this
        # session died, so it has to be written while we still know.
        try:
            from core.health_log import session_end
            session_end('clean' if exit_code == 0 else 'error')
        except Exception:                                       # noqa: BLE001
            pass
        # The same reap production does. WebView2 leaves processes holding the
        # profile, and the next `python dev.py` is the thing that pays for it.
        try:
            handoff.stop()
        except Exception:                                       # noqa: BLE001
            pass
        try:
            launcher._terminate_child_processes()
        except Exception:                                       # noqa: BLE001
            pass
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
