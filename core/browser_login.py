"""Sign in to Canvas the way a browser does, inside the app's own web view.

The app already ships a full browser on both platforms - WebView2 on Windows,
WKWebView on macOS, both driven by pywebview. This module opens a second window
onto the user's Canvas instance, lets them log in through their institution's
own identity provider (SAML, Entra, Shibboleth, whatever it is, MFA included),
and then reads the session cookies out of the web view's **native** cookie
store. Those cookies become a :class:`~core.canvas_auth.CanvasCredential` that
the rest of the app uses exactly as it uses an access token.

Why the web view and not the user's real browser
------------------------------------------------
Reading cookies out of an installed browser's FILES is dead, and it is dead on
both platforms at once:

* Chrome 127 (July 2024) bound the cookie encryption key to the browser process
  with App-Bound Encryption, so a copy of the cookie database decrypts to
  nothing even with administrator rights. Edge is Chromium and inherits it.
* Chrome 136 (2025) closed the remaining door by ignoring
  ``--remote-debugging-port`` on the default profile, precisely because
  attackers were using it for cookie theft after ABE landed.
* Safari's cookie jar needs Full Disk Access, which is an alarming prompt for
  an app that fetches lecture notes.

The web view has none of those problems because the session is created *in* it.
It also gives Windows and macOS the same code path, which the browser-cookie
approach never could.

**Note the word FILES above.** Asking the browser to hand its own cookie over,
through its own extension API and on the user's click, is a different thing
entirely and is implemented in `core/handoff.py` - no database is read,
nothing is decrypted, and App-Bound Encryption is irrelevant because the
request comes from inside the browser. The blanket wording this paragraph used
to carry ("reading cookies out of an installed browser is dead") was a
conclusion about a TECHNIQUE that read as one about a GOAL, and it closed that
route conceptually for two passes.

How success is detected, and why it is not JavaScript
----------------------------------------------------
The obvious probe - navigate to ``/api/v1/users/self`` and read the JSON, or
inject a ``fetch()`` - depends on two things that differ by platform: whether
the web view renders ``application/json`` inline rather than downloading it,
and whether pywebview's injected JS bridge survives Canvas' Content Security
Policy. Neither is worth betting the login on.

So the probe is the real thing: once the window is sitting on the Canvas
origin, harvest the cookies and **make an actual API call from Python with
them**. That tests end to end exactly what the downloader will do for the rest
of the session, it needs no JavaScript, and it behaves identically on both
platforms. A credential that passes this check is known-good, not assumed-good.

Threading
---------
Every public entry point here is safe to call from a Streamlit script thread,
because none of them block on the user. The work happens on a daemon thread and
the UI polls :func:`status`, the same shape ``ui/auth.py`` already uses for the
macOS Keychain prompt - and for the same reason: a native window raised from
the script thread stops the script finishing, and the frontend then has nothing
to render (see ``.claude/rules/macos.md``). State is process-global rather than
in ``st.session_state`` because a background thread has no ``ScriptRunContext``.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

from core.canvas_auth import (
    CanvasCredential, SESSION_COOKIE_NAMES, canvas_host, cookie_domain_matches,
    from_cookies,
)

logger = logging.getLogger(__name__)

#: How long to wait, with the window HIDDEN, for an already-valid session to
#: prove itself. This covers the silent path: Canvas' own session has expired
#: but the institution's SSO session has not, so the redirect chain to the IdP
#: and back completes with no interaction. 15s is generous for a chain that is
#: normally two redirects; the cost of being generous is only paid when the
#: user is going to have to log in anyway.
SILENT_TIMEOUT = 15.0

#: How long the visible window stays open waiting for a human. Long, because
#: the user may be fetching a phone for MFA. The window has a close button and
#: closing it is reported as ``cancelled``, so this is a backstop, not a
#: deadline anyone should meet.
INTERACTIVE_TIMEOUT = 600.0

#: Gap between polls of the window's URL.
POLL_INTERVAL = 0.5

#: Timeout for the Python-side verification call.
VERIFY_TIMEOUT = 20

#: How long to wait for the profile's cookie list. Generous: it is a
#: one-off at the end of a sign-in the user has already finished, and
#: the cost of giving up early is that their sign-in is forgotten.
COOKIE_ENUMERATION_TIMEOUT = 15

#: How many consecutive polls the window's URL must be UNCHANGED before an
#: interactive attempt gives up on the silent path and shows the window.
#:
#: `SILENT_TIMEOUT` alone is a fixed clock, and the whole of it is paid by the
#: one user who cannot avoid it: the person who has to type a password.
#: Measured in the real app against real CBS SSO - the hidden window was sitting
#: on the Entra login page at **3.3s** and the window was not shown until
#: **17.0s**, i.e. 13.7 seconds of spinner over a page that was ready. The
#: constant does not scale with the machine, so a faster laptop makes that gap
#: BIGGER, not smaller.
#:
#: A settled URL is the honest signal that the redirect chain has stopped and a
#: human is needed. It cannot fire on a successful silent renewal, because the
#: loop harvests and verifies BEFORE it counts a poll as settled - a renewal
#: that works returns from inside that check. 4 polls = 2s of stillness, which
#: is long enough not to trip on a slow multi-hop SSO chain.
SETTLE_POLLS = 4


def _webview2_control(window):
    """The ``WebView2`` WinForms control behind *window*, or ``None``.

    Deliberately stops SHORT of ``.CoreWebView2``. Everything on the way there
    (``window.native``, ``.browser``, ``.webview``) is a plain Python
    attribute on pywebview's own objects and is safe from any thread;
    ``.CoreWebView2`` is a WinForms control property and is **not**. Reading
    it from the sign-in worker raises a cross-thread error, which - caught and
    turned into "not ready yet" - would make the retry answer False for ever
    and the feature silently never activate.

    Found by a probe HANGING, not by reading: an earlier version of this
    reached `.CoreWebView2` here, and the two probes that appeared to prove
    the API works had both happened to touch it inside the UI-thread hop.
    """
    try:
        browser = getattr(getattr(window, 'native', None), 'browser', None)
        return getattr(browser, 'webview', None)
    except Exception as e:                                      # noqa: BLE001
        logger.debug("The web view control is not reachable: %s", e)
        return None


def _on_ui_thread(window, work):
    """Run *work* on the UI thread and hand back what it returned.

    ``CoreWebView2`` is UI-thread-only, and the sign-in worker is a daemon
    thread - reaching it directly raises *"CoreWebView2 can only be accessed
    from the UI thread"*. This is the lesson the 2026-09-12 popup attempt paid
    for: that fix's FIRST version failed for exactly this reason and reported
    nothing useful about it.

    Returns ``(ok, value)``. ``ok`` False means the hop itself failed.
    """
    box = {}

    def _run():
        try:
            box['value'] = work()
            box['ok'] = True
        except Exception as e:                                  # noqa: BLE001
            box['error'] = repr(e)
            box['ok'] = False
        return True

    try:
        from System import Boolean, Func
        window.native.Invoke(Func[Boolean](_run))
    except Exception as e:                                      # noqa: BLE001
        logger.debug("Could not marshal to the web view's UI thread: %s", e)
        return False, None
    if not box.get('ok'):
        logger.debug("UI-thread work failed: %s", box.get('error'))
        return False, None
    return True, box.get('value')


def enable_password_manager(window) -> bool:
    """Let the sign-in window save and fill the user's institution password.

    **This is the friction that a longer session does nothing about.** A
    student's institution password lives in their browser's password manager;
    the app's web view is a separate profile that knows none of it, and
    WebView2 ships with ``IsPasswordAutosaveEnabled = False``. So without this
    the user types a full institutional password by hand on every single
    sign-in, however rarely that happens.

    Measured off the live ``CoreWebView2.Settings`` on 2026-09-12:

    ==================================  =======  =====================
    setting                             default  after this call
    ==================================  =======  =====================
    ``IsPasswordAutosaveEnabled``       False    **True**
    ``AreDefaultContextMenusEnabled``   False    **True**
    ``IsGeneralAutofillEnabled``        True     True (already on)
    ``AreBrowserAcceleratorKeysEnabled`` False   False (left alone)
    ==================================  =======  =====================

    **Ctrl+V already worked and still does** - measured by putting a string on
    the clipboard, focusing a real password input and reading the value back
    out of the DOM, with a no-keystroke control that came back empty. So paste
    was never the blocker and the context menu is for DISCOVERABILITY: a user
    who reaches for right-click, which is what a password-manager extension's
    users do, currently gets nothing at all.

    **ORDERING IS SAFE BY CONSTRUCTION, and the reason is better than the one
    first written here.** pywebview sets ``AreDefaultContextMenusEnabled``
    ITSELF, from its debug flag, inside ``on_webview_ready`` - so this looked
    like a race that a too-early write would lose silently, and that guess is
    what originally put this call behind a "the window has reported a URL"
    gate. **Measured, and the hazard does not exist**: ``CoreWebView2`` is
    ``None`` until that very event fires, and this write is marshalled onto
    the same UI thread, so it cannot interleave with the handler - it can only
    be queued behind it. Raced as hard as possible (an attempt every 20ms from
    window creation): first success at **2.25s**, then 6 seconds of sampling
    with **no revert**, both values reading True throughout. So the call needs
    no gate and simply retries until it takes.

    **The answer is READ BACK, and that is the entire design.** The popup fix
    that was built and backed out on 2026-09-12 reported ``handler_installed:
    true`` while plainly not working, because it measured that OUR
    subscription took and never that pywebview's had gone: a guard that could
    not say no. A settings property CAN be read back, so this one is only
    allowed to answer True when the live object agrees.

    Windows only. WKWebView has no equivalent for a non-browser app, so this
    answers False on macOS without touching anything.
    """
    if sys.platform != 'win32':
        return False
    control = _webview2_control(window)
    if control is None:
        return False

    def _apply():
        # `.CoreWebView2` is touched HERE, on the UI thread, and nowhere else.
        core = control.CoreWebView2
        if core is None:
            # The async initialisation has not finished. Not a failure - the
            # caller retries on its next poll.
            return None
        settings = core.Settings
        settings.IsPasswordAutosaveEnabled = True
        settings.AreDefaultContextMenusEnabled = True
        # Read back from the LIVE object, not from what we just assigned.
        return (bool(settings.IsPasswordAutosaveEnabled),
                bool(settings.AreDefaultContextMenusEnabled))

    ok, result = _on_ui_thread(window, _apply)
    if not ok or not result:
        return False
    autosave, menus = result
    if not autosave:
        # Refused, or reverted by something else. Say so rather than reporting
        # a capability the window does not have.
        logger.warning("The sign-in window could not enable password saving, "
                       "so the user will have to type their password.")
        return False
    logger.info("Sign-in window: password manager on, context menu %s.",
                "on" if menus else "off")
    return True


#: How long a kept sign-in lasts. 30 days matches what students are used to
#: from their institution's own "stay signed in" tick box, which is the thing
#: this stands in for.
KEEP_SIGNED_IN_DAYS = 30

#: Cookies never given an expiry, whatever host they belong to. Deliberately
#: NOT restricted to the Canvas host: the whole point is the IDENTITY
#: PROVIDER's session, because that is what lets the next launch renew Canvas'
#: own day-long session without asking anybody anything.
#:
#: A cookie is only ever re-dated INSIDE WebView2's own encrypted store. It is
#: never read out, never written to a file of ours, and never leaves the
#: machine - which is what makes this materially different from harvesting an
#: SSO cookie, and why it needs no new credential store.


def persist_session_cookies(window, days: int = KEEP_SIGNED_IN_DAYS) -> int:
    """Give every session cookie in the profile an expiry. Answers how many.

    **This is the app's own "stay signed in", and it works at institutions
    whose identity provider does not offer one.** Measured (2026-09-12): the
    profile keeps cookies carrying an expiry and loses ones that do not, so an
    IdP session the user did not tick "Stay signed in" at is gone on the next
    launch and they sign in again. Re-dating it in place is exactly what that
    tick box does.

    Measured end to end, two processes, with the browser process proven gone in
    between: a session cookie converted in run 1 came back in run 2 reading
    ``IsSession = False`` and was sent to the server. **The control - a second
    session cookie left untouched - did NOT come back**, which is the only
    reason the first half means anything: without it "the cookie survived"
    could just mean the profile keeps session cookies by itself.

    Three things here are measured rather than guessed, and each one cost a
    run:

    * ``GetCookiesAsync(None)`` returns the WHOLE profile, not just the
      current page's cookies - which is what makes the IdP reachable at all,
      since pywebview's ``get_cookies()`` is scoped to the current URL.
    * The Task must be STARTED on the UI thread and then polled from here.
      Waiting on it inside the hop deadlocks: it completes on that thread's
      own message loop.
    * ``CoreWebView2Cookie.Expires`` is a **System.DateTime** in the .NET
      wrapper, even though the underlying C++ API takes a double. Assigning a
      float raises ``'float' value cannot be converted to System.DateTime``,
      which is how the first attempt failed - silently, because it happened
      inside the UI-thread closure.

    Answers 0 on every failure path, and 0 is also the honest answer for a
    profile whose cookies are all dated already.
    """
    if sys.platform != 'win32':
        return 0
    control = _webview2_control(window)
    if control is None:
        return 0

    ok, task = _on_ui_thread(
        window,
        lambda: (control.CoreWebView2.CookieManager.GetCookiesAsync(None)
                 if control.CoreWebView2 is not None else None))
    if not ok or task is None:
        return 0

    deadline = time.monotonic() + COOKIE_ENUMERATION_TIMEOUT
    while time.monotonic() < deadline and not task.IsCompleted:
        time.sleep(0.1)
    if not task.IsCompleted:
        logger.warning("Timed out reading the sign-in profile's cookies, so "
                       "this sign-in will not be remembered past today.")
        return 0

    def _redate():
        from System import DateTime
        core = control.CoreWebView2
        if core is None:
            return 0
        manager = core.CookieManager
        when = DateTime.UtcNow.AddDays(days)
        converted = 0
        for cookie in task.Result:
            if not cookie.IsSession:
                continue
            cookie.Expires = when
            manager.AddOrUpdateCookie(cookie)
            converted += 1
        return converted

    ok, count = _on_ui_thread(window, _redate)
    if not ok:
        return 0
    count = int(count or 0)
    if count:
        logger.info("Kept %d session cookie(s) for %d days so the next launch "
                    "can sign in without asking.", count, days)
    return count


#: What a logout has to remove from the web view profile. Cookies alone is not
#: enough once passwords can be saved there, and these three are exactly the
#: identity-bearing kinds - deliberately NOT `AllProfile`, which also wipes
#: caches and site storage belonging to the app's own localhost window.
_LOGOUT_DATA_KINDS = ('Cookies', 'PasswordAutosave', 'GeneralAutofill')


def _clear_profile_identity_data(window) -> bool:
    """Drop cookies, saved passwords and autofill from the shared profile.

    Answers whether the call was made. ``CoreWebView2.Profile.
    ClearBrowsingDataAsync`` is the only API that reaches saved passwords;
    there is no API to enumerate them, so "the passwords are gone" cannot be
    read back the way a settings property can. The honest proxy is that
    COOKIES are readable and the same call clears them, which is what
    :func:`clear_session` checks.

    The returned ``Task`` is deliberately NOT awaited: it completes on the UI
    thread's own message loop, so waiting on it from there deadlocks.
    """
    if sys.platform != 'win32':
        return False
    control = _webview2_control(window)
    if control is None:
        return False

    def _clear():
        from Microsoft.Web.WebView2.Core import CoreWebView2BrowsingDataKinds
        core = control.CoreWebView2
        if core is None:
            return False
        kinds = None
        for name in _LOGOUT_DATA_KINDS:
            kind = getattr(CoreWebView2BrowsingDataKinds, name)
            kinds = kind if kinds is None else (kinds | kind)
        core.Profile.ClearBrowsingDataAsync(kinds)
        return True

    ok, done = _on_ui_thread(window, _clear)
    return bool(ok and done)


def webview_profile_dir() -> str:
    """Where the web view keeps its cookies and site data.

    A sibling of the settings file, so one user-visible folder holds everything
    the app remembers. Returned even if it does not exist yet - pywebview
    creates it.
    """
    from shared.helpers import get_config_dir
    return os.path.join(get_config_dir(), 'webview')


# ── Availability ─────────────────────────────────────────────────────────────

def is_available() -> tuple[bool, str]:
    """Whether an embedded web view can be opened right now.

    Returns ``(ok, reason)``. The reason is user-facing when ``ok`` is False.

    False in exactly one situation that matters: the app is being run as
    ``streamlit run app.py`` in a real browser for development, so there is no
    pywebview GUI loop to attach a window to. Saying so plainly beats a button
    that hangs.

    ``webview.guilib`` is the proxy for "a GUI loop is running", because
    ``webview.start()`` is what sets it - and ``create_window`` only really
    builds a window when it is already set. A DEVELOPER is the only person who
    can see this message: a packaged launch always runs ``webview.start()``, so
    for a real user it can only appear if that has failed outright. Hence two
    wordings. Naming the launcher is right for a user and useless to a
    developer, who needs the command that actually works.
    """
    try:
        import webview
    except Exception as e:                                      # noqa: BLE001
        logger.warning("pywebview is not importable: %s", e, exc_info=True)
        return False, "The in-app browser component is not available in this build."

    if getattr(webview, 'guilib', None) is None:
        if not getattr(sys, 'frozen', False):
            # Running from source. `python dev.py` is start.py's threading model
            # with the app window swapped for a control window, so the sign-in
            # window works there and nowhere else in a browser-based dev loop.
            return False, (
                "Signing in with Canvas needs a desktop window, which "
                "`streamlit run app.py` cannot open. Run `python dev.py` "
                "instead - same app in your browser, with the sign-in window "
                "working - or paste a Canvas Access Token."
            )
        return False, (
            "Signing in with Canvas needs the desktop app window. "
            "Start the app with the Canvas Downloader launcher rather than in a "
            "web browser, or paste a Canvas Access Token instead."
        )
    return True, ""


# ── Verification: the one place that decides a credential is good ────────────

def verify(credential: CanvasCredential, api_url: str) -> tuple[bool, str, str]:
    """Ask Canvas who the credential belongs to.

    Returns ``(ok, display_name, message)``. This is the single definition of
    "this credential works" - the login flow uses it to decide it is done, and
    startup uses it to decide a stored credential is still live, so the two can
    never disagree about what a working session is.

    Deliberately strict about what counts as success. An institution that has
    logged the user out answers a browser-shaped request with a 200 and an HTML
    login page, which ``status_code == 200`` alone would read as a win; so the
    body has to parse as JSON and carry an ``id``.
    """
    if not credential or not credential.usable:
        return False, "", "No Canvas session to check."

    base = (api_url or '').rstrip('/')
    if not base:
        return False, "", "No Canvas address to check against."
    if '://' not in base:
        base = f'https://{base}'

    try:
        import requests
        session = requests.Session()
        try:
            credential.apply_to_requests_session(session)
            resp = session.get(
                f'{base}/api/v1/users/self',
                headers=credential.auth_headers(),
                timeout=VERIFY_TIMEOUT,
            )
        finally:
            session.close()
    except Exception as e:                                      # noqa: BLE001
        logger.warning("Canvas session check could not reach %s: %s",
                       base, e, exc_info=True)
        return False, "", "Could not reach Canvas. Check your internet connection."

    if resp.status_code in (401, 403):
        return False, "", "Your Canvas session has expired."
    if resp.status_code >= 400:
        return False, "", f"Canvas answered {resp.status_code}."

    try:
        data = resp.json()
    except ValueError:
        # 200 with a non-JSON body is the signed-out case: an SSO portal
        # answering with its login page.
        return False, "", "Your Canvas session has expired."

    if not isinstance(data, dict) or not data.get('id'):
        return False, "", "Your Canvas session has expired."

    return True, str(data.get('name') or ''), ""


# ── The job ──────────────────────────────────────────────────────────────────

class _Job:
    """One login attempt. Owned by the module lock, mutated by its worker."""

    __slots__ = ('api_url', 'resolved_url', 'state', 'credential', 'user_name',
                 'message', 'interactive', 'cancel_requested', 'window',
                 'keep_signed_in')

    def __init__(self, api_url: str, interactive: bool,
                 keep_signed_in: bool = True):
        self.api_url = api_url
        #: Whether to date the profile's session cookies on success, so the
        #: next launch can renew without asking. Decided by the UI layer and
        #: passed in rather than read here, so the settings file keeps exactly
        #: one reader. Defaults True so the two error-state jobs above need no
        #: change - neither ever runs a worker.
        self.keep_signed_in = keep_signed_in
        # The base URL the window actually LANDED on, which is not always the
        # one the user typed: a vanity address (canvas.cbs.dk) redirects to the
        # canonical host (cbscanvas.instructure.com), and the session cookies
        # belong to the canonical one. Scoping them to the typed host would
        # send nothing at all.
        self.resolved_url = api_url
        self.state = 'running'
        self.credential: CanvasCredential | None = None
        self.user_name = ''
        self.message = ''
        self.interactive = interactive
        self.cancel_requested = False
        self.window = None


_job: _Job | None = None
_lock = threading.Lock()


def status() -> str:
    """One of ``idle`` / ``running`` / ``needs_user`` / ``ok`` / ``cancelled`` / ``error``.

    ``running`` means the window is hidden and a silent renewal is being
    attempted; ``needs_user`` means it is on screen and waiting for a human.
    """
    with _lock:
        return _job.state if _job else 'idle'


def result() -> CanvasCredential | None:
    """The credential from a finished login, or ``None``.

    Does NOT consume it. The same lesson as ``unlocked_token()`` in
    ``ui/auth.py``: the state here is process-global while the "am I waiting
    for a login?" flag is per Streamlit session, so a second session (a reload,
    or a second window) that consumed it would leave the first with nothing and
    no explanation.
    """
    with _lock:
        return _job.credential if _job and _job.state == 'ok' else None


def user_name() -> str:
    with _lock:
        return _job.user_name if _job and _job.state == 'ok' else ''


def resolved_url() -> str:
    """The Canvas base URL the finished sign-in actually landed on.

    A vanity address redirects to the canonical Instructure host, and that is
    the host the credential belongs to - so the caller should adopt THIS as the
    Canvas URL, not what the user typed.
    """
    with _lock:
        return _job.resolved_url if _job and _job.state == 'ok' else ''


def was_interactive() -> bool:
    """Whether the attempt in hand is one the USER started.

    A hidden renewal that fails is not news: nobody asked for it, and the login
    screen it falls back to is already the right answer. Reporting it as
    "Canvas sign-in did not finish" puts a failure in front of someone who has
    done nothing but open the app.
    """
    with _lock:
        return bool(_job.interactive) if _job else False


def message() -> str:
    """Why a login is not finished. Empty unless the state explains itself."""
    with _lock:
        return _job.message if _job else ''


def reset() -> None:
    """Forget the current job. Used by logout, by force_reauth, and by retry."""
    global _job
    with _lock:
        job, _job = _job, None
    if job is not None:
        job.cancel_requested = True
        _destroy(job)


def clear_session() -> bool:
    """Sign the embedded web view out: drop every cookie in its profile.

    This is the half of "log out" that a credential store cannot do. The web
    view keeps its own persistent profile so that a returning user is signed in
    silently; leaving it intact at logout would mean the next launch signs
    straight back in - as the PREVIOUS user, on a shared machine.

    Profile-wide rather than per-site on purpose: the Canvas session is only
    half of it, and the institution's identity-provider session is what would
    actually let a silent sign-in succeed. Both live in this profile, neither
    is ours to keep once the user has said to log out.

    Returns True if the cookies were cleared. Never raises: a logout must
    complete whatever the web view does.
    """
    try:
        import webview
    except Exception as e:                                      # noqa: BLE001
        logger.warning("Could not reach the web view to sign it out: %s", e,
                       exc_info=True)
        return False

    windows = list(getattr(webview, 'windows', None) or ())
    if not windows:
        # No GUI (development in a browser), so there is no profile holding a
        # session either. Nothing to do, and not a failure.
        return False
    # SAVED PASSWORDS TOO, and this is a requirement created by
    # `enable_password_manager`: the profile can now hold the user's
    # institution password, and `clear_cookies()` does not reach it. Without
    # this, the docstring's own reasoning about a shared machine stops being
    # true - the next user finds the previous one's password filled in for
    # them. Attempted FIRST, because it covers the cookies as well.
    cleared_everything = False
    try:
        cleared_everything = _clear_profile_identity_data(windows[0])
    except Exception as e:                                      # noqa: BLE001
        logger.warning("Could not clear saved passwords on logout: %s", e,
                       exc_info=True)

    try:
        # ALSO, not instead. `ClearBrowsingDataAsync` is not awaited (it
        # completes on the UI thread's own loop, so waiting from there
        # deadlocks), and this call is synchronous - so it is what makes
        # "the cookies are gone" true by the time this returns, on the one
        # store a caller can actually verify.
        windows[0].clear_cookies()
    except Exception as e:                                      # noqa: BLE001
        logger.warning("Could not clear the web view's cookies on logout: %s",
                       e, exc_info=True)
        return cleared_everything
    if not cleared_everything:
        # Cookies went, saved passwords may not have. Worth a line: on this
        # machine a logout is then weaker than it looks, and nothing else
        # would ever say so.
        logger.warning("Signed the web view out, but saved passwords could "
                       "not be cleared from its profile.")
    return True


def bring_to_front(api_url: str) -> bool:
    """Re-show the sign-in window for *api_url* if one is already waiting.

    Answers True when there was one. The sign-in window is not modal and has no
    owner, so it can end up BEHIND the main window - and the obvious thing to do
    then is press "Sign in with Canvas" again. Without this that click threw the
    open window away and started a fresh hidden attempt: measured in the real
    app, the window vanished at 2.5s and came back at 17.6s with the CBS login
    reloaded and everything typed into it lost.

    Only a window the user is already looking at (``needs_user``) is re-shown. A
    hidden attempt still in its silent phase is left alone, because showing that
    one would put a login window in front of someone who has not been told the
    silent path failed yet.
    """
    with _lock:
        job = _job
        window = job.window if job else None
        live = bool(job and job.state == 'needs_user' and job.api_url == (api_url or '').strip())
    if not (live and window is not None):
        return False
    try:
        window.show()
        return True
    except Exception as e:                                      # noqa: BLE001
        # The window is gone or unresponsive; the caller falls through to
        # starting a fresh attempt, which is the outcome it wanted anyway.
        logger.warning("Could not re-show the Canvas sign-in window: %s", e,
                       exc_info=True)
        return False


def cancel() -> None:
    """Ask a running login to stop and close its window."""
    with _lock:
        job = _job
    if job is not None:
        job.cancel_requested = True


def _destroy(job: _Job) -> None:
    """Close the login window, if it is still open. Never raises."""
    window, job.window = job.window, None
    if window is None:
        return
    try:
        window.destroy()
    except Exception as e:                                      # noqa: BLE001
        # A window we cannot close is a cosmetic problem; losing the credential
        # we just harvested because closing threw would not be.
        logger.warning("Could not close the Canvas login window: %s", e,
                       exc_info=True)


def begin_login(api_url: str, *, interactive: bool = True,
                keep_signed_in: bool = True) -> None:
    """Start a login for *api_url* on a daemon thread. Idempotent.

    Returns immediately. Nothing waits on the result: the login page below the
    notice keeps working, so a user who never finishes the window is not stuck.

    With ``interactive=False`` the window is never shown; the attempt either
    renews silently or reports ``error``. That is the startup path, where
    putting a login window in front of someone who did not ask for one would be
    worse than simply showing the login screen.
    """
    global _job

    url = (api_url or '').strip()
    if not url:
        with _lock:
            _job = _Job('', interactive)
            _job.state = 'error'
            _job.message = "Enter your Canvas address first."
        return

    ok, reason = is_available()
    if not ok:
        with _lock:
            _job = _Job(url, interactive)
            _job.state = 'error'
            _job.message = reason
        return

    with _lock:
        if _job is not None and _job.state in ('running', 'needs_user') \
                and _job.api_url == url:
            return                                   # already in flight
        superseded, _job = _job, _Job(url, interactive, keep_signed_in)
        job = _job

    # A job this one replaces must be told to stop, and its window closed NOW.
    # Without this the old worker keeps polling a window the user can still
    # see: `_finish` declines to record a state for a superseded job, so it
    # never reaches the branch that closes one, and an already-visible window
    # sits there until its own ten-minute clock runs out - two sign-in windows,
    # one of them for an address the user has moved on from. `reset()` in
    # `ui/auth.begin_browser_signin` covers the app's own route; this closes it
    # for every caller, which is what stops the next one rediscovering it.
    if superseded is not None and superseded.state in ('running', 'needs_user'):
        superseded.cancel_requested = True
        _destroy(superseded)

    threading.Thread(target=_worker, args=(job,), daemon=True,
                     name="canvas-browser-login").start()


def _finish(job: _Job, state: str, *, credential=None, name='', message='') -> None:
    """Record a terminal state, but only if *job* is still the current one."""
    with _lock:
        if _job is not job:
            return                                   # superseded by a newer attempt
        job.state = state
        job.credential = credential
        job.user_name = name
        job.message = message


def _harvest(window, api_url: str) -> CanvasCredential | None:
    """Read the web view's cookies for the Canvas host into a credential.

    Returns ``None`` when the window holds nothing that looks like a Canvas
    session yet, which is the normal answer while the user is still on their
    identity provider.
    """
    host = canvas_host(api_url)
    try:
        raw = window.get_cookies() or []
    except Exception as e:                                      # noqa: BLE001
        logger.debug("Cookies not readable yet: %s", e)
        return None

    # pywebview hands back a list of http.cookies.SimpleCookie, one morsel
    # each, on BOTH platforms - WebView2's CookieManager and WKWebView's
    # WKHTTPCookieStore are normalised to the same shape by the backends. Both
    # include HttpOnly cookies, which is the whole reason this works:
    # canvas_session is HttpOnly, so document.cookie could never have seen it.
    #
    # EVERYTHING the Canvas host set is kept, because the live session is
    # exactly what a browser would send. That is a reversal, and the reason the
    # earlier version kept only `canvas_session` is worth stating so it is not
    # reinstated here: a real CBS credential serialised to 3,260 bytes against
    # Windows Credential Manager's 2,560-byte ceiling. That is a fact about the
    # KEYRING, and it is now enforced in `CanvasCredential.to_storable`, where
    # it belongs. Enforcing it at the harvest also threw the extras away for the
    # live session, and one of them can be load-bearing: an institution behind a
    # WAF issues a clearance cookie (Cloudflare's `cf_clearance`, 426 chars on
    # the measured session) and without it the first API call meets a challenge
    # page - a 200 that is not JSON, which `verify` reports as "your Canvas
    # session has expired" with nothing the user can do about it. Keeping them
    # in memory costs nothing and needs no per-WAF allowlist to maintain.
    #
    # The DOMAIN check is what makes widening safe, and it is not belt and
    # braces. pywebview's macOS backend filters the cookie store with
    # `if domain not in self.url` - a plain substring test against the URL the
    # window was loaded with - so on a window opened at
    # `https://cbscanvas.instructure.com/login`, a cookie belonging to the
    # unrelated tenant `canvas.instructure.com` passes, because that string does
    # occur inside it. Everything harvested here goes into a jar scoped to the
    # Canvas host, i.e. it becomes something this app SENDS to Canvas, so a
    # foreign cookie must not reach it. The Windows backend scopes to the
    # current URL and is already correct; this makes the two agree.
    cookies: dict = {}
    for entry in raw:
        try:
            for name, morsel in entry.items():
                domain = (morsel.get('domain') or '').strip()
                # A morsel with no domain came from the host being asked, which
                # is the Canvas host - both backends scope their query to it.
                if domain and not cookie_domain_matches(host, domain):
                    logger.debug("Ignoring cookie %r: domain %r is not %s",
                                 name, domain, host)
                    continue
                cookies[name] = morsel.value
        except Exception as e:                                  # noqa: BLE001
            logger.debug("Skipping an unreadable cookie: %s", e)

    if not any(cookies.get(name) for name in SESSION_COOKIE_NAMES):
        return None

    user_agent = ''
    try:
        user_agent = window.evaluate_js('navigator.userAgent') or ''
    except Exception as e:                                      # noqa: BLE001
        # Not fatal. The User-Agent only keeps the session looking like the
        # client that created it; requests' default is still a working client.
        logger.debug("Could not read the web view User-Agent: %s", e)

    return from_cookies(cookies, api_url, user_agent=str(user_agent or ''))


WINDOW_TITLE = 'Sign in to Canvas'


def _display_host(url: str) -> str:
    """The host of *url* as it should be SHOWN to a person, or ``''``.

    Punycoded, deliberately. ``urlparse().hostname`` hands back whatever the
    URL contained, so an internationalised host arrives as the Unicode form -
    and the Unicode form is the one that can be built out of homoglyphs to read
    as somebody else's domain. Showing ``xn--...`` is ugly exactly where ugly
    is the correct answer. A host that will not encode is shown as it came,
    which is still better than showing nothing.
    """
    host = canvas_host(url)
    if not host:
        return ''
    try:
        return host.encode('idna').decode('ascii')
    except Exception:                                           # noqa: BLE001
        # Empty labels, an over-long label, or an underscore in a self-hosted
        # name. None of those are worth losing the whole indicator over.
        return host


def _title_for(url: str) -> str:
    """The window title for a sign-in sitting on *url*.

    **The address bar is the one thing an embedded web view takes away from the
    user**, and this is what gives it back. A student signing in here types
    their university password into a window with no URL anywhere on it, so
    "am I really on my own institution's login page?" is a question they
    currently cannot answer - which is the standing objection to embedded-webview
    SSO, and the reason Google blocks it outright. The chain is real and it
    leaves Canvas: CBS goes to `login.microsoftonline.com` and back. Naming the
    host in the title bar makes the window self-describing at the moment it
    matters, and costs one string per poll.

    Falls back to the bare title when the URL is unreadable, so a window whose
    URL cannot be polled is never left advertising the host it was on before.
    """
    host = _display_host(url)
    return f"{WINDOW_TITLE} - {host}" if host else WINDOW_TITLE


def _set_title(window, title: str) -> None:
    """Retitle the login window. Never raises, never blocks.

    pywebview's ``title`` setter begins with ``events.loaded.wait(15)``, and
    this runs inside the 0.5s poll loop - so on a window whose first page has
    not loaded yet it would stall the whole login for fifteen seconds, taking
    the harvest, the settle counter and the cancel check down with it. The
    ``loaded`` flag is only cleared by ``load_url``/``load_html``, never by the
    redirect chain itself, so once the first page is in it stays set and the
    setter returns at once. Checking it first is what keeps that true.
    """
    try:
        if not window.events.loaded.is_set():
            return
        window.title = title
    except Exception as e:                                      # noqa: BLE001
        logger.debug("Could not retitle the sign-in window: %s", e)


def _worker(job: _Job) -> None:
    """Drive one login attempt from start to finish."""
    import webview

    # Resolve a vanity address to the canonical Canvas host BEFORE opening the
    # window, and do it through the engine's own resolver rather than a second
    # copy of that rule. This is load-bearing twice over: canvas.cbs.dk
    # redirects to cbscanvas.instructure.com, so the session cookies belong to
    # the canonical host - scoping them to the typed one would send nothing -
    # and the "are we on Canvas yet?" test below compares hosts, so against the
    # typed host it would never match and the sign-in could never finish.
    # CanvasManager memoises the lookup process-wide, so the real client built
    # after this login pays nothing for it.
    try:
        from core.canvas_logic import CanvasManager
        base = CanvasManager('', job.api_url).api_url
    except Exception as e:                                      # noqa: BLE001
        logger.warning("Could not resolve %r to a Canvas host: %s",
                       job.api_url, e, exc_info=True)
        base = job.api_url if '://' in job.api_url else f'https://{job.api_url}'
    base = (base or '').rstrip('/')

    host = canvas_host(base)
    if not host:
        _finish(job, 'error', message="That does not look like a Canvas address.")
        return

    job.resolved_url = base

    closed = threading.Event()

    try:
        window = webview.create_window(
            _title_for(base),
            url=f'{base}/login',
            width=960, height=800,
            hidden=True,
        )
    except Exception as e:                                      # noqa: BLE001
        logger.error("Could not open the Canvas login window: %s", e, exc_info=True)
        _finish(job, 'error',
                message="The sign-in window could not be opened.")
        return

    job.window = window
    try:
        window.events.closed += closed.set
    except Exception as e:                                      # noqa: BLE001
        # Without this the user closing the window reads as a timeout rather
        # than a cancellation. Worth a warning, not worth aborting.
        logger.warning("Could not watch the login window for closing: %s", e,
                       exc_info=True)

    shown = False
    started = time.monotonic()
    # BOTH modes start hidden on the SAME short clock, because the silent phase
    # is the same attempt either way: navigate, and see whether the
    # institution's SSO session carries us back to Canvas without asking. Only
    # what happens when it EXPIRES differs - an interactive login shows the
    # window and switches to the long clock, a silent one gives up.
    #
    # Giving an interactive login INTERACTIVE_TIMEOUT here instead is the shape
    # this had when it was first written, and it is a total failure that no
    # unit test saw: the window stays hidden for the full ten minutes, so the
    # user clicks "Sign in with Canvas" and nothing ever appears. Measured in
    # the real app - 75 seconds in `running`, no window - which is why this
    # constant is picked once, here, rather than per branch.
    deadline = started + SILENT_TIMEOUT

    #: The session cookie value the last FAILED verify was about. Canvas hands
    #: an ANONYMOUS visitor a session cookie - measured: `GET /login/canvas`,
    #: the landing page at every institution without SSO, answers
    #: `Set-Cookie: canvas_session=...; httponly` with nobody logged in - so
    #: `_harvest` succeeds on every poll while the user is still typing and
    #: `verify()` would spend an API call each time, up to ~1,200 of them across
    #: the ten-minute interactive window. Canvas ROTATES the session on login,
    #: so comparing the value costs nothing and the successful attempt still
    #: fires on the very next poll.
    last_failed_cookie = None
    settled_url, settled_polls = '', 0
    #: The title the window is currently wearing, so the retitle below fires on
    #: a change of host and not on every one of the ~1,200 polls.
    titled = _title_for(base)
    #: Whether WebView2's password manager has been switched on for this
    #: window. One shot, retried until it takes, because `CoreWebView2` is
    #: None until its async initialisation completes (measured ~2.3s). The
    #: user's institution password lives in their browser's password manager
    #: and this window is a profile that knows none of it, so without this
    #: they type it by hand on every sign-in however rare those become.
    password_manager_on = False

    def _show_now(reason: str) -> bool:
        """Put the window on screen and switch to the long clock.

        ONE implementation, because there are now two ways to get here - the
        page settling and the silent clock expiring - and a second copy is how
        one of them would stop extending the deadline (the mutation harness
        already carries that exact regression).
        """
        nonlocal shown, deadline
        shown = True
        deadline = time.monotonic() + INTERACTIVE_TIMEOUT
        with _lock:
            if _job is job:
                job.state = 'needs_user'
        try:
            window.show()
        except Exception as e:                                  # noqa: BLE001
            logger.error("Could not show the Canvas login window: %s", e,
                         exc_info=True)
            _destroy(job)
            _finish(job, 'error',
                    message="The sign-in window could not be shown.")
            return False
        logger.info("Canvas sign-in window shown after %.1fs (%s).",
                    time.monotonic() - started, reason)
        return True

    try:
        while True:
            if job.cancel_requested:
                _finish(job, 'cancelled', message="Sign-in was cancelled.")
                return
            if closed.is_set():
                # The user closed the window. In the silent phase that cannot
                # be a deliberate cancel (they never saw it), so report it the
                # same way a silent timeout is reported.
                if shown:
                    _finish(job, 'cancelled', message="Sign-in was cancelled.")
                else:
                    _finish(job, 'error',
                            message="The sign-in window closed unexpectedly.")
                return

            current = ''
            try:
                current = window.get_current_url() or ''
            except Exception as e:                              # noqa: BLE001
                logger.debug("Login window URL not readable yet: %s", e)

            # Let the user's password manager work. Attempted on every poll
            # until it takes, because `CoreWebView2` is None until its async
            # initialisation completes (measured: ~2.3s); once on, this is one
            # attribute test per poll. Deliberately NOT gated on the window
            # having reported a URL - that gate was added against a revert
            # hazard which was then measured not to exist (see
            # `enable_password_manager`), and it only delayed the setting past
            # the first page load, which at a Canvas-native institution IS the
            # password form.
            if not password_manager_on:
                password_manager_on = enable_password_manager(window)

            # Say where the window actually IS. Tracked against the title
            # LAST APPLIED rather than against the previous URL, because the
            # ordinary way the window appears is the settle rule - four polls
            # of an unchanged URL - so "has the URL changed since last poll?"
            # is false on exactly the poll after it is first shown, and the
            # indicator would never appear at all on the common path.
            if shown:
                _want = _title_for(current)
                if _want != titled:
                    titled = _want
                    _set_title(window, _want)

            # Only harvest while the window is actually sitting on the Canvas
            # origin: both backends scope get_cookies() to the current URL, so
            # asking while the user is on their identity provider returns the
            # IdP's cookies and never Canvas'.
            if current and canvas_host(current) == host:
                # Harvested and verified against the RESOLVED base, which is
                # the host the cookies actually belong to.
                credential = _harvest(window, base)
                if credential is not None:
                    _cookie = next(
                        (credential.cookies.get(n) for n in SESSION_COOKIE_NAMES
                         if credential.cookies.get(n)), None)
                    if _cookie is not None and _cookie == last_failed_cookie:
                        # The same session Canvas already refused - the user is
                        # still on the login form. Asking again cannot answer
                        # differently until Canvas issues a new one.
                        pass
                    else:
                        ok, name, why = verify(credential, base)
                        if ok:
                            # BEFORE `_destroy`, because this needs the live
                            # window - and this is the one moment the profile
                            # holds both Canvas' session and the identity
                            # provider's. The IdP's is the one that matters:
                            # it is what lets the NEXT launch renew Canvas'
                            # day-long session with no interaction at all.
                            if job.keep_signed_in:
                                try:
                                    persist_session_cookies(window)
                                except Exception as e:          # noqa: BLE001
                                    # A sign-in that works must never be
                                    # undone by failing to remember it.
                                    logger.warning(
                                        "Could not keep this sign-in past "
                                        "today: %s", e, exc_info=True)
                            _destroy(job)
                            _finish(job, 'ok', credential=credential, name=name)
                            return
                        last_failed_cookie = _cookie
                        logger.debug("Harvested a Canvas session that did not "
                                     "verify (%s); still waiting.",
                                     why or 'no reason')

            # Has the page stopped moving? Counted AFTER the harvest above, so a
            # silent renewal that works has already returned and can never be
            # interrupted by showing a window nobody asked for.
            if current and current == settled_url:
                settled_polls += 1
            else:
                settled_url, settled_polls = current, 0

            if job.interactive and not shown and settled_polls >= SETTLE_POLLS:
                if not _show_now("the page stopped moving - a human is needed"):
                    return

            now = time.monotonic()
            if now >= deadline:
                if not job.interactive:
                    _destroy(job)
                    _finish(job, 'error',
                            message="Your Canvas session could not be renewed.")
                    return
                if not shown:
                    # Silent renewal did not work: the user has to log in. The
                    # backstop for a page that never settles (a chain that keeps
                    # redirecting, or a URL we cannot read).
                    if not _show_now("the silent attempt expired"):
                        return
                else:
                    _destroy(job)
                    _finish(job, 'error',
                            message="Sign-in timed out. Please try again.")
                    return

            time.sleep(POLL_INTERVAL)
    except Exception as e:                                      # noqa: BLE001
        logger.error("Canvas browser login failed: %s", e, exc_info=True)
        _destroy(job)
        _finish(job, 'error',
                message="Something went wrong during sign-in. Please try again.")
    finally:
        # A terminal state always closes the window. _destroy is idempotent.
        with _lock:
            done = _job is not job or job.state not in ('running', 'needs_user')
        if done:
            _destroy(job)

