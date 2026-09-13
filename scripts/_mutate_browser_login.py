"""Mutation pass for signing in to Canvas with a browser session.

`tests/test_browser_login.py` guards three properties, and each one fails
SILENTLY if it regresses - which is the whole reason this pass exists:

* the session cookie must never leave the Canvas host (a leak nothing logs);
* browser mode must send no Authorization header (a 401 that reads as "your
  session expired", so the user re-signs-in for ever);
* the web view's profile must persist (the sign-in works, and is forgotten on
  every launch, with nothing failing anywhere).

Every mutant here is a plausible edit rather than a strawman. Several are the
literal "simplification" someone would reach for: `cookies={...}` instead of a
domain-scoped jar, `storage_path` without `private_mode`, forwarding `use_auth`
instead of forcing it off.

Restore is from an in-memory SNAPSHOT, never `git checkout`: this repo is
routinely worked by two sessions at once. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath,
restoring nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_browser_login.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

AUTHMOD = "core/canvas_auth.py"
LOGIN = "core/browser_login.py"
LOGIC = "core/canvas_logic.py"
UI = "ui/auth.py"
START = "start.py"
SYNCX = "sync/execution.py"
PANAUTH = "panopto/auth.py"
HEALTH = "core/health_log.py"

TESTS = ["tests/test_browser_login.py"]
TEST_TARGET = TESTS

#: (label, file, old, new)
BROWSER_LOGIN_MUTANTS = [
    # -- 1. the cookie must not leave the Canvas host ------------------------
    ("the aiohttp jar loses its domain, so every file download hands the "
     "content CDN a complete Canvas login",
     AUTHMOD,
     "            jar.update_cookies(dict(self.cookies),\n"
     "                               response_url=URL(f'https://{self.host}/'))",
     "            jar.update_cookies(dict(self.cookies))"),

    ("the requests cookies lose their domain the same way",
     AUTHMOD,
     "                session.cookies.set(name, value, domain=self.host, path='/')",
     "                session.cookies.set(name, value)"),

    # -- 2. browser mode must send no Authorization header -------------------
    ("browser mode sends an Authorization header too, which Canvas rejects "
     "BEFORE it looks at the session cookie",
     AUTHMOD,
     "        if self.kind == TOKEN and self.token:\n"
     "            headers['Authorization'] = f'Bearer {self.token}'",
     "        if True:\n"
     "            headers['Authorization'] = f'Bearer {self.token}'"),

    ("the canvasapi requester forwards use_auth instead of forcing it off, so "
     "every API call carries an empty bearer",
     LOGIC,
     "        return super().request(method, endpoint, headers, False, **kwargs)",
     "        return super().request(method, endpoint, headers, use_auth, **kwargs)"),

    ("the API client stops swapping in the cookie requester, so a browser "
     "login silently authenticates as nobody",
     LOGIC,
     "        if cred.is_browser:\n"
     "            # Swapping the whole requester",
     "        if False:\n"
     "            # Swapping the whole requester"),

    ("the sync engine goes back to formatting its own bearer, so sync works "
     "on a token and not on a browser session",
     SYNCX,
     "        async with aiohttp.ClientSession(\n"
     "            timeout=timeout, connector=_sync_connector,\n"
     "            **credential_of(cm).aiohttp_session_kwargs()\n"
     "        ) as session:",
     "        async with aiohttp.ClientSession(\n"
     "            headers={'Authorization': f'Bearer {cm.api_key}'}, timeout=timeout,\n"
     "            connector=_sync_connector\n"
     "        ) as session:"),

    # -- 3. what counts as a usable credential -------------------------------
    ("any cookie counts as a login, so a web view parked on the identity "
     "provider is stored as a Canvas session",
     AUTHMOD,
     "            return bool(self.host) and any(\n"
     "                self.cookies.get(name) for name in SESSION_COOKIE_NAMES\n"
     "            )",
     "            return bool(self.host) and bool(self.cookies)"),

    ("a credential with no host counts as usable, and its cookies then have "
     "nothing to scope them",
     AUTHMOD,
     "            return bool(self.host) and any(\n"
     "                self.cookies.get(name) for name in SESSION_COOKIE_NAMES\n"
     "            )",
     "            return any(\n"
     "                self.cookies.get(name) for name in SESSION_COOKIE_NAMES\n"
     "            )"),

    ("a damaged credential store raises instead of reading as signed out - on "
     "the startup path, where an exception is a blank window",
     AUTHMOD,
     "        if not isinstance(data, dict):\n"
     "            return cls(kind=TOKEN)",
     "        if False:\n"
     "            return cls(kind=TOKEN)"),

    ("coerce stringifies whatever it is given instead of refusing, so a "
     "garbage bearer goes to Canvas and comes back as 'token revoked'",
     AUTHMOD,
     "    raise TypeError(\n"
     "        f\"Canvas credential must be a CanvasCredential, str or None, \"\n"
     "        f\"got {type(value).__name__}\"\n"
     "    )",
     "    return from_token(str(value))"),

    ("credential_of falls back to the token when the credential is merely "
     "EMPTY, masking a logged-out state as an authentication failure",
     AUTHMOD,
     "    cred = getattr(manager, 'auth', None)\n"
     "    if isinstance(cred, CanvasCredential):\n"
     "        return cred",
     "    cred = getattr(manager, 'auth', None)\n"
     "    if isinstance(cred, CanvasCredential) and cred.usable:\n"
     "        return cred"),

    # -- 4. verification -----------------------------------------------------
    ("verify accepts any 200, so an SSO portal's own login page is read as a "
     "successful sign-in",
     LOGIN,
     "    if not isinstance(data, dict) or not data.get('id'):\n"
     "        return False, \"\", \"Your Canvas session has expired.\"",
     "    if False:\n"
     "        return False, \"\", \"Your Canvas session has expired.\""),

    ("verify stops refusing an unusable credential and spends a round trip "
     "proving what it already knew",
     LOGIN,
     "    if not credential or not credential.usable:\n"
     "        return False, \"\", \"No Canvas session to check.\"",
     "    if False:\n"
     "        return False, \"\", \"No Canvas session to check.\""),

    # -- 3b. contracts the old `str` credential satisfied silently -----------
    # Both of these SHIPPED and were found by driving the real app against
    # real Canvas, not by the suite. They are the cost of changing the type of
    # a value that thirteen call sites carry.
    ("the cookies go back into the hash, so the credential is unhashable and "
     "the course cache's (token, url) key raises 'We couldn't reach Canvas'",
     AUTHMOD,
     "    cookies: Mapping[str, str] = field(default_factory=dict, hash=False)",
     "    cookies: Mapping[str, str] = field(default_factory=dict)"),

    ("the cookies leave __eq__ as well, so a renewed session silently reuses "
     "the expired one's cached courses",
     AUTHMOD,
     "    cookies: Mapping[str, str] = field(default_factory=dict, hash=False)",
     "    cookies: Mapping[str, str] = field(default_factory=dict, hash=False,\n"
     "                                       compare=False)"),

    ("adopt_pending_browser_login gives up on the per-session flag before "
     "reading the status, stranding a login another session finished",
     UI,
     "    if st.session_state.get('is_authenticated'):\n"
     "        st.session_state['browser_login_pending'] = False\n"
     "        return False\n"
     "\n"
     "    from core import browser_login\n"
     "    status = browser_login.status()",
     "    if not st.session_state.get('browser_login_pending'):\n"
     "        return False\n"
     "    if st.session_state.get('is_authenticated'):\n"
     "        st.session_state['browser_login_pending'] = False\n"
     "        return False\n"
     "\n"
     "    from core import browser_login\n"
     "    status = browser_login.status()"),

    # -- 3c. logging out means logging out -----------------------------------
    # All three reported from the real app, by the product owner, after a
    # deliberate logout.
    # RE-ANCHORED 2026-09-12. The decision moved out of `restore_saved_session`
    # into `_restore_browser_session` when it gained a second call site (the
    # marker in the settings file is a HINT; the credential store is the fact).
    # The property is identical - the renewal may only be armed with a stored
    # credential in hand - so the mutant is the same mutant, and its anchor is
    # now the early return that makes it structurally true.
    ("a hidden renewal is armed with no stored credential, so signing out "
     "immediately starts a sign-in the user never asked for",
     UI,
     "    credential, _needs_prompt = load_browser_credential(api_url)\n"
     "    if credential is None:",
     "    credential, _needs_prompt = load_browser_credential(api_url)\n"
     "    if False:"),

    ("a failed HIDDEN renewal is announced as 'Canvas sign-in did not finish' "
     "on a login screen the user reached deliberately",
     UI,
     "        if browser_login.was_interactive():\n"
     "            st.session_state['browser_login_failed'] = (",
     "        if True:\n"
     "            st.session_state['browser_login_failed'] = ("),

    ("logout forgets the Canvas address, so the login screen it lands on no "
     "longer knows which school the user attends",
     UI,
     "                if st.session_state.get('api_url'):\n"
     "                    st.session_state['url_input'] = st.session_state['api_url']\n"
     "                    st.session_state['url_verified'] = True",
     "                pass  # address deliberately forgotten"),

    # -- 4b. the silent phase ------------------------------------------------
    # THE SHIPPED BUG, reproduced exactly. This is what the worker did when it
    # was first written, and it is a total failure of the feature: an
    # interactive login gets the ten-minute clock up front, so the window never
    # appears and clicking "Sign in with Canvas" does visibly nothing. No unit
    # test saw it; the real app did, at 75 seconds in `running` with no window.
    ("an interactive sign-in starts on the LONG clock, so the window stays "
     "hidden for ten minutes and the button appears to do nothing",
     LOGIN,
     "    deadline = started + SILENT_TIMEOUT",
     "    deadline = started + (INTERACTIVE_TIMEOUT if job.interactive\n"
     "                          else SILENT_TIMEOUT)"),

    ("showing the window does not extend the clock, so it appears and is torn "
     "down again on the next poll",
     LOGIN,
     "        shown = True\n"
     "        deadline = time.monotonic() + INTERACTIVE_TIMEOUT",
     "        shown = True"),

    ("the settle rule is gone, so an interactive sign-in waits out the whole "
     "silent clock over a login page that was ready in three seconds",
     LOGIN,
     "            if job.interactive and not shown and settled_polls >= SETTLE_POLLS:",
     "            if False and not shown and settled_polls >= SETTLE_POLLS:"),

    ("the settle rule fires for a SILENT renewal too, putting a login window in "
     "front of somebody who never asked for one",
     LOGIN,
     "            if job.interactive and not shown and settled_polls >= SETTLE_POLLS:",
     "            if not shown and settled_polls >= SETTLE_POLLS:"),

    ("the STORE takes every cookie again, so a real credential is 3,260 bytes "
     "and no longer fits the OS credential store",
     AUTHMOD,
     "        cookies = {name: value for name, value in self.cookies.items()\n"
     "                   if name in SESSION_COOKIE_NAMES}",
     "        cookies = dict(self.cookies)"),

    ("the HARVEST goes back to trimming to the session cookie, so an "
     "institution behind a WAF loses its clearance cookie and every API call "
     "meets a challenge page reported as 'your session expired'",
     LOGIN,
     "                cookies[name] = morsel.value",
     "                if name in SESSION_COOKIE_NAMES:\n"
     "                    cookies[name] = morsel.value"),

    ("the harvest stops checking the cookie's DOMAIN, so pywebview's macOS "
     "substring filter lets another tenant's canvas_session through and the "
     "app scopes it to OUR host",
     LOGIN,
     "                if domain and not cookie_domain_matches(host, domain):",
     "                if False:"),

    ("domain matching loses its dot boundary, so scanvas.instructure.com "
     "counts as a parent of cbscanvas.instructure.com",
     AUTHMOD,
     "    return host == domain or host.endswith('.' + domain)",
     "    return host == domain or host.endswith(domain)"),

    # -- 10. the window has to say where it IS -------------------------------
    ("the sign-in window stops naming the host it is on, so the user types a "
     "university password into a window with no address anywhere on it",
     LOGIN,
     "            if shown:\n"
     "                _want = _title_for(current)",
     "            if False:\n"
     "                _want = _title_for(current)"),

    ("the host indicator keeps the Unicode form, so a homoglyph domain reads "
     "as the real one",
     LOGIN,
     "        return host.encode('idna').decode('ascii')",
     "        return host"),

    ("retitling stops waiting for the page to load, so pywebview's "
     "events.loaded.wait(15) stalls the poll loop that owns the harvest, the "
     "settle counter and the cancel check",
     LOGIN,
     "        if not window.events.loaded.is_set():\n"
     "            return",
     "        if False:\n"
     "            return"),

    # -- 11. states that must not loop or leak -------------------------------
    ("an idle job leaves the pending flag set, so the poll fragment reruns the "
     "app about once a second for as long as the page is open",
     UI,
     "        st.session_state['browser_login_pending'] = False\n"
     "        return False\n"
     "\n"
     "    st.session_state['browser_login_pending'] = False\n"
     "    if status != 'ok':",
     "        return False\n"
     "\n"
     "    st.session_state['browser_login_pending'] = False\n"
     "    if status != 'ok':"),

    ("a superseded login leaves its window on screen for its own full "
     "ten-minute clock, so the user faces two sign-in windows",
     LOGIN,
     "    if superseded is not None and superseded.state in ('running', 'needs_user'):",
     "    if False:"),

    ("the verify throttle is dropped, so an unchanged anonymous session is sent "
     "to Canvas on every poll - ~1,200 API calls while the user types",
     LOGIN,
     "                    if _cookie is not None and _cookie == last_failed_cookie:",
     "                    if False:"),

    ("a second click destroys the open sign-in window again instead of "
     "bringing it to the front",
     UI,
     "    if interactive and browser_login.bring_to_front(api_url):\n"
     "        st.session_state['browser_login_pending'] = True\n"
     "        return",
     "    if False:\n"
     "        st.session_state['browser_login_pending'] = True\n"
     "        return"),

    # -- 8. Panopto: Canvas will not mint a sessionless launch for a session ---
    ("Panopto goes back to the token-only sessionless_launch endpoint, which "
     "Canvas answers 403 for every browser session",
     PANAUTH,
     "    if _canvas_cred.is_browser:\n"
     "        # Canvas will not mint a sessionless launch",
     "    if False:\n"
     "        # Canvas will not mint a sessionless launch"),

    ("the in-app launch forgets the Canvas cookies, so the LTI chain walks it "
     "anonymously and lands nowhere",
     PANAUTH,
     "            _jar = _canvas_cred.requests_cookie_jar()\n"
     "            if _jar is not None:\n"
     "                session.cookies.update(_jar)",
     "            _jar = None"),

    ("the module-item form is dropped, so every recording resolves to the "
     "course FOLDER instead of its own delivery",
     PANAUTH,
     "        item_id = (params.get(\"module_item_id\") or [\"\"])[0]\n"
     "        if item_id:",
     "        item_id = \"\"\n"
     "        if item_id:"),

    # -- 9. the persistent profile must not lock the next launch out ----------
    ("the reaper matches only the exact profile folder, so WebView2's own "
     "EBWebView subfolder never matches and nothing is ever reaped",
     HEALTH,
     "        return udd == target or udd.startswith(target + os.sep)",
     "        return udd == target"),

    ("the reaper stops asking whether the owner is alive, so a second running "
     "instance loses its window mid-session",
     HEALTH,
     "                if parent is not None and parent.is_running():\n"
     "                    continue",
     "                if False:\n"
     "                    continue"),

    ("force_reauth stops asking how the user signed in, so an expired browser "
     "session is destroyed instead of renewed",
     UI,
     "    _browser = browser_session_active()",
     "    _browser = False"),

    ("a silent renewal shows a window anyway, putting a login in front of "
     "someone who never asked for one",
     LOGIN,
     "                if not job.interactive:\n"
     "                    _destroy(job)",
     "                if False:\n"
     "                    _destroy(job)"),

    # -- 5. harvesting -------------------------------------------------------
    ("harvest returns a credential before Canvas has issued a session, so the "
     "sign-in 'succeeds' while the user is still on their identity provider",
     LOGIN,
     "    if not any(cookies.get(name) for name in SESSION_COOKIE_NAMES):\n"
     "        return None",
     "    if False:\n"
     "        return None"),

    ("a page with no JS bridge loses the whole login rather than just the "
     "User-Agent",
     LOGIN,
     "        logger.debug(\"Could not read the web view User-Agent: %s\", e)",
     "        logger.debug(\"Could not read the web view User-Agent: %s\", e)\n"
     "        return None"),

    # DOCUMENTED EQUIVALENT - kept because the reasoning is worth having, not
    # because it can be caught. Removing the early return makes `windows[0]`
    # raise IndexError on an empty list, which the try/except below catches and
    # answers False: the same return value on the same input, differing only in
    # whether a warning is logged. There is no observable behaviour to assert,
    # and adding a log-level assertion would pin an implementation detail rather
    # than the contract ("a logout must complete whatever the web view does").
    ("EQUIVALENT: clear_session loses its explicit no-GUI branch and reaches "
     "the same answer through the exception handler instead",
     LOGIN,
     "    windows = list(getattr(webview, 'windows', None) or ())\n"
     "    if not windows:",
     "    windows = list(getattr(webview, 'windows', None) or ())\n"
     "    if False:"),

    # -- 6. the wiring that makes it persist ---------------------------------
    ("storage_path without private_mode - the profile directory is set and "
     "WebView2 still runs InPrivate, so nothing is ever remembered",
     START,
     "        _webview_kwargs = {'private_mode': False, 'storage_path': _profile_dir}",
     "        _webview_kwargs = {'storage_path': _profile_dir}"),

    ("a profile that cannot be created aborts the launch instead of degrading "
     "to a session that is simply not remembered",
     START,
     "    except Exception as _profile_err:\n"
     "        logger.warning(",
     "    except Exception as _profile_err:\n"
     "        raise\n"
     "        logger.warning("),

    # -- 7. the UI -----------------------------------------------------------
    ("the token read overwrites a browser session that has already signed in, "
     "dropping the user on the login page holding a valid credential",
     UI,
     "                    if not st.session_state.get('is_authenticated'):\n"
     "                        st.session_state['api_token'] = loaded_token",
     "                    if True:\n"
     "                        st.session_state['api_token'] = loaded_token"),

    ("the sign-in control becomes a plain st.button, which inside st.form "
     "cannot rerun - so clicking it does nothing at all",
     UI,
     "                _browser_clicked = st.form_submit_button(\n"
     "                    'Sign in with Canvas',",
     "                _browser_clicked = st.button(\n"
     "                    'Sign in with Canvas',"),

    ("the token route stops recording how the user signed in, so a switch "
     "away from a browser session restores the wrong credential for ever",
     UI,
     "                    config_data['auth_method'] = TOKEN",
     "                    pass  # auth_method deliberately not recorded"),

    ("the poll fragment emits a second element, which rewinds the event "
     "container's write index and hands the next block a stranger's children",
     UI,
     "    # stranger's children - is invisible in review.\n"
     "    st.markdown(_browser_notice_html(_state), unsafe_allow_html=True)",
     "    # stranger's children - is invisible in review.\n"
     "    st.markdown(_browser_notice_html(_state), unsafe_allow_html=True)\n"
     "    st.caption('')"),

    ("the notice interpolates a server-supplied message into raw HTML",
     UI,
     "    return (\n"
     "        \"<div class='kc-notice'>\"\n"
     "        f\"<div class='kc-head'>{_BROWSER_SVG}\"\n"
     "        \"<span>Canvas sign-in did not finish</span></div>\"",
     "    return (\n"
     "        \"<div class='kc-notice'>\"\n"
     "        f\"<div class='kc-head'>{_BROWSER_SVG}\"\n"
     "        f\"<span>Canvas sign-in did not finish {{state}}</span></div>\""),
    # -- the sign-in window's password manager (2026-09-12) -----------------
    ("the password manager is never switched on, so the student types a full "
     "institutional password by hand on every single sign-in",
     LOGIN,
     "        settings.IsPasswordAutosaveEnabled = True",
     "        pass  # password saving deliberately left off"),

    ("right-click Paste stays off, so a user who reaches for the context "
     "menu - which is what a password-manager extension's users do - gets "
     "nothing",
     LOGIN,
     "        settings.AreDefaultContextMenusEnabled = True",
     "        pass  # context menu deliberately left off"),

    ("the answer is ASSUMED instead of read back off the live object, which "
     "is exactly the guard-that-cannot-say-no shape the backed-out popup fix "
     "shipped",
     LOGIN,
     "        return (bool(settings.IsPasswordAutosaveEnabled),\n"
     "                bool(settings.AreDefaultContextMenusEnabled))",
     "        return (True, True)"),

    ("a REFUSED write is reported as success, so the app believes the user "
     "has a password manager when they do not",
     LOGIN,
     "    if not autosave:",
     "    if False:"),

    ("an uninitialised web view is reported as done, so the one shot is spent "
     "before CoreWebView2 exists and the setting never lands",
     LOGIN,
     "        core = control.CoreWebView2\n"
     "        if core is None:\n"
     "            # The async initialisation has not finished. Not a failure - the\n"
     "            # caller retries on its next poll.\n"
     "            return None",
     "        core = control.CoreWebView2\n"
     "        if core is None:\n"
     "            return (True, True)"),

    ("_webview2_control reaches .CoreWebView2 itself again, a cross-thread "
     "access from the sign-in worker that makes the retry answer False for "
     "ever",
     LOGIN,
     "        browser = getattr(getattr(window, 'native', None), 'browser', None)\n"
     "        return getattr(browser, 'webview', None)",
     "        browser = getattr(getattr(window, 'native', None), 'browser', None)\n"
     "        return getattr(getattr(browser, 'webview', None), 'CoreWebView2', None)"),

    ("the Windows guard is dropped, so macOS reaches for a WinForms control "
     "that is not there",
     LOGIN,
     "    if sys.platform != 'win32':\n"
     "        return False\n"
     "    control = _webview2_control(window)\n"
     "    if control is None:\n"
     "        return False\n"
     "\n"
     "    def _apply():",
     "    if False:\n"
     "        return False\n"
     "    control = _webview2_control(window)\n"
     "    if control is None:\n"
     "        return False\n"
     "\n"
     "    def _apply():"),

    ("the worker stops switching it on, making the whole thing dead code - "
     "which is what refresh_silently was for three passes",
     LOGIN,
     "            if not password_manager_on:\n"
     "                password_manager_on = enable_password_manager(window)",
     "            if False:\n"
     "                password_manager_on = enable_password_manager(window)"),

    ("logging out stops reaching saved passwords, so on a shared machine the "
     "next user finds the previous one's institution password filled in",
     LOGIN,
     "_LOGOUT_DATA_KINDS = ('Cookies', 'PasswordAutosave', 'GeneralAutofill')",
     "_LOGOUT_DATA_KINDS = ('Cookies',)"),

    ("a logout that could only clear cookies says nothing, so a weaker "
     "logout is un-diagnosable",
     LOGIN,
     "        logger.warning(\"Signed the web view out, but saved passwords could \"\n"
     "                       \"not be cleared from its profile.\")",
     "        pass"),

    # -- the app's own "stay signed in" (2026-09-12) ------------------------
    ("a finished sign-in is never kept, so every launch after Canvas' own day "
     "is a fresh login - the defect the whole retention pass exists to remove",
     LOGIN,
     "                            if job.keep_signed_in:\n"
     "                                try:\n"
     "                                    persist_session_cookies(window)",
     "                            if False:\n"
     "                                try:\n"
     "                                    persist_session_cookies(window)"),

    ("the cookies are kept AFTER the window is destroyed, so there is nothing "
     "left to read them from",
     LOGIN,
     "                            if job.keep_signed_in:\n"
     "                                try:\n"
     "                                    persist_session_cookies(window)\n"
     "                                except Exception as e:          # noqa: BLE001\n"
     "                                    # A sign-in that works must never be\n"
     "                                    # undone by failing to remember it.\n"
     "                                    logger.warning(\n"
     "                                        \"Could not keep this sign-in past \"\n"
     "                                        \"today: %s\", e, exc_info=True)\n"
     "                            _destroy(job)",
     "                            _destroy(job)\n"
     "                            if job.keep_signed_in:\n"
     "                                try:\n"
     "                                    persist_session_cookies(window)\n"
     "                                except Exception as e:          # noqa: BLE001\n"
     "                                    logger.warning(\n"
     "                                        \"Could not keep this sign-in past \"\n"
     "                                        \"today: %s\", e, exc_info=True)"),

    ("the enumeration is filtered to the current page, so the IDENTITY "
     "PROVIDER's cookie - the only one that matters here - is invisible and "
     "the daily login stays",
     LOGIN,
     "        lambda: (control.CoreWebView2.CookieManager.GetCookiesAsync(None)",
     "        lambda: (control.CoreWebView2.CookieManager.GetCookiesAsync('canvas')"),

    ("a float goes back into Expires, which the .NET wrapper refuses inside "
     "the UI-thread closure where nothing surfaces it - the sign-in looks "
     "fine and is silently forgotten",
     LOGIN,
     "        from System import DateTime\n",
     "        import time as _t\n"),

    ("cookies the identity provider deliberately dated are re-dated too, "
     "overriding a choice it made rather than standing in for a missing one",
     LOGIN,
     "            if not cookie.IsSession:\n"
     "                continue",
     "            if False:\n"
     "                continue"),

    ("a cookie list that never arrives is reported as a successful keep, so a "
     "forgotten sign-in looks like a remembered one",
     LOGIN,
     "        logger.warning(\"Timed out reading the sign-in profile's cookies, so \"\n"
     "                       \"this sign-in will not be remembered past today.\")\n"
     "        return 0",
     "        return 1"),

    ("the user's choice is ignored and the sign-in is always kept",
     LOGIN,
     "    def __init__(self, api_url: str, interactive: bool,\n"
     "                 keep_signed_in: bool = True):",
     "    def __init__(self, api_url: str, interactive: bool,\n"
     "                 keep_signed_in: bool = True):\n"
     "        keep_signed_in = True"),

    ("the UI stops passing the choice through, so it cannot be turned off",
     UI,
     "    browser_login.begin_login(api_url, interactive=interactive,\n"
     "                              keep_signed_in=_keep_signed_in_enabled())",
     "    browser_login.begin_login(api_url, interactive=interactive)"),

    ("keeping the sign-in defaults OFF, so the feature does nothing for "
     "anyone who has never opened Settings",
     UI,
     "        return bool(config.get('keep_signed_in', True))",
     "        return bool(config.get('keep_signed_in', False))"),

    ("an unreadable settings file reinstates the daily login, because of a "
     "file permission problem somewhere else entirely",
     UI,
     "    except Exception:                                              # noqa: BLE001\n"
     "        return True\n"
     "\n"
     "\n"
     "def _token_upgrade_enabled() -> bool:",
     "    except Exception:                                              # noqa: BLE001\n"
     "        return False\n"
     "\n"
     "\n"
     "def _token_upgrade_enabled() -> bool:"),

]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in BROWSER_LOGIN_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in BROWSER_LOGIN_MUTANTS:
        body = snapshot[rel]
        anchored = old.replace("\n", _nl_of(body))
        if anchored not in body:
            stale.append(f"{label!r} in {rel}")
        elif body.count(anchored) > 1:
            # The twin-anchor trap: str.replace(..., 1) takes whichever copy is
            # defined FIRST, so the pass would report a result under a label
            # that is a lie. CLAUDE.md records five instances of this.
            stale.append(f"{label!r} in {rel} matches {body.count(anchored)} "
                         f"times - anchor it uniquely")
    if stale:
        print("STALE OR AMBIGUOUS ANCHORS - these mutants could not run "
              "correctly, so any score recorded for them is UNMEASURED:")
        for s in stale:
            print("  " + s)
        return 4

    print(f"baseline: running {len(TESTS)} test file(s)")
    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in BROWSER_LOGIN_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass (another "
                  f"session?). Nothing restored - the file on disk is THEIR "
                  f"edit, not a mutant.")
            return 3
        nl = _nl_of(current)
        old_nl, new_nl = old.replace("\n", nl), new.replace("\n", nl)
        if old_nl not in current:
            print(f"\nSTALE ANCHOR for {label!r} in {rel} - cannot run it")
            return 4

        _write(rel, current.replace(old_nl, new_nl, 1))
        assert _read(rel) != snapshot[rel], f"{label}: mutation changed nothing"
        try:
            rc = subprocess.run([sys.executable, "-m", "pytest", *TEST_TARGET,
                                 "-q", "-x", "--no-header",
                                 "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True,
                                timeout=900).returncode
        except subprocess.TimeoutExpired:
            rc = 1          # a mutant that hangs the suite is one it noticed
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{rel}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(BROWSER_LOGIN_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
